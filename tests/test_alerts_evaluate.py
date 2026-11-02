"""Evaluation functions on hand-built alert tables."""
import numpy as np
import pandas as pd
import pytest

from aetherguard import grid
from aetherguard.alerts import evaluate as ev
from alerts_helpers import THRESHOLDS


def table(levels_by_cell: dict[int, list[int]], start="2024-07-01", raw=None, lat=11.5) -> pd.DataFrame:
    rows = []
    for cell, levels in levels_by_cell.items():
        for d, level in enumerate(levels):
            rows.append({"cell_id": cell, "date": pd.Timestamp(start) + pd.Timedelta(days=d), "level": level,
                         "raw_level": (raw or levels_by_cell)[cell][d], "lat": lat, "blind": False,
                         "blind_escalated": False, "confidence": "High"})
    return pd.DataFrame(rows)


def test_event_detection_finds_the_first_watch_day_and_its_lead():
    alerts = table({1: [0, 0, 1, 1, 2, 2, 2, 2], 2: [0, 0, 0, 0, 0, 0, 0, 0], 3: [1, 1, 1, 1, 1, 1, 1, 1]})
    events = pd.DataFrame({"cell_id": [1, 2, 1], "date": ["2024-07-07", "2024-07-07", "2024-07-04"]})
    per, summary = ev.event_detection(alerts, events, lead_days=7)
    by = per.set_index(["cell_id", "date"])
    assert by.loc[(1, pd.Timestamp("2024-07-07")), "lead_days"] == 4          # first Watch on 07-03
    assert by.loc[(1, pd.Timestamp("2024-07-04")), "lead_days"] == 1
    assert not by.loc[(2, pd.Timestamp("2024-07-07")), "detected"]
    assert summary["n_events"] == 3 and summary["n_detected"] == 2 and summary["detection_rate"] == pytest.approx(2 / 3)
    assert summary["median_lead_days"] == 2.5 and summary["n_lead_at_least_1_day"] == 2
    assert summary["detected_by_level"] == {"Watch": 2, "Warning": 1, "Emergency": 0}


def test_event_detection_window_is_limited_to_the_lead_days_and_the_event_day():
    alerts = table({1: [1, 0, 0, 0, 0, 0, 0, 0, 0, 0]})
    miss = ev.event_detection(alerts, pd.DataFrame({"cell_id": [1], "date": ["2024-07-10"]}), lead_days=7)[1]
    hit = ev.event_detection(alerts, pd.DataFrame({"cell_id": [1], "date": ["2024-07-08"]}), lead_days=7)[1]
    after = ev.event_detection(alerts, pd.DataFrame({"cell_id": [1], "date": ["2024-07-01"]}), lead_days=0)[1]
    assert miss["n_detected"] == 0 and hit["n_detected"] == 1 and hit["median_lead_days"] == 7
    assert after["n_detected"] == 1 and after["median_lead_days"] == 0


def test_event_detection_reports_how_much_history_was_available():
    alerts = table({1: [1]})                              # a single-day table: lead can only be 0
    per, summary = ev.event_detection(alerts, pd.DataFrame({"cell_id": [1], "date": ["2024-07-01"]}), 7)
    assert per["days_available"].tolist() == [1] and summary["n_with_history"] == 0 and summary["mean_lead_days"] == 0


def test_event_with_no_rows_is_a_miss_with_zero_days_available():
    per, summary = ev.event_detection(table({1: [1, 1]}), pd.DataFrame({"cell_id": [9], "date": ["2024-07-02"]}), 7)
    assert per["detected"].tolist() == [False] and per["days_available"].tolist() == [0]
    assert summary["median_lead_days"] is None


def test_window_detection_counts_alerts_in_the_cell_or_its_eight_neighbours():
    centre = 20_000_000 + 1000
    neighbour = grid.neighbours(centre)[0]
    far = centre + 50_000
    alerts = table({neighbour: [0, 1, 0], far: [0, 0, 0], 7: [1, 0, 0], 8: [0, 0, 0]})
    out = ev.window_detection(alerts, [centre, far], "2024-07-01", "2024-07-03")
    assert out["n_positive_cells"] == 2 and out["n_detected"] == 1 and out["detection_rate"] == 0.5
    assert out["n_other_cells"] == 3 and out["other_cells_alerted_any_day"] == pytest.approx(2 / 3)
    assert out["other_cell_days_alerted"] == pytest.approx(2 / 9)
    outside = ev.window_detection(alerts, [centre], "2024-07-03", "2024-07-03")
    assert outside["n_detected"] == 0


