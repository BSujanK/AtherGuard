import json

import numpy as np
import pytest

from aetherguard.hazard import calibration as c


def test_calibrator_is_monotone_and_clips_outside_the_fit_range():
    rng = np.random.default_rng(0)
    scores = rng.random(500)
    labels = (rng.random(500) < scores * 0.5).astype(float)
    labels[0] = 1.0
    cal = c.MonotoneCalibrator.fit(scores, labels, np.ones(500))
    grid = np.linspace(-1, 2, 300)
    out = cal.predict(grid)
    assert (np.diff(out) >= 0).all()
    assert out[0] == out[grid <= scores.min()][-1] and out[-1] == out[grid >= scores.max()][0]
    assert ((out >= 0) & (out <= 1)).all()


def test_calibrator_is_weight_aware():
    scores = np.array([0.1, 0.1, 0.9, 0.9])
    labels = np.array([1.0, 0.0, 1.0, 0.0])
    plain = c.MonotoneCalibrator.fit(scores, labels, np.ones(4))
    weighted = c.MonotoneCalibrator.fit(scores, labels, np.array([1.0, 99.0, 1.0, 9.0]))
    assert plain.predict([0.1])[0] == pytest.approx(0.5)
    assert weighted.predict([0.1])[0] == pytest.approx(0.01)
    assert weighted.predict([0.9])[0] == pytest.approx(0.1)


def test_calibrated_probability_estimates_the_true_base_rate():
    # 10 positives among 1,000,000 cell-days represented by 1000 rows of weight 1000: P is ~1e-5.
    scores = np.r_[np.full(10, 0.9), np.linspace(0, 1, 1000)]
    labels = np.r_[np.ones(10), np.zeros(1000)]
    weights = np.r_[np.ones(10), np.full(1000, 1000.0)]
    cal = c.MonotoneCalibrator.fit(scores, labels, weights)
    assert cal.predict([1.0])[0] == pytest.approx(10 / (10 + 100 * 1000.0), rel=0.2)
    assert cal.predict([0.0])[0] == 0.0


def test_calibrator_round_trips_through_a_dict():
    cal = c.MonotoneCalibrator([0.0, 0.5, 1.0], [0.0, 1e-6, 5e-6])
    again = c.MonotoneCalibrator.from_dict(cal.to_dict())
    np.testing.assert_array_equal(cal.predict([0.2, 0.7]), again.predict([0.2, 0.7]))


@pytest.mark.parametrize("scores,labels,weights", [
    ([0.1, np.nan], [1, 0], [1, 1]), ([0.1, 0.2], [1, 0], [1, 0]), ([0.1, 0.2], [0, 0], [1, 1]),
    ([0.1, 0.2], [1, 2], [1, 1])])
def test_calibrator_rejects_bad_input(scores, labels, weights):
    with pytest.raises(ValueError):
        c.MonotoneCalibrator.fit(scores, labels, weights)


def test_reliability_table_and_ece_on_handmade_data():
    risk = np.array([0.1, 0.1, 0.1, 0.1, 0.5, 0.5, 0.5, 0.5])
    labels = np.array([0, 0, 0, 1, 0, 1, 1, 1], dtype=float)
    weights = np.ones(8)
    table = c.reliability_table(risk, labels, weights, [0.0, 0.5, 1.0])
    assert [r["population"] for r in table] == [4.0, 4.0]
    assert [r["positives"] for r in table] == [1, 3]
    assert table[0]["mean_risk"] == pytest.approx(0.1) and table[0]["observed_rate"] == pytest.approx(0.25)
    assert c.expected_calibration_error(table) == pytest.approx(0.5 * 0.15 + 0.5 * 0.25)


def test_reliability_bins_are_weighted_and_keep_ties_together():
    risk = np.array([0.0, 0.0, 0.0, 1.0])
    weights = np.array([20.0, 20.0, 20.0, 40.0])
    table = c.reliability_table(risk, np.array([0, 0, 0, 1.0]), weights, c.decile_edges(10))
    assert [r["population"] for r in table] == [60.0, 40.0]     # the three tied zeros span 60% of the population yet share one bin
    assert sum(r["population_share"] for r in table) == pytest.approx(1.0)


