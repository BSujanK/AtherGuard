"""Simple comparison models that raise the same alert burden as the model under test.

Each baseline is held to v3's alert shares so that the comparison is of where the alerts go, not of how many there are.
The `shares` of every function are cumulative, as `level_scores` reads alerts: the share of scored cell-days at Watch or
above, at Warning or above, and at Emergency, so they never increase from one to the next.

* `rain_baseline`: three rain accumulation cuts, fitted on development cell-days and applied to the evaluated season;
* `susceptibility_baseline`: the same shares placed every day on the cells of highest static score, with no rain, which
  shows what the rain-driven part of the model adds.
"""
from __future__ import annotations

import numpy as np

Shares = tuple[float, float, float]
Cuts = tuple[float, float, float]


def _check_shares(shares: Shares) -> tuple[float, float, float]:
    watch, warning, emergency = (float(s) for s in shares)
    if not 1.0 >= watch >= warning >= emergency >= 0.0:
        raise ValueError(f"shares must be cumulative, in [0, 1] and not increasing, got {tuple(shares)}")
    return watch, warning, emergency


def burden_matched_cuts(values: np.ndarray, scored: np.ndarray, shares: Shares) -> Cuts:
    """Cuts (watch, warning, emergency) so that about `shares` of the scored cell-days reach each level.

    The cuts are quantiles of the finite `values` of scored cell-days, so they do not decrease, and a value at or above a
    cut reaches that level. Ties in `values` can make the realised share a little larger than asked. A share of 0, or no
    finite scored value, gives an infinite cut, which nothing reaches.
    """
    values, scored = np.asarray(values, dtype=np.float64), np.asarray(scored, dtype=bool)
    if values.shape != scored.shape:
        raise ValueError(f"values {values.shape} and scored {scored.shape} must share one shape")
    shares = _check_shares(shares)
    pool = values[scored]
    pool = pool[np.isfinite(pool)]
    if not len(pool):
        return (np.inf, np.inf, np.inf)
    cuts = [float(np.quantile(pool, 1.0 - share)) if share > 0.0 else np.inf for share in shares]
    return tuple(np.maximum.accumulate(cuts).tolist())


def threshold_levels(values: np.ndarray, cuts: Cuts) -> np.ndarray:
    """Levels (int8, 0 to 3, the shape of `values`) of the cuts each value reaches; NaN reaches none."""
    values = np.asarray(values, dtype=np.float64)
    return sum((values >= cut).astype(np.int8) for cut in cuts)


def rain_baseline(
    acc_3: np.ndarray, scored: np.ndarray, dev_acc_3: np.ndarray, dev_scored: np.ndarray, dev_shares: Shares
) -> np.ndarray:
    """Levels (cells x days) from 3-day rain alone, with cuts fitted to `dev_shares` on the development cell-days."""
    acc_3, scored = np.asarray(acc_3), np.asarray(scored, dtype=bool)
    if acc_3.shape != scored.shape:
        raise ValueError(f"acc_3 {acc_3.shape} and scored {scored.shape} must share one shape")
    levels = threshold_levels(acc_3, burden_matched_cuts(dev_acc_3, dev_scored, dev_shares))
    levels[~scored] = 0
    return levels


def susceptibility_baseline(static_score: np.ndarray, n_days: int, scored: np.ndarray, shares: Shares) -> np.ndarray:
    """Levels (cells x `n_days`) that rank each day's scored cells by `static_score` and alert the top `shares` of them.

    The count of cells at each level is the share of that day's scored cells, rounded half up. Cells with equal scores
    are ranked in index order. Unscored cells stay at level 0.
    """
    static_score, scored = np.asarray(static_score, dtype=np.float64), np.asarray(scored, dtype=bool)
    if scored.shape != (len(static_score), n_days):
        raise ValueError(f"scored {scored.shape} must have shape {(len(static_score), n_days)}: cells x days")
    shares = _check_shares(shares)
    order = np.argsort(-static_score, kind="stable")
    rank = np.empty(scored.shape, dtype=np.int64)
    rank[order] = np.cumsum(scored[order], axis=0)
    n_scored = scored.sum(axis=0)
    levels = np.zeros(scored.shape, dtype=np.int8)
    for share in shares:
        levels += (rank <= np.floor(share * n_scored + 0.5)).astype(np.int8)
    levels[~scored] = 0
    return levels
