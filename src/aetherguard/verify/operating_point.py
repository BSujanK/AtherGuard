"""Region x month alert thresholds that keep v3's detection with the fewest alerts (spec W2).

A stratum is the region of a cell and the month of a day. For every stratum and candidate threshold t, `stratum_curves`
counts the hits (events whose own-cell risk on the event day reaches t) and the alerts (alert-universe cell-days at or above
t). `allocate` chooses one threshold per stratum so that the total hits reach a target with the fewest total alerts,
exactly (a dynamic programme over the strata), which spends the alerts where they buy the most events.
`monotone` then keeps the thresholds of one stratum from decreasing from Watch to Warning to Emergency.
`candidate_levels` turns such thresholds into the alert levels of a season panel: the section 11 chain of
`hardening_dev.season_levels` (rain cap, hold release, hysteresis) on raw levels from the stratum thresholds, with the
optional Emergency confirmation of candidate C2.

The rest turns this into the pre-declared study (`python -m aetherguard.verify operating-point`):

1. `fit` on the development seasons: per level, the stratum curves over the pooled seasons, the target (v3's point-level hits
   in the strata that can be hit at all) and `allocate`, then `monotone` across the levels. C1 uses the thresholds as they are;
   C2 adds the Emergency confirmation.
2. `development_table` runs v3, C1 and C2 through the whole chain, and `select` picks C1 or C2 on those numbers alone.
3. `evaluate_once` is the single look at the 2018-2025 held-out set: `score_heldout` measures v3 against the selected
   candidate, `decide` applies the adoption criterion of spec section 3 literally, and the result file it writes (and the
   committed report, `run` refuses when either exists) keep a second look from happening.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable, Iterable

import numpy as np
import pandas as pd

from ..alerts import levels as lv
from ..config import PROJECT_ROOT, data_root
from ..hazard import model as hm
from ..hazard.jsonio import dump_json, jsonable
from ..live import burden
from ..live import hardening as H
from ..live import hardening_dev as D
from ..live import postrules as pr
from ..live import precision_study as ps
from ..live import run as live_run
from ..live.backtest import BOOTSTRAP, SEASON_YEARS
from . import heldout, report
from .matching import match
from .report import LEVEL_NAMES, TOLERANCES, _pct, extract
from .scores import bootstrap_scores, grouped_pod, paired_change

Stratum = tuple[str, int]
LEVELS = (lv.WATCH, lv.WARNING, lv.EMERGENCY)
STRATUM_MONTHS = (6, 7, 8, 9)      # the months with thresholds of their own; October-December keep v3's
QUANTILES = np.linspace(0.5, 0.999, 200)           # candidate thresholds: v3 risk quantiles 50% to 99.9% in 200 steps
CANDIDATES = {"C1": False, "C2": True}             # name -> confirm_emergency
THRESHOLD_NAMES = {1: "watch", 2: "warning", 3: "emergency"}
REPORT_STEM = "phase7_operating_point"
REPORTS = PROJECT_ROOT / "reports"
ALLOWED_SLIDES_LOST = {1: 2, 2: 1, 3: 1}           # spec section 3: Watch+ by more than 2 slides, Warning+ and Emergency by more than 1


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


def candidate_levels(
    season: D.Season,
    thresholds: dict[int, dict[Stratum, float | None]],
    config,
    base_rules: pr.PostRules | None,
    confirm_emergency: bool,
    upper: str = "new_hi",
) -> np.ndarray:
    """Alert levels (cells x days) of a season under region x month thresholds, the rest of section 11 unchanged.

    `thresholds` maps the levels 1-3 to their threshold per (region, month) stratum, as `allocate` returns them. A cell-day
    whose stratum has no threshold (None, absent, or a month outside June-September) uses the v3 threshold of its region
    (`season.thresholds`); Watch <= Warning <= Emergency is then enforced on every cell-day (`monotone`), against the v3
    values where they were used. The raw level is the one of `season_levels`: the point level, raised to Watch where
    `uncertain_high` holds against the panel field `upper`.

    With `confirm_emergency` (candidate C2) a raw Emergency is published as Warning unless the raw level of the same cell
    the day before was at least Warning; the first day of the panel has no day before. The rain cap, hold release and
    hysteresis of `base_rules` follow as in `season_levels`, the hysteresis stepping down against the thresholds of the
    stratum of each day.
    """
    if set(thresholds) != set(LEVELS):
        raise ValueError(f"thresholds needs the levels 1, 2 and 3, got {sorted(thresholds)}")
    panel = season.panel
    row_thresholds = _cell_day_thresholds(season, thresholds)
    raw = lv.raw_level(panel["risk"], panel[upper], row_thresholds)[0]
    if confirm_emergency:
        warned_before = np.zeros(raw.shape, dtype=bool)
        warned_before[:, 1:] = raw[:, :-1] >= lv.WARNING
        raw = np.where((raw == lv.EMERGENCY) & ~warned_before, lv.WARNING, raw).astype(np.int8)
    return D.levels_from_raw(season, raw, config, base_rules, row_thresholds=row_thresholds)


def _cell_day_thresholds(season: D.Season, thresholds: dict[int, dict[Stratum, float | None]]) -> np.ndarray:
    """(cells, days, 3) watch / warning / emergency thresholds of every cell-day: its stratum's where it has one, else its
    region's v3 thresholds, non-decreasing across the levels. NaN for a cell whose region has no v3 thresholds (it never
    alerts, as in `season_levels`)."""
    panel = season.panel
    month = np.array([day.month for day in panel.days])
    resolved: dict[int, dict[Stratum, float | None]] = {level: {} for level in LEVELS}
    for region, v3 in season.thresholds.items():
        for m in np.unique(month):
            stratum = (region, int(m))
            for level in LEVELS:
                value = thresholds[level].get(stratum) if stratum[1] in STRATUM_MONTHS else None
                resolved[level][stratum] = float(v3.as_array()[level - 1]) if value is None else value
    resolved = monotone(resolved)
    out = np.full((*panel["risk"].shape, len(LEVELS)), np.nan)
    for region in season.thresholds:
        for m in np.unique(month):
            out[np.ix_(season.region == region, month == m)] = [resolved[level][(region, int(m))] for level in LEVELS]
    return out


# ------------------------------------------------------------------------------------- fit on development

def _season_arrays(season: D.Season) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, pd.DataFrame]:
    """(risk, region, month, universe, events) of a season from 1 June: risk is cells x days, `events` holds the distinct
    (cell, day) events as the integer `row` and `col` into it."""
    panel, first = season.panel, season.first
    days = pd.DatetimeIndex(pd.to_datetime(panel.days[first:]))
    ids = panel.cells["cell_id"].to_numpy(dtype=np.int64)
    events = season.events[["cell_id", "date"]].drop_duplicates()
    positions = pd.DataFrame({"row": pd.Index(ids).get_indexer(events["cell_id"].to_numpy(dtype=np.int64)),
                              "col": days.get_indexer(pd.DatetimeIndex(pd.to_datetime(events["date"])))})
    return (np.asarray(panel["risk"], dtype=np.float64)[:, first:], season.region, days.month.to_numpy(),
            panel.cells["in_universe"].to_numpy(dtype=bool), positions)


def candidate_grid(load: Callable[[], Iterable[D.Season]]) -> np.ndarray:
    """The candidate thresholds: `QUANTILES` of the risk over the scored cell-days of the universe cells of all seasons."""
    values = []
    for season in load():
        risk = np.asarray(season.panel["risk"], dtype=np.float64)[season.panel.cells["in_universe"].to_numpy(dtype=bool),
                                                                  season.first:]
        values.append(risk[np.isfinite(risk)])
    if not values:
        raise ValueError("no development seasons to take the candidate thresholds from")
    return np.quantile(np.concatenate(values), QUANTILES)


def _point_counts(risk, region, month, universe, events, v3: dict[str, lv.Thresholds], level: int) -> dict[Stratum, tuple[int, int]]:
    """Per stratum, the events and the universe cell-days whose risk reaches v3's threshold of `level` for the region."""
    rows, cols = events["row"].to_numpy(), events["col"].to_numpy()
    event_risk, event_region, event_month = risk[rows, cols], region[rows], month[cols]
    out = {}
    for r in np.unique(region):
        cut = float(v3[str(r)].as_array()[level - 1]) if str(r) in v3 else np.nan
        for m in np.unique(month):
            hit = (event_region == r) & (event_month == m) & (event_risk >= cut)
            alerts = risk[np.ix_((region == r) & universe, month == m)] >= cut
            out[(str(r), int(m))] = (int(hit.sum()), int(alerts.sum()))
    return out


