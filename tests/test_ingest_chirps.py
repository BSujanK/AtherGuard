import http.server
import threading
from datetime import date

import numpy as np
import pytest

from aetherguard import grid
from aetherguard.config import load_config
from aetherguard.ingest import chirps
from aetherguard.manifest import Manifest


def _cfg(**overrides):
    cfg = {"full_years": {"start": 2007, "end": 2008}, "extra_ranges": [], "domain_bbox": {
        "lat_min": 8.0, "lat_max": 36.0, "lon_min": 72.0, "lon_max": 98.0}}
    cfg.update(overrides)
    return cfg


# ---------------------------------------------------------------- needed dates

def test_needed_dates_full_years_are_inclusive_and_sorted_unique():
    days = chirps.needed_dates(_cfg())
    assert days[0] == date(2007, 1, 1) and days[-1] == date(2008, 12, 31)
    assert len(days) == 365 + 366 and days == sorted(set(days))


def test_needed_dates_merges_overlapping_ranges_without_duplicates():
    days = chirps.needed_dates(_cfg(extra_ranges=[
        {"start": "2008-12-30", "end": "2009-01-02"}, {"start": "2009-01-01", "end": "2009-01-03"}]))
    assert days[-3:] == [date(2009, 1, 1), date(2009, 1, 2), date(2009, 1, 3)]
    assert len(days) == 365 + 366 + 3


def test_needed_dates_for_the_real_config_is_about_4566():
    days = chirps.needed_dates(load_config("ingest"))
    assert len(days) == 4383 + 107 + 76
    assert date(2024, 7, 30) in days and date(2023, 6, 16) in days and date(2019, 6, 1) not in days


# ---------------------------------------------------------------- pixel grid

def test_cell_centres_equal_chirps_pixel_centres():
    rng = np.random.default_rng(0)
    lat_idx = rng.integers(800, 2800, 500)
    lon_idx = rng.integers(0, 7200, 500)
    ids = lat_idx * grid.ID_STRIDE + lon_idx
    row, col = chirps.cell_to_chirps_pixel(ids)
    lat_c, lon_c = grid.cell_center(ids)
    assert np.abs(lat_c - (49.975 - 0.05 * row)).max() < 1e-9
    assert np.abs(lon_c - (-179.975 + 0.05 * col)).max() < 1e-9


def test_wayanad_reference_cell_maps_to_its_pixel():
    cid = grid.latlon_to_cell(11.55, 76.13)
    assert chirps.cell_to_chirps_pixel(cid) == (2799 - 2031, 5122)


def test_chirps_extremes_and_out_of_coverage_cells():
    assert chirps.cell_to_chirps_pixel(2799 * grid.ID_STRIDE) == (0, 0)
    assert chirps.cell_to_chirps_pixel(800 * grid.ID_STRIDE + 7199) == (1999, 7199)
    for bad in (2800 * grid.ID_STRIDE, 799 * grid.ID_STRIDE):
        with pytest.raises(ValueError):
            chirps.cell_to_chirps_pixel(bad)


def test_domain_window_for_the_config_bbox():
    win = chirps.domain_window(_cfg())
    assert (win["n_rows"], win["n_cols"]) == (560, 520)
    assert win["col_off"] == 5040 and win["row_off"] == 280  # row 280 = lat 35.975 (north edge 36.0)
    assert -90 + (win["lat_idx_lo"] + 0.5) * 0.05 == pytest.approx(8.025)
    with pytest.raises(ValueError):
        chirps.domain_window(_cfg(domain_bbox={"lat_min": 8.0, "lat_max": 60.0, "lon_min": 72.0, "lon_max": 98.0}))
    with pytest.raises(ValueError):
        chirps.domain_window(_cfg(domain_bbox={"lat_min": 8.013, "lat_max": 36.0, "lon_min": 72.0, "lon_max": 98.0}))


# ---------------------------------------------------------------- download

class _Server:
    def __init__(self):
        self.hits: dict[str, int] = {}
        self.lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.not_found: set[str] = set()
        self.flaky_once: set[str] = set()
        self.always_fail: set[str] = set()
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                with outer.lock:
                    outer.hits[self.path] = outer.hits.get(self.path, 0) + 1
                    outer.active += 1
                    outer.max_active = max(outer.max_active, outer.active)
                    n = outer.hits[self.path]
                try:
                    status, body = 200, self.path.encode() * 20
                    if any(tag in self.path for tag in outer.not_found):
                        status, body = 404, b""
                    elif any(tag in self.path for tag in outer.always_fail):
                        status, body = 503, b""
                    elif any(tag in self.path for tag in outer.flaky_once) and n == 1:
                        status, body = 503, b""
                    self.send_response(status)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                finally:
                    with outer.lock:
                        outer.active -= 1

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}" + "/{y}/chirps-v2.0.{y}.{m}.{d}.tif.gz"


