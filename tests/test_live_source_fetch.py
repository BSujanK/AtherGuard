"""Live source fetch, freshness and the backtest cut-off (aetherguard.live.sources): fakes only, no network."""
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest
import requests

from aetherguard.live import sources as S
from aetherguard.live.early_map import EarlyLateMap

import live_run_helpers as H

UTC = timezone.utc


def ctx_for(tmp_path, backtest=False, day=H.DAY, now=H.NOW):
    cfg = H.make_cfg(tmp_path)
    return cfg, S.make_context(day, cfg, now, backtest, tmp_path / "raw")


# ---- statuses and fetch_all ----------------------------------------------------------------------------------------

def test_status_serialises_and_reports_usability():
    status = S.SourceStatus("gfs", False, H.NOW, H.NOW, 2.0, "partial")
    assert status.usable and status.to_dict()["valid_through"] == "2026-08-12T05:30:00+00:00"
    assert not S.failed("gfs", "down").usable and S.failed("gfs", "down").to_dict()["valid_through"] is None


def test_fetch_all_never_raises_and_redacts_credentials(tmp_path):
    cfg = H.make_cfg(tmp_path)

    class Boom:
        name = "gfs"

        def fetch(self, ctx):
            raise RuntimeError("HTTP 500 from https://x.example/data?token=SECRET123&a=1")

    sources = {**H.healthy_sources(), "gfs": Boom()}
    del sources["ghcn"]
    statuses = S.fetch_all(H.DAY, cfg, sources=sources, now=H.NOW, raw_dir=tmp_path / "raw")
    assert list(statuses) == list(S.SOURCE_NAMES)
    assert statuses["gfs"].ok is False and "SECRET123" not in statuses["gfs"].error and "RuntimeError" in statuses["gfs"].error
    assert statuses["ghcn"].error == "source not configured"
    assert statuses["imd_rt"].ok and statuses["imerg_early"].ok and statuses["imerg_late"].ok


def test_a_source_must_return_its_own_status(tmp_path):
    cfg = H.make_cfg(tmp_path)

    class Wrong:
        def fetch(self, ctx):
            return S.SourceStatus("imd_rt", True, H.NOW, H.NOW, 0.0, None)
    statuses = S.fetch_all(H.DAY, cfg, sources={"gfs": Wrong()}, now=H.NOW, raw_dir=tmp_path / "raw")
    assert "unusable status" in statuses["gfs"].error


def planted(issued_offset_minutes, name="imd_rt"):
    class Planted:
        def fetch(self, ctx):
            issued = (ctx.cutoff or ctx.now) + timedelta(minutes=issued_offset_minutes)
            return S.SourceStatus(name, True, issued - timedelta(hours=1), issued, 1.0, None)
    return Planted()


def test_backtest_rejects_a_planted_late_input_and_keeps_an_early_one(tmp_path):
    cfg = H.make_cfg(tmp_path)
    late = S.fetch_all(H.DAY, cfg, sources={"imd_rt": planted(+1)}, now=H.NOW, backtest=True, raw_dir=tmp_path)
    assert late["imd_rt"].usable is False and "after the backtest cut-off" in late["imd_rt"].error
    assert late["imd_rt"].issued is not None
    early = S.fetch_all(H.DAY, cfg, sources={"imd_rt": planted(-1)}, now=H.NOW, backtest=True, raw_dir=tmp_path)
    assert early["imd_rt"].ok
    live = S.fetch_all(H.DAY, cfg, sources={"imd_rt": planted(+1)}, now=H.NOW, backtest=False, raw_dir=tmp_path)
    assert live["imd_rt"].ok          # outside backtest the cut-off does not apply


def test_backtest_rejects_an_unknown_issue_time(tmp_path):
    cfg = H.make_cfg(tmp_path)

    class NoStamp:
        def fetch(self, ctx):
            return S.SourceStatus("imd_rt", True, H.NOW, None, None, None)
    status = S.fetch_all(H.DAY, cfg, sources={"imd_rt": NoStamp()}, now=H.NOW, backtest=True, raw_dir=tmp_path)["imd_rt"]
    assert not status.usable and "issue time unknown" in status.error


# ---- IMERG source and the live rain series -------------------------------------------------------------------------