@dataclass
class Fit:
    """What the development seasons give: the candidate thresholds (`grid`), the monotone thresholds of every level and
    stratum, per level the target hits, the `Allocation` before `monotone`, and v3's point-level hits and alerts over the
    strata that got a threshold."""

    grid: np.ndarray
    thresholds: dict[int, dict[Stratum, float | None]]
    targets: dict[int, int]
    allocations: dict[int, Allocation]
    v3_point: dict[int, dict[str, int]]


def fit(load: Callable[[], Iterable[D.Season]], grid: np.ndarray) -> Fit:
    """Region x month thresholds from the development seasons of `load()` (a fresh pass over them on every call).

    Per level L the hits and alerts of every stratum and candidate are summed over the seasons; the target is v3's point-level
    hits (own cell, event day, risk at or above the card threshold of the region, no rules) in the strata that can be hit at
    all, since the others keep v3's thresholds; `allocate` then finds the fewest alerts that keep that many hits, and
    `monotone` makes the three levels' thresholds of each stratum non-decreasing.
    """
    curves: dict[Stratum, dict] = {}
    point: dict[int, dict[Stratum, list[int]]] = {level: {} for level in LEVELS}
    for season in load():
        risk, region, month, universe, events = _season_arrays(season)
        for stratum, curve in stratum_curves(risk, region, month, universe, events, grid).items():
            total = curves.setdefault(stratum, {"thresholds": curve["thresholds"], "hits": 0, "alerts": 0})
            total["hits"], total["alerts"] = total["hits"] + curve["hits"], total["alerts"] + curve["alerts"]
        for level in LEVELS:
            for stratum, counts in _point_counts(risk, region, month, universe, events, season.thresholds, level).items():
                total = point[level].setdefault(stratum, [0, 0])
                total[0], total[1] = total[0] + counts[0], total[1] + counts[1]
    if not curves:
        raise ValueError("no development seasons to fit")
    active = [stratum for stratum, curve in curves.items() if curve["hits"].max() > 0]
    targets = {level: sum(point[level][s][0] for s in active) for level in LEVELS}
    v3_point = {level: {"hits": targets[level], "alerts": sum(point[level][s][1] for s in active)} for level in LEVELS}
    allocations = {level: allocate(curves, targets[level]) for level in LEVELS}
    thresholds = monotone({level: allocation.thresholds for level, allocation in allocations.items()})
    return Fit(np.asarray(grid, dtype=np.float64).copy(), thresholds, targets, allocations, v3_point)


