"""Phase 2b-i data for the learned engine: the fault dataset restricted to the days that have gridded references
(ENGINE_PERIOD), the reference coverage, and the causal feature matrix.

    python -m aetherguard.integrity.engine_data [--rebuild] [--raw-dir DIR]

Writes to data/processed/integrity/: fault_dataset_2007.parquet (+ _report.json), grid_refs_2007.npz (cache),
features_2007.parquet (+ _report.json). The station split file is the FROZEN one written by baseline_report and
is never regenerated here. Fault injection is unchanged except for the explicit relaxation ladder below.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import evaluate, features, grids, inject, neighbours
from .baseline_report import DATASET_SEED, NEIGHBOUR_SETTINGS, _window, real_flag_calibration
from .common import dumps_strict, integrity_dir
from .splits import SPLIT_SEED, default_path, make_station_splits
from .stations import StationSet, load_station_set

ENGINE_PERIOD = ("2007-01-01", "2024-12-31")   # days with gridded references (IMD / CHIRPS / POWER from 2007)
ENGINE_DATASET_NAME = "fault_dataset_2007.parquet"
ENGINE_REPORT_NAME = "fault_dataset_2007_report.json"
REFS_CACHE_NAME = "grid_refs_2007.npz"
FEATURES_NAME = "features_2007.parquet"
FEATURES_REPORT_NAME = "features_2007_report.json"
MIN_TEST_EPISODES = 15      # per fault type, else relax
MIN_TRAIN_EPISODES = 40
BASE_MIN_VALID_DAYS = inject.MIN_VALID_DAYS_PER_YEAR   # 200
RELAXED_MIN_VALID_DAYS = 150                           # relaxation (i), this dataset only
RELAXED_DENSITY = 0.15                                 # relaxation (ii)
BASE_DENSITY = 0.08
ENGINE_MIN_VALID_DAYS = RELAXED_MIN_VALID_DAYS   # the chosen (final) rung, kept by ruling; also used by the extra seeds
ENGINE_DENSITY = RELAXED_DENSITY
LADDER = (("base", BASE_MIN_VALID_DAYS, BASE_DENSITY),
          ("min_valid_days_150", RELAXED_MIN_VALID_DAYS, BASE_DENSITY),
          ("min_valid_days_150_density_0.15", RELAXED_MIN_VALID_DAYS, RELAXED_DENSITY))


def episode_counts(report: dict) -> dict:
    return {split: {name: cell["episodes"] for name, cell in row["by_type"].items()}
            for split, row in report["splits"].items()}


def episode_shortfalls(report: dict) -> list[dict]:
    """Fault types below the minimum episode count: TEST < 15 or TRAIN < 40."""
    out = []
    for split, minimum in (("test", MIN_TEST_EPISODES), ("train", MIN_TRAIN_EPISODES)):
        for name, count in episode_counts(report)[split].items():
            if count < minimum:
                out.append({"split": split, "fault_type": name, "episodes": count, "minimum": minimum})
    return out


def build_engine_dataset(sset: StationSet, splits: dict, calibration: dict | None, seed: int = DATASET_SEED):
    """(table, info): the dataset on ENGINE_PERIOD from the first rung of the relaxation ladder without a
    shortfall (the last rung when every rung falls short). `info["attempts"]` records every rung's counts."""
    window = _window(sset, *ENGINE_PERIOD)
    attempts = []
    for label, min_valid, density in LADDER:
        table = inject.build_fault_dataset(window, splits, seed=seed, density=density,
                                           calibration=calibration, min_valid_days=min_valid)
        report = inject.dataset_report(table)
        short = episode_shortfalls(report)
        attempts.append({"label": label, "min_valid_days": min_valid, "density": density,
                         "clean_real_days": int(table["clean_real"].sum()),
                         "episodes": episode_counts(report), "shortfalls": short})
        if not short:
            break
    chosen = attempts[-1]
    return table, {"chosen": chosen["label"], "min_valid_days": chosen["min_valid_days"],
                   "density": chosen["density"], "unresolved_shortfalls": chosen["shortfalls"],
                   "attempts": attempts}


