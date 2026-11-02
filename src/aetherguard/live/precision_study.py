"""Precision study of the live alert levels (spec section 14): terrain plausibility and per-level rain floors.

    python -m aetherguard.live.precision_study dev          # floors and terrain variable on the development panels, diagnosis
    python -m aetherguard.live.precision_study heldout      # the one 2018 evaluation and the adoption decision
    python -m aetherguard.live.precision_study live-replay  # the live days 2026-10-16..2026-10-24 offline, nothing written to data/live
    python -m aetherguard.live.precision_study report       # reports/phase6_precision_rules.{md,json}

An analysis only: the frozen model, `postrules.py`, the live run and the published tables are not touched. The candidate rules
are written to `data/processed/alerts/post_rules_v4_candidate.json`, which no run reads. The design, the floors' definition and
the adoption criterion are section 14 of the live design spec and were written before any 2018 number of this study existed.

* Rule T (terrain plausibility): a cell-day on a cell whose terrain variable is below the 5th percentile of that variable over
  the development positives cannot exceed Watch. The variable is the one of `TERRAIN_VARIABLES` whose floor removes the largest
  share of the development NEGATIVE Warning-or-above point cell-days.
* Rule R (per-level rain floors): Warning needs any of the 1-, 3-, 7-day IMERG rains to reach the 5th percentile of that window
  over the development positives whose point reaches Warning; Emergency likewise with the positives reaching Emergency.
* The conditions are evaluated on top of the section 11 levels (7-day 11.50 mm rain cap, hold windows 2 / 1 / 1, blind-hold limit),
  with the same hysteresis (`levels.apply_hysteresis`) and the hold release extended to the new tests.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, replace
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from ..alerts import levels as lv
from ..alerts.config import load_config_file as load_alert_config
from ..config import PROJECT_ROOT, data_root
from ..hazard import data as hd
from ..hazard import model as hm
from ..hazard.jsonio import dump_json
from ..hazard.tables import _table
from ..hazard.train import extra_groups_used
from . import backtest as bt
from . import burden
from . import hardening as H
from . import hardening_dev as D
from . import postrules as pr
from . import run as live_run

OUT_DIR = "precision_study"                       # under data/processed/alerts/
DEV_FILE, HELDOUT_FILE, REPLAY_FILE = "dev_precision.json", "heldout_precision.json", "live_replay.json"
CANDIDATE_RULES = Path("data") / "processed" / "alerts" / "post_rules_v4_candidate.json"
REPORT_STEM = "phase6_precision_rules"
TERRAIN_VARIABLES = ("stat_slope_p90", "stat_slope_mean", "stat_relief")     # the tie-break order of the choice
FLOOR_PERCENTILE = 5.0
RAIN_WINDOWS = H.RAIN_WINDOWS
LEVELS = D.LEVELS
CONDITIONS = ("baseline", "T", "R", "T+R")
CAP_DEFAULT = (lv.NORMAL, lv.NORMAL, lv.WATCH, lv.WATCH)
FLAT_SLOPE_DEG, LOW_ELEVATION_M, LOW_RAIN_MM = 5.0, 100.0, 20.0     # the descriptive classes of the diagnosis and the replay
REPLAY_FIRST, REPLAY_REPORT_FROM = date(2026, 10, 9), date(2026, 10, 16)
REPLAY_LAST = date(2026, 10, 24)
JAMMU = (33.1, 74.7, 0.25)                        # lat, lon, half-width in degrees of the listed cell box
KANYAKUMARI_CELL = 19625150
PD_SEED, PD_ROWS = 20261024, 1000
ELEVATION_GRID = (0.0, 10.0, 25.0, 50.0, 75.0, 100.0, 150.0, 200.0, 300.0, 500.0, 750.0, 1000.0, 1500.0, 2000.0, 3000.0, 4000.0)
LOW_ELEVATION_PD_LIMIT_M = 300.0
ELEVATION_BANDS = (0.0, 50.0, 100.0, 200.0, 500.0, 1000.0, 2000.0, np.inf)
ACCURACY_BINS = ((0.0, 1.0), (1.0, 5.0), (5.0, np.inf))
MAX_LOST = {"Watch": 1, "Warning": 1, "Emergency": 1}      # section 14.6 (a)-(c)


def out_dir() -> Path:
    return H.alerts_dir(OUT_DIR)


def write_json(path: Path, payload: dict) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    dump_json(path, payload)


# ----------------------------------------------------------------------------------------------- candidates

@dataclass(frozen=True)
class Candidate:
    """One condition: rule T (`terrain_variable` below `terrain_min` caps the level at Watch) and/or rule R (the Warning and
    Emergency rain tests; each passes when any window reaches its floor)."""
    name: str
    terrain_variable: str | None = None
    terrain_min: float | None = None
    warning: pr.RainRule | None = None
    emergency: pr.RainRule | None = None

    def __post_init__(self) -> None:
        if (self.terrain_variable is None) != (self.terrain_min is None):
            raise ValueError("the terrain rule needs both its variable and its floor")
        if self.terrain_variable is not None and self.terrain_variable not in TERRAIN_VARIABLES:
            raise ValueError(f"terrain variable must be one of {TERRAIN_VARIABLES}, got {self.terrain_variable!r}")

    @property
    def has_terrain(self) -> bool:
        return self.terrain_variable is not None

    @property
    def has_rain(self) -> bool:
        return self.warning is not None or self.emergency is not None

    def to_dict(self) -> dict:
        floors = lambda rule: None if rule is None else {str(w): m for w, m in sorted(rule.minimum_mm.items())}
        return {"name": self.name,
                "terrain": None if not self.has_terrain else {"variable": self.terrain_variable, "minimum": self.terrain_min},
                "warning_rain_floor_mm": floors(self.warning), "emergency_rain_floor_mm": floors(self.emergency)}

    @classmethod
    def from_dict(cls, values: dict) -> "Candidate":
        rule = lambda m: None if not m else pr.RainRule({int(w): float(v) for w, v in m.items()})
        terrain = values.get("terrain")
        return cls(values["name"], None if not terrain else terrain["variable"],
                   None if not terrain else float(terrain["minimum"]),
                   rule(values.get("warning_rain_floor_mm")), rule(values.get("emergency_rain_floor_mm")))


def conditions_from(terrain: tuple[str, float] | None, warning: pr.RainRule | None,
                    emergency: pr.RainRule | None) -> dict[str, Candidate]:
    """The four conditions of the study; a rule that is vacuous (no rain floor) leaves R and T+R out."""
    variable, minimum = terrain if terrain else (None, None)
    out = {"baseline": Candidate("baseline")}
    if terrain:
        out["T"] = Candidate("T", variable, minimum)
    if warning is not None or emergency is not None:
        out["R"] = Candidate("R", warning=warning, emergency=emergency)
        if terrain:
            out["T+R"] = Candidate("T+R", variable, minimum, warning, emergency)
    return out


def terrain_alternatives(floors: dict[str, float], chosen: str | None) -> dict[str, Candidate]:
    """Rule T on each terrain variable that was NOT chosen, at its own development floor: a descriptive sensitivity of the
    development and live-replay runs (never evaluated on 2018, whose single look is the chosen conditions)."""
    return {f"T[{v}]": Candidate(f"T[{v}]", v, floors[v]) for v in TERRAIN_VARIABLES if v != chosen}


# ------------------------------------------------------------------------------------------------ the floors

def percentile_floor(values, percentile: float = FLOOR_PERCENTILE) -> float | None:
    values = np.asarray(values, dtype=np.float64)
    values = values[np.isfinite(values)]
    return float(np.percentile(values, percentile)) if len(values) else None


def terrain_floors(positives: pd.DataFrame) -> dict[str, float | None]:
    """The 5th percentile of each candidate terrain variable over the development positives."""
    return {v: percentile_floor(positives[v]) for v in TERRAIN_VARIABLES}


def development_positives(hazard_cfg: dict | None = None) -> pd.DataFrame:
    """The in-domain development positives (train + validation samples, every month): the population of the 11.50 mm rule."""
    cfg = hazard_cfg or hm.hazard_config(D.PROJECT_HAZARD_CONFIG)
    samples = hd.load_development(None, cfg["extra_groups"], extra_groups_used(cfg), cfg["meta_columns"]).samples
    return samples[(samples["kind"] == "positive") & samples["in_domain"].astype(bool)].reset_index(drop=True)


def cell_terrain(cells: pd.DataFrame, table: pd.DataFrame) -> pd.DataFrame:
    """The own-cell terrain variables of `cells` (cell_id column) from the scored-cell table."""
    lookup = table.set_index("cell_id")[list(TERRAIN_VARIABLES)]
    return lookup.reindex(cells["cell_id"].to_numpy(dtype=np.int64)).reset_index(drop=True)


def event_mask(season: D.Season) -> np.ndarray:
    """(cells, days) True on the labelled event cell-days of the season's panel."""
    panel = season.panel
    mask = np.zeros(panel.scored.shape, dtype=bool)
    row_of = {int(c): i for i, c in enumerate(panel.cells["cell_id"])}
    col_of = {pd.Timestamp(d): j for j, d in enumerate(panel.days)}
    for event in season.events.itertuples():
        i, j = row_of.get(int(event.cell_id)), col_of.get(pd.Timestamp(event.date))
        if i is not None and j is not None:
            mask[i, j] = True
    return mask


