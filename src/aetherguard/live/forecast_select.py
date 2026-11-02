"""Choice of the forecast rain of the forecast leads, and the accuracy of the scenario certainty (spec section 12).

    python -m aetherguard.live.forecast_select select      [--cells N] [--seed S] [--bootstrap B]
    python -m aetherguard.live.forecast_select scenarios   [--cells N] [--seed S] [--bootstrap B]

select     Candidates {GFS, ECMWF HRES, ECMWF ensemble mean} x {raw, bias-corrected} (GEFS was not archived: see the report).
           For every June-September issue day of 2024 (primary) and 2023 (secondary) and every lead, the v3 model scores the same
           2,536 cells (the seeded sample of `forecast_skill`) from forecast-driven features and from the observed features of
           the target day. Both sides get the published level of a forecast row: the model's point level, `uncertain_high` of
           the rules and the rain cap of section 11. Per lead the candidates are ranked by
             1. agreement of the forecast level with the observed-feature level (primary), then
             2. recall of the observed Watch+ and Warning+ levels, then
             3. rain MAE (equal to the CRPS of a single-valued forecast) and the >= 50 mm hit rate and false-alarm ratio.
           A candidate replaces GFS (raw) only when its agreement beats GFS by more than the bootstrap standard error of the
           difference (days resampled) and its Warning+ recall is not lower. The chosen configuration per lead is written to
           `forecast_selection` (configs/live_run.yaml), the widening factors of the chosen configuration (10th / 90th percentile
           of observed / forecast risk on 2024) to `forecast_widening`, the old GFS factors being kept as the fallback's.
scenarios  On 2024, with the chosen configuration, each cell of each forecast lead is scored with no further rain, with the
           forecast and with its heavy-rain bound; "firm" cells (the three levels agree) are compared with the others on how
           often the forecast level equals the observed-feature level.
Writes `reports/phase6_forecast_selection.{json,md}` and `reports/phase6_forecast_certainty.{json,md}`. Everything is seeded.
"""
from __future__ import annotations

import argparse
import json
import os
import pickle
import shutil
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from ..alerts import levels as lv
from ..alerts.config import load_config_file as load_alert_config
from ..config import PROJECT_ROOT
from ..features import imerg_features as F
from ..hazard import model as hm
from ..hazard.freeze import FrozenMismatchError, default_external_files, verify_freeze
from ..hazard.jsonio import dump_json
from ..ingest import imerg
from . import forecast_choice as fc
from . import forecast_features as FF
from . import forecast_map as fm
from . import forecast_skill as FS
from . import postrules as pr
from . import run as live_run
from .sources import project_path

LEADS = fc.LEADS
CANDIDATES = tuple(fc.Config(source, mapped) for source in fc.SOURCES for mapped in (False, True))
BASELINE = fc.GFS_RAW
PRIMARY_YEAR, SECONDARY_YEAR = 2024, 2023
DEFAULT_BOOTSTRAP = 2000
DEFAULT_SEED = FS.DEFAULT_SEED
SELECTION_STEM, CERTAINTY_STEM = "phase6_forecast_selection", "phase6_forecast_certainty"
DAY_FIELDS = ("n", "same", "within_one", "obs_watch", "hit_watch", "fc_watch", "obs_warning", "hit_warning", "fc_warning")
PER_DAY_FILE = "forecast_selection_per_day.npz"


def key(config: fc.Config) -> str:
    return f"{config.source}{'+map' if config.mapped else ''}"


# ------------------------------------------------------------------------------------------------------ set-up

@dataclass
class Setup:
    cfg: dict
    model: hm.HazardModel
    thresholds: object
    alert_config: object
    rules: pr.PostRules
    sample: pd.DataFrame
    clim: object
    store: object
    rain_dir: Path
    maps: fm.ForecastMaps
    groups: dict
    watch_floor: float
    seed: int


