"""v3.1 challenger study (spec section 15): candidates, training-only label removal, alert-level statistics, the
pre-declared selection and the final refit."""
import copy
import dataclasses

import numpy as np
import pytest

from aetherguard.config import PROJECT_ROOT, load_config_file
from aetherguard.hazard import challengers as ch
from aetherguard.hazard import cv
from aetherguard.hazard import data as hd
from aetherguard.hazard import model as hm
from aetherguard.hazard import v31_challenger as vc

from hazard_helpers import COLUMN_MAP, synthetic_development

FOLDS = [[2007, 2008, 2009], [2010, 2011, 2012], [2013, 2014, 2015], [2016, 2017]]
COLUMNS = ["stat_relief", "stat_slope_mean", "stat_elev_mean", "stat_aspect_sin", "rain_acc_1", "rain_acc_3", "rain_acc_7",
           "rain_days_since_10mm"]
SELECTED = {"hp": {"num_leaves": 4, "min_data_in_leaf": 10, "feature_fraction": 0.9, "lambda_l2": 1.0, "learning_rate": 0.2},
            "neg_mix": "matched_plus_universe", "columns": COLUMNS}


def tiny_study() -> dict:
    study = load_config_file(PROJECT_ROOT / "configs" / "hazard_v31_challenger.yaml")
    base = copy.deepcopy(hm.hazard_config(PROJECT_ROOT / study["base_config"]))
    base["training"].update(max_rounds=40, early_stopping_rounds=5, universe_negatives=600)
    base["cv"]["folds"] = FOLDS
    base["bootstrap"].update(n=40)
    base["ensemble"].update(members=3)
    study["base"] = base
    study["low_rain_column"] = "rain_acc_3"
    return study


@pytest.fixture(scope="module")
def study():
    return tiny_study()


@pytest.fixture(scope="module")
def world():
    samples, universe = synthetic_development(n_pos_train=110, n_pos_validation=50, n_per_region=2500)
    dev = hd.build_development(samples, universe, COLUMN_MAP)
    return dev, cv.make_layout(dev, FOLDS)


# ------------------------------------------------------------------------------------------ candidates

def test_c1_adds_only_the_elevation_constraint_to_the_v3_vector(study):
    candidates = vc.make_candidates(study, COLUMNS)
    c0 = dict(zip(COLUMNS, candidates["C0"].constraints))
    c1 = dict(zip(COLUMNS, candidates["C1"].constraints))
    assert c0 == dict(zip(COLUMNS, hm.configured_constraints(COLUMNS, study["base"]))) and c0["stat_elev_mean"] == 0
    assert c1["stat_elev_mean"] == 1 and {k: v for k, v in c1.items() if k != "stat_elev_mean"} == \
        {k: v for k, v in c0.items() if k != "stat_elev_mean"}
    assert c0["stat_slope_mean"] == 1 and c0["rain_acc_3"] == 1 and c0["rain_days_since_10mm"] == -1


def test_c2_and_c3_drop_the_elevation_input_and_only_c3_drops_positives(study):
    candidates = vc.make_candidates(study, COLUMNS)
    assert candidates["C0"].columns == COLUMNS and candidates["C1"].columns == COLUMNS
    for name in ("C2", "C3"):
        assert candidates[name].columns == [c for c in COLUMNS if c != "stat_elev_mean"]
        assert len(candidates[name].constraints) == len(COLUMNS) - 1
    assert [candidates[n].drop_implausible for n in ("C0", "C1", "C2", "C3")] == [False, False, False, True]


def test_candidate_definitions_are_checked(study):
    with pytest.raises(ValueError, match="already constrained"):
        vc.candidate_constraints(COLUMNS, {"increasing_extra": ["stat_slope_mean"]}, study["base"])
    with pytest.raises(ValueError, match="not an input"):
        vc.candidate_constraints(COLUMNS, {"increasing_extra": ["stat_twi_proxy"]}, study["base"])
    broken = copy.deepcopy(study)
    broken["candidates"]["C2"]["exclude"] = ["not_a_column"]
    with pytest.raises(ValueError, match="not inputs of the frozen model"):
        vc.make_candidates(broken, COLUMNS)
    broken = copy.deepcopy(study)
    broken["reference"] = "C9"
    with pytest.raises(ValueError, match="reference"):
        vc.make_candidates(broken, COLUMNS)


# ------------------------------------------------------------------------------- training-only removal

