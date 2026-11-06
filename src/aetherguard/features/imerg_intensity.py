"""`iint`: rain-intensity features per 0.05-degree cell from the half-hourly-derived daily fields of `ingest.imerg_hh`
(W3, docs/superpowers/specs/2026-11-06-aetherguard-w3-rain-intensity.md section 1).

Six float32 features for the IMD day D (03:00 UTC on D-1 to 03:00 UTC on D), read from the day files
`<root>/<run>/<yyyy>/<yyyymmdd>.npz` (maps in the orientation of the daily IMERG store, 280 rows x 260 columns of 0.1 degree):
* `iint_max1h_1`, `iint_max3h_1`, `iint_max6h_1`: the largest 1, 3 and 6 hour rain (mm) within day D;
* `iint_max3h_max3d`, `iint_max6h_max3d`: the largest of the 3- and 6-hour maxima over D-2, D-1 and D;
* `iint_wet_hours_1`: hours of day D with at least 0.1 mm/h.

Cell to pixel mapping is that of the daily IMERG features (`imerg_features.cell_pixels`: the 0.1 degree pixel that contains
the cell centre); a cell outside the domain grid is NaN in every column.

NaN rule (strict, as `irain`): a missing day file is NaN, never zero; a three-day maximum is NaN when any of the three days is
NaN at that pixel or has no file. The rolling windows live inside each day file, so they never cross the IMD-day boundary.

Train and serve share the code. The training features read complete Late days (48 half-hours); the live features come from
the same `features_from_maps` fed with a day reduced over the half-hours a live run has (`truncated_from_halfhours`, the
first 44, i.e. `imerg_hh.reduce_day` with `n_expected=44`): only the window end differs.

Frozen tables (`build_iint_tables`): group `iint`, written next to the other IMERG groups with its own columns file, manifest
and report; no existing group or manifest is touched. `<name>_iint.parquet` has the rows (cell_id, date) of every sample file
of the frozen feature store; `season_<year>_iint.parquet` has the cells x days of the held-out season panel
(`season_<year>_training.npz`), cell-major, i.e. the order of `panel[cells, days].ravel()`.

2024 train-serve gap (`train_serve_gap`): the median relative error of `max3h` between the truncated Early days (built with
`imerg_hh --run early --live-window`) and the complete Late days over the wet cell-days (full max3h >= 1 mm); above 20% the live
run must use the previous complete IMD day (declared lag 1) and the model is trained the same way.

CLI: python -m aetherguard.features.imerg_intensity tables [--out-dir DIR] [--root DIR] [--panels-dir DIR] [--years 2018-2025] [--force]
     python -m aetherguard.features.imerg_intensity gap [--root DIR] [--panels-dir DIR] [--start 2024-06-01] [--end 2024-12-31] [--out FILE]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import stat
import sys
import time
from collections import OrderedDict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd

from ..config import PROJECT_ROOT, data_root
from ..hazard.jsonio import dump_json
from ..ingest import imerg as imerg_mod
from ..ingest import imerg_hh
from ..manifest import sha256_file
from . import imerg_build as B
from . import imerg_features as F
from .build import MANIFEST_NAME as FEATURES_MANIFEST

GROUP = "iint"
RUN = "late"                                           # training-style days: complete HHL
LIVE_RUN = imerg_hh.store_name("early", live_window=True)       # truncated HHE days of the gap study
FIELDS = ("max1h", "max3h", "max6h", "wet_hours")
MAX_DAYS = 3
CACHE_DAYS = 6                                         # day maps kept while a date-sorted frame is read
REPORT_NAME = "iint_report.json"
HELDOUT_YEARS = tuple(range(2018, 2026))
PANELS_SUBDIR = ("alerts", "heldout_seasons")          # under the processed directory: verify.seasons.OUT_DIR

WET_MAX3H_MM = 1.0                                     # a cell-day is wet when the complete Late max3h reaches this
GAP_LIMIT = 0.20                                       # spec section 1: median relative error above which the lag applies
GAP_YEAR = 2024
GAP_REPORT = PROJECT_ROOT / "reports" / "phase7_rain_intensity_gap.json"
WET_DEFINITION = f"full Late max3h >= {WET_MAX3H_MM} mm"


class IintIntegrityError(RuntimeError):
    """The frozen iint directory is damaged, stale or incompatible with the current inputs / configuration."""


def feature_names() -> list[str]:
    return ["iint_max1h_1", "iint_max3h_1", "iint_max6h_1", "iint_max3h_max3d", "iint_max6h_max3d", "iint_wet_hours_1"]


def default_root() -> Path:
    return data_root() / "processed" / "imerg_intensity"


def default_panels_dir() -> Path:
    return data_root().joinpath("processed", *PANELS_SUBDIR)


# ------------------------------------------------------------------------------------------ day files

def load_day(root, run: str, day: date) -> dict[str, np.ndarray] | None:
    """The four maps (float32, rows x cols) of the day file of IMD day `day`, or None when there is no such file."""
    path = imerg_hh._day_path(Path(root), run, day)
    if not path.is_file():
        return None
    with np.load(path) as data:
        maps = {name: np.asarray(data[name]) for name in FIELDS}
    for name, values in maps.items():
        if values.shape != (imerg_mod.ROWS, imerg_mod.COLS):
            raise ValueError(f"{path}: {name} has shape {values.shape}, expected {(imerg_mod.ROWS, imerg_mod.COLS)}")
    return {name: values.astype(np.float32, copy=False) for name, values in maps.items()}


class DayLoader:
    """`load_day` for one (root, run) with a small cache, and a record of the day files that were not there."""

    def __init__(self, root, run: str = RUN) -> None:
        self.root, self.run = Path(root), run
        self.missing: set[date] = set()
        self._cache: OrderedDict[date, dict[str, np.ndarray] | None] = OrderedDict()

    def get(self, day: date) -> dict[str, np.ndarray] | None:
        if day in self._cache:
            self._cache.move_to_end(day)
            return self._cache[day]
        maps = load_day(self.root, self.run, day)
        if maps is None:
            self.missing.add(day)
        self._cache[day] = maps
        while len(self._cache) > CACHE_DAYS:
            self._cache.popitem(last=False)
        return maps

    def window(self, day: date) -> list:
        """The maps of D-2, D-1 and D (oldest first), None for a day without a file."""
        return [self.get(day - timedelta(days=k)) for k in range(MAX_DAYS - 1, -1, -1)]


# ------------------------------------------------------------------------------------------ features

def _at(maps: dict[str, np.ndarray] | None, name: str, pixels: np.ndarray, inside: np.ndarray) -> np.ndarray:
    """Value of map `name` at the flat pixels; NaN for a missing day and for pixels outside the grid."""
    if maps is None:
        return np.full(len(pixels), np.nan, dtype=np.float32)
    return np.where(inside, maps[name].reshape(-1)[np.where(inside, pixels, 0)], np.nan).astype(np.float32)


def day_features(maps: dict[str, np.ndarray] | None, pixels) -> np.ndarray:
    """(n, 4) float32 max1h, max3h, max6h and wet hours of ONE day at the flat pixels (NaN where `maps` is None)."""
    pixels = np.asarray(pixels, dtype=np.int64)
    inside = pixels >= 0
    return np.stack([_at(maps, name, pixels, inside) for name in FIELDS], axis=1)


def features_from_maps(window: Sequence, pixels) -> np.ndarray:
    """(n, 6) float32 features (`feature_names` order) at the flat pixels from the day maps of D-2, D-1 and D (None = no file).

    The one-day features are those of D; the three-day maxima are NaN as soon as one of the three days is NaN there."""
    if len(window) != MAX_DAYS:
        raise ValueError(f"the window needs the maps of {MAX_DAYS} days (three: D-2, D-1, D), got {len(window)}")
    pixels = np.asarray(pixels, dtype=np.int64)
    days = [day_features(maps, pixels) for maps in window]
    today = days[-1]
    return np.column_stack([today[:, 0], today[:, 1], today[:, 2],
                            np.max([d[:, 1] for d in days], axis=0),          # NaN propagates through np.max
                            np.max([d[:, 2] for d in days], axis=0), today[:, 3]]).astype(np.float32)


def truncated_from_halfhours(fields: np.ndarray, n_available: int = imerg_hh.LIVE_HALF_HOURS) -> dict[str, np.ndarray]:
    """Day maps over the first `n_available` half-hours of the IMD day (a live run before the day has closed): the same
    `imerg_hh.reduce_day` as the complete day, with the window ending earlier. `fields` may hold more half-hours than that."""
    fields = np.asarray(fields)
    if fields.shape[0] < n_available:
        raise ValueError(f"{n_available} half-hours are needed, got {fields.shape[0]}")
    return imerg_hh.reduce_day(fields[:n_available], n_available)


def cell_features(day: date, cell_ids, root, run: str = RUN) -> pd.DataFrame:
    """The six features of IMD day `day` for each cell (one row per entry of `cell_ids`, in its order, default index)."""
    pixels = F.cell_pixels(cell_ids)
    return pd.DataFrame(features_from_maps(DayLoader(root, run).window(day), pixels), columns=feature_names())


def frame_features(frame: pd.DataFrame, loader: DayLoader) -> pd.DataFrame:
    """The six features for the (cell_id, date) rows of `frame`, in its row order and with its index."""
    pixels = F.cell_pixels(frame["cell_id"].to_numpy(dtype=np.int64))
    values = np.full((len(frame), len(feature_names())), np.nan, dtype=np.float32)
    for stamp, rows in frame.groupby("date", sort=True).indices.items():
        values[rows] = features_from_maps(loader.window(pd.Timestamp(stamp).date()), pixels[rows])
    return pd.DataFrame(values, columns=feature_names(), index=frame.index)


# ------------------------------------------------------------------------------------------ held-out panels

def panel_path(panels_dir, year: int) -> Path:
    return Path(panels_dir) / f"season_{year}_training.npz"


def read_panel(panels_dir, year: int) -> tuple[np.ndarray, list[date]]:
    """Cell ids and days of a held-out season panel (`verify.seasons`)."""
    path = panel_path(panels_dir, year)
    if not path.is_file():
        raise FileNotFoundError(f"{path} not found (score the held-out seasons first: python -m aetherguard.verify seasons)")
    with np.load(path, allow_pickle=False) as data:
        return data["cell_id"].astype(np.int64), [date.fromisoformat(str(d)) for d in data["days"]]


def panel_frame(cell_ids: np.ndarray, days: list[date]) -> pd.DataFrame:
    """(cell_id, date) rows of cells x days, cell-major: the order of `panel[cells, days].ravel()`."""
    stamps = np.array(days, dtype="datetime64[ns]")
    return pd.DataFrame({"cell_id": np.repeat(cell_ids, len(days)), "date": np.tile(stamps, len(cell_ids))})


def season_name(year: int) -> str:
    return f"season_{year}_{GROUP}.parquet"


# ------------------------------------------------------------------------------------------ build and freeze

def build_config(years=HELDOUT_YEARS) -> dict:
    """Everything that changes a feature value."""
    return {"features": feature_names(), "run": RUN, "max_days": MAX_DAYS, "half_hours_per_day": imerg_hh.HALF_HOURS,
            "window_slots": dict(imerg_hh.WINDOW_SLOTS), "wet_mm_per_h": float(imerg_hh.WET_MM_PER_H),
            "heldout_years": [int(y) for y in years]}


def store_signature(root, run: str = RUN) -> tuple[str, int]:
    """(SHA-256 over the relative path and size of every day file of `run`, number of files)."""
    base = Path(root) / run
    entries = sorted(f"{p.relative_to(base).as_posix()}:{p.stat().st_size}" for p in base.rglob("*.npz"))
    return hashlib.sha256("\n".join(entries).encode("utf-8")).hexdigest(), len(entries)


def _input_records(inputs: B.ImergInputs, root, panels_dir, years) -> dict:
    signature, n_files = store_signature(root)
    return {"features_manifest": {"path": B._display_path(inputs.features_dir / FEATURES_MANIFEST),
                                  "sha256": sha256_file(inputs.features_dir / FEATURES_MANIFEST)},
            "intensity_store": {"path": B._display_path(Path(root) / RUN), "signature": signature, "n_files": n_files},
            "season_panels": {str(y): {"path": B._display_path(panel_path(panels_dir, y)),
                                       "sha256": sha256_file(panel_path(panels_dir, y))} for y in years}}


def _managed(out_dir: Path, stems: list[str], years) -> list[Path]:
    return [*(out_dir / B.table_name(s, GROUP) for s in stems), *(out_dir / season_name(y) for y in years),
            out_dir / B.columns_name(GROUP), out_dir / B.manifest_name(GROUP), out_dir / REPORT_NAME]


def _table_report(frame: pd.DataFrame, features: pd.DataFrame, loader: DayLoader, seconds: float) -> dict:
    outside = int((F.cell_pixels(frame["cell_id"].to_numpy(dtype=np.int64)) < 0).sum())
    return {"rows": len(frame), "rows_outside_grid": outside, "nan_share": B._nan_share(features),
            "days_without_file": len(loader.missing), "first_missing_days": [d.isoformat() for d in sorted(loader.missing)[:20]],
            "seconds": round(seconds, 1)}


def build_iint_tables(inputs: B.ImergInputs, out_dir, root, panels_dir, years=HELDOUT_YEARS, force: bool = False,
                      cfg: dict | None = None) -> tuple[dict, bool]:
    """Write the frozen iint tables; returns (manifest, reused). With a manifest present and `force` False nothing is
    rewritten: files, inputs and configuration are verified (IintIntegrityError on any problem)."""
    out_dir, root, panels_dir = Path(out_dir), Path(root), Path(panels_dir)
    cfg = cfg if cfg is not None else build_config(years)
    manifest_path = out_dir / B.manifest_name(GROUP)
    if not force and manifest_path.exists():
        result = verify_iint_tables(out_dir, inputs, root, panels_dir, cfg)
        if not result["ok"]:
            raise IintIntegrityError(f"{out_dir} is frozen but not intact (pass force=True to rebuild): "
                                     + "; ".join(result["problems"]))
        return json.loads(manifest_path.read_text(encoding="utf-8")), True

    started = time.perf_counter()
    stems, _ = B._sample_stems(inputs)
    panels = {y: read_panel(panels_dir, y) for y in years}
    out_dir.mkdir(parents=True, exist_ok=True)
    B._set_mode(_managed(out_dir, stems, years), stat.S_IWRITE | stat.S_IREAD)
    rows: dict[str, int] = {}
    per_file: dict[str, dict] = {}
    jobs = [(B.base_name(stem), B.table_name(stem, GROUP),
             lambda stem=stem: pd.read_parquet(inputs.features_dir / B.base_name(stem), columns=["cell_id", "date"]))
            for stem in stems]
    jobs += [(f"season_{y}_training.npz", season_name(y), lambda y=y: panel_frame(*panels[y])) for y in years]
    for source, name, make_frame in jobs:
        tick = time.perf_counter()
        frame = make_frame()
        loader = DayLoader(root)
        features = frame_features(frame, loader)
        pd.concat([frame[["cell_id", "date"]].reset_index(drop=True), features.reset_index(drop=True)],
                  axis=1).to_parquet(out_dir / name, index=False)
        rows[name] = len(frame)
        per_file[source] = _table_report(frame, features, loader, time.perf_counter() - tick)
    B._write_json(out_dir / B.columns_name(GROUP), {c: GROUP for c in feature_names()})
    total = round(time.perf_counter() - started, 1)
    B._write_json(out_dir / REPORT_NAME, {"files": per_file, "seconds": {"total": total}})
    files = {n: {"sha256": sha256_file(out_dir / n), "size_bytes": (out_dir / n).stat().st_size, "n_rows": None}
             for n in (B.columns_name(GROUP), REPORT_NAME)}
    for name, n_rows in rows.items():
        files[name] = {"sha256": sha256_file(out_dir / name), "size_bytes": (out_dir / name).stat().st_size,
                       "n_rows": n_rows}
    B._write_json(manifest_path, {
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "frozen": True, "group": GROUP,
        "config": cfg, "inputs": _input_records(inputs, root, panels_dir, years),
        "sample_files": [B.base_name(s) for s in stems], "season_files": [season_name(y) for y in years],
        "files": files, "runtime_seconds": total})
    B._set_mode(_managed(out_dir, stems, years), stat.S_IREAD)
    return json.loads(manifest_path.read_text(encoding="utf-8")), False


def verify_iint_tables(out_dir, inputs: B.ImergInputs | None = None, root=None, panels_dir=None,
                       cfg: dict | None = None) -> dict:
    """Check the frozen files against the manifest; returns {"ok": bool, "problems": [str]}. Raises FileNotFoundError
    when there is no manifest. With `inputs`: unchanged feature-store manifest, keys of the sample tables identical to the
    base tables; with `root`: unchanged day files of the intensity store; with `panels_dir`: unchanged season panels and
    keys of the season tables equal to their cells x days; with `cfg`: configuration equal to the frozen one."""
    out_dir = Path(out_dir)
    path = out_dir / B.manifest_name(GROUP)
    if not path.is_file():
        raise FileNotFoundError(f"{path} not found")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["files"], manifest["config"], manifest["inputs"], manifest["sample_files"], manifest["season_files"]
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
    recorded = manifest["inputs"]
    if inputs is not None and sha256_file(inputs.features_dir / FEATURES_MANIFEST) != recorded["features_manifest"]["sha256"]:
        problems.append(f"input changed after freezing: {FEATURES_MANIFEST}")
    if root is not None and store_signature(root)[0] != recorded["intensity_store"]["signature"]:
        problems.append(f"input changed after freezing: the intensity store day files of the `{RUN}` run")
    if panels_dir is not None:
        for year, entry in recorded["season_panels"].items():
            panel = panel_path(panels_dir, int(year))
            if not panel.is_file() or sha256_file(panel) != entry["sha256"]:
                problems.append(f"input changed after freezing: {panel.name}")
    if problems:
        return {"ok": False, "problems": problems}
    return {"ok": True, "problems": _content_problems(out_dir, manifest, inputs, panels_dir)}


def _content_problems(out_dir: Path, manifest: dict, inputs, panels_dir) -> list[str]:
    expected = feature_names()
    problems: list[str] = []
    try:
        columns = json.loads((out_dir / B.columns_name(GROUP)).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"cannot read {B.columns_name(GROUP)}: {exc}"]
    if columns != {c: GROUP for c in expected}:
        problems.append(f"{B.columns_name(GROUP)} does not map exactly the iint columns to `{GROUP}`")
    tables = [(B.table_name(B.base_stem(base).removesuffix("_features"), GROUP), base) for base in manifest["sample_files"]]
    tables += [(name, None) for name in manifest["season_files"]]
    for name, base in tables:
        try:
            table = pd.read_parquet(out_dir / name)
        except (OSError, ValueError) as exc:
            problems.append(f"cannot read {name}: {exc}")
            continue
        if list(table.columns) != ["cell_id", "date", *expected]:
            problems.append(f"{name}: columns are not cell_id, date and the iint features")
            continue
        if any(table[c].dtype != np.float32 for c in expected):
            problems.append(f"{name}: feature columns not float32")
        if np.isinf(table[expected].to_numpy(dtype=np.float64)).any():
            problems.append(f"{name}: infinite feature values")
        keys = None
        if base is not None and inputs is not None:
            keys = pd.read_parquet(inputs.features_dir / base, columns=["cell_id", "date"])
        elif base is None and panels_dir is not None:
            keys = panel_frame(*read_panel(panels_dir, int(name.split("_")[1])))
        if keys is not None and not table[["cell_id", "date"]].equals(keys):
            problems.append(f"{name}: keys (cell_id, date) differ from their source in value or order")
    return problems


# ------------------------------------------------------------------------------------------ train-serve gap

def decide(median_relative_error: float) -> tuple[str, int]:
    """Spec section 1: same-day truncated features unless the median relative error of max3h exceeds `GAP_LIMIT`, in which
    case the live run uses the previous complete IMD day (declared lag 1 day) and the model is trained the same way."""
    if median_relative_error > GAP_LIMIT:
        return "previous_complete_day", 1
    return "same_day_truncated", 0


class _GapStats:
    """Accumulates (full, truncated) max3h pairs over days; only the wet pairs are kept."""

    def __init__(self) -> None:
        self.n = self.n_wet = self.n_live_nan = 0
        self._relative: list[np.ndarray] = []
        self._signed: list[np.ndarray] = []
        self._month: list[np.ndarray] = []

    def add(self, full: np.ndarray, live: np.ndarray, month: str) -> None:
        full, live = full.astype(np.float64), live.astype(np.float64)
        wet = full >= WET_MAX3H_MM
        usable = wet & np.isfinite(live)
        self.n += len(full)
        self.n_wet += int(wet.sum())
        self.n_live_nan += int((wet & ~usable).sum())
        signed = (live[usable] - full[usable]) / full[usable]
        self._signed.append(signed)
        self._relative.append(np.abs(signed))
        self._month.append(np.full(len(signed), month))

    def result(self) -> dict:
        relative = np.concatenate(self._relative) if self._relative else np.empty(0)
        if not len(relative):
            raise ValueError(f"no wet cell-day ({WET_DEFINITION}) with both a complete and a truncated value to compare")
        signed = np.concatenate(self._signed)
        months = np.concatenate(self._month)
        return {"n_cell_days": self.n, "n_wet": self.n_wet, "n_wet_live_nan": self.n_live_nan,
                "n_compared": int(len(relative)), "median_relative_error": float(np.median(relative)),
                "mean_relative_error": float(relative.mean()),
                "percentiles_relative_error": {str(q): float(np.percentile(relative, q)) for q in (25, 75, 90, 95)},
                "median_signed_relative_error": float(np.median(signed)),
                "share_over_limit": float((relative > GAP_LIMIT).mean()),
                "by_month": {m: {"n": int((months == m).sum()), "median_relative_error": float(np.median(relative[months == m]))}
                             for m in sorted(set(months.tolist()))}}


def train_serve_gap(cell_ids, days: Sequence[date], root, full_run: str = RUN, live_run: str = LIVE_RUN) -> dict:
    """Median relative error of max3h, truncated (`live_run` day files) vs complete (`full_run`), over the wet cell-days of
    `days` (full max3h >= `WET_MAX3H_MM`), plus the decision of the 20% rule. The rule is applied to the `cells`
    cell-days; the same statistics over all pixels of the domain are reported as `domain`. Days without a file in either run
    are left out and listed."""
    cell_pixels = F.cell_pixels(cell_ids)
    all_pixels = np.arange(imerg_mod.ROWS * imerg_mod.COLS, dtype=np.int64)
    cells, domain = _GapStats(), _GapStats()
    missing_full: list[str] = []
    missing_live: list[str] = []
    compared = 0
    for day in days:
        full, live = load_day(root, full_run, day), load_day(root, live_run, day)
        if full is None:
            missing_full.append(day.isoformat())
        if live is None:
            missing_live.append(day.isoformat())
        if full is None or live is None:
            continue
        compared += 1
        for stats, pixels in ((cells, cell_pixels), (domain, all_pixels)):
            stats.add(day_features(full, pixels)[:, 1], day_features(live, pixels)[:, 1], f"{day:%Y-%m}")
    cell_result = cells.result()
    decision, lag = decide(cell_result["median_relative_error"])
    return {"year": days[0].year, "limit": GAP_LIMIT, "wet_definition": WET_DEFINITION,
            "measure": "median over wet cell-days of |max3h(truncated Early day) - max3h(complete Late day)| / max3h(complete Late day)",
            "truncated_half_hours": imerg_hh.LIVE_HALF_HOURS, "complete_half_hours": imerg_hh.HALF_HOURS,
            "days": {"first": days[0].isoformat(), "last": days[-1].isoformat(), "requested": len(days),
                     "compared": compared, "missing_full": missing_full, "missing_live": missing_live},
            "cells": {"n_cells": int(len(cell_pixels)), **cell_result}, "domain": domain.result(),
            "decision": decision, "declared_lag_days": lag}


# ------------------------------------------------------------------------------------------------- CLI

def parse_years(text: str) -> tuple[int, ...]:
    low, _, high = text.partition("-")
    years = tuple(range(int(low), int(high or low) + 1))
    if not years:
        raise argparse.ArgumentTypeError(f"empty year range {text!r}")
    return years


def _tables(args) -> int:
    inputs = B.default_inputs()
    out_dir = args.out_dir or B.default_out_dir()
    manifest, reused = build_iint_tables(inputs, out_dir, args.root, args.panels_dir, args.years, force=args.force)
    report = json.loads((out_dir / REPORT_NAME).read_text(encoding="utf-8"))
    print(f"iint {'reused (verified intact)' if reused else 'built and frozen'} in {out_dir} "
          f"({manifest['runtime_seconds']} s to build)")
    for name, entry in report["files"].items():
        print(f"{name}: {entry['rows']} rows ({entry['rows_outside_grid']} outside the grid); mean NaN share "
              f"{np.mean(list(entry['nan_share'].values())):.1%}; {entry['days_without_file']} days without a file")
    return 0


def _gap(args) -> int:
    cells, _ = read_panel(args.panels_dir, GAP_YEAR)
    days = [args.start + timedelta(k) for k in range((args.end - args.start).days + 1)]
    result = train_serve_gap(cells, days, args.root)
    dump_json(args.out, result)
    stats = result["cells"]
    print(f"train-serve gap {days[0]}..{days[-1]}: median relative error of max3h {stats['median_relative_error']:.1%} over "
          f"{stats['n_compared']} wet cell-days ({result['days']['compared']}/{len(days)} days) -> {result['decision']} "
          f"(lag {result['declared_lag_days']} d); written to {args.out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="W3 rain-intensity features and the train-serve gap.")
    sub = parser.add_subparsers(dest="command", required=True)
    tables = sub.add_parser("tables", help="build and freeze the iint feature tables")
    tables.add_argument("--out-dir", type=Path, help="default: <data>/processed/features/imerg")
    tables.add_argument("--years", type=parse_years, default=HELDOUT_YEARS, help="held-out seasons, e.g. 2018-2025")
    tables.add_argument("--force", action="store_true", help="replace an existing frozen build")
    gap = sub.add_parser("gap", help="measure the 2024 train-serve gap and apply the 20%% rule")
    gap.add_argument("--start", type=date.fromisoformat, default=date(GAP_YEAR, 6, 1))
    gap.add_argument("--end", type=date.fromisoformat, default=date(GAP_YEAR, 12, 31))
    gap.add_argument("--out", type=Path, default=GAP_REPORT)
    for p in (tables, gap):
        p.add_argument("--root", type=Path, default=default_root(), help="intensity store (default: <data>/processed/imerg_intensity)")
        p.add_argument("--panels-dir", type=Path, default=default_panels_dir(),
                       help="held-out season panels (default: <data>/processed/alerts/heldout_seasons)")
    args = parser.parse_args(argv)
    if args.command == "gap" and args.end < args.start:
        parser.error(f"empty range: {args.start} is after {args.end}")
    try:
        return (_tables if args.command == "tables" else _gap)(args)
    except (IintIntegrityError, B.ImergFeaturesIntegrityError, FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