def development_table(
    load: Callable[[], Iterable[D.Season]], models: dict[str, Callable[[D.Season], np.ndarray]]
) -> dict[str, dict[int, dict[str, int]]]:
    """Per model and level, over the seasons of `load()`: the distinct development `events`, the `hits` (events whose own cell
    has at least that level on the event day: cell-exact, so a lower bound of the tolerant detection) and the `alerts`
    (cell-days at or above the level, on the universe-sample cells). `models` map a season to its full-panel levels."""
    table = {name: {level: {"events": 0, "hits": 0, "alerts": 0} for level in LEVELS} for name in models}
    for season in load():
        _, _, _, universe, events = _season_arrays(season)
        rows, cols = events["row"].to_numpy(), events["col"].to_numpy()
        for name, levels_of in models.items():
            levels = np.asarray(levels_of(season))[:, season.first:]
            at_event, in_universe = levels[rows, cols], levels[universe]
            for level in LEVELS:
                entry = table[name][level]
                entry["events"] += len(rows)
                entry["hits"] += int((at_event >= level).sum())
                entry["alerts"] += int((in_universe >= level).sum())
    return table


def select(table: dict[str, dict[int, dict[str, int]]]) -> str:
    """"C2" when it has fewer development Warning+ alert cell-days than C1 at equal or higher development detection at every
    level, else "C1" (ties go to C1). `table` is the `development_table` rows of C1 and C2."""
    c1, c2 = table["C1"], table["C2"]
    fewer = c2[lv.WARNING]["alerts"] < c1[lv.WARNING]["alerts"]
    kept = all(c2[level]["hits"] >= c1[level]["hits"] for level in LEVELS)
    return "C2" if fewer and kept else "C1"


# ----------------------------------------------------------------------------------- the held-out look

@dataclass
class HeldOut:
    """The pooled held-out set: v3's and the candidate's levels (cells x days, seasons joined over days), the cells, days,
    scored cells, the events dated on those days and how many distinct events fall outside them."""

    cell_ids: np.ndarray
    days: list[date]
    scored: np.ndarray
    v3: np.ndarray
    candidate: np.ndarray
    events: pd.DataFrame
    events_outside: int


