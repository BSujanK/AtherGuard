import copy

import numpy as np
import pandas as pd
import pytest

from aetherguard.hazard import baselines as bl
from aetherguard.hazard import cv
from aetherguard.hazard import data as hd
from aetherguard.hazard import metrics as mt
from aetherguard.hazard import model as hm

from hazard_helpers import COLUMN_MAP, synthetic_development

BASE = hm.hazard_config()
FOLDS = [[2007, 2008], [2009, 2010], [2011, 2012], [2013, 2014], [2015], [2016], [2017]]
HP = {"num_leaves": 4, "min_data_in_leaf": 10, "feature_fraction": 0.9, "lambda_l2": 1.0, "learning_rate": 0.2}


def tiny_cfg():
    cfg = copy.deepcopy(BASE)
    cfg["training"].update(max_rounds=40, early_stopping_rounds=5, universe_negatives=600)
    cfg["cv"]["folds"] = FOLDS
    cfg["grid"] = {"num_leaves": [4, 8], "min_data_in_leaf": [10], "feature_fraction": [0.9], "lambda_l2": [0, 5]}
    cfg["bootstrap"].update(n=60)
    return cfg


@pytest.fixture(scope="module")
def world():
    samples, universe = synthetic_development(n_pos_train=110, n_pos_validation=50, n_per_region=2500)
    dev = hd.build_development(samples, universe, COLUMN_MAP)
    return dev, cv.make_layout(dev, FOLDS)


@pytest.fixture(scope="module")
def columns():
    cols = hd.model_columns(BASE["groups"], COLUMN_MAP)
    return cols, hm.configured_constraints(cols, BASE)


@pytest.fixture(scope="module")
def result(world, columns):
    dev, layout = world
    return cv.run_cv(dev, layout, columns[0], columns[1], HP, "matched_only", tiny_cfg(), "t")


# --------------------------------------------------------------------------------------------- layout

def test_layout_assigns_every_row_to_its_year_fold(world):
    dev, layout = world
    fold_of = {y: k for k, block in enumerate(FOLDS) for y in block}
    for frame, fold in ((layout.positives, layout.pos_fold), (layout.negatives, layout.neg_fold),
                        (layout.matched, layout.matched_fold)):
        assert (frame["year"].map(fold_of).to_numpy() == fold).all()
    assert len(layout.positives) == 160 and len(layout.matched) == 800
    assert set(layout.strata) <= {f"{y}-{r}" for y in range(2007, 2018) for r in ("himalaya", "western_ghats")}
    spread = pd.Series(layout.neg_weight).groupby(layout.strata).nunique()
    assert (spread == 1).all()


def test_layout_rejects_overlapping_and_missing_year_folds(world):
    dev, _ = world
    with pytest.raises(ValueError, match="more than one fold"):
        cv.make_layout(dev, [[2007, 2008], [2008, 2009]])
    with pytest.raises(ValueError, match="not assigned"):
        cv.make_layout(dev, [[2007, 2008]])


# ------------------------------------------------------------------------------------------ CV fitting

def test_every_fold_is_fitted_without_its_own_years_and_scored_out_of_fold(world, columns, monkeypatch):
    dev, layout = world
    seen = []
    real = hm.fit_booster

    def spy(train, cols, cons, hp, seed, settings, **kwargs):
        seen.append((train["year"].unique().tolist(), kwargs["valid"]["year"].unique().tolist()))
        assert set(train["split"]) <= {"train", "validation"} and train["in_domain"].all()
        return real(train, cols, cons, hp, seed, settings, **kwargs)

    monkeypatch.setattr(hm, "fit_booster", spy)
    out = cv.run_cv(dev, layout, columns[0], columns[1], HP, "matched_only", tiny_cfg(), "t")
    assert len(seen) == 7
    for years, (train_years, valid_years) in zip(FOLDS, seen):
        assert set(valid_years) <= set(years) and not set(train_years) & set(years)
    assert out.oof.complete()