@pytest.fixture
def server():
    srv = _Server()
    yield srv
    srv.httpd.shutdown()
    srv.httpd.server_close()


def _env(tmp_path):
    root = tmp_path / "data"
    raw = root / "raw" / "chirps"
    return raw, Manifest(tmp_path / "manifest.jsonl", root)


def _days(n, start=date(2020, 1, 1)):
    return [date.fromordinal(start.toordinal() + i) for i in range(n)]


def _dl(dates, raw, manifest, server, **kw):
    kw.setdefault("retries", 2)
    kw.setdefault("backoff", 0)
    kw.setdefault("retry_pause", 0)
    return chirps.download_chirps(dates, raw, manifest, workers=kw.pop("workers", 3),
                                  url_template=server.url, **kw)


def test_download_writes_per_year_paths_and_reconciles(server, tmp_path):
    raw, manifest = _env(tmp_path)
    days = _days(10, date(2019, 12, 28))  # spans two years
    summary = _dl(days, raw, manifest, server)
    assert summary == {"ok": 10, "already_present": 0, "missing": 0, "failed": 0}
    assert (raw / "2019" / "chirps-v2.0.2019.12.31.tif.gz").exists()
    assert (raw / "2020" / "chirps-v2.0.2020.01.03.tif.gz").exists()
    assert len(manifest.entries()) == 10
    assert manifest.verify() == []
    assert "chirps" in next(iter(manifest.entries().values())).licence.lower()


def test_rerun_skips_files_that_are_manifest_current(server, tmp_path):
    raw, manifest = _env(tmp_path)
    days = _days(8)
    _dl(days, raw, manifest, server)
    hits_before = sum(server.hits.values())
    summary = _dl(days, raw, manifest, server)
    assert summary == {"ok": 0, "already_present": 8, "missing": 0, "failed": 0}
    assert sum(server.hits.values()) == hits_before


def test_resume_after_partial_run_fetches_only_the_rest(server, tmp_path):
    raw, manifest = _env(tmp_path)
    days = _days(12)
    _dl(days[:5], raw, manifest, server)
    summary = _dl(days, raw, manifest, server)
    assert summary == {"ok": 7, "already_present": 5, "missing": 0, "failed": 0}


def test_404_is_recorded_as_missing_and_the_run_continues(server, tmp_path):
    raw, manifest = _env(tmp_path)
    days = _days(6)
    server.not_found = {"2020.01.03"}
    summary = _dl(days, raw, manifest, server)
    assert summary == {"ok": 5, "already_present": 0, "missing": 1, "failed": 0}
    assert chirps._read_dates(raw / chirps.MISSING_DATES_FILE) == {"2020-01-03"}
    assert not (raw / "2020" / "chirps-v2.0.2020.01.03.tif.gz").exists()
    assert server.hits["/2020/chirps-v2.0.2020.01.03.tif.gz"] == 1  # 404 is not retried


def test_missing_record_is_dropped_once_the_file_arrives(server, tmp_path):
    raw, manifest = _env(tmp_path)
    days = _days(3)
    server.not_found = {"2020.01.02"}
    _dl(days, raw, manifest, server)
    server.not_found = set()
    summary = _dl(days, raw, manifest, server)
    assert summary["ok"] == 1 and summary["already_present"] == 2
    assert chirps._read_dates(raw / chirps.MISSING_DATES_FILE) == set()


def test_transient_failure_is_retried_at_the_end(server, tmp_path):
    raw, manifest = _env(tmp_path)
    days = _days(4)
    server.flaky_once = {"2020.01.02"}
    summary = _dl(days, raw, manifest, server, retries=1)  # first pass gives up after one try
    assert summary == {"ok": 4, "already_present": 0, "missing": 0, "failed": 0}
    assert server.hits["/2020/chirps-v2.0.2020.01.02.tif.gz"] == 2
    assert chirps._read_dates(raw / chirps.FAILED_DATES_FILE) == set()


