"""Loaders, feature-group column filters and row selection for the hazard model (Phase 3b).

`feature_columns.json` (column -> group) is the single source of truth for which columns may be model inputs: a
feature group is a column filter, so a new group (e.g. `integ`) is added by listing it in `configs/hazard.yaml`.
Columns of group `meta` (cell id, coordinates, region, month, sources, flags, weights) are never inputs.

Protocol v2 (docs/phase3-design.md): model work happens on the DEVELOPMENT rows, i.e. the train and validation splits
pooled (2007-2017); test_2018, the 2023 window and the case studies are scored only, never fitted or selected on.
Extra feature groups (`integ`, `corr`) live in separate parquet files with a manifest; `load_table` joins them by
position after verifying that the (cell_id, date) keys and row counts are identical and the checksums match.

Population semantics (docs/phase1-design.md D3, `features/sampling.py`): universe rows are uniform draws over the
candidate cells x all days of the split. `weight` = universe_size / rows per region, so the weighted rows
approximate the true operating population. Rows with `in_buffer` are ambiguous (near an event record) and rows with
`is_positive_cell_day` are positives; neither counts as a negative. `universe_negatives` renormalises the weights so
they still sum to `universe_size` per split-region after that removal.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import data_root
from ..manifest import sha256_file

TRAIN = "train"
VALIDATION = "validation"
TEST = "test_2018"
MODEL_SPLITS = (TRAIN, VALIDATION, TEST)
DEVELOPMENT_SPLITS = (TRAIN, VALIDATION)
SAMPLE_NAMES = {TRAIN: "train_samples", VALIDATION: "validation_samples", TEST: "test_2018_samples"}
UNIVERSE_NAMES = {TRAIN: "universe_train", VALIDATION: "universe_validation", TEST: "universe_test_2018"}
WINDOW_NAME = "window_2023_samples"
CASE_NAMES = ("case_kerala_2018", "case_wayanad_2024")
META = "meta"
NEG_MIXES = ("matched_only", "matched_plus_universe")
TRAINING_KINDS = frozenset({"positive", "negative", "universe"})
NEVER_INPUTS = frozenset({"cell_id", "terrain_cell_id", "date", "split", "region", "label", "kind", "terrain_source",
                          "in_domain", "rain_ok", "lat", "lon", "month", "rain_source", "weight", "universe_size",
                          "in_buffer", "is_positive_cell_day", "is_window_positive_cell", "slope_ok"})


class LeakageError(ValueError):
    """Rows outside the in-domain development period were offered for fitting or selection."""


class ExtraGroupError(ValueError):
    """An extra feature file does not match its base feature table (keys, row count or checksum)."""


def features_dir() -> Path:
    return data_root() / "processed" / "features"


def load_features(name: str, directory: Path | None = None) -> pd.DataFrame:
    """The frozen feature table `<name>_features.parquet` (e.g. `train_samples`, `universe_validation`)."""
    path = Path(directory or features_dir()) / f"{name}_features.parquet"
    if not path.is_file():
        raise FileNotFoundError(f"{path} not found; build the feature store first (aetherguard.features.features_build)")
    return pd.read_parquet(path)


def load_column_map(directory: Path | None = None, extras: dict | None = None, use=(),
                    meta_columns=()) -> dict[str, str]:
    """column -> group of the feature store, plus the columns of the extra groups named in `use`. Columns listed in
    `meta_columns` are reclassified as `meta` (never model inputs) whatever their group; ones whose group is not
    loaded are simply absent."""
    root = Path(directory or features_dir())
    path = root / "feature_columns.json"
    if not path.is_file():
        raise FileNotFoundError(f"{path} not found; build the feature store first")
    mapping = json.loads(path.read_text(encoding="utf-8"))
    for name in use:
        spec = _extra_spec(extras, name)
        columns_path = root / spec["subdir"] / spec["columns_file"]
        if not columns_path.is_file():
            raise FileNotFoundError(f"{columns_path} not found; build the `{name}` feature group first")
        extra = json.loads(columns_path.read_text(encoding="utf-8"))
        clash = sorted(set(extra) & set(mapping))
        if clash:
            raise ExtraGroupError(f"group `{name}` redefines existing columns {clash}")
        mapping.update(extra)
    return {c: (META if c in set(meta_columns) else g) for c, g in mapping.items()}


def _extra_spec(extras: dict | None, name: str) -> dict:
    if not extras or name not in extras:
        raise ValueError(f"extra feature group {name!r} is not configured (configured: {sorted(extras or {})})")
    return extras[name]


def _verified_extra(root: Path, table: str, spec: dict, base: pd.DataFrame) -> pd.DataFrame:
    directory = root / spec["subdir"]
    path = directory / f"{table}_{spec['suffix']}.parquet"
    manifest_path = directory / spec["manifest_file"]
    if not path.is_file() or not manifest_path.is_file():
        raise FileNotFoundError(f"{path} or {manifest_path} not found; build the extra feature group first")
    entry = json.loads(manifest_path.read_text(encoding="utf-8"))["files"].get(path.name)
    if entry is None:
        raise ExtraGroupError(f"{path.name} is not listed in {manifest_path.name}")
    if sha256_file(path) != entry["sha256"]:
        raise ExtraGroupError(f"{path.name} does not match the checksum in {manifest_path.name}")
    extra = pd.read_parquet(path)
    if len(extra) != entry["n_rows"] or len(extra) != len(base):
        raise ExtraGroupError(f"{path.name} has {len(extra)} rows; expected {len(base)} (manifest {entry['n_rows']})")
    same_keys = (extra["cell_id"].to_numpy() == base["cell_id"].to_numpy()).all() and (
        extra["date"].to_numpy() == base["date"].to_numpy()).all()
    if not same_keys:
        raise ExtraGroupError(f"{path.name} keys (cell_id, date) differ from the base table in value or order")
    return extra.drop(columns=["cell_id", "date"])


def load_table(name: str, directory: Path | None = None, extras: dict | None = None, use=()) -> pd.DataFrame:
    """A feature table with the extra groups named in `use` joined on (cell_id, date), keys verified identical."""
    root = Path(directory or features_dir())
    base = load_features(name, root)
    for group in use:
        extra = _verified_extra(root, name, _extra_spec(extras, group), base)
        clash = sorted(set(extra.columns) & set(base.columns))
        if clash:
            raise ExtraGroupError(f"group `{group}` columns {clash} already exist in {name}")
        base = pd.concat([base.reset_index(drop=True), extra.reset_index(drop=True)], axis=1)
    return base


def model_columns(groups, column_map: dict[str, str] | None = None, exclude_prefixes=()) -> list[str]:
    """Input columns of the given feature groups, in feature-store order, minus any `exclude_prefixes`."""
    mapping = load_column_map() if column_map is None else column_map
    groups = list(groups)
    if META in groups:
        raise ValueError("meta columns are never model inputs")
    known = set(mapping.values()) - {META}
    unknown = [g for g in groups if g not in known]
    if unknown:
        raise ValueError(f"unknown feature groups {unknown}; the feature store defines {sorted(known)}")
    columns = [c for c, g in mapping.items() if g in groups and not c.startswith(tuple(exclude_prefixes))]
    leaked = sorted(set(columns) & NEVER_INPUTS)
    if leaked:
        raise ValueError(f"columns {leaked} may not be model inputs but are assigned to feature groups")
    if not columns:
        raise ValueError("no input columns selected")
    return columns


# ------------------------------------------------------------------------------------------- selection

def in_domain_positives(samples: pd.DataFrame) -> pd.DataFrame:
    return samples[(samples["kind"] == "positive") & samples["in_domain"].astype(bool)]


def universe_negative_mask(universe: pd.DataFrame, include_buffer: bool = False) -> np.ndarray:
    keep = ~universe["is_positive_cell_day"].to_numpy(dtype=bool)
    if not include_buffer:
        keep &= ~universe["in_buffer"].to_numpy(dtype=bool)
    return keep


def renormalised_weights(universe: pd.DataFrame, keep: np.ndarray) -> np.ndarray:
    """Weights of the kept rows so that they sum to `universe_size` within each split-region."""
    kept = universe[keep]
    sizes = kept.groupby(["split", "region"])["universe_size"].nunique()
    if (sizes > 1).any():
        raise ValueError("universe_size must be unique within a split-region")
    counts = kept.groupby(["split", "region"])["weight"].transform("size").to_numpy(dtype=np.float64)
    return kept["universe_size"].to_numpy(dtype=np.float64) / counts


def universe_negatives(universe: pd.DataFrame, include_buffer: bool = False) -> pd.DataFrame:
    """Non-buffer, non-positive universe rows with `weight` renormalised to sum to universe_size per split-region.

    The original weight is kept as `weight_drawn`; `include_buffer=True` is the sensitivity variant that counts
    buffer rows as negatives.
    """
    keep = universe_negative_mask(universe, include_buffer)
    out = universe[keep].copy()
    out["weight_drawn"] = out["weight"]
    out["weight"] = renormalised_weights(universe, keep)
    out["label"] = np.int8(0)
    return out


@dataclass(frozen=True)
class SplitData:
    """One split's evaluation populations."""
    split: str
    positives: pd.DataFrame                 # in-domain positive cell-days (events)
    n_out_of_domain: dict[str, int]         # positives below the slope floor, per region (counted as misses)
    matched: pd.DataFrame                   # matched negatives of the sample file (never used for the headline FA)
    universe: pd.DataFrame                  # all universe rows (buffer and positive cell-days included)
    universe_sizes: dict[str, int]

    @property
    def negatives(self) -> pd.DataFrame:
        return universe_negatives(self.universe)


