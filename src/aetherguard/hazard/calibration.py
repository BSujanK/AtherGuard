"""Weighted monotone calibration, reliability tables and ECE (Phase 3b/3c).

The calibration population is the validation in-domain positives (weight 1 each) plus the validation universe
negatives (weights summing to the number of operating cell-days). A weighted isotonic regression of the 0/1 label
on the raw model score therefore estimates P(landslide on that cell-day) at the TRUE all-year base rate, a very
small number (of order 1e-6), which is why `risk_per_100k = 1e5 * P` is also reported.
"""
from __future__ import annotations

import json

import numpy as np
from sklearn.isotonic import IsotonicRegression


class MonotoneCalibrator:
    """Non-decreasing map raw score -> probability, stored as the isotonic thresholds (JSON-serialisable)."""

    def __init__(self, x_thresholds, y_thresholds) -> None:
        self.x = np.asarray(x_thresholds, dtype=np.float64)
        self.y = np.asarray(y_thresholds, dtype=np.float64)
        if self.x.ndim != 1 or self.x.shape != self.y.shape or len(self.x) == 0:
            raise ValueError("calibrator thresholds must be two equally long non-empty vectors")
        if (np.diff(self.x) < 0).any() or (np.diff(self.y) < 0).any():
            raise ValueError("calibrator thresholds must be non-decreasing")

    @classmethod
    def fit(cls, scores, labels, weights) -> "MonotoneCalibrator":
        scores = np.asarray(scores, dtype=np.float64)
        labels = np.asarray(labels, dtype=np.float64)
        weights = np.asarray(weights, dtype=np.float64)
        if not (scores.shape == labels.shape == weights.shape) or scores.ndim != 1:
            raise ValueError("scores, labels and weights must be equally long vectors")
        if not np.isfinite(scores).all():
            raise ValueError("calibration scores must be finite")
        if (weights <= 0).any() or not np.isfinite(weights).all():
            raise ValueError("calibration weights must be finite and positive")
        if not set(np.unique(labels)) <= {0.0, 1.0} or labels.sum() == 0:
            raise ValueError("calibration needs 0/1 labels with at least one positive")
        iso = IsotonicRegression(y_min=0.0, y_max=1.0, increasing=True, out_of_bounds="clip")
        iso.fit(scores, labels, sample_weight=weights)
        return cls(iso.X_thresholds_, iso.y_thresholds_)

    def predict(self, scores) -> np.ndarray:
        return np.interp(np.asarray(scores, dtype=np.float64), self.x, self.y)

    def to_dict(self) -> dict:
        return {"x_thresholds": self.x.tolist(), "y_thresholds": self.y.tolist()}

    @classmethod
    def from_dict(cls, payload: dict) -> "MonotoneCalibrator":
        return cls(payload["x_thresholds"], payload["y_thresholds"])


