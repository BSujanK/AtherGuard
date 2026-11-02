"""The corrector on cells: predictions for the rows of the frozen feature tables (`corr_` columns) and their manifest.

The station-side predictors are mapped to the cell-side feature columns (`data.CELL_COLUMN_MAP`): aligned CHIRPS
`src_chi_acc_1` / `src_chi_acc_3`, wetness `wet_top` / `wet_root` (already UTC day D-1), the terrain statics, and
`stat_elev_mean` as the point elevation. Output columns (float32), NaN where `src_chi_acc_1` is missing:

  corr_q50_1, corr_q90_1, corr_q99_1   predicted gauge-rain quantiles (mm) of the IMD day D
  corr_p_exceed99                      calibrated P(gauge >= the local 99th percentile of wet days)

Files go to data/processed/features/corrector/<name>_corr.parquet (same cell_id, date keys and row order), frozen with a
SHA-256 manifest; a second build verifies and reuses them.
"""
from __future__ import annotations

import json
import os
import stat
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import PROJECT_ROOT
from ..manifest import sha256_file
from . import data as cdata
from .model import CorrectorModel

CORR_COLUMNS = ["corr_q50_1", "corr_q90_1", "corr_q99_1", "corr_p_exceed99"]
MANIFEST_NAME = "corrector_manifest.json"
COLUMNS_NAME = "corrector_columns.json"
FEATURES_MANIFEST = "features_manifest.json"


class CorrectorIntegrityError(RuntimeError):
    """The frozen corrector feature directory is damaged, stale or does not match its inputs."""


def predict_cells(model: CorrectorModel, df: pd.DataFrame) -> pd.DataFrame:
    """Corrector columns for a frame holding either the predictor columns or a feature-table's cell columns."""
    predictors = df if "chirps_1" in df.columns else cdata.predictors_from_features(df)
    for column in model.columns:
        if column not in predictors.columns:
            raise KeyError(f"predictor {column!r} is missing")
    pred = model.predict(predictors)
    out = pd.DataFrame({"corr_q50_1": pred["q50"], "corr_q90_1": pred["q90"], "corr_q99_1": pred["q99"],
                        "corr_p_exceed99": pred["p_exceed"]}, index=df.index)
    missing = predictors["chirps_1"].isna().to_numpy()
    out.loc[missing, :] = np.nan
    return out.astype(np.float32)


def corr_name(features_file: str) -> str:
    return features_file.replace("_features.parquet", "_corr.parquet")


def _display(path: Path) -> str:
    try:
        return Path(path).resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return Path(path).name


def _inputs(features_dir: Path, model_dir: Path) -> dict:
    return {"features_manifest": {"path": _display(features_dir / FEATURES_MANIFEST),
                                  "sha256": sha256_file(features_dir / FEATURES_MANIFEST)},
            "model_card": {"path": _display(model_dir / "card.json"), "sha256": sha256_file(model_dir / "card.json")},
            "model_bundle": {"path": _display(model_dir / "model.json"), "sha256": sha256_file(model_dir / "model.json")}}


def _set_mode(paths, mode: int) -> None:
    for path in paths:
        if Path(path).exists():
            os.chmod(path, mode)


def verify_cells(out_dir, features_dir, model_dir) -> dict:
    out_dir, features_dir, model_dir = Path(out_dir), Path(features_dir), Path(model_dir)
    manifest_path = out_dir / MANIFEST_NAME
    if not manifest_path.is_file():
        raise FileNotFoundError(f"{MANIFEST_NAME} not found in {out_dir}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    problems = []
    for name, entry in manifest["files"].items():
        path = out_dir / name
        if not path.is_file():
            problems.append(f"missing: {name}")
        elif sha256_file(path) != entry["sha256"]:
            problems.append(f"checksum mismatch: {name}")
    if _inputs(features_dir, model_dir) != manifest["inputs"]:
        problems.append("inputs (frozen features / corrector model) changed after the corrector build")
    for name in manifest["feature_files"]:
        keys = pd.read_parquet(out_dir / corr_name(name), columns=["cell_id", "date"])
        base = pd.read_parquet(features_dir / name, columns=["cell_id", "date"])
        if not keys.equals(base):
            problems.append(f"{corr_name(name)}: keys / row order differ from {name}")
    return {"ok": not problems, "problems": problems}


def build_cell_files(model: CorrectorModel, features_dir, out_dir, model_dir, force: bool = False) -> tuple[dict, bool]:
    """Write (or verify and reuse) the frozen corr tables for every frozen features file; returns (manifest, reused)."""
    features_dir, out_dir, model_dir = Path(features_dir), Path(out_dir), Path(model_dir)
    manifest_path = out_dir / MANIFEST_NAME
    if manifest_path.exists() and not force:
        result = verify_cells(out_dir, features_dir, model_dir)
        if not result["ok"]:
            raise CorrectorIntegrityError(f"{out_dir} is frozen but not intact (pass force=True to rebuild): "
                                          + "; ".join(result["problems"]))
        return json.loads(manifest_path.read_text(encoding="utf-8")), True
    started = time.perf_counter()
    listed = json.loads((features_dir / FEATURES_MANIFEST).read_text(encoding="utf-8"))["files"]
    files = sorted(n for n in listed if n.endswith("_features.parquet"))
    out_dir.mkdir(parents=True, exist_ok=True)
    managed = [out_dir / n for n in (*(corr_name(f) for f in files), COLUMNS_NAME, MANIFEST_NAME)]
    _set_mode(managed, stat.S_IWRITE | stat.S_IREAD)
    rows, shares = {}, {}
    for name in files:
        features = pd.read_parquet(features_dir / name)
        pred = predict_cells(model, features.reset_index(drop=True))
        table = pd.concat([features[["cell_id", "date"]].reset_index(drop=True), pred], axis=1)
        table.to_parquet(out_dir / corr_name(name), index=False)
        rows[corr_name(name)] = len(table)
        shares[corr_name(name)] = {c: float(table[c].isna().mean()) for c in CORR_COLUMNS}
    (out_dir / COLUMNS_NAME).write_text(json.dumps({c: "corr" for c in CORR_COLUMNS}, indent=2) + "\n", encoding="utf-8")
    entries = {n: {"sha256": sha256_file(out_dir / n), "size_bytes": (out_dir / n).stat().st_size, "n_rows": rows.get(n)}
               for n in (*rows, COLUMNS_NAME)}
    manifest = {"created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "frozen": True,
                "inputs": _inputs(features_dir, model_dir), "feature_files": files, "files": entries,
                "nan_share": shares, "runtime_seconds": round(time.perf_counter() - started, 1)}
    manifest_path.write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    _set_mode(managed, stat.S_IREAD)
    return json.loads(manifest_path.read_text(encoding="utf-8")), False
