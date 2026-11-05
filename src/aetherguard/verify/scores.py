"""Event-based detection and alert precision of published levels, with bootstrap confidence intervals.

Everything is scored at one alert threshold `min_level`: an alert is any cell-day with `levels >= min_level`, whether or
not its row is scored (a held alert on an unscored row is still an alert a user would see).

* probability of detection (`pod`): the share of events (`Match.event_level`) whose highest level reached `min_level`. An
  event the panel had no view of (`event_level == -1`) counts as an event and as a miss;
* precision: the share of alert cell-days that an event lies within tolerance of (`Match.alert_verified`).

Confidence intervals are percentile bootstraps. Days are the resampling unit for cell-day counts and precision, because
the cells of one day are not independent (one storm alerts many of them), and events are the unit for POD. `paired_change`
resamples the same days for two level sets, together with the events of those days, so the change between them is
compared like for like.
"""
from __future__ import annotations

import math
from typing import Iterator

import numpy as np

from ..live.backtest import BOOTSTRAP
from .matching import Match

CHUNK_CELLS = 2_000_000  # replicate x day weights held at once, which bounds the bootstrap's memory


def _ratio(numerator: float, denominator: float) -> float:
    return float(numerator) / float(denominator) if denominator else math.nan


def _difference(a: float, b: float) -> float:
    return a - b if not (math.isnan(a) or math.isnan(b)) else math.nan


def _check(levels: np.ndarray, scored: np.ndarray, m: Match) -> tuple[np.ndarray, np.ndarray]:
    levels, scored = np.asarray(levels), np.asarray(scored, dtype=bool)
    if levels.shape != scored.shape or levels.shape != m.alert_verified.shape:
        raise ValueError(
            f"levels {levels.shape}, scored {scored.shape} and alert_verified {m.alert_verified.shape} must share one shape"
        )
    return levels, scored


def _interval(values: np.ndarray, level: float) -> list[float]:
    values = values[np.isfinite(values)]
    if not len(values):
        return [math.nan, math.nan]
    tail = 100.0 * (1.0 - level) / 2.0
    lo, hi = np.percentile(values, [tail, 100.0 - tail])
    return [float(lo), float(hi)]