def build_setup(cfg: dict, maps_path: Path, n_cells: int, seed: int) -> Setup:
    model_config = project_path(cfg["model_config"])
    model_dir = hm.configured_model_dir(hm.hazard_config(model_config))
    try:
        verify_freeze(model_dir, default_external_files(model_config))
    except FrozenMismatchError as exc:
        raise live_run.LiveRunError(f"v3 model does not match its freeze record: {exc}") from exc
    model = hm.HazardModel.load(model_dir)
    cells = live_run.load_cells(cfg)
    rain_dir = project_path(cfg["imerg"]["processed_dir"])
    store = imerg.ImergStore(rain_dir, "late")
    clim = live_run.load_climatology(cfg, store, F.cell_pixels(cells["cell_id"].to_numpy()))
    labels = FS.load_labels(cells, date(2021, 6, 1), date(2024, 9, 30) + timedelta(days=max(LEADS)))
    scored = set(int(c) for c in cells["cell_id"])
    sample = FS.candidate_cells(cells, labels.restrict_to(scored).cell_ids(), n_cells, seed)
    thresholds = live_run.card_thresholds(model, sample["region"])
    pooled = live_run.pooled_thresholds(thresholds)
    return Setup(cfg=cfg, model=model, thresholds=thresholds, alert_config=load_alert_config(project_path(cfg["alert_config"])),
                 rules=pr.load_rules(project_path(cfg["post_rules"])), sample=sample, clim=clim, store=store,
                 rain_dir=rain_dir, maps=fm.ForecastMaps.load(maps_path, fm.pixel_regions_of(cfg)),
                 groups=FS._region_groups(cfg), watch_floor=FS.FLOOR_FRACTION * pooled.watch, seed=seed)


