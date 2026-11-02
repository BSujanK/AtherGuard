"""Dashboard API (/api) on fixture replay stores, fake live run directories and a fake terrain table (no network)."""
import asyncio
import base64
import json
import re
import threading
import time
import urllib.request
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import uvicorn
import yaml
from fastapi.testclient import TestClient

from aetherguard.alerts import store as alert_store
from aetherguard.grid import CELL_DEG, latlon_to_cell
from aetherguard.serve import api, dash_api
from aetherguard.serve import places as pl
from aetherguard.serve import terrain_grid as tg
from alerts_store_helpers import build_store

SETS = {"case_a": {"n_cells": 4, "n_days": 6, "positive_cells": (1,)},
        "case_b": {"n_cells": 2, "n_days": 4, "start": "2024-07-04"}}
NO_DIST = "no-dist"


def decode(text, dtype):
    return np.frombuffer(base64.b64decode(text), dtype=dtype)


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    root = tmp_path_factory.mktemp("dash")
    _, store = build_store(root, SETS)
    return root, store


def make_client(store, tmp_path, **kwargs):
    """A client on `store` with the live runs, terrain table, cache and base map under `tmp_path` and no built dashboard."""
    app = api.create_app(store, live_dir=tmp_path / "live", dist_dir=tmp_path / NO_DIST, **kwargs)
    app.state.dash = replace(app.state.dash, features_dir=Path(store).parent / "features",
                             terrain_source=tmp_path / "terrain.parquet", terrain_cache=tmp_path / "serve" / "terrain_grid.npz",
                             basemap_dir=tmp_path / "basemap", places_dir=tmp_path / "places",
                             live_run_config=tmp_path / "live_run.yaml")
    return TestClient(app)


@pytest.fixture
def client(built, tmp_path):
    return make_client(built[1], tmp_path)


def write_run(live_dir, day, leads=(0, 1), freshness=None, rain_column="rain_acc_1", confidence="High", extra=None):
    """A live run directory: alerts.parquet (lead 0), risk_D<k>.parquet, features_D0.parquet and freshness.json.
    `extra` maps additional alerts.parquet column names to their three values."""
    folder = live_dir / day
    folder.mkdir(parents=True, exist_ok=True)
    for lead in leads:
        frame = pd.DataFrame({"cell_id": [20_000_005, 10_000_003, 30_000_001], "date": pd.Timestamp(day),
                              "risk": [0.2 + lead, 0.1, 0.3], "risk_hi": [0.4, 0.2, 0.5], "level": np.int8([2, 0, 3]),
                              "confidence": [confidence, "Degraded", "Insufficient"]})
        if lead == 0:
            frame = frame.assign(**(extra or {}))
        frame.to_parquet(folder / ("alerts.parquet" if lead == 0 else f"risk_D{lead}.parquet"), index=False)
    pd.DataFrame({"cell_id": [1, 2], "date": pd.Timestamp(day), "lat": [12.01, 12.02], "lon": [76.01, 76.02],
                  rain_column: [10.0, 30.0]}).to_parquet(folder / "features_D0.parquet", index=False)
    if freshness is not None:
        (folder / "freshness.json").write_text(json.dumps(freshness))
    return folder


# ---- mode ----------------------------------------------------------------------------------------------------------

def mode_of(client):
    """/api/mode without its time-dependent `next_run`, the `thresholds`, the `leads` and the scored status (each covered by
    its own tests)."""
    body = client.get("/api/mode").json()
    for key in ("next_run", "thresholds", "thresholds_by_region", "leads", "scored_share", "last_scored_date"):
        body.pop(key)
    return body


def test_mode_without_any_data_is_none(tmp_path):
    body = mode_of(make_client(tmp_path / "nothing", tmp_path))
    assert body == {"mode": "none", "set": None, "latest_date": None, "dates": []}


def test_mode_is_replay_of_the_newest_set_without_a_live_run(client):
    body = mode_of(client)
    assert body["mode"] == "replay" and body["set"] == "case_b" and body["latest_date"] == "2024-07-07"
    assert body["dates"] == ["2024-07-04", "2024-07-05", "2024-07-06", "2024-07-07"]


def test_mode_is_live_when_a_run_directory_exists(built, tmp_path):
    client = make_client(built[1], tmp_path)
    write_run(tmp_path / "live", "2024-07-09")
    write_run(tmp_path / "live", "2024-07-10")
    (tmp_path / "live" / "not-a-date").mkdir()
    (tmp_path / "live" / "2024-07-11").mkdir()                         # a run still fetching: no alerts.parquet yet
    assert mode_of(client) == {"mode": "live", "set": "live", "latest_date": "2024-07-10",
                               "dates": ["2024-07-09", "2024-07-10"]}


def test_mode_is_live_when_the_store_holds_a_set_named_live(tmp_path):
    _, store = build_store(tmp_path, {"case_a": SETS["case_a"], "live": {"n_cells": 2, "n_days": 2, "start": "2024-08-01"}})
    body = mode_of(make_client(store, tmp_path))
    assert body == {"mode": "live", "set": "live", "latest_date": "2024-08-02", "dates": ["2024-08-01", "2024-08-02"]}


def test_mode_follows_a_rebuilt_store_without_a_restart(tmp_path):
    _, store = build_store(tmp_path, {"case_a": SETS["case_a"]})
    client = make_client(store, tmp_path)
    assert client.get("/api/mode").json()["latest_date"] == "2024-07-06"
    manifest = json.loads((store / alert_store.MANIFEST_FILE).read_text())
    manifest["sets"]["case_a"]["dates"].append("2024-07-20")
    (store / alert_store.MANIFEST_FILE).write_text(json.dumps(manifest))
    assert client.get("/api/mode").json()["latest_date"] == "2024-07-20"


def test_mode_lists_the_leads_each_live_date_can_show(built, tmp_path):
    client = make_client(built[1], tmp_path)
    write_run(tmp_path / "live", "2024-07-09", leads=(0,))
    write_run(tmp_path / "live", "2024-07-10", leads=(0, 1, 2, 3))
    write_run(tmp_path / "live", "2024-07-11", leads=(0, 1, 3))
    assert client.get("/api/mode").json()["leads"] == {"2024-07-09": [0], "2024-07-10": [0, 1, 2, 3],
                                                       "2024-07-11": [0, 1, 3]}


def test_mode_lists_lead_zero_only_for_every_replay_date(client):
    body = client.get("/api/mode").json()
    assert body["mode"] == "replay" and body["leads"] == {day: [0] for day in body["dates"]}


def test_mode_leads_of_a_live_store_set_without_run_directories_is_lead_zero(tmp_path):
    _, store = build_store(tmp_path, {"live": {"n_cells": 2, "n_days": 2, "start": "2024-08-01"}})
    assert make_client(store, tmp_path).get("/api/mode").json()["leads"] == {"2024-08-01": [0], "2024-08-02": [0]}


def test_mode_leads_are_empty_without_data(tmp_path):
    assert make_client(tmp_path / "nothing", tmp_path).get("/api/mode").json()["leads"] == {}


def write_summary(folder, thresholds):
    (folder / "run.json").write_text(json.dumps({"model": {"thresholds": thresholds}}))


def test_mode_thresholds_of_a_replay_set_come_from_the_store_manifest(client):
    assert client.get("/api/mode").json()["thresholds"] == {"watch": 1e-5, "warning": 4e-5, "emergency": 1e-4,
                                                            "source": "test"}


def test_mode_thresholds_of_a_live_set_come_from_the_newest_run_summary(built, tmp_path):
    client = make_client(built[1], tmp_path)
    write_summary(write_run(tmp_path / "live", "2024-07-09"), {"watch": 1.0, "warning": 2.0, "emergency": 3.0, "source": "old"})
    live = {"watch": 2e-6, "warning": 9e-6, "emergency": 3e-5, "source": "card.alert_levels"}
    write_summary(write_run(tmp_path / "live", "2024-07-10"), live)
    assert client.get("/api/mode").json()["thresholds"] == live


@pytest.mark.parametrize("summary", [None, "{half", json.dumps({"model": {}}),
                                     json.dumps({"model": {"thresholds": {"watch": 0, "warning": 1, "emergency": 2}}}),
                                     json.dumps({"model": {"thresholds": {"watch": "x", "warning": 1, "emergency": 2}}})])
def test_mode_thresholds_of_a_live_set_fall_back_to_the_manifest_without_a_usable_summary(built, tmp_path, summary):
    client = make_client(built[1], tmp_path)
    folder = write_run(tmp_path / "live", "2024-07-10")
    if summary is not None:
        (folder / "run.json").write_text(summary)
    assert client.get("/api/mode").json()["thresholds"]["watch"] == 1e-5


def test_mode_thresholds_are_null_without_data_or_a_manifest_entry(tmp_path):
    assert make_client(tmp_path / "nothing", tmp_path).get("/api/mode").json()["thresholds"] is None
    _, store = build_store(tmp_path, {"case_a": SETS["case_a"]})
    manifest = json.loads((store / alert_store.MANIFEST_FILE).read_text())
    del manifest["thresholds"]
    (store / alert_store.MANIFEST_FILE).write_text(json.dumps(manifest))
    assert make_client(store, tmp_path).get("/api/mode").json()["thresholds"] is None


BY_REGION = {"himalaya": {"watch": 2.78e-6, "warning": 1.38e-5, "emergency": 4.92e-5, "source": "card.alert_levels risk_by_region[himalaya]"},
             "western_ghats": {"watch": 3.81e-6, "warning": 1.37e-5, "emergency": 2.56e-5, "source": "card.alert_levels risk_by_region[western_ghats]"}}
POOLED = {"watch": 3.01e-6, "warning": 1.18e-5, "emergency": 4.81e-5, "source": "card.alert_levels"}


