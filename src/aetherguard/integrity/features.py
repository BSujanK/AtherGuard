"""Causal feature matrix for the learned integrity model (one row per station-day).

EVERY feature at day t uses only information up to and including day t (trailing windows, running
counters): the engine runs causally. The only look-up that is not a function of the past is the per-station
wet-day percentile table, computed once from the TRAIN years (2007-2015) of the station's own observed
series (`station_climatology`) and passed in as a fixed table, so nothing from validation / test years leaks.

Column groups, selectable with `select_columns` (an ablation is a column filter):
  own_   the station's own series
  nbr_   references from the neighbours' observed values (wide table: k=10 within 300 km)
  grid_  references from the IMD and CHIRPS-aligned grids and the cross-source agreement counts
  wet_   POWER soil wetness (UTC day, GWETTOP masked where GWETROOT is NaN)

Definitions that need a choice (all documented here, none silent):
* wet day = value >= 1 mm. A trailing window of w days gives a statistic only if at least ceil(0.7 w) of its
  days are observed, else NaN (missing is never 0).
* ratios against a reference use +1 mm smoothing, (obs + 1) / (ref + 1), so dry references do not blow up.
* correlations are Pearson over the days where both series are valid in the trailing window; NaN with fewer
  than 10 pairs or a constant series (so they use 14- and 30-day windows: a 7-day window cannot hold 10 pairs).
* `grid_agree_count` is defined only when obs >= 20 mm (NaN otherwise): the number of independent references
  among imd, chirps_aligned and the neighbour idw mean with a value >= 0.3 * obs.
"""
from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

from . import neighbours
from .grids import GridRefs

WET_MM = 1.0
WINDOWS = (7, 14, 30)
MIN_VALID_SHARE = 0.7
MIN_PAIRS = 10
TRAIN_YEARS = (2007, 2015)
MIN_CLIMATOLOGY_WET_DAYS = 20
CLIMATOLOGY_PERCENTILES = {"p50": 50, "p90": 90, "p99": 99}
AGREE_MIN_OBS_MM = 20.0
AGREE_FRACTION = 0.3
GRID_DRY_MM = 5.0
PREFIXES = ("own_", "nbr_", "grid_", "wet_")
GRID_REFS = ("imd", "chirps_aligned")
CORR_WINDOWS = (14, 30)
SUM_WINDOWS = (7, 14, 30)


def station_climatology(values: pd.DataFrame, train_years: tuple[int, int] = TRAIN_YEARS) -> pd.DataFrame:
    """Per-station wet-day (>= 1 mm) percentiles p50 / p90 / p99 of the observed values in the train years.

    NaN for a station with fewer than 20 wet days in those years. Rows are stations."""
    window = values[(values.index.year >= train_years[0]) & (values.index.year <= train_years[1])]
    out = {}
    for sid in values.columns:
        v = window[sid].to_numpy(np.float32)
        wet = v[np.isfinite(v) & (v >= WET_MM)]
        if len(wet) < MIN_CLIMATOLOGY_WET_DAYS:
            out[sid] = {name: np.nan for name in CLIMATOLOGY_PERCENTILES}
        else:
            out[sid] = {name: float(np.percentile(wet, q)) for name, q in CLIMATOLOGY_PERCENTILES.items()}
    return pd.DataFrame.from_dict(out, orient="index", columns=list(CLIMATOLOGY_PERCENTILES))


def _windows(x: np.ndarray, w: int) -> np.ndarray:
    """(days, w) trailing windows ending on each day (NaN-padded before the first day)."""
    return sliding_window_view(np.concatenate([np.full(w - 1, np.nan, dtype=x.dtype), x]), w)


def _min_valid(w: int) -> int:
    return math.ceil(MIN_VALID_SHARE * w)


