"""Offline tests for the live-source probe: report assembly, failure handling and the pure format helpers."""
import json
import time
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from aetherguard.live import probe

DOMAIN = {"lat_min": 8.0, "lat_max": 36.0, "lon_min": 72.0, "lon_max": 98.0}
NOW = datetime(2026, 10, 14, 14, 0, tzinfo=timezone.utc)


def fake_probe(name="src", **overrides):
    raw = {"name": name, "reachable": True, "url_pattern": "https://example.test/{day}", "auth": "none",
           "format": "netCDF4", "variables": {"rain": {"units": "mm/day"}}, "bytes_per_day_domain": 1000.0,
           "seconds_per_day": 2.5, "latency_hours": 12.0, "history_start": "2000-06-01", "decision": "use",
           "notes": ["ok"]}
    raw.update(overrides)
    return raw


# ------------------------------------------------------------------ report assembly
def test_report_is_strict_json_with_nan_and_numpy_values_as_null():
    report = probe.build_report(
        [fake_probe(latency_hours=float("nan"), bytes_per_day_domain=np.float32("inf"),
                    details={"values": np.array([1.0, np.nan]), "count": np.int64(3), "day": date(2018, 8, 15)})],
        NOW, DOMAIN)
    text = json.dumps(report, allow_nan=False)  # raises on NaN / Infinity
    source = json.loads(text)["sources"][0]
    assert source["latency_hours"] is None and source["bytes_per_day_domain"] is None
    assert source["details"] == {"values": [1.0, None], "count": 3, "day": "2018-08-15"}


def test_every_source_carries_every_required_field_even_when_nothing_was_measured():
    report = probe.build_report([{"name": "bare"}], NOW, DOMAIN)
    source = report["sources"][0]
    for field in probe.SOURCE_FIELDS:
        assert field in source
    assert source["reachable"] is False and source["decision"] == "drop" and source["notes"] == []


@pytest.mark.parametrize("decision", probe.DECISIONS)
def test_valid_decisions_are_kept(decision):
    assert probe.assemble_source(fake_probe(decision=decision))["decision"] == decision


@pytest.mark.parametrize("decision", ["maybe", "", "USE", None])
def test_an_invalid_decision_is_rejected(decision):
    with pytest.raises(ValueError, match="decision"):
        probe.assemble_source(fake_probe(decision=decision))


def test_user_actions_are_collected_at_the_top_of_the_report():
    report = probe.build_report([fake_probe("a"), fake_probe("b", needs_user_action="approve the app")], NOW, DOMAIN)
    assert report["needs_user_action"] == [{"source": "b", "action": "approve the app"}]
    assert "## Needs human action" in probe.render_markdown(report)
    assert "approve the app" in probe.render_markdown(report)


# ------------------------------------------------------------------ failure handling
def test_a_raising_probe_becomes_unreachable_with_only_the_class_name():
    secret_url = "https://data.example.test/file?token=SUPERSECRET123"

    def raising(result, deadline):
        result["format"] = "partial knowledge kept"
        raise RuntimeError(f"HTTP 500 from {secret_url}")

    outcome = probe.run_probe("boom", raising, timeout_s=5)
    source = probe.assemble_source(outcome)
    assert source["reachable"] is False and source["error_class"] == "RuntimeError"
    assert source["decision"] == "drop" and source["format"] == "partial knowledge kept"
    assert "SUPERSECRET123" not in json.dumps(source) and "token" not in json.dumps(source)


def test_a_probe_that_exceeds_its_time_box_is_marked_with_timeouterror():
    started = time.monotonic()
    outcome = probe.run_probe("slow", lambda result, deadline: time.sleep(2.0), timeout_s=0.2)
    assert time.monotonic() - started < 1.5
    assert outcome["reachable"] is False and outcome["error_class"] == "TimeoutError"


def test_a_successful_probe_returns_what_it_filled_in_and_gets_a_deadline():
    seen = {}

    def fine(result, deadline):
        seen["remaining"] = deadline - time.monotonic()
        result.update(reachable=True, decision="fallback")

    outcome = probe.run_probe("fine", fine, timeout_s=30)
    assert outcome["reachable"] is True and outcome["decision"] == "fallback" and "error_class" not in outcome
    assert 0 < seen["remaining"] < 30


def test_write_report_redacts_known_secrets_and_writes_valid_json(tmp_path):
    report = probe.build_report([fake_probe(notes=["leaked s3cr3t-value here"])], NOW, DOMAIN)
    md, js = probe.write_report(report, tmp_path / "reports", ["s3cr3t-value"])
    assert js.name == "phase6_live_sources_probe.json" and md.name == "phase6_live_sources_probe.md"
    assert "s3cr3t-value" not in js.read_text(encoding="utf-8") + md.read_text(encoding="utf-8")
    parsed = json.loads(js.read_text(encoding="utf-8"), parse_constant=pytest.fail)
    assert parsed["sources"][0]["name"] == "src"
    assert "| src | yes | use |" in md.read_text(encoding="utf-8")