def test_oof_scores_and_pooled_metrics(result, world):
    _, layout = world
    assert result.oof.complete() and len(result.fold_best_iterations) == 7
    assert result.n_trees == int(round(np.median(result.fold_best_iterations)))
    pooled = result.pooled
    assert 0.0 < pooled["fa_at_recall_0.9"] < 1.0 and pooled["logloss"] > 0
    assert pooled["fa_at_recall_0.9"] == pytest.approx(result.oof.score_set(layout).point([0.9], [])["fa_at_recall_0.9"])
    assert len(result.per_fold) == 7 and sum(f["n_positives"] for f in result.per_fold) == 160
    assert all(f["best_iteration"] >= 1 for f in result.per_fold)
    assert result.summary()["n_inputs"] == len(result.columns)


def test_signal_is_learned_out_of_fold(result, world):
    _, layout = world
    random_fa = cv.pooled_metrics(layout, cv.Oof(np.random.default_rng(0).random(len(layout.positives)),
                                                 np.random.default_rng(1).random(len(layout.negatives)),
                                                 np.random.default_rng(2).random(len(layout.matched))))
    assert result.pooled["fa_at_recall_0.9"] < random_fa["fa_at_recall_0.9"] - 0.2


def test_cv_is_deterministic(world, columns, result):
    dev, layout = world
    again = cv.run_cv(dev, layout, columns[0], columns[1], HP, "matched_only", tiny_cfg(), "t")
    np.testing.assert_array_equal(result.oof.pos, again.oof.pos)
    np.testing.assert_array_equal(result.oof.neg, again.oof.neg)
    assert result.fold_best_iterations == again.fold_best_iterations


def test_matched_plus_universe_draws_from_training_years_only(world, columns, monkeypatch):
    dev, layout = world
    real = hd.training_frame
    drawn_years = []

    def spy(samples, universe, neg_mix, n_universe, seed, regions=None):
        frame = real(samples, universe, neg_mix, n_universe, seed, regions)
        if neg_mix == "matched_plus_universe":
            drawn_years.append(set(frame.loc[frame["kind"] == "universe", "year"]))
        return frame

    monkeypatch.setattr(hd, "training_frame", spy)
    cv.run_cv(dev, layout, columns[0], columns[1], HP, "matched_plus_universe", tiny_cfg(), "t")
    assert len(drawn_years) == 7
    for years, drawn in zip(FOLDS, drawn_years):
        assert drawn and not drawn & set(years)


# -------------------------------------------------------------------------------------------- grid

def test_grid_candidates_and_ranking_rule():
    grid = cv.grid_candidates(BASE["grid"])
    assert len(grid) == 16 and {tuple(g) for g in grid} == {("num_leaves", "min_data_in_leaf", "feature_fraction",
                                                             "lambda_l2")}
    assert BASE["training"]["learning_rate"] == 0.05 and BASE["training"]["max_rounds"] == 1000

    def fake(fa, ll):
        return cv.CVResult("x", [], [], {}, "m", 1, [1], None, {"fa_at_recall_0.9": fa, "logloss": ll}, [], 0.0)

    assert cv.ranking_key(fake(0.1, 0.5), 3) < cv.ranking_key(fake(0.2, 0.1), 0)
    assert cv.ranking_key(fake(0.1, 0.4), 5) < cv.ranking_key(fake(0.1, 0.5), 0)
    assert cv.ranking_key(fake(0.1, 0.4), 1) < cv.ranking_key(fake(0.1, 0.4), 2)


def test_run_grid_cross_validates_every_point_plus_the_extra_neg_mix(world, columns):
    dev, layout = world
    cfg = tiny_cfg()
    results, selected = cv.run_grid(dev, layout, columns[0], columns[1], cfg)
    assert len(results) == 4 + 1
    assert [r.neg_mix for r in results[:4]] == ["matched_only"] * 4 and results[4].neg_mix == "matched_plus_universe"
    assert all(r.hp["learning_rate"] == 0.05 for r in results)
    assert selected is min(results, key=lambda r: cv.ranking_key(r, results.index(r)))
    best_grid = min(results[:4], key=lambda r: cv.ranking_key(r, results.index(r)))
    assert results[4].hp == best_grid.hp


