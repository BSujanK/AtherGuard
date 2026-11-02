import numpy as np
import pandas as pd
import pytest

from aetherguard.cases import openmeteo as om
from aetherguard.cases import score
from aetherguard.grid import ID_STRIDE, cell_center, latlon_to_cell

THRESHOLDS = {"watch": 0.25, "warning": 0.5, "emergency": 0.8}


def dummy_scorer(frame):
    """Monotone in rain_acc_3: risk = acc3 / 400 (clipped), a band of +-20% for the interval."""
    risk = np.clip(frame["rain_acc_3"].to_numpy(np.float64) / 400.0, 0, 1)
    return pd.DataFrame({"risk": risk, "risk_lo": risk * 0.8, "risk_hi": np.minimum(risk * 1.2, 1.0), "risk_per_100k": 1e5 * risk})


class ObjectScorer:
    def score_frame(self, frame):
        return dummy_scorer(frame)


def cell(lat_index, lon_index):
    return lat_index * ID_STRIDE + lon_index


def kerala_frame():
    """A 5 x 5 block of cells (lat index 2030-2034, lon index 5120-5124) for 10 days; a storm over the centre cell."""
    cells = [cell(a, b) for a in range(2030, 2035) for b in range(5120, 5125)]
    days = pd.date_range("2018-08-01", periods=10)
    acc3 = pd.DataFrame(0.0, index=days, columns=cells)
    centre = cell(2032, 5122)
    acc3.loc["2018-08-04", centre] = 120.0          # 0.30 -> Watch
    acc3.loc["2018-08-05", centre] = 200.0          # 0.50 -> Warning
    acc3.loc["2018-08-06", centre] = 340.0          # 0.85 -> Emergency
    acc3.loc["2018-08-10", cell(2030, 5120)] = 150.0   # a late Watch at a corner cell (first alert on its event day)
    rows = [{"cell_id": c, "date": d, "rain_acc_3": float(acc3.loc[d, c]), "is_positive_cell_day": False}
            for d in days for c in cells]
    frame = pd.DataFrame(rows)

    def mark(c, d):
        frame.loc[(frame["cell_id"] == c) & (frame["date"] == pd.Timestamp(d)), "is_positive_cell_day"] = True
    mark(cell(2032, 5123), "2018-08-06")            # neighbour of the storm: detected through the footprint
    mark(cell(2034, 5124), "2018-08-08")            # far corner, nothing around it
    mark(cell(2030, 5120), "2018-08-10")            # alert only on the event day
    mark(centre, "2018-08-01")                      # first day of the table: no days before
    return frame


def test_thresholds_must_be_complete_finite_and_strictly_increasing():
    assert score.check_thresholds(THRESHOLDS) == THRESHOLDS
    for bad in ({"watch": 0.1, "warning": 0.2}, {"watch": 0.3, "warning": 0.3, "emergency": 0.5},
                {"watch": 0.5, "warning": 0.2, "emergency": 0.9}, {"watch": np.nan, "warning": 0.2, "emergency": 0.9}):
        with pytest.raises(ValueError):
            score.check_thresholds(bad)


def test_levels_use_inclusive_thresholds_and_nan_risk_is_never_an_alert():
    risk = [0.0, 0.2499, 0.25, 0.4999, 0.5, 0.7999, 0.8, 1.0, np.nan]
    assert score.levels_from_risk(risk, THRESHOLDS).tolist() == [0, 0, 1, 1, 2, 2, 3, 3, 0]


def test_scorer_may_be_a_callable_or_an_object_and_its_contract_is_checked():
    frame = kerala_frame()
    a = score.run_scorer(dummy_scorer, frame)
    b = score.run_scorer(ObjectScorer(), frame)
    pd.testing.assert_frame_equal(a, b)
    assert list(a.columns) == list(score.SCORE_COLUMNS)
    with pytest.raises(ValueError, match="risk_hi"):
        score.run_scorer(lambda f: dummy_scorer(f).drop(columns=["risk_hi"]), frame)
    with pytest.raises(ValueError, match="rows"):
        score.run_scorer(lambda f: dummy_scorer(f).iloc[:-1], frame)