def test_run_writes_the_report_from_fake_probes(isolated_data_root, tmp_path, monkeypatch):
    fakes = {"one": lambda r, d: r.update(reachable=True, decision="use", notes=["fine"]),
             "two": lambda r, d: (_ for _ in ()).throw(ConnectionError("https://x.test/?key=ABCDEFGH"))}
    monkeypatch.setattr(probe, "build_probes", lambda ctx: fakes)
    monkeypatch.setattr(probe, "collect_secrets", lambda: ["ABCDEFGH"])
    report = probe.run(None, 5, tmp_path / "out")
    assert [s["name"] for s in report["sources"]] == ["one", "two"]
    assert report["sources"][1]["error_class"] == "ConnectionError"
    assert report["extras"]["chosen_paths"]["gfs_live"] is None
    assert (tmp_path / "out" / "phase6_live_sources_probe.json").is_file()


def test_run_rejects_an_unknown_probe_name_before_doing_anything(isolated_data_root, tmp_path):
    with pytest.raises(SystemExit, match="unknown probe"):
        probe.run({"nope"}, 5, tmp_path / "out")
    assert not (tmp_path / "out").exists()


# ------------------------------------------------------------------ extrapolation and the intensity rule
def test_day_counts_for_the_training_history():
    assert probe.monsoon_days(date(2007, 6, 1), date(2007, 9, 30)) == 122
    assert probe.monsoon_days(date(2006, 10, 1), date(2018, 12, 31)) == 12 * 122
    extra = probe.extrapolate_history(10.0, 1e6)
    assert extra["days_all"] == 4475 and extra["days_monsoon"] == 1464
    assert extra["hours_monsoon"] == pytest.approx(10.0 * 1464 / 3600)
    assert extra["gb_all"] == pytest.approx(4475 * 1e6 / 1e9)


def test_unmeasured_extrapolation_stays_unmeasured():
    extra = probe.extrapolate_history(None, None)
    assert extra["hours_all"] is None and extra["gb_monsoon"] is None


@pytest.mark.parametrize("hours, gb, expected", [
    (11.99, 19.99, "use"), (12.0, 5.0, "drop"), (5.0, 20.0, "drop"), (0.0, 0.0, "use"),
    (None, 1.0, "drop"), (1.0, None, "drop"), (None, None, "drop")])
def test_intensity_group_is_used_only_under_both_limits(hours, gb, expected):
    assert probe.intensity_decision(hours, gb) == expected


# ------------------------------------------------------------------ IMERG helpers
def test_imerg_pixel_ranges_for_the_domain():
    assert probe.imerg_index_range(72.0, 98.0, "lon") == (2520, 2779)
    assert probe.imerg_index_range(8.0, 36.0, "lat") == (980, 1259)
    assert probe.imerg_index_range(72.05, 72.05, "lon") == (2520, 2520)


def test_granule_info_reads_times_size_and_links():
    entry = {"title": "GPM_3IMERGDL.07:3B-DAY-L.MS.MRG.3IMERG.20261012-S000000-E235959.V07C.nc4",
             "time_start": "2026-10-12T00:00:00.000Z", "time_end": "2026-10-12T23:59:59.999Z",
             "updated": "2026-10-13T14:27:14.000Z", "granule_size": "28.5",
             "links": [{"rel": "http://esipfed.org/ns/fedsearch/1.1/documentation#", "href": "https://doc.test/x.pdf"},
                       {"rel": "http://esipfed.org/ns/fedsearch/1.1/data#",
                        "href": "https://data.gesdisc.earthdata.nasa.gov/data/GPM_L3/f.nc4"},
                       {"rel": "http://esipfed.org/ns/fedsearch/1.1/service#",
                        "href": "https://opendap.earthdata.nasa.gov/collections/C1/granules/GPM_3IMERGDL.07%3Af.nc4"}]}
    info = probe.granule_info(entry)
    assert info["file_name"].endswith("V07C.nc4") and info["size_bytes"] == int(28.5 * 1024 * 1024)
    assert info["data_url"].startswith("https://data.gesdisc.earthdata.nasa.gov/data/")
    assert info["opendap_url"].startswith("https://opendap.earthdata.nasa.gov/collections/")
    assert probe.hours_between(info["time_end"], info["ingested"]) == pytest.approx(14.45, abs=0.01)


APPROVAL_URL = ("https://gpm1.gesdisc.eosdis.nasa.gov/data-redirect?error=access_denied&error_msg=Pre+authorization"
                "&resolution_url=https%3A%2F%2Furs.earthdata.nasa.gov%2Fapprove_app%3Fclient_id%3DABC&state=x")