def reference_coverage(table: pd.DataFrame, refs: grids.GridRefs, wide_table: pd.DataFrame) -> dict:
    """Per split: clean real days (outside episode windows too) with (a) IMD, (b) CHIRPS-aligned, (c) >= 2 valid
    wide neighbours (observed values), (d) any reference."""
    mats = evaluate.to_matrices(table)
    ids = list(mats.value_obs.columns)
    n_valid = neighbours.neighbour_reference(mats.value_obs, wide_table)["n_valid"].to_numpy()
    imd = refs.available("imd")[ids].to_numpy()
    chirps = refs.available("chirps_aligned")[ids].to_numpy()
    nbr = n_valid >= 2
    out = {}
    for split in sorted(set(mats.split_of.values())):
        cols = np.array([i for i, sid in enumerate(ids) if mats.split_of[sid] == split])
        clean = mats.clean_real[:, cols]
        sel = {"imd": imd[:, cols], "chirps_aligned": chirps[:, cols], "wide_neighbours_ge2": nbr[:, cols]}
        sel["any_reference"] = sel["imd"] | sel["chirps_aligned"] | sel["wide_neighbours_ge2"]
        out[split] = {"clean_real_days": int(clean.sum()),
                      **{name: {"days": int((m & clean).sum()),
                                "share": float((m & clean).sum() / clean.sum()) if clean.sum() else float("nan")}
                         for name, m in sel.items()}}
    return out


def load_or_build_refs(meta: pd.DataFrame, index: pd.DatetimeIndex, path: Path, rebuild: bool) -> grids.GridRefs:
    ids = np.asarray(meta["id"], dtype="U16")
    if path.is_file() and not rebuild:
        with np.load(path) as cached:
            if (np.array_equal(cached["ids"], ids) and len(cached["dates"]) == len(index)
                    and cached["dates"][0] == index[0].strftime("%Y-%m-%d")
                    and cached["dates"][-1] == index[-1].strftime("%Y-%m-%d")):
                return grids.GridRefs({n: pd.DataFrame(cached[n], index=index, columns=list(ids))
                                       for n in grids.SOURCES})
    refs = grids.station_grid_refs(meta, index)
    np.savez_compressed(path, ids=ids, dates=index.strftime("%Y-%m-%d").to_numpy().astype("U10"),
                        **{n: refs.values[n].to_numpy() for n in grids.SOURCES})
    return refs


TRAIN_EXTRA_SEEDS = (20261101, 20261102, 20261103, 20261104)   # extra injections for TRAIN stations (training only)
STABILITY_SEEDS = (20261201, 20261202, 20261203)                 # extra injections for VAL / TEST stations (stability check)


def load_or_build_seed_set(seed: int, window: StationSet, splits: dict, calibration: dict | None,
                           refs: grids.GridRefs, wide_table: pd.DataFrame, split_names, rebuild: bool = False):
    """(table, features) of an extra injection seed, restricted to the stations of `split_names`.

    Same frozen splits and injector settings as the headline dataset (ENGINE_MIN_VALID_DAYS, ENGINE_DENSITY);
    only the seed differs. Cached in data/processed/integrity/seeds/."""
    wanted = {sid for name in split_names for sid in splits[name]}
    ids = [sid for sid in window.meta["id"] if sid in wanted]
    folder = integrity_dir() / "seeds"
    folder.mkdir(exist_ok=True)
    tag = f"seed_{seed}_{'_'.join(sorted(split_names))}"
    t_path, f_path = folder / f"{tag}_dataset.parquet", folder / f"{tag}_features.parquet"
    if t_path.is_file() and f_path.is_file() and not rebuild:
        return pd.read_parquet(t_path), pd.read_parquet(f_path)
    full = inject.build_fault_dataset(window, splits, seed=seed, density=ENGINE_DENSITY, calibration=calibration,
                                      min_valid_days=ENGINE_MIN_VALID_DAYS)
    obs = evaluate.to_matrices(full).value_obs[list(window.meta["id"])]
    feats = features.build_features(obs, obs.index, window.meta, refs, wide_table, stations=ids)
    table = full[full["station"].astype(str).isin(set(ids))].reset_index(drop=True)
    table["station"] = table["station"].astype(str)
    table.to_parquet(t_path, index=False)
    feats.to_parquet(f_path, index=False)
    return table, feats


