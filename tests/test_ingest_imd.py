"""IMD gauge-grid ingest: download, read, store and lookup. Offline and hermetic; real data is marked realdata."""
import json
import sys
import types

import numpy as np
import pandas as pd
import pytest

from aetherguard.config import PROJECT_ROOT
from aetherguard.grid import cell_center, latlon_to_cell
from aetherguard.ingest import imd
from aetherguard.ingest.imd import (
    ImdDownloadError,
    ImdFormatError,
    ImdGrid,
    ImdStoreError,
    build_imd_store,
    days_in_year,
    download_imd_years,
    expected_size_bytes,
    imd_raw_path,
    read_imd_year,
)
from aetherguard.manifest import Manifest

WAYANAD = (20, 39)  # grid index of (11.5 N, 76.25 E): (11.5 - 6.5) / 0.25 and (76.25 - 66.5) / 0.25


def _year_array(year, fill=1.0):
    arr = np.full((days_in_year(year), 129, 135), fill, dtype="<f4")
    arr[:, WAYANAD[0], WAYANAD[1]] = year * 1000 + np.arange(1, days_in_year(year) + 1)  # value = year*1000 + doy
    return arr


def _write_grd(raw_dir, year, arr):
    path = imd_raw_path(raw_dir, year)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.ascontiguousarray(arr, dtype="<f4").tofile(path)
    return path


@pytest.fixture
def manifest(tmp_path):
    return Manifest(tmp_path / "manifest.jsonl", tmp_path / "data")


@pytest.fixture
def raw_dir(tmp_path):
    return tmp_path / "data" / "raw" / "imd"


def _fake_fetch(calls, size_of=expected_size_bytes, failing=()):
    def fetch(year, directory):
        calls.append(year)
        if year in failing:
            raise RuntimeError(f"server said no for {year}")
        path = imd_raw_path(directory, year)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(bytes(size_of(year)))
    return fetch


# ---------------------------------------------------------------- sizes
def test_sizes_match_the_verified_2024_file():
    assert days_in_year(2024) == 366 and days_in_year(2023) == 365
    assert days_in_year(2000) == 366 and days_in_year(1900) == 365
    assert expected_size_bytes(2024) == 25_495_560 == 366 * 129 * 135 * 4
    assert expected_size_bytes(2023) == 365 * 129 * 135 * 4


# ---------------------------------------------------------------- download
def test_download_fetches_registers_and_is_idempotent(raw_dir, manifest):
    calls = []
    report = download_imd_years(2023, 2024, raw_dir, manifest, fetch=_fake_fetch(calls))
    assert calls == [2023, 2024]
    assert report.downloaded == [2023, 2024] and report.skipped == [] and report.failed == {}
    entries = manifest.entries()
    assert sorted(entries) == ["raw/imd/rain/2023.grd", "raw/imd/rain/2024.grd"]
    entry = entries["raw/imd/rain/2024.grd"]
    assert entry.source == "IMD gridded rainfall 0.25 deg (via imdlib)"
    assert entry.url == "https://imdpune.gov.in"
    assert entry.licence == "IMD data terms (verify before redistribution)"
    assert entry.size_bytes == expected_size_bytes(2024)

    calls.clear()
    lines_before = manifest.manifest_path.read_text(encoding="utf-8").splitlines()
    again = download_imd_years(2023, 2024, raw_dir, manifest, fetch=_fake_fetch(calls))
    assert calls == [] and again.skipped == [2023, 2024] and again.downloaded == [] and again.failed == {}
    assert manifest.manifest_path.read_text(encoding="utf-8").splitlines() == lines_before


def test_download_records_failures_per_year_and_continues(raw_dir, manifest):
    calls = []
    report = download_imd_years(2022, 2024, raw_dir, manifest, fetch=_fake_fetch(calls, failing={2023}))
    assert calls == [2022, 2023, 2024]
    assert report.downloaded == [2022, 2024]
    assert list(report.failed) == [2023] and "server said no for 2023" in report.failed[2023]
    assert not imd_raw_path(raw_dir, 2023).exists()
    assert sorted(manifest.entries()) == ["raw/imd/rain/2022.grd", "raw/imd/rain/2024.grd"]