def test_unapproved_application_is_recognised_from_the_redirect_chain():
    state, resolution = probe.classify_earthdata_access(
        200, ["https://gpm1.test/data/f.nc4", "https://urs.test/oauth/authorize?client_id=ABC", APPROVAL_URL],
        b"<!DOCTYPE")
    assert state == "app_not_authorized"
    assert resolution == "https://urs.earthdata.nasa.gov/approve_app?client_id=ABC"


@pytest.mark.parametrize("status, head, expected", [
    (200, b"\x89HDF\r\n\x1a\n", "ok"), (200, b"CDF\x01", "ok"), (200, b"<!DOCTYPE", "unexpected_response"),
    (401, b"", "unauthorized"), (403, b"x", "unauthorized"), (500, b"x", "unexpected_response")])
def test_earthdata_access_classification(status, head, expected):
    assert probe.classify_earthdata_access(status, ["https://data.test/f.nc4"], head)[0] == expected


DMR = """<?xml version="1.0"?>
<Dataset xmlns="http://xml.opendap.org/ns/DAP/4.0#" name="f.nc4">
  <Dimension name="time" size="1"/><Dimension name="lon" size="3600"/><Dimension name="lat" size="1800"/>
  <Group name="Grid">
    <Float32 name="precipitation"><Dim name="/Grid/time"/><Dim name="/Grid/lon"/><Dim name="/Grid/lat"/></Float32>
  </Group>
  <Float32 name="other"><Dim name="/lat"/><Dim name="/lon"/></Float32>
</Dataset>"""


def test_dimension_order_is_read_from_the_dmr():
    assert probe.dmr_dim_order(DMR, "precipitation") == ["Grid/time", "Grid/lon", "Grid/lat"]
    assert probe.dmr_dim_order(DMR, "other") == ["lat", "lon"]
    with pytest.raises(LookupError):
        probe.dmr_dim_order(DMR, "missing")


def test_constraint_expression_follows_the_file_dimension_order():
    ce = probe.dap4_constraint("precipitation", ["time", "lon", "lat"], (2520, 2779), (980, 1259))
    assert ce == ("dap4.ce=/precipitation[0][2520:2779][980:1259];/time;/lon[2520:2779];/lat[980:1259]")
    swapped = probe.dap4_constraint("Grid/precipitation", ["time", "lat", "lon"], (2520, 2779), (980, 1259))
    assert swapped.startswith("dap4.ce=/Grid/precipitation[0][980:1259][2520:2779];/Grid/time;/Grid/lon[")


def write_imerg_like(path, point_value=123.4):
    """A small file in the IMERG daily layout: dims (time, lon, lat), ascending axes, 0.1-degree pixel centres."""
    lon = np.round(np.arange(70.05, 100.0, 0.1), 2)
    lat = np.round(np.arange(5.05, 40.0, 0.1), 2)
    data = np.full((1, lon.size, lat.size), 1.0, dtype="float32")
    wayanad = (int(np.abs(lon - 76.13).argmin()), int(np.abs(lat - 11.47).argmin()))
    data[0, wayanad[0], wayanad[1]] = np.nan if point_value is None else point_value
    data[0, int(np.abs(lon - 80.05).argmin()), int(np.abs(lat - 20.05).argmin())] = np.nan  # one more gap in the domain
    ds = xr.Dataset({"precipitation": (("time", "lon", "lat"), data, {"units": "mm/day"})},
                    coords={"time": [0], "lon": lon, "lat": lat})
    ds.to_netcdf(path, engine="scipy", encoding={"precipitation": {"_FillValue": np.float32(-9999.9)}})
    return lon[wayanad[0]], lat[wayanad[1]]


def test_precipitation_description_reports_dims_orientation_fill_and_the_wayanad_value(tmp_path):
    path = tmp_path / "imerg_like.nc"
    lon, lat = write_imerg_like(path)
    info = probe.read_precipitation(path, DOMAIN)
    assert info["engine"] in probe.READ_ENGINES
    assert info["variable"] == "precipitation" and info["units"] == "mm/day"
    assert info["dims_order"] == ["time", "lon", "lat"]
    assert info["lat_ascending"] is True and info["lon_ascending"] is True
    assert info["fill_value"] == pytest.approx(-9999.9, rel=1e-6)
    assert info["point_value"] == pytest.approx(123.4, rel=1e-5) and info["point_plausible"] is True
    assert (info["point_lat"], info["point_lon"]) == pytest.approx((lat, lon))
    assert info["shape_domain"] == [1, 260, 280]
    assert info["domain_valid_share"] == pytest.approx(1 - 1 / (260 * 280))


def test_a_missing_point_value_is_none_and_not_plausible(tmp_path):
    path = tmp_path / "gap.nc"
    write_imerg_like(path, point_value=None)
    info = probe.read_precipitation(path, DOMAIN)
    assert info["point_value"] is None and info["point_plausible"] is False