def write_model(folder, **model):
    (folder / "run.json").write_text(json.dumps({"model": model}))


def test_mode_serves_the_thresholds_of_each_region_from_the_newest_run_summary(built, tmp_path):
    client = make_client(built[1], tmp_path)
    write_model(write_run(tmp_path / "live", "2024-07-09"), thresholds=POOLED, thresholds_by_region={"himalaya": {**BY_REGION["himalaya"], "watch": 9.0}})
    write_model(write_run(tmp_path / "live", "2024-07-10"), thresholds=POOLED, thresholds_by_region=BY_REGION)
    body = client.get("/api/mode").json()
    assert body["thresholds_by_region"] == BY_REGION
    assert body["thresholds"] == POOLED


def test_mode_drops_a_region_whose_thresholds_are_unusable(built, tmp_path):
    client = make_client(built[1], tmp_path)
    bad = {"watch": 0, "warning": 1, "emergency": 2, "source": "x"}
    write_model(write_run(tmp_path / "live", "2024-07-10"), thresholds=POOLED,
                thresholds_by_region={**BY_REGION, "himalaya": bad, "elsewhere": "no"})
    assert client.get("/api/mode").json()["thresholds_by_region"] == {"western_ghats": BY_REGION["western_ghats"]}


@pytest.mark.parametrize("model", [{}, {"thresholds_by_region": None}, {"thresholds_by_region": []}, {"thresholds_by_region": {"himalaya": 3}}])
def test_mode_thresholds_by_region_are_null_without_usable_ones(built, tmp_path, model):
    client = make_client(built[1], tmp_path)
    write_model(write_run(tmp_path / "live", "2024-07-10"), thresholds=POOLED, **model)
    assert client.get("/api/mode").json()["thresholds_by_region"] is None


def test_mode_thresholds_by_region_of_a_replay_set_are_null_unless_the_manifest_has_them(built, tmp_path):
    assert make_client(built[1], tmp_path).get("/api/mode").json()["thresholds_by_region"] is None
    _, store = build_store(tmp_path, {"case_a": SETS["case_a"]})
    manifest = json.loads((store / alert_store.MANIFEST_FILE).read_text())
    manifest["thresholds_by_region"] = BY_REGION
    (store / alert_store.MANIFEST_FILE).write_text(json.dumps(manifest))
    assert make_client(store, tmp_path).get("/api/mode").json()["thresholds_by_region"] == BY_REGION


def test_mode_thresholds_by_region_are_null_without_data(tmp_path):
    assert make_client(tmp_path / "nothing", tmp_path).get("/api/mode").json()["thresholds_by_region"] is None


def write_scored(live_dir, day, n_scored, n_cells=100):
    folder = write_run(live_dir, day)
    (folder / "run.json").write_text(json.dumps({"leads": {"0": {"n_cells": n_cells, "n_scored": n_scored}}}))


def test_mode_reports_the_share_of_cells_scored_on_the_shown_date(built, tmp_path):
    client = make_client(built[1], tmp_path)
    write_scored(tmp_path / "live", "2024-07-09", 80)
    write_scored(tmp_path / "live", "2024-07-10", 25)
    body = client.get("/api/mode").json()
    assert body["scored_share"] == 0.25
    assert body["last_scored_date"] == "2024-07-10"


def test_mode_last_scored_date_skips_days_that_scored_nothing(built, tmp_path):
    client = make_client(built[1], tmp_path)
    write_scored(tmp_path / "live", "2024-07-08", 100)
    write_scored(tmp_path / "live", "2024-07-09", 0)
    write_scored(tmp_path / "live", "2024-07-10", 0)
    body = client.get("/api/mode").json()
    assert body["scored_share"] == 0.0
    assert body["last_scored_date"] == "2024-07-08"


def test_mode_last_scored_date_is_null_when_no_day_scored_anything(built, tmp_path):
    client = make_client(built[1], tmp_path)
    write_scored(tmp_path / "live", "2024-07-10", 0)
    body = client.get("/api/mode").json()
    assert (body["scored_share"], body["last_scored_date"]) == (0.0, None)


@pytest.mark.parametrize("summary", [None, "{half", json.dumps({}), json.dumps({"leads": {"0": {"n_cells": 0, "n_scored": 0}}}),
                                     json.dumps({"leads": {"0": {"n_cells": "x", "n_scored": 1}}})])
def test_mode_scored_status_is_null_without_a_usable_summary(built, tmp_path, summary):
    client = make_client(built[1], tmp_path)
    folder = write_run(tmp_path / "live", "2024-07-10")
    if summary is not None:
        (folder / "run.json").write_text(summary)
    body = client.get("/api/mode").json()
    assert (body["scored_share"], body["last_scored_date"]) == (None, None)


def test_mode_scored_status_is_null_for_a_replay_set_and_without_data(client, tmp_path):
    body = client.get("/api/mode").json()
    assert (body["scored_share"], body["last_scored_date"]) == (None, None)
    body = make_client(tmp_path / "nothing", tmp_path).get("/api/mode").json()
    assert (body["scored_share"], body["last_scored_date"]) == (None, None)


IST = dash_api.IST


@pytest.mark.parametrize("now, run_time, expected", [
    (datetime(2026, 10, 15, 4, 0, tzinfo=IST), "11:00", "2026-10-15T11:00:00+05:30"),
    (datetime(2026, 10, 15, 11, 0, tzinfo=IST), "11:00", "2026-10-16T11:00:00+05:30"),       # due now: the next one is tomorrow
    (datetime(2026, 10, 15, 23, 59, tzinfo=IST), "11:00", "2026-10-16T11:00:00+05:30"),
    (datetime(2026, 10, 15, 22, 0, tzinfo=timezone.utc), "09:30", "2026-10-16T09:30:00+05:30"),   # 03:30 IST on the 16th
    (datetime(2026, 12, 31, 12, 0, tzinfo=IST), "7:05", "2027-01-01T07:05:00+05:30"),
])
def test_next_run_is_the_next_occurrence_of_the_run_time_in_ist(now, run_time, expected):
    assert dash_api.next_run_after(now, run_time) == expected


def write_live_run_config(path, schedule):
    path.write_text(yaml.safe_dump({"live_dir": "data/live", "schedule": schedule}), encoding="utf-8")


def test_mode_reports_the_next_run_from_the_live_run_config(built, tmp_path):
    write_live_run_config(tmp_path / "live_run.yaml", {"timezone": "Asia/Kolkata", "run_time": "07:45"})
    body = make_client(built[1], tmp_path).get("/api/mode").json()
    when = datetime.fromisoformat(body["next_run"])
    assert when.utcoffset() == timedelta(hours=5, minutes=30) and (when.hour, when.minute) == (7, 45)
    assert datetime.now(IST) < when <= datetime.now(IST) + timedelta(days=1)


@pytest.mark.parametrize("content", [None, "schedule: {}", "schedule: {run_time: 11:00}", "schedule: {run_time: '25:99'}",
                                     "schedule: [unclosed", "- not a mapping"])
def test_mode_next_run_falls_back_to_eleven_when_the_config_has_no_usable_run_time(built, tmp_path, content):
    if content is not None:
        (tmp_path / "live_run.yaml").write_text(content, encoding="utf-8")
    when = datetime.fromisoformat(make_client(built[1], tmp_path).get("/api/mode").json()["next_run"])
    assert (when.hour, when.minute, when.utcoffset()) == (11, 0, timedelta(hours=5, minutes=30))


def test_mode_next_run_is_present_even_without_any_data(tmp_path):
    assert make_client(tmp_path / "nothing", tmp_path).get("/api/mode").json()["next_run"].endswith("+05:30")


def test_the_real_live_run_config_names_a_run_time_the_dashboard_accepts():
    assert dash_api.RUN_TIME_PATTERN.match(dash_api.configured_run_time(dash_api.DashConfig.default().live_run_config))


# ---- grid ----------------------------------------------------------------------------------------------------------

def test_grid_round_trips_the_store_day_as_typed_arrays(client):
    body = client.get("/api/grid", params={"date": "2024-07-06", "set": "case_a"}).json()
    listed = {c["cell_id"]: c for c in client.get("/risk", params={"date": "2024-07-06", "set": "case_a"}).json()["cells"]}
    assert body["date"] == "2024-07-06" and body["lead"] == 0 and body["set"] == "case_a" and body["n"] == 4
    assert (body["lat0"], body["lon0"], body["step"]) == (-90.0, -180.0, 0.05)
    cells, risk, level = decode(body["cells"], "<u4"), decode(body["risk"], "<f4"), decode(body["level"], "u1")
    confidence, risk_hi = decode(body["confidence"], "u1"), decode(body["risk_hi"], "<f4")
    assert [a.size for a in (cells, risk, level, confidence, risk_hi)] == [4] * 5
    assert list(cells) == sorted(listed)
    for i, cell in enumerate(cells):
        assert level[i] == listed[cell]["level"] and risk[i] == pytest.approx(listed[cell]["risk"], rel=1e-6)
        assert confidence[i] == {"High": 0, "Degraded": 1, "Insufficient": 2}[listed[cell]["confidence"]]
        assert risk_hi[i] >= risk[i]
    assert 0 < level.max() <= 3


def test_grid_defaults_to_the_first_set_holding_the_date(client):
    assert client.get("/api/grid", params={"date": "2024-07-05"}).json()["set"] == "case_a"
    assert client.get("/api/grid", params={"date": "2024-07-05", "set": "case_b"}).json()["n"] == 2


@pytest.mark.parametrize("params, status, text", [
    ({"date": "2030-01-01"}, 404, "available 2024-07-01..2024-07-07"),
    ({"date": "2024-07-06", "set": "nope"}, 404, "unknown set"),
    ({"date": "2024-07-06", "lead": 1}, 404, "lead 0 only"),
    ({"date": "2024-07-06", "lead": 4}, 422, ""),
    ({"date": "2024-7-6"}, 422, ""), ({}, 422, "")])