def load_split(split: str, directory: Path | None = None) -> SplitData:
    if split not in MODEL_SPLITS:
        raise ValueError(f"split must be one of {MODEL_SPLITS}")
    samples = load_features(SAMPLE_NAMES[split], directory)
    universe = load_features(UNIVERSE_NAMES[split], directory)
    return split_data(split, samples, universe)


def split_data(split: str, samples: pd.DataFrame, universe: pd.DataFrame) -> SplitData:
    positives_all = samples[samples["kind"] == "positive"]
    out_of_domain = positives_all[~positives_all["in_domain"].astype(bool)]
    sizes = universe.groupby("region")["universe_size"].first()
    return SplitData(split=split, positives=in_domain_positives(samples),
                     n_out_of_domain={r: int((out_of_domain["region"] == r).sum()) for r in sorted(sizes.index)},
                     matched=samples[samples["kind"] == "negative"], universe=universe,
                     universe_sizes={r: int(v) for r, v in sizes.items()})


def evaluation_frame(data: SplitData, regions=None, include_buffer: bool = False) -> pd.DataFrame:
    """Positives (label 1, eval_weight 1) followed by weighted universe negatives (label 0, eval_weight = weight)."""
    negatives = universe_negatives(data.universe, include_buffer)
    positives = data.positives.assign(label=np.int8(1))
    columns = [c for c in positives.columns if c in negatives.columns]
    frame = pd.concat([positives[columns].assign(eval_weight=1.0),
                       negatives[columns].assign(eval_weight=negatives["weight"].to_numpy(dtype=np.float64))],
                      ignore_index=True)
    if regions is not None:
        frame = frame[frame["region"].isin(list(regions))].reset_index(drop=True)
    return frame