def test_removing_positives_changes_the_training_rows_but_not_the_evaluation_layout(world):
    dev, layout = world
    positives = dev.positives
    keys = positives.iloc[[0, 5, 9]][["cell_id", "date"]]
    reduced = vc.without_positives(dev, keys)
    assert len(dev.positives) - len(reduced.positives) == 3
    assert len(reduced.samples) == len(dev.samples) - 3
    assert (reduced.samples["kind"] == "negative").sum() == (dev.samples["kind"] == "negative").sum()
    assert reduced.universe is dev.universe
    again = cv.make_layout(dev, FOLDS)
    assert len(layout.positives) == len(again.positives) == len(dev.positives)
    # a key that is not a positive removes nothing (here: a matched negative's key)
    negative_key = dev.samples.loc[dev.samples["kind"] == "negative", ["cell_id", "date"]].iloc[:2]
    assert len(vc.without_positives(dev, negative_key).samples) == len(dev.samples)
    assert len(vc.without_positives(dev, keys.iloc[:0]).samples) == len(dev.samples)


def test_a_candidate_trained_without_positives_is_still_scored_on_all_of_them(world, study):
    dev, layout = world
    candidates = vc.make_candidates(study, COLUMNS)
    keys = dev.positives.iloc[:6][["cell_id", "date"]]
    plain = vc.run_candidate(candidates["C2"], dev, layout, SELECTED, study["base"], keys)
    dropped = vc.run_candidate(candidates["C3"], dev, layout, SELECTED, study["base"], keys)
    assert len(dropped.oof.pos) == len(plain.oof.pos) == len(layout.positives)
    assert len(dropped.oof.neg) == len(plain.oof.neg) and dropped.oof.complete() and plain.oof.complete()
    assert not np.array_equal(dropped.oof.pos, plain.oof.pos)
    same = vc.run_candidate(candidates["C3"], dev, layout, SELECTED, study["base"], keys.iloc[:0])
    assert np.array_equal(same.oof.pos, plain.oof.pos)            # nothing to drop: C3 is C2


# ------------------------------------------------------------------------------- alert-level statistics

def hand_population() -> vc.Population:
    # 4 positives (scores 9, 7, 5, 1; the 7 and the 1 on low terrain, the 5 low-rain); 6 universe rows with weights 10 each
    neg_score = np.array([8.0, 6.0, 6.0, 4.0, 2.0, 0.0])
    return vc.Population(
        pos_score=np.array([9.0, 7.0, 5.0, 1.0]), neg_score=neg_score, neg_weight=np.full(6, 10.0),
        pos_low=np.array([False, True, False, True]), neg_low=np.array([False, True, False, False, True, True]),
        pos_lowrain=np.array([False, False, True, True]), neg_lowrain=np.array([True, False, False, False, True, True]),
        pos_region=np.array(["a", "a", "b", "b"]), neg_region=np.array(["a", "a", "a", "b", "b", "b"]))


def test_level_statistics_by_hand():
    stats = vc.level_statistics(hand_population(), 6.0)
    # alerted: positives 9 and 7; universe rows 8, 6, 6 -> 30 weighted cell-days
    assert stats["events"] == 2 and stats["recall"] == 0.5
    assert stats["cell_days"] == 32.0 and stats["fa_share"] == pytest.approx(0.5)
    assert stats["low_cell_days"] == 11.0                       # positive 7 and the universe row 6 (low)
    assert stats["low_share"] == pytest.approx(11 / 32) and stats["lowrain_share"] == pytest.approx(10 / 32)
    assert stats["precision_per_1000"] == pytest.approx(1000 * 2 / 32)
    # low-terrain population: positives 7 and 1 plus the universe rows 6, 2 and 0 (3 x 10) = 32 cell-days
    assert stats["low_alert_rate"] == pytest.approx(11 / 32)
    assert stats["other_alert_rate"] == pytest.approx(21 / 32)
    assert stats["low_precision_per_1000"] == pytest.approx(1000 * 1 / 11)
    assert stats["other_precision_per_1000"] == pytest.approx(1000 * 1 / 21)
    assert stats["low_base_events_per_1000"] == pytest.approx(1000 * 2 / 32)
    assert stats["other_base_events_per_1000"] == pytest.approx(1000 * 2 / 32)


def test_level_statistics_by_region_and_an_empty_alert():
    pop = hand_population()
    region = vc.level_statistics(pop, 6.0, "a")
    assert region["events"] == 2 and region["recall"] == 1.0 and region["cell_days"] == 32.0
    nothing = vc.level_statistics(pop, 100.0)
    assert nothing["events"] == 0 and nothing["cell_days"] == 0.0 and np.isnan(nothing["low_share"])
    assert np.isnan(nothing["precision_per_1000"]) and nothing["fa_share"] == 0.0