def test_imerg_runs_ask_for_the_days_that_exist_at_run_time(tmp_path):
    cfg, ctx = ctx_for(tmp_path)
    late, early = H.imerg_sources(late_missing=True)["imerg_late"], H.imerg_sources(early_missing=True)["imerg_early"]
    assert late.wanted_days(H.DAY)[-1] == H.DAY - timedelta(days=2) and late.required_day(H.DAY) == H.DAY - timedelta(days=2)
    assert early.wanted_days(H.DAY) == [H.DAY - timedelta(days=k) for k in (3, 2, 1)] and early.required_day(H.DAY) == H.DAY - timedelta(days=1)
    late.fetch(ctx)
    early.fetch(ctx)
    asked_late, asked_early = late.store.updated[0], early.store.updated[0]
    assert max(asked_late) == H.DAY - timedelta(days=2) and len(asked_late) == 129      # Late D-1 is not published at 05:30 UTC
    assert asked_early == [H.DAY - timedelta(days=k) for k in (3, 2, 1)]


def test_imerg_status_names_the_missing_day(tmp_path):
    _, ctx = ctx_for(tmp_path)
    status = H.imerg_sources(early_missing=True)["imerg_early"].fetch(ctx)
    assert not status.usable and "no early granule" in status.error
    full = H.imerg_sources()["imerg_late"].fetch(ctx)
    assert full.ok and full.valid_through == S.utc_day_end(H.DAY - timedelta(days=2)) and full.latency_h == 14.5


def test_imerg_update_failure_keeps_the_days_already_stored(tmp_path):
    _, ctx = ctx_for(tmp_path)
    source = H.imerg_sources()["imerg_late"]
    source.store.days.discard(H.DAY - timedelta(days=2))

    def fail(days):
        raise requests.ConnectionError("CMR down")
    source.store.update = fail
    status = source.fetch(ctx)
    assert not status.ok and status.valid_through is not None and "update failed: ConnectionError" in status.error


def test_the_early_run_is_unusable_without_its_fitted_mapping(tmp_path):
    _, ctx = ctx_for(tmp_path)
    early = H.imerg_sources()["imerg_early"]
    early.mapping = None
    status = early.fetch(ctx)
    assert not status.usable and "mapping missing" in status.error


def test_imerg_days_issued_after_the_cutoff_are_not_usable_in_a_backtest(tmp_path):
    _, ctx = ctx_for(tmp_path, backtest=True)
    late = H.imerg_sources()["imerg_late"]
    late.store.days.add(H.DAY - timedelta(days=1))                    # present in the store now, published after 11:00 IST
    assert late.usable(H.DAY - timedelta(days=2), ctx) and not late.usable(H.DAY - timedelta(days=1), ctx)
    live_ctx = ctx_for(tmp_path)[1]
    assert late.usable(H.DAY - timedelta(days=1), live_ctx)


def make_view(tmp_path, first_hours=0.5, backtest=False, product="gfs_00z_0_3h", **options):
    _, ctx = ctx_for(tmp_path, backtest=backtest)
    runs = H.imerg_sources(**options)
    fh = None if first_hours is None else np.full((280, 260), first_hours, dtype=np.float32)
    return S.LiveRainView(H.DAY, runs["imerg_late"], runs["imerg_early"], ctx, fh, product), runs


def test_the_live_series_uses_late_early_mapped_and_the_gfs_hours(tmp_path):
    view, runs = make_view(tmp_path, late_overrides={H.DAY - timedelta(days=2): 10.0},
                           early_overrides={H.DAY - timedelta(days=1): 20.0})
    runs["imerg_early"].mapping = EarlyLateMap(np.array([1.0, 100.0]), np.array([2.0, 200.0]))
    runs["imerg_late"].store.days.add(H.DAY - timedelta(days=1))
    runs["imerg_late"].store.overrides[H.DAY - timedelta(days=1)] = 999.0       # a Late D-1 must never be used
    runs["imerg_early"].store.overrides[H.DAY + timedelta(days=1)] = 555.0      # nor anything after D
    row, col = H.pixel_of("kathmandu")
    out = view.gather([row], [col], H.DAY - timedelta(days=3), 5)[0]
    assert view.product(H.DAY - timedelta(days=3)) == "late" and view.product(H.DAY - timedelta(days=2)) == "late"
    assert out[1] == 10.0                                                           # Late D-2
    assert out[2] == pytest.approx(40.0)                                            # Early D-1 20 mm mapped x2
    assert out[3] == pytest.approx(8 * 0.5)                                         # 0.125 x (8 g) = g
    assert np.isnan(out[4]) and view.product(H.DAY + timedelta(days=1)) == "missing"
    assert [view.product(H.DAY - timedelta(days=1)), view.product(H.DAY)] == ["early_mapped", "gfs_00z_0_3h"]


def test_the_default_early_use_is_as_is(tmp_path):
    view, runs = make_view(tmp_path, early_overrides={H.DAY - timedelta(days=1): 20.0})
    row, col = H.pixel_of("kathmandu")
    assert view.gather([row], [col], H.DAY - timedelta(days=1), 1)[0, 0] == 20.0
    assert view.product(H.DAY - timedelta(days=1)) == "early"
    assert S.IdentityMap().apply(np.array([0.0, 0.03, np.nan, 5.0]))[3] == 5.0