def test_persistent_failure_is_reported_and_recorded(server, tmp_path):
    raw, manifest = _env(tmp_path)
    days = _days(5)
    server.always_fail = {"2020.01.04"}
    summary = _dl(days, raw, manifest, server, retries=2)
    assert summary == {"ok": 4, "already_present": 0, "missing": 0, "failed": 1}
    assert chirps._read_dates(raw / chirps.FAILED_DATES_FILE) == {"2020-01-04"}
    assert sum(summary.values()) == len(days)
    text = (raw / chirps.PROGRESS_LOG).read_text(encoding="utf-8")
    assert "failed 2020-01-04" in text and "HTTP 503" in text


def test_runs_stop_after_repeated_failures_and_still_reconcile(server, tmp_path):
    raw, manifest = _env(tmp_path)
    days = _days(40)
    server.always_fail = {"/2020/"}
    summary = _dl(days, raw, manifest, server, workers=1, retries=1, abort_after=5)
    assert summary == {"ok": 0, "already_present": 0, "missing": 0, "failed": 40}
    assert sum(server.hits.values()) <= 6  # stopped asking after 5 consecutive failures


def test_parallelism_never_exceeds_the_worker_count(server, tmp_path):
    raw, manifest = _env(tmp_path)
    _dl(_days(40), raw, manifest, server, workers=2)
    assert server.max_active <= 2


def test_progress_line_every_100_files(server, tmp_path):
    raw, manifest = _env(tmp_path)
    _dl(_days(230), raw, manifest, server, workers=6)
    lines = (raw / chirps.PROGRESS_LOG).read_text(encoding="utf-8").splitlines()
    progress = [line for line in lines if "download: " in line]
    assert [line.split("download: ")[1].split(" done")[0] for line in progress] == ["100/230", "200/230", "230/230"]


def test_duplicate_dates_are_rejected(server, tmp_path):
    raw, manifest = _env(tmp_path)
    with pytest.raises(ValueError):
        _dl([date(2020, 1, 1), date(2020, 1, 1)], raw, manifest, server)


# ---------------------------------------------------------------- crop and store

def _write_chirps_gz(path, fill, marks=(), nodata_tag=False):
    """A synthetic global CHIRPS-shaped day: `fill` everywhere, (row, col, value) marks on top."""
    import gzip

    import rasterio
    from affine import Affine

    array = np.full((chirps.CHIRPS_ROWS, chirps.CHIRPS_COLS), fill, dtype=np.float32)
    for row, col, value in marks:
        array[row, col] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    tif = path.with_suffix("")
    with rasterio.open(tif, "w", driver="GTiff", width=chirps.CHIRPS_COLS, height=chirps.CHIRPS_ROWS, count=1,
                       dtype="float32", transform=Affine(0.05, 0.0, -180.0, 0.0, -0.05, 50.0),
                       nodata=-9999.0 if nodata_tag else None) as dst:
        dst.write(array, 1)
    with tif.open("rb") as source, gzip.open(path, "wb", compresslevel=1) as target:
        target.write(source.read())
    tif.unlink()


WAYANAD = grid.latlon_to_cell(11.55, 76.13)
WAYANAD_ROW, WAYANAD_COL = chirps.cell_to_chirps_pixel(WAYANAD)
SMALL = _cfg(full_years={"start": 2020, "end": 2020}, extra_ranges=[])


def _raw_tree(tmp_path, days, values, missing=(), sea_fill=-9999.0, nodata_tag=False):
    raw = tmp_path / "raw"
    for d, v in zip(days, values):
        if d in missing:
            continue
        _write_chirps_gz(chirps.raw_path(raw, d), sea_fill, [(WAYANAD_ROW, WAYANAD_COL, v)], nodata_tag)
    if missing:
        chirps._write_dates(raw / chirps.MISSING_DATES_FILE, {d.isoformat() for d in missing})
    return raw


def test_crop_reproduces_known_pixels_and_masks_negatives(tmp_path):
    days = _days(4, date(2020, 3, 1))
    raw = _raw_tree(tmp_path, days, [0.0, 28.42, 85.25, 12.0])
    index = chirps.crop_chirps(days, raw, tmp_path / "out", SMALL, workers=2)
    store = chirps.ChirpsStore(tmp_path / "out")
    series = store.cell_series(WAYANAD, date(2020, 3, 1), date(2020, 3, 4))
    assert series.dtype == np.float32
    bound = index["float16_abs_bound_at_max"]
    assert np.allclose(series, [0.0, 28.42, 85.25, 12.0], atol=bound, rtol=0)
    assert index["rows"] == 560 and index["cols"] == 520
    # a pixel that is -9999 in the file is NaN, not 0 and not negative
    other = grid.latlon_to_cell(12.5, 77.5)
    assert np.isnan(store.cell_series(other, date(2020, 3, 1), date(2020, 3, 4))).all()
    assert index["nan_share"] == pytest.approx(1 - 1 / (560 * 520), abs=1e-9)
    assert index["max_value"] == pytest.approx(85.25, abs=0.05)
    assert index["float16_relative_bound"] == 2 ** -11