def _scores(levels: np.ndarray, pool: HeldOut, m, labels: np.ndarray, boot: dict) -> dict[int, dict]:
    return {k: bootstrap_scores(levels, pool.scored, m, k, boot) | grouped_pod(m.event_level, labels, k, boot) for k in LEVELS}


def score_heldout(pool: HeldOut, boot: dict = BOOTSTRAP, published: dict | None = None) -> dict:
    """v3 against the candidate on `pool`, tolerant and cell-exact, per level.

    Per tolerance: `v3` and `candidate` hold the `scores.bootstrap_scores` of each level plus the detection of independent
    slides (`grouped_pod` over `heldout.event_clusters`), and `change` the `scores.paired_change` (candidate minus v3, days
    resampled together). v3 is scored first and compared with `published` ({tolerance: {level: {field: value}}}, the numbers
    the W1 report gives); a difference raises before the candidate is scored.
    """
    scores: dict = {}
    matched: dict = {}
    for name, tolerance in TOLERANCES.items():
        m = match(pool.v3, pool.cell_ids, pool.days, pool.events, tolerance)
        labels = heldout.event_clusters(m.events)
        matched[name] = (m, labels)
        scores[name] = {"v3": _scores(pool.v3, pool, m, labels, boot)}
    _check_published(scores, published)
    for name, tolerance in TOLERANCES.items():
        m_v3, labels = matched[name]
        m = match(pool.candidate, pool.cell_ids, pool.days, pool.events, tolerance)
        scores[name]["candidate"] = _scores(pool.candidate, pool, m, labels, boot)
        scores[name]["change"] = {k: paired_change(pool.candidate, pool.v3, pool.scored, m, m_v3, k, boot) for k in LEVELS}
    first = scores["tolerant"]["v3"][1]
    return {"events": first["events"], "slides": first["groups"], "events_outside_panel_days": pool.events_outside, **scores}


def _check_published(scores: dict, published: dict | None) -> None:
    wrong = []
    for name, levels in (published or {}).items():
        for level, expected in levels.items():
            for key, value in expected.items():
                got = scores[name]["v3"][level][key]
                if got != value:
                    wrong.append(f"{name} {LEVEL_NAMES[level]} {key} {got} against {value}")
    if wrong:
        raise ValueError("v3's held-out numbers differ from the published ones, so the pool is wrong: " + "; ".join(wrong))


def published_v3(path: Path) -> dict:
    """v3's POOLED numbers of the W1 report at `path`, as `score_heldout` checks them."""
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    v3 = document["sets"]["POOLED"]["models"]["v3"]
    keys = ("events", "hits", "alert_cell_days", "group_hits", "groups")
    return {name: {int(level): {key: entry[key] for key in keys} for level, entry in levels.items()} for name, levels in v3.items()}


def decide(scores: dict) -> dict:
    """The adoption criterion of spec section 3, literally, in both tolerances (`scores` as `score_heldout` returns them).

    1. Independent-slide detection of the candidate is lower than v3's by no more than 1 slide at Warning+ and at Emergency
       and by no more than 2 at Watch+.
    2. Warning+ alert cell-days fall, and the paired-bootstrap interval of the change lies entirely below 0.

    Every condition is recorded with its numbers; the candidate is adopted only if all of them pass.
    """
    conditions = []
    for name in TOLERANCES:
        entry = scores[name]
        for level in LEVELS:
            v3, candidate = entry["v3"][level]["group_hits"], entry["candidate"][level]["group_hits"]
            conditions.append({"tolerance": name, "condition": f"{THRESHOLD_NAMES[level]}_detection", "v3": v3,
                               "candidate": candidate, "lost": v3 - candidate, "allowed": ALLOWED_SLIDES_LOST[level],
                               "passed": v3 - candidate <= ALLOWED_SLIDES_LOST[level]})
        change = entry["change"][lv.WARNING]
        interval = [float(x) for x in change["alert_cell_days_change_ci"]]
        conditions.append({"tolerance": name, "condition": "warning_burden", "change": change["alert_cell_days_change"],
                           "ci": interval, "passed": bool(change["alert_cell_days_change"] < 0 and interval[1] < 0)})
    failed = [f"{c['tolerance']}: {c['condition']}" for c in conditions if not c["passed"]]
    return {"adopt": not failed, "conditions": conditions, "failed": failed}


