import itertools

import numpy as np
import pandas as pd
import pytest

from aetherguard.verify.operating_point import Allocation, allocate, monotone, stratum_curves

H6, H7, W6, W7 = ("himalaya", 6), ("himalaya", 7), ("western_ghats", 6), ("western_ghats", 7)
NAN = np.nan


def _panel():
    risk = np.array(
        [
            [0.9, 0.2, 0.5],
            [0.6, 0.4, NAN],
            [0.1, 0.8, 0.7],
            [0.95, 0.3, 0.6],
        ]
    )
    region = np.array(["himalaya", "himalaya", "western_ghats", "western_ghats"])
    month = np.array([6, 6, 7])
    universe = np.array([True, True, True, False])
    # (0, 0) is listed twice; (1, 2) has NaN risk; cell 3 is outside the alert universe but its events still count.
    events = pd.DataFrame({"row": [0, 1, 0, 3, 3, 2, 1], "col": [0, 0, 0, 0, 1, 2, 2]})
    return risk, region, month, universe, events


def test_stratum_curves_count_hits_per_event_and_alerts_on_universe_cells():
    risk, region, month, universe, events = _panel()
    candidates = np.array([0.3, 0.5, 0.7])
    curves = stratum_curves(risk, region, month, universe, events, candidates)
    assert set(curves) == {H6, H7, W6, W7}
    expected = {  # (hits, alerts) at thresholds 0.3, 0.5, 0.7
        H6: ([2, 2, 1], [3, 2, 1]),
        H7: ([0, 0, 0], [1, 1, 0]),
        W6: ([2, 1, 1], [1, 1, 1]),
        W7: ([1, 1, 1], [1, 1, 1]),
    }
    for stratum, (hits, alerts) in expected.items():
        assert curves[stratum]["thresholds"].tolist() == candidates.tolist()
        assert curves[stratum]["hits"].tolist() == hits, stratum
        assert curves[stratum]["alerts"].tolist() == alerts, stratum


def test_stratum_curves_reject_events_outside_the_panel():
    risk, region, month, universe, _ = _panel()
    for bad in ({"row": [4], "col": [0]}, {"row": [0], "col": [3]}, {"row": [-1], "col": [0]}):
        with pytest.raises(ValueError):
            stratum_curves(risk, region, month, universe, pd.DataFrame(bad), np.array([0.5]))


def test_stratum_curves_reject_unsorted_candidates_and_copy_them():
    risk, region, month, universe, events = _panel()
    for bad in (np.array([0.5, 0.3]), np.array([0.3, np.nan]), np.array([[0.3, 0.5]])):
        with pytest.raises(ValueError):
            stratum_curves(risk, region, month, universe, events, bad)
    candidates = np.array([0.3, 0.5])
    curves = stratum_curves(risk, region, month, universe, events, candidates)
    curves[H6]["thresholds"][0] = 9.0
    assert candidates.tolist() == [0.3, 0.5]
    assert curves[W6]["thresholds"].tolist() == [0.3, 0.5]


def test_stratum_curves_reject_mismatched_shapes():
    risk, region, month, universe, events = _panel()
    with pytest.raises(ValueError):
        stratum_curves(risk, region[:3], month, universe, events, np.array([0.5]))
    with pytest.raises(ValueError):
        stratum_curves(risk, region, month[:2], universe, events, np.array([0.5]))
    with pytest.raises(ValueError):
        stratum_curves(risk, region, month, universe[:3], events, np.array([0.5]))


def _curve(alerts, hits):
    return {"thresholds": np.array([1.0, 2.0, 3.0, 4.0]), "hits": np.array(hits), "alerts": np.array(alerts)}


DENSE = _curve([40, 30, 20, 10], [20, 19, 16, 8])  # each extra alert buys many hits
SPARSE = _curve([100, 70, 40, 10], [7, 6, 5, 1])   # each extra alert buys few hits


def test_allocation_spends_alerts_where_events_are_dense():
    result = allocate({H6: DENSE, W6: SPARSE}, target_hits=25)
    assert result.thresholds == {H6: 1.0, W6: 3.0}  # lower threshold in the dense stratum, higher in the sparse one
    assert (result.hits, result.alerts) == (25, 80)
    # the uniform solution (one candidate index for both) reaches 25 hits only at t = 2, with 100 alerts
    assert result.alerts < 100


def _brute_force(curves, target):
    best = None
    for picks in itertools.product(*(range(len(c["hits"])) for c in curves)):
        hits = sum(c["hits"][i] for c, i in zip(curves, picks))
        alerts = sum(c["alerts"][i] for c, i in zip(curves, picks))
        if hits >= target and (best is None or alerts < best):
            best = alerts
    return best