def test_grid_errors_are_clear(client, params, status, text):
    response = client.get("/api/grid", params=params)
    assert response.status_code == status and text in json.dumps(response.json()["detail"])


def test_grid_without_a_store_says_so(tmp_path):
    response = make_client(tmp_path / "nothing", tmp_path).get("/api/grid", params={"date": "2024-07-06"})
    assert response.status_code == 404 and "no replay store" in response.json()["detail"]


def test_grid_of_a_live_run_serves_every_lead(built, tmp_path):
    client = make_client(built[1], tmp_path)
    write_run(tmp_path / "live", "2024-07-10", leads=(0, 1))
    zero = client.get("/api/grid", params={"date": "2024-07-10"}).json()
    one = client.get("/api/grid", params={"date": "2024-07-10", "lead": 1, "set": "live"}).json()
    assert zero["set"] == one["set"] == "live" and one["lead"] == 1 and zero["n"] == 3
    assert list(decode(zero["cells"], "<u4")) == [10_000_003, 20_000_005, 30_000_001]      # ordered by cell id
    assert list(decode(zero["level"], "u1")) == [0, 2, 3] and list(decode(zero["confidence"], "u1")) == [1, 0, 2]
    assert decode(one["risk"], "<f4")[1] == pytest.approx(1.2)
    missing = client.get("/api/grid", params={"date": "2024-07-10", "lead": 2})
    assert missing.status_code == 404 and "no lead-2 forecast" in missing.json()["detail"]
    unknown = client.get("/api/grid", params={"date": "2030-01-01"})
    assert unknown.status_code == 404 and "live runs available 2024-07-10..2024-07-10" in unknown.json()["detail"]


def test_grid_rejects_an_unknown_confidence_label(built, tmp_path):
    client = make_client(built[1], tmp_path)
    write_run(tmp_path / "live", "2024-07-10", confidence="Sure")
    response = client.get("/api/grid", params={"date": "2024-07-10"})
    assert response.status_code == 500 and "Sure" in response.json()["detail"]


def test_grid_flags_encode_blind_escalation_hysteresis_holds_and_untrusted_gauges(built, tmp_path):
    client = make_client(built[1], tmp_path)
    write_run(tmp_path / "live", "2024-07-10", extra={
        "blind_escalated": [True, False, True],
        "reason_codes": ["sources_disagree_heavy_rain", "risk_above_watch;hysteresis_hold",
                         "sensors_untrusted_heavy_rain;hysteresis_hold"]})
    body = client.get("/api/grid", params={"date": "2024-07-10"}).json()
    assert list(decode(body["cells"], "<u4")) == [10_000_003, 20_000_005, 30_000_001]
    assert list(decode(body["flags"], "u1")) == [dash_api.FLAG_HELD, dash_api.FLAG_BLIND,
                                                 dash_api.FLAG_BLIND | dash_api.FLAG_HELD | dash_api.FLAG_UNTRUSTED]
    assert (dash_api.FLAG_BLIND, dash_api.FLAG_HELD, dash_api.FLAG_UNTRUSTED) == (1, 2, 4)


def test_grid_flags_mark_a_rain_capped_cell_and_a_disagreeing_ensemble(built, tmp_path):
    client = make_client(built[1], tmp_path)
    write_run(tmp_path / "live", "2024-07-10", extra={
        "blind_escalated": [False, False, False],
        "reason_codes": ["risk_above_emergency;no_recent_rain", "risk_above_watch", "no_recent_rain;hysteresis_hold"],  # rows in file order
        "confidence_causes": ["", "ensemble_disagrees", "gauges_untrusted;ensemble_disagrees"]})
    body = client.get("/api/grid", params={"date": "2024-07-10"}).json()
    assert list(decode(body["cells"], "<u4")) == [10_000_003, 20_000_005, 30_000_001]
    assert list(decode(body["flags"], "u1")) == [dash_api.FLAG_DISAGREE, dash_api.FLAG_CAPPED,
                                                 dash_api.FLAG_CAPPED | dash_api.FLAG_HELD | dash_api.FLAG_DISAGREE]
    assert (dash_api.FLAG_CAPPED, dash_api.FLAG_DISAGREE) == (8, 16)


def test_grid_flags_of_a_forecast_lead_read_the_same_columns_when_it_has_them(built, tmp_path):
    client = make_client(built[1], tmp_path)
    folder = write_run(tmp_path / "live", "2024-07-10", leads=(0, 1))
    lead = pd.read_parquet(folder / "risk_D1.parquet").assign(
        reason_codes=["no_recent_rain", "", ""], confidence_causes=["", "", "ensemble_disagrees"])
    lead.to_parquet(folder / "risk_D1.parquet", index=False)
    body = client.get("/api/grid", params={"date": "2024-07-10", "lead": 1}).json()
    assert list(decode(body["flags"], "u1")) == [0, dash_api.FLAG_CAPPED, dash_api.FLAG_DISAGREE]


def test_grid_flags_round_trip_the_replay_store_columns(client):
    body = client.get("/api/grid", params={"date": "2024-07-06", "set": "case_a"}).json()
    listed = {c["cell_id"]: c for c in client.get("/risk", params={"date": "2024-07-06", "set": "case_a"}).json()["cells"]}
    flags = decode(body["flags"], "u1")
    assert flags.size == body["n"]
    for cell, flag in zip(decode(body["cells"], "<u4"), flags):
        assert bool(flag & dash_api.FLAG_HELD) == ("hysteresis_hold" in listed[cell]["reason_codes"])


def test_grid_flags_are_zero_when_the_table_has_no_reason_columns(built, tmp_path):
    client = make_client(built[1], tmp_path)
    write_run(tmp_path / "live", "2024-07-10", leads=(0, 1))
    for lead in (0, 1):
        body = client.get("/api/grid", params={"date": "2024-07-10", "lead": lead}).json()
        assert list(decode(body["flags"], "u1")) == [0, 0, 0]


# ---- cell history --------------------------------------------------------------------------------------------------

def test_cell_history_lists_the_days_of_the_window(client):
    body = client.get("/api/cells/1003/history", params={"set": "case_a", "days": 3}).json()
    assert body["cell_id"] == 1003 and body["set"] == "case_a" and body["days"] == 3
    assert body["dates"] == ["2024-07-04", "2024-07-05", "2024-07-06"]
    listed = [client.get("/risk/cell/1003", params={"date": d, "set": "case_a"}).json() for d in body["dates"]]
    assert body["risk"] == [c["risk"] for c in listed] and body["level"] == [c["level"] for c in listed]


def test_cell_history_carries_the_one_day_rain_of_each_source_and_null_where_the_table_lacks_it(built, tmp_path, client):
    body = client.get("/api/cells/1003/history", params={"set": "case_a", "days": 3}).json()
    assert set(body["rain"]) == {"imd_acc_1", "chirps_acc_1", "station_trw_1"}
    sources = [client.get("/risk/cell/1003", params={"date": d, "set": "case_a"}).json()["sources"] for d in body["dates"]]
    for column in body["rain"]:
        assert body["rain"][column] == pytest.approx([s[column] for s in sources])
    assert all(v is not None for v in body["rain"]["imd_acc_1"])
    live = make_client(built[1], tmp_path)
    write_run(tmp_path / "live", "2024-07-10")                                   # a run table without evidence columns
    assert live.get("/api/cells/20000005/history").json()["rain"] == {c: [None] for c in body["rain"]}


def test_cell_history_ends_at_the_requested_date_and_defaults_to_the_mode_set(client):
    body = client.get("/api/cells/1000/history", params={"days": 30, "date": "2024-07-05", "set": "case_a"}).json()
    assert body["dates"][0] == "2024-07-01" and body["dates"][-1] == "2024-07-05"
    default = client.get("/api/cells/1001/history").json()                       # mode set: case_b, 2024-07-04..07
    assert default["set"] == "case_b" and default["dates"] == ["2024-07-04", "2024-07-05", "2024-07-06", "2024-07-07"]


@pytest.mark.parametrize("path, params, status", [
    ("/api/cells/9/history", {"set": "case_a"}, 404), ("/api/cells/1000/history", {"set": "nope"}, 404),
    ("/api/cells/1000/history", {"date": "2030-01-01", "set": "case_a"}, 404),
    ("/api/cells/1000/history", {"days": 0}, 422), ("/api/cells/x/history", {}, 422)])
def test_cell_history_errors(client, path, params, status):
    response = client.get(path, params=params)
    assert response.status_code == status and response.json()["detail"]


def test_cell_history_of_a_live_run_directory(built, tmp_path):
    client = make_client(built[1], tmp_path)
    for day in ("2024-07-09", "2024-07-10"):
        write_run(tmp_path / "live", day)
    body = client.get("/api/cells/20000005/history").json()
    assert body["set"] == "live" and body["dates"] == ["2024-07-09", "2024-07-10"] and body["level"] == [2, 2]


def test_cell_history_without_any_data_is_a_404(tmp_path):
    assert make_client(tmp_path / "nothing", tmp_path).get("/api/cells/1/history").status_code == 404


# ---- terrain -------------------------------------------------------------------------------------------------------

def write_terrain(path, points):
    """A terrain table from (lat, lon, elev) points."""
    ids = [int(latlon_to_cell(lat, lon)) for lat, lon, _ in points]
    pd.DataFrame({"cell_id": ids, "lat": [p[0] for p in points], "lon": [p[1] for p in points],
                  "elev_mean": [p[2] for p in points], "elev_std": 1.0}).to_parquet(path, index=False)
    return ids