@pytest.mark.parametrize("product", ["gfs_00z_0_3h", "gfs_18z_6_9h", "gfs_12z_12_15h"])
def test_the_training_rule_applied_to_the_live_series_gives_the_gfs_part_exactly(tmp_path, product):
    from aetherguard.features.imerg_features import imd_day_series
    view, _ = make_view(tmp_path, first_hours=0.8, product=product)
    row, col = H.pixel_of("kathmandu")
    utc = view.gather([row], [col], H.DAY - timedelta(days=2), 3)
    imd = imd_day_series(utc)[0]
    assert view.product(H.DAY) == product
    assert imd[1] == pytest.approx(0.875 * H.LIGHT_MM + 0.8)          # IMD day D = 0.875 Early(D-1) + g
    assert imd[0] == pytest.approx(0.875 * H.LIGHT_MM + 0.125 * H.LIGHT_MM)       # IMD day D-1 = 0.875 Late(D-2) + 0.125 Early(D-1)


def test_without_gfs_hours_the_tail_is_persisted_from_utc_d_minus_1(tmp_path):
    from aetherguard.features.imerg_features import imd_day_series
    view, _ = make_view(tmp_path, first_hours=None, early_overrides={H.DAY - timedelta(days=1): 20.0})
    row, col = H.pixel_of("kathmandu")
    utc = view.gather([row], [col], H.DAY - timedelta(days=1), 2)[0]
    assert view.product(H.DAY) == "persist_d1" and utc[0] == utc[1] == 20.0          # UTC D := UTC D-1
    assert imd_day_series(utc[None, :])[0, 0] == pytest.approx(20.0)                  # 0.875 x 20 + 0.125 x 20
    assert view.imd_day_inputs()["D"] == {"utc_day_0.875": "early", "utc_day_0.125": "persist_d1",
                                           "product": "early+persist_d1"}
    assert view.coverage_gaps() == []


def test_missing_products_are_missing_not_zero(tmp_path):
    view, _ = make_view(tmp_path, first_hours=None, early_missing=True)
    row, col = H.pixel_of("kathmandu")
    out = view.gather([row], [col], H.DAY - timedelta(days=2), 3)[0]
    assert out[0] == H.LIGHT_MM and np.isnan(out[1]) and np.isnan(out[2])           # nothing to persist either
    assert view.imd_day_inputs()["D"]["product"] == "missing" and view.imd_day_inputs()["D-1"]["product"] == "missing"
    assert view.coverage_gaps() == [H.DAY - timedelta(days=1), H.DAY]
    nothing = S.LiveRainView(H.DAY, None, None, ctx_for(tmp_path)[1])
    assert all(nothing.product(H.DAY - timedelta(days=k)) == "missing" for k in range(4))


def test_early_fills_d3_and_d2_where_late_is_missing(tmp_path):
    view, runs = make_view(tmp_path)
    runs["imerg_late"].store.days.discard(H.DAY - timedelta(days=2))
    assert view.product(H.DAY - timedelta(days=2)) == "early"
    assert view.imd_day_inputs()["D-1"]["product"] == "early"


def test_early_map_mode_selects_identity_or_the_fitted_curve(tmp_path):
    assert H.make_cfg(tmp_path)["early_map"]["mode"] == "identity"
    fitted = H.make_cfg(tmp_path, early_map={"mode": "fitted", "file": str(tmp_path / "map.json")})
    assert S.default_sources(fitted)["imerg_early"].mapping is None              # no file yet: the Early run is unusable
    H.FITTED_MAP.save(tmp_path / "map.json")
    loaded = S.default_sources(fitted)["imerg_early"].mapping
    assert isinstance(loaded, EarlyLateMap) and loaded.label == "early_mapped"
    with pytest.raises(ValueError, match="early_map.mode"):
        S.default_sources(H.make_cfg(tmp_path, early_map={"mode": "bogus", "file": "x"}))


# ---- GFS ------------------------------------------------------------------------------------------------------------

def gfs_file(root, day, valid=(True, True, True), hours=()):
    path = S.GfsSource({}, latency_h=3.95, first_hours_latency_h=3.6, root=root).day_file(day)
    path.parent.mkdir(parents=True, exist_ok=True)
    days = np.full((3, 280, 260), 3.0, dtype=np.float32)
    days[[not v for v in valid]] = np.nan
    np.savez(path, days=days, cycle=np.array(datetime(day.year, day.month, day.day, tzinfo=UTC).isoformat()),
             issued_utc=np.array("x"), lead_days=np.array([1, 2, 3]), day_valid=np.array(valid),
             missing_hours=np.array(hours, dtype=np.int32), lats=np.zeros(1), lons=np.zeros(1))
    return path