def _day_weights(rng: np.random.Generator, n_days: int, boot: dict) -> Iterator[np.ndarray]:
    """Blocks of bootstrap replicates (rows) of how many times each of `n_days` days was drawn (columns)."""
    block = max(1, CHUNK_CELLS // n_days)
    done = 0
    while done < boot["n"]:
        rows = min(block, boot["n"] - done)
        drawn = rng.integers(0, n_days, (rows, n_days)) + (np.arange(rows) * n_days)[:, None]
        yield np.bincount(drawn.ravel(), minlength=rows * n_days).reshape(rows, n_days)
        done += rows


def _per_day(levels: np.ndarray, m: Match, min_level: int) -> tuple[np.ndarray, np.ndarray]:
    alert = levels >= min_level
    return alert.sum(axis=0), (alert & m.alert_verified).sum(axis=0)


def level_scores(levels: np.ndarray, scored: np.ndarray, m: Match, min_level: int) -> dict:
    """Detection and precision of `levels` (cells x days) at `min_level` against the matched events `m`.

    `alert_share` is alert cell-days over scored cell-days, and its numerator includes alerts on unscored rows (held
    levels), unlike `baselines.realised_shares`, which counts scored rows only.
    """
    levels, scored = _check(levels, scored, m)
    alert = levels >= min_level
    alert_cell_days = int(alert.sum())
    verified = int((alert & m.alert_verified).sum())
    events = int(len(m.event_level))
    hits = int((m.event_level >= min_level).sum())
    return {
        "events": events,
        "hits": hits,
        "pod": _ratio(hits, events),
        "alert_cell_days": alert_cell_days,
        "verified_alert_cell_days": verified,
        "precision": _ratio(verified, alert_cell_days),
        "alert_share": _ratio(alert_cell_days, scored.sum()),
        "events_per_1000_alert_cell_days": _ratio(1000 * hits, alert_cell_days),
    }


def bootstrap_scores(levels: np.ndarray, scored: np.ndarray, m: Match, min_level: int, boot: dict = BOOTSTRAP) -> dict:
    """`level_scores` plus percentile intervals: `pod_ci` resamples events, `precision_ci` and `alert_cell_days_ci` days.

    A replicate whose drawn days hold no alert has no precision, so it is dropped from `precision_ci`; the number kept is
    `precision_ci_replicates` (of `boot["n"]`), which shows how thin the interval is when alerts are rare.
    """
    out = level_scores(levels, scored, m, min_level)
    rng = np.random.default_rng(boot["seed"])
    n_days = np.shape(levels)[1]
    alerts, verified = _per_day(np.asarray(levels), m, min_level)
    if n_days:
        alert_reps, verified_reps = [], []
        for weights in _day_weights(rng, n_days, boot):
            alert_reps.append(weights @ alerts)
            verified_reps.append(weights @ verified)
        alert_reps, verified_reps = np.concatenate(alert_reps), np.concatenate(verified_reps)
        with np.errstate(invalid="ignore", divide="ignore"):
            precision_reps = verified_reps / alert_reps
        out["alert_cell_days_ci"] = _interval(alert_reps.astype(np.float64), boot["level"])
        out["precision_ci"] = _interval(precision_reps, boot["level"])
        out["precision_ci_replicates"] = int(np.isfinite(precision_reps).sum())
    else:
        out["alert_cell_days_ci"] = out["precision_ci"] = [math.nan, math.nan]
        out["precision_ci_replicates"] = 0
    hit = m.event_level >= min_level
    if len(hit):
        pod_reps = hit[rng.integers(0, len(hit), (boot["n"], len(hit)))].mean(axis=1)
        out["pod_ci"] = _interval(pod_reps, boot["level"])
    else:
        out["pod_ci"] = [math.nan, math.nan]
    return out


def grouped_pod(event_level: np.ndarray, groups: np.ndarray, min_level: int, boot: dict = BOOTSTRAP) -> dict:
    """Detection of groups of events (records of one slide): a group is detected when any member reached `min_level`.

    `groups` labels each event of `event_level` (`Match.event_level`); the interval resamples the groups.
    """
    event_level, groups = np.asarray(event_level), np.asarray(groups)
    if groups.shape != event_level.shape:
        raise ValueError(f"groups {groups.shape} must label each of the {event_level.shape} events")
    labels, inverse = np.unique(groups, return_inverse=True)
    detected = np.zeros(len(labels), dtype=bool)
    np.logical_or.at(detected, inverse, event_level >= min_level)
    out = {"groups": int(len(labels)), "group_hits": int(detected.sum()), "group_pod": _ratio(detected.sum(), len(labels))}
    if len(labels):
        rng = np.random.default_rng(boot["seed"])
        out["group_pod_ci"] = _interval(detected[rng.integers(0, len(labels), (boot["n"], len(labels)))].mean(axis=1), boot["level"])
    else:
        out["group_pod_ci"] = [math.nan, math.nan]
    return out


def paired_change(
    levels_a: np.ndarray,
    levels_b: np.ndarray,
    scored: np.ndarray,
    m_a: Match,
    m_b: Match,
    min_level: int,
    boot: dict = BOOTSTRAP,
) -> dict:
    """Change from `levels_b` to `levels_a` (a minus b) in alert cell-days, hits and precision, each with a `_ci`.

    Both level sets must be matched against the same events, so each replicate draws the same days for a and b and takes
    the events of those days (every event once per draw of its day) for both.
    """
    levels_a, scored = _check(levels_a, scored, m_a)
    levels_b, _ = _check(levels_b, scored, m_b)
    if m_a.event_day is None or m_b.event_day is None:
        raise ValueError("paired_change needs Match.event_day, which match() provides")
    if not np.array_equal(m_a.event_day, m_b.event_day):
        raise ValueError("m_a and m_b must be matched against the same events")
    n_days = levels_a.shape[1]
    alerts_a, verified_a = _per_day(levels_a, m_a, min_level)
    alerts_b, verified_b = _per_day(levels_b, m_b, min_level)
    hit_a, hit_b = m_a.event_level >= min_level, m_b.event_level >= min_level
    hits_a, hits_b = int(hit_a.sum()), int(hit_b.sum())
    precision_a = _ratio(verified_a.sum(), alerts_a.sum())
    precision_b = _ratio(verified_b.sum(), alerts_b.sum())
    out = {
        "alert_cell_days_change": int(alerts_a.sum() - alerts_b.sum()),
        "hits_change": hits_a - hits_b,
        "precision_change": _difference(precision_a, precision_b),
    }
    if not n_days:
        for key in ("alert_cell_days_change", "hits_change", "precision_change"):
            out[f"{key}_ci"] = [math.nan, math.nan]
        return out
    rng = np.random.default_rng(boot["seed"])
    alert_reps, hits_reps, precision_reps = [], [], []
    for weights in _day_weights(rng, n_days, boot):
        alert_reps.append(weights @ (alerts_a - alerts_b))
        hits_reps.append(weights[:, m_a.event_day] @ (hit_a.astype(np.int64) - hit_b.astype(np.int64)))
        with np.errstate(invalid="ignore", divide="ignore"):
            precision_reps.append((weights @ verified_a) / (weights @ alerts_a) - (weights @ verified_b) / (weights @ alerts_b))
    for key, reps in (
        ("alert_cell_days_change", alert_reps),
        ("hits_change", hits_reps),
        ("precision_change", precision_reps),
    ):
        out[f"{key}_ci"] = _interval(np.concatenate(reps).astype(np.float64), boot["level"])
    return out