def test_download_rejects_a_wrong_size_file_and_leaves_nothing_behind(raw_dir, manifest):
    report = download_imd_years(2024, 2024, raw_dir, manifest,
                                fetch=_fake_fetch([], size_of=lambda year: 5000))
    assert list(report.failed) == [2024]
    assert "5000" in report.failed[2024] and str(expected_size_bytes(2024)) in report.failed[2024]
    assert not imd_raw_path(raw_dir, 2024).exists()
    assert manifest.entries() == {}


def test_download_refetches_a_truncated_existing_file(raw_dir, manifest):
    path = imd_raw_path(raw_dir, 2023)
    path.parent.mkdir(parents=True)
    path.write_bytes(bytes(4096))  # imdlib would skip this (>= 1 KiB); we must not
    calls = []
    report = download_imd_years(2023, 2023, raw_dir, manifest, fetch=_fake_fetch(calls))
    assert calls == [2023] and report.downloaded == [2023]
    assert path.stat().st_size == expected_size_bytes(2023)


def test_download_registers_an_unrecorded_complete_file_without_fetching(raw_dir, manifest):
    path = imd_raw_path(raw_dir, 2023)
    path.parent.mkdir(parents=True)
    path.write_bytes(bytes(expected_size_bytes(2023)))
    calls = []
    report = download_imd_years(2023, 2023, raw_dir, manifest, fetch=_fake_fetch(calls))
    assert calls == [] and report.registered == [2023] and report.failed == {}
    assert manifest.is_current(path)


def test_download_refetches_a_file_that_no_longer_matches_its_manifest_entry(raw_dir, manifest):
    download_imd_years(2023, 2023, raw_dir, manifest, fetch=_fake_fetch([]))
    path = imd_raw_path(raw_dir, 2023)
    tampered = bytearray(path.read_bytes())
    tampered[0] = 1  # same size, different checksum
    path.write_bytes(bytes(tampered))
    calls = []
    report = download_imd_years(2023, 2023, raw_dir, manifest, fetch=_fake_fetch(calls))
    assert calls == [2023] and report.downloaded == [2023]
    assert manifest.is_current(path) and path.read_bytes()[0] == 0


def test_download_accepts_a_valid_file_even_if_the_fetcher_raised_afterwards(raw_dir, manifest):
    def fetch(year, directory):
        _fake_fetch([])(year, directory)
        raise RuntimeError("post-processing failed after the file was written")
    report = download_imd_years(2023, 2023, raw_dir, manifest, fetch=fetch)
    assert report.downloaded == [2023] and report.failed == {}


def test_download_validates_the_year_range(raw_dir, manifest):
    with pytest.raises(ValueError, match="start_year"):
        download_imd_years(2024, 2023, raw_dir, manifest, fetch=_fake_fetch([]))


def _install_fake_imdlib(monkeypatch, behaviour):
    module = types.ModuleType("imdlib")
    module.calls = []

    def get_data(var_type, start_yr, end_yr=None, fn_format=None, file_dir=None, **kwargs):
        module.calls.append((var_type, start_yr, end_yr, fn_format, file_dir, kwargs))
        behaviour(start_yr, file_dir)
    module.get_data = get_data
    monkeypatch.setitem(sys.modules, "imdlib", module)
    return module


def test_default_fetcher_calls_imdlib_yearwise_and_keeps_stdout_quiet(raw_dir, manifest, monkeypatch, capsys):
    def behaviour(year, file_dir):
        print("Downloading: rain for year", year)
        _fake_fetch([])(year, raw_dir)
    module = _install_fake_imdlib(monkeypatch, behaviour)
    report = download_imd_years(2023, 2023, raw_dir, manifest)
    assert report.downloaded == [2023]
    assert module.calls == [("rain", 2023, 2023, "yearwise", str(raw_dir), {})]
    assert capsys.readouterr().out == ""