class RegionCalibrator:
    """Per-region monotone calibrators with the pooled calibrator as fallback (Stage A, v3).

    `by_region` holds one MonotoneCalibrator for each region that had at least `min_positives` out-of-fold positives;
    every other region, a missing region (NaN) and a region unseen at fit time are calibrated by `pooled`.
    """

    def __init__(self, by_region: dict[str, MonotoneCalibrator], pooled: MonotoneCalibrator,
                 min_positives: int = 25) -> None:
        if int(min_positives) < 1:
            raise ValueError("min_positives must be at least 1")
        self.by_region = dict(by_region)
        self.pooled = pooled
        self.min_positives = int(min_positives)

    def _row_regions(self, raw: np.ndarray, region) -> np.ndarray:
        if isinstance(region, str):
            return np.full(raw.shape[0], region, dtype=object)
        regions = np.asarray(region, dtype=object)
        if regions.shape != (raw.shape[0],):
            raise ValueError(f"region must be one name or one name per row ({raw.shape[0]}), got shape {regions.shape}")
        return regions

    def uses_pooled(self, region) -> np.ndarray:
        """Boolean per row: True where the pooled calibrator (not a region's own) is used."""
        regions = np.atleast_1d(np.asarray(region, dtype=object))
        own = np.zeros(regions.shape, dtype=bool)
        for name in self.by_region:
            own |= regions == name
        return ~own

    def predict(self, raw, region) -> np.ndarray:
        """Calibrated risk of `raw` scores (1-D, or 2-D with rows first) for per-row `region` names or one name."""
        raw = np.asarray(raw, dtype=np.float64)
        if raw.ndim == 0:
            raise ValueError("raw must have at least one dimension")
        regions = self._row_regions(raw, region)
        out = self.pooled.predict(raw)
        for name, calibrator in self.by_region.items():
            rows = regions == name
            if rows.any():
                out[rows] = calibrator.predict(raw[rows])
        return out

    def to_json(self) -> dict:
        return {"min_positives": self.min_positives, "pooled": self.pooled.to_dict(),
                "by_region": {name: c.to_dict() for name, c in sorted(self.by_region.items())}}

    @classmethod
    def from_json(cls, payload: dict | str) -> "RegionCalibrator":
        if isinstance(payload, str):
            payload = json.loads(payload)
        return cls({name: MonotoneCalibrator.from_dict(p) for name, p in payload["by_region"].items()},
                   MonotoneCalibrator.from_dict(payload["pooled"]), payload["min_positives"])


def reliability_table(risk, labels, weights, edges) -> list[dict]:
    """Weighted reliability table over bins of equal weighted population share.

    `edges` are increasing cumulative population shares from 0 to 1 (e.g. 0, .1, ..., 1 for deciles); rows with the
    same risk always fall in the same bin, so a bin can be empty and is then omitted. Per bin: population cell-days
    (sum of weights), positives, mean predicted risk and observed positive rate (positives / population).
    """
    risk = np.asarray(risk, dtype=np.float64)
    labels = np.asarray(labels, dtype=np.float64)
    weights = np.asarray(weights, dtype=np.float64)
    edges = np.asarray(edges, dtype=np.float64)
    if not (risk.shape == labels.shape == weights.shape) or edges[0] != 0.0 or edges[-1] != 1.0:
        raise ValueError("risk, labels and weights must align and edges must run from 0 to 1")
    order = np.argsort(risk, kind="stable")
    risk, labels, weights = risk[order], labels[order], weights[order]
    cumulative = np.cumsum(weights)
    total = cumulative[-1]
    group_start = np.concatenate(([True], risk[1:] != risk[:-1]))
    share_before = np.where(group_start, (cumulative - weights) / total, np.nan)
    share_before = _forward_fill(share_before)
    bins = np.searchsorted(edges[1:-1], share_before, side="right")
    rows = []
    for b in range(len(edges) - 1):
        mask = bins == b
        if not mask.any():
            continue
        population = float(weights[mask].sum())
        rows.append({"bin": b, "population_share": population / total, "population": population,
                     "positives": int(labels[mask].sum()),
                     "mean_risk": float(np.sum(weights[mask] * risk[mask]) / population),
                     "observed_rate": float(np.sum(weights[mask] * labels[mask]) / population),
                     "risk_min": float(risk[mask].min()), "risk_max": float(risk[mask].max())})
    return rows


def _forward_fill(values: np.ndarray) -> np.ndarray:
    index = np.where(~np.isnan(values), np.arange(len(values)), 0)
    np.maximum.accumulate(index, out=index)
    return values[index]


def expected_calibration_error(table: list[dict]) -> float:
    """Population-weighted mean absolute gap between mean predicted risk and observed rate over the bins."""
    return float(sum(row["population_share"] * abs(row["mean_risk"] - row["observed_rate"]) for row in table))


def decile_edges(n_bins: int) -> np.ndarray:
    return np.linspace(0.0, 1.0, n_bins + 1)