def test_levels_table_has_a_level_name_per_cell_day_and_the_interval_level():
    frame = kerala_frame()
    result = score.score_case("kerala_2018", dummy_scorer, THRESHOLDS, frame=frame)
    levels = result.levels
    assert len(levels) == len(frame) and list(levels["cell_id"]) == list(frame["cell_id"])
    centre = levels[(levels["cell_id"] == cell(2032, 5122))].set_index("date")
    assert centre.loc["2018-08-04", "level_name"] == "Watch" and centre.loc["2018-08-05", "level_name"] == "Warning"
    assert centre.loc["2018-08-06", "level_name"] == "Emergency" and centre.loc["2018-08-02", "level_name"] == "Normal"
    assert (levels["level_hi"] >= levels["level"]).all()
    assert centre.loc["2018-08-03", "level"] == 0 and centre.loc["2018-08-03", "level_hi"] == 0


def test_kerala_detection_lead_time_and_alerted_area():
    result = score.score_case("kerala_2018", dummy_scorer, THRESHOLDS, frame=kerala_frame())
    events = result.events.set_index(["cell_id", "date"])
    near = events.loc[(cell(2032, 5123), pd.Timestamp("2018-08-06"))]
    assert near["detected"] and near["own_level"] == 0                      # detected only through the 8-neighbour footprint
    assert near["alert_days_before"] == 2 and near["first_alert_lead_days"] == 2 and near["detected_within_7d"]
    far = events.loc[(cell(2034, 5124), pd.Timestamp("2018-08-08"))]
    assert not far["detected"] and far["alert_days_before"] == 0 and np.isnan(far["first_alert_lead_days"])
    assert not far["detected_within_7d"]
    late = events.loc[(cell(2030, 5120), pd.Timestamp("2018-08-10"))]
    assert late["detected"] and late["alert_days_before"] == 0 and late["first_alert_lead_days"] == 0
    first = events.loc[(cell(2032, 5122), pd.Timestamp("2018-08-01"))]
    assert not first["detected"] and first["days_available_before"] == 0
    m = result.metrics
    assert m["n_events"] == 4 and m["detected_on_event_day"] == 2 and m["detected_share"] == 0.5
    assert m["detected_within_7d"] == 2 and m["own_cell_at_watch"] == 1
    assert m["median_first_alert_lead_days"] == 1.0
    area = m["alerted_area"]
    assert area["cells_in_case"] == 25 and area["days"] == 10
    per_day = {r["date"]: r for r in area["per_day"]}
    assert per_day["2018-08-06"]["watch_cells"] == 1 and per_day["2018-08-06"]["emergency_cells"] == 1
    assert per_day["2018-08-06"]["watch_share"] == pytest.approx(1 / 25)
    assert per_day["2018-08-02"]["watch_cells"] == 0 and per_day["2018-08-05"]["warning_cells"] == 1
    assert area["max_watch_share"] == pytest.approx(1 / 25) and area["mean_watch_cells"] == pytest.approx(4 / 10)


def test_lookback_stops_at_the_first_day_without_an_alert_and_at_seven_days():
    frame = kerala_frame()
    frame.loc[frame["cell_id"] == cell(2032, 5122), "rain_acc_3"] = 200.0       # Warning on every day
    frame["is_positive_cell_day"] = False
    frame.loc[(frame["cell_id"] == cell(2032, 5122)) & (frame["date"] == pd.Timestamp("2018-08-10")), "is_positive_cell_day"] = True
    events = score.score_case("kerala_2018", dummy_scorer, THRESHOLDS, frame=frame).events
    assert events["alert_days_before"].iloc[0] == 7 and events["first_alert_lead_days"].iloc[0] == 7
    frame.loc[(frame["cell_id"] == cell(2032, 5122)) & (frame["date"] == pd.Timestamp("2018-08-08")), "rain_acc_3"] = 0.0
    events = score.score_case("kerala_2018", dummy_scorer, THRESHOLDS, frame=frame).events
    assert events["alert_days_before"].iloc[0] == 1                           # 08-09 alerts, 08-08 does not
    assert events["first_alert_lead_days"].iloc[0] == 7                       # but the first alert in the span is 7 days back


def wayanad_frame():
    focus = int(latlon_to_cell(om.WAYANAD["lat"], om.WAYANAD["lon"]))
    base_lat, base_lon = divmod(focus, ID_STRIDE)
    cells = [cell(base_lat + a, base_lon + b) for a in range(-3, 4) for b in range(-3, 4)]
    days = pd.date_range("2024-07-27", periods=6)
    rows = []
    far_hot = cell(base_lat + 3, base_lon + 3)        # ~22 km from the point: outside the 10 km disc
    for d in days:
        for c in cells:
            acc3 = 0.0
            if c == focus:
                acc3 = {"2024-07-29": 120.0, "2024-07-30": 300.0}.get(str(d.date()), 0.0)
            if c == far_hot and str(d.date()) == "2024-07-28":
                acc3 = 220.0
            rows.append({"cell_id": c, "date": d, "rain_acc_3": acc3})
    return pd.DataFrame(rows), focus, far_hot


