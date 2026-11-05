"""Baseline verification report: v3 against two simple models, on the development seasons and on 2018.

    python -m aetherguard.verify baseline    # reports/phase7_verification_baseline.{json,md}

Everything is loaded exactly as `live.precision_study` loads it (`run_dev`, `run_heldout`): the development panels are the
out-of-fold seasons 2007-2017, the 2018 panel is the operational one, and v3's levels are `hardening_dev.season_levels` with the
section 11 rules, which is the study's `baseline` condition. Seasons are read from 1 June. 2018 is re-measured with the frozen
v3 and is not a new held-out look; its cell-exact hits must equal the published ones, or the loading is wrong.

* Development panels hold every event cell and a seeded sample of universe cells (`in_universe`). Alert cell-days, precision
  and alert share are counted on the universe-sample cells only, a random sample and so unbiased; POD is over all development
  events. Tolerant matching there sees only the panel cells, so the tolerant development POD is a lower bound. 2018 holds every
  cell and is the primary tolerant measurement.
* Models: `v3`; `rain_3d`, three 3-day rain cuts fitted to v3's development shares; `susceptibility`, a static map (season-mean
  v3 risk) alerted at v3's shares of the evaluated set. `shares` of each model give its target and realised shares.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from ..alerts import levels as lv
from ..hazard import model as hm
from ..hazard.jsonio import dump_json
from ..live import backtest as bt
from ..live import burden
from ..live import hardening as H
from ..live import hardening_dev as D
from ..live import precision_study as ps
from ..live import run as live_run
from ..live.backtest import BOOTSTRAP
from .baselines import Shares, rain_baseline, realised_shares, susceptibility_baseline
from .matching import CELL_EXACT, Tolerance, match
from .scores import bootstrap_scores

LEVELS = (1, 2, 3)
LEVEL_NAMES = {1: "Watch+", 2: "Warning+", 3: "Emergency"}
TOLERANCES = {"tolerant": Tolerance(10.0, 1), "cell_exact": CELL_EXACT}
MODELS = {
    "v3": "v3 (frozen model, section 11 rules)",
    "rain_3d": "3-day rain cuts at v3's development shares",
    "susceptibility": "static map (season-mean v3 risk)",
}
REPORT_STEM = "phase7_verification_baseline"


def model_table(
    levels_by_model: dict[str, np.ndarray],
    scored: np.ndarray,
    cell_ids: np.ndarray,
    days: list[date],
    events: pd.DataFrame,
    tolerances: dict[str, Tolerance],
    universe: np.ndarray | None = None,
    boot: dict = BOOTSTRAP,
) -> dict:
    """`bootstrap_scores` per model, tolerance name and alert level (keys "1", "2", "3" for Watch+, Warning+, Emergency).

    `universe` (bool per cell) restricts alert cell-days, precision and alert share to those cells while POD stays over all
    events matched against every cell.
    """
    scored = np.asarray(scored, dtype=bool)
    if universe is not None:
        universe = np.asarray(universe, dtype=bool)
        if universe.shape != (len(cell_ids),):
            raise ValueError(f"universe {universe.shape} must hold one flag per cell ({len(cell_ids)})")
    table: dict[str, dict] = {}
    for model, levels in levels_by_model.items():
        table[model] = {}
        for name, tolerance in tolerances.items():
            m = match(levels, cell_ids, days, events, tolerance)
            view, view_scored = levels, scored
            if universe is not None:
                m = replace(m, alert_verified=m.alert_verified[universe])
                view, view_scored = levels[universe], scored[universe]
            table[model][name] = {str(k): bootstrap_scores(view, view_scored, m, k, boot) for k in LEVELS}
    return table


def susceptibility_levels(
    static_score: np.ndarray, n_days: int, scored: np.ndarray, shares: Shares, universe: np.ndarray | None = None
) -> np.ndarray:
    """`susceptibility_baseline` levels; with `universe` the shares hold on those cells and the others follow the same cuts.

    Each day and level, a cell outside the universe alerts when its static score reaches the lowest score alerted among the
    universe cells that day, so the universe sample reaches the shares and the extra (event) cells are alerted on equal terms.
    """
    static_score, scored = np.asarray(static_score, dtype=np.float64), np.asarray(scored, dtype=bool)
    if universe is None:
        return susceptibility_baseline(static_score, n_days, scored, shares)
    universe = np.asarray(universe, dtype=bool)
    inside = susceptibility_baseline(static_score[universe], n_days, scored[universe], shares)
    levels = np.zeros(scored.shape, dtype=np.int8)
    levels[universe] = inside
    outside = ~universe
    for level in LEVELS:
        cut = np.where(inside >= level, static_score[universe][:, None], np.inf).min(axis=0)
        levels[outside] += (scored[outside] & (static_score[outside][:, None] >= cut[None, :])).astype(np.int8)
    return levels


# ------------------------------------------------------------------------------------------------------ loading

@dataclass
class Part:
    """One season from 1 June: v3's levels and what the baselines need."""

    cell_ids: np.ndarray
    in_universe: np.ndarray
    days: list[date]
    scored: np.ndarray
    acc_3: np.ndarray
    static_score: np.ndarray  # mean v3 risk of each cell over the season's scored days; -inf for a cell never scored
    v3: np.ndarray
    events: pd.DataFrame