def gfs_source(tmp_path, monkeypatch, first_hours=1.5, unavailable=()):
    """A GfsSource whose hour files come from `fetch_hour` (cycles whose hour is in `unavailable` are refused)."""
    calls = {"live": 0, "fetched": [], "reads": []}

    def read_accumulation(end_path, end_hour, start_path, start_hour, bbox):
        calls["reads"].append((end_hour, start_hour))
        return np.full((280, 260), first_hours, dtype=np.float32)
    monkeypatch.setattr(S, "read_accumulation", read_accumulation)

    def fetch_live(day, cfg, now_utc, root):
        calls["live"] += 1

    def fetch_hour(cycle, hour, cfg, dest, root, backtest):
        calls["fetched"].append((cycle.hour, hour))
        if cycle.hour in unavailable:
            raise S.DownloadError(f"HTTP 403 for the {cycle:%Y-%m-%d %HZ} cycle")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"GRIB")
    source = S.GfsSource({"domain_bbox": {}}, latency_h=3.95, first_hours_latency_h=3.6, root=tmp_path,
                         fetch_live=fetch_live, fetch_archive=lambda days, cfg, root: calls.__setitem__("archive", days),
                         fetch_hour=fetch_hour)
    return source, calls


def test_gfs_complete_uses_the_00z_cycle(tmp_path, monkeypatch):
    source, calls = gfs_source(tmp_path, monkeypatch)
    gfs_file(tmp_path, H.DAY)
    _, ctx = ctx_for(tmp_path)
    status = source.fetch(ctx)
    assert status.ok and status.error is None and status.valid_through == S.imd_day_end(H.DAY + timedelta(days=3))
    assert status.issued == datetime(2026, 8, 12, 3, 57, tzinfo=UTC) and calls["live"] == 1
    assert status.latency_h == pytest.approx(3.95)          # issued minus the cycle time, not minus the end of the forecast
    assert calls["fetched"] == [(0, 3)] and calls["reads"] == [(3, 0)]
    data = source.load(ctx)
    assert data.forecast.day_valid.all() and float(data.first_hours[0, 0]) == 1.5
    assert data.first_hours_product == "gfs_00z_0_3h"


def test_gfs_falls_back_to_the_18z_cycle_for_the_nowcast_tail(tmp_path, monkeypatch):
    source, calls = gfs_source(tmp_path, monkeypatch, unavailable=(0,))
    gfs_file(tmp_path, H.DAY)
    _, ctx = ctx_for(tmp_path)
    status = source.fetch(ctx)
    assert calls["fetched"] == [(0, 3), (18, 6), (18, 9)] and calls["reads"] == [(9, 6)]       # f009 - f006 = 00-03 UTC D
    assert status.ok and "gfs_18z_6_9h" in status.error and "00Z cycle" in status.error
    assert source.load(ctx).first_hours_product == "gfs_18z_6_9h"


def test_gfs_falls_back_to_the_12z_cycle_next(tmp_path, monkeypatch):
    source, calls = gfs_source(tmp_path, monkeypatch, unavailable=(0, 18))
    gfs_file(tmp_path, H.DAY)
    _, ctx = ctx_for(tmp_path)
    assert source.fetch(ctx).ok
    assert calls["fetched"][-2:] == [(12, 12), (12, 15)] and calls["reads"] == [(15, 12)]
    assert source.load(ctx).first_hours_product == "gfs_12z_12_15h"


def test_gfs_without_any_cycle_leaves_the_tail_to_persistence(tmp_path, monkeypatch):
    source, calls = gfs_source(tmp_path, monkeypatch, unavailable=(0, 18, 12))
    gfs_file(tmp_path, H.DAY)
    _, ctx = ctx_for(tmp_path)
    status = source.fetch(ctx)
    data = source.load(ctx)
    assert not status.ok and status.usable and "persisted" in status.error and calls["reads"] == []
    assert data.first_hours is None and data.first_hours_product == "persist_d1" and data.forecast is not None


def test_gfs_partial_forecast_is_late_and_names_the_lead_days(tmp_path, monkeypatch):
    source, _ = gfs_source(tmp_path, monkeypatch)
    gfs_file(tmp_path, H.DAY, valid=(True, False, False), hours=[72, 96])
    status = source.fetch(ctx_for(tmp_path)[1])
    assert not status.ok and status.usable and "D+2, D+3" in status.error and "[72, 96]" in status.error
    assert S.source_state(status, H.DAY, H.make_cfg(tmp_path)) == "late"


