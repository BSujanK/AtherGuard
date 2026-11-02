"""ECMWF IFS open-data ingest: locations, `.index` parsing, ensemble statistics, IMD-day totals, live and archive fetch.

Hermetic: the network layer is a fake `Http` that serves synthetic `.index` files and byte ranges, and `ecmwf.decode_tp`
is replaced by a function that turns the fake bytes into constant fields on a coarse grid. The GRIB decoding itself is
`gfs.decode_apcp` (tested in test_ingest_gfs.py); one `live` test calls data.ecmwf.int.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pytest

from aetherguard.config import load_config
from aetherguard.http import DownloadError
from aetherguard.ingest import ecmwf, gfs
from aetherguard.manifest import Manifest

UTC = timezone.utc
CFG = load_config("live")
REAL_DECODE = ecmwf.decode_tp
LATS = np.arange(8.0, 36.01, 0.25)
LONS = np.arange(72.0, 98.01, 0.25)


def utc(y, m, d, h=0):
    return datetime(y, m, d, h, tzinfo=UTC)


# ------------------------------------------------------------------------------------------------- locations

def test_archive_layout_changes_on_the_configured_day():
    old, new = utc(2023, 7, 14, 18), utc(2024, 7, 14, 18)
    assert ecmwf.archive_prefix(old, CFG["ecmwf"]["archive"]) == "20230714/18z/0p4-beta"
    assert ecmwf.archive_prefix(new, CFG["ecmwf"]["archive"]) == "20240714/18z/ifs/0p25"
    assert ecmwf.archive_prefix(utc(2024, 2, 27, 12), CFG["ecmwf"]["archive"]) == "20240227/12z/0p4-beta"
    assert ecmwf.archive_prefix(utc(2024, 2, 28, 12), CFG["ecmwf"]["archive"]) == "20240228/12z/ifs/0p25"


def test_urls_name_cycle_step_and_stream():
    cycle = utc(2024, 7, 14, 18)
    assert ecmwf.archive_urls(cycle, 81, "scda", CFG)[1] == (
        "https://ecmwf-forecasts.s3.eu-central-1.amazonaws.com/20240714/18z/ifs/0p25/scda/20240714180000-81h-scda-fc.grib2")
    assert ecmwf.archive_urls(cycle, 81, "enfo", CFG, "index")[0].endswith("/enfo/20240714180000-81h-enfo-ef.index")
    assert ecmwf.live_urls(utc(2026, 10, 23, 12), 87, "oper", CFG) == [(
        "https://data.ecmwf.int/forecasts/20261023/12z/ifs/0p25/oper/20261023120000-87h-oper-fc.grib2")]


def test_deterministic_stream_depends_on_the_cycle_hour():
    assert [ecmwf.stream_name("hres", utc(2024, 7, 14, h)) for h in (0, 6, 12, 18)] == ["oper", "scda", "oper", "scda"]
    assert ecmwf.stream_name("ens", utc(2024, 7, 14, 18)) == "enfo"
    with pytest.raises(ValueError):
        ecmwf.stream_name("gefs", utc(2024, 7, 14))


# ---------------------------------------------------------------------------------------------- time rules

def test_archive_cycle_is_the_12z_run_of_the_day_before():
    assert ecmwf.archive_cycle(date(2024, 7, 15), CFG) == utc(2024, 7, 14, 12)


def test_live_candidates_are_newest_first_and_never_after_03_utc_or_now():
    day = date(2026, 10, 24)
    assert ecmwf.cycle_candidates(day, CFG, utc(2026, 10, 24, 5)) == [utc(2026, 10, 24, 0), utc(2026, 10, 23, 18),
                                                                       utc(2026, 10, 23, 12)]
    assert ecmwf.cycle_candidates(day, CFG, utc(2026, 10, 23, 22)) == [utc(2026, 10, 23, 18), utc(2026, 10, 23, 12)]
    with pytest.raises(ValueError):
        ecmwf.cycle_candidates(day, CFG, datetime(2026, 10, 24, 5))


def test_needed_steps_of_the_18z_and_12z_cycles_are_three_hourly():
    assert gfs.required_hours(utc(2026, 10, 23, 18), date(2026, 10, 24)) == [9, 33, 57, 81]
    assert gfs.required_hours(utc(2026, 10, 23, 12), date(2026, 10, 24)) == [15, 39, 63, 87]


# --------------------------------------------------------------------------------------- index and statistics

def index_text(stream: str, members: range = range(51), other: bool = True) -> str:
    rows = []
    if other:
        rows.append({"param": "2t", "type": "fc", "_offset": 0, "_length": 50})
    for m in members:
        if stream == "enfo":
            rec = {"param": "tp", "type": "cf" if m == 0 else "pf", "_offset": 1000 + 100 * m, "_length": 100}
            if m:
                rec["number"] = str(m)
        else:
            rec = {"param": "tp", "type": "fc", "_offset": 1000, "_length": 100}
        rows.append(rec)
        if other:
            rows.append({"param": "msl", "type": "pf", "number": "1", "_offset": 9999, "_length": 1})
    return "\n".join(json.dumps(r) for r in rows) + "\n"


def test_tp_ranges_of_hres_and_ensemble():
    hres = ecmwf.tp_ranges(ecmwf.parse_index(index_text("oper", range(1))), "oper")
    assert hres == {0: (1000, 1099)}
    ens = ecmwf.tp_ranges(ecmwf.parse_index(index_text("enfo")), "enfo")
    assert sorted(ens) == list(range(51)) and ens[0] == (1000, 1099) and ens[50] == (6000, 6099)
    assert ecmwf.tp_ranges(ecmwf.parse_index(index_text("scda", range(1))), "scda") == {0: (1000, 1099)}


def test_parse_index_skips_blank_lines():
    assert ecmwf.parse_index('{"a": 1}\n\n{"a": 2}\n') == [{"a": 1}, {"a": 2}]


def test_ensemble_stats_mean_and_percentiles():
    members = np.arange(1, 52, dtype=np.float32).reshape(51, 1, 1) * np.ones((51, 2, 2), dtype=np.float32)
    stats = ecmwf.ensemble_stats(members)
    assert stats["mean"].shape == (2, 2) and stats["mean"].dtype == np.float32
    assert np.allclose(stats["mean"], 26.0) and np.allclose(stats["p50"], 26.0)
    assert np.allclose(stats["p10"], np.percentile(np.arange(1, 52), 10)) and np.allclose(stats["p90"], 46.0)


def test_ensemble_stats_propagate_nan():
    members = np.ones((51, 2, 2), dtype=np.float32)
    members[7, 0, 0] = np.nan
    stats = ecmwf.ensemble_stats(members)
    assert all(np.isnan(v[0, 0]) and np.isfinite(v[1, 1]) for v in stats.values())


# ------------------------------------------------------------------------------------------------ GRIB decoding

def make_tp(start, end, lon_first=180.0, ni=1440, nj=4, lat_top=9.5):
    """A global-style 0.25 degree tp message (metres) whose value in each column is the longitude it sits at; the columns run
    from `lon_first` and wrap through 0 like the ECMWF open-data grids."""
    import eccodes
    gid = eccodes.codes_grib_new_from_samples("regular_ll_sfc_grib2")
    try:
        for key, value in (("paramId", 228228), ("Ni", ni), ("Nj", nj), ("packingType", "grid_simple"),
                           ("iDirectionIncrementInDegrees", 0.25), ("jDirectionIncrementInDegrees", 0.25),
                           ("longitudeOfFirstGridPointInDegrees", lon_first),
                           ("longitudeOfLastGridPointInDegrees", (lon_first + 0.25 * (ni - 1)) % 360),
                           ("stepType", "accum"), ("startStep", start), ("endStep", end), ("jScansPositively", 0),
                           ("latitudeOfFirstGridPointInDegrees", lat_top),
                           ("latitudeOfLastGridPointInDegrees", lat_top - 0.25 * (nj - 1))):
            eccodes.codes_set(gid, key, value)
        lons = (lon_first + 0.25 * np.arange(ni)) % 360
        eccodes.codes_set_values(gid, np.tile(lons / 1000.0, nj))
        return eccodes.codes_get_message(gid)
    finally:
        eccodes.codes_release(gid)


def test_decode_tp_sorts_the_wrapped_longitudes_and_converts_to_mm():
    pytest.importorskip("eccodes")
    lats, lons, field = REAL_DECODE(make_tp(0, 33), 33, CFG["domain_bbox"])
    assert lons[0] == 72.0 and lons[-1] == 98.0 and np.all(np.diff(lons) > 0)
    assert lats.tolist() == [8.75, 9.0, 9.25, 9.5]
    assert np.allclose(field, np.tile(lons, (4, 1)), atol=1e-2)            # metres / 1000 -> the longitude in mm


def test_decode_tp_rejects_a_bucket_and_the_wrong_step():
    pytest.importorskip("eccodes")
    with pytest.raises(gfs.GribDecodeError, match="covers hours 6-33"):
        REAL_DECODE(make_tp(6, 33), 33, CFG["domain_bbox"])
    with pytest.raises(gfs.GribDecodeError, match="expected 0-39"):
        REAL_DECODE(make_tp(0, 33), 39, CFG["domain_bbox"])
    with pytest.raises(gfs.GribDecodeError):
        REAL_DECODE(b"not grib", 33, CFG["domain_bbox"])


# ------------------------------------------------------------------------------------------------ fake source

class FakeHttp:
    """Serves `.index` files and byte ranges of one synthetic ECMWF tree; records the requests it received."""

    def __init__(self, published=None, broken=None, members=range(51), absent=()):
        self.absent = absent                  # URL fragments of copies that do not exist (HTTP 404)
        self.published = published            # callable(url) -> bool for HEAD; None: everything exists
        self.broken = broken or set()         # (step, member) whose byte range fails
        self.members = members
        self.heads, self.texts, self.ranges = [], [], []

    def head(self, url):
        self.heads.append(url)
        return {"Last-Modified": "Mon, 15 Jul 2024 07:55:09 GMT"} if self.published is None or self.published(url) else None

    def text(self, url):
        self.texts.append(url)
        if any(fragment in url for fragment in self.absent):
            raise gfs.NotPublishedError(f"HTTP 404 from {url}", status=404)
        stream = "enfo" if "-enfo-" in url else "oper"
        return index_text(stream, self.members if stream == "enfo" else range(1))

    def byte_range(self, url, first, last):
        step = int(url.rsplit("/", 1)[1].split("-")[1].rstrip("h"))
        member = 0 if "-enfo-" not in url else (first - 1000) // 100
        self.ranges.append((url, member, step))
        if (step, member) in self.broken:
            raise DownloadError("HTTP 500", retriable=False, status=500)
        return json.dumps({"step": step, "member": member}).encode()


@pytest.fixture(autouse=True)
def fake_decoder(monkeypatch):
    """Cumulative rain of member m at step h: (1 + m) * h / 10 mm everywhere, so an IMD day of length 24 h is 2.4 (1 + m)."""
    def decode(data, step, bbox):
        info = json.loads(data)
        assert info["step"] == step
        return LATS, LONS, np.full((LATS.size, LONS.size), (1 + info["member"]) * step / 10.0, dtype=np.float32)
    monkeypatch.setattr(ecmwf, "decode_tp", decode)


# ------------------------------------------------------------------------------------------------ one stream

ISSUE = date(2024, 7, 15)
CYCLE = utc(2024, 7, 14, 18)


def test_hres_days_are_cumulative_differences_on_the_imerg_grid():
    result = ecmwf.fetch_stream(FakeHttp(), "hres", CYCLE, ISSUE, CFG, ecmwf.archive_urls)
    assert result.day_valid.tolist() == [True, True, True] and result.missing_steps == []
    field = result.fields["hres"]
    assert field.shape == (3, 280, 260) and field.dtype == np.float32
    assert np.allclose(field, 2.4, atol=1e-5)            # (1 + 0) * 24 h / 10
    assert [u.rsplit("/", 1)[1] for u in result.urls][0] == "20240714180000-9h-scda-fc.grib2"


def test_ensemble_keeps_mean_and_percentiles_not_members():
    result = ecmwf.fetch_stream(FakeHttp(), "ens", CYCLE, ISSUE, CFG, ecmwf.archive_urls)
    assert result.n_members == 51 and set(result.fields) == {"mean", "p10", "p50", "p90"}
    assert np.allclose(result.fields["mean"], 2.4 * 26, atol=1e-4)                       # mean of 1..51
    assert np.allclose(result.fields["p90"], 2.4 * 46, atol=1e-4) and np.allclose(result.fields["p10"], 2.4 * 6, atol=1e-4)


def test_a_failed_step_makes_its_lead_days_nan_never_zero():
    result = ecmwf.fetch_stream(FakeHttp(broken={(33, 0)}), "hres", CYCLE, ISSUE, CFG, ecmwf.archive_urls)
    assert result.day_valid.tolist() == [False, False, True]            # D+1 = (9, 33], D+2 = (33, 57], D+3 = (57, 81]
    assert result.missing_steps == [33] and "33" in result.failures
    assert np.isnan(result.fields["hres"][:2]).all() and np.allclose(result.fields["hres"][2], 2.4, atol=1e-5)


def test_an_ensemble_index_without_the_control_member_is_enough():
    result = ecmwf.fetch_stream(FakeHttp(members=range(1, 51)), "ens", CYCLE, ISSUE, CFG, ecmwf.archive_urls)
    assert result.day_valid.all() and result.n_members == 50
    assert np.allclose(result.fields["mean"], 2.4 * 26.5, atol=1e-4)           # members 1..50 -> 1 + m = 2..51


def test_an_ensemble_member_that_fails_is_left_out():
    result = ecmwf.fetch_stream(FakeHttp(broken={(57, 3)}), "ens", CYCLE, ISSUE, CFG, ecmwf.archive_urls)
    assert result.n_members == 50 and result.day_valid.all()
    assert "member3@57" in result.failures
    kept = np.array([m for m in range(51) if m != 3], dtype=np.float64)
    assert np.allclose(result.fields["mean"][0], 2.4 * 26, atol=1e-4)                  # D+1 does not use step 57
    assert np.allclose(result.fields["mean"][1:], 2.4 * (1 + kept.mean()), atol=1e-4)


def test_too_few_complete_members_invalidate_the_ensemble():
    broken = {(step, m) for m in range(20) for step in (9, 33, 57, 81)}
    result = ecmwf.fetch_stream(FakeHttp(broken=broken), "ens", CYCLE, ISSUE, CFG, ecmwf.archive_urls)
    assert not result.day_valid.any() and np.isnan(result.fields["mean"]).all()
    assert "members" in result.failures


def test_the_second_copy_is_used_when_the_first_has_no_index():
    http = FakeHttp(absent=("storage.googleapis.com",))
    result = ecmwf.fetch_stream(http, "hres", CYCLE, ISSUE, CFG, ecmwf.archive_urls)
    assert result.day_valid.all()
    assert all("amazonaws.com" in u for u in result.urls) and any("googleapis" in u for u in http.texts)
    assert all("googleapis" in u for u in ecmwf.fetch_stream(FakeHttp(), "hres", CYCLE, ISSUE, CFG, ecmwf.archive_urls).urls)


def test_no_copy_with_an_index_is_a_missing_step():
    http = FakeHttp(absent=("googleapis", "amazonaws"))
    result = ecmwf.fetch_stream(http, "hres", CYCLE, ISSUE, CFG, ecmwf.archive_urls)
    assert not result.day_valid.any() and result.missing_steps == [9, 33, 57, 81]


def test_an_index_without_tp_is_a_missing_step():
    http = FakeHttp(members=range(0))
    result = ecmwf.fetch_stream(http, "ens", CYCLE, ISSUE, CFG, ecmwf.archive_urls)
    assert not result.day_valid.any() and result.missing_steps == [9, 33, 57, 81]


# --------------------------------------------------------------------------------------------- live and archive

def make_manifest(tmp_path):
    return Manifest(tmp_path / "manifest.jsonl", tmp_path)


def test_live_uses_the_newest_published_cycle_of_each_product(tmp_path):
    day = date(2026, 10, 24)
    now = utc(2026, 10, 24, 5)
    # the 00Z run of the day is not out, the 18Z run of the day before is out for the ensemble only
    def published(url):
        if "/20261024/00z/" in url:
            return False
        return not ("/20261023/18z/" in url and "scda" in url)
    http = FakeHttp(published=published)
    path = ecmwf.fetch_live(day, CFG, now_utc=now, root=tmp_path, manifest=make_manifest(tmp_path), http=http)
    forecast = ecmwf.load_day(path)
    assert forecast.ens_cycle == utc(2026, 10, 23, 18)
    assert forecast.hres_cycle == utc(2026, 10, 23, 12)
    assert forecast.hres_valid.all() and forecast.ens_valid.all() and forecast.n_members == 51
    assert forecast.hres.shape == (3, 280, 260) and forecast.hres.dtype == np.float32 and forecast.ens_p90 is not None
    assert np.allclose(forecast.ens_mean, 2.4 * 26, rtol=1e-3)            # stored as float16


def test_live_raises_when_no_cycle_is_published(tmp_path):
    http = FakeHttp(published=lambda url: False)
    with pytest.raises(ecmwf.EcmwfFetchError, match="no ECMWF stream"):
        ecmwf.fetch_live(date(2026, 10, 24), CFG, now_utc=utc(2026, 10, 24, 5), root=tmp_path,
                         manifest=make_manifest(tmp_path), http=http)
    assert not ecmwf.day_file_path(tmp_path, date(2026, 10, 24)).exists()


def test_live_keeps_the_stream_that_worked(tmp_path):
    http = FakeHttp(published=lambda url: "-enfo-" not in url)
    path = ecmwf.fetch_live(date(2026, 10, 24), CFG, now_utc=utc(2026, 10, 24, 5), root=tmp_path,
                            manifest=make_manifest(tmp_path), http=http)
    forecast = ecmwf.load_day(path)
    assert forecast.hres is not None and forecast.hres_valid.all()
    assert forecast.ens_mean is None and not forecast.ens_valid.any() and forecast.ens_cycle is None


def test_day_file_is_recorded_in_the_manifest_with_url_and_licence(tmp_path):
    manifest = make_manifest(tmp_path)
    path = ecmwf.fetch_live(date(2026, 10, 24), CFG, now_utc=utc(2026, 10, 24, 5), root=tmp_path, manifest=manifest,
                            http=FakeHttp())
    entry = manifest.entries()[manifest.relpath(path)]
    assert "data.ecmwf.int/forecasts/20261024/00z/ifs/0p25/" in entry.url
    assert entry.licence == ecmwf.LICENCE and "CC BY 4.0" in entry.licence


def test_archive_writes_one_file_per_day_and_is_idempotent(tmp_path):
    manifest = make_manifest(tmp_path)
    days = [date(2024, 7, 15), date(2024, 7, 16)]
    first = ecmwf.fetch_archive(days, CFG, workers=2, root=tmp_path, manifest=manifest, http=FakeHttp())
    assert first["written"] == ["2024-07-15", "2024-07-16"] and first["failed"] == {} and first["incomplete"] == {}
    http = FakeHttp()
    again = ecmwf.fetch_archive(days, CFG, workers=2, root=tmp_path, manifest=manifest, http=http)
    assert again["skipped"] == ["2024-07-15", "2024-07-16"] and again["written"] == [] and http.texts == []
    forecast = ecmwf.load_day(ecmwf.day_file_path(tmp_path, days[0]))
    assert forecast.hres_cycle == utc(2024, 7, 14, 12) == forecast.ens_cycle
    with np.load(ecmwf.day_file_path(tmp_path, days[0])) as data:
        assert any("/ifs/0p25/enfo/" in u for u in data["urls"])


def test_archive_reports_a_day_with_nothing_and_stops_after_repeated_failures(tmp_path):
    http = FakeHttp(published=lambda url: True, members=range(0))
    http.text = lambda url: (_ for _ in ()).throw(DownloadError("HTTP 500", retriable=False, status=500))
    days = [date(2024, 7, 1) + timedelta(days=n) for n in range(6)]
    summary = ecmwf.fetch_archive(days, CFG, workers=1, root=tmp_path, manifest=make_manifest(tmp_path), http=http,
                                  abort_after=3)
    assert summary["written"] == [] and len(summary["failed"]) == 6
    assert sum("stopped after repeated failures" in r for r in summary["failed"].values()) == 3


def test_archive_flags_a_day_with_a_missing_lead(tmp_path):
    summary = ecmwf.fetch_archive([ISSUE], CFG, root=tmp_path, manifest=make_manifest(tmp_path),
                                  http=FakeHttp(broken={(87, 0)}))
    assert summary["written"] == ["2024-07-15"]
    assert summary["incomplete"]["2024-07-15"] == {"hres": [True, True, False], "ens": [True, True, True]}


def test_archive_days_from_windows():
    windows = [{"start": "2023-09-29", "end": "2023-10-01"}, {"start": "2024-06-01", "end": "2024-06-01"}]
    assert ecmwf.archive_days(windows) == [date(2023, 9, 29), date(2023, 9, 30), date(2023, 10, 1), date(2024, 6, 1)]


def test_config_windows_cover_june_to_september_of_2023_and_2024():
    days = ecmwf.archive_days(CFG["ecmwf"]["archive"]["windows"])
    assert len(days) == 244 and {d.month for d in days} == {6, 7, 8, 9} and {d.year for d in days} == {2023, 2024}


# ------------------------------------------------------------------------------------------ publication time

def test_publication_latency_is_last_modified_minus_cycle_time():
    http = FakeHttp()
    hours = ecmwf.publication_latency_h(http, utc(2024, 7, 15, 0), "hres", date(2024, 7, 15), CFG)
    assert hours == pytest.approx(7 + 55 / 60 + 9 / 3600)
    assert http.heads[0].endswith("20240715000000-75h-oper-fc.grib2") and "amazonaws.com" in http.heads[0]


def test_publication_latency_none_when_the_file_is_missing():
    assert ecmwf.publication_latency_h(FakeHttp(published=lambda u: False), utc(2024, 7, 15), "ens", ISSUE, CFG) is None


# ---------------------------------------------------------------------------------------------- the pacing

def test_http_spaces_requests(monkeypatch):
    slept = []
    clock = {"t": 100.0}
    monkeypatch.setattr(ecmwf.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(ecmwf.time, "sleep", lambda s: slept.append(round(s, 3)))
    http = ecmwf.Http(requests_per_s=4.0)
    for _ in range(3):
        http._wait_for_slot()
    assert slept == [0.25, 0.5]


@pytest.mark.live
def test_live_index_of_the_newest_cycle_has_tp_for_every_member():
    http = ecmwf.Http()
    day = datetime.now(UTC).date()
    for cycle in ecmwf.cycle_candidates(day, CFG, datetime.now(UTC) + timedelta(days=1)):
        url = ecmwf.live_urls(cycle, gfs.required_hours(cycle, day)[0], "enfo", CFG, "index")[0]
        try:
            ranges = ecmwf.tp_ranges(ecmwf.parse_index(http.text(url)), "enfo")
        except DownloadError:
            continue
        assert len(ranges) == 51
        return
    pytest.skip("no ECMWF cycle published yet")


# ------------------------------------------------------------------------------------------ the measurement report

def test_publication_report_picks_the_newest_cycle_that_is_out_before_the_run(monkeypatch):
    from aetherguard.ingest import ecmwf_build
    monkeypatch.setattr(ecmwf, "publication_latency_h", lambda http, cycle, kind, day, cfg: 7.9 if kind == "hres" else 8.5)
    result = ecmwf_build.measure_publication(CFG, [date(2024, 7, 15), date(2024, 7, 16)], object())
    rows = {(r["cycle"], r["product"]): r for r in result["rows"]}
    assert len(rows) == 6 and rows["00Z of D", "hres"]["found"] == 2 and rows["00Z of D", "hres"]["max_h"] == 7.9
    assert rows["00Z of D", "hres"]["newest_file_at"] == "D 07:54 UTC" and not rows["00Z of D", "hres"]["before_run"]
    assert rows["18Z of D-1", "ens"]["newest_file_at"] == "D 02:30 UTC" and rows["18Z of D-1", "ens"]["before_run"]
    assert rows["12Z of D-1", "hres"]["newest_file_at"] == "D-1 19:54 UTC" and rows["12Z of D-1", "hres"]["before_run"]
    assert "uses the newest cycle that is out for both products: 18Z of D-1" in result["decision"]
    assert "00Z of D (D 08:30 UTC) is not out before the run" in result["decision"]
    text = ecmwf_build.render_publication(result)
    assert "| 00Z of D | hres | oper | 2/2 |" in text and result["decision"] in text


def test_publication_report_without_any_cycle_out():
    from aetherguard.ingest import ecmwf_build
    result = ecmwf_build.measure_publication(CFG, [date(2024, 7, 15)], FakeHttp(published=lambda url: False))
    assert all(r["found"] == 0 and r["max_h"] is None for r in result["rows"])
    assert result["decision"].startswith("No cycle is out")
