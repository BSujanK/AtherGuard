"""Build, freeze and verify the feature tables of Phase 1 Task 5b.

For every sample file listed in the frozen `samples_manifest.json` this writes `<stem>_features.parquet` with the
IDENTICAL rows and row order (all sample columns kept) plus lat, lon, month, rain_source and the float32 feature
columns of `compute`. Also written: `feature_columns.json` (column -> group; every non-feature column is group
`meta`), `feature_report.json` (rows, NaN shares, source usage, runtime) and `features_manifest.json` (SHA-256 of
every file, input checksums, configuration). The files are then read-only (frozen); a second build verifies and
reuses them, `force=True` rebuilds. Feature groups: rain, src, wet, stat (the `integ` group is built later).
"""
from __future__ import annotations

import json
import os
import stat
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import PROJECT_ROOT, data_root, load_config
from ..manifest import sha256_file
from .compute import STAT_COLUMNS, FeatureContext, compute_features, feature_names
from .sources import day_numbers

MANIFEST_NAME = "features_manifest.json"
COLUMNS_NAME = "feature_columns.json"
REPORT_NAME = "feature_report.json"
SAMPLES_MANIFEST = "samples_manifest.json"


class FeaturesIntegrityError(RuntimeError):
    """A frozen feature directory is damaged, stale or incompatible with the current inputs / configuration."""


@dataclass(frozen=True)
class FeatureInputs:
    samples_dir: Path
    terrain: Path
    imd_dir: Path
    chirps_dir: Path
    power_npz: Path

    def checksummed(self) -> dict[str, Path]:
        """Small or decisive files whose checksum is recorded (the multi-GB rain arrays are covered by their indexes)."""
        return {"samples_manifest": self.samples_dir / SAMPLES_MANIFEST, "terrain": self.terrain,
                "imd_index": self.imd_dir / "imd_index.json", "chirps_index": self.chirps_dir / "chirps_index.json",
                "power": self.power_npz}


def default_inputs() -> FeatureInputs:
    root = data_root() / "processed"
    return FeatureInputs(samples_dir=root / "features" / "samples", terrain=root / "terrain" / "cell_terrain.parquet",
                         imd_dir=root / "rain", chirps_dir=root / "rain", power_npz=root / "rain" / "power_wetness.npz")


def default_out_dir() -> Path:
    return data_root() / "processed" / "features"


def load_configs() -> dict:
    splits = load_config("splits")
    return {"features": load_config("features"), "splits": {"day_splits": splits["day_splits"]}}


def _display_path(path: Path) -> str:
    try:
        return Path(path).resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return Path(path).name


def features_name(sample_file: str) -> str:
    return f"{Path(sample_file).stem}_features.parquet"


def _sample_files(inputs: FeatureInputs) -> list[str]:
    try:
        manifest = json.loads((inputs.samples_dir / SAMPLES_MANIFEST).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"{SAMPLES_MANIFEST} not found in {inputs.samples_dir} (build the samples first)") from exc
    for name, entry in manifest["files"].items():
        path = inputs.samples_dir / name
        if not path.is_file() or sha256_file(path) != entry["sha256"]:
            raise FeaturesIntegrityError(f"sample file {name} is missing or does not match {SAMPLES_MANIFEST}")
    return list(manifest["files"])


def _train_days(cfg: dict) -> tuple[int, int]:
    spec = cfg["splits"]["day_splits"][cfg["features"]["climatology"]["split"]]
    return int(day_numbers([spec["start"]])[0]), int(day_numbers([spec["end"]])[0])


def column_groups(columns: list[str]) -> dict[str, str]:
    """column -> group for every output column: a feature prefix group, or `meta`."""
    groups = {c: g for g, names in feature_names().items() for c in names}
    return {c: groups.get(c, "meta") for c in columns}


def _counts(values: pd.Series) -> dict[str, int]:
    return {k: int(v) for k, v in values.value_counts().sort_index().items()}


def _nan_report(table: pd.DataFrame) -> dict:
    out = {}
    for group, names in feature_names().items():
        missing = table[names].isna()
        out[group] = {"mean_column_nan_share": float(missing.to_numpy().mean()),
                      "rows_any_nan": float(missing.any(axis=1).mean()),
                      "rows_all_nan": float(missing.all(axis=1).mean())}
    return out


