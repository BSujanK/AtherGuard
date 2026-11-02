"""The `integ_` feature group for the hazard model, built from the out-of-fold engine outputs and the station data.

    python -m aetherguard.integrity.hazard_features [--out-dir DIR] [--force]

For every frozen `data/processed/features/*_features.parquet` it writes `integ/<name>_integ.parquet` with the SAME
`cell_id`, `date` keys and row order plus float32 `integ_` columns. Everything at sample date D uses only station
information up to and including D (IMD-day basis: the gauge day equals the IMD day, see the day-basis experiment):

* integ_n_st_100km          stations within 100 km of the cell centre with an observed value on D (count, 0 if none)
* integ_frac_trusted_100km  share of those that are not flagged (NaN if none)
* integ_trw_rain_1 / _3     trust-weighted inverse-distance (1/d^2, d floored at 1 km) mean of the station rain of day D
                            / of the 3-day total of D-2..D, over stations within 100 km that are USABLE (observed and not
                            flagged; arbiter-retained genuine extremes are not flagged, so they count). A reading's weight
                            is its trust (clipped to [0.001, 1]), 1.0 for a retained genuine extreme; the 3-day weight is
                            the mean trust of the three days and needs all three days usable. NaN if no station qualifies.
                            Repaired values are NEVER used.
* integ_st_minus_grid_1     integ_trw_rain_1 minus the cell's own rain_acc_1 (NaN if either is missing)
* integ_max_st_rain_1_100km largest usable reading on D within 100 km (NaN if none)
* integ_n_flagged_100km_7d  flagged readings within 100 km over D-6..D (count)
* integ_dist_nearest_km     distance to the nearest station observed on D, NaN if none within 300 km

Causality of the flags: the engine's L1 stuck / duplicate flags are retroactive (they also mark the first days of a
confirmed streak / block). `causal_flags` removes that look-ahead: a day flagged ONLY by L1 stays unflagged until the
run of such days reaches the confirmation length (stuck 3, duplicate block 7, bounds immediate).
"""
from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import PROJECT_ROOT, data_root
from ..grid import cell_center
from ..manifest import sha256_file
from .common import dumps_strict, integrity_dir
from .neighbours import haversine_km
from .stations import load_station_set

RADIUS_KM = 100.0
FAR_KM = 300.0
MIN_DISTANCE_KM = 1.0
MIN_TRUST = 1e-3
STUCK_CONFIRM_DAYS = 3
DUPLICATE_CONFIRM_DAYS = 7
PREFIX = "integ_"
COLUMNS = ["integ_n_st_100km", "integ_frac_trusted_100km", "integ_trw_rain_1", "integ_trw_rain_3",
           "integ_st_minus_grid_1", "integ_max_st_rain_1_100km", "integ_n_flagged_100km_7d", "integ_dist_nearest_km"]
MANIFEST_NAME = "integ_manifest.json"
COLUMNS_NAME = "integ_columns.json"
REPORT_NAME = "integ_report.json"
FEATURES_MANIFEST = "features_manifest.json"
ENGINE_PERIOD = ("2007-01-01", "2024-12-31")


class IntegIntegrityError(RuntimeError):
    """The frozen integ directory is damaged, stale or does not match the current inputs."""


@dataclass
class StationDays:
    """Station observations and engine decisions as (days, stations) matrices on a consecutive daily index."""
    index: pd.DatetimeIndex
    ids: list[str]
    lat: np.ndarray
    lon: np.ndarray
    value: np.ndarray      # observed rain, NaN = missing
    trust: np.ndarray      # engine trust, NaN where unobserved
    flagged: np.ndarray    # bool: flagged by the engine (causal flags)
    genuine: np.ndarray    # bool: retained by the arbiter as a genuine extreme


