import copy

import numpy as np
import pandas as pd
import pytest

from aetherguard.grid import ID_STRIDE, neighbours
from aetherguard.hazard import data as hd
from aetherguard.hazard import evaluate as ev
from aetherguard.hazard import model as hm
from aetherguard.hazard.calibration import MonotoneCalibrator
from aetherguard.hazard.metrics import ScoreSet

from hazard_helpers import UNIVERSE_SIZES, synthetic_samples, synthetic_universe

CFG = copy.deepcopy(hm.hazard_config())
CFG["bootstrap"]["n"] = 60


def _split(name, seed, n_pos=150):
    return hd.split_data(name, synthetic_samples(name, n_pos=n_pos, seed=seed, n_out_of_domain=4),
                         synthetic_universe(name, n_per_region=2500, seed=seed + 50))


SCORERS = {"model": lambda f: f["rain_acc_3"].fillna(0.0).to_numpy() + 0.5 * f["stat_slope_mean"].to_numpy(),
           "weak": lambda f: f["wet_top"].to_numpy()}


@pytest.fixture(scope="module")
def views():
    val, test = _split("validation", 1), _split("test_2018", 2)
    raw_val, raw_test = ev.score_universe(val, SCORERS), ev.score_universe(test, SCORERS)
    return val, test, raw_val, raw_test


def test_build_view_weights_masks_and_regions(views):
    val, _, raw_val, _ = views
    view = ev.build_view(val, raw_val)
    assert len(view.neg_weight) == 2 * (2500 - 30 - 1)
    for region, size in UNIVERSE_SIZES.items():
        assert view.neg_weight[view.neg_region == region].sum() == pytest.approx(size)
    assert view.n_positives == 150 and view.n_out_of_domain == 4
    with_buffer = ev.build_view(val, raw_val, include_buffer=True)
    assert len(with_buffer.neg_weight) == 2 * (2500 - 1)
    ghats = ev.build_view(val, raw_val, region="western_ghats")
    assert set(ghats.neg_region) == {"western_ghats"} and set(ghats.pos_region) == {"western_ghats"}
    assert ghats.neg_weight.sum() == pytest.approx(UNIVERSE_SIZES["western_ghats"])
    assert ghats.n_out_of_domain == val.n_out_of_domain["western_ghats"]
    assert ghats.name == "validation:western_ghats"


def test_evaluate_split_reports_cis_and_paired_differences(views):
    val, _, raw_val, _ = views
    result = ev.evaluate_split(ev.build_view(val, raw_val), CFG)
    metric = result["metrics"]["model"]["fa_at_recall_0.9"]
    assert metric["lo"] <= metric["value"] <= metric["hi"]
    assert {"recall_at_fa_0.01", "recall_at_fa_0.05", "pr_auc", "fa_at_recall_0.8", "fa_at_recall_0.95"} <= set(
        result["metrics"]["model"])
    paired = result["paired_fa_at_headline_recall"]["weak"]
    assert paired["value"] > 0 and paired["verdict"] == "model better"
    assert result["warning"] is None and result["n_positives"] == 150


def test_few_positives_trigger_a_warning(views):
    val, _, raw_val, _ = views
    result = ev.evaluate_split(ev.build_view(val, raw_val, region="western_ghats"), CFG)
    assert result["n_positives"] < 100 and "only" in result["warning"]


def test_thresholds_come_from_validation_and_are_applied_unchanged_to_test(views):
    val, test, raw_val, raw_test = views
    val_view, test_view = ev.build_view(val, raw_val), ev.build_view(test, raw_test)
    thresholds = ev.validation_thresholds(val_view, CFG)
    thr = thresholds["model"]["recall_0.9"]
    assert thr == pytest.approx(np.sort(val_view.sets["model"].pos)[::-1][int(np.ceil(0.9 * 150)) - 1])
    result = ev.evaluate_split(test_view, CFG, fixed_thresholds=thresholds)
    entry = result["fixed_thresholds"]["model"]["recall_0.9"]
    assert entry["threshold"] == thr
    scoring = test_view.sets["model"]
    assert entry["recall"]["value"] == pytest.approx(np.mean(scoring.pos >= thr))
    assert entry["fa_share"]["value"] == pytest.approx(scoring.fa_at(thr))
    own = scoring.threshold_for_recall(0.9)
    assert own != thr          # re-picking on test would give a different threshold: it must not happen
    fa_entry = result["fixed_thresholds"]["model"]["fa_0.01"]
    assert fa_entry["fa_share"]["value"] <= 0.01 + 1e-12 or fa_entry["threshold"] > 0