def refuse_second_look(path: Path) -> None:
    if Path(path).exists():
        raise FileExistsError(f"{Path(path).name} exists: the held-out look of {path} has been taken and is not repeated")


def evaluate_once(path: Path, build: Callable[[], HeldOut], boot: dict = BOOTSTRAP, published: dict | None = None,
                  context: dict | None = None) -> dict:
    """The single held-out look: score `build()` and decide, then store the result at `path`.

    Raises FileExistsError, before `build` loads anything, when `path` exists: the look has been taken and is not repeated.
    A failure before the result is stored (a pool that does not reproduce v3's published numbers) leaves nothing behind and
    may be rerun; the file is created exclusively, so two runs cannot both store a result.
    """
    path = Path(path)
    refuse_second_look(path)
    scores = score_heldout(build(), boot, published)
    result = {**(context or {}), "scores": scores, "decision": decide(scores)}
    text = json.dumps(jsonable(result), indent=2, allow_nan=False)
    with open(path, "x", encoding="utf-8") as handle:
        handle.write(text + "\n")
    return result


# --------------------------------------------------------------------------------------------- outputs

def _by_stratum(thresholds: dict[Stratum, float | None]) -> dict[str, dict[str, float | None]]:
    out: dict[str, dict[str, float | None]] = {}
    for (region, month), value in sorted(thresholds.items()):
        out.setdefault(region, {})[str(month)] = value
    return out


def thresholds_document(fit_: Fit, selected: str, v3: dict[str, lv.Thresholds]) -> dict:
    """The candidate thresholds file: both candidates (same thresholds, C2 with the Emergency confirmation), the selection and
    v3's thresholds. A stratum with None keeps v3's; October-December are not listed and keep v3's."""
    shared = {THRESHOLD_NAMES[level]: _by_stratum(fit_.thresholds[level]) for level in LEVELS}
    return {
        "version": 1,
        "status": "candidate; not read by the live run until adopted and wired in a separate, reviewed step (spec section 4)",
        "strata": "region x month, June-September; a null threshold and October-December keep v3's region threshold",
        "grid": {"quantiles": [float(QUANTILES[0]), float(QUANTILES[-1])], "steps": len(QUANTILES),
                 "lowest": float(fit_.grid[0]), "highest": float(fit_.grid[-1])},
        "selected": selected,
        "candidates": {name: {"confirm_emergency": confirm, "thresholds": shared} for name, confirm in CANDIDATES.items()},
        "v3": {region: {THRESHOLD_NAMES[level]: float(t.as_array()[level - 1]) for level in LEVELS} for region, t in v3.items()},
    }


def report_result(fit_: Fit, table: dict, selected: str, heldout_result: dict, v3: dict[str, lv.Thresholds]) -> dict:
    """The report document: the thresholds, the fit, the development table, the selection and the held-out look."""
    return {
        "protocol": {
            "spec": "docs/superpowers/specs/2026-11-06-aetherguard-w2-operating-point.md",
            "alert_levels": LEVEL_NAMES,
            "tolerances": {n: {"km": t.km, "days": t.days} for n, t in TOLERANCES.items()},
            "development": f"out-of-fold seasons {burden.DEV_YEARS[0]}-{burden.DEV_YEARS[-1]} from 1 June; alert cell-days on the "
                           "universe-sample cells only, detection cell-exact on all development events",
            "heldout": f"POOLED {SEASON_YEARS[0]}-{SEASON_YEARS[-1]}, the training-style panels of verify.seasons",
            "bootstrap": BOOTSTRAP,
            "candidates": {name: "region x month thresholds" + (" and the Emergency confirmation" if confirm else "")
                           for name, confirm in CANDIDATES.items()},
        },
        "thresholds": thresholds_document(fit_, selected, v3),
        "fit": {str(level): {"target_hits": fit_.targets[level], "allocated_hits": fit_.allocations[level].hits,
                             "allocated_alerts": fit_.allocations[level].alerts, "v3_point_hits": fit_.v3_point[level]["hits"],
                             "v3_point_alerts": fit_.v3_point[level]["alerts"]} for level in LEVELS},
        "development": table,
        "selected": selected,
        "heldout": heldout_result,
    }


def _threshold(value: float | None) -> str:
    return "v3" if value is None else f"{value:.3g}"