# ----------------------------------------------------------------------------------- group selection

def _entry(name, n, fa, se, order=0):
    return {"name": name, "n_inputs": n, "fa": fa, "se": se, "order": order}


def test_simpler_candidate_is_kept_unless_the_complex_one_is_better_by_more_than_its_se():
    entries = [_entry("full", 43, 0.20, 0.02), _entry("small", 30, 0.205, 0.02)]
    assert cv.select_simplest(entries)["name"] == "small"
    entries = [_entry("full", 43, 0.20, 0.02), _entry("small", 30, 0.23, 0.02)]
    assert cv.select_simplest(entries)["name"] == "full"
    entries = [_entry("full", 43, 0.20, 0.02), _entry("small", 30, 0.22, 0.02)]       # exactly one SE: not enough
    assert cv.select_simplest(entries)["name"] == "small"
    chain = [_entry("a", 10, 0.30, 0.02), _entry("b", 20, 0.25, 0.02), _entry("c", 30, 0.24, 0.02)]
    assert cv.select_simplest(chain)["name"] == "b"
    tie = [_entry("x", 10, 0.2, 0.1, 1), _entry("y", 10, 0.2, 0.1, 0)]
    assert cv.select_simplest(tie)["name"] == "y"


def test_candidates_resolve_from_config_and_stage_two_extends_the_winner():
    cfg = copy.deepcopy(BASE)
    column_map = {**COLUMN_MAP, "integ_trw_rain_1": "integ", "corr_q50_1": "corr"}
    stage1 = {s["name"]: cv.resolve_candidate(s, None, cfg, column_map) for s in cfg["group_stages"][0]["candidates"]}
    assert set(stage1) == {"full", "stat_no_elevation", "drop_src", "drop_wet"}
    assert "stat_elev_mean" in stage1["full"]["columns"] and "stat_elev_mean" not in stage1["stat_no_elevation"]["columns"]
    assert "stat_slope_mean" in stage1["stat_no_elevation"]["columns"]
    assert not any(c.startswith("src_") for c in stage1["drop_src"]["columns"])
    assert not any(c.startswith("wet_") for c in stage1["drop_wet"]["columns"])
    resolved = [cv.resolve_candidate(s, stage1["stat_no_elevation"], cfg, column_map)
                for s in cfg["group_stages"][1]["candidates"]]
    assert [r["name"] for r in resolved] == ["stat_no_elevation+integ", "stat_no_elevation+corr",
                                              "stat_no_elevation+integ+corr"]
    assert "integ_trw_rain_1" in resolved[0]["columns"] and "corr_q50_1" not in resolved[0]["columns"]
    assert {"integ_trw_rain_1", "corr_q50_1"} <= set(resolved[2]["columns"])
    assert "stat_elev_mean" not in resolved[2]["columns"]
    with pytest.raises(ValueError, match="extends the previous"):
        cv.resolve_candidate(cfg["group_stages"][1]["candidates"][0], None, cfg, column_map)


def test_all_groups_lists_every_group_a_candidate_may_use():
    assert cv.all_groups(BASE) == ["rain", "src", "wet", "stat", "integ", "corr"]


def test_station_presence_columns_are_configured_as_non_inputs():
    assert {"integ_n_st_100km", "integ_dist_nearest_km", "integ_n_flagged_100km_7d"} == set(BASE["meta_columns"])
    assert BASE["presence_column"] in BASE["meta_columns"]


def test_select_groups_runs_two_stages_and_reports_se_and_ci(world, columns):
    dev, layout = world
    cfg = tiny_cfg()
    cfg["group_stages"] = [{"candidates": [{"name": "full", "groups": ["rain", "src", "wet", "stat"]},
                                           {"name": "drop_src", "groups": ["rain", "wet", "stat"]}]},
                           {"candidates": [{"name": "+again", "add_groups": ["stat"]}]}]
    winner, table, every = cv.select_groups(dev, layout, cfg, HP, "matched_only", COLUMN_MAP)
    assert {r["name"] for r in table if r["stage"] == 0} == {"full", "drop_src"}
    assert sum(r["selected_in_stage"] for r in table if r["stage"] == 0) == 1
    assert winner.name in every and sum(r["selected_in_stage"] for r in table if r["stage"] == 1) == 1
    assert all(r["se"] > 0 for r in table)
    stage1_names = [r["name"] for r in table if r["stage"] == 1]
    assert stage1_names[0] in {"full", "drop_src"} and len(stage1_names) == 2     # incumbent + the extension