def test_overall_recall_counts_out_of_domain_positives_as_misses(views):
    val, test, raw_val, raw_test = views
    thresholds = ev.validation_thresholds(ev.build_view(val, raw_val), CFG)
    view = ev.build_view(test, raw_test)
    out = ev.overall_recall(view, thresholds, "recall_0.9", CFG)["model"]
    hits = out["in_domain"]["hits"]
    assert out["in_domain"]["n"] == 150 and out["overall"]["n"] == 154 and out["overall"]["hits"] == hits
    assert out["overall"]["value"] == pytest.approx(hits / 154)


def test_share_with_ci():
    out = ev.share_with_ci([1, 1, 0, 0], 200, 1, extra_zeros=4)
    assert out["value"] == 0.25 and out["n"] == 8 and out["hits"] == 2
    assert out["lo"] <= 0.25 <= out["hi"]
    assert ev.share_with_ci([1, 1, 0, 0], 200, 1) == ev.share_with_ci([1, 1, 0, 0], 200, 1)


def _window_frame():
    """Positive cell P with neighbours, a second positive cell Q far away, three control cells; 3 days each."""
    p, q = 2000 * ID_STRIDE + 3000, 2100 * ID_STRIDE + 3100
    cells = {"window_cell": sorted({p, q, *neighbours(p), *neighbours(q)}), "window_control": [900_000_001, 900_000_002,
                                                                                               900_000_003]}
    rows = [{"cell_id": c, "date": d, "kind": k, "is_window_positive_cell": c in (p, q) and k == "window_cell"}
            for k, ids in cells.items() for c in ids for d in range(3)]
    return p, q, pd.DataFrame(rows)


def test_window_detection_uses_the_max_over_days_and_the_3x3_neighbourhood():
    p, q, frame = _window_frame()
    scores = np.full(len(frame), 1.0)
    neighbour = neighbours(p)[3]
    scores[((frame["cell_id"] == neighbour) & (frame["date"] == 2)).to_numpy()] = 9.0     # a neighbour, one day
    scores[((frame["cell_id"] == 900_000_001) & (frame["date"] == 1)).to_numpy()] = 9.0   # one control cell, one day
    out = ev.window_detection(frame, scores, threshold=5.0, n_boot=50, seed=1)
    assert out["positive_cells"] == 2
    assert out["detection"]["hits"] == 1 and out["detection"]["value"] == 0.5
    detected = {c["cell_id"]: c["detected"] for c in out["cells"]}
    assert detected == {p: True, q: False}
    assert all(c["neighbourhood_cells"] == 9 for c in out["cells"])
    assert out["control_cells"] == 3 and out["control_any_alert"]["hits"] == 1
    assert out["control_cell_day_alert_share"] == pytest.approx(1 / 9)
    assert ev.window_detection(frame, scores, 9.0, 50, 1)["detection"]["hits"] == 1       # alert is >= threshold
    assert ev.window_detection(frame, scores, np.inf, 50, 1)["detection"]["hits"] == 0


def test_window_neighbourhood_is_limited_to_cells_present_in_the_window_rows():
    p, _, frame = _window_frame()
    frame = frame[~((frame["cell_id"] == neighbours(p)[0]) & (frame["kind"] == "window_cell"))]
    out = ev.window_detection(frame, np.zeros(len(frame)), 1.0, 20, 1)
    assert {c["cell_id"]: c["neighbourhood_cells"] for c in out["cells"]}[p] == 8


def test_calibration_report_on_a_known_population():
    sets = {"model": ScoreSet([1.0, 1.0], [0.0, 0.0], [1, 1])}
    scored = ev.ScoredSplit("x", sets, np.array([99.0, 99.0]), np.array(["a", "a"]), np.array(["a", "a"]), 0,
                            risk_pos=np.array([0.01, 0.01]), risk_neg=np.array([0.0, 0.0]))
    out = ev.calibration_report(scored, CFG)
    assert out["base_rate"] == pytest.approx(2 / 198)
    assert out["mean_predicted_risk"] == pytest.approx(2 * 0.01 / 200)
    assert out["ece_deciles"] >= 0 and out["deciles"] and out["tail_bins"]
    with pytest.raises(ValueError, match="no calibrated risk"):
        ev.calibration_report(ev.ScoredSplit("x", sets, np.array([1.0]), np.array(["a"]), np.array(["a"]), 0), CFG)