def test_default_fetcher_reports_imdlib_swallowed_http_errors(raw_dir, manifest, monkeypatch):
    def behaviour(year, file_dir):
        print("File Download Failed! Error: 503 Server Error")  # imdlib prints and returns None
    _install_fake_imdlib(monkeypatch, behaviour)
    report = download_imd_years(2023, 2023, raw_dir, manifest)
    assert list(report.failed) == [2023]
    assert "503 Server Error" in report.failed[2023]


def test_default_fetcher_reports_missing_imdlib(raw_dir, manifest, monkeypatch):
    monkeypatch.setitem(sys.modules, "imdlib", None)  # makes `import imdlib` raise ImportError
    report = download_imd_years(2023, 2023, raw_dir, manifest)
    assert "imdlib is not installed" in report.failed[2023]


# ---------------------------------------------------------------- read_imd_year
def test_read_maps_missing_and_negative_to_nan_and_keeps_orientation(raw_dir):
    arr = _year_array(2023)
    arr[0, 5, 5] = -999.0
    arr[1, 6, 6] = -0.5  # any negative is missing
    arr[2, 7, 7] = 0.0   # zero rain is a value
    path = _write_grd(raw_dir, 2023, arr)
    out = read_imd_year(path, 2023)
    assert out.dtype == np.float32 and out.shape == (365, 129, 135)
    assert np.isnan(out[0, 5, 5]) and np.isnan(out[1, 6, 6]) and out[2, 7, 7] == 0.0
    assert (out >= 0).sum() + np.isnan(out).sum() == out.size
    # index 0 is 6.5 N and index 0 of the day axis is 1 January: no flipping anywhere
    assert out[0, WAYANAD[0], WAYANAD[1]] == 2023 * 1000 + 1
    assert out[364, WAYANAD[0], WAYANAD[1]] == 2023 * 1000 + 365
    assert out[0, 128 - WAYANAD[0], WAYANAD[1]] == 1.0  # the mirrored row holds the fill, not the plant


def test_read_handles_leap_years(raw_dir):
    path = _write_grd(raw_dir, 2024, _year_array(2024))
    out = read_imd_year(path, 2024)
    assert out.shape == (366, 129, 135)
    assert out[31 + 28, WAYANAD[0], WAYANAD[1]] == 2024 * 1000 + 60  # 29 Feb 2024 is day 60


@pytest.mark.parametrize("delta", [-4, -1, 4, 135 * 129 * 4])
def test_read_rejects_any_size_other_than_the_exact_expected_size(raw_dir, delta):
    path = imd_raw_path(raw_dir, 2023)
    path.parent.mkdir(parents=True)
    path.write_bytes(bytes(expected_size_bytes(2023) + delta))
    with pytest.raises(ImdFormatError, match="2023"):
        read_imd_year(path, 2023)


def test_read_rejects_a_leap_file_read_as_a_common_year(raw_dir):
    path = _write_grd(raw_dir, 2024, _year_array(2024))
    with pytest.raises(ImdFormatError, match="expected 25"):
        read_imd_year(path, 2023)


def test_read_missing_file_is_a_typed_error(raw_dir):
    with pytest.raises(ImdFormatError, match="not found"):
        read_imd_year(imd_raw_path(raw_dir, 2023), 2023)


# ---------------------------------------------------------------- build_imd_store
def _planted_raw(raw_dir):
    """2023 (365 d) and 2024 (366 d); everything valid except a few planted cells."""
    a23, a24 = _year_array(2023), _year_array(2024)
    a23[:, 5, 5] = a24[:, 5, 5] = -999.0            # never valid
    a23[:10, 30, 30] = a24[:10, 30, 30] = -999.0    # valid 97 % of days in both years -> covered
    a23[:10, 31, 31] = -999.0
    a24[:30, 31, 31] = -999.0                       # valid only 91.8 % in 2024 -> not covered
    _write_grd(raw_dir, 2023, a23)
    _write_grd(raw_dir, 2024, a24)