def extract(season: D.Season, config, base_rules) -> Part:
    panel, first = season.panel, season.first
    risk = np.asarray(panel["risk"])[:, first:]
    finite = np.isfinite(risk)
    count = finite.sum(axis=1)
    static = np.full(len(risk), -np.inf)
    np.divide(np.where(finite, risk, 0.0).sum(axis=1), count, out=static, where=count > 0)
    return Part(
        cell_ids=panel.cells["cell_id"].to_numpy(dtype=np.int64),
        in_universe=panel.cells["in_universe"].to_numpy(dtype=bool),
        days=list(panel.days[first:]),
        scored=panel.scored[:, first:].copy(),
        acc_3=np.array(panel["acc_3"])[:, first:],
        static_score=static,
        v3=D.season_levels(season, "new_hi", config, base_rules)[:, first:],
        events=season.events[["cell_id", "date"]].reset_index(drop=True),
    )


def load_development(model, config, base_rules, say) -> list[Part]:
    """The development seasons, one panel in memory at a time, as `precision_study.run_dev` loads them."""
    years = burden.DEV_YEARS
    events = burden.development_events(years)
    parts = []
    for year in years:
        season = D.load_seasons(H.alerts_dir(H.DEV_DIR), [year], model.card, events, say)[0]
        parts.append(extract(season, config, base_rules))
        del season
    for part in parts[1:]:
        if not (np.array_equal(part.cell_ids, parts[0].cell_ids) and np.array_equal(part.in_universe, parts[0].in_universe)):
            raise ValueError("the development panels do not share one cell set")
    return parts


def load_2018(cfg: dict, model, config, base_rules) -> Part:
    """The 2018 season as `precision_study.run_heldout` loads it."""
    spec = bt.load_set("season_2018", cfg=cfg)
    panel = H.load_panel(H.alerts_dir(H.HELDOUT_DIR) / H.HELDOUT_FILE)
    if panel.cells["cell_id"].tolist() != spec.cells["cell_id"].tolist():
        raise ValueError("the 2018 panel does not hold the cells of the season_2018 backtest set")
    season = D.Season(2018, panel, panel.days.index(spec.start), spec.events.reset_index(drop=True),
                      lv.card_region_thresholds(model.card, panel.cells["region"]))
    return extract(season, config, base_rules)


def published_2018_hits() -> dict[str, int]:
    """The 2018 cell-exact hits by level as the accuracy hardening published them, keyed "1", "2", "3"."""
    path = H.alerts_dir(H.HELDOUT_DIR) / "evaluation.json"
    detected = json.loads(path.read_text(encoding="utf-8"))["season_2018"]["conditions"]["after"]["detected_at_least"]
    return {str(lv.parse_level(name)): int(entry["hits"]) for name, entry in detected.items()}


# ----------------------------------------------------------------------------------------------------- measuring

@dataclass
class RainFit:
    """What the rain baseline takes from the development seasons."""

    acc_3: np.ndarray
    scored: np.ndarray
    shares: Shares


def pooled(parts: list[Part], field: str) -> np.ndarray:
    return np.concatenate([getattr(p, field) for p in parts], axis=1)


def fit_rain(parts: list[Part], universe: np.ndarray | None) -> RainFit:
    """The rain baseline's fit on the `universe` cells of `parts` pooled over days: their 3-day rain and v3's realised shares."""
    rows = np.ones(len(parts[0].cell_ids), dtype=bool) if universe is None else universe
    scored = pooled(parts, "scored")[rows]
    return RainFit(pooled(parts, "acc_3")[rows], scored, realised_shares(pooled(parts, "v3")[rows], scored))


