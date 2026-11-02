"""Build, freeze and verify the positive cell-day tables and the evaluation splits (design D4)."""
from __future__ import annotations

import io
import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ..config import PROJECT_ROOT, load_config
from ..manifest import sha256_file
from . import rules

CELL_DAYS_NAME = "positive_cell_days.parquet"
WINDOWS_NAME = "window_positives.parquet"
MANIFEST_NAME = "splits_manifest.json"
OUTPUT_NAMES = (CELL_DAYS_NAME, WINDOWS_NAME)


class SplitsFrozenError(RuntimeError):
    """The splits directory already holds a frozen build and `force` was not given."""


def _display_path(path: Path) -> str:
    """Project-relative POSIX path, or just the file name for a file outside the project."""
    try:
        return Path(path).resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return Path(path).name


def _set_mode(paths, mode: int) -> None:
    for path in paths:
        if Path(path).exists():
            os.chmod(path, mode)


def _make_writable(out_dir: Path) -> None:
    _set_mode([out_dir / name for name in (*OUTPUT_NAMES, MANIFEST_NAME)], stat.S_IWRITE | stat.S_IREAD)


def _make_read_only(out_dir: Path) -> None:
    _set_mode([out_dir / name for name in (*OUTPUT_NAMES, MANIFEST_NAME)], stat.S_IREAD)


def _iso(value) -> str | None:
    return None if pd.isna(value) else pd.Timestamp(value).strftime("%Y-%m-%d")


def _region_counts(rows: pd.DataFrame, regions: list[str], unit: str) -> dict:
    by_region = rows.groupby("region")["n_events"].agg(["size", "sum"])
    return {r: {unit: int(by_region.loc[r, "size"]) if r in by_region.index else 0,
                "events": int(by_region.loc[r, "sum"]) if r in by_region.index else 0}
            for r in regions}


def _split_summary(rows: pd.DataFrame, regions: list[str]) -> dict:
    return {"cell_days": len(rows), "events": int(rows["n_events"].sum()),
            "min_date": _iso(rows["event_date"].min()), "max_date": _iso(rows["event_date"].max()),
            "regions": _region_counts(rows, regions, "cell_days")}


def _manifest(events_path: Path, events: pd.DataFrame, cell_days: pd.DataFrame, windows: pd.DataFrame,
              out_dir: Path, cfg: dict) -> dict:
    regions = sorted(set(cell_days["region"]) | set(windows["region"]))
    files = {name: {"sha256": sha256_file(out_dir / name), "size_bytes": (out_dir / name).stat().st_size,
                    "n_rows": len(table)}
             for name, table in ((CELL_DAYS_NAME, cell_days), (WINDOWS_NAME, windows))}
    case_studies = {}
    for name, spec in cfg["case_studies"].items():
        rows = cell_days[cell_days["case_study"] == name]
        case_studies[name] = {"region": spec["region"], "start": spec["start"], "end": spec["end"],
                              "cell_days": len(rows), "events": int(rows["n_events"].sum())}
    window_spec = cfg["window_test"]
    window_regions = _region_counts(windows, regions, "cell_windows")
    return {
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "frozen": True,
        "config": cfg,
        "events": {"path": _display_path(events_path), "sha256": sha256_file(events_path),
                   "n_rows": len(events)},
        "files": files,
        "totals": {"day_exact_cell_days": len(cell_days), "day_exact_events": int(cell_days["n_events"].sum()),
                   "window_cells": len(windows), "window_events": int(windows["n_events"].sum())},
        "splits": {name: _split_summary(cell_days[cell_days["split"] == name], regions)
                   for name in cfg["day_splits"]},
        "window_test": {"name": window_spec["name"], "cell_windows": len(windows),
                        "events": int(windows["n_events"].sum()),
                        "window_start_min": _iso(windows["window_start"].min()),
                        "window_end_max": _iso(windows["window_end"].max()),
                        "regions": window_regions},
        "case_studies": case_studies,
        "leakage": rules.leakage_report(cell_days, cfg),
    }


