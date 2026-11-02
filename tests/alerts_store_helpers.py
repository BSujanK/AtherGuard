"""Feature-table and replay-store fixtures for the alert tests (a stand-in hazard model, no real data)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from aetherguard.alerts import replay
from alerts_helpers import CONFIG, HEALTHY, STATIONS, THRESHOLDS, station_outputs


FREEZE = {"created_utc": "2026-10-03T00:00:00Z", "sha256": {"card.json": "0" * 64}}


def write_feature_fixture(directory, name: str, n_cells: int = 3, n_days: int = 6, start="2024-07-01", seed=0,
                          positive_cells=(), extra=None):
    """`<name>_features.parquet` plus `integ/<name>_integ.parquet` with n_cells cells x n_days consecutive days; rain
    rises over the days (faster for higher cells) so later days alert. `extra` maps extra column names to
    functions of (cell index, day index). Returns the feature frame with integ columns."""
    rng = np.random.default_rng(seed)
    rows = []
    for c in range(n_cells):
        for d, date in enumerate(pd.date_range(start, periods=n_days)):
            rain = float(2 + 6 * d * (c + 1) + rng.random())
            rows.append({**HEALTHY, "cell_id": 1000 + c, "date": date, "lat": 11.5 + 0.05 * c, "lon": 76.0,
                         "split": "test_2018", "region": "western_ghats", "kind": "case", "rain_acc_1": rain,
                         "src_imd_acc_1": rain, "src_chi_acc_1": rain * 1.1, "integ_trw_rain_1": rain,
                         "integ_max_st_rain_1_100km": rain, "weight": 100.0, "in_buffer": False,
                         "is_positive_cell_day": bool(c in positive_cells and d == n_days - 1),
                         **{k: f(c, d) for k, f in (extra or {}).items()}})
    frame = pd.DataFrame(rows)
    integ_columns = [c for c in frame.columns if c.startswith("integ_")]
    directory = Path(directory)
    (directory / "integ").mkdir(parents=True, exist_ok=True)
    frame.drop(columns=integ_columns).to_parquet(directory / f"{name}_features.parquet")
    frame[["cell_id", "date"] + integ_columns].to_parquet(directory / "integ" / f"{name}_integ.parquet")
    (directory / "corrector").mkdir(exist_ok=True)
    frame[["cell_id", "date"]].assign(corr_q50_1=1.0).to_parquet(directory / "corrector" / f"{name}_corr.parquet")
    return frame


def rain_scorer(frame: pd.DataFrame) -> pd.DataFrame:
    """A stand-in hazard model: risk grows with the day's rain (Watch at 10 mm for THRESHOLDS)."""
    risk = 1e-6 * np.asarray(frame["rain_acc_1"], dtype=float)
    return pd.DataFrame({"risk": risk, "risk_lo": 0.5 * risk, "risk_hi": 1.5 * risk, "risk_per_100k": 1e5 * risk},
                        index=frame.index)


def explainer(frame: pd.DataFrame) -> list[list[dict]]:
    return [[{"feature": "rain_acc_1", "value": float(v), "contribution": 0.5}] for v in frame["rain_acc_1"]]


def build_store(root: Path, sets: dict[str, dict], seed_start: int = 1) -> tuple[dict, Path]:
    """Build a replay store from fixture feature tables. `sets[name]` are write_feature_fixture keyword arguments."""
    features = Path(root) / "features"
    for i, (name, kwargs) in enumerate(sets.items()):
        write_feature_fixture(features, name, seed=seed_start + i, **kwargs)
    outputs = station_outputs({"A": {"flag_every": 7}, "B": {}}, days=2400, start="2018-01-01")
    out = Path(root) / "store"
    manifest = replay.build_replay(list(sets), out, features_dir=features, model_columns=[], scorer=rain_scorer,
                                   explainer=explainer, thresholds=THRESHOLDS, config=CONFIG, station_outputs=outputs,
                                   stations=STATIONS, freeze=FREEZE, manifest_fields={"thresholds": THRESHOLDS.to_dict(),
                                                                       "model": {"card_sha256": "0" * 64},
                                                                       "provisional": None})
    return manifest, out
