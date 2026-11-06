import itertools
import json
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from aetherguard import grid
from aetherguard.alerts import levels as lv
from aetherguard.hazard.jsonio import jsonable
from aetherguard.live import hardening as H
from aetherguard.live import hardening_dev as D
from aetherguard.live import postrules as pr
from aetherguard.verify import operating_point as op
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


# ------------------------------------------------------------------------------- fit on development seasons

def _fit_season():
    """Four days over a June/July boundary, four cells. Himalaya June, Himalaya July and Western Ghats June hold events; Western
    Ghats July holds none. Cell 4 is outside the alert universe: its 2e-4 alerts nowhere and holds no event."""
    low = 1e-6
    risk = [[2e-4, low, 1.5e-4, low],
            [low, low, low, 5e-5],
            [low, 9e-5, low, low],
            [2e-4, low, low, low]]
    season = _season(risk, ["himalaya", "himalaya", "western_ghats", "western_ghats"], date(2010, 6, 29))
    season.panel.cells["in_universe"] = [True, True, True, False]
    season.events = pd.DataFrame({"cell_id": [1, 1, 2, 3, 1],
                                  "date": pd.to_datetime(["2010-06-29", "2010-07-01", "2010-07-02", "2010-06-30", "2010-06-29"])})
    return season


GRID = np.array([1e-5, 3e-5, 1e-4])


def _load(*seasons):
    return lambda: iter(seasons)


def test_fit_targets_the_v3_point_hits_of_the_active_strata_and_keeps_inactive_strata_at_v3():
    fit = op.fit(_load(_fit_season()), GRID)
    assert fit.targets == {1: 4, 2: 4, 3: 2}
    assert fit.v3_point == {1: {"hits": 4, "alerts": 4}, 2: {"hits": 4, "alerts": 4}, 3: {"hits": 2, "alerts": 2}}
    assert {level: (a.hits, a.alerts) for level, a in fit.allocations.items()} == {1: (4, 4), 2: (4, 4), 3: (2, 2)}
    assert fit.thresholds == {
        1: {H6: 1e-4, H7: 3e-5, W6: 3e-5, W7: None},
        2: {H6: 1e-4, H7: 3e-5, W6: 3e-5, W7: None},
        3: {H6: 1e-4, H7: 1e-4, W6: 1e-4, W7: None},
    }
    assert fit.grid.tolist() == GRID.tolist()


def test_fit_adds_the_curves_of_all_seasons_and_makes_the_thresholds_monotone():
    one = op.fit(_load(_fit_season()), GRID)
    two = op.fit(_load(_fit_season(), _fit_season()), GRID)
    assert two.targets == {level: 2 * target for level, target in one.targets.items()}
    assert two.thresholds == one.thresholds
    for stratum in (H6, H7, W6):
        values = [two.thresholds[level][stratum] for level in (1, 2, 3)]
        assert values == sorted(values)


def test_candidate_grid_is_the_risk_quantiles_of_the_scored_universe_cell_days():
    low = 1e-6
    values = np.array([2e-4, low, 1.5e-4, low, low, low, low, 5e-5, low, 9e-5, low, low])   # cells 1-3, not cell 4
    grid_ = op.candidate_grid(_load(_fit_season()))
    assert len(grid_) == 200
    assert grid_.tolist() == np.quantile(values, op.QUANTILES).tolist()
    assert op.QUANTILES[0] == 0.5 and op.QUANTILES[-1] == 0.999


def test_development_table_counts_cell_exact_hits_and_universe_alerts_over_seasons():
    everywhere = {"two": lambda s: np.full(s.panel["risk"].shape, 2, dtype=np.int8),
                  "one": lambda s: np.ones(s.panel["risk"].shape, dtype=np.int8)}
    table = op.development_table(_load(_fit_season(), _fit_season()), everywhere)
    # 4 distinct events a season (the repeated one counts once); 3 universe cells x 4 days of alerts a season
    assert table["two"] == {1: {"events": 8, "hits": 8, "alerts": 24}, 2: {"events": 8, "hits": 8, "alerts": 24},
                            3: {"events": 8, "hits": 0, "alerts": 0}}
    assert table["one"][2] == {"events": 8, "hits": 0, "alerts": 0}


def test_development_table_reads_the_level_on_the_event_day_in_the_events_own_cell():
    levels = np.zeros((4, 4), dtype=np.int8)
    levels[0, 0], levels[1, 3] = 3, 2           # events (cell 1, 29 June) and (cell 2, 2 July); (cell 1, 1 July) sits at 0
    levels[2, 0] = 3                            # a level in another cell on another day is no hit
    table = op.development_table(_load(_fit_season()), {"m": lambda s: levels})
    assert [table["m"][k]["hits"] for k in (1, 2, 3)] == [2, 2, 1]


