"""API endpoints on a fixture replay store (TestClient, no network, no real data)."""
from dataclasses import replace

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from aetherguard.serve import api
from aetherguard.serve import places as pl
from alerts_store_helpers import build_store

SETS = {"case_a": {"n_cells": 4, "n_days": 6, "positive_cells": (1,)},
        "case_b": {"n_cells": 2, "n_days": 4, "start": "2024-07-04"}}


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    _, root = build_store(tmp_path_factory.mktemp("api"), SETS)
    return TestClient(api.create_app(root))


@pytest.fixture(autouse=True)
def no_places(client, tmp_path):
    """Hermetic: the place table is looked up in tmp_path, never in the project data."""
    client.app.state.dash = replace(client.app.state.dash, places_dir=tmp_path / "places")


@pytest.fixture
def built_places(tmp_path):
    folder = tmp_path / "places"
    folder.mkdir()
    pd.DataFrame([(1003, "Mananthavady", "Wayanad", "Kerala", "India", 8, 11.8, 76.0, 41000)],
                 columns=pl.TABLE_COLUMNS).to_parquet(folder / pl.TABLE_NAME, index=False)


@pytest.fixture(autouse=True)
def verified_freeze(monkeypatch):
    monkeypatch.setattr(api, "verify_freeze", lambda: {"created_utc": "2026-10-03T11:39:44Z"})
    monkeypatch.setattr(api, "_freeze_status", lambda: ("verified", "2026-10-03T11:39:44Z", None))


def test_health_reports_versions_card_hash_thresholds_and_store_status(client):
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["data_manifest_status"] == "ok"
    assert body["model_freeze_status"] == "verified" and body["model_frozen_utc"] == "2026-10-03T11:39:44Z"
    assert body["aetherguard_version"] and body["python"] and "fastapi" in body["packages"]
    assert body["model_card_sha256"] == "0" * 64 and body["thresholds"]["source"] == "test"
    assert body["sets"]["case_a"] == {"first_date": "2024-07-01", "last_date": "2024-07-06", "n_days": 6, "n_rows": 24}


def test_health_without_a_store_is_degraded_not_an_error(tmp_path):
    body = TestClient(api.create_app(tmp_path / "nothing")).get("/health").json()
    assert body["status"] == "degraded" and body["data_manifest_status"] == "missing" and body["sets"] == {}


def test_risk_lists_the_cells_of_a_day_sorted_by_risk(client):
    body = client.get("/risk", params={"date": "2024-07-06"}).json()
    assert body["set"] == "case_a" and body["n_cells"] == 4 and len(body["cells"]) == 4
    risks = [c["risk"] for c in body["cells"]]
    assert risks == sorted(risks, reverse=True)
    assert sum(body["level_counts"].values()) == 4 and body["thresholds"]["watch"] == 1e-5
    first = body["cells"][0]
    assert {"cell_id", "lat", "lon", "region", "risk", "level", "level_name", "confidence", "reason_codes"} <= set(first)
    assert first["level_name"] in ("Normal", "Watch", "Warning", "Emergency")


def test_risk_filters_by_set_region_bbox_level_and_limit(client):
    assert client.get("/risk", params={"date": "2024-07-05", "set": "case_b"}).json()["n_cells"] == 2
    assert client.get("/risk", params={"date": "2024-07-06", "region": "western_ghats"}).json()["n_cells"] == 4
    assert client.get("/risk", params={"date": "2024-07-06", "region": "himalaya"}).json()["n_cells"] == 0
    box = client.get("/risk", params={"date": "2024-07-06", "bbox": "75,11.4,77,11.55"}).json()
    assert box["n_cells"] == 2                                     # lat 11.5 and 11.55
    high = client.get("/risk", params={"date": "2024-07-06", "min_level": "warning"}).json()
    assert all(c["level"] >= 2 for c in high["cells"]) and 0 < high["n_cells"] < 4
    limited = client.get("/risk", params={"date": "2024-07-06", "limit": 1}).json()
    assert len(limited["cells"]) == 1 and limited["n_cells"] == 4