def _rolling_stats(x: np.ndarray, w: int) -> dict[str, np.ndarray]:
    win = _windows(x, w)
    valid = np.isfinite(win)
    n = valid.sum(axis=1)
    ok = n >= _min_valid(w)
    filled = np.where(valid, win, 0.0).astype(np.float64)
    safe_n = np.maximum(n, 1)
    mean = filled.sum(axis=1) / safe_n
    var = (np.where(valid, (win - mean[:, None]) ** 2, 0.0)).sum(axis=1) / safe_n
    zero = ((win == 0) & valid).sum(axis=1) / safe_n
    top = np.where(valid, win, -np.inf).max(axis=1)
    ordered = np.diff(np.sort(win, axis=1), axis=1)
    distinct = 1 + ((ordered != 0) & np.isfinite(ordered)).sum(axis=1)
    same = win[:, 1:] == win[:, :-1]
    current = np.ones(len(win), dtype=np.int32)
    longest = current.copy()
    for j in range(same.shape[1]):
        current = np.where(same[:, j], current + 1, 1)
        longest = np.maximum(longest, current)
    wet = ((win >= WET_MM) & valid).sum(axis=1) / safe_n
    stats = {"mean": mean, "std": np.sqrt(var), "zero_frac": zero, "max": top, "distinct": distinct,
             "longest_run": longest, "wet_frac": wet}
    return {k: np.where(ok, v, np.nan) for k, v in stats.items()}


