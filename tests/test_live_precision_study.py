"""The precision study (live.precision_study): terrain and per-level rain rules on tiny synthetic panels."""
import json
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from aetherguard.alerts import levels as lv
from aetherguard.live import hardening as H
from aetherguard.live import hardening_dev as D
from aetherguard.live import postrules as pr
from aetherguard.live import precision_study as P

from alerts_helpers import CONFIG

T = lv.Thresholds(watch=1e-5, warning=4e-5, emergency=1e-4, source="test")
DAYS = [date(2010, 6, 1) + timedelta(days=k) for k in range(6)]
BASE = pr.PostRules(None, pr.RainRule({7: 10.0}), (1, 2, 3), hold_window_days=3,
                    hold_windows={1: 2, 2: 1, 3: 1}, blind_hold_days=2)
WARNING_RULE, EMERGENCY_RULE = pr.RainRule({3: 20.0, 7: 40.0}), pr.RainRule({3: 60.0})


def _season(risk, acc=None, universe=None, events=None):
    """One season on a panel of `risk` (cells, days); `acc` maps window -> rain, default 100 mm everywhere."""
    risk = np.asarray(risk, dtype=np.float64)
    cells = pd.DataFrame({"cell_id": np.arange(len(risk)) + 1, "region": "himalaya",
                          "in_universe": np.ones(len(risk), bool) if universe is None else universe})
    panel = H.new_panel(cells, DAYS[:risk.shape[1]], 4)
    panel.values["risk"][:] = risk
    panel.values["new_hi"][:] = risk
    for w in P.RAIN_WINDOWS:
        panel.values[f"acc_{w}"][:] = (acc or {}).get(w, 100.0)
    panel.values["acc_3"][:] = (acc or {}).get(3, 100.0)
    events = pd.DataFrame({"cell_id": pd.Series(dtype="int64"), "date": pd.Series(dtype="datetime64[ns]")}) \
        if events is None else events
    return D.Season(2010, panel, 0, events, {"himalaya": T})


def _levels(season, candidate, flat=None):
    flat = np.zeros(len(season.panel.cells), bool) if flat is None else np.asarray(flat)
    return P.season_candidate_levels(season, CONFIG, BASE, candidate, flat)


def test_the_baseline_levels_equal_the_section_11_levels():
    risk = np.array([[2e-4, 2e-4, 3e-5, 1e-6, 1e-6, 5e-5], [5e-5, 1e-6, 1e-6, 1e-6, 2e-4, 2e-4]])
    acc = {7: np.array([[50.0, 50.0, 0.0, 0.0, 0.0, 50.0], [50.0, 50.0, 50.0, 0.0, 50.0, 50.0]])}
    season = _season(risk, acc)
    assert P.baseline_check([season], CONFIG, BASE)["identical"]
    assert _levels(season, P.Candidate("baseline")).tolist() == D.season_levels(season, "new_hi", CONFIG, BASE).tolist()


def test_rule_r_lowers_emergency_to_warning_and_warning_to_watch_on_their_rain_tests():
    risk = np.full((3, 1), 2e-4)                                      # Emergency point on every cell
    acc = {3: np.array([[70.0], [30.0], [5.0]]), 7: np.array([[70.0], [30.0], [5.0]]), 1: np.array([[1.0], [1.0], [1.0]])}
    season = _season(np.vstack([risk[:1], risk[:1], risk[:1]]), acc)
    out = _levels(season, P.Candidate("R", warning=WARNING_RULE, emergency=EMERGENCY_RULE))
    # 70 mm passes both tests; 30 mm passes only the Warning test; 5 mm / 5 mm fails both but passes none of the section 11
    # rule either (7-day 5 mm < 10 mm), which caps it to Watch first
    assert out[:, 0].tolist() == [3, 2, 1]


def test_rule_r_without_an_emergency_test_leaves_emergency_alone_as_the_spec_words_it():
    season = _season(np.full((2, 1), 2e-4), {3: np.array([[30.0], [30.0]]), 7: np.array([[30.0], [30.0]])})
    assert _levels(season, P.Candidate("R", warning=pr.RainRule({3: 50.0, 7: 50.0})))[:, 0].tolist() == [3, 3]
    assert _levels(season, P.Candidate("R", emergency=pr.RainRule({3: 50.0})))[:, 0].tolist() == [2, 2]