@pytest.mark.parametrize("params, status", [
    ({"date": "2024-7-6"}, 422), ({"date": "2024-13-45"}, 422), ({"date": "2030-01-01"}, 404),
    ({"date": "2024-07-06", "set": "nope"}, 404), ({"date": "2024-07-06", "bbox": "1,2,3"}, 422),
    ({"date": "2024-07-06", "bbox": "77,11,75,12"}, 422), ({"date": "2024-07-06", "min_level": "severe"}, 422),
    ({}, 422), ({"date": "2024-07-06", "limit": 0}, 422)])
def test_risk_rejects_bad_input_with_clear_status(client, params, status):
    response = client.get("/risk", params=params)
    assert response.status_code == status and response.json()["detail"]


def test_a_missing_date_names_the_available_range(client):
    assert "available 2024-07-01..2024-07-07" in client.get("/risk", params={"date": "2030-01-01"}).json()["detail"]


def test_cell_explanation_is_complete_and_consistent_with_the_risk_list(client):
    listed = {c["cell_id"]: c for c in client.get("/risk", params={"date": "2024-07-06"}).json()["cells"]}
    body = client.get("/risk/cell/1003", params={"date": "2024-07-06"}).json()
    assert body["level"] == listed[1003]["level"] and body["confidence"] == listed[1003]["confidence"]
    assert body["risk"] == listed[1003]["risk"] and body["risk_lo"] < body["risk"] < body["risk_hi"]
    assert body["shap"][0] == {"feature": "rain_acc_1", "value": pytest.approx(body["shap"][0]["value"]),
                               "contribution": 0.5}
    assert set(body["sources"]) >= {"imd_acc_1", "chirps_acc_1", "station_max_1", "spread_1day", "dis_ratio_3"}
    assert set(body["sensor_trust"]) == {"n_stations", "n_trusted", "n_flagged_7d", "n_out_of_distribution",
                                         "flagged_types"}
    assert body["thresholds"]["emergency"] == 1e-4 and body["raw_level"] in ("Normal", "Watch", "Warning", "Emergency")
    assert isinstance(body["confidence_causes"], list) and isinstance(body["reason_codes"], list)


def test_cell_explanation_carries_the_place_when_the_table_has_the_cell(built_places, client):
    body = client.get("/risk/cell/1003", params={"date": "2024-07-06"}).json()
    assert body["place"] == {"place": "Mananthavady", "district": "Wayanad", "state": "Kerala", "country": "India",
                             "distance_km": 8, "place_lat": 11.8, "place_lon": 76.0, "population": 41000}
    assert client.get("/risk/cell/1002", params={"date": "2024-07-06"}).json()["place"] is None


def test_cell_explanation_place_is_null_without_a_table(client):
    assert client.get("/risk/cell/1003", params={"date": "2024-07-06"}).json()["place"] is None


def test_cell_explanation_errors(client):
    assert client.get("/risk/cell/9", params={"date": "2024-07-06"}).status_code == 404
    assert client.get("/risk/cell/1003", params={"date": "2030-01-01"}).status_code == 404
    assert client.get("/risk/cell/notanumber", params={"date": "2024-07-06"}).status_code == 422


def test_sensors_return_trust_state_and_filter_by_bbox(client):
    body = client.get("/sensors", params={"date": "2024-07-03"}).json()
    by = {s["station"]: s for s in body["stations"]}
    assert body["n_stations"] == 2 and sum(body["state_counts"].values()) == 2
    assert by["B"]["state"] == "trusted" and by["B"]["trust"] == pytest.approx(0.95)
    assert {"fault_type", "flagged", "genuine_extreme", "reasons", "ood", "flag_rate_window"} <= set(by["A"])
    inside = client.get("/sensors", params={"date": "2024-07-03", "bbox": "75.9,11.45,76.05,11.55"}).json()
    assert [s["station"] for s in inside["stations"]] == ["A"]
    assert client.get("/sensors", params={"date": "2030-01-01"}).status_code == 404


