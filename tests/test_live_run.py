"""The daily live run (aetherguard.live.run) on fake sources, a tiny model and a handful of cells: no network."""
import base64
import json
from datetime import timedelta

import numpy as np
import pandas as pd
import pytest
import yaml
from fastapi.testclient import TestClient

from aetherguard.alerts.store import NoSensorsError, ReplayStore
from aetherguard.live import forecast_features
from aetherguard.live import run as live_run
from aetherguard.live import sources as S
from aetherguard.live.sources import FetchContext, SourceStatus
from aetherguard.serve import api

import live_run_helpers as H

LEAD_FILES = ["risk_D0.parquet", "risk_D1.parquet", "risk_D2.parquet", "risk_D3.parquet"]
FEATURE_FILES = ["features_D0.parquet", "features_D1.parquet", "features_D2.parquet", "features_D3.parquet"]
FILES = ["alerts.parquet", "freshness.json", "run.json", *FEATURE_FILES, *LEAD_FILES]


def run_dir(cfg, day=H.DAY):
    return live_run.live_root(cfg) / day.isoformat()


def alerts_of(cfg, day=H.DAY):
    return pd.read_parquet(run_dir(cfg, day) / "alerts.parquet")


def wayanad(frame):
    return frame[frame["cell_id"] == int(H.tiny_cells().query("region == 'western_ghats'")["cell_id"].iloc[0])].iloc[0]