def test_build_writes_year_arrays_index_and_coverage_mask(raw_dir, tmp_path):
    _planted_raw(raw_dir)
    out_dir = tmp_path / "processed" / "rain"
    index = build_imd_store(raw_dir, out_dir, 2023, 2024)
    assert sorted(p.name for p in out_dir.iterdir()) == [
        "imd_2023.npy", "imd_2024.npy", "imd_coverage_mask.npy", "imd_index.json"]
    a24 = np.load(out_dir / "imd_2024.npy")
    assert a24.dtype == np.float32 and a24.shape == (366, 129, 135)
    assert np.isnan(a24[:, 5, 5]).all() and a24[0, WAYANAD[0], WAYANAD[1]] == 2024 * 1000 + 1
    mask = np.load(out_dir / "imd_coverage_mask.npy")
    assert mask.dtype == bool and mask.shape == (129, 135)
    assert mask[WAYANAD] and mask[30, 30] and not mask[5, 5] and not mask[31, 31]
    assert index["covered_cells"] == int(mask.sum()) == 129 * 135 - 2
    assert json.loads((out_dir / "imd_index.json").read_text(encoding="utf-8")) == index
    assert sorted(index["years"]) == ["2023", "2024"]
    assert index["years"]["2024"]["shape"] == [366, 129, 135]
    assert index["years"]["2023"]["file"] == "imd_2023.npy"
    n_nan_2023 = 365 + 10 + 10  # cell (5,5) every day, (30,30) 10 days, (31,31) 10 days
    assert index["years"]["2023"]["nan_share"] == pytest.approx(n_nan_2023 / (365 * 129 * 135))
    assert index["grid"] == {"lat_min": 6.5, "lat_max": 38.5, "lon_min": 66.5, "lon_max": 100.0,
                             "step": 0.25, "n_lat": 129, "n_lon": 135}
    assert index["coverage_min_valid_share"] == 0.95
    assert "lat index 0 = 6.5" in index["orientation"]


def test_coverage_needs_strictly_more_than_95_percent_valid_days(raw_dir, tmp_path):
    arr = _year_array(2023)   # 365 days: 347 valid = 95.07 % (covered), 346 valid = 94.79 % (not)
    arr[:365 - 347, 40, 40] = -999.0
    arr[:365 - 346, 41, 41] = -999.0
    _write_grd(raw_dir, 2023, arr)
    index = build_imd_store(raw_dir, tmp_path / "out", 2023, 2023)
    mask = np.load(tmp_path / "out" / "imd_coverage_mask.npy")
    assert mask[40, 40] and not mask[41, 41]
    assert index["covered_cells"] == 129 * 135 - 1


def test_build_fails_loudly_on_a_missing_or_malformed_year(raw_dir, tmp_path):
    _write_grd(raw_dir, 2023, _year_array(2023))
    with pytest.raises(ImdStoreError, match="2024"):
        build_imd_store(raw_dir, tmp_path / "out", 2023, 2024)
    imd_raw_path(raw_dir, 2024).write_bytes(bytes(10))
    with pytest.raises(ImdFormatError):
        build_imd_store(raw_dir, tmp_path / "out", 2023, 2024)
    with pytest.raises(ValueError, match="start_year"):
        build_imd_store(raw_dir, tmp_path / "out", 2024, 2023)


def test_a_failed_build_does_not_leave_a_half_written_index(raw_dir, tmp_path):
    _write_grd(raw_dir, 2023, _year_array(2023))
    out_dir = tmp_path / "out"
    with pytest.raises(ImdStoreError):
        build_imd_store(raw_dir, out_dir, 2023, 2024)
    assert not (out_dir / "imd_index.json").exists()


