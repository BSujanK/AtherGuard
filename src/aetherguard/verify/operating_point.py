"""Region x month alert thresholds that keep v3's detection with the fewest alerts (spec W2).

A stratum is the region of a cell and the month of a day. For every stratum and candidate threshold t, `stratum_curves`
counts the hits (events whose own-cell risk on the event day reaches t) and the alerts (alert-universe cell-days at or above
t). `allocate` chooses one threshold per stratum so that the total hits reach a target with the fewest total alerts,
exactly (a dynamic programme over the strata), which spends the alerts where they buy the most events.
`monotone` then keeps the thresholds of one stratum from decreasing from Watch to Warning to Emergency.

Everything here is a function of arrays; the panels and events are assembled elsewhere.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

Stratum = tuple[str, int]


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

    Each stratum maps to `thresholds` (a copy of the `candidates`, which must ascend), `hits` and `alerts`, one entry per
    candidate. Both counts are non-increasing.
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
    if candidates.ndim != 1 or not np.isfinite(candidates).all() or not (np.diff(candidates) >= 0).all():
        raise ValueError("candidates must be a one-dimensional, ascending array of finite thresholds")
    rows, cols = _event_positions(events, n_cells, n_days)

    event_risk, event_region, event_month = risk[rows, cols], region[rows], month[cols]
    curves: dict[Stratum, dict] = {}
    for r in np.unique(region):
        for m in np.unique(month):
            in_stratum = event_region == r
            in_stratum &= event_month == m
            alert_risk = risk[np.ix_((region == r) & universe, month == m)]
            curves[(str(r), int(m))] = {
                "thresholds": candidates.copy(),
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


@dataclass(frozen=True)
class Allocation:
    """The chosen thresholds and what they achieve over the strata that got one.

    `thresholds` maps every stratum to its threshold, or None where no event can be hit; `hits` and `alerts` are the totals
    of the strata that got a threshold.
    """

    thresholds: dict[Stratum, float | None]
    hits: int
    alerts: int


def allocate(curves: dict[Stratum, dict], target_hits: int) -> Allocation:
    """One candidate threshold per stratum, with the fewest total alerts among the choices whose total hits reach `target_hits`.

    Exact: a multiple-choice knapsack dynamic programme over the strata and the hit totals reachable (capped at the
    target), so neither the overshoot of the hits nor non-concave curves can cost alerts. Among the choices with the fewest
    alerts, the one with the higher thresholds (higher candidate index, summed over the strata) wins.

    A stratum in which no event can be hit (no events, none with a finite risk, or all below the lowest candidate) maps to
    None: it keeps v3's threshold and adds nothing to the hits. `target_hits` is therefore a total over the strata that do
    get a threshold. A target that even the lowest thresholds cannot reach raises ValueError.
    """
    if target_hits < 0:
        raise ValueError(f"target_hits must not be negative, got {target_hits}")
    target = int(target_hits)
    active = {}
    for stratum, curve in curves.items():
        hits = np.asarray(curve["hits"], dtype=np.int64)
        alerts = np.asarray(curve["alerts"], dtype=np.int64)
        thresholds = np.asarray(curve["thresholds"], dtype=np.float64)
        if not hits.shape == alerts.shape == thresholds.shape or hits.ndim != 1:
            raise ValueError(f"the thresholds, hits and alerts of {stratum} must be one-dimensional and of one length")
        if hits.max(initial=0) > 0:
            active[stratum] = (thresholds, hits, alerts)
    reachable = sum(int(h.max()) for _, h, _ in active.values())
    if reachable < target:
        raise ValueError(f"target of {target} hits is out of reach: the lowest thresholds give {reachable}")
    thresholds_out: dict[Stratum, float | None] = {s: None for s in curves}
    if not active:
        return Allocation(thresholds_out, 0, 0)

    # The cost of a choice is alerts * scale + (candidate steps below the top), so the cheapest total has the fewest
    # alerts and then the highest candidates; scale exceeds the summed penalties of any choice.
    scale = sum(len(t) for t, _, _ in active.values()) + 1
    unreachable = np.iinfo(np.int64).max // 4
    if sum(int(a.max()) for _, _, a in active.values()) * scale >= unreachable:
        raise ValueError("alert counts are too large for the allocation")

    cost = np.full(target + 1, unreachable, dtype=np.int64)
    cost[0] = 0
    steps = []  # per stratum: for every capped hit total, the candidate chosen and the total before it
    for thresholds, hits, alerts in active.values():
        best = np.full(target + 1, unreachable, dtype=np.int64)
        chosen = np.full(target + 1, -1, dtype=np.int64)
        before = np.full(target + 1, -1, dtype=np.int64)
        for i in range(len(thresholds)):
            step = int(alerts[i]) * scale + (len(thresholds) - 1 - i)
            reach = np.full(target + 1, unreachable, dtype=np.int64)
            came = np.full(target + 1, -1, dtype=np.int64)
            gain = int(hits[i])
            if gain < target:
                reach[gain:target] = cost[: target - gain] + step
                came[gain:target] = np.arange(target - gain)
                top = target - gain + int(np.argmin(cost[target - gain :]))
            else:
                top = int(np.argmin(cost))
            reach[target], came[target] = cost[top] + step, top
            reach = np.minimum(reach, unreachable)
            better = reach < best
            best[better], chosen[better], before[better] = reach[better], i, came[better]
        steps.append((chosen, before))
        cost = best

    if cost[target] >= unreachable:
        raise ValueError(f"target of {target} hits is out of reach")
    total, hits_done, alerts_done = target, 0, 0
    for (stratum, (thresholds, hits, alerts)), (chosen, before) in zip(reversed(list(active.items())), reversed(steps)):
        i = int(chosen[total])
        thresholds_out[stratum] = float(thresholds[i])
        hits_done, alerts_done = hits_done + int(hits[i]), alerts_done + int(alerts[i])
        total = int(before[total])
    return Allocation(thresholds_out, hits_done, alerts_done)


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
    if any(t is not None and np.isnan(t) for level in by_level.values() for t in level.values()):
        raise ValueError("thresholds must not be NaN")
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