def test_rule_t_caps_flat_cells_at_watch_and_leaves_watch_alone():
    season = _season(np.array([[2e-4], [5e-5], [2e-5]]))
    candidate = P.Candidate("T", "stat_slope_p90", 9.0)
    assert _levels(season, candidate, flat=[True, True, True])[:, 0].tolist() == [1, 1, 1]
    assert _levels(season, candidate, flat=[False, True, False])[:, 0].tolist() == [3, 1, 1]
    assert _levels(season, P.Candidate("baseline"), flat=[True, True, True])[:, 0].tolist() == [3, 2, 1]


def test_a_held_warning_on_a_flat_cell_is_released_the_next_day_but_not_elsewhere():
    risk = np.array([[5e-5, 3.5e-5, 3.5e-5]] * 2)                      # Warning, then raw Watch with the risk above the exit
    season = _season(risk)
    candidate = P.Candidate("T", "stat_slope_p90", 9.0)
    out = _levels(season, candidate, flat=[True, False])
    assert out[0].tolist() == [1, 1, 1] and out[1].tolist() == [2, 2, 2]


def test_a_held_emergency_falls_to_warning_under_rule_r_and_to_watch_without_it():
    risk = np.array([[2e-4, 6e-5, 6e-5, 6e-5]])
    acc = {3: np.array([[100.0, 30.0, 30.0, 30.0]])}                   # day 2: Warning test passes, Emergency test fails
    season = _season(risk, acc)
    with_r = _levels(season, P.Candidate("R", warning=WARNING_RULE, emergency=EMERGENCY_RULE))
    assert with_r[0].tolist() == [3, 2, 2, 2]
    assert _levels(season, P.Candidate("baseline"))[0, :2].tolist() == [3, 3]            # held by the section 11 hysteresis


def test_level_passes_need_every_test_of_the_level():
    base_ok = np.array([True, True, True, False])
    rain = {1: np.zeros(4), 3: np.array([70.0, 30.0, 5.0, 70.0]), 7: np.array([70.0, 30.0, 5.0, 70.0])}
    flat = np.array([False, False, False, False])
    p = P.level_passes(base_ok, rain, flat, P.Candidate("R", warning=WARNING_RULE, emergency=EMERGENCY_RULE))
    assert p[lv.WATCH].tolist() == [True, True, True, False]
    assert p[lv.WARNING].tolist() == [True, True, False, False]
    assert p[lv.EMERGENCY].tolist() == [True, False, False, False]
    t = P.level_passes(base_ok, rain, np.array([True, False, False, False]), P.Candidate("T", "stat_relief", 150.0))
    assert t[lv.WARNING].tolist() == [False, True, True, False]


def test_floors_are_fifth_percentiles_and_vacuous_windows_are_dropped():
    assert P.percentile_floor(np.arange(101.0)) == 5.0
    assert P.percentile_floor([np.nan]) is None
    frame = pd.DataFrame({v: np.arange(101.0) for v in P.TERRAIN_VARIABLES})
    assert P.terrain_floors(frame) == {v: 5.0 for v in P.TERRAIN_VARIABLES}
    # three events at Emergency (1-day rain 0, 3-day 40..60, 7-day 80..120) and one at Warning
    risk = np.array([[2e-4], [2e-4], [2e-4], [5e-5]])
    events = pd.DataFrame({"cell_id": [1, 2, 3, 4], "date": pd.to_datetime([DAYS[0]] * 4)})
    season = _season(risk, events=events)
    for w, values in ((1, [0.0, 0.0, 0.0, 0.0]), (3, [40.0, 50.0, 60.0, 5.0]), (7, [80.0, 100.0, 120.0, 20.0])):
        season.panel.values[f"acc_{w}"][:, 0] = values
    study = P.rain_floor_study([season])
    assert study["Emergency"]["n_positives"] == 3 and study["Warning"]["n_positives"] == 4
    assert study["Emergency"]["vacuous_windows"] == [1] and study["Emergency"]["windows_used"] == [3, 7]
    assert study["Emergency"]["floor_mm"]["3"] == pytest.approx(41.0)
    warning, emergency = P.rain_rules_of(study)
    assert warning.minimum_mm[3] == pytest.approx(5 + 0.15 * 35 - 0.0, abs=2.0) and emergency.minimum_mm[7] == pytest.approx(82.0)


