import math
from datetime import date

import numpy as np
import pandas as pd
import pytest

from aetherguard.live.backtest import BOOTSTRAP
from aetherguard.verify.matching import Match
from aetherguard.verify.scores import bootstrap_scores, level_scores, paired_change

# 4 cells x 5 days; 8 cell-days are Warning or above (level >= 2).
LEVELS = np.array(
    [
        [0, 2, 2, 3, 0],
        [0, 2, 3, 0, 0],
        [0, 0, 2, 3, 0],
        [0, 0, 0, 2, 0],
    ],
    dtype=np.int8,
)
SCORED = np.ones(LEVELS.shape, dtype=bool)
SCORED[3, 0] = False
LEVELS_HELD_ON_UNSCORED = LEVELS.copy()
LEVELS_HELD_ON_UNSCORED[3, 0] = 1

VERIFIED = np.zeros(LEVELS.shape, dtype=bool)
VERIFIED[[0, 1, 2], [1, 2, 3]] = True  # three of the eight alerts have an event nearby
VERIFIED[3, 0] = True  # ... and so does a cell-day that is not an alert

EVENT_DAY = np.array([1, 2, 3, 0])
EVENTS = pd.DataFrame({"cell_id": [1, 2, 3, 4], "date": [date(2018, 7, 2 + d) for d in EVENT_DAY]})
MATCH = Match(np.array([3, 1, 0, -1], dtype=np.int8), VERIFIED, EVENTS, 0, EVENT_DAY)
EMPTY_MATCH = Match(np.zeros(0, dtype=np.int8), np.zeros(LEVELS.shape, dtype=bool), EVENTS.iloc[:0], 0, np.zeros(0, dtype=int))


def test_precision_is_verified_alert_cell_days_over_alert_cell_days():
    s = level_scores(LEVELS, SCORED, MATCH, min_level=2)
    assert (s["alert_cell_days"], s["verified_alert_cell_days"]) == (8, 3) and s["precision"] == pytest.approx(3 / 8)


def test_pod_counts_events_with_a_level_at_or_above():
    s = level_scores(LEVELS, SCORED, MATCH, min_level=1)  # event levels [3, 1, 0, -1]
    assert (s["events"], s["hits"]) == (4, 2) and s["pod"] == pytest.approx(0.5)


def test_an_unscored_held_alert_still_counts():
    s = level_scores(LEVELS_HELD_ON_UNSCORED, SCORED, MATCH, min_level=1)
    assert s["alert_cell_days"] == 9


def test_alert_share_and_yield_use_scored_cell_days_and_hits():
    s = level_scores(LEVELS, SCORED, MATCH, min_level=1)
    assert s["alert_share"] == pytest.approx(8 / 19)
    assert s["events_per_1000_alert_cell_days"] == pytest.approx(1000 * 2 / 8)


def test_no_events_gives_nan_pod_not_zero():
    assert math.isnan(level_scores(LEVELS, SCORED, EMPTY_MATCH, 1)["pod"])


def test_no_alerts_gives_nan_precision_not_zero():
    s = level_scores(LEVELS, SCORED, MATCH, min_level=4)
    assert s["alert_cell_days"] == 0 and math.isnan(s["precision"]) and math.isnan(s["events_per_1000_alert_cell_days"])


def test_a_shape_mismatch_is_rejected():
    with pytest.raises(ValueError, match="share one shape"):
        level_scores(LEVELS[:, :4], SCORED[:, :4], MATCH, 1)


def test_bootstrap_is_seeded_and_brackets_the_point():
    a, b = bootstrap_scores(LEVELS, SCORED, MATCH, 1), bootstrap_scores(LEVELS, SCORED, MATCH, 1)
    assert a == b and a["precision_ci"][0] <= a["precision"] <= a["precision_ci"][1]
    assert a["pod_ci"][0] <= a["pod"] <= a["pod_ci"][1]
    assert a["alert_cell_days_ci"][0] <= a["alert_cell_days"] <= a["alert_cell_days_ci"][1]
    assert 0 < a["precision_ci_replicates"] <= BOOTSTRAP["n"]


