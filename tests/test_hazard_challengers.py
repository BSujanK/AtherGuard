"""Challenger experiments (Task 5): CatBoost learner, paired FA@90 bootstrap, adoption rule, OOF files, harness."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from aetherguard.hazard import catboost_learner as cbl
from aetherguard.hazard import challengers as ch
from aetherguard.hazard import cv
from aetherguard.hazard import data as hd
from aetherguard.hazard import metrics as mt
from aetherguard.hazard import model as hm

from hazard_helpers import COLUMN_MAP, synthetic_development

CFG = hm.hazard_config()
HP = {"depth": 4, "l2_leaf_reg": 3.0, "learning_rate": 0.1}


# ------------------------------------------------------------------------------------------ CatBoost learner

def _band_data(n=1500, seed=0):
    """y rises with x1 overall but is rare in a middle band: an unconstrained fit is non-monotone in x1."""
    rng = np.random.default_rng(seed)
    x1, x2 = rng.uniform(0, 10, n), rng.normal(size=n)
    p = np.where((x1 > 4) & (x1 < 6), 0.02, np.where(x1 >= 6, 0.7, 0.2))
    frame = pd.DataFrame({"x1": x1, "x2": x2, "label": (rng.random(n) < p).astype(int), "split": "train",
                          "kind": "negative", "sample_weight": 1.0})
    frame.loc[rng.random(n) < 0.1, "x1"] = np.nan
    return frame


def _partial_dependence(model, frame, column, n_grid=25):
    grid = np.linspace(0.5, 9.5, n_grid)
    curve = []
    for value in grid:
        probe = frame.assign(**{column: value})
        curve.append(cbl.predict_raw(model, probe, ["x1", "x2"]).mean())
    return np.diff(curve)


def test_catboost_honours_monotone_constraints_and_an_unconstrained_fit_does_not():
    frame = _band_data()
    constrained, n = cbl.fit_catboost(frame, ["x1", "x2"], [1, 0], HP, 1, CFG["training"], num_rounds=80)
    assert n == 80 and _partial_dependence(constrained, frame, "x1").min() >= -1e-12
    free, _ = cbl.fit_catboost(frame, ["x1", "x2"], [0, 0], HP, 1, CFG["training"], num_rounds=80)
    assert _partial_dependence(free, frame, "x1").min() < -1e-3
    decreasing, _ = cbl.fit_catboost(frame.assign(x2=-frame["x1"].fillna(0)), ["x1", "x2"], [0, -1], HP, 1,
                                     CFG["training"], num_rounds=60)
    probe = [cbl.predict_raw(decreasing, frame.assign(x2=v), ["x1", "x2"]).mean() for v in np.linspace(-9, 0, 20)]
    assert np.diff(probe).max() <= 1e-12 and probe[-1] < probe[0]


def test_catboost_is_deterministic_with_the_seed_and_writes_no_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    frame = _band_data()
    runs = [cbl.fit_catboost(frame, ["x1", "x2"], [1, 0], HP, seed, CFG["training"], num_rounds=40)[0]
            for seed in (3, 3, 4)]
    scores = [cbl.predict_raw(m, frame, ["x1", "x2"]) for m in runs]
    assert np.array_equal(scores[0], scores[1]) and not np.array_equal(scores[0], scores[2])
    assert list(tmp_path.iterdir()) == []


def test_catboost_early_stopping_returns_a_tree_count_and_needs_rounds_without_validation():
    frame = _band_data(2000)
    train, valid = frame.iloc[:1400], frame.iloc[1400:]
    settings = {**CFG["training"], "max_rounds": 300, "early_stopping_rounds": 15}
    model, best = cbl.fit_catboost(train, ["x1", "x2"], [1, 0], HP, 5, settings, valid=valid)
    assert 1 <= best <= model.tree_count_ < 300
    assert model.tree_count_ <= best + settings["early_stopping_rounds"] + 1
    refit, rounds = cbl.fit_catboost(train, ["x1", "x2"], [1, 0], HP, 5, settings, num_rounds=best)
    assert rounds == best and refit.tree_count_ == best
    with pytest.raises(ValueError, match="num_rounds"):
        cbl.fit_catboost(train, ["x1", "x2"], [1, 0], HP, 5, settings)


def test_catboost_refuses_leaked_rows_and_missing_columns():
    frame = _band_data(400)
    with pytest.raises(hd.LeakageError):
        cbl.fit_catboost(frame.assign(split="test_2018"), ["x1", "x2"], [1, 0], HP, 1, CFG["training"], num_rounds=5)
    model, _ = cbl.fit_catboost(frame, ["x1", "x2"], [1, 0], HP, 1, CFG["training"], num_rounds=5)
    with pytest.raises(ValueError, match="lacks required model columns"):
        cbl.predict_raw(model, frame[["x1"]], ["x1", "x2"])


def test_catboost_contributions_add_up_to_the_raw_log_odds():
    frame = _band_data(600)
    model, _ = cbl.fit_catboost(frame, ["x1", "x2"], [1, 0], HP, 1, CFG["training"], num_rounds=30)
    shap = cbl.contributions(model, frame.iloc[:50], ["x1", "x2"])
    assert shap.shape == (50, 2)
    p = cbl.predict_raw(model, frame.iloc[:50], ["x1", "x2"])
    bias = np.log(p / (1 - p)) - shap.sum(axis=1)
    assert np.allclose(bias, bias[0], atol=1e-9)


def test_catboost_thread_count_is_capped():
    params = cbl.catboost_params(HP, [1, 0], 1, CFG["training"], thread_count=64)
    assert params["thread_count"] == 6 and params["allow_writing_files"] is False
    assert params["monotone_constraints"] == [1, 0] and params["iterations"] == CFG["training"]["max_rounds"]


# ---------------------------------------------------------------------------------- OOF frames and pairing

def hand_frame(pos, neg, weights=None, matched=(), strata=None):
    """An OOF frame (the saved layout) from positive / universe / matched scores."""
    n_p, n_n, n_m = len(pos), len(neg), len(matched)
    weights = np.ones(n_n) if weights is None else np.asarray(weights, dtype=float)
    strata = ["2010-himalaya"] * n_n if strata is None else list(strata)
    n = n_p + n_n + n_m
    return pd.DataFrame({
        "kind": ["positive"] * n_p + ["universe"] * n_n + ["matched"] * n_m,
        "cell_id": np.arange(n, dtype=np.int64),
        "date": pd.Timestamp("2010-07-01") + pd.to_timedelta(np.arange(n) % 5, unit="D"),
        "region": "himalaya", "year": np.int16(2010), "stratum": [None] * n_p + strata + [None] * n_m,
        "fold": np.int8(0), "label": [1] * n_p + [0] * (n_n + n_m),
        "weight": np.r_[np.ones(n_p), weights, np.ones(n_m)],
        "score": np.r_[pos, neg, matched].astype(float)})


def synthetic_pair(seed=0, n_pos=60, n_neg=600, gains=(2.0, 0.6)):
    """Two scorings of the same rows; the second separates positives from negatives less well."""
    rng = np.random.default_rng(seed)
    strata = np.where(np.arange(n_neg) % 2 == 0, "2010-himalaya", "2010-western_ghats")
    base_p, base_n = rng.normal(size=n_pos), rng.normal(size=n_neg)
    return [hand_frame(base_p + gain, base_n, strata=strata) for gain in gains]


def test_identical_scorings_have_a_zero_difference_and_a_degenerate_interval():
    a, _ = synthetic_pair()
    out = ch.paired_fa_difference(a, a.copy(), n_boot=200, seed=1)
    assert out["point_difference"] == 0.0 and out["mean_difference"] == 0.0
    assert (out["ci_lo"], out["ci_hi"], out["se"]) == (0.0, 0.0, 0.0) and not out["excludes_zero"]
    assert out["share_a_better"] == 0.0 and out["share_tied"] == 1.0


def test_a_clearly_better_scoring_has_a_negative_difference_that_excludes_zero():
    rng = np.random.default_rng(3)
    strata = ["2010-himalaya", "2010-western_ghats"] * 200
    neg = rng.uniform(0, 0.65, 400)
    good = hand_frame(rng.uniform(0.6, 1.0, 50), neg, strata=strata)
    weak = good.assign(score=np.r_[rng.uniform(0.3, 1.0, 50), neg])
    out = ch.paired_fa_difference(good, weak, n_boot=300, seed=2)
    assert out["point_difference"] < -0.2 and out["ci_hi"] < 0 and out["excludes_zero"]
    assert out["se"] > 0 and out["ci_lo"] < out["mean_difference"] < out["ci_hi"]
    reverse = ch.paired_fa_difference(weak, good, n_boot=300, seed=2)
    assert reverse["ci_lo"] > 0 and reverse["excludes_zero"]
    assert reverse["mean_difference"] == pytest.approx(-out["mean_difference"], abs=1e-12)


def test_point_difference_matches_hand_computed_false_alarm_shares():
    pos = np.arange(10, 0, -1, dtype=float)                      # 10 positives, 90% recall -> the 9th highest = 2
    neg_a = np.r_[[5.0, 2.5], np.zeros(8)]                        # 2 of 10 equal-weight negatives >= 2  -> 0.2
    neg_b = np.r_[[5.0, 4.0, 3.0, 2.0], np.zeros(6)]              # 4 of 10                               -> 0.4
    out = ch.paired_fa_difference(hand_frame(pos, neg_a), hand_frame(pos, neg_b), n_boot=50, seed=4)
    assert out["fa_a"] == pytest.approx(0.2) and out["fa_b"] == pytest.approx(0.4)
    assert out["point_difference"] == pytest.approx(-0.2)


def test_pairing_resamples_like_the_existing_bootstrap_with_shared_indices():
    a, b = synthetic_pair(seed=5)
    out = ch.paired_fa_difference(a, b, n_boot=120, seed=9)
    sets = {n: ch.score_set(f) for n, f in (("a", a), ("b", b))}
    neg = a[a["kind"] == "universe"]
    boots = mt.bootstrap_metrics(sets, neg["weight"].to_numpy(), neg["stratum"].to_numpy(), recalls=[0.9],
                                 fa_shares=[], n_boot=120, seed=9)
    diff = boots["a"]["fa_at_recall_0.9"] - boots["b"]["fa_at_recall_0.9"]
    assert out["mean_difference"] == pytest.approx(diff.mean(), abs=1e-15)
    assert out["se"] == pytest.approx(diff.std(ddof=1), abs=1e-15)
    assert (out["ci_lo"], out["ci_hi"]) == pytest.approx(tuple(np.percentile(diff, [2.5, 97.5])), abs=1e-15)


def test_many_pairs_in_one_bootstrap_equal_the_single_pair_calls():
    a, b = synthetic_pair(seed=6)
    c = b.assign(score=b["score"] * 0.9 + np.random.default_rng(1).normal(0, 0.5, len(b)))
    frames = {"a": a, "b": b, "c": c}
    both = ch.paired_fa_differences(frames, [("a", "b"), ("c", "b"), ("a", "c")], n_boot=80, seed=3)
    for x, y in (("a", "b"), ("c", "b"), ("a", "c")):
        single = ch.paired_fa_difference(frames[x], frames[y], n_boot=80, seed=3)
        assert both["differences"][f"{x}-{y}"] == single
    assert set(both["metrics"]) == {"a", "b", "c"}
    assert both["metrics"]["a"]["fa_at_recall_0.9"]["lo"] <= both["metrics"]["a"]["fa_at_recall_0.9"]["value"] <= both["metrics"]["a"]["fa_at_recall_0.9"]["hi"]


def test_pairing_refuses_different_rows_and_nan_scores():
    a, b = synthetic_pair(seed=7)
    with pytest.raises(ValueError, match="same rows"):
        ch.paired_fa_difference(a, b.assign(cell_id=b["cell_id"] + 1), n_boot=10, seed=1)
    with pytest.raises(ValueError, match="same rows"):
        ch.paired_fa_difference(a, b.iloc[::-1].reset_index(drop=True), n_boot=10, seed=1)
    with pytest.raises(ValueError, match="same rows"):
        ch.paired_fa_difference(a, b.iloc[:-1], n_boot=10, seed=1)
    with pytest.raises(ValueError, match="NaN"):
        ch.paired_fa_difference(a, b.assign(score=np.nan), n_boot=10, seed=1)


def test_oof_files_round_trip_and_follow_the_layout_order(tmp_path):
    samples, universe = synthetic_development(n_pos_train=30, n_pos_validation=15, n_per_region=400)
    dev = hd.build_development(samples, universe, COLUMN_MAP)
    layout = cv.make_layout(dev, [[2007, 2008, 2009, 2010, 2011], [2012, 2013, 2014, 2015], [2016, 2017]])
    rng = np.random.default_rng(0)
    oof = cv.Oof(rng.random(len(layout.positives)), rng.random(len(layout.negatives)),
                 rng.random(len(layout.matched)))
    frame = ch.oof_frame(layout, oof)
    assert list(frame["kind"].unique()) == ["positive", "universe", "matched"]
    assert len(frame) == len(layout.positives) + len(layout.negatives) + len(layout.matched)
    path = ch.write_oof(tmp_path / "oof_x.parquet", frame)
    again = ch.read_oof(path)
    pd.testing.assert_frame_equal(frame, again)
    back = ch.oof_scores(again)
    np.testing.assert_array_equal(back.pos, oof.pos)
    np.testing.assert_array_equal(back.neg, oof.neg)
    np.testing.assert_array_equal(back.matched, oof.matched)
    rows = frame[frame["kind"] == "universe"]
    np.testing.assert_array_equal(rows["weight"].to_numpy(), layout.neg_weight)
    np.testing.assert_array_equal(rows["stratum"].to_numpy(), layout.strata)
    assert frame.loc[frame["kind"] == "positive", "fold"].tolist() == layout.pos_fold.tolist()
    with pytest.raises(ValueError, match="NaN"):
        ch.write_oof(tmp_path / "bad.parquet", ch.oof_frame(layout, cv.Oof.empty(layout)))


# ----------------------------------------------------------------------------------------- adoption rule

def test_adoption_requires_a_gain_larger_than_the_paired_se():
    assert ch.adoption(incumbent_fa=0.2000, challenger_fa=0.1700, se=0.0200)["adopt"]
    assert not ch.adoption(0.2000, 0.1850, 0.0200)["adopt"]            # gain 0.015 < se 0.02
    assert not ch.adoption(0.2000, 0.1800, 0.0200)["adopt"]            # gain of exactly one SE is not "more than"
    assert not ch.adoption(0.2000, 0.2100, 0.0001)["adopt"]            # worse
    decision = ch.adoption(0.2, 0.17, 0.02)
    assert decision["gain"] == pytest.approx(0.03) and decision["se"] == 0.02
    assert decision["gain_over_se"] == pytest.approx(1.5)


def test_choose_adoption_picks_the_lowest_fa_among_those_that_qualify():
    rows = [{"name": "a", "fa": 0.19, "se": 0.01}, {"name": "b", "fa": 0.17, "se": 0.01},
            {"name": "c", "fa": 0.16, "se": 0.05}, {"name": "d", "fa": 0.18, "se": 0.005}]
    assert ch.choose_adoption(0.20, rows)["name"] == "b"              # c's gain 0.04 < 0.05, a's gain 0.01 = se
    assert ch.choose_adoption(0.20, rows[:1]) is None and ch.choose_adoption(0.20, []) is None


# ----------------------------------------------------------------------------------------------- blending

def test_rank_blend_averages_the_within_fold_ranks_of_both_scorings():
    zero = hand_frame([4.0, 1.0], [3.0, 2.0], matched=[2.5])
    one = hand_frame([40.0, 10.0], [30.0, 20.0], matched=[25.0]).assign(fold=np.int8(1))
    a = pd.concat([zero, one], ignore_index=True).assign(cell_id=np.arange(10))
    reverse = a.assign(score=-a["score"])
    same = ch.rank_blend(a, a)
    in_zero = same[same["fold"] == 0].set_index("cell_id")["score"]
    # the fold's reference is its positives + universe scores {4, 3, 2, 1}: mid-rank / n
    assert in_zero.loc[0] == pytest.approx(0.875) and in_zero.loc[2] == pytest.approx(0.625)
    assert in_zero.loc[3] == pytest.approx(0.375) and in_zero.loc[1] == pytest.approx(0.125)
    assert in_zero.loc[4] == pytest.approx(0.5)                       # matched 2.5 sits between 2 and 3
    in_one = same[same["fold"] == 1].set_index("cell_id")["score"]   # folds are ranked separately
    assert in_one.to_numpy() == pytest.approx(in_zero.to_numpy())
    opposed = ch.rank_blend(a, reverse)
    assert opposed["score"].to_numpy() == pytest.approx(0.5)          # perfectly opposed rankings average to 0.5
    assert (same["cell_id"] == a["cell_id"]).all() and (same["fold"] == a["fold"]).all()
    assert same["kind"].tolist() == a["kind"].tolist()


# ---------------------------------------------------------------------------- harness on a synthetic world

import copy  # noqa: E402
import json  # noqa: E402

from aetherguard.config import PROJECT_ROOT  # noqa: E402
from aetherguard.hazard import challengers_report as chr_  # noqa: E402

FOLDS = [[2007, 2008, 2009, 2010, 2011], [2012, 2013, 2014, 2015], [2016, 2017]]
V3 = hm.hazard_config(PROJECT_ROOT / "configs" / "hazard_v3.yaml")
CB_HP = {"depth": 3, "l2_leaf_reg": 3.0, "learning_rate": 0.2}
LGB_HP = {"num_leaves": 4, "min_data_in_leaf": 10, "feature_fraction": 0.9, "lambda_l2": 1.0, "learning_rate": 0.2}


def tiny_cfg():
    cfg = copy.deepcopy(hm.hazard_config())
    cfg["training"].update(max_rounds=30, early_stopping_rounds=5, universe_negatives=600)
    cfg["cv"]["folds"] = FOLDS
    cfg["bootstrap"].update(n=40)
    return cfg


@pytest.fixture(scope="module")
def world():
    samples, universe = synthetic_development(n_pos_train=70, n_pos_validation=30, n_per_region=1500)
    dev = hd.build_development(samples, universe, COLUMN_MAP)
    cfg = tiny_cfg()
    cols = hd.model_columns(cfg["groups"], COLUMN_MAP)
    return dev, cv.make_layout(dev, FOLDS), cfg, cols, hm.configured_constraints(cols, cfg)


def test_catboost_cv_gives_a_complete_deterministic_oof_with_one_tree_count(world):
    dev, layout, cfg, cols, constraints = world
    first = ch.run_cv_catboost(dev, layout, cols, constraints, CB_HP, "matched_only", cfg, "cb", thread_count=2)
    again = ch.run_cv_catboost(dev, layout, cols, constraints, CB_HP, "matched_only", cfg, "cb", thread_count=2)
    assert first.oof.complete() and len(first.fold_best_iterations) == len(FOLDS)
    assert first.n_trees == int(round(np.median(first.fold_best_iterations)))
    np.testing.assert_array_equal(first.oof.pos, again.oof.pos)
    np.testing.assert_array_equal(first.oof.neg, again.oof.neg)
    assert 0.0 < first.pooled[ch.HEADLINE] < 1.0 and first.pooled["pr_auc"] > 0
    # the same rows, folds and metric code as the LightGBM harness: a better-than-chance model on separable data
    lgb = cv.run_cv(dev, layout, cols, constraints, LGB_HP, "matched_only", cfg, "lgb")
    assert first.pooled[ch.HEADLINE] < 0.6 and lgb.pooled[ch.HEADLINE] < 0.6
    assert set(first.pooled) == set(lgb.pooled)


def test_reproduce_selected_accepts_matching_results_and_raises_on_a_mismatch(world, tmp_path):
    dev, layout, cfg, cols, constraints = world
    result = cv.run_cv(dev, layout, cols, constraints, LGB_HP, "matched_only", cfg, "x")
    selected = {"name": "full", "columns": cols, "hp": LGB_HP, "neg_mix": "matched_only", "n_trees": result.n_trees,
                "pooled": result.pooled}
    (tmp_path / "cv_results.json").write_text(json.dumps({"selected": selected}), encoding="utf-8")
    again, record = ch.reproduce_selected(dev, layout, cfg, tmp_path, "inc")
    assert record["abs_difference"] == 0.0 and record["n_trees"] == record["reported_n_trees"] == result.n_trees
    np.testing.assert_array_equal(again.oof.pos, result.oof.pos)
    selected["pooled"] = {**result.pooled, ch.HEADLINE: result.pooled[ch.HEADLINE] + 0.01}
    (tmp_path / "cv_results.json").write_text(json.dumps({"selected": selected}), encoding="utf-8")
    with pytest.raises(ch.ReproductionError, match="reported"):
        ch.reproduce_selected(dev, layout, cfg, tmp_path, "inc")


def test_catboost_grid_names_and_hyper_parameters_come_from_the_configuration():
    grid = ch.catboost_candidates(V3)
    assert len(grid) == 4
    assert sorted((g["hp"]["depth"], g["hp"]["l2_leaf_reg"]) for g in grid) == [(4, 3), (4, 10), (6, 3), (6, 10)]
    assert [g["name"] for g in grid] == ["cb_d4_l2_3", "cb_d4_l2_10", "cb_d6_l2_3", "cb_d6_l2_10"]
    assert all(g["hp"]["learning_rate"] == 0.1 for g in grid)
    fallback = copy.deepcopy(V3)
    del fallback["challengers"]["catboost"]["learning_rate"]
    assert ch.catboost_candidates(fallback)[0]["hp"]["learning_rate"] == fallback["training"]["learning_rate"]
    names = ch.candidate_names(V3)
    assert names[:2] == [ch.INCUMBENT, ch.FROZEN_V2] and names[-1] == ch.BLEND and len(names) == len(set(names))
    assert V3["challengers"]["catboost"]["thread_count"] <= 6


def test_the_challenger_lightgbm_candidates_resolve_to_the_documented_column_sets():
    column_map = {**{f"irain_{n}": "irain" for n in ("acc_1", "acc3_vs_clim", "acc7_vs_clim", "acc30_vs_clim")},
                  "stat_slope_mean": "stat", **{c: "iclim" for c in ("iclim_pct_1", "iclim_acc1_over_map")}}
    specs = {s["name"]: s for s in ch.lightgbm_candidates(V3)}
    add = cv.resolve_candidate(specs["lgb_iclim_add"], None, V3, column_map)
    swap = cv.resolve_candidate(specs["lgb_iclim_swap"], None, V3, column_map)
    assert set(add["columns"]) == set(column_map)
    assert set(swap["columns"]) == set(column_map) - {"irain_acc3_vs_clim", "irain_acc7_vs_clim", "irain_acc30_vs_clim"}
    assert all(c == 1 for col, c in zip(add["columns"], add["constraints"]) if col.startswith(("iclim_", "irain_")))


def test_best_of_ranks_by_fa_then_log_loss_and_ignores_other_families():
    rng = np.random.default_rng(0)
    strata = ["2010-himalaya", "2010-western_ghats"] * 150
    neg = rng.uniform(0, 1, 300)
    good = hand_frame(rng.uniform(0.5, 1.0, 40), neg, strata=strata, matched=rng.uniform(0, 1, 20))
    worse = good.assign(score=np.r_[rng.uniform(0.3, 1.0, 40), neg, rng.uniform(0, 1, 20)])
    frames = {"a": worse, "b": good, "c": good, "v2": good}
    metas = {"a": {"family": "lightgbm"}, "b": {"family": "lightgbm"}, "c": {"family": "catboost"},
             "v2": {"family": "frozen_v2"}}
    assert ch.best_of(frames, metas, "lightgbm") == "b" and ch.best_of(frames, metas, "catboost") == "c"
    assert ch.best_of(frames, metas, "blend") is None


def test_report_pairs_every_challenger_with_the_incumbent_and_applies_the_rule(tmp_path, monkeypatch):
    monkeypatch.setenv("AETHERGUARD_DATA_DIR", str(tmp_path / "data"))
    a, weak = synthetic_pair(seed=11, n_pos=80, n_neg=800, gains=(2.0, 0.4))
    strong = a.assign(score=a["score"] + np.where(a["kind"] == "positive", 1.0, 0.0))
    frames = {ch.INCUMBENT: a, ch.FROZEN_V2: weak, "better": strong, "same": a.copy()}

    def meta(name, family, **extra):
        return {"name": name, "family": family, "description": name, "n_inputs": 3, "hp": {}, "neg_mix": "x",
                "n_trees": 5, "adoptable": True, "columns": ["a"], "probabilistic": False, **extra}
    metas = {ch.INCUMBENT: meta(ch.INCUMBENT, "lightgbm"), ch.FROZEN_V2: meta(ch.FROZEN_V2, "frozen_v2", adoptable=False),
             "better": meta("better", "lightgbm"), "same": meta("same", "catboost")}
    cfg = tiny_cfg()
    cfg["challengers"] = {"report_stem": "stem", "oof_dir": "c"}
    repro = {ch.INCUMBENT: {"name": "n", "reported_fa_at_90": 0.1, "recomputed_fa_at_90": 0.1, "abs_difference": 0.0,
                            "n_trees": 5, "reported_n_trees": 5}}
    payload = chr_.write_report(cfg, Path("c.yaml"), frames, metas, repro,
                                {"positives": 80, "universe": 800, "matched": 0}, 1.0, report_dir=tmp_path)
    by_name = {c["name"]: c for c in payload["candidates"]}
    assert by_name["same"]["paired_vs_v3"]["point_difference"] == 0.0 and not by_name["same"]["paired_vs_v3"]["excludes_zero"]
    assert by_name["better"]["paired_vs_v3"]["point_difference"] < 0
    assert payload["v3_vs_v2"]["better_than_v2"] == (payload["v3_vs_v2"]["ci_hi"] < 0)
    assert payload["multiple_comparisons"]["n_challengers"] == 2
    decisions = {e["name"]: e for e in payload["adoption"]["evaluated"]}
    assert not decisions["same"]["adopt"]
    assert decisions["better"]["adopt"] == (decisions["better"]["gain"] > decisions["better"]["se"])
    written = json.loads((tmp_path / "stem.json").read_text())                      # strict JSON
    assert written["incumbent"] == ch.INCUMBENT and (tmp_path / "stem.md").read_text().startswith("# Challenger")
    assert "negative favours the candidate" in (tmp_path / "stem.md").read_text()


def test_unknown_candidate_names_are_refused(tmp_path):
    with pytest.raises(ValueError, match="unknown candidates"):
        ch.run(PROJECT_ROOT / "configs" / "hazard_v3.yaml", only={"nope"}, say=lambda m: None)