def base_rates(data: SplitData) -> dict:
    """Positives per operating cell-day (all days of the split x candidate cells), overall and per region."""
    per_region = {}
    for region, size in data.universe_sizes.items():
        n_pos = int((data.positives["region"] == region).sum())
        per_region[region] = {"positives": n_pos, "universe_cell_days": size, "base_rate": n_pos / size,
                              "per_100k_cell_days": 1e5 * n_pos / size}
    n_pos, size = len(data.positives), sum(data.universe_sizes.values())
    return {"overall": {"positives": n_pos, "universe_cell_days": size, "base_rate": n_pos / size,
                        "per_100k_cell_days": 1e5 * n_pos / size}, "regions": per_region}


# --------------------------------------------------------------------------------------------- training

def assert_development_rows(frame: pd.DataFrame) -> None:
    """Only development rows (train + validation splits: positive, matched negative, universe) may enter fitting or
    selection; test_2018, window and case rows raise."""
    for column in ("split", "kind"):
        if column not in frame.columns:
            raise LeakageError(f"training rows must carry a `{column}` column")
    bad_split = frame.loc[~frame["split"].isin(DEVELOPMENT_SPLITS), "split"].unique()
    if len(bad_split):
        raise LeakageError(f"rows from splits {sorted(map(str, bad_split))} offered for fitting; only "
                           f"{list(DEVELOPMENT_SPLITS)} are allowed")
    bad_kind = frame.loc[~frame["kind"].isin(TRAINING_KINDS), "kind"].unique()
    if len(bad_kind):
        raise LeakageError(f"rows of kind {sorted(map(str, bad_kind))} offered for fitting (case/window rows are never fitted)")


