"""Derive the data-dependent alert thresholds from the DEVELOPMENT period (train + validation, 2007-2017) only.

    python -m aetherguard.alerts.derive [--features DIR] [--out data/processed/alerts/alert_config.json]

Reads the frozen train / validation sample and universe feature tables (with their `integ_` columns) and refuses any
row from another split or dated after `derivation.dev_end` (test_2018, the 2023 window and the case sets are never
read). Universe rows carry the weights that make them represent all cell-days, so every statistic below is
weighted. Derived (percentiles in `configs/alerts.yaml`):

  dis_ratio_lo / _hi    5th / 95th percentile of src_dis_ratio_3 over cell-days where both rain sources are valid
  heavy_acc1_mm / _acc3_mm   95th percentile over cell-days of the largest 1-day / 3-day amount among IMD and CHIRPS
  agree_abs_mm          median of |station - grid| (integ_st_minus_grid_1) where a usable station exists
  agree_rel             median of |station - grid| / larger value on days where that value is >= 10 mm

The derivation block of the output also records the development share of each confidence state, the share of
cell-days on which blind escalation would fire, and how many development landslide cell-days the heavy-rain levels
cover (with the design defaults 50 mm / 100 mm for comparison).
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from ..hazard import data as hd
from ..manifest import sha256_file
from . import confidence as cf
from .config import AlertConfig, alerts_settings, default_config_path, save_config, structural_parameters
from .frames import load_feature_frame

DESIGN_DEFAULT_HEAVY = (50.0, 100.0)


def weighted_quantile(values, weights, percentile: float) -> float:
    """Percentile (0-100) of `values` with `weights`, NaN values dropped (the smallest value whose cumulative weight
    reaches the percentile)."""
    values, weights = np.asarray(values, dtype=np.float64), np.asarray(weights, dtype=np.float64)
    keep = np.isfinite(values) & (weights > 0)
    if not keep.any():
        raise ValueError("no finite values to take a percentile of")
    order = np.argsort(values[keep], kind="stable")
    v, cumulative = values[keep][order], np.cumsum(weights[keep][order])
    return float(v[min(np.searchsorted(cumulative, percentile / 100.0 * cumulative[-1]), len(v) - 1)])


def _assert_development(frame: pd.DataFrame, name: str, settings: dict) -> None:
    d = settings["derivation"]
    bad = sorted(set(frame["split"].astype(str)) - set(d["dev_splits"]))
    if bad:
        raise hd.LeakageError(f"{name}: rows of splits {bad} offered for threshold derivation; only {d['dev_splits']}")
    if pd.to_datetime(frame["date"]).max() > pd.Timestamp(d["dev_end"]):
        raise hd.LeakageError(f"{name}: rows after {d['dev_end']} offered for threshold derivation")


def _max_of_sources(frame: pd.DataFrame, window: int) -> np.ndarray:
    return np.fmax(frame[f"src_imd_acc_{window}"].to_numpy(np.float64),
                   frame[f"src_chi_acc_{window}"].to_numpy(np.float64))


def derive_parameters(universe: pd.DataFrame, positives: pd.DataFrame, settings: dict) -> tuple[AlertConfig, dict]:
    """The AlertConfig and its derivation record from development universe rows (weighted) and in-domain positives."""
    d = settings["derivation"]
    w = universe["weight"].to_numpy(np.float64)
    both = universe["src_dis_both"].to_numpy() == 1
    ratio = universe["src_dis_ratio_3"].to_numpy()
    lo, hi = (weighted_quantile(ratio[both], w[both], p) for p in d["dis_ratio_percentiles"])
    heavy1 = weighted_quantile(_max_of_sources(universe, 1), w, d["heavy_rain_universe_percentile"])
    heavy3 = weighted_quantile(_max_of_sources(universe, 3), w, d["heavy_rain_universe_percentile"])
    diff = universe["integ_st_minus_grid_1"].to_numpy(np.float64)
    agree_abs = weighted_quantile(np.abs(diff), w, d["station_agree_abs_percentile"])
    larger = np.fmax(universe["integ_trw_rain_1"].to_numpy(np.float64), universe["rain_acc_1"].to_numpy(np.float64))
    wet = np.isfinite(diff) & (larger >= d["station_agree_rel_min_mm"])
    agree_rel = weighted_quantile(np.abs(diff[wet]) / larger[wet], w[wet], d["station_agree_rel_percentile"])
    config = AlertConfig.from_dict({**structural_parameters(settings), "dis_ratio_lo": lo, "dis_ratio_hi": hi,
                                    "heavy_acc1_mm": heavy1, "heavy_acc3_mm": heavy3, "agree_abs_mm": agree_abs,
                                    "agree_rel": agree_rel})
    percentile_keys = ("dis_ratio_percentiles", "heavy_rain_universe_percentile", "station_agree_abs_percentile",
                       "station_agree_rel_percentile", "station_agree_rel_min_mm")
    return config, {"n_universe_rows": int(len(universe)), "n_positives": int(len(positives)),
                    "n_both_sources_rows": int(both.sum()), "n_station_wet_rows": int(wet.sum()),
                    "percentiles": {k: d[k] for k in percentile_keys},
                    "development_behaviour": development_behaviour(universe, positives, config)}


def _heavy_share(frame: pd.DataFrame, acc1: float, acc3: float, weights=None) -> float:
    heavy = (_max_of_sources(frame, 1) >= acc1) | (_max_of_sources(frame, 3) >= acc3)
    return float(np.average(heavy, weights=weights))


def development_behaviour(universe: pd.DataFrame, positives: pd.DataFrame, config: AlertConfig) -> dict:
    """How the derived rules behave on the development data (no station out-of-distribution information)."""
    w = universe["weight"].to_numpy(np.float64)
    u = cf.assess(universe, np.zeros(len(universe), dtype=int), config)
    p = cf.assess(positives, np.zeros(len(positives), dtype=int), config)
    states = (cf.HIGH, cf.DEGRADED, cf.INSUFFICIENT)
    return {
        "universe_confidence_share": {s: float(np.average(u["confidence"] == s, weights=w)) for s in states},
        "positives_confidence_share": {s: float(np.mean(p["confidence"] == s)) for s in states},
        "universe_blind_share": float(np.average(u["blind"], weights=w)),
        "positives_blind_share": float(p["blind"].mean()),
        "heavy_rain_share_universe": {
            "derived": _heavy_share(universe, config.heavy_acc1_mm, config.heavy_acc3_mm, w),
            "design_default_50_100": _heavy_share(universe, *DESIGN_DEFAULT_HEAVY, weights=w)},
        "heavy_rain_share_positives": {
            "derived": _heavy_share(positives, config.heavy_acc1_mm, config.heavy_acc3_mm),
            "design_default_50_100": _heavy_share(positives, *DESIGN_DEFAULT_HEAVY)}}


def derive(features_dir: Path | None = None, settings: dict | None = None) -> tuple[AlertConfig, dict]:
    settings = settings or alerts_settings()
    directory = Path(features_dir or hd.features_dir())
    universe_parts, positive_parts, files = [], [], {}
    for split in settings["derivation"]["dev_splits"]:
        for name in (hd.UNIVERSE_NAMES[split], hd.SAMPLE_NAMES[split]):
            frame = load_feature_frame(name, directory)
            _assert_development(frame, name, settings)
            (universe_parts if name == hd.UNIVERSE_NAMES[split] else positive_parts).append(
                frame if name == hd.UNIVERSE_NAMES[split] else hd.in_domain_positives(frame))
            path = directory / f"{name}_features.parquet"
            files[path.name] = {"sha256": sha256_file(path), "n_rows": int(len(frame))}
    config, record = derive_parameters(pd.concat(universe_parts, ignore_index=True),
                                       pd.concat(positive_parts, ignore_index=True), settings)
    record.update(created_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), inputs=files,
                  period=f"2007-01-01..{settings['derivation']['dev_end']} (train + validation splits)",
                  note="derived from development-period data only; test_2018, window_2023 and the case sets "
                       "are never read")
    return config, record


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--features", type=Path, default=None, help="feature store directory")
    parser.add_argument("--out", type=Path, default=None, help="alert_config.json to write")
    args = parser.parse_args(argv)
    config, record = derive(args.features)
    out = args.out or default_config_path()
    save_config(out, config, record)
    print(f"wrote {out}")
    for key, value in config.to_dict().items():
        print(f"  {key} = {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