def test_terrain_grid_places_cells_by_their_ids_south_to_north(tmp_path):
    ids = write_terrain(tmp_path / "t.parquet", [(8.025, 72.025, 120.5), (35.975, 97.975, 4800.0), (11.525, 76.025, -3.0),
                                                 (7.0, 70.0, 99.0)])                       # the last is outside the domain
    grid = tg.build_terrain_grid(pd.read_parquet(tmp_path / "t.parquet"))
    assert grid.shape == (tg.ROWS, tg.COLS) == (560, 520) and grid.dtype == np.float16
    assert grid[0, 0] == 120.5 and grid[559, 519] == 4800.0 and grid[70, 80] == -3.0
    assert np.isnan(grid).sum() == grid.size - 3
    assert ids[2] // 10_000 - tg.LAT_INDEX0 == 70 and ids[2] % 10_000 - tg.LON_INDEX0 == 80


def test_terrain_endpoint_round_trips_and_caches_the_grid(tmp_path):
    write_terrain(tmp_path / "terrain.parquet", [(8.025, 72.025, 120.5), (11.525, 76.025, 431.0)])
    client = make_client(tmp_path / "nothing", tmp_path)
    body = client.get("/api/terrain").json()
    assert (body["rows"], body["cols"], body["lat0"], body["lon0"], body["step"]) == (560, 520, 8.0, 72.0, 0.05)
    elev = decode(body["elev"], "<f2").reshape(560, 520)
    assert elev[0, 0] == 120.5 and elev[70, 80] == 431.0 and np.isnan(elev).sum() == elev.size - 2
    cache = tmp_path / "serve" / "terrain_grid.npz"
    assert cache.is_file()
    with np.load(cache) as stored:
        assert stored["elev"].dtype == np.float16 and stored["elev"].shape == (560, 520)


def test_terrain_cache_is_reused_until_the_source_changes(tmp_path, monkeypatch):
    source, cache = tmp_path / "t.parquet", tmp_path / "cache" / "grid.npz"
    write_terrain(source, [(8.025, 72.025, 10.0)])
    assert tg.load_terrain_grid(source, cache)[0, 0] == 10.0
    monkeypatch.setattr(tg, "build_terrain_grid", lambda table: pytest.fail("rebuilt from an unchanged source"))
    assert tg.load_terrain_grid(source, cache)[0, 0] == 10.0
    monkeypatch.undo()
    write_terrain(source, [(8.025, 72.025, 20.0), (8.075, 72.025, 30.0)])
    assert tg.load_terrain_grid(source, cache)[1, 0] == 30.0


def test_terrain_without_a_table_is_a_404_with_the_build_command(tmp_path):
    response = make_client(tmp_path / "nothing", tmp_path).get("/api/terrain")
    assert response.status_code == 404 and "terrain_build" in response.json()["detail"]


# ---- base map ------------------------------------------------------------------------------------------------------

BASEMAP_ELEV = np.array([[0.0, 100.5, -250.0, 6000.0], [12.0, 1.0, 2400.0, 8.0], [3000.0, 0.0, -1.0, 55.5]], dtype=np.float32)
BASEMAP_MASK = np.array([[1, 1, 0, 2], [1, 1, 4, 0], [3, 1, 0, 4]], dtype=np.uint8)
BASEMAP_OUTLINE = [{"name": "India", "rings": [[[68.0, 6.0], [68.2, 6.0], [68.2, 6.15], [68.0, 6.0]]]},
                   {"name": "Nepal", "rings": []}, {"name": "Bhutan", "rings": []}]


def write_basemap(folder, elev=BASEMAP_ELEV, mask=BASEMAP_MASK, lat0=6.0, lon0=68.0):
    """A tiny base map in the file layout of aetherguard.serve.basemap (npz arrays plus the json with the outlines)."""
    folder.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(folder / dash_api.BASEMAP_NPZ, elev=elev, mask=mask, lat0=np.float64(lat0), lon0=np.float64(lon0),
                        step=np.float64(CELL_DEG))
    (folder / dash_api.BASEMAP_JSON).write_text(json.dumps({"outline": BASEMAP_OUTLINE, "grid": {"rows": elev.shape[0]}}))
    return folder


@pytest.fixture(autouse=True)
def fresh_basemap_cache():
    dash_api._basemap_payload.cache_clear()


def test_the_basemap_file_names_are_the_ones_the_builder_writes():
    from aetherguard.serve import basemap as builder
    assert (dash_api.BASEMAP_NPZ, dash_api.BASEMAP_JSON) == (builder.NPZ_NAME, builder.JSON_NAME)


def test_basemap_round_trips_elevation_mask_and_outline(tmp_path):
    write_basemap(tmp_path / "basemap")
    body = make_client(tmp_path / "nothing", tmp_path).get("/api/basemap").json()
    assert (body["rows"], body["cols"], body["lat0"], body["lon0"], body["step"]) == (3, 4, 6.0, 68.0, CELL_DEG)
    np.testing.assert_array_equal(decode(body["elev"], "<f2").reshape(3, 4), BASEMAP_ELEV.astype(np.float16))
    np.testing.assert_array_equal(decode(body["mask"], "u1").reshape(3, 4), BASEMAP_MASK)
    assert body["outline"] == BASEMAP_OUTLINE


def test_basemap_elevation_is_compact_little_endian_float16_and_the_mask_one_byte_per_cell(tmp_path):
    write_basemap(tmp_path / "basemap")
    body = make_client(tmp_path / "nothing", tmp_path).get("/api/basemap").json()
    assert len(base64.b64decode(body["elev"])) == 3 * 4 * 2 and len(base64.b64decode(body["mask"])) == 3 * 4
    assert base64.b64decode(body["elev"])[2:4] == np.array([100.5], dtype="<f2").tobytes()


def test_basemap_rows_and_columns_land_on_the_cell_ids_of_the_global_grid(tmp_path):
    """Row r, column c is cell (lat_index0 + r) * 10000 + lon_index0 + c: the id /api/grid uses for the same place."""
    write_basemap(tmp_path / "basemap")
    body = make_client(tmp_path / "nothing", tmp_path).get("/api/basemap").json()
    lat_index0, lon_index0 = divmod(int(latlon_to_cell(body["lat0"] + body["step"] / 2, body["lon0"] + body["step"] / 2)), 10_000)
    assert (lat_index0, lon_index0) == (1920, 4960)
    for row in range(body["rows"]):
        for col in range(body["cols"]):
            lat = body["lat0"] + (row + 0.5) * body["step"]
            lon = body["lon0"] + (col + 0.5) * body["step"]
            assert int(latlon_to_cell(lat, lon)) == (lat_index0 + row) * 10_000 + lon_index0 + col


def test_basemap_is_cached_until_a_file_changes(tmp_path, monkeypatch):
    folder = write_basemap(tmp_path / "basemap")
    client = make_client(tmp_path / "nothing", tmp_path)
    first = client.get("/api/basemap").json()
    monkeypatch.setattr(np, "load", lambda *a, **k: pytest.fail("re-read an unchanged base map"))
    assert client.get("/api/basemap").json() == first
    monkeypatch.undo()
    write_basemap(folder, elev=BASEMAP_ELEV + 1)
    assert client.get("/api/basemap").json()["elev"] != first["elev"]


def test_basemap_without_files_is_a_404_with_the_build_command_and_no_local_path(tmp_path):
    response = make_client(tmp_path / "nothing", tmp_path).get("/api/basemap")
    assert response.status_code == 404 and "aetherguard.serve.basemap build" in response.json()["detail"]
    assert_no_local_path(response, tmp_path)


def test_basemap_missing_its_outline_file_is_a_404(tmp_path):
    folder = write_basemap(tmp_path / "basemap")
    (folder / dash_api.BASEMAP_JSON).unlink()
    assert make_client(tmp_path / "nothing", tmp_path).get("/api/basemap").status_code == 404


@pytest.mark.parametrize("damage", ["truncated", "mask_shape", "no_outline"])
def test_an_unreadable_basemap_is_a_500_that_names_no_local_path(tmp_path, damage):
    folder = write_basemap(tmp_path / "basemap")
    if damage == "truncated":
        (folder / dash_api.BASEMAP_NPZ).write_bytes((folder / dash_api.BASEMAP_NPZ).read_bytes()[:40])
    elif damage == "mask_shape":
        write_basemap(folder, mask=BASEMAP_MASK[:2])
    else:
        (folder / dash_api.BASEMAP_JSON).write_text("{}")
    response = make_client(tmp_path / "nothing", tmp_path).get("/api/basemap")
    assert response.status_code == 500 and "cannot be read" in response.json()["detail"]
    assert_no_local_path(response, tmp_path)


# ---- rain ----------------------------------------------------------------------------------------------------------

def test_coarse_rain_averages_cells_per_quarter_degree_bin():
    field = dash_api.coarse_rain([8.1, 8.2, 35.9, 7.9, 8.1], [72.1, 72.2, 97.9, 72.1, 72.1], [10.0, 30.0, 5.0, 99.0, np.nan])
    assert field.shape == (112, 104) and field.dtype == np.float32
    assert field[0, 0] == 20.0 and field[111, 103] == 5.0 and np.isnan(field).sum() == field.size - 2


def test_rain_of_a_replay_day_is_the_binned_feature_rain(built, client):
    root, _ = built
    body = client.get("/api/rain", params={"date": "2024-07-06", "set": "case_a"}).json()
    features = pd.read_parquet(root / "features" / "case_a_features.parquet")
    day = features[features["date"] == "2024-07-06"]
    assert body["set"] == "case_a" and body["column"] == "rain_acc_1" and body["unit"] == "mm/day"
    assert (body["rows"], body["cols"], body["lat0"], body["lon0"], body["step"]) == (112, 104, 8.0, 72.0, 0.25)
    field = decode(body["rain"], "<f4").reshape(112, 104)
    assert field[14, 16] == pytest.approx(day["rain_acc_1"].mean()) and np.isnan(field).sum() == field.size - 1
    assert body["n_cells"] == 4