def terrain_removal(seasons: list[D.Season], terrain: list[pd.DataFrame], floors: dict[str, float]) -> dict:
    """Per terrain variable, the share of the development NEGATIVE alert cell-days (scored universe cell-days from 1 June with a
    point level of Warning or above that are not event cell-days) on cells below the variable's floor, and the labelled events
    with a Warning+ point on such cells (the cost)."""
    out = {v: {"floor": floors[v], "negative_alert_cell_days": 0, "removed": 0, "positive_alert_cell_days": 0,
               "positive_removed": 0} for v in TERRAIN_VARIABLES}
    for season, table in zip(seasons, terrain):
        panel, first = season.panel, season.first
        universe = panel.cells["in_universe"].to_numpy(dtype=bool)[:, None]
        alert = (D.point_levels(season) >= lv.WARNING) & panel.scored
        alert[:, :first] = False
        events = event_mask(season)
        negatives, positives = alert & universe & ~events, alert & events
        for v in TERRAIN_VARIABLES:
            below = (table[v].to_numpy(dtype=np.float64) < floors[v])[:, None]
            out[v]["negative_alert_cell_days"] += int(negatives.sum())
            out[v]["removed"] += int((negatives & below).sum())
            out[v]["positive_alert_cell_days"] += int(positives.sum())
            out[v]["positive_removed"] += int((positives & below).sum())
    for entry in out.values():
        entry["removed_share"] = entry["removed"] / entry["negative_alert_cell_days"] if entry["negative_alert_cell_days"] else None
    return out


def choose_terrain_variable(removal: dict) -> dict:
    """The variable whose floor removes the largest share of the negative alert cell-days; ties go to `TERRAIN_VARIABLES` order."""
    shares = {v: (removal[v]["removed_share"] if removal[v]["removed_share"] is not None else -1.0) for v in TERRAIN_VARIABLES}
    best = max(TERRAIN_VARIABLES, key=lambda v: (shares[v], -TERRAIN_VARIABLES.index(v)))
    return {"variable": best, "minimum": removal[best]["floor"], "removed_share": removal[best]["removed_share"],
            "rule": "the candidate whose 5th-percentile floor removes the largest share of the development negative "
                    "Warning+ point cell-days (ties in the order listed)"}


def rain_floor_study(seasons: list[D.Season]) -> dict:
    """Per level (Warning, Emergency): the 5th percentile of the 1-, 3- and 7-day rain of the development positives (event
    cell-days with a score) whose point reaches that level. Windows with a 0 mm floor are vacuous and left out of the rule."""
    rows = {lv.WARNING: [], lv.EMERGENCY: []}
    for season in seasons:
        point, panel = D.point_levels(season), season.panel
        row_of = {int(c): i for i, c in enumerate(panel.cells["cell_id"])}
        col_of = {pd.Timestamp(d): j for j, d in enumerate(panel.days)}
        for event in season.events.itertuples():
            i, j = row_of.get(int(event.cell_id)), col_of.get(pd.Timestamp(event.date))
            if i is None or j is None or not panel.scored[i, j]:
                continue
            for level in rows:
                if point[i, j] >= level:
                    rows[level].append([panel[f"acc_{w}"][i, j] for w in RAIN_WINDOWS])
    out = {}
    for level, values in rows.items():
        values = np.asarray(values, dtype=np.float64).reshape(-1, len(RAIN_WINDOWS))
        floors = {w: percentile_floor(values[:, k]) for k, w in enumerate(RAIN_WINDOWS)}
        used = {w: m for w, m in floors.items() if m is not None and m > 0}
        out[lv.level_name(level)] = {"n_positives": int(len(values)), "floor_mm": {str(w): m for w, m in floors.items()},
                                     "windows_used": sorted(used), "vacuous_windows": sorted(set(RAIN_WINDOWS) - set(used)),
                                     "rule": pr.RainRule(used).describe() if used else None}
    return out


def rain_rules_of(floor_study: dict) -> tuple[pr.RainRule | None, pr.RainRule | None]:
    rule = lambda entry: pr.RainRule({int(w): entry["floor_mm"][str(w)] for w in entry["windows_used"]}) if entry["windows_used"] else None
    return rule(floor_study["Warning"]), rule(floor_study["Emergency"])


# --------------------------------------------------------------------------------------------- the conditions

def apply_candidate(raw, rain: dict[int, np.ndarray], flat, candidate: Candidate) -> np.ndarray:
    """The raw level (after the section 11 rain cap) under the candidate: Emergency failing its rain test becomes Warning, a
    Warning failing its test becomes Watch, then a flat cell cannot exceed Watch. `flat` broadcasts against `raw`."""
    out = np.asarray(raw, dtype=np.int8).copy()
    if candidate.emergency is not None:
        out = np.where((out == lv.EMERGENCY) & ~candidate.emergency.passes_arrays(rain), lv.WARNING, out)
    if candidate.warning is not None:
        out = np.where((out == lv.WARNING) & ~candidate.warning.passes_arrays(rain), lv.WATCH, out)
    if candidate.has_terrain:
        out = np.where(np.asarray(flat, dtype=bool) & (out >= lv.WARNING), lv.WATCH, out)
    return out.astype(np.int8)


def level_passes(base_ok, rain: dict[int, np.ndarray], flat, candidate: Candidate) -> dict[int, np.ndarray]:
    """Per level (Watch, Warning, Emergency): where the cell-day passes every test of that level (the section 11 rain rule, the
    candidate's rain test, not a flat cell) - the hold of that level is released on the days of its window that all fail."""
    base_ok = np.asarray(base_ok, dtype=bool)
    shape = base_ok.shape
    plausible = ~np.asarray(flat, dtype=bool) if candidate.has_terrain else np.ones(shape, dtype=bool)
    warning = candidate.warning.passes_arrays(rain) if candidate.warning is not None else np.ones(shape, dtype=bool)
    emergency = candidate.emergency.passes_arrays(rain) if candidate.emergency is not None else np.ones(shape, dtype=bool)
    return {lv.WATCH: base_ok, lv.WARNING: base_ok & warning & plausible, lv.EMERGENCY: base_ok & emergency & plausible}


def hold_caps(candidate: Candidate) -> tuple[np.ndarray, np.ndarray]:
    """(cap on ordinary cells, cap on flat cells) of the hold release: a released Emergency falls to Warning when rule R tests
    it separately, to Watch on a flat cell (rule T) and otherwise as in section 11."""
    main = np.array(CAP_DEFAULT, dtype=np.int8)
    if candidate.emergency is not None:
        main[lv.EMERGENCY] = lv.WARNING
    return main, np.array(CAP_DEFAULT, dtype=np.int8)


