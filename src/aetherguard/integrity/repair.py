"""Repair of flagged, non-retained readings from the independent references, with an uncertainty band.

`repaired` is the weighted median of the available references (imd, chirps_aligned, wide-neighbour idw); the
weight of a source is proportional to 1 / MAE of that source against the true value on the calibration (VAL)
clean days. The band is repaired + the 10th / 90th percentile of the empirical residual (truth - ensemble) on
those clean days, stratified by 3 bins of the ensemble value (< 1 mm, 1-10 mm, >= 10 mm; a bin with fewer than
30 residuals uses the pooled quantiles), clipped at 0 mm. NaN where no reference is available. The original
reading is never altered: repair is a separate set of columns.
"""
from __future__ import annotations

import json

import numpy as np

SOURCES = ("imd", "chirps_aligned", "neighbours")
BIN_EDGES = (1.0, 10.0)
QUANTILES = (0.1, 0.9)
MIN_BIN_SIZE = 30


def weighted_median(values: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """Column-wise weighted median of (k, n) values; NaN values carry no weight; NaN where none is valid.

    The lower weighted median: the smallest value whose cumulative weight reaches half of the total."""
    valid = np.isfinite(values)
    w = np.where(valid, weights, 0.0)
    order = np.argsort(np.where(valid, values, np.inf), axis=0, kind="stable")
    sorted_v = np.take_along_axis(values, order, axis=0)
    cum = np.cumsum(np.take_along_axis(w, order, axis=0), axis=0)
    total = cum[-1]
    pick = (cum >= 0.5 * total[None, :] - 1e-12).argmax(axis=0)
    out = sorted_v[pick, np.arange(values.shape[1])]
    return np.where(total > 0, out, np.nan)


def _bin(ensemble: np.ndarray) -> np.ndarray:
    return np.digitize(ensemble, BIN_EDGES)


class Repairer:
    def __init__(self, weights: dict[str, float], quantiles: dict[str, list[float]], n_fit: int, mae: dict) -> None:
        self.weights, self.quantiles, self.n_fit, self.mae = weights, quantiles, n_fit, mae

    @classmethod
    def fit(cls, truth, refs: dict) -> "Repairer":
        """Fit weights and residual quantiles on calibration clean days (`truth` and the reference arrays)."""
        truth = np.asarray(truth, dtype=np.float64)
        mae = {}
        for name in SOURCES:
            ref = np.asarray(refs[name], dtype=np.float64)
            both = np.isfinite(truth) & np.isfinite(ref)
            if not both.any():
                raise ValueError(f"no calibration days with both the truth and the {name} reference")
            mae[name] = float(np.abs(truth[both] - ref[both]).mean())
        inverse = {n: 1.0 / max(m, 1e-6) for n, m in mae.items()}
        total = sum(inverse.values())
        weights = {n: v / total for n, v in inverse.items()}
        ensemble = cls._ensemble(refs, weights)
        ok = np.isfinite(truth) & np.isfinite(ensemble)
        residual = truth[ok] - ensemble[ok]
        bins = _bin(ensemble[ok])
        pooled = np.quantile(residual, QUANTILES)
        quantiles = {"pooled": [float(v) for v in pooled]}
        for b in range(len(BIN_EDGES) + 1):
            part = residual[bins == b]
            quantiles[str(b)] = [float(v) for v in (np.quantile(part, QUANTILES) if len(part) >= MIN_BIN_SIZE else pooled)]
        return cls(weights, quantiles, int(ok.sum()), mae)

    @staticmethod
    def _ensemble(refs: dict, weights: dict) -> np.ndarray:
        values = np.stack([np.asarray(refs[n], dtype=np.float64) for n in SOURCES])
        w = np.array([weights[n] for n in SOURCES])[:, None] * np.ones_like(values)
        return weighted_median(values, w)

    def ensemble(self, refs: dict) -> np.ndarray:
        return self._ensemble(refs, self.weights)

    def repair(self, refs: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """(repaired, lo, hi); NaN where no reference is available."""
        ens = self.ensemble(refs)
        lo_q = np.array([self.quantiles[str(b)][0] for b in range(len(BIN_EDGES) + 1)])
        hi_q = np.array([self.quantiles[str(b)][1] for b in range(len(BIN_EDGES) + 1)])
        bins = np.where(np.isfinite(ens), _bin(np.nan_to_num(ens)), 0)
        lo = np.where(np.isfinite(ens), np.maximum(ens + lo_q[bins], 0.0), np.nan)
        hi = np.where(np.isfinite(ens), np.maximum(ens + hi_q[bins], 0.0), np.nan)
        return ens, lo, hi

    def to_json(self) -> dict:
        return {"weights": self.weights, "quantiles": self.quantiles, "n_fit": self.n_fit, "mae": self.mae,
                "bin_edges": list(BIN_EDGES)}

    @classmethod
    def from_json(cls, data: dict) -> "Repairer":
        return cls(data["weights"], data["quantiles"], data["n_fit"], data["mae"])

    def dumps(self) -> str:
        return json.dumps(self.to_json(), indent=1)
