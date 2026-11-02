"""IMERG daily ingest: pixel mapping, lon-major orientation, fill values, missing days, resumability, gather.

Everything runs against a local HTTP server that imitates CMR (granule search) and Hyrax (DAP4 subset): the
subset files are synthetic netCDF written by xarray in the exact (time, lon, lat) layout measured in
reports/phase6_live_sources_probe.md. The `realdata` tests read the real stores built by imerg_build.
"""
import hashlib
import http.server
import json
import threading
from datetime import date, datetime, timedelta, timezone
from urllib.parse import parse_qs, unquote, urlparse

import numpy as np
import pytest
import xarray as xr

from aetherguard.config import data_root, load_config
from aetherguard.grid import cell_center, latlon_to_cell
from aetherguard.http import DownloadError
from aetherguard.ingest import imerg, imerg_build
from aetherguard.ingest.imerg import ImergFormatError, ImergStore, imerg_pixel
from aetherguard.manifest import Manifest

ROWS, COLS = 280, 260
FILL = -9999.900390625
LATE_CID = load_config("live")["imerg"]["runs"]["late"]["concept_id"]
WAYANAD = (11.47, 76.13)
WAYANAD_PIXEL = (34, 41)


# ------------------------------------------------------------------------------------------ synthetic source

def make_field(value=1.0, plants=()):
    """(rows, cols) float32 field in store orientation with `value` everywhere and planted (row, col, value)."""
    field = np.full((ROWS, COLS), value, dtype=np.float32)
    for row, col, planted in plants:
        field[row, col] = planted
    return field


def write_subset(path, day, field, dims=("time", "lon", "lat"), day_stamp=None):
    """Write `field` (rows, cols) as the Hyrax subset file: variable `precipitation` shaped (time, lon, lat)."""
    lat = np.round(8.05 + 0.1 * np.arange(ROWS), 6)
    lon = np.round(72.05 + 0.1 * np.arange(COLS), 6).astype(np.float32)
    data = field.T[None] if dims == ("time", "lon", "lat") else field[None]
    coords = {"time": [np.datetime64(day_stamp or day, "ns")], "lon": lon, "lat": lat}
    da = xr.DataArray(data.astype(np.float32), dims=dims, coords=coords, attrs={"units": "mm/day"})
    da.encoding["_FillValue"] = np.float32(FILL)
    ds = xr.Dataset({"precipitation": da})
    ds.to_netcdf(path, engine="h5netcdf")
    ds.close()


