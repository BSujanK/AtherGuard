import json
from datetime import date

import numpy as np
import pytest
import xarray as xr

from aetherguard import grid
from aetherguard.config import load_config
from aetherguard.ingest import power

CFG = {"domain_bbox": {"lat_min": 8.0, "lat_max": 36.0, "lon_min": 72.0, "lon_max": 98.0},
       "power": {"zarr": "s3://unused/never-opened.zarr", "variables": ["GWETTOP", "GWETROOT"]}}
PERIOD = ("2007-01-01", "2007-01-10")


def _dataset(n_days=13, start="2006-12-29", nan_day=None):
    """A small MERRA-2-shaped store: lat step 0.5, lon step 0.625, value encodes the grid point and day."""
    times = np.arange(np.datetime64(start), np.datetime64(start) + np.timedelta64(n_days, "D"))
    lat = np.arange(0.0, 45.0 + 0.25, 0.5)
    lon = np.arange(60.0, 110.0, 0.625)
    t, la, lo = np.meshgrid(np.arange(len(times)), np.arange(len(lat)), np.arange(len(lon)), indexing="ij")
    top = (0.01 + 0.0001 * la + 0.00001 * lo + 0.01 * t).astype(np.float32)
    root = (top * 0.5).astype(np.float32)
    if nan_day is not None:
        top[nan_day] = np.nan
    ds = xr.Dataset({"GWETTOP": (("time", "lat", "lon"), top), "GWETROOT": (("time", "lat", "lon"), root)},
                    coords={"time": times.astype("datetime64[ns]"), "lat": lat, "lon": lon})
    ds["GWETTOP"].encoding["chunks"] = (5844, 15, 15)
    return ds


def _build(tmp_path, ds=None, **kw):
    return power.build_power_wetness(CFG, tmp_path / "rain", dataset=ds if ds is not None else _dataset(),
                                     period=kw.pop("period", PERIOD), **kw)


def test_build_selects_period_and_padded_domain_and_writes_files(tmp_path):
    index = _build(tmp_path)
    assert index["period"] == {"start": "2007-01-01", "end": "2007-01-10", "n_days": 10}
    data = np.load(tmp_path / "rain" / "power_wetness.npz")
    assert data["GWETTOP"].dtype == np.float32 and data["GWETTOP"].shape == (10, 59, 43)
    assert data["GWETROOT"].shape == (10, 59, 43)
    assert str(data["dates"][0]) == "2007-01-01" and str(data["dates"][-1]) == "2007-01-10"
    assert data["lat"][0] == 7.5 and data["lat"][-1] == 36.5  # one MERRA-2 step of padding
    assert data["lon"][0] == 71.875 and data["lon"][-1] == 98.125
    assert index["grid"]["n_lat"] == 59 and index["grid"]["n_lon"] == 43
    assert json.loads((tmp_path / "rain" / "power_index.json").read_text())["grid"]["lon_step"] == 0.625
    assert index["variables"]["GWETTOP"]["chunks_time_lat_lon"] == [5844, 15, 15]
    assert index["elapsed_seconds"] >= 0


def test_fill_out_of_range_and_nan_become_nan_and_are_counted(tmp_path):
    ds = _dataset()
    ds["GWETTOP"].values[3, 20, 30] = -999.0
    ds["GWETTOP"].values[3, 20, 31] = 1.5
    ds["GWETTOP"].values[3, 20, 32] = -0.25
    ds["GWETTOP"].values[3, 20, 33] = np.nan
    index = _build(tmp_path, ds)
    stats = index["variables"]["GWETTOP"]
    assert stats["n_fill_value"] == 1 and stats["n_out_of_range"] == 2
    data = np.load(tmp_path / "rain" / "power_wetness.npz")
    top = data["GWETTOP"]
    assert np.isfinite(top).sum() < top.size
    assert stats["min"] >= 0.0 and stats["max"] <= 1.0
    assert 0.0 < stats["nan_share"] < 0.01
    assert not (top == -999).any() and not (top > 1).any() and not (top < 0).any()
    assert index["variables"]["GWETROOT"]["n_fill_value"] == 0
    assert 0.0 <= stats["share_exactly_one"] < 0.01


def test_all_nan_day_is_counted(tmp_path):
    index = _build(tmp_path, _dataset(nan_day=4))  # array day 4 = 2007-01-02
    assert index["variables"]["GWETTOP"]["n_all_nan_days"] == 1
    assert index["variables"]["GWETROOT"]["n_all_nan_days"] == 0


def test_empty_selection_and_gappy_days_are_errors(tmp_path):
    with pytest.raises(ValueError, match="empty"):
        _build(tmp_path, period=("2010-01-01", "2010-01-05"))
    ds = _dataset()
    gappy = ds.isel(time=[0, 1, 2, 4, 5, 6, 7, 8, 9, 10, 11, 12])
    with pytest.raises(ValueError, match="consecutive"):
        _build(tmp_path, gappy, period=("2006-12-29", "2007-01-10"))


def test_default_period_comes_from_the_domain_config(tmp_path):
    ds = _dataset(n_days=3, start="2007-01-01")
    index = power.build_power_wetness(CFG, tmp_path / "rain", dataset=ds)
    domain_period = load_config("domain")["period"]
    assert index["period"]["start"] == domain_period["start"] == "2007-01-01"
    assert index["period"]["end"] == "2007-01-03"  # the data ends earlier than the configured end