def _file_report(table: pd.DataFrame) -> dict:
    report = {"rows": len(table), "nan_share": _nan_report(table), "rain_source": _counts(table["rain_source"])}
    if "kind" in table.columns:
        report["by_kind"] = {kind: {"rows": len(part), "nan_share": _nan_report(part),
                                    "rain_source": _counts(part["rain_source"])}
                             for kind, part in table.groupby("kind")}
    if "rain_ok" in table.columns:
        bad = table[~table["rain_ok"].astype(bool)]
        has_source = bad["rain_source"] != "none"
        report["rain_ok_false"] = {
            "rows": len(bad),
            "no_rain_source_on_day": int((~has_source).sum()),
            "source_but_30_day_window_incomplete": int((has_source & bad["rain_acc_30"].isna()).sum()),
            "source_and_30_day_window_complete": int((has_source & bad["rain_acc_30"].notna()).sum()),
            "by_split": _counts(bad["split"]) if "split" in bad.columns else {}}
        report["rain_ok_true_but_acc30_nan"] = int(table.loc[table["rain_ok"].astype(bool), "rain_acc_30"].isna().sum())
    return report


def _set_mode(paths, mode: int) -> None:
    for path in paths:
        if Path(path).exists():
            os.chmod(path, mode)


def _managed(out_dir: Path, sample_files: list[str]) -> list[Path]:
    return [out_dir / n for n in (*(features_name(f) for f in sample_files), COLUMNS_NAME, REPORT_NAME, MANIFEST_NAME)]


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def build_features(inputs: FeatureInputs, out_dir, force: bool = False, cfg: dict | None = None) -> tuple[dict, bool]:
    """Write the frozen feature tables; returns (manifest, reused).

    With a manifest present and `force` False nothing is rewritten: files, input checksums and configuration are
    verified and the stored manifest returned with reused=True; any problem raises FeaturesIntegrityError.
    """
    out_dir = Path(out_dir)
    cfg = cfg if cfg is not None else load_configs()
    manifest_path = out_dir / MANIFEST_NAME
    if manifest_path.exists() and not force:
        result = verify_features(out_dir, inputs, cfg)
        if not result["ok"]:
            raise FeaturesIntegrityError(f"{out_dir} is frozen but not intact (pass force=True to rebuild): "
                                         + "; ".join(result["problems"]))
        return json.loads(manifest_path.read_text(encoding="utf-8")), True

    started = time.perf_counter()
    sample_files = _sample_files(inputs)
    cells = np.unique(np.concatenate([pd.read_parquet(inputs.samples_dir / f, columns=["cell_id"])["cell_id"]
                                      .to_numpy(dtype=np.int64) for f in sample_files]))
    terrain = pd.read_parquet(inputs.terrain, columns=["cell_id", *STAT_COLUMNS])
    first_day, last_day = _train_days(cfg)
    context = FeatureContext.build(cells, inputs.imd_dir, inputs.chirps_dir, inputs.power_npz, terrain, first_day,
                                   last_day, pixel_chunk=cfg["features"]["pixel_chunk"])
    context_seconds = time.perf_counter() - started

    out_dir.mkdir(parents=True, exist_ok=True)
    _set_mode(_managed(out_dir, sample_files), stat.S_IWRITE | stat.S_IREAD)
    per_file, columns, rows = {}, {}, {}
    for sample_file in sample_files:
        tick = time.perf_counter()
        table = compute_features(pd.read_parquet(inputs.samples_dir / sample_file), context,
                                 chunk_rows=cfg["features"]["chunk_rows"])
        name = features_name(sample_file)
        table.to_parquet(out_dir / name, index=False)
        columns.update(column_groups(list(table.columns)))
        per_file[name] = {**_file_report(table), "seconds": round(time.perf_counter() - tick, 1)}
        rows[name] = len(table)
    _write_json(out_dir / COLUMNS_NAME, columns)
    report = {"files": per_file,
              "source_usage": {"imd": dict(context.imd.counters), "chirps": dict(context.chirps.counters),
                               "wetness": dict(context.wet_top.counters)},
              "climatology": {"first_day": str(np.datetime64(first_day, "D")),
                              "last_day": str(np.datetime64(last_day, "D")),
                              "imd_pixels": len(context.clim_imd.pix), "chirps_pixels": len(context.clim_chirps.pix)},
              "seconds": {"context_and_climatology": round(context_seconds, 1),
                          "total": round(time.perf_counter() - started, 1)}}
    _write_json(out_dir / REPORT_NAME, report)
    files = {name: {"sha256": sha256_file(out_dir / name), "size_bytes": (out_dir / name).stat().st_size,
                    "n_rows": rows.get(name)} for name in (*rows, COLUMNS_NAME, REPORT_NAME)}
    manifest = {
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "frozen": True,
        "config": cfg,
        "inputs": {name: {"path": _display_path(path), "sha256": sha256_file(path)}
                   for name, path in inputs.checksummed().items()},
        "sample_files": sample_files,
        "files": files,
        "runtime_seconds": report["seconds"]["total"],
    }
    _write_json(manifest_path, manifest)
    _set_mode(_managed(out_dir, sample_files), stat.S_IREAD)
    return json.loads(manifest_path.read_text(encoding="utf-8")), False