def test_alerted_area_uses_the_cell_area_and_the_daily_share():
    alerts = table({1: [1, 0], 2: [2, 0], 3: [0, 0], 4: [0, 0]})
    out = ev.alerted_area(alerts)
    one = float(ev.cell_area_km2(11.5))
    assert out["n_days"] == 2 and out["cells_per_day_mean"] == 4
    assert out["watch_share_mean"] == pytest.approx(0.25) and out["watch_share_max"] == 0.5
    assert out["warning_share_mean"] == pytest.approx(0.125)
    assert out["watch_km2_max"] == pytest.approx(2 * one) and out["watch_km2_mean"] == pytest.approx(one)
    assert out["peak_day"] == "2024-07-01"
    assert 25 < one < 35                      # 0.05 degrees is about 5.6 km x 5.4 km


def test_flapping_counts_changes_and_quick_reactivations_and_respects_gaps():
    levels = {1: [1, 0, 1, 0, 0, 0, 0, 1], 2: [1, 1, 1, 1, 1, 1, 1, 1]}
    out = ev.flapping(table(levels), "level", window=3)
    assert out["n_changes"] == 4 and out["n_flaps"] == 1       # 1,0,1 within 3 days; the 4-day gap is not a flap
    assert out["changes_per_1000_cell_days"] == pytest.approx(1000 * 4 / 16)
    gap = table({1: [1, 0]})
    later = table({1: [1]}, start="2024-07-05")
    assert ev.flapping(pd.concat([gap, later]), "level", 3)["n_changes"] == 1     # the date gap is not a change


def test_hysteresis_reduces_flapping_in_the_comparison():
    raw = {1: [1, 0, 1, 0, 1, 0, 1, 0]}
    held = {1: [1, 1, 1, 1, 1, 1, 1, 1]}
    out = ev.flapping_comparison(table(held, raw=raw), 3)
    assert out["with_hysteresis"]["n_flaps"] == 0 and out["without_hysteresis"]["n_flaps"] == 3
    assert out["without_hysteresis"]["n_changes"] == 7


def test_blind_escalations_and_their_coincidence_with_events():
    alerts = table({1: [0, 0, 1, 1, 1], 2: [0, 0, 1, 1, 1], 3: [0, 0, 0, 0, 0]})
    alerts["blind"] = alerts["cell_id"].isin([1, 2]) & (alerts["date"] >= "2024-07-03")
    alerts["blind_escalated"] = alerts["blind"] & (alerts["date"] == "2024-07-03")
    events = pd.DataFrame({"cell_id": [1], "date": ["2024-07-05"]})
    out = ev.blind_escalations(alerts, events, lead_days=7)
    assert out["n_blind"] == 6 and out["n_escalated"] == 2 and out["n_cells_escalated"] == 2
    assert out["n_coinciding_event"] == 1 and out["n_events_covered"] == 1
    assert ev.blind_escalations(alerts, None, 7)["n_coinciding_event"] is None


def test_level_mix_is_weighted():
    alerts = table({1: [0, 1], 2: [2, 0]})
    alerts["confidence"] = ["High", "Degraded", "Insufficient", "High"]
    mix = ev.level_mix(alerts, weights=[1, 1, 2, 4])
    assert mix["level"]["Normal"] == pytest.approx(5 / 8) and mix["level"]["Warning"] == pytest.approx(2 / 8)
    assert mix["confidence"]["High"] == pytest.approx(5 / 8)


def test_universe_operating_view_rates_recall_and_cost_loss():
    n = 100
    universe = pd.DataFrame({"cell_id": np.arange(n), "date": pd.Timestamp("2018-07-01"), "split": "test_2018",
                             "region": "himalaya", "weight": 10.0, "universe_size": 1000, "in_buffer": False,
                             "is_positive_cell_day": False, "risk": 1e-7, "level": 0})
    universe.loc[:9, ["risk", "level"]] = [2e-5, 1]                  # 10% at Watch
    universe.loc[:1, ["risk", "level"]] = [5e-5, 2]                  # 2% at Warning
    positives = pd.DataFrame({"risk": [3e-5, 2e-4, 1e-7], "level": [1, 3, 0]})
    out = ev.universe_operating_view(universe, positives, n_out_of_domain=1, thresholds=THRESHOLDS, ratios=[0.1, 0.02])
    assert out["per_level"]["Watch"]["alerts_per_1000_cell_days"] == pytest.approx(100.0)
    assert out["per_level"]["Warning"]["alerts_per_1000_cell_days"] == pytest.approx(20.0)
    assert out["per_level"]["Watch"]["recall_in_domain"] == pytest.approx(2 / 3)
    assert out["per_level"]["Watch"]["recall_all"] == pytest.approx(2 / 4)
    assert out["base_rate"] == pytest.approx(4 / 1000)
    assert [r["cost_loss"] for r in out["cost_loss"]["ratios"]] == [0.1, 0.02]
    assert out["cost_loss"]["operating_points"]["watch"]["implied_cost_ratio"] == THRESHOLDS.watch