def causal_flags(oof: pd.DataFrame) -> pd.Series:
    """`flagged` of an OOF frame with the retroactive L1 look-ahead removed (see the module doc)."""
    frame = oof[["station", "date", "flagged", "l1_flag", "l1_reason", "reasons"]].copy()
    order = np.lexsort((frame["date"].to_numpy(), frame["station"].to_numpy()))
    frame = frame.iloc[order]
    only = (frame["flagged"] & frame["l1_flag"] & ~frame["reasons"].str.contains("model", regex=False)).to_numpy()
    station = frame["station"].to_numpy()
    date = frame["date"].to_numpy()
    start = np.ones(len(frame), dtype=bool)
    start[1:] = ~(only[:-1] & only[1:] & (station[1:] == station[:-1]) & ((date[1:] - date[:-1]) == np.timedelta64(1, "D")))
    run = np.cumsum(start)
    position = pd.Series(np.where(only, 1, 0), index=frame.index).groupby(run).cumsum().to_numpy()
    reason = frame["l1_reason"].to_numpy()
    confirm = np.where(pd.Series(reason).str.contains("duplicate_block", regex=False).to_numpy(), DUPLICATE_CONFIRM_DAYS,
                       np.where(pd.Series(reason).str.contains("stuck", regex=False).to_numpy(), STUCK_CONFIRM_DAYS, 1))
    causal = frame["flagged"].to_numpy() & (~only | (position >= confirm))
    return pd.Series(causal, index=frame.index).reindex(oof.index)


def station_days(oof: pd.DataFrame, values: pd.DataFrame, meta: pd.DataFrame) -> StationDays:
    """Matrices from the OOF engine outputs (real series) and the station values."""
    flagged = oof.assign(causal=causal_flags(oof))

    def wide(column, fill=None):
        out = flagged.pivot(index="date", columns="station", values=column)
        return out.reindex(index=values.index, columns=list(values.columns))

    trust, causal, genuine = wide("trust"), wide("causal"), wide("genuine_extreme")
    return StationDays(values.index, list(values.columns), meta["lat"].to_numpy(float), meta["lon"].to_numpy(float),
                       values.to_numpy(np.float64), trust.to_numpy(np.float64),
                       causal.fillna(False).to_numpy(bool), genuine.fillna(False).to_numpy(bool))


def _shift(a: np.ndarray, k: int, fill) -> np.ndarray:
    out = np.full_like(a, fill)
    out[k:] = a[:-k]
    return out


def integ_features(sd: StationDays, cell_lat, cell_lon, dates, rain_acc_1, chunk_rows: int = 20_000) -> pd.DataFrame:
    """The integ_ columns for rows (cell lat/lon, date, the cell's own rain_acc_1); see the module doc."""
    if not ((sd.index[1:] - sd.index[:-1]) == pd.Timedelta(days=1)).all():
        raise ValueError("the station days must be on a consecutive daily index")
    cell_lat, cell_lon = np.asarray(cell_lat, float), np.asarray(cell_lon, float)
    rain1 = np.asarray(rain_acc_1, dtype=np.float64)
    day = sd.index.get_indexer(pd.DatetimeIndex(dates))
    if (day < 0).any():
        raise ValueError("some sample dates are outside the station-day index")
    observed = np.isfinite(sd.value)
    usable = observed & ~sd.flagged & np.isfinite(sd.trust)
    weight = np.where(usable, np.where(sd.genuine, 1.0, np.clip(np.nan_to_num(sd.trust), MIN_TRUST, 1.0)), 0.0)
    value = np.where(usable, sd.value, 0.0)
    usable3 = usable & _shift(usable, 1, False) & _shift(usable, 2, False)
    value3 = np.where(usable3, value + _shift(value, 1, 0.0) + _shift(value, 2, 0.0), 0.0)
    weight3 = np.where(usable3, (weight + _shift(weight, 1, 0.0) + _shift(weight, 2, 0.0)) / 3.0, 0.0)
    flag_day = (sd.flagged & observed).astype(np.int32)
    cum = np.concatenate([np.zeros((1, flag_day.shape[1]), dtype=np.int32), np.cumsum(flag_day, axis=0)])
    flag7 = cum[1:] - cum[np.maximum(np.arange(1, len(cum)) - 7, 0)]
    max_value = np.where(usable, sd.value, -np.inf)
    cells, inverse = np.unique(np.stack([cell_lat, cell_lon], axis=1), axis=0, return_inverse=True)
    inverse = np.asarray(inverse).ravel()
    dist = haversine_km(cells[:, [0]], cells[:, [1]], sd.lat[None, :], sd.lon[None, :])
    n = len(day)
    out = {c: np.full(n, np.nan) for c in COLUMNS}
    for lo in range(0, n, chunk_rows):
        sel = slice(lo, lo + chunk_rows)
        d, t = dist[inverse[sel]], day[sel]
        near = d <= RADIUS_KM
        obs = observed[t]
        near_obs = near & obs
        n_st = near_obs.sum(axis=1)
        out["integ_n_st_100km"][sel] = n_st
        trusted = (near_obs & ~sd.flagged[t]).sum(axis=1)
        out["integ_frac_trusted_100km"][sel] = np.where(n_st > 0, trusted / np.maximum(n_st, 1), np.nan)
        idw = 1.0 / np.maximum(d, MIN_DISTANCE_KM) ** 2
        for name, w_mat, v_mat in (("integ_trw_rain_1", weight, value), ("integ_trw_rain_3", weight3, value3)):
            w = np.where(near, w_mat[t] * idw, 0.0)
            total = w.sum(axis=1)
            out[name][sel] = np.where(total > 0, (w * v_mat[t]).sum(axis=1) / np.where(total > 0, total, 1.0), np.nan)
        peak = np.where(near, max_value[t], -np.inf).max(axis=1)
        out["integ_max_st_rain_1_100km"][sel] = np.where(np.isfinite(peak), peak, np.nan)
        out["integ_n_flagged_100km_7d"][sel] = np.where(near, flag7[t], 0).sum(axis=1)
        nearest = np.where(obs, d, np.inf).min(axis=1)
        out["integ_dist_nearest_km"][sel] = np.where(nearest <= FAR_KM, nearest, np.nan)
    out["integ_st_minus_grid_1"] = out["integ_trw_rain_1"] - rain1
    return pd.DataFrame({c: out[c].astype(np.float32) for c in COLUMNS})