def test_gfs_without_any_file_fails_with_the_fetch_error(tmp_path, monkeypatch):
    source, _ = gfs_source(tmp_path, monkeypatch, unavailable=(0, 18, 12))

    def refuse(day, cfg, now_utc, root):
        raise requests.ConnectionError("NOMADS unreachable")
    source._fetch_live = refuse
    status = source.fetch(ctx_for(tmp_path)[1])
    assert not status.usable and "ConnectionError" in status.error
    assert source.load(ctx_for(tmp_path)[1]).first_hours_product == "persist_d1"


def test_gfs_backtest_uses_the_archive_and_skips_cycles_issued_after_the_cutoff(tmp_path, monkeypatch):
    source, calls = gfs_source(tmp_path, monkeypatch)
    _, ctx = ctx_for(tmp_path, backtest=True)
    status = source.fetch(ctx)
    assert calls["live"] == 0 and calls["archive"] == [H.DAY] and "no GFS forecast file" in status.error
    assert status.latency_h == pytest.approx(3.6)           # no forecast: the cycle that supplied the 00-03 UTC hours
    assert source.load(ctx).first_hours_product == "gfs_00z_0_3h"
    # the 00Z cycle is published 3.6 h after its time (03:36 UTC); a cut-off at 08:00 IST = 02:30 UTC leaves the 18Z cycle
    early_cfg = H.make_cfg(tmp_path)
    early_cfg["schedule"]["data_cutoff"] = "08:00"
    gfs_file(tmp_path, H.DAY)
    calls["fetched"].clear()
    early_ctx = S.make_context(H.DAY, early_cfg, H.NOW, True, tmp_path / "raw")
    status = source.fetch(early_ctx)
    assert (0, 3) not in calls["fetched"] and source.load(early_ctx).first_hours_product == "gfs_18z_6_9h"
    assert "not published yet" in status.error


def test_fetch_hour_file_prefers_nomads_live_and_the_archive_in_a_backtest(tmp_path, monkeypatch):
    from aetherguard.ingest import gfs
    seen = []
    monkeypatch.setattr(gfs, "fetch_nomads_hour", lambda cycle, hour, cfg, dest, manifest: seen.append(("nomads", hour)))
    monkeypatch.setattr(gfs, "fetch_archive_hour", lambda cycle, hour, cfg, dest, manifest: seen.append(("archive", hour)))
    cycle = datetime(2026, 8, 12, tzinfo=UTC)
    S.fetch_hour_file(cycle, 3, {}, tmp_path / "f.grib2", tmp_path, backtest=False)
    S.fetch_hour_file(cycle, 9, {}, tmp_path / "f.grib2", tmp_path, backtest=True)
    assert seen == [("nomads", 3), ("archive", 9)]

    def refuse(cycle, hour, cfg, dest, manifest):
        raise gfs.DownloadError("HTTP 403")
    monkeypatch.setattr(gfs, "fetch_nomads_hour", refuse)
    S.fetch_hour_file(cycle, 6, {}, tmp_path / "f.grib2", tmp_path, backtest=False)
    assert seen[-1] == ("archive", 6)


# ---- IMD real-time ------------------------------------------------------------------------------------------------

def test_imd_grid_parsing_marks_missing_as_nan():
    grid = np.full((129, 135), 5.0, dtype="<f4")
    grid[0, 0], grid[1, 1] = -999.0, -3.0
    parsed = S.parse_imd_grid(grid.tobytes())
    assert np.isnan(parsed[0, 0]) and np.isnan(parsed[1, 1]) and parsed[2, 2] == 5.0
    with pytest.raises(ValueError, match="bytes"):
        S.parse_imd_grid(b"123")


def test_imd_files_are_cached_and_reused_by_the_next_run(tmp_path):
    calls = []
    source = H.imd_source(H.imd_post(calls=calls))
    cfg = H.make_cfg(tmp_path)
    ctx = S.make_context(H.DAY, cfg, H.NOW, False)
    status = source.fetch(ctx)
    assert status.ok and sorted(calls) == [H.DAY - timedelta(days=k) for k in (2, 1, 0)] and sorted(source.grids) == sorted(calls)
    next_day = H.DAY + timedelta(days=1)
    next_calls = []
    second = H.imd_source(H.imd_post(calls=next_calls))
    assert second.fetch(S.make_context(next_day, cfg, H.NOW + timedelta(days=1), False)).ok
    assert next_calls == [next_day]                                    # D-1 and D-2 of the next run come from the cache


