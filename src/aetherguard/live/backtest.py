"""Operational backtest of the frozen v3-live model: what the daily live run would have said, day by day.

    python -m aetherguard.live.backtest [--set season_2018|window_2023|kerala_2018|wayanad_2024|all]
                                        [--start YYYY-MM-DD --end YYYY-MM-DD] [--model data/processed/hazard/model_v3_live]
                                        [--out reports]

For every IMD day D of a window each candidate cell is scored twice, with the same frozen model:

* **operational** features, built exactly as the live run builds them (spec section 10) through `live.sources.LiveRainView`
  and `live.forecast_features.lead_features`: Late for UTC days up to D-2, Early (identity map) for UTC D-1, the 00-03 UTC
  rain of D from the GFS fallback chain (the 00Z cycle of D when the local archive has it, else persistence from UTC D-1,
  `persist_d1`), and nothing issued after the 11:00 IST cut-off of D. Local stores only: no network is touched, so a
  day whose Early D-1 granule is not on disk has no operational features and is reported as unscored, not filled.
* **training-style** features: the Late run for every UTC day including the whole of UTC D (0.875 UTC(D-1) + 0.125
  UTC(D)), the construction the model was trained on.

The difference between the two is the train/live gap the section-10 substitutions cause. Per variant the report gives
the frozen model's own Watch rule (raw score at or above the frozen recall-first threshold, the rule of the test_2018
evaluation) and the alert levels (risk against the card thresholds, `uncertain_high`, hysteresis of the live state),
detection and lead time of the labelled events, the share of cell-days at Watch or above per day, and which input
product supplied each day. The alert engine's source-agreement, station and blind-escalation rules are not applied: the
IMD real-time archive and the gauge history of the past are not on disk.

Sets: `season_2018` (1 Jun - 30 Sep 2018, the universe cells, test_2018 positives), `window_2023` (the 2023 India window
cells), `kerala_2018` (case cells, 1-20 Aug 2018) and `wayanad_2024` (case box, 15 Jul - 5 Aug 2024).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime, time as clock, timedelta, timezone
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from ..alerts import levels as lv
from ..alerts.config import DEFAULT_UNCERTAIN_PERCENTILE, alerts_settings
from ..alerts.config import load_config_file as load_alert_config
from ..cases import openmeteo as om
from ..cases import score as case_score
from ..config import PROJECT_ROOT, data_root, load_config
from ..features import imerg_build
from ..features import imerg_features as F
from ..features.compute import ClimTable
from ..features.sampling import candidate_cells
from ..grid import neighbours
from ..hazard import evaluate as ev
from ..hazard import model as hm
from ..ingest import imerg as imerg_mod
from ..manifest import sha256_file
from . import forecast_features
from . import run as live_run
from .sources import (PERSIST, FetchContext, ImergSource, LiveRainView, early_mapping, make_context, project_path,
                      read_accumulation)

UTC = timezone.utc
SCHEMA = 1
OPERATIONAL, TRAINING_STYLE = "operational", "training_style"
VARIANTS = (OPERATIONAL, TRAINING_STYLE)
RULES = ("raw_watch", "engine")
CORE_COLUMN = live_run.CORE_COLUMN
WARMUP_DAYS = 7                      # days scored before a window so the hysteresis state is not a cold start
LOOKBACK_DAYS = 7
GFS_CYCLE_HOUR = 0
ARCHIVE_TAIL_FILE = "f003_apcp0h.grib2"      # the cumulative 0-3 h APCP of the 00Z cycle = 00-03 UTC of the same date
DEFAULT_MODEL_CONFIG = "configs/hazard_v3.yaml"
BOOTSTRAP = {"n": 2000, "seed": 31337, "level": 0.95}


# ---------------------------------------------------------------------------------------------- inputs

@dataclass(frozen=True)
class TailResult:
    """The 00-03 UTC rain of IMD day D (mm on the IMERG grid, None for persistence), the product behind it and why."""
    first_hours: np.ndarray | None
    product: str
    note: str | None = None


@dataclass
class Stores:
    """Everything a backtest day reads. `late` / `early` are `ImergSource`s over local stores; `tail(day, ctx)` is the
    GFS fallback chain restricted to what is on disk."""
    cfg: dict
    late: ImergSource
    early: ImergSource
    clim: ClimTable
    tail: Callable[[date, FetchContext], TailResult]


def archive_tail(root: Path, bbox: dict, latency_h: float) -> Callable[[date, FetchContext], TailResult]:
    """The 00-03 UTC tail from the local GFS archive (`<root>/raw/gfs/archive/<YYYYMMDD>00/f003_apcp0h.grib2`, 2021
    June-September onward): the 00Z cycle of D when it is on disk and was issued before the cut-off, else persistence
    from UTC D-1. The 18Z / 12Z cycles of D-1 of the live chain are not in the local archive."""
    def tail(day: date, ctx: FetchContext) -> TailResult:
        cycle = datetime.combine(day, clock(GFS_CYCLE_HOUR), tzinfo=UTC)
        path = Path(root) / "raw" / "gfs" / "archive" / f"{cycle:%Y%m%d%H}" / ARCHIVE_TAIL_FILE
        if cycle + timedelta(hours=latency_h) > ctx.horizon:
            return TailResult(None, PERSIST, "00Z cycle issued after the cut-off")
        if not path.is_file():
            return TailResult(None, PERSIST, "no 00Z cycle in the local GFS archive")
        return TailResult(read_accumulation(path, 3, None, 0, bbox), "gfs_00z_0_3h")
    return tail


def default_clim(cfg: dict, store, flat_pixels: np.ndarray, cache: Path) -> ClimTable:
    """Train-range IMERG climatology of the pixels (the training pipeline's own definition), cached in `cache`."""
    window = imerg_build.build_config()["climatology"]
    pixels = np.unique(flat_pixels[flat_pixels >= 0])
    if cache.is_file():
        with np.load(cache, allow_pickle=False) as data:
            if (str(data["first_day"]), str(data["last_day"])) == (window["first_day"], window["last_day"]) \
                    and np.isin(pixels, data["pix"]).all():
                return ClimTable(data["pix"], data["values"])
    clim = F.imerg_climatology(store, pixels, date.fromisoformat(window["first_day"]),
                               date.fromisoformat(window["last_day"]))
    cache.parent.mkdir(parents=True, exist_ok=True)
    part = cache.with_name(cache.name + ".part.npz")
    np.savez(part, pix=clim.pix, values=clim.values, first_day=window["first_day"], last_day=window["last_day"])
    part.replace(cache)
    return clim


def build_stores(cells: pd.DataFrame, cfg: dict | None = None, root: Path | None = None) -> Stores:
    """The real local stores for `cells`: IMERG Late and Early on disk, the local GFS archive, no network."""
    cfg = cfg or live_run.load_run_config()
    root = Path(root) if root is not None else data_root()
    processed = project_path(cfg["imerg"]["processed_dir"])
    latency = cfg["imerg"]["latency_h"]
    late_store, early_store = imerg_mod.ImergStore(processed, "late"), imerg_mod.ImergStore(processed, "early")
    mapping = early_mapping(cfg)
    late = ImergSource("late", late_store, latency_h=latency["late"], window_days=cfg["imerg"]["late_window_days"])
    early = ImergSource("early", early_store, latency_h=latency["early"], window_days=cfg["imerg"]["late_window_days"],
                        mapping=mapping)
    bbox = load_config("live")["domain_bbox"]
    clim = default_clim(cfg, late_store, F.cell_pixels(cells["cell_id"].to_numpy(dtype=np.int64)),
                        root / "processed" / "live_backtest" / "imerg_climatology.npz")
    return Stores(cfg, late, early, clim, archive_tail(root, bbox, cfg["gfs"]["first_hours_latency_h"]))


# ----------------------------------------------------------------------------------------------- features

def operational_view(day: date, stores: Stores) -> tuple[LiveRainView, TailResult]:
    """The live rain view of IMD day `day` as the 11:00 IST run saw it: sources issued after the cut-off are unusable."""
    ctx = make_context(day, stores.cfg, None, True)
    tail = stores.tail(day, ctx)
    return LiveRainView(day, stores.late, stores.early, ctx, tail.first_hours, tail.product), tail


def operational_features(day: date, cells: pd.DataFrame, stores: Stores) -> pd.DataFrame:
    """The `irain`, `iapi`, `inbr` features of `cells` for IMD day `day` from what existed at the 11:00 IST run of that
    day: Late through UTC D-2, Early for UTC D-1, the GFS (or persisted) 00-03 UTC tail, nothing later. Same index as
    `cells`; NaN where an input day is missing."""
    view, _ = operational_view(day, stores)
    return forecast_features.lead_features(cells, day, 0, view, None, stores.clim)


def training_style_features(day: date, cells: pd.DataFrame, stores: Stores) -> pd.DataFrame:
    """The same features built as the model was trained: the Late run for every UTC day through the whole of UTC D."""
    return forecast_features.lead_features(cells, day, 0, stores.late.store, None, stores.clim)


# --------------------------------------------------------------------------------------------- scoring

@dataclass
class Panel:
    """Scores of one variant: arrays of shape (cells, days). `upper` holds further percentiles of the calibrated ensemble
    (keyed by percentile) for an `uncertain_high` rule that does not use the 90th, `risk_hi`."""
    raw: np.ndarray
    risk: np.ndarray
    risk_hi: np.ndarray
    upper: dict[float, np.ndarray] = field(default_factory=dict)


def new_panel(n_cells: int, n_days: int, percentiles=()) -> Panel:
    return Panel(np.full((n_cells, n_days), np.nan, dtype=np.float32), np.full((n_cells, n_days), np.nan),
                 np.full((n_cells, n_days), np.nan), {p: np.full((n_cells, n_days), np.nan) for p in percentiles})


def score_into(panel: Panel, column: int, model, frame: pd.DataFrame, percentiles=()) -> int:
    """Score the rows of `frame` whose core rain input is known into column `column`; returns how many were scored."""
    scorable = np.isfinite(frame[CORE_COLUMN].to_numpy(dtype=np.float64))
    if scorable.any():
        rows = frame[scorable]
        scored = model.score(rows)
        panel.raw[scorable, column] = model.raw_score(rows)
        panel.risk[scorable, column] = scored["risk"].to_numpy()
        panel.risk_hi[scorable, column] = scored["risk_hi"].to_numpy()
        for percentile in percentiles:
            panel.upper[percentile][scorable, column] = model.ensemble_percentile(rows, percentile)
    return int(scorable.sum())


def day_range(first: date, last: date) -> list[date]:
    return [first + timedelta(days=k) for k in range((last - first).days + 1)]


def score_days(days: list[date], cells: pd.DataFrame, model, stores: Stores, progress=None, percentiles=()
               ) -> tuple[dict[str, Panel], list[dict]]:
    """Both variants' panels for `days`, and one record per day: the input product behind IMD day D and D-1, the GFS
    tail used, how many cells were scorable, and how far the two variants' features and scores are apart."""
    panels = {v: new_panel(len(cells), len(days), percentiles) for v in VARIANTS}
    records = []
    started = time.perf_counter()
    for j, day in enumerate(days):
        view, tail = operational_view(day, stores)
        inputs = view.imd_day_inputs()
        features = {OPERATIONAL: forecast_features.lead_features(cells, day, 0, view, None, stores.clim),
                    TRAINING_STYLE: training_style_features(day, cells, stores)}
        scored = {v: score_into(panels[v], j, model, pd.concat([cells, features[v]], axis=1), percentiles)
                  for v in VARIANTS}
        both = np.isfinite(panels[OPERATIONAL].raw[:, j]) & np.isfinite(panels[TRAINING_STYLE].raw[:, j])
        gap = {}
        for column in ("irain_acc_1", "irain_acc_3"):
            delta = np.abs(features[OPERATIONAL][column].to_numpy(dtype=np.float64)
                           - features[TRAINING_STYLE][column].to_numpy(dtype=np.float64))
            gap[f"mean_abs_diff_{column}_mm"] = float(np.nanmean(delta)) if np.isfinite(delta).any() else None
        gap["raw_rank_correlation"] = rank_correlation(panels[OPERATIONAL].raw[both, j],
                                                       panels[TRAINING_STYLE].raw[both, j])
        records.append({"date": day.isoformat(), "input_D": inputs["D"], "input_D-1": inputs["D-1"],
                        "utc_D-1_product": view.product(day - timedelta(days=1)), "tail_product": tail.product,
                        "tail_note": tail.note, "scored_cells": scored, "cells": len(cells), **gap})
        if progress and (j % 10 == 0 or j == len(days) - 1):
            progress(f"  {day} ({j + 1}/{len(days)}) {time.perf_counter() - started:.0f}s")
    return panels, records


def rank_correlation(a: np.ndarray, b: np.ndarray) -> float | None:
    """Spearman correlation of two score vectors over the same cells (None when fewer than 3 or constant)."""
    if len(a) < 3:
        return None
    ra, rb = pd.Series(a).rank().to_numpy(), pd.Series(b).rank().to_numpy()
    if ra.std() == 0 or rb.std() == 0:
        return None
    return float(np.corrcoef(ra, rb)[0, 1])


# ------------------------------------------------------------------------------------------------ levels

def engine_levels(panel: Panel, cells: pd.DataFrame, days: list[date], thresholds: dict[str, lv.Thresholds],
                  exit_factor: float, exit_days: int, upper: np.ndarray | None = None) -> np.ndarray:
    """Alert level 0-3 per (cell, day): risk against the thresholds of the cell's region (`thresholds` maps region to
    Thresholds, one entry `"*"` applies to every cell), `uncertain_high`, then the hysteresis of the live state run
    over the consecutive days. `upper` (cells, days) replaces the panel's `risk_hi` as the bound `uncertain_high` tests.
    A cell-day without a score is level 0 raw and never steps a held level down."""
    upper = panel.risk_hi if upper is None else upper
    region = cells["region"].to_numpy()
    out = np.zeros(panel.risk.shape, dtype=np.int8)
    stamps = pd.DatetimeIndex(pd.to_datetime(days))
    for name, thr in thresholds.items():
        rows = np.flatnonzero(np.ones(len(cells), dtype=bool) if name == "*" else region == name)
        if not len(rows):
            continue
        risk = panel.risk[rows]
        raw_level, _ = lv.raw_level(risk, upper[rows], thr)
        ids = np.repeat(cells["cell_id"].to_numpy(dtype=np.int64)[rows], len(days))
        dates = np.tile(stamps.to_numpy(), len(rows))
        held = lv.apply_hysteresis(ids, dates, raw_level.ravel(), risk.ravel(), thr, exit_factor, exit_days)
        out[rows] = held.reshape(raw_level.shape)
    return out


def uncertain_bound(panel: Panel, alert_config) -> np.ndarray:
    """The scores the configured `uncertain_high` rule tests: the 90th percentile (`risk_hi`), another percentile the
    panel holds, or the point risk when the rule is off."""
    percentile = alert_config.uncertain_percentile
    if percentile is None:
        return panel.risk
    if percentile == DEFAULT_UNCERTAIN_PERCENTILE:
        return panel.risk_hi
    if percentile not in panel.upper:
        raise ValueError(f"the scores hold no {percentile:g}th percentile of the ensemble, which the alert configuration "
                         "names; score with percentiles=(...)")
    return panel.upper[percentile]


def configured_percentiles(*alert_configs) -> tuple[float, ...]:
    """The ensemble percentiles beyond `risk_hi` that these alert configurations need scored."""
    return tuple(sorted({c.uncertain_percentile for c in alert_configs} - {None, DEFAULT_UNCERTAIN_PERCENTILE}))


def rule_levels(panel: Panel, cells: pd.DataFrame, days: list[date], model, alert_config, mode: str) -> dict[str, np.ndarray]:
    """Level matrices (cells, days) of the decision rules of one variant: `raw_watch` (0/1: the frozen raw-score Watch
    threshold, the rule of the test evaluation) and `engine` (risk levels with hysteresis; `mode` `region` uses each
    region's risk thresholds, `pooled` compares every cell with the pooled ones as the live runner does)."""
    card = model.card
    watch_raw = float(card["alert_levels"]["watch"]["raw"])
    with np.errstate(invalid="ignore"):
        raw_watch = (panel.raw >= watch_raw).astype(np.int8)
    if mode == "pooled":
        thresholds = {"*": lv.thresholds_from_card(card, alerts_settings()["v1_card_fallback"])}
    else:
        thresholds = lv.card_region_thresholds(card, cells["region"])
    engine = engine_levels(panel, cells, days, thresholds, alert_config.exit_factor, alert_config.exit_days,
                           uncertain_bound(panel, alert_config))
    return {"raw_watch": raw_watch, "engine": engine}


# ---------------------------------------------------------------------------------------------- metrics

def event_outcomes(levels: np.ndarray, scored: np.ndarray, cell_ids: np.ndarray, days: list[date],
                   events: pd.DataFrame) -> pd.DataFrame:
    """One row per labelled event (cell, date): was its own cell / its 3x3 footprint at Watch or above on the event day,
    the lead (event day minus the first Watch+ day within the 7 days up to and including it, 0 = first alert on the
    day) and the consecutive Watch+ days right before it. Days outside the window count as no information.
    `scored` marks the cell-days that have a score; an unscored event is a miss, flagged `scored` false."""
    row_of = {int(c): i for i, c in enumerate(cell_ids)}
    col_of = {pd.Timestamp(d): j for j, d in enumerate(days)}
    rows = []
    for event in events.itertuples():
        cell, day = int(event.cell_id), pd.Timestamp(event.date)
        own = row_of.get(cell)
        footprint = [row_of[c] for c in (cell, *neighbours(cell)) if c in row_of]

        def alert(d: pd.Timestamp, cells_: list[int]) -> bool | None:
            j = col_of.get(d)
            if j is None or not cells_:
                return None
            return bool(levels[cells_, j].max() >= 1)

        entry = {"cell_id": cell, "date": day.date().isoformat(),
                 "scored": bool(own is not None and day in col_of and scored[own, col_of[day]])}
        for label, members in (("own", [] if own is None else [own]), ("footprint", footprint)):
            span = [alert(day - pd.Timedelta(days=back), members) for back in range(LOOKBACK_DAYS, -1, -1)]
            before = 0
            for back in range(1, LOOKBACK_DAYS + 1):
                if alert(day - pd.Timedelta(days=back), members) is not True:
                    break
                before += 1
            first = next((LOOKBACK_DAYS - i for i, state in enumerate(span) if state), None)
            entry[f"{label}_detected"] = bool(span[-1])
            entry[f"{label}_lead_days"] = None if first is None else int(first)
            entry[f"{label}_alert_days_before"] = before
        entry["own_level"] = None if own is None or day not in col_of else int(levels[own, col_of[day]])
        rows.append(entry)
    return pd.DataFrame(rows)


def share_ci(flags, n: int, seed: int, level: float) -> dict:
    """Share of True flags with a percentile-bootstrap CI over the events (NaN when there are no events)."""
    flags = np.asarray(flags, dtype=bool)
    if not len(flags):
        return {"value": None, "lo": None, "hi": None, "n": 0, "hits": 0}
    out = ev.share_with_ci(flags, n, seed, level)
    return {k: out[k] for k in ("value", "lo", "hi", "n", "hits")}


def summarize_events(table: pd.DataFrame) -> dict:
    """Detection shares with bootstrap CIs and lead-time summaries of an `event_outcomes` table."""
    if table.empty:
        return {"n_events": 0}
    boot = BOOTSTRAP
    out = {"n_events": int(len(table)), "n_scored": int(table["scored"].sum()),
           "n_unscored": int((~table["scored"]).sum())}
    for label in ("own", "footprint"):
        detected = table[f"{label}_detected"].to_numpy(dtype=bool)
        scored = table["scored"].to_numpy(dtype=bool)
        leads = table[f"{label}_lead_days"].dropna().astype(float)
        out[label] = {
            "detected_of_all_events": share_ci(detected, boot["n"], boot["seed"], boot["level"]),
            "detected_of_scored_events": share_ci(detected[scored], boot["n"], boot["seed"], boot["level"]),
            "detected_within_7d": share_ci(table[f"{label}_lead_days"].notna().to_numpy(), boot["n"], boot["seed"],
                                           boot["level"]),
            "median_lead_days": float(leads.median()) if len(leads) else None,
            "mean_lead_days": float(leads.mean()) if len(leads) else None,
            "lead_days_counts": {int(k): int(v) for k, v in leads.value_counts().sort_index().items()},
            "median_alert_days_before": float(table[f"{label}_alert_days_before"].median())}
    return out


def mean_ci(values: np.ndarray) -> dict:
    """Mean over days with a seeded percentile bootstrap over the days (days are the independent unit)."""
    values = np.asarray(values, dtype=np.float64)
    values = values[np.isfinite(values)]
    if not len(values):
        return {"value": None, "lo": None, "hi": None, "n_days": 0}
    boot = BOOTSTRAP
    rng = np.random.default_rng(boot["seed"])
    means = values[rng.integers(0, len(values), (boot["n"], len(values)))].mean(axis=1)
    tail = (1 - boot["level"]) / 2
    return {"value": float(values.mean()), "lo": float(np.quantile(means, tail)), "hi": float(np.quantile(means, 1 - tail)),
            "n_days": int(len(values))}


def alert_share(levels: np.ndarray, scored: np.ndarray, minimum: int = 1) -> np.ndarray:
    """Per day the share of the scored cells at `minimum` or above (NaN on a day with no scored cell)."""
    n = scored.sum(axis=0).astype(np.float64)
    hits = ((levels >= minimum) & scored).sum(axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(n > 0, hits / n, np.nan)


def share_summary(share: np.ndarray, days: list[date]) -> dict:
    finite = share[np.isfinite(share)]
    months = pd.Series(share, index=pd.DatetimeIndex(pd.to_datetime(days))).groupby(lambda t: t.strftime("%Y-%m")).mean()
    return {"mean_daily_share": mean_ci(share), "median_daily_share": float(np.median(finite)) if len(finite) else None,
            "max_daily_share": float(finite.max()) if len(finite) else None,
            "min_daily_share": float(finite.min()) if len(finite) else None,
            "mean_by_month": {k: None if not np.isfinite(v) else float(v) for k, v in months.items()}}


def flapping(levels: np.ndarray, scored: np.ndarray, window: int) -> dict:
    """Level changes between consecutive scored days and Watch+ flaps of a (cell, day) level matrix: a flap is an alert
    that switches off for 1..`window` scored days and on again (counted once per re-activation, as
    `alerts.evaluate.flapping`). Per 1000 scored cell-days."""
    on = (levels >= lv.WATCH) & scored
    changes = int(((levels[:, 1:] != levels[:, :-1]) & scored[:, 1:] & scored[:, :-1]).sum())
    flaps = 0
    for gap in range(1, window + 1):
        span = levels.shape[1] - gap - 1
        if span <= 0:
            break
        again = on[:, :span] & on[:, gap + 1:gap + 1 + span]
        for k in range(1, gap + 1):
            again &= scored[:, k:k + span] & ~on[:, k:k + span]
        flaps += int(again.sum())
    n = int(scored.sum())
    return {"cell_days": n, "n_changes": changes, "n_flaps": flaps,
            "changes_per_1000_cell_days": 1000 * changes / n if n else None,
            "flaps_per_1000_cell_days": 1000 * flaps / n if n else None}


def chance_alert_within(levels: np.ndarray, scored: np.ndarray, lookback: int = LOOKBACK_DAYS) -> float | None:
    """The chance rate behind a lead time: the share of (scored cell, day) pairs whose cell had a Watch+ day among the
    `lookback` days before and the day itself. When this is large, a labelled event is 'alerted within 7 days' by luck."""
    alert = (levels >= 1) & scored
    if alert.shape[1] <= lookback:
        return None
    spans = [alert[:, j - lookback:j + 1].any(axis=1) for j in range(lookback, alert.shape[1])]
    return float(np.mean(spans))


def paired_events(operational: pd.DataFrame, training: pd.DataFrame, label: str = "own") -> dict:
    """How the two variants agree on the same events: both / only operational / only training-style / neither."""
    if operational.empty:
        return {}
    a, b = operational[f"{label}_detected"].to_numpy(bool), training[f"{label}_detected"].to_numpy(bool)
    return {"both": int((a & b).sum()), "only_operational": int((a & ~b).sum()),
            "only_training_style": int((~a & b).sum()), "neither": int((~a & ~b).sum())}


def watch_agreement(a: np.ndarray, b: np.ndarray, scored: np.ndarray) -> float | None:
    """Mean over days of the Jaccard overlap of the Watch+ cell sets of two level matrices (days with no alert in
    either are skipped)."""
    values = []
    for j in range(a.shape[1]):
        wa, wb = (a[:, j] >= 1) & scored[:, j], (b[:, j] >= 1) & scored[:, j]
        union = (wa | wb).sum()
        if union:
            values.append((wa & wb).sum() / union)
    return float(np.mean(values)) if values else None


# ------------------------------------------------------------------------------------------------ sets

@dataclass
class BacktestSet:
    name: str
    start: date
    end: date
    cells: pd.DataFrame                  # cell_id, lat, lon, region, stat_*
    events: pd.DataFrame | None          # cell_id, date of the labelled events (None: none exist)
    kind: str                            # season | window | case_events | case_series
    window_frame: pd.DataFrame | None = None     # window_2023: cell_id, date, kind, is_window_positive_cell
    focus: tuple[float, float] | None = None
    note: str = ""


def features_dir() -> Path:
    return data_root() / "processed" / "features"


def universe_cell_ids() -> np.ndarray:
    """The cells the hazard evaluation's universe is drawn from: own-terrain cells of a region in scope with a mean
    slope at or above the frozen slope floor (`features.sampling.candidate_cells`, floor from the samples manifest)."""
    manifest = json.loads((features_dir() / "samples" / "samples_manifest.json").read_text(encoding="utf-8"))
    floor = float(manifest["report"]["slope_floor"]["floor"])
    terrain = pd.read_parquet(data_root() / "processed" / "terrain" / "cell_terrain.parquet", columns=["cell_id", "slope_mean"])
    regions = pd.read_parquet(features_dir() / "cell_regions.parquet")
    return candidate_cells(terrain, regions, floor)["cell_id"].to_numpy(dtype=np.int64)


def select_cells(cell_ids, cfg: dict | None = None) -> pd.DataFrame:
    """The scored-cell table (`live.run.load_cells`) restricted to `cell_ids`; a cell the table lacks is an error."""
    cfg = cfg or live_run.load_run_config()
    cells = live_run.load_cells(cfg)
    wanted = np.unique(np.asarray(cell_ids, dtype=np.int64))
    out = cells[cells["cell_id"].isin(wanted)].reset_index(drop=True)
    if len(out) != len(wanted):
        raise ValueError(f"{len(wanted) - len(out)} of the {len(wanted)} requested cells are not scored cells "
                         f"(terrain and region tables, regions {cfg['scored_regions']})")
    return out


def load_set(name: str, start: date | None = None, end: date | None = None, cfg: dict | None = None) -> BacktestSet:
    """A named backtest set with its cells, labelled events and default dates (overridable with `start` / `end`)."""
    cfg = cfg or live_run.load_run_config()
    directory = features_dir()
    if name == "season_2018":
        test = pd.read_parquet(directory / "test_2018_samples_features.parquet",
                               columns=["cell_id", "date", "kind", "in_domain"])
        positives = test[(test["kind"] == "positive") & test["in_domain"]][["cell_id", "date"]].reset_index(drop=True)
        cells = select_cells(np.union1d(universe_cell_ids(), positives["cell_id"].to_numpy()), cfg)
        first, last = start or date(2018, 6, 1), end or date(2018, 9, 30)
        events = positives[(positives["date"] >= pd.Timestamp(first)) & (positives["date"] <= pd.Timestamp(last))]
        return BacktestSet(name, first, last, cells, events.reset_index(drop=True), "season",
                           note="universe cells and the in-domain test_2018 positives of the window")
    if name == "window_2023":
        window = pd.read_parquet(directory / "window_2023_samples_features.parquet",
                                 columns=["cell_id", "date", "kind", "is_window_positive_cell"])
        first, last = start or window["date"].min().date(), end or window["date"].max().date()
        return BacktestSet(name, first, last, select_cells(window["cell_id"].unique(), cfg), None, "window",
                           window_frame=window[(window["date"] >= pd.Timestamp(first)) & (window["date"] <= pd.Timestamp(last))],
                           note="window-positive cells with their 8 neighbours and the control cells of the frozen window table")
    if name == "kerala_2018":
        case = pd.read_parquet(directory / "case_kerala_2018_samples_features.parquet",
                               columns=["cell_id", "date", "is_positive_cell_day"])
        first, last = start or case["date"].min().date(), end or case["date"].max().date()
        events = case[case["is_positive_cell_day"] & (case["date"] >= pd.Timestamp(first)) & (case["date"] <= pd.Timestamp(last))]
        return BacktestSet(name, first, last, select_cells(case["cell_id"].unique(), cfg),
                           events[["cell_id", "date"]].reset_index(drop=True), "case_events",
                           note="every western-ghats universe cell; positives are the case table's cell-days")
    if name == "wayanad_2024":
        case = pd.read_parquet(directory / "case_wayanad_2024_samples_features.parquet", columns=["cell_id", "date"])
        first, last = start or case["date"].min().date(), end or case["date"].max().date()
        return BacktestSet(name, first, last, select_cells(case["cell_id"].unique(), cfg), None, "case_series",
                           focus=(om.WAYANAD["lat"], om.WAYANAD["lon"]),
                           note="qualitative replay of the 30 July 2024 Mundakkai event; no NASA label exists")
    raise ValueError(f"unknown backtest set {name!r}; choose one of {SET_NAMES}")


SET_NAMES = ("season_2018", "window_2023", "kerala_2018", "wayanad_2024")


# ------------------------------------------------------------------------------------------ one backtest

def set_days(spec: BacktestSet) -> list[date]:
    """The days a set scores: its window preceded by the warm-up days of the hysteresis state."""
    return day_range(spec.start - timedelta(days=WARMUP_DAYS), spec.end)


def run_set(spec: BacktestSet, model, stores: Stores, alert_config, progress=None,
            scored: tuple[dict[str, Panel], list[dict]] | None = None) -> dict:
    """Run one backtest set with both variants and return its result dict. `scored` is the output of `score_days` over
    `set_days(spec)`, to evaluate several alert configurations on one scoring pass."""
    started = time.perf_counter()
    days_all = set_days(spec)
    panels, records = scored or score_days(days_all, spec.cells, model, stores, progress,
                                           configured_percentiles(alert_config))
    keep = np.array([d >= spec.start for d in days_all])
    days = [d for d in days_all if d >= spec.start]
    watch_raw = float(model.card["alert_levels"]["watch"]["raw"])
    day_records = [r for r in records if r["date"] >= spec.start.isoformat()]
    result = {"set": spec.name, "note": spec.note, "start": spec.start.isoformat(), "end": spec.end.isoformat(),
              "warmup_days": WARMUP_DAYS, "n_days": len(days), "n_cells": int(len(spec.cells)),
              "cells_by_region": {k: int(v) for k, v in spec.cells["region"].value_counts().sort_index().items()},
              "watch_raw_threshold": watch_raw, "days": day_records, "inputs": input_summary(day_records),
              "variants": {}}
    packs = {}
    for variant in VARIANTS:
        panel = panels[variant]
        by_mode = {mode: rule_levels(panel, spec.cells, days_all, model, alert_config, mode) for mode in MODES}
        kept = Panel(panel.raw[:, keep], panel.risk[:, keep], panel.risk_hi[:, keep])
        packs[variant] = {"levels": {m: {r: lev[:, keep] for r, lev in rules.items()} for m, rules in by_mode.items()},
                          "scored": np.isfinite(kept.risk), "panel": kept}
        result["variants"][variant] = variant_summary(spec, days, packs[variant], watch_raw)
    result["gap"] = gap_summary(spec, days, packs, result["variants"], day_records)
    result["seconds"] = time.perf_counter() - started
    return result


MODES = ("region", "pooled")


def input_summary(day_records: list[dict]) -> dict:
    """Which products supplied the live inputs on the backtest days (the persistence share is the key one)."""
    n = len(day_records)
    tails: dict[str, int] = {}
    early: dict[str, int] = {}
    for r in day_records:
        tails[r["tail_product"]] = tails.get(r["tail_product"], 0) + 1
        early[r["utc_D-1_product"]] = early.get(r["utc_D-1_product"], 0) + 1
    persisted = tails.get(PERSIST, 0)
    return {"days": n, "tail_products": tails, "persist_d1_days": persisted,
            "persist_d1_share": (persisted / n) if n else None, "utc_d-1_products": early,
            "days_without_operational_scores": sum(1 for r in day_records if r["scored_cells"][OPERATIONAL] == 0),
            "days_without_training_style_scores": sum(1 for r in day_records if r["scored_cells"][TRAINING_STYLE] == 0)}


def region_shares(level: np.ndarray, scored: np.ndarray, cells: pd.DataFrame, days: list[date]) -> dict:
    region = cells["region"].to_numpy()
    return {r: share_summary(alert_share(level[region == r], scored[region == r], 1), days)["mean_daily_share"]["value"]
            for r in sorted(set(region))}


def variant_summary(spec: BacktestSet, days: list[date], pack: dict, watch_raw: float) -> dict:
    """Alert shares, event outcomes and the set's own scoring for one variant, per threshold mode and decision rule."""
    scored, panel, cells = pack["scored"], pack["panel"], spec.cells
    out = {"scored_cell_days": int(scored.sum()), "cell_days": int(scored.size)}
    cell_ids = cells["cell_id"].to_numpy(dtype=np.int64)
    for mode, rules in pack["levels"].items():
        out[mode] = {}
        for rule, level in rules.items():
            entry = {"alert_share_watch_plus": share_summary(alert_share(level, scored, 1), days),
                     "alert_share_by_region": region_shares(level, scored, cells, days)}
            entry["chance_watch_within_7d"] = chance_alert_within(level, scored)
            entry["flapping"] = flapping(level, scored, alerts_settings()["evaluation"]["flap_window_days"])
            if rule == "engine":
                entry["alert_share_warning_plus"] = share_summary(alert_share(level, scored, 2), days)
                entry["alert_share_emergency"] = share_summary(alert_share(level, scored, 3), days)
            if spec.events is not None and len(spec.events):
                table = event_outcomes(level, scored, cell_ids, days, spec.events)
                entry["events"] = summarize_events(table)
                entry["event_table"] = table.to_dict("records")
            if spec.kind == "window":
                score, threshold = (panel.raw, watch_raw) if rule == "raw_watch" else (level.astype(np.float64), 1.0)
                entry["window_test"] = window_detection(spec.window_frame, cells, days, score, threshold)
            if spec.kind == "case_series":
                entry["series"] = wayanad_series(cells, days, panel, level, spec.focus)
            out[mode][rule] = entry
    return out


def window_detection(frame: pd.DataFrame, cells: pd.DataFrame, days: list[date], score: np.ndarray, threshold: float) -> dict:
    """The 2023 window test (`hazard.evaluate.window_detection`) on a backtest score matrix: a window-positive cell is
    detected when the maximum score over the window days of any of its 3x3 neighbourhood reaches the threshold."""
    index = pd.MultiIndex.from_arrays([np.repeat(cells["cell_id"].to_numpy(), len(days)),
                                       np.tile(pd.DatetimeIndex(pd.to_datetime(days)).to_numpy(), len(cells))])
    values = pd.Series(np.asarray(score, dtype=np.float64).ravel(), index=index)
    keyed = pd.MultiIndex.from_arrays([frame["cell_id"].to_numpy(), frame["date"].to_numpy()])
    scores = values.reindex(keyed).to_numpy()
    boot = BOOTSTRAP
    return ev.window_detection(frame.reset_index(drop=True), scores, threshold, boot["n"], boot["seed"], boot["level"])


def wayanad_series(cells: pd.DataFrame, days: list[date], panel: Panel, level: np.ndarray, focus) -> dict:
    """The Wayanad box series (`cases.score.wayanad_metrics`): focus cell, cells within 10 km, whole box, first Watch+ day."""
    frame = pd.DataFrame({"cell_id": np.repeat(cells["cell_id"].to_numpy(), len(days)),
                          "date": np.tile(pd.DatetimeIndex(pd.to_datetime(days)).to_numpy(), len(cells)),
                          "risk": panel.risk.ravel(), "risk_hi": panel.risk_hi.ravel(),
                          "level": level.ravel().astype(np.int8)})
    metrics, series = case_score.wayanad_metrics(frame, frame[["cell_id"]], *focus)
    return {"metrics": metrics, "series": series.to_dict("records")}


def gap_summary(spec: BacktestSet, days: list[date], packs: dict, variants: dict, day_records: list[dict]) -> dict:
    """The train/live gap: operational minus training-style on the same cells and days."""
    out = {"modes": {}}
    both = packs[OPERATIONAL]["scored"] & packs[TRAINING_STYLE]["scored"]
    for mode in MODES:
        out["modes"][mode] = {}
        for rule in RULES:
            a, b = (packs[v]["levels"][mode][rule] for v in VARIANTS)
            share_a, share_b = (alert_share(packs[v]["levels"][mode][rule], packs[v]["scored"]) for v in VARIANTS)
            entry = {"alert_share_difference": mean_ci(share_a - share_b),
                     "watch_set_agreement_jaccard": watch_agreement(a, b, both)}
            if spec.events is not None and len(spec.events):
                tables = [pd.DataFrame(variants[v][mode][rule]["event_table"]) for v in VARIANTS]
                entry["paired_events_own"] = paired_events(tables[0], tables[1], "own")
                entry["paired_events_footprint"] = paired_events(tables[0], tables[1], "footprint")
            out["modes"][mode][rule] = entry
    rank = [r["raw_rank_correlation"] for r in day_records if r["raw_rank_correlation"] is not None]
    out["raw_rank_correlation"] = {"mean": float(np.mean(rank)) if rank else None,
                                   "min": float(np.min(rank)) if rank else None}
    for column in ("irain_acc_1", "irain_acc_3"):
        values = [r[f"mean_abs_diff_{column}_mm"] for r in day_records if r[f"mean_abs_diff_{column}_mm"] is not None]
        out[f"mean_abs_diff_{column}_mm"] = float(np.mean(values)) if values else None
    return out


def run_backtest(start: date, end: date, model_dir: Path | None = None, *, set_name: str = "season_2018",
                 spec: BacktestSet | None = None, stores: Stores | None = None, model=None, alert_config=None,
                 cfg: dict | None = None, progress=None) -> dict:
    """Backtest `set_name` over IMD days `start`..`end` with the frozen model in `model_dir` (default: the v3-live model
    named by `configs/live_run.yaml`, which must be frozen) and return the result dict (see the module doc). Writes
    nothing. `spec`, `stores`, `model` and `alert_config` replace the real ones (tests)."""
    cfg = cfg or live_run.load_run_config()
    if model is None:
        model = live_run.load_live_model(cfg) if model_dir is None else hm.HazardModel.load(Path(model_dir))
    spec = spec or load_set(set_name, start, end, cfg)
    stores = stores or build_stores(spec.cells, cfg)
    alert_config = alert_config or load_alert_config(project_path(cfg["alert_config"]))
    return run_set(spec, model, stores, alert_config, progress)


# ------------------------------------------------------------------------------------------------------ CLI

def run_sets(names, model_dir: Path | None, cfg: dict | None = None, start: date | None = None, end: date | None = None,
             progress=None) -> tuple[dict, dict]:
    """Run the named sets with the frozen model; returns ({set: result}, report meta). Needs a verified freeze unless
    `model_dir` is given explicitly."""
    cfg = cfg or live_run.load_run_config()
    model = live_run.load_live_model(cfg) if model_dir is None else hm.HazardModel.load(Path(model_dir))
    directory = hm.configured_model_dir(hm.hazard_config(project_path(cfg["model_config"]))) if model_dir is None \
        else Path(model_dir)
    results = {}
    for name in names:
        if progress:
            progress(f"set {name}")
        spec = load_set(name, start, end, cfg)
        results[name] = run_backtest(spec.start, spec.end, spec=spec, model=model, cfg=cfg, progress=progress)
    meta = {"created_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "model_dir": hm.display_path(directory),
            "model_card_sha256": sha256_file(directory / hm.CARD_FILE), "bootstrap": BOOTSTRAP,
            "warmup_days": WARMUP_DAYS, "data_cutoff_local": cfg["schedule"]["data_cutoff"],
            "early_map_mode": cfg["early_map"]["mode"]}
    return results, meta


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m aetherguard.live.backtest", description=__doc__.splitlines()[0])
    parser.add_argument("--set", default="all", choices=(*SET_NAMES, "all"), help="backtest set (default: all four)")
    parser.add_argument("--start", type=date.fromisoformat, default=None, help="first IMD day (one set only)")
    parser.add_argument("--end", type=date.fromisoformat, default=None, help="last IMD day (one set only)")
    parser.add_argument("--model", type=Path, default=None, help="model directory (default: the frozen v3-live model)")
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "reports", help="report directory")
    parser.add_argument("--stem", default=None, help="report file stem (default phase6_backtest)")
    args = parser.parse_args(argv)
    from . import backtest_report as br
    names = SET_NAMES if args.set == "all" else (args.set,)
    if args.set == "all" and (args.start or args.end):
        parser.error("--start / --end need one --set")
    if bool(args.start) != bool(args.end):
        parser.error("--start and --end go together")
    try:
        results, meta = run_sets(names, args.model, start=args.start, end=args.end, progress=lambda m: print(m, flush=True))
    except (live_run.LiveRunError, ValueError, OSError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    meta["test_reference"] = br.load_test_reference(args.out)
    json_path, md_path = br.write_reports(results, meta, args.out, args.stem or br.REPORT_STEM)
    print(f"wrote {hm.display_path(md_path)} and {hm.display_path(json_path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