def test_rebuilding_replaces_the_store(raw_dir, tmp_path):
    _write_grd(raw_dir, 2023, _year_array(2023))
    out_dir = tmp_path / "out"
    build_imd_store(raw_dir, out_dir, 2023, 2023)
    _write_grd(raw_dir, 2023, _year_array(2023, fill=7.0))
    build_imd_store(raw_dir, out_dir, 2023, 2023)
    assert np.load(out_dir / "imd_2023.npy")[0, 0, 0] == 7.0


# ---------------------------------------------------------------- ImdGrid
@pytest.fixture
def store(raw_dir, tmp_path):
    _planted_raw(raw_dir)
    out_dir = tmp_path / "processed" / "rain"
    build_imd_store(raw_dir, out_dir, 2023, 2024)
    return out_dir


def test_nearest_index_rounds_to_the_nearest_quarter_degree(store):
    grid = ImdGrid(store)
    assert grid.nearest_index(11.5, 76.25) == WAYANAD
    assert grid.nearest_index(11.6, 76.3) == WAYANAD          # 0.1 and 0.05 deg away
    assert grid.nearest_index(11.4, 76.2) == WAYANAD
    assert grid.nearest_index(6.5, 66.5) == (0, 0)
    assert grid.nearest_index(38.5, 100.0) == (128, 134)


def test_nearest_index_ties_round_up_to_the_higher_latitude_and_longitude(store):
    grid = ImdGrid(store)
    assert grid.nearest_index(11.625, 76.375) == (21, 40)   # exactly halfway: higher index
    assert grid.nearest_index(11.6249, 76.3749) == (20, 39)
    # 0.05-degree cell centres hit ties (e.g. 6.625 = 0.025 + 6.6); floating-point noise must not flip them
    lat, lon = cell_center(latlon_to_cell(6.63, 66.63))      # centre (6.625, 66.625)
    assert grid.nearest_index(lat, lon) == (1, 1)


def test_nearest_index_is_none_outside_the_grid(store):
    grid = ImdGrid(store)
    assert grid.nearest_index(6.376, 66.5) == (0, 0)           # still nearer to the first row than to nothing
    assert grid.nearest_index(6.374, 66.5) is None
    assert grid.nearest_index(38.624, 100.0) == (128, 134)
    assert grid.nearest_index(38.625, 100.0) is None           # tie goes up, off the grid
    assert grid.nearest_index(11.5, 66.374) is None
    assert grid.nearest_index(11.5, 100.125) is None           # 100.125 ties up to column 135, off the grid
    assert grid.nearest_index(-30.0, 76.25) is None
    assert grid.nearest_index(11.5, 170.0) is None


def test_nearest_index_rejects_non_finite_coordinates(store):
    grid = ImdGrid(store)
    with pytest.raises(ValueError, match="finite"):
        grid.nearest_index(float("nan"), 76.25)
    with pytest.raises(ValueError, match="finite"):
        grid.nearest_index(11.5, float("inf"))


def test_is_covered_uses_the_coverage_mask_and_is_false_off_grid(store):
    grid = ImdGrid(store)
    assert grid.is_covered(11.5, 76.25) is True
    assert grid.is_covered(6.5 + 5 * 0.25, 66.5 + 5 * 0.25) is False      # never valid
    assert grid.is_covered(6.5 + 31 * 0.25, 66.5 + 31 * 0.25) is False    # valid < 95 % in 2024
    assert grid.is_covered(60.0, 76.25) is False
    assert grid.covered_cells == 129 * 135 - 2


def test_series_spans_years_with_the_day_label_convention(store):
    grid = ImdGrid(store)
    out = grid.series(11.5, 76.25, "2023-12-30", "2024-01-02")
    assert out.dtype == np.float32
    # array index k of a year is day-of-year k+1 and is labelled with that calendar date
    assert out.tolist() == [2023 * 1000 + 364, 2023 * 1000 + 365, 2024 * 1000 + 1, 2024 * 1000 + 2]
    leap = grid.series(11.5, 76.25, pd.Timestamp("2024-02-28"), pd.Timestamp("2024-03-01").date())
    assert leap.tolist() == [2024 * 1000 + 59, 2024 * 1000 + 60, 2024 * 1000 + 61]
    assert grid.series(11.5, 76.25, "2024-12-31", "2024-12-31").tolist() == [2024 * 1000 + 366]


