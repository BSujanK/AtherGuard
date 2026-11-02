import json

import numpy as np
import pandas as pd
import pytest

from aetherguard.config import data_root
from aetherguard.integrity import grids

# Stations: KL in India at IMD point (20, 39) and CHIRPS pixel (9, 5) of the toy window; NP is outside the
# IMD coverage mask (a Nepal-like station with data present in the grid but uncovered).
META = pd.DataFrame([{"id": "KL", "lat": 11.5, "lon": 76.25}, {"id": "NP", "lat": 27.7, "lon": 85.4}])
DATES = pd.date_range("2006-12-30", "2007-01-12", freq="D")


def write_imd(root):
    data = np.full((365, 129, 135), np.nan, dtype=np.float32)
    data[:, 20, 39] = np.arange(1, 366)           # KL: value = day of year
    data[:, 85, 76] = 7.0                          # NP's point holds data, but is not in the coverage mask
    mask = np.zeros((129, 135), dtype=bool)
    mask[20, 39] = True
    np.save(root / "imd_2007.npy", data)
    np.save(root / "imd_coverage_mask.npy", mask)
    (root / "imd_index.json").write_text(json.dumps({
        "years": {"2007": {"file": "imd_2007.npy"}}, "covered_cells": 1,
        "coverage_mask": "imd_coverage_mask.npy"}), encoding="utf-8")


def write_chirps(root):
    n = 10                                         # 2007-01-01 .. 2007-01-10
    data = np.full((n, 20, 20), np.nan, dtype=np.float16)
    data[:, 9, 5] = np.arange(1, n + 1) * 10.0     # KL pixel: 10, 20, ... 100 (UTC days)
    data[3, 9, 5] = np.nan                         # one missing value
    np.save(root / "chirps_2007.npy", data)
    stamps = [str(d.date()) for d in pd.date_range("2007-01-01", periods=n)]
    (root / "chirps_2007_dates.json").write_text(json.dumps(stamps), encoding="utf-8")
    (root / "chirps_index.json").write_text(json.dumps({
        "missing_dates": [], "days_per_year": {"2007": n}, "rows": 20, "cols": 20,
        "row_off": 760, "col_off": 5120}), encoding="utf-8")


def write_power(root):
    dates = pd.date_range("2007-01-01", periods=12).strftime("%Y-%m-%d").to_numpy().astype("U10")
    lat = np.array([11.5, 12.0, 27.5, 28.0])
    lon = np.array([76.25, 76.875, 85.0, 85.625])
    top = np.full((12, 4, 4), 0.4, dtype=np.float32)
    root_zone = np.full((12, 4, 4), 0.3, dtype=np.float32)
    top[:, 0, 0] = np.linspace(0.2, 0.9, 12)           # KL's MERRA-2 point
    root_zone[:, 0, 0] = np.linspace(0.1, 0.8, 12)
    root_zone[5, 0, 0] = np.nan                         # a missing root value masks GWETTOP that day
    top[:, 2, 3] = 1.0                                  # NP: an "ocean" point (GWETTOP 1.0, GWETROOT NaN)
    root_zone[:, 2, 3] = np.nan
    np.savez_compressed(root / "power_wetness.npz", GWETTOP=top, GWETROOT=root_zone, lat=lat, lon=lon, dates=dates)


@pytest.fixture
def rain_dir(tmp_path):
    root = tmp_path / "rain"
    root.mkdir()
    write_imd(root)
    write_chirps(root)
    write_power(root)
    return root


def test_imd_follows_the_nearest_point_and_is_nan_when_uncovered_or_outside_the_stored_years(rain_dir):
    refs = grids.station_grid_refs(META, DATES, rain_dir)
    imd = refs.values["imd"]
    assert imd["KL"].iloc[:2].isna().all()                      # 2006 is not in the store: NaN, not 0
    assert imd["KL"].iloc[2] == 1.0 and imd["KL"].iloc[-1] == 12.0   # day-of-year of 2007-01-01 / 01-12
    assert imd["NP"].isna().all()                               # data exists but the cell is uncovered
    assert imd.dtypes.eq(np.float32).all() and imd.index.equals(pd.DatetimeIndex(DATES).as_unit("ns"))


