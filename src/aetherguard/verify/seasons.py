"""Held-out season panels for the ground-truth expansion (spec W1): the frozen v3-live model scored over June-December
of each year 2018-2025 on the cells of the 2018 backtest set, with the training-style features (IMERG Late through the
whole of UTC day D) so the pooled seasons compare like for like.

    python -m aetherguard.verify seasons --years 2018-2025 [--out DIR] [--force]

Each season is one `live.hardening` panel (`season_<year>_training.npz`, the 2018 operational panel of
`accuracy_hardening_heldout` is left alone) with a JSON sidecar of the days, cells, scored share per day, the model card's
hash and the seconds it took. A season whose panel exists is skipped unless forced.
"""
from __future__ import annotations

import argparse
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import data_root
from ..hazard import model as hm
from ..hazard.jsonio import dump_json
from ..live import backtest as bt
from ..live import hardening as H
from ..live import run as live_run
from ..manifest import sha256_file

OUT_DIR = "heldout_seasons"          # under data/processed/alerts/
SEASON_START, SEASON_END = (6, 1), (12, 31)


def season_path(directory: Path | None, year: int) -> Path:
    directory = H.alerts_dir(OUT_DIR) if directory is None else Path(directory)
    return directory / f"season_{year}_training.npz"


def parse_years(text: str) -> tuple[int, ...]:
    first, _, last = text.partition("-")
    years = tuple(range(int(first), int(last or first) + 1))
    if not years or not set(years) <= set(bt.SEASON_YEARS):
        raise argparse.ArgumentTypeError(f"years must lie in {bt.SEASON_YEARS[0]}-{bt.SEASON_YEARS[-1]}, got {text}")
    return years


def model_card_sha(cfg: dict) -> str:
    directory = hm.configured_model_dir(hm.hazard_config(live_run.project_path(cfg["model_config"])))
    return sha256_file(directory / hm.CARD_FILE)


def scored_share_summary(panel: H.Panel) -> dict:
    """Per day the share of the candidate cells with a score: min / mean / max, the days under half, the mean by month."""
    share = panel.scored.mean(axis=0)
    months = pd.Series(share, index=pd.DatetimeIndex(pd.to_datetime(panel.days))).groupby(lambda t: t.strftime("%Y-%m")).mean()
    return {"min": float(share.min()), "mean": float(share.mean()), "max": float(share.max()),
            "days_below_half": int((share < 0.5).sum()), "mean_by_month": {k: float(v) for k, v in months.items()}}


def score_season(year: int, out_dir: Path | None = None, say=print, force: bool = False) -> Path:
    """Score June-December `year` (plus the backtest warm-up days before 1 June) of the 2018 set's cells with the frozen
    model and the training-style features; returns the panel's path. An existing panel is kept unless `force`."""
    path = season_path(out_dir, year)
    if path.is_file() and not force:
        say(f"season {year}: {path} exists, skipped")
        return path
    started = time.perf_counter()
    cfg = live_run.load_run_config()
    model = live_run.load_live_model(cfg)
    spec = bt.load_set(f"season_{year}", date(year, *SEASON_START), date(year, *SEASON_END), cfg)
    stores = bt.build_stores(spec.cells, cfg)
    say(f"season {year}: {len(spec.cells)} cells, {spec.start} to {spec.end}")
    panel = H.score_panel(bt.set_days(spec), spec.cells.assign(in_universe=True), lambda day: model,
                          lambda day: bt.training_style_features(day, spec.cells, stores), say)
    path.parent.mkdir(parents=True, exist_ok=True)
    seconds = time.perf_counter() - started
    dump_json(path.with_suffix(".json"), {
        "year": year, "features": "training_style", "n_days": len(panel.days), "n_cells": int(len(panel.cells)),
        "first_day": panel.days[0].isoformat(), "last_day": panel.days[-1].isoformat(), "warmup_days": bt.WARMUP_DAYS,
        "n_members": panel.n_members, "scored_share_per_day": scored_share_summary(panel),
        "model_card_sha256": model_card_sha(cfg), "seconds": seconds})
    H.save_panel(path, panel)
    say(f"season {year}: written {path} in {seconds:.0f}s")
    return path


def run(years, out_dir: Path | None, force: bool, say) -> None:
    for year in years:
        score_season(year, out_dir, say, force)