def test_a_file_without_a_precipitation_variable_is_an_error(tmp_path):
    path = tmp_path / "other.nc"
    xr.Dataset({"temp": (("lat", "lon"), np.zeros((2, 2), dtype="float32"))},
               coords={"lat": [1.0, 2.0], "lon": [1.0, 2.0]}).to_netcdf(path, engine="scipy")
    with pytest.raises(LookupError):
        probe.read_precipitation(path, DOMAIN)


def test_unreadable_file_names_the_engines_tried_without_a_path(tmp_path):
    path = tmp_path / "junk.nc"
    path.write_bytes(b"not a netcdf file at all")
    with pytest.raises(OSError, match="no xarray engine"):
        probe.open_dataset_any(path)


# ------------------------------------------------------------------ GFS helpers
LISTING = ('<a href="gfs.t06z.pgrb2.0p25.f096">gfs.t06z.pgrb2.0p25.f096</a>   14-Oct-2026 09:56  521M   '
           '<a href="gfs.t06z.pgrb2.0p25.f096.idx">gfs.t06z.pgrb2.0p25.f096.idx</a>   14-Oct-2026 09:56  30K\n'
           '<a href="gfs.t06z.pgrb2.0p25.f003">gfs.t06z.pgrb2.0p25.f003</a>   14-Oct-2026 09:32  500M\n')


def test_nomads_listing_gives_publication_times_by_forecast_hour():
    files = probe.parse_nomads_listing(LISTING)
    assert sorted(files) == [3, 96]  # the .idx entries are not forecast files
    assert files[96] == (datetime(2026, 10, 14, 9, 56, tzinfo=timezone.utc), "521M")


def test_grib_filter_request_selects_apcp_and_the_domain():
    params = probe.nomads_filter_params(datetime(2026, 10, 14, 6, tzinfo=timezone.utc), 24, DOMAIN)
    assert params == {"dir": "/gfs.20261014/06/atmos", "file": "gfs.t06z.pgrb2.0p25.f024", "var_APCP": "on",
                      "lev_surface": "on", "subregion": "", "leftlon": 72.0, "rightlon": 98.0, "toplat": 36.0,
                      "bottomlat": 8.0}


IDX = ("1:0:d=2023071500:PRMSL:mean sea level:24 hour fcst:\n"
       "596:431119784:d=2023071500:APCP:surface:18-24 hour acc fcst:\n"
       "597:431487086:d=2023071500:APCP:surface:0-1 day acc fcst:\n"
       "598:432003066:d=2023071500:ACPCP:surface:18-24 hour acc fcst:\n")


def test_idx_records_give_exact_byte_ranges_for_the_apcp_messages_only():
    ranges = probe.apcp_byte_ranges(probe.parse_idx(IDX))
    assert ranges == [(431119784, 431487085, "18-24 hour acc fcst"), (431487086, 432003065, "0-1 day acc fcst")]


def test_last_idx_record_runs_to_the_end_of_the_file():
    records = probe.parse_idx("1:0:d=2023071500:APCP:surface:0-3 hour acc fcst:\n")
    assert probe.apcp_byte_ranges(records) == [(0, None, "0-3 hour acc fcst")]


def test_global_field_crop_matches_the_nomads_domain_grid():
    ni, nj = 1440, 721
    field = (np.arange(nj)[:, None] * 10_000 + np.arange(ni)[None, :]).astype(float)  # row*10000 + column
    crop = probe.crop_global_025(field.reshape(-1), ni, nj, 90.0, DOMAIN)
    assert crop.shape == (113, 105)  # 8-36 N and 72-98 E, as the NOMADS subset
    assert crop[0, 0] == 216 * 10_000 + 288  # row 216 = 36 N (north first), column 288 = 72 E
    assert crop[-1, -1] == 328 * 10_000 + 392  # row 328 = 8 N, column 392 = 98 E


def test_archive_first_day_is_the_earliest_dated_directory():
    assert probe._aws_first_day(["gfs.20210101/", "gfs.20210102/"]) == "2021-01-01"
    assert probe._aws_first_day(["gfs.2021"]) is None


def test_grib_messages_decode_with_grid_metadata(tmp_path):
    eccodes = pytest.importorskip("eccodes")
    gid = eccodes.codes_grib_new_from_samples("regular_ll_sfc_grib2")
    try:
        count = eccodes.codes_get(gid, "numberOfValues")
        eccodes.codes_set_values(gid, np.linspace(0.0, 5.0, count))
        path = tmp_path / "sample.grib2"
        with path.open("wb") as handle:
            eccodes.codes_write(gid, handle)
    finally:
        eccodes.codes_release(gid)
    messages = probe.decode_grib(path)
    assert len(messages) == 1
    message = messages[0]
    assert message["ni"] * message["nj"] == message["values"].size
    assert message["min"] == pytest.approx(0.0, abs=1e-3) and message["max"] == pytest.approx(5.0, abs=1e-3)
    assert "values" not in probe._summary(messages)[0]


