"""Alert burden on the DEVELOPMENT years: where the Watch-or-above share comes from, and the alert parameters for v3.

    python -m aetherguard.live.burden score   [--years 2007-2017] [--out DIR]
    python -m aetherguard.live.burden analyze [--panels DIR] [--out reports]

`score` runs the frozen v3-live model on June-September of the development years (2007-2017: train + validation
splits, never 2018) for every universe cell, with the training-style features of the operational backtest (Late IMERG
for every UTC day; the stored features are reproduced exactly, Early IMERG does not exist for those years) and keeps per
cell-day the raw score, the calibrated risk and the upper bound of the calibrated ensemble at the percentiles an
`uncertain_high` rule may use. Each year is scored with a warm-up before 1 June so that the hysteresis state is not a cold
start, and saved as one file; a year whose file exists is not scored again.

`analyze` reads those panels and (1) decomposes the burden - the Watch-or-above share and the detection of the
development positives of the seasons under the raw point-risk rule, plus `uncertain_high`, plus hysteresis, plus the
exit rule - and (2) grids the structural parameters that drive the burden (hysteresis `exit_factor`, `exit_days` and the
`uncertain_high` bound) on those years only, picks the combination with the smallest Watch-or-above share whose
detection and median lead do not fall below those of the current parameters (point estimates; the event-level bootstrap
standard error is reported, never used to choose), and writes the v3 alert config and the report. Nothing here reads
2018, the 2023 window or any case set. The thresholds are those of the frozen card, per region.
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
import time
from dataclasses import dataclass, replace
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from ..alerts import levels as lv
from ..alerts import derive as alert_derive
from ..alerts.config import AlertConfig, alerts_settings, default_config_path, save_config
from ..alerts.config import load_config_file as load_alert_config
from ..config import PROJECT_ROOT, data_root
from ..hazard.jsonio import dump_json
from ..hazard import cv
from ..hazard import data as hd
from ..hazard import model as hm
from ..hazard.train import extra_groups_used
from . import backtest as bt
from . import burden_report
from . import run as live_run

DEV_YEARS = tuple(range(2007, 2018))
OOF_SAMPLE = {"cells": 5000, "seed": 20261016}
SEASON_START, SEASON_END = (6, 1), (9, 30)
UNCERTAIN_PERCENTILES = (60.0, 75.0)          # ensemble percentiles kept besides the 90th (risk_hi) for narrower bounds
PANEL_DIR = "alert_burden_v3"                 # under data/processed/alerts/
OOF_PANEL_DIR = "alert_burden_v3_oof"
ANALYSIS_FILE = "dev_analysis.json"
HELDOUT_FILE = "heldout_results.json"
OOF_CHECK_FILE = "oof_check.json"


def panel_dir(name: str = PANEL_DIR) -> Path:
    return data_root() / "processed" / "alerts" / name


def season_days(year: int, warmup: int = bt.WARMUP_DAYS) -> tuple[list[date], int]:
    """(days from `warmup` days before 1 June through 30 September, the index of 1 June)."""
    first, last = date(year, *SEASON_START), date(year, *SEASON_END)
    return bt.day_range(first - timedelta(days=warmup), last), warmup


def bound_name(percentile: float) -> str:
    return f"p{int(percentile)}"


def bound_percentile(bound: str) -> float | None:
    """The ensemble percentile a bound name stands for (`off`: None, no `uncertain_high` rule)."""
    return None if bound == "off" else float(bound[1:])


UPPER_BOUNDS = (bound_name(hm.INTERVAL_PERCENTILES[1]), *(bound_name(p) for p in UNCERTAIN_PERCENTILES))


# ----------------------------------------------------------------------------------------------- inputs

def development_events(years=DEV_YEARS, directory: Path | None = None) -> pd.DataFrame:
    """In-domain positives of the train and validation samples that fall in June-September of `years`
    (cell_id, date, split)."""
    directory = directory or bt.features_dir()
    parts = []
    for split in ("train", "validation"):
        table = pd.read_parquet(directory / f"{split}_samples_features.parquet",
                                columns=["cell_id", "date", "kind", "in_domain"])
        table = table[(table["kind"] == "positive") & table["in_domain"].astype(bool)]
        month, year = table["date"].dt.month, table["date"].dt.year
        keep = year.isin(list(years)) & (month >= SEASON_START[0]) & (month <= SEASON_END[0])
        parts.append(table[keep][["cell_id", "date"]].assign(split=split))
    return pd.concat(parts, ignore_index=True).sort_values(["date", "cell_id"]).reset_index(drop=True)


def development_cells(events: pd.DataFrame, cfg: dict) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """(cells, events kept, counts): the universe cells of the hazard evaluation plus any other scored cell that holds a
    development positive, with an `in_universe` flag; events in cells that are not scored cells are dropped and counted."""
    universe = bt.universe_cell_ids()
    scored = live_run.load_cells(cfg)
    known = scored["cell_id"].isin(np.union1d(universe, events["cell_id"].to_numpy(dtype=np.int64)))
    cells = scored[known].reset_index(drop=True)
    cells = cells.assign(in_universe=cells["cell_id"].isin(universe).to_numpy())
    inside = events["cell_id"].isin(cells["cell_id"])
    counts = {"events": int(len(events)), "events_in_scored_cells": int(inside.sum()),
              "events_in_universe_cells": int(events["cell_id"].isin(universe).sum()),
              "cells": int(len(cells)), "universe_cells": int(cells["in_universe"].sum())}
    return cells, events[inside].reset_index(drop=True), counts


# ------------------------------------------------------------------------------------------------ scoring

@dataclass
class Scores:
    """Scores of one season: arrays of shape (cells, days). `upper` maps a bound name (`p90` is the model's own
    `risk_hi`) to the upper bound of the calibrated ensemble at that percentile."""
    raw: np.ndarray
    risk: np.ndarray
    upper: dict[str, np.ndarray]


def new_scores(n_cells: int, n_days: int) -> Scores:
    return Scores(np.full((n_cells, n_days), np.nan, dtype=np.float32), np.full((n_cells, n_days), np.nan),
                  {name: np.full((n_cells, n_days), np.nan) for name in UPPER_BOUNDS})


def ensemble_scores(model, rows: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, dict[str, np.ndarray]]:
    """(raw score, calibrated risk, upper bounds by name) of `rows`: the bounds are percentiles of the calibrated ensemble
    members, `p90` being the `risk_hi` `model.score` gave when this study ran (Task 6b). Since the spec section 11
    amendment `risk_hi` is re-centred on the point (`hazard.model.recentred_percentile`); this study keeps its own
    definition so that its panels and report stay reproducible."""
    raw = model.raw_score(rows)
    risk, _ = model.calibrate(raw, rows)
    members, _ = model.calibrate(model.member_raw_scores(rows), rows)
    percentiles = [hm.INTERVAL_PERCENTILES[1], *UNCERTAIN_PERCENTILES]
    bounds = np.percentile(members, percentiles, axis=1)
    return raw, risk, {bound_name(p): b for p, b in zip(percentiles, bounds)}


def score_season(days: list[date], cells: pd.DataFrame, model, stores: bt.Stores, progress=None) -> Scores:
    """The training-style scores of `cells` on every day of `days` (a cell-day without its rain input stays NaN)."""
    scores = new_scores(len(cells), len(days))
    started = time.perf_counter()
    for j, day in enumerate(days):
        frame = pd.concat([cells, bt.training_style_features(day, cells, stores)], axis=1)
        scorable = np.isfinite(frame[bt.CORE_COLUMN].to_numpy(dtype=np.float64))
        if scorable.any():
            raw, risk, bounds = ensemble_scores(model, frame[scorable])
            scores.raw[scorable, j], scores.risk[scorable, j] = raw, risk
            for name, bound in bounds.items():
                scores.upper[name][scorable, j] = bound
        if progress and (j % 20 == 0 or j == len(days) - 1):
            progress(f"  {day} ({j + 1}/{len(days)}) {time.perf_counter() - started:.0f}s")
    return scores


def save_scores(path: Path, cells: pd.DataFrame, days: list[date], scores: Scores) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part.npz")
    np.savez_compressed(
        part, cell_id=cells["cell_id"].to_numpy(dtype=np.int64), region=cells["region"].to_numpy(dtype=str),
        in_universe=cells["in_universe"].to_numpy(dtype=bool), days=np.array([d.isoformat() for d in days]),
        raw=scores.raw, risk=scores.risk, **{f"upper_{k}": v for k, v in scores.upper.items()})
    part.replace(path)


def load_scores(path: Path) -> tuple[pd.DataFrame, list[date], Scores]:
    with np.load(path, allow_pickle=False) as data:
        cells = pd.DataFrame({"cell_id": data["cell_id"], "region": data["region"].astype(object),
                              "in_universe": data["in_universe"]})
        days = [date.fromisoformat(str(d)) for d in data["days"]]
        scores = Scores(data["raw"], data["risk"], {k: data[f"upper_{k}"] for k in UPPER_BOUNDS})
    return cells, days, scores


def season_path(directory: Path, year: int) -> Path:
    return Path(directory) / f"season_{year}.npz"


def score_years(years, cells: pd.DataFrame, model_of, stores: bt.Stores, directory: Path, progress=None) -> list[Path]:
    """Score and save each of `years` that has no file yet, with the model `model_of(year)`; returns all their paths."""
    paths = []
    for year in years:
        path = season_path(directory, year)
        if not path.is_file():
            if progress:
                progress(f"season {year}")
            days, _ = season_days(year)
            save_scores(path, cells, days, score_season(days, cells, model_of(year), stores, progress))
        paths.append(path)
    return paths


# ----------------------------------------------------------------------------------- out-of-fold scoring

def fold_models(final_model: hm.HazardModel, hazard_cfg: dict, directory: Path | None = None, progress=None
                ) -> tuple[dict[int, hm.HazardModel], dict]:
    """The year-blocked cross-validation models of the final configuration, one per development year.

    The frozen model was fitted on every development positive, so its scores of the development years are in-sample.
    Fold k is refitted as `hazard.cv.run_cv` fits it (same rows, seeds, hyper-parameters, early stopping, then extended to
    the card's tree count) with its own bagging ensemble, and scores the years of its fold; the frozen model's
    calibrators map its raw scores, as they were fitted on exactly such out-of-fold scores, and the card's thresholds
    apply. Returns ({year: model}, a check): the share of development positives at or above the card's Watch raw
    threshold under these models against the out-of-fold recall the card reports."""
    card = final_model.card
    dev = hd.load_development(directory, hazard_cfg["extra_groups"], extra_groups_used(hazard_cfg),
                              hazard_cfg["meta_columns"])
    layout = cv.make_layout(dev, card["folds"])
    columns, constraints, hp = final_model.columns, final_model.constraints, card["hyperparameters"]
    settings, seed, n_trees = hazard_cfg["training"], hazard_cfg["seed"], int(card["n_trees"])
    ensemble = hazard_cfg["ensemble"]
    watch_raw = float(card["alert_levels"]["watch"]["raw"])
    models, hits = {}, 0
    for k, years in enumerate(layout.folds):
        inside = dev.samples["year"].isin(years)
        train = hd.training_frame(dev.samples[~inside], dev.universe[~dev.universe["year"].isin(years)], card["neg_mix"],
                                  settings["universe_negatives"], seed + k)
        held = dev.samples[inside]
        valid = hd.training_frame(held, held.iloc[:0], "matched_only", 0, seed)
        booster, _ = hm.fit_booster(train, columns, constraints, hp, seed + k, settings, valid=valid)
        hm.extend_booster(booster, n_trees)
        members = hm.fit_ensemble(train, columns, constraints, hp, n_trees, ensemble["members"],
                                  ensemble["seed"] + 1000 * (k + 1), settings)
        model = hm.HazardModel(columns, constraints, booster, n_trees, members, final_model.calibrator, card,
                               final_model.region_calibrator)
        positives = layout.positives[layout.pos_fold == k]
        hits += int((model.raw_score(positives) >= watch_raw).sum())
        models.update({int(year): model for year in years})
        if progress:
            progress(f"  fold {k} {list(years)} fitted")
    check = {"oof_recall_at_watch": hits / len(layout.positives), "card_oof_recall_at_watch": card["alert_levels"]["watch"]["oof_recall"],
             "positives": int(len(layout.positives))}
    return models, check


def sample_cells(events: pd.DataFrame, cells: pd.DataFrame, n: int, seed: int) -> pd.DataFrame:
    """The cells of an out-of-fold run: every cell that holds a development event, plus `n` universe cells drawn with
    `seed`, which alone carry `in_universe` (the burden is measured on them)."""
    universe = np.sort(cells.loc[cells["in_universe"], "cell_id"].to_numpy(dtype=np.int64))
    drawn = np.random.default_rng(seed).choice(universe, size=min(n, len(universe)), replace=False)
    keep = cells["cell_id"].isin(np.union1d(drawn, events["cell_id"].to_numpy(dtype=np.int64)))
    out = cells[keep].reset_index(drop=True)
    return out.assign(in_universe=out["cell_id"].isin(drawn).to_numpy())


# ------------------------------------------------------------------------------------------ levels and metrics

OFF = "off"                       # no `uncertain_high` rule
CURRENT_BOUND = bound_name(hm.INTERVAL_PERCENTILES[1])
BOOTSTRAP_SE = {"n": 2000, "seed": 20261016}
GRID = {"exit_factor": (0.8, 0.9, 1.0), "exit_days": (1, 2), "bound": (CURRENT_BOUND, "p75", "p60", OFF)}
MAX_COMBINATIONS = 30


def config_key(bound: str, hysteresis: tuple[float, int] | None) -> str:
    return f"{bound}|" + ("none" if hysteresis is None else f"{hysteresis[0]:g}|{hysteresis[1]}")


def make_config(bound: str, hysteresis: tuple[float, int] | None, label: str | None = None) -> dict:
    return {"key": config_key(bound, hysteresis), "label": label, "bound": bound,
            "exit_factor": None if hysteresis is None else hysteresis[0],
            "exit_days": None if hysteresis is None else hysteresis[1]}


def hysteresis_of(config: dict) -> tuple[float, int] | None:
    return None if config["exit_factor"] is None else (config["exit_factor"], config["exit_days"])


def grid_configs(current: tuple[float, int]) -> list[dict]:
    """The grid (`GRID`) with the combination of the current parameters first: exit_factor x exit_days x the
    `uncertain_high` bound."""
    combos = [make_config(bound, (factor, days)) for bound, factor, days in
              itertools.product(GRID["bound"], GRID["exit_factor"], GRID["exit_days"])]
    if len(combos) > MAX_COMBINATIONS:
        raise ValueError(f"the grid has {len(combos)} combinations, more than the {MAX_COMBINATIONS} the protocol allows")
    now = make_config(CURRENT_BOUND, current)
    if now["key"] not in {c["key"] for c in combos}:
        raise ValueError(f"the current parameters {current} are not on the grid")
    return [now, *(c for c in combos if c["key"] != now["key"])]


def decomposition_configs(current: tuple[float, int]) -> list[dict]:
    """The steps from the raw point-risk rule to the full alert levels, and a side row that separates the effects.

    (a) the point risk against the Watch threshold of the region; (b) plus `uncertain_high`; (c) plus hysteresis with
    the day count only (a level is held until `exit_days` consecutive days are below it, whatever the risk); (d) the full
    levels, whose exit rule also needs the risk below `exit_factor` x the held level's threshold. The side row is
    hysteresis without `uncertain_high`."""
    return [make_config(OFF, None, "a. raw point-risk rule"),
            make_config(CURRENT_BOUND, None, "b. a + uncertain_high"),
            make_config(CURRENT_BOUND, (1.0, current[1]), "c. b + hysteresis (day count only, exit factor 1)"),
            make_config(CURRENT_BOUND, current, "d. c + exit rule = the full alert levels"),
            make_config(OFF, current, "side: point risk + full hysteresis, no uncertain_high")]


def season_levels(scores: Scores, cells: pd.DataFrame, days: list[date], thresholds: dict[str, lv.Thresholds],
                  bound: str, hysteresis: tuple[float, int] | None) -> np.ndarray:
    """Alert level 0-3 per (cell, day) under the thresholds of each cell's region: the raw level from the point risk
    (`uncertain_high` against the ensemble bound `bound`, never with `OFF`), then the hysteresis `(exit_factor,
    exit_days)` over the consecutive days unless it is None."""
    upper = scores.risk if bound == OFF else scores.upper[bound]
    if hysteresis is not None:
        return bt.engine_levels(bt.Panel(scores.raw, scores.risk, upper), cells, days, thresholds, *hysteresis)
    out = np.zeros(scores.risk.shape, dtype=np.int8)
    region = cells["region"].to_numpy()
    for name, thr in thresholds.items():
        rows = region == name
        out[rows] = lv.raw_level(scores.risk[rows], upper[rows], thr)[0]
    return out


def bootstrap_se(flags, n: int = BOOTSTRAP_SE["n"], seed: int = BOOTSTRAP_SE["seed"]) -> float | None:
    """Standard deviation of the share of True flags over seeded bootstrap resamples of the events."""
    flags = np.asarray(flags, dtype=np.float64)
    if len(flags) < 2:
        return None
    resamples = flags[np.random.default_rng(seed).integers(0, len(flags), (n, len(flags)))].mean(axis=1)
    return float(resamples.std(ddof=1))


def season_stats(levels: np.ndarray, scored: np.ndarray, universe: np.ndarray, cell_ids: np.ndarray, days: list[date],
                 events: pd.DataFrame, flap_window: int) -> dict:
    """One season (levels over its June-September days only): the cell-day counts at Watch+, Warning+ and Emergency and
    the flapping of the universe cells, and the outcome of every development event (own cell, footprint, lead)."""
    lv_u, sc_u = levels[universe], scored[universe]
    table = bt.event_outcomes(levels, scored, cell_ids, days, events)
    if "split" in events.columns and len(table):
        table["split"] = events["split"].to_numpy()
    return {"cell_days": int(sc_u.sum()), "watch": int(((lv_u >= lv.WATCH) & sc_u).sum()),
            "warning": int(((lv_u >= lv.WARNING) & sc_u).sum()), "emergency": int(((lv_u >= lv.EMERGENCY) & sc_u).sum()),
            "flapping": bt.flapping(lv_u, sc_u, flap_window), "events": table.to_dict("records")}


def _detection(table: pd.DataFrame, column: str) -> dict:
    flags = table[column].to_numpy(dtype=bool)
    out = bt.share_ci(flags, bt.BOOTSTRAP["n"], bt.BOOTSTRAP["seed"], bt.BOOTSTRAP["level"])
    return {**out, "se": bootstrap_se(flags)}


def combine_seasons(by_year: dict[int, dict]) -> dict:
    """Burden, flapping and detection of one rule over all its seasons."""
    seasons = [by_year[y] for y in sorted(by_year)]
    n = sum(s["cell_days"] for s in seasons)
    table = pd.DataFrame([e for s in seasons for e in s["events"]])
    flaps, changes = (sum(s["flapping"][k] for s in seasons) for k in ("n_flaps", "n_changes"))
    out = {"cell_days": n, "n_seasons": len(seasons),
           "watch_plus_share": sum(s["watch"] for s in seasons) / n,
           "warning_plus_share": sum(s["warning"] for s in seasons) / n,
           "emergency_share": sum(s["emergency"] for s in seasons) / n,
           "watch_plus_share_by_year": {int(y): by_year[y]["watch"] / by_year[y]["cell_days"] for y in sorted(by_year)},
           "flapping": {"n_flaps": flaps, "n_changes": changes, "flaps_per_1000_cell_days": 1000 * flaps / n,
                        "changes_per_1000_cell_days": 1000 * changes / n},
           "n_events": int(len(table)), "own_day": None, "own_within_7d": None, "footprint_day": None,
           "median_lead_days": None, "mean_lead_days": None}
    if table.empty:
        return out
    leads = table["own_lead_days"].dropna().astype(float)
    out.update(own_day=_detection(table, "own_detected"),
               own_within_7d=_detection(table.assign(within=table["own_lead_days"].notna()), "within"),
               footprint_day=_detection(table, "footprint_detected"),
               median_lead_days=float(leads.median()) if len(leads) else None,
               mean_lead_days=float(leads.mean()) if len(leads) else None)
    if "split" in table.columns:
        out["own_day_by_split"] = {name: _detection(part, "own_detected") for name, part in table.groupby("split")}
    return out


LOSS_TOLERANCE = 0.005            # the costed alternative may lose this share of the events (never the choice)


def choose(results: list[dict], baseline_key: str, allowed_loss: int = 0) -> dict:
    """The result with the smallest Watch-or-above share among those whose own-cell detection (events hit) is not below
    the baseline's (by more than `allowed_loss` events) and whose median lead is not shorter; ties go to the earlier
    result (the current parameters come first). Point estimates only: the standard errors are reported, never used to
    choose. `allowed_loss` is 0 for the choice; the costed alternative uses a small tolerance."""
    base = next(r for r in results if r["config"]["key"] == baseline_key)
    floor_hits, floor_lead = base["own_day"]["hits"] - allowed_loss, base["median_lead_days"]

    def admissible(r: dict) -> bool:
        lead = r["median_lead_days"]
        return r["own_day"]["hits"] >= floor_hits and (floor_lead is None or (lead is not None and lead >= floor_lead))
    return min((r for r in results if admissible(r)), key=lambda r: r["watch_plus_share"])


# --------------------------------------------------------------------------------------------------- analysis

BASES = {"frozen": {"directory": PANEL_DIR, "model": "the frozen v3-live model (fitted on every development positive, so "
                    "its detection of them is in-sample)"},
         "oof": {"directory": OOF_PANEL_DIR, "model": "the year-blocked cross-validation models of the v3-live configuration, "
                 "each scoring the years it did not train on (out-of-fold, the setting the card's thresholds were set in)"}}


def analyze(years, directory: Path, cfg: dict, current_config: AlertConfig, progress=None, basis: str = "frozen") -> dict:
    """Decompose the burden and grid the structural parameters on the scored development `years` (see the module doc);
    `basis` names which model produced the panels in `directory`."""
    _assert_development(years)
    if not years:
        raise ValueError("no years to analyze")
    model = live_run.load_live_model(cfg)
    card = model.card
    events = development_events(years)
    flap_window = alerts_settings()["evaluation"]["flap_window_days"]
    current = (current_config.exit_factor, current_config.exit_days)
    decomposition, grid = decomposition_configs(current), grid_configs(current)
    configs = {c["key"]: c for c in [*grid, *decomposition]}      # a labelled decomposition step wins a shared key
    stats: dict[str, dict[int, dict]] = {key: {} for key in configs}
    raw_rule: dict[int, dict] = {}
    ties = {"cell_days": 0, "risk_rule_only": 0, "raw_rule_only": 0}
    watch_raw = float(card["alert_levels"]["watch"]["raw"])
    started = time.perf_counter()
    for year in years:
        cells, days, scores = load_scores(season_path(directory, year))
        thresholds = lv.card_region_thresholds(card, cells["region"])
        first = days.index(date(year, *SEASON_START))
        kept, scored = days[first:], np.isfinite(scores.risk)[:, first:]
        in_year = events[(events["date"].dt.year == year) & events["cell_id"].isin(cells["cell_id"])]
        ids, universe = cells["cell_id"].to_numpy(dtype=np.int64), cells["in_universe"].to_numpy(dtype=bool)
        for key, config in configs.items():
            levels = season_levels(scores, cells, days, thresholds, config["bound"], hysteresis_of(config))[:, first:]
            stats[key][year] = season_stats(levels, scored, universe, ids, kept, in_year, flap_window)
        with np.errstate(invalid="ignore"):
            point = (scores.raw >= watch_raw).astype(np.int8)[:, first:]
        raw_rule[year] = season_stats(point, scored, universe, ids, kept, in_year, flap_window)
        watch = np.array([thresholds[r].watch for r in cells["region"]])[:, None]
        by_risk = (scores.risk[:, first:] >= watch)[universe] & scored[universe]
        by_raw = point[universe].astype(bool) & scored[universe]
        ties["cell_days"] += int(scored[universe].sum())
        ties["risk_rule_only"] += int((by_risk & ~by_raw).sum())
        ties["raw_rule_only"] += int((by_raw & ~by_risk).sum())
        if progress:
            progress(f"  {year} done ({time.perf_counter() - started:.0f}s)")
    summaries = {key: {"config": configs[key], **combine_seasons(by_year)} for key, by_year in stats.items()}
    candidates = [summaries[c["key"]] for c in grid]
    chosen = choose(candidates, grid[0]["key"])
    allowed = int(LOSS_TOLERANCE * summaries[grid[0]["key"]]["n_events"])
    alternative = choose(candidates, grid[0]["key"], allowed)
    return {"protocol": protocol_record(years, len(grid), basis), "years": list(years),
            "events": {"in_season": int(len(events)), "in_scored_cells": summaries[grid[0]["key"]]["n_events"]},
            "thresholds_by_region": {k: v.to_dict() for k, v in thresholds.items()},
            "watch_raw_threshold": watch_raw, "raw_score_rule": combine_seasons(raw_rule),
            "risk_rule_vs_raw_rule": {"risk_rule_only_share": ties["risk_rule_only"] / ties["cell_days"],
                                      "raw_rule_only_share": ties["raw_rule_only"] / ties["cell_days"],
                                      "note": "cell-days at Watch under the calibrated-risk threshold of the region but "
                                              "below the frozen raw-score threshold (isotonic calibration is flat over "
                                              "stretches of raw scores), and the reverse"},
            "decomposition": [summaries[c["key"]] for c in decomposition], "grid": candidates,
            "current": summaries[grid[0]["key"]], "chosen": chosen, "alternative": alternative,
            "allowed_loss_events": allowed, "grid_spec": {k: list(v) for k, v in GRID.items()},
            "selection": {"objective": "minimise the development Watch+ cell-day share",
                          "constraints": "own-cell detection of the development events (point estimate) not below that of the "
                                         "current parameters, median lead not shorter",
                          "current_key": grid[0]["key"], "chosen_key": chosen["config"]["key"],
                          "alternative_key": alternative["config"]["key"]}}


DATA_DERIVED = ("dis_ratio_lo", "dis_ratio_hi", "heavy_acc1_mm", "heavy_acc3_mm", "agree_abs_mm", "agree_rel")


def compact_result(result: dict) -> dict:
    """The numbers of one analysed rule that the config's derivation record keeps."""
    own = result["own_day"]
    return {"key": result["config"]["key"], "bound": result["config"]["bound"],
            "exit_factor": result["config"]["exit_factor"], "exit_days": result["config"]["exit_days"],
            "watch_plus_share": result["watch_plus_share"], "warning_plus_share": result["warning_plus_share"],
            "emergency_share": result["emergency_share"], "events": result["n_events"],
            "own_day_hits": own["hits"], "own_day_share": own["value"], "own_day_se": own["se"],
            "median_lead_days": result["median_lead_days"],
            "flaps_per_1000_cell_days": result["flapping"]["flaps_per_1000_cell_days"]}


def v3_alert_config(analysis: dict, previous: AlertConfig, derived: tuple[AlertConfig, dict], which: str = "chosen"
                    ) -> tuple[AlertConfig, dict]:
    """The alert config for v3: the data-derived values re-derived from the development features (`alerts.derive`,
    which reads no model, so they come out as the v2 values) and the structural parameters of the grid's choice."""
    config, record = derived
    chosen = analysis[which]["config"]
    config = replace(config, exit_factor=chosen["exit_factor"], exit_days=chosen["exit_days"],
                     uncertain_percentile=bound_percentile(chosen["bound"]))
    record = {**record, "structural_rederivation": {
        "protocol": analysis["protocol"], "selection": analysis["selection"], "grid": analysis["grid_spec"],
        "previous": {"exit_factor": previous.exit_factor, "exit_days": previous.exit_days,
                     "uncertain_percentile": previous.uncertain_percentile},
        "chosen": {"exit_factor": config.exit_factor, "exit_days": config.exit_days,
                   "uncertain_percentile": config.uncertain_percentile},
        "development_before": compact_result(analysis["current"]), "development_after": compact_result(analysis[which]),
        "all_combinations": [compact_result(r) for r in analysis["grid"]],
        "data_derived_values_equal_to_previous": {k: getattr(config, k) == getattr(previous, k) for k in DATA_DERIVED}}}
    return config, record


def _assert_development(years) -> None:
    outside = sorted(set(years) - set(DEV_YEARS))
    if outside:
        raise ValueError(f"years {outside} are outside the development period {DEV_YEARS[0]}-{DEV_YEARS[-1]}")


def protocol_record(years, grid_size: int, basis: str) -> dict:
    return {"period": f"{SEASON_START[0]:02d}-{SEASON_START[1]:02d} to {SEASON_END[0]:02d}-{SEASON_END[1]:02d} of "
                      f"{min(years)}-{max(years)} (train + validation years)", "basis": basis,
            "model": f"{BASES[basis]['model']}; training-style features (Late IMERG), thresholds of the card per region",
            "bootstrap_se": BOOTSTRAP_SE, "grid_size": grid_size,
            "note": "Chosen on development years only; test_2018, the 2023 window and the case sets are not read"}


# ------------------------------------------------------------------------------------------------------ CLI

def parse_years(text: str) -> tuple[int, ...]:
    first, _, last = text.partition("-")
    years = tuple(range(int(first), int(last or first) + 1))
    if not years or not set(years) <= set(DEV_YEARS):
        raise argparse.ArgumentTypeError(f"years must lie in {DEV_YEARS[0]}-{DEV_YEARS[-1]} (development only), got {text}")
    return years


def compare_set(spec: bt.BacktestSet, model, stores: bt.Stores, configs: dict[str, AlertConfig], progress=None
                ) -> dict[str, dict]:
    """One backtest set scored once and evaluated under each of the alert `configs`: {label: result}."""
    scored = bt.score_days(bt.set_days(spec), spec.cells, model, stores, progress,
                           bt.configured_percentiles(*configs.values()))
    return {label: bt.run_set(spec, model, stores, config, scored=scored) for label, config in configs.items()}


def heldout_configs(args) -> dict[str, AlertConfig]:
    configs = {"old": load_alert_config(args.old_config or default_config_path()),
               "new": load_alert_config(args.new_config)}
    if args.alt_config:
        configs["alt"] = load_alert_config(args.alt_config)
    return configs


def run_heldout(args, cfg: dict) -> int:
    configs, model = heldout_configs(args), live_run.load_live_model(cfg)
    results: dict[str, dict] = {label: {} for label in configs}
    for name in args.sets:
        print(f"set {name}", flush=True)
        spec = bt.load_set(name, cfg=cfg)
        for label, result in compare_set(spec, model, bt.build_stores(spec.cells, cfg), configs,
                                         lambda m: print(m, flush=True)).items():
            results[label][name] = result
    dump_json((args.panels or panel_dir()) / HELDOUT_FILE, results)
    return 0


def run_report(args, cfg: dict) -> int:
    directory = args.panels or panel_dir()
    analysis = json.loads((panel_dir(OOF_PANEL_DIR) / ANALYSIS_FILE).read_text(encoding="utf-8"))
    frozen = json.loads((directory / ANALYSIS_FILE).read_text(encoding="utf-8"))
    results = json.loads((directory / HELDOUT_FILE).read_text(encoding="utf-8"))
    configs = heldout_configs(args)
    parameters = {label: config.to_dict() for label, config in configs.items()}
    heldout = burden_report.heldout_comparison(results)
    report = burden_report.build_report(analysis, frozen, parameters, heldout, {"limits": LIMITS})
    json_path, md_path = burden_report.write_report(report, args.out)
    burden_report.append_section(Path(args.out) / "phase6_backtest.md", burden_report.backtest_section(report))
    print(f"wrote {json_path} and {md_path}")
    return 0


LIMITS = [
    "The out-of-fold models are refits of the v3-live configuration with the cross-validation's own seeds; their "
    "ensembles (the `uncertain_high` bounds) use seeds of this study, so they are not the cross-validation's models "
    "member for member. The burden of that analysis is measured on a seeded sample of 5,000 of the 36,792 universe cells; "
    "the frozen-model analysis on all of them gives the same table to within a point.",
    "The frozen-model analysis detects the development events in-sample (the model was fitted on them), so its "
    "detection is near 100% under every rule.",
    "Training-style features (Late IMERG for every UTC day) were used: Early IMERG does not exist for 2007-2017, so the "
    "train/live gap of the operational inputs is not in the development numbers.",
    "The source-agreement, gauge and blind-escalation rules of the alert engine are not applied (no IMD real-time archive or "
    "gauge history on disk), neither in the development analysis nor in the backtest; the live alert share can be higher by the "
    "cells they raise to Watch.",
    "The data-derived values (source-disagreement range, heavy-rain amounts, station agreement) are percentiles of the "
    "development feature tables and do not depend on the model, so there was nothing to re-derive for v3.",
    "Lead time is capped at 7 days and saturates when the alert share is high; it is informative only against the chance "
    "rate. The labels are partial: alerts on cells without a recorded landslide count as alert share, not as errors.",
    "The Watch threshold itself (the card's recall-first operating point) was not touched; it fixes the floor of the burden."]


def run_analysis(args, cfg: dict) -> int:
    directory = args.panels or panel_dir(BASES[args.basis]["directory"])
    previous = load_alert_config(args.current_config or default_config_path())
    result = analyze(args.years, directory, cfg, previous, lambda m: print(m, flush=True), args.basis)
    dump_json(directory / ANALYSIS_FILE, result)
    chosen = result["chosen"]
    print(f"current {result['selection']['current_key']}: Watch+ {result['current']['watch_plus_share']:.4f}; chosen "
          f"{result['selection']['chosen_key']}: Watch+ {chosen['watch_plus_share']:.4f}")
    if args.write_config:
        config, record = v3_alert_config(result, previous, alert_derive.derive())
        save_config(args.write_config, config, record)
        print(f"wrote {args.write_config}")
    if args.write_alternative:
        config, record = v3_alert_config(result, previous, alert_derive.derive(), "alternative")
        save_config(args.write_alternative, config, record)
        print(f"wrote {args.write_alternative}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m aetherguard.live.burden", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    score = sub.add_parser("score", help="score the development seasons with the frozen v3-live model")
    score.add_argument("--years", type=parse_years, default=DEV_YEARS, help="e.g. 2013-2017 (default 2007-2017)")
    score.add_argument("--out", type=Path, default=None, help="panel directory")
    oof = sub.add_parser("score-oof", help="score the development seasons with the year-blocked cross-validation models")
    oof.add_argument("--years", type=parse_years, default=DEV_YEARS)
    oof.add_argument("--cells", type=int, default=OOF_SAMPLE["cells"], help="universe cells drawn besides the event cells")
    oof.add_argument("--out", type=Path, default=None, help="panel directory")
    analysis = sub.add_parser("analyze", help="decompose the burden and grid the alert parameters")
    analysis.add_argument("--years", type=parse_years, default=DEV_YEARS)
    analysis.add_argument("--basis", choices=tuple(BASES), default="frozen", help="which scoring the panels hold")
    analysis.add_argument("--panels", type=Path, default=None, help="panel directory (default: the basis's)")
    analysis.add_argument("--current-config", type=Path, default=None,
                          help="the alert config whose parameters are the baseline (default: the v2 alert_config.json)")
    analysis.add_argument("--write-config", type=Path, default=None, help="write the v3 alert config here")
    analysis.add_argument("--write-alternative", type=Path, default=None,
                          help="write the costed alternative (the smallest burden within the loss tolerance) here")
    heldout = sub.add_parser("heldout", help="run 2018 / 2023 / Kerala once under the old and the new parameters")
    report = sub.add_parser("report", help="write reports/phase6_alert_burden and the backtest report section")
    for parser_ in (heldout, report):
        parser_.add_argument("--panels", type=Path, default=None, help="panel directory")
        parser_.add_argument("--old-config", type=Path, default=None, help="default: the v2 alert_config.json")
        parser_.add_argument("--new-config", type=Path, required=True, help="the v3 alert config")
        parser_.add_argument("--alt-config", type=Path, default=None, help="the costed alternative, evaluated beside them")
    heldout.add_argument("--sets", nargs="+", default=["season_2018", "window_2023", "kerala_2018"], choices=bt.SET_NAMES)
    report.add_argument("--out", type=Path, default=PROJECT_ROOT / "reports", help="report directory")
    args = parser.parse_args(argv)
    cfg = live_run.load_run_config()
    try:
        if args.command not in ("score", "score-oof"):
            return {"analyze": run_analysis, "heldout": run_heldout, "report": run_report}[args.command](args, cfg)
        model = live_run.load_live_model(cfg)
        events = development_events(args.years)
        cells, kept, counts = development_cells(events, cfg)
        say = lambda m: print(m, flush=True)
        if args.command == "score-oof":
            cells = sample_cells(kept, cells, args.cells, OOF_SAMPLE["seed"])
            models, check = fold_models(model, hm.hazard_config(live_run.project_path(cfg["model_config"])), progress=say)
            directory = args.out or panel_dir(OOF_PANEL_DIR)
            directory.mkdir(parents=True, exist_ok=True)
            dump_json(directory / OOF_CHECK_FILE, {**check, "cells": int(len(cells)), "sample": OOF_SAMPLE})
            print(json.dumps(check), flush=True)
            model_of = models.__getitem__
        else:
            directory, model_of = args.out or panel_dir(), lambda year: model
        print(json.dumps(counts), flush=True)
        score_years(args.years, cells, model_of, bt.build_stores(cells, cfg), directory, say)
    except (live_run.LiveRunError, ValueError, OSError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