def test_allocation_is_alert_minimal_on_a_non_concave_curve():
    # Skipping the middle candidates is cheapest here, which a Lagrangian (concave-hull) solver cannot see.
    step = _curve([50, 20, 19, 10], [10, 10, 4, 1])
    other = _curve([30, 25, 20, 10], [8, 5, 3, 1])
    result = allocate({H6: step, W6: other}, target_hits=13)
    assert result.alerts == _brute_force([step, other], 13)


def test_allocation_matches_brute_force_on_random_instances():
    rng = np.random.default_rng(7)
    strata = [H6, H7, W6]
    for _ in range(200):
        curves = {
            s: {
                "thresholds": np.arange(6, dtype=float),
                "hits": np.sort(rng.integers(0, 12, 6))[::-1],
                "alerts": np.sort(rng.integers(0, 60, 6))[::-1],
            }
            for s in strata
        }
        hittable = {s: c for s, c in curves.items() if c["hits"].max() > 0}
        target = int(rng.integers(0, sum(c["hits"].max() for c in hittable.values()) + 1))
        result = allocate(curves, target)
        assert result.alerts == _brute_force(list(hittable.values()), target)
        assert result.hits >= target
        picked = {s: int(t) for s, t in result.thresholds.items() if t is not None}
        assert set(picked) == set(hittable)
        assert result.hits == sum(curves[s]["hits"][i] for s, i in picked.items())
        assert result.alerts == sum(curves[s]["alerts"][i] for s, i in picked.items())


def test_allocation_breaks_ties_towards_higher_thresholds():
    flat = _curve([10, 10, 10, 10], [5, 5, 5, 5])
    assert allocate({H6: flat}, target_hits=5).thresholds == {H6: 4.0}


def test_allocation_of_target_zero_alerts_as_little_as_possible():
    result = allocate({H6: DENSE, W6: SPARSE}, target_hits=0)
    assert result.thresholds == {H6: 4.0, W6: 4.0}
    assert (result.hits, result.alerts) == (9, 20)


def test_allocation_of_an_unreachable_target_raises():
    with pytest.raises(ValueError):
        allocate({H6: DENSE, W6: SPARSE}, target_hits=28)


def test_stratum_without_events_keeps_v3():
    empty = _curve([40, 30, 20, 10], [0, 0, 0, 0])
    result = allocate({H6: DENSE, H7: empty, W6: SPARSE}, target_hits=25)
    assert result.thresholds == {H6: 1.0, H7: None, W6: 3.0}
    assert (result.hits, result.alerts) == (25, 80)  # only the strata with a threshold are counted


def test_stratum_with_only_unscorable_events_keeps_v3():
    risk, region, month, universe, events = _panel()
    curves = stratum_curves(risk, region, month, universe, events, np.array([0.3, 0.5, 0.7]))
    assert allocate(curves, target_hits=1).thresholds[H7] is None


def test_allocation_with_no_hittable_events_is_all_none():
    empty = _curve([40, 30, 20, 10], [0, 0, 0, 0])
    assert allocate({H6: empty, W6: empty}, target_hits=0) == Allocation({H6: None, W6: None}, 0, 0)
    with pytest.raises(ValueError):
        allocate({H6: empty}, target_hits=1)


def test_allocation_rejects_a_negative_target_and_ragged_curves():
    with pytest.raises(ValueError):
        allocate({H6: DENSE}, target_hits=-1)
    with pytest.raises(ValueError):
        allocate({H6: {"thresholds": np.arange(3.0), "hits": np.arange(4), "alerts": np.arange(4)}}, target_hits=0)


def test_monotone_rejects_nan_thresholds():
    with pytest.raises(ValueError):
        monotone({1: {H6: 0.1}, 2: {H6: np.nan}, 3: {H6: 0.3}})


def test_monotone_raises_warning_to_watch_and_emergency_to_warning():
    by_level = {
        1: {H6: 0.5, W6: 0.2},
        2: {H6: 0.4, W6: 0.6},
        3: {H6: 0.3, W6: 0.5},
    }
    out = monotone(by_level)
    assert out == {1: {H6: 0.5, W6: 0.2}, 2: {H6: 0.5, W6: 0.6}, 3: {H6: 0.5, W6: 0.6}}
    assert by_level[2][H6] == 0.4  # the input is not modified


def test_monotone_leaves_none_and_skips_it_when_comparing():
    by_level = {1: {H6: 0.5, W6: None}, 2: {H6: None, W6: 0.4}, 3: {H6: 0.2, W6: 0.3}}
    out = monotone(by_level)
    assert out[1] == {H6: 0.5, W6: None}
    assert out[2] == {H6: None, W6: 0.4}
    assert out[3] == {H6: 0.5, W6: 0.4}


def test_monotone_rejects_missing_levels_or_mismatched_strata():
    with pytest.raises(ValueError):
        monotone({1: {H6: 0.1}, 2: {H6: 0.2}})
    with pytest.raises(ValueError):
        monotone({1: {H6: 0.1}, 2: {H6: 0.2}, 3: {W6: 0.3}})