def test_reader_returns_nearest_point_values_and_nan_outside_the_store(tmp_path):
    _build(tmp_path)
    reader = power.PowerWetness(tmp_path / "rain" / "power_wetness.npz")
    cell = grid.latlon_to_cell(11.55, 76.13)  # centre 11.575 N, 76.125 E
    i, j = reader.nearest_point(cell)
    assert reader.lat[i] == 11.5 and reader.lon[j] == 76.25  # 76.125 is nearer to 76.25 (0.125) than 75.625
    series = reader.cell_series(cell, "2006-12-31", date(2007, 1, 3), "GWETTOP")
    assert series.dtype == np.float32 and len(series) == 4
    assert np.isnan(series[0])  # 2006-12-31 is outside the stored period
    ds = _dataset()
    expected = ds["GWETTOP"].sel(time="2007-01-01", lat=11.5, lon=76.25).item()
    assert series[1] == pytest.approx(expected)
    assert reader.cell_series(cell, "2007-01-01", "2007-01-01", "GWETROOT")[0] == pytest.approx(expected * 0.5)
    assert np.isnan(reader.cell_series(cell, "2008-05-01", "2008-05-03", "GWETTOP")).all()
    assert reader.dates()[0] == date(2007, 1, 1) and len(reader.dates()) == 10
    assert reader.variables == ["GWETROOT", "GWETTOP"]


def test_reader_rejects_unknown_variable_bad_range_and_foreign_cell(tmp_path):
    _build(tmp_path)
    reader = power.PowerWetness(tmp_path / "rain" / "power_wetness.npz")
    cell = grid.latlon_to_cell(11.55, 76.13)
    with pytest.raises(KeyError):
        reader.cell_series(cell, "2007-01-01", "2007-01-02", "PRECTOTCORR")
    with pytest.raises(ValueError):
        reader.cell_series(cell, "2007-01-05", "2007-01-02", "GWETTOP")
    with pytest.raises(ValueError, match="outside the stored POWER grid"):
        reader.cell_series(grid.latlon_to_cell(40.0, 76.0), "2007-01-01", "2007-01-02", "GWETTOP")


def test_every_cell_inside_the_bbox_has_a_nearest_point_within_half_a_step(tmp_path):
    _build(tmp_path)
    reader = power.PowerWetness(tmp_path / "rain" / "power_wetness.npz")
    for lat, lon in [(8.025, 72.025), (35.975, 97.975), (8.025, 97.975), (35.975, 72.025), (22.0, 85.0)]:
        cell = grid.latlon_to_cell(lat, lon)
        i, j = reader.nearest_point(cell)
        lat_c, lon_c = grid.cell_center(cell)
        assert abs(reader.lat[i] - lat_c) <= 0.25 + 1e-9 and abs(reader.lon[j] - lon_c) <= 0.3125 + 1e-9


def test_tie_goes_to_the_southern_western_point(tmp_path):
    _build(tmp_path)
    reader = power.PowerWetness(tmp_path / "rain" / "power_wetness.npz")
    reader.lat = np.array([10.0, 10.05, 10.1])  # synthetic lattice where a centre (10.075) is half-way
    reader.lon = np.array([76.0, 76.05, 76.1])
    cell = grid.latlon_to_cell(10.07, 76.07)  # centre 10.075 N, 76.075 E: ties between indices 1 and 2
    assert reader.nearest_point(cell) == (1, 1)


@pytest.mark.realdata
def test_real_power_store_values_are_plausible():
    from aetherguard.config import data_root
    reader = power.PowerWetness(data_root() / "processed" / "rain" / "power_wetness.npz")
    cell = grid.latlon_to_cell(11.55, 76.13)
    series = reader.cell_series(cell, "2024-07-01", "2024-07-31", "GWETTOP")
    print("Wayanad GWETTOP July 2024:", np.round(series, 2).tolist())
    assert np.isfinite(series).all() and ((series >= 0) & (series <= 1)).all()


def test_cli_prints_a_summary(monkeypatch, tmp_path, capsys):
    from aetherguard.ingest import power_build
    monkeypatch.setenv("AETHERGUARD_DATA_DIR", str(tmp_path / "data"))
    seen = []

    def fake_build(cfg, out_dir):
        seen.append(out_dir)
        stats = {"nan_share": 0.0, "min": 0.03, "max": 1.0, "n_fill_value": 0, "n_out_of_range": 0,
                 "chunks_time_lat_lon": [5844, 15, 15]}
        return {"period": {"n_days": 6575, "start": "2007-01-01", "end": "2024-12-31"},
                "grid": {"n_lat": 59, "n_lon": 43}, "elapsed_seconds": 20.5,
                "variables": {"GWETTOP": stats, "GWETROOT": stats}}

    monkeypatch.setattr(power_build, "build_power_wetness", fake_build)
    assert power_build.main() == 0
    assert seen == [tmp_path / "data" / "processed" / "rain"]
    out = capsys.readouterr().out
    assert "6575 days" in out and "GWETROOT" in out