def cell_coordinates(cell_ids) -> tuple[np.ndarray, np.ndarray]:
    return cell_center(np.asarray(cell_ids, dtype=np.int64))


# ------------------------------------------------------------------------------------------- build and freeze

def default_features_dir() -> Path:
    return data_root() / "processed" / "features"


def feature_files(features_dir: Path) -> list[str]:
    manifest = json.loads((features_dir / FEATURES_MANIFEST).read_text(encoding="utf-8"))
    return sorted(n for n in manifest["files"] if n.endswith("_features.parquet"))


def integ_name(features_file: str) -> str:
    return features_file.replace("_features.parquet", "_integ.parquet")


def _display(path: Path) -> str:
    try:
        return Path(path).resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return Path(path).name


def _inputs(features_dir: Path, oof_path: Path) -> dict:
    return {"oof_outputs": {"path": _display(oof_path), "sha256": sha256_file(oof_path)},
            "features_manifest": {"path": _display(features_dir / FEATURES_MANIFEST),
                                  "sha256": sha256_file(features_dir / FEATURES_MANIFEST)}}


def _set_mode(paths, mode: int) -> None:
    for path in paths:
        if Path(path).exists():
            os.chmod(path, mode)


def _managed(out_dir: Path, files: list[str]) -> list[Path]:
    return [out_dir / n for n in (*(integ_name(f) for f in files), COLUMNS_NAME, REPORT_NAME, MANIFEST_NAME)]


def _file_report(table: pd.DataFrame, features: pd.DataFrame) -> dict:
    rep = {"rows": int(len(table)), "columns": {c: {"nan_share": float(table[c].isna().mean()),
                                                   "median": float(table[c].median()) if table[c].notna().any() else None}
                                                for c in COLUMNS}}
    has_station = (table["integ_n_st_100km"] > 0).to_numpy()
    rep["share_rows_with_station_100km"] = float(has_station.mean())
    positive = None
    for col in ("is_positive_cell_day", "label"):
        if col in features.columns:
            positive = features[col].astype(bool).to_numpy()
            break
    if "region" in features.columns:
        rep["by_region"] = {}
        for region, part in features.groupby("region").groups.items():
            idx = np.asarray(part)
            entry = {"rows": int(len(idx)), "share_with_station_100km": float(has_station[idx].mean())}
            if positive is not None:
                pos = positive[idx]
                entry["positives"] = {"rows": int(pos.sum()),
                                      "share_with_station_100km": float(has_station[idx][pos].mean()) if pos.any() else None}
                entry["negatives"] = {"rows": int((~pos).sum()),
                                      "share_with_station_100km": float(has_station[idx][~pos].mean()) if (~pos).any() else None}
            rep["by_region"][region] = entry
    return rep