def test_series_is_nan_where_the_grid_point_has_no_data_or_is_off_grid(store):
    grid = ImdGrid(store)
    dead = grid.series(6.5 + 5 * 0.25, 66.5 + 5 * 0.25, "2023-12-31", "2024-01-01")
    assert np.isnan(dead).all() and dead.shape == (2,)
    partial = grid.series(6.5 + 30 * 0.25, 66.5 + 30 * 0.25, "2023-01-09", "2023-01-12")
    assert np.isnan(partial[:2]).all() and partial[2:].tolist() == [1.0, 1.0]   # first 10 days are -999
    off = grid.series(60.0, 76.25, "2023-06-01", "2023-06-03")
    assert np.isnan(off).all() and off.shape == (3,)


def test_series_raises_for_years_not_in_the_store_and_bad_ranges(store):
    grid = ImdGrid(store)
    with pytest.raises(ImdStoreError, match="2025"):
        grid.series(11.5, 76.25, "2024-12-30", "2025-01-02")
    with pytest.raises(ImdStoreError, match="2022"):
        grid.series(11.5, 76.25, "2022-12-31", "2023-01-01")
    with pytest.raises(ValueError, match="start_date"):
        grid.series(11.5, 76.25, "2024-01-02", "2024-01-01")


def test_a_year_listed_in_the_index_but_missing_on_disk_is_an_error_not_silent_nan(store):
    (store / "imd_2024.npy").unlink()
    grid = ImdGrid(store)
    with pytest.raises(ImdStoreError, match="imd_2024.npy"):
        grid.series(11.5, 76.25, "2024-01-01", "2024-01-02")
    assert grid.series(11.5, 76.25, "2023-01-01", "2023-01-02").shape == (2,)


def test_year_arrays_are_memory_mapped_lazily(store):
    grid = ImdGrid(store)
    assert grid._arrays == {}
    grid.series(11.5, 76.25, "2024-01-01", "2024-01-02")
    assert set(grid._arrays) == {2024}
    assert isinstance(grid._arrays[2024], np.memmap)


def test_cell_series_uses_the_0p05_cell_centre(store):
    grid = ImdGrid(store)
    cell = latlon_to_cell(11.52, 76.27)    # centre (11.525, 76.275) -> nearest IMD point (11.5, 76.25)
    out = grid.cell_series(cell, "2024-07-29", "2024-07-30")
    assert out.tolist() == [2024 * 1000 + 211, 2024 * 1000 + 212]


def test_grid_without_a_store_is_a_typed_error(tmp_path):
    with pytest.raises(ImdStoreError, match="imd_index.json"):
        ImdGrid(tmp_path / "nowhere")


def test_module_constants_describe_the_verified_grid():
    assert (imd.N_LAT, imd.N_LON, imd.STEP) == (129, 135, 0.25)
    assert imd.LAT_MIN + (imd.N_LAT - 1) * imd.STEP == 38.5
    assert imd.LON_MIN + (imd.N_LON - 1) * imd.STEP == 100.0
    assert issubclass(ImdFormatError, imd.ImdError) and issubclass(ImdDownloadError, imd.ImdError)
    assert issubclass(ImdStoreError, imd.ImdError)


