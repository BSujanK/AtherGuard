"""Out-of-fold v4 panels of the development years on EVERY scored cell, through the whole year.

    python -m aetherguard.live.oof_v4_full score [--years 2007-2017] [--window jun_dec|jan_may] [--out DIR]

Why. The operating-point study (`verify.operating_options`) needs three things the existing development panels
(`accuracy_hardening_oof_v4`: June-September, the 5,000 seeded universe cells plus the event cells) cannot give:

* the months outside the monsoon, where the live burden was found far above expectation (`phase8_season_validity`);
* tolerant matching (10 km, 1 day) without a lower bias: on a 14% sample of the cells most neighbours of an event are
  missing, so an alert beside it cannot be seen;
* district aggregation: a district's level depends on all of its cells.

So this scores every scored cell (36,792: the live run's cells, all of them universe cells) with the year-blocked
cross-validation models of v4, exactly as `post_rules_v4.score_dev` does for its sample (the same folds, seeds, tree count
and ensemble, refitted by `burden.fold_models`, which must reproduce the card's out-of-fold recall at Watch), with the same
features (`post_rules_v4.day_features`: training-style rain, the six intensity inputs at the card's lag, the nine static
inputs). Two windows per year:

* `jun_dec`: 25 May (the backtest warm-up of 7 days) to 31 December, the window of the held-out season panels
  (`alerts/v4_seasons`), so development and held-out panels compare like for like;
* `jan_may`: 1 January to 31 May with no warm-up (the half-hourly intensity files start on 2007-01-01, so 2007 has no
  December before it; every year starts cold for the same rule; a hysteresis hold cannot reach back over New Year).

The aspect / TWI contributions of the terrain diagnostic are not computed (`hardening.score_rows(explain=False)`): they
are the costliest field and no step here reads them. One panel per year and window is written and kept; a rerun scores
only the missing ones. The refitted fold models (about 3.5 minutes) are kept in `fold_models.pkl` next to the panels,
tied to the hash of the v4 card, so that one year can be scored per process and the heavy-job lock released between
years. Nothing here reads 2018-2025 or any held-out event.
"""
from __future__ import annotations

import argparse
import json
import pickle
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from ..config import PROJECT_ROOT, data_root
from ..features import imerg_intensity as ii
from ..features import static_w5 as sw
from ..hazard import model as hm
from ..hazard.jsonio import dump_json
from ..manifest import sha256_file
from . import backtest as bt
from . import burden
from . import hardening as H
from . import post_rules_v4 as P
from . import run as live_run

OUT_DIR = "oof_v4_full"              # under data/processed/alerts/
FOLD_MODELS_FILE = "fold_models.pkl"
WINDOWS = {"jun_dec": ((6, 1), (12, 31), bt.WARMUP_DAYS), "jan_may": ((1, 1), (5, 31), 0)}


def window_days(year: int, window: str) -> tuple[list[date], int]:
    """(the days of `window` in `year` with its warm-up before the first day, the index of the first day)."""
    (m0, d0), (m1, d1), warmup = WINDOWS[window]
    first = date(year, m0, d0)
    return bt.day_range(first - timedelta(days=warmup), date(year, m1, d1)), warmup


def panel_path(directory: Path, window: str, year: int) -> Path:
    return Path(directory) / f"{window}_{year}.npz"


def out_dir() -> Path:
    return data_root() / "processed" / "alerts" / OUT_DIR


def unexplained(model, rows):
    return H.score_rows(model, rows, explain=False)


def card_sha(cfg: dict) -> str:
    directory = hm.configured_model_dir(hm.hazard_config(live_run.project_path(P.V4_MODEL_CONFIG)))
    return sha256_file(directory / hm.CARD_FILE)


def cached_fold_models(directory: Path, sha: str, fit) -> tuple[dict, dict]:
    """({year: model}, check) from `directory`/FOLD_MODELS_FILE when it was written for the card of hash `sha`, else
    `fit()`, stored there for the next process. We write this file ourselves; it is never shared."""
    path = Path(directory) / FOLD_MODELS_FILE
    if path.is_file():
        with open(path, "rb") as handle:
            stored = pickle.load(handle)
        if stored["card_sha256"] == sha:
            return stored["models"], stored["check"]
    models, check = fit()
    Path(directory).mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    with open(part, "wb") as handle:
        pickle.dump({"card_sha256": sha, "models": models, "check": check}, handle, protocol=pickle.HIGHEST_PROTOCOL)
    part.replace(path)
    return models, check


