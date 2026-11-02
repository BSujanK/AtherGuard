"""Build, freeze and verify the v3-live IMERG feature tables (groups `irain`, `iapi`, `inbr`).

For every sample file of the frozen feature store (`features_manifest.json`, `sample_files`) this writes
`<out_dir>/<name>_{irain,iapi,inbr}.parquet` (`<name>` = the base file name without `_features.parquet`): the keys
`cell_id`, `date` copied from `<name>_features.parquet` (same rows, same order) plus the float32 columns of
`imerg_features`. Per group also `<group>_columns.json` (column -> group) and `<group>_manifest.json` (SHA-256 and row
count of every file, input checksums, configuration), exactly the files `hazard.data.load_table` and
`load_column_map` verify for the `irain`/`iapi`/`inbr` entries of `configs/hazard_v3.yaml`; and `imerg_report.json`
(NaN share per column per file, IMERG days missing, runtime). The files are then read-only (frozen); a second build
verifies and reuses them, `--force` rebuilds. The frozen v2 feature store is only read.

Inputs recorded in the manifests: the SHA-256 of `features_manifest.json` and of the IMERG index. The index changes
whenever the live runner appends a day, so the checked value covers only its entries up to the last sample date (a
`signature`: present days with their source version, missing and failed days); the whole-file checksum is kept for
information.

CLI: python -m aetherguard.features.imerg_build [--out-dir DIR] [--force]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import PROJECT_ROOT, data_root
from ..ingest import imerg as imerg_mod
from ..manifest import sha256_file
from . import imerg_features as F
from .build import MANIFEST_NAME as FEATURES_MANIFEST
from .build import load_configs

REPORT_NAME = "imerg_report.json"


class ImergFeaturesIntegrityError(RuntimeError):
    """A frozen IMERG feature directory is damaged, stale or incompatible with the current inputs / configuration."""


@dataclass(frozen=True)
class ImergInputs:
    features_dir: Path       # the frozen v2 feature store: base tables and features_manifest.json
    index_path: Path         # imerg_late_index.json of the store the features are computed from


def default_inputs() -> ImergInputs:
    root = data_root() / "processed"
    return ImergInputs(features_dir=root / "features", index_path=root / "rain" / "imerg_late_index.json")


def default_out_dir() -> Path:
    return data_root() / "processed" / "features" / "imerg"


def manifest_name(group: str) -> str:
    return f"{group}_manifest.json"


def columns_name(group: str) -> str:
    return f"{group}_columns.json"


def table_name(base: str, group: str) -> str:
    return f"{base}_{group}.parquet"


def base_stem(sample_file: str) -> str:
    """`train_samples` for `train_samples.parquet` (the name of the table, as `hazard.data.load_table` takes it)."""
    return Path(sample_file).stem


def base_name(stem: str) -> str:
    return f"{stem}_features.parquet"


def build_config() -> dict:
    """Everything that changes a feature value (chunking does not)."""
    train = load_configs()["splits"]["day_splits"]["train"]
    return {"acc_windows": list(F.ACC_WINDOWS), "api_decays": list(F.API_DECAYS), "api_spinup": F.API_SPINUP,
            "clim_windows": list(F.CLIM_WINDOWS), "nbr_windows": list(F.NBR_WINDOWS),
            "climatology": {"first_day": str(train["start"]), "last_day": str(train["end"])}}


def _display_path(path: Path) -> str:
    try:
        return Path(path).resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return Path(path).name


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _set_mode(paths, mode: int) -> None:
    for path in paths:
        if Path(path).exists():
            os.chmod(path, mode)


def _managed(out_dir: Path, stems: list[str]) -> list[Path]:
    tables = [out_dir / table_name(s, g) for s in stems for g in F.GROUPS]
    sidecars = [out_dir / n for g in F.GROUPS for n in (columns_name(g), manifest_name(g))]
    return [*tables, *sidecars, out_dir / REPORT_NAME]


# --------------------------------------------------------------------------------------- inputs and coverage

def index_signature(index_path: Path, through: date) -> str:
    """SHA-256 of the IMERG index entries up to and including `through`: per year the source version of every
    present day, and the missing and failed days."""
    years = json.loads(Path(index_path).read_text(encoding="utf-8"))["years"]
    cut = through.isoformat()
    payload = {y: {"versions": {d: v for d, v in sorted(e["versions"].items()) if d <= cut},
                   "missing": sorted(d for d in e["missing"] if d <= cut),
                   "failed": sorted(d for d in e["failed"] if d <= cut)}
               for y, e in sorted(years.items()) if int(y) <= through.year}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def coverage_gaps(index_path: Path, first: date, last: date) -> list[str]:
    """ISO dates in first..last that the IMERG index does not list as present."""
    years = json.loads(Path(index_path).read_text(encoding="utf-8"))["years"]
    present = {d for entry in years.values() for d in entry["present"]}
    days = (first + timedelta(k) for k in range((last - first).days + 1))
    return [d.isoformat() for d in days if d.isoformat() not in present]


def _sample_stems(inputs: ImergInputs) -> tuple[list[str], dict]:
    path = inputs.features_dir / FEATURES_MANIFEST
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"{FEATURES_MANIFEST} not found in {inputs.features_dir} "
                                "(build the feature store first)") from exc
    stems = [base_stem(f) for f in manifest["sample_files"]]
    for stem in stems:
        file = inputs.features_dir / base_name(stem)
        entry = manifest["files"].get(file.name)
        if not file.is_file() or entry is None or sha256_file(file) != entry["sha256"]:
            raise ImergFeaturesIntegrityError(f"{file.name} is missing or does not match {FEATURES_MANIFEST}")
    return stems, manifest


def _input_records(inputs: ImergInputs, through: date) -> dict:
    return {"features_manifest": {"path": _display_path(inputs.features_dir / FEATURES_MANIFEST),
                                  "sha256": sha256_file(inputs.features_dir / FEATURES_MANIFEST)},
            "imerg_index": {"path": _display_path(inputs.index_path), "through": through.isoformat(),
                            "signature": index_signature(inputs.index_path, through),
                            "file_sha256_at_build": sha256_file(inputs.index_path)}}


# ------------------------------------------------------------------------------------------------- build

def _nan_share(table: pd.DataFrame) -> dict[str, float]:
    return {c: float(table[c].isna().mean()) for c in table.columns}


def build_imerg_tables(inputs: ImergInputs, out_dir, store, force: bool = False,
                       cfg: dict | None = None) -> tuple[dict, bool]:
    """Write the frozen IMERG feature tables; returns ({group: manifest}, reused).

    `store` is an `ImergStore` (or anything with the same `gather`). With manifests present and `force` False
    nothing is rewritten: files, inputs and configuration are verified and the stored manifests returned with
    reused=True; any problem raises ImergFeaturesIntegrityError.
    """
    out_dir = Path(out_dir)
    cfg = cfg if cfg is not None else build_config()
    if not force and any((out_dir / manifest_name(g)).exists() for g in F.GROUPS):
        result = verify_imerg_tables(out_dir, inputs, cfg)
        if not result["ok"]:
            raise ImergFeaturesIntegrityError(f"{out_dir} is frozen but not intact (pass force=True to rebuild): "
                                              + "; ".join(result["problems"]))
        return {g: json.loads((out_dir / manifest_name(g)).read_text(encoding="utf-8")) for g in F.GROUPS}, True

    started = time.perf_counter()
    stems, _ = _sample_stems(inputs)
    keys = {stem: pd.read_parquet(inputs.features_dir / base_name(stem), columns=["cell_id", "date"])
            for stem in stems}
    through = max(pd.Timestamp(k["date"].max()) for k in keys.values()).date()
    cells = np.unique(np.concatenate([k["cell_id"].to_numpy(dtype=np.int64) for k in keys.values()]))
    train = cfg["climatology"]
    clim = F.imerg_climatology(store, F.cell_pixels(cells), date.fromisoformat(train["first_day"]),
                               date.fromisoformat(train["last_day"]), pixel_chunk=1500)
    clim_seconds = time.perf_counter() - started

    out_dir.mkdir(parents=True, exist_ok=True)
    _set_mode(_managed(out_dir, stems), stat.S_IWRITE | stat.S_IREAD)
    rows: dict[str, int] = {}
    per_file: dict[str, dict] = {}
    for stem in stems:
        tick = time.perf_counter()
        frame = keys[stem]
        features = F.build_imerg_features(frame, store, clim)
        outside = int((F.cell_pixels(frame["cell_id"].to_numpy(dtype=np.int64)) < 0).sum())
        for group, names in F.feature_names().items():
            table = pd.concat([frame[["cell_id", "date"]].reset_index(drop=True),
                               features[names].reset_index(drop=True)], axis=1)
            table.to_parquet(out_dir / table_name(stem, group), index=False)
            rows[table_name(stem, group)] = len(table)
        per_file[base_name(stem)] = {"rows": len(frame), "rows_outside_grid": outside,
                                     "nan_share": _nan_share(features), "seconds": round(time.perf_counter() - tick, 1)}
    for group, names in F.feature_names().items():
        _write_json(out_dir / columns_name(group), {c: group for c in names})

    first_needed = date.fromisoformat(str(imerg_mod.HISTORY_START))
    gaps = coverage_gaps(inputs.index_path, first_needed, through)
    total = round(time.perf_counter() - started, 1)
    _write_json(out_dir / REPORT_NAME, {
        "files": per_file,
        "climatology": {"first_day": train["first_day"], "last_day": train["last_day"], "pixels": int(len(clim.pix))},
        "imerg_days_missing": {"first_day": first_needed.isoformat(), "last_day": through.isoformat(),
                               "n_missing": len(gaps), "days": gaps},
        "seconds": {"climatology": round(clim_seconds, 1), "total": total}})

    created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    records = _input_records(inputs, through)
    for group in F.GROUPS:
        names = [columns_name(group), REPORT_NAME]
        files = {n: {"sha256": sha256_file(out_dir / n), "size_bytes": (out_dir / n).stat().st_size, "n_rows": None}
                 for n in names}
        for stem in stems:
            n = table_name(stem, group)
            files[n] = {"sha256": sha256_file(out_dir / n), "size_bytes": (out_dir / n).stat().st_size,
                        "n_rows": rows[n]}
        _write_json(out_dir / manifest_name(group), {
            "created_utc": created, "frozen": True, "group": group, "config": cfg, "inputs": records,
            "sample_files": [base_name(s) for s in stems], "files": files, "runtime_seconds": total})
    _set_mode(_managed(out_dir, stems), stat.S_IREAD)
    return {g: json.loads((out_dir / manifest_name(g)).read_text(encoding="utf-8")) for g in F.GROUPS}, False


# ------------------------------------------------------------------------------------------------ verify

def _content_problems(out_dir: Path, group: str, manifest: dict, inputs: ImergInputs | None) -> list[str]:
    expected = F.feature_names()[group]
    problems: list[str] = []
    try:
        columns = json.loads((out_dir / columns_name(group)).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"cannot read {columns_name(group)}: {exc}"]
    if columns != {c: group for c in expected}:
        problems.append(f"{columns_name(group)} does not map exactly the {group} columns to `{group}`")
    for base in manifest["sample_files"]:
        name = table_name(base_stem(base).removesuffix("_features"), group)
        try:
            table = pd.read_parquet(out_dir / name)
        except (OSError, ValueError) as exc:
            problems.append(f"cannot read {name}: {exc}")
            continue
        if list(table.columns) != ["cell_id", "date", *expected]:
            problems.append(f"{name}: columns are not cell_id, date and the {group} features")
            continue
        wrong = [c for c in expected if table[c].dtype != np.float32]
        if wrong:
            problems.append(f"{name}: feature columns not float32: {wrong[:5]}")
        if np.isinf(table[expected].to_numpy(dtype=np.float64)).any():
            problems.append(f"{name}: infinite feature values")
        if inputs is not None:
            keys = pd.read_parquet(inputs.features_dir / base, columns=["cell_id", "date"])
            if not table[["cell_id", "date"]].equals(keys):
                problems.append(f"{name}: keys (cell_id, date) differ from {base} in value or order")
    return problems


def verify_imerg_tables(out_dir, inputs: ImergInputs | None = None, cfg: dict | None = None) -> dict:
    """Check the frozen files against the manifests; returns {"ok": bool, "problems": [str]}.

    Always: manifests present and readable, file checksums, columns files, float32 finite-or-NaN feature columns.
    With `inputs`: unchanged feature-store manifest and IMERG index entries, keys identical to the base tables.
    With `cfg`: configuration equal to the frozen one. Raises FileNotFoundError only when no manifest exists.
    """
    out_dir = Path(out_dir)
    present = [g for g in F.GROUPS if (out_dir / manifest_name(g)).is_file()]
    if not present:
        raise FileNotFoundError(f"no {manifest_name('<group>')} found in {out_dir}")
    problems = [f"missing: {manifest_name(g)}" for g in F.GROUPS if g not in present]
    manifests: dict[str, dict] = {}
    for group in present:
        try:
            manifest = json.loads((out_dir / manifest_name(group)).read_text(encoding="utf-8"))
            manifest["files"], manifest["config"], manifest["inputs"], manifest["sample_files"]
        except (ValueError, KeyError, TypeError) as exc:
            problems.append(f"{manifest_name(group)} unreadable or incomplete: {exc!r}")
            continue
        manifests[group] = manifest
        if manifest.get("frozen") is not True:
            problems.append(f"{manifest_name(group)} says the features are not frozen")
        if cfg is not None and json.loads(json.dumps(cfg)) != manifest["config"]:
            problems.append(f"{group}: configuration changed after freezing")
        for name, entry in manifest["files"].items():
            path = out_dir / name
            if not path.is_file():
                problems.append(f"missing: {name}")
            elif sha256_file(path) != entry["sha256"]:
                problems.append(f"checksum mismatch: {name}")
        if inputs is not None:
            recorded = manifest["inputs"]
            if sha256_file(inputs.features_dir / FEATURES_MANIFEST) != recorded["features_manifest"]["sha256"]:
                problems.append(f"{group}: input changed after freezing: {FEATURES_MANIFEST}")
            through = date.fromisoformat(recorded["imerg_index"]["through"])
            if index_signature(inputs.index_path, through) != recorded["imerg_index"]["signature"]:
                problems.append(f"{group}: input changed after freezing: IMERG index entries up to {through}")
    if problems:
        return {"ok": False, "problems": problems}
    for group, manifest in manifests.items():
        problems.extend(_content_problems(out_dir, group, manifest, inputs))
    return {"ok": not problems, "problems": problems}


# ----------------------------------------------------------------------------------------------------- CLI

def format_summary(manifests: dict, report: dict, out_dir: Path, reused: bool) -> str:
    runtime = max(m["runtime_seconds"] for m in manifests.values())
    lines = [f"IMERG features {'reused (verified intact)' if reused else 'built and frozen'} in {out_dir} "
             f"({runtime} s to build)"]
    for name, entry in report["files"].items():
        shares = entry["nan_share"]
        by_group = ", ".join(f"{g} {np.mean([shares[c] for c in names]):.1%}" for g, names in F.feature_names().items())
        lines.append(f"{name}: {entry['rows']} rows ({entry['rows_outside_grid']} outside the grid); "
                     f"mean NaN share {by_group}")
    gaps = report["imerg_days_missing"]
    if gaps["n_missing"]:
        lines.append(f"WARNING: {gaps['n_missing']} IMERG days missing in {gaps['first_day']}..{gaps['last_day']}: "
                     f"{', '.join(gaps['days'][:20])}{' ...' if gaps['n_missing'] > 20 else ''}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build and freeze the v3-live IMERG feature tables.")
    parser.add_argument("--out-dir", type=Path, help="default: <data>/processed/features/imerg")
    parser.add_argument("--force", action="store_true", help="replace an existing frozen build")
    args = parser.parse_args(argv)
    inputs = default_inputs()
    out_dir = args.out_dir or default_out_dir()
    store = imerg_mod.ImergStore(inputs.index_path.parent, run="late")
    try:
        manifests, reused = build_imerg_tables(inputs, out_dir, store, force=args.force)
    except (ImergFeaturesIntegrityError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        store.close()
    report = json.loads((out_dir / REPORT_NAME).read_text(encoding="utf-8"))
    print(format_summary(manifests, report, out_dir, reused))
    return 0


if __name__ == "__main__":
    sys.exit(main())
