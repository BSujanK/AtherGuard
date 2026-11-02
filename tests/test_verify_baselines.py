import numpy as np
import pytest

from aetherguard.verify.baselines import (
    burden_matched_cuts,
    rain_baseline,
    susceptibility_baseline,
    threshold_levels,
)


def test_cuts_reproduce_the_target_shares():
    cuts = burden_matched_cuts(np.arange(1000.0), np.ones(1000, bool), (0.5, 0.2, 0.05))
    lv = threshold_levels(np.arange(1000.0), cuts)
    assert [(lv >= k).mean() for k in (1, 2, 3)] == pytest.approx([0.5, 0.2, 0.05], abs=0.001)


def test_nan_rain_never_alerts():
    assert threshold_levels(np.array([np.nan, 50.0]), (1.0, 10.0, 40.0)).tolist() == [0, 3]


def test_threshold_levels_is_int8_and_keeps_shape():
    lv = threshold_levels(np.array([[0.0, 1.0, 10.0], [40.0, np.nan, 5.0]]), (1.0, 10.0, 40.0))
    assert lv.dtype == np.int8
    assert lv.tolist() == [[0, 1, 2], [3, 0, 1]]


def test_cuts_use_only_finite_values_of_scored_cell_days():
    values = np.concatenate([np.arange(100.0), np.full(100, 1e6), np.full(50, np.nan)])
    scored = np.concatenate([np.ones(100, bool), np.zeros(100, bool), np.ones(50, bool)])
    cuts = burden_matched_cuts(values, scored, (0.5, 0.2, 0.1))
    assert cuts == pytest.approx((49.5, 79.2, 89.1))


def test_cuts_never_decrease():
    cuts = burden_matched_cuts(np.arange(10.0), np.ones(10, bool), (0.2, 0.2, 0.2))
    assert cuts[0] <= cuts[1] <= cuts[2]


def test_a_zero_share_alerts_nothing_and_no_scored_values_alert_nothing():
    assert threshold_levels(np.arange(10.0), burden_matched_cuts(np.arange(10.0), np.ones(10, bool), (0.5, 0.0, 0.0))).tolist() == [
        0, 0, 0, 0, 0, 1, 1, 1, 1, 1,
    ]
    cuts = burden_matched_cuts(np.array([np.nan, 5.0]), np.array([True, False]), (0.5, 0.2, 0.1))
    assert threshold_levels(np.array([np.nan, 5.0]), cuts).tolist() == [0, 0]


@pytest.mark.parametrize("shares", [(0.1, 0.2, 0.05), (1.5, 0.2, 0.1), (0.5, 0.2, -0.1)])
def test_cuts_reject_shares_that_are_not_cumulative(shares):
    with pytest.raises(ValueError, match="shares"):
        burden_matched_cuts(np.arange(10.0), np.ones(10, bool), shares)


def test_cuts_reject_mismatched_shapes():
    with pytest.raises(ValueError, match="shape"):
        burden_matched_cuts(np.arange(10.0), np.ones(9, bool), (0.5, 0.2, 0.1))


def test_rain_baseline_applies_development_cuts_and_zeroes_unscored_cells():
    dev = np.tile(np.arange(100.0), (2, 1))
    dev_scored = np.ones_like(dev, bool)
    acc = np.array([[0.0, 85.0, 99.0], [99.0, 99.0, 99.0]])
    scored = np.array([[True, True, True], [False, False, False]])
    lv = rain_baseline(acc, scored, dev, dev_scored, (0.5, 0.2, 0.05))
    assert lv.dtype == np.int8
    assert lv.tolist() == [[0, 2, 3], [0, 0, 0]]


def test_susceptibility_baseline_alerts_the_same_cells_every_day():
    lv = susceptibility_baseline(np.array([0.1, 0.9, 0.5, 0.2]), 3, np.ones((4, 3), bool), (0.25, 0.25, 0.25))
    assert lv[1].tolist() == [3, 3, 3] and lv[[0, 2, 3]].max() == 0


def test_susceptibility_baseline_places_cumulative_shares_over_each_days_scored_cells():
    static = np.array([0.1, 0.9, 0.5, 0.2, 0.7, 0.3, 0.8, 0.4])
    lv = susceptibility_baseline(static, 2, np.ones((8, 2), bool), (0.5, 0.25, 0.125))
    assert lv.dtype == np.int8
    assert lv[:, 0].tolist() == [0, 3, 1, 0, 1, 0, 2, 0]


def test_susceptibility_baseline_skips_unscored_cells_and_ranks_the_rest():
    static = np.array([0.9, 0.5, 0.1, 0.7])
    scored = np.array([[False, True], [True, True], [True, True], [True, False]])
    lv = susceptibility_baseline(static, 2, scored, (0.5, 0.5, 0.5))
    assert lv[:, 0].tolist() == [0, 3, 0, 3]
    assert lv[:, 1].tolist() == [3, 3, 0, 0]


def test_susceptibility_baseline_rejects_mismatched_shapes():
    with pytest.raises(ValueError, match="shape"):
        susceptibility_baseline(np.arange(4.0), 3, np.ones((4, 2), bool), (0.25, 0.25, 0.25))
