"""`iclim`: climatology-normalised IMERG rain, a challenger feature group (Task 5; docs/superpowers/specs/
2026-10-14-aetherguard-live-global-design.md section 4).

For every pixel the IMD-day accumulation over 1, 3 and 7 days (the `irain` day basis: 0.875 * UTC(d-1) + 0.125 * UTC(d))
is placed in the pixel's OWN 2007-2015 distribution of the same window, wet and dry days alike:
* `iclim_pct_{1,3,7}`: the mid-rank share of that distribution, (count below + half the count equal) / count, in [0, 1];
  dry days tie at zero, so a dry day sits at half the pixel's dry-day share rather than at 0;
* `iclim_acc{1,3,7}_over_map`: the accumulation over the pixel's mean annual precipitation (MAP), the mean IMD-day rain
  of 2007-2015 times 365.25, floored at `MAP_FLOOR_MM` so near-desert pixels do not explode.
Both are non-decreasing in the accumulation (monotone increasing in the model).

Causality. The distribution and MAP use only IMERG UTC days inside 2007-01-01..2015-12-31 (the first day of the range
has no IMD-day value, as in `imerg_features.imerg_climatology`); the features at day D use rain up to UTC day D only
(weight 1/8 of IMD day D), nothing later. NaN rule as `irain`: a window with any missing day is NaN; a pixel outside
the grid or without a valid climatology gives NaN.

CLI: python -m aetherguard.features.imerg_clim [--out-dir DIR] [--force]  (writes `<name>_iclim.parquet` for every
sample file, `iclim_columns.json`, `iclim_manifest.json`, `iclim_report.json`; frozen read-only like the other groups.)
"""
from __future__ import annotations

import argparse
import json
import stat
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from ..ingest import imerg as imerg_mod
from ..ingest.align import IMD_SHARE_OF_CURRENT_UTC_DAY, IMD_SHARE_OF_PREVIOUS_UTC_DAY
from ..manifest import sha256_file
from . import imerg_build as B
from . import imerg_features as F
from .build import MANIFEST_NAME as FEATURES_MANIFEST
from .compute import trailing_window_sums
from .sources import day_numbers

GROUP = "iclim"
PCT_WINDOWS = (1, 3, 7)
MAP_FLOOR_MM = 50.0
DAYS_PER_YEAR = 365.25
CHUNK_DAYS = 120
PIXEL_BLOCK = 1000
REPORT_NAME = "iclim_report.json"


class IclimIntegrityError(RuntimeError):
    """The frozen iclim directory is damaged, stale or incompatible with the current inputs / configuration."""


def feature_names() -> list[str]:
    return ([f"iclim_pct_{k}" for k in PCT_WINDOWS] + [f"iclim_acc{k}_over_map" for k in PCT_WINDOWS])


# ------------------------------------------------------------------------------------------- climatology

@dataclass(frozen=True)
class IclimTable:
    pix: np.ndarray            # sorted unique flat pixel ids (row * COLS + col)
    sorted_acc: np.ndarray     # (P, W, N) float32: the pixel's valid window sums in ascending order, NaN-padded
    n_valid: np.ndarray        # (P, W) valid sums per pixel and window
    map_mm: np.ndarray         # (P,) mean annual precipitation (NaN when the pixel has no valid day)


