import numpy as np
import pytest

from aetherguard.verify.baselines import (
    burden_matched_cuts,
    burden_matched_levels,
    ed_ratio,
    ed_threshold_levels,
    fit_ed_threshold,
    realised_shares,
    rain_baseline,
    rain_events,
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
    assert lv[:, 1].tolist() == [3, 0, 0, 0]


def test_susceptibility_baseline_rejects_mismatched_shapes():
    with pytest.raises(ValueError, match="shape"):
        susceptibility_baseline(np.arange(4.0), 3, np.ones((4, 2), bool), (0.25, 0.25, 0.25))


def test_zero_rain_never_alerts_when_the_share_exceeds_the_non_zero_fraction():
    rain = np.concatenate([np.zeros(600), np.arange(1.0, 401.0)])
    cuts = burden_matched_cuts(rain, np.ones(1000, bool), (0.5, 0.2, 0.05))
    lv = threshold_levels(rain, cuts)
    assert (lv[:600] == 0).all()
    assert realised_shares(lv, np.ones(1000, bool))[0] == pytest.approx(0.4, abs=0.01)
    assert realised_shares(lv, np.ones(1000, bool))[1:] == pytest.approx((0.2, 0.05), abs=0.01)


def test_a_heavy_tie_takes_the_side_closer_to_the_target():
    ones = np.ones(1000, bool)
    ties = np.concatenate([np.zeros(500), np.full(300, 5.0), np.arange(200.0) + 10.0])  # >= 5 is 0.5, > 5 is 0.2
    closer_above = threshold_levels(ties, burden_matched_cuts(ties, ones, (0.45, 0.0, 0.0)))
    assert realised_shares(closer_above, ones)[0] == 0.5
    closer_below = threshold_levels(ties, burden_matched_cuts(ties, ones, (0.25, 0.0, 0.0)))
    assert realised_shares(closer_below, ones)[0] == 0.2


def test_realised_shares_counts_scored_cell_days_only():
    levels = np.array([[0, 1, 2, 3], [3, 3, 3, 3]], dtype=np.int8)
    scored = np.array([[True, True, True, True], [False, False, False, False]])
    assert realised_shares(levels, scored) == (0.75, 0.5, 0.25)
    assert all(np.isnan(realised_shares(levels, np.zeros((2, 4), bool))))


def test_susceptibility_baseline_carries_the_remainder_so_rare_levels_appear():
    static = np.random.default_rng(0).random(1000)
    scored = np.ones((1000, 30), bool)
    lv = susceptibility_baseline(static, 30, scored, (0.0004, 0.0004, 0.0004))
    assert (lv == 3).sum() == 12
    nested = susceptibility_baseline(static, 30, scored, (0.1, 0.01, 0.0004))
    assert [(nested >= k).sum() for k in (1, 2, 3)] == [3000, 300, 12]
    assert realised_shares(nested, scored) == pytest.approx((0.1, 0.01, 0.0004))


# ---------------------------------------------------------------------------------- event-duration threshold

def test_rain_events_total_and_length_of_the_wet_run_ending_each_day():
    daily = np.array([[0.0, 2.0, 3.0, 0.5, 4.0, np.nan, 2.0, 2.0, 0.0, 3.0]])
    event, duration = rain_events(daily)
    nan = np.nan
    assert np.allclose(event[0], [0.0, 2.0, 5.0, 0.0, 4.0, nan, nan, nan, 0.0, 3.0], equal_nan=True)
    assert np.allclose(duration[0], [0, 1, 2, 0, 1, nan, nan, nan, 0, 1], equal_nan=True)


def test_rain_events_a_run_that_starts_with_the_series_is_unknown():
    event, duration = rain_events(np.array([[5.0, 5.0, 0.0, 5.0]]))
    assert np.allclose(event[0], [np.nan, np.nan, 0.0, 5.0], equal_nan=True)
    assert np.allclose(duration[0], [np.nan, np.nan, 0.0, 1.0], equal_nan=True)


def test_rain_events_wet_threshold_is_inclusive_and_cells_are_independent():
    event, duration = rain_events(np.array([[0.0, 1.0, 1.0], [0.0, 0.9, 1.0]]))
    assert event.tolist() == [[0.0, 1.0, 2.0], [0.0, 0.0, 1.0]]
    assert duration.tolist() == [[0.0, 1.0, 2.0], [0.0, 0.0, 1.0]]


def test_ed_ratio_is_one_on_the_threshold_curve():
    duration = np.array([1.0, 2.0, 5.0])
    assert ed_ratio(7.0 * duration**0.8, duration, 7.0, 0.8) == pytest.approx([1.0, 1.0, 1.0])


def test_ed_ratio_above_one_is_an_event_over_the_threshold_and_no_event_is_zero():
    ratio = ed_ratio(np.array([20.0, 5.0, 0.0, np.nan]), np.array([2.0, 2.0, 0.0, 2.0]), 4.0, 1.0)
    assert ratio[0] > 1.0 > ratio[1]
    assert ratio[2] == 0.0
    assert np.isnan(ratio[3])


def test_burden_matched_levels_reach_the_shares_and_leave_unscored_cell_days_dry():
    values = np.arange(1000.0)
    scored = np.ones(1000, bool)
    scored[:100] = False
    levels = burden_matched_levels(values, scored, (0.5, 0.2, 0.05))
    assert levels.dtype == np.int8
    assert (levels[:100] == 0).all()
    assert realised_shares(levels, scored) == pytest.approx((0.5, 0.2, 0.05), abs=0.002)


def test_ed_threshold_levels_rank_by_the_ratio_to_the_curve_not_by_total_rain():
    duration = np.array([1.0, 10.0, 1.0, 0.0])
    event = np.array([30.0, 40.0, 5.0, 0.0])      # alpha 5, gamma 1: ratios 6, 0.8, 1, 0
    levels = ed_threshold_levels(event, duration, 5.0, 1.0, (0.5, 0.25, 0.25), np.ones(4, bool))
    assert levels.tolist() == [3, 0, 1, 0]


def test_ed_threshold_levels_never_alert_without_an_event_or_on_unscored_cell_days():
    event = np.array([[0.0, 9.0, 9.0, np.nan]])
    duration = np.array([[0.0, 1.0, 1.0, 1.0]])
    scored = np.array([[True, True, False, True]])
    levels = ed_threshold_levels(event, duration, 1.0, 1.0, (1.0, 1.0, 1.0), scored)
    assert levels.tolist() == [[0, 3, 0, 0]]


def test_ed_threshold_levels_reach_v3_shares_over_many_cell_days():
    rng = np.random.default_rng(3)
    duration = rng.integers(1, 8, (50, 40)).astype(float)
    event = duration * rng.gamma(2.0, 8.0, duration.shape)
    scored = np.ones(duration.shape, bool)
    levels = ed_threshold_levels(event, duration, 5.0, 0.8, (0.3, 0.1, 0.02), scored)
    assert realised_shares(levels, scored) == pytest.approx((0.3, 0.1, 0.02), abs=0.005)


def test_fit_ed_threshold_recovers_the_slope_and_puts_five_percent_of_events_below_the_curve():
    rng = np.random.default_rng(11)
    duration = rng.integers(1, 12, 4000).astype(float)
    event = 6.0 * duration**0.8 * np.exp(rng.normal(0.4, 0.5, 4000))
    alpha, gamma = fit_ed_threshold(duration, event)
    assert gamma == pytest.approx(0.8, abs=0.03)
    assert (event < alpha * duration**gamma).mean() == pytest.approx(0.05, abs=0.002)
    assert alpha < 6.0 * np.exp(0.4)


def test_fit_ed_threshold_ignores_cell_days_without_an_event_or_rain_total():
    duration = np.array([0.0, 1.0, 2.0, 3.0, 4.0, 5.0, np.nan, 6.0])
    event = np.array([0.0, 4.0, 9.0, 12.0, 17.0, 20.0, 99.0, np.nan])
    assert fit_ed_threshold(duration, event) == fit_ed_threshold(duration[1:6], event[1:6])


def test_fit_ed_threshold_needs_at_least_a_few_events_with_different_durations():
    with pytest.raises(ValueError, match="events"):
        fit_ed_threshold(np.array([1.0, 1.0, 1.0]), np.array([3.0, 4.0, 5.0]))
    with pytest.raises(ValueError, match="events"):
        fit_ed_threshold(np.array([1.0, 2.0]), np.array([3.0, 4.0]))