class FakeNasa(http.server.BaseHTTPRequestHandler):
    """CMR (`/cmr`) and Hyrax (`/collections/<id>/granules/<UR>.dap.nc4`) in one local server."""

    granules: dict = {}      # day -> {"name": file name, "updated": ISO text, "field": array or None, "status": int}
    cmr_hits = 0
    data_hits: list = []
    tmp_dir = None
    run_letter = "L"

    def log_message(self, *args):
        pass

    def _send(self, status, body=b"", content_type="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _entry(self, day, spec):
        base = f"http://127.0.0.1:{self.server.server_address[1]}"
        ur = f"GPM_3IMERGD{self.run_letter}.07%3A{spec['name']}"
        stamp = f"{day.isoformat()}T"
        return {"title": f"GPM_3IMERGD{self.run_letter}.07:{spec['name']}", "producer_granule_id": spec["name"],
                "time_start": stamp + "00:00:00.000Z", "time_end": stamp + "23:59:59.999Z",
                "updated": spec["updated"], "granule_size": "28.0",
                "links": [
                    {"rel": "http://esipfed.org/ns/fedsearch/1.1/data#", "href": f"{base}/data/{spec['name']}"},
                    {"rel": "http://esipfed.org/ns/fedsearch/1.1/service#",
                     "href": f"{base}/collections/{LATE_CID}/granules/{ur}"},
                    {"rel": "http://esipfed.org/ns/fedsearch/1.1/service#",
                     "href": f"{base}/virtual-directory/collections/{LATE_CID}/temporal"}]}

    def do_GET(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path == "/cmr":
            FakeNasa.cmr_hits += 1
            first, last = (datetime.fromisoformat(t.replace("Z", "+00:00")) for t in query["temporal"][0].split(","))
            days = sorted(d for d in FakeNasa.granules if first.date() <= d <= last.date())
            size, page = int(query["page_size"][0]), int(query.get("page_num", ["1"])[0])
            chosen = days[(page - 1) * size: page * size]
            entries = [self._entry(d, FakeNasa.granules[d]) for d in chosen]
            self._send(200, json.dumps({"feed": {"entry": entries}}).encode())
        elif parsed.path.endswith(".dap.nc4"):
            name = unquote(parsed.path).rsplit(":", 1)[-1][: -len(".dap.nc4")]
            day = next((d for d, s in FakeNasa.granules.items() if s["name"] == name), None)
            FakeNasa.data_hits.append(day)
            if day is None:
                self._send(404)
                return
            spec = FakeNasa.granules[day]
            if spec.get("status", 200) != 200:
                self._send(spec["status"])
            elif spec.get("garbage"):
                self._send(200, b"<html>Earthdata login</html>", "text/html")
            else:
                path = FakeNasa.tmp_dir / f"{name}.srv.nc4"
                write_subset(path, day, spec["field"])
                self._send(200, path.read_bytes(), "application/x-netcdf4")
        else:
            self._send(404)


def granule_name(day, version="V07B", letter="L"):
    return f"3B-DAY-{letter}.MS.MRG.3IMERG.{day:%Y%m%d}-S000000-E235959.{version}.nc4"


@pytest.fixture
def nasa(tmp_path, monkeypatch):
    FakeNasa.granules, FakeNasa.cmr_hits, FakeNasa.data_hits = {}, 0, []
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


def publish(nasa_cls, days, version="V07B", value=None, plants=(), updated="2024-06-12T05:33:16.000Z"):
    for day in days:
        nasa_cls.granules[day] = {
            "name": granule_name(day, version), "updated": updated,
            "field": make_field(float(day.toordinal() % 50) if value is None else value, plants)}


@pytest.fixture
def make_store(tmp_path):
    root = tmp_path / "data"
    root.mkdir(exist_ok=True)

    def build(run="late"):
        return ImergStore(root / "processed" / "rain", run, raw_dir=root / "raw" / "imerg",
                          manifest=Manifest(tmp_path / "manifest.jsonl", root))
    return build


def days_from(start, n):
    return [start + timedelta(d) for d in range(n)]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ------------------------------------------------------------------------------------------ pixel mapping

def test_grid_constants_follow_the_shared_live_config():
    grid = load_config("live")["domain_grid"]
    assert (imerg.ROWS, imerg.COLS) == (grid["rows"], grid["cols"]) == (ROWS, COLS)
    assert imerg.domain_lat()[0] == pytest.approx(grid["lat_first"]) and imerg.domain_lon()[0] == \
        pytest.approx(grid["lon_first"])
    assert imerg.domain_lat()[-1] == pytest.approx(35.95) and imerg.domain_lon()[-1] == pytest.approx(97.95)


def test_wayanad_cell_maps_to_the_pixel_centred_on_11_45_76_15():
    row, col = imerg_pixel(latlon_to_cell(*WAYANAD))
    assert (row, col) == WAYANAD_PIXEL
    assert imerg.domain_lat()[row] == pytest.approx(11.45) and imerg.domain_lon()[col] == pytest.approx(76.15)


def test_every_cell_centre_lies_inside_its_pixel():
    rng = np.random.default_rng(0)
    cells = latlon_to_cell(rng.uniform(8.0, 35.999, 2000), rng.uniform(72.0, 97.999, 2000))
    rows, cols = imerg_pixel(cells)
    lat_c, lon_c = cell_center(cells)
    assert np.abs(lat_c - imerg.domain_lat()[rows]).max() <= 0.05 + 1e-9
    assert np.abs(lon_c - imerg.domain_lon()[cols]).max() <= 0.05 + 1e-9
    # cells that share a pixel: the two 0.05 cells on each axis
    south, north = latlon_to_cell(11.43, 76.13), latlon_to_cell(11.48, 76.13)
    assert south != north and imerg_pixel(south) == imerg_pixel(north)


def test_pixel_extremes_and_scalar_types():
    assert imerg_pixel(latlon_to_cell(8.0, 72.0)) == (0, 0)
    assert imerg_pixel(latlon_to_cell(35.99, 97.99)) == (ROWS - 1, COLS - 1)
    row, col = imerg_pixel(latlon_to_cell(27.7, 85.3))
    assert type(row) is int and type(col) is int and (row, col) == (197, 133)


@pytest.mark.parametrize("lat, lon", [(7.95, 76.0), (36.0, 76.0), (20.0, 71.95), (20.0, 98.0)])
def test_cells_outside_the_domain_raise(lat, lon):
    with pytest.raises(ValueError, match="outside"):
        imerg_pixel(latlon_to_cell(lat, lon))


# ------------------------------------------------------------------------------------------ CMR names

def test_parse_granule_reads_both_version_letters_and_the_cmr_opendap_link():
    entry = {"title": "GPM_3IMERGDL.07:" + granule_name(date(2018, 8, 15), "V07B"),
             "producer_granule_id": granule_name(date(2018, 8, 15), "V07B"),
             "time_start": "2018-08-15T00:00:00.000Z", "updated": "2024-06-12T05:33:16.000Z",
             "links": [{"rel": "http://esipfed.org/ns/fedsearch/1.1/service#",
                        "href": "https://cmr.earthdata.nasa.gov/virtual-directory/collections/C1/temporal"},
                       {"rel": "http://esipfed.org/ns/fedsearch/1.1/service#",
                        "href": "https://opendap.earthdata.nasa.gov/collections/C1/granules/GPM_3IMERGDL.07%3AX"}]}
    old = imerg.parse_granule(entry)
    assert (old.day, old.version) == (date(2018, 8, 15), "V07B")
    assert old.opendap_url == "https://opendap.earthdata.nasa.gov/collections/C1/granules/GPM_3IMERGDL.07%3AX"
    new_name = granule_name(date(2026, 10, 13), "V07C")
    new = imerg.parse_granule({**entry, "producer_granule_id": new_name, "time_start": "2026-10-13T00:00:00.000Z"})
    assert (new.day, new.version, new.file_name) == (date(2026, 10, 13), "V07C", new_name)


def test_parse_granule_without_an_opendap_link_is_an_error():
    with pytest.raises(ValueError, match="OPeNDAP"):
        imerg.parse_granule({"producer_granule_id": granule_name(date(2018, 1, 1)), "updated": "2024-01-01T00:00:00Z",
                             "time_start": "2018-01-01T00:00:00.000Z", "links": []})


def test_subset_url_uses_the_cmr_link_and_the_measured_constraint(nasa):
    publish(nasa, [date(2018, 8, 15)])
    granule = imerg.discover("late", date(2018, 8, 15), date(2018, 8, 15))[date(2018, 8, 15)]
    assert imerg.subset_url(granule) == (
        granule.opendap_url + ".dap.nc4?dap4.ce=/precipitation[0][2520:2779][980:1259];/time;"
        "/lon[2520:2779];/lat[980:1259]")


def test_discover_pages_through_cmr_and_takes_the_latest_update_per_day(nasa, monkeypatch):
    monkeypatch.setattr(imerg, "CMR_PAGE_SIZE", 2)
    days = days_from(date(2024, 6, 1), 5)
    publish(nasa, days)
    older = dict(nasa.granules[days[0]])
    nasa.granules[days[0]] = {**older, "name": granule_name(days[0], "V07C"), "updated": "2025-01-01T00:00:00.000Z"}
    found = imerg.discover("late", days[0], days[-1])
    assert sorted(found) == days and nasa.cmr_hits == 3
    assert found[days[0]].version == "V07C"


def test_discover_rejects_unknown_runs():
    with pytest.raises(ValueError, match="run"):
        imerg.discover("noon", date(2024, 1, 1), date(2024, 1, 2))


# ------------------------------------------------------------------------------------------ reading one file

def test_read_day_transposes_the_lon_major_file_into_lat_lon_order(tmp_path):
    day = date(2018, 8, 15)
    write_subset(tmp_path / "a.nc4", day, make_field(0.0, [(34, 41, 61.0), (0, 259, 7.0), (279, 0, 9.0)]))
    out = imerg.read_day(tmp_path / "a.nc4", day)
    assert out.shape == (ROWS, COLS) and out.dtype == np.float32
    assert out[34, 41] == 61.0 and out[0, 259] == 7.0 and out[279, 0] == 9.0
    assert out[41, 34] == 0.0  # the un-transposed index holds nothing


def test_read_day_turns_fill_and_negative_values_into_nan(tmp_path):
    day = date(2018, 8, 15)
    write_subset(tmp_path / "a.nc4", day, make_field(1.0, [(5, 6, FILL), (7, 8, -3.0), (9, 10, 0.0)]))
    out = imerg.read_day(tmp_path / "a.nc4", day)
    assert np.isnan(out[5, 6]) and np.isnan(out[7, 8])
    assert out[9, 10] == 0.0 and np.isfinite(out).sum() == ROWS * COLS - 2


def test_read_day_refuses_a_file_that_is_not_lon_major(tmp_path):
    day = date(2018, 8, 15)
    write_subset(tmp_path / "a.nc4", day, make_field(), dims=("time", "lat", "lon"))
    with pytest.raises(ImergFormatError, match="dimensions"):
        imerg.read_day(tmp_path / "a.nc4", day)


def test_read_day_refuses_the_wrong_day_and_an_all_fill_day(tmp_path):
    day = date(2018, 8, 15)
    write_subset(tmp_path / "a.nc4", day, make_field(), day_stamp=date(2018, 8, 16))
    with pytest.raises(ImergFormatError, match="2018-08-16"):
        imerg.read_day(tmp_path / "a.nc4", day)
    write_subset(tmp_path / "b.nc4", day, make_field(FILL))
    with pytest.raises(ImergFormatError, match="no valid"):
        imerg.read_day(tmp_path / "b.nc4", day)


def test_read_day_refuses_a_file_that_is_not_netcdf(tmp_path):
    (tmp_path / "a.nc4").write_bytes(b"<html>Earthdata login</html>")
    with pytest.raises(ImergFormatError, match="cannot be read"):
        imerg.read_day(tmp_path / "a.nc4", date(2018, 8, 15))


# ------------------------------------------------------------------------------------------ the store

def test_update_stores_the_planted_value_where_imerg_pixel_says(nasa, make_store):
    day = date(2018, 8, 15)
    publish(nasa, [day], value=0.0, plants=[(*WAYANAD_PIXEL, 61.0)])
    store = make_store()
    summary = store.update([day])
    row, col = imerg_pixel(latlon_to_cell(*WAYANAD))
    assert summary["added"] == 1 and store.gather([row], [col], day, 1)[0, 0] == pytest.approx(61.0)
    # the raw file is cached under raw/imerg/late/<yyyy>/ with a manifest row
    cached = sorted((store.raw_dir / "late" / "2018").glob("*.nc4"))
    assert len(cached) == 1 and "V07B" in cached[0].name
    assert store.manifest.is_current(cached[0])
    assert np.load(store.processed_dir / "imerg_late_2018.npy", mmap_mode="r").shape == (365, ROWS, COLS)


def test_gather_returns_float32_rows_by_pixel_and_nan_outside_the_store(nasa, make_store):
    days = days_from(date(2024, 6, 1), 3)
    publish(nasa, days, plants=[(10, 20, 5.0)])
    store = make_store()
    store.update(days)
    out = store.gather(np.array([10, 11]), np.array([20, 20]), date(2024, 5, 31), 6)
    assert out.shape == (2, 6) and out.dtype == np.float32
    assert np.isnan(out[:, 0]).all() and np.isnan(out[:, 4:]).all()
    assert (out[0, 1:4] == 5.0).all()
    assert (out[1, 1:4] == np.array([d.toordinal() % 50 for d in days], dtype=np.float32)).all()


def test_gather_validates_pixels_and_length(nasa, make_store):
    store = make_store()
    for rows, cols in (([ROWS], [0]), ([0], [COLS]), ([-1], [0])):
        with pytest.raises(ValueError, match="pixel"):
            store.gather(rows, cols, date(2024, 6, 1), 2)
    with pytest.raises(ValueError, match="length"):
        store.gather([0], [0], date(2024, 6, 1), 0)
    with pytest.raises(ValueError, match="same length"):
        store.gather([0, 1], [0], date(2024, 6, 1), 2)


def test_missing_day_is_nan_and_listed(nasa, make_store):
    days = days_from(date(2024, 6, 1), 3)
    publish(nasa, [days[0], days[2]])
    store = make_store()
    summary = store.update(days)
    assert summary["added"] == 2 and summary["missing"] == [days[1].isoformat()] and summary["failed"] == []
    assert store.dates() == [days[0], days[2]] and not store.has_date(days[1]) and store.has_date(days[2])
    assert np.isnan(store.gather([3], [3], days[1], 1)).all()
    index = json.loads((store.processed_dir / "imerg_late_index.json").read_text(encoding="utf-8"))
    assert index["years"]["2024"]["missing"] == [days[1].isoformat()]
    assert index["years"]["2024"]["present"] == [days[0].isoformat(), days[2].isoformat()]


def test_a_missing_day_is_fetched_when_it_appears_later(nasa, make_store):
    days = days_from(date(2024, 6, 1), 2)
    publish(nasa, days[:1])
    store = make_store()
    store.update(days)
    publish(nasa, days[1:])
    summary = make_store().update(days)
    assert summary["added"] == 1 and summary["missing"] == [] and summary["already_present"] == 1
    index = json.loads((store.processed_dir / "imerg_late_index.json").read_text(encoding="utf-8"))
    assert index["years"]["2024"]["missing"] == []


def test_idempotent_rerun_makes_no_requests(nasa, make_store):
    days = days_from(date(2024, 6, 1), 4)
    publish(nasa, days)
    store = make_store()
    store.update(days)
    before = (nasa.cmr_hits, len(nasa.data_hits), sha(store.processed_dir / "imerg_late_2024.npy"),
              sha(store.processed_dir / "imerg_late_index.json"))
    summary = make_store().update(days)
    assert summary["already_present"] == 4 and summary["added"] == 0 and summary["bytes_fetched"] == 0
    assert (nasa.cmr_hits, len(nasa.data_hits), sha(store.processed_dir / "imerg_late_2024.npy"),
            sha(store.processed_dir / "imerg_late_index.json")) == before


def test_resume_after_a_lost_index_reuses_manifest_current_raw_files(nasa, make_store):
    days = days_from(date(2024, 6, 1), 3)
    publish(nasa, days)
    store = make_store()
    store.update(days)
    (store.processed_dir / "imerg_late_index.json").unlink()
    fetched = len(nasa.data_hits)
    summary = make_store().update(days)
    assert summary["added"] == 3 and summary["bytes_fetched"] == 0 and len(nasa.data_hits) == fetched
    assert make_store().dates() == days


def test_gather_across_a_year_boundary(nasa, make_store):
    days = days_from(date(2023, 12, 30), 4)  # 30, 31 Dec and 1, 2 Jan
    publish(nasa, days, plants=[(10, 20, 3.0)])
    store = make_store()
    store.update(days)
    out = store.gather([10], [20], date(2023, 12, 29), 6)
    assert out.shape == (1, 6)
    assert np.isnan(out[0, 0]) and (out[0, 1:5] == 3.0).all() and np.isnan(out[0, 5])
    only_new_year = store.gather([10], [20], date(2024, 1, 1), 3)
    assert (only_new_year[0, :2] == 3.0).all() and np.isnan(only_new_year[0, 2])
    assert (store.processed_dir / "imerg_late_2023.npy").exists() and (store.processed_dir / "imerg_late_2024.npy").exists()
    assert np.load(store.processed_dir / "imerg_late_2024.npy", mmap_mode="r").shape == (366, ROWS, COLS)


def test_year_with_no_file_gathers_as_nan(nasa, make_store):
    publish(nasa, [date(2024, 1, 5)])
    store = make_store()
    store.update([date(2024, 1, 5)])
    out = store.gather([1, 2], [3, 4], date(2022, 12, 30), 4)
    assert np.isnan(out).all()


def test_update_appends_only_new_days_and_leaves_older_years_untouched(nasa, make_store):
    first = days_from(date(2023, 12, 30), 2)
    publish(nasa, first)
    store = make_store()
    store.update(first)
    old_year = store.processed_dir / "imerg_late_2023.npy"
    old_hash, old_mtime = sha(old_year), old_year.stat().st_mtime_ns
    fetched = len(nasa.data_hits)

    new = days_from(date(2024, 1, 1), 2)
    publish(nasa, new)
    summary = make_store().update(first + new)
    assert summary["already_present"] == 2 and summary["added"] == 2
    assert len(nasa.data_hits) == fetched + 2  # only the two new days were requested
    assert sha(old_year) == old_hash and old_year.stat().st_mtime_ns == old_mtime

    # a third call appends into the existing 2024 file without disturbing the days already in it
    year_file = store.processed_dir / "imerg_late_2024.npy"
    before = np.array(np.load(year_file, mmap_mode="r")[0])
    more = [date(2024, 1, 3)]
    publish(nasa, more)
    make_store().update(more)
    after = np.load(year_file, mmap_mode="r")
    assert np.array_equal(after[0], before) and np.isfinite(after[2]).all() and np.isnan(after[3]).all()
    assert sha(old_year) == old_hash


def test_index_records_grid_orientation_and_the_source_version_per_day(nasa, make_store):
    old, new = date(2024, 6, 10), date(2024, 6, 11)
    publish(nasa, [old], version="V07B")
    publish(nasa, [new], version="V07C")
    store = make_store()
    store.update([old, new])
    text = (store.processed_dir / "imerg_late_index.json").read_text(encoding="utf-8")
    index = json.loads(text, parse_constant=lambda name: pytest.fail(f"non-strict JSON constant {name}"))
    assert index["run"] == "late" and index["units"] == "mm/day" and index["day_basis"] == "utc"
    assert index["grid"] == load_config("live")["domain_grid"]
    assert "lon-major" in index["orientation"] and "south" in index["orientation"]
    year = index["years"]["2024"]
    assert year["n_days"] == 366 and year["n_present"] == 2
    assert year["versions"] == {"2024-06-10": "V07B", "2024-06-11": "V07C"}
    assert index["days_present"] == 2 and index["first_day"] == "2024-06-10" and index["last_day"] == "2024-06-11"


def test_a_failing_day_is_listed_and_retried_next_time(nasa, make_store):
    days = days_from(date(2024, 6, 1), 3)
    publish(nasa, days)
    nasa.granules[days[1]]["status"] = 403
    store = make_store()
    summary = store.update(days)
    assert summary["added"] == 2 and summary["failed"] == [days[1].isoformat()] and summary["missing"] == []
    assert summary["failure_reasons"] == {"DownloadError": 1}
    assert not store.has_date(days[1])
    assert not list((store.raw_dir / "late" / "2024").glob(f"*{days[1]:%Y%m%d}*"))
    del nasa.granules[days[1]]["status"]
    again = make_store().update(days)
    assert again["added"] == 1 and again["failed"] == [] and make_store().dates() == days


def test_a_response_that_is_not_netcdf_is_discarded_and_reported_failed(nasa, make_store):
    day = date(2024, 6, 1)
    publish(nasa, [day])
    nasa.granules[day]["garbage"] = True
    store = make_store()
    summary = store.update([day])
    assert summary["failed"] == [day.isoformat()] and summary["added"] == 0
    assert summary["failure_reasons"] == {"ImergFormatError": 1}
    assert len(nasa.data_hits) == imerg.FORMAT_ATTEMPTS
    assert not list((store.raw_dir / "late" / "2024").glob("*.nc4"))
    assert store.dates() == []


def test_repeated_failures_stop_the_build_and_count_the_rest_as_failed(nasa, make_store, monkeypatch):
    monkeypatch.setattr(imerg, "ABORT_AFTER", 2)
    days = days_from(date(2024, 6, 1), 6)
    publish(nasa, days)
    for day in days:
        nasa.granules[day]["status"] = 403
    summary = make_store().update(days, workers=1)
    assert summary["failed"] == [d.isoformat() for d in days] and summary["added"] == 0
    assert len(nasa.data_hits) == 2 and "not attempted" in " ".join(summary["failure_reasons"])


def test_an_error_while_storing_propagates_and_the_next_run_resumes(nasa, make_store, monkeypatch):
    days = days_from(date(2024, 6, 1), 5)
    publish(nasa, days)
    store = make_store()
    monkeypatch.setattr(store, "_open_year_for_write", lambda year: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError, match="disk full"):
        store.update(days, workers=1)
    assert make_store().dates() == []
    resumed = make_store().update(days)
    assert resumed["added"] == 5 and make_store().dates() == days


def test_workers_are_bounded(nasa, make_store):
    store = make_store()
    for workers in (0, 7):
        with pytest.raises(ValueError, match="workers"):
            store.update([date(2024, 6, 1)], workers=workers)


def test_an_empty_store_is_valid_and_unknown_runs_are_rejected(tmp_path):
    store = ImergStore(tmp_path / "rain", "early")
    assert store.dates() == [] and not store.has_date(date(2024, 6, 1))
    assert np.isnan(store.gather([0], [0], date(2024, 6, 1), 3)).all()
    with pytest.raises(ValueError, match="run"):
        ImergStore(tmp_path / "rain", "noon")


def test_early_and_late_stores_are_independent(nasa, make_store):
    day = date(2024, 6, 1)
    publish(nasa, [day], value=1.0)
    late = make_store("late")
    late.update([day])
    early = make_store("early")
    assert early.dates() == [] and late.dates() == [day]
    assert (early.processed_dir / "imerg_late_2024.npy").exists()
    assert not (early.processed_dir / "imerg_early_2024.npy").exists()


def test_a_corrupt_index_is_refused(tmp_path):
    rain = tmp_path / "rain"
    rain.mkdir()
    (rain / "imerg_late_index.json").write_text(json.dumps({"years": {"2024": {
        "n_days": 366, "present": ["2024-06-01"], "versions": {}, "missing": [], "failed": []}}}), encoding="utf-8")
    with pytest.raises(ValueError, match="corrupt"):
        ImergStore(rain, "late")


def test_network_errors_during_discovery_propagate_without_touching_the_store(nasa, make_store, monkeypatch):
    monkeypatch.setattr(imerg, "CMR_URL", imerg.CMR_URL.replace("/cmr", "/nowhere"))
    store = make_store()
    with pytest.raises(DownloadError):
        store.update([date(2024, 6, 1)])
    assert store.dates() == [] and not (store.processed_dir / "imerg_late_index.json").exists()


# ------------------------------------------------------------------------------------------ CLI

TODAY = date(2026, 10, 15)


def test_resolve_ranges_defaults_and_yesterday():
    assert imerg_build.resolve_ranges("late", None, None, TODAY) == [(date(2006, 10, 1), date(2026, 10, 14))]
    assert imerg_build.resolve_ranges("late", "2024-07-01", "yesterday", TODAY) == [(date(2024, 7, 1), date(2026, 10, 14))]
    assert imerg_build.resolve_ranges("early", "yesterday", "yesterday", TODAY) == [(date(2026, 10, 14), date(2026, 10, 14))]


def test_resolve_ranges_early_without_dates_is_the_configured_backtest_windows():
    assert imerg_build.resolve_ranges("early", None, None, TODAY) == [
        (date(2018, 6, 1), date(2018, 9, 30)), (date(2023, 5, 1), date(2023, 8, 15)),
        (date(2024, 6, 1), date(2024, 8, 15))]


def test_resolve_ranges_refuses_unusable_combinations():
    with pytest.raises(ValueError, match="--start"):
        imerg_build.resolve_ranges("early", None, "2024-07-01", TODAY)
    with pytest.raises(ValueError, match="empty range"):
        imerg_build.resolve_ranges("late", "2024-07-02", "2024-07-01", TODAY)


def test_cli_builds_a_range_then_does_nothing_on_the_rerun(nasa, isolated_data_root, tmp_path, capsys):
    days = days_from(date(2024, 6, 1), 3)
    publish(nasa, days[:2])
    argv = ["--run", "late", "--start", "2024-06-01", "--end", "2024-06-03", "--workers", "2",
            "--manifest", str(tmp_path / "manifest.jsonl")]
    assert imerg_build.main(argv) == 0
    out = capsys.readouterr().out
    assert "added 2" in out and "missing 1" in out and "2024-06-03" in out and "2024: 2 present, 1 missing" in out
    store = ImergStore(isolated_data_root / "processed" / "rain", "late")
    assert store.dates() == days[:2]
    hits = (nasa.cmr_hits, len(nasa.data_hits))
    publish(nasa, days[2:])
    assert imerg_build.main(argv) == 0
    assert "added 1" in capsys.readouterr().out and nasa.cmr_hits == hits[0] + 1 and len(nasa.data_hits) == hits[1] + 1


def test_cli_exit_status_is_1_when_a_day_fails(nasa, isolated_data_root, tmp_path, capsys):
    publish(nasa, [date(2024, 6, 1)])
    nasa.granules[date(2024, 6, 1)]["status"] = 403
    argv = ["--run", "late", "--start", "2024-06-01", "--end", "2024-06-01", "--manifest", str(tmp_path / "m.jsonl")]
    assert imerg_build.main(argv) == 1
    assert "1 failed day(s)" in capsys.readouterr().err


def test_cli_rejects_more_workers_than_the_politeness_limit(capsys):
    with pytest.raises(SystemExit) as info:
        imerg_build.main(["--run", "late", "--workers", "7"])
    assert info.value.code == 2 and "--workers" in capsys.readouterr().err


# ------------------------------------------------------------------------------------------ real data

REAL_DIR = data_root() / "processed" / "rain"


def _real(run):
    if not (REAL_DIR / f"imerg_{run}_index.json").exists():
        pytest.skip(f"real IMERG {run} store not built (python -m aetherguard.ingest.imerg_build --run {run})")
    return ImergStore(REAL_DIR, run)


@pytest.mark.realdata
def test_real_wayanad_2018_08_15_matches_the_probe_anchor_for_late_and_early():
    row, col = imerg_pixel(latlon_to_cell(*WAYANAD))
    late = _real("late").gather([row], [col], date(2018, 8, 15), 1)[0, 0]
    early = _real("early").gather([row], [col], date(2018, 8, 15), 1)[0, 0]
    assert late == pytest.approx(61.0, abs=0.01) and early == pytest.approx(44.5, abs=0.05)


@pytest.mark.realdata
def test_real_wayanad_2024_07_29_and_30_are_finite_and_positive():
    row, col = imerg_pixel(latlon_to_cell(*WAYANAD))
    values = _real("late").gather([row], [col], date(2024, 7, 29), 2)[0]
    assert np.isfinite(values).all() and (values > 0).all()


@pytest.mark.realdata
def test_real_kathmandu_cell_is_finite():
    row, col = imerg_pixel(latlon_to_cell(27.7, 85.3))
    series = _real("late").gather([row], [col], date(2024, 7, 1), 31)[0]
    assert np.isfinite(series).all() and series.max() > 0


@pytest.mark.realdata
def test_real_late_store_reports_its_missing_days_explicitly():
    store = _real("late")
    index = json.loads((REAL_DIR / "imerg_late_index.json").read_text(encoding="utf-8"))
    first = store.dates()[0]
    assert first == date(2006, 10, 1)
    listed = {d for y in index["years"].values() for d in y["missing"] + y["failed"]}
    start, end = first, store.dates()[-1]
    expected_gap = {(start + timedelta(k)).isoformat() for k in range((end - start).days + 1)} - \
        {d.isoformat() for d in store.dates()}
    assert expected_gap <= listed
    assert datetime.now(timezone.utc).date() - end <= timedelta(days=30)
