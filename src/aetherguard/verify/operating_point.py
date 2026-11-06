"""Region x month alert thresholds that keep v3's detection with the fewest alerts (spec W2).

A stratum is the region of a cell and the month of a day. For every stratum and candidate threshold t, `stratum_curves`
counts the hits (events whose own-cell risk on the event day reaches t) and the alerts (alert-universe cell-days at or above
t). `allocate` chooses one threshold per stratum to maximise the total of hits - lambda * alerts, with lambda the largest
for which the total hits still reach a target: the optimal allocation equalises the marginal hits per alert across strata.
`monotone` then keeps the thresholds of one stratum from decreasing from Watch to Warning to Emergency.

Everything here is a function of arrays; the panels and events are assembled elsewhere.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

Stratum = tuple[str, int]

_LAMBDA_FLOOR = 1e-12     # below this lambda no realistic alert count outweighs one hit
_LAMBDA_RELATIVE_TOL = 1e-12
_MAX_BISECTIONS = 100


def stratum_curves(
    risk: np.ndarray,
    region: np.ndarray,
    month: np.ndarray,
    universe: np.ndarray,
    events: pd.DataFrame,
    candidates: np.ndarray,
) -> dict[Stratum, dict]:
    """Hits and alerts at every candidate threshold, for each (region, month) stratum of the panel.

    `risk` is cells x days; `region` holds the region of each cell, `month` the month of each day, and `universe` marks the
    cells whose cell-days count as alerts. `events` has integer columns `row` (cell index) and `col` (day index) into
    `risk`; repeated rows are one event. Events count in every cell, whether or not it is in the universe. A NaN risk
    never hits and never alerts.

    Each stratum maps to `thresholds` (the `candidates`, as given), `hits` and `alerts`, one entry per candidate. Both
    counts are non-increasing when the candidates ascend.
    """
    risk = np.asarray(risk, dtype=np.float64)
    region, month = np.asarray(region), np.asarray(month)
    universe = np.asarray(universe, dtype=bool)
    candidates = np.asarray(candidates, dtype=np.float64)
    if risk.ndim != 2:
        raise ValueError(f"risk must be cells x days, got shape {risk.shape}")
    n_cells, n_days = risk.shape
    if region.shape != (n_cells,) or universe.shape != (n_cells,):
        raise ValueError(f"region {region.shape} and universe {universe.shape} must have one entry per cell ({n_cells})")
    if month.shape != (n_days,):
        raise ValueError(f"month {month.shape} must have one entry per day ({n_days})")
    if candidates.ndim != 1:
        raise ValueError(f"candidates must be one-dimensional, got shape {candidates.shape}")
    rows, cols = _event_positions(events, n_cells, n_days)

    event_risk, event_region, event_month = risk[rows, cols], region[rows], month[cols]
    curves: dict[Stratum, dict] = {}
    for r in np.unique(region):
        for m in np.unique(month):
            in_stratum = event_region == r
            in_stratum &= event_month == m
            alert_risk = risk[np.ix_((region == r) & universe, month == m)]
            curves[(str(r), int(m))] = {
                "thresholds": candidates,
                "hits": _count_at_or_above(event_risk[in_stratum], candidates),
                "alerts": _count_at_or_above(alert_risk.ravel(), candidates),
            }
    return curves


def _event_positions(events: pd.DataFrame, n_cells: int, n_days: int) -> tuple[np.ndarray, np.ndarray]:
    missing = {"row", "col"} - set(events.columns)
    if missing:
        raise ValueError(f"events lack the columns {sorted(missing)}")
    events = events[["row", "col"]].drop_duplicates()
    rows, cols = events["row"].to_numpy(dtype=np.int64), events["col"].to_numpy(dtype=np.int64)
    if ((rows < 0) | (rows >= n_cells)).any() or ((cols < 0) | (cols >= n_days)).any():
        raise ValueError(f"events lie outside the panel of {n_cells} cells x {n_days} days")
    return rows, cols


def _count_at_or_above(values: np.ndarray, candidates: np.ndarray) -> np.ndarray:
    """For each candidate, how many of `values` are at or above it; NaN values count for none."""
    finite = np.sort(values[~np.isnan(values)])
    return len(finite) - np.searchsorted(finite, candidates, side="left")


def allocate(curves: dict[Stratum, dict], target_hits: int) -> dict[Stratum, float | None]:
    """One threshold per stratum maximising the total of hits - lambda * alerts, with lambda the largest keeping hits up.

    Each stratum picks its own best candidate for a given lambda (the highest threshold among equally good ones, which
    alerts least). The total hits of these picks never rise with lambda, so lambda is bisected, on a log scale, to the
    largest value for which the total hits are still at least `target_hits`, and the picks at that lambda are returned.

    A stratum in which no event can be hit (no events, or none with a finite risk) maps to None: it keeps v3's threshold and
    adds nothing to the hits. `target_hits` is therefore a total over the strata that do get a threshold. A target that even
    lambda = 0, the lowest candidates, cannot reach raises ValueError.
    """
    if target_hits < 0:
        raise ValueError(f"target_hits must not be negative, got {target_hits}")
    active = {s: c for s, c in curves.items() if np.max(c["hits"], initial=0) > 0}
    result: dict[Stratum, float | None] = {s: None for s in curves}
    if not active:
        if target_hits > 0:
            raise ValueError(f"no stratum has an event to hit, so {target_hits} hits cannot be reached")
        return result

    def pick(lam: float) -> dict[Stratum, int]:
        picks = {}
        for s, c in active.items():
            objective = np.asarray(c["hits"], dtype=np.float64) - lam * np.asarray(c["alerts"], dtype=np.float64)
            picks[s] = len(objective) - 1 - int(np.argmax(objective[::-1]))
        return picks

    def total_hits(picks: dict[Stratum, int]) -> int:
        return int(sum(active[s]["hits"][i] for s, i in picks.items()))

    best = total_hits(pick(0.0))
    if best < target_hits:
        raise ValueError(f"target of {target_hits} hits is out of reach: the lowest thresholds give {best}")
    # Above this lambda one alert costs more than every hit, so each stratum alerts as little as it can.
    high = float(sum(np.max(c["hits"]) for c in active.values())) + 1.0
    low = _LAMBDA_FLOOR
    if total_hits(pick(high)) >= target_hits:
        chosen = pick(high)
    elif total_hits(pick(low)) < target_hits:
        chosen = pick(0.0)
    else:
        for _ in range(_MAX_BISECTIONS):
            if high / low - 1.0 < _LAMBDA_RELATIVE_TOL:
                break
            mid = float(np.sqrt(low * high))
            if total_hits(pick(mid)) >= target_hits:
                low = mid
            else:
                high = mid
        chosen = pick(low)
    for s, i in chosen.items():
        result[s] = float(active[s]["thresholds"][i])
    return result


def monotone(by_level: dict[int, dict[Stratum, float | None]]) -> dict[int, dict[Stratum, float | None]]:
    """Thresholds that do not decrease from level 1 (Watch) to 2 (Warning) to 3 (Emergency) within each stratum.

    A level below the highest threshold of the lower levels is raised to it. None (the stratum keeps v3's threshold) stays
    None and is skipped when comparing the other levels; monotonicity against v3's own thresholds is enforced when None is
    resolved to them (Task 2, `candidate_levels`). The input is not modified.
    """
    if set(by_level) != {1, 2, 3}:
        raise ValueError(f"by_level needs the levels 1, 2 and 3, got {sorted(by_level)}")
    strata = set(by_level[1])
    if any(set(by_level[level]) != strata for level in (2, 3)):
        raise ValueError("every level must hold thresholds for the same strata")
    out: dict[int, dict[Stratum, float | None]] = {level: {} for level in (1, 2, 3)}
    for s in by_level[1]:
        floor = -np.inf
        for level in (1, 2, 3):
            t = by_level[level][s]
            if t is not None:
                t = max(t, floor)
                floor = t
            out[level][s] = t
    return out