def published(setup: Setup, frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(point risk, published level, scored) of `frame`: the level of a forecast row of the daily run (unwidened bound, rain cap)."""
    scorable = live_run.scorable_mask(frame, setup.model.columns)
    scores, level, _ = live_run.lead_scores(setup.model, frame, scorable, setup.thresholds, setup.alert_config, setup.rules, None)
    ok = pr.rain_ok(frame, setup.rules) | ~scorable
    level = pr.capped_levels(level, ok, np.zeros(len(frame), dtype=bool), setup.rules)[0]
    return scores["risk"].to_numpy(dtype=np.float64), level, scorable


def observed_side(setup: Setup, day: date, lead: int):
    features = FF.lead_features(setup.sample, day + timedelta(days=lead), 0, setup.store, None, setup.clim)
    return published(setup, pd.concat([setup.sample, features], axis=1))


def forecast_side(setup: Setup, day: date, lead: int, rain: np.ndarray):
    features = FF.lead_features(setup.sample, day, lead, setup.store, rain, setup.clim)
    return published(setup, pd.concat([setup.sample, features], axis=1))


def candidate_rain(setup: Setup, products: dict, config: fc.Config, lead: int) -> fc.LeadField | None:
    """The rain of `config` for D+1..D+lead (bias-corrected when the config says so); None when the source lacks a day."""
    choice = fc.ForecastChoice({k: config for k in LEADS}, fallback=config, maps_file="maps" if config.mapped else None)
    return fc.resolve_lead(products, choice, setup.maps, lead)


def usable_everywhere(products: dict, lead: int) -> bool:
    return all(source in products and products[source].valid[:lead].all() for source in fc.SOURCES)


# ---------------------------------------------------------------------------------------------------- statistics

def day_counts(obs_level, level, both) -> np.ndarray:
    o, f = np.asarray(obs_level)[both], np.asarray(level)[both]
    return np.array([o.size, (o == f).sum(), (np.abs(o.astype(int) - f) <= 1).sum(),
                     (o >= lv.WATCH).sum(), ((o >= lv.WATCH) & (f >= lv.WATCH)).sum(), (f >= lv.WATCH).sum(),
                     (o >= lv.WARNING).sum(), ((o >= lv.WARNING) & (f >= lv.WARNING)).sum(), (f >= lv.WARNING).sum()],
                    dtype=np.int64)


def pooled(counts: np.ndarray) -> dict:
    """Metrics from per-day count rows (days, len(DAY_FIELDS))."""
    t = dict(zip(DAY_FIELDS, counts.sum(axis=0))) if len(counts) else dict.fromkeys(DAY_FIELDS, 0)
    ratio = lambda a, b: float(a) / float(b) if b else None   # noqa: E731
    return {"pairs": int(t["n"]), "agreement": ratio(t["same"], t["n"]), "within_one": ratio(t["within_one"], t["n"]),
            "watch_recall": ratio(t["hit_watch"], t["obs_watch"]), "watch_precision": ratio(t["hit_watch"], t["fc_watch"]),
            "warning_recall": ratio(t["hit_warning"], t["obs_warning"]),
            "warning_precision": ratio(t["hit_warning"], t["fc_warning"]), "observed_warning": int(t["obs_warning"])}


def agreement_of(counts: np.ndarray) -> float:
    total = counts[:, 0].sum()
    return float(counts[:, 1].sum() / total) if total else float("nan")


def bootstrap(counts_by_candidate: dict[str, np.ndarray], baseline: str, n_boot: int, seed: int) -> dict:
    """Standard errors of each candidate's agreement and of its difference from the baseline: issue days resampled with
    replacement (the same days for every candidate), pooled agreement of the resample."""
    rng = np.random.default_rng(seed)
    n_days = len(next(iter(counts_by_candidate.values())))
    if n_days == 0:
        return {name: {"agreement_se": None, "delta_vs_baseline": None, "delta_se": None} for name in counts_by_candidate}
    draws = rng.integers(0, n_days, size=(n_boot, n_days))
    boot = {}
    for name, counts in counts_by_candidate.items():
        same, total = counts[:, 1][draws].sum(axis=1), counts[:, 0][draws].sum(axis=1)
        boot[name] = same / np.maximum(total, 1)
    out = {}
    for name, counts in counts_by_candidate.items():
        delta = boot[name] - boot[baseline]
        out[name] = {"agreement_se": float(boot[name].std(ddof=1)),
                     "delta_vs_baseline": agreement_of(counts) - agreement_of(counts_by_candidate[baseline]),
                     "delta_se": float(delta.std(ddof=1))}
    return out


# ------------------------------------------------------------------------------------------------ the selection

def season_observed(setup: Setup, year: int) -> tuple[np.ndarray, date]:
    rows, cols = np.divmod(np.arange(imerg.ROWS * imerg.COLS), imerg.COLS)
    days = fm.season_days(year)
    first, last = days[0], days[-1] + timedelta(days=max(LEADS))
    return F.imd_day_series(setup.store.gather(rows, cols, first, (last - first).days + 1)), first


CHECKPOINT_EVERY_DAYS = 5


def _save_checkpoint(path: Path, state: dict) -> None:
    part = path.with_name(path.name + ".part")
    with part.open("wb") as handle:
        pickle.dump(state, handle, protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(part, path)


def evaluate_year(setup: Setup, year: int, progress=None, checkpoint: Path | None = None) -> dict:
    """Per (lead, candidate): per-day count rows, rain accumulators and risk ratios for the issue days of `year`.

    With a `checkpoint` file the running state is saved every few issue days and picked up again when the file exists, so an
    interrupted evaluation resumes with the same result as an uninterrupted one (days are independent and the state is exact).
    """
    imd, first = season_observed(setup, year)
    days = fm.season_days(year)
    state = None
    if checkpoint is not None and Path(checkpoint).is_file():
        with Path(checkpoint).open("rb") as handle:
            state = pickle.load(handle)
    if state is None:
        state = {"done": 0,
                 "counts": {(k, key(c)): [] for k in LEADS for c in CANDIDATES},
                 "rain": {(k, key(c)): {g: FS.SkillAccumulator(thresholds=(50.0,)) for g in setup.groups}
                          for k in LEADS for c in CANDIDATES},
                 "ratios": {(k, key(c)): [] for k in LEADS for c in CANDIDATES}, "used": {k: [] for k in LEADS}}
    counts, rain, ratios, used = state["counts"], state["rain"], state["ratios"], state["used"]
    for i, day in enumerate(days):
        if i < state["done"]:
            continue
        products = fc.load_product_days(setup.rain_dir, day)
        for k in LEADS:
            if not usable_everywhere(products, k):
                continue
            obs_risk, obs_level, obs_ok = observed_side(setup, day, k)
            observed_rain = imd[:, (day + timedelta(days=k) - first).days - 1]
            used[k].append(day.isoformat())
            for config in CANDIDATES:
                field = candidate_rain(setup, products, config, k)
                risk, level, ok = forecast_side(setup, day, k, field.days)
                both = obs_ok & ok
                counts[(k, key(config))].append(day_counts(obs_level, level, both))
                informative = both & (np.maximum(obs_risk, risk) >= setup.watch_floor) & (obs_risk > 0) & (risk > 0)
                ratios[(k, key(config))].append((obs_risk[informative] / risk[informative]).astype(np.float32))
                predicted = field.days[k - 1].ravel()
                for name, pixels in setup.groups.items():
                    rain[(k, key(config))][name].add(observed_rain[pixels], predicted[pixels])
        state["done"] = i + 1
        if checkpoint is not None and (state["done"] % CHECKPOINT_EVERY_DAYS == 0 or state["done"] == len(days)):
            _save_checkpoint(Path(checkpoint), state)
        if progress is not None:
            progress(year, i + 1, len(days))
    return {"counts": {name: np.stack(rows) if rows else np.zeros((0, len(DAY_FIELDS)), dtype=np.int64)
                       for name, rows in counts.items()},
            "rain": rain, "ratios": {name: np.concatenate(parts) if parts else np.empty(0, np.float32)
                                     for name, parts in ratios.items()}, "days": used}


def rain_summary(accumulators: dict) -> dict:
    out = {}
    for group, acc in accumulators.items():
        s = acc.summary()
        e = s["events"]["50"]
        out[group] = {"bias_mm": s["bias_mm"], "mae_mm": s["mae_mm"], "hit_rate_50": e["hit_rate"],
                      "false_alarm_ratio_50": e["false_alarm_ratio"]}
    return out


def table_of(result: dict, n_boot: int, seed: int) -> dict:
    """{lead: {candidate: metrics}} for one year's evaluation."""
    out = {}
    for k in LEADS:
        per = {key(c): result["counts"][(k, key(c))] for c in CANDIDATES}
        stats = bootstrap(per, key(BASELINE), n_boot, seed + k)
        out[str(k)] = {"days": len(result["days"][k]), "candidates": {
            name: {**pooled(counts), **stats[name], "rain": rain_summary(result["rain"][(k, name)])}
            for name, counts in per.items()}}
    return out


def decide(primary: dict) -> dict:
    """The chosen configuration per lead (module doc): the best eligible candidate on agreement, else GFS raw."""
    baseline = key(BASELINE)
    decisions = {}
    for lead, entry in primary.items():
        base = entry["candidates"][baseline]
        eligible = []
        for name, m in entry["candidates"].items():
            if name == baseline or m["agreement"] is None:
                continue
            beats = m["delta_vs_baseline"] > m["delta_se"]
            keeps_recall = (m["warning_recall"] or 0.0) >= (base["warning_recall"] or 0.0)
            if beats and keeps_recall:
                eligible.append(name)
        if eligible:
            best = max(eligible, key=lambda n: (entry["candidates"][n]["agreement"], entry["candidates"][n]["watch_recall"] or 0.0,
                                                -(entry["candidates"][n]["rain"]["domain"]["mae_mm"] or 1e9)))
            m = entry["candidates"][best]
            reason = (f"agreement {m['agreement']:.4f} vs GFS {base['agreement']:.4f} (+{m['delta_vs_baseline']:.4f}, "
                      f"bootstrap SE {m['delta_se']:.4f}); Warning+ recall {m['warning_recall']:.3f} vs {base['warning_recall']:.3f}")
        else:
            best = baseline
            reason = "no candidate beats GFS by more than the bootstrap SE of the difference without lowering Warning+ recall"
        decisions[lead] = {"chosen": best, "eligible": eligible, "reason": reason}
    return decisions


def config_of(name: str) -> fc.Config:
    source, _, mapped = name.partition("+")
    return fc.Config(source, bool(mapped))


# ----------------------------------------------------------------------------------------------- the reports

def _f(value, digits=3) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def selection_markdown(payload: dict) -> list[str]:
    lines = ["# Forecast rain selection (spec section 12)", "",
             f"Cells: the seeded sample of the forecast-skill report ({payload['cells']} cells, seed {payload['seed']}); model "
             f"{payload['model']}. Both sides are published levels (point level, `uncertain_high` of the rules, rain cap); the "
             "observed-feature level of the target day is the reference. Bias-corrected (`+map`) curves: GFS fitted on "
             "June-September 2021-2023, ECMWF on 2023 only, so 2023 is in-sample for every `+map` candidate and for none of the raw "
             "ones; 2024 is held out for all. GEFS: " + payload["gefs"], ""]
    for year in (PRIMARY_YEAR, SECONDARY_YEAR):
        entry = payload["tables"][str(year)]
        label = "primary, held out" if year == PRIMARY_YEAR else "secondary; `+map` in-sample"
        lines += [f"## June-September {year} ({label})", ""]
        for lead, block in entry.items():
            lines += [f"### Lead D+{lead} ({block['days']} issue days)", "",
                      "| candidate | pairs | agreement (SE) | within one | Watch+ recall | Warning+ recall | Warning+ precision | "
                      "delta vs GFS (SE) | rain MAE domain (mm) | hit >=50 | FAR >=50 |", "|---|---|---|---|---|---|---|---|---|---|---|"]
            for name, m in block["candidates"].items():
                rain = m["rain"]["domain"]
                lines.append(f"| {name} | {m['pairs']} | {_f(m['agreement'], 4)} ({_f(m['agreement_se'], 4)}) | {_f(m['within_one'])} | "
                             f"{_f(m['watch_recall'])} | {_f(m['warning_recall'])} | {_f(m['warning_precision'])} | "
                             f"{_f(m['delta_vs_baseline'], 4)} ({_f(m['delta_se'], 4)}) | {_f(rain['mae_mm'], 2)} | "
                             f"{_f(rain['hit_rate_50'])} | {_f(rain['false_alarm_ratio_50'])} |")
            lines.append("")
    lines += ["Rain MAE is also the CRPS of a single-valued forecast; the member totals of the ensemble are not stored, so no "
              "ensemble CRPS is computed.", "", "## Decision (primary period, pre-declared rule)", "",
              "| lead | chosen | eligible | reason |", "|---|---|---|---|"]
    for lead, d in payload["decision"].items():
        lines.append(f"| D+{lead} | {d['chosen']} | {', '.join(d['eligible']) or 'none'} | {d['reason']} |")
    widening = payload["widening"]
    lines += ["", "## Widening factors of the chosen configuration (2024 issue days)", "",
              "| lead | chosen | informative cell-days | lo | hi | GFS raw lo | GFS raw hi |", "|---|---|---|---|---|---|---|"]
    for lead in ("1", "2", "3"):
        w, g = widening["chosen"]["leads"][lead], widening["gfs_raw_2024"]["leads"][lead]
        lines.append(f"| D+{lead} | {payload['decision'][lead]['chosen']} | {w['n']} | {_f(w['lo'])} | {_f(w['hi'])} | "
                     f"{_f(g['lo'])} | {_f(g['hi'])} |")
    return lines


def certainty_markdown(payload: dict) -> list[str]:
    lines = ["# Scenario certainty on 2024 (spec section 12, F1)", "",
             f"Configuration per lead: {payload['choice']}. Each forecast row is scored with no further rain (`dry`), with the forecast "
             "and with its heavy-rain bound (`wet`); `firm` = the three published levels agree. Reference: the published level from "
             "the observed features of the target day. Standard errors resample issue days.", "",
             "| lead | group | cells | share | forecast level = observed (SE) | within one | observed inside [min, max] |",
             "|---|---|---|---|---|---|---|"]
    for lead, block in payload["leads"].items():
        for group, m in block["groups"].items():
            lines.append(f"| D+{lead} | {group} | {m['n']} | {_f(m['share'])} | {_f(m['agreement'])} ({_f(m['agreement_se'])}) | "
                         f"{_f(m['within_one'])} | {_f(m['coverage'])} |")
    return lines


# ------------------------------------------------------------------------------------------------ the commands

def _progress(year: int, done: int, total: int) -> None:
    if done % 10 == 0 or done == total:
        print(f"[forecast_select] {year}: issue day {done}/{total}", flush=True)


def run_select(cfg: dict, maps_path: Path, reports_dir: Path, n_cells: int, seed: int, n_boot: int) -> int:
    setup = build_setup(cfg, maps_path, n_cells, seed)
    results = {year: evaluate_year(setup, year, _progress, rain_dir_of(cfg) / f"forecast_select_{year}.ckpt")
               for year in (PRIMARY_YEAR, SECONDARY_YEAR)}
    tables = {str(year): table_of(result, n_boot, seed) for year, result in results.items()}
    decision = decide(tables[str(PRIMARY_YEAR)])
    primary = results[PRIMARY_YEAR]
    widening = {"chosen": FS.widening_factors({k: primary["ratios"][(k, decision[str(k)]["chosen"])] for k in LEADS}),
                "gfs_raw_2024": FS.widening_factors({k: primary["ratios"][(k, key(BASELINE))] for k in LEADS})}
    selection_file = project_path(cfg["forecast_selection"])
    choice = fc.ForecastChoice({k: config_of(decision[str(k)]["chosen"]) for k in LEADS}, BASELINE,
                               str(maps_path.relative_to(PROJECT_ROOT).as_posix()) if maps_path.is_relative_to(PROJECT_ROOT)
                               else str(maps_path), f"reports/{SELECTION_STEM}.md")
    pooled_t = live_run.pooled_thresholds(setup.thresholds)
    payload = {"cells": int(len(setup.sample)), "seed": seed, "bootstrap": n_boot, "model": hm.display_path(
        hm.configured_model_dir(hm.hazard_config(project_path(cfg["model_config"])))),
        "thresholds": pooled_t.to_dict(), "fit_seasons": fm.FIT_SEASONS, "tables": tables, "decision": decision,
        "widening": widening, "gefs": ("not used: its archive carries APCP as 3- and 6-hour buckets without a running total, so an "
                                       "IMD day needs about 29 range requests per member (31 members), about 900 per issue day and "
                                       "about 66 GB for the two seasons, beyond the one-hour effort allowed; GFS and ECMWF remain."),
        "days": {str(year): result["days"] for year, result in results.items()}}
    old = project_path(cfg["forecast_widening"])
    old_payload = json.loads(old.read_text(encoding="utf-8")) if old.is_file() else {}
    gfs_leads = old_payload.get("fallback", {}).get("leads") or old_payload.get("leads")
    if gfs_leads and not old_payload.get("fallback"):
        shutil.copyfile(old, old.with_name(f"{old.stem}_gfs_2021_2024{old.suffix}"))
    dump_json(old, {**widening["chosen"], "fallback": {"leads": gfs_leads, "source": "gfs raw, June-September 2021-2024"},
                    "configuration": choice.to_dict(), "issue_days": "June-September 2024", "sample_cells": int(len(setup.sample)),
                    "seed": seed, "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "report": f"reports/{SELECTION_STEM}.md"})
    fc.save_choice(selection_file, choice, {"decision": decision})
    dump_json(reports_dir / f"{SELECTION_STEM}.json", payload)
    (reports_dir / f"{SELECTION_STEM}.md").write_text("\n".join(selection_markdown(payload)) + "\n", encoding="utf-8")
    per_day = {f"{y}_D{k}_{name}": counts for y, r in results.items() for (k, name), counts in r["counts"].items()}
    np.savez_compressed(rain_dir_of(cfg) / PER_DAY_FILE, **per_day)
    print(f"[forecast_select] wrote {selection_file}, {old} and {reports_dir / (SELECTION_STEM + '.md')}", flush=True)
    return 0


def rain_dir_of(cfg: dict) -> Path:
    return project_path(cfg["imerg"]["processed_dir"])


def run_scenarios(cfg: dict, maps_path: Path, reports_dir: Path, n_cells: int, seed: int, n_boot: int) -> int:
    setup = build_setup(cfg, maps_path, n_cells, seed)
    choice = fc.load_choice(project_path(cfg["forecast_selection"]))
    factors = live_run.load_widening(cfg, live_run.LiveDeps())[0]
    checkpoint = rain_dir_of(cfg) / "forecast_select_scenarios.ckpt"
    state = {"done": 0, "rows": {k: [] for k in LEADS}}      # rows: per issue day, certainty_counts
    if checkpoint.is_file():
        with checkpoint.open("rb") as handle:
            state = pickle.load(handle)
    rows = state["rows"]
    for i, day in enumerate(fm.season_days(PRIMARY_YEAR)):
        if i < state["done"]:
            continue
        products = fc.load_product_days(setup.rain_dir, day)
        for k in LEADS:
            field = fc.resolve_lead(products, choice, setup.maps, k)
            if field is None or field.fallback:
                continue
            observed = observed_side(setup, day, k)
            factor = factors[k] if factors else None
            scenes = fc.scenario_fields(field, factor[1] if factor else 1.0)
            levels = {name: forecast_side(setup, day, k, scenes[name]) for name in ("dry", "forecast", "wet")}
            scored = levels["forecast"][2] & observed[2]
            certainty, low, high = pr.scenario_certainty(levels["forecast"][1], levels["dry"][1], levels["wet"][1], scored)
            rows[k].append(certainty_counts(observed[1], levels["forecast"][1], certainty, low, high, scored))
        state["done"] = i + 1
        if state["done"] % CHECKPOINT_EVERY_DAYS == 0:
            _save_checkpoint(checkpoint, state)
        if (i + 1) % 10 == 0:
            print(f"[forecast_select] scenarios: issue day {i + 1}", flush=True)
    leads = {}
    rng = np.random.default_rng(seed)
    for k in LEADS:
        data = np.stack(rows[k]) if rows[k] else np.zeros((0, 3, 5), dtype=np.int64)
        leads[str(k)] = {"days": int(len(data)), "groups": certainty_groups(data, n_boot, rng)}
    payload = {"choice": ", ".join(f"D+{k}: {key(choice.leads[k])}" for k in LEADS), "cells": int(len(setup.sample)),
               "seed": seed, "leads": leads}
    dump_json(reports_dir / f"{CERTAINTY_STEM}.json", payload)
    (reports_dir / f"{CERTAINTY_STEM}.md").write_text("\n".join(certainty_markdown(payload)) + "\n", encoding="utf-8")
    print(f"[forecast_select] wrote {reports_dir / (CERTAINTY_STEM + '.md')}", flush=True)
    return 0


GROUPS = ("firm", "depends_on_forecast", "all")


def certainty_counts(obs_level, level, certainty, low, high, scored) -> np.ndarray:
    """(3 groups, 5) counts of one day: cells, forecast level = observed, within one, observed inside [min, max]."""
    obs, fc_level = np.asarray(obs_level)[scored], np.asarray(level)[scored]
    kind, lo, hi = np.asarray(certainty)[scored], np.asarray(low)[scored], np.asarray(high)[scored]
    out = np.zeros((len(GROUPS), 5), dtype=np.int64)
    for g, name in enumerate(GROUPS):
        pick = np.ones(obs.size, dtype=bool) if name == "all" else kind == name
        o, f = obs[pick], fc_level[pick]
        out[g] = (o.size, (o == f).sum(), (np.abs(o.astype(int) - f) <= 1).sum(), ((o >= lo[pick]) & (o <= hi[pick])).sum(),
                  pick.sum())
    return out


def certainty_groups(data: np.ndarray, n_boot: int, rng: np.random.Generator) -> dict:
    out = {}
    if not len(data):
        return out
    draws = rng.integers(0, len(data), size=(n_boot, len(data)))
    total_all = data[:, 2, 0].sum()
    for g, name in enumerate(GROUPS):
        n = data[:, g, 0].sum()
        boot = data[draws, g, 1].sum(axis=1) / np.maximum(data[draws, g, 0].sum(axis=1), 1)
        out[name] = {"n": int(n), "share": float(n / total_all) if total_all else None,
                     "agreement": float(data[:, g, 1].sum() / n) if n else None, "agreement_se": float(boot.std(ddof=1)),
                     "within_one": float(data[:, g, 2].sum() / n) if n else None,
                     "coverage": float(data[:, g, 3].sum() / n) if n else None}
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("select", "scenarios"))
    parser.add_argument("--config", type=Path, default=None, help="configs/live_run.yaml")
    parser.add_argument("--maps", type=Path, default=None, help=f"mapping file (default <imerg.processed_dir>/{fm.MAP_NAME})")
    parser.add_argument("--reports-dir", type=Path, default=PROJECT_ROOT / "reports")
    parser.add_argument("--cells", type=int, default=FS.DEFAULT_SAMPLE_CELLS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--bootstrap", type=int, default=DEFAULT_BOOTSTRAP)
    args = parser.parse_args(argv)
    cfg = live_run.load_run_config(args.config)
    maps_path = args.maps or rain_dir_of(cfg) / fm.MAP_NAME
    run = run_select if args.command == "select" else run_scenarios
    try:
        return run(cfg, maps_path, args.reports_dir, args.cells, args.seed, args.bootstrap)
    except (live_run.LiveRunError, OSError, ValueError) as exc:
        print(f"[forecast_select] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
