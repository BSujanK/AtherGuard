import numpy as np
import pandas as pd
import pytest
from integrity_helpers import dly_line, month_lines, write_raw_tree

from aetherguard.audit import ghcnd
from aetherguard.config import data_root
from aetherguard.integrity import stations

STATIONS = [("IN000000001", 11.5, 76.1, 900.0, "UPLAND ONE"),
            ("IN000000002", 12.0, 76.5, 50.0, "LOWLAND TWO"),
            ("NP000000003", 27.7, 85.3, 1300.0, "KATHMANDU")]


def _tree(tmp_path):
    jan = month_lines("IN000000001", 2000, {1: [0.0, 12.5, None, 3.0]})
    feb_flag = dly_line("IN000000001", 2000, 2, days={1: (500, "K"), 2: (0, " "), 3: (25, " ")})
    second = month_lines("IN000000002", 2000, {1: [1.0] * 31, 2: [0.0] * 29, 3: [2.0] * 31})
    third = month_lines("NP000000003", 2000, {1: [5.0] * 31})
    return write_raw_tree(tmp_path / "ghcnd", STATIONS, {
        "IN000000001": jan + feb_flag + "\n", "IN000000002": second, "NP000000003": third})


def test_parser_equals_read_dly_on_a_hand_made_file(tmp_path):
    raw = _tree(tmp_path)
    path = raw / "dly" / "IN000000001.dly"
    ours = stations.read_prcp_dly(path)
    theirs = ghcnd.read_dly(path)
    theirs["date"] = pd.to_datetime(theirs["date"])
    theirs = theirs.set_index("date")
    shared = ours.loc[theirs.index]
    np.testing.assert_allclose(shared["value"].to_numpy(np.float64),
                               theirs["value"].to_numpy(np.float64), equal_nan=True, rtol=1e-6)
    assert (shared["flag"].to_numpy() == theirs["qflag"].str.strip().to_numpy()).all()


def test_parsed_frame_is_daily_continuous_float32_with_nan_for_missing(tmp_path):
    frame = stations.read_prcp_dly(_tree(tmp_path) / "dly" / "IN000000001.dly")
    assert frame["value"].dtype == np.float32
    assert (frame.index.to_series().diff().dropna() == pd.Timedelta(days=1)).all()
    assert frame.index[0] == pd.Timestamp("2000-01-01") and frame.index[-1] == pd.Timestamp("2000-02-29")
    assert frame.loc["2000-01-02", "value"] == pytest.approx(12.5)
    assert np.isnan(frame.loc["2000-01-03", "value"])  # the -9999 sentinel, never 0
    assert np.isnan(frame.loc["2000-01-20", "value"])
    assert frame.loc["2000-02-01", "flag"] == "K" and frame.loc["2000-02-02", "flag"] == ""


def test_short_and_duplicated_lines_raise(tmp_path):
    bad = tmp_path / "bad.dly"
    bad.write_text(dly_line("IN000000001", 2000, 1)[:100] + "\n", encoding="ascii")
    with pytest.raises(ValueError, match="short"):
        stations.read_prcp_dly(bad)
    dup = tmp_path / "dup.dly"
    dup.write_text((dly_line("IN000000001", 2000, 1) + "\n") * 2, encoding="ascii")
    with pytest.raises(ValueError, match="twice"):
        stations.read_prcp_dly(dup)


def test_non_prcp_elements_are_ignored(tmp_path):
    path = tmp_path / "x.dly"
    path.write_text(dly_line("IN000000001", 2000, 1, element="TMAX", days={1: (300, " ")}) + "\n"
                    + dly_line("IN000000001", 2000, 1, days={1: (7, " ")}) + "\n", encoding="ascii")
    frame = stations.read_prcp_dly(path)
    assert frame.loc["2000-01-01", "value"] == pytest.approx(0.7)


def test_load_station_set_shapes_meta_and_window(tmp_path):
    raw = _tree(tmp_path)
    sset = stations.load_station_set(raw, start="2000-01-01", end="2000-03-31")
    assert list(sset.values.columns) == ["IN000000001", "IN000000002", "NP000000003"]
    assert sset.values.shape == (91, 3) and sset.flags.shape == (91, 3)
    assert sset.values.dtypes.eq(np.float32).all()
    assert sset.values.index.equals(sset.flags.index)
    assert np.isnan(sset.values.loc["2000-03-01", "IN000000001"])  # outside that station's record
    assert sset.values.loc["2000-03-15", "IN000000002"] == pytest.approx(2.0)
    assert sset.flags.loc["2000-02-01", "IN000000001"] == "K"
    assert sset.flags.loc["2000-02-02", "IN000000001"] == ""
    meta = sset.meta.set_index("id")
    assert list(sset.meta["id"]) == list(sset.values.columns)
    assert meta.loc["IN000000001", "upland"] and not meta.loc["IN000000002", "upland"]
    assert meta.loc["NP000000003", "country"] == "NP"
    assert meta.loc["IN000000001", "region"] == "western_ghats"
    assert {"id", "name", "lat", "lon", "elevation_m", "region", "upland"} <= set(sset.meta.columns)


def test_window_clips_and_none_means_the_full_span(tmp_path):
    raw = _tree(tmp_path)
    clipped = stations.load_station_set(raw, start="2000-02-01", end="2000-02-10")
    assert len(clipped.values) == 10
    full = stations.load_station_set(raw, start=None, end=None)
    assert full.values.index[0] == pd.Timestamp("2000-01-01")
    assert full.values.index[-1] == pd.Timestamp("2000-03-31")


def test_station_without_a_dly_file_raises(tmp_path):
    raw = _tree(tmp_path)
    (raw / "dly" / "NP000000003.dly").unlink()
    with pytest.raises(FileNotFoundError, match="NP000000003"):
        stations.load_station_set(raw, start="2000-01-01", end="2000-03-31")


def test_load_full_series_spans_the_whole_history(tmp_path):
    raw = _tree(tmp_path)
    full = stations.load_full_series("IN000000002", raw_dir=raw)
    assert list(full.columns) == ["value", "flag"]
    assert full.index[0] == pd.Timestamp("2000-01-01") and full.index[-1] == pd.Timestamp("2000-03-31")


@pytest.mark.realdata
def test_real_station_parse_equals_read_dly():
    raw = data_root() / "raw" / "ghcnd"
    path = raw / "dly" / "IN019131301.dly"  # the station with real K flags
    ours = stations.read_prcp_dly(path)
    theirs = ghcnd.read_dly(path)
    theirs["date"] = pd.to_datetime(theirs["date"])
    theirs = theirs.set_index("date")
    assert len(ours) >= len(theirs)
    shared = ours.loc[theirs.index]
    np.testing.assert_allclose(shared["value"].to_numpy(np.float64),
                               theirs["value"].to_numpy(np.float64), equal_nan=True, rtol=1e-6)
    assert (shared["flag"].to_numpy() == theirs["qflag"].str.strip().to_numpy()).all()
    assert (shared["flag"] == "K").sum() == 5


@pytest.mark.realdata
def test_real_station_set_has_the_selected_stations():
    sset = stations.load_station_set()
    assert sset.values.shape[1] == 140 == len(sset.meta)
    assert sset.values.index[0] == pd.Timestamp("1990-01-01")
    assert sset.values.index[-1] == pd.Timestamp("2024-12-31")
    assert set(sset.meta["country"]) == {"IN", "NP"}
