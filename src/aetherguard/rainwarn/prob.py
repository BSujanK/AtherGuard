"""The probability engine of the heavy-rain warnings (spec 2026-11-14-aetherguard-rain-warnings.md, sections 3, 4 and 7).

The ECMWF day files keep four statistics of the ensemble (mean, p10, p50, p90), not the members, so the member fraction
above a threshold cannot be recomputed. Two things are built from them here:

* the *raw* probability, the exceedance of a CDF rebuilt from the stored quantiles (piecewise linear through 0, p10, p50,
  p90 and an exponential tail through p50 and p90). It is shown beside the product only;
* the *predictors* of the calibrated probability: log ratios of neighbourhood statistics of the forecast to the threshold
  plus the climatological log-odds of the event, fed to a logistic regression fitted per lead and threshold on fitting days
  only. The neighbourhood (maximum or mean over a (2r+1) x (2r+1) pixel square) absorbs part of the displacement error of
  a forecast whose rain falls a few pixels away.

Warning levels combine probability and severity with fixed rules (spec section 7); nothing here is tuned on test days.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import ndimage

FIXED_MM = {"heavy": 64.5, "very_heavy": 115.6, "extremely_heavy": 204.5}
PERCENTILES = {"p95": 95.0, "p99": 99.0}
THRESHOLDS = (*FIXED_MM, *PERCENTILES)
CLIM_FLOOR = 1e-4
TAIL_FACTOR = np.log(5.0)        # P(X > p50) / P(X > p90) = 0.5 / 0.1

LEVEL_UNAVAILABLE = -1
LEVEL_NAMES = {LEVEL_UNAVAILABLE: "unavailable", 0: "none", 1: "yellow", 2: "orange", 3: "red"}
# (level, [(threshold, minimum probability), ...]) checked from red down; any one condition raises the level
LEVEL_RULES = ((3, (("very_heavy", 0.5), ("extremely_heavy", 0.25))),
               (2, (("heavy", 0.5), ("very_heavy", 0.2), ("p99", 0.4))),
               (1, (("heavy", 0.2), ("p95", 0.4))))


def is_percentile(name: str) -> bool:
    return name in PERCENTILES


def quantile_exceedance(p10, p50, p90, threshold) -> np.ndarray:
    """P(X > threshold) of the CDF through (0, 0), (p10, 0.1), (p50, 0.5), (p90, 0.9) with the exponential tail
    0.1 exp(-ln5 (x - p90) / (p90 - p50)) above p90 (zero when p90 = p50); NaN where a quantile is NaN."""
    p10, p50, p90 = (np.asarray(a, dtype=np.float64) for a in (p10, p50, p90))
    t = np.broadcast_to(np.asarray(threshold, dtype=np.float64), p50.shape)
    out = np.full(p50.shape, np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        below = 1.0 - 0.1 * np.where(p10 > 0, t / p10, 1.0)
        low = 0.9 - 0.4 * (t - p10) / (p50 - p10)
        mid = 0.5 - 0.4 * (t - p50) / (p90 - p50)
        tail = np.where(p90 > p50, 0.1 * np.exp(-TAIL_FACTOR * (t - p90) / (p90 - p50)), 0.0)
    out = np.where(t <= p10, below, np.where(t <= p50, low, np.where(t <= p90, mid, tail)))
    out = np.where(np.isfinite(p10) & np.isfinite(p50) & np.isfinite(p90), np.clip(out, 0.0, 1.0), np.nan)
    return out


def neighbourhood(grid: np.ndarray, radius: int, how: str) -> np.ndarray:
    """Maximum or mean over the (2r+1)^2 square around each pixel, NaN ignored (NaN where the square holds no value)."""
    grid = np.asarray(grid, dtype=np.float64)
    if radius == 0:
        return grid.copy()
    size = 2 * radius + 1
    valid = np.isfinite(grid)
    if how == "max":
        out = ndimage.maximum_filter(np.where(valid, grid, -np.inf), size=size, mode="constant", cval=-np.inf)
        return np.where(np.isfinite(out), out, np.nan)
    if how == "mean":
        total = ndimage.uniform_filter(np.where(valid, grid, 0.0), size=size, mode="constant", cval=0.0)
        count = ndimage.uniform_filter(valid.astype(np.float64), size=size, mode="constant", cval=0.0)
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.where(count > 1e-9, total / np.where(count > 1e-9, count, 1.0), np.nan)
    raise ValueError(f"unknown neighbourhood statistic {how!r}")


def clim_logit(clim) -> np.ndarray:
    p = np.clip(np.asarray(clim, dtype=np.float64), CLIM_FLOOR, 1.0 - CLIM_FLOOR)
    return np.log(p / (1.0 - p))


def predictors(fields: dict[str, np.ndarray], names: tuple[str, ...], threshold, clim, *, percentile: bool) -> np.ndarray:
    """(n, len(names) + 1 [+ 1]) predictor matrix: log1p(field) - log1p(t) per named field, the climatological log-odds,
    and log1p(t) for a percentile threshold (a fixed threshold makes it a constant)."""
    log_t = np.log1p(np.asarray(threshold, dtype=np.float64))
    columns = [np.log1p(np.maximum(np.asarray(fields[n], dtype=np.float64), 0.0)) - log_t for n in names]
    columns.append(clim_logit(clim))
    if percentile:
        columns.append(np.broadcast_to(log_t, columns[0].shape))
    return np.column_stack(columns)


@dataclass(frozen=True)
class LogisticModel:
    coef: np.ndarray            # (k + 1,) intercept first, on standardised predictors
    mean: np.ndarray
    scale: np.ndarray
    n: int
    n_events: int
    log_loss: float

    def to_dict(self) -> dict:
        return {"coef": self.coef.tolist(), "mean": self.mean.tolist(), "scale": self.scale.tolist(), "n": self.n,
                "n_events": self.n_events, "log_loss": self.log_loss}

    @classmethod
    def from_dict(cls, data: dict) -> "LogisticModel":
        return cls(coef=np.asarray(data["coef"], dtype=np.float64), mean=np.asarray(data["mean"], dtype=np.float64),
                   scale=np.asarray(data["scale"], dtype=np.float64), n=int(data["n"]), n_events=int(data["n_events"]),
                   log_loss=float(data["log_loss"]))


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 0.5 * (1.0 + np.tanh(0.5 * z))


def fit_logistic(x: np.ndarray, y: np.ndarray, *, ridge: float = 1e-6, max_iter: int = 50, tol: float = 1e-9,
                 chunk: int = 250_000) -> LogisticModel:
    """Logistic regression by Newton iterations on standardised predictors, ridge `ridge` x n on the slopes (not the
    intercept). The gradient and Hessian are summed over row chunks so a fit on millions of pixel-days stays small in
    memory. Rows with a NaN predictor must be removed by the caller."""
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    n, k = x.shape
    mean, scale = x.mean(axis=0), x.std(axis=0)
    scale = np.where(scale > 1e-12, scale, 1.0)
    base = np.clip(y.mean(), 1e-9, 1 - 1e-9)
    coef = np.zeros(k + 1)
    coef[0] = np.log(base / (1 - base))
    penalty = np.full(k + 1, ridge * n)
    penalty[0] = 0.0

    def chunks():
        for start in range(0, n, chunk):
            block = np.column_stack([np.ones(min(chunk, n - start)), (x[start:start + chunk] - mean) / scale])
            yield block, y[start:start + chunk]
    for _ in range(max_iter):
        gradient, hessian = -penalty * coef, np.diag(penalty)
        for block, target in chunks():
            p = _sigmoid(block @ coef)
            gradient += block.T @ (target - p)
            hessian += (block.T * (p * (1 - p))) @ block
        step = np.linalg.solve(hessian, gradient)
        coef = coef + step
        if np.max(np.abs(step)) < tol:
            break
    total = 0.0
    for block, target in chunks():
        p = np.clip(_sigmoid(block @ coef), 1e-15, 1 - 1e-15)
        total += float(np.sum(target * np.log(p) + (1 - target) * np.log(1 - p)))
    return LogisticModel(coef=coef, mean=mean, scale=scale, n=int(n), n_events=int(y.sum()), log_loss=-total / n)


def predict_logistic(model: LogisticModel, x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    z = model.coef[0] + ((x - model.mean) / model.scale) @ model.coef[1:]
    return np.where(np.isfinite(x).all(axis=1), _sigmoid(z), np.nan)


def warning_levels(probs: dict[str, np.ndarray]) -> np.ndarray:
    """Level code per pixel (0 none .. 3 red, -1 unavailable where any probability is NaN), first matching rule wins."""
    stack = {name: np.asarray(probs[name], dtype=np.float64) for name in THRESHOLDS}
    shape = next(iter(stack.values())).shape
    level = np.zeros(shape, dtype=np.int8)
    for code, conditions in reversed(LEVEL_RULES):
        hit = np.zeros(shape, dtype=bool)
        for name, minimum in conditions:
            hit |= stack[name] >= minimum
        level[hit] = code
    missing = np.zeros(shape, dtype=bool)
    for values in stack.values():
        missing |= ~np.isfinite(values)
    level[missing] = LEVEL_UNAVAILABLE
    return level
