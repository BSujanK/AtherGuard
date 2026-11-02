"""Parity of the dashboard API with the published tables (live.audit_parity), against a stand-in for the API."""
import json
from datetime import date

import numpy as np
import pandas as pd

from aetherguard.live import audit_parity as ap
from aetherguard.serve import dash_api
from aetherguard.serve import places as pl

DAY = "2026-10-20"
N = 40


def _table(lead):
    risk = np.linspace(1e-7, 1e-3, N)
    level = np.repeat(np.int8([0, 1, 2, 3]), N // 4)
    sources = {"imd_acc_1": 4.5, "chirps_acc_1": 3.5}
    frame = pd.DataFrame({
        "cell_id": 19_000_000 + np.arange(N), "date": pd.Timestamp(DAY) + pd.Timedelta(days=lead), "lead": np.int8(lead),
        "risk": risk, "risk_lo": risk / 2, "risk_hi": risk * 2, "risk_per_100k": risk * 1e5, "level": level,
        "level_name": np.array(["Normal", "Watch", "Warning", "Emergency"], dtype=object)[level],
        "confidence": "Degraded", "confidence_causes": "forecast_day;x", "reasons_json": json.dumps({"sources": sources})})
    if lead:
        frame["certainty"] = "firm"
        frame["level_min"], frame["level_max"] = frame["level"], frame["level"]
    return frame


def _places(cells):
    return pd.DataFrame({"cell_id": cells, "place": "Town", "district": "D", "state": "S", "country": "India", "distance_km": 3,
                         "place_lat": 11.0, "place_lon": 76.0, "population": 100}).set_index("cell_id", drop=False)


class FakeApi:
    """Serves /api/grid and /risk/cell/{id} from the tables, with optional planted differences."""

    def __init__(self, tables, places, features):
        self.tables, self.places, self.features = tables, places, features
        self.risk_shift = {}
        self.wrong_place = set()

    def __call__(self, base, path, **params):
        lead = int(params["lead"])
        table = self.tables[lead].sort_values("cell_id")
        if path == "/api/grid":
            return {"cells": dash_api._encode(table["cell_id"], "<u4"), "risk": dash_api._encode(table["risk"], "<f4"),
                    "risk_hi": dash_api._encode(table["risk_hi"], "<f4"), "level": dash_api._encode(table["level"], "u1"),
                    "confidence": dash_api._encode(table["confidence"].map(dash_api.CONFIDENCE_CODES), "u1")}
        cell = int(path.rsplit("/", 1)[1])
        row = table[table["cell_id"] == cell].iloc[0]
        out = {k: (None if pd.isna(row[k]) else row[k].item() if hasattr(row[k], "item") else row[k]) for k in
               ("risk", "risk_lo", "risk_hi", "risk_per_100k", "level", "level_name", "confidence")}
        out["risk"] = out["risk"] * (1 + self.risk_shift.get(cell, 0.0))
        out["confidence_causes"] = row["confidence_causes"].split(";")
        out["target_date"] = pd.Timestamp(row["date"]).date().isoformat()
        out["place"] = None if cell in self.wrong_place else pl.place_record(self.places.loc[cell])
        if lead:
            out.update(certainty=row["certainty"], level_min=int(row["level_min"]), level_max=int(row["level_max"]))
            out["rain"] = {"forecast": [{"date": (date.fromisoformat(DAY) + pd.Timedelta(days=k)).isoformat(), "lead": k,
                                         "mm": float(self.features.at[cell, f"gfs_rain_d{k}"])} for k in range(1, lead + 1)]}
        else:
            out["sources"] = json.loads(row["reasons_json"])["sources"]
        return out


def _setup(tmp_path, monkeypatch):
    folder = tmp_path / DAY
    folder.mkdir()
    tables = {0: _table(0), 1: _table(1)}
    tables[0].to_parquet(folder / "alerts.parquet", index=False)
    tables[1].to_parquet(folder / "risk_D1.parquet", index=False)
    features = pd.DataFrame({"cell_id": tables[1]["cell_id"], "gfs_rain_d1": np.linspace(0, 30, N).astype(np.float32)})
    features.to_parquet(folder / "features_D1.parquet", index=False)
    places = _places(tables[0]["cell_id"].to_numpy())
    fake = FakeApi(tables, places, features.set_index("cell_id"))
    monkeypatch.setattr(ap, "_get", fake)
    return folder, places, fake


def test_a_stratified_sample_has_every_level_and_is_repeatable():
    level = np.repeat(np.int8([0, 1, 2, 3]), [900, 90, 9, 1])
    rows = ap.stratified_sample(level, 300)
    assert set(level[rows]) == {0, 1, 2, 3} and len(rows) == 300 and (np.diff(rows) > 0).all()
    assert (ap.stratified_sample(level, 300) == rows).all()
    assert len(ap.stratified_sample(level[:5], 300)) == 5


def test_an_api_that_serves_the_published_rows_has_no_mismatch(tmp_path, monkeypatch):
    folder, places, _ = _setup(tmp_path, monkeypatch)
    found = ap.Mismatches()
    for lead in (0, 1):
        assert ap.compare_lead("http://x", DAY, folder, lead, places, found) == N
    assert found.to_dict()["total"] == 0, found.examples
    assert found.compared["risk"] == 2 * N and found.compared["rain"] == 2 * N and found.compared["place"] == 2 * N


def test_each_planted_difference_is_counted_under_its_field(tmp_path, monkeypatch):
    folder, places, fake = _setup(tmp_path, monkeypatch)
    cells = _table(0)["cell_id"].to_numpy()
    fake.risk_shift[int(cells[3])] = 1e-6
    fake.wrong_place.add(int(cells[5]))
    fake.features.loc[int(cells[7]), "gfs_rain_d1"] += 1.0
    found = ap.Mismatches()
    for lead in (0, 1):
        ap.compare_lead("http://x", DAY, folder, lead, places, found)
    assert found.counts == {"risk": 2, "place": 2, "rain": 1}, found.counts


def test_main_api_writes_the_result_and_exits_two_on_a_mismatch(tmp_path, monkeypatch):
    folder, places, fake = _setup(tmp_path, monkeypatch)
    (folder / "run.json").write_text("{}", encoding="utf-8")
    fake.risk_shift[int(_table(0)["cell_id"].iloc[0])] = 0.5
    places_path = tmp_path / "places.parquet"
    places.reset_index(drop=True).to_parquet(places_path, index=False)
    cfg = {"places_table": str(places_path)}
    assert ap.main_api("http://x", cfg, tmp_path, tmp_path / "out") == ap.EXIT_VIOLATIONS
    result = json.loads((tmp_path / "out" / f"api_parity_{DAY}.json").read_text(encoding="utf-8"))
    assert result["date"] == DAY and result["mismatches"]["risk"] >= 1