def candidate_levels(raw, risk, rain: dict[int, np.ndarray], base_ok, flat, candidate: Candidate, base_rules: pr.PostRules,
                     region, ids, stamps, thresholds: dict[str, lv.Thresholds], config) -> np.ndarray:
    """Alert levels (cells, days) of `candidate`: `raw` is the raw level after the section 11 rain cap, `rain` the windows of
    the candidate's tests, `base_ok` the section 11 rain rule; the hysteresis holds each level over its window of
    `base_rules` and releases it on the days every test of the level fails."""
    flat = np.asarray(flat, dtype=bool)
    flat_days = flat[:, None] if flat.ndim == 1 else flat
    new_raw = apply_candidate(raw, rain, flat_days, candidate)
    passes = level_passes(base_ok, rain, flat_days, candidate)
    release = np.zeros((*new_raw.shape, 4), dtype=bool)
    for level in D.LEVELS:
        release[..., level] = ~D.window_any(passes[level], base_rules.window_of(level))
    main, flat_cap = hold_caps(candidate)
    groups = ((~flat, main), (flat, flat_cap)) if candidate.has_terrain else ((np.ones(len(flat), dtype=bool), main),)
    region = np.asarray(region)
    out = np.zeros(new_raw.shape, dtype=np.int8)
    for name, thr in thresholds.items():
        for members, cap in groups:
            rows = np.flatnonzero((region == name) & members)
            if not len(rows):
                continue
            row_ids = np.repeat(np.asarray(ids, dtype=np.int64)[rows], new_raw.shape[1])
            dates = np.tile(stamps, len(rows))
            out[rows] = lv.apply_hysteresis(row_ids, dates, new_raw[rows].ravel(), np.asarray(risk)[rows].ravel(), thr,
                                            config.exit_factor, config.exit_days, None, release[rows].reshape(-1, 4), cap,
                                            base_rules.blind_hold_days).reshape(len(rows), -1)
    return out


def season_candidate_levels(season: D.Season, config, base_rules: pr.PostRules, candidate: Candidate, flat) -> np.ndarray:
    """Levels (cells, days) of a development or 2018 season under `candidate` (`flat`: per cell, True below the terrain floor)."""
    panel = season.panel
    risk, bound, region = panel["risk"], panel["new_hi"], season.region
    raw = np.zeros(risk.shape, dtype=np.int8)
    for name, thr in season.thresholds.items():
        rows = region == name
        raw[rows] = lv.raw_level(risk[rows], bound[rows], thr)[0]
    rain = {w: panel[f"acc_{w}"] for w in RAIN_WINDOWS}
    base_ok = D.rain_ok(panel, base_rules.rain)
    raw = np.where(base_ok, raw, base_rules.cap_array()[raw]).astype(np.int8)
    stamps = pd.DatetimeIndex(pd.to_datetime(panel.days)).to_numpy()
    return candidate_levels(raw, risk, rain, base_ok, flat, candidate, base_rules, region,
                            panel.cells["cell_id"].to_numpy(), stamps, season.thresholds, config)


def flat_cells(cells: pd.DataFrame, table: pd.DataFrame, candidate: Candidate) -> np.ndarray:
    """Per cell of `cells`: below the candidate's terrain floor (all False without rule T)."""
    if not candidate.has_terrain:
        return np.zeros(len(cells), dtype=bool)
    return cell_terrain(cells, table)[candidate.terrain_variable].to_numpy(dtype=np.float64) < candidate.terrain_min


# ----------------------------------------------------------------------------------------------- the metrics

def season_metrics(season: D.Season, levels: np.ndarray, below_floor: np.ndarray) -> dict:
    """What one season gives the study: the own-cell level of every event, the universe cell-days at each level or above (in
    total, per day and on the cells below the terrain floor)."""
    outcome = D.season_outcome(season, levels)
    panel, first = season.panel, season.first
    universe = panel.cells["in_universe"].to_numpy(dtype=bool)
    lev, scored = levels[universe, first:], panel.scored[universe, first:]
    below = np.asarray(below_floor, dtype=bool)[universe][:, None]
    return {"cell_days": outcome["cell_days"], "own_level": outcome["own_level"],
            "at_least": outcome["at_least"],
            "per_day": {L: ((lev >= L) & scored).sum(axis=0) for L in LEVELS},
            "below_floor_at_least": {L: int(((lev >= L) & scored & below).sum()) for L in LEVELS}}


def summarize(metrics: list[dict], scale: float = 1.0) -> dict:
    """Per level: events detected (own cell, event day), alert cell-days (scaled to all universe cells by `scale`), their share of
    the cell-days, the cell-days on cells below the floor and the precision proxy (detected events per 1,000 alert cell-days)."""
    own = np.concatenate([m["own_level"] for m in metrics])
    cell_days = sum(m["cell_days"] for m in metrics)
    boot = bt.BOOTSTRAP
    out = {"n_events": int(len(own)), "cell_days": cell_days, "scale": scale, "levels": {}}
    for L in LEVELS:
        alert = sum(m["at_least"][L] for m in metrics)
        hits = int((own >= L).sum())
        out["levels"][lv.level_name(L)] = {
            "events_detected": bt.share_ci(own >= L, boot["n"], boot["seed"], boot["level"]),
            "alert_cell_days": int(alert), "alert_cell_days_scaled": alert * scale,
            "alert_share": alert / cell_days if cell_days else None,
            "alert_cell_days_below_terrain_floor": sum(m["below_floor_at_least"][L] for m in metrics),
            "events_per_1000_alert_cell_days": 1000 * hits / (alert * scale) if alert else None}
    return out


def paired_bootstrap(differences) -> dict:
    """Mean of paired differences (before minus after, one per unit) with the seeded percentile bootstrap of `backtest.BOOTSTRAP`."""
    return bt.mean_ci(np.asarray(differences, dtype=np.float64))


def paired_change(base: list[dict], other: list[dict]) -> dict:
    """The change of a condition against the baseline, per level: the paired bootstrap over days of the cell-days removed
    (baseline minus condition, universe cells) and over events of the detection (condition minus baseline)."""
    own_base = np.concatenate([m["own_level"] for m in base])
    own_other = np.concatenate([m["own_level"] for m in other])
    boot = bt.BOOTSTRAP
    out = {}
    for L in LEVELS:
        days = np.concatenate([b["per_day"][L] - o["per_day"][L] for b, o in zip(base, other)])
        base_total = int(sum(b["at_least"][L] for b in base))
        ci = paired_bootstrap(days)
        change = (own_other >= L).astype(np.float64) - (own_base >= L).astype(np.float64)
        rng = np.random.default_rng(boot["seed"])
        resamples = change[rng.integers(0, len(change), (boot["n"], len(change)))].mean(axis=1) if len(change) else np.zeros(1)
        tail = (1 - boot["level"]) / 2
        out[lv.level_name(L)] = {
            "alert_cell_days_removed": int(days.sum()), "alert_cell_days_baseline": base_total,
            "removed_share": float(days.sum() / base_total) if base_total else None,
            "removed_per_day": ci,
            "events_lost": int(((own_base >= L) & ~(own_other >= L)).sum()),
            "events_net_change": int((own_other >= L).sum() - (own_base >= L).sum()),
            "detection_change": {"value": float(change.mean()) if len(change) else None,
                                 "lo": float(np.quantile(resamples, tail)), "hi": float(np.quantile(resamples, 1 - tail))}}
    return out


def adoption_decision(change: dict) -> dict:
    """The pre-declared criterion (spec 14.6) for one condition's `paired_change`: it loses at most 1 event at Watch+, Warning+
    and Emergency, and the paired-bootstrap 95% interval of the per-day Warning+ reduction excludes 0."""
    lost = {name: change[name]["events_lost"] for name in MAX_LOST}
    reduction = change["Warning"]["removed_per_day"]
    excludes_zero = reduction["lo"] is not None and reduction["lo"] > 0
    checks = {"watch_plus_lost_at_most_1": lost["Watch"] <= MAX_LOST["Watch"],
              "warning_plus_lost_at_most_1": lost["Warning"] <= MAX_LOST["Warning"],
              "emergency_lost_at_most_1": lost["Emergency"] <= MAX_LOST["Emergency"],
              "warning_plus_cell_day_reduction_ci_excludes_0": bool(excludes_zero)}
    return {"events_lost": lost, "checks": checks, "adopt": all(checks.values())}