def test_rain_of_a_live_run_prefers_the_imerg_column(built, tmp_path):
    client = make_client(built[1], tmp_path)
    write_run(tmp_path / "live", "2024-07-10", rain_column="irain_acc_1")
    body = client.get("/api/rain", params={"date": "2024-07-10"}).json()
    assert body["set"] == "live" and body["column"] == "irain_acc_1"
    assert decode(body["rain"], "<f4").reshape(112, 104)[16, 16] == pytest.approx(20.0)


def test_rain_names_the_rain_sources_of_the_days_alert_rows(client):
    assert client.get("/api/rain", params={"date": "2024-07-06", "set": "case_a"}).json()["rain_sources"] == ["imd"]


def test_rain_sources_are_most_frequent_first_and_empty_without_the_column(tmp_path):
    path = tmp_path / "alerts.parquet"
    pd.DataFrame({"rain_source": ["imd", "chirps_aligned", "chirps_aligned", None]}).to_parquet(path)
    assert dash_api._rain_sources(path) == ["chirps_aligned", "imd"]
    pd.DataFrame({"risk": [0.1]}).to_parquet(path)
    assert dash_api._rain_sources(path) == []


@pytest.mark.parametrize("params, status, text", [
    ({"date": "2030-01-01"}, 404, "available"), ({"date": "2024-07-06", "set": "nope"}, 404, "unknown set"),
    ({"date": "bad"}, 422, "")])
def test_rain_errors(client, params, status, text):
    response = client.get("/api/rain", params=params)
    assert response.status_code == status and text in json.dumps(response.json()["detail"])


def test_rain_without_the_feature_table_names_the_missing_file(built, tmp_path):
    client = make_client(built[1], tmp_path)
    client.app.state.dash = replace(client.app.state.dash, features_dir=tmp_path / "empty")
    response = client.get("/api/rain", params={"date": "2024-07-06"})
    assert response.status_code == 404 and "case_a_features.parquet" in response.json()["detail"]


# ---- sources status ------------------------------------------------------------------------------------------------

def test_sources_status_without_a_live_run_says_so(client, tmp_path):
    body = client.get("/api/sources/status").json()
    assert body["available"] is False and "no live run" in body["reason"]
    assert str(tmp_path) not in body["reason"] and tmp_path.name not in body["reason"]


def test_sources_status_reason_is_relative_to_the_project_root_not_an_absolute_path(tmp_path, monkeypatch):
    monkeypatch.setattr(dash_api, "PROJECT_ROOT", tmp_path)          # hermetic: the real data/live may hold runs
    client = make_client(tmp_path / "nothing", tmp_path)
    client.app.state.dash = replace(client.app.state.dash, live_dir=tmp_path / "data" / "live")
    reason = client.get("/api/sources/status").json()["reason"]
    assert reason.endswith("under data/live)") and str(dash_api.PROJECT_ROOT) not in reason


@pytest.mark.parametrize("path, expected", [
    (dash_api.PROJECT_ROOT / "data" / "live", "data/live"),
    (dash_api.data_root() / "live" / "2024-07-10" / "freshness.json", "data/live/2024-07-10/freshness.json"),
    (Path("elsewhere") / "outside" / "live", "live")])
def test_display_path_hides_the_machine_location(path, expected):
    assert dash_api.display_path(path) == expected


def test_sources_status_is_the_newest_runs_freshness(built, tmp_path):
    client = make_client(built[1], tmp_path)
    write_run(tmp_path / "live", "2024-07-09", freshness={"run": "old"})
    fresh = {"run": "2024-07-10", "sources": {"imerg_late": {"status": "ok", "latency_h": 7.5}}}
    write_run(tmp_path / "live", "2024-07-10", freshness=fresh)
    (tmp_path / "live" / "2024-07-11").mkdir()                                        # no freshness yet: ignored
    assert client.get("/api/sources/status").json() == fresh


def test_sources_status_reports_an_unreadable_file(built, tmp_path):
    client = make_client(built[1], tmp_path)
    (write_run(tmp_path / "live", "2024-07-10") / "freshness.json").write_text("{half")
    body = client.get("/api/sources/status").json()
    assert body["available"] is False and "unreadable" in body["reason"] and str(tmp_path) not in body["reason"]


# ---- stream --------------------------------------------------------------------------------------------------------

def parse(chunk):
    event, data = chunk.strip().split("\n", 1)
    return event.removeprefix("event: "), json.loads(data.removeprefix("data: "))


async def next_event(stream, timeout=5.0):
    return parse(await asyncio.wait_for(stream.__anext__(), timeout))


def test_stream_announces_a_new_run_changed_sources_and_a_rebuilt_store(built, tmp_path):
    client = make_client(built[1], tmp_path, poll_interval=0.02, heartbeat_interval=60)
    live = tmp_path / "live"
    write_run(live, "2024-07-09", freshness={"v": 1})

    async def scenario():
        stream = dash_api.event_stream(client.app.state.store, client.app.state.dash)
        assert (await next_event(stream))[0] == "heartbeat"                       # on connect
        write_run(live, "2024-07-10", freshness={"v": 2})
        seen = [await next_event(stream), await next_event(stream)]
        assert [name for name, _ in seen] == ["run", "sources"]
        assert seen[0][1]["trigger"] == "live_run" and seen[0][1]["latest_date"] == "2024-07-10"
        assert seen[0][1]["mode"] == "live" and seen[1][1] == {"v": 2}
        (live / "2024-07-10" / "freshness.json").write_text(json.dumps({"v": 3}))
        assert await next_event(stream) == ("sources", {"v": 3})
        manifest = json.loads((built[1] / alert_store.MANIFEST_FILE).read_text())
        copy = tmp_path / "store"
        copy.mkdir()
        manifest["sets"]["case_b"]["dates"].append("2024-07-30")
        (copy / alert_store.MANIFEST_FILE).write_text(json.dumps(manifest))
        replay = dash_api.event_stream(alert_store.ReplayStore(copy), client.app.state.dash)
        assert (await next_event(replay))[0] == "heartbeat"
        manifest["sets"]["case_b"]["dates"].append("2024-07-31")
        (copy / alert_store.MANIFEST_FILE).write_text(json.dumps(manifest))
        name, data = await next_event(replay)
        assert name == "run" and data["trigger"] == "replay_store"
        await stream.aclose()
        await replay.aclose()

    asyncio.run(scenario())


def test_stream_sends_heartbeats_on_the_configured_interval(built, tmp_path):
    client = make_client(built[1], tmp_path, poll_interval=0.01, heartbeat_interval=0.05)

    async def scenario():
        stream = dash_api.event_stream(client.app.state.store, client.app.state.dash)
        beats = [await next_event(stream) for _ in range(3)]
        await stream.aclose()
        return beats

    beats = asyncio.run(scenario())
    assert [name for name, _ in beats] == ["heartbeat"] * 3 and "time" in beats[0][1]


def test_stream_over_http_is_event_stream_and_delivers_run_events(built, tmp_path):
    app = api.create_app(built[1], live_dir=tmp_path / "live", dist_dir=tmp_path / NO_DIST, poll_interval=0.02,
                         heartbeat_interval=0.1)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        port = server.servers[0].sockets[0].getsockname()[1]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/stream", timeout=10) as response:
            assert response.headers["Content-Type"].startswith("text/event-stream")
            assert response.headers["Cache-Control"] == "no-cache"
            names, deadline = [], time.monotonic() + 10
            while "run" not in names and time.monotonic() < deadline:
                line = response.readline().decode().strip()
                if line.startswith("event: "):
                    names.append(line.removeprefix("event: "))
                    if names == ["heartbeat"]:
                        write_run(tmp_path / "live", "2024-07-10")
        assert names[0] == "heartbeat" and "run" in names
    finally:
        server.should_exit = True
        thread.join(timeout=10)


# ---- serving the built dashboard -----------------------------------------------------------------------------------