def _threshold_rows(document: dict) -> list[str]:
    rows = []
    for region, months in document["candidates"]["C1"]["thresholds"]["watch"].items():
        for month in months:
            cells = []
            for level in LEVELS:
                value = document["candidates"]["C1"]["thresholds"][THRESHOLD_NAMES[level]][region][month]
                cells.append(f"{document['v3'][region][THRESHOLD_NAMES[level]]:.3g} -> {_threshold(value)}")
            rows.append(f"| {region.replace('_', ' ').title()} | {month} | " + " | ".join(cells) + " |")
    return rows


def _development_rows(table: dict) -> list[str]:
    rows = []
    for name, levels in table.items():
        for level in LEVELS:
            e, v3 = levels[level], table["v3"][level]
            per_thousand = 1000 * e["hits"] / e["alerts"] if e["alerts"] else float("nan")
            change = "" if name == "v3" else f"{e['hits'] - v3['hits']:+d} / {e['alerts'] - v3['alerts']:+,d} ({_pct((e['alerts'] - v3['alerts']) / v3['alerts'])})"
            rows.append(f"| {name} | {LEVEL_NAMES[level]} | {e['events']} | {e['hits']} | {_pct(e['hits'] / e['events'])} | "
                        f"{e['alerts']:,} | {per_thousand:.2f} | {change} |")
    return rows


def _ci(interval: list, digits: int = 0) -> str:
    return "[n/a]" if any(x is None or x != x for x in interval) else f"[{interval[0]:,.{digits}f}, {interval[1]:,.{digits}f}]"


def _heldout_rows(scores: dict) -> list[str]:
    rows = []
    for name in TOLERANCES:
        entry = scores[name]
        for level in LEVELS:
            v3, c, d = entry["v3"][level], entry["candidate"][level], entry["change"][level]
            rows.append(
                f"| {name} | {LEVEL_NAMES[level]} | {v3['group_hits']} | {c['group_hits']} | {v3['groups']} | {v3['hits']} | {c['hits']} | "
                f"{v3['alert_cell_days']:,} | {c['alert_cell_days']:,} | {d['alert_cell_days_change']:+,d} "
                f"{_ci(d['alert_cell_days_change_ci'])} | {_pct(v3['precision'], 4)} | {_pct(c['precision'], 4)} | "
                f"{100 * d['precision_change']:+.4f} pp {_ci([100 * x for x in d['precision_change_ci']], 4)} |")
    return rows


def _condition_rows(decision: dict) -> list[str]:
    rows = []
    for c in decision["conditions"]:
        if c["condition"] == "warning_burden":
            numbers = f"Warning+ alert cell-days change {c['change']:+,d}, 95% CI {_ci(c['ci'])}; must fall with the interval below 0"
        else:
            numbers = f"v3 {c['v3']}, candidate {c['candidate']}, lost {c['lost']}, allowed {c['allowed']}"
        rows.append(f"| {c['tolerance']} | {c['condition']} | {numbers} | {'pass' if c['passed'] else 'FAIL'} |")
    return rows