def test_crop_files_shape_dtype_and_dates(tmp_path):
    import json
    days = _days(5, date(2020, 12, 30))
    raw = _raw_tree(tmp_path, days, [1, 2, 3, 4, 5])
    index = chirps.crop_chirps(days, raw, tmp_path / "out", _cfg())
    a2020 = np.load(tmp_path / "out" / "chirps_2020.npy", mmap_mode="r")
    a2021 = np.load(tmp_path / "out" / "chirps_2021.npy", mmap_mode="r")
    assert a2020.shape == (2, 560, 520) and a2021.shape == (3, 560, 520)
    assert a2020.dtype == np.float16
    assert index["days_per_year"] == {"2020": 2, "2021": 3}
    stamps = json.loads((tmp_path / "out" / "chirps_2021_dates.json").read_text())
    assert stamps == [d.isoformat() for d in days if d.year == 2021]
    assert (tmp_path / "out" / "chirps_index.json").exists()


def test_missing_day_is_nan_listed_and_not_in_store(tmp_path):
    days = _days(4, date(2020, 3, 1))
    raw = _raw_tree(tmp_path, days, [5.0, 6.0, 7.0, 8.0], missing={days[1]})
    index = chirps.crop_chirps(days, raw, tmp_path / "out", SMALL)
    assert index["missing_dates"] == ["2020-03-02"]
    store = chirps.ChirpsStore(tmp_path / "out")
    assert not store.has_date(days[1]) and store.has_date(days[0])
    assert store.dates() == [days[0], days[2], days[3]]
    series = store.cell_series(WAYANAD, days[0], days[3])
    assert series[0] == 5.0 and np.isnan(series[1]) and series[2] == 7.0


def test_crop_refuses_days_with_neither_file_nor_404_record(tmp_path):
    days = _days(3, date(2020, 3, 1))
    raw = _raw_tree(tmp_path, days, [1, 2, 3])
    chirps.raw_path(raw, days[2]).unlink()
    with pytest.raises(chirps.ChirpsIncompleteError, match="2020-03-03"):
        chirps.crop_chirps(days, raw, tmp_path / "out", SMALL)
    assert not (tmp_path / "out" / "chirps_index.json").exists()


def test_all_nan_day_that_has_a_file_is_an_error(tmp_path):
    days = _days(2, date(2020, 3, 1))
    raw = tmp_path / "raw"
    _write_chirps_gz(chirps.raw_path(raw, days[0]), -9999.0, [(WAYANAD_ROW, WAYANAD_COL, 1.0)])
    _write_chirps_gz(chirps.raw_path(raw, days[1]), -9999.0)  # nothing but nodata
    with pytest.raises(ValueError, match="2020-03-02"):
        chirps.crop_chirps(days, raw, tmp_path / "out", SMALL)


def test_value_beyond_float16_is_an_error(tmp_path):
    days = _days(1, date(2020, 3, 1))
    raw = _raw_tree(tmp_path, days, [70000.0])
    with pytest.raises(ValueError, match="float16"):
        chirps.crop_chirps(days, raw, tmp_path / "out", SMALL)


def test_declared_nodata_is_also_masked(tmp_path):
    days = _days(1, date(2020, 3, 1))
    raw = _raw_tree(tmp_path, days, [3.0], nodata_tag=True)
    chirps.crop_chirps(days, raw, tmp_path / "out", SMALL)
    store = chirps.ChirpsStore(tmp_path / "out")
    assert store.cell_series(WAYANAD, days[0], days[0])[0] == 3.0
    assert np.isnan(store.cell_series(grid.latlon_to_cell(12.5, 77.5), days[0], days[0])).all()