def test_bootstrap_seed_changes_the_interval():
    base = {"n": 3, "level": 0.95}
    a = bootstrap_scores(LEVELS, SCORED, MATCH, 1, {**base, "seed": 1})
    b = bootstrap_scores(LEVELS, SCORED, MATCH, 1, {**base, "seed": 2})
    assert a["pod_ci"] != b["pod_ci"] or a["precision_ci"] != b["precision_ci"]


def test_bootstrap_intervals_are_nan_when_the_denominator_is_empty():
    s = bootstrap_scores(LEVELS, SCORED, EMPTY_MATCH, 1)
    assert all(math.isnan(x) for x in s["pod_ci"])
    s = bootstrap_scores(LEVELS, SCORED, MATCH, 4)
    assert all(math.isnan(x) for x in s["precision_ci"]) and s["alert_cell_days_ci"] == [0.0, 0.0]
    assert s["precision_ci_replicates"] == 0


def test_bootstrap_with_no_days_has_nan_day_intervals():
    none = np.zeros((4, 0), dtype=np.int8)
    m = Match(np.zeros(0, dtype=np.int8), np.zeros((4, 0), dtype=bool), EVENTS.iloc[:0], 0, np.zeros(0, dtype=int))
    s = bootstrap_scores(none, none.astype(bool), m, 1)
    assert math.isnan(s["precision_ci"][0]) and math.isnan(s["alert_cell_days_ci"][1]) and math.isnan(s["alert_share"])
    assert s["precision_ci_replicates"] == 0


def test_paired_change_of_identical_levels_is_zero():
    c = paired_change(LEVELS, LEVELS, SCORED, MATCH, MATCH, 2)
    assert c["alert_cell_days_change"] == 0 and c["alert_cell_days_change_ci"] == [0, 0]
    assert c["hits_change"] == 0 and c["hits_change_ci"] == [0, 0]
    assert c["precision_change"] == 0 and c["precision_change_ci"] == [0, 0]


def test_paired_change_against_silence_counts_every_alert_and_hit():
    none = np.zeros_like(LEVELS)
    silent = Match(np.full(4, 0, dtype=np.int8), VERIFIED, EVENTS, 0, EVENT_DAY)
    c = paired_change(LEVELS, none, SCORED, MATCH, silent, 1)
    assert (c["alert_cell_days_change"], c["hits_change"]) == (8, 2)
    assert math.isnan(c["precision_change"]) and all(math.isnan(x) for x in c["precision_change_ci"])
    lo, hi = c["alert_cell_days_change_ci"]
    assert lo <= 8 <= hi and lo >= 0
    lo, hi = c["hits_change_ci"]
    assert lo <= 2 <= hi


def test_paired_change_in_precision_brackets_the_point():
    sparse = LEVELS.copy()
    sparse[3, 3] = 0
    sparse[0, 2] = 0
    c = paired_change(LEVELS, sparse, SCORED, MATCH, MATCH, 2)
    assert c["alert_cell_days_change"] == 2
    lo, hi = c["precision_change_ci"]
    assert lo <= c["precision_change"] <= hi


def test_paired_change_is_seeded():
    other = np.where(LEVELS == 3, 1, LEVELS).astype(np.int8)
    assert paired_change(LEVELS, other, SCORED, MATCH, MATCH, 2) == paired_change(LEVELS, other, SCORED, MATCH, MATCH, 2)


def test_paired_change_needs_the_same_events_for_both_sides():
    other = Match(MATCH.event_level, VERIFIED, EVENTS, 0, np.array([0, 0, 0, 0]))
    with pytest.raises(ValueError, match="same events"):
        paired_change(LEVELS, LEVELS, SCORED, MATCH, other, 2)
    bare = Match(MATCH.event_level, VERIFIED, EVENTS, 0)
    with pytest.raises(ValueError, match="event_day"):
        paired_change(LEVELS, LEVELS, SCORED, bare, bare, 2)