def recommend(decisions: dict[str, dict], changes: dict[str, dict]) -> dict:
    """Among the conditions meeting the criterion, the one removing the most Warning+ cell-days; None when none does."""
    adoptable = [name for name, d in decisions.items() if d["adopt"]]
    best = max(adoptable, key=lambda n: changes[n]["Warning"]["alert_cell_days_removed"], default=None)
    return {"adoptable": adoptable, "recommended": best}


def evaluate_conditions(seasons: list[D.Season], config, base_rules: pr.PostRules, candidates: dict[str, Candidate],
                        table: pd.DataFrame, scale: float) -> dict:
    """Every condition on `seasons` (`table`: the scored-cell terrain table), the changes against the baseline and the
    pre-declared decisions. The 'below the terrain floor' count uses the terrain floor of the T condition when there is one."""
    terrain = next((c for c in candidates.values() if c.has_terrain), None)
    below = [flat_cells(s.panel.cells, table, terrain) if terrain else np.zeros(len(s.panel.cells), dtype=bool) for s in seasons]
    metrics = {}
    for name, candidate in candidates.items():
        flats = [flat_cells(s.panel.cells, table, candidate) for s in seasons]
        levels = [season_candidate_levels(s, config, base_rules, candidate, f) for s, f in zip(seasons, flats)]
        metrics[name] = [season_metrics(s, lev, f) for s, lev, f in zip(seasons, levels, below)]
    summaries = {name: summarize(m, scale) for name, m in metrics.items()}
    changes = {name: paired_change(metrics["baseline"], m) for name, m in metrics.items() if name != "baseline"}
    decisions = {name: adoption_decision(c) for name, c in changes.items()}
    return {"summaries": summaries, "changes": changes, "decisions": decisions, **recommend(decisions, changes)}


def baseline_check(seasons: list[D.Season], config, base_rules: pr.PostRules) -> dict:
    """The study's baseline levels against `hardening_dev.season_levels` with the section 11 rules: they must be identical."""
    same = [bool(np.array_equal(season_candidate_levels(s, config, base_rules, Candidate("baseline"), np.zeros(len(s.panel.cells), bool)),
                                D.season_levels(s, "new_hi", config, base_rules))) for s in seasons]
    return {"seasons": len(same), "identical_seasons": int(sum(same)), "identical": bool(all(same))}


# ------------------------------------------------------------------------------------------------ diagnosis

def low_terrain_flags(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.assign(flat=frame["stat_slope_mean"] < FLAT_SLOPE_DEG, low=frame["stat_elev_mean"] < LOW_ELEVATION_M,
                        flat_or_low=(frame["stat_slope_mean"] < FLAT_SLOPE_DEG) | (frame["stat_elev_mean"] < LOW_ELEVATION_M))


def accuracy_label(km) -> str:
    for lo, hi in ACCURACY_BINS:
        if lo <= km < hi or (np.isinf(hi) and km >= lo):
            return f"{lo:g}-{hi:g} km" if np.isfinite(hi) else f">={lo:g} km"
    return "unknown"


def positives_on_low_terrain(positives: pd.DataFrame, catalog: pd.DataFrame) -> dict:
    """Development positives on cells with a mean slope under 5 degrees or a mean elevation under 100 m: overall, by region, by
    catalog source and by the catalog's location accuracy (`catalog`: positive_cell_days with cell_id, event_date, sources,
    max_accuracy_km)."""
    frame = low_terrain_flags(positives).merge(
        catalog[["cell_id", "event_date", "sources", "max_accuracy_km"]].rename(columns={"event_date": "date"}),
        on=["cell_id", "date"], how="left")
    frame["accuracy"] = frame["max_accuracy_km"].map(lambda km: "unknown" if pd.isna(km) else accuracy_label(float(km)))
    frame["sources"] = frame["sources"].fillna("unknown")

    def share(part: pd.DataFrame) -> dict:
        n = int(len(part))
        return {"n": n, **{k: int(part[k].sum()) for k in ("flat", "low", "flat_or_low")},
                **{f"{k}_share": (float(part[k].mean()) if n else None) for k in ("flat", "low", "flat_or_low")}}
    return {"all": share(frame),
            "by_region": {r: share(g) for r, g in frame.groupby("region")},
            "by_source": {s: share(g) for s, g in frame.groupby("sources")},
            "by_accuracy": {a: share(g) for a, g in frame.groupby("accuracy")},
            "by_region_and_source": {f"{r}|{s}": share(g) for (r, s), g in frame.groupby(["region", "sources"])}}


def elevation_bands(samples: pd.DataFrame) -> list[dict]:
    """Positive and negative development samples by mean-elevation band."""
    out = []
    for lo, hi in zip(ELEVATION_BANDS[:-1], ELEVATION_BANDS[1:]):
        part = samples[(samples["stat_elev_mean"] >= lo) & (samples["stat_elev_mean"] < hi)]
        positive = int((part["kind"] == "positive").sum())
        out.append({"band_m": f"{lo:g}-{hi:g}" if np.isfinite(hi) else f">={lo:g}", "positives": positive,
                    "negatives": int(len(part) - positive), "positive_share": positive / len(part) if len(part) else None})
    return out


def sample_rows(samples: pd.DataFrame, n_each: int, seed: int) -> pd.DataFrame:
    """Up to `n_each` positive and `n_each` negative rows, drawn with `seed` (stable order)."""
    rng = np.random.default_rng(seed)
    parts = []
    for kind in ("positive", "negative"):
        pool = samples[samples["kind"] == kind]
        take = rng.choice(len(pool), size=min(n_each, len(pool)), replace=False)
        parts.append(pool.iloc[np.sort(take)])
    return pd.concat(parts, ignore_index=True)


def elevation_ice(score, rows: pd.DataFrame, grid=ELEVATION_GRID) -> np.ndarray:
    """(rows, grid) scores of `score(frame)` with `stat_elev_mean` set to each grid value and every other input as it is."""
    out = np.empty((len(rows), len(grid)))
    for k, elevation in enumerate(grid):
        out[:, k] = np.asarray(score(rows.assign(stat_elev_mean=np.float32(elevation))), dtype=np.float64)
    return out


def logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, 1e-12, 1 - 1e-12)
    return np.log(p / (1 - p))


def pd_summary(ice: np.ndarray, grid=ELEVATION_GRID) -> dict:
    """The partial dependence (mean score and mean log-odds over the rows) and whether it decreases with elevation up to
    `LOW_ELEVATION_PD_LIMIT_M`, plus the share of ICE curves whose score at 50 m exceeds the score at 300 m."""
    if not len(ice):
        return {"n_rows": 0}
    mean_raw, mean_logit = ice.mean(axis=0), logit(ice).mean(axis=0)
    low = [k for k, g in enumerate(grid) if g <= LOW_ELEVATION_PD_LIMIT_M]
    steps = np.diff(mean_logit[low])
    at = lambda g: list(grid).index(g)
    return {"n_rows": int(len(ice)), "grid_m": list(grid), "pd_score": mean_raw.tolist(), "pd_logodds": mean_logit.tolist(),
            "decreasing_up_to_limit": bool((steps <= 0).all()), "limit_m": LOW_ELEVATION_PD_LIMIT_M,
            "pd_logodds_50m_minus_300m": float(mean_logit[at(50.0)] - mean_logit[at(300.0)]),
            "pd_logodds_50m_minus_1000m": float(mean_logit[at(50.0)] - mean_logit[at(1000.0)]),
            "ice_share_50m_above_300m": float((ice[:, at(50.0)] > ice[:, at(300.0)]).mean()),
            "ice_share_50m_above_1000m": float((ice[:, at(50.0)] > ice[:, at(1000.0)]).mean()),
            "argmax_grid_m": float(grid[int(np.argmax(mean_logit))])}


def elevation_dependence(score, rows: pd.DataFrame) -> dict:
    """PD / ICE of the model on `stat_elev_mean` over `rows`, overall, by region and over the rows that are themselves low."""
    ice = elevation_ice(score, rows)
    out = {"rows": int(len(rows)), "all": pd_summary(ice)}
    for region in sorted(rows["region"].unique()):
        out[f"region_{region}"] = pd_summary(ice[(rows["region"] == region).to_numpy()])
    own_low = (rows["stat_elev_mean"] < LOW_ELEVATION_PD_LIMIT_M).to_numpy()
    out[f"rows_below_{LOW_ELEVATION_PD_LIMIT_M:g}m"] = pd_summary(ice[own_low])
    return out