def test_crop_is_resumable_and_recrops_when_the_missing_set_changes(tmp_path):
    days = _days(3, date(2020, 3, 1))
    raw = _raw_tree(tmp_path, days, [1.0, 2.0, 3.0], missing={days[1]})
    chirps.crop_chirps(days, raw, tmp_path / "out", SMALL)
    stamp = (tmp_path / "out" / "chirps_2020.npy").stat().st_mtime_ns
    chirps.crop_chirps(days, raw, tmp_path / "out", SMALL)
    assert (tmp_path / "out" / "chirps_2020.npy").stat().st_mtime_ns == stamp  # untouched
    _write_chirps_gz(chirps.raw_path(raw, days[1]), -9999.0, [(WAYANAD_ROW, WAYANAD_COL, 2.0)])
    chirps._write_dates(raw / chirps.MISSING_DATES_FILE, set())
    index = chirps.crop_chirps(days, raw, tmp_path / "out", SMALL)
    assert index["missing_dates"] == []
    assert chirps.ChirpsStore(tmp_path / "out").cell_series(WAYANAD, days[1], days[1])[0] == 2.0


def test_crop_recrops_when_the_needed_dates_change(tmp_path):
    days = _days(3, date(2020, 3, 1))
    raw = _raw_tree(tmp_path, days, [1.0, 2.0, 3.0])
    chirps.crop_chirps(days[:2], raw, tmp_path / "out", SMALL)
    index = chirps.crop_chirps(days, raw, tmp_path / "out", SMALL)
    assert index["days_per_year"] == {"2020": 3}


def test_unreadable_gz_raises_a_named_error(tmp_path):
    days = _days(1, date(2020, 3, 1))
    raw = tmp_path / "raw"
    bad = chirps.raw_path(raw, days[0])
    bad.parent.mkdir(parents=True)
    bad.write_bytes(b"this is not a gzip file")
    with pytest.raises(chirps.ChirpsReadError, match="chirps-v2.0.2020.03.01"):
        chirps.crop_chirps(days, raw, tmp_path / "out", SMALL)


def test_fallback_extraction_is_used_when_vsigzip_fails(tmp_path, monkeypatch):
    days = _days(1, date(2020, 3, 1))
    raw = _raw_tree(tmp_path, days, [9.0])
    real = chirps._read_raster_window
    seen = []

    def vsigzip_broken(tif_path, window, path):
        seen.append(tif_path)
        if tif_path.startswith("/vsigzip/"):
            from rasterio.errors import RasterioIOError
            raise RasterioIOError("vsigzip unavailable")
        return real(tif_path, window, path)

    monkeypatch.setattr(chirps, "_read_raster_window", vsigzip_broken)
    chirps.crop_chirps(days, raw, tmp_path / "out", SMALL)
    assert seen[0].startswith("/vsigzip/") and seen[1].endswith("day.tif")
    assert chirps.ChirpsStore(tmp_path / "out").cell_series(WAYANAD, days[0], days[0])[0] == 9.0


def test_wrong_raster_shape_is_an_error(tmp_path):
    import gzip

    import rasterio
    from affine import Affine
    days = _days(1, date(2020, 3, 1))
    raw = tmp_path / "raw"
    path = chirps.raw_path(raw, days[0])
    path.parent.mkdir(parents=True)
    tif = path.with_suffix("")
    with rasterio.open(tif, "w", driver="GTiff", width=100, height=100, count=1, dtype="float32",
                       transform=Affine(0.05, 0.0, -180.0, 0.0, -0.05, 50.0)) as dst:
        dst.write(np.ones((100, 100), dtype=np.float32), 1)
    with tif.open("rb") as source, gzip.open(path, "wb") as target:
        target.write(source.read())
    with pytest.raises(chirps.ChirpsReadError, match="expected"):
        chirps.crop_chirps(days, raw, tmp_path / "out", SMALL)


def test_store_cell_series_is_nan_outside_the_stored_dates_and_rejects_foreign_cells(tmp_path):
    days = _days(3, date(2020, 3, 1))
    raw = _raw_tree(tmp_path, days, [1.0, 2.0, 3.0])
    chirps.crop_chirps(days, raw, tmp_path / "out", SMALL)
    store = chirps.ChirpsStore(tmp_path / "out")
    series = store.cell_series(WAYANAD, date(2020, 2, 28), date(2020, 3, 5))
    assert len(series) == 7
    assert np.isnan(series[:2]).all() and list(series[2:5]) == [1.0, 2.0, 3.0] and np.isnan(series[5:]).all()
    assert np.isnan(store.cell_series(WAYANAD, "2019-01-01", "2019-01-03")).all()  # year not in the store
    with pytest.raises(ValueError, match="outside the stored domain"):
        store.cell_series(grid.latlon_to_cell(40.0, 76.0), days[0], days[0])
    with pytest.raises(ValueError):
        store.cell_series(WAYANAD, days[2], days[0])