# ---------------------------------------------------------------------------------------------- selection

def _dev(hits, alerts):
    return {level: {"events": 100, "hits": h, "alerts": a} for level, h, a in zip((1, 2, 3), hits, alerts)}


def test_selection_takes_c2_only_with_fewer_warning_alerts_at_equal_or_higher_detection_everywhere():
    c1 = _dev((90, 80, 60), (1000, 500, 200))
    assert op.select({"C1": c1, "C2": _dev((90, 80, 60), (1000, 480, 150))}) == "C2"       # same detection, fewer alerts
    assert op.select({"C1": c1, "C2": _dev((91, 80, 61), (1000, 499, 150))}) == "C2"       # higher detection is fine
    assert op.select({"C1": c1, "C2": _dev((90, 80, 59), (1000, 400, 100))}) == "C1"       # one event lost at Emergency
    assert op.select({"C1": c1, "C2": _dev((89, 80, 60), (1000, 400, 100))}) == "C1"       # ... at Watch+
    assert op.select({"C1": c1, "C2": _dev((90, 79, 60), (1000, 400, 100))}) == "C1"       # ... at Warning+


def test_selection_ties_go_to_c1_and_more_warning_alerts_never_win():
    c1 = _dev((90, 80, 60), (1000, 500, 200))
    assert op.select({"C1": c1, "C2": _dev((90, 80, 60), (900, 500, 100))}) == "C1"        # equal Warning+ alerts
    assert op.select({"C1": c1, "C2": _dev((95, 85, 65), (1000, 501, 200))}) == "C1"       # more Warning+ alerts
    assert op.select({"C1": c1, "C2": c1}) == "C1"


# ------------------------------------------------------------------------------------------- the decision

def _scores(slides):
    return {level: {"group_hits": n, "groups": 87} for level, n in zip((1, 2, 3), slides)}


def _evaluation(lost=(0, 0, 0), change=-1000, ci=(-1500.0, -500.0), exact_lost=None, exact_ci=None):
    v3 = (85, 79, 73)
    out = {}
    for name, loss, interval in (("tolerant", lost, ci), ("cell_exact", exact_lost or lost, exact_ci or ci)):
        out[name] = {
            "v3": _scores(v3),
            "candidate": _scores(tuple(n - x for n, x in zip(v3, loss))),
            "change": {level: {"alert_cell_days_change": change if level == 2 else 0,
                               "alert_cell_days_change_ci": list(interval)} for level in (1, 2, 3)},
        }
    return out


def _results(decision):
    return {(c["tolerance"], c["condition"]): c["passed"] for c in decision["conditions"]}


def test_decision_passes_when_every_condition_holds_in_both_tolerances():
    decision = op.decide(_evaluation())
    assert decision["adopt"] is True
    assert all(_results(decision).values()) and len(decision["conditions"]) == 8


def test_decision_allows_one_slide_lost_at_warning_and_emergency_and_two_at_watch():
    assert op.decide(_evaluation(lost=(2, 1, 1)))["adopt"] is True
    assert op.decide(_evaluation(lost=(0, 0, 0), exact_lost=(2, 1, 1)))["adopt"] is True
    assert op.decide(_evaluation(lost=(-3, -2, -1)))["adopt"] is True            # more slides than v3 is fine


@pytest.mark.parametrize("lost, failing", [((3, 0, 0), "watch_detection"), ((0, 2, 0), "warning_detection"),
                                           ((0, 0, 2), "emergency_detection")])
def test_decision_fails_one_slide_beyond_the_allowance_in_either_tolerance(lost, failing):
    for evaluation, tolerance in ((_evaluation(lost=lost, exact_lost=(0, 0, 0)), "tolerant"), (_evaluation(exact_lost=lost), "cell_exact")):
        decision = op.decide(evaluation)
        assert decision["adopt"] is False
        assert [key for key, passed in _results(decision).items() if not passed] == [(tolerance, failing)]


@pytest.mark.parametrize("change, ci", [(-1000, (-1500.0, 0.0)),        # the interval touches 0
                                        (-1000, (-1500.0, 20.0)),       # the interval contains 0
                                        (50, (20.0, 80.0)),             # an increase, interval excluding 0
                                        (0, (-10.0, -5.0)),             # no reduction
                                        (-1000, (float("nan"), float("nan")))])