# ------------------------------------------------------------------------------------------------------ dev

def load_inputs(cfg: dict):
    model = live_run.load_live_model(cfg)
    config = load_alert_config(live_run.project_path(cfg["alert_config"]))
    base_rules = pr.load_rules(live_run.project_path(cfg["post_rules"]))
    return model, config, base_rules


def candidate_document(candidates: dict[str, Candidate], base_rules: pr.PostRules, derivation: dict) -> dict:
    """The proposed rules: the section 11 parameters (so `postrules.load_rules` still reads the file) plus the candidates."""
    return {"version": pr.VERSION, "parameters": base_rules.to_dict(),
            "candidates": {name: c.to_dict() for name, c in candidates.items() if name != "baseline"},
            "status": "candidate; not wired into any run (spec section 14)", "derivation": derivation}


def run_dev(cfg: dict, directory: Path, say=print) -> dict:
    started = time.perf_counter()
    model, config, base_rules = load_inputs(cfg)
    table = live_run.load_cells(cfg)
    years = burden.DEV_YEARS
    events = burden.development_events(years)
    say("loading the development panels")
    seasons = D.load_seasons(H.alerts_dir(H.DEV_DIR), years, model.card, events, say)
    tables = [cell_terrain(s.panel.cells, table) for s in seasons]
    universe_cells = int(len(bt.universe_cell_ids()))
    sampled = int(seasons[0].panel.cells["in_universe"].sum())

    say("rule T: terrain floors")
    positives = development_positives()
    floors = terrain_floors(positives)
    removal = terrain_removal(seasons, tables, floors)
    choice = choose_terrain_variable(removal)
    say(f"  terrain variable {choice['variable']} below {choice['minimum']:.3f} removes {100 * choice['removed_share']:.1f}% of the negative Warning+ cell-days")

    say("rule R: per-level rain floors")
    floor_study = rain_floor_study(seasons)
    warning, emergency = rain_rules_of(floor_study)
    candidates = conditions_from((choice["variable"], choice["minimum"]), warning, emergency)
    say(f"  conditions {list(candidates)}")

    say("baseline check and development evaluation")
    check = baseline_check(seasons, config, base_rules)
    if not check["identical"]:
        raise ValueError(f"the study's baseline levels differ from the section 11 levels: {check}")
    evaluation = evaluate_conditions(seasons, config, base_rules, candidates, table, universe_cells / sampled)
    alternatives = evaluate_conditions(seasons, config, base_rules,
                                       {"baseline": candidates["baseline"], **terrain_alternatives(floors, choice["variable"])},
                                       table, universe_cells / sampled)

    say("diagnosis")
    catalog = pd.read_parquet(data_root() / "processed" / "splits" / "positive_cell_days.parquet")
    cfg_hz = hm.hazard_config(D.PROJECT_HAZARD_CONFIG)
    samples = hd.load_development(None, cfg_hz["extra_groups"], extra_groups_used(cfg_hz), cfg_hz["meta_columns"]).samples
    samples = samples[samples["in_domain"].astype(bool)].reset_index(drop=True)
    diagnosis = {"positives_on_low_terrain": positives_on_low_terrain(positives, catalog),
                 "elevation_bands": elevation_bands(samples),
                 "elevation_dependence": elevation_dependence(model.raw_score, sample_rows(samples, PD_ROWS, PD_SEED)),
                 "monotone_constraint_on_elevation": int(model.constraints[model.columns.index("stat_elev_mean")]) if model.constraints else None,
                 "definitions": {"flat": f"stat_slope_mean < {FLAT_SLOPE_DEG:g} degrees", "low": f"stat_elev_mean < {LOW_ELEVATION_M:g} m",
                                 "pd_sample": {"seed": PD_SEED, "rows_each_kind": PD_ROWS}}}
    result = {"protocol": {"period": "06-01 to 09-30 of 2007-2017, out of fold", "panels": hm.display_path(H.alerts_dir(H.DEV_DIR)),
                           "universe_cells": universe_cells, "sampled_universe_cells": sampled,
                           "development_positives": int(len(positives)), "spec": "section 14"},
              "baseline_rules": base_rules.to_dict(), "baseline_check": check,
              "terrain": {"floors_5th_percentile": floors, "removal": removal, "choice": choice},
              "rain_floors": floor_study, "conditions": {n: c.to_dict() for n, c in candidates.items()},
              "evaluation": evaluation, "evaluation_terrain_alternatives": alternatives, "diagnosis": diagnosis, "seconds": time.perf_counter() - started}
    write_json(Path(directory) / DEV_FILE, result)
    if not (Path(directory) / HELDOUT_FILE).is_file():          # the decision of a finished 2018 evaluation stays
        write_json(PROJECT_ROOT / CANDIDATE_RULES, candidate_document(candidates, base_rules, {
            "source": hm.display_path(Path(directory) / DEV_FILE), "decision": "pending: no rule has been evaluated on 2018 yet"}))
    say(f"wrote {hm.display_path(Path(directory) / DEV_FILE)}")
    return result


# --------------------------------------------------------------------------------------------------- heldout

def run_heldout(cfg: dict, directory: Path, say=print) -> dict:
    """The one 2018 evaluation of the conditions the development run chose; the adoption decision of spec 14.6."""
    started = time.perf_counter()
    dev = json.loads((Path(directory) / DEV_FILE).read_text(encoding="utf-8"))
    candidates = {n: Candidate.from_dict(c) for n, c in dev["conditions"].items()}
    model, config, base_rules = load_inputs(cfg)
    table = live_run.load_cells(cfg)
    spec = bt.load_set("season_2018", cfg=cfg)
    panel = H.load_panel(H.alerts_dir(H.HELDOUT_DIR) / H.HELDOUT_FILE)
    if panel.cells["cell_id"].tolist() != spec.cells["cell_id"].tolist():
        raise ValueError("the 2018 panel does not hold the cells of the season_2018 backtest set")
    season = D.Season(2018, panel, panel.days.index(spec.start), spec.events.reset_index(drop=True),
                      lv.card_region_thresholds(model.card, panel.cells["region"]))
    check = baseline_check([season], config, base_rules)
    if not check["identical"]:
        raise ValueError(f"the study's baseline levels differ from the section 11 levels on 2018: {check}")
    say("2018: every condition, once")
    evaluation = evaluate_conditions([season], config, base_rules, candidates, table, 1.0)
    reference = json.loads((H.alerts_dir(H.HELDOUT_DIR) / "evaluation.json").read_text(encoding="utf-8"))
    published = {k: v["hits"] for k, v in reference["season_2018"]["conditions"]["after"]["detected_at_least"].items()}
    got = {k: v["events_detected"]["hits"] for k, v in evaluation["summaries"]["baseline"]["levels"].items()}
    result = {"protocol": {"set": "season_2018", "cells": int(len(panel.cells)), "days": len(panel.days) - season.first,
                           "events": int(len(season.events)), "single_look": True},
              "baseline_check": check, "baseline_matches_evaluation_json": got == published,
              "evaluation_json_hits": published, "conditions": dev["conditions"], "evaluation": evaluation,
              "criterion": "spec 14.6", "seconds": time.perf_counter() - started}
    write_json(Path(directory) / HELDOUT_FILE, result)
    write_json(PROJECT_ROOT / CANDIDATE_RULES, candidate_document(candidates, base_rules, {
        "source": hm.display_path(Path(directory) / HELDOUT_FILE), "adoptable": evaluation["adoptable"],
        "recommended": evaluation["recommended"], "decisions": evaluation["decisions"]}))
    say(f"adoptable: {evaluation['adoptable']}, recommended: {evaluation['recommended']}")
    return result


# ----------------------------------------------------------------------------------------------- live replay

def replay_days(live_dir: Path, first: date = REPLAY_FIRST, last: date = REPLAY_LAST) -> list[date]:
    """The consecutive days from `first` (or the first one that exists) through `last` whose live tables are stored."""
    days = []
    day = first
    while day <= last:
        if (live_dir / day.isoformat() / "alerts.parquet").is_file() and (live_dir / day.isoformat() / "features_D0.parquet").is_file():
            days.append(day)
        elif days:
            raise ValueError(f"the live day {day} is missing; the replay needs consecutive days")
        day += timedelta(days=1)
    return days