# ------------------------------------------------------------------ GHCN-Daily helpers
def test_ncei_rows_give_newest_date_and_quality_flags_per_station():
    rows = [{"DATE": "2026-10-01", "STATION": "A", "PRCP": "0.0", "PRCP_ATTRIBUTES": "H,,2"},
            {"DATE": "2026-10-03", "STATION": "A", "PRCP": "4.5", "PRCP_ATTRIBUTES": ",K,S"},
            {"DATE": "2026-10-09", "STATION": "A"},  # a row without PRCP is a gap, not a zero
            {"DATE": "2026-10-02", "STATION": "B", "PRCP": "  ", "PRCP_ATTRIBUTES": ",,S"},
            {"DATE": "2026-10-04", "STATION": "C", "PRCP": "1.0", "PRCP_ATTRIBUTES": ",K,S"}]
    parsed = probe.parse_ncei_rows(rows)
    assert parsed["n_rows"] == 5 and parsed["n_prcp"] == 3
    assert parsed["newest_by_station"] == {"A": "2026-10-03", "C": "2026-10-04"}
    assert parsed["qflag_counts"] == {"K": 2}


def test_ghcn_station_selection_spreads_ten_stations_over_the_selection(tmp_path):
    raw = tmp_path / "raw" / "ghcnd"
    raw.mkdir(parents=True)
    inventory, stations = [], []
    for k in range(40):
        sid = f"IN{k:09d}"
        stations.append(f"{sid:<11} {10.0 + k * 0.1:8.4f} {76.0:9.4f} {100.0:6.1f} {'':<2} {'S' + str(k):<30}")
        inventory.append(f"{sid:<11} {10.0 + k * 0.1:8.4f} {76.0:9.4f} {'PRCP':<4} 2000 2025")
    (raw / "ghcnd-stations.txt").write_text("\n".join(stations) + "\n", encoding="ascii")
    (raw / "ghcnd-inventory.txt").write_text("\n".join(inventory) + "\n", encoding="ascii")
    cfg = {"ghcnd": {"countries": ["IN"], "first_year_max": 2015, "last_year_min": 2024, "upland_min_elev_m": 500}}
    selected, ids = probe.select_ghcn_stations(cfg, tmp_path)
    assert isinstance(selected, pd.DataFrame) and len(selected) == 40
    assert len(ids) == 10 and ids[0] == "IN000000000" and ids[1] == "IN000000004"


def test_chosen_paths_name_only_sources_decided_use():
    sources = [{"name": "imerg_late_daily", "decision": "use"}, {"name": "imerg_early_daily", "decision": "fallback"},
               {"name": "imerg_late_halfhourly", "decision": "drop"},
               {"name": "gfs_nomads_grib_filter", "decision": "use"}, {"name": "gfs_aws_archive", "decision": "drop"}]
    paths = probe.chosen_paths(sources)
    assert paths["imerg_primary"] == "imerg_late_daily" and paths["imerg_same_day_decision"] == "fallback"
    assert paths["gfs_live"] == "gfs_nomads_grib_filter" and paths["gfs_archive"] is None
    assert paths["imerg_intensity_group_decision"] == "drop"


# ------------------------------------------------------------------ IMERG probe flow with faked network
def granule_entry(day, ingested, size_mib=28.0, stem="3B-DAY-L.MS.MRG.3IMERG", short="GPM_3IMERGDL", version="V07C"):
    ymd = day.replace("-", "")
    file_name = f"{stem}.{ymd}-S000000-E235959.{version}.nc4"
    return {"title": f"{short}.07:{file_name}", "time_start": f"{day}T00:00:00.000Z",
            "time_end": f"{day}T23:59:59.999Z", "updated": ingested, "granule_size": str(size_mib),
            "links": [{"rel": "http://esipfed.org/ns/fedsearch/1.1/data#",
                       "href": f"https://data.test/data/{file_name}"},
                      {"rel": "http://esipfed.org/ns/fedsearch/1.1/service#",
                       "href": f"https://opendap.earthdata.nasa.gov/collections/C1/granules/{short}.07%3A{file_name}"}]}


def fake_cmr(url, params=None, **kwargs):
    if url.endswith("collections.json"):
        return {"feed": {"entry": [{"id": "C1"}]}}
    if params.get("temporal"):
        return {"feed": {"entry": [granule_entry("2018-08-15", "2024-06-12T05:33:16.000Z")] * params["page_size"]}}
    if params["sort_key"] == "start_date":
        return {"feed": {"entry": [granule_entry("1998-01-01", "2024-12-10T16:42:38.000Z", 24.0)]}}
    return {"feed": {"entry": [granule_entry("2026-10-12", "2026-10-13T14:27:14.000Z")] * params["page_size"]}}


