"""GFS forecast ingest: IMD-day windows, bucket -> cumulative, cycle choice, regrid, live and archive fetch.

Everything except the decoder test is hermetic: the network layer (`gfs._get`) and the GRIB decoder
(`gfs.decode_apcp`) are replaced by fakes that produce synthetic fields. The decoder itself is tested on GRIB2
messages written with eccodes in tmp_path; one `realdata` test decodes a real downloaded file and one `live` test
calls NOMADS.
"""
from __future__ import annotations

import copy
import json
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pytest
import yaml

from aetherguard.config import PROJECT_ROOT, data_root, load_config
from aetherguard.http import DownloadError
from aetherguard.ingest import gfs
from aetherguard.manifest import Manifest

UTC = timezone.utc
HOUR = timedelta(hours=1)


def utc(y, m, d, h=0, minute=0):
    return datetime(y, m, d, h, minute, tzinfo=UTC)


# ------------------------------------------------------------------------------------------------- config

def test_live_config_matches_ingest_bbox_and_module_grid():
    live, ingest = load_config("live"), load_config("ingest")
    assert live["domain_bbox"] == ingest["domain_bbox"]
    grid = live["domain_grid"]
    assert gfs.TARGET_LATS.size == grid["rows"] and gfs.TARGET_LONS.size == grid["cols"]
    assert gfs.TARGET_LATS[0] == pytest.approx(grid["lat_first"]) and gfs.TARGET_LONS[0] == pytest.approx(grid["lon_first"])
    assert np.allclose(np.diff(gfs.TARGET_LATS), grid["step"]) and np.allclose(np.diff(gfs.TARGET_LONS), grid["step"])
    box = live["domain_bbox"]
    assert gfs.TARGET_LATS[-1] + grid["step"] / 2 == pytest.approx(box["lat_max"])
    assert gfs.TARGET_LONS[-1] + grid["step"] / 2 == pytest.approx(box["lon_max"])


# --------------------------------------------------------------------------------------- IMD-day windows

def test_windows_for_00z_cycle_on_issue_day():
    # IMD day D+1 = (03:00 UTC D, 03:00 UTC D+1] -> lead hours 3..27 for the 00Z cycle of D
    assert gfs.imd_day_windows(utc(2023, 7, 15), date(2023, 7, 15)) == [(3, 27), (27, 51), (51, 75)]


def test_windows_for_earlier_and_later_cycles():
    assert gfs.imd_day_windows(utc(2023, 7, 14, 18), date(2023, 7, 15)) == [(9, 33), (33, 57), (57, 81)]
    # a 06Z cycle starts after the first window opens (03:00 UTC): that window cannot be forecast
    assert gfs.imd_day_windows(utc(2023, 7, 15, 6), date(2023, 7, 15)) == [(-3, 21), (21, 45), (45, 69)]


def test_required_hours_are_positive_boundaries():
    assert gfs.required_hours(utc(2023, 7, 15), date(2023, 7, 15)) == [3, 27, 51, 75]
    assert gfs.required_hours(utc(2023, 7, 15, 6), date(2023, 7, 15)) == [21, 45, 69]


def hourly_cumulative(cycle, rain_by_lead, shape=(2, 3), last=96):
    """cumulative[h] = sum of the hourly rain whose hour ENDS at lead 1..h (stamp convention (T-1h, T])."""
    out, total = {}, np.zeros(shape, dtype=np.float32)
    for h in range(1, last + 1):
        total = total + np.float32(rain_by_lead.get(h, 0.0))
        out[h] = total.copy()
    return out


def brute_force_days(cycle, rain_by_lead, issue_day):
    """Independent IMD-day totals: assign every hourly stamp T to the day X with 03:00 UTC X-1 < T <= 03:00 UTC X."""
    totals = {k: 0.0 for k in (1, 2, 3)}
    for h, mm in rain_by_lead.items():
        stamp = cycle + h * HOUR
        label = (stamp - timedelta(hours=3, minutes=1)).date() + timedelta(days=1)
        k = (label - issue_day).days
        if k in totals:
            totals[k] += mm
    return [totals[1], totals[2], totals[3]]


def test_imd_days_boundaries_exactly_at_0300_utc():
    cycle, issue = utc(2023, 7, 15), date(2023, 7, 15)
    # hour ending 03:00 D (lead 3) belongs to IMD day D, not D+1; hour ending 04:00 D (lead 4) opens D+1;
    # lead 27 (03:00 D+1) closes D+1; lead 28 opens D+2; 51 closes D+2; 52 opens D+3; 75 closes D+3; 76 is D+4
    rain = {3: 100.0, 4: 1.0, 27: 2.0, 28: 4.0, 51: 8.0, 52: 16.0, 75: 32.0, 76: 64.0}
    days = gfs.apcp_imd_days(hourly_cumulative(cycle, rain), cycle, issue)
    assert days.shape == (3, 2, 3)
    assert days[:, 0, 0].tolist() == [3.0, 12.0, 48.0]
    assert days[:, 0, 0].tolist() == brute_force_days(cycle, rain, issue)


@pytest.mark.parametrize("cycle", [utc(2023, 7, 14, 18), utc(2023, 7, 14, 12), utc(2023, 7, 15)])
def test_imd_days_match_brute_force_for_random_hourly_rain(cycle):
    issue = date(2023, 7, 15)
    rng = np.random.default_rng(7)
    rain = {h: float(rng.gamma(0.5, 2.0)) for h in range(1, 97)}
    days = gfs.apcp_imd_days(hourly_cumulative(cycle, rain), cycle, issue)
    assert days[:, 0, 0] == pytest.approx(brute_force_days(cycle, rain, issue), rel=1e-4)