def test_decision_requires_a_reduction_whose_interval_excludes_zero(change, ci):
    decision = op.decide(_evaluation(change=change, ci=ci))
    assert decision["adopt"] is False
    assert _results(decision)[("tolerant", "warning_burden")] is False


def test_decision_fails_when_only_the_cell_exact_burden_interval_touches_zero():
    decision = op.decide(_evaluation(exact_ci=(-1500.0, 0.0)))
    assert decision["adopt"] is False
    assert [key for key, passed in _results(decision).items() if not passed] == [("cell_exact", "warning_burden")]


def test_decision_records_the_numbers_behind_each_condition():
    decision = op.decide(_evaluation(lost=(0, 2, 1), change=-700, ci=(-900.0, -100.0)))
    by_key = {(c["tolerance"], c["condition"]): c for c in decision["conditions"]}
    warning = by_key[("tolerant", "warning_detection")]
    assert (warning["v3"], warning["candidate"], warning["lost"], warning["allowed"], warning["passed"]) == (79, 77, 2, 1, False)
    burden = by_key[("cell_exact", "warning_burden")]
    assert (burden["change"], burden["ci"], burden["passed"]) == (-700, [-900.0, -100.0], True)
    assert decision["failed"] == ["tolerant: warning_detection", "cell_exact: warning_detection"]


# ----------------------------------------------------------------------------- the single held-out look

A_CELL = int(grid.latlon_to_cell(30.025, 78.025))
CELLS = np.array([A_CELL, A_CELL + 1, A_CELL + 20])           # a cell, its neighbour 4.8 km away, one 96 km away
BOOT = {"n": 60, "seed": 5, "level": 0.95}


def _pool():
    days = [date(2019, 7, 1) + timedelta(days=k) for k in range(5)]
    v3 = np.zeros((3, 5), dtype=np.int8)
    v3[0, 1], v3[1, 1], v3[2, 3], v3[0, 3] = 2, 2, 3, 1                       # Warning+ on 3 cell-days
    candidate = np.zeros((3, 5), dtype=np.int8)
    candidate[0, 1], candidate[2, 3] = 2, 3                                   # the neighbour's alert is dropped
    events = pd.DataFrame({"cell_id": [A_CELL, A_CELL + 1, A_CELL + 20],
                           "date": pd.to_datetime(["2019-07-02", "2019-07-02", "2019-07-04"])})
    return op.HeldOut(CELLS, days, np.ones((3, 5), dtype=bool), v3, candidate, events, 1)


GOOD = {"hits": 3, "alert_cell_days": 3, "group_hits": 2, "groups": 2}


def test_score_heldout_counts_slides_burden_and_the_paired_change_per_tolerance_and_level():
    scores = op.score_heldout(_pool(), BOOT)
    assert scores["events"] == 3 and scores["slides"] == 2 and scores["events_outside_panel_days"] == 1
    for tolerance in ("tolerant", "cell_exact"):
        entry = scores[tolerance]
        assert entry["v3"][2]["group_hits"] == 2 and entry["candidate"][2]["group_hits"] == 2
        assert entry["v3"][2]["alert_cell_days"] == 3 and entry["candidate"][2]["alert_cell_days"] == 2
        assert entry["change"][2]["alert_cell_days_change"] == -1
        assert len(entry["change"][2]["alert_cell_days_change_ci"]) == 2
    assert scores["cell_exact"]["v3"][2]["hits"] == 3 and scores["cell_exact"]["candidate"][2]["hits"] == 2


def test_score_heldout_stops_when_v3_does_not_reproduce_the_published_numbers():
    assert op.score_heldout(_pool(), BOOT, {t: {2: GOOD} for t in ("tolerant", "cell_exact")})["slides"] == 2
    with pytest.raises(ValueError, match="differ from the published"):
        op.score_heldout(_pool(), BOOT, {"tolerant": {2: {**GOOD, "hits": 4}}})


def test_the_held_out_look_happens_once(tmp_path):
    path = tmp_path / "w2_heldout.json"
    built = []

    def build():
        built.append(1)
        return _pool()

    result = op.evaluate_once(path, build, BOOT)
    assert built == [1] and path.is_file()
    assert result["decision"]["adopt"] in (True, False) and result["scores"]["slides"] == 2
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["decision"]["adopt"] == result["decision"]["adopt"]
    with pytest.raises(FileExistsError, match="w2_heldout.json"):
        op.evaluate_once(path, build, BOOT)
    assert built == [1]                           # the second call did not even load the held-out panels
    assert json.loads(path.read_text(encoding="utf-8")) == stored


