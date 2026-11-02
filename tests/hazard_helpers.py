"""Synthetic feature tables with the schema of the frozen feature store, for the hazard tests."""
from __future__ import annotations

import numpy as np
import pandas as pd

META_COLUMNS = ["cell_id", "date", "split", "region", "label", "kind", "terrain_source", "terrain_cell_id",
                "in_domain", "rain_ok", "lat", "lon", "month", "rain_source", "weight", "universe_size",
                "in_buffer", "is_positive_cell_day", "is_window_positive_cell", "slope_ok"]
FEATURE_GROUPS = {
    "rain_acc_1": "rain", "rain_acc_3": "rain", "rain_acc_5": "rain", "rain_acc_7": "rain",
    "rain_acc_14": "rain", "rain_acc_30": "rain",
    "rain_max1d_7": "rain", "rain_wetdays_30": "rain", "rain_days_since_10mm": "rain",
    "rain_acc3_vs_clim": "rain",
    "src_imd_acc_1": "src", "src_chi_acc_1": "src", "src_dis_diff_1": "src", "src_dis_ratio_1": "src",
    "wet_top": "wet", "wet_top_chg3": "wet",
    "stat_relief": "stat", "stat_slope_mean": "stat", "stat_elev_mean": "stat", "stat_aspect_sin": "stat",
}
COLUMN_MAP = {**{c: "meta" for c in META_COLUMNS}, **FEATURE_GROUPS}
UNIVERSE_SIZES = {"himalaya": 9_000_000, "western_ghats": 3_000_000}


def _features(rng: np.random.Generator, n: int, positive: np.ndarray) -> dict[str, np.ndarray]:
    """Risk rises with rain and slope; positives are shifted up. NaNs in some src_ columns."""
    shift = np.where(positive, 1.0, 0.0)
    acc1 = np.exp(rng.normal(1.5 + 1.4 * shift, 0.8, n))
    acc3 = acc1 * (1.5 + rng.random(n))
    acc7 = acc3 * (1.5 + rng.random(n))
    slope = np.clip(rng.normal(14 + 8 * shift, 6, n), 2.6, 45)
    out = {
        "rain_acc_1": acc1, "rain_acc_3": acc3, "rain_acc_5": acc3 * 1.3, "rain_acc_7": acc7,
        "rain_acc_14": acc7 * 1.5, "rain_acc_30": acc7 * (2 + rng.random(n)),
        "rain_max1d_7": acc1 * (1 + rng.random(n)), "rain_wetdays_30": rng.integers(2, 30, n).astype(float),
        "rain_days_since_10mm": rng.integers(0, 20, n).astype(float) - 4 * shift,
        "rain_acc3_vs_clim": acc3 / 20.0,
        "src_imd_acc_1": acc1 + rng.normal(0, 1, n), "src_chi_acc_1": acc1 * rng.uniform(0.5, 1.5, n),
        "src_dis_diff_1": rng.normal(0, 3, n), "src_dis_ratio_1": rng.uniform(0.5, 2, n),
        "wet_top": rng.uniform(0.2, 0.9, n), "wet_top_chg3": rng.normal(0, 0.05, n),
        "stat_relief": slope * 10 + rng.normal(0, 20, n), "stat_slope_mean": slope,
        "stat_elev_mean": rng.uniform(100, 3000, n), "stat_aspect_sin": rng.uniform(-1, 1, n),
    }
    for name in ("src_imd_acc_1", "src_chi_acc_1", "src_dis_diff_1", "src_dis_ratio_1"):
        out[name][rng.random(n) < 0.1] = np.nan
    return {k: v.astype(np.float32) for k, v in out.items()}


def _random_dates(rng: np.random.Generator, n: int, years) -> pd.Series:
    start = np.array([np.datetime64(f"{y}-01-01") for y in years])
    spans = np.array([366 if y % 4 == 0 else 365 for y in years])
    pick = rng.integers(0, len(years), n)
    return pd.Series(start[pick] + rng.integers(0, spans[pick]).astype("timedelta64[D]")).astype("datetime64[ns]")


def synthetic_samples(split: str, n_pos: int = 120, ratio: int = 5, seed: int = 0, n_out_of_domain: int = 3,
                      years=None) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    n_neg = n_pos * ratio
    n = n_pos + n_neg + n_out_of_domain
    kind = np.array(["positive"] * (n_pos + n_out_of_domain) + ["negative"] * n_neg)
    positive = kind == "positive"
    frame = pd.DataFrame({
        "cell_id": np.arange(n, dtype=np.int64) + 1_000_000, "date": pd.Timestamp("2010-07-01"),
        "split": split, "region": np.where(rng.random(n) < 0.7, "himalaya", "western_ghats"),
        "label": positive.astype(np.int8), "kind": kind, "terrain_source": "own",
        "in_domain": np.r_[np.ones(n_pos, bool), np.zeros(n_out_of_domain, bool), np.ones(n_neg, bool)],
        "rain_ok": True, "lat": np.float32(25.0), "lon": np.float32(90.0), "month": np.int8(7),
        "rain_source": "imd"})
    if years is not None:
        frame["date"] = _random_dates(rng, n, years)
    for name, values in _features(rng, n, positive).items():
        frame[name] = values
    return frame


