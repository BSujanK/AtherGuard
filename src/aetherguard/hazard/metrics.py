"""Weighted detection metrics and the paired bootstrap used by the hazard evaluation (Phase 3c).

Population model: the evaluated set is the in-domain positive cell-days (each an event, weight 1) plus negatives
drawn uniformly from the operating population (candidate cells x all days), each carrying the number of
cell-days it stands for. An alert is `score >= threshold`. Then
  recall                 = share of positives alerted,
  false-alarm share (FA) = weighted share of the negative population alerted (alerted cell-days per cell-day).
A score of -inf means "never alert"; NaN scores are rejected (the caller decides how missing data scores).

Bootstrap: positives are resampled as events (iid, with replacement); negatives are resampled iid with
replacement within each stratum (split-region), which keeps the stratum weight constant, so a resample is a
vector of multiplicities over the original rows. All scorings of the same rows share one resample per draw, so
differences between models are paired.
"""
from __future__ import annotations

import math

import numpy as np


def _as_scores(values, name: str) -> np.ndarray:
    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 1:
        raise ValueError(f"{name} must be one-dimensional")
    if np.isnan(array).any():
        raise ValueError(f"{name} contains NaN scores; map missing data to -inf (never alert) before scoring")
    return array


def _recall_rank(recall: float, n_positives: int) -> int:
    """Number of positives that must be alerted to reach `recall` (at least one)."""
    if not 0.0 < recall <= 1.0:
        raise ValueError(f"recall must be in (0, 1], got {recall}")
    return max(1, math.ceil(recall * n_positives - 1e-9))


class ScoreSet:
    """One scoring of a fixed set of positives and weighted negatives, ready for repeated evaluation."""

    def __init__(self, pos_scores, neg_scores, neg_weights) -> None:
        self.pos = _as_scores(pos_scores, "positive scores")
        neg = _as_scores(neg_scores, "negative scores")
        weights = np.asarray(neg_weights, dtype=np.float64)
        if len(self.pos) == 0 or len(neg) == 0:
            raise ValueError("a score set needs at least one positive and one negative")
        if weights.shape != neg.shape or not np.isfinite(weights).all() or (weights <= 0).any():
            raise ValueError("negative weights must be finite, positive and one per negative score")
        self.order = np.argsort(-neg, kind="stable")
        self.neg_sorted = neg[self.order]
        self.w_sorted = weights[self.order]
        self._neg_ascending = -self.neg_sorted
        ends = np.append(np.flatnonzero(self.neg_sorted[1:] != self.neg_sorted[:-1]) + 1, len(neg))
        self.level_counts = ends                      # number of negatives with score >= each distinct level
        self.level_scores = self.neg_sorted[ends - 1]

    def count_ge(self, threshold: float) -> int:
        return int(np.searchsorted(self._neg_ascending, -threshold, side="right"))

    def cum_weights(self, multiplicity_sorted: np.ndarray | None = None) -> np.ndarray:
        """Cumulative negative weight in descending-score order, with a leading 0."""
        weights = self.w_sorted if multiplicity_sorted is None else self.w_sorted * multiplicity_sorted
        return np.concatenate(([0.0], np.cumsum(weights)))

    def threshold_for_recall(self, recall: float, pos_sorted_desc: np.ndarray | None = None) -> float:
        ps = np.sort(self.pos)[::-1] if pos_sorted_desc is None else pos_sorted_desc
        return float(ps[_recall_rank(recall, len(ps)) - 1])

    def threshold_for_fa(self, fa_share: float, cum0: np.ndarray | None = None) -> float:
        """Lowest score level whose alerted negative share is <= `fa_share` (+inf when even the top level exceeds it)."""
        cum = self.cum_weights() if cum0 is None else cum0
        shares = cum[self.level_counts] / cum[-1]
        m = int(np.searchsorted(shares, fa_share, side="right"))
        return math.inf if m == 0 else float(self.level_scores[m - 1])

    @staticmethod
    def recall_at(pos_sorted_desc: np.ndarray, threshold: float) -> float:
        return float(np.searchsorted(-pos_sorted_desc, -threshold, side="right")) / len(pos_sorted_desc)

    def fa_at(self, threshold: float, cum0: np.ndarray | None = None) -> float:
        cum = self.cum_weights() if cum0 is None else cum0
        return float(cum[self.count_ge(threshold)] / cum[-1])

    def average_precision(self, pos_sorted_desc: np.ndarray, cum0: np.ndarray) -> float:
        """Step-wise weighted average precision (positives weight 1, negatives their weights)."""
        n_pos = len(pos_sorted_desc)
        ends = np.append(np.flatnonzero(pos_sorted_desc[1:] != pos_sorted_desc[:-1]), n_pos - 1)
        tp = ends + 1
        gained = np.diff(tp, prepend=0)
        counts = np.searchsorted(self._neg_ascending, -pos_sorted_desc[ends], side="right")
        fp = cum0[counts]
        return float(np.sum(gained / n_pos * tp / (tp + fp)))

    def metrics(self, pos_sorted_desc: np.ndarray, cum0: np.ndarray, recalls, fa_shares) -> dict[str, float]:
        out: dict[str, float] = {}
        for recall in recalls:
            out[f"fa_at_recall_{recall}"] = self.fa_at(self.threshold_for_recall(recall, pos_sorted_desc), cum0)
        for fa in fa_shares:
            out[f"recall_at_fa_{fa}"] = self.recall_at(pos_sorted_desc, self.threshold_for_fa(fa, cum0))
        out["pr_auc"] = self.average_precision(pos_sorted_desc, cum0)
        return out

    def point(self, recalls=(0.9,), fa_shares=(0.01,)) -> dict[str, float]:
        return self.metrics(np.sort(self.pos)[::-1], self.cum_weights(), recalls, fa_shares)