def load_replay(live_dir: Path, days: list[date], model: hm.HazardModel) -> dict:
    """Matrices (cells, days) of the stored live days: the published raw level, level and point risk (NaN where the cell has no
    score), the IMERG windows, and the per-cell terrain and region of the last day."""
    columns = ["cell_id", "region", "lat", "lon", *TERRAIN_VARIABLES, "stat_elev_mean", *[f"irain_acc_{w}" for w in (1, 3, 5, 7)]]
    columns = list(dict.fromkeys(columns))
    ids = rain = raw = level = risk = None
    frames = []
    for j, day in enumerate(days):
        features = pd.read_parquet(live_dir / day.isoformat() / "features_D0.parquet")
        alerts = pd.read_parquet(live_dir / day.isoformat() / "alerts.parquet", columns=["cell_id", "raw_level", "level", "risk"])
        if ids is None:
            ids = features["cell_id"].to_numpy(dtype=np.int64)
            n = len(ids)
            rain = {w: np.full((n, len(days)), np.nan) for w in RAIN_WINDOWS}
            raw, level = (np.zeros((n, len(days)), dtype=np.int8) for _ in range(2))
            risk = np.full((n, len(days)), np.nan)
        if not (np.array_equal(features["cell_id"].to_numpy(), ids) and np.array_equal(alerts["cell_id"].to_numpy(), ids)):
            raise ValueError(f"the cells of {day} differ from those of {days[0]}")
        scorable = live_run.scorable_mask(features, model.columns)
        for w in RAIN_WINDOWS:
            rain[w][:, j] = features[f"irain_acc_{w}"].to_numpy(dtype=np.float64)
        raw[:, j], level[:, j] = alerts["raw_level"].to_numpy(), alerts["level"].to_numpy()
        risk[:, j] = np.where(scorable, alerts["risk"].to_numpy(dtype=np.float64), np.nan)
        frames.append(features[columns] if j == len(days) - 1 else None)
    return {"ids": ids, "rain": rain, "raw": raw, "published": level, "risk": risk, "last": frames[-1], "days": days}


def replay_counts(base: np.ndarray, other: np.ndarray) -> dict:
    """Per day, the cells at each level and the cells lowered / raised against `base` (both (cells, days))."""
    return {"levels": [{lv.level_name(L): int((other[:, j] == L).sum()) for L in range(4)} for j in range(other.shape[1])],
            "lowered": [int((other[:, j] < base[:, j]).sum()) for j in range(other.shape[1])],
            "raised": [int((other[:, j] > base[:, j]).sum()) for j in range(other.shape[1])]}


def replay_classes(last: pd.DataFrame, acc3: np.ndarray, base_level: np.ndarray) -> dict[str, np.ndarray]:
    """Cells of the last replay day in the descriptive classes (alert = baseline level, per the spec 14.5 counts)."""
    return {"flat_cell_alerts (slope_mean<5 deg, Watch+)": (last["stat_slope_mean"].to_numpy() < FLAT_SLOPE_DEG) & (base_level >= lv.WATCH),
            "low_elevation_alerts (elev_mean<100 m, Watch+)": (last["stat_elev_mean"].to_numpy() < LOW_ELEVATION_M) & (base_level >= lv.WATCH),
            "flat_cell_warning_plus": (last["stat_slope_mean"].to_numpy() < FLAT_SLOPE_DEG) & (base_level >= lv.WARNING),
            f"low_rain_warning_plus (3-day IMERG<{LOW_RAIN_MM:g} mm)": (acc3 < LOW_RAIN_MM) & (base_level >= lv.WARNING)}


def named_cells(last: pd.DataFrame, rain: dict, levels: dict[str, np.ndarray], published: np.ndarray, limit: int = 40) -> dict:
    """Rows of the Kanyakumari cell and of the cells within the Jammu box that are Watch or above in the published table."""
    lat0, lon0, half = JAMMU
    lat, lon = last["lat"].to_numpy(), last["lon"].to_numpy()
    jammu = (np.abs(lat - lat0) <= half) & (np.abs(lon - lon0) <= half) & (published[:, -1] >= lv.WATCH)
    kanya = last["cell_id"].to_numpy() == KANYAKUMARI_CELL

    def rows(indices):
        out = []
        for i in indices:
            out.append({"cell_id": int(last["cell_id"].iloc[i]), "lat": float(lat[i]), "lon": float(lon[i]),
                        "slope_mean": float(last["stat_slope_mean"].iloc[i]), "slope_p90": float(last["stat_slope_p90"].iloc[i]),
                        "relief": float(last["stat_relief"].iloc[i]), "elev_mean": float(last["stat_elev_mean"].iloc[i]),
                        "acc_1": float(rain[1][i, -1]), "acc_3": float(rain[3][i, -1]), "acc_7": float(rain[7][i, -1]),
                        "published_levels": published[i].tolist(), **{f"{name}_levels": lev[i].tolist() for name, lev in levels.items()}})
        return out
    cells = np.flatnonzero(jammu)
    listed = cells[np.argsort(-published[cells, -1], kind="stable")][:limit]
    return {"kanyakumari": rows(np.flatnonzero(kanya)),
            "jammu_box": {"lat": lat0, "lon": lon0, "half_width_deg": half, "watch_plus_cells": int(jammu.sum()),
                          "listed": rows(listed)}}


def run_replay(cfg: dict, directory: Path, say=print) -> dict:
    started = time.perf_counter()
    dev = json.loads((Path(directory) / DEV_FILE).read_text(encoding="utf-8"))
    candidates = {n: Candidate.from_dict(c) for n, c in dev["conditions"].items()}
    chosen = dev["terrain"]["choice"]["variable"]
    candidates.update(terrain_alternatives(dev["terrain"]["floors_5th_percentile"], chosen))
    model, config, base_rules = load_inputs(cfg)
    live_dir = live_run.live_root(cfg)
    days = replay_days(live_dir)
    say(f"replaying {days[0]}..{days[-1]} ({len(days)} days) from the stored live tables")
    data = load_replay(live_dir, days, model)
    last = data["last"]
    regions = last["region"].to_numpy()
    thresholds = live_run.card_thresholds(model, regions)
    by_region = {r: thresholds.of(r) for r in np.unique(regions)}
    stamps = pd.DatetimeIndex(pd.to_datetime(days)).to_numpy()
    base_ok = D.rain_ok_arrays(data["rain"], base_rules.rain) if hasattr(D, "rain_ok_arrays") else \
        base_rules.rain.passes_arrays({w: data["rain"][w] for w in base_rules.rain.minimum_mm})
    levels = {}
    for name, candidate in candidates.items():
        flat = flat_cells(last, last, candidate)
        levels[name] = candidate_levels(data["raw"], data["risk"], data["rain"], base_ok, flat, candidate, base_rules, regions,
                                        data["ids"], stamps, by_region, config)
    first_report = days.index(REPLAY_REPORT_FROM)
    published, base = data["published"], levels["baseline"]
    agree = (base == published)
    check = {"days": [d.isoformat() for d in days], "cells": int(len(data["ids"])),
             "baseline_equals_published_per_day": [int(agree[:, j].sum()) for j in range(len(days))],
             "baseline_differs_from_published_from_report_start": int((~agree[:, first_report:]).sum())}
    acc3 = data["rain"][3][:, -1]
    classes = replay_classes(last, acc3, base[:, -1])
    effect = {}
    for name in candidates:
        if name == "baseline":
            continue
        counts = replay_counts(base, levels[name])
        changed = {}
        for cname, mask in classes.items():
            changed[cname] = {"alerts": int(mask.sum()), "lowered_by_rule": int((mask & (levels[name][:, -1] < base[:, -1])).sum())}
        transitions = {f"{lv.level_name(a)}->{lv.level_name(b)}": int(((base[:, -1] == a) & (levels[name][:, -1] == b)).sum())
                       for a in range(1, 4) for b in range(a)}
        effect[name] = {**counts, "last_day_transitions": transitions, "last_day_classes": changed}
    result = {"protocol": {"days": check["days"], "report_from": REPLAY_REPORT_FROM.isoformat(), "written_to_data_live": False,
                           "chain": "published raw level and point risk, the section 11 hold windows, one continuous chain",
                           "low_rain_mm": LOW_RAIN_MM},
              "baseline_check": check, "conditions": {n: c.to_dict() for n, c in candidates.items()},
              "baseline": replay_counts(base, base), "published_levels": replay_counts(published, published)["levels"],
              "effect": effect,
              "named_cells": named_cells(last, data["rain"], {n: lev for n, lev in levels.items()}, published),
              "seconds": time.perf_counter() - started}
    write_json(Path(directory) / REPLAY_FILE, result)
    say(f"wrote {hm.display_path(Path(directory) / REPLAY_FILE)}")
    return result


