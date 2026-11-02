"""Station trust states, the out-of-distribution guard and the station-to-cell join."""
import numpy as np
import pandas as pd
import pytest

from aetherguard.alerts import stations as st
from alerts_helpers import CONFIG, STATIONS, station_outputs


def test_clean_station_is_trusted_and_unobserved_days_are_missing():
    out = st.station_states(station_outputs({"A": {"missing_from": 50}}, 60), CONFIG)
    assert out.loc[out["date"] == "2024-01-10", "state"].item() == "trusted"
    assert out.loc[out["date"] == "2024-02-20", "state"].item() == "missing"
    assert not out["ood"].any()


def test_a_flagged_reading_below_the_ood_rate_is_faulty():
    out = st.station_states(station_outputs({"A": {"flag_every": 50}}, 100), CONFIG)   # rate 2% < 3x1%
    day0 = out.loc[out["date"] == "2024-01-01"].iloc[0]
    assert day0["state"] == "faulty" and not day0["ood"]


def test_station_above_three_times_the_target_becomes_uncertain_never_faulty():
    out = st.station_states(station_outputs({"A": {"flag_every": 10}}, 100), CONFIG)   # rate 10% > 3%
    late = out[out["date"] >= "2024-02-15"]
    assert late["ood"].all()
    assert set(late["state"]) == {"uncertain"}                                       # flagged days too
    assert not (out["state"] == "faulty").any() or (out.loc[out["state"] == "faulty", "date"] < "2024-02-01").all()


def test_ood_needs_the_minimum_observed_days():
    out = st.station_states(station_outputs({"A": {"flag_every": 2}}, 20), CONFIG)
    assert not out["ood"].any() and (out.loc[out["flagged"], "state"] == "faulty").all()


def test_ood_rate_is_a_trailing_window_so_it_recovers():
    outputs = station_outputs({"A": {"flag_every": 5}}, 140)
    outputs.loc[outputs["date"] >= "2024-01-31", ["flagged", "fault_type"]] = [False, ""]   # clean after day 30
    out = st.station_states(outputs, CONFIG).set_index("date")
    assert out.loc["2024-01-31", "ood"] and not out.loc["2024-05-09", "ood"]


def test_states_keep_row_order_and_reject_duplicates_and_missing_columns():
    outputs = station_outputs({"A": {}, "B": {}}, 5).sample(frac=1, random_state=1)
    out = st.station_states(outputs, CONFIG)
    assert (out["station"].to_numpy() == outputs["station"].to_numpy()).all()
    with pytest.raises(ValueError, match="one row per"):
        st.station_states(pd.concat([outputs, outputs.iloc[:1]]), CONFIG)
    with pytest.raises(ValueError, match="lack columns"):
        st.station_states(outputs.drop(columns=["trust"]), CONFIG)


def test_nearby_summary_counts_ood_stations_and_lists_flagged_types_within_radius():
    outputs = pd.concat([station_outputs({"A": {"flag_every": 2, "fault_type": "stuck_value"}}, 60),
                         station_outputs({"B": {}}, 60), station_outputs({"FAR": {"flag_every": 2}}, 60)])
    states = st.station_states(outputs, CONFIG)
    dates = pd.to_datetime(["2024-02-10", "2024-02-11", "2024-02-10", "2030-01-01"])
    lat, lon = [11.5, 11.5, 40.0, 11.5], [76.0, 76.0, 100.0, 76.0]
    n_ood, types = st.nearby_station_summary(lat, lon, dates, states, STATIONS, 100.0)
    assert n_ood.tolist() == [1, 1, 0, 0]               # A is OOD and near; FAR is OOD but 1500 km away
    assert types[0] == "stuck_value" and types[1] == ""   # 2024-02-10 flagged (even day), 02-11 not
    assert types[2] == "" and types[3] == ""            # nothing near / date outside the outputs


def test_stations_frame_needs_coordinates():
    with pytest.raises(ValueError, match="lat, lon"):
        st.station_coordinates(pd.DataFrame({"id": ["A"]}))
    assert st.station_coordinates(STATIONS)["station"].tolist() == ["A", "B", "FAR"]


def test_empty_station_outputs_give_an_empty_state_table():
    empty = station_outputs({"A": {}}, 3).iloc[:0]
    out = st.station_states(empty, CONFIG)
    assert out.empty and {"ood", "state", "flag_rate_window"} <= set(out.columns)