REAL_FEATURES_NAME = "features_real_2007.parquet"


def load_or_build_real_features(window: StationSet, refs: grids.GridRefs, wide_table: pd.DataFrame,
                                rebuild: bool = False) -> pd.DataFrame:
    """Features of the REAL (uninjected) 2007-2024 series, cached; used for the out-of-fold outputs and the
    real-flag sanity check."""
    path = integrity_dir() / REAL_FEATURES_NAME
    expected = window.values.size
    if path.is_file() and not rebuild:
        cached = pd.read_parquet(path)
        if len(cached) == expected:
            return cached
    feats = features.build_features(window.values, window.values.index, window.meta, refs, wide_table)
    feats.to_parquet(path, index=False)
    return feats


def run(raw_dir=None, rebuild: bool = False) -> dict:
    """Build the restricted dataset, reference coverage and features; returns the combined report."""
    if not default_path().is_file():
        raise FileNotFoundError("the frozen station split is missing; run aetherguard.integrity.baseline_report first")
    full = load_station_set(raw_dir, start=None, end=None)
    sset = _window(full, "1990-01-01", "2024-12-31")
    splits = make_station_splits(full.meta, seed=SPLIT_SEED)   # reads the frozen file
    out = integrity_dir()
    path = out / ENGINE_DATASET_NAME
    if path.is_file() and not rebuild:
        table = pd.read_parquet(path)
        previous = out / ENGINE_REPORT_NAME
        recorded = json.loads(previous.read_text(encoding="utf-8")).get("build", {}) if previous.is_file() else {}
        info = recorded if "chosen" in recorded else {"reused": True}  # keep the ladder record of the original build
    else:
        table, info = build_engine_dataset(sset, splits, real_flag_calibration(full, sset))
        table.to_parquet(path, index=False)
    window = _window(sset, *ENGINE_PERIOD)
    refs = load_or_build_refs(window.meta, window.values.index, out / REFS_CACHE_NAME, rebuild)
    wide = neighbours.neighbour_table(window.meta, *NEIGHBOUR_SETTINGS["wide"])
    report = {"period": list(ENGINE_PERIOD), "build": info,
              "dataset": inject.dataset_report(table),
              "reference_coverage_all_station_days": refs.coverage(),
              "reference_coverage_clean_days": reference_coverage(table, refs, wide)}
    (out / ENGINE_REPORT_NAME).write_text(dumps_strict(report), encoding="utf-8")
    mats = evaluate.to_matrices(table)
    obs = mats.value_obs[list(window.meta["id"])]
    feats = features.build_features(obs, obs.index, window.meta, refs, wide)
    feats.to_parquet(out / FEATURES_NAME, index=False)
    feature_report = features.feature_report(feats)
    (out / FEATURES_REPORT_NAME).write_text(dumps_strict(feature_report), encoding="utf-8")
    report["features"] = feature_report
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw-dir", default=None)
    parser.add_argument("--rebuild", action="store_true", help="rebuild the 2007 dataset and the reference cache")
    args = parser.parse_args(argv)
    report = run(args.raw_dir, rebuild=args.rebuild)
    chosen = report["build"].get("chosen", "reused")
    print(f"engine dataset ({chosen}): {report['dataset']['n_episodes']} episodes; "
          f"features {report['features']['rows']} rows x {report['features']['n_features']} "
          f"({report['features']['memory_mb']} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
