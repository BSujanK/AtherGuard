"""Accuracy hardening of the live alerts (spec section 11): the scores the post-model rules are chosen and evaluated on.

    python -m aetherguard.live.hardening score-dev      [--years 2007-2017]
    python -m aetherguard.live.hardening analyze-dev    [--write-rules data/processed/alerts/post_rules_v3.json]
    python -m aetherguard.live.hardening score-heldout
    python -m aetherguard.live.hardening evaluate       --rules data/processed/alerts/post_rules_v3.json
    python -m aetherguard.live.hardening leads
    python -m aetherguard.live.hardening fixture
    python -m aetherguard.live.hardening report

`score-dev` refits the year-blocked cross-validation models of the v3-live configuration (`burden.fold_models`, the
models that reproduce the card's out-of-fold recall) and scores June-September of every development year (2007-2017)
out of fold on the cells of the Task 6b out-of-fold study (every development-event cell plus the same seeded 5,000
universe cells), with the training-style features. Per cell-day a panel keeps what the post-model rules need: the raw
and calibrated point score, the old interval (10th / 90th percentile of the calibrated members) and the re-centred one,
the members' median, how many members reach each alert level, the 1-, 3- and 7-day IMERG rain, and, on the cell-days
whose point reaches Watch or that are dry, the point model's contributions of the aspect and TWI inputs.

`analyze-dev` chooses the ensemble-agreement minimum and the rain-trigger rule on those panels only (`hardening_dev`).
`score-heldout` and `evaluate` then score the 2018 operational backtest set once with the frozen model and recompute the
live day 2026-10-23 offline from its stored features, before and after the chosen rules; nothing there is chosen.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import PROJECT_ROOT, data_root
from ..hazard import model as hm
from ..hazard.jsonio import dump_json
from . import backtest as bt
from . import burden
from . import run as live_run

DEV_DIR = "accuracy_hardening_oof"           # under data/processed/alerts/
HELDOUT_DIR = "accuracy_hardening_heldout"
HELDOUT_FILE = "season_2018_operational.npz"
DRY_ACC3_MM = 1.0                            # a cell-day is "dry" when its 3-day IMERG rain is below this
RAIN_WINDOWS = (1, 3, 7)
TERRAIN_INPUTS = ("stat_aspect_sin", "stat_aspect_cos", "stat_twi_proxy")
FLOAT_FIELDS = ("raw", "acc_1", "acc_3", "acc_7", "c_aspect_sin", "c_aspect_cos", "c_twi", "c_positive", "margin")
RISK_FIELDS = ("risk", "old_lo", "old_hi", "new_lo", "new_hi", "median_risk")
COUNT_FIELDS = ("n_watch", "n_warning", "n_emergency")
FLAG_FIELDS = ("top3_terrain",)
FIELDS = FLOAT_FIELDS + RISK_FIELDS + COUNT_FIELDS + FLAG_FIELDS


def alerts_dir(name: str) -> Path:
    return data_root() / "processed" / "alerts" / name


# --------------------------------------------------------------------------------------------------- panels

@dataclass
class Panel:
    """Scores of one season, arrays of shape (cells, days) keyed by `FIELDS`; NaN (count 0, flag False) where a cell-day
    has no score or, for the contribution fields, was not explained."""
    cells: pd.DataFrame                  # cell_id, region, in_universe
    days: list[date]
    n_members: int
    values: dict[str, np.ndarray]

    def __getitem__(self, name: str) -> np.ndarray:
        return self.values[name]

    @property
    def scored(self) -> np.ndarray:
        return np.isfinite(self.values["risk"])


def new_panel(cells: pd.DataFrame, days: list[date], n_members: int) -> Panel:
    shape = (len(cells), len(days))
    values = {name: np.full(shape, np.nan, dtype=np.float32) for name in FLOAT_FIELDS}
    values.update({name: np.full(shape, np.nan) for name in RISK_FIELDS})
    values.update({name: np.zeros(shape, dtype=np.uint8) for name in COUNT_FIELDS})
    values.update({name: np.zeros(shape, dtype=bool) for name in FLAG_FIELDS})
    return Panel(cells[["cell_id", "region", "in_universe"]].reset_index(drop=True), list(days), n_members, values)


def score_rows(model: hm.HazardModel, rows: pd.DataFrame) -> dict[str, np.ndarray]:
    """Per row of `rows` (every rain input known) the panel fields: the point and the members of `model`, the old and the
    re-centred interval, member counts per alert level, the rain and, where the point reaches Watch or the cell-day is
    dry, the aspect / TWI contributions of the point model (log-odds of the raw score)."""
    point_raw = model.raw_score(rows)
    member_raw = model.member_raw_scores(rows)
    stacked = np.column_stack([point_raw,
                               hm.recentred_percentile(point_raw, member_raw, hm.INTERVAL_PERCENTILES[0]),
                               hm.recentred_percentile(point_raw, member_raw, hm.INTERVAL_PERCENTILES[1]),
                               np.percentile(member_raw, hm.CENTRE_PERCENTILE, axis=1)])
    calibrated, _ = model.calibrate(stacked, rows)
    members, _ = model.calibrate(member_raw, rows)
    old_lo, old_hi = np.percentile(members, hm.INTERVAL_PERCENTILES, axis=1)
    thresholds = model.level_thresholds(rows)
    if thresholds is None:
        raise ValueError("the model card names no alert levels; the panels need them")
    member_level = (members[:, :, None] >= thresholds[:, None, :]).sum(axis=2)
    out = {"raw": point_raw, "risk": calibrated[:, 0], "new_lo": calibrated[:, 1], "new_hi": calibrated[:, 2],
           "median_risk": calibrated[:, 3], "old_lo": old_lo, "old_hi": old_hi,
           **{name: (member_level >= level).sum(axis=1) for level, name in enumerate(COUNT_FIELDS, start=1)},
           **{f"acc_{w}": rows[f"irain_acc_{w}"].to_numpy(dtype=np.float64) for w in RAIN_WINDOWS}}
    point_level = (calibrated[:, :1] >= thresholds).sum(axis=1)
    explain = (point_level >= 1) | (out["acc_3"] < DRY_ACC3_MM)
    for name in ("c_aspect_sin", "c_aspect_cos", "c_twi", "c_positive", "margin"):
        out[name] = np.full(len(rows), np.nan)
    out["top3_terrain"] = np.zeros(len(rows), dtype=bool)
    if explain.any():
        matrix = hm.feature_matrix(rows[explain], model.columns)
        contrib = model.booster.predict(matrix, num_iteration=model.best_iteration, pred_contrib=True)
        inputs = contrib[:, :-1]
        position = {c: model.columns.index(c) for c in TERRAIN_INPUTS}
        out["c_aspect_sin"][explain] = inputs[:, position["stat_aspect_sin"]]
        out["c_aspect_cos"][explain] = inputs[:, position["stat_aspect_cos"]]
        out["c_twi"][explain] = inputs[:, position["stat_twi_proxy"]]
        out["c_positive"][explain] = np.clip(inputs, 0.0, None).sum(axis=1)
        out["margin"][explain] = contrib.sum(axis=1)
        top3 = np.argsort(-np.abs(inputs), axis=1, kind="stable")[:, :3]
        out["top3_terrain"][explain] = np.isin(top3, list(position.values())).all(axis=1)
    return out


def score_panel(days: list[date], cells: pd.DataFrame, model_of, features_of, progress=None) -> Panel:
    """A panel of `cells` over `days`: `features_of(day)` gives the rain inputs of the cells (same index), `model_of(day)`
    the model scoring that day. A cell-day without its 3-day rain stays unscored (the backtest's rule)."""
    first = model_of(days[0])
    panel = new_panel(cells, days, len(first.members))
    started = time.perf_counter()
    for j, day in enumerate(days):
        frame = pd.concat([cells.reset_index(drop=True), features_of(day).reset_index(drop=True)], axis=1)
        scorable = np.isfinite(frame[live_run.CORE_COLUMN].to_numpy(dtype=np.float64))
        if scorable.any():
            for name, values in score_rows(model_of(day), frame[scorable]).items():
                panel.values[name][scorable, j] = values
        if progress and (j % 20 == 0 or j == len(days) - 1):
            progress(f"  {day} ({j + 1}/{len(days)}) {time.perf_counter() - started:.0f}s")
    return panel


def save_panel(path: Path, panel: Panel) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part.npz")
    np.savez_compressed(part, cell_id=panel.cells["cell_id"].to_numpy(dtype=np.int64),
                        region=panel.cells["region"].to_numpy(dtype=str),
                        in_universe=panel.cells["in_universe"].to_numpy(dtype=bool),
                        days=np.array([d.isoformat() for d in panel.days]), n_members=np.int64(panel.n_members),
                        **panel.values)
    part.replace(path)


def load_panel(path: Path) -> Panel:
    with np.load(path, allow_pickle=False) as data:
        cells = pd.DataFrame({"cell_id": data["cell_id"], "region": data["region"].astype(object),
                              "in_universe": data["in_universe"]})
        days = [date.fromisoformat(str(d)) for d in data["days"]]
        return Panel(cells, days, int(data["n_members"]), {name: data[name] for name in FIELDS})


def season_path(directory: Path, year: int) -> Path:
    return Path(directory) / f"season_{year}.npz"


# ---------------------------------------------------------------------------------------------------- CLI

def score_dev(years, cfg: dict, directory: Path, say) -> None:
    """Out-of-fold panels of the development seasons (see the module doc); a season whose file exists is kept."""
    model = live_run.load_live_model(cfg)
    events = burden.development_events(years)
    cells, kept, counts = burden.development_cells(events, cfg)
    cells = burden.sample_cells(kept, cells, burden.OOF_SAMPLE["cells"], burden.OOF_SAMPLE["seed"])
    say(json.dumps(counts))
    models, check = burden.fold_models(model, hm.hazard_config(live_run.project_path(cfg["model_config"])), progress=say)
    directory.mkdir(parents=True, exist_ok=True)
    dump_json(directory / burden.OOF_CHECK_FILE, {**check, "cells": int(len(cells)), "sample": burden.OOF_SAMPLE})
    say(json.dumps(check))
    if abs(check["oof_recall_at_watch"] - check["card_oof_recall_at_watch"]) > 1e-12:
        raise ValueError(f"the refitted fold models do not reproduce the card's out-of-fold recall: {check}")
    stores = bt.build_stores(cells, cfg)
    for year in years:
        path = season_path(directory, year)
        if path.is_file():
            continue
        say(f"season {year}")
        days, _ = burden.season_days(year)
        panel = score_panel(days, cells, lambda day: models[day.year],
                            lambda day: bt.training_style_features(day, cells, stores), say)
        save_panel(path, panel)


def score_heldout(cfg: dict, directory: Path, say) -> None:
    """The 2018 operational backtest set (`backtest.load_set("season_2018")`, operational features, warm-up days
    included) scored once with the frozen v3-live model."""
    model = live_run.load_live_model(cfg)
    spec = bt.load_set("season_2018", cfg=cfg)
    cells = spec.cells.assign(in_universe=True)
    stores = bt.build_stores(spec.cells, cfg)
    panel = score_panel(bt.set_days(spec), cells, lambda day: model,
                        lambda day: bt.operational_features(day, spec.cells, stores), say)
    save_panel(Path(directory) / HELDOUT_FILE, panel)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m aetherguard.live.hardening", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    dev = sub.add_parser("score-dev", help="out-of-fold panels of the development seasons")
    dev.add_argument("--years", type=burden.parse_years, default=burden.DEV_YEARS)
    dev.add_argument("--out", type=Path, default=None, help=f"panel directory (default data/processed/alerts/{DEV_DIR})")
    held = sub.add_parser("score-heldout", help="the 2018 operational backtest set, frozen model, scored once")
    held.add_argument("--out", type=Path, default=None,
                      help=f"panel directory (default data/processed/alerts/{HELDOUT_DIR})")
    analysis = sub.add_parser("analyze-dev", help="choose the post-model rules on the development panels")
    analysis.add_argument("--panels", type=Path, default=None)
    analysis.add_argument("--write-rules", type=Path, default=None, help="write the chosen rules here")
    evaluate = sub.add_parser("evaluate", help="2018 and the live day 2026-10-23 before and after the chosen rules")
    evaluate.add_argument("--rules", type=Path, required=True)
    evaluate.add_argument("--live-day", type=date.fromisoformat, default=date(2026, 10, 23))
    sub.add_parser("leads", help="which bound uncertain_high tests on the forecast leads (forecast-skill pairs)")
    fixture = sub.add_parser("fixture", help="write the regression fixture of the two reported 23 Oct false alarms")
    fixture.add_argument("--out", type=Path, default=PROJECT_ROOT / "tests" / "fixtures" / "false_alarms_2026-10-23")
    fixture.add_argument("--rerun", action="store_true",
                         help="the continuous re-run with the rules (17-23 Oct, 22 Oct included) instead of the first run")
    report = sub.add_parser("report", help="write reports/phase6_accuracy_hardening.{md,json}")
    report.add_argument("--out", type=Path, default=PROJECT_ROOT / "reports")
    args = parser.parse_args(argv)
    cfg = live_run.load_run_config()
    say = lambda m: print(m, flush=True)
    try:
        if args.command == "score-dev":
            score_dev(args.years, cfg, args.out or alerts_dir(DEV_DIR), say)
        elif args.command == "score-heldout":
            score_heldout(cfg, args.out or alerts_dir(HELDOUT_DIR), say)
        elif args.command == "analyze-dev":
            from . import hardening_dev
            hardening_dev.run(args.panels or alerts_dir(DEV_DIR), cfg, args.write_rules, say)
        elif args.command == "leads":
            from . import hardening_leads, postrules
            rules_path = live_run.project_path(cfg["post_rules"])
            result = hardening_leads.run(cfg, postrules.load_rules(rules_path), say)
            hardening_leads.adopt(rules_path, result, say)
        elif args.command == "fixture":
            from . import hardening_eval
            hardening_eval.write_false_alarm_fixture(cfg, args.out, say,
                                                     hardening_eval.RERUN_DAYS if args.rerun else hardening_eval.FIXTURE_DAYS)
        elif args.command == "evaluate":
            from . import hardening_eval
            hardening_eval.run(args.rules, cfg, args.live_day, say)
        else:
            from . import hardening_report
            hardening_report.write(args.out, say)
    except (live_run.LiveRunError, ValueError, OSError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