def test_day_whose_window_starts_before_the_cycle_is_nan():
    cycle, issue = utc(2023, 7, 15, 6), date(2023, 7, 15)
    cumulative = hourly_cumulative(cycle, {h: 1.0 for h in range(1, 97)})
    days = gfs.apcp_imd_days(cumulative, cycle, issue)
    assert np.isnan(days[0]).all() and np.isfinite(days[1:]).all()
    assert gfs.imd_day_valid(cumulative, cycle, issue).tolist() == [False, True, True]
    assert gfs.missing_hours(cumulative, cycle, issue) == []


def test_missing_forecast_hour_gives_nan_for_the_affected_days_only():
    cycle, issue = utc(2023, 7, 15), date(2023, 7, 15)
    cumulative = hourly_cumulative(cycle, {h: 1.0 for h in range(1, 97)})
    del cumulative[51]  # boundary shared by D+2 (end) and D+3 (start)
    days = gfs.apcp_imd_days(cumulative, cycle, issue)
    assert np.isfinite(days[0]).all() and np.isnan(days[1]).all() and np.isnan(days[2]).all()
    assert gfs.missing_hours(cumulative, cycle, issue) == [51]
    assert gfs.imd_day_valid(cumulative, cycle, issue).tolist() == [True, False, False]
    assert (days[0] == 24.0).all()  # the untouched day is exact, never zero-filled


def test_apcp_imd_days_without_any_field_is_an_error():
    with pytest.raises(ValueError, match="no cumulative"):
        gfs.apcp_imd_days({}, utc(2023, 7, 15), date(2023, 7, 15))


# ------------------------------------------------------------------------------- bucket -> cumulative