def test_imd_not_published_is_a_failure_and_a_transport_error_stops_the_run(tmp_path):
    cfg = H.make_cfg(tmp_path)
    ctx = S.make_context(H.DAY, cfg, H.NOW, False)
    status = H.imd_source(lambda day, timeout: None).fetch(ctx)
    assert not status.usable and "not published" in status.error
    calls = []

    def flaky(day, timeout):
        calls.append(day)
        raise requests.ReadTimeout("slow")
    source = H.imd_source(flaky)
    status = source.fetch(S.make_context(H.DAY, H.make_cfg(tmp_path / "other"), H.NOW, False))
    assert not status.usable and "ReadTimeout" in status.error and len(calls) == 1


def test_imd_backtest_only_reads_days_published_before_the_cutoff(tmp_path):
    calls = []
    source = H.imd_source(H.imd_post(calls=calls))
    status = source.fetch(S.make_context(H.DAY, H.make_cfg(tmp_path), H.NOW, True))
    # IMD day d is published about 24 h after 03:00 UTC of d: day D is not there at 11:00 IST of D, D-1 is
    assert sorted(calls) == [H.DAY - timedelta(days=2), H.DAY - timedelta(days=1)]
    assert not status.ok and status.usable and "no file for IMD day" in status.error


# ---- GHCN ----------------------------------------------------------------------------------------------------------

def test_ghcn_values_are_nan_not_zero_where_missing(tmp_path):
    source = H.ghcn_source()
    status = source.fetch(S.make_context(H.DAY, H.make_cfg(tmp_path), H.NOW, False, tmp_path / "raw"))
    data = source.load(None)
    assert status.ok and status.valid_through == S.utc_day_end(H.DAY - timedelta(days=6))
    assert list(data.values.columns) == list(H.STATIONS["id"]) and data.values.index[-1] == pd.Timestamp(H.DAY)
    assert data.values.iloc[-1].isna().all() and data.values.iloc[0].eq(3.2).all()
    assert (tmp_path / "raw" / "ghcn_prcp.csv").is_file()


def test_ghcn_empty_and_partial_answers(tmp_path):
    ctx = S.make_context(H.DAY, H.make_cfg(tmp_path), H.NOW, False, tmp_path / "raw")
    assert "no PRCP value" in H.ghcn_source(lambda params: []).fetch(ctx).error

    def one_bad(params):
        if "GH000002" in params["stations"]:
            raise requests.ConnectionError("down")
        return H.ghcn_fetch(params)
    source = H.ghcn_source(one_bad)
    source.per_request = 1
    status = source.fetch(ctx)
    assert not status.ok and status.usable and "1 of 2 requests failed" in status.error
    assert source.load(ctx).values["GH000002"].isna().all()


def test_ghcn_backtest_drops_values_not_yet_published(tmp_path):
    source = H.ghcn_source()
    source.fetch(S.make_context(H.DAY, H.make_cfg(tmp_path), H.NOW, True, tmp_path / "raw"))
    newest = source.load(None).values.dropna(how="all").index.max()
    # a value for date x is published 120 h after the end of x: at the cut-off only dates up to D-6 qualify
    assert newest == pd.Timestamp(H.DAY - timedelta(days=6))
    rows = [{"DATE": (H.DAY - timedelta(days=1)).isoformat(), "STATION": "GH000001", "PRCP": "9", "PRCP_ATTRIBUTES": ",,"}]
    late = H.ghcn_source(lambda params: rows)
    status = late.fetch(S.make_context(H.DAY, H.make_cfg(tmp_path), H.NOW, True, tmp_path / "raw"))
    assert not status.usable


# ---- freshness ----------------------------------------------------------------------------------------------------

def test_freshness_states_and_expectations(tmp_path):
    cfg = H.make_cfg(tmp_path)
    day = H.DAY
    assert S.expected_valid_through("imerg_late", day, cfg) == S.utc_day_end(day - timedelta(days=2))
    assert S.expected_valid_through("imerg_early", day, cfg) == S.utc_day_end(day - timedelta(days=1))
    assert S.expected_valid_through("imd_rt", day, cfg) == S.imd_day_end(day)
    on_time = S.SourceStatus("imd_rt", True, S.imd_day_end(day), H.NOW, 2.0, None)
    behind = S.SourceStatus("imd_rt", True, S.imd_day_end(day - timedelta(days=1)), H.NOW, 26.0, None)
    assert S.source_state(on_time, day, cfg) == "ok" and S.source_state(behind, day, cfg) == "late"
    assert S.source_state(S.failed("imd_rt", "x"), day, cfg) == "failed"
    record = S.freshness_record(day, cfg, {"imd_rt": on_time}, H.NOW, True, {"D": {}})
    assert record["data_cutoff_utc"] == "2026-08-12T05:30:00+00:00" and record["imd_day_inputs"] == {"D": {}}
    assert record["sources"]["imd_rt"]["state"] == "ok"