@pytest.fixture
def dist_client(built, tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>AetherGuard</title><div id=root></div>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    return TestClient(api.create_app(built[1], live_dir=tmp_path / "live", dist_dir=dist))


def test_dist_is_served_at_the_root_and_for_client_side_routes(dist_client):
    for path in ("/", "/index.html", "/map", "/some/deep/link"):
        response = dist_client.get(path)
        assert response.status_code == 200 and "AetherGuard" in response.text and "text/html" in response.headers["content-type"]
    assert dist_client.get("/assets/app.js").text == "console.log(1)"


def test_dist_never_shadows_the_api_or_existing_routes(dist_client):
    assert dist_client.get("/api/mode").json()["mode"] == "replay"
    assert dist_client.get("/health").json()["aetherguard_version"]
    assert dist_client.get("/risk", params={"date": "2024-07-06"}).json()["n_cells"] == 4
    assert dist_client.get("/risk/cell/1003", params={"date": "2024-07-06"}).status_code == 200
    unknown = dist_client.get("/api/nope")
    assert unknown.status_code == 404 and "AetherGuard" not in unknown.text
    assert dist_client.get("/assets/missing.js").status_code == 404
    assert dist_client.post("/").status_code == 405 and dist_client.post("/risk").status_code == 405


def test_without_a_built_dashboard_the_root_is_not_found(client):
    assert client.get("/").status_code == 404 and client.get("/api/mode").status_code == 200


def test_the_dashboard_api_is_read_only(client):
    paths = {p: set(ops) for p, ops in client.get("/openapi.json").json()["paths"].items() if p.startswith("/api")}
    assert len(paths) == 9 and all(ops == {"get"} for ops in paths.values())
    assert client.post("/api/mode").status_code == 405


# ---- NaN and infinity in JSON --------------------------------------------------------------------------------------

NON_FINITE = ["risk", "risk_lo", "risk_hi", "risk_per_100k"]


def store_with_non_finite_risk(tmp_path, value=float("nan")):
    """A fresh store whose cell 1003 has `value` in every risk column on 2024-07-06 (an Insufficient live cell)."""
    _, store = build_store(tmp_path, {"case_a": SETS["case_a"]})
    path = store / "case_a" / alert_store.ALERTS_DIR / "2024-07-06.parquet"
    frame = pd.read_parquet(path)
    frame.loc[frame["cell_id"] == 1003, NON_FINITE] = value
    frame.to_parquet(path, index=False)
    return store


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_cell_explanation_serialises_non_finite_risk_as_null(tmp_path, value):
    client = make_client(store_with_non_finite_risk(tmp_path, value), tmp_path)
    response = client.get("/risk/cell/1003", params={"date": "2024-07-06"})
    assert response.status_code == 200
    body = response.json()
    assert [body[name] for name in NON_FINITE] == [None] * 4
    assert body["level_name"] and body["shap"]


def test_risk_list_and_alert_list_serialise_non_finite_risk_as_null(tmp_path):
    client = make_client(store_with_non_finite_risk(tmp_path), tmp_path)
    cells = client.get("/risk", params={"date": "2024-07-06"}).json()["cells"]
    assert [c["risk"] for c in cells if c["cell_id"] == 1003] == [None]
    assert sum(c["risk"] is not None for c in cells) == 3
    alerts = client.get("/alerts", params={"start": "2024-07-06", "end": "2024-07-06", "min_level": "Normal"})
    assert alerts.status_code == 200 and None in [a["risk"] for a in alerts.json()["alerts"]]


def test_the_sources_status_file_may_hold_nan_without_a_server_error(built, tmp_path):
    client = make_client(built[1], tmp_path)
    folder = write_run(tmp_path / "live", "2024-07-10")
    (folder / "freshness.json").write_text('{"sources": {"gfs": {"latency_h": NaN, "late_h": Infinity}}}')
    response = client.get("/api/sources/status")
    assert response.status_code == 200 and response.json() == {"sources": {"gfs": {"latency_h": None, "late_h": None}}}


def test_the_null_nan_response_leaves_finite_values_alone():
    from aetherguard.serve.jsonsafe import NullNaNJSONResponse, finite_or_none
    assert finite_or_none({"a": [1.5, float("nan"), (float("inf"), "x", None, True)], "b": 3}) == {
        "a": [1.5, None, [None, "x", None, True]], "b": 3}
    assert NullNaNJSONResponse({"a": [1.5, float("nan")], "b": "NaN"}).body == b'{"a":[1.5,null],"b":"NaN"}'


# ---- no absolute local paths in messages ---------------------------------------------------------------------------

DRIVE_PATH = re.compile(r"[A-Za-z]:[\\/]|/(?:home|Users|tmp|var)/")


def assert_no_local_path(response, tmp_path):
    text = response.json()["detail"]                   # decoded: the raw body escapes backslashes
    assert str(tmp_path) not in text and tmp_path.as_posix() not in text and not DRIVE_PATH.search(text), text


@pytest.mark.parametrize("path, params", [("/risk", {"date": "2024-07-06"}), ("/api/grid", {"date": "2024-07-06"}),
                                          ("/api/rain", {"date": "2024-07-06"}),
                                          ("/api/cells/1/history", {"set": "case_a"})])
def test_a_missing_store_error_names_no_absolute_path(tmp_path, path, params):
    response = make_client(tmp_path / "nothing", tmp_path).get(path, params=params)
    assert response.status_code == 404 and "no replay store" in response.json()["detail"]
    assert_no_local_path(response, tmp_path)


def test_a_missing_terrain_table_error_names_no_absolute_path(tmp_path):
    response = make_client(tmp_path / "nothing", tmp_path).get("/api/terrain")
    assert response.status_code == 404 and "terrain_build" in response.json()["detail"]
    assert_no_local_path(response, tmp_path)


def test_a_missing_feature_table_error_names_no_absolute_path(built, tmp_path):
    client = make_client(built[1], tmp_path)
    client.app.state.dash = replace(client.app.state.dash, features_dir=tmp_path / "empty")
    response = client.get("/api/rain", params={"date": "2024-07-06"})
    assert response.status_code == 404 and "case_a_features.parquet" in response.json()["detail"]
    assert_no_local_path(response, tmp_path)


def test_an_unreadable_grid_error_names_no_absolute_path(built, tmp_path):
    client = make_client(built[1], tmp_path)
    folder = write_run(tmp_path / "live", "2024-07-10")
    pd.DataFrame({"cell_id": [1]}).to_parquet(folder / "alerts.parquet", index=False)
    response = client.get("/api/grid", params={"date": "2024-07-10"})
    assert response.status_code == 500 and "cannot be read as a risk grid" in response.json()["detail"]
    assert_no_local_path(response, tmp_path)


def test_a_missing_live_lead_error_names_no_absolute_path(built, tmp_path):
    client = make_client(built[1], tmp_path)
    write_run(tmp_path / "live", "2024-07-10", leads=(0,))
    response = client.get("/api/grid", params={"date": "2024-07-10", "lead": 2})
    assert response.status_code == 404 and "no lead-2 forecast" in response.json()["detail"]
    assert_no_local_path(response, tmp_path)


def test_scrub_replaces_known_roots_and_any_other_drive_path():
    live = dash_api.PROJECT_ROOT / "data" / "live"
    text = f"cannot read {live} and {live.as_posix()}/x.parquet; also " + r"C:\Users\someone\secret\file.txt"
    scrubbed = dash_api.scrub(text)
    assert "data/live" in scrubbed and str(dash_api.PROJECT_ROOT) not in scrubbed and "someone" not in scrubbed
    assert dash_api.scrub("plain message") == "plain message"


# ---- serving the dashboard: client routes and API routes -----------------------------------------------------------

def test_the_three_client_routes_load_the_app_and_the_json_routes_next_to_them_stay_json(dist_client):
    for path in ("/map", "/alerts-why", "/sensors-sources"):
        response = dist_client.get(path)
        assert response.status_code == 200 and "<div id=root>" in response.text, path
    assert dist_client.get("/alerts", params={"start": "2024-07-01", "end": "2024-07-06"}).json()["start"] == "2024-07-01"
    assert dist_client.get("/sensors", params={"date": "2024-07-06"}).json()["date"] == "2024-07-06"
    assert dist_client.get("/risk", params={"date": "2024-07-06"}).json()["date"] == "2024-07-06"
    assert dist_client.get("/health").headers["content-type"].startswith("application/json")
    assert "swagger" in dist_client.get("/docs").text.lower() and dist_client.get("/openapi.json").json()["paths"]


def test_a_route_without_a_response_model_also_sends_nan_as_null(built, tmp_path):
    client = make_client(built[1], tmp_path)
    client.app.add_api_route("/probe", lambda: {"risk": float("nan"), "n": 1}, methods=["GET"])
    response = client.get("/probe")
    assert response.status_code == 200 and response.json() == {"risk": None, "n": 1}


# ---- place names ---------------------------------------------------------------------------------------------------

PLACE_ROWS = [
    (20_000_005, "Mananthavady", "Wayanad", "Kerala", "India", 8, 11.8, 76.0, 41_000),
    (10_000_003, "Kathmandu", None, "Bagmati Province", "Nepal", 5, 27.7, 85.3, 1_000_000),
    (30_000_001, "Mananthavady", "Wayanad", "Kerala", "India", 32, 11.8, 76.0, 41_000),
]


def write_places(tmp_path, rows=PLACE_ROWS):
    folder = tmp_path / "places"
    folder.mkdir(exist_ok=True)
    frame = pd.DataFrame(rows, columns=pl.TABLE_COLUMNS)
    frame.to_parquet(folder / pl.TABLE_NAME, index=False)
    return folder / pl.TABLE_NAME


def decode_places(body):
    """{cell_id: (place, district, state, country, distance_km)} from a /api/places payload."""
    cells = decode(body["cells"], "<u4")
    columns = {k: decode(body[k], dtype) for k, dtype in (("place", "<u4"), ("district", "<u2"), ("state", "<u2"),
                                                          ("country", "u1"), ("distance_km", "<u2"))}
    return {int(c): (body["places"][columns["place"][i]], body["districts"][columns["district"][i]] or None,
                     body["states"][columns["state"][i]] or None, body["countries"][columns["country"][i]] or None,
                     int(columns["distance_km"][i])) for i, c in enumerate(cells)}


def test_places_round_trips_every_label_with_the_attribution(client, tmp_path):
    write_places(tmp_path)
    body = client.get("/api/places").json()
    assert body["attribution"] == "Place names: GeoNames (CC BY 4.0)" and body["n"] == 3
    assert decode_places(body) == {
        10_000_003: ("Kathmandu", None, "Bagmati Province", "Nepal", 5),
        20_000_005: ("Mananthavady", "Wayanad", "Kerala", "India", 8),
        30_000_001: ("Mananthavady", "Wayanad", "Kerala", "India", 32)}
    assert body["far_km"] == 25 and body["places"].count("Mananthavady") == 1


def test_places_payload_is_compact_for_the_whole_domain(tmp_path):
    rng = np.random.default_rng(1)
    n = 36_792
    names = [f"Place number {i}" for i in range(1700)]
    rows = [(i, names[rng.integers(1700)], f"District {rng.integers(150)}", f"State {rng.integers(30)}", "India",
             int(rng.integers(0, 200)), 20.0, 80.0, 1000) for i in range(n)]
    write_places(tmp_path, rows)
    text = make_client(tmp_path / "nothing", tmp_path).get("/api/places").text
    assert len(text) < 1_500_000


def test_places_without_the_table_is_a_404_naming_the_build_command_and_no_local_path(client, tmp_path):
    response = client.get("/api/places")
    assert response.status_code == 404
    detail = response.json()["detail"]
    assert "aetherguard.serve.places build" in detail and str(tmp_path) not in detail


def test_places_with_an_unreadable_table_is_a_404_not_a_500(client, tmp_path):
    (tmp_path / "places").mkdir()
    (tmp_path / "places" / pl.TABLE_NAME).write_bytes(b"not parquet")
    assert client.get("/api/places").status_code == 404
    pd.DataFrame({"cell_id": [1]}).to_parquet(tmp_path / "places" / pl.TABLE_NAME)
    assert client.get("/api/places").status_code == 404


def test_places_is_cached_until_the_file_changes(client, tmp_path, monkeypatch):
    write_places(tmp_path)
    reads = []
    original = pl.read_table
    monkeypatch.setattr(pl, "read_table", lambda path: reads.append(path) or original(path))
    first = client.get("/api/places").json()
    assert client.get("/api/places").json() == first
    assert len(reads) <= 1
    write_places(tmp_path, PLACE_ROWS[:1])
    assert client.get("/api/places").json()["n"] == 1


def test_cell_history_carries_the_place_of_the_cell(client, tmp_path):
    write_places(tmp_path, [(1000, "Mananthavady", "Wayanad", "Kerala", "India", 8, 11.8, 76.0, 41_000)])
    place = client.get("/api/cells/1000/history").json()["place"]
    assert place == {"place": "Mananthavady", "district": "Wayanad", "state": "Kerala", "country": "India",
                     "distance_km": 8, "place_lat": 11.8, "place_lon": 76.0, "population": 41_000}


def test_cell_history_place_is_null_without_a_table_or_a_row(client, tmp_path):
    assert client.get("/api/cells/1000/history").json()["place"] is None
    write_places(tmp_path)
    assert client.get("/api/cells/1000/history").json()["place"] is None


# ---- forecast detail of one cell -----------------------------------------------------------------------------------

FORECAST_CELL = 20_000_005
RUN_DAY = "2026-08-12"


def forecast_shap(lead):
    return json.dumps([{"feature": "irain_acc_1", "value": 10.0 * lead, "contribution": 0.5 * lead},
                       {"feature": "stat_slope_mean", "value": 31.0, "contribution": -0.2}])


def forecast_reasons(risk, lead, causes=""):
    return json.dumps({"level": "Warning", "raw_level": "Warning", "codes": ["risk_above_warning"],
                       "risk": {"point": risk, "lo": risk / 2, "hi": risk * 2, "per_100k": risk * 1e5},
                       "confidence": {"state": "Degraded", "causes": [c for c in causes.split(";") if c]},
                       "sources": {"imd_acc_1": None, "chirps_acc_1": None, "station_max_1": None, "rain_source": "gfs"},
                       "sensor_trust": {"n_stations": 0, "n_trusted": 0, "n_flagged_7d": 0, "n_out_of_distribution": 0,
                                        "flagged_types": []},
                       "shap": json.loads(forecast_shap(lead))})


def write_forecast(live_dir, day=RUN_DAY, leads=(1, 2, 3), detail=True, features=True):
    """Alert, risk_D<lead> and features_D<lead> tables of one live run, with (or without) the per-lead detail."""
    observed = json.dumps({"sources": {"imd_acc_1": 8.0, "chirps_acc_1": 19.6, "rain_source": "imerg"}})
    folder = write_run(live_dir, day, leads=(0,), extra={"reasons_json": [observed, "{}", "{}"]})
    for lead in leads:
        table = pd.DataFrame({"cell_id": [FORECAST_CELL, 5], "date": pd.Timestamp(day) + pd.Timedelta(days=lead),
                              "lat": [11.55, 11.6], "lon": [76.15, 76.2], "region": ["western_ghats", None],
                              "risk": [1e-4 * lead, np.nan], "risk_lo": [5e-5 * lead, np.nan],
                              "risk_hi": [3e-4 * lead, np.nan], "risk_per_100k": [10.0 * lead, np.nan],
                              "level": np.int8([2, 0]), "level_name": ["Warning", "Normal"],
                              "confidence": ["Degraded", "Insufficient"],
                              "confidence_causes": ["forecast_uncertainty_uncalibrated", "forecast_input_missing"],
                              "widened": [False, False]})
        if detail:
            table["shap_json"] = [forecast_shap(lead), "[]"]
            table["reasons_json"] = [forecast_reasons(1e-4 * lead, lead, "forecast_uncertainty_uncalibrated"), "{}"]
        table.to_parquet(folder / f"risk_D{lead}.parquet", index=False)
        if features:
            gfs = {f"gfs_rain_d{k}": [20.0 * k + lead, np.nan] for k in range(1, lead + 1)}
            pd.DataFrame({"cell_id": [FORECAST_CELL, 5], "date": pd.Timestamp(day) + pd.Timedelta(days=lead),
                          "irain_acc_1": [10.0 * lead, 1.0], **gfs}).to_parquet(folder / f"features_D{lead}.parquet", index=False)
    return folder


def forecast_cell(client, lead, cell=FORECAST_CELL, day=RUN_DAY, **params):
    return client.get(f"/risk/cell/{cell}", params={"date": day, "lead": lead, **params})


def test_a_forecast_cell_reads_its_own_leads_table_and_says_what_it_is(client, tmp_path):
    write_forecast(tmp_path / "live")
    body = forecast_cell(client, 3).json()
    assert (body["lead"], body["forecast"], body["issued_date"], body["target_date"]) == (3, True, RUN_DAY, "2026-08-15")
    assert body["date"] == RUN_DAY and body["set"] == "live" and body["cell_id"] == FORECAST_CELL
    assert (body["level"], body["level_name"], body["confidence"], body["widened"]) == (2, "Warning", "Degraded", False)
    assert body["risk"] == pytest.approx(3e-4) and body["risk_lo"] == pytest.approx(1.5e-4) and body["risk_hi"] == pytest.approx(9e-4)
    assert body["confidence_causes"] == ["forecast_uncertainty_uncalibrated"] and body["reason_codes"] == ["risk_above_warning"]
    assert body["detail_missing"] is None and body["lat"] == 11.55 and body["region"] == "western_ghats"


def test_a_forecast_cell_has_the_shap_of_that_lead(client, tmp_path):
    write_forecast(tmp_path / "live")
    assert [f["contribution"] for f in forecast_cell(client, 1).json()["shap"]] == [0.5, -0.2]
    assert [f["contribution"] for f in forecast_cell(client, 3).json()["shap"]] == [1.5, -0.2]
    assert forecast_cell(client, 3).json()["shap"][0]["value"] == 30.0


def test_a_forecast_cell_reports_the_observed_rain_through_d_and_the_gfs_days_to_the_target(client, tmp_path):
    write_forecast(tmp_path / "live")
    rain = forecast_cell(client, 3).json()["rain"]
    assert rain["unit"] == "mm/day" and rain["observed_date"] == RUN_DAY
    assert rain["observed"]["imd_acc_1"] == 8.0 and rain["observed"]["chirps_acc_1"] == 19.6
    assert rain["forecast"] == [{"date": "2026-08-13", "lead": 1, "mm": 23.0}, {"date": "2026-08-14", "lead": 2, "mm": 43.0},
                                {"date": "2026-08-15", "lead": 3, "mm": 63.0}]
    assert [d["lead"] for d in forecast_cell(client, 1).json()["rain"]["forecast"]] == [1]


def test_a_forecast_cell_leaves_the_sources_without_values_and_says_why(client, tmp_path):
    write_forecast(tmp_path / "live")
    body = forecast_cell(client, 2).json()
    assert body["sources"]["imd_acc_1"] is None and body["sources"]["station_max_1"] is None
    assert body["sensor_trust"]["n_stations"] == 0
    assert "gauge" in body["unavailable"] and "GFS" in body["unavailable"]


def test_lead_zero_is_the_default_and_unchanged(client, tmp_path):
    default = client.get("/risk/cell/1000", params={"date": "2024-07-06"}).json()
    explicit = client.get("/risk/cell/1000", params={"date": "2024-07-06", "lead": 0}).json()
    assert default == explicit
    assert (default["lead"], default["forecast"], default["rain"], default["detail_missing"]) == (0, False, None, None)
    assert default["issued_date"] == default["target_date"] == "2024-07-06"


def test_a_run_that_predates_per_lead_detail_returns_what_exists(client, tmp_path):
    write_forecast(tmp_path / "live", detail=False, features=False)
    response = forecast_cell(client, 3)
    body = response.json()
    assert response.status_code == 200 and body["detail_missing"] == "this run predates per-lead detail"
    assert body["level"] == 2 and body["risk"] == pytest.approx(3e-4) and body["shap"] == [] and body["rain"]["forecast"] == []


def test_a_run_with_shap_but_without_the_features_file_is_flagged_incomplete(client, tmp_path):
    write_forecast(tmp_path / "live", features=False)
    body = forecast_cell(client, 1).json()
    assert body["detail_missing"] == "this run predates per-lead detail" and len(body["shap"]) == 2


@pytest.mark.parametrize("cell,day,lead,params,status", [
    (FORECAST_CELL, "2026-08-11", 1, {}, 404),           # no run that day
    (FORECAST_CELL, RUN_DAY, 4, {}, 422),                # lead out of range
    (999, RUN_DAY, 1, {}, 404),                          # a cell the run did not score
    (FORECAST_CELL, RUN_DAY, 1, {"set": "case_a"}, 404),  # replay sets hold lead 0 only
])
def test_forecast_cell_errors(client, tmp_path, cell, day, lead, params, status):
    write_forecast(tmp_path / "live")
    assert forecast_cell(client, lead, cell, day, **params).status_code == status


def test_a_lead_the_run_did_not_publish_is_a_404(client, tmp_path):
    write_forecast(tmp_path / "live", leads=(1,))
    assert forecast_cell(client, 1).status_code == 200
    response = forecast_cell(client, 2)
    assert response.status_code == 404 and "no lead-2 forecast" in response.json()["detail"]


def test_forecast_cell_carries_its_place(client, tmp_path):
    write_forecast(tmp_path / "live")
    write_places(tmp_path, [(FORECAST_CELL, "Mananthavady", "Wayanad", "Kerala", "India", 8, 11.8, 76.0, 41_000)])
    assert forecast_cell(client, 2).json()["place"]["place"] == "Mananthavady"


def test_history_lists_the_forecast_points_of_the_run(client, tmp_path):
    live = tmp_path / "live"
    write_forecast(live)
    body = client.get(f"/api/cells/{FORECAST_CELL}/history", params={"set": "live"}).json()
    assert body["issued_date"] == RUN_DAY
    assert [(p["lead"], p["target_date"]) for p in body["forecast"]] == [(1, "2026-08-13"), (2, "2026-08-14"), (3, "2026-08-15")]
    assert body["forecast"][2]["risk"] == pytest.approx(3e-4) and body["forecast"][2]["level"] == 2
    assert body["forecast"][0]["risk_hi"] == pytest.approx(3e-4)


def test_history_has_no_forecast_points_for_a_replay_set(client, tmp_path):
    assert client.get("/api/cells/1000/history").json()["forecast"] == []


# ---- section 12: certainty, forecast source, capped-level numbers ----------------------------------------------------

def add_certainty(folder, lead, kinds=("depends_on_forecast", None), low=(0, 0), high=(3, 0)):
    path = folder / f"risk_D{lead}.parquet"
    table = pd.read_parquet(path)
    table["certainty"], table["level_min"], table["level_max"] = list(kinds), np.int8(low), np.int8(high)
    table.to_parquet(path, index=False)


def write_run_json(folder, source="ecmwf_hres", fallback=False, minimum=None):
    leads = {str(k): {"forecast": {"source": source, "label": "ECMWF IFS HRES (CC BY 4.0)" if source.startswith("ecmwf") else "NOAA GFS",
                                   "mapped": False, "fallback": fallback, "cycle": "2026-08-11T12:00:00+00:00"}} for k in (1, 2, 3)}
    (folder / "run.json").write_text(json.dumps({"leads": leads, "post_rules": {"parameters": {"rain_minimum_mm": minimum or {"7": 11.5}}}}))


def test_a_forecast_cell_carries_its_certainty_range_and_rain_source(client, tmp_path):
    folder = write_forecast(tmp_path / "live")
    add_certainty(folder, 2)
    write_run_json(folder)
    body = forecast_cell(client, 2).json()
    assert (body["certainty"], body["level_min"], body["level_max"]) == ("depends_on_forecast", 0, 3)
    assert body["forecast_source"] == {"source": "ecmwf_hres", "label": "ECMWF IFS HRES (CC BY 4.0)", "mapped": False,
                                       "fallback": False, "cycle": "2026-08-11T12:00:00+00:00",
                                       "attribution": "Contains ECMWF open data (IFS), licensed CC BY 4.0"}
    assert "ECMWF IFS HRES (CC BY 4.0) forecast" in body["unavailable"]


def test_a_gfs_forecast_has_no_attribution_and_a_run_without_run_json_names_gfs(client, tmp_path):
    folder = write_forecast(tmp_path / "live")
    write_run_json(folder, source="gfs", fallback=True)
    assert forecast_cell(client, 1).json()["forecast_source"]["attribution"] is None
    (folder / "run.json").unlink()
    body = forecast_cell(client, 1).json()
    assert body["forecast_source"] is None and body["certainty"] is None and "GFS forecast" in body["unavailable"]


def test_grid_of_a_forecast_lead_has_certainty_bytes_and_the_source(client, tmp_path):
    folder = write_forecast(tmp_path / "live")
    add_certainty(folder, 2)
    write_run_json(folder)
    body = client.get("/api/grid", params={"date": RUN_DAY, "lead": 2}).json()
    cells = np.frombuffer(base64.b64decode(body["cells"]), "<u4")
    certainty = np.frombuffer(base64.b64decode(body["certainty"]), "u1")
    assert dict(zip(cells.tolist(), certainty.tolist())) == {5: 0, FORECAST_CELL: 2}
    assert np.frombuffer(base64.b64decode(body["level_max"]), "u1").tolist() == [dict(zip([5, FORECAST_CELL], [0, 3]))[c] for c in cells]
    assert body["forecast"]["label"] == "ECMWF IFS HRES (CC BY 4.0)" and body["forecast"]["fallback"] is False
    lead_zero = client.get("/api/grid", params={"date": RUN_DAY, "lead": 0}).json()
    assert "certainty" not in lead_zero and "forecast" not in lead_zero


def test_grid_of_a_table_from_before_section_12_has_no_certainty(client, tmp_path):
    write_forecast(tmp_path / "live")
    body = client.get("/api/grid", params={"date": RUN_DAY, "lead": 1}).json()
    assert "certainty" not in body and body["forecast"] is None


def test_a_capped_forecast_row_reports_the_rain_behind_the_cap(client, tmp_path):
    folder = write_forecast(tmp_path / "live")
    path = folder / "risk_D1.parquet"
    table = pd.read_parquet(path)
    table["reasons_json"] = [json.dumps({**json.loads(r), "codes": ["risk_above_warning", "no_recent_rain"],
                                         "rain_rule": {"passed": False, "exempt": False, "capped": True}}) if r != "{}" else r
                             for r in table["reasons_json"]]
    table.to_parquet(path, index=False)
    features = pd.read_parquet(folder / "features_D1.parquet")
    features["irain_acc_7"] = [4.25, 1.0]
    features.to_parquet(folder / "features_D1.parquet", index=False)
    write_run_json(folder)
    rule = forecast_cell(client, 1).json()["rain_rule"]
    assert rule == {"passed": False, "exempt": False, "capped": True, "window_days": 7, "rain_mm": 4.25, "minimum_mm": 11.5,
                    "capped_to": "Warning"}


def test_a_rule_that_did_not_cap_is_returned_as_it_is(client, tmp_path):
    folder = write_forecast(tmp_path / "live")
    write_run_json(folder)
    assert dash_api.rain_rule_detail(folder.parent, RUN_DAY, 1, FORECAST_CELL, {"passed": True, "capped": False}, "Watch") == {
        "passed": True, "capped": False}
    assert dash_api.rain_rule_detail(folder.parent, RUN_DAY, 1, FORECAST_CELL, None, "Watch") is None
    assert dash_api.rain_rule_detail(folder.parent, "2026-01-01", 1, FORECAST_CELL, {"capped": True}, "Watch") == {"capped": True}


# ---- thresholds of one cell ----------------------------------------------------------------------------------------

def live_store_client(tmp_path):
    _, store = build_store(tmp_path, {"live": {"n_cells": 2, "n_days": 2, "start": "2024-08-01"}})
    return make_client(store, tmp_path)


def write_run_model(tmp_path, day, **model):
    folder = tmp_path / "live" / day
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "run.json").write_text(json.dumps({"model": model}))