def test_a_failed_look_leaves_no_result_file_and_may_be_repeated(tmp_path):
    path = tmp_path / "w2_heldout.json"
    with pytest.raises(ValueError):
        op.evaluate_once(path, _pool, BOOT, {"tolerant": {2: {**GOOD, "hits": 9}}})
    assert not path.exists()
    assert op.evaluate_once(path, _pool, BOOT)["scores"]["slides"] == 2


# ---------------------------------------------------------------------------------------------- the report

def _document(tmp_path):
    season = _fit_season()
    fit = op.fit(_load(season), GRID)
    models = {"v3": lambda s: D.season_levels(s, "new_hi", CONFIG, None),
              "C1": lambda s: candidate_levels(s, fit.thresholds, CONFIG, None, False),
              "C2": lambda s: candidate_levels(s, fit.thresholds, CONFIG, None, True)}
    table = op.development_table(_load(season), models)
    selected = op.select({name: table[name] for name in ("C1", "C2")})
    heldout = op.evaluate_once(tmp_path / "w2_heldout.json", _pool, BOOT)
    return fit, table, selected, heldout


def test_the_report_names_the_thresholds_tables_decision_and_caveats(tmp_path):
    fit, table, selected, heldout = _document(tmp_path)
    result = op.report_result(fit, table, selected, heldout, V3)
    text = op.markdown(result)
    for needle in ("Himalaya", "Western Ghats", "C1", "Adopt", "relative", "chance floor", "Warning+", "Emergency"):
        assert needle.lower() in text.lower(), needle
    json.dumps(jsonable(result), allow_nan=False)          # strict JSON, no stray objects


def test_the_thresholds_document_lists_both_candidates_and_the_selection(tmp_path):
    fit, _, selected, _ = _document(tmp_path)
    out = op.thresholds_document(fit, selected, V3)
    assert out["selected"] == selected and set(out["candidates"]) == {"C1", "C2"}
    assert out["candidates"]["C2"]["confirm_emergency"] is True and out["candidates"]["C1"]["confirm_emergency"] is False
    assert out["candidates"]["C1"]["thresholds"]["warning"]["himalaya"]["6"] == 1e-4
    assert out["candidates"]["C1"]["thresholds"]["warning"]["western_ghats"]["7"] is None
    assert out["v3"]["himalaya"]["watch"] == HIM.watch


# --------------------------------------------------------------------------- the published references

def _entry(hits, alerts, group_hits, events=92, groups=87):
    return {"events": events, "hits": hits, "alert_cell_days": alerts, "group_hits": group_hits, "groups": groups, "pod": 0.9}


def test_published_v3_reads_the_pooled_numbers_by_tolerance_and_integer_level(tmp_path):
    models = {"v3": {t: {"1": _entry(90, 300, 85), "2": _entry(84, 200, 79), "3": _entry(78, 100, 73)} for t in ("tolerant", "cell_exact")}}
    path = tmp_path / "w1.json"
    path.write_text(json.dumps({"sets": {"POOLED": {"models": models}, "S2018": {"models": {}}}}), encoding="utf-8")
    published = op.published_v3(path)
    assert set(published) == {"tolerant", "cell_exact"} and set(published["tolerant"]) == {1, 2, 3}
    assert published["cell_exact"][2] == {"events": 92, "hits": 84, "alert_cell_days": 200, "group_hits": 79, "groups": 87}


def test_development_v3_must_reproduce_the_baseline_report(tmp_path):
    cell_exact = {str(k): {"events": 10, "hits": h, "alert_cell_days": a} for k, h, a in ((1, 9, 90), (2, 7, 50), (3, 4, 20))}
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps({"sets": {"development": {"models": {"v3": {"cell_exact": cell_exact}}}}}), encoding="utf-8")
    table = {"v3": _dev((9, 7, 4), (90, 50, 20))}
    for level in table["v3"].values():
        level["events"] = 10
    op._check_development_v3(table, path)
    table["v3"][2]["alerts"] = 51
    with pytest.raises(ValueError, match="differ from the published"):
        op._check_development_v3(table, path)


def test_run_refuses_when_the_committed_report_exists(tmp_path, monkeypatch):
    """A fresh clone has no data/ result file, but the committed report still blocks a second look."""
    from aetherguard.verify import operating_point as op
    monkeypatch.setattr(op, "heldout_result_path", lambda: tmp_path / "absent.json")
    monkeypatch.setattr(op.live_run, "load_run_config", lambda: {})
    (tmp_path / f"{op.REPORT_STEM}.json").write_text("{}", encoding="utf-8")
    with pytest.raises(FileExistsError):
        op.run(tmp_path, say=lambda *_: None)
