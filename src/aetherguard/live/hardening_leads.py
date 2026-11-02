"""Which upper bound `uncertain_high` should test on the forecast leads (spec section 11.6), on the forecast-skill pairs.

    python -m aetherguard.live.hardening leads

The evidence base is the one the widening factors were derived on (`forecast_skill hazard`): every issue day of the local
GFS archive (June-September 2021-2024), leads 1-3, the same seeded sample of cells (every labelled cell plus 2,500 drawn
with seed 20261015). For each pair the frozen v3-live model scores the target day from observed features (the level the
day will be published at: point risk against the card's thresholds per region, `uncertain_high` on the re-centred
`risk_hi`, the rain cap of the post-model rules) and from forecast-driven features under three options:

  widened    `uncertain_high` tests `risk_hi` x the lead's widening factor (what the runner did);
  unwidened  `uncertain_high` tests the re-centred ensemble `risk_hi` of the forecast features;
  none       no `uncertain_high` on a forecast lead (point risk only).

Each with the same rain cap on the forecast's own 7-day rain. PRE-DECLARED: the option with the higher exact level
agreement with the observed-feature level is chosen; a tie (equal to three decimals) goes to the lower Watch-or-above
share. Nothing here reads 2018 or a live day; the published widening factors themselves are not changed.
"""
from __future__ import annotations

import json
import time
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from ..alerts import levels as lv
from ..features import imerg_features as F
from ..hazard import model as hm
from ..hazard.jsonio import dump_json
from ..ingest import imerg
from . import forecast_features as FF
from . import forecast_skill as FS
from . import hardening as H
from . import postrules as pr
from . import run as live_run

OPTIONS = ("widened", "unwidened", "none")
RESULT_FILE = "forecast_leads.json"
TIE_DECIMALS = 3


def score_side(model: hm.HazardModel, frame: pd.DataFrame) -> dict[str, np.ndarray]:
    """risk, re-centred risk_hi and the 7-day rain of every row (NaN where the 3-day rain is unknown)."""
    out = {name: np.full(len(frame), np.nan) for name in ("risk", "risk_hi", "acc_7")}
    scorable = np.isfinite(frame[live_run.CORE_COLUMN].to_numpy(dtype=np.float64))
    if scorable.any():
        scored = model.score(frame[scorable])
        out["risk"][scorable] = scored["risk"].to_numpy()
        out["risk_hi"][scorable] = scored["risk_hi"].to_numpy()
    out["acc_7"] = frame["irain_acc_7"].to_numpy(dtype=np.float64)
    return out


def levels_of(risk, bound, acc7, region, thresholds: lv.RegionThresholds, rules: pr.PostRules) -> np.ndarray:
    raw, _ = lv.raw_level(risk, bound, thresholds, region)
    ok = rules.rain.passes_arrays({7: acc7}) if rules.gates and rules.rain is not None else np.ones(len(raw), bool)
    capped, _ = pr.capped_levels(raw, ok, np.zeros(len(raw), dtype=bool), rules)
    return capped