def build_splits(events_path, out_dir, force: bool = False) -> dict:
    """Write the cell-day tables and the checksummed manifest, then mark them read-only (frozen).

    Raises `SplitsFrozenError` (changing nothing) when a manifest already exists and `force` is False.
    All computation happens before the first write, so a failing build leaves the directory untouched.
    """
    events_path, out_dir = Path(events_path), Path(out_dir)
    manifest_path = out_dir / MANIFEST_NAME
    if manifest_path.exists() and not force:
        raise SplitsFrozenError(f"{out_dir} is frozen ({MANIFEST_NAME} exists); pass force=True to rebuild it")
    cfg = load_config("splits")
    events = pd.read_parquet(events_path)
    cell_days, windows = rules.build_tables(events, cfg)

    out_dir.mkdir(parents=True, exist_ok=True)
    _make_writable(out_dir)
    cell_days.to_parquet(out_dir / CELL_DAYS_NAME, index=False)
    windows.to_parquet(out_dir / WINDOWS_NAME, index=False)
    manifest = _manifest(events_path, events, cell_days, windows, out_dir, cfg)
    manifest_path.write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    _make_read_only(out_dir)
    return manifest


def _roundtrip(df: pd.DataFrame) -> pd.DataFrame:
    """Pass a table through parquet so in-memory dtypes match what was stored on disk."""
    buffer = io.BytesIO()
    df.to_parquet(buffer, index=False)
    buffer.seek(0)
    return pd.read_parquet(buffer)


def _check_reproduction(out_dir: Path, events_path: Path, cfg: dict) -> list[str]:
    try:
        cell_days, windows = rules.build_tables(pd.read_parquet(events_path), cfg)
    except (OSError, ValueError, KeyError) as exc:
        return [f"cannot reproduce the splits from {events_path.name}: {exc}"]
    problems = []
    for name, table in ((CELL_DAYS_NAME, cell_days), (WINDOWS_NAME, windows)):
        try:
            stored = pd.read_parquet(out_dir / name)
        except (OSError, ValueError) as exc:
            problems.append(f"cannot read {name} to compare with the events: {exc}")
            continue
        try:
            pd.testing.assert_frame_equal(stored, _roundtrip(table))
        except AssertionError as exc:
            problems.append(f"{name} does not reproduce from the events ({str(exc).splitlines()[0]})")
    return problems


def verify_splits(out_dir, events_path=None) -> dict:
    """Check the frozen files against the manifest; returns {"ok": bool, "problems": [str]}.

    Raises FileNotFoundError only when the manifest itself is missing. With `events_path` it also checks
    the label store is unchanged and that re-running the split computation reproduces the stored tables.
    """
    out_dir = Path(out_dir)
    manifest_path = out_dir / MANIFEST_NAME
    if not manifest_path.is_file():
        raise FileNotFoundError(f"{MANIFEST_NAME} not found in {out_dir}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        recorded = manifest["files"]
        cfg = manifest["config"]
        events_sha = manifest["events"]["sha256"]
    except (ValueError, KeyError, TypeError) as exc:
        return {"ok": False, "problems": [f"manifest unreadable or incomplete: {exc!r}"]}

    problems: list[str] = []
    if manifest.get("frozen") is not True:
        problems.append("manifest says the splits are not frozen")
    for name, entry in recorded.items():
        path = out_dir / name
        if not path.is_file():
            problems.append(f"missing: {name}")
        elif sha256_file(path) != entry["sha256"]:
            problems.append(f"checksum mismatch: {name}")
    if events_path is not None:
        events_path = Path(events_path)
        if not events_path.is_file():
            problems.append(f"events file missing: {events_path.name}")
        else:
            if sha256_file(events_path) != events_sha:
                problems.append(f"events checksum mismatch: {events_path.name} changed after freezing")
            problems.extend(_check_reproduction(out_dir, events_path, cfg))
    return {"ok": not problems, "problems": problems}