@pytest.fixture
def ctx(tmp_path):
    from aetherguard.manifest import Manifest
    root = tmp_path / "data"
    root.mkdir()
    return probe.Context(DOMAIN, NOW, root, Manifest(tmp_path / "manifest.jsonl", root), {})


def test_daily_probe_when_the_application_is_not_approved_keeps_cmr_facts_and_asks_for_action(ctx, monkeypatch):
    monkeypatch.setattr(probe, "fetch_json", fake_cmr)
    monkeypatch.setattr(probe, "preflight_earthdata",
                        lambda url: ("app_not_authorized", "https://urs.test/approve_app?client_id=ABC"))
    result = {"name": "imerg_late_daily"}
    probe.probe_imerg_daily(result, time.monotonic() + 100, ctx, "GPM_3IMERGDL", "use", "primary")
    assert result["reachable"] is True and result["history_start"] == "1998-01-01"
    assert result["latency_hours"] == pytest.approx(14.45, abs=0.01)
    assert result["decision"] == "use" and result["decision_basis"].startswith("provisional")
    assert "https://urs.test/approve_app?client_id=ABC" in result["needs_user_action"]
    assert result["bytes_per_day_domain"] is None and result["details"]["data_access"] == "app_not_authorized"
    json.dumps(probe.assemble_source(result), allow_nan=False)


def test_daily_probe_measures_the_subset_and_reads_the_value_at_wayanad(ctx, monkeypatch):
    monkeypatch.setattr(probe, "fetch_json", fake_cmr)
    monkeypatch.setattr(probe, "preflight_earthdata", lambda url: ("ok", None))

    def fake_subset(c, granule, dest, variable_path, source):
        dest.parent.mkdir(parents=True, exist_ok=True)
        write_imerg_like(dest)
        return {"pattern": "hyrax_cloud_dap4_dap.nc4", "bytes": 4321, "seconds": 3.5}

    monkeypatch.setattr(probe, "_fetch_imerg_subset", fake_subset)
    result = {"name": "imerg_early_daily"}
    probe.probe_imerg_daily(result, time.monotonic() + 100, ctx, "GPM_3IMERGDE", "fallback", "same day")
    assert [d["which"] for d in result["details"]["days"]] == ["historical", "newest"]
    assert result["details"]["days"][0]["array"]["point_value"] == pytest.approx(123.4, rel=1e-5)
    assert result["bytes_per_day_domain"] == 4321 and result["seconds_per_day"] == 3.5
    assert result["variables"]["precipitation"]["dims_order"] == ["time", "lon", "lat"]
    assert result["decision"] == "fallback" and result["decision_basis"] == "measured"
    assert "needs_user_action" not in result


def test_daily_probe_falls_back_to_the_full_file_when_no_subset_pattern_works(ctx, monkeypatch):
    monkeypatch.setattr(probe, "fetch_json", fake_cmr)
    monkeypatch.setattr(probe, "preflight_earthdata", lambda url: ("ok", None))
    monkeypatch.setattr(probe, "_fetch_imerg_subset",
                        lambda *a, **k: {"pattern": None, "failed_attempts": ["a:DownloadError"]})

    def fake_full(c, url, dest, source):
        dest.parent.mkdir(parents=True, exist_ok=True)
        write_imerg_like(dest)
        return {"bytes": 30_000_000, "seconds": 20.0}

    monkeypatch.setattr(probe, "_timed_download", fake_full)
    result = {"name": "imerg_late_daily"}
    probe.probe_imerg_daily(result, time.monotonic() + 100, ctx, "GPM_3IMERGDL", "use", "primary")
    assert result["bytes_per_day_domain"] == 30_000_000 and result["seconds_per_day"] == 20.0
    assert result["details"]["days"][0]["full_file"]["bytes"] == 30_000_000


@pytest.mark.parametrize("seconds, size, expected", [(0.2, 100_000, "use"), (2.0, 3_000_000, "drop")])
def test_half_hourly_decision_follows_the_measured_monsoon_cost(ctx, monkeypatch, seconds, size, expected):
    stem = "3B-HHR-L.MS.MRG.3IMERG"

    def cmr(url, params=None, **kwargs):
        if url.endswith("collections.json"):
            return {"feed": {"entry": [{"id": "C2"}]}}
        count = 48 if params.get("temporal") else 1
        return {"feed": {"entry": [granule_entry("2018-08-15", "2024-06-12T05:33:16.000Z", 7.0, stem,
                                                 "GPM_3IMERGHHL", "V07B")] * count}}

    def fake_subset(c, granule, dest, variable_path, source):
        dest.parent.mkdir(parents=True, exist_ok=True)
        write_imerg_like(dest)
        return {"pattern": "p", "bytes": size, "seconds": seconds}

    monkeypatch.setattr(probe, "fetch_json", cmr)
    monkeypatch.setattr(probe, "preflight_earthdata", lambda url: ("ok", None))
    monkeypatch.setattr(probe, "_fetch_imerg_subset", fake_subset)
    monkeypatch.setattr(probe, "read_precipitation", lambda path, domain, group=None: {
        k: None for k in ("variable", "units", "fill_value", "dims_order", "lat_ascending", "lon_ascending")})
    result = {"name": "imerg_late_halfhourly"}
    probe.probe_imerg_halfhourly(result, time.monotonic() + 100, ctx)
    assert result["details"]["granules_on_2018_08_15"] == 48
    assert result["seconds_per_day"] == pytest.approx(seconds * 48)
    assert result["decision"] == expected