# ---------------------------------------------------------------- CLI
def test_cli_downloads_builds_and_prints_a_compact_summary(isolated_data_root, tmp_path, capsys):
    from aetherguard.ingest.imd_build import main
    raw, out = isolated_data_root / "raw" / "imd", isolated_data_root / "processed" / "rain"
    common = ["--raw-dir", str(raw), "--out-dir", str(out), "--manifest", str(tmp_path / "m.jsonl")]
    assert main(["--start", "2023", "--end", "2024", *common], fetch=_fake_fetch([])) == 0
    first = capsys.readouterr().out
    assert "2 fetched" in first and "0 failed" in first
    assert "2 years 2023..2024" in first and f"{129 * 135} of {129 * 135} grid points" in first
    assert (out / "imd_index.json").is_file()
    assert main(["--start", "2023", "--end", "2024", *common], fetch=_fake_fetch([])) == 0
    assert "0 fetched, 2 already present" in capsys.readouterr().out
    assert main(["--start", "2022", "--end", "2022", *common], fetch=_fake_fetch([], failing={2022})) == 1
    captured = capsys.readouterr()
    assert "FAILED 2022" in captured.out and "not building" in captured.err


# ---------------------------------------------------------------- real data (python -m aetherguard.ingest.imd_build)
REAL_RAW = PROJECT_ROOT / "data" / "raw" / "imd"
REAL_STORE = PROJECT_ROOT / "data" / "processed" / "rain"
POSITIVES = PROJECT_ROOT / "data" / "processed" / "splits" / "positive_cell_days.parquet"


@pytest.fixture(scope="module")
def real_grid():
    if not (REAL_STORE / "imd_index.json").is_file():
        pytest.skip("real IMD store not built (python -m aetherguard.ingest.imd_build)")
    return ImdGrid(REAL_STORE)


@pytest.mark.realdata
def test_real_raw_files_have_the_exact_expected_size():
    missing = [y for y in range(2007, 2025) if not imd_raw_path(REAL_RAW, y).is_file()]
    if missing:
        pytest.skip(f"real IMD files missing for {missing}")
    for year in range(2007, 2025):
        assert imd_raw_path(REAL_RAW, year).stat().st_size == expected_size_bytes(year) == \
            days_in_year(year) * 129 * 135 * 4


@pytest.mark.realdata
def test_real_wayanad_2024_matches_the_phase0_audit(real_grid):
    out = real_grid.series(11.5, 76.25, "2024-07-29", "2024-07-30")
    assert out[1] == pytest.approx(179.24, abs=0.01)
    assert out[0] == pytest.approx(6.6, abs=0.05)


@pytest.mark.realdata
def test_real_nepal_points_are_nan_and_uncovered_and_dehradun_is_covered(real_grid):
    for lat, lon in [(27.75, 85.25), (28.25, 84.0)]:   # Kathmandu, Pokhara
        year = real_grid.series(lat, lon, "2024-01-01", "2024-12-31")
        assert year.shape == (366,) and np.isnan(year).all()
        assert real_grid.is_covered(lat, lon) is False
    assert real_grid.is_covered(30.25, 78.0) is True   # Dehradun
    mask = np.load(REAL_STORE / "imd_coverage_mask.npy")
    print(f"\ncoverage mask {mask.shape}, covered cells {int(mask.sum())} of {mask.size}")
    assert mask.shape == (129, 135) and real_grid.covered_cells == int(mask.sum()) > 0


@pytest.mark.realdata
def test_real_positive_cell_days_coverage_by_region_and_split(real_grid):
    if not POSITIVES.is_file():
        pytest.skip("real positive cell-days not built (python -m aetherguard.splits.build)")
    positives = pd.read_parquet(POSITIVES)
    centres = [cell_center(int(c)) for c in positives["cell_id"]]
    positives["covered"] = [real_grid.is_covered(lat, lon) for lat, lon in centres]
    positives["valid_on_day"] = [
        bool(np.isfinite(real_grid.cell_series(int(c), d, d)[0]))
        for c, d in zip(positives["cell_id"], positives["event_date"])
    ]
    table = positives.groupby(["region", "split"]).agg(
        cell_days=("cell_id", "size"), covered=("covered", "sum"), valid_on_event_date=("valid_on_day", "sum"))
    print("\npositive cell-days on IMD-covered cells\n" + table.to_string())
    assert int(table["cell_days"].sum()) == len(positives)