def _content_problems(out_dir: Path, manifest: dict, inputs: FeatureInputs | None) -> list[str]:
    try:
        groups = json.loads((out_dir / COLUMNS_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"cannot read {COLUMNS_NAME}: {exc}"]
    problems: list[str] = []
    feature_columns = [c for c, g in groups.items() if g != "meta"]
    required = [c for names in feature_names().values() for c in names]
    for sample_file in manifest["sample_files"]:
        name = features_name(sample_file)
        try:
            table = pd.read_parquet(out_dir / name)
        except (OSError, ValueError) as exc:
            problems.append(f"cannot read {name}: {exc}")
            continue
        unlisted = [c for c in table.columns if c not in groups]
        if unlisted:
            problems.append(f"{name}: columns not in {COLUMNS_NAME}: {unlisted[:5]}")
        missing = [c for c in required if c not in table.columns]
        if missing:
            problems.append(f"{name}: missing feature columns: {missing[:5]}")
            continue
        wrong = [c for c in feature_columns if c in table.columns and table[c].dtype != np.float32]
        if wrong:
            problems.append(f"{name}: feature columns not float32: {wrong[:5]}")
        if np.isinf(table[required].to_numpy(dtype=np.float64)).any():
            problems.append(f"{name}: infinite feature values")
        if inputs is not None:
            samples = pd.read_parquet(inputs.samples_dir / sample_file)
            if list(table.columns[:len(samples.columns)]) != list(samples.columns):
                problems.append(f"{name}: leading columns differ from {sample_file}")
            elif not table[list(samples.columns)].equals(samples):
                problems.append(f"{name}: rows / row order differ from {sample_file}")
    return problems


def verify_features(out_dir, inputs: FeatureInputs | None = None, cfg: dict | None = None) -> dict:
    """Check the frozen files against the manifest; returns {"ok": bool, "problems": [str]}.

    Always: file checksums, feature columns float32 and finite-or-NaN, every column grouped in feature_columns.json.
    With `inputs`: unchanged input checksums and identical rows / row order versus the sample files.
    With `cfg`: configuration equal to the frozen one. Raises FileNotFoundError only when the manifest is missing.
    """
    out_dir = Path(out_dir)
    manifest_path = out_dir / MANIFEST_NAME
    if not manifest_path.is_file():
        raise FileNotFoundError(f"{MANIFEST_NAME} not found in {out_dir}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        recorded, frozen_cfg, recorded_inputs = manifest["files"], manifest["config"], manifest["inputs"]
        manifest["sample_files"]
    except (ValueError, KeyError, TypeError) as exc:
        return {"ok": False, "problems": [f"manifest unreadable or incomplete: {exc!r}"]}
    problems: list[str] = []
    if manifest.get("frozen") is not True:
        problems.append("manifest says the features are not frozen")
    if cfg is not None and json.loads(json.dumps(cfg)) != frozen_cfg:
        problems.append("configuration changed after freezing")
    for name, entry in recorded.items():
        path = out_dir / name
        if not path.is_file():
            problems.append(f"missing: {name}")
        elif sha256_file(path) != entry["sha256"]:
            problems.append(f"checksum mismatch: {name}")
    if inputs is not None:
        for name, path in inputs.checksummed().items():
            if not Path(path).is_file():
                problems.append(f"input missing: {name} ({Path(path).name})")
            elif sha256_file(path) != recorded_inputs[name]["sha256"]:
                problems.append(f"input changed after freezing: {name} ({Path(path).name})")
    if problems:
        return {"ok": False, "problems": problems}
    problems.extend(_content_problems(out_dir, manifest, inputs))
    return {"ok": not problems, "problems": problems}