def score(years, window: str, cfg: dict, directory: Path, say, root: Path | None = None) -> list[Path]:
    """Score the panels of `years` x `window` that do not exist yet (module doc); returns every panel's path."""
    from ..hazard import v4_int
    burden._assert_development(years)
    directory = Path(directory)
    todo = [y for y in years if not panel_path(directory, window, y).is_file()]
    if not todo:
        say("every panel exists")
        return [panel_path(directory, window, y) for y in years]
    model = live_run.load_live_model(P.v4_cfg(cfg))
    lag = int(model.card.get("intensity", {}).get("lag_days", 0))
    static_names = [c for c in model.columns if c in sw.STATIC_COLUMNS]
    root = Path(root or ii.default_root())
    days_of = {y: window_days(y, window)[0] for y in todo}
    missing = ii.missing_days(root, ii.window_days([d for y in todo for d in days_of[y]], lag), ii.RUN)
    if missing:
        raise ValueError(f"{len(missing)} half-hourly Late day files are missing under {root} ({ii.format_ranges(missing)})")
    study = v4_int.load_study(PROJECT_ROOT / P.V4_STUDY)
    cells, _, counts = burden.development_cells(burden.development_events(years), cfg)
    say(json.dumps(counts))

    def fit():
        dev = v4_int.load_development(study, None, lag)
        return burden.fold_models(model, study["base"], progress=say, dev=dev)

    models, check = cached_fold_models(directory, card_sha(cfg), fit)
    say(json.dumps(check))
    if abs(check["oof_recall_at_watch"] - check["card_oof_recall_at_watch"]) > 1e-12:
        raise ValueError(f"the refitted v4 fold models do not reproduce the card's out-of-fold recall: {check}")
    directory.mkdir(parents=True, exist_ok=True)
    dump_json(directory / burden.OOF_CHECK_FILE, {**check, "cells": int(len(cells)), "model_config": P.V4_MODEL_CONFIG,
                                                  "lag_days": lag, "static_inputs": static_names, "windows": WINDOWS})
    static = sw.join_static(cells[["cell_id"]], sw.static_table())[static_names] if static_names else None
    stores = bt.build_stores(cells, cfg)
    for year in todo:
        path = panel_path(directory, window, year)
        days = days_of[year]
        say(f"{window} {year}: {len(cells)} cells, {days[0]} to {days[-1]}")
        started = time.perf_counter()
        panel = H.score_panel(days, cells, lambda day: models[year],
                              lambda day: P.day_features(day, cells, stores, root, lag, static), say, score=unexplained)
        seconds = time.perf_counter() - started
        dump_json(path.with_suffix(".json"), {
            "year": year, "window": window, "first_day": days[0].isoformat(), "last_day": days[-1].isoformat(),
            "first_index": window_days(year, window)[1], "n_cells": int(len(cells)), "n_members": panel.n_members,
            "scored_share": float(panel.scored.mean()), "model_config": P.V4_MODEL_CONFIG, "seconds": seconds})
        H.save_panel(path, panel)
        say(f"{window} {year} written in {seconds:.0f}s")
        del panel
    return [panel_path(directory, window, y) for y in years]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m aetherguard.live.oof_v4_full", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    cmd = sub.add_parser("score", help="score the missing panels")
    cmd.add_argument("--years", type=burden.parse_years, default=burden.DEV_YEARS)
    cmd.add_argument("--window", choices=sorted(WINDOWS), default="jun_dec")
    cmd.add_argument("--out", type=Path, default=None, help=f"panel directory (default data/processed/alerts/{OUT_DIR})")
    args = parser.parse_args(argv)
    cfg = live_run.load_run_config()
    score(args.years, args.window, cfg, args.out or out_dir(), lambda m: print(m, flush=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