# ------------------------------------------------------------------------------------- scalar helpers

def threshold_for_recall(pos_scores, recall: float) -> float:
    """Highest threshold that still alerts at least `recall` of the positives."""
    ps = np.sort(_as_scores(pos_scores, "positive scores"))[::-1]
    return float(ps[_recall_rank(recall, len(ps)) - 1])


def threshold_for_fa_share(neg_scores, neg_weights, fa_share: float) -> float:
    """Lowest threshold whose weighted alerted share of the negatives is <= `fa_share`."""
    neg = _as_scores(neg_scores, "negative scores")
    return ScoreSet([0.0], neg, neg_weights).threshold_for_fa(fa_share)


def recall_at_threshold(pos_scores, threshold: float) -> float:
    return float(np.mean(_as_scores(pos_scores, "positive scores") >= threshold))


def fa_share_at_threshold(neg_scores, neg_weights, threshold: float) -> float:
    neg = _as_scores(neg_scores, "negative scores")
    weights = np.asarray(neg_weights, dtype=np.float64)
    return float(weights[neg >= threshold].sum() / weights.sum())


def fa_share_at_recall(pos_scores, neg_scores, neg_weights, recall: float) -> float:
    return ScoreSet(pos_scores, neg_scores, neg_weights).point([recall], [])[f"fa_at_recall_{recall}"]


def recall_at_fa_share(pos_scores, neg_scores, neg_weights, fa_share: float) -> float:
    return ScoreSet(pos_scores, neg_scores, neg_weights).point([], [fa_share])[f"recall_at_fa_{fa_share}"]


def weighted_pr_auc(pos_scores, neg_scores, neg_weights) -> float:
    return ScoreSet(pos_scores, neg_scores, neg_weights).point([], [])["pr_auc"]


# ----------------------------------------------------------------------------------------- bootstrap

def _validate_strata(weights: np.ndarray, strata: np.ndarray) -> list[np.ndarray]:
    groups = []
    for label in np.unique(strata):
        index = np.flatnonzero(strata == label)
        w = weights[index]
        if not np.allclose(w, w[0], rtol=1e-9, atol=0.0):
            raise ValueError(f"weights must be constant within a stratum (stratum {label!r}); the iid bootstrap "
                             "of universe rows is only valid for equally weighted draws")
        groups.append(index)
    return groups