def markdown(result: dict) -> str:
    held, selected = result["heldout"], result["selected"]
    scores, decision = held["scores"], held["decision"]
    verdict = "Adopt" if decision["adopt"] else "Do not adopt"
    reason = "every condition of spec section 3 passes in both tolerances" if decision["adopt"] else "failed: " + "; ".join(decision["failed"])
    lines = [
        "# W2: precision-optimal operating point (phase 7)",
        "",
        f"**{verdict} candidate {selected}** ({reason}). Spec section 3, pre-declared before any result: the "
        f"selected candidate is adopted only if, on POOLED {SEASON_YEARS[0]}-{SEASON_YEARS[-1]} ({scores['slides']} independent "
        "slides), tolerant and cell-exact, independent-slide detection is not lower than v3's by more than 1 slide at "
        "Warning+ and at Emergency and 2 at Watch+, and Warning+ alert cell-days fall with the paired-bootstrap 95% CI of the "
        "reduction (days resampled) excluding 0. Otherwise it is reported and not adopted; nothing is tuned after the look.",
        "",
        "## Reading this report",
        "",
        "- Candidates: C1 = region x month thresholds (June-September; October-December and strata without events keep v3's); "
        "C2 = C1 and an Emergency confirmation (Emergency is published only if the raw level of the cell the day before was at "
        "least Warning, else Warning). Section 11 post-model rules and hysteresis apply unchanged on top of both. Selected on "
        "development only.",
        "- Thresholds per level and stratum: the exact fewest alerts that keep v3's point-level hits (development, own cell, "
        "event day) over the strata that can be hit, from v3's risk quantiles 50% to 99.9% in 200 steps, then made "
        "non-decreasing across levels.",
        "- Development numbers are in-sample for the thresholds (fitted on those seasons), so the burden reduction there is "
        "optimistic and is not evidence; only the held-out look decides. Development detection is cell-exact (a tolerant "
        "development figure would be a lower bound) and development alert cell-days are counted on the universe-sample cells.",
        "- Ground truth after 2018 is very incomplete (the reported and catalog events are a small fraction of the slides that "
        "happened), so held-out precision is relative: for comparing v3 with the candidate at the burdens each raises, not an "
        "absolute false-alarm rate.",
        "- Tolerant detection has a high chance floor at Watch+ and Warning+: the 10 km / 1 day window covers about 30-40 "
        "cell-days, so scattered alerts would also hit often. Read tolerant detection only as a comparison at similar burden; the "
        "cell-exact rows do not reward scattered alerts.",
        f"- {scores['slides']} independent slides ({scores['events']} records) is a small sample: one slide is "
        f"{100 / scores['slides']:.1f} points of detection.",
        "- The candidate is not read by the live run; adopting it needs a separate, reviewed wiring step.",
        "",
        "## Thresholds by region and month (v3 -> candidate; v3 = the stratum keeps v3's)",
        "",
        "Risk thresholds; the three levels are shared by C1 and C2.",
        "",
        "| region | month | Watch | Warning | Emergency |",
        "|---|---|---|---|---|",
        *_threshold_rows(result["thresholds"]),
        "",
        "## Fit on the development seasons",
        "",
        "Point level (risk against the thresholds, no rules), over the strata that can be hit. The allocation keeps at least the "
        "target hits with the fewest alert cell-days.",
        "",
        "| level | target hits (v3) | hits allocated | v3 alert cell-days | allocated alert cell-days |",
        "|---|---|---|---|---|",
        *[f"| {LEVEL_NAMES[int(level)]} | {f['target_hits']} | {f['allocated_hits']} | {f['v3_point_alerts']:,} | "
          f"{f['allocated_alerts']:,} |" for level, f in result["fit"].items()],
        "",
        "## Development, full chain (cell-exact detection, universe-sample alert cell-days)",
        "",
        "C2 would be selected only with fewer Warning+ alert cell-days than C1 at equal or higher detection at every level; "
        f"otherwise C1 (ties go to C1). Selected: **{selected}**.",
        "",
        "| model | level | events | hits | detection | alert cell-days | hits per 1000 alert cell-days | change against v3: hits / alert cell-days |",
        "|---|---|---|---|---|---|---|---|",
        *_development_rows(result["development"]),
        "",
        f"## Held-out look, POOLED ({scores['events']} records, {scores['slides']} independent slides; "
        f"{scores['events_outside_panel_days']} further event dated outside the panel days)",
        "",
        f"v3 against {selected}. Detection is in independent slides (a slide is detected when any record is); `events hit` counts "
        "records. The change is candidate minus v3 with a paired-bootstrap 95% interval (days resampled).",
        "",
        "| tolerance | level | v3 slides | candidate slides | of | v3 events hit | candidate events hit | v3 alert cell-days | "
        "candidate alert cell-days | change [95% CI] | v3 precision | candidate precision | precision change [95% CI] |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
        *_heldout_rows(scores),
        "",
        "## Decision",
        "",
        f"**{verdict} {selected}.**",
        "",
        "| tolerance | condition | numbers | result |",
        "|---|---|---|---|",
        *_condition_rows(decision),
        "",
    ]
    return "\n".join(lines)


# ----------------------------------------------------------------------------------------------- the run

def thresholds_path() -> Path:
    return data_root() / "processed" / "alerts" / "thresholds_w2_candidate.json"


def heldout_result_path() -> Path:
    return data_root() / "processed" / "alerts" / "w2_heldout.json"


def _check_development_v3(table: dict, path: Path) -> None:
    """v3's development numbers through this module must equal those of the W0 baseline report (cell-exact)."""
    published = json.loads(Path(path).read_text(encoding="utf-8"))["sets"]["development"]["models"]["v3"]["cell_exact"]
    wrong = [f"{LEVEL_NAMES[level]} {key} {table['v3'][level][mine]} against {published[str(level)][theirs]}"
             for level in LEVELS for key, mine, theirs in (("hits", "hits", "hits"), ("alerts", "alerts", "alert_cell_days"),
                                                           ("events", "events", "events"))
             if table["v3"][level][mine] != published[str(level)][theirs]]
    if wrong:
        raise ValueError("v3's development numbers differ from the published baseline, so the loading is wrong: " + "; ".join(wrong))