def verify_integ(out_dir, features_dir=None, oof_path=None) -> dict:
    out_dir = Path(out_dir)
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
    if features_dir is not None and oof_path is not None:
        if _inputs(Path(features_dir), Path(oof_path)) != manifest["inputs"]:
            problems.append("inputs (OOF outputs / frozen features) changed after the integ build")
        features_dir = Path(features_dir)
        for name in manifest["feature_files"]:
            integ = pd.read_parquet(out_dir / integ_name(name), columns=["cell_id", "date"])
            base = pd.read_parquet(features_dir / name, columns=["cell_id", "date"])
            if not integ.equals(base):
                problems.append(f"{integ_name(name)}: keys / row order differ from {name}")
    return {"ok": not problems, "problems": problems}


def build_integ(features_dir, out_dir, oof_path=None, force: bool = False, station_set=None) -> tuple[dict, bool]:
    """Write the frozen integ tables; returns (manifest, reused). Verifies and reuses an existing build.

    `station_set` (default: the real 2007-2024 stations) supplies the station values and coordinates."""
    features_dir, out_dir = Path(features_dir), Path(out_dir)
    oof_path = Path(oof_path) if oof_path is not None else integrity_dir() / "engine_outputs_2007_oof.parquet"
    manifest_path = out_dir / MANIFEST_NAME
    if manifest_path.exists() and not force:
        result = verify_integ(out_dir, features_dir, oof_path)
        if not result["ok"]:
            raise IntegIntegrityError(f"{out_dir} is frozen but not intact (pass force=True to rebuild): "
                                      + "; ".join(result["problems"]))
        return json.loads(manifest_path.read_text(encoding="utf-8")), True
    started = time.perf_counter()
    files = feature_files(features_dir)
    window = station_set if station_set is not None else load_station_set(start=ENGINE_PERIOD[0], end=ENGINE_PERIOD[1])
    oof = pd.read_parquet(oof_path)
    sd = station_days(oof, window.values, window.meta)
    out_dir.mkdir(parents=True, exist_ok=True)
    _set_mode(_managed(out_dir, files), stat.S_IWRITE | stat.S_IREAD)
    reports, rows = {}, {}
    for name in files:
        tick = time.perf_counter()
        features = pd.read_parquet(features_dir / name)
        lat, lon = cell_coordinates(features["cell_id"])
        table = integ_features(sd, lat, lon, features["date"], features["rain_acc_1"])
        keys = features[["cell_id", "date"]].reset_index(drop=True)
        result = pd.concat([keys, table], axis=1)
        result.to_parquet(out_dir / integ_name(name), index=False)
        reports[integ_name(name)] = {**_file_report(table, features), "seconds": round(time.perf_counter() - tick, 1)}
        rows[integ_name(name)] = len(result)
    (out_dir / COLUMNS_NAME).write_text(json.dumps({c: "integ" for c in COLUMNS}, indent=2) + "\n", encoding="utf-8")
    changed = int((oof["flagged"] & ~causal_flags(oof)).sum())
    report = {"files": reports, "causal_flag_adjustment": {"flagged_days": int(oof["flagged"].sum()),
                                                           "days_unflagged_by_causality_rule": changed},
              "radius_km": RADIUS_KM, "far_km": FAR_KM, "seconds_total": round(time.perf_counter() - started, 1)}
    (out_dir / REPORT_NAME).write_text(dumps_strict(report), encoding="utf-8")
    entries = {n: {"sha256": sha256_file(out_dir / n), "size_bytes": (out_dir / n).stat().st_size, "n_rows": rows.get(n)}
               for n in (*rows, COLUMNS_NAME, REPORT_NAME)}
    manifest = {"created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "frozen": True,
                "inputs": _inputs(features_dir, oof_path), "feature_files": files, "files": entries,
                "runtime_seconds": report["seconds_total"]}
    manifest_path.write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    _set_mode(_managed(out_dir, files), stat.S_IREAD)
    return json.loads(manifest_path.read_text(encoding="utf-8")), False


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Build and freeze the integ_ hazard feature group.")
    parser.add_argument("--features-dir", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    features_dir = args.features_dir or default_features_dir()
    out_dir = args.out_dir or features_dir / "integ"
    try:
        manifest, reused = build_integ(features_dir, out_dir, force=args.force)
    except (IntegIntegrityError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"integ features {'reused (verified intact)' if reused else 'built and frozen'} in {out_dir} "
          f"({manifest['runtime_seconds']} s to build)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
