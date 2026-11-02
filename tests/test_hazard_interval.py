"""The ensemble interval re-centred on the point model, the calibrated member median and the ensemble agreement
(spec section 11): risk_lo <= risk <= risk_hi on every row."""
import numpy as np
import pandas as pd
import pytest

from aetherguard.alerts import levels as lv
from aetherguard.hazard import model as hm
from aetherguard.hazard.calibration import MonotoneCalibrator, RegionCalibrator

from live_run_helpers import MODEL_COLUMNS, tiny_model

CARD_LEVELS = {"alert_levels": {
    "watch": {"raw": 0.2, "risk": 0.2, "risk_by_region": {"himalaya": 0.15, "western_ghats": 0.25}},
    "warning": {"raw": 0.5, "risk": 0.5, "risk_by_region": {"himalaya": 0.45, "western_ghats": 0.55}},
    "emergency": {"raw": 0.8, "risk": 0.8, "risk_by_region": {"himalaya": 0.75, "western_ghats": 0.85}}}}


def _random_scores(seed: int, n: int = 2000, members: int = 20):
    rng = np.random.default_rng(seed)
    centre = rng.uniform(-30, 10, n)
    point = hm.expit(centre + rng.normal(0, 3, n))
    member = hm.expit(centre[:, None] + rng.normal(0, 1, (n, members)) * rng.uniform(0, 4, n)[:, None])
    point[:5] = [0.0, 1.0, 1e-300, 1 - 1e-16, 0.5]          # extremes the logit clip must survive
    member[:3] = [np.zeros(members), np.ones(members), np.full(members, 0.3)]
    return point, member


@pytest.mark.parametrize("seed", range(5))
def test_recentred_bounds_bracket_the_point_on_random_inputs(seed):
    point, member = _random_scores(seed)
    lo = hm.recentred_percentile(point, member, 10.0)
    hi = hm.recentred_percentile(point, member, 90.0)
    assert np.isfinite(lo).all() and np.isfinite(hi).all()
    assert (lo <= point).all() and (point <= hi).all()
    assert ((0.0 <= lo) & (hi <= 1.0)).all()
    calibrator = MonotoneCalibrator(np.sort(np.random.default_rng(seed).uniform(0, 1, 30)),
                                    np.sort(np.random.default_rng(seed + 1).uniform(0, 1e-4, 30)))
    risk_lo, risk, risk_hi = (calibrator.predict(v) for v in (lo, point, hi))
    assert (risk_lo <= risk).all() and (risk <= risk_hi).all()


def test_recentred_bound_is_the_members_logit_spread_moved_to_the_point():
    member = np.array([[0.01, 0.02, 0.04, 0.08, 0.16]])
    point = np.array([0.3])
    q90, median = np.percentile(member, [90, 50], axis=1)
    expected = hm.expit(hm.logit(point) + hm.logit(q90) - hm.logit(median))
    assert hm.recentred_percentile(point, member, 90.0) == pytest.approx(expected, rel=1e-12)
    # a point far above every member (the reported 23 Oct cell) keeps an interval around itself
    assert hm.recentred_percentile(point, member, 10.0)[0] < 0.3 < hm.recentred_percentile(point, member, 90.0)[0]
    # identical members: no spread, the interval collapses onto the point
    flat = np.full((1, 5), 0.02)
    assert hm.recentred_percentile(point, flat, 10.0)[0] == pytest.approx(0.3, rel=1e-12)
    assert hm.recentred_percentile(point, flat, 90.0)[0] == pytest.approx(0.3, rel=1e-12)


def test_recentred_percentile_rejects_mismatched_member_scores():
    with pytest.raises(ValueError, match="rows, members"):
        hm.recentred_percentile(np.array([0.1, 0.2]), np.array([[0.1, 0.2, 0.3]]), 90.0)