def gfs_messages(hourly, hours, drop=()):
    """What the pgrb2 files carry: step 'start-end' with the bucket reset every 6 h, plus the 0-H message."""
    buckets, cumulative = {}, {}
    for h in hours:
        if h in drop:
            continue
        start = 0 if h <= 6 else ((h - 1) // 6) * 6
        bucket = np.full((2, 2), sum(hourly[start + 1:h + 1]), dtype=np.float32)
        buckets[h] = (start, h, bucket)
        cumulative[h] = (0, h, np.full((2, 2), sum(hourly[1:h + 1]), dtype=np.float32))
    return buckets, cumulative


def test_bucket_steps_chain_into_the_cumulative_series():
    rng = np.random.default_rng(1)
    hourly = [0.0] + [float(x) for x in rng.gamma(0.5, 2.0, 96)]
    hours = list(range(3, 97, 3))
    buckets, cumulative = gfs_messages(hourly, hours)
    assert [buckets[h][:2] for h in (3, 6, 9, 12, 15, 18, 24)] == \
        [(0, 3), (0, 6), (6, 9), (6, 12), (12, 15), (12, 18), (18, 24)]
    from_buckets = gfs.cumulative_from_messages(buckets)
    from_cumulative = gfs.cumulative_from_messages(cumulative)
    assert sorted(from_buckets) == hours
    for h in hours:
        assert from_buckets[h][0, 0] == pytest.approx(sum(hourly[1:h + 1]), rel=1e-5)
        assert from_buckets[h][0, 0] == pytest.approx(from_cumulative[h][0, 0], rel=1e-5)


def test_bucket_chain_breaks_where_its_base_hour_is_missing():
    hourly = [0.0] + [1.0] * 96
    buckets, _ = gfs_messages(hourly, list(range(3, 49, 3)), drop=(12,))
    result = gfs.cumulative_from_messages(buckets)
    # f012 is gone, so f015 (12-15) and f018 (12-18) have no base; f021 (18-21) chains from f018 and is gone too
    assert 12 not in result and 15 not in result and 18 not in result and 21 not in result
    # f024 (18-24) needs f018; f030 (24-30) needs f024; ... everything after is lost until the next 0-H message
    assert 24 not in result and 30 not in result
    assert result[9][0, 0] == 9.0 and result[3][0, 0] == 3.0 and result[6][0, 0] == 6.0


def test_cumulative_message_does_not_need_the_previous_hours():
    hourly = [0.0] + [1.0] * 96
    _, cumulative = gfs_messages(hourly, [3, 27, 51, 75])
    assert gfs.cumulative_from_messages(cumulative)[27][0, 0] == 27.0


def test_message_ending_at_another_hour_is_rejected():
    with pytest.raises(ValueError, match="ends at hour 9"):
        gfs.cumulative_from_messages({12: (6, 9, np.zeros((2, 2), dtype=np.float32))})


# --------------------------------------------------------------------------------------- cycle choice

def published_set(*cycles):
    return lambda cycle: cycle in set(cycles)


def test_cycle_is_the_latest_published_one():
    now = utc(2026, 10, 14, 10, 30)
    assert gfs.latest_complete_cycle(now, published_set(utc(2026, 10, 14, 6))) == utc(2026, 10, 14, 6)


def test_unpublished_cycle_steps_back_six_hours():
    now = utc(2026, 10, 14, 10, 30)
    assert gfs.latest_complete_cycle(now, published_set(utc(2026, 10, 14, 0))) == utc(2026, 10, 14, 0)


@pytest.mark.parametrize("now, candidates", [
    (utc(2026, 10, 14, 6, 0), [utc(2026, 10, 14, 6), utc(2026, 10, 14, 0)]),       # exactly on the cycle hour
    (utc(2026, 10, 14, 5, 59), [utc(2026, 10, 14, 0), utc(2026, 10, 13, 18)]),     # a minute before it
    (utc(2026, 10, 14, 0, 0), [utc(2026, 10, 14, 0), utc(2026, 10, 13, 18)]),      # midnight
    (utc(2026, 10, 14, 0, 1), [utc(2026, 10, 14, 0), utc(2026, 10, 13, 18)]),
])
def test_cycle_candidates_are_tried_newest_first_from_the_floor(now, candidates):
    asked = []

    def published(cycle):
        asked.append(cycle)
        return cycle == candidates[-1]

    assert gfs.latest_complete_cycle(now, published) == candidates[-1]
    assert asked == candidates


def test_gives_up_after_four_cycles():
    asked = []

    def never(cycle):
        asked.append(cycle)
        return False

    with pytest.raises(gfs.NoCompleteCycleError, match="4 cycles"):
        gfs.latest_complete_cycle(utc(2026, 10, 14, 10, 30), never)
    assert asked == [utc(2026, 10, 14, 6), utc(2026, 10, 14, 0), utc(2026, 10, 13, 18), utc(2026, 10, 13, 12)]


def test_fourth_cycle_back_is_still_accepted():
    assert gfs.latest_complete_cycle(utc(2026, 10, 14, 10, 30), published_set(utc(2026, 10, 13, 12))) \
        == utc(2026, 10, 13, 12)


def test_naive_time_is_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        gfs.latest_complete_cycle(datetime(2026, 10, 14, 10), lambda cycle: True)


def test_non_utc_time_is_converted():
    ist = timezone(timedelta(hours=5, minutes=30))
    now = datetime(2026, 10, 14, 16, 0, tzinfo=ist)  # 10:30 UTC
    assert gfs.latest_complete_cycle(now, lambda cycle: True) == utc(2026, 10, 14, 6)


# --------------------------------------------------------------------------------------------- regrid

def source_axes():
    return np.arange(8.0, 36.0 + 1e-9, 0.25), np.arange(72.0, 98.0 + 1e-9, 0.25)


def test_regrid_preserves_a_uniform_field():
    lats, lons = source_axes()
    out = gfs.regrid_to_imerg(np.full((lats.size, lons.size), 7.5, dtype=np.float32), lats, lons)
    assert out.shape == (280, 260) and out.dtype == np.float32
    assert np.allclose(out, 7.5, rtol=0, atol=1e-5)


def test_regrid_keeps_the_domain_mean_within_one_percent():
    lats, lons = source_axes()
    lat2, lon2 = np.meshgrid(lats, lons, indexing="ij")
    field = (4.0 + 3.0 * np.sin(lat2 / 3.0) * np.cos(lon2 / 4.0) + 6.0 * np.exp(-((lat2 - 20) ** 2 + (lon2 - 80) ** 2) / 8.0))
    out = gfs.regrid_to_imerg(field.astype(np.float32), lats, lons)
    assert abs(out.mean() / field.mean() - 1.0) < 0.01


def test_regrid_orientation_south_to_north_west_to_east():
    lats, lons = source_axes()
    lat2, lon2 = np.meshgrid(lats, lons, indexing="ij")
    by_lat = gfs.regrid_to_imerg(lat2.astype(np.float32), lats, lons)
    by_lon = gfs.regrid_to_imerg(lon2.astype(np.float32), lats, lons)
    assert np.allclose(by_lat[:, 0], gfs.TARGET_LATS, atol=1e-4) and np.allclose(by_lat[0], by_lat[0, 0])
    assert np.allclose(by_lon[0, :], gfs.TARGET_LONS, atol=1e-4) and np.allclose(by_lon[:, 0], by_lon[0, 0])
    assert gfs.TARGET_LATS[0] == pytest.approx(8.05) and gfs.TARGET_LATS[-1] == pytest.approx(35.95)
    assert gfs.TARGET_LONS[0] == pytest.approx(72.05) and gfs.TARGET_LONS[-1] == pytest.approx(97.95)


def test_regrid_is_bilinear_between_nodes():
    lats, lons = source_axes()
    field = np.zeros((lats.size, lons.size), dtype=np.float32)
    field[0, 0] = 10.0  # node (8.00, 72.00); target (8.05, 72.05) is 20% of the way to both neighbours
    out = gfs.regrid_to_imerg(field, lats, lons)
    assert out[0, 0] == pytest.approx(10.0 * 0.8 * 0.8, rel=1e-5)


def test_regrid_nan_only_spreads_to_pixels_that_use_it():
    lats, lons = source_axes()
    field = np.ones((lats.size, lons.size), dtype=np.float32)
    field[40, 40] = np.nan  # node (18.0, 82.0)
    out = gfs.regrid_to_imerg(field, lats, lons)
    nan_rows, nan_cols = np.nonzero(np.isnan(out))
    assert nan_rows.size > 0
    assert gfs.TARGET_LATS[nan_rows].min() > 17.75 and gfs.TARGET_LATS[nan_rows].max() < 18.25
    assert gfs.TARGET_LONS[nan_cols].min() > 81.75 and gfs.TARGET_LONS[nan_cols].max() < 82.25
    assert np.isfinite(out[:90]).all() and np.isfinite(out[110:]).all()


def test_regrid_rejects_a_grid_that_does_not_cover_the_domain():
    lats, lons = np.arange(10.0, 30.0, 0.25), np.arange(75.0, 90.0, 0.25)
    out = gfs.regrid_to_imerg(np.ones((lats.size, lons.size), dtype=np.float32), lats, lons)
    assert np.isnan(out[0]).all() and np.isnan(out[:, 0]).all()  # outside the source: explicit NaN
    assert np.isfinite(out[(20 - 8) * 10, (80 - 72) * 10])


def test_regrid_requires_ascending_axes_and_matching_shape():
    lats, lons = source_axes()
    field = np.ones((lats.size, lons.size), dtype=np.float32)
    with pytest.raises(ValueError, match="ascending"):
        gfs.regrid_to_imerg(field[::-1], lats[::-1], lons)
    with pytest.raises(ValueError, match="shape"):
        gfs.regrid_to_imerg(field[:-1], lats, lons)


def test_crop_to_bbox_keeps_the_domain_inclusive():
    lats, lons = np.arange(-90.0, 90.01, 0.25), np.arange(0.0, 359.9, 0.25)
    values = np.zeros((lats.size, lons.size), dtype=np.float32)
    sub_lats, sub_lons, sub = gfs.crop_to_bbox(lats, lons, values, load_config("live")["domain_bbox"])
    assert (sub_lats[0], sub_lats[-1], sub_lons[0], sub_lons[-1]) == (8.0, 36.0, 72.0, 98.0)
    assert sub.shape == (113, 105)


# --------------------------------------------------------------------------------------- GRIB decoder

def make_grib(start, end, values, lats_descending=True, lon0=72.0, lat_top=9.5, ni=5, nj=4, short="tp"):
    """One synthetic GRIB2 APCP message (0.25 degree, simple packing) written with eccodes."""
    import eccodes
    gid = eccodes.codes_grib_new_from_samples("regular_ll_sfc_grib2")
    try:
        for key, value in (("paramId", 228228), ("Ni", ni), ("Nj", nj), ("packingType", "grid_simple"),
                           ("iDirectionIncrementInDegrees", 0.25), ("jDirectionIncrementInDegrees", 0.25),
                           ("longitudeOfFirstGridPointInDegrees", lon0),
                           ("longitudeOfLastGridPointInDegrees", lon0 + 0.25 * (ni - 1)),
                           ("stepType", "accum"), ("startStep", start), ("endStep", end)):
            eccodes.codes_set(gid, key, value)
        lat_bottom = lat_top - 0.25 * (nj - 1)
        if lats_descending:
            eccodes.codes_set(gid, "jScansPositively", 0)
            eccodes.codes_set(gid, "latitudeOfFirstGridPointInDegrees", lat_top)
            eccodes.codes_set(gid, "latitudeOfLastGridPointInDegrees", lat_bottom)
        else:
            eccodes.codes_set(gid, "jScansPositively", 1)
            eccodes.codes_set(gid, "latitudeOfFirstGridPointInDegrees", lat_bottom)
            eccodes.codes_set(gid, "latitudeOfLastGridPointInDegrees", lat_top)
        eccodes.codes_set_values(gid, np.asarray(values, dtype=np.float64).ravel())
        assert eccodes.codes_get(gid, "shortName") == short
        return eccodes.codes_get_message(gid)
    finally:
        eccodes.codes_release(gid)


def test_decode_picks_the_cumulative_message_and_orients_the_grid():
    pytest.importorskip("eccodes")
    bucket = np.full((4, 5), 1.0)
    cumulative = np.arange(20, dtype=float).reshape(4, 5)  # row 0 = northernmost (9.5) as stored
    data = make_grib(6, 12, bucket) + make_grib(0, 12, cumulative)
    lats, lons, values, start, end = gfs.decode_apcp(data)
    assert (start, end) == (0, 12)
    assert lats.tolist() == [8.75, 9.0, 9.25, 9.5] and lons.tolist() == [72.0, 72.25, 72.5, 72.75, 73.0]
    assert values.shape == (4, 5) and values.dtype == np.float32
    assert np.allclose(values[3], cumulative[0], atol=1e-3)  # northernmost stored row is now the last row
    assert np.allclose(values[0], cumulative[3], atol=1e-3)


def test_decode_handles_south_to_north_storage_like_nomads():
    pytest.importorskip("eccodes")
    stored = np.arange(20, dtype=float).reshape(4, 5)  # row 0 = southernmost (8.75)
    lats, _, values, start, end = gfs.decode_apcp(make_grib(0, 3, stored, lats_descending=False))
    assert lats.tolist() == [8.75, 9.0, 9.25, 9.5] and (start, end) == (0, 3)
    assert np.allclose(values, stored, atol=1e-3)


def test_decode_returns_a_bucket_when_no_cumulative_message_exists():
    pytest.importorskip("eccodes")
    _, _, _, start, end = gfs.decode_apcp(make_grib(6, 9, np.ones((4, 5))))
    assert (start, end) == (6, 9)


def test_decode_rejects_garbage_and_truncation():
    pytest.importorskip("eccodes")
    with pytest.raises(gfs.GribDecodeError, match="GRIB"):
        gfs.decode_apcp(b"<html>Data file is not present</html>")
    good = make_grib(0, 3, np.ones((4, 5)))
    with pytest.raises(gfs.GribDecodeError, match="truncated"):
        gfs.decode_apcp(good[:-10])
    with pytest.raises(gfs.GribDecodeError, match="no APCP"):
        gfs.decode_apcp(b"")


# ---------------------------------------------------------------------------- fakes for fetch tests

SRC_LATS, SRC_LONS = source_axes()
RATE = 0.1  # mm per hour in the synthetic fields


def payload(hour: int, start: int = 0, size: int = 0) -> bytes:
    body = b"GRIB|%d|%d" % (hour, start)
    return body + b"." * max(0, size - len(body))


def fake_decode(data: bytes):
    _, hour, start = data.split(b".")[0].split(b"|")
    hour, start = int(hour), int(start)
    values = np.full((SRC_LATS.size, SRC_LONS.size), RATE * (hour - start), dtype=np.float32)
    return SRC_LATS, SRC_LONS, values, start, hour


class FakeResponse:
    def __init__(self, content: bytes, status: int = 200):
        self.content, self.status_code = content, status
        self.text = content.decode("latin-1")


def cfg_for_tests():
    cfg = copy.deepcopy(load_config("live"))
    cfg["gfs"]["live"]["request_pause_s"] = 0.0
    return cfg


def listing_html(cycle: datetime, hours):
    rows = "".join(
        f'<a href="gfs.t{cycle.hour:02d}z.pgrb2.0p25.f{h:03d}">gfs.t{cycle.hour:02d}z.pgrb2.0p25.f{h:03d}</a>'
        f'                  14-Oct-2026 09:56  1.1M\n' for h in hours)
    return f"<html><pre>{rows}</pre></html>"


class FakeNomads:
    """Answers the listing and filter requests of `fetch_live`."""

    def __init__(self, published_cycles, missing_hours=(), error_hours=()):
        self.published, self.missing, self.errors = set(published_cycles), set(missing_hours), set(error_hours)
        self.requests = []

    def __call__(self, url, *, headers=None, params=None, **kwargs):
        self.requests.append((url, dict(params or {})))
        if params and "file" in params:
            hour = int(params["file"][-3:])
            assert params["var_APCP"] == "on" and params["lev_surface"] == "on"
            assert (params["leftlon"], params["rightlon"], params["bottomlat"], params["toplat"]) == (72.0, 98.0, 8.0, 36.0)
            if hour in self.errors:
                raise DownloadError("HTTP 503 from nomads", retriable=True, status=503)
            if hour in self.missing:
                return FakeResponse(b"<html>Data file is not present</html>")
            return FakeResponse(payload(hour))
        day, hh = url.rstrip("/").split("/")[-3:-1]
        cycle = datetime.strptime(day[4:] + hh, "%Y%m%d%H").replace(tzinfo=UTC)
        if cycle not in self.published:
            raise gfs.NotPublishedError("HTTP 404", status=404)
        return FakeResponse(listing_html(cycle, range(3, 97, 3)).encode())


@pytest.fixture
def store(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    return root, Manifest(tmp_path / "manifest.jsonl", root)


def load_npz(path):
    with np.load(path) as handle:
        return {key: handle[key] for key in handle.files}


def test_nomads_published_treats_403_and_404_as_not_yet_and_other_errors_as_errors(monkeypatch):
    cfg = load_config("live")

    def raising(status):
        def fake(url, **kwargs):
            raise DownloadError(f"HTTP {status}", status=status)
        return fake

    for status in (403, 404):
        monkeypatch.setattr(gfs, "_get", raising(status))
        assert gfs.nomads_published(utc(2026, 10, 14, 18), cfg) is False
    monkeypatch.setattr(gfs, "_get", raising(500))
    with pytest.raises(DownloadError):
        gfs.nomads_published(utc(2026, 10, 14, 18), cfg)
    monkeypatch.setattr(gfs, "_get", lambda url, **kw: FakeResponse(listing_html(utc(2026, 10, 14), range(3, 90, 3)).encode()))
    assert gfs.nomads_published(utc(2026, 10, 14), cfg) is False  # f096 not listed yet


# ----------------------------------------------------------------------------------------- fetch_live

def test_fetch_live_writes_the_day_file(monkeypatch, store):
    root, manifest = store
    net = FakeNomads(published_cycles=[utc(2026, 10, 14, 0)])
    monkeypatch.setattr(gfs, "_get", net)
    monkeypatch.setattr(gfs, "decode_apcp", fake_decode)
    path = gfs.fetch_live(date(2026, 10, 14), cfg_for_tests(), now_utc=utc(2026, 10, 14, 4, 5), root=root, manifest=manifest)
    assert path == root / "processed" / "rain" / "gfs_imdday_2026-10-14.npz"
    arrays = load_npz(path)
    assert arrays["days"].shape == (3, 280, 260) and arrays["days"].dtype == np.float32
    assert np.allclose(arrays["days"], RATE * 24, atol=1e-4)
    assert arrays["lead_days"].tolist() == [1, 2, 3]
    assert str(arrays["cycle"]) == "2026-10-14T00:00:00+00:00"
    assert str(arrays["issued_utc"]) == "2026-10-14T04:05:00+00:00"
    assert arrays["day_valid"].tolist() == [True, True, True] and arrays["missing_hours"].size == 0
    assert np.allclose(arrays["lats"], gfs.TARGET_LATS) and np.allclose(arrays["lons"], gfs.TARGET_LONS)
    raw = sorted((root / "raw" / "gfs" / "live" / "2026101400").glob("f*.grib2"))
    assert len(raw) == 32 and all(manifest.is_current(p) for p in raw)
    assert manifest.is_current(path)


def test_fetch_live_never_uses_a_cycle_after_0300_utc_of_the_issue_day(monkeypatch, store):
    root, manifest = store
    net = FakeNomads(published_cycles=[utc(2026, 10, 14, 0), utc(2026, 10, 14, 6), utc(2026, 10, 14, 12)])
    monkeypatch.setattr(gfs, "_get", net)
    monkeypatch.setattr(gfs, "decode_apcp", fake_decode)
    path = gfs.fetch_live(date(2026, 10, 14), cfg_for_tests(), now_utc=utc(2026, 10, 14, 15), root=root, manifest=manifest)
    assert str(load_npz(path)["cycle"]) == "2026-10-14T00:00:00+00:00"  # D+1 starts at 03:00 UTC, before 06Z


def test_fetch_live_steps_back_when_the_newest_cycle_is_incomplete(monkeypatch, store):
    root, manifest = store
    net = FakeNomads(published_cycles=[utc(2026, 10, 13, 18)])
    monkeypatch.setattr(gfs, "_get", net)
    monkeypatch.setattr(gfs, "decode_apcp", fake_decode)
    path = gfs.fetch_live(date(2026, 10, 14), cfg_for_tests(), now_utc=utc(2026, 10, 14, 3, 30), root=root, manifest=manifest)
    arrays = load_npz(path)
    assert str(arrays["cycle"]) == "2026-10-13T18:00:00+00:00"
    assert np.allclose(arrays["days"], RATE * 24, atol=1e-4)  # windows (9,33), (33,57), (57,81)


def test_fetch_live_records_a_missing_hour_as_nan_days_and_a_gap(monkeypatch, store):
    root, manifest = store
    net = FakeNomads(published_cycles=[utc(2026, 10, 14, 0)], missing_hours=[51], error_hours=[78])
    monkeypatch.setattr(gfs, "_get", net)
    monkeypatch.setattr(gfs, "decode_apcp", fake_decode)
    path = gfs.fetch_live(date(2026, 10, 14), cfg_for_tests(), now_utc=utc(2026, 10, 14, 4), root=root, manifest=manifest)
    arrays = load_npz(path)
    assert arrays["day_valid"].tolist() == [True, False, False]
    assert np.isfinite(arrays["days"][0]).all() and np.isnan(arrays["days"][1:]).all()
    assert arrays["missing_hours"].tolist() == [51]  # f078 failed too, but no window needs it
    gaps = json.loads((root / "processed" / "rain" / gfs.GAPS_FILE).read_text(encoding="utf-8"))
    entry = gaps["2026-10-14"]
    assert entry["cycle"] == "2026-10-14T00:00:00+00:00" and entry["nan_lead_days"] == [2, 3]
    assert sorted(entry["fetch_failures"]) == ["51", "78"] and entry["missing_hours"] == [51]
    assert "Data file is not present" not in json.dumps(gaps) and "503" in entry["fetch_failures"]["78"]


def test_fetch_live_with_nothing_fetched_is_an_error_and_writes_nothing(monkeypatch, store):
    root, manifest = store
    net = FakeNomads(published_cycles=[utc(2026, 10, 14, 0)], missing_hours=range(3, 97, 3))
    monkeypatch.setattr(gfs, "_get", net)
    monkeypatch.setattr(gfs, "decode_apcp", fake_decode)
    with pytest.raises(gfs.GfsFetchError, match="no forecast hour"):
        gfs.fetch_live(date(2026, 10, 14), cfg_for_tests(), now_utc=utc(2026, 10, 14, 4), root=root, manifest=manifest)
    assert not list((root / "processed").glob("**/*.npz"))


def test_fetch_live_gives_up_when_no_cycle_is_complete(monkeypatch, store):
    root, manifest = store
    monkeypatch.setattr(gfs, "_get", FakeNomads(published_cycles=[]))
    with pytest.raises(gfs.NoCompleteCycleError):
        gfs.fetch_live(date(2026, 10, 14), cfg_for_tests(), now_utc=utc(2026, 10, 14, 4), root=root, manifest=manifest)


def test_fetch_live_rerun_does_not_download_again(monkeypatch, store):
    root, manifest = store
    net = FakeNomads(published_cycles=[utc(2026, 10, 14, 0)])
    monkeypatch.setattr(gfs, "_get", net)
    monkeypatch.setattr(gfs, "decode_apcp", fake_decode)
    args = (date(2026, 10, 14), cfg_for_tests())
    kwargs = dict(now_utc=utc(2026, 10, 14, 4), root=root, manifest=manifest)
    gfs.fetch_live(*args, **kwargs)
    first = sum(1 for _, params in net.requests if "file" in params)
    gfs.fetch_live(*args, **kwargs)
    assert sum(1 for _, params in net.requests if "file" in params) == first == 32


# --------------------------------------------------------------------------------------- fetch_archive

class FakeAws:
    """S3 stand-in: .idx text and ranged GETs for 00Z files; selected files can 404 or fail."""

    def __init__(self, missing=(), failing=(), no_cumulative=()):
        self.missing, self.failing, self.no_cumulative = set(missing), set(failing), set(no_cumulative)
        self.calls = []

    def __call__(self, url, *, headers=None, params=None, **kwargs):
        self.calls.append((url, dict(headers or {})))
        key = url[:-4] if url.endswith(".idx") else url
        day = key.split("/gfs.")[1][:8]
        hour = int(key[-3:])
        if (day, hour) in self.failing:
            raise DownloadError("HTTP 500 from s3", retriable=True, status=500)
        if (day, hour) in self.missing:
            raise gfs.NotPublishedError("HTTP 404", status=404)
        bucket_start = 21 if hour == 27 else max(0, hour - 6)
        if url.endswith(".idx"):
            lines = [f"1:0:d={day}00:HGT:surface:{hour} hour fcst:"]
            if hour > 6:  # up to f006 the bucket and the cumulative total are the same record
                lines.append(f"2:1000:d={day}00:APCP:surface:{bucket_start}-{hour} hour acc fcst:")
            if (day, hour) not in self.no_cumulative:
                lines.append(f"3:1600:d={day}00:APCP:surface:0-{hour} hour acc fcst:")
            lines.append(f"4:2500:d={day}00:PRATE:surface:{hour} hour fcst:")
            return FakeResponse(("\n".join(lines) + "\n").encode())
        start, end = (int(x) for x in headers["Range"].removeprefix("bytes=").split("-"))
        assert (start, end) == (1600, 2499), headers["Range"]  # the cumulative record, nothing else
        return FakeResponse(payload(hour, 0, end - start + 1), status=206)


def archive_urls(net):
    return [url for url, _ in net.calls if not url.endswith(".idx")]


def run_archive(days, store, **kwargs):
    root, manifest = store
    return gfs.fetch_archive(days, cfg_for_tests(), root=root, manifest=manifest, **kwargs)


def test_fetch_archive_writes_one_file_per_day_from_apcp_ranges_only(monkeypatch, store):
    root, _ = store
    net = FakeAws()
    monkeypatch.setattr(gfs, "_get", net)
    monkeypatch.setattr(gfs, "decode_apcp", fake_decode)
    days = [date(2023, 7, 14), date(2023, 7, 15)]
    summary = run_archive(days, store, workers=2)
    assert summary["written"] == ["2023-07-14", "2023-07-15"] and summary["skipped"] == [] and summary["failed"] == {}
    assert summary["gaps"] == {}
    arrays = load_npz(root / "processed" / "rain" / "gfs_imdday_2023-07-15.npz")
    assert arrays["days"].shape == (3, 280, 260) and np.allclose(arrays["days"], RATE * 24, atol=1e-4)
    assert str(arrays["cycle"]) == "2023-07-15T00:00:00+00:00"
    ranged = [h for _, h in net.calls if "Range" in h]
    assert len(ranged) == 8 and all(h["Range"] == "bytes=1600-2499" for h in ranged)  # cumulative record only
    assert sorted({u.rsplit(".f", 1)[1] for u in archive_urls(net)}) == ["003", "027", "051", "075"]
    assert all("/atmos/" in u for u in archive_urls(net))
    assert summary["bytes_downloaded"] == 8 * 900


def test_fetch_archive_rerun_is_idempotent(monkeypatch, store):
    net = FakeAws()
    monkeypatch.setattr(gfs, "_get", net)
    monkeypatch.setattr(gfs, "decode_apcp", fake_decode)
    days = [date(2023, 7, 14), date(2023, 7, 15)]
    run_archive(days, store)
    calls = len(net.calls)
    again = run_archive(days, store)
    assert again["written"] == [] and again["skipped"] == ["2023-07-14", "2023-07-15"] and again["failed"] == {}
    assert len(net.calls) == calls  # no request at all


def test_fetch_archive_is_resumable_after_a_failure(monkeypatch, store):
    root, _ = store
    net = FakeAws(failing=[("20230715", 51)])
    monkeypatch.setattr(gfs, "_get", net)
    monkeypatch.setattr(gfs, "decode_apcp", fake_decode)
    days = [date(2023, 7, 14), date(2023, 7, 15), date(2023, 7, 16)]
    first = run_archive(days, store)
    assert first["written"] == ["2023-07-14", "2023-07-16"] and list(first["failed"]) == ["2023-07-15"]
    assert "HTTP 500" in first["failed"]["2023-07-15"]
    assert not (root / "processed" / "rain" / "gfs_imdday_2023-07-15.npz").exists()
    net.failing.clear()
    second = run_archive(days, store)
    assert second["written"] == ["2023-07-15"] and second["skipped"] == ["2023-07-14", "2023-07-16"]
    # the day that failed earlier reuses the raw records already on disk for hours 3, 27
    fetched = [u for u in archive_urls(net) if "gfs.20230715" in u]
    assert sorted(u.rsplit(".f", 1)[1] for u in fetched).count("003") == 1


def test_fetch_archive_missing_file_becomes_a_recorded_gap(monkeypatch, store):
    root, manifest = store
    net = FakeAws(missing=[("20230715", 27)], no_cumulative=[("20230716", 75)])
    monkeypatch.setattr(gfs, "_get", net)
    monkeypatch.setattr(gfs, "decode_apcp", fake_decode)
    summary = run_archive([date(2023, 7, 15), date(2023, 7, 16)], store)
    assert summary["failed"] == {} and summary["written"] == ["2023-07-15", "2023-07-16"]
    assert summary["gaps"] == {"2023-07-15": [27], "2023-07-16": [75]}
    first = load_npz(root / "processed" / "rain" / "gfs_imdday_2023-07-15.npz")
    assert first["day_valid"].tolist() == [False, False, True]  # hour 27 bounds D+1 (end) and D+2 (start)
    assert np.isnan(first["days"][:2]).all() and np.isfinite(first["days"][2]).all()
    assert first["missing_hours"].tolist() == [27]
    second = load_npz(root / "processed" / "rain" / "gfs_imdday_2023-07-16.npz")
    assert second["day_valid"].tolist() == [True, True, False]
    gaps = json.loads((root / "processed" / "rain" / gfs.GAPS_FILE).read_text(encoding="utf-8"))
    assert gaps["2023-07-15"]["missing_hours"] == [27] and gaps["2023-07-15"]["nan_lead_days"] == [1, 2]
    assert "no 0-H" in gaps["2023-07-16"]["fetch_failures"]["75"]
    # a day with gaps is still a finished day: the rerun does not hammer S3 for it again
    calls = len(net.calls)
    assert run_archive([date(2023, 7, 15)], store)["skipped"] == ["2023-07-15"] and len(net.calls) == calls


def test_fetch_archive_stops_asking_after_repeated_failures(monkeypatch, store):
    net = FakeAws(failing=[(f"202307{d:02d}", 3) for d in range(1, 31)])
    monkeypatch.setattr(gfs, "_get", net)
    monkeypatch.setattr(gfs, "decode_apcp", fake_decode)
    days = [date(2023, 7, d) for d in range(1, 31)]
    summary = run_archive(days, store, abort_after=5)
    assert len(summary["failed"]) == 30 and summary["written"] == []
    assert sum("not attempted" in m for m in summary["failed"].values()) == 25
    assert len(net.calls) == 5  # one failed .idx request per attempted day


def test_fetch_archive_path_without_atmos_level_before_march_2021(monkeypatch, store):
    assert gfs.archive_key(utc(2021, 3, 22), 3, load_config("live")["gfs"]["archive"]) == \
        "gfs.20210322/00/gfs.t00z.pgrb2.0p25.f003"
    assert gfs.archive_key(utc(2021, 3, 23), 3, load_config("live")["gfs"]["archive"]) == \
        "gfs.20210323/00/atmos/gfs.t00z.pgrb2.0p25.f003"


def test_archive_days_keeps_only_the_configured_months():
    cfg = load_config("live")["gfs"]["archive"]
    days = gfs.archive_days(date(2021, 5, 30), date(2021, 10, 2), cfg)
    assert days[0] == date(2021, 6, 1) and days[-1] == date(2021, 9, 30) and len(days) == 122
    assert len(gfs.archive_days(date(2021, 6, 1), date(2024, 9, 30), cfg)) == 4 * 122


def test_fetch_archive_rejects_a_corrupt_record(monkeypatch, store):
    def wrong_hour(data):
        lats, lons, values, start, end = fake_decode(data)
        return lats, lons, values, start, end + 3

    monkeypatch.setattr(gfs, "_get", FakeAws())
    monkeypatch.setattr(gfs, "decode_apcp", wrong_hour)
    summary = run_archive([date(2023, 7, 15)], store)
    assert summary["written"] == [] and "ends at hour" in summary["failed"]["2023-07-15"]


# ------------------------------------------------------------------------------------- transport layer

def test_get_retries_server_errors_and_not_client_errors(monkeypatch):
    class Resp:
        def __init__(self, code):
            self.status_code, self.content, self.text = code, b"x", "x"

    calls = []

    def fake_requests_get(url, **kwargs):
        calls.append(kwargs["headers"])
        return Resp([503, 200][len(calls) - 1])

    monkeypatch.setattr(gfs.requests, "get", fake_requests_get)
    monkeypatch.setattr(gfs.time, "sleep", lambda s: None)
    assert gfs._get("https://example.org/x", headers={"Range": "bytes=1-2"}).status_code == 200
    assert len(calls) == 2 and calls[0]["Range"] == "bytes=1-2" and calls[0]["Accept-Encoding"] == "identity"

    monkeypatch.setattr(gfs.requests, "get", lambda url, **kw: Resp(404))
    with pytest.raises(gfs.NotPublishedError):
        gfs._get("https://example.org/x")
    monkeypatch.setattr(gfs.requests, "get", lambda url, **kw: Resp(403))
    with pytest.raises(DownloadError) as caught:
        gfs._get("https://example.org/x")
    assert not caught.value.retriable and not isinstance(caught.value, gfs.NotPublishedError)


# ------------------------------------------------------------------------------- real files and network

def real_live_files():
    return sorted((data_root() / "raw" / "gfs" / "live").glob("*/f012.grib2"))


@pytest.mark.realdata
@pytest.mark.skipif(not real_live_files(), reason="no real NOMADS file downloaded (python -m aetherguard.ingest.gfs_build --live)")
def test_real_nomads_files_decode_and_buckets_reproduce_the_cumulative():
    pytest.importorskip("eccodes")
    f012 = real_live_files()[-1]
    f006 = f012.with_name("f006.grib2")
    fields12 = gfs.decode_apcp_fields(f012.read_bytes())
    fields6 = gfs.decode_apcp_fields(f006.read_bytes())
    assert sorted((f.step_start_h, f.step_end_h) for f in fields12) == [(0, 12), (6, 12)]
    assert {(f.step_start_h, f.step_end_h) for f in fields6} == {(0, 6)}
    lats, lons, cumulative, start, end = gfs.decode_apcp(f012.read_bytes())
    assert (start, end) == (0, 12) and cumulative.shape == (113, 105)
    assert lats[0] == pytest.approx(8.0) and lats[-1] == pytest.approx(36.0)
    assert lons[0] == pytest.approx(72.0) and lons[-1] == pytest.approx(98.0)
    bucket = next(f.values for f in fields12 if f.step_start_h == 6)
    base = gfs.decode_apcp(f006.read_bytes())[2]
    assert np.nanmax(np.abs(base + bucket - cumulative)) < 0.2  # GRIB simple-packing resolution
    assert np.nanmin(cumulative) >= 0 and np.isfinite(cumulative).all()
    on_grid = gfs.regrid_to_imerg(cumulative, lats, lons)
    assert on_grid.shape == (280, 260) and abs(on_grid.mean() / cumulative.mean() - 1) < 0.05


@pytest.mark.live
def test_nomads_latest_cycle_f024_over_the_network(tmp_path):
    pytest.importorskip("eccodes")
    cfg = load_config("live")
    now = datetime.now(UTC)
    cycle = gfs.latest_complete_cycle(now, lambda c: gfs.nomads_published(c, cfg))
    assert 0 <= (now - cycle).total_seconds() / 3600 < 24 + 6 * 4
    manifest = Manifest(tmp_path / "m.jsonl", tmp_path)
    dest = tmp_path / "f024.grib2"
    gfs.fetch_nomads_hour(cycle, 24, cfg, dest, manifest)
    lats, lons, values, start, end = gfs.decode_apcp(dest.read_bytes())
    assert (start, end) == (0, 24) and values.shape == (113, 105)
    assert np.isfinite(values).all() and 0 <= values.mean() < 100


# ------------------------------------------------------------------------------------------------- CLI

def test_cli_rejects_bad_arguments(capsys):
    from aetherguard.ingest import gfs_build
    for argv in ([], ["--live", "--workers", "7"], ["--live", "--workers", "0"],
                 ["--archive", "--start", "2024-02-01", "--end", "2024-01-01"]):
        with pytest.raises(SystemExit) as caught:
            gfs_build.main(argv)
        assert caught.value.code == 2
    assert "--workers must be between 1 and 6" in capsys.readouterr().err


def test_cli_archive_passes_days_workers_and_cycle(monkeypatch, capsys):
    from aetherguard.ingest import gfs_build
    seen = {}

    def fake_archive(days, cfg, cycle_hour, *, workers):
        seen.update(days=days, cycle_hour=cycle_hour, workers=workers)
        return {"written": [d.isoformat() for d in days], "skipped": [], "failed": {}, "gaps": {},
                "bytes_downloaded": 0, "seconds": 0.0}

    monkeypatch.setattr(gfs, "fetch_archive", fake_archive)
    assert gfs_build.main(["--archive", "--start", "2023-05-30", "--end", "2023-06-02", "--workers", "3"]) == 0
    assert seen == {"days": [date(2023, 6, 1), date(2023, 6, 2)], "cycle_hour": 0, "workers": 3}
    assert "written 2" in capsys.readouterr().out