def measure(name: str, parts: list[Part], universe: np.ndarray | None, fit: RainFit | None, say) -> tuple[dict, RainFit]:
    """The model table of a set of seasons pooled over days; `fit=None` fits the rain baseline on this set's own universe."""
    cell_ids = parts[0].cell_ids
    days = [d for p in parts for d in p.days]
    scored, v3, acc_3 = pooled(parts, "scored"), pooled(parts, "v3"), pooled(parts, "acc_3")
    events = pd.concat([p.events for p in parts], ignore_index=True)
    rows = np.ones(len(cell_ids), dtype=bool) if universe is None else universe
    v3_shares = realised_shares(v3[rows], scored[rows])
    if fit is None:
        fit = fit_rain(parts, universe)
    rain = rain_baseline(acc_3, scored, fit.acc_3, fit.scored, fit.shares)
    susceptibility = np.concatenate(
        [susceptibility_levels(p.static_score, len(p.days), p.scored, v3_shares, universe) for p in parts], axis=1)
    levels = {"v3": v3, "rain_3d": rain, "susceptibility": susceptibility}
    shares = {
        "v3": {"target": None, "realised": list(v3_shares)},
        "rain_3d": {"target": list(fit.shares), "realised": list(realised_shares(rain[rows], scored[rows]))},
        "susceptibility": {"target": list(v3_shares), "realised": list(realised_shares(susceptibility[rows], scored[rows]))},
    }
    say(f"{name}: scoring {len(cell_ids)} cells x {len(days)} days, {len(events)} events")
    entry = {
        "cells": int(len(cell_ids)),
        "cells_counted_for_alerts": int(rows.sum()),
        "days": len(days),
        "events": int(len(events.drop_duplicates())),
        "shares": shares,
        "models": model_table(levels, scored, cell_ids, days, events, TOLERANCES, universe),
    }
    return entry, fit


def run(cfg: dict, say=print) -> dict:
    started = time.perf_counter()
    model, config, base_rules = ps.load_inputs(cfg)
    say("loading the development panels")
    parts = load_development(model, config, base_rules, say)
    development, fit = measure("development", parts, parts[0].in_universe, None, say)
    del parts
    say("loading the 2018 panel")
    season_2018, _ = measure("season_2018", [load_2018(cfg, model, config, base_rules)], None, fit, say)
    hits = {k: v["hits"] for k, v in season_2018["models"]["v3"]["cell_exact"].items()}
    published = published_2018_hits()
    if hits != published:
        raise ValueError(f"v3 cell-exact hits on 2018 {hits} differ from the published {published}: the loading is wrong")
    return {
        "protocol": {
            "alert_levels": LEVEL_NAMES,
            "tolerances": {n: {"km": t.km, "days": t.days} for n, t in TOLERANCES.items()},
            "models": MODELS,
            "development": f"pooled {burden.DEV_YEARS[0]}-{burden.DEV_YEARS[-1]} seasons from 1 June, out of fold; alert "
                           "cell-days, precision and alert share on the seeded universe-sample cells only, POD on all "
                           "development events",
            "season_2018": "every cell of the operational 2018 panel from 1 June; re-measured with the frozen v3, not a new "
                           "held-out look",
            "bootstrap": BOOTSTRAP,
            "published_2018_cell_exact_hits": published,
        },
        "sets": {"development": development, "season_2018": season_2018},
        "seconds": time.perf_counter() - started,
    }


# ------------------------------------------------------------------------------------------------------- output

def _pct(value: float | None, digits: int = 1) -> str:
    return "n/a" if value is None or value != value else f"{100 * value:.{digits}f}%"


def _interval(ci: list[float], digits: int = 1) -> str:
    return "[n/a]" if any(v != v for v in ci) else f"[{100 * ci[0]:.{digits}f}, {100 * ci[1]:.{digits}f}]"


TABLE_HEADER = ("| model | tolerance | level | events | hits | POD [95% CI] | alert cell-days | precision [95% CI] | realised share |"
                "\n|---|---|---|---|---|---|---|---|---|")
SHARE_HEADER = "| model | target Watch+ / Warning+ / Emergency | realised |\n|---|---|---|"