def build_iclim_table(store, flat_pixels, first_day: date, last_day: date, windows=PCT_WINDOWS,
                      pixel_chunk: int = PIXEL_BLOCK) -> IclimTable:
    """Per pixel, the sorted trailing IMD-day window sums of first_day..last_day ONLY and the MAP. The IMD-day series
    is built from the UTC days inside the range, so its first day is NaN; a window counts only when it lies wholly in
    the range with no missing day."""
    pix = np.unique(np.asarray(flat_pixels, dtype=np.int64))
    pix = pix[pix >= 0]
    n_days = (last_day - first_day).days + 1
    sorted_acc = np.full((len(pix), len(windows), n_days), np.nan, dtype=np.float32)
    n_valid = np.zeros((len(pix), len(windows)), dtype=np.int32)
    map_mm = np.full(len(pix), np.nan)
    for start in range(0, len(pix), pixel_chunk):
        sel = slice(start, start + pixel_chunk)
        chunk = pix[sel]
        utc = store.gather(chunk // imerg_mod.COLS, chunk % imerg_mod.COLS, first_day, n_days)
        imd = np.full((len(chunk), n_days), np.nan)
        imd[:, 1:] = F.imd_day_series(utc)
        valid_days = ~np.isnan(imd)
        count = valid_days.sum(axis=1)
        map_mm[sel] = np.where(count > 0, np.where(valid_days, imd, 0.0).sum(axis=1) / np.maximum(count, 1)
                               * DAYS_PER_YEAR, np.nan)
        for w, k in enumerate(windows):
            sums = trailing_window_sums(imd, k).astype(np.float32)
            n_valid[sel, w] = (~np.isnan(sums)).sum(axis=1)
            sorted_acc[sel, w, :] = np.sort(sums, axis=1)          # NaN sorts last
    return IclimTable(pix, sorted_acc, n_valid, map_mm)


def mid_rank_share(sorted_values: np.ndarray, n_valid: int, x: np.ndarray) -> np.ndarray:
    """(count of values below x + half the count equal to x) / n_valid among the first `n_valid` sorted values."""
    reference = sorted_values[:n_valid]
    x = np.asarray(x, dtype=np.float32)
    return (np.searchsorted(reference, x, side="left") + np.searchsorted(reference, x, side="right")) / (2.0 * n_valid)


# ------------------------------------------------------------------------------------------------ features

def _block_features(store, table: IclimTable, centres: np.ndarray, flat: np.ndarray, days: np.ndarray) -> dict:
    widest = max(PCT_WINDOWS)
    first_imd = int(days.min()) - (widest - 1)             # IMD day of IMD-series column 0
    n_imd = int(days.max()) - first_imd + 1
    utc = store.gather(centres // imerg_mod.COLS, centres % imerg_mod.COLS, F.EPOCH + timedelta(days=first_imd - 1),
                       n_imd + 1)
    imd = F.imd_day_series(utc)
    own = np.searchsorted(centres, flat)
    t = days - first_imd
    if len(table.pix) == 0:
        return {name: np.full(len(flat), np.nan) for name in feature_names()}
    position = np.minimum(np.searchsorted(table.pix, flat), len(table.pix) - 1)
    known = table.pix[position] == flat
    out: dict[str, np.ndarray] = {}
    for w, k in enumerate(PCT_WINDOWS):
        acc = trailing_window_sums(imd, k)[own, t]
        pct = np.full(len(flat), np.nan)
        usable = known & ~np.isnan(acc) & (table.n_valid[position, w] > 0)
        x = acc.astype(np.float32)
        for p in np.unique(position[usable]):
            rows = usable & (position == p)
            pct[rows] = mid_rank_share(table.sorted_acc[p, w], int(table.n_valid[p, w]), x[rows])
        out[f"iclim_pct_{k}"] = pct
        reference = np.where(known, np.maximum(table.map_mm[position], MAP_FLOOR_MM), np.nan)
        out[f"iclim_acc{k}_over_map"] = acc / reference
    return out


def build_iclim_features(frame: pd.DataFrame, store, table: IclimTable, chunk_days: int = CHUNK_DAYS,
                         pixel_block: int = PIXEL_BLOCK) -> pd.DataFrame:
    """The `iclim` float32 columns for the (cell_id, date) rows of `frame`, in its row order and with its index. `store`
    needs `gather(rows, cols, first_day, length) -> float32 (n, length)` (NaN where missing); `table` is the
    2007-2015 climatology of the frame's pixels. Rows are processed by calendar chunk and block of centre pixels, so
    memory is bounded by the block."""
    cells = frame["cell_id"].to_numpy(dtype=np.int64)
    days = day_numbers(frame["date"].to_numpy())
    flat = F.cell_pixels(cells)
    names = feature_names()
    out = {name: np.full(len(frame), np.nan, dtype=np.float32) for name in names}
    usable = np.flatnonzero(flat >= 0)
    chunk = days[usable] // chunk_days
    for c in np.unique(chunk):
        in_chunk = usable[chunk == c]
        centres, inverse = np.unique(flat[in_chunk], return_inverse=True)
        block_of = inverse // pixel_block
        for b in np.unique(block_of):
            sel = in_chunk[block_of == b]
            values = _block_features(store, table, centres[b * pixel_block:(b + 1) * pixel_block], flat[sel], days[sel])
            for name in names:
                out[name][sel] = values[name]
    return pd.DataFrame(out, index=frame.index)


# ------------------------------------------------------------------------------------------ build and freeze

def build_config() -> dict:
    """Everything that changes a feature value."""
    return {"windows": list(PCT_WINDOWS), "map_floor_mm": MAP_FLOOR_MM, "days_per_year": DAYS_PER_YEAR,
            "percentile": "mid-rank share of the pixel's own daily distribution of the same window (wet and dry days)",
            "climatology": B.build_config()["climatology"]}


def _managed(out_dir: Path, stems: list[str]) -> list[Path]:
    return [*(out_dir / B.table_name(s, GROUP) for s in stems), out_dir / B.columns_name(GROUP),
            out_dir / B.manifest_name(GROUP), out_dir / REPORT_NAME]


def build_iclim_tables(inputs: B.ImergInputs, out_dir, store, force: bool = False,
                       cfg: dict | None = None) -> tuple[dict, bool]:
    """Write the frozen iclim tables; returns (manifest, reused). With a manifest present and `force` False nothing is
    rewritten: files, inputs and configuration are verified (IclimIntegrityError on any problem)."""
    out_dir = Path(out_dir)
    cfg = cfg if cfg is not None else build_config()
    manifest_path = out_dir / B.manifest_name(GROUP)
    if not force and manifest_path.exists():
        result = verify_iclim_tables(out_dir, inputs, cfg)
        if not result["ok"]:
            raise IclimIntegrityError(f"{out_dir} is frozen but not intact (pass force=True to rebuild): "
                                      + "; ".join(result["problems"]))
        return json.loads(manifest_path.read_text(encoding="utf-8")), True

    started = time.perf_counter()
    stems, _ = B._sample_stems(inputs)
    keys = {stem: pd.read_parquet(inputs.features_dir / B.base_name(stem), columns=["cell_id", "date"])
            for stem in stems}
    through = max(pd.Timestamp(k["date"].max()) for k in keys.values()).date()
    cells = np.unique(np.concatenate([k["cell_id"].to_numpy(dtype=np.int64) for k in keys.values()]))
    train = cfg["climatology"]
    table = build_iclim_table(store, F.cell_pixels(cells), date.fromisoformat(train["first_day"]),
                              date.fromisoformat(train["last_day"]))
    clim_seconds = time.perf_counter() - started

    out_dir.mkdir(parents=True, exist_ok=True)
    B._set_mode(_managed(out_dir, stems), stat.S_IWRITE | stat.S_IREAD)
    rows: dict[str, int] = {}
    per_file: dict[str, dict] = {}
    for stem in stems:
        tick = time.perf_counter()
        frame = keys[stem]
        features = build_iclim_features(frame, store, table)
        outside = int((F.cell_pixels(frame["cell_id"].to_numpy(dtype=np.int64)) < 0).sum())
        out = pd.concat([frame[["cell_id", "date"]].reset_index(drop=True), features.reset_index(drop=True)], axis=1)
        name = B.table_name(stem, GROUP)
        out.to_parquet(out_dir / name, index=False)
        rows[name] = len(out)
        per_file[B.base_name(stem)] = {"rows": len(frame), "rows_outside_grid": outside,
                                       "nan_share": B._nan_share(features), "seconds": round(time.perf_counter() - tick, 1)}
    B._write_json(out_dir / B.columns_name(GROUP), {c: GROUP for c in feature_names()})
    total = round(time.perf_counter() - started, 1)
    B._write_json(out_dir / REPORT_NAME, {
        "files": per_file,
        "climatology": {"first_day": train["first_day"], "last_day": train["last_day"], "pixels": int(len(table.pix)),
                        "map_mm_percentiles_5_50_95": [float(v) for v in np.nanpercentile(table.map_mm, [5, 50, 95])]},
        "seconds": {"climatology": round(clim_seconds, 1), "total": total}})
    files = {n: {"sha256": sha256_file(out_dir / n), "size_bytes": (out_dir / n).stat().st_size, "n_rows": None}
             for n in (B.columns_name(GROUP), REPORT_NAME)}
    for stem in stems:
        n = B.table_name(stem, GROUP)
        files[n] = {"sha256": sha256_file(out_dir / n), "size_bytes": (out_dir / n).stat().st_size, "n_rows": rows[n]}
    B._write_json(manifest_path, {
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "frozen": True, "group": GROUP,
        "config": cfg, "inputs": B._input_records(inputs, through), "sample_files": [B.base_name(s) for s in stems],
        "files": files, "runtime_seconds": total})
    B._set_mode(_managed(out_dir, stems), stat.S_IREAD)
    return json.loads(manifest_path.read_text(encoding="utf-8")), False


def verify_iclim_tables(out_dir, inputs: B.ImergInputs | None = None, cfg: dict | None = None) -> dict:
    """Check the frozen files against the manifest; returns {"ok": bool, "problems": [str]}. Raises FileNotFoundError
    when there is no manifest. With `inputs`: unchanged feature-store manifest and IMERG index entries and keys
    identical to the base tables; with `cfg`: configuration equal to the frozen one."""
    out_dir = Path(out_dir)
    path = out_dir / B.manifest_name(GROUP)
    if not path.is_file():
        raise FileNotFoundError(f"{path} not found")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["files"], manifest["config"], manifest["inputs"], manifest["sample_files"]
    except (ValueError, KeyError, TypeError) as exc:
        return {"ok": False, "problems": [f"{path.name} unreadable or incomplete: {exc!r}"]}
    problems: list[str] = []
    if manifest.get("frozen") is not True:
        problems.append(f"{path.name} says the features are not frozen")
    if cfg is not None and json.loads(json.dumps(cfg)) != manifest["config"]:
        problems.append("configuration changed after freezing")
    for name, entry in manifest["files"].items():
        file = out_dir / name
        if not file.is_file():
            problems.append(f"missing: {name}")
        elif sha256_file(file) != entry["sha256"]:
            problems.append(f"checksum mismatch: {name}")
    if inputs is not None:
        recorded = manifest["inputs"]
        if sha256_file(inputs.features_dir / FEATURES_MANIFEST) != recorded["features_manifest"]["sha256"]:
            problems.append(f"input changed after freezing: {FEATURES_MANIFEST}")
        through = date.fromisoformat(recorded["imerg_index"]["through"])
        if B.index_signature(inputs.index_path, through) != recorded["imerg_index"]["signature"]:
            problems.append(f"input changed after freezing: IMERG index entries up to {through}")
    if problems:
        return {"ok": False, "problems": problems}
    try:
        columns = json.loads((out_dir / B.columns_name(GROUP)).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"ok": False, "problems": [f"cannot read {B.columns_name(GROUP)}: {exc}"]}
    expected = feature_names()
    if columns != {c: GROUP for c in expected}:
        problems.append(f"{B.columns_name(GROUP)} does not map exactly the iclim columns to `{GROUP}`")
    for base in manifest["sample_files"]:
        name = B.table_name(B.base_stem(base).removesuffix("_features"), GROUP)
        try:
            table = pd.read_parquet(out_dir / name)
        except (OSError, ValueError) as exc:
            problems.append(f"cannot read {name}: {exc}")
            continue
        if list(table.columns) != ["cell_id", "date", *expected]:
            problems.append(f"{name}: columns are not cell_id, date and the iclim features")
            continue
        if any(table[c].dtype != np.float32 for c in expected):
            problems.append(f"{name}: feature columns not float32")
        if np.isinf(table[expected].to_numpy(dtype=np.float64)).any():
            problems.append(f"{name}: infinite feature values")
        if inputs is not None and not table[["cell_id", "date"]].equals(
                pd.read_parquet(inputs.features_dir / base, columns=["cell_id", "date"])):
            problems.append(f"{name}: keys (cell_id, date) differ from {base} in value or order")
    return {"ok": not problems, "problems": problems}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build and freeze the iclim (climatology-normalised IMERG rain) tables.")
    parser.add_argument("--out-dir", type=Path, help="default: <data>/processed/features/imerg")
    parser.add_argument("--force", action="store_true", help="replace an existing frozen build")
    args = parser.parse_args(argv)
    inputs = B.default_inputs()
    out_dir = args.out_dir or B.default_out_dir()
    store = imerg_mod.ImergStore(inputs.index_path.parent, run="late")
    try:
        manifest, reused = build_iclim_tables(inputs, out_dir, store, force=args.force)
    except (IclimIntegrityError, B.ImergFeaturesIntegrityError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        store.close()
    report = json.loads((out_dir / REPORT_NAME).read_text(encoding="utf-8"))
    print(f"iclim {'reused (verified intact)' if reused else 'built and frozen'} in {out_dir} "
          f"({manifest['runtime_seconds']} s to build)")
    for name, entry in report["files"].items():
        print(f"{name}: {entry['rows']} rows ({entry['rows_outside_grid']} outside the grid); mean NaN share "
              f"{np.mean(list(entry['nan_share'].values())):.1%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