def test_a_live_cell_carries_the_thresholds_its_region_was_levelled_against(tmp_path):
    client = live_store_client(tmp_path)
    write_run_model(tmp_path, "2024-08-02", thresholds=POOLED, thresholds_by_region=BY_REGION)
    body = client.get("/risk/cell/1000", params={"date": "2024-08-02"}).json()
    assert body["region"] == "western_ghats" and body["thresholds_region"] == "western_ghats"
    assert body["thresholds"]["emergency"] == 2.56e-5 and body["thresholds"]["source"].endswith("[western_ghats]")


def test_a_live_cell_without_regional_thresholds_gets_the_runs_pooled_ones(tmp_path):
    client = live_store_client(tmp_path)
    write_run_model(tmp_path, "2024-08-02", thresholds=POOLED, thresholds_by_region={"himalaya": BY_REGION["himalaya"]})
    body = client.get("/risk/cell/1000", params={"date": "2024-08-02"}).json()
    assert (body["thresholds_region"], body["thresholds"]["emergency"]) == ("pooled", 4.81e-5)


def test_a_live_date_without_a_usable_run_summary_keeps_the_stores_thresholds(tmp_path):
    client = live_store_client(tmp_path)
    body = client.get("/risk/cell/1000", params={"date": "2024-08-02"}).json()
    assert (body["thresholds_region"], body["thresholds"]["emergency"]) == (None, 1e-4)