# -------------------------------------------------------------------------------------------------- report

def _read(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def pct(value, digits: int = 1) -> str:
    return "n/a" if value is None else f"{100 * value:.{digits}f}%"


def num(value, digits: int = 2) -> str:
    return "n/a" if value is None else f"{value:,.{digits}f}"


def detect(entry: dict) -> str:
    return f"{entry['hits']}/{entry['n']}"


def conditions_table(evaluation: dict) -> str:
    rows = []
    for name, summary in evaluation["summaries"].items():
        for level, entry in summary["levels"].items():
            rows.append([name, level, detect(entry["events_detected"]), f"{entry['alert_cell_days']:,}", pct(entry["alert_share"]),
                         f"{entry['alert_cell_days_below_terrain_floor']:,}", num(entry["events_per_1000_alert_cell_days"], 4)])
    return _table(["condition", "level or above", "events detected", "alert cell-days", "share of cell-days",
                   "cell-days on cells below the terrain floor", "events per 1,000 alert cell-days"], rows)


def change_table(evaluation: dict) -> str:
    rows = []
    for name, change in evaluation["changes"].items():
        scale = evaluation["summaries"][name]["scale"]
        for level, entry in change.items():
            r = entry["removed_per_day"]
            d = entry["detection_change"]
            removed = entry["alert_cell_days_removed"]
            dense = 1000 * entry["events_lost"] / (removed * scale) if removed > 0 else None
            rows.append([name, level, f"{removed:,} ({pct(entry['removed_share'])})",
                         f"{num(r['value'], 1)} [{num(r['lo'], 1)}, {num(r['hi'], 1)}]", str(entry["events_lost"]),
                         num(dense, 4), f"{100 * d['value']:+.1f} pp [{100 * d['lo']:+.1f}, {100 * d['hi']:+.1f}]"])
    return _table(["condition", "level or above", "cell-days removed", "removed per day, paired bootstrap 95% CI", "events lost",
                   "events lost per 1,000 removed cell-days", "detection change (paired bootstrap 95% CI)"], rows)


def decision_table(evaluation: dict) -> str:
    rows = []
    for name, decision in evaluation["decisions"].items():
        c = decision["checks"]
        rows.append([name, str(decision["events_lost"]["Watch"]), str(decision["events_lost"]["Warning"]),
                     str(decision["events_lost"]["Emergency"]), "yes" if c["warning_plus_cell_day_reduction_ci_excludes_0"] else "no",
                     "ADOPT" if decision["adopt"] else "not adopted"])
    return _table(["condition", "Watch+ lost", "Warning+ lost", "Emergency lost", "Warning+ reduction CI excludes 0", "decision"], rows)


def build(directory: Path) -> dict:
    dev = _read(Path(directory) / DEV_FILE)
    held = _read(Path(directory) / HELDOUT_FILE)
    replay = _read(Path(directory) / REPLAY_FILE)
    return {"created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "spec": "docs/superpowers/specs/"
            "2026-10-14-aetherguard-live-global-design.md section 14", "development": dev, "heldout_2018": held, "live_replay": replay,
            "candidate_rules": hm.display_path(PROJECT_ROOT / CANDIDATE_RULES)}


def markdown(report: dict) -> str:
    dev, held, replay = report["development"], report["heldout_2018"], report["live_replay"]
    terrain, floors = dev["terrain"], dev["rain_floors"]
    lines = ["# Precision rules: terrain plausibility and per-level rain floors", "",
             f"Generated {report['created_utc']}. Design, floors' definition and the adoption criterion: {report['spec']} "
             "(written before any 2018 number of this study). Analysis only: the frozen model, the live run, `postrules.py` and the "
             f"published tables are unchanged; the candidate rules are in `{report['candidate_rules']}` and are not wired anywhere. "
             "Every number is read from the result files of `data/processed/alerts/precision_study/`.", ""]
    held_eval, dev_eval = held["evaluation"], dev["evaluation"]
    last = replay["effect"]
    lines += ["## Summary", "",
              f"* Terrain variable chosen by the pre-declared rule: {terrain['choice']['variable']} < {terrain['choice']['minimum']:.1f} "
              f"(removes {pct(terrain['choice']['removed_share'])} of the development negative Warning+ cell-days).",
              f"* 2018 decision (spec 14.6): adoptable {held_eval['adoptable'] or 'none'}; recommended {held_eval['recommended'] or 'none'}. "
              + "; ".join(f"{n}: {d['events_lost']['Warning']} Warning+ and {d['events_lost']['Emergency']} Emergency events lost, "
                          f"{pct(held_eval['changes'][n]['Warning']['removed_share'])} of Warning+ cell-days removed"
                          for n, d in held_eval["decisions"].items()) + ".",
              f"* Development panels (in-sample for the floors): adoptable {dev_eval['adoptable'] or 'none'}; "
              + "; ".join(f"{n} loses {d['events_lost']['Warning']} Warning+ and {d['events_lost']['Emergency']} Emergency of "
                          f"{dev_eval['summaries']['baseline']['levels']['Warning']['events_detected']['hits']} / "
                          f"{dev_eval['summaries']['baseline']['levels']['Emergency']['events_detected']['hits']}"
                          for n, d in dev_eval["decisions"].items()) + ".",
              "* Live 2026-10-24 (offline): cells lowered by each condition: "
              + "; ".join(f"{n} {e['lowered'][-1]}" for n, e in last.items()) + ".",
              "* The criterion is a loss and significance test, not a precision gain: compare the 'events lost per 1,000 removed cell-days' "
              "column with the baseline 'events per 1,000 alert cell-days' to see how selective the removed cell-days are.", ""]
    lines += ["## Floors chosen on the development years (2007-2017)", "",
              f"Development positives (in-domain, train + validation samples): {dev['protocol']['development_positives']}. Baseline "
              f"check (the study's section 11 levels equal `hardening_dev.season_levels` on every season): "
              f"{'passed' if dev['baseline_check']['identical'] else 'FAILED'} ({dev['baseline_check']['identical_seasons']}/"
              f"{dev['baseline_check']['seasons']} seasons).", "",
              "### Rule T: which terrain variable", ""]
    rows = [[v, num(e["floor"], 3), f"{e['negative_alert_cell_days']:,}", f"{e['removed']:,}", pct(e["removed_share"]),
             f"{e['positive_removed']}/{e['positive_alert_cell_days']}"] for v, e in terrain["removal"].items()]
    lines += [_table(["variable", "5th-percentile floor", "negative Warning+ point cell-days", "below the floor", "share removed",
                      "event cell-days (Warning+ point) below the floor"], rows), "",
              f"Chosen: **{terrain['choice']['variable']} < {terrain['choice']['minimum']:.3f}**, which removes "
              f"{pct(terrain['choice']['removed_share'])} of the development negative Warning+ point cell-days (sampled universe "
              "cells; the universe is already limited to a mean slope of at least the frozen slope floor).", "",
              "### Rule R: per-level rain floors (5th percentile over development positives reaching the level)", ""]
    rows = [[level, str(e["n_positives"]), *[num(e["floor_mm"][str(w)], 3) for w in RAIN_WINDOWS],
             ", ".join(str(w) for w in e["windows_used"]) or "none (vacuous)", e["rule"] or "n/a"] for level, e in floors.items()]
    lines += [_table(["level", "positives", "1-day mm", "3-day mm", "7-day mm", "windows used", "rule"], rows), "",
              f"Conditions evaluated: {', '.join(dev['conditions'])}.", ""]
    for title, block, key in (("Development panels (out of fold; the floors were selected on them, so this is in-sample for the floors)",
                               dev["evaluation"], "development"), ("2018, the single look", held["evaluation"], "2018")):
        lines += [f"## {title}", ""]
        if key == "2018":
            lines += [f"2018 operational panel: {held['protocol']['cells']} cells, {held['protocol']['days']} days, "
                      f"{held['protocol']['events']} events. Baseline equals the published `evaluation.json` hits "
                      f"({held['evaluation_json_hits']}): {held['baseline_matches_evaluation_json']}.", ""]
        else:
            lines += [f"Cell-day counts are of the {dev['protocol']['sampled_universe_cells']:,} sampled universe cells (the precision "
                      f"proxy scales them to all {dev['protocol']['universe_cells']:,}).", ""]
        lines += [conditions_table(block), "", "Change against the section 11 baseline:", "", change_table(block), ""]
        lines += ["Pre-declared criterion (spec 14.6):", "", decision_table(block), "",
                  f"Adoptable: {block['adoptable'] or 'none'}; recommended: {block['recommended'] or 'none'}.", ""]
    alt = dev["evaluation_terrain_alternatives"]
    lines += ["## Terrain variable sensitivity (development panels only; NOT evaluated on 2018)", "",
              "The two terrain variables that the pre-declared rule did not choose, at their own development floors. Descriptive: the "
              "choice above stands and 2018 was not looked at for these.", "", conditions_table(alt), "", change_table(alt), ""]
    lines += ["## Live replay 2026-10-16..2026-10-24 (offline, nothing written to `data/live`)", "",
              f"A continuous chain from {replay['protocol']['days'][0]} through the stored published raw level and point risk. Baseline chain "
              f"equals the published levels except on {replay['baseline_check']['baseline_differs_from_published_from_report_start']} "
              "cell-days from 2026-10-16.", ""]
    rows = []
    for name, effect in replay["effect"].items():
        rows.append([name, str(effect["lowered"][-1]), json.dumps(effect["last_day_transitions"]),
                     "; ".join(f"{k}: {v['lowered_by_rule']}/{v['alerts']}" for k, v in effect["last_day_classes"].items())])
    lines += [_table(["condition", "cells lowered on 2026-10-24", "level transitions on 2026-10-24", "alerts lowered / alerts, by class"], rows), "",
              "Named cells (levels per replay day, oldest first):", ""]
    named = replay["named_cells"]
    rows = []
    for cell in named["kanyakumari"] + named["jammu_box"]["listed"][:15]:
        rows.append([str(cell["cell_id"]), f"{cell['lat']:.3f}N {cell['lon']:.3f}E",
                     f"slope {cell['slope_mean']:.1f}/p90 {cell['slope_p90']:.1f}, relief {cell['relief']:.0f}, elev {cell['elev_mean']:.0f}",
                     f"{cell['acc_1']:.1f}/{cell['acc_3']:.1f}/{cell['acc_7']:.1f}", str(cell["published_levels"][-1]),
                     *[str(cell[f"{n}_levels"][-1]) for n in replay["effect"]]])
    lines += [_table(["cell", "position", "terrain", "IMERG 1/3/7 mm", "published", *replay["effect"]], rows), "",
              f"Jammu box (33.1N 74.7E +/- 0.25): {named['jammu_box']['watch_plus_cells']} Watch+ cells in the published table.", ""]
    diag = dev["diagnosis"]
    lines += ["## Diagnosis (not a rule): low-elevation positives and the model's dependence on elevation", ""]
    low = diag["positives_on_low_terrain"]
    rows = [[k, str(v["n"]), f"{v['flat']} ({pct(v['flat_share'])})", f"{v['low']} ({pct(v['low_share'])})",
             f"{v['flat_or_low']} ({pct(v['flat_or_low_share'])})"] for group in ("by_region", "by_source", "by_accuracy")
            for k, v in low[group].items()]
    rows.insert(0, ["all", str(low["all"]["n"]), f"{low['all']['flat']} ({pct(low['all']['flat_share'])})",
                    f"{low['all']['low']} ({pct(low['all']['low_share'])})",
                    f"{low['all']['flat_or_low']} ({pct(low['all']['flat_or_low_share'])})"])
    lines += [f"Development positives on cells with {diag['definitions']['flat']} or {diag['definitions']['low']}:", "",
              _table(["group", "positives", "mean slope < 5", "mean elevation < 100 m", "either"], rows), "",
              "Positive share of the development samples by elevation band:", "",
              _table(["mean elevation (m)", "positives", "negatives", "positive share"],
                     [[b["band_m"], str(b["positives"]), str(b["negatives"]), pct(b["positive_share"], 2)] for b in diag["elevation_bands"]]), ""]
    rows = []
    for name, pd_ in diag["elevation_dependence"].items():
        if not isinstance(pd_, dict) or "grid_m" not in pd_:
            continue
        rows.append([name, str(pd_["n_rows"]), "yes" if pd_["decreasing_up_to_limit"] else "no",
                     f"{pd_['pd_logodds_50m_minus_300m']:+.2f}", f"{pd_['pd_logodds_50m_minus_1000m']:+.2f}",
                     pct(pd_["ice_share_50m_above_300m"]), f"{pd_['argmax_grid_m']:g}"])
    lines += [f"Partial dependence of the frozen v3-live model on `stat_elev_mean` (seeded sample, seed {diag['definitions']['pd_sample']['seed']}):",
              "", _table(["rows", "n", f"PD decreasing up to {LOW_ELEVATION_PD_LIMIT_M:g} m", "PD(50 m) - PD(300 m), log-odds",
                         "PD(50 m) - PD(1000 m)", "ICE curves with 50 m above 300 m", "elevation of the PD maximum (m)"], rows), "",
              f"Monotone constraint on `stat_elev_mean` in the model: {diag['monotone_constraint_on_elevation']} (0 = none).", ""]
    grid = diag["elevation_dependence"]["all"]
    lines += [_table(["elevation (m)", *[f"{g:g}" for g in grid["grid_m"]]],
                     [["PD log-odds, all rows", *[f"{v:.2f}" for v in grid["pd_logodds"]]]]), ""]
    lines += ["## Limits", "",
              "* The development evaluation is in-sample for the floors; only 2018 decides, and it is one season with 56 events.",
              "* The universe is limited to cells with a mean slope above the frozen floor, so the dev and 2018 counts of 'cells below "
              "the terrain floor' describe that universe, not the whole grid.",
              "* Alert cell-days are a false-alarm proxy (events are rare), not a verified count of false alarms.",
              f"* Runtime of the runs: dev {dev['seconds']:.0f} s, 2018 {held['seconds']:.0f} s, replay {replay['seconds']:.0f} s.", ""]
    return "\n".join(lines)


def write_report(directory: Path, out: Path, say=print) -> None:
    report = build(directory)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / f"{REPORT_STEM}.json", report)
    (out / f"{REPORT_STEM}.md").write_text(markdown(report), encoding="utf-8")
    say(f"wrote {hm.display_path(out / (REPORT_STEM + '.md'))}")


# ------------------------------------------------------------------------------------------------------ CLI

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m aetherguard.live.precision_study", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name, text in (("dev", "floors and terrain variable on the development panels, and the diagnosis"),
                       ("heldout", "the one 2018 evaluation and the adoption decision"),
                       ("live-replay", "the live days offline from the stored tables"),
                       ("report", f"write reports/{REPORT_STEM}.{{md,json}}")):
        p = sub.add_parser(name, help=text)
        p.add_argument("--dir", type=Path, default=None, help=f"result directory (default data/processed/alerts/{OUT_DIR})")
        if name == "report":
            p.add_argument("--out", type=Path, default=PROJECT_ROOT / "reports")
    args = parser.parse_args(argv)
    directory = args.dir or out_dir()
    say = lambda m: print(m, flush=True)
    try:
        if args.command == "report":
            write_report(directory, args.out, say)
        else:
            cfg = live_run.load_run_config()
            {"dev": run_dev, "heldout": run_heldout, "live-replay": run_replay}[args.command](cfg, directory, say)
    except (live_run.LiveRunError, ValueError, OSError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