def test_alerts_list_has_reasons_sorted_and_filtered_by_level(client):
    body = client.get("/alerts", params={"start": "2024-07-01", "end": "2024-07-06"}).json()
    assert body["min_level"] == "Watch" and body["n_alerts"] == len(body["alerts"]) > 0 and not body["truncated"]
    assert all(a["level"] >= 1 for a in body["alerts"])
    dates = [a["date"] for a in body["alerts"]]
    assert dates == sorted(dates)
    first = body["alerts"][0]
    assert first["reasons"]["shap"][0]["feature"] == "rain_acc_1" and "state" in first["reasons"]["confidence"]
    strict = client.get("/alerts", params={"start": "2024-07-01", "end": "2024-07-06", "min_level": "Emergency"}).json()
    assert strict["n_alerts"] <= body["n_alerts"] and all(a["level"] == 3 for a in strict["alerts"])
    cut = client.get("/alerts", params={"start": "2024-07-01", "end": "2024-07-06", "limit": 2}).json()
    assert len(cut["alerts"]) == 2 and cut["truncated"] and cut["n_alerts"] == body["n_alerts"]


def test_alerts_with_nothing_in_range_is_empty_and_bad_ranges_are_rejected(client):
    empty = client.get("/alerts", params={"start": "2030-01-01", "end": "2030-01-05"}).json()
    assert empty["n_alerts"] == 0 and empty["alerts"] == []
    assert client.get("/alerts", params={"start": "2024-07-06", "end": "2024-07-01"}).status_code == 422
    assert client.get("/alerts", params={"start": "2024-07-01", "end": "2024-07-06", "min_level": "x"}).status_code == 422
    assert client.get("/alerts", params={"start": "2024-07-01", "end": "2024-07-06", "set": "nope"}).status_code == 404


def test_the_api_is_read_only(client):
    methods = {m for route in client.app.routes for m in getattr(route, "methods", set())}
    assert methods <= {"GET", "HEAD"}
    assert client.post("/risk", params={"date": "2024-07-06"}).status_code == 405


def test_main_binds_the_loopback_address_only(monkeypatch):
    calls = []
    monkeypatch.setattr(api.uvicorn, "run", lambda *a, **kw: calls.append((a, kw)))
    assert api.main(["--port", "8123"]) == 0
    assert calls == [(("aetherguard.serve.api:app",), {"host": "127.0.0.1", "port": 8123})]
    assert api.HOST == "127.0.0.1"


def test_the_store_directory_comes_from_the_environment(tmp_path, monkeypatch):
    _, root = build_store(tmp_path, {"case_a": SETS["case_a"]})
    monkeypatch.setenv(api.STORE_ENV, str(root))
    assert TestClient(api.create_app()).get("/health").json()["data_manifest_status"] == "ok"


def test_health_is_degraded_when_the_model_freeze_does_not_verify(client, monkeypatch):
    monkeypatch.setattr(api, "_freeze_status", lambda: ("mismatch", None, "model differs from its freeze record"))
    body = client.get("/health").json()
    assert body["status"] == "degraded" and body["model_freeze_status"] == "mismatch"
    assert "differs" in body["model_freeze_detail"]


def test_freeze_status_reads_the_freeze_record(monkeypatch, tmp_path):
    from aetherguard.hazard import model as hm
    monkeypatch.undo()
    monkeypatch.setattr(hm, "default_model_dir", lambda: tmp_path)
    assert api._freeze_status() == ("not_frozen", None, "FROZEN.json not found")
    (tmp_path / "FROZEN.json").write_text("{}")
    monkeypatch.setattr(api, "verify_freeze", lambda: (_ for _ in ()).throw(api.FrozenMismatchError("changed")))
    assert api._freeze_status() == ("mismatch", None, "changed")
    monkeypatch.setattr(api, "verify_freeze", lambda: {"created_utc": "t"})
    assert api._freeze_status() == ("verified", "t", None)