def assert_training_rows(frame: pd.DataFrame) -> None:
    """Rows that may be fitted on: development rows that are also in the slope domain."""
    assert_development_rows(frame)
    if "in_domain" in frame.columns and not frame["in_domain"].astype(bool).all():
        raise LeakageError("out-of-domain rows (below the slope floor) offered for fitting")


def training_frame(samples: pd.DataFrame, universe: pd.DataFrame, neg_mix: str, n_universe: int, seed: int,
                   regions=None) -> pd.DataFrame:
    """Training rows with `label` and `sample_weight`.

    Always: train in-domain positives (weight 1) and the matched negatives (weight 1). For `matched_plus_universe`
    additionally `n_universe` randomly drawn non-buffer, non-positive universe_train rows, each weighted so that the
    matched and the universe negatives contribute EQUAL total weight (n_matched / n_drawn per row).
    """
    if neg_mix not in NEG_MIXES:
        raise ValueError(f"neg_mix must be one of {NEG_MIXES}, got {neg_mix!r}")
    if regions is not None:
        regions = list(regions)
        samples = samples[samples["region"].isin(regions)]
        universe = universe[universe["region"].isin(regions)]
    kept = pd.concat([in_domain_positives(samples), samples[samples["kind"] == "negative"]], ignore_index=True)
    kept = kept.assign(sample_weight=1.0)
    parts = [kept]
    if neg_mix == "matched_plus_universe":
        pool = universe[universe_negative_mask(universe)]
        n_draw = min(n_universe, len(pool))
        if n_draw == 0:
            raise ValueError("no universe negatives available for matched_plus_universe")
        drawn = pool.iloc[np.sort(np.random.default_rng(seed).choice(len(pool), n_draw, replace=False))]
        n_matched = int((kept["kind"] == "negative").sum())
        drawn = drawn.assign(label=np.int8(0), in_domain=True, sample_weight=n_matched / n_draw)
        columns = [c for c in kept.columns if c in drawn.columns]
        parts.append(drawn[columns])
    frame = pd.concat(parts, ignore_index=True)
    assert_training_rows(frame)
    return frame


# ------------------------------------------------------------------------------------------- development