def test_calibration_of_a_calibrated_model_has_small_ece(views):
    val, _, raw_val, _ = views
    keep = hd.universe_negative_mask(val.universe)
    raw = np.concatenate([raw_val["model"][0], raw_val["model"][1][keep]])
    labels = np.r_[np.ones(150), np.zeros(int(keep.sum()))]
    weights = np.r_[np.ones(150), hd.universe_negatives(val.universe)["weight"].to_numpy()]
    calibrator = MonotoneCalibrator.fit(raw, labels, weights)
    risk = (calibrator.predict(raw_val["model"][0]), calibrator.predict(raw_val["model"][1]))
    out = ev.calibration_report(ev.build_view(val, raw_val, risk=risk), CFG)
    assert out["ece_deciles_relative_to_base_rate"] < 0.3


def test_case_alerts_counts_positives_and_excludes_buffer_from_the_alert_share():
    frame = pd.DataFrame({"is_positive_cell_day": [True, True, False, False, False, False],
                          "in_buffer": [True, False, False, False, True, False]})
    scores = np.array([9.0, 1.0, 9.0, 1.0, 9.0, 1.0])
    out = ev.case_alerts(frame, scores, 5.0)
    assert out["positive_cell_days"] == 2 and out["positives_alerted"] == 1 and out["recall"] == 0.5
    assert out["alerted_share_non_buffer"] == pytest.approx(1 / 3)      # rows 2, 3, 5 are eligible
    assert out["alerted_cell_days"] == 3 and out["max_score"] == 9.0
    empty = ev.case_alerts(frame.assign(is_positive_cell_day=False), scores, 5.0)
    assert empty["recall"] is None


def test_paired_fixed_thresholds_compare_model_and_baseline_at_their_own_thresholds(views):
    val, _, raw_val, _ = views
    view = ev.build_view(val, raw_val)
    thresholds = {"model": {"watch": float(np.sort(view.sets["model"].pos)[::-1][int(0.9 * 150)])},
                  "weak": {"watch": float(np.sort(view.sets["weak"].pos)[::-1][int(0.9 * 150)])}}
    result = ev.evaluate_split(view, CFG, fixed_thresholds=thresholds, comparators=["weak"])
    paired = result["paired_fixed_thresholds"]["weak"]["watch"]
    model_fa = result["fixed_thresholds"]["model"]["watch"]["fa_share"]["value"]
    weak_fa = result["fixed_thresholds"]["weak"]["watch"]["fa_share"]["value"]
    assert paired["fa_share_baseline_minus_model"]["value"] == pytest.approx(weak_fa - model_fa)
    assert paired["fa_share_baseline_minus_model"]["value"] > 0 and paired["fa_share_baseline_minus_model"]["lo"] > 0
    model_rec = result["fixed_thresholds"]["model"]["watch"]["recall"]["value"]
    weak_rec = result["fixed_thresholds"]["weak"]["watch"]["recall"]["value"]
    assert paired["recall_model_minus_baseline"]["value"] == pytest.approx(model_rec - weak_rec)
    assert set(result["paired_fa_at_headline_recall"]) == {"weak"}


def test_paired_recall_difference_point_sign_matches_its_interval(views):
    """Regression: the point value of recall_model_minus_baseline once had the opposite sign to its bootstrap CI."""
    val, _, raw_val, _ = views
    view = ev.build_view(val, raw_val)
    thresholds = {"model": {"watch": float(np.sort(view.sets["model"].pos)[::-1][int(0.9 * 150)])},
                  "weak": {"watch": float(np.sort(view.sets["weak"].pos)[::-1][int(0.6 * 150)])}}
    result = ev.evaluate_split(view, CFG, fixed_thresholds=thresholds, comparators=["weak"])
    paired = result["paired_fixed_thresholds"]["weak"]["watch"]["recall_model_minus_baseline"]
    model_rec = result["fixed_thresholds"]["model"]["watch"]["recall"]["value"]
    weak_rec = result["fixed_thresholds"]["weak"]["watch"]["recall"]["value"]
    assert model_rec > weak_rec
    assert paired["value"] == pytest.approx(model_rec - weak_rec)
    assert paired["lo"] <= paired["value"] <= paired["hi"]