def test_select_groups_reuses_known_results(world, columns, result, monkeypatch):
    dev, layout = world
    cfg = tiny_cfg()
    cfg["group_stages"] = [{"candidates": [{"name": "full", "groups": ["rain", "src", "wet", "stat"]}]}]
    calls = []
    monkeypatch.setattr(cv, "run_cv", lambda *a, **k: calls.append(a) or result)
    winner, table, _ = cv.select_groups(dev, layout, cfg, HP, "matched_only", COLUMN_MAP, known={"full": result})
    assert winner is result and not calls and len(table) == 1


# ------------------------------------------------------------------------ calibration and thresholds

def test_calibrator_from_pooled_oof_is_monotone_and_hits_the_base_rate(result, world):
    _, layout = world
    calibrator = cv.fit_calibrator(layout, result.oof)
    risk = np.r_[calibrator.predict(result.oof.pos), calibrator.predict(result.oof.neg)]
    weights = np.r_[np.ones(len(result.oof.pos)), layout.neg_weight]
    assert np.average(risk, weights=weights) == pytest.approx(len(result.oof.pos) / layout.neg_weight.sum(), rel=0.02)
    order = np.argsort(result.oof.neg)
    assert (np.diff(calibrator.predict(result.oof.neg[order])) >= 0).all()


def test_crossfit_calibration_uses_other_folds_only(result, world, monkeypatch):
    _, layout = world
    fitted = []
    real = cv.cal.MonotoneCalibrator.fit

    def spy(scores, labels, weights):
        fitted.append(len(scores))
        return real(scores, labels, weights)

    monkeypatch.setattr(cv.cal.MonotoneCalibrator, "fit", staticmethod(spy))
    risk_pos, risk_neg = cv.crossfit_risk(layout, result.oof)
    assert not np.isnan(risk_pos).any() and not np.isnan(risk_neg).any()
    total = len(result.oof.pos) + len(result.oof.neg)
    assert len(fitted) == 7 and all(n < total for n in fitted)


def test_calibration_summary_has_per_year_rows_and_ece(result, world):
    _, layout = world
    calibrator = cv.fit_calibrator(layout, result.oof)
    summary = cv.calibration_summary(layout, result.oof, calibrator, tiny_cfg())
    assert set(summary["crossfit"]["per_year"]) == set(range(2007, 2018))
    assert summary["insample"]["ece_deciles"] <= summary["crossfit"]["ece_deciles"] + 1e-12
    assert summary["insample"]["mean_predicted"] == pytest.approx(summary["base_rate"], rel=0.05)
    year = summary["crossfit"]["per_year"][2012]
    assert year["observed"] == pytest.approx(year["positives"] / year["population"])


def test_alert_levels_are_ordered_and_recall_first_is_more_conservative(result, world):
    _, layout = world
    calibrator = cv.fit_calibrator(layout, result.oof)
    out = cv.operating_thresholds(layout, result.oof, calibrator, tiny_cfg())
    assert out["watch"] == out["recall_first"]
    assert out["recall_first"]["raw"] <= out["plain_recall_90"]["raw"]
    assert out["recall_first"]["oof_recall"] >= out["plain_recall_90"]["oof_recall"] >= 0.9
    assert out["recall_first"]["oof_fa_share"] >= out["plain_recall_90"]["oof_fa_share"]
    assert out["watch"]["raw"] < out["warning"]["raw"] < out["emergency"]["raw"]
    assert out["warning"]["oof_recall"] >= 0.75 and out["emergency"]["oof_recall"] >= 0.5
    assert out["warning"]["oof_recall"] < 0.8 and out["emergency"]["oof_recall"] < 0.55
    assert out["watch"]["risk"] <= out["warning"]["risk"] <= out["emergency"]["risk"]
    assert cv.operating_thresholds(layout, result.oof, None, tiny_cfg())["watch"]["risk"] is None