def level_models(thresholds: dict[int, dict[Stratum, float | None]], config, base_rules) -> dict[str, Callable[[D.Season], np.ndarray]]:
    """v3 and the two candidates as functions from a season to its full-panel levels."""
    models = {"v3": lambda season: D.season_levels(season, "new_hi", config, base_rules)}
    for name, confirm in CANDIDATES.items():
        models[name] = lambda season, confirm=confirm: candidate_levels(season, thresholds, config, base_rules, confirm)
    return models


def development_fit(model, config, base_rules, say) -> tuple[Fit, dict, str]:
    """Steps 1 and 2 on the development seasons: the fit, the table of v3, C1 and C2, and the selection."""
    events = burden.development_events()

    def load():
        for year in burden.DEV_YEARS:
            yield D.load_seasons(H.alerts_dir(H.DEV_DIR), [year], model.card, events)[0]

    say("development: candidate thresholds")
    grid = candidate_grid(load)
    say(f"development: stratum curves and allocation over {len(grid)} candidates")
    fitted = fit(load, grid)
    say("development: v3, C1 and C2 through the whole chain")
    table = development_table(load, level_models(fitted.thresholds, config, base_rules))
    _check_development_v3(table, REPORTS / f"{report.REPORT_STEM}.json")
    return fitted, table, select(table)


def build_heldout(cfg: dict, model, config, base_rules, thresholds, confirm: bool, say) -> HeldOut:
    """The POOLED 2018-2025 held-out set as `heldout.measure_set` assembles it, with v3's levels and the candidate's."""
    reference = H.load_panel(H.alerts_dir(H.HELDOUT_DIR) / H.HELDOUT_FILE).cells["cell_id"].to_numpy()
    events = heldout.load_event_table(cfg)
    events = events[pd.to_datetime(events["date"]).dt.year.isin(SEASON_YEARS)]
    v3, candidate, scored, days = [], [], [], []
    for year in SEASON_YEARS:
        say(f"held-out season {year}: v3 and the candidate")
        season = heldout.load_panel_season(year, reference, model)
        part = extract(season, config, base_rules)
        v3.append(part.v3)
        scored.append(part.scored)
        days += part.days
        candidate.append(candidate_levels(season, thresholds, config, base_rules, confirm)[:, season.first:])
        del season, part
    kept, outside = heldout.events_on_days(events, days)
    return HeldOut(reference, days, np.concatenate(scored, axis=1), np.concatenate(v3, axis=1),
                   np.concatenate(candidate, axis=1), kept, outside)


def run(out: Path, say=print) -> dict:
    """The whole study: development fit and selection, the candidate file, the single held-out look, the report."""
    started = time.perf_counter()
    cfg = live_run.load_run_config()
    result_path = heldout_result_path()
    refuse_second_look(result_path)
    refuse_second_look(Path(out) / f"{REPORT_STEM}.json")      # committed: guards a fresh clone without data/
    model, config, base_rules = ps.load_inputs(cfg)
    fitted, table, selected = development_fit(model, config, base_rules, say)
    v3 = lv.card_region_thresholds(model.card, sorted({region for region, _ in fitted.thresholds[1]}))
    dump_json(thresholds_path(), thresholds_document(fitted, selected, v3))
    say(f"selected {selected}; wrote {hm.display_path(thresholds_path())}")
    say("held-out look (once)")
    looked = evaluate_once(result_path, lambda: build_heldout(cfg, model, config, base_rules, fitted.thresholds, CANDIDATES[selected], say),
                           BOOTSTRAP, published_v3(REPORTS / f"{heldout.REPORT_STEM}.json"),
                           {"selected": selected, "thresholds_file": hm.display_path(thresholds_path())})
    result = report_result(fitted, table, selected, looked, v3) | {"seconds": time.perf_counter() - started}
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    dump_json(out / f"{REPORT_STEM}.json", result)
    (out / f"{REPORT_STEM}.md").write_text(markdown(result), encoding="utf-8")
    say(f"wrote {hm.display_path(out / REPORT_STEM)}.{{json,md}}")
    return result