def test_bootstrap_statistics_are_paired_deterministic_and_centred_on_the_point():
    pop = hand_population()
    other = dataclasses.replace(pop, pos_score=pop.pos_score + 0.5)
    strata = np.array(["x", "x", "x", "y", "y", "y"])
    a = vc.bootstrap_level_statistics({"a": pop, "b": other}, {"a": 6.0, "b": 6.0}, strata, 400, 11)
    b = vc.bootstrap_level_statistics({"a": pop, "b": other}, {"a": 6.0, "b": 6.0}, strata, 400, 11)
    for key in vc.SHARES:
        np.testing.assert_array_equal(a["a"][key], b["a"][key])
    same = vc.bootstrap_level_statistics({"a": pop, "c": pop}, {"a": 6.0, "c": 6.0}, strata, 50, 3)
    for key in vc.SHARES:
        np.testing.assert_array_equal(same["a"][key], same["c"][key])
    assert abs(np.nanmean(a["a"]["recall"]) - 0.5) < 0.06
    assert abs(np.nanmean(a["a"]["fa_share"]) - 0.5) < 0.06
    assert np.all(a["a"]["fa_share"] >= 0) and np.all(np.isfinite(a["a"]["cell_days"]))
    interval = vc.interval(a["a"]["low_share"], 0.95)
    assert interval["lo"] <= np.nanmean(a["a"]["low_share"]) <= interval["hi"]
    assert vc.interval([np.nan, np.nan], 0.95) == {"lo": None, "hi": None, "se": None}


# ------------------------------------------------------------------------------------------- selection

def evaluation(rows: dict, reference_share=0.40) -> dict:
    """rows: name -> (FA@90, CI lower end of FA - FA(C0), Warning low-terrain share)."""
    candidates = {"C0": {"levels": {"warning": {"low_share": reference_share}}, "fa_at_90": {"value": 0.20}}}
    for name, (fa, lo, share) in rows.items():
        candidates[name] = {"levels": {"warning": {"low_share": share}}, "fa_at_90": {"value": fa},
                            "fa_diff_vs_reference": {"point_difference": fa - 0.20, "ci_lo": lo, "ci_hi": lo + 0.02}}
    return {"reference": "C0", "candidates": candidates}


def test_selection_takes_the_lowest_low_terrain_share_among_the_eligible(study):
    result = vc.select(evaluation({"C1": (0.21, -0.01, 0.30), "C2": (0.20, -0.02, 0.25), "C3": (0.20, 0.003, 0.10)}), study)
    assert result["selected"] == "C2" and result["result"] == "C2"
    by_name = {r["candidate"]: r for r in result["candidates"]}
    assert not by_name["C3"]["eligible"] and not by_name["C3"]["not_worse_than_reference"]   # significantly worse
    assert by_name["C1"]["eligible"] and by_name["C2"]["eligible"]


def test_selection_needs_a_lower_share_than_the_reference_and_ties_go_to_fewer_changes(study):
    result = vc.select(evaluation({"C1": (0.19, -0.03, 0.45), "C2": (0.21, 0.0, 0.40), "C3": (0.2, -0.01, 0.41)}), study)
    assert result["selected"] is None and result["result"] == vc.NO_CHALLENGER
    tie = vc.select(evaluation({"C1": (0.2, -0.01, 0.30), "C2": (0.2, -0.01, 0.30), "C3": (0.2, -0.01, 0.30)}), study)
    assert tie["selected"] == "C1"
    tie = vc.select(evaluation({"C1": (0.2, 0.01, 0.20), "C2": (0.2, -0.01, 0.30), "C3": (0.2, -0.01, 0.30)}), study)
    assert tie["selected"] == "C2"


def test_a_difference_interval_that_touches_zero_is_not_worse(study):
    result = vc.select(evaluation({"C1": (0.2, 0.0, 0.30), "C2": (0.2, 1e-9, 0.1), "C3": (0.2, 0.0, 0.5)}), study)
    assert result["selected"] == "C1"


# ---------------------------------------------------------------------- the stage end to end (synthetic)

@pytest.fixture(scope="module")
def evaluated(world, study):
    dev, layout = world
    candidates = vc.make_candidates(study, COLUMNS)
    keys = dev.positives.iloc[:8][["cell_id", "date"]]
    results = {n: vc.run_candidate(c, dev, layout, SELECTED, study["base"], keys) for n, c in candidates.items()}
    frames = {n: ch.oof_frame(layout, r.oof) for n, r in results.items()}
    return dev, layout, candidates, results, frames, vc.evaluate_candidates(layout, frames, results, study, say=lambda m: None), keys


def test_every_candidate_is_scored_on_the_same_rows_and_all_positives(evaluated):
    _, layout, _, results, frames, _, _ = evaluated
    for name, frame in frames.items():
        assert (frame["kind"] == "positive").sum() == len(layout.positives), name
        ch.assert_same_rows(frames["C0"], frame)
    assert results["C2"].columns == results["C3"].columns and len(results["C0"].columns) == len(COLUMNS)