def synthetic_universe(split: str, n_per_region: int = 3000, seed: int = 1, n_buffer: int = 30,
                       years=None) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    parts = []
    for r, (region, size) in enumerate(UNIVERSE_SIZES.items()):
        n = n_per_region
        frame = pd.DataFrame({
            "cell_id": np.arange(n, dtype=np.int64) + 5_000_000 + r * 100_000, "date": pd.Timestamp("2010-08-01"),
            "split": split, "region": region, "kind": "universe", "weight": size / n, "universe_size": size,
            "in_buffer": np.arange(n) < n_buffer, "is_positive_cell_day": np.arange(n) == n - 1,
            "lat": np.float32(25.0), "lon": np.float32(90.0), "month": np.int8(7)})
        if years is not None:
            frame["date"] = _random_dates(rng, n, years)
        for name, values in _features(rng, n, np.zeros(n, bool)).items():
            frame[name] = values
        parts.append(frame)
    return pd.concat(parts, ignore_index=True)


TRAIN_YEARS = tuple(range(2007, 2016))
VALIDATION_YEARS = (2016, 2017)


def synthetic_development(n_pos_train: int = 90, n_pos_validation: int = 40, n_per_region: int = 3000, seed: int = 0):
    """(samples, universe) of the development period: train covers 2007-2015, validation 2016-2017."""
    samples = pd.concat([synthetic_samples("train", n_pos_train, seed=seed, years=TRAIN_YEARS),
                         synthetic_samples("validation", n_pos_validation, seed=seed + 1, years=VALIDATION_YEARS)],
                        ignore_index=True)
    samples["cell_id"] = np.arange(len(samples), dtype=np.int64) + 1_000_000
    universe = pd.concat([synthetic_universe("train", n_per_region, seed + 2, years=TRAIN_YEARS),
                          synthetic_universe("validation", n_per_region, seed + 3, years=VALIDATION_YEARS)],
                         ignore_index=True)
    universe["cell_id"] = np.arange(len(universe), dtype=np.int64) + 5_000_000
    return samples, universe


INTEG_COLUMNS = {"integ_n_st_100km": "integ", "integ_trw_rain_1": "integ", "integ_frac_trusted_100km": "integ"}
CORR_COLUMNS = {"corr_q50_1": "corr", "corr_p_exceed99": "corr"}


def write_store(directory, tables: dict, seed: int = 5, extras: bool = True):
    """A tiny feature store: `tables` maps file stems (e.g. `train_samples`, `universe_test_2018`) to frames; writes the
    base tables, the column map and, optionally, the integ / corrector extra files with manifests."""
    import hashlib
    import json
    from pathlib import Path
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    for name, frame in tables.items():
        frame.to_parquet(directory / f"{name}_features.parquet")
    (directory / "feature_columns.json").write_text(json.dumps(dict(COLUMN_MAP)), encoding="utf-8")
    if not extras:
        return directory
    for subdir, suffix, columns, manifest in (("integ", "integ", INTEG_COLUMNS, "integ_manifest.json"),
                                              ("corrector", "corr", CORR_COLUMNS, "corrector_manifest.json")):
        sub = directory / subdir
        sub.mkdir(exist_ok=True)
        files = {}
        for name, frame in tables.items():
            extra = frame[["cell_id", "date"]].copy()
            for column in columns:
                extra[column] = rng.random(len(frame)).astype(np.float32)
                if column == "integ_n_st_100km":
                    extra[column] = (rng.random(len(frame)) < 0.4).astype(np.float32) * 3
            path = sub / f"{name}_{suffix}.parquet"
            extra.to_parquet(path)
            files[path.name] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "n_rows": len(extra)}
        (sub / f"{subdir}_columns.json").write_text(json.dumps(columns), encoding="utf-8")
        (sub / manifest).write_text(json.dumps({"files": files}), encoding="utf-8")
    return directory


def write_dev_store(directory, samples: pd.DataFrame, universe: pd.DataFrame, seed: int = 5, extras: bool = True):
    """A tiny development feature store (train and validation tables, with optional extra files)."""
    tables = {}
    for split, (sample_name, universe_name) in {"train": ("train_samples", "universe_train"),
                                                "validation": ("validation_samples", "universe_validation")}.items():
        tables[sample_name] = samples[samples["split"] == split].reset_index(drop=True)
        tables[universe_name] = universe[universe["split"] == split].reset_index(drop=True)
    return write_store(directory, tables, seed, extras)


EXTRA_GROUPS = {"integ": {"subdir": "integ", "suffix": "integ", "columns_file": "integ_columns.json",
                          "manifest_file": "integ_manifest.json"},
                "corr": {"subdir": "corrector", "suffix": "corr", "columns_file": "corrector_columns.json",
                         "manifest_file": "corrector_manifest.json"}}