@pytest.fixture(scope="module")
def happy(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("happy")
    cfg = H.make_cfg(tmp)
    return cfg, live_run.run_day(H.DAY, cfg, deps=H.make_deps())


# ---- happy path ---------------------------------------------------------------------------------------------------

def test_happy_path_writes_every_file_and_the_bulletin(happy):
    cfg, summary = happy
    assert sorted(p.name for p in run_dir(cfg).iterdir() if p.is_file()) == sorted(FILES)
    assert (run_dir(cfg) / "raw" / "imd_rt").is_dir()
    assert (live_run.project_path(cfg["report_dir"]) / f"{H.DAY}.md").is_file()
    assert summary["status"] == "complete" and not summary["failed_sources"] and not summary["retry_recommended"]
    assert summary["files"] == sorted(FILES)
    assert json.loads((run_dir(cfg) / "run.json").read_text(encoding="utf-8"))["date"] == H.DAY.isoformat()


def test_alerts_follow_the_rain(happy):
    cfg, _ = happy
    alerts = alerts_of(cfg)
    row = wayanad(alerts)
    assert row["level"] == 3 and row["confidence"] == "High" and row["risk"] > 0.9
    others = alerts[alerts["cell_id"] != row["cell_id"]]
    assert (others["level"] == 0).all()
    assert str(alerts["date"].dt.date.iloc[0]) == H.DAY.isoformat()
    assert alerts["level"].dtype == np.int8
    assert set(alerts["confidence"]) <= {"High", "Degraded", "Insufficient"}


def test_features_are_the_alert_frame(happy):
    cfg, _ = happy
    features = pd.read_parquet(run_dir(cfg) / "features_D0.parquet")
    for column in ("irain_acc_1", "iapi_90", "inbr_max_acc_1", "stat_slope_mean", "src_imd_acc_1", "src_chi_acc_1",
                   "src_dis_ratio_3", "rain_acc_1", "rain_source", "integ_n_st_100km"):
        assert column in features.columns
    row = wayanad(features)
    # IMD day D = 0.875 x mapped Early(D-1) + the GFS 0-3 h part: 0.875 * 90 + 0.5
    assert row["irain_acc_1"] == pytest.approx(0.875 * H.HEAVY_MM + 0.5, rel=1e-5)
    assert row["rain_acc_1"] == row["irain_acc_1"] and row["rain_source"] == "imerg"
    assert row["src_imd_acc_1"] == pytest.approx(60.0)
    assert row["src_chi_acc_1"] == pytest.approx(row["irain_acc_1"], rel=1e-5)


def test_last_two_imd_days_record_their_products(happy):
    cfg, summary = happy
    inputs = summary["imd_day_inputs"]
    assert inputs["D"] == {"utc_day_0.875": "early", "utc_day_0.125": "gfs_00z_0_3h", "product": "early+gfs_00z_0_3h"}
    assert inputs["D-1"]["product"] == "late+early"
    freshness = json.loads((run_dir(cfg) / "freshness.json").read_text(encoding="utf-8"))
    assert freshness["imd_day_inputs"] == inputs


def test_freshness_schema(happy):
    cfg, _ = happy
    freshness = json.loads((run_dir(cfg) / "freshness.json").read_text(encoding="utf-8"))
    assert freshness["available"] is True and freshness["date"] == H.DAY.isoformat() and freshness["backtest"] is False
    assert list(freshness["sources"]) == ["imerg_late", "imerg_early", "gfs", "imd_rt", "ghcn"]
    for source in freshness["sources"].values():
        assert set(source) == {"name", "ok", "valid_through", "issued", "latency_h", "error", "state",
                               "expected_valid_through"}
    assert {s["state"] for s in freshness["sources"].values()} == {"ok"}


def test_replay_set_live_is_readable(happy):
    cfg, _ = happy
    store = ReplayStore(live_run.project_path(cfg["replay_dir"]))
    assert store.status() == "ok" and store.dates("live") == [H.DAY.isoformat()]
    name, frame = store.alerts(H.DAY.isoformat(), "live")
    assert name == "live" and len(frame) == 4
    assert store.manifest["sets"]["live"]["has_sensors"] is True


def test_replay_set_accumulates_dates_and_keeps_other_sets(tmp_path):
    cfg = H.make_cfg(tmp_path)
    store_dir = live_run.project_path(cfg["replay_dir"])
    store_dir.mkdir(parents=True)
    (store_dir / "store_manifest.json").write_text(json.dumps({"freeze": {"x": 1}, "sets": {"other": {"dates": ["2018-08-01"],
                                                    "n_rows": 1, "n_cells": 1, "has_sensors": False}}}), encoding="utf-8")
    live_run.run_day(H.DAY, cfg, deps=H.make_deps())
    live_run.run_day(H.DAY + timedelta(days=1), cfg, deps=H.make_deps(
        sources=H.healthy_sources(H.DAY + timedelta(days=1))))
    manifest = json.loads((store_dir / "store_manifest.json").read_text(encoding="utf-8"))
    assert manifest["freeze"] == {"x": 1} and manifest["sets"]["other"]["dates"] == ["2018-08-01"]
    assert manifest["sets"]["live"]["dates"] == [H.DAY.isoformat(), (H.DAY + timedelta(days=1)).isoformat()]
    assert manifest["sets"]["live"]["n_rows"] == 8
    assert not (store_dir / live_run.REPLAY_STAGE).exists()


def test_dashboard_api_reads_the_run(happy, tmp_path):
    cfg, _ = happy
    app = api.create_app(live_run.project_path(cfg["replay_dir"]), live_dir=live_run.live_root(cfg),
                         dist_dir=tmp_path / "no-dist")
    client = TestClient(app)
    mode = client.get("/api/mode").json()
    assert mode["mode"] == "live" and mode["latest_date"] == H.DAY.isoformat()
    for lead in (0, 1, 2, 3):
        body = client.get("/api/grid", params={"date": H.DAY.isoformat(), "lead": lead}).json()
        assert body["n"] == 4 and body["lead"] == lead and body["set"] == "live"
        level = np.frombuffer(base64.b64decode(body["level"]), dtype="u1")
        assert level.max() <= 3
    risk = np.frombuffer(base64.b64decode(client.get("/api/grid", params={"date": H.DAY.isoformat()}).json()["risk"]), "<f4")
    assert risk.max() > 0.9
    status = client.get("/api/sources/status").json()
    assert status["available"] is True and status["sources"]["gfs"]["state"] == "ok"
    rain = client.get("/api/rain", params={"date": H.DAY.isoformat()}).json()
    assert rain["column"] == "irain_acc_1" and rain["n_cells"] == 4
    history = client.get("/api/cells/%d/history" % int(wayanad(alerts_of(cfg))["cell_id"])).json()
    assert history["level"] == [3]


# ---- idempotency ---------------------------------------------------------------------------------------------------

def test_rerun_skips_and_force_recomputes(tmp_path):
    cfg = H.make_cfg(tmp_path)
    calls = []
    sources = H.healthy_sources()
    sources["imd_rt"] = H.imd_source(H.imd_post(calls=calls))
    first = live_run.run_day(H.DAY, cfg, deps=H.make_deps(sources))
    stamp = (run_dir(cfg) / "alerts.parquet").stat().st_mtime_ns
    n_calls = len(calls)
    second = live_run.run_day(H.DAY, cfg, deps=H.make_deps(sources))
    assert second["skipped"] is True and second["started_utc"] == first["started_utc"]
    assert (run_dir(cfg) / "alerts.parquet").stat().st_mtime_ns == stamp and len(calls) == n_calls
    again = live_run.run_day(H.DAY, cfg, force=True, deps=H.make_deps(sources, now=lambda: H.NOW + timedelta(minutes=30)))
    assert "skipped" not in again and again["forced"] is True
    assert again["started_utc"] != first["started_utc"]
    assert (run_dir(cfg) / "alerts.parquet").stat().st_mtime_ns != stamp


def test_a_day_with_a_rain_gap_is_recomputed_on_the_next_attempt(tmp_path):
    cfg = H.make_cfg(tmp_path)
    broken = live_run.run_day(H.DAY, cfg, deps=H.make_deps(H.healthy_sources(early_missing=True)))
    assert broken["retry_recommended"] is True
    fixed = live_run.run_day(H.DAY, cfg, deps=H.make_deps(H.healthy_sources()))
    assert "skipped" not in fixed and fixed["retry_recommended"] is False
    assert live_run.run_day(H.DAY, cfg, deps=H.make_deps(H.healthy_sources()))["skipped"] is True


# ---- every source failure ------------------------------------------------------------------------------------------

def broken(name):
    sources = H.healthy_sources()
    if name == "imerg_late":
        sources.update(H.imerg_sources(late_missing=True))
    elif name == "imerg_early":
        sources.update(H.imerg_sources(early_missing=True))
    elif name == "gfs":
        sources["gfs"] = H.FakeGfs(valid=(False, False, False), first_hours_mm=None)
    elif name == "imd_rt":
        sources["imd_rt"] = H.imd_source(lambda day, timeout: None)
    elif name == "ghcn":
        sources["ghcn"] = H.ghcn_source(lambda params: [])
    return sources


def run_broken(tmp_path, name):
    cfg = H.make_cfg(tmp_path)
    summary = live_run.run_day(H.DAY, cfg, deps=H.make_deps(broken(name)))
    return cfg, summary, (live_run.project_path(cfg["report_dir"]) / f"{H.DAY}.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("name", ["imerg_late", "imerg_early", "gfs", "imd_rt", "ghcn"])
def test_single_source_failure_still_publishes_and_is_named(tmp_path, name):
    cfg, summary, text = run_broken(tmp_path, name)
    assert summary["sources"][name]["state"] in ("failed", "late")
    assert f"`{name}`" in text.split("## Failed / missing sources")[1].split("## Alerts by lead")[0]
    assert (run_dir(cfg) / "alerts.parquet").is_file() and (run_dir(cfg) / "run.json").is_file()


def test_imerg_missing_makes_cells_insufficient_and_applies_the_blind_rule(tmp_path):
    cfg, summary, text = run_broken(tmp_path, "imerg_early")
    alerts = alerts_of(cfg)
    assert (alerts["confidence"] == "Insufficient").all()
    assert alerts["risk"].isna().all()
    assert alerts["confidence_causes"].str.contains(live_run.CAUSE_MODEL_INPUT).all()
    row = wayanad(alerts)
    assert row["blind"] and row["blind_escalated"] and row["level"] >= 1            # IMD shows heavy rain: never a silent Normal
    assert "sources_disagree_heavy_rain" in row["reason_codes"] and live_run.CAUSE_MODEL_INPUT in row["reason_codes"]
    detail = json.loads(row["reasons_json"])
    assert detail["confidence"]["state"] == "Insufficient" and set(detail["risk"].values()) == {None}
    quiet = alerts[alerts["cell_id"] != row["cell_id"]]
    assert (quiet["level"] == 0).all()                                                # nothing shows rain there
    assert summary["retry_recommended"] is True and summary["imerg_gaps"]
    assert "IMERG-based rain missing" in text and "Retry recommended" in text
    assert summary["leads"]["0"]["n_scored"] == 0 and summary["leads"]["0"]["confidence"]["Insufficient"] == 4


def test_imd_realtime_missing_lowers_confidence_to_degraded_only(tmp_path):
    cfg, summary, _ = run_broken(tmp_path, "imd_rt")
    alerts = alerts_of(cfg)
    assert (alerts["confidence"] == "Degraded").all()
    assert alerts["confidence_causes"].str.contains("imd_missing").all()
    assert wayanad(alerts)["level"] == 3 and alerts["risk"].notna().all()
    assert summary["leads"]["0"]["n_scored"] == 4


def test_gfs_missing_drops_the_forecast_leads_but_lead_zero_persists_the_tail(tmp_path):
    cfg, summary, text = run_broken(tmp_path, "gfs")
    for name in LEAD_FILES[1:]:
        assert not (run_dir(cfg) / name).exists()
    assert (run_dir(cfg) / "alerts.parquet").is_file() and (run_dir(cfg) / "risk_D0.parquet").is_file()
    assert all(not summary["leads"][k]["published"] for k in "123")
    assert "Forecast lead D+1 not published" in text and "GFS forecast day D+1 not available" in text
    # the 00-03 UTC hours of IMD day D fall back to persistence (UTC D := UTC D-1): scored, capped at Degraded, no retry
    assert summary["imd_day_inputs"]["D"]["utc_day_0.125"] == "persist_d1" and summary["retry_recommended"] is False
    alerts = alerts_of(cfg)
    assert alerts["risk"].notna().all() and not alerts["confidence"].eq("High").any()
    assert alerts["confidence_causes"].str.contains(live_run.CAUSE_NOWCAST_TAIL).all()
    assert wayanad(alerts)["level"] == 3
    assert "nowcast_tail_persisted" in text.split("## Failed / missing sources")[1].split("## Alerts by lead")[0]
    row = pd.read_parquet(run_dir(cfg) / "features_D0.parquet")
    assert wayanad(row)["irain_acc_1"] == pytest.approx(H.HEAVY_MM)             # 0.875 * 90 + 0.125 * 90


@pytest.mark.parametrize("product", ["gfs_18z_6_9h", "gfs_12z_12_15h"])
def test_a_fallback_gfs_cycle_keeps_lead_zero_at_full_confidence(tmp_path, product):
    cfg = H.make_cfg(tmp_path)
    sources = H.healthy_sources()
    sources["gfs"] = H.FakeGfs(first_hours_product=product)
    summary = live_run.run_day(H.DAY, cfg, deps=H.make_deps(sources))
    assert summary["imd_day_inputs"]["D"]["utc_day_0.125"] == product
    assert summary["imd_day_inputs"]["D"]["product"] == f"early+{product}"
    assert (alerts_of(cfg)["confidence"] == "High").all() and not summary["retry_recommended"]
    assert not alerts_of(cfg)["confidence_causes"].str.contains(live_run.CAUSE_NOWCAST_TAIL).any()


def test_persisted_tail_cap_reapplies_the_blind_rule():
    from alerts_helpers import CONFIG, THRESHOLDS, feature_rows, scores_for
    from aetherguard.alerts.engine import run_alerts
    features = feature_rows([{"src_imd_acc_1": 50.0, "src_chi_acc_1": 52.0, "rain_acc_1": 52.0, "src_imd_acc_3": 55.0,
                              "src_chi_acc_3": 57.0}, {}], n=2, cell_id=[1, 2], start="2024-07-01")
    features["date"] = features["date"].iloc[0]
    table = run_alerts(features, scores_for(features, 1e-7), None, thresholds=THRESHOLDS, config=CONFIG, hysteresis=False)
    assert list(table["confidence"]) == ["High", "High"] and not table["blind"].any()
    capped = live_run.cap_to_degraded(table, CONFIG, live_run.CAUSE_NOWCAST_TAIL)
    assert list(capped["confidence"]) == ["Degraded", "Degraded"]
    assert capped["confidence_causes"].str.contains("nowcast_tail_persisted").all()
    heavy, quiet = capped.iloc[0], capped.iloc[1]
    assert heavy["blind"] and heavy["blind_escalated"] and heavy["raw_level"] == 1 and not quiet["blind"] and quiet["raw_level"] == 0
    assert "nowcast_tail_persisted_heavy_rain" in heavy["reason_codes"]
    detail = json.loads(heavy["reasons_json"])
    assert detail["confidence"]["state"] == "Degraded" and "nowcast_tail_persisted_heavy_rain" in detail["codes"]
    assert detail["raw_level"] == "Watch"


def test_a_partial_forecast_publishes_the_valid_leads_only(tmp_path):
    cfg = H.make_cfg(tmp_path)
    sources = H.healthy_sources()
    sources["gfs"] = H.FakeGfs(valid=(True, False, True))
    summary = live_run.run_day(H.DAY, cfg, deps=H.make_deps(sources))
    assert [summary["leads"][k]["published"] for k in "123"] == [True, False, True]
    assert (run_dir(cfg) / "risk_D1.parquet").is_file() and not (run_dir(cfg) / "risk_D2.parquet").exists()


def test_ghcn_missing_means_no_integ_columns_and_the_bulletin_says_so(tmp_path):
    cfg, summary, text = run_broken(tmp_path, "ghcn")
    features = pd.read_parquet(run_dir(cfg) / "features_D0.parquet")
    assert not [c for c in features.columns if c.startswith("integ_")]
    assert summary["integrity"]["ran"] is False and "GHCN" in summary["integrity"]["reason"]
    assert "Integrity engine did not run" in text and "no `integ_*`" in text
    assert wayanad(alerts_of(cfg))["level"] == 3


# ---- the gauge table of the live set ---------------------------------------------------------------------------------

def observed_on_d_fetch(params: dict) -> list[dict]:
    """The usual late gauges, plus a reading on D for GH000001 only."""
    rows = [r for r in H.ghcn_fetch(params) if r["STATION"] != "GH000001" or r["DATE"] <= (H.DAY - timedelta(days=6)).isoformat()]
    if "GH000001" in params["stations"].split(","):
        rows.append({"DATE": H.DAY.isoformat(), "STATION": "GH000001", "PRCP": "1.0", "PRCP_ATTRIBUTES": ",,"})
    return rows


def sensors_client(cfg, tmp_path):
    app = api.create_app(live_run.project_path(cfg["replay_dir"]), live_dir=live_run.live_root(cfg), dist_dir=tmp_path / "no-dist")
    return TestClient(app)


def test_the_live_set_gets_a_gauge_table_with_every_station_and_its_last_reading(happy):
    cfg, _ = happy
    store = ReplayStore(live_run.project_path(cfg["replay_dir"]))
    name, table = store.sensors(H.DAY.isoformat(), "live")
    assert name == "live" and sorted(table["station"]) == ["GH000001", "GH000002"]
    assert list(table.columns[:3]) == ["date", "station", "name"] and "last_reading" in table.columns
    one = table.set_index("station").loc["GH000001"]
    assert one["name"] == "a" and one["lat"] == 11.5 and one["lon"] == 76.1
    last = (H.DAY - timedelta(days=6)).isoformat()
    assert (table["state"] == "missing").all() and table["trust"].isna().all() and (table["last_reading"] == last).all()
    assert store.manifest["sets"]["live"]["sensor_dates"] == [H.DAY.isoformat()]
    assert store.status() == "ok"


def test_a_station_read_on_d_is_scored_and_the_others_keep_their_last_reading(tmp_path):
    cfg = H.make_cfg(tmp_path)
    sources = {**H.healthy_sources(), "ghcn": H.ghcn_source(observed_on_d_fetch)}
    live_run.run_day(H.DAY, cfg, deps=H.make_deps(sources))
    body = sensors_client(cfg, tmp_path).get("/sensors", params={"date": H.DAY.isoformat()}).json()
    by = {s["station"]: s for s in body["stations"]}
    assert body["reason"] is None and body["n_stations"] == 2 and body["state_counts"] == {"trusted": 1, "missing": 1}
    assert by["GH000001"]["state"] == "trusted" and by["GH000001"]["trust"] == pytest.approx(0.95)
    assert by["GH000001"]["last_reading"] == H.DAY.isoformat()
    assert by["GH000002"]["state"] == "missing" and by["GH000002"]["trust"] is None
    assert by["GH000002"]["last_reading"] == (H.DAY - timedelta(days=6)).isoformat()


def test_stations_without_a_reading_on_d_are_listed_with_their_last_reading_date(happy, tmp_path):
    cfg, _ = happy
    body = sensors_client(cfg, tmp_path).get("/sensors", params={"date": H.DAY.isoformat()}).json()
    assert body["n_stations"] == 2 and body["state_counts"] == {"missing": 2} and body["reason"] is None
    assert {s["last_reading"] for s in body["stations"]} == {(H.DAY - timedelta(days=6)).isoformat()}
    assert all(s["trust"] is None and s["state"] == "missing" for s in body["stations"])


def test_a_station_never_read_in_the_window_has_no_last_reading(tmp_path):
    cfg = H.make_cfg(tmp_path)
    only_first = lambda params: [r for r in H.ghcn_fetch(params) if r["STATION"] == "GH000001"]
    live_run.run_day(H.DAY, cfg, deps=H.make_deps({**H.healthy_sources(), "ghcn": H.ghcn_source(only_first)}))
    body = sensors_client(cfg, tmp_path).get("/sensors", params={"date": H.DAY.isoformat()}).json()
    by = {s["station"]: s for s in body["stations"]}
    assert by["GH000002"]["state"] == "missing" and by["GH000002"]["last_reading"] is None
    assert by["GH000001"]["last_reading"] == (H.DAY - timedelta(days=6)).isoformat()


def test_ghcn_failure_writes_no_gauge_table_and_the_api_says_why(tmp_path):
    cfg, _, _ = run_broken(tmp_path, "ghcn")
    store = ReplayStore(live_run.project_path(cfg["replay_dir"]))
    entry = store.manifest["sets"]["live"]
    assert entry["has_sensors"] is False and entry["sensor_dates"] == []
    assert not list((live_run.project_path(cfg["replay_dir"]) / "live" / "sensors").glob("*.parquet"))
    with pytest.raises(NoSensorsError, match="GHCN-Daily gauges unavailable"):
        store.sensors(H.DAY.isoformat(), "live")
    assert store.status() == "ok"
    response = sensors_client(cfg, tmp_path).get("/sensors", params={"date": H.DAY.isoformat()})
    body = response.json()
    assert response.status_code == 200 and body["set"] == "live" and body["date"] == H.DAY.isoformat()
    assert body["n_stations"] == 0 and body["stations"] == [] and body["state_counts"] == {}
    assert "GHCN-Daily gauges unavailable" in body["reason"]
    assert sensors_client(cfg, tmp_path).get("/sensors", params={"date": "2030-01-01"}).status_code == 404


def test_each_day_keeps_its_own_gauge_table_and_a_later_failure_removes_a_stale_one(tmp_path):
    cfg = H.make_cfg(tmp_path)
    next_day = H.DAY + timedelta(days=1)
    live_run.run_day(H.DAY, cfg, deps=H.make_deps())
    live_run.run_day(next_day, cfg, deps=H.make_deps(sources={**H.healthy_sources(next_day), "ghcn": H.ghcn_source(lambda p: [])}))
    store = ReplayStore(live_run.project_path(cfg["replay_dir"]))
    assert store.manifest["sets"]["live"]["sensor_dates"] == [H.DAY.isoformat()]
    assert store.manifest["sets"]["live"]["has_sensors"] is True
    assert len(store.sensors(H.DAY.isoformat(), "live")[1]) == 2
    with pytest.raises(NoSensorsError):
        store.sensors(next_day.isoformat(), "live")
    assert store.status() == "ok"
    live_run.run_day(H.DAY, cfg, force=True, deps=H.make_deps(sources={**H.healthy_sources(), "ghcn": H.ghcn_source(lambda p: [])}))
    store = ReplayStore(live_run.project_path(cfg["replay_dir"]))
    assert store.manifest["sets"]["live"]["has_sensors"] is False
    with pytest.raises(NoSensorsError):
        store.sensors(H.DAY.isoformat(), "live")
    assert store.status() == "ok"


def test_a_set_published_before_gauge_tables_existed_answers_with_a_reason(tmp_path):
    cfg = H.make_cfg(tmp_path)
    live_run.run_day(H.DAY, cfg, deps=H.make_deps())
    manifest_path = live_run.project_path(cfg["replay_dir"]) / "store_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for key in ("sensor_dates", "sensor_gaps"):
        manifest["sets"]["live"].pop(key, None)
    manifest["sets"]["live"]["has_sensors"] = False
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    body = sensors_client(cfg, tmp_path).get("/sensors", params={"date": H.DAY.isoformat()}).json()
    assert body["stations"] == [] and "no sensor tables" in body["reason"]


def test_an_integrity_failure_is_reported_not_raised(tmp_path):
    cfg = H.make_cfg(tmp_path)

    def explode(gauges, view, imd):
        raise RuntimeError("engine unavailable")
    summary = live_run.run_day(H.DAY, cfg, deps=H.make_deps(integrity=explode))
    assert summary["integrity"]["ran"] is False and "engine unavailable" in summary["integrity"]["reason"]


def test_all_sources_failing_still_publishes_a_bulletin(tmp_path):
    cfg = H.make_cfg(tmp_path)
    sources = {"imerg_late": H.imerg_sources(late_missing=True)["imerg_late"],
               "imerg_early": H.imerg_sources(early_missing=True)["imerg_early"],
               "gfs": H.FakeGfs(valid=(False,) * 3, first_hours_mm=None),
               "imd_rt": H.imd_source(lambda day, timeout: None), "ghcn": H.ghcn_source(lambda params: [])}
    summary = live_run.run_day(H.DAY, cfg, deps=H.make_deps(sources))
    text = (live_run.project_path(cfg["report_dir"]) / f"{H.DAY}.md").read_text(encoding="utf-8")
    assert sorted(summary["failed_sources"]) == sorted(["imerg_late", "imerg_early", "gfs", "imd_rt", "ghcn"])
    for name in summary["failed_sources"]:
        assert f"`{name}`" in text
    alerts = alerts_of(cfg)
    assert (alerts["confidence"] == "Insufficient").all() and alerts["risk"].isna().all()
    assert (alerts["level"] == 0).all()                       # no source shows heavy rain: Normal, but flagged Insufficient
    assert (run_dir(cfg) / "run.json").is_file() and summary["retry_recommended"]


# ---- forecast widening --------------------------------------------------------------------------------------------

def test_forecast_without_widening_factors_is_at_most_degraded(happy):
    cfg, summary = happy
    assert summary["forecast_widening"]["applied"] is False
    for lead in (1, 2, 3):
        table = pd.read_parquet(run_dir(cfg) / f"risk_D{lead}.parquet")
        assert not table["confidence"].eq("High").any() and table["confidence_causes"].str.contains(live_run.CAUSE_UNCALIBRATED).all()
        assert not table["widened"].any()
    assert "forecast_uncertainty_uncalibrated" in (live_run.project_path(cfg["report_dir"]) / f"{H.DAY}.md").read_text(encoding="utf-8")


def test_forecast_widening_factors_are_applied_when_present(tmp_path):
    plain_cfg, wide_cfg = H.make_cfg(tmp_path / "a"), H.make_cfg(tmp_path / "b")
    (tmp_path / "b").mkdir(exist_ok=True)
    H.write_widening(live_run.project_path(wide_cfg["forecast_widening"]), lo=0.5, hi=3.0)
    live_run.run_day(H.DAY, plain_cfg, deps=H.make_deps())
    summary = live_run.run_day(H.DAY, wide_cfg, deps=H.make_deps())
    assert summary["forecast_widening"] == {"applied": True, "path": wide_cfg["forecast_widening"], "reason": None}
    plain = pd.read_parquet(run_dir(plain_cfg) / "risk_D2.parquet").set_index("cell_id")
    wide = pd.read_parquet(run_dir(wide_cfg) / "risk_D2.parquet").set_index("cell_id")
    assert wide["widened"].all()
    # a forecast day has no observation: never High, with the forecast causes instead of the uncalibrated one
    assert (wide["confidence"] == "Degraded").all()
    assert wide["confidence_causes"].str.contains("forecast_day;observed_through_d_").all()
    assert wide["confidence_causes"].str.contains("forecast_widened").all()
    assert not wide["confidence_causes"].str.contains(live_run.CAUSE_UNCALIBRATED).any()
    assert (wide["risk"] == plain["risk"]).all()
    assert (wide["risk_lo"] <= plain["risk_lo"] + 1e-12).all() and (wide["risk_hi"] >= plain["risk_hi"] - 1e-12).all()
    assert (wide["risk_hi"] <= 1.0).all()               # the saturated test model is at 1 already: widening cannot pass a probability of 1
    lead0 = pd.read_parquet(run_dir(wide_cfg) / "risk_D0.parquet")
    assert not lead0["widened"].any()


def test_an_unusable_widening_file_is_treated_as_absent(tmp_path):
    cfg = H.make_cfg(tmp_path)
    live_run.project_path(cfg["forecast_widening"]).write_text(json.dumps({"leads": {"1": {"lo": 0.5, "hi": -1}}}), encoding="utf-8")
    summary = live_run.run_day(H.DAY, cfg, deps=H.make_deps())
    assert summary["forecast_widening"]["applied"] is False and "positive finite" in summary["forecast_widening"]["reason"]


# ---- hysteresis ----------------------------------------------------------------------------------------------------

def test_hysteresis_continues_from_the_previous_live_day(tmp_path):
    cfg = H.make_cfg(tmp_path)
    previous = H.DAY - timedelta(days=1)
    heavy = H.healthy_sources(previous)
    heavy["imd_rt"] = H.imd_source(H.imd_post(heavy_mm=H.LIGHT_MM))       # IMD files are cached in the run folders
    live_run.run_day(previous, cfg, deps=H.make_deps(heavy, now=lambda: H.NOW - timedelta(days=1)))
    assert wayanad(alerts_of(cfg, previous))["level"] == 3
    # today the rain has stopped: the raw level is Normal, but the state machine needs exit_days quiet days to step down
    calm = H.healthy_sources(heavy_days=[])
    calm["gfs"] = H.FakeGfs(heavy_leads=())
    calm["imd_rt"] = H.imd_source(H.imd_post(heavy_mm=H.LIGHT_MM))
    summary = live_run.run_day(H.DAY, cfg, deps=H.make_deps(calm))
    row = wayanad(alerts_of(cfg))
    assert row["raw_level"] == 0 and row["level"] == 3                       # one quiet day is not exit_days (2) yet
    assert "hysteresis_hold" in row["reason_codes"] and json.loads(row["reasons_json"])["level"] == "Emergency"
    assert summary["hysteresis"] == {"previous_days_used": 1, "first_previous": previous.isoformat()}
    # the same day computed without the previous day's state starts from the raw level
    fresh_cfg = H.make_cfg(tmp_path / "fresh")
    live_run.run_day(H.DAY, fresh_cfg, deps=H.make_deps(calm))
    assert wayanad(alerts_of(fresh_cfg))["level"] == 0


def test_hysteresis_history_ignores_later_days_and_stops_at_a_gap(tmp_path):
    cfg = H.make_cfg(tmp_path)
    live_root = live_run.live_root(cfg)
    for offset, level in ((1, 3), (3, 3), (-1, 3)):
        folder = live_root / (H.DAY - timedelta(days=offset)).isoformat()
        folder.mkdir(parents=True)
        pd.DataFrame({"cell_id": [1], "date": pd.Timestamp(H.DAY - timedelta(days=offset)), "raw_level": np.int8(level),
                      "risk": 0.9}).to_parquet(folder / "alerts.parquet", index=False)
    history = live_run.previous_state(live_root, H.DAY, 30)
    assert list(history["date"]) == [pd.Timestamp(H.DAY - timedelta(days=1))]        # day D-2 is missing: the chain ends


def test_a_cell_without_a_score_keeps_its_level(tmp_path):
    cfg = H.make_cfg(tmp_path)
    previous = H.DAY - timedelta(days=1)
    live_run.run_day(previous, cfg, deps=H.make_deps(H.healthy_sources(previous), now=lambda: H.NOW - timedelta(days=1)))
    live_run.run_day(H.DAY, cfg, deps=H.make_deps(H.healthy_sources(early_missing=True)))
    row = wayanad(alerts_of(cfg))
    assert row["level"] == 3 and np.isnan(row["risk"]) and "hysteresis_hold" in row["reason_codes"]


# ---- backtest, timezone, CLI --------------------------------------------------------------------------------------

def test_backtest_ignores_inputs_issued_after_the_cutoff(tmp_path):
    cfg = H.make_cfg(tmp_path)
    # a planted Late value for UTC D-1 exists in the store (it was published at 14:30 UTC D, after the 11:00 IST cut-off)
    plant = {H.DAY - timedelta(days=1): 999.0}
    sources = H.healthy_sources()
    sources["imerg_late"].store.days.add(H.DAY - timedelta(days=1))
    sources["imerg_late"].store.overrides.update(plant)
    summary = live_run.run_day(H.DAY, cfg, backtest=True, deps=H.make_deps(sources))
    features = pd.read_parquet(run_dir(cfg) / "features_D0.parquet")
    assert features["irain_acc_1"].max() < 200 and summary["backtest"] is True
    freshness = json.loads((run_dir(cfg) / "freshness.json").read_text(encoding="utf-8"))
    assert freshness["backtest"] is True and freshness["data_cutoff_utc"] == "2026-08-12T05:30:00+00:00"
    assert summary["imd_day_inputs"]["D"]["utc_day_0.875"] == "early"
    # a Late run past the cut-off stays unused in a live run as well: the construction does not depend on the clock
    assert live_run.run_day(H.DAY, cfg, force=True, deps=H.make_deps(sources))["imd_day_inputs"]["D"]["utc_day_0.875"] == "early"


def test_backtest_rejects_a_source_issued_after_the_cutoff(tmp_path):
    cfg = H.make_cfg(tmp_path)
    sources = H.healthy_sources()

    class LateImd:
        name = "imd_rt"

        def fetch(self, ctx: FetchContext) -> SourceStatus:
            issued = ctx.cutoff + timedelta(minutes=1)
            return SourceStatus("imd_rt", True, issued - timedelta(hours=1), issued, 1.0, None)

        def load(self, ctx):
            raise AssertionError("a rejected source must not be loaded")
    sources["imd_rt"] = LateImd()
    summary = live_run.run_day(H.DAY, cfg, backtest=True, deps=H.make_deps(sources))
    assert summary["sources"]["imd_rt"]["state"] == "failed" and "after the backtest cut-off" in summary["sources"]["imd_rt"]["error"]


def test_the_run_date_is_the_ist_date_and_the_imd_day_boundary_is_0830_ist(tmp_path):
    from datetime import datetime, timezone
    from aetherguard.live.sources import cutoff_utc, imd_day_end, resolve_day, utc_day_end
    cfg = H.make_cfg(tmp_path)
    late_evening_utc = datetime(2026, 10, 14, 20, 0, tzinfo=timezone.utc)          # 01:30 IST on the 15th
    assert resolve_day("today", cfg, late_evening_utc).isoformat() == "2026-10-15"
    assert resolve_day("2026-01-02", cfg).isoformat() == "2026-01-02"
    assert imd_day_end(H.DAY) == datetime(2026, 8, 12, 3, 0, tzinfo=timezone.utc)      # 08:30 IST of D
    assert utc_day_end(H.DAY) == datetime(2026, 8, 13, 0, 0, tzinfo=timezone.utc)
    assert cutoff_utc(H.DAY, cfg) == H.NOW                                             # 11:00 IST


def write_cli_config(tmp_path, **hazard) -> str:
    cfg = H.make_cfg(tmp_path)
    hazard_path = tmp_path / "hazard_test.yaml"
    hazard_path.write_text(yaml.safe_dump({"model_dir": "model_unfrozen_test", "cv_report_stem": "none", **hazard}), encoding="utf-8")
    cfg["model_config"] = str(hazard_path)
    path = tmp_path / "live_run_test.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return str(path)


def test_cli_refuses_a_model_that_is_not_frozen(tmp_path, isolated_data_root, capsys):
    config = write_cli_config(tmp_path)
    assert live_run.main(["run", "--date", "2026-08-12", "--config", config]) == 1
    assert "v3-live model not frozen yet" in capsys.readouterr().err
    assert not (tmp_path / "live").exists()
    (isolated_data_root / "processed" / "hazard" / "model_unfrozen_test").mkdir(parents=True)
    assert live_run.main(["run", "--date", "2026-08-12", "--config", config]) == 1
    assert "v3-live model not frozen yet" in capsys.readouterr().err


def test_cli_reports_a_model_that_changed_after_the_freeze(tmp_path, isolated_data_root, capsys):
    config = write_cli_config(tmp_path)
    folder = isolated_data_root / "processed" / "hazard" / "model_unfrozen_test"
    folder.mkdir(parents=True)
    (folder / live_run.FROZEN_NAME).write_text(json.dumps({"sha256": {}, "external_files": []}), encoding="utf-8")
    assert live_run.main(["run", "--date", "2026-08-12", "--config", config]) == 1
    assert "does not match its freeze record" in capsys.readouterr().err


def test_cli_exit_codes_and_idempotent_message(tmp_path, monkeypatch, capsys):
    cfg = H.make_cfg(tmp_path)
    path = tmp_path / "live_run_test.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    sources = {"value": H.healthy_sources()}
    monkeypatch.setattr(live_run, "load_live_model", lambda cfg: H.tiny_model())
    monkeypatch.setattr(live_run, "load_cells", lambda cfg: H.tiny_cells())
    original = live_run.run_day

    def with_fakes(day, cfg, force=False, backtest=False, deps=None):
        return original(day, cfg, force, backtest, H.make_deps(sources["value"]))
    monkeypatch.setattr(live_run, "run_day", with_fakes)
    args = ["run", "--date", H.DAY.isoformat(), "--config", str(path)]
    assert live_run.main(args) == 0
    assert "published; leads 0,1,2,3; failed sources: none" in capsys.readouterr().out
    assert live_run.main(args) == 0
    assert "skipped (already complete)" in capsys.readouterr().out
    sources["value"] = H.healthy_sources(early_missing=True)
    assert live_run.main([*args, "--force"]) == live_run.EXIT_RETRY


def test_install_script_dry_run_prints_the_task_definition():
    import shutil
    import subprocess
    from pathlib import Path
    shell = shutil.which("powershell") or shutil.which("pwsh")
    script = Path(__file__).resolve().parents[1] / "scripts" / "install_daily_task.ps1"
    if shell is None:
        pytest.skip("PowerShell is not available")
    out = subprocess.run([shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-DryRun"],
                         capture_output=True, text=True, timeout=60, check=True).stdout
    for needle in ("AetherGuard daily", "11:00", "-m aetherguard.live run --date today", "StartWhenAvailable", "-WindowStyle Hidden",
                   "RestartCount", "RestartInterval", "logs",
                   # a start on wake or logon waits for the network (Wi-Fi reconnects after the trigger fires)
                   "Network wait:", "cmr.earthdata.nasa.gov", "20 minutes"):
        assert needle in out, needle


def test_fitted_early_mode_labels_the_product_and_matches_identity_for_an_identity_curve(tmp_path):
    cfg = H.make_cfg(tmp_path / "fitted")
    fitted = live_run.run_day(H.DAY, cfg, deps=H.make_deps(H.healthy_sources(mapping=H.FITTED_MAP)))
    assert fitted["imd_day_inputs"]["D"]["product"] == "early_mapped+gfs_00z_0_3h"
    assert fitted["imd_day_inputs"]["D-1"]["product"] == "late+early_mapped"
    plain_cfg = H.make_cfg(tmp_path / "plain")
    live_run.run_day(H.DAY, plain_cfg, deps=H.make_deps())
    pd.testing.assert_series_equal(alerts_of(cfg)["risk"], alerts_of(plain_cfg)["risk"])


def test_the_bulletin_names_a_fallback_gfs_cycle(tmp_path):
    cfg = H.make_cfg(tmp_path)
    sources = H.healthy_sources()
    sources["gfs"] = H.FakeGfs(first_hours_product="gfs_12z_12_15h")
    summary = live_run.run_day(H.DAY, cfg, deps=H.make_deps(sources))
    assert summary["nowcast_tail"] == {"product": "gfs_12z_12_15h", "persisted": False}
    text = (live_run.project_path(cfg["report_dir"]) / f"{H.DAY}.md").read_text(encoding="utf-8")
    assert "came from `gfs_12z_12_15h`" in text


# ---- thresholds by region ------------------------------------------------------------------------------------------

REGION_CARD = {"alert_levels": {
    "watch": {"raw": 1.0, "risk": 0.2, "risk_by_region": {"himalaya": 0.4, "western_ghats": 0.2}},
    "warning": {"raw": 2.0, "risk": 0.5, "risk_by_region": {"himalaya": 0.6, "western_ghats": 0.5}},
    "emergency": {"raw": 3.0, "risk": 0.8, "risk_by_region": {"himalaya": 0.9, "western_ghats": 0.8}}}}


def flat_risk_model(risk=0.3, region_calibrated=True):
    """The tiny model scoring every cell at a constant calibrated risk, with a v3-style card."""
    from aetherguard.hazard.calibration import RegionCalibrator
    model = H.tiny_model()
    model.card = REGION_CARD
    if region_calibrated:
        model.region_calibrator = RegionCalibrator({}, model.calibrator)
    model.score = lambda frame: pd.DataFrame({"risk": risk, "risk_lo": risk, "risk_hi": risk, "risk_per_100k": 1e5 * risk},
                                             index=frame.index)
    return model


def test_a_region_calibrated_model_is_compared_with_the_thresholds_of_each_region():
    regions = ["himalaya", "western_ghats", "himalaya"]
    thresholds = live_run.card_thresholds(flat_risk_model(), regions)
    assert isinstance(thresholds, live_run.lv.RegionThresholds)
    assert thresholds.of("himalaya").as_array().tolist() == [0.4, 0.6, 0.9]
    assert thresholds.of("western_ghats").as_array().tolist() == [0.2, 0.5, 0.8]
    assert thresholds.pooled.as_array().tolist() == [0.2, 0.5, 0.8] and thresholds.pooled.source == "card.alert_levels"


def test_a_pooled_model_keeps_the_pooled_thresholds_whatever_the_card_says():
    thresholds = live_run.card_thresholds(flat_risk_model(region_calibrated=False), ["himalaya", "western_ghats"])
    assert isinstance(thresholds, live_run.lv.Thresholds) and thresholds.as_array().tolist() == [0.2, 0.5, 0.8]


def test_the_run_levels_cells_by_the_thresholds_of_their_region_in_every_lead(tmp_path):
    cfg = H.make_cfg(tmp_path)
    summary = live_run.run_day(H.DAY, cfg, deps=H.make_deps(model=flat_risk_model(), thresholds=None))
    cells = H.tiny_cells().set_index("cell_id")["region"]
    for name in ("alerts.parquet", "risk_D1.parquet", "risk_D3.parquet"):
        table = pd.read_parquet(run_dir(cfg) / name)
        levels = dict(zip(table["cell_id"], table["level"]))
        # risk 0.3: Watch in the ghats (Watch 0.2), Normal in the himalaya (Watch 0.4)
        assert {cells[c]: l for c, l in levels.items()} == {"himalaya": 0, "western_ghats": 1}, name
    pooled = live_run.run_day(H.DAY, H.make_cfg(tmp_path / "pooled"),
                              deps=H.make_deps(model=flat_risk_model(region_calibrated=False), thresholds=None))
    assert pooled["leads"]["0"]["levels"]["Watch"] == 4 and summary["leads"]["0"]["levels"]["Watch"] == 2


def test_run_json_records_the_pooled_thresholds_and_those_of_each_region(tmp_path):
    cfg = H.make_cfg(tmp_path)
    summary = live_run.run_day(H.DAY, cfg, deps=H.make_deps(model=flat_risk_model(), thresholds=None))
    model = json.loads((run_dir(cfg) / "run.json").read_text(encoding="utf-8"))["model"]
    assert model == summary["model"] and model["calibration"] == "per_region"
    assert model["thresholds"] == {"watch": 0.2, "warning": 0.5, "emergency": 0.8, "source": "card.alert_levels"}
    assert model["thresholds_by_region"]["himalaya"]["watch"] == 0.4
    assert model["thresholds_by_region"]["western_ghats"]["emergency"] == 0.8
    text = (live_run.project_path(cfg["report_dir"]) / f"{H.DAY}.md").read_text(encoding="utf-8")
    assert "By region: himalaya Watch 0.4, Warning 0.6, Emergency 0.9; western_ghats Watch 0.2" in text
    plain = live_run.run_day(H.DAY, H.make_cfg(tmp_path / "plain"), deps=H.make_deps())
    assert plain["model"]["thresholds"]["watch"] == 0.2 and plain["model"]["thresholds_by_region"] is None


def test_hysteresis_history_uses_each_cells_region_thresholds(tmp_path):
    cfg = H.make_cfg(tmp_path)
    previous = H.DAY - timedelta(days=1)
    kathmandu = int(H.tiny_cells().query("region == 'himalaya'")["cell_id"].iloc[0])
    folder = live_run.live_root(cfg) / previous.isoformat()
    folder.mkdir(parents=True)
    # yesterday this himalaya cell was at Warning (0.6); today's risk 0.3 is Watch under the pooled thresholds but below
    # the himalaya Watch (0.4); it is also below 0.8 x 0.6 = 0.48, so only the first of the two quiet days has passed
    pd.DataFrame({"cell_id": [kathmandu], "date": pd.Timestamp(previous), "raw_level": np.int8(2), "risk": 0.7}
                 ).to_parquet(folder / "alerts.parquet", index=False)
    live_run.run_day(H.DAY, cfg, deps=H.make_deps(model=flat_risk_model(), thresholds=None))
    row = alerts_of(cfg).set_index("cell_id").loc[kathmandu]
    assert row["raw_level"] == 0 and row["level"] == 2 and "hysteresis_hold" in row["reason_codes"]


# ---- the uncertain_high bound ---------------------------------------------------------------------------------------

def test_uncertain_high_uses_the_configured_percentile_in_lead_zero_and_the_forecast_leads(tmp_path):
    from dataclasses import replace
    asked = []

    def model_with_bound():
        model = flat_risk_model(risk=0.1)
        model.ensemble_percentile = lambda frame, percentile: asked.append(percentile) or np.full(len(frame), 0.25)
        return model
    cells = H.tiny_cells().set_index("cell_id")["region"]

    def watch_cells(cfg, name):
        table = pd.read_parquet(run_dir(cfg) / name)
        return {cells[c] for c, level in zip(table["cell_id"], table["level"]) if level >= 1}
    default = H.make_cfg(tmp_path / "default")
    live_run.run_day(H.DAY, default, deps=H.make_deps(model=model_with_bound(), thresholds=None))
    assert asked == [] and watch_cells(default, "alerts.parquet") == set()          # risk_hi 0.1 is below every Watch threshold
    narrower = H.make_cfg(tmp_path / "narrower")
    live_run.run_day(H.DAY, narrower, deps=H.make_deps(model=model_with_bound(), thresholds=None,
                                                       alert_config=replace(H.ALERT_CONFIG, uncertain_percentile=75.0)))
    assert set(asked) == {75.0}
    for name in ("alerts.parquet", "risk_D1.parquet"):
        assert watch_cells(narrower, name) == {"western_ghats"}, name              # 0.25 reaches the ghats Watch (0.2), not 0.4
    alerts = alerts_of(narrower)
    assert alerts["uncertain_high"].sum() == 2 and "risk_p75" not in alerts.columns
    off = H.make_cfg(tmp_path / "off")
    live_run.run_day(H.DAY, off, deps=H.make_deps(model=model_with_bound(), thresholds=None,
                                                  alert_config=replace(H.ALERT_CONFIG, uncertain_percentile=None)))
    assert watch_cells(off, "alerts.parquet") == set() and not alerts_of(off)["uncertain_high"].any()


# ---- which cells are scored --------------------------------------------------------------------------------------

def rain_frame(**values):
    base = {name: 1.0 for name in live_run.RAIN_INPUTS}
    base.update(irain_acc_3=10.0, stat_slope_mean=np.nan)
    base.update(values)
    return pd.DataFrame([base])


def test_a_cell_is_scored_only_when_every_rain_input_of_the_model_is_known():
    columns = ["irain_acc_1", "irain_acc_3", "irain_acc_30", "irain_share1_3", "iapi_90", "inbr_max_acc_1", "stat_slope_mean"]
    assert live_run.scorable_mask(rain_frame(), columns).all()                       # a NaN terrain input does not matter
    for name in ("irain_acc_30", "iapi_90", "inbr_max_acc_1", "irain_acc_1"):
        assert not live_run.scorable_mask(rain_frame(**{name: np.nan}), columns).any(), name
    assert live_run.scorable_mask(rain_frame(irain_acc_30=np.nan), ["irain_acc_1", "iapi_90"]).all()    # not a model input


def test_the_one_day_share_may_be_nan_only_when_three_day_rain_is_under_1_mm():
    columns = ["irain_acc_3", "irain_share1_3"]
    assert live_run.scorable_mask(rain_frame(irain_acc_3=0.4, irain_share1_3=np.nan), columns).all()
    assert not live_run.scorable_mask(rain_frame(irain_acc_3=12.0, irain_share1_3=np.nan), columns).any()
    assert not live_run.scorable_mask(rain_frame(irain_acc_3=np.nan, irain_share1_3=np.nan), columns).any()


def test_a_forecast_lead_is_scored_only_for_cells_scored_on_day_d():
    frame = pd.concat([rain_frame(), rain_frame(irain_acc_30=np.nan), rain_frame()], ignore_index=True)
    columns = ["irain_acc_3", "irain_acc_30"]
    base = np.array([True, True, False])
    assert list(live_run.lead_scorable(frame, columns, base)) == [True, False, False]


def test_forecast_leads_on_all_forecast_three_day_rain_are_not_scored_when_observed_days_are_missing(tmp_path):
    """The first live run: Early UTC D-1 was not published, so D, D+1 and D+2 had no score, but D+3 (a 3-day window made of
    forecast days only) was scored for every cell by a model that was handed NaN longer windows."""
    cfg = H.make_cfg(tmp_path)
    summary = live_run.run_day(H.DAY, cfg, deps=H.make_deps(H.healthy_sources(early_missing=True)))
    for lead in "0123":
        assert summary["leads"][lead]["n_scored"] == 0, lead
        if lead != "0":                                  # on day D the blind rule may still raise a cell with heavy IMD rain
            assert summary["leads"][lead]["levels"]["Normal"] == 4
    table = pd.read_parquet(run_dir(cfg) / "risk_D3.parquet")
    assert table["risk"].isna().all() and (table["confidence"] == "Insufficient").all() and (table["level"] == 0).all()
    assert table["confidence_causes"].str.contains(live_run.CAUSE_FORECAST_MISSING).all()
    # the 3-day window of lead 3 is made of forecast days only, so it is finite; the longer windows are not
    sources = H.healthy_sources(early_missing=True)
    ctx = S.make_context(H.DAY, cfg, H.NOW, False, tmp_path / "raw")
    view = S.LiveRainView(H.DAY, sources["imerg_late"], None, ctx, None)
    cells = H.tiny_cells().assign(date=pd.Timestamp(H.DAY))
    features = forecast_features.lead_features(cells, H.DAY, 3, view, H.FakeGfs().forecast.days, H.tiny_clim(cells))
    assert features["irain_acc_3"].notna().all() and features["irain_acc_7"].isna().all()
    assert not live_run.lead_scorable(features, H.MODEL_COLUMNS, np.ones(len(cells), dtype=bool)).any()


def test_candidate_cells_are_the_trained_universe_and_the_rest_is_not_written(tmp_path):
    cfg = H.make_cfg(tmp_path)
    H.write_cell_tables(tmp_path, cfg)
    cells, info = live_run.load_candidate_cells(cfg)
    assert sorted(cells["cell_id"]) == sorted(H.tiny_cells()["cell_id"])
    assert info == {"assessed": 4, "in_scope": 6, "not_assessed": 2, "slope_floor_deg": H.SLOPE_FLOOR,
                    "definition": live_run.CELL_SET_DEFINITION}
    deps = H.make_deps(cells=None)
    summary = live_run.run_day(H.DAY, cfg, deps=deps)
    assert summary["cell_set"] == info
    for name in LEAD_FILES:
        assert sorted(pd.read_parquet(run_dir(cfg) / name)["cell_id"]) == sorted(cells["cell_id"])
    assert sorted(alerts_of(cfg)["cell_id"]) == sorted(cells["cell_id"])
    assert summary["leads"]["0"]["n_cells"] == 4
    text = (live_run.project_path(cfg["report_dir"]) / f"{H.DAY}.md").read_text(encoding="utf-8")
    assert "Cells assessed: 4 of 6" in text and "not assessed: 2" in text and "5" in text
    app = api.create_app(live_run.project_path(cfg["replay_dir"]), live_dir=live_run.live_root(cfg), dist_dir=tmp_path / "no-dist")
    body = TestClient(app).get("/api/grid", params={"date": H.DAY.isoformat(), "lead": 1}).json()
    assert body["n"] == 4


def test_the_runner_and_the_backtest_score_the_same_candidate_cells(tmp_path, monkeypatch):
    from aetherguard.live import backtest
    cfg = H.make_cfg(tmp_path)
    H.write_cell_tables(tmp_path, cfg)
    features = tmp_path / "data" / "processed" / "features"
    (features / "samples").mkdir(parents=True)
    (tmp_path / "data" / "processed" / "terrain").mkdir(parents=True)
    import shutil
    shutil.copy(live_run.project_path(cfg["samples_manifest"]), features / "samples" / "samples_manifest.json")
    shutil.copy(live_run.project_path(cfg["region_table"]), features / "cell_regions.parquet")
    shutil.copy(live_run.project_path(cfg["terrain_table"]), tmp_path / "data" / "processed" / "terrain" / "cell_terrain.parquet")
    monkeypatch.setenv("AETHERGUARD_DATA_DIR", str(tmp_path / "data"))
    cells, _ = live_run.load_candidate_cells(cfg)
    assert sorted(backtest.universe_cell_ids()) == sorted(cells["cell_id"])


# ---- per-lead detail ----------------------------------------------------------------------------------------------

def lead_rows(cfg, lead):
    """(risk table, feature table) of one lead, indexed by cell id."""
    return (pd.read_parquet(run_dir(cfg) / f"risk_D{lead}.parquet").set_index("cell_id"),
            pd.read_parquet(run_dir(cfg) / f"features_D{lead}.parquet").set_index("cell_id"))


def shap_of(row):
    return json.loads(row["shap_json"])


def test_forecast_leads_carry_shap_reasons_and_their_own_features(happy):
    cfg, _ = happy
    for lead in (1, 2, 3):
        risk, features = lead_rows(cfg, lead)
        assert {"shap_json", "reasons_json"} <= set(risk.columns)
        assert set(H.MODEL_COLUMNS) <= set(features.columns)
        assert (features["date"] == pd.Timestamp(H.DAY + timedelta(days=lead))).all()
        assert [c for c in features.columns if c.startswith("gfs_rain_d")] == [f"gfs_rain_d{k}" for k in range(1, lead + 1)]
        assert list(features.index) == list(risk.index)


def test_forecast_shap_comes_from_the_features_of_that_lead(happy):
    cfg, _ = happy
    row = int(H.tiny_cells().query("region == 'western_ghats'")["cell_id"].iloc[0])
    d0 = shap_of(alerts_of(cfg).set_index("cell_id").loc[row])
    for lead in (1, 3):
        risk, features = lead_rows(cfg, lead)
        shap = shap_of(risk.loc[row])
        used = {f["feature"]: f["value"] for f in shap}
        assert shap and all(used[name] == pytest.approx(features.loc[row, name]) for name in used)
        assert len(shap) <= 5
    d1 = {f["feature"]: f["value"] for f in shap_of(lead_rows(cfg, 1)[0].loc[row])}
    assert d1["irain_acc_1"] != {f["feature"]: f["value"] for f in d0}["irain_acc_1"]


def test_perturbing_the_gfs_rain_of_d3_changes_the_d3_shap_and_leaves_d0_alone(tmp_path):
    calm_cfg, wet_cfg = H.make_cfg(tmp_path / "calm"), H.make_cfg(tmp_path / "wet")
    for folder in ("calm", "wet"):
        (tmp_path / folder).mkdir(exist_ok=True)
    row = int(H.tiny_cells().query("region == 'western_ghats'")["cell_id"].iloc[0])
    sources_calm, sources_wet = H.healthy_sources(), H.healthy_sources()
    sources_calm["gfs"], sources_wet["gfs"] = H.FakeGfs(heavy_leads=()), H.FakeGfs(heavy_leads=(3,))
    live_run.run_day(H.DAY, calm_cfg, deps=H.make_deps(sources_calm))
    live_run.run_day(H.DAY, wet_cfg, deps=H.make_deps(sources_wet))
    calm3, calm_features = lead_rows(calm_cfg, 3)
    wet3, wet_features = lead_rows(wet_cfg, 3)
    assert wet_features.loc[row, "gfs_rain_d3"] == pytest.approx(H.HEAVY_MM) and calm_features.loc[row, "gfs_rain_d3"] == pytest.approx(4.0)
    assert shap_of(wet3.loc[row]) != shap_of(calm3.loc[row])
    assert json.loads(wet3.loc[row, "reasons_json"])["shap"] == shap_of(wet3.loc[row])
    assert alerts_of(wet_cfg).set_index("cell_id").loc[row, "shap_json"] == alerts_of(calm_cfg).set_index("cell_id").loc[row, "shap_json"]
    for lead in (1, 2):                                           # the earlier leads never see the day-3 forecast
        assert lead_rows(wet_cfg, lead)[0].loc[row, "shap_json"] == lead_rows(calm_cfg, lead)[0].loc[row, "shap_json"]


def test_forecast_reasons_match_the_lead_table_and_leave_unknown_evidence_empty(happy):
    cfg, _ = happy
    risk, _ = lead_rows(cfg, 2)
    for cell, row in risk.iterrows():
        reasons = json.loads(row["reasons_json"])
        assert reasons["level"] == row["level_name"] and reasons["confidence"]["state"] == row["confidence"]
        assert reasons["risk"]["point"] == (None if np.isnan(row["risk"]) else pytest.approx(row["risk"]))
        assert all(value is None for key, value in reasons["sources"].items() if key.endswith(("_1", "_3")))
        assert reasons["sensor_trust"]["n_stations"] == 0


def test_a_lead_that_is_not_published_leaves_no_detail_files(tmp_path):
    cfg = H.make_cfg(tmp_path)
    live_run.run_day(H.DAY, cfg, deps=H.make_deps())
    sources = H.healthy_sources()
    sources["gfs"] = H.FakeGfs(valid=(True, False, True))
    live_run.run_day(H.DAY, cfg, force=True, deps=H.make_deps(sources))
    assert (run_dir(cfg) / "features_D1.parquet").is_file() and not (run_dir(cfg) / "features_D2.parquet").exists()
    assert (run_dir(cfg) / "features_D3.parquet").is_file()