def test_the_evaluation_reports_every_metric_of_the_spec_for_every_candidate(evaluated):
    _, _, _, _, _, report, _ = evaluated
    assert report["reference"] == "C0" and set(report["candidates"]) == {"C0", "C1", "C2", "C3"}
    c0 = report["candidates"]["C0"]
    assert "fa_diff_vs_reference" not in c0 and "low_share_diff_vs_reference" not in c0
    for name, entry in report["candidates"].items():
        assert 0 < entry["fa_at_90"]["value"] < 1 and entry["fa_at_90"]["lo"] <= entry["fa_at_90"]["hi"]
        assert set(entry["levels"]) == set(vc.LEVELS) and set(entry["at_reference_thresholds"]) == set(vc.LEVELS)
        for level in vc.LEVELS:
            stats = entry["levels"][level]
            assert 0 <= stats["recall"] <= 1 and 0 <= stats["fa_share"] <= 1 and stats["cell_days"] > 0
            assert set(vc.SHARES) <= set(stats["bootstrap"])
        assert entry["ece"]["crossfit_per_region"]["ece_deciles"] >= 0 and entry["ece"]["crossfit_pooled"]["ece_deciles"] >= 0
        assert set(entry["by_region_warning"]) == {"himalaya", "western_ghats"}
        assert entry["thresholds"]["warning"]["risk_by_region"].keys() == {"himalaya", "western_ghats"}
        if name != "C0":
            assert entry["fa_diff_vs_reference"]["n_boot"] == 40
            assert entry["low_share_diff_vs_reference"]["value"] == pytest.approx(
                entry["levels"]["warning"]["low_share"] - c0["levels"]["warning"]["low_share"])
    ref = c0["levels"]
    assert ref["watch"]["recall"] >= ref["warning"]["recall"] >= ref["emergency"]["recall"]
    assert c0["at_reference_thresholds"]["warning"]["raw_threshold"] == ref["warning"]["raw_threshold"]
    assert c0["at_reference_thresholds"]["warning"]["recall"] == ref["warning"]["recall"]


def test_selection_runs_on_the_evaluation_and_names_a_candidate_or_none(evaluated, study):
    *_, report, _ = evaluated
    result = vc.select(report, study)
    assert [r["candidate"] for r in result["candidates"]] == ["C1", "C2", "C3"]
    assert result["selected"] in (None, "C1", "C2", "C3")
    for row in result["candidates"]:
        assert row["eligible"] == (row["not_worse_than_reference"] and row["lower_low_share"])


def test_final_refit_saves_a_loadable_per_region_model_with_the_card_thresholds(evaluated, study, tmp_path):
    dev, layout, candidates, results, _, report, keys = evaluated
    model = vc.fit_final(candidates["C3"], dev, layout, results["C3"], study["base"], keys, tmp_path / "C3")
    loaded = hm.HazardModel.load(tmp_path / "C3")
    assert loaded.columns == candidates["C3"].columns and "stat_elev_mean" not in loaded.columns
    assert loaded.region_calibrator is not None and len(loaded.members) == 3
    assert loaded.card["candidate"] == "C3" and loaded.card["training"]["positives_dropped"] == 8
    assert loaded.card["alert_levels"]["warning"]["raw"] == pytest.approx(report["candidates"]["C3"]["thresholds"]["warning"]["raw"])
    scored = loaded.score(dev.positives.head(20))
    assert np.isfinite(scored["risk"]).all()
    assert np.allclose(scored["risk"], model.score(dev.positives.head(20))["risk"])
    for name, constraint in zip(loaded.columns, loaded.constraints):
        assert constraint == hm.configured_constraints([name], study["base"])[0]


def test_the_reference_must_reproduce_the_frozen_model(evaluated):
    *_, results, _, _, _ = evaluated
    result = results["C0"]
    frozen = {"pooled": {vc.HEADLINE: result.pooled[vc.HEADLINE]}, "n_trees": result.n_trees}
    assert vc.check_reproduction(result, frozen)["abs_difference"] == 0.0
    with pytest.raises(ch.ReproductionError):
        vc.check_reproduction(result, {**frozen, "n_trees": result.n_trees + 1})
    with pytest.raises(ch.ReproductionError):
        vc.check_reproduction(result, {"pooled": {vc.HEADLINE: result.pooled[vc.HEADLINE] + 0.01}, "n_trees": result.n_trees})


def test_saved_candidates_round_trip(evaluated, tmp_path):
    _, _, _, results, frames, _, _ = evaluated
    vc.save_oof(tmp_path, frames["C2"], results["C2"])
    again = vc.load_result(tmp_path, "C2")
    assert again.n_trees == results["C2"].n_trees and again.columns == results["C2"].columns
    np.testing.assert_array_equal(again.oof.pos, results["C2"].oof.pos)
    np.testing.assert_array_equal(again.oof.neg, results["C2"].oof.neg)
