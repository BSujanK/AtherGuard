"""Half-hourly IMERG ingest: IMD-day window, subset URL, daily reduction, resumable build.

Everything runs against a local HTTP server that imitates CMR (granule search) and Hyrax (DAP4 subset): the subset
bodies are synthetic netCDF4 files in the layout measured by the W3 pilot (group /Grid, variable `precipitation`
shaped (time, lon, lat), mm/h, fill value -9999.9). No test touches the network.
"""
import http.server
import json
import threading
import time
from datetime import date, datetime, timedelta, timezone
from urllib.parse import parse_qs, unquote, urlparse

import h5netcdf
import numpy as np
import pytest

from aetherguard.ingest import imerg, imerg_hh
from aetherguard.manifest import Manifest

ROWS, COLS = 280, 260
FILL = -9999.900390625
HALF = timedelta(minutes=30)
CONCEPTS = {"late": imerg_hh.CONCEPT_IDS["late"], "early": imerg_hh.CONCEPT_IDS["early"]}


def utc(year, month, day, hour=0, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def imd_start(day):
    """First half-hour of the IMD day `day`: 03:00 UTC on the previous calendar day."""
    return utc(day.year, day.month, day.day, 3) - timedelta(days=1)


def stack(value=0.0):
    return np.full((imerg_hh.HALF_HOURS, ROWS, COLS), value, dtype=np.float32)


# ------------------------------------------------------------------------------------------ reduce_day

def brute_force(series, windows):
    """Reference: max over the rolling sums of `windows` consecutive half-hours, times 0.5 h."""
    sums = [series[i:i + windows].sum() * 0.5 for i in range(len(series) - windows + 1)]
    return max(sums)


def test_rolling_maxima_are_sums_of_2_6_and_12_consecutive_half_hours():
    rng = np.random.default_rng(3)
    fields = (rng.gamma(0.4, 4.0, size=(48, ROWS, COLS))).astype(np.float32)
    out = imerg_hh.reduce_day(fields)
    for row, col in [(0, 0), (10, 200), (279, 259), (140, 130)]:
        series = fields[:, row, col].astype(np.float64)
        assert out["max1h"][row, col] == pytest.approx(brute_force(series, 2), rel=1e-5)
        assert out["max3h"][row, col] == pytest.approx(brute_force(series, 6), rel=1e-5)
        assert out["max6h"][row, col] == pytest.approx(brute_force(series, 12), rel=1e-5)


def test_outputs_are_float32_maps_with_the_documented_orientation():
    fields = stack()
    fields[20:22, 10, 200] = 8.0            # one pixel: row 10 (latitude index), col 200 (longitude index)
    out = imerg_hh.reduce_day(fields)
    assert set(out) == {"max1h", "max3h", "max6h", "wet_hours", "n_halfhours"}
    for name, array in out.items():
        assert array.shape == (ROWS, COLS) and array.dtype == np.float32, name
    assert out["max1h"][10, 200] == pytest.approx(8.0)          # 2 half-hours x 8 mm/h x 0.5 h
    assert out["max1h"][200, 10] == 0.0                  # the transposed index is untouched
    assert np.count_nonzero(out["max1h"]) == 1
    assert out["wet_hours"][10, 200] == pytest.approx(1.0)
    assert out["n_halfhours"].min() == out["n_halfhours"].max() == 48


def test_a_dry_pixel_is_zero_not_nan():
    out = imerg_hh.reduce_day(stack())
    for name in ("max1h", "max3h", "max6h", "wet_hours"):
        assert (out[name] == 0.0).all(), name


def test_windows_never_cross_the_day_boundary():
    fields = stack()
    fields[0, 5, 5] = 10.0                  # first half-hour of the day
    fields[47, 5, 5] = 10.0                 # last half-hour of the day, 47 half-hours later
    out = imerg_hh.reduce_day(fields)
    assert out["max1h"][5, 5] == pytest.approx(5.0)             # one spike per window, never both
    assert out["max6h"][5, 5] == pytest.approx(5.0)
    assert out["wet_hours"][5, 5] == pytest.approx(1.0)


def test_nan_half_hour_makes_the_pixels_maxima_nan_never_zero():
    fields = stack(1.0)
    fields[17, 3, 4] = np.nan
    out = imerg_hh.reduce_day(fields)
    for name in ("max1h", "max3h", "max6h", "wet_hours"):
        assert np.isnan(out[name][3, 4]), name
        assert np.isfinite(out[name][3, 5]) and np.isfinite(out[name][4, 4]), name   # neighbours unaffected
    assert out["n_halfhours"][3, 4] == 47 and out["n_halfhours"][3, 5] == 48
    assert out["max1h"][3, 5] == pytest.approx(1.0)


def test_an_all_nan_pixel_is_nan_everywhere():
    fields = stack(2.0)
    fields[:, 7, 7] = np.nan
    out = imerg_hh.reduce_day(fields)
    assert all(np.isnan(out[n][7, 7]) for n in ("max1h", "max3h", "max6h", "wet_hours"))
    assert out["n_halfhours"][7, 7] == 0


def test_wet_hours_counts_half_hours_at_or_above_a_tenth_of_a_mm_per_hour():
    fields = stack()
    fields[0, 1, 1] = 0.1                   # exactly the threshold: wet
    fields[1, 1, 1] = np.float32(0.0999)    # below: dry
    fields[2, 1, 1] = 3.0
    fields[10:20, 2, 2] = 0.5               # ten wet half-hours = 5 hours
    out = imerg_hh.reduce_day(fields)
    assert out["wet_hours"][1, 1] == pytest.approx(1.0)         # 2 wet half-hours x 0.5 h
    assert out["wet_hours"][2, 2] == pytest.approx(5.0)
    assert out["wet_hours"][0, 0] == 0.0


def test_truncated_window_ends_earlier_and_never_sees_the_missing_tail():
    fields = stack()
    fields[43, 9, 9] = 20.0                 # inside the first 44 half-hours
    fields[46, 9, 9] = 40.0                 # in the part that has not arrived
    out = imerg_hh.reduce_day(fields[:44], n_expected=44)
    assert out["max1h"][9, 9] == pytest.approx(10.0)            # 20 mm/h x 0.5 h; the 40 is invisible
    assert out["max6h"][9, 9] == pytest.approx(10.0)
    assert out["n_halfhours"].max() == 44
    assert imerg_hh.reduce_day(fields)["max1h"][9, 9] == pytest.approx(20.0)   # the full day does see the 40


def test_truncated_window_matches_the_full_day_on_the_same_prefix():
    rng = np.random.default_rng(5)
    fields = rng.gamma(0.4, 4.0, size=(48, ROWS, COLS)).astype(np.float32)
    out = imerg_hh.reduce_day(fields[:44], n_expected=44)
    series = fields[:44, 100, 100].astype(np.float64)
    assert out["max3h"][100, 100] == pytest.approx(brute_force(series, 6), rel=1e-5)


def test_a_window_longer_than_the_truncated_day_is_nan_not_zero():
    out = imerg_hh.reduce_day(stack(1.0)[:4], n_expected=4)
    assert out["max1h"][0, 0] == pytest.approx(1.0) and out["max1h"][0, 0] > 0
    assert np.isnan(out["max3h"]).all() and np.isnan(out["max6h"]).all()   # 6 and 12 half-hours do not fit


def test_fewer_fields_than_a_day_need_an_explicit_n_expected():
    with pytest.raises(ValueError, match="48"):
        imerg_hh.reduce_day(stack()[:44])
    with pytest.raises(ValueError):
        imerg_hh.reduce_day(stack()[:44], n_expected=45)
    with pytest.raises(ValueError):
        imerg_hh.reduce_day(stack(), n_expected=49)
    with pytest.raises(ValueError):
        imerg_hh.reduce_day(stack()[:0], n_expected=0)
    with pytest.raises(ValueError, match="shape"):
        imerg_hh.reduce_day(np.zeros((48, 280, 259), dtype=np.float32))


# ------------------------------------------------------------------------------------------ subset URL

def test_subset_url_carries_the_index_box_of_the_daily_store():
    link = "https://opendap.example/collections/C1-GES_DISC/granules/GPM_3IMERGHHL.07%3Aname.HDF5"
    url = imerg_hh.subset_url(link)
    assert url == (f"{link}.dap.nc4?dap4.ce=/Grid/precipitation[0][2520:2779][980:1259];"
                   "/Grid/time;/Grid/lon[2520:2779];/Grid/lat[980:1259]")
    assert (imerg.COLS, imerg.ROWS) == (260, 280)               # the box is 260 lon x 280 lat


# ------------------------------------------------------------------------------------------ fake NASA

def grid_bytes(field, tmp_dir, name):
    """netCDF4 body of a Hyrax subset: /Grid/precipitation (time, lon, lat) in mm/h, plus time, lon, lat."""
    path = tmp_dir / f"{name}.srv.nc4"
    lat = np.round(8.05 + 0.1 * np.arange(ROWS), 6).astype(np.float32)
    lon = np.round(72.05 + 0.1 * np.arange(COLS), 6).astype(np.float32)
    with h5netcdf.File(path, "w") as handle:
        grid = handle.create_group("Grid")
        grid.dimensions = {"time": 1, "lon": COLS, "lat": ROWS}
        grid.create_variable("precipitation", ("time", "lon", "lat"), "f4", data=field.T[None].astype(np.float32))
        grid.create_variable("time", ("time",), "i4", data=np.array([0], dtype=np.int32))
        grid.create_variable("lon", ("lon",), "f4", data=lon)
        grid.create_variable("lat", ("lat",), "f4", data=lat)
    return path.read_bytes()


class FakeNasa(http.server.BaseHTTPRequestHandler):
    """CMR (`/cmr`) and Hyrax (`/collections/<id>/granules/<UR>.dap.nc4`) for half-hourly granules."""

    field_for = staticmethod(lambda start: np.zeros((ROWS, COLS), dtype=np.float32))
    absent: set = set()          # half-hour starts CMR does not list
    failing: dict = {}           # half-hour start -> HTTP status of the data request
    all_status: int | None = None
    cmr_hits = 0
    data_hits: list = []
    cmr_params: list = []
    tmp_dir = None
    bodies: dict = {}
    body_lock = threading.Lock()
    delay = 0.0
    active = 0
    peak = 0
    lock = threading.Lock()

    def log_message(self, *args):
        pass

    def _send(self, status, body=b"", content_type="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    @staticmethod
    def _name(start):
        end = start + HALF - timedelta(seconds=1)
        return (f"3B-HHR-L.MS.MRG.3IMERG.{start:%Y%m%d}-S{start:%H%M%S}-E{end:%H%M%S}.{start.hour * 60 + start.minute:04d}"
                ".V07B.HDF5")

    def _entry(self, start):
        base = f"http://127.0.0.1:{self.server.server_address[1]}"
        name = self._name(start)
        return {"title": f"GPM_3IMERGHHL.07:{name}", "producer_granule_id": name,
                "time_start": start.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                "time_end": (start + HALF - timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%S.999Z"),
                "updated": "2024-06-12T05:33:16.000Z",
                "links": [
                    {"rel": "http://esipfed.org/ns/fedsearch/1.1/data#", "href": f"{base}/data/{name}"},
                    {"rel": "http://esipfed.org/ns/fedsearch/1.1/service#",
                     "href": f"{base}/collections/{CONCEPTS['late']}/granules/GPM_3IMERGHHL.07%3A{name}"},
                    {"rel": "http://esipfed.org/ns/fedsearch/1.1/service#",
                     "href": f"{base}/virtual-directory/collections/{CONCEPTS['late']}/temporal"}]}

    def do_GET(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path == "/cmr":
            FakeNasa.cmr_hits += 1
            FakeNasa.cmr_params.append({k: v[0] for k, v in query.items()})
            first, last = (datetime.fromisoformat(t.replace("Z", "+00:00")) for t in query["temporal"][0].split(","))
            starts, cursor = [], first.replace(minute=first.minute - first.minute % 30, second=0)
            while cursor <= last:
                if cursor + HALF > first and cursor not in FakeNasa.absent:
                    starts.append(cursor)
                cursor += HALF
            self._send(200, json.dumps({"feed": {"entry": [self._entry(s) for s in starts]}}).encode())
        elif parsed.path.endswith(".dap.nc4"):
            name = unquote(parsed.path).rsplit(":", 1)[-1][: -len(".dap.nc4")]
            stamp = name.split(".3IMERG.")[1][:16]
            start = datetime.strptime(stamp, "%Y%m%d-S%H%M%S").replace(tzinfo=timezone.utc)
            with FakeNasa.lock:
                FakeNasa.data_hits.append(start)
                FakeNasa.active += 1
                FakeNasa.peak = max(FakeNasa.peak, FakeNasa.active)
            try:
                if FakeNasa.delay:
                    time.sleep(FakeNasa.delay)
                status = FakeNasa.all_status or FakeNasa.failing.get(start, 200)
                if status != 200:
                    self._send(status)
                else:
                    field = FakeNasa.field_for(start)
                    key = field.tobytes()
                    with FakeNasa.body_lock:                  # most half-hours share a field: write each file once
                        if key not in FakeNasa.bodies:
                            FakeNasa.bodies[key] = grid_bytes(field, FakeNasa.tmp_dir, f"body{len(FakeNasa.bodies)}")
                        body = FakeNasa.bodies[key]
                    self._send(200, body, "application/x-netcdf4")
            finally:
                with FakeNasa.lock:
                    FakeNasa.active -= 1
        else:
            self._send(404)


@pytest.fixture
def nasa(tmp_path, monkeypatch):
    FakeNasa.field_for = staticmethod(lambda start: np.zeros((ROWS, COLS), dtype=np.float32))
    FakeNasa.absent, FakeNasa.failing, FakeNasa.all_status = set(), {}, None
    FakeNasa.cmr_hits, FakeNasa.data_hits, FakeNasa.cmr_params = 0, [], []
    FakeNasa.delay, FakeNasa.active, FakeNasa.peak, FakeNasa.bodies = 0.0, 0, 0, {}
    FakeNasa.tmp_dir = tmp_path / "server"
    FakeNasa.tmp_dir.mkdir()
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeNasa)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(imerg, "CMR_URL", f"http://127.0.0.1:{httpd.server_address[1]}/cmr")
    monkeypatch.setattr(imerg, "BACKOFF_S", 0.0)
    yield FakeNasa
    httpd.shutdown()
    httpd.server_close()
    thread.join()


@pytest.fixture
def store(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    return {"root": data / "processed" / "imerg_intensity", "manifest": Manifest(tmp_path / "manifest.jsonl", data)}


def run_build(store, run, start, end, **kwargs):
    imerg_hh.build(run, start, end, store["root"], manifest=store["manifest"], **kwargs)


def day_file(store, run, day):
    return store["root"] / run / f"{day:%Y}" / f"{day:%Y%m%d}.npz"


# ------------------------------------------------------------------------------------------ granules

def test_granules_lists_the_48_half_hours_of_the_imd_day_in_time_order(nasa):
    day = date(2018, 8, 15)
    links = imerg_hh.granules("late", day)
    assert len(links) == 48
    stamps = [unquote(link).rsplit("3IMERG.", 1)[1][:16] for link in links]
    assert stamps[0] == "20180814-S030000" and stamps[-1] == "20180815-S023000"
    assert stamps == sorted(stamps)
    params = nasa.cmr_params[0]
    assert params["collection_concept_id"] == CONCEPTS["late"]
    assert params["temporal"] == "2018-08-14T03:00:00Z,2018-08-15T02:59:59Z"
    assert all("/collections/" in link and "/granules/" in link for link in links)


def test_granules_uses_the_early_collection_for_the_early_run(nasa):
    imerg_hh.granules("early", date(2024, 7, 1))
    assert nasa.cmr_params[0]["collection_concept_id"] == CONCEPTS["early"]


def test_granules_omits_a_half_hour_cmr_does_not_list(nasa):
    nasa.absent = {utc(2018, 8, 15, 0, 30)}
    assert len(imerg_hh.granules("late", date(2018, 8, 15))) == 47


def test_granules_rejects_an_unknown_run():
    with pytest.raises(ValueError, match="run"):
        imerg_hh.granules("final", date(2018, 8, 15))


# ------------------------------------------------------------------------------------------ build

def test_build_writes_the_reduced_day_and_keeps_nothing_raw(nasa, store):
    day = date(2018, 8, 15)
    nasa.field_for = staticmethod(lambda start: np.full((ROWS, COLS), 2.0, dtype=np.float32))
    run_build(store, "late", day, day)
    with np.load(day_file(store, "late", day)) as data:
        assert set(data.files) == {"max1h", "max3h", "max6h", "wet_hours", "n_halfhours", "versions"}
        assert data["versions"].tolist() == ["V07B"]
        assert data["max1h"].dtype == np.float32 and data["max1h"].shape == (ROWS, COLS)
        assert data["max1h"][0, 0] == pytest.approx(2.0)            # 2 half-hours x 2 mm/h x 0.5 h
        assert data["max3h"][5, 5] == pytest.approx(6.0)
        assert data["max6h"][279, 259] == pytest.approx(12.0)
        assert data["wet_hours"][0, 0] == pytest.approx(24.0)
        assert (data["n_halfhours"] == 48).all()
    produced = sorted(p.relative_to(store["root"]).as_posix() for p in store["root"].rglob("*") if p.is_file())
    assert produced == ["late/2018/20180815.npz"]                   # no raw subset, no .part
    assert len(nasa.data_hits) == 48
    assert {h.isoformat() for h in nasa.data_hits} >= {"2018-08-14T03:00:00+00:00", "2018-08-15T02:30:00+00:00"}


def test_build_keeps_the_orientation_of_the_daily_store(nasa, store):
    day = date(2018, 8, 15)

    def field_for(start):
        field = np.zeros((ROWS, COLS), dtype=np.float32)
        field[34, 41] = 10.0 if start == utc(2018, 8, 14, 12) else 0.0       # Wayanad pixel (row 34, col 41)
        return field
    nasa.field_for = staticmethod(field_for)
    run_build(store, "late", day, day)
    with np.load(day_file(store, "late", day)) as data:
        assert data["max1h"][34, 41] == pytest.approx(5.0)
        assert np.count_nonzero(data["max1h"]) == 1


def test_build_records_each_day_file_in_the_manifest(nasa, store):
    day = date(2018, 8, 15)
    run_build(store, "late", day, day)
    entries = store["manifest"].entries()
    assert list(entries) == ["processed/imerg_intensity/late/2018/20180815.npz"]
    entry = next(iter(entries.values()))
    assert entry.size_bytes == day_file(store, "late", day).stat().st_size and "dap4" not in entry.url


def test_a_finished_day_is_skipped_on_rerun(nasa, store):
    first, last = date(2018, 8, 15), date(2018, 8, 16)
    run_build(store, "late", first, last)
    assert len(nasa.data_hits) == 96 and nasa.cmr_hits == 2
    before = day_file(store, "late", first).stat().st_mtime_ns
    run_build(store, "late", first, last)
    assert len(nasa.data_hits) == 96 and nasa.cmr_hits == 2
    assert day_file(store, "late", first).stat().st_mtime_ns == before
    day_file(store, "late", last).unlink()                          # only the missing day is redone
    run_build(store, "late", first, last)
    assert len(nasa.data_hits) == 144 and nasa.cmr_hits == 3


def test_a_finished_day_missing_from_the_manifest_is_recorded_on_rerun(nasa, store):
    day = date(2018, 8, 15)
    run_build(store, "late", day, day)
    store["manifest"].manifest_path.unlink()
    run_build(store, "late", day, day)
    assert len(nasa.data_hits) == 48
    assert len(store["manifest"].entries()) == 1


def test_a_listed_half_hour_that_fails_leaves_the_day_unwritten_and_counts_as_failed(nasa, store, caplog):
    day = date(2018, 8, 15)
    nasa.field_for = staticmethod(lambda start: np.full((ROWS, COLS), 1.0, dtype=np.float32))
    nasa.failing = {utc(2018, 8, 14, 20, 30): 500}
    with caplog.at_level("WARNING", logger="aetherguard.ingest.imerg_hh"):
        run_build(store, "late", day, day)
    assert not day_file(store, "late", day).exists() and not list(store["root"].rglob("*.part"))
    assert store["manifest"].entries() == {}
    assert "2018-08-14 20:30" in caplog.text and "HTTP 500" in caplog.text and "day failed" in caplog.text
    assert "1 consecutive" in caplog.text
    assert "dap4" not in caplog.text and "http://" not in caplog.text
    assert nasa.data_hits.count(utc(2018, 8, 14, 20, 30)) == imerg_hh.ATTEMPTS == 5      # retried, then given up
    nasa.failing = {}                                               # the next run retries the day and completes it
    run_build(store, "late", day, day)
    with np.load(day_file(store, "late", day)) as data:
        assert (data["n_halfhours"] == 48).all() and np.isfinite(data["max1h"]).all()


def test_consecutive_days_with_a_failed_listed_half_hour_abort_the_build(nasa, store, monkeypatch):
    monkeypatch.setattr(imerg_hh, "ABORT_AFTER", 2)
    nasa.failing = {imd_start(d) + HALF * 7: 500 for d in (date(2018, 8, 1), date(2018, 8, 2), date(2018, 8, 3))}
    with pytest.raises(imerg_hh.BuildAborted, match="2 consecutive"):
        run_build(store, "late", date(2018, 8, 1), date(2018, 8, 5))
    assert not list(store["root"].rglob("*.npz"))


def test_a_half_hour_cmr_does_not_list_is_nan_and_logged(nasa, store, caplog):
    day = date(2018, 8, 15)
    nasa.field_for = staticmethod(lambda start: np.full((ROWS, COLS), 1.0, dtype=np.float32))
    nasa.absent = {utc(2018, 8, 15, 1)}
    with caplog.at_level("WARNING", logger="aetherguard.ingest.imerg_hh"):
        run_build(store, "late", day, day)
    with np.load(day_file(store, "late", day)) as data:
        assert np.isnan(data["max3h"]).all() and np.isnan(data["wet_hours"]).all()
        assert (data["n_halfhours"] == 47).all() and data["versions"].tolist() == ["V07B"]
    assert "01:00" in caplog.text and "not listed" in caplog.text and len(nasa.data_hits) == 47


def test_a_client_error_is_not_retried(nasa, store):
    day = date(2018, 8, 15)
    nasa.failing = {utc(2018, 8, 14, 3): 404}
    run_build(store, "late", day, day)
    assert nasa.data_hits.count(utc(2018, 8, 14, 3)) == 1
    assert not day_file(store, "late", day).exists()


def test_a_login_page_instead_of_data_is_retried_and_fails_the_day(nasa, store, monkeypatch):
    day = date(2018, 8, 15)
    original = FakeNasa._send

    def send(self, status, body=b"", content_type="application/json"):
        if content_type == "application/x-netcdf4" and "S030000" in self.path:
            body, content_type = b"<html>Earthdata login</html>", "text/html"
        original(self, status, body, content_type)
    monkeypatch.setattr(FakeNasa, "_send", send)
    run_build(store, "late", day, day)
    assert not day_file(store, "late", day).exists()


def test_build_aborts_after_consecutive_failed_days_and_writes_nothing(nasa, store, monkeypatch):
    monkeypatch.setattr(imerg_hh, "ABORT_AFTER", 3)
    nasa.all_status = 401                                           # credentials rejected
    with pytest.raises(imerg_hh.BuildAborted, match="3 consecutive"):
        run_build(store, "late", date(2018, 8, 1), date(2018, 8, 20))
    assert not list(store["root"].rglob("*.npz"))
    assert nasa.cmr_hits == 3                                       # days 4.. were never attempted


def test_the_abort_limit_is_the_configured_thirty(nasa):
    assert imerg_hh.ABORT_AFTER == imerg.ABORT_AFTER == 30


def test_a_good_day_resets_the_consecutive_failure_count(nasa, store, monkeypatch):
    monkeypatch.setattr(imerg_hh, "ABORT_AFTER", 2)
    bad = {d for d in (date(2018, 8, 1), date(2018, 8, 3), date(2018, 8, 5))}
    nasa.failing = {start: 401 for start in [imd_start(d) + k * HALF for d in bad for k in range(48)]}
    run_build(store, "late", date(2018, 8, 1), date(2018, 8, 6))
    written = {p.stem for p in store["root"].rglob("*.npz")}
    assert written == {"20180802", "20180804", "20180806"}


def test_months_filter_builds_only_the_requested_months(nasa, store):
    run_build(store, "late", date(2018, 5, 30), date(2018, 6, 2), months={6})
    assert {p.stem for p in store["root"].rglob("*.npz")} == {"20180601", "20180602"}


def test_requests_never_exceed_the_worker_limit(nasa, store):
    nasa.delay = 0.02
    run_build(store, "late", date(2018, 8, 15), date(2018, 8, 15), workers=3)
    assert 1 < nasa.peak <= 3


@pytest.mark.parametrize("workers", [0, 5])
def test_workers_are_limited_to_four(nasa, store, workers):
    with pytest.raises(ValueError, match="workers"):
        run_build(store, "late", date(2018, 8, 15), date(2018, 8, 15), workers=workers)


def test_build_rejects_an_unknown_run_and_an_empty_range(nasa, store):
    with pytest.raises(ValueError, match="run"):
        run_build(store, "final", date(2018, 8, 15), date(2018, 8, 15))
    with pytest.raises(ValueError, match="after"):
        run_build(store, "late", date(2018, 8, 16), date(2018, 8, 15))


# ------------------------------------------------------------------------------------------ repair

def run_repair(store, run, start, end, **kwargs):
    return imerg_hh.repair(run, start, end, store["root"], manifest=store["manifest"], **kwargs)


def test_repair_rewrites_a_day_once_cmr_lists_all_48(nasa, store):
    day = date(2018, 8, 15)
    nasa.field_for = staticmethod(lambda start: np.full((ROWS, COLS), 1.0, dtype=np.float32))
    nasa.absent = {utc(2018, 8, 15, 1)}
    run_build(store, "late", day, day)
    path = day_file(store, "late", day)
    with np.load(path) as data:
        assert np.isnan(data["max1h"]).all() and (data["n_halfhours"] == 47).all()
    hits = len(nasa.data_hits)

    assert run_repair(store, "late", day, day)["rewritten"] == 0     # CMR still lists 47: left as it is
    assert len(nasa.data_hits) == hits and np.load(path)["n_halfhours"].max() == 47

    nasa.absent = set()                                             # the archive caught up
    counts = run_repair(store, "late", day, day)
    assert counts == {"scanned": 1, "incomplete": 1, "rewritten": 1, "versions_added": 0}
    with np.load(path) as data:
        assert (data["n_halfhours"] == 48).all() and data["max1h"][0, 0] == pytest.approx(1.0)
        assert data["versions"].tolist() == ["V07B"]
    assert len(nasa.data_hits) == hits + 48
    assert not list(store["root"].rglob("*.part"))
    assert store["manifest"].is_current(path)

    hits = len(nasa.data_hits)                                      # a complete day is not touched again
    assert run_repair(store, "late", day, day)["incomplete"] == 0
    assert len(nasa.data_hits) == hits


def test_repair_keeps_the_old_file_when_the_refetch_fails(nasa, store):
    day = date(2018, 8, 15)
    nasa.absent = {utc(2018, 8, 15, 1)}
    run_build(store, "late", day, day)
    path = day_file(store, "late", day)
    before = path.read_bytes()
    nasa.absent = set()
    nasa.failing = {utc(2018, 8, 14, 9): 500}
    assert run_repair(store, "late", day, day)["rewritten"] == 0
    assert path.read_bytes() == before


def test_repair_adds_versions_to_a_complete_day_written_without_them(nasa, store):
    day = date(2018, 8, 15)
    nasa.field_for = staticmethod(lambda start: np.full((ROWS, COLS), 3.0, dtype=np.float32))
    run_build(store, "late", day, day)
    path = day_file(store, "late", day)
    with np.load(path) as data:
        old = {name: data[name] for name in data.files if name != "versions"}
    np.savez_compressed(path, **old)                                # the file as the first build wrote it
    hits = len(nasa.data_hits)
    counts = run_repair(store, "late", day, day)
    assert counts["versions_added"] == 1 and len(nasa.data_hits) == hits       # nothing refetched
    with np.load(path) as data:
        assert data["versions"].tolist() == ["V07B"]
        assert all(np.array_equal(data[name], old[name], equal_nan=True) for name in old)


def test_repair_leaves_days_without_a_file_alone_and_honours_months(nasa, store):
    run_build(store, "late", date(2018, 6, 1), date(2018, 6, 1))
    nasa.cmr_hits = 0
    counts = run_repair(store, "late", date(2018, 5, 31), date(2018, 6, 3), months={6})
    assert counts["scanned"] == 1 and nasa.cmr_hits == 0           # complete, with versions: no request at all


# ------------------------------------------------------------------------------------------ CLI

def test_live_window_build_reduces_only_the_first_44_half_hours_into_its_own_directory(nasa, store):
    day = date(2024, 8, 1)
    nasa.field_for = staticmethod(lambda start: np.full((ROWS, COLS), 2.0 if start < utc(2024, 8, 1, 1) else 40.0,
                                                        dtype=np.float32))
    run_build(store, "early", day, day, live_window=True)
    assert not day_file(store, "early", day).exists()
    path = store["root"] / "early_live" / "2024" / "20240801.npz"
    with np.load(path) as data:
        assert imerg_hh.LIVE_HALF_HOURS == 44 and (data["n_halfhours"] == 44).all()
        assert data["max3h"][0, 0] == pytest.approx(6.0)             # the 40 mm/h tail is never fetched
        assert data["wet_hours"][0, 0] == pytest.approx(22.0)
        assert data["versions"].tolist() == ["V07B"]
    assert len(nasa.data_hits) == 44 and max(nasa.data_hits) == utc(2024, 8, 1, 0, 30)
    assert nasa.cmr_params[0]["collection_concept_id"] == CONCEPTS["early"]


def test_live_window_day_equals_reduce_day_of_the_prefix_of_the_full_day(nasa, store):
    day = date(2024, 8, 1)
    rng = np.random.default_rng(11)
    starts = [imd_start(day) + k * HALF for k in range(48)]
    series = {s: rng.gamma(0.4, 4.0, size=(ROWS, COLS)).astype(np.float32) for s in starts}
    nasa.field_for = staticmethod(lambda start: series[start])
    run_build(store, "early", day, day, live_window=True)
    expected = imerg_hh.reduce_day(np.stack([series[s] for s in starts[:44]]), n_expected=44)
    with np.load(store["root"] / "early_live" / "2024" / "20240801.npz") as data:
        for name, values in expected.items():
            np.testing.assert_array_equal(data[name], values)


def test_live_window_does_not_warn_about_the_unfetched_tail(nasa, store, caplog):
    nasa.absent = {utc(2024, 8, 1, 2)}                              # a tail half-hour CMR lacks: irrelevant to the window
    with caplog.at_level("WARNING"):
        run_build(store, "early", date(2024, 8, 1), date(2024, 8, 1), live_window=True)
    assert not [r for r in caplog.records if "not listed" in r.getMessage()]


def test_live_window_and_complete_day_files_do_not_collide(nasa, store):
    day = date(2024, 8, 1)
    run_build(store, "early", day, day, live_window=True)
    run_build(store, "early", day, day)
    assert day_file(store, "early", day).exists() and (store["root"] / "early_live" / "2024" / "20240801.npz").exists()


def test_parse_months():
    assert imerg_hh.parse_months("6-9") == {6, 7, 8, 9}
    assert imerg_hh.parse_months("6-12") == set(range(6, 13))
    assert imerg_hh.parse_months("7") == {7}
    for bad in ("9-6", "0-3", "6-13", "x", ""):
        with pytest.raises(ValueError):
            imerg_hh.parse_months(bad)


def test_cli_passes_its_arguments_to_build(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(imerg_hh, "build", lambda *a, **k: calls.append((a, k)))
    code = imerg_hh.main(["--run", "late", "--start", "2007-01-01", "--end", "2017-12-31", "--months", "6-9",
                          "--workers", "2", "--root", str(tmp_path / "out")])
    assert code == 0
    (args, kwargs), = calls
    assert args == ("late", date(2007, 1, 1), date(2017, 12, 31), tmp_path / "out")
    assert kwargs == {"workers": 2, "months": {6, 7, 8, 9}, "live_window": False}


def test_cli_live_window_flag_reaches_build_and_excludes_repair(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(imerg_hh, "build", lambda *a, **k: calls.append((a, k)))
    assert imerg_hh.main(["--run", "early", "--start", "2024-06-01", "--end", "2024-12-31", "--live-window",
                          "--root", str(tmp_path)]) == 0
    (args, kwargs), = calls
    assert args[0] == "early" and kwargs["live_window"] is True
    with pytest.raises(SystemExit):
        imerg_hh.main(["--run", "early", "--start", "2024-06-01", "--end", "2024-06-02", "--live-window", "--repair"])


def test_cli_repair_runs_repair_not_build(tmp_path, monkeypatch):
    built, repaired = [], []
    monkeypatch.setattr(imerg_hh, "build", lambda *a, **k: built.append(a))
    monkeypatch.setattr(imerg_hh, "repair", lambda *a, **k: repaired.append((a, k)))
    code = imerg_hh.main(["--run", "late", "--start", "2007-06-01", "--end", "2007-09-30", "--repair",
                          "--root", str(tmp_path)])
    assert code == 0 and not built
    (args, kwargs), = repaired
    assert args == ("late", date(2007, 6, 1), date(2007, 9, 30), tmp_path) and kwargs == {"workers": 4, "months": None}


def test_cli_default_root_is_the_processed_intensity_store(monkeypatch):
    calls = []
    monkeypatch.setattr(imerg_hh, "build", lambda *a, **k: calls.append(a))
    imerg_hh.main(["--run", "early", "--start", "2024-06-01", "--end", "2024-06-02"])
    assert calls[0][3].as_posix().endswith("processed/imerg_intensity")


def test_cli_rejects_more_than_four_workers_and_reports_an_abort(monkeypatch, capsys):
    with pytest.raises(SystemExit):
        imerg_hh.main(["--run", "late", "--start", "2018-08-01", "--end", "2018-08-02", "--workers", "5"])

    def abort(*args, **kwargs):
        raise imerg_hh.BuildAborted("30 consecutive failed days")
    monkeypatch.setattr(imerg_hh, "build", abort)
    assert imerg_hh.main(["--run", "late", "--start", "2018-08-01", "--end", "2018-08-02"]) == 2
    assert "30 consecutive failed days" in capsys.readouterr().err