def test_half_hourly_stays_dropped_and_unmeasured_when_access_is_blocked(ctx, monkeypatch):
    def cmr(url, params=None, **kwargs):
        if url.endswith("collections.json"):
            return {"feed": {"entry": [{"id": "C2"}]}}
        return {"feed": {"entry": [granule_entry("2018-08-15", "2024-06-12T05:33:16.000Z", 7.0)] * 48}}

    monkeypatch.setattr(probe, "fetch_json", cmr)
    monkeypatch.setattr(probe, "preflight_earthdata", lambda url: ("app_not_authorized", None))
    result = {"name": "imerg_late_halfhourly"}
    probe.probe_imerg_halfhourly(result, time.monotonic() + 100, ctx)
    assert result["decision"] == "drop" and "seconds_per_day" not in result
    assert result["details"]["full_files_extrapolation"]["gb_monsoon"] > 20  # the full-file route alone fails the limit
    assert "NASA GESDISC DATA ARCHIVE" in result["needs_user_action"]


# ------------------------------------------------------------------ download helpers with a faked transfer
def test_subset_attempts_try_the_next_pattern_and_use_the_dmr_dimension_order(ctx, monkeypatch):
    urls = []

    class Reply:
        text = DMR

    def fake_download(url, dest, manifest, source, licence, **kwargs):
        urls.append(url)
        if ".dap.nc4?" in url:
            raise RuntimeError("first pattern refused")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"\x89HDF" + b"0" * 100)
        return dest

    monkeypatch.setattr(probe, "_get", lambda url, **k: Reply())
    monkeypatch.setattr(probe, "download", fake_download)
    granule = probe.granule_info(granule_entry("2018-08-15", "2024-06-12T05:33:16.000Z"))
    out = probe._fetch_imerg_subset(ctx, granule, ctx.work_dir / "sub.nc4", "Grid/precipitation", "test")
    assert out["pattern"] == "hyrax_cloud_dap4_nc4" and out["bytes"] == 104
    assert out["dims_assumed_or_read"] == ["Grid/time", "Grid/lon", "Grid/lat"]
    assert urls[0].split("?")[1].startswith("dap4.ce=/Grid/precipitation[0][2520:2779][980:1259]")


def test_all_failed_subset_patterns_are_listed_by_class_only(ctx, monkeypatch):
    def refuse(*args, **kwargs):
        raise ConnectionError("https://x.test/?token=SECRETVALUE")

    monkeypatch.setattr(probe, "_get", lambda url, **k: (_ for _ in ()).throw(TimeoutError()))
    monkeypatch.setattr(probe, "download", refuse)
    granule = probe.granule_info(granule_entry("2018-08-15", "2024-06-12T05:33:16.000Z"))
    out = probe._fetch_imerg_subset(ctx, granule, ctx.work_dir / "sub.nc4", "precipitation", "test")
    assert out["pattern"] is None
    assert out["failed_attempts"] == ["hyrax_cloud_dap4_dap.nc4:ConnectionError",
                                      "hyrax_cloud_dap4_nc4:ConnectionError"]
    assert "SECRETVALUE" not in json.dumps(out)


def test_a_download_that_is_not_a_netcdf_file_is_discarded(ctx, monkeypatch):
    def html_download(url, dest, manifest, source, licence, **kwargs):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"<!DOCTYPE html>login page")
        return dest

    monkeypatch.setattr(probe, "download", html_download)
    dest = ctx.work_dir / "x" / "f.nc4"
    with pytest.raises(ValueError, match="not netCDF"):
        probe._timed_download(ctx, "https://data.test/f.nc4", dest, "test")
    assert not dest.exists()


# ------------------------------------------------------------------ IMD real-time fetch and read
class _Reply:
    def __init__(self, content=b"", status=200):
        self.content, self.status_code = content, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise probe.requests.HTTPError(f"HTTP {self.status_code}")