def year_weighted_negatives(universe: pd.DataFrame, include_buffer: bool = False) -> pd.DataFrame:
    """Universe negatives with weights fixed per calendar year (needed for year-blocked cross-validation).

    Within a split-region the universe covers `universe_size` cell-days over the split's valid days. A year's share of
    them is its number of valid days (distinct universe dates in that year) over the split's, so year `y` carries
    `universe_size * days(y) / days(split)` cell-days; its non-buffer, non-positive rows share that total equally.
    Weights then sum to `universe_size` per split-region AND to the year's share per year-region, so any set of years
    is a correctly weighted sample of its own period. `weight_drawn` keeps the original draw weight.
    """
    keep = universe_negative_mask(universe, include_buffer)
    year = universe["date"].dt.year.to_numpy()
    days = (universe.assign(year=year)[["split", "year", "date"]].drop_duplicates()
            .groupby(["split", "year"]).size().rename("days"))
    split_days = days.groupby(level="split").transform("sum")
    sizes = universe.groupby(["split", "region"])["universe_size"].nunique()
    if (sizes > 1).any():
        raise ValueError("universe_size must be unique within a split-region")
    kept = universe[keep].assign(year=year[keep])
    cells = kept.groupby(["split", "region", "year"]).size().rename("n_rows").reset_index()
    cells = cells.join(universe.groupby(["split", "region"])["universe_size"].first(), on=["split", "region"])
    cells = cells.join(days, on=["split", "year"]).join(split_days.rename("split_days"), on=["split", "year"])
    cells["year_weight"] = cells["universe_size"] * cells["days"] / cells["split_days"] / cells["n_rows"]
    full = universe[["split", "region"]].drop_duplicates().merge(days.reset_index()[["split", "year"]], on="split")
    missing = full.merge(cells[["split", "region", "year"]], how="left", indicator=True)
    if (missing["_merge"] == "left_only").any():
        raise ValueError("a split-region-year has no negative universe rows left; its weight cannot be assigned")
    out = universe[keep].copy()
    out["year"] = year[keep]
    out["weight_drawn"] = out["weight"]
    out["weight"] = out.merge(cells[["split", "region", "year", "year_weight"]], on=["split", "region", "year"],
                              how="left")["year_weight"].to_numpy()
    out["label"] = np.int8(0)
    return out


@dataclass(frozen=True)
class Development:
    """The pooled train + validation rows (2007-2017) that every v2 fitting and selection step is restricted to."""
    samples: pd.DataFrame          # positives (in and out of domain) and matched negatives, with `year`
    universe: pd.DataFrame         # all universe rows, with `year`
    column_map: dict[str, str]
    universe_sizes: dict[str, int]  # per region, summed over the development splits

    @property
    def positives(self) -> pd.DataFrame:
        return in_domain_positives(self.samples)

    @property
    def negatives(self) -> pd.DataFrame:
        return year_weighted_negatives(self.universe)

    @property
    def n_out_of_domain(self) -> dict[str, int]:
        positives = self.samples[self.samples["kind"] == "positive"]
        outside = positives[~positives["in_domain"].astype(bool)]
        return {r: int((outside["region"] == r).sum()) for r in sorted(self.universe_sizes)}


def build_development(samples: pd.DataFrame, universe: pd.DataFrame, column_map: dict[str, str]) -> Development:
    for frame in (samples, universe):
        assert_development_rows(frame)
    samples = samples.assign(year=samples["date"].dt.year.astype(np.int16))
    universe = universe.assign(year=universe["date"].dt.year.astype(np.int16))
    per_split = universe.groupby(["split", "region"])["universe_size"].first()
    sizes = per_split.groupby(level="region").sum()
    return Development(samples, universe, column_map, {r: int(v) for r, v in sizes.items()})


def load_development(directory: Path | None = None, extras: dict | None = None, use=(),
                     meta_columns=()) -> Development:
    """Development rows from the frozen feature store; `use` names the extra feature groups to join and
    `meta_columns` the loaded columns that must never be model inputs."""
    root = Path(directory or features_dir())
    samples = pd.concat([load_table(SAMPLE_NAMES[s], root, extras, use) for s in DEVELOPMENT_SPLITS],
                        ignore_index=True)
    universe = pd.concat([load_table(UNIVERSE_NAMES[s], root, extras, use) for s in DEVELOPMENT_SPLITS],
                         ignore_index=True)
    return build_development(samples, universe, load_column_map(root, extras, use, meta_columns))