def _layered_table():
    # risk: below Watch / point below Watch with hi above / Watch / blind-raised / held by hysteresis
    t = THRESHOLDS
    risk = [1e-7, 5e-6, 2e-5, 1e-7, 1e-7]
    alerts = pd.DataFrame({"cell_id": [1, 2, 3, 4, 5], "date": pd.Timestamp("2024-07-01"), "risk": risk,
                           "risk_hi": [2e-7, 2e-5, 3e-5, 2e-7, 2e-7], "raw_level": [0, 1, 1, 1, 0],
                           "level": [0, 1, 1, 1, 1], "lat": 11.5})
    return alerts, t


def test_layer_levels_add_one_rule_at_a_time():
    alerts, t = _layered_table()
    layers = ev.layer_levels(alerts, t)
    assert layers["point_risk"].tolist() == [0, 0, 1, 0, 0]
    assert layers["plus_uncertain_high"].tolist() == [0, 1, 1, 0, 0]
    assert layers["plus_blind_rule"].tolist() == [0, 1, 1, 1, 0]
    assert layers["after_hysteresis"].tolist() == [0, 1, 1, 1, 1]
    shares = ev.layer_shares(alerts, t)["Watch"]
    assert [shares[k] for k in ev.LAYERS] == [0.2, 0.4, 0.6, 0.8]


def test_universe_layer_view_reports_each_layer_for_each_level():
    alerts, t = _layered_table()
    universe = alerts.assign(region="himalaya", split="test_2018", weight=10.0, universe_size=1000, in_buffer=False,
                             is_positive_cell_day=False)
    positives = alerts.iloc[[2, 1]]
    view = ev.universe_layer_view(universe, positives, n_out_of_domain=1, thresholds=t)
    watch = view["Watch"]
    assert watch["point_risk"]["alerts_per_1000_cell_days"] == pytest.approx(200.0)
    assert watch["after_hysteresis"]["alerts_per_1000_cell_days"] == pytest.approx(800.0)
    assert watch["point_risk"]["recall_in_domain"] == 0.5 and watch["plus_uncertain_high"]["recall_in_domain"] == 1.0
    assert watch["plus_uncertain_high"]["recall_all"] == pytest.approx(2 / 3)
    assert set(view) == {"Watch", "Warning", "Emergency"}


def test_cause_counts_split_the_combined_codes():
    frame = pd.DataFrame({"confidence_causes": ["", "imd_missing;sources_disagree", "sources_disagree"]})
    assert ev.cause_counts(frame) == {"sources_disagree": 2, "imd_missing": 1}


def test_saturation_reports_days_at_emergency_and_ties_at_the_top_rank():
    days = pd.date_range("2024-07-15", periods=4)
    series = pd.DataFrame({"date": days, "risk": [1e-3, 2e-3, 1e-3, 5e-4], "level": [3, 3, 3, 3],
                           "level_name": ["Emergency"] * 4})
    share = pd.DataFrame({"date": days, "emergency_share": [0.5, 0.6, 0.5, 0.4]})
    out = ev.saturation(series, share)
    assert out["days_at_emergency"] == 4 and out["max_risk_days"] == ["2024-07-16"]
    assert out["risk_rank_by_day"]["2024-07-15"] == 2 and out["risk_rank_by_day"]["2024-07-18"] == 4
    assert out["distinct_risk_values"] == 3 and out["emergency_share_all_cells"]["max"] == 0.6
    tied = ev.saturation(series.assign(risk=[2e-3, 2e-3, 1e-3, 5e-4]))
    assert tied["max_risk_days"] == ["2024-07-15", "2024-07-16"]
    assert ev.emergency_share_by_day(series.assign(date=days)).shape == (4, 2)
