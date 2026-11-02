"""Build, freeze and verify the sample tables of Phase 1 Task 5a (design D3, D4 and docs/phase3-design.md).

Tables written to the output directory (all one row per cell-day, `date` = calendar date):
  {split}_samples.parquet   positives (label 1) and negatives (label 0) for train / validation / test_2018
  universe_{split}.parquet  uniform draw over candidate cells x drawable days, with weight, in_buffer, is_positive flag
  window_2023_samples.parquet           window-positive cells + their 8 neighbours, and a himalaya control sample
  case_kerala_2018_samples.parquet / case_wayanad_2024_samples.parquet   full case-study grids (no sampling)
plus `samples_manifest.json` (row counts, SHA-256, seed, slope floor, parameters, input checksums, report); the files
are then read-only (frozen). A second build verifies the checksums and reuses the files; `force=True` rebuilds.
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
from ..grid import neighbours
from ..manifest import sha256_file
from ..splits import rules
from . import sampling
from .sampling import EventBuffer, RainCoverage, SamplingError

MANIFEST_NAME = "samples_manifest.json"
WINDOW_NAME = "window_2023_samples.parquet"
CASE_NAMES = {"kerala_2018": "case_kerala_2018_samples.parquet", "wayanad_2024": "case_wayanad_2024_samples.parquet"}
SAMPLE_COLUMNS = ["cell_id", "date", "split", "region", "label", "kind", "terrain_source", "terrain_cell_id",
                  "in_domain", "rain_ok"]
UNIVERSE_COLUMNS = ["cell_id", "date", "split", "region", "kind", "weight", "universe_size", "in_buffer",
                    "is_positive_cell_day"]
WINDOW_COLUMNS = ["cell_id", "date", "split", "region", "kind", "is_window_positive_cell"]
CASE_COLUMNS = ["cell_id", "date", "split", "region", "kind", "slope_ok", "in_buffer", "is_positive_cell_day"]
TERRAIN_SOURCES = ("own", "nearest_land", "none")


class SamplesIntegrityError(RuntimeError):
    """A frozen sample directory is damaged, stale or incompatible with the current inputs / configuration."""


def sample_name(split: str) -> str:
    return f"{split}_samples.parquet"


def universe_name(split: str) -> str:
    return f"universe_{split}.parquet"


def output_names(cfg: dict) -> list[str]:
    splits = cfg["samples"]["sample_splits"]
    return [*(sample_name(s) for s in splits), *(universe_name(s) for s in splits), WINDOW_NAME, *CASE_NAMES.values()]


@dataclass(frozen=True)
class SampleInputs:
    terrain: Path
    regions: Path
    positives: Path
    windows: Path
    events: Path

    def named(self) -> dict[str, Path]:
        return {"terrain": self.terrain, "regions": self.regions, "positives": self.positives,
                "windows": self.windows, "events": self.events}


def default_inputs() -> SampleInputs:
    root = data_root() / "processed"
    return SampleInputs(terrain=root / "terrain" / "cell_terrain.parquet",
                        regions=root / "features" / "cell_regions.parquet",
                        positives=root / "splits" / "positive_cell_days.parquet",
                        windows=root / "splits" / "window_positives.parquet",
                        events=root / "labels" / "events.parquet")


def default_out_dir() -> Path:
    return data_root() / "processed" / "features" / "samples"


def load_configs() -> dict:
    """The configuration bundle recorded in the manifest: samples.yaml, the split bounds and the rain ranges."""
    splits, ingest = load_config("splits"), load_config("ingest")
    return {"samples": load_config("samples"),
            "splits": {"day_splits": splits["day_splits"], "window_test": splits["window_test"]},
            "ingest": {"full_years": ingest["full_years"], "extra_ranges": ingest["extra_ranges"]}}


def _display_path(path: Path) -> str:
    try:
        return Path(path).resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return Path(path).name


def _set_mode(paths, mode: int) -> None:
    for path in paths:
        if Path(path).exists():
            os.chmod(path, mode)


def _managed_files(out_dir: Path, cfg: dict) -> list[Path]:
    return [out_dir / name for name in (*output_names(cfg), MANIFEST_NAME)]


# ---------------------------------------------------------------------------------------- table assembly

def _typed(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    out = frame[columns].copy()
    out["cell_id"] = out["cell_id"].astype("int64")
    out["date"] = out["date"].astype("datetime64[ns]")
    for column in out.columns:
        if out[column].dtype == object:
            out[column] = out[column].astype("str")
    return out.sort_values(["date", "cell_id"], kind="stable").reset_index(drop=True)


def _days_between(start: str, end: str) -> np.ndarray:
    return np.arange(np.datetime64(start, "D"), np.datetime64(end, "D") + np.timedelta64(1, "D"), dtype="datetime64[D]")


def _require_drawable(days: np.ndarray, coverage: RainCoverage, what: str) -> None:
    missing = days[~coverage.drawable(days)]
    if len(missing):
        raise SamplingError(f"{what}: {len(missing)} day(s) lack rain with look-back (first {missing[0]})")


def _positive_rows(positives: pd.DataFrame, split: str) -> pd.DataFrame:
    rows = positives[positives["split"] == split]
    return pd.DataFrame({"cell_id": rows["cell_id"], "date": rows["event_date"], "split": split,
                         "region": rows["region"], "label": np.int8(1), "kind": "positive",
                         "terrain_source": rows["terrain_source"], "terrain_cell_id": rows["terrain_cell_id"],
                         "in_domain": rows["in_domain"], "rain_ok": rows["rain_ok"]})


def _negative_rows(negatives: pd.DataFrame, split: str, region: str) -> pd.DataFrame:
    return pd.DataFrame({"cell_id": negatives["cell_id"], "date": negatives["date"], "split": split,
                         "region": region, "label": np.int8(0), "kind": "negative", "terrain_source": "own",
                         "terrain_cell_id": pd.array(negatives["cell_id"], dtype="Int64"), "in_domain": True,
                         "rain_ok": True})


def _count_by(frame: pd.DataFrame, mask: pd.Series, regions: list[str]) -> dict:
    sub = frame[mask]
    return {**{r: int((sub["region"] == r).sum()) for r in regions}, "total": len(sub)}


def _positive_report(positives: pd.DataFrame, regions: list[str], split_names: list[str]) -> dict:
    report = {}
    for split in split_names:
        rows = positives[positives["split"] == split]
        entry = {"cell_days": _count_by(rows, rows["region"].notna(), regions)}
        for source in TERRAIN_SOURCES:
            entry[f"terrain_{source}"] = _count_by(rows, rows["terrain_source"] == source, regions)
        entry["in_slope_domain"] = _count_by(rows, rows["in_domain"], regions)
        entry["below_slope_floor"] = _count_by(rows, ~rows["in_domain"] & (rows["terrain_source"] != "none"), regions)
        entry["no_rain_lookback"] = _count_by(rows, ~rows["rain_ok"], regions)
        report[split] = entry
    return report


def _month_probs(dates: pd.Series) -> np.ndarray:
    counts = np.bincount(dates.dt.month.to_numpy() - 1, minlength=12).astype(float)
    return counts / counts.sum() if counts.sum() else counts


def _candidate_report(in_scope: pd.DataFrame, candidates: pd.DataFrame, regions: list[str]) -> dict:
    def counts(frame):
        return {**{r: int((frame["region"] == r).sum()) for r in regions}, "total": len(frame)}

    before, after = counts(in_scope), counts(candidates)
    return {"before_floor": before, "after_floor": after,
            "removed_share": {k: (None if before[k] == 0 else 1 - after[k] / before[k]) for k in before}}


def _split_tables(split: str, split_index: int, positives: pd.DataFrame, candidates: pd.DataFrame, buffer: EventBuffer,
                  coverage: RainCoverage, cfg: dict) -> tuple[pd.DataFrame, pd.DataFrame, dict, dict]:
    """Sample table (positives + negatives) and universe table of one split, with their report entries."""
    scfg = cfg["samples"]
    start, end = cfg["splits"]["day_splits"][split]["start"], cfg["splits"]["day_splits"][split]["end"]
    scored = positives[positives["terrain_source"].isin(["own", "nearest_land"]) & (positives["split"] == split)]
    split_pairs = positives.loc[positives["split"] == split, ["cell_id", "event_date"]]
    in_universe = positives.merge(candidates[["cell_id", "region"]].rename(columns={"region": "cell_region"}),
                                  on="cell_id")
    in_universe = in_universe[(in_universe["split"] == split) & in_universe["rain_ok"]]
    window_days = coverage.drawable_days(start, end)
    sample_parts, universe_parts = [_positive_rows(positives, split)], []
    negative_report, universe_report = {}, {}
    for region_index, region in enumerate(scfg["sample_regions"]):
        cells = candidates.loc[candidates["region"] == region, "cell_id"].to_numpy()
        ref = scored[scored["region"] == region]
        negatives, stats = sampling.draw_negatives(
            sampling.stream(scfg["seed"], "negatives", split_index, region_index),
            int(scfg["negatives"]["ratio"]) * len(ref), cells, _month_probs(ref["event_date"]), start, end, coverage,
            buffer, max_draws_per_target=scfg["negatives"]["max_draws_per_negative"],
            min_batch=scfg["negatives"]["min_batch"])
        sample_parts.append(_negative_rows(negatives, split, region))
        negative_report[region] = {**stats, "positives_for_ratio": len(ref)}

        universe, size = sampling.draw_universe(
            sampling.stream(scfg["seed"], "universe", split_index, region_index), cells, window_days,
            scfg["universe"]["n_per_region"], buffer, split_pairs)
        universe_parts.append(universe.assign(split=split, region=region, kind="universe"))
        n_positive = int((in_universe["cell_region"] == region).sum())
        universe_report[region] = {
            "universe_size": int(size), "n_candidate_cells": len(cells), "n_days": len(window_days),
            "n_rows": len(universe), "weight": float(size / len(universe)),
            "rows_in_buffer": int(universe["in_buffer"].sum()),
            "rows_positive_cell_day": int(universe["is_positive_cell_day"].sum()),
            "positives_in_universe": n_positive, "base_rate_per_100k_cell_days": float(n_positive / size * 1e5)}
    return (_typed(pd.concat(sample_parts, ignore_index=True), SAMPLE_COLUMNS),
            _typed(pd.concat(universe_parts, ignore_index=True), UNIVERSE_COLUMNS), negative_report, universe_report)


def _case_table(name: str, spec: dict, terrain: pd.DataFrame, cell_regions: pd.DataFrame, candidates: pd.DataFrame,
                floor: float, buffer: EventBuffer, positives: pd.DataFrame, coverage: RainCoverage,
                split_cfg: dict) -> tuple[pd.DataFrame, dict]:
    """Every cell of the case study (candidate cells of a region, or all kept cells in a box) x every day."""
    if "region" in spec:
        cells = candidates.loc[candidates["region"] == spec["region"], "cell_id"].to_numpy(dtype=np.int64)
    else:
        box = terrain[terrain["lat"].between(spec["lat_min"], spec["lat_max"])
                      & terrain["lon"].between(spec["lon_min"], spec["lon_max"])]
        cells = np.sort(box["cell_id"].to_numpy(dtype=np.int64))
    days = _days_between(spec["start"], spec["end"])
    _require_drawable(days, coverage, f"case study {name}")
    grid_cells, grid_days = np.repeat(cells, len(days)), np.tile(days, len(cells))
    split = rules.assign_split(spec["start"], split_cfg)
    positive_keys = sampling.pair_keys(positives["cell_id"].to_numpy(), positives["event_date"].to_numpy())
    table = pd.DataFrame({
        "cell_id": grid_cells, "date": grid_days.astype("datetime64[ns]"), "split": split,
        "region": cell_regions.set_index("cell_id")["region"].reindex(grid_cells).to_numpy(), "kind": f"case_{name}",
        "slope_ok": terrain.set_index("cell_id")["slope_mean"].reindex(grid_cells).to_numpy() >= floor,
        "in_buffer": buffer.hits(grid_cells, grid_days),
        "is_positive_cell_day": np.isin(sampling.pair_keys(grid_cells, grid_days), positive_keys)})
    report = {"split": split, "n_cells": len(cells), "n_days": len(days), "n_rows": len(table),
              "cell_days_slope_ok": int(table["slope_ok"].sum()),
              "positive_cell_days": int(table["is_positive_cell_day"].sum()), "start": spec["start"], "end": spec["end"]}
    return _typed(table, CASE_COLUMNS), report


def build_tables(inputs: SampleInputs, cfg: dict) -> tuple[dict[str, pd.DataFrame], dict]:
    """Compute every table and the report from the inputs; pure and deterministic (no files written)."""
    scfg = cfg["samples"]
    terrain = pd.read_parquet(inputs.terrain, columns=["cell_id", "lat", "lon", "slope_mean"])
    cell_regions = pd.read_parquet(inputs.regions)
    windows = pd.read_parquet(inputs.windows)
    events = pd.read_parquet(inputs.events, columns=["cell_id", "event_date"])
    regions = list(scfg["sample_regions"])
    coverage = RainCoverage.from_config(cfg["ingest"], scfg["lookback_days"])

    positives = sampling.attach_terrain(pd.read_parquet(inputs.positives), terrain,
                                        scfg["terrain"]["nearest_land_max_cells"])
    floor = sampling.slope_floor(positives, scfg["slope_floor"]["percentile"], scfg["slope_floor"]["reference_split"])
    positives["in_domain"] = (positives["slope_mean"] >= floor["floor"]).to_numpy()
    positives["rain_ok"] = coverage.drawable(positives["event_date"].to_numpy())
    in_scope = sampling.candidate_cells(terrain, cell_regions, -np.inf)
    candidates = sampling.candidate_cells(terrain, cell_regions, floor["floor"])
    # the buffer is every label-store record plus the positive cell-days themselves
    buffer = EventBuffer.from_events(
        pd.concat([events, positives[["cell_id", "event_date"]].astype({"cell_id": "Int64"})], ignore_index=True),
        scfg["buffer"]["cells"], scfg["buffer"]["days"])

    report: dict = {
        "slope_floor": {**floor, "candidate_cells": _candidate_report(in_scope, candidates, regions)},
        "rain_coverage": {"ranges": [[a.strftime("%Y-%m-%d"), b.strftime("%Y-%m-%d")] for a, b in coverage.ranges],
                          "lookback_days": coverage.lookback_days},
        "buffer": {"records": buffer.n_records, "cells": buffer.cells, "days": buffer.days},
        "positives": _positive_report(positives, regions, list(cfg["splits"]["day_splits"])),
        "negatives": {}, "universe": {}, "case_studies": {},
    }
    total = sum(v["cell_days"]["total"] for v in report["positives"].values())
    report["slope_floor"]["positives_below_floor_share_all_splits"] = (
        sum(v["below_slope_floor"]["total"] for v in report["positives"].values()) / total if total else None)

    tables: dict[str, pd.DataFrame] = {}
    for split_index, split in enumerate(scfg["sample_splits"]):
        (tables[sample_name(split)], tables[universe_name(split)],
         report["negatives"][split], report["universe"][split]) = _split_tables(
            split, split_index, positives, candidates, buffer, coverage, cfg)
    tables[WINDOW_NAME], report["window_2023"] = _window_table(
        windows, terrain, cell_regions, candidates, coverage, cfg["splits"]["window_test"], scfg, regions)
    for name, filename in CASE_NAMES.items():
        tables[filename], report["case_studies"][name] = _case_table(
            name, scfg["case_studies"][name], terrain, cell_regions, candidates, floor["floor"], buffer, positives,
            coverage, {"day_splits": cfg["splits"]["day_splits"]})
    return tables, report


def _window_table(windows: pd.DataFrame, terrain: pd.DataFrame, cell_regions: pd.DataFrame,
                  candidates: pd.DataFrame, coverage: RainCoverage, window_spec: dict, scfg: dict,
                  regions: list[str]) -> tuple[pd.DataFrame, dict]:
    """Window-positive cells + 8 neighbours present in the terrain table, plus a control sample, x every window day."""
    days = _days_between(window_spec["window_start"], window_spec["window_end"])
    _require_drawable(days, coverage, "window 2023")
    kept = set(terrain["cell_id"].tolist())
    positive_cells = sorted(set(windows["cell_id"].tolist()))
    neighbourhood = np.array(sorted({n for c in positive_cells for n in (c, *neighbours(c))} & kept), dtype=np.int64)
    control_region, n_control = scfg["window_2023"]["control_region"], int(scfg["window_2023"]["control_n"])
    pool = candidates.loc[(candidates["region"] == control_region) & ~candidates["cell_id"].isin(neighbourhood),
                          "cell_id"].to_numpy(dtype=np.int64)
    if len(pool) < n_control:
        raise SamplingError(f"window control: only {len(pool)} candidate cells for {n_control} draws")
    rng = sampling.stream(scfg["seed"], "window_control", 0, regions.index(control_region))
    control = np.sort(pool[rng.choice(len(pool), size=n_control, replace=False)])
    region_of = cell_regions.set_index("cell_id")["region"]
    parts = []
    for cells, kind in ((neighbourhood, "window_cell"), (control, "window_control")):
        grid_cells = np.repeat(cells, len(days))
        parts.append(pd.DataFrame({
            "cell_id": grid_cells, "date": np.tile(days, len(cells)).astype("datetime64[ns]"),
            "split": window_spec["name"], "region": region_of.reindex(grid_cells).to_numpy(), "kind": kind,
            "is_window_positive_cell": np.isin(grid_cells, positive_cells)}))
    table = _typed(pd.concat(parts, ignore_index=True), WINDOW_COLUMNS)
    report = {"n_window_positive_cells": len(positive_cells),
              "window_positive_cells_without_terrain": len(set(positive_cells) - kept),
              "n_neighbourhood_cells": len(neighbourhood), "n_control_cells": n_control, "n_days": len(days),
              "n_rows": len(table), "start": window_spec["window_start"], "end": window_spec["window_end"]}
    return table, report


# ---------------------------------------------------------------------------------------- freeze

def _jsonable(value):
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    return value


def build_samples(inputs: SampleInputs, out_dir, force: bool = False, cfg: dict | None = None) -> tuple[dict, bool]:
    """Write the frozen sample tables and manifest; returns (manifest, reused).

    With a manifest already present and `force` False nothing is rewritten: the files, input checksums and
    configuration are verified and the stored manifest is returned with reused=True; any problem raises
    SamplesIntegrityError. All computation happens before the first write.
    """
    out_dir = Path(out_dir)
    cfg = cfg if cfg is not None else load_configs()
    manifest_path = out_dir / MANIFEST_NAME
    if manifest_path.exists() and not force:
        result = verify_samples(out_dir, inputs, cfg)
        if not result["ok"]:
            raise SamplesIntegrityError(f"{out_dir} is frozen but not intact (pass force=True to rebuild): "
                                        + "; ".join(result["problems"]))
        return json.loads(manifest_path.read_text(encoding="utf-8")), True

    started = time.perf_counter()
    tables, report = build_tables(inputs, cfg)
    out_dir.mkdir(parents=True, exist_ok=True)
    _set_mode(_managed_files(out_dir, cfg), stat.S_IWRITE | stat.S_IREAD)
    for name, table in tables.items():
        table.to_parquet(out_dir / name, index=False)
    manifest = {
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "frozen": True,
        "seed": cfg["samples"]["seed"],
        "slope_floor": report["slope_floor"]["floor"],
        "config": cfg,
        "inputs": {name: {"path": _display_path(path), "sha256": sha256_file(path)}
                   for name, path in inputs.named().items()},
        "files": {name: {"sha256": sha256_file(out_dir / name), "size_bytes": (out_dir / name).stat().st_size,
                         "n_rows": len(table)} for name, table in tables.items()},
        "report": report,
        "elapsed_seconds": round(time.perf_counter() - started, 1),
    }
    manifest_path.write_text(json.dumps(_jsonable(manifest), indent=2, allow_nan=False) + "\n", encoding="utf-8")
    _set_mode(_managed_files(out_dir, cfg), stat.S_IREAD)
    return json.loads(manifest_path.read_text(encoding="utf-8")), False


# ---------------------------------------------------------------------------------------- verify

def _content_problems(out_dir: Path, cfg: dict) -> list[str]:
    """Integrity of the frozen tables themselves (no inputs needed)."""
    problems: list[str] = []
    scfg, bounds = cfg["samples"], cfg["splits"]["day_splits"]
    frames = {}
    for split in scfg["sample_splits"]:
        try:
            frames[split] = pd.read_parquet(out_dir / sample_name(split))
        except (OSError, ValueError) as exc:
            problems.append(f"cannot read {sample_name(split)}: {exc}")
    for split, frame in frames.items():
        if frame.duplicated(["cell_id", "date"]).any():
            problems.append(f"{sample_name(split)}: a (cell, date) appears more than once")
        lo, hi = pd.Timestamp(bounds[split]["start"]), pd.Timestamp(bounds[split]["end"])
        if not frame["date"].between(lo, hi).all():
            problems.append(f"{sample_name(split)}: dates outside {lo.date()}..{hi.date()}")
        if (frame["split"] != split).any():
            problems.append(f"{sample_name(split)}: rows labelled with another split")
        if ((frame["kind"] == "positive") != (frame["label"] == 1)).any():
            problems.append(f"{sample_name(split)}: kind and label disagree")
        for region in scfg["sample_regions"]:
            in_region = frame[frame["region"] == region]
            n_pos = int(((in_region["kind"] == "positive") & in_region["terrain_source"].isin(["own", "nearest_land"])).sum())
            n_neg = int((in_region["kind"] == "negative").sum())
            if n_neg != scfg["negatives"]["ratio"] * n_pos:
                problems.append(f"{sample_name(split)} {region}: {n_neg} negatives for {n_pos} positives "
                                f"(expected ratio {scfg['negatives']['ratio']})")
    names = list(frames)
    for i, left in enumerate(names):
        for right in names[i + 1:]:
            shared = frames[left].merge(frames[right], on=["cell_id", "date"])
            if len(shared):
                problems.append(f"{len(shared)} (cell, date) shared by {left} and {right}")
    return problems


def _input_problems(out_dir: Path, cfg: dict, inputs: SampleInputs, manifest: dict) -> list[str]:
    problems: list[str] = []
    for name, path in inputs.named().items():
        if not Path(path).is_file():
            problems.append(f"input missing: {name} ({Path(path).name})")
        elif sha256_file(path) != manifest["inputs"][name]["sha256"]:
            problems.append(f"input changed after freezing: {name} ({Path(path).name})")
    if problems:
        return problems
    scfg = cfg["samples"]
    events = pd.read_parquet(inputs.events, columns=["cell_id", "event_date"])
    positives = pd.read_parquet(inputs.positives)
    pairs = pd.concat([events, positives[["cell_id", "event_date"]].astype({"cell_id": "Int64"})], ignore_index=True)
    buffer = EventBuffer.from_events(pairs, scfg["buffer"]["cells"], scfg["buffer"]["days"])
    for split in scfg["sample_splits"]:
        frame = pd.read_parquet(out_dir / sample_name(split))
        negatives = frame[frame["kind"] == "negative"]
        if buffer.hits(negatives["cell_id"].to_numpy(), negatives["date"].to_numpy()).any():
            problems.append(f"{sample_name(split)}: a negative lies inside the event buffer")
        expected = positives[positives["split"] == split]
        stored = frame[frame["kind"] == "positive"]
        merged = expected.merge(stored, left_on=["cell_id", "event_date"], right_on=["cell_id", "date"], how="outer",
                                indicator=True)
        if len(stored) != len(expected) or (merged["_merge"] != "both").any():
            problems.append(f"{sample_name(split)}: positives differ from the frozen positive cell-days")
    return problems


def verify_samples(out_dir, inputs: SampleInputs | None = None, cfg: dict | None = None) -> dict:
    """Check the frozen files against the manifest; returns {"ok": bool, "problems": [str]}.

    Always checks file checksums and the table invariants (no (cell, date) shared between splits, dates in range,
    negatives = ratio x positives per split and region). With `inputs` it also checks the inputs are unchanged, that
    no negative is inside the event buffer and that every positive cell-day is present exactly once. With `cfg` it
    checks the configuration equals the one frozen. Raises FileNotFoundError only when the manifest is missing.
    """
    out_dir = Path(out_dir)
    manifest_path = out_dir / MANIFEST_NAME
    if not manifest_path.is_file():
        raise FileNotFoundError(f"{MANIFEST_NAME} not found in {out_dir}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        recorded, frozen_cfg = manifest["files"], manifest["config"]
        manifest["inputs"]
    except (ValueError, KeyError, TypeError) as exc:
        return {"ok": False, "problems": [f"manifest unreadable or incomplete: {exc!r}"]}
    problems: list[str] = []
    if manifest.get("frozen") is not True:
        problems.append("manifest says the samples are not frozen")
    if cfg is not None and _jsonable(cfg) != frozen_cfg:
        problems.append("configuration changed after freezing")
    for name, entry in recorded.items():
        path = out_dir / name
        if not path.is_file():
            problems.append(f"missing: {name}")
        elif sha256_file(path) != entry["sha256"]:
            problems.append(f"checksum mismatch: {name}")
    if problems:
        return {"ok": False, "problems": problems}
    problems.extend(_content_problems(out_dir, frozen_cfg))
    if inputs is not None:
        problems.extend(_input_problems(out_dir, frozen_cfg, inputs, manifest))
    return {"ok": not problems, "problems": problems}