def test_chirps_utc_and_aligned_follow_the_day_basis_and_keep_missing_as_nan(rain_dir):
    refs = grids.station_grid_refs(META, DATES, rain_dir)
    utc, aligned = refs.values["chirps_utc"]["KL"], refs.values["chirps_aligned"]["KL"]
    day = lambda s: pd.Timestamp(s)  # noqa: E731
    assert utc[day("2007-01-02")] == 20.0 and np.isnan(utc[day("2007-01-04")]) and np.isnan(utc[day("2006-12-31")])
    assert aligned[day("2007-01-03")] == pytest.approx(0.875 * 20 + 0.125 * 30)
    assert np.isnan(aligned[day("2007-01-01")])                 # D-1 not in the store
    assert np.isnan(aligned[day("2007-01-04")]) and np.isnan(aligned[day("2007-01-05")])   # either day missing
    assert refs.values["chirps_utc"]["NP"].isna().all()         # pixel outside the toy window: NaN, not an error


def test_power_masks_top_wetness_wherever_root_is_nan(rain_dir):
    refs = grids.station_grid_refs(META, DATES, rain_dir)
    top, root = refs.values["gw_top"], refs.values["gw_root"]
    day = pd.Timestamp("2007-01-01")
    assert top.loc[day, "KL"] == pytest.approx(0.2) and root.loc[day, "KL"] == pytest.approx(0.1)
    masked = pd.Timestamp("2007-01-06")                         # index 5: GWETROOT NaN
    assert np.isnan(root.loc[masked, "KL"]) and np.isnan(top.loc[masked, "KL"])
    assert top["NP"].isna().all() and root["NP"].isna().all()   # ocean-like point never leaks GWETTOP == 1.0
    assert np.isnan(top.loc["2006-12-30":"2006-12-31", "KL"]).all()   # before the store starts: NaN


def test_availability_and_coverage_counts(rain_dir):
    refs = grids.station_grid_refs(META, DATES, rain_dir)
    avail = refs.available("imd")
    assert avail["KL"].sum() == 12 and avail["NP"].sum() == 0
    cov = refs.coverage("2007-01-01", "2007-01-12")
    assert cov["imd"] == {"station_days": 24, "available": 12, "share": 0.5, "stations_with_any": 1}
    assert cov["chirps_utc"]["available"] == 9                  # 10 days minus the missing one, KL only
    assert set(cov) == set(grids.SOURCES)
    whole = refs.coverage()
    assert whole["imd"]["station_days"] == 2 * len(DATES)


def test_long_table_has_one_row_per_station_day_with_availability_flags(rain_dir):
    refs = grids.station_grid_refs(META, DATES, rain_dir)
    long = refs.to_long()
    assert len(long) == 2 * len(DATES)
    assert {"station", "date", "imd", "imd_available", "chirps_aligned_available", "gw_top_available"} <= set(long.columns)
    kl = long[long["station"] == "KL"].set_index("date")
    assert bool(kl.loc[pd.Timestamp("2007-01-02"), "imd_available"]) and not bool(kl.loc[pd.Timestamp("2006-12-30"), "imd_available"])


def test_dates_must_be_consecutive(rain_dir):
    with pytest.raises(ValueError, match="consecutive"):
        grids.station_grid_refs(META, pd.DatetimeIndex(["2007-01-01", "2007-01-03"]), rain_dir)


@pytest.mark.realdata
def test_real_wayanad_point_has_imd_far_above_chirps_utc_on_2024_07_30():
    rain = data_root() / "processed" / "rain"
    point = pd.DataFrame([{"id": "WAYANAD", "lat": 11.55, "lon": 76.13}])
    refs = grids.station_grid_refs(point, pd.date_range("2024-07-28", "2024-07-31"), rain)
    day = pd.Timestamp("2024-07-30")
    assert refs.values["imd"].loc[day, "WAYANAD"] == pytest.approx(179.2, abs=0.5)
    assert refs.values["chirps_utc"].loc[day, "WAYANAD"] < 5.0
    assert refs.values["chirps_aligned"].loc[day, "WAYANAD"] < 0.2 * refs.values["imd"].loc[day, "WAYANAD"]
    assert refs.available("gw_top").loc[day, "WAYANAD"]