def test_a_live_cell_uses_the_run_of_its_own_date(tmp_path):
    client = live_store_client(tmp_path)
    write_run_model(tmp_path, "2024-08-01", thresholds=POOLED, thresholds_by_region={"western_ghats": {**BY_REGION["western_ghats"], "emergency": 7e-5}})
    write_run_model(tmp_path, "2024-08-02", thresholds=POOLED, thresholds_by_region=BY_REGION)
    assert client.get("/risk/cell/1000", params={"date": "2024-08-01"}).json()["thresholds"]["emergency"] == 7e-5


def test_a_replay_cell_keeps_the_stores_thresholds(client, tmp_path):
    write_run_model(tmp_path, "2024-07-06", thresholds=POOLED, thresholds_by_region=BY_REGION)
    body = client.get("/risk/cell/1003", params={"date": "2024-07-06"}).json()
    assert (body["thresholds_region"], body["thresholds"]["emergency"]) == (None, 1e-4)


def test_a_forecast_cell_carries_the_thresholds_of_its_region_in_the_run(client, tmp_path):
    write_forecast(tmp_path / "live")
    write_run_model(tmp_path, RUN_DAY, thresholds=POOLED, thresholds_by_region=BY_REGION)
    body = forecast_cell(client, 2).json()
    assert (body["thresholds_region"], body["thresholds"]["emergency"]) == ("western_ghats", 2.56e-5)