def _rows(entry: dict, models=MODELS) -> list[str]:
    rows = []
    for model in models:
        for tolerance in TOLERANCES:
            for level in LEVELS:
                s = entry["models"][model][tolerance][str(level)]
                rows.append(
                    f"| {model} | {tolerance} | {LEVEL_NAMES[level]} | {s['events']} | {s['hits']} | "
                    f"{_pct(s['pod'])} {_interval(s['pod_ci'])} | {s['alert_cell_days']:,} | "
                    f"{_pct(s['precision'], 3)} {_interval(s['precision_ci'], 3)} | {_pct(s['alert_share'], 2)} |")
    return rows


def _share_rows(entry: dict, models=MODELS) -> list[str]:
    rows = []
    for model in models:
        s = entry["shares"][model]
        target = "n/a" if s["target"] is None else " / ".join(_pct(v, 2) for v in s["target"])
        rows.append(f"| {model} | {target} | {' / '.join(_pct(v, 2) for v in s['realised'])} |")
    return rows


def markdown(result: dict) -> str:
    dev, y18 = result["sets"]["development"], result["sets"]["season_2018"]
    header = ("| model | tolerance | level | events | hits | POD [95% CI] | alert cell-days | precision [95% CI] | realised share |\n"
              "|---|---|---|---|---|---|---|---|---|")
    share_header = "| model | target Watch+ / Warning+ / Emergency | realised |\n|---|---|---|"
    published = result["protocol"]["published_2018_cell_exact_hits"]
    lines = [
        "# Verification baseline (phase 7, W0)",
        "",
        "v3 against two simple models: three 3-day rain cuts fitted to v3's development shares (`rain_3d`), and a static map "
        "(season-mean v3 risk) alerted at v3's shares of the evaluated set (`susceptibility`). Both are burden-matched to v3 on "
        "the development seasons; on 2018 only `susceptibility` is (see the caveats below). "
        "POD is the share of events whose highest level within tolerance reached the level; precision is the share of alert "
        "cell-days that an event lies within tolerance of. `tolerant` is 10 km and 1 day, `cell_exact` the same cell and day. "
        "Intervals are 95% percentile bootstraps (days resampled for precision, events for POD).",
        "",
        "## Reading this report",
        "",
        "- 2018 is re-measured with the frozen v3 and is not a new held-out look. Its v3 cell-exact Watch+ / Warning+ / Emergency "
        f"hits, {' / '.join(str(published[str(k)]) for k in LEVELS)}, equal the published ones.",
        "- Development panels hold every event cell and a seeded sample of universe cells. Alert cell-days, precision and alert "
        "share are counted on the universe-sample cells only (a random sample, so unbiased) and are not scaled up to the full "
        "universe; POD is over all development events.",
        "- Tolerant matching on development panels only sees the panel cells, so the tolerant development POD is a lower bound. "
        "2018 (all cells) is the primary tolerant measurement.",
        "- The rain baseline's cuts are fitted on the development universe-sample cell-days and applied unchanged to 2018; on the "
        "development panels they are applied to the data they were fitted on.",
        "- On 2018 `rain_3d` keeps its development cuts and raises fewer alerts than v3 (see the shares table), so its POD "
        "there is not burden-matched.",
        "- `susceptibility` is the static map (season-mean v3 risk): each day the scored cells of highest mean risk are alerted, "
        "with no rain. It is computed from v3's risk over the same season it is scored on (hindsight), so it is an optimistic "
        "baseline.",
        "",
        f"## 2018 ({y18['cells']:,} cells, {y18['days']} days, {y18['events']} events)",
        "",
        header,
        *_rows(y18),
        "",
        "Alert shares, target against realised:",
        "",
        share_header,
        *_share_rows(y18),
        "",
        f"## Development 2007-2017, out of fold ({dev['cells']:,} cells, of which {dev['cells_counted_for_alerts']:,} "
        f"universe-sample cells counted for alerts; {dev['days']} days, {dev['events']} events)",
        "",
        header,
        *_rows(dev),
        "",
        "Alert shares on the universe-sample cells, target against realised:",
        "",
        share_header,
        *_share_rows(dev),
        "",
    ]
    return "\n".join(lines)


def write_baseline(out: Path, say=print) -> dict:
    result = run(live_run.load_run_config(), say)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    dump_json(out / f"{REPORT_STEM}.json", result)
    (out / f"{REPORT_STEM}.md").write_text(markdown(result), encoding="utf-8")
    say(f"wrote {hm.display_path(out / REPORT_STEM)}.{{json,md}}")
    return result
