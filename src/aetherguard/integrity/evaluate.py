"""Evaluation metrics for the sensor-integrity engine and its baselines.

All matrix arguments are days x stations (rows are consecutive days). Definitions:

* truth: a day is a positive of type T when `fault_type == T` (only days an injector CHANGED);
  a day is clean when it is a clean real day outside every episode window.
* recall_at_fpr: the threshold is chosen on the scored CLEAN days of the evaluated stations so that
  the false-flag rate is at most `fpr` (ties can make it lower; the achieved rate is returned).
  Boolean flags use no threshold and report (recall, achieved false-flag rate) instead. NaN scores
  mean "not scored": a NaN clean day is left out of the false-flag denominator, a NaN positive
  counts as a miss.
* detection_delay: days from an episode's first day to its first flagged (truth) day; NaN = missed.
* genuine-extreme retention: real extremes are clean, unflagged readings at or above the station's
  99.5th wet-day (>= 1 mm) percentile, computed per station on its own clean history (no train/test
  distinction: it labels real observations, nothing is learned from it), corroborated by at least 2
  valid neighbours reading >= 30% of the value. Retention = share NOT flagged.
* bootstrap_ci: percentile interval from resampling STATIONS with replacement (the threshold is held
  fixed at the one chosen on the full evaluation set).
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score

from . import neighbours
from .inject import FAULT_TYPES

EXTREME_PERCENTILE = 99.5
EXTREME_MIN_NEIGHBOURS = 2
EXTREME_NEIGHBOUR_FRAC = 0.3
WET_MM = 1.0
MIN_WET_DAYS = 100


@dataclass(frozen=True)
class FaultMatrices:
    """The long fault table as days x stations matrices (stations in `stations` order)."""
    stations: list[str]
    value_true: pd.DataFrame
    value_obs: pd.DataFrame
    fault_type: np.ndarray      # object, '' = none
    episode_id: np.ndarray      # int, -1 = none
    clean_real: np.ndarray      # bool
    clean: np.ndarray           # clean_real and outside every episode window
    real_flag: pd.DataFrame     # NOAA QFLAG letter or ''
    split_of: dict[str, str]


def to_matrices(table: pd.DataFrame) -> FaultMatrices:
    frame = table.assign(station=table["station"].astype(str), fault_type=table["fault_type"].astype(str))

    def wide(column):
        return frame.pivot(index="date", columns="station", values=column)

    obs, true, flags = wide("value_obs"), wide("value_true"), wide("real_flag")
    stations = list(obs.columns)
    fault = wide("fault_type").to_numpy(dtype=object)
    episode = wide("episode_id").to_numpy().astype(np.int64)
    clean_real = wide("clean_real").to_numpy().astype(bool)
    split_of = frame.drop_duplicates("station").set_index("station")["split"].astype(str).to_dict()
    return FaultMatrices(stations, true.astype(np.float32), obs.astype(np.float32), fault, episode,
                         clean_real, clean_real & (episode < 0), flags, split_of)


def operating_flags(score, clean_mask, fpr: float) -> tuple[np.ndarray, float | None]:
    """(flag array, threshold): boolean scores are flags as they are (threshold None); numeric
    scores are flagged above the threshold that gives at most `fpr` false flags on scored clean days."""
    s = np.asarray(score)
    clean = np.asarray(clean_mask, dtype=bool)
    if s.dtype == bool:
        return s, None
    if not 0 < fpr < 1:
        raise ValueError("fpr must be in (0, 1)")
    scored = np.isfinite(s)
    pool = s[clean & scored]
    if len(pool) == 0:
        raise ValueError("no scored clean days to set the threshold on")
    threshold = float(np.quantile(pool, 1 - fpr, method="higher"))
    with np.errstate(invalid="ignore"):
        return scored & (s > threshold), threshold


def recall_at_fpr(score, truth_type, clean_mask, fpr: float, fault_types: Sequence[str] = FAULT_TYPES) -> dict:
    """Per fault type recall at the false-flag rate `fpr` (see module doc)."""
    flag, threshold = operating_flags(score, clean_mask, fpr)
    s = np.asarray(score)
    truth = np.asarray(truth_type, dtype=object)
    clean = np.asarray(clean_mask, dtype=bool)
    scored = np.ones(s.shape, dtype=bool) if s.dtype == bool else np.isfinite(s)
    pool = clean & scored
    per_type = {}
    for name in fault_types:
        positive = truth == name
        n_pos = int(positive.sum())
        hit = int((flag & positive).sum())
        per_type[name] = {"recall": hit / n_pos if n_pos else float("nan"), "n_positive": n_pos,
                          "n_detected": hit, "n_unscored": int((positive & ~scored).sum())}
    recalls = [v["recall"] for v in per_type.values() if v["n_positive"]]
    return {"threshold": threshold, "achieved_fpr": float(flag[pool].mean()) if pool.any() else float("nan"),
            "n_clean_scored": int(pool.sum()), "n_clean": int(clean.sum()), "per_type": per_type,
            "macro_recall": float(np.mean(recalls)) if recalls else float("nan")}


def detection_delay(flag, episode_id, truth_mask=None) -> pd.DataFrame:
    """Per episode: `delay_days` (first flagged day minus first day of the episode; NaN = missed)
    and `detected`. With `truth_mask` only flags on those days count as detections."""
    flag = np.asarray(flag, dtype=bool)
    episode = np.asarray(episode_id)
    hit = flag if truth_mask is None else flag & np.asarray(truth_mask, dtype=bool)
    rows, cols = np.nonzero(episode >= 0)
    days = pd.DataFrame({"episode_id": episode[rows, cols], "row": rows, "col": cols, "hit": hit[rows, cols]})
    start = days.groupby("episode_id")["row"].min()
    first = days[days["hit"]].groupby("episode_id")["row"].min().reindex(start.index)
    out = pd.DataFrame({"episode_id": start.index.to_numpy(),
                        "station_col": days.groupby("episode_id")["col"].first().to_numpy(),
                        "delay_days": (first - start).to_numpy(dtype=float)})
    out["detected"] = out["delay_days"].notna()
    return out.reset_index(drop=True)


def episode_types(fault_type, episode_id) -> pd.Series:
    """Fault type of every episode (from its changed days), indexed by episode id."""
    fault = np.asarray(fault_type, dtype=object)
    episode = np.asarray(episode_id)
    hit = (fault != "") & (episode >= 0)
    return pd.Series(fault[hit], index=episode[hit]).groupby(level=0).first()


def pr_auc(score, positive, negative) -> float:
    """Average precision of `score` separating `positive` days from `negative` (clean) days; NaN when
    there are no positives. A NaN-scored negative is dropped, a NaN-scored positive ranks last."""
    s = np.asarray(score, dtype=float).ravel()
    pos = np.asarray(positive, dtype=bool).ravel()
    neg = np.asarray(negative, dtype=bool).ravel()
    if not pos.any():
        return float("nan")
    keep = (pos | neg) & (np.isfinite(s) | pos)
    s, y = s[keep], pos[keep]
    finite = np.isfinite(s)
    s[~finite] = (s[finite].min() - 1.0) if finite.any() else 0.0
    return float(average_precision_score(y, s))


def genuine_extremes(values: pd.DataFrame, eligible, table: pd.DataFrame, percentile: float = EXTREME_PERCENTILE,
                     min_neighbours: int = EXTREME_MIN_NEIGHBOURS, frac: float = EXTREME_NEIGHBOUR_FRAC,
                     min_wet_days: int = MIN_WET_DAYS) -> pd.DataFrame:
    """Boolean frame of the real, corroborated extreme readings (definition in the module doc)."""
    eligible = np.asarray(eligible, dtype=bool)
    data = values.to_numpy(np.float32)
    with np.errstate(invalid="ignore"):
        wet = eligible & (data >= WET_MM)
        limit = np.full(data.shape[1], np.inf)
        for j in np.flatnonzero(wet.sum(axis=0) >= min_wet_days):
            limit[j] = np.percentile(data[wet[:, j], j], percentile)
        extreme = eligible & (data >= limit[None, :])
        support = neighbours.neighbour_count(values, table, frac * data, strict=False).to_numpy()
    return pd.DataFrame(extreme & (support >= min_neighbours), index=values.index, columns=values.columns)


def retention_from_extremes(flag, extremes) -> dict:
    """Retention = share of the genuine extremes NOT flagged; numerator and denominator always given."""
    extremes = np.asarray(extremes, dtype=bool)
    flagged = np.asarray(flag, dtype=bool)
    denominator = int(extremes.sum())
    numerator = int((extremes & ~flagged).sum())
    return {"numerator": numerator, "denominator": denominator,
            "retention": numerator / denominator if denominator else float("nan"),
            "n_flagged": denominator - numerator}


def genuine_extreme_retention(flag, values: pd.DataFrame, table: pd.DataFrame, eligible, **kwargs) -> dict:
    """`retention_from_extremes` for the extremes `genuine_extremes(values, eligible, table)` finds."""
    return retention_from_extremes(flag, genuine_extremes(values, eligible, table, **kwargs).to_numpy())


def per_station_hits(hit, mask) -> list[np.ndarray]:
    """One array per station column: `hit` (as float 0/1) on the days where `mask` is True."""
    hit = np.asarray(hit)
    mask = np.asarray(mask, dtype=bool)
    return [hit[mask[:, j], j].astype(float) for j in range(hit.shape[1])]


def bootstrap_ci(per_station: Sequence[np.ndarray], statistic: Callable = np.mean, n_boot: int = 1000,
                 seed: int = 0, level: float = 0.95) -> tuple[float, float]:
    """Percentile CI of `statistic(concatenated observations)` over stations resampled with
    replacement. Stations with no observations are left out of the resample; NaN when none remain."""
    groups = [np.asarray(g, dtype=float) for g in per_station if len(g)]
    if not groups:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    draws = []
    for _ in range(n_boot):
        pick = rng.integers(0, len(groups), len(groups))
        draws.append(statistic(np.concatenate([groups[i] for i in pick])))
    draws = np.asarray(draws, dtype=float)
    if not np.isfinite(draws).any():
        return float("nan"), float("nan")
    lo, hi = np.nanpercentile(draws, [50 * (1 - level), 50 * (1 + level)])
    return float(lo), float(hi)
