"""Parity between what the dashboard API serves and the published tables (spec section 13, check `api_parity`).

    python -m aetherguard.live.audit --api http://127.0.0.1:8790 [--out DIR]

For the newest published day and each lead 0..3, a seeded sample of SAMPLE_CELLS cells (stratified: every alert level present
in the table is represented, up to SAMPLE_CELLS / 4 cells each, the rest drawn at random) is read from `/api/grid` (risk,
risk_hi, level, confidence, flags) and `/risk/cell/{id}` (risk, lo, hi, per 100k, level and its name, confidence and its
causes, the place, the rain evidence or the forecast rain, the certainty fields) and compared with the parquet rows:

    risk / risk_hi in the grid are float32 copies (compared as float32), the cell explanation carries the float64 value;
    the place equals the row of the place table (`serve.places.place_record`);
    lead 0 rain = the `reasons_json` sources of the alerts row (imd_acc_1, chirps_acc_1, ...);
    lead k rain = `gfs_rain_d1..dk` of features_D<k>.parquet (`rain.forecast[*].mm`).

Writes `<out>/api_parity_<day>.json`; exit 2 on any mismatch, 1 when the API cannot be read.
"""
from __future__ import annotations

import base64
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from ..hazard.jsonio import dump_json
from ..serve import places as pl
from ..serve.dash_api import CONFIDENCE_CODES
from .audit import EXAMPLES, published_days
from .sources import project_path

SAMPLE_CELLS = 300
SEED = 20261024
TIMEOUT_S = 60
EXIT_VIOLATIONS = 2
FIELDS = ("risk", "risk_lo", "risk_hi", "risk_per_100k", "level", "level_name", "confidence", "confidence_causes", "place",
          "rain", "certainty", "lead", "date")