def test_store_spans_years_and_accepts_iso_strings(tmp_path):
    days = [date(2020, 12, 31), date(2021, 1, 1)]
    raw = _raw_tree(tmp_path, days, [4.0, 5.0])
    chirps.crop_chirps(days, raw, tmp_path / "out", _cfg())
    store = chirps.ChirpsStore(tmp_path / "out")
    assert list(store.cell_series(WAYANAD, "2020-12-30", "2021-01-02")[1:3]) == [4.0, 5.0]
    assert store.has_date("2021-01-01") and not store.has_date("2021-01-02")


@pytest.mark.realdata
def test_real_wayanad_pixel_matches_the_phase0_audit():
    from aetherguard.config import data_root
    store = chirps.ChirpsStore(data_root() / "processed" / "rain")
    series = store.cell_series(WAYANAD, date(2024, 7, 28), date(2024, 7, 31))
    print("Wayanad CHIRPS 2024-07-28..31:", series.tolist())
    assert np.allclose(series, [0.0, 28.42, 0.0, 85.25], atol=0.05, rtol=0)


# ---------------------------------------------------------------- CLI

def _patch_cli(monkeypatch, tmp_path, download_summary):
    from aetherguard.ingest import chirps_build
    root = tmp_path / "data"
    monkeypatch.setenv("AETHERGUARD_DATA_DIR", str(root))
    calls = {"download": [], "crop": []}

    def fake_download(dates, raw_dir, manifest, workers, **kwargs):
        calls["download"].append((len(dates), raw_dir, workers))
        return download_summary

    def fake_crop(dates, raw_dir, out_dir, cfg, **kwargs):
        calls["crop"].append((len(dates), raw_dir, out_dir))
        return {"rows": 560, "cols": 520, "days_per_year": {"2007": 365}, "missing_dates": [],
                "nan_share": 0.5, "max_value": 100.0}

    monkeypatch.setattr(chirps, "download_chirps", fake_download)
    monkeypatch.setattr(chirps, "crop_chirps", fake_crop)
    return chirps_build, calls, root


OK_SUMMARY = {"ok": 4566, "already_present": 0, "missing": 0, "failed": 0}


def test_cli_downloads_then_crops_with_the_configured_defaults(monkeypatch, tmp_path, capsys):
    chirps_build, calls, root = _patch_cli(monkeypatch, tmp_path, OK_SUMMARY)
    assert chirps_build.main(["--manifest", str(tmp_path / "m.jsonl")]) == 0
    assert calls["download"] == [(4566, root / "raw" / "chirps", 6)]
    assert calls["crop"] == [(4566, root / "raw" / "chirps", root / "processed" / "rain")]
    out = capsys.readouterr().out
    assert "4566" in out and "560x520" in out


def test_cli_stage_flags(monkeypatch, tmp_path):
    chirps_build, calls, root = _patch_cli(monkeypatch, tmp_path, OK_SUMMARY)
    chirps_build.main(["--download-only", "--manifest", str(tmp_path / "m.jsonl")])
    assert len(calls["download"]) == 1 and calls["crop"] == []
    chirps_build.main(["--crop-only", "--manifest", str(tmp_path / "m.jsonl")])
    assert len(calls["download"]) == 1 and len(calls["crop"]) == 1
    with pytest.raises(SystemExit):
        chirps_build.main(["--download-only", "--crop-only"])


def test_cli_rejects_more_workers_than_configured(monkeypatch, tmp_path):
    chirps_build, calls, root = _patch_cli(monkeypatch, tmp_path, OK_SUMMARY)
    for bad in ("7", "0"):
        with pytest.raises(SystemExit):
            chirps_build.main(["--workers", bad, "--manifest", str(tmp_path / "m.jsonl")])
    assert calls["download"] == []
    chirps_build.main(["--workers", "2", "--manifest", str(tmp_path / "m.jsonl")])
    assert calls["download"][0][2] == 2


def test_cli_does_not_crop_after_failed_downloads(monkeypatch, tmp_path, capsys):
    chirps_build, calls, root = _patch_cli(monkeypatch, tmp_path, {**OK_SUMMARY, "ok": 4565, "failed": 1})
    assert chirps_build.main(["--manifest", str(tmp_path / "m.jsonl")]) == 1
    assert calls["crop"] == []
    assert "re-run the same command" in capsys.readouterr().err
