import itertools
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from aetherguard.alerts import levels as lv
from aetherguard.live import hardening as H
from aetherguard.live import hardening_dev as D
from aetherguard.live import postrules as pr
from aetherguard.verify.operating_point import Allocation, allocate, candidate_levels, monotone, stratum_curves

from alerts_helpers import CONFIG

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


# ---------------------------------------------------------------------------------------- candidate levels

HIM = lv.Thresholds(watch=1e-5, warning=4e-5, emergency=1e-4, source="test")
GHATS = lv.Thresholds(watch=4e-5, warning=8e-5, emergency=2e-4, source="test")
V3 = {"himalaya": HIM, "western_ghats": GHATS}
RULES = pr.PostRules(None, pr.RainRule({7: 10.0}), (1, 2, 3), hold_window_days=2, blind_hold_days=1)


def _season(risk, regions, start, new_hi=None, acc7=None):
    risk = np.asarray(risk, dtype=np.float64)
    days = [start + timedelta(days=k) for k in range(risk.shape[1])]
    cells = pd.DataFrame({"cell_id": np.arange(len(risk)) + 1, "region": regions, "in_universe": True})
    panel = H.new_panel(cells, days, 4)
    panel.values["risk"][:] = risk
    panel.values["new_hi"][:] = risk if new_hi is None else new_hi
    panel.values["acc_7"][:] = 50.0 if acc7 is None else acc7
    events = pd.DataFrame({"cell_id": pd.Series(dtype="int64"), "date": pd.Series(dtype="datetime64[ns]")})
    return D.Season(2010, panel, 0, events, {region: V3[region] for region in set(regions)})


def _random_season(start, n_days=18, seed=7):
    rng = np.random.default_rng(seed)
    shape = (8, n_days)
    risk = np.exp(rng.uniform(np.log(3e-6), np.log(4e-4), shape))
    risk[rng.random(shape) < 0.05] = np.nan
    regions = ["himalaya"] * 4 + ["western_ghats"] * 4
    return _season(risk, regions, start, new_hi=risk * rng.uniform(1.0, 3.0, shape),
                   acc7=rng.choice([0.0, 50.0], shape))


def _v3_thresholds(changes=()):
    """Every stratum at v3's thresholds, with the values of `changes` ({(level, region, month): threshold}) put in."""
    out = {level: {(region, month): float(v3.as_array()[level - 1]) for region, v3 in V3.items()
                   for month in (6, 7, 8, 9)} for level in (1, 2, 3)}
    for (level, region, month), value in dict(changes).items():
        out[level][(region, month)] = value
    return out


@pytest.mark.parametrize("rules", [None, RULES])
def test_v3_thresholds_everywhere_without_confirmation_give_the_section_11_levels(rules):
    season = _random_season(date(2010, 6, 24))
    expected = D.season_levels(season, "new_hi", CONFIG, rules)
    assert expected.max() == 3 and expected.min() == 0
    got = candidate_levels(season, _v3_thresholds(), CONFIG, rules, False)
    assert got.dtype == expected.dtype and got.tolist() == expected.tolist()


def test_lowering_one_strata_threshold_changes_only_that_region_and_month():
    season = _random_season(date(2010, 6, 24))
    month = np.array([d.month for d in season.panel.days])
    western_ghats = season.region == "western_ghats"
    base = candidate_levels(season, _v3_thresholds(), CONFIG, RULES, False)
    lowered = candidate_levels(season, _v3_thresholds({(2, "western_ghats", 7): 5e-5}), CONFIG, RULES, False)
    changed = lowered != base
    assert changed.any() and (lowered >= base).all()
    assert not changed[~western_ghats].any()
    assert not changed[:, month == 6].any()