def test_wayanad_series_first_alert_days_for_the_disc_and_the_box():
    frame, focus, far_hot = wayanad_frame()
    result = score.score_case("wayanad_2024", dummy_scorer, THRESHOLDS, frame=frame)
    m = result.metrics
    assert m["focus_cell"] == focus and m["focus_distance_km"] < 3 and m["box_cells"] == 49
    assert 1 <= m["cells_within_radius"] < 49
    assert m["first_watch_plus"] == {"focus": "2024-07-29", "within_10km": "2024-07-29", "box": "2024-07-28"}
    assert m["first_warning_plus"] == {"focus": "2024-07-30", "within_10km": "2024-07-30", "box": "2024-07-28"}
    assert m["peak_near_date"] == "2024-07-30" and m["peak_near_risk"] == pytest.approx(0.75)
    assert m["peak_box_risk"] == pytest.approx(0.75)
    series = result.series.set_index("date")
    assert series.loc["2024-07-28", "box_max_level"] == 2 and series.loc["2024-07-28", "near_max_level"] == 0
    assert series.loc["2024-07-30", "focus_level"] == 2 and series.loc["2024-07-30", "box_cells_watch_plus"] == 1
    assert len(series) == 6 and series["box_cells"].eq(49).all()


def test_wayanad_without_any_alert_reports_none_and_a_custom_focus_point_is_honoured():
    frame, focus, far_hot = wayanad_frame()
    frame["rain_acc_3"] = 0.0
    result = score.score_case("wayanad_2024", dummy_scorer, THRESHOLDS, frame=frame)
    assert result.metrics["first_watch_plus"] == {"focus": None, "within_10km": None, "box": None}
    frame2, _, _ = wayanad_frame()
    lat, lon = cell_center(far_hot)
    moved = score.score_case("wayanad_2024", dummy_scorer, THRESHOLDS, frame=frame2, focus=(float(lat), float(lon)))
    assert moved.metrics["focus_cell"] == far_hot and moved.metrics["first_watch_plus"]["focus"] == "2024-07-28"


def test_a_scorer_monotone_in_rain_gives_monotone_levels_and_scoring_is_deterministic():
    frame = kerala_frame()
    one = score.score_case("kerala_2018", dummy_scorer, THRESHOLDS, frame=frame)
    two = score.score_case("kerala_2018", dummy_scorer, THRESHOLDS, frame=frame)
    pd.testing.assert_frame_equal(one.levels, two.levels)
    assert one.metrics == two.metrics
    order = frame["rain_acc_3"].argsort(kind="stable")
    assert (np.diff(one.levels["level"].to_numpy()[order]) >= 0).all()


def test_unknown_case_and_bad_thresholds_are_rejected():
    with pytest.raises(ValueError, match="unknown case"):
        score.score_case("nowhere", dummy_scorer, THRESHOLDS, frame=kerala_frame())
    with pytest.raises(ValueError, match="strictly increasing"):
        score.score_case("kerala_2018", dummy_scorer, {"watch": 0.5, "warning": 0.5, "emergency": 0.6}, frame=kerala_frame())


@pytest.mark.realdata
def test_real_case_frames_score_with_a_dummy_scorer():
    kerala = score.score_case("kerala_2018", dummy_scorer, {"watch": 0.15, "warning": 0.4, "emergency": 0.8})
    assert kerala.metrics["n_events"] == 23 and kerala.metrics["alerted_area"]["cells_in_case"] == 8048
    assert kerala.metrics["alerted_area"]["days"] == 20 and kerala.metrics["detected_on_event_day"] > 0
    wayanad = score.score_case("wayanad_2024", dummy_scorer, {"watch": 0.15, "warning": 0.4, "emergency": 0.8})
    assert wayanad.metrics["box_cells"] == 140 and wayanad.metrics["first_watch_plus"]["box"] is not None
    assert wayanad.metrics["focus_distance_km"] < 5 and len(wayanad.series) == 22
