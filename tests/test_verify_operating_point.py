import numpy as np
import pandas as pd
import pytest

from aetherguard.verify.operating_point import allocate, monotone, stratum_curves

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
    chosen = allocate({H6: DENSE, W6: SPARSE}, target_hits=25)
    assert chosen == {H6: 1.0, W6: 3.0}  # lower threshold in the dense stratum, higher in the sparse one
    index = {1.0: 0, 2.0: 1, 3.0: 2, 4.0: 3}
    hits = DENSE["hits"][index[chosen[H6]]] + SPARSE["hits"][index[chosen[W6]]]
    alerts = DENSE["alerts"][index[chosen[H6]]] + SPARSE["alerts"][index[chosen[W6]]]
    assert hits >= 25
    # the uniform solution (one candidate index for both) reaches 25 hits only at t = 2, with 100 alerts
    assert alerts == 80 < 100


def test_allocation_reaches_the_target_hits():
    curves = {H6: DENSE, W6: SPARSE}
    for target in range(0, 28):
        chosen = allocate(curves, target_hits=target)
        hits = sum(c["hits"][list(c["thresholds"]).index(chosen[s])] for s, c in curves.items())
        assert hits >= target


def test_allocation_of_an_unreachable_target_raises():
    with pytest.raises(ValueError):
        allocate({H6: DENSE, W6: SPARSE}, target_hits=28)


def test_stratum_without_events_keeps_v3():
    empty = _curve([40, 30, 20, 10], [0, 0, 0, 0])
    chosen = allocate({H6: DENSE, H7: empty, W6: SPARSE}, target_hits=25)
    assert chosen[H7] is None
    assert chosen[H6] == 1.0 and chosen[W6] == 3.0


def test_stratum_with_only_unscorable_events_keeps_v3():
    risk, region, month, universe, events = _panel()
    curves = stratum_curves(risk, region, month, universe, events, np.array([0.3, 0.5, 0.7]))
    chosen = allocate(curves, target_hits=1)
    assert chosen[H7] is None


def test_allocation_with_no_hittable_events_is_all_none():
    empty = _curve([40, 30, 20, 10], [0, 0, 0, 0])
    assert allocate({H6: empty, W6: empty}, target_hits=0) == {H6: None, W6: None}


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