def stratified_sample(level: np.ndarray, n: int, seed: int = SEED) -> np.ndarray:
    """Row positions of an `n`-sample (all rows if fewer) with every level present, at most n / 4 rows per level first."""
    rng = np.random.default_rng(seed)
    chosen: list[int] = []
    for value in np.unique(level):
        rows = np.flatnonzero(level == value)
        chosen.extend(rng.choice(rows, size=min(len(rows), max(1, n // 4)), replace=False).tolist())
    rest = np.setdiff1d(np.arange(len(level)), chosen)
    if len(chosen) < n and len(rest):
        chosen.extend(rng.choice(rest, size=min(n - len(chosen), len(rest)), replace=False).tolist())
    return np.sort(np.array(chosen[:max(n, len(np.unique(level)))], dtype=np.int64))


def _same(a, b, rel: float = 1e-12) -> bool:
    if a is None or b is None or (isinstance(a, float) and np.isnan(a)) or (isinstance(b, float) and np.isnan(b)):
        return (a is None or (isinstance(a, float) and np.isnan(a))) and (b is None or (isinstance(b, float) and np.isnan(b)))
    return abs(float(a) - float(b)) <= rel * max(abs(float(a)), abs(float(b)))


class Mismatches:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.examples: dict[str, list[dict]] = {}
        self.compared: dict[str, int] = {}

    def check(self, field: str, cell: int, lead: int, served, published, equal: bool) -> None:
        self.compared[field] = self.compared.get(field, 0) + 1
        if equal:
            return
        self.counts[field] = self.counts.get(field, 0) + 1
        if len(self.examples.setdefault(field, [])) < EXAMPLES:
            self.examples[field].append({"cell_id": cell, "lead": lead, "served": served, "published": published})

    def to_dict(self) -> dict:
        return {"compared": self.compared, "mismatches": self.counts, "examples": self.examples,
                "total": int(sum(self.counts.values()))}


def decode(payload: dict, key: str, dtype: str) -> np.ndarray:
    return np.frombuffer(base64.b64decode(payload[key]), dtype=dtype)


def _get(base: str, path: str, **params) -> dict:
    response = requests.get(base.rstrip("/") + path, params=params, timeout=TIMEOUT_S)
    response.raise_for_status()
    return response.json()


def _published(day_dir: Path, lead: int) -> pd.DataFrame:
    return pd.read_parquet(day_dir / ("alerts.parquet" if lead == 0 else f"risk_D{lead}.parquet"))


def compare_lead(base: str, day: str, day_dir: Path, lead: int, places: pd.DataFrame | None, found: Mismatches,
                 n: int = SAMPLE_CELLS, seed: int = SEED) -> int:
    """Compare a sample of one lead; returns the number of cells sampled."""
    table = _published(day_dir, lead).sort_values("cell_id", kind="stable").reset_index(drop=True)
    grid = _get(base, "/api/grid", date=day, lead=lead)
    cells = decode(grid, "cells", "<u4")
    found.check("grid.cells", -1, lead, cells.tolist()[:3], table["cell_id"].tolist()[:3],
                len(cells) == len(table) and bool((cells == table["cell_id"].to_numpy()).all()))
    served = {"risk": decode(grid, "risk", "<f4"), "risk_hi": decode(grid, "risk_hi", "<f4"),
              "level": decode(grid, "level", "u1"), "confidence": decode(grid, "confidence", "u1")}
    rows = stratified_sample(table["level"].to_numpy(), n, seed + lead)
    features = None
    if lead > 0 and (day_dir / f"features_D{lead}.parquet").is_file():
        features = pd.read_parquet(day_dir / f"features_D{lead}.parquet").set_index("cell_id")
    for i in rows:
        row = table.iloc[i]
        cell = int(row["cell_id"])
        if len(cells) == len(table):
            for name in ("risk", "risk_hi"):
                found.check(f"grid.{name}", cell, lead, float(served[name][i]), float(row[name]),
                            _same(float(served[name][i]), float(np.float32(row[name])), 0.0))
            found.check("grid.level", cell, lead, int(served["level"][i]), int(row["level"]), int(served["level"][i]) == int(row["level"]))
            found.check("grid.confidence", cell, lead, int(served["confidence"][i]), row["confidence"],
                        int(served["confidence"][i]) == CONFIDENCE_CODES[row["confidence"]])
        detail = _get(base, f"/risk/cell/{cell}", date=day, lead=lead)
        for name in ("risk", "risk_lo", "risk_hi", "risk_per_100k"):
            found.check(name, cell, lead, detail.get(name), None if pd.isna(row[name]) else float(row[name]),
                        _same(detail.get(name), None if pd.isna(row[name]) else float(row[name])))
        found.check("level", cell, lead, detail.get("level"), int(row["level"]), detail.get("level") == int(row["level"]))
        found.check("level_name", cell, lead, detail.get("level_name"), row["level_name"], detail.get("level_name") == row["level_name"])
        found.check("confidence", cell, lead, detail.get("confidence"), row["confidence"], detail.get("confidence") == row["confidence"])
        causes = [c for c in str(row["confidence_causes"] or "").split(";") if c]
        found.check("confidence_causes", cell, lead, detail.get("confidence_causes"), causes, detail.get("confidence_causes") == causes)
        found.check("date", cell, lead, detail.get("target_date"), pd.Timestamp(row["date"]).date().isoformat(),
                    detail.get("target_date") == pd.Timestamp(row["date"]).date().isoformat())
        if "certainty" in table.columns and lead > 0:
            published = row["certainty"] if isinstance(row["certainty"], str) else None
            found.check("certainty", cell, lead, [detail.get("certainty"), detail.get("level_min"), detail.get("level_max")],
                        [published, int(row["level_min"]), int(row["level_max"])],
                        [detail.get("certainty"), detail.get("level_min"), detail.get("level_max")] ==
                        [published, int(row["level_min"]), int(row["level_max"])])
        if places is not None:
            label = places.loc[cell] if cell in places.index else None
            expected = None if label is None else pl.place_record(label)
            found.check("place", cell, lead, detail.get("place"), expected, detail.get("place") == expected)
        reasons = json.loads(row["reasons_json"]) if "reasons_json" in table.columns else None
        if lead == 0 and reasons is not None:
            sources = {k: v for k, v in reasons.get("sources", {}).items()}
            found.check("rain", cell, lead, detail.get("sources"), sources, detail.get("sources") == sources)
        elif lead > 0 and features is not None and cell in features.index:
            forecast = [{"date": (date.fromisoformat(day) + pd.Timedelta(days=k)).isoformat(), "lead": k,
                         "mm": None if pd.isna(features.at[cell, f"gfs_rain_d{k}"]) else float(features.at[cell, f"gfs_rain_d{k}"])}
                        for k in range(1, lead + 1)]
            served_rain = (detail.get("rain") or {}).get("forecast")
            found.check("rain", cell, lead, served_rain, forecast, served_rain == forecast)
    return len(rows)


def main_api(url: str, cfg: dict, live_dir: Path, out: Path) -> int:
    days = published_days(live_dir)
    if not days:
        print("no published day", file=sys.stderr)
        return 1
    day = days[-1].isoformat()
    day_dir = Path(live_dir) / day
    places_path = project_path(cfg["places_table"]) if cfg.get("places_table") else None
    places = pl.read_table(places_path).set_index("cell_id", drop=False) if places_path and places_path.is_file() else None
    found = Mismatches()
    sampled = {}
    try:
        for lead in range(4):
            if (day_dir / ("alerts.parquet" if lead == 0 else f"risk_D{lead}.parquet")).is_file():
                sampled[lead] = compare_lead(url, day, day_dir, lead, places, found)
    except (requests.RequestException, ValueError, KeyError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    result = {"date": day, "api": url, "sample_cells_per_lead": SAMPLE_CELLS, "sampled": sampled, "seed": SEED, **found.to_dict()}
    Path(out).mkdir(parents=True, exist_ok=True)
    dump_json(Path(out) / f"api_parity_{day}.json", result)
    print(f"{day}: api parity over {sum(sampled.values())} cells, {sum(found.compared.values())} comparisons, "
          f"mismatches: {result['total']}")
    return EXIT_VIOLATIONS if result["total"] else 0