# ------------------------------------------------------------------------------------------ baselines

def test_baselines_are_refitted_inside_every_fold_on_that_folds_training_rows(world, monkeypatch):
    dev, layout = world
    seen = []
    real = bl.fit_baselines

    def spy(samples, universe):
        seen.append((set(samples["year"]), set(universe["year"])))
        return real(samples, universe)

    monkeypatch.setattr(bl, "fit_baselines", spy)
    oofs = cv.run_cv_baselines(dev, layout, tiny_cfg())
    assert set(oofs) == {"intensity_duration", "lhasa_style", "logistic"}
    assert len(seen) == 7
    for years, (sample_years, universe_years) in zip(FOLDS, seen):
        assert not sample_years & set(years) and not universe_years & set(years)
    for oof in oofs.values():
        assert not np.isnan(oof.pos).any() and not np.isnan(oof.neg).any() and not np.isnan(oof.matched).any()


def test_baseline_oofs_share_the_layout_and_are_comparable(world, result):
    dev, layout = world
    oofs = cv.run_cv_baselines(dev, layout, tiny_cfg())
    for oof in oofs.values():
        assert len(oof.pos) == len(result.oof.pos) and len(oof.neg) == len(result.oof.neg)
        assert 0.0 < cv.pooled_metrics(layout, oof)["fa_at_recall_0.9"] <= 1.0


def test_bootstrap_of_oofs_is_paired_and_deterministic(result, world):
    _, layout = world
    cfg = tiny_cfg()
    a = cv.bootstrap_oofs(layout, {"m": result.oof}, cfg)
    b = cv.bootstrap_oofs(layout, {"m": result.oof}, cfg)
    np.testing.assert_array_equal(a["m"]["fa_at_recall_0.9"], b["m"]["fa_at_recall_0.9"])
    assert mt.bootstrap_se(a["m"]["fa_at_recall_0.9"]) > 0


# ------------------------------------------------------------------------------------ station presence

def test_presence_comparison_splits_rows_by_station_presence(world, result):
    dev, layout = world
    rng = np.random.default_rng(0)
    layout_p = cv.Layout(layout.folds, layout.positives.assign(st=rng.integers(0, 3, len(layout.positives))),
                         layout.negatives.assign(st=rng.integers(0, 3, len(layout.negatives))), layout.matched,
                         layout.pos_fold, layout.neg_fold, layout.matched_fold, layout.strata)
    out = cv.presence_comparison(layout_p, {"a": result.oof, "b": result.oof}, "st", tiny_cfg())
    with_s, without = out["with_station"], out["without_station"]
    assert with_s["n_positives"] + without["n_positives"] == len(layout.positives)
    assert with_s["universe_share"] + without["universe_share"] == pytest.approx(1.0)
    assert set(with_s["metrics"]) == {"a", "b"}
    key = "fa_at_recall_0.9"
    assert with_s["metrics"]["a"][key]["value"] == with_s["metrics"]["b"][key]["value"]
    assert with_s["metrics"]["a"][key]["lo"] <= with_s["metrics"]["a"][key]["hi"]


def test_resolve_all_candidates_extends_each_stage_winner():
    column_map = {**COLUMN_MAP, "integ_trw_rain_1": "integ", "corr_q50_1": "corr"}
    specs = cv.resolve_all_candidates(BASE, column_map, ["drop_src", "drop_src"])
    assert [s["name"] for s in specs] == ["full", "stat_no_elevation", "drop_src", "drop_wet", "drop_src+integ",
                                          "drop_src+corr", "drop_src+integ+corr"]
    by_name = {s["name"]: s for s in specs}
    assert not any(c.startswith("src_") for c in by_name["drop_src+integ"]["columns"])
    assert "integ_trw_rain_1" in by_name["drop_src+integ"]["columns"]
    with pytest.raises(ValueError, match="not a candidate"):
        cv.resolve_all_candidates(BASE, column_map, ["nonsense", "drop_src"])