def test_a_rain_floor_study_with_only_zero_floors_is_vacuous():
    season = _season(np.array([[2e-4]]), events=pd.DataFrame({"cell_id": [1], "date": pd.to_datetime([DAYS[0]])}))
    for w in P.RAIN_WINDOWS:
        season.panel.values[f"acc_{w}"][:] = 0.0
    warning, emergency = P.rain_rules_of(P.rain_floor_study([season]))
    assert warning is None and emergency is None
    assert set(P.conditions_from(("stat_relief", 100.0), warning, emergency)) == {"baseline", "T"}


def test_the_terrain_variable_is_the_one_removing_most_negative_alert_cell_days():
    # four universe cells alert at Warning on every day; cell 1 is the event cell; each variable puts a different cell set below its floor
    season = _season(np.full((4, 2), 5e-5), events=pd.DataFrame({"cell_id": [1], "date": pd.to_datetime([DAYS[1]])}))
    table = pd.DataFrame({"stat_slope_p90": [1.0, 1.0, 9.0, 9.0], "stat_slope_mean": [1.0, 1.0, 1.0, 9.0],
                          "stat_relief": [1.0, 9.0, 9.0, 9.0]})
    floors = {v: 5.0 for v in P.TERRAIN_VARIABLES}
    removal = P.terrain_removal([season], [table], floors)
    assert removal["stat_slope_mean"]["negative_alert_cell_days"] == 7           # 8 alert cell-days minus the event cell-day
    assert removal["stat_slope_p90"]["removed"] == 3 and removal["stat_slope_mean"]["removed"] == 5
    assert removal["stat_relief"]["removed"] == 1 and removal["stat_relief"]["positive_removed"] == 1
    assert P.choose_terrain_variable(removal)["variable"] == "stat_slope_mean"
    tied = {v: {"removed_share": 0.5, "floor": 3.0} for v in P.TERRAIN_VARIABLES}
    assert P.choose_terrain_variable(tied)["variable"] == "stat_slope_p90"


def test_paired_change_counts_events_lost_and_a_ci_on_the_removed_cell_days():
    def metrics(per_day, own):
        return {"cell_days": 100, "own_level": np.array(own), "at_least": {1: 10, 2: sum(per_day), 3: 0},
                "per_day": {1: np.zeros(len(per_day)), 2: np.array(per_day), 3: np.zeros(len(per_day))},
                "below_floor_at_least": {1: 0, 2: 0, 3: 0}}
    base = [metrics([10, 12, 11, 13], [3, 2, 2, 0])]
    other = [metrics([6, 7, 6, 8], [3, 1, 2, 0])]
    change = P.paired_change(base, other)
    assert change["Warning"]["events_lost"] == 1 and change["Warning"]["alert_cell_days_removed"] == 19
    assert change["Warning"]["removed_per_day"]["lo"] > 0
    decision = P.adoption_decision(change)
    assert decision["adopt"] and decision["events_lost"] == {"Watch": 0, "Warning": 1, "Emergency": 0}
    flat = P.paired_change(base, [metrics([10, 12, 11, 13], [3, 2, 2, 0])])
    assert flat["Warning"]["removed_per_day"]["lo"] <= 0 <= flat["Warning"]["removed_per_day"]["hi"]
    assert not P.adoption_decision(flat)["adopt"]


def test_the_adoption_criterion_boundaries():
    def change(lost_w, lost_e, lost_watch, lo):
        entry = lambda lost: {"events_lost": lost, "removed_per_day": {"lo": lo}, "alert_cell_days_removed": 5}
        return {"Watch": entry(lost_watch), "Warning": entry(lost_w), "Emergency": entry(lost_e)}
    assert P.adoption_decision(change(1, 1, 1, 0.5))["adopt"]
    assert not P.adoption_decision(change(2, 0, 0, 0.5))["adopt"]
    assert not P.adoption_decision(change(0, 2, 0, 0.5))["adopt"]
    assert not P.adoption_decision(change(0, 0, 2, 0.5))["adopt"]
    assert not P.adoption_decision(change(0, 0, 0, 0.0))["adopt"]
    decisions = {"T": {"adopt": True}, "R": {"adopt": True}, "T+R": {"adopt": False}}
    changes = {"T": {"Warning": {"alert_cell_days_removed": 5}},
               "R": {"Warning": {"alert_cell_days_removed": 9}}, "T+R": {"Warning": {"alert_cell_days_removed": 99}}}
    assert P.recommend(decisions, changes) == {"adoptable": ["T", "R"], "recommended": "R"}
    assert P.recommend({"T": {"adopt": False}}, {"T": {}})["recommended"] is None