def test_default_sources_name_all_five_and_disabled_ones_fail_with_their_reason(tmp_path, monkeypatch):
    cfg = H.make_cfg(tmp_path)
    cfg["gfs"]["enabled"] = cfg["imd_rt"]["enabled"] = cfg["ghcn"]["enabled"] = False
    sources = S.default_sources(cfg)
    assert list(sources) == ["imerg_late", "imerg_early", "gfs", "ecmwf", "imd_rt", "ghcn"]
    assert isinstance(sources["ecmwf"], S.EcmwfSource) and "ecmwf" not in S.SOURCE_NAMES
    assert isinstance(sources["imerg_early"].mapping, S.IdentityMap)          # the shipped default is identity
    statuses = S.fetch_all(H.DAY, cfg, sources={k: sources[k] for k in ("gfs", "imd_rt", "ghcn")}, now=H.NOW,
                           raw_dir=tmp_path)
    assert all("disabled in configs/live_run.yaml" == statuses[k].error for k in ("gfs", "imd_rt", "ghcn"))


@pytest.mark.live
def test_fetch_all_for_today_against_the_real_sources(tmp_path, monkeypatch):
    """Read-only smoke: the IMERG stores are not updated (their statuses show what they hold), GFS files land in the
    usual raw/processed folders, IMD and gauge files in `tmp_path`. Prints the five statuses (run with -s)."""
    from aetherguard.live import run as live_run
    cfg = live_run.load_run_config()
    cfg["live_dir"] = str(tmp_path / "live")
    sources = S.default_sources(cfg)
    for name in ("imerg_late", "imerg_early"):
        monkeypatch.setattr(sources[name].store, "update", lambda days: {})
    now = datetime.now(UTC)
    day = S.resolve_day("today", cfg, now)
    statuses = S.fetch_all(day, cfg, sources=sources, now=now, raw_dir=tmp_path / "raw")
    for name, status in statuses.items():
        print(name, S.source_state(status, day, cfg), status.valid_through, status.issued, status.error)
    assert list(statuses) == [*S.SOURCE_NAMES, *S.OPTIONAL_SOURCE_NAMES]


def test_source_latencies_follow_the_probe_definitions(tmp_path):
    """reports/phase6_live_sources_probe.md: IMERG, IMD and GHCN latency = issued minus the end of the data's last day;
    GFS = issued minus the cycle time."""
    _, ctx = ctx_for(tmp_path)
    late = H.imerg_sources()["imerg_late"].fetch(ctx)
    assert late.latency_h == pytest.approx((late.issued - late.valid_through).total_seconds() / 3600) == 14.5
    imd = H.imd_source().fetch(ctx)
    assert imd.latency_h == pytest.approx((imd.issued - S.imd_day_end(H.DAY)).total_seconds() / 3600)
    assert all(s.latency_h >= 0 for s in (late, imd, H.ghcn_source().fetch(ctx)))


# ----------------------------------------------------------------------------------------------------- ECMWF

ECMWF_CYCLE = datetime(2026, 8, 11, 18, tzinfo=timezone.utc)          # the 18Z run of D-1 for H.DAY


def write_ecmwf_day(root, day=H.DAY, hres_valid=(True, True, True), ens_valid=(True, True, True), cycle=ECMWF_CYCLE):
    from aetherguard.ingest import ecmwf
    shape = (3, 280, 260)
    arrays = {"lead_days": np.array([1, 2, 3]), "hres": np.full(shape, 2.0, np.float16), "hres_valid": np.array(hres_valid),
              "hres_cycle": np.array(cycle.isoformat()), "ens_mean": np.full(shape, 3.0, np.float16),
              "ens_p10": np.full(shape, 1.0, np.float16), "ens_p50": np.full(shape, 3.0, np.float16),
              "ens_p90": np.full(shape, 6.0, np.float16), "ens_valid": np.array(ens_valid),
              "ens_cycle": np.array(cycle.isoformat()), "n_members": np.array(51)}
    path = ecmwf.day_file_path(root, day)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(path, **arrays)
    return path


def ecmwf_source(tmp_path, **fetchers):
    return S.EcmwfSource({}, latency_h=8.2, root=tmp_path, **fetchers)