def test_ensemble_agreement_counts_members_at_the_points_level():
    thresholds = np.tile([0.2, 0.5, 0.8], (4, 1))
    point = np.array([0.1, 0.3, 0.6, 0.9])
    members = np.array([[0.0, 0.0, 0.0, 0.0],          # Normal point: agreement 1 whatever the members
                        [0.1, 0.2, 0.6, 0.9],          # Watch point: 3 of 4 members at Watch or above
                        [0.1, 0.3, 0.4, 0.55],         # Warning point: 1 of 4 at Warning or above
                        [0.8, 0.79, 0.1, 0.95]])       # Emergency point: 2 of 4
    assert hm.ensemble_agreement(point, members, thresholds).tolist() == [1.0, 0.75, 0.25, 0.5]


def _card_model(region_calibrated: bool) -> hm.HazardModel:
    model = tiny_model()
    region = (RegionCalibrator({"himalaya": model.calibrator, "western_ghats": model.calibrator}, model.calibrator)
              if region_calibrated else None)
    return hm.HazardModel(model.columns, model.constraints, model.booster, model.best_iteration, model.members,
                          model.calibrator, CARD_LEVELS, region)


def _rows(seed: int, n: int = 300) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    acc3 = rng.uniform(0, 320, n)
    frame = pd.DataFrame({"irain_acc_1": acc3 * rng.uniform(0, 0.8, n), "irain_acc_3": acc3,
                          "irain_acc_7": acc3 * rng.uniform(1, 2, n), "iapi_90": acc3 * rng.uniform(0.3, 1, n),
                          "inbr_max_acc_1": acc3 * rng.uniform(0, 0.9, n), "stat_slope_mean": rng.uniform(5, 40, n)})
    return frame.assign(region=np.where(rng.random(n) < 0.5, "himalaya", "western_ghats"))


@pytest.mark.parametrize("region_calibrated", [False, True])
def test_a_real_tiny_model_keeps_every_row_inside_its_interval(region_calibrated):
    model = _card_model(region_calibrated)
    rows = _rows(4)
    scored = model.score(rows)
    assert list(scored.columns) == ["risk", "risk_lo", "risk_hi", "risk_per_100k", "member_median_risk",
                                    "ensemble_agreement"]
    risk = scored["risk"].to_numpy()
    assert (scored["risk_lo"].to_numpy() <= risk).all() and (risk <= scored["risk_hi"].to_numpy()).all()
    assert np.array_equal(scored["risk_per_100k"].to_numpy(), 1e5 * risk)
    median = np.percentile(model.member_raw_scores(rows), 50, axis=1)
    assert np.array_equal(scored["member_median_risk"].to_numpy(), model.calibrate(median, rows)[0])
    agreement = scored["ensemble_agreement"].to_numpy()
    assert ((0 <= agreement) & (agreement <= 1)).all()


def test_agreement_uses_the_thresholds_of_each_rows_region_for_a_region_calibrated_model():
    model = _card_model(True)
    rows = _rows(5)
    thresholds = model.level_thresholds(rows)
    expected = np.where((rows["region"] == "himalaya").to_numpy()[:, None], [0.15, 0.45, 0.75], [0.25, 0.55, 0.85])
    assert np.array_equal(thresholds, expected)
    members, _ = model.calibrate(model.member_raw_scores(rows), rows)
    scored = model.score(rows)
    assert np.array_equal(scored["ensemble_agreement"].to_numpy(),
                          hm.ensemble_agreement(scored["risk"].to_numpy(), members, expected))
    # a pooled model (or a frame without regions) uses the pooled thresholds
    pooled = np.tile([0.2, 0.5, 0.8], (len(rows), 1))
    assert np.array_equal(_card_model(False).level_thresholds(rows), pooled)
    assert np.array_equal(model.level_thresholds(rows.drop(columns="region")), pooled)


def test_a_card_without_alert_levels_gives_an_unknown_agreement():
    scored = tiny_model().score(_rows(6)[MODEL_COLUMNS])
    assert scored["ensemble_agreement"].isna().all()
    assert scored["member_median_risk"].notna().all()


def test_the_level_thresholds_match_the_live_runners_card_thresholds():
    model = _card_model(True)
    rows = _rows(7)
    pooled = lv.thresholds_from_card(CARD_LEVELS, {})
    runner = lv.RegionThresholds(lv.card_region_thresholds(CARD_LEVELS, rows["region"]), pooled)
    assert np.array_equal(model.level_thresholds(rows), runner.matrix(rows["region"].to_numpy()))