def bootstrap_metrics(sets: dict[str, ScoreSet], neg_weights, strata, *, recalls, fa_shares, n_boot: int,
                      seed: int, fixed_thresholds: dict[str, dict[str, float]] | None = None
                      ) -> dict[str, dict[str, np.ndarray]]:
    """Per-resample metrics for every scoring in `sets` (all scoring the SAME rows in the SAME order).

    `neg_weights` / `strata` are in the original negative order. `fixed_thresholds[model][name]` adds
    `fixed_recall_<name>` and `fixed_fa_<name>` (a threshold chosen elsewhere, e.g. on validation, applied
    to each resample).
    """
    weights = np.asarray(neg_weights, dtype=np.float64)
    strata_array = np.asarray(strata)
    groups = _validate_strata(weights, strata_array)
    first = next(iter(sets.values()))
    n_pos, n_neg = len(first.pos), len(weights)
    for name, scoring in sets.items():
        if len(scoring.pos) != n_pos or len(scoring.neg_sorted) != n_neg:
            raise ValueError(f"scoring {name!r} does not cover the same rows as the others")
    fixed = fixed_thresholds or {}
    rng = np.random.default_rng(seed)
    out = {name: {} for name in sets}
    keys: dict[str, list[str]] = {}
    for name, scoring in sets.items():
        probe = scoring.point(recalls, fa_shares)
        keys[name] = list(probe) + [f"{kind}_{label}" for label in fixed.get(name, {}) for kind in ("fixed_recall", "fixed_fa")]
        for key in keys[name]:
            out[name][key] = np.empty(n_boot)
    for b in range(n_boot):
        pos_index = rng.integers(0, n_pos, n_pos)
        multiplicity = np.zeros(n_neg)
        for index in groups:
            multiplicity[index] = np.bincount(rng.integers(0, len(index), len(index)), minlength=len(index))
        for name, scoring in sets.items():
            ps = np.sort(scoring.pos[pos_index])[::-1]
            cum0 = scoring.cum_weights(multiplicity[scoring.order])
            values = scoring.metrics(ps, cum0, recalls, fa_shares)
            for label, threshold in fixed.get(name, {}).items():
                values[f"fixed_recall_{label}"] = scoring.recall_at(ps, threshold)
                values[f"fixed_fa_{label}"] = scoring.fa_at(threshold, cum0)
            for key, value in values.items():
                out[name][key][b] = value
    return out


def confidence_interval(samples, level: float = 0.95) -> tuple[float, float]:
    tail = (1.0 - level) / 2.0 * 100.0
    lo, hi = np.percentile(np.asarray(samples, dtype=np.float64), [tail, 100.0 - tail])
    return float(lo), float(hi)


def summarize(point: float, samples, level: float = 0.95) -> dict[str, float]:
    lo, hi = confidence_interval(samples, level)
    return {"value": float(point), "lo": lo, "hi": hi}


def paired_difference(a_samples, b_samples, a_point: float, b_point: float, level: float = 0.95) -> dict[str, float]:
    """b - a over paired resamples (for lower-is-better metrics a positive value favours `a`)."""
    diff = np.asarray(b_samples, dtype=np.float64) - np.asarray(a_samples, dtype=np.float64)
    lo, hi = confidence_interval(diff, level)
    return {"value": float(b_point - a_point), "lo": lo, "hi": hi, "share_a_better": float(np.mean(diff > 0)),
            "share_tied": float(np.mean(diff == 0))}


def verdict(lo: float, hi: float) -> str:
    """Whether a paired difference (b - a, lower-is-better metric) favours a, favours b, or is unresolved."""
    if lo > 0:
        return "a_better"
    if hi < 0:
        return "b_better"
    return "tie"



def recall_first_threshold(pos_scores, recall: float, n_boot: int, seed: int, percentile: float = 5.0) -> float:
    """Highest threshold whose bootstrap `percentile`-th percentile recall is at least `recall`.

    Positives are resampled as events with replacement `n_boot` times; for each candidate threshold (a distinct
    positive score) the recall of every resample is computed and its low percentile compared with the target. Alerts
    are `score >= threshold`, so tied positives are always alerted together. The lowest positive score always
    qualifies (recall 1), so a threshold exists.
    """
    if not 0.0 < recall <= 1.0:
        raise ValueError(f"recall must be in (0, 1], got {recall}")
    scores = np.sort(_as_scores(pos_scores, "positive scores"))[::-1]
    n = len(scores)
    if n == 0:
        raise ValueError("no positive scores")
    counts = np.random.default_rng(seed).multinomial(n, np.full(n, 1.0 / n), size=n_boot)
    recall_at_rank = np.cumsum(counts, axis=1) / n
    last_of_level = np.append(np.flatnonzero(scores[1:] != scores[:-1]), n - 1)
    low = np.percentile(recall_at_rank[:, last_of_level], percentile, axis=0)
    qualifies = np.flatnonzero(low >= recall - 1e-12)
    return float(scores[last_of_level[qualifies[0]]])


def bootstrap_se(samples) -> float:
    return float(np.std(np.asarray(samples, dtype=np.float64), ddof=1))