def test_october_to_december_and_unlisted_strata_keep_the_v3_thresholds():
    season = _random_season(date(2010, 9, 28), n_days=8, seed=3)
    base = D.season_levels(season, "new_hi", CONFIG, RULES)
    thresholds = _v3_thresholds()
    for level in (1, 2, 3):
        thresholds[level].update({("himalaya", 10): 1e-9, ("western_ghats", 10): 1e-9, ("himalaya", 11): 1e-9,
                                  ("terai", 7): 1e-9, ("western_ghats", 9): None})
    assert candidate_levels(season, thresholds, CONFIG, RULES, False).tolist() == base.tolist()
    assert candidate_levels(season, {1: {}, 2: {}, 3: {}}, CONFIG, RULES, False).tolist() == base.tolist()


def test_a_threshold_below_the_lower_levels_is_raised_to_them_on_each_cell_day():
    july = date(2010, 7, 1)
    emergency_below_warning = _season([[3e-5, 3e-5]], ["himalaya"], july)
    got = candidate_levels(emergency_below_warning, _v3_thresholds({(3, "himalaya", 7): 2e-5}), CONFIG, None, False)
    assert got.tolist() == [[1, 1]]              # Emergency (2e-5) is raised to Warning (4e-5), which 3e-5 does not reach
    watch_above_v3_warning = _season([[4.5e-5, 4.5e-5]], ["himalaya"], july)
    thresholds = _v3_thresholds({(1, "himalaya", 7): 5e-5})
    thresholds[2][("himalaya", 7)] = None        # resolves to v3's Warning (4e-5), which is raised to Watch (5e-5)
    assert candidate_levels(watch_above_v3_warning, thresholds, CONFIG, None, False).tolist() == [[0, 0]]


def test_the_thresholds_of_the_month_apply_to_each_day_of_a_hysteresis_run():
    # Watch is 1e-5 in June and 3e-5 in July for the Himalaya; the risk of 2e-5 is Watch in June, Normal in July
    season = _season([[2e-5] * 4], ["himalaya"], date(2010, 6, 29))
    thresholds = _v3_thresholds({(1, "himalaya", 7): 3e-5, (2, "himalaya", 7): 4e-5})
    got = candidate_levels(season, thresholds, CONFIG, None, False)
    assert got.tolist() == [[1, 1, 1, 0]]        # July 1 holds Watch (one day below), July 2 steps down


def test_the_confirmation_publishes_warning_for_an_emergency_not_preceded_by_warning():
    quiet, loud, warn = 1e-6, 2e-4, 5e-5
    season = _season([[quiet, loud, quiet, quiet, quiet, quiet],     # a lone Emergency
                      [loud, loud, quiet, quiet, quiet, quiet],      # Emergency on the first day, then a second one
                      [warn, loud, quiet, quiet, quiet, quiet]],     # Emergency after a Warning
                     ["himalaya"] * 3, date(2010, 7, 1))
    plain = candidate_levels(season, _v3_thresholds(), CONFIG, None, False)
    confirmed = candidate_levels(season, _v3_thresholds(), CONFIG, None, True)
    assert plain.tolist() == [[0, 3, 3, 2, 2, 1], [3, 3, 3, 2, 2, 1], [2, 3, 3, 2, 2, 1]]
    assert confirmed.tolist() == [[0, 2, 2, 1, 1, 0], [2, 3, 3, 2, 2, 1], [2, 3, 3, 2, 2, 1]]


def test_the_confirmation_looks_at_the_raw_level_before_the_rain_cap():
    # day 1 is capped to Watch by the rain rule, yet day 2's Emergency is confirmed by day 1's raw Warning
    season = _season([[5e-5, 5e-5, 2e-4]], ["himalaya"], date(2010, 7, 1), acc7=[[50.0, 0.0, 50.0]])
    rules = pr.PostRules(None, pr.RainRule({7: 10.0}), (1, 2, 3), hold_window_days=3)
    assert candidate_levels(season, _v3_thresholds(), CONFIG, rules, True)[0, 2] == 3


def test_candidate_levels_need_the_three_levels():
    season = _season([[2e-5]], ["himalaya"], date(2010, 7, 1))
    with pytest.raises(ValueError, match="levels 1, 2 and 3"):
        candidate_levels(season, {1: {}, 2: {}}, CONFIG, None, False)