def test_imd_post_writes_a_complete_file(tmp_path, monkeypatch):
    sent = {}

    def fake_post(url, **kw):
        sent.update(kw)
        return _Reply(b"x" * probe.IMD_FILE_BYTES)

    monkeypatch.setattr(probe.requests, "post", fake_post)
    dest = tmp_path / "f.grd"
    assert probe._post_imd_day(date(2026, 10, 13), dest) is True
    assert sent["data"] == {"rain": "13102026"} and sent["timeout"] > 0
    assert dest.stat().st_size == probe.IMD_FILE_BYTES


def test_imd_day_that_is_not_published_is_an_empty_response_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(probe.requests, "post", lambda url, **kw: _Reply(b""))
    dest = tmp_path / "f.grd"
    assert probe._post_imd_day(date(2026, 10, 15), dest) is False and not dest.exists()


def test_imd_post_retries_once_after_a_timeout_then_gives_up(tmp_path, monkeypatch):
    calls = []

    def flaky(url, **kw):
        calls.append(1)
        if len(calls) == 1:
            raise probe.requests.ReadTimeout()
        return _Reply(b"x" * probe.IMD_FILE_BYTES)

    monkeypatch.setattr(probe.requests, "post", flaky)
    assert probe._post_imd_day(date(2026, 10, 13), tmp_path / "f.grd") is True and len(calls) == 2

    def always_down(url, **kw):
        raise probe.requests.ConnectTimeout()

    monkeypatch.setattr(probe.requests, "post", always_down)
    with pytest.raises(probe.requests.ConnectTimeout):
        probe._post_imd_day(date(2026, 10, 13), tmp_path / "g.grd")


def test_imd_post_rejects_a_file_of_the_wrong_size(tmp_path, monkeypatch):
    monkeypatch.setattr(probe.requests, "post", lambda url, **kw: _Reply(b"x" * 1000))
    with pytest.raises(ValueError, match="size"):
        probe._post_imd_day(date(2026, 10, 13), tmp_path / "f.grd")


@pytest.mark.filterwarnings("ignore:datetime.datetime.utcnow:DeprecationWarning")  # raised inside imdlib itself
def test_imd_day_is_read_with_latitude_first_orientation(tmp_path, monkeypatch):
    pytest.importorskip("imdlib")
    grid = np.full((129, 135), -999.0, dtype="<f4")
    grid[20, 39] = 50.0  # 11.5 N, 76.25 E: row = (11.5 - 6.5) / 0.25, column = (76.25 - 66.5) / 0.25
    grid[0, 0] = 1.0

    def fake_post(day, dest, **kwargs):
        dest.write_bytes(grid.tobytes())
        return True

    monkeypatch.setattr(probe, "_post_imd_day", fake_post)
    info = probe._read_imd_day(date(2026, 10, 13), tmp_path / "imd", DOMAIN)
    assert info["ok"] and info["dims_order"] == ["time", "lat", "lon"] and info["lat_ascending"] is True
    assert info["wayanad_nearest_mm"] == 50.0
    assert info["valid_cells"] == 2 and info["valid_cells_in_domain"] == 1
    assert info["missing_sentinel_cells_in_file"] == 129 * 135 - 2
    assert info["imdlib_data_attribute_shape"] == [1, 135, 129]  # imdlib's own array is the transpose


def test_imd_probe_reports_the_newest_day_and_an_upper_bound_latency(ctx, monkeypatch):
    def fake_read(day, folder, domain):
        if day == NOW.date():
            return {"day": day.isoformat(), "ok": False, "error_class": "NotPublished", "seconds": 1.0}
        return {"day": day.isoformat(), "ok": True, "seconds": 20.0, "file_bytes": 69660, "units": "mm/day",
                "dims_order": ["time", "lat", "lon"], "lat_ascending": True, "lat_range": [6.5, 38.5],
                "lon_range": [66.5, 100.0], "valid_cells": 4964, "file_cells": 17415}

    monkeypatch.setattr(probe, "_read_imd_day", fake_read)
    result = {"name": "imd_realtime"}
    probe.probe_imd_realtime(result, time.monotonic() + 100, ctx)
    assert result["reachable"] is True and result["decision"] == "use" and result["bytes_per_day_domain"] == 69660
    # newest published day is 2026-10-13, valid until 03:00 UTC that day; probe time is 2026-10-14 14:00 UTC
    assert result["latency_hours"] == pytest.approx(35.0)
    assert [a["day"] for a in result["details"]["attempts"]] == ["2026-10-13", "2026-10-14"]


def test_imd_probe_fails_when_neither_recent_day_can_be_read(ctx, monkeypatch):
    monkeypatch.setattr(probe, "_read_imd_day", lambda day, folder, domain: {
        "day": day.isoformat(), "ok": False, "error_class": "NotPublished", "seconds": 1.0})
    result = {"name": "imd_realtime"}
    probe.probe_imd_realtime(result, time.monotonic() + 100, ctx)
    assert result["reachable"] is False and result["decision"] == "drop"
    assert [a["day"] for a in result["details"]["attempts"]] == ["2026-10-13", "2026-10-12"]