def _current_runs(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Length of the run of identical values ending today (NaN on missing days), and its positive-only twin."""
    t = np.arange(len(x))
    same = np.zeros(len(x), dtype=bool)
    same[1:] = (x[1:] == x[:-1]) & np.isfinite(x[1:])
    last_break = np.maximum.accumulate(np.where(~same, t, 0))
    run = (t - last_break + 1).astype(np.float64)
    run[~np.isfinite(x)] = np.nan
    positive = np.where(x > 0, run, np.where(np.isfinite(x), 0.0, np.nan))
    return run, positive


def _days_since_wet(x: np.ndarray) -> np.ndarray:
    t = np.arange(len(x))
    last = np.maximum.accumulate(np.where(np.isfinite(x) & (x >= WET_MM), t, -1))
    return np.where(last >= 0, t - last, np.nan).astype(np.float64)


def _trailing_corr(x: np.ndarray, y: np.ndarray, w: int) -> np.ndarray:
    """Pearson correlation of x and y over the days of the trailing window where both are valid."""
    wx, wy = _windows(x.astype(np.float64), w), _windows(y.astype(np.float64), w)
    pair = np.isfinite(wx) & np.isfinite(wy)
    n = pair.sum(axis=1)
    safe_n = np.maximum(n, 1)
    mx = np.where(pair, wx, 0.0).sum(axis=1) / safe_n
    my = np.where(pair, wy, 0.0).sum(axis=1) / safe_n
    dx, dy = np.where(pair, wx - mx[:, None], 0.0), np.where(pair, wy - my[:, None], 0.0)
    sxx, syy, sxy = (dx * dx).sum(axis=1), (dy * dy).sum(axis=1), (dx * dy).sum(axis=1)
    denom = np.sqrt(sxx * syy)
    good = (n >= MIN_PAIRS) & (sxx > 1e-12) & (syy > 1e-12)
    return np.where(good, sxy / np.where(denom > 0, denom, 1.0), np.nan)


def _pair_sums(x: np.ndarray, g: np.ndarray, w: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Trailing sums of x and g over the days where both are valid, and the number of such days."""
    wx, wg = _windows(x.astype(np.float64), w), _windows(g.astype(np.float64), w)
    pair = np.isfinite(wx) & np.isfinite(wg)
    n = pair.sum(axis=1)
    return np.where(pair, wx, 0.0).sum(axis=1), np.where(pair, wg, 0.0).sum(axis=1), n


def _trailing_fraction(flag: np.ndarray, pair: np.ndarray, w: int) -> np.ndarray:
    """Share of the last w days with `flag` (on valid pairs only); NaN with fewer than 7 valid pairs."""
    f = _windows(flag.astype(np.float64), w).sum(axis=1)
    n = _windows(pair.astype(np.float64), w).sum(axis=1)
    return np.where(n >= 7, f / w, np.nan)


def _ratio(num: np.ndarray, den: np.ndarray) -> np.ndarray:
    return (num + 1.0) / (den + 1.0)


def _own_features(x: np.ndarray, clim: pd.Series) -> dict[str, np.ndarray]:
    out: dict[str, np.ndarray] = {}
    stats = {w: _rolling_stats(x, w) for w in WINDOWS}
    for w in WINDOWS:
        for name in ("mean", "std", "zero_frac", "max", "distinct", "longest_run"):
            out[f"own_{name}_{w}"] = stats[w][name]
    out["own_wet_frac_30"] = stats[30]["wet_frac"]
    out["own_run_len"], out["own_pos_run_len"] = _current_runs(x)
    out["own_days_since_wet"] = _days_since_wet(x)
    for name in CLIMATOLOGY_PERCENTILES:
        out[f"own_ratio_{name}"] = x / clim[name] if np.isfinite(clim[name]) else np.full(len(x), np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        out["own_ratio_7_30"] = np.where(stats[30]["mean"] > 0, stats[7]["mean"] / stats[30]["mean"], np.nan)
    return out


def _grid_features(x: np.ndarray, refs: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    out: dict[str, np.ndarray] = {}
    for name, g in refs.items():
        short = "chirps" if name == "chirps_aligned" else name
        out[f"grid_resid_{short}"] = x - g
        out[f"grid_ratio_{short}"] = _ratio(x, g)
        for w in SUM_WINDOWS:
            sx, sg, n = _pair_sums(x, g, w)
            enough = n >= _min_valid(w)
            out[f"grid_sumdiff_{short}_{w}"] = np.where(enough, sx - sg, np.nan)
            out[f"grid_sumratio_{short}_{w}"] = np.where(enough, _ratio(sx, sg), np.nan)
        out[f"grid_corr_{short}_30"] = _trailing_corr(x, g, 30)
        pair = np.isfinite(x) & np.isfinite(g)
        with np.errstate(invalid="ignore"):
            out[f"grid_zero_vs_wet_{short}_14"] = _trailing_fraction(pair & (x == 0) & (g > GRID_DRY_MM), pair, 14)
            out[f"grid_wet_vs_zero_{short}_14"] = _trailing_fraction(pair & (x > GRID_DRY_MM) & (g == 0), pair, 14)
    return out


def _agreement(x: np.ndarray, independent: Sequence[np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    stacked = np.stack(independent)
    n_refs = np.isfinite(stacked).sum(axis=0).astype(np.float64)
    with np.errstate(invalid="ignore"):
        agree = (np.isfinite(stacked) & (stacked >= AGREE_FRACTION * x[None, :])).sum(axis=0).astype(np.float64)
    agree = np.where(np.isfinite(x) & (x >= AGREE_MIN_OBS_MM), agree, np.nan)
    return agree, n_refs


def select_columns(columns: Sequence[str], groups: Sequence[str]) -> list[str]:
    """The feature columns whose prefix is in `groups` (e.g. ("own_",) or ("own_", "wet_"))."""
    unknown = set(groups) - set(PREFIXES)
    if unknown:
        raise ValueError(f"unknown feature groups {sorted(unknown)}; choose from {PREFIXES}")
    return [c for c in columns if c.startswith(tuple(groups))]


def build_features(values: pd.DataFrame, dates, meta: pd.DataFrame, refs: GridRefs,
                   neighbour_table: pd.DataFrame, climatology: pd.DataFrame | None = None,
                   stations: Sequence[str] | None = None) -> pd.DataFrame:
    """Feature table: columns station, date, then float32 own_/nbr_/grid_/wet_ columns.

    `values` is the OBSERVED date x station matrix (the engine never sees the truth); `dates` must equal its
    index and the `refs` index. `climatology` (from `station_climatology`; default: computed from `values`) is a
    fixed per-station table. `stations` restricts the output to some stations (neighbours still use all)."""
    index = pd.DatetimeIndex(dates)
    if not (values.index.equals(index) and refs.index.equals(index)):
        raise ValueError("values, refs and dates must share the same daily index")
    if list(refs.columns) != list(values.columns) or list(meta["id"]) != list(values.columns):
        raise ValueError("values, refs and meta must list the same stations in the same order")
    clim = climatology if climatology is not None else station_climatology(values)
    nbr = neighbours.neighbour_reference(values, neighbour_table)
    chosen = list(stations) if stations is not None else list(values.columns)
    pieces = []
    for sid in chosen:
        x = values[sid].to_numpy(np.float32)
        cols: dict[str, np.ndarray] = _own_features(x, clim.loc[sid])
        idw = nbr["idw_mean"][sid].to_numpy(np.float32)
        cols["nbr_idw_mean"] = idw
        cols["nbr_median"] = nbr["median"][sid].to_numpy(np.float32)
        cols["nbr_max"] = nbr["max"][sid].to_numpy(np.float32)
        cols["nbr_n_valid"] = nbr["n_valid"][sid].to_numpy(np.float32)
        cols["nbr_frac_wet"] = nbr["frac_wet"][sid].to_numpy(np.float32)
        cols["nbr_resid"] = x - idw
        cols["nbr_ratio"] = _ratio(x, idw)
        for w in CORR_WINDOWS:
            cols[f"nbr_corr_{w}"] = _trailing_corr(x, idw, w)
        grids = {name: refs.values[name][sid].to_numpy(np.float32) for name in GRID_REFS}
        cols.update(_grid_features(x, grids))
        cols["grid_agree_count"], cols["grid_n_refs"] = _agreement(x, [grids["imd"], grids["chirps_aligned"], idw])
        top, root = refs.values["gw_top"][sid].to_numpy(np.float32), refs.values["gw_root"][sid].to_numpy(np.float32)
        cols["wet_top"], cols["wet_root"] = top, root
        for name, series in (("top", top), ("root", root)):
            change = np.full(len(series), np.nan, dtype=np.float32)
            change[3:] = series[3:] - series[:-3]
            cols[f"wet_{name}_chg3"] = change
        frame = pd.DataFrame({k: np.asarray(v, dtype=np.float32) for k, v in cols.items()})
        frame.insert(0, "date", index)
        frame.insert(0, "station", sid)
        pieces.append(frame)
    return pd.concat(pieces, ignore_index=True)


def feature_report(features: pd.DataFrame) -> dict:
    """Rows, memory and NaN shares per group and per column, over all rows and over the rows where the station
    has an observed value (`own_run_len` is NaN exactly on missing days)."""
    cols = [c for c in features.columns if c not in ("station", "date")]
    observed = features["own_run_len"].notna()
    nan_all = features[cols].isna().mean()
    nan_obs = features.loc[observed, cols].isna().mean() if observed.any() else nan_all * np.nan
    groups = {}
    for prefix in PREFIXES:
        members = [c for c in cols if c.startswith(prefix)]
        groups[prefix] = {"columns": len(members), "nan_share_mean": float(nan_all[members].mean()),
                          "nan_share_mean_on_observed_days": float(nan_obs[members].mean())}
    return {"rows": int(len(features)), "rows_with_observed_value": int(observed.sum()), "n_features": len(cols),
            "memory_mb": round(float(features.memory_usage(deep=True).sum()) / 2**20, 1),
            "by_group": groups, "nan_share_by_column": {c: float(nan_all[c]) for c in cols},
            "nan_share_by_column_on_observed_days": {c: float(nan_obs[c]) for c in cols}}