def test_reliability_rejects_misaligned_input():
    with pytest.raises(ValueError):
        c.reliability_table([0.1, 0.2], [0, 1], [1.0], [0.0, 1.0])


# ------------------------------------------------------------------------------------- RegionCalibrator

def _region_data(seed=0, n=600):
    """Two regions with different base rates; raw score has the same ranking meaning in both."""
    rng = np.random.default_rng(seed)
    region = np.where(rng.random(n) < 0.5, "himalaya", "western_ghats")
    score = rng.random(n)
    rate = np.where(region == "himalaya", 0.1, 0.4) * score
    label = (rng.random(n) < rate).astype(float)
    label[0] = 1.0
    return score, label, region


def _fit_pair(min_positives=25):
    score, label, region = _region_data()
    weights = np.ones(len(score))
    pooled = c.MonotoneCalibrator.fit(score, label, weights)
    by_region = {r: c.MonotoneCalibrator.fit(score[region == r], label[region == r], weights[region == r])
                 for r in ("himalaya", "western_ghats")}
    return c.RegionCalibrator(by_region, pooled, min_positives), score, region


def test_region_calibrator_is_monotone_within_each_region_and_differs_between_them():
    rc, _, _ = _fit_pair()
    grid = np.linspace(0, 1, 200)
    out = {r: rc.predict(grid, r) for r in ("himalaya", "western_ghats")}
    for risk in out.values():
        assert (np.diff(risk) >= 0).all() and ((risk >= 0) & (risk <= 1)).all()
    assert not np.array_equal(out["himalaya"], out["western_ghats"])
    assert out["western_ghats"][-1] > out["himalaya"][-1]


def test_region_calibrator_applies_each_rows_own_region_and_the_pooled_fallback():
    rc, score, region = _fit_pair()
    rows = np.array(["himalaya", "western_ghats", "atlantis", np.nan, "himalaya"], dtype=object)
    raw = np.array([0.2, 0.2, 0.2, 0.2, 0.9])
    out = rc.predict(raw, rows)
    assert out[0] == rc.by_region["himalaya"].predict([0.2])[0] and out[4] == rc.by_region["himalaya"].predict([0.9])[0]
    assert out[1] == rc.by_region["western_ghats"].predict([0.2])[0]
    assert out[2] == out[3] == rc.pooled.predict([0.2])[0]
    np.testing.assert_array_equal(rc.uses_pooled(rows), [False, False, True, True, False])
    np.testing.assert_array_equal(rc.predict(raw[:2], "himalaya"), rc.by_region["himalaya"].predict(raw[:2]))


def test_region_calibrator_handles_2d_member_scores_and_validates_shapes():
    rc, _, _ = _fit_pair()
    raw = np.random.default_rng(1).random((4, 3))
    regions = ["himalaya", "western_ghats", "himalaya", "unknown"]
    out = rc.predict(raw, regions)
    assert out.shape == (4, 3)
    for k, region in enumerate(regions):
        calibrator = rc.by_region.get(region, rc.pooled)
        np.testing.assert_array_equal(out[k], calibrator.predict(raw[k]))
    with pytest.raises(ValueError, match="one name per row"):
        rc.predict(raw, ["himalaya"])
    with pytest.raises(ValueError, match="at least one dimension"):
        rc.predict(0.5, "himalaya")
    with pytest.raises(ValueError, match="min_positives"):
        c.RegionCalibrator({}, rc.pooled, 0)


def test_region_calibrator_json_round_trip_keeps_predictions_and_min_positives():
    rc, score, region = _fit_pair(min_positives=30)
    payload = rc.to_json()
    assert payload["min_positives"] == 30 and sorted(payload["by_region"]) == ["himalaya", "western_ghats"]
    for again in (c.RegionCalibrator.from_json(payload), c.RegionCalibrator.from_json(json.dumps(payload))):
        assert again.min_positives == 30 and sorted(again.by_region) == sorted(rc.by_region)
        np.testing.assert_array_equal(again.predict(score, region), rc.predict(score, region))
        np.testing.assert_array_equal(again.pooled.predict(score), rc.pooled.predict(score))
    assert c.RegionCalibrator({}, rc.pooled).min_positives == 25