def test_ecmwf_live_fetch_reads_the_day_file_it_just_wrote(tmp_path):
    calls = []
    source = ecmwf_source(tmp_path, fetch_live=lambda day, cfg, now_utc, root: calls.append((day, now_utc)) or write_ecmwf_day(root))
    ctx = S.make_context(H.DAY, {"schedule": {"timezone": "Asia/Kolkata", "data_cutoff": "11:00"}}, H.NOW, False, tmp_path)
    status = source.fetch(ctx)
    assert calls == [(H.DAY, H.NOW)] and status.ok and status.error is None and status.name == "ecmwf"
    assert status.valid_through == S.imd_day_end(H.DAY + timedelta(days=3))
    assert status.issued == min(ECMWF_CYCLE + timedelta(hours=8.2), H.NOW) and status.latency_h == pytest.approx(8.2)
    data = source.load(ctx)
    assert data.hres_valid.all() and data.n_members == 51 and data.ens_mean.dtype == np.float32


def test_ecmwf_partial_day_is_usable_but_not_ok(tmp_path):
    write_ecmwf_day(tmp_path, hres_valid=(True, False, False), ens_valid=(False, False, False))
    source = ecmwf_source(tmp_path, fetch_live=lambda *a, **k: None)
    status = source.fetch(S.make_context(H.DAY, {"schedule": {"timezone": "Asia/Kolkata", "data_cutoff": "11:00"}}, H.NOW, False, tmp_path))
    assert status.usable and not status.ok
    assert status.valid_through == S.imd_day_end(H.DAY + timedelta(days=1))
    assert "HRES is missing D+2, D+3" in status.error and "ensemble has no data" in status.error


def test_ecmwf_failed_fetch_keeps_an_earlier_file_of_the_day_and_says_so(tmp_path):
    write_ecmwf_day(tmp_path)

    def boom(*a, **k):
        raise RuntimeError("HTTP 503")
    status = ecmwf_source(tmp_path, fetch_live=boom).fetch(
        S.make_context(H.DAY, {"schedule": {"timezone": "Asia/Kolkata", "data_cutoff": "11:00"}}, H.NOW, False, tmp_path))
    assert status.usable and "newest cycle not fetched" in status.error and "HTTP 503" in status.error


def test_ecmwf_without_a_file_fails_with_the_reason(tmp_path):
    def boom(*a, **k):
        raise RuntimeError("HTTP 503")
    cfg = {"schedule": {"timezone": "Asia/Kolkata", "data_cutoff": "11:00"}}
    status = ecmwf_source(tmp_path, fetch_live=boom).fetch(S.make_context(H.DAY, cfg, H.NOW, False, tmp_path))
    assert not status.usable and "HTTP 503" in status.error
    assert not ecmwf_source(tmp_path, fetch_live=lambda *a, **k: None).fetch(S.make_context(H.DAY, cfg, H.NOW, False, tmp_path)).usable


def test_ecmwf_backtest_reads_the_archive_and_respects_the_cutoff(tmp_path):
    cfg = {"schedule": {"timezone": "Asia/Kolkata", "data_cutoff": "11:00"}}
    fetched = []
    source = ecmwf_source(tmp_path, fetch_archive=lambda days, live_cfg, root: fetched.append(days) or write_ecmwf_day(root))
    statuses = S.fetch_all(H.DAY, cfg, sources={"ecmwf": source}, now=H.NOW, backtest=True, raw_dir=tmp_path)
    assert fetched == [[H.DAY]] and statuses["ecmwf"].ok          # 18Z of D-1 + 8.2 h = 02:12 UTC, before the 05:30 UTC cut-off
    late = ecmwf_source(tmp_path)
    write_ecmwf_day(tmp_path, cycle=datetime(2026, 8, 12, 0, tzinfo=timezone.utc))     # a 00Z run of D, out at 08:12 UTC
    status = S.fetch_all(H.DAY, cfg, sources={"ecmwf": late}, now=H.NOW, backtest=True, raw_dir=tmp_path)["ecmwf"]
    assert not status.usable and "after the backtest cut-off" in status.error


def test_fetch_all_adds_ecmwf_only_when_it_is_configured(tmp_path):
    cfg = H.make_cfg(tmp_path)
    plain = S.fetch_all(H.DAY, cfg, sources=H.healthy_sources(), now=H.NOW, raw_dir=tmp_path)
    assert "ecmwf" not in plain
    write_ecmwf_day(tmp_path)
    withit = S.fetch_all(H.DAY, cfg, sources={**H.healthy_sources(), "ecmwf": ecmwf_source(tmp_path, fetch_live=lambda *a, **k: None)},
                         now=H.NOW, raw_dir=tmp_path)
    assert list(withit) == [*S.SOURCE_NAMES, "ecmwf"] and withit["ecmwf"].ok
    assert S.source_state(withit["ecmwf"], H.DAY, cfg) == "ok"
