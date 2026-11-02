"""Baselines the learned engine has to beat; each scores ANY date x station values matrix.

* range_check         bool flag: value outside 0..1500 mm/day (or +-inf).
* noaa_style_qa       bool flag: re-implementation of the NOAA checks K (streak), D (duplicate block),
                      O (climatological outlier) and S (spatial), see NoaaQaConfig.
* robust_zscore       float score: |x - median| / (1.4826 MAD + eps) over a trailing 60-day window
                      of the station's own series (today included), wet days only, 0 on dry days.
* isolation_forest    float score (higher = more anomalous): sklearn IsolationForest fitted on the
                      rolling features of the TRAIN stations, applied to any other stations.

NaN in an output means "not scored" (missing reading, or too little history): it is never a flag
and never a 0 score. Neighbour-based rules use the neighbours' OBSERVED values.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view
from sklearn.ensemble import IsolationForest

from . import checks, neighbours

ZSCORE_WINDOW = 60
ZSCORE_MIN_PERIODS = 30
ZSCORE_EPS = 0.1          # mm, the gauge resolution: keeps a zero MAD from dividing by zero
MAD_TO_SIGMA = 1.4826
WINDOWS = (7, 14)
_STATS = ("mean", "std", "zero_frac", "max", "distinct", "longest_run")
FEATURE_NAMES = ["value"] + [f"{stat}_{w}" for w in WINDOWS for stat in _STATS]


@dataclass(frozen=True)
class NoaaQaConfig:
    """Thresholds of the NOAA-style re-implementation.

    d_min_block = 28 is the shortest real NOAA D run in the selected stations (whole duplicated
    months of 28-31 days, 61-62 for two months)."""
    k_min_run: int = checks.NOAA_K_MIN_RUN
    d_min_block: int = 28
    d_min_positive: int = checks.DUPLICATE_MIN_POSITIVE
    o_factor: float = 1.5
    o_percentile: float = 99.9
    wet_mm: float = 1.0
    min_wet_days: int = 100      # fewer wet days than this: no percentile, no O flags
    s_high_mm: float = 10.0
    s_low_mm: float = 1.0
    s_min_neighbours: int = 3


def _frame_like(values: pd.DataFrame, array: np.ndarray) -> pd.DataFrame:
    return pd.DataFrame(array, index=values.index, columns=values.columns)


def range_check(values: pd.DataFrame, max_mm: float = checks.MAX_MM) -> pd.DataFrame:
    return checks.bounds(values, max_mm)


def noaa_style_reasons(values: pd.DataFrame, table: pd.DataFrame,
                       cfg: NoaaQaConfig | None = None) -> dict[str, pd.DataFrame]:
    """The four NOAA-style checks as separate boolean frames {K, D, O, S}."""
    cfg = cfg or NoaaQaConfig()
    data = values.to_numpy(np.float32)
    with np.errstate(invalid="ignore"):
        wet = np.where(data >= cfg.wet_mm, data, np.nan)
        counts = np.isfinite(wet).sum(axis=0)
        limit = np.full(data.shape[1], np.inf)
        for j in np.flatnonzero(counts >= cfg.min_wet_days):
            limit[j] = cfg.o_factor * np.nanpercentile(wet[:, j], cfg.o_percentile)
        outlier = data > limit[None, :]
        high = neighbours.neighbour_count(values, table, cfg.s_high_mm, strict=True).to_numpy()
        ref = neighbours.neighbour_reference(values, table)
        n_valid, nb_max = ref["n_valid"].to_numpy(), ref["max"].to_numpy()
        zero_while_wet_around = (data == 0) & (high >= cfg.s_min_neighbours)
        wet_while_dry_around = ((data > cfg.s_high_mm) & (n_valid >= cfg.s_min_neighbours)
                                & (nb_max < cfg.s_low_mm))
    return {
        "K": _frame_like(values, checks.stuck(data, cfg.k_min_run)),
        "D": _frame_like(values, checks.duplicate_block(data, cfg.d_min_block, cfg.d_min_positive)),
        "O": _frame_like(values, outlier),
        "S": _frame_like(values, zero_while_wet_around | wet_while_dry_around),
    }


def noaa_style_qa(values: pd.DataFrame, table: pd.DataFrame, cfg: NoaaQaConfig | None = None) -> pd.DataFrame:
    reasons = noaa_style_reasons(values, table, cfg)
    return reasons["K"] | reasons["D"] | reasons["O"] | reasons["S"]


def _robust_column(x: np.ndarray, window: int, min_periods: int, eps: float) -> np.ndarray:
    score = np.zeros(len(x), dtype=np.float32)
    score[~np.isfinite(x)] = np.nan
    wet = np.flatnonzero(np.isfinite(x) & (x > 0))
    if len(wet) == 0:
        return score
    padded = np.concatenate([np.full(window - 1, np.nan, dtype=np.float32), x])
    windows = sliding_window_view(padded, window)[wet]
    enough = np.isfinite(windows).sum(axis=1) >= min_periods
    score[wet[~enough]] = np.nan
    windows, rows = windows[enough], wet[enough]
    median = np.nanmedian(windows, axis=1)
    mad = np.nanmedian(np.abs(windows - median[:, None]), axis=1)
    score[rows] = np.abs(x[rows] - median) / (MAD_TO_SIGMA * mad + eps)
    return score


def robust_zscore(values: pd.DataFrame, window: int = ZSCORE_WINDOW,
                  min_periods: int = ZSCORE_MIN_PERIODS, eps: float = ZSCORE_EPS) -> pd.DataFrame:
    """Score per station-day (see module doc); NaN for a wet day with fewer than `min_periods`
    valid days in its window."""
    data = values.to_numpy(np.float32)
    out = np.column_stack([_robust_column(np.ascontiguousarray(data[:, j]), window, min_periods, eps)
                           for j in range(data.shape[1])]) if data.shape[1] else data
    return _frame_like(values, out)


def _distinct(block: np.ndarray) -> np.ndarray:
    return 1 + (np.diff(np.sort(block, axis=1), axis=1) != 0).sum(axis=1)


def _longest_run(block: np.ndarray) -> np.ndarray:
    same = block[:, 1:] == block[:, :-1]
    current = np.ones(len(block), dtype=np.int32)
    best = current.copy()
    for j in range(same.shape[1]):
        current = np.where(same[:, j], current + 1, 1)
        best = np.maximum(best, current)
    return best


def window_features(series) -> np.ndarray:
    """(days, len(FEATURE_NAMES)) rolling features of one station's series.

    Trailing windows of 7 and 14 days that END on the day (mean, std, zero fraction, max,
    number of distinct values, longest identical run) plus the day's own value. A day is scored
    only when its whole 14-day window is observed; otherwise its row is NaN."""
    x = np.asarray(series, dtype=np.float32)
    longest = max(WINDOWS)
    out = np.full((len(x), len(FEATURE_NAMES)), np.nan, dtype=np.float32)
    if len(x) < longest:
        return out
    windows = sliding_window_view(x, longest)
    rows = np.flatnonzero(np.isfinite(windows).all(axis=1))
    if len(rows) == 0:
        return out
    block = windows[rows]
    columns = [block[:, -1]]
    for w in WINDOWS:
        part = block[:, -w:].astype(np.float64)
        columns += [part.mean(axis=1), part.std(axis=1), (part == 0).mean(axis=1), part.max(axis=1),
                    _distinct(part), _longest_run(part)]
    out[rows + longest - 1] = np.column_stack(columns).astype(np.float32)
    return out


def fit_isolation_forest(values_train: pd.DataFrame, seed: int, n_estimators: int = 200,
                         max_samples: int = 1024) -> IsolationForest:
    """Fit on the rolling features of every scoreable day of the given (TRAIN) stations."""
    data = values_train.to_numpy(np.float32)
    rows = [f[np.isfinite(f).all(axis=1)] for f in (window_features(data[:, j]) for j in range(data.shape[1]))]
    features = np.concatenate(rows) if rows else np.empty((0, len(FEATURE_NAMES)), dtype=np.float32)
    if len(features) == 0:
        raise ValueError("no scoreable training rows (every 14-day window has a missing value)")
    model = IsolationForest(n_estimators=n_estimators, max_samples=min(max_samples, len(features)),
                            random_state=seed, n_jobs=1)
    return model.fit(features)


def isolation_forest(values: pd.DataFrame, model: IsolationForest) -> pd.DataFrame:
    """Anomaly score per station-day (higher = more anomalous, NaN = not scoreable)."""
    data = values.to_numpy(np.float32)
    out = np.full(data.shape, np.nan, dtype=np.float32)
    for j in range(data.shape[1]):
        features = window_features(data[:, j])
        rows = np.flatnonzero(np.isfinite(features).all(axis=1))
        if len(rows):
            out[rows, j] = -model.score_samples(features[rows])
    return _frame_like(values, out)