def test_evaluate_conditions_reports_every_condition_against_the_baseline():
    risk = np.array([[2e-4, 2e-4, 2e-4]] * 4)
    events = pd.DataFrame({"cell_id": [1], "date": pd.to_datetime([DAYS[2]])})
    season = _season(risk, {3: 30.0}, events=events)
    table = pd.DataFrame({"cell_id": [1, 2, 3, 4], "stat_slope_p90": [30.0, 3.0, 3.0, 3.0],
                          "stat_slope_mean": 10.0, "stat_relief": 500.0})
    candidates = P.conditions_from(("stat_slope_p90", 9.0), WARNING_RULE, EMERGENCY_RULE)
    result = P.evaluate_conditions([season], CONFIG, BASE, candidates, table, 2.0)
    assert set(result["summaries"]) == {"baseline", "T", "R", "T+R"}
    base = result["summaries"]["baseline"]["levels"]["Emergency"]
    assert base["alert_cell_days"] == 12 and base["alert_cell_days_scaled"] == 24.0 and base["events_detected"]["hits"] == 1
    assert result["summaries"]["T"]["levels"]["Warning"]["alert_cell_days"] == 3                 # only the steep cell stays
    assert result["summaries"]["T"]["levels"]["Warning"]["alert_cell_days_below_terrain_floor"] == 0
    assert result["summaries"]["baseline"]["levels"]["Warning"]["alert_cell_days_below_terrain_floor"] == 9
    assert result["changes"]["R"]["Emergency"]["events_lost"] == 1                                 # 30 mm fails the 60 mm test
    assert result["changes"]["R"]["Warning"]["events_lost"] == 0
    assert set(result["decisions"]) == {"T", "R", "T+R"}


def test_candidates_round_trip_and_the_candidate_file_still_loads_as_post_rules(tmp_path):
    candidates = P.conditions_from(("stat_slope_p90", 9.7), WARNING_RULE, EMERGENCY_RULE)
    again = {n: P.Candidate.from_dict(c.to_dict()) for n, c in candidates.items()}
    assert again == candidates
    document = P.candidate_document(candidates, BASE, {"decision": "x"})
    path = tmp_path / "rules.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    assert pr.load_rules(path).to_dict() == BASE.to_dict()
    assert set(document["candidates"]) == {"T", "R", "T+R"}
    with pytest.raises(ValueError):
        P.Candidate("T", "stat_slope_p90", None)
    with pytest.raises(ValueError):
        P.Candidate("T", "stat_elev_mean", 3.0)


def test_positives_on_low_terrain_by_region_source_and_accuracy():
    positives = pd.DataFrame({"cell_id": [1, 2, 3, 4], "date": pd.to_datetime(["2010-07-01"] * 4),
                              "region": ["western_ghats", "western_ghats", "himalaya", "himalaya"],
                              "stat_slope_mean": [2.0, 20.0, 3.0, 25.0], "stat_elev_mean": [30.0, 500.0, 2000.0, 90.0]})
    catalog = pd.DataFrame({"cell_id": [1, 2, 3], "event_date": pd.to_datetime(["2010-07-01"] * 3),
                            "sources": ["hma", "coolr_reports", "hma"], "max_accuracy_km": [5.0, 1.0, 0.0]})
    out = P.positives_on_low_terrain(positives, catalog)
    assert out["all"]["flat"] == 2 and out["all"]["low"] == 2 and out["all"]["flat_or_low"] == 3
    assert out["by_region"]["western_ghats"]["flat_or_low"] == 1 and out["by_region"]["himalaya"]["flat_or_low"] == 2
    assert out["by_source"]["hma"]["n"] == 2 and out["by_source"]["unknown"]["n"] == 1
    assert out["by_accuracy"]["unknown"]["n"] == 1 and out["by_accuracy"][">=5 km"]["n"] == 1
    assert out["by_accuracy"]["0-1 km"]["n"] == 1 and out["by_accuracy"]["1-5 km"]["n"] == 1
    bands = P.elevation_bands(pd.DataFrame({"stat_elev_mean": [10.0, 60.0, 60.0, 3000.0],
                                            "kind": ["positive", "negative", "positive", "negative"]}))
    assert bands[0] == {"band_m": "0-50", "positives": 1, "negatives": 0, "positive_share": 1.0}
    assert bands[1]["positives"] == 1 and bands[1]["negatives"] == 1