def run(cfg: dict, rules: pr.PostRules, say=print) -> dict:
    started = time.perf_counter()
    model = live_run.load_live_model(cfg)
    cells = live_run.load_cells(cfg)
    rain_dir = live_run.project_path(cfg["imerg"]["processed_dir"])
    store = imerg.ImergStore(rain_dir, "late")
    clim = live_run.load_climatology(cfg, store, F.cell_pixels(cells["cell_id"].to_numpy()))
    days = FS.issue_days_of_archive()
    labels = FS.load_labels(cells, days[0], days[-1] + timedelta(days=max(FS.LEADS)))
    labels = labels.restrict_to(set(int(c) for c in cells["cell_id"]))
    sample = FS.candidate_cells(cells, set(labels.cell_ids()), FS.DEFAULT_SAMPLE_CELLS, FS.DEFAULT_SEED)
    thresholds = live_run.card_thresholds(model, sample["region"])
    if not isinstance(thresholds, lv.RegionThresholds):
        raise ValueError("the live model is expected to be calibrated per region")
    factors, why = live_run.load_widening(cfg, live_run.LiveDeps())
    if factors is None:
        raise ValueError(f"no widening factors: {why}")
    region = sample["region"].to_numpy(dtype=object)
    observed_cache: dict = {}
    tallies = {k: {o: np.zeros((4, 4), dtype=np.int64) for o in OPTIONS} for k in FS.LEADS}
    say(f"{len(days)} issue days, {len(sample)} cells")
    for i, day in enumerate(sorted(days)):
        loaded = FS.load_gfs_day(rain_dir, day)
        if loaded is None:
            continue
        forecast, valid = loaded
        for k in FS.LEADS:
            if not valid[k - 1]:
                continue
            target = day + timedelta(days=k)
            if target not in observed_cache:
                frame = pd.concat([sample, FF.lead_features(sample, target, 0, store, None, clim)], axis=1)
                observed_cache[target] = score_side(model, frame)
            obs = observed_cache[target]
            fc = score_side(model, pd.concat([sample, FF.lead_features(sample, day, k, store, forecast, clim)], axis=1))
            both = np.isfinite(obs["risk"]) & np.isfinite(fc["risk"])
            if not both.any():
                continue
            observed_level = levels_of(obs["risk"][both], obs["risk_hi"][both], obs["acc_7"][both], region[both],
                                       thresholds, rules)
            bounds = {"widened": np.maximum(fc["risk_hi"][both] * factors[k][1], fc["risk"][both]),
                      "unwidened": fc["risk_hi"][both], "none": fc["risk"][both]}
            for option, bound in bounds.items():
                level = levels_of(fc["risk"][both], bound, fc["acc_7"][both], region[both], thresholds, rules)
                np.add.at(tallies[k][option], (observed_level.astype(np.int64), level.astype(np.int64)), 1)
        observed_cache = {t: v for t, v in observed_cache.items() if t > day}
        if (i + 1) % 25 == 0 or i + 1 == len(days):
            say(f"  issue day {i + 1}/{len(days)} ({time.perf_counter() - started:.0f}s)")
    result = {"issue_days": len(days), "cells": int(len(sample)), "seed": FS.DEFAULT_SEED, "rules": rules.to_dict(),
              "widening": {str(k): {"lo": lo, "hi": hi} for k, (lo, hi) in factors.items()}, "leads": {}}
    for k in FS.LEADS:
        entry = {}
        for option in OPTIONS:
            confusion = tallies[k][option]
            n = int(confusion.sum())
            entry[option] = {"n": n, "confusion": confusion.tolist(),
                             "exact_agreement": float(np.trace(confusion) / n) if n else None,
                             "forecast_watch_plus_share": float(confusion[:, 1:].sum() / n) if n else None,
                             "observed_watch_plus_share": float(confusion[1:, :].sum() / n) if n else None}
        result["leads"][str(k)] = entry
    result["choice"] = choose(result["leads"])
    result["seconds"] = time.perf_counter() - started
    path = H.alerts_dir(H.DEV_DIR) / RESULT_FILE
    dump_json(path, result)
    say(f"wrote {hm.display_path(path)}; choice: {result['choice']['option']}")
    return result


def choose(leads: dict) -> dict:
    """The pre-declared choice over all leads pooled: higher exact agreement, ties (to TIE_DECIMALS) to the lower
    forecast Watch-or-above share."""
    pooled = {}
    for option in OPTIONS:
        n = sum(leads[k][option]["n"] for k in leads)
        agree = sum(leads[k][option]["exact_agreement"] * leads[k][option]["n"] for k in leads) / n
        watch = sum(leads[k][option]["forecast_watch_plus_share"] * leads[k][option]["n"] for k in leads) / n
        pooled[option] = {"exact_agreement": agree, "forecast_watch_plus_share": watch}
    best = min(OPTIONS, key=lambda o: (-round(pooled[o]["exact_agreement"], TIE_DECIMALS),
                                       pooled[o]["forecast_watch_plus_share"]))
    return {"option": best, "pooled": pooled,
            "rule": "higher exact level agreement with the observed-feature level (pooled over leads 1-3); a tie to three "
                    "decimals goes to the lower forecast Watch+ share (pre-declared)"}


def adopt(rules_path: Path, result: dict, say=print) -> pr.PostRules:
    """Write the chosen forecast-lead bound into the rules file (the rest of the rules and their derivation are kept)."""
    rules = pr.load_rules(rules_path)
    chosen = replace(rules, lead_uncertain_bound=result["choice"]["option"])
    derivation = {**rules.derivation, "lead_uncertain_bound": {
        "source": hm.display_path(H.alerts_dir(H.DEV_DIR) / RESULT_FILE), **result["choice"]}}
    pr.save_rules(rules_path, chosen, derivation)
    say(f"wrote lead_uncertain_bound={chosen.lead_uncertain_bound} into {hm.display_path(Path(rules_path))}")
    return chosen


def load_result() -> dict:
    return json.loads((H.alerts_dir(H.DEV_DIR) / RESULT_FILE).read_text(encoding="utf-8"))