def test_elevation_partial_dependence_detects_a_decrease_at_low_elevation():
    rows = pd.DataFrame({"stat_elev_mean": [20.0, 400.0, 1500.0], "region": ["western_ghats", "himalaya", "himalaya"],
                         "kind": "positive"})
    decreasing = lambda frame: 1.0 / (1.0 + np.asarray(frame["stat_elev_mean"], dtype=float) / 100.0) / 10.0
    out = P.elevation_dependence(decreasing, rows)
    assert out["all"]["decreasing_up_to_limit"] and out["all"]["pd_logodds_50m_minus_300m"] > 0
    assert out["all"]["ice_share_50m_above_300m"] == 1.0 and out["all"]["argmax_grid_m"] == 0.0
    assert out["region_himalaya"]["n_rows"] == 2 and out["rows_below_300m"]["n_rows"] == 1
    increasing = lambda frame: 0.001 + 0.0001 * np.asarray(frame["stat_elev_mean"], dtype=float) / 100.0
    assert not P.elevation_dependence(increasing, rows)["all"]["decreasing_up_to_limit"]


def test_sample_rows_are_seeded_and_balanced():
    samples = pd.DataFrame({"kind": ["positive"] * 5 + ["negative"] * 20, "x": np.arange(25)})
    a, b = P.sample_rows(samples, 4, 7), P.sample_rows(samples, 4, 7)
    assert a.equals(b) and (a["kind"] == "positive").sum() == 4 and (a["kind"] == "negative").sum() == 4
    assert (P.sample_rows(samples, 10, 7)["kind"] == "positive").sum() == 5


def test_replay_chain_matches_the_season_machinery_and_lowers_flat_cells():
    risk = np.array([[2e-4, 6e-5, 6e-5], [2e-4, 6e-5, 6e-5]])
    rain = {w: np.full((2, 3), 100.0) for w in P.RAIN_WINDOWS}
    raw = lv.level_from_risk(risk, T).astype(np.int8)
    base_ok = np.ones((2, 3), dtype=bool)
    stamps = pd.DatetimeIndex(pd.to_datetime(DAYS[:3])).to_numpy()
    common = (risk, rain, base_ok)
    args = dict(base_rules=BASE, region=np.array(["himalaya"] * 2), ids=np.array([1, 2]), stamps=stamps,
                thresholds={"himalaya": T}, config=CONFIG)
    base = P.candidate_levels(raw, *common, np.zeros(2, bool), P.Candidate("baseline"), **args)
    assert base[0].tolist() == base[1].tolist() and base[0, 0] == 3
    flat = P.candidate_levels(raw, *common, np.array([True, False]), P.Candidate("T", "stat_relief", 150.0), **args)
    assert flat[0].max() == 1 and (flat[1] == base[1]).all()


def test_replay_days_stop_at_a_gap(tmp_path):
    for d in ("2026-10-09", "2026-10-10", "2026-10-12"):
        (tmp_path / d).mkdir()
        for name in ("alerts.parquet", "features_D0.parquet"):
            (tmp_path / d / name).write_bytes(b"")
    with pytest.raises(ValueError, match="2026-10-11"):
        P.replay_days(tmp_path, date(2026, 10, 9), date(2026, 10, 12))
    assert P.replay_days(tmp_path, date(2026, 10, 8), date(2026, 10, 10)) == [date(2026, 10, 9), date(2026, 10, 10)]


def test_terrain_alternatives_use_their_own_variable_and_floor():
    season = _season(np.full((2, 2), 5e-5))
    table = pd.DataFrame({"cell_id": [1, 2], "stat_slope_p90": [1.0, 20.0], "stat_slope_mean": [20.0, 1.0], "stat_relief": 500.0})
    alternatives = P.terrain_alternatives({"stat_slope_p90": 9.0, "stat_slope_mean": 4.0, "stat_relief": 100.0}, "stat_relief")
    assert set(alternatives) == {"T[stat_slope_p90]", "T[stat_slope_mean]"}
    result = P.evaluate_conditions([season], CONFIG, BASE, {"baseline": P.Candidate("baseline"), **alternatives}, table, 1.0)
    assert result["summaries"]["baseline"]["levels"]["Warning"]["alert_cell_days"] == 4
    for name in alternatives:                                                    # each lowers exactly its own flat cell
        assert result["summaries"][name]["levels"]["Warning"]["alert_cell_days"] == 2
    assert result["changes"]["T[stat_slope_p90]"]["Warning"]["alert_cell_days_removed"] == 2
