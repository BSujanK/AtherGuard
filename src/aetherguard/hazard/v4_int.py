"""The W3 rain-intensity challenger v4-int (docs/superpowers/specs/2026-11-06-aetherguard-w3-rain-intensity.md sections 2-3).

    python -m aetherguard.hazard.v4_int dev        # stage 1: CV of the v3-live refit (reference) and v4-int, pooled OOF FA@90
    python -m aetherguard.hazard.v4_int seasons    # v4-int scored on the 2018-2025 season panels (reads no outcome)
    python -m aetherguard.hazard.v4_int heldout    # stage 2: the single held-out look
    python -m aetherguard.hazard.v4_int report     # reports/phase7_rain_intensity.{md,json}

Configuration: configs/hazard_v4_int.yaml; the frozen v3-live configuration is its `base_config`, so v4-int is trained,
cross-validated and calibrated exactly as v3-live was and differs from it only by the six `iint` inputs, each constrained
non-decreasing. Models and results go to data/processed/hazard/v4_int; no frozen v3 artifact is written.

Stage 1 (development, year-blocked CV 2007-2017 with v3's folds and seeds): the pooled out-of-fold FA@90 is a false-alarm
share, so lower is better. The paired bootstrap gives the 95% interval of FA@90(v4_int) - FA@90(C0). "Includes or favours
v4-int" is read literally as that interval's LOWER bound being <= 0 (v4-int is not significantly worse). A failed stage 1 is
final: the held-out set is not read.

Stage 2 (held-out, once): the season panels of 2018-2025 are pooled as the W1 report assembles them (87 independent slides,
tolerant and cell-exact matching). The frozen season panels hold v3's scores only, so `seasons` scores v4-int on the same
cells and days with the training-style features plus the frozen iint season tables. v4-int then enters the comparison as
`match_burden` levels: in each season the cell-days are ranked by v4-int's own calibrated risk and cut to the Watch+ /
Warning+ / Emergency shares v3 realised in that season (the W1 benchmarks' rule), so v4-int is neither favoured nor
penalised by its thresholds. v3's levels are the frozen model's levels with the section 11 rules and the hysteresis; v4-int
ranks by risk alone, without those rules. v4-int is adopted only if its independent-slide detection at Warning+ and at
Emergency is at least v3's in all four comparisons (tolerant and cell-exact) and higher in at least one.

The look is taken once: `heldout` refuses to run when its result file in data/ or the committed report exists, and the result
is created exclusively. `report` refuses while stage 1 has passed and no look has been taken, so a report can never be what
blocks the look.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from ..config import PROJECT_ROOT, data_root, load_config_file
from ..features import imerg_intensity as ii
from ..live import backtest as bt
from ..live import hardening as H
from ..live import precision_study as ps
from ..live import run as live_run
from ..manifest import sha256_file
from ..verify import heldout as vh
from ..verify import operating_point as op
from ..verify import report as vr
from ..verify import seasons as vs
from ..verify.baselines import burden_matched_levels, realised_shares
from . import challengers as ch
from . import cv
from . import data as hd
from . import model as hm
from . import train as tr
from . import v31_challenger as vc
from .jsonio import dump_json, jsonable

DEFAULT_CONFIG = PROJECT_ROOT / "configs" / "hazard_v4_int.yaml"
DEV_RESULTS = "dev_results.json"
HELDOUT = "heldout.json"
OOF_SUBDIR = "oof"
SEASON_TAG = "v4_int"                # season_<year>_v4_int.npz, next to (never in) v3's heldout_seasons
MODEL_SUBDIR = "models"
HEADLINE = ch.HEADLINE
WARNING, EMERGENCY = 2, 3
DECIDING_LEVELS = {WARNING: "Warning+", EMERGENCY: "Emergency"}
NO_GAIN = "no comparison is higher"
NO_KEYS = pd.DataFrame({"cell_id": np.zeros(0, dtype=np.int64), "date": pd.to_datetime([])})   # v4-int drops no positives
STAGE_ONE_RULE = ("pooled OOF FA@90 is a false-alarm share (lower is better); passes when the paired bootstrap interval of "
                  "v4_int - C0 has lower bound <= 0, i.e. v4-int is not significantly worse")


class StageOneError(RuntimeError):
    """The step needs a stage 1 that has passed (or has been run)."""


class IintTableError(RuntimeError):
    """A frozen iint season table does not match its manifest or the panel it is joined to."""


# ---------------------------------------------------------------------------------------------- study

def load_study(path: Path | str | None = None) -> dict:
    """The study configuration with the frozen v3-live configuration under `base`."""
    study = load_config_file(Path(path or DEFAULT_CONFIG))
    study["base"] = hm.hazard_config(PROJECT_ROOT / study["base_config"])
    return study


def _plain_name(name: str, key: str) -> str:
    if Path(name).name != name or name in (".", ".."):
        raise ValueError(f"{key} must be a plain directory name, got {name!r}")
    return name


def output_dir(study: dict) -> Path:
    return data_root() / "processed" / "hazard" / _plain_name(study["output_dir"], "output_dir")


def seasons_dir(study: dict) -> Path:
    return data_root() / "processed" / "alerts" / _plain_name(study["seasons_dir"], "seasons_dir")


def report_path(study: dict) -> Path:
    return PROJECT_ROOT / "reports" / f"{study['report_stem']}.json"


def extra_groups(study: dict) -> dict:
    """The feature groups the base configuration knows plus the `iint` group of this study."""
    return {**study["base"]["extra_groups"], **study["extra_groups"]}


def groups_used(study: dict) -> list[str]:
    """The extra groups to join onto the development rows: those v3-live uses, then the groups the candidates add."""
    added = [g for spec in study["candidates"].values() for g in spec.get("add_groups", [])]
    return list(dict.fromkeys([*tr.extra_groups_used(study["base"]), *added]))


def iint_dir(study: dict, features_dir: Path) -> Path:
    return Path(features_dir) / study["extra_groups"][ii.GROUP]["subdir"]


def frozen_selection(study: dict) -> dict:
    return vc.frozen_selection(study)


def published_v3_numbers() -> dict:
    """v3's POOLED numbers of the committed W1 report, which the pool assembled here must reproduce."""
    return op.published_v3(op.REPORTS / f"{vh.REPORT_STEM}.json")


# ------------------------------------------------------------------------------------------- candidates

def make_candidates(study: dict, base_columns, column_map: dict[str, str] | None = None) -> dict[str, vc.Candidate]:
    """C0 (the frozen inputs and v3 constraints) and v4_int (C0 plus `add_increasing`, each constrained non-decreasing).
    With `column_map` the added inputs must be columns of the candidate's `add_groups`."""
    out = {}
    for name, spec in study["candidates"].items():
        added = list(spec.get("add_increasing", []))
        if len(set(added)) != len(added):
            raise ValueError(f"candidate {name}: add_increasing names an input more than once")
        clash = [c for c in added if c in base_columns]
        if clash:
            raise ValueError(f"candidate {name}: add_increasing names {clash}, already an input of the frozen model")
        if column_map is not None:
            groups = spec.get("add_groups", [])
            stray = [c for c in added if column_map.get(c) not in groups]
            if stray:
                raise ValueError(f"candidate {name}: {stray} are not columns of the groups {groups}")
        columns = [*base_columns, *added]
        out[name] = vc.Candidate(name, spec["description"], columns,
                                 vc.candidate_constraints(columns, {"increasing_extra": added}, study["base"]), False)
    for key in ("reference", "challenger"):
        if study[key] not in out:
            raise ValueError(f"the {key} candidate {study[key]!r} is not defined")
    return out


# ------------------------------------------------------------------------------------ stage 1 (development)

def compare(frames: dict[str, pd.DataFrame], study: dict) -> dict:
    """The paired bootstrap of FA@90(challenger) - FA@90(reference) on identical OOF rows, with every point metric of both."""
    base = study["base"]
    boot, ops = base["bootstrap"], base["operating_points"]
    reference, challenger = study["reference"], study["challenger"]
    paired = ch.paired_fa_differences(frames, [(challenger, reference)], boot["n"], boot["seed"], boot["level"],
                                      recalls=ops["recalls"], fa_shares=ops["fa_shares"])
    return {"difference": paired["differences"][f"{challenger}-{reference}"], "metrics": paired["metrics"]}


def stage_one(difference: dict) -> dict:
    """Spec section 3, development: passes when the interval of v4_int - C0 has a lower bound <= 0 (it includes 0 or lies
    below it). FA@90 is a false-alarm share, so a negative difference favours v4-int; only an interval wholly above 0 fails."""
    lo, hi = float(difference["ci_lo"]), float(difference["ci_hi"])
    return {"rule": STAGE_ONE_RULE, "difference": float(difference["point_difference"]), "ci": [lo, hi],
            "level": difference.get("level"), "passed": bool(lo <= 0),
            "verdict": "favours v4-int" if hi < 0 else "includes zero" if lo <= 0 else "significantly worse than v3"}


def fit_model(candidate: vc.Candidate, dev: hd.Development, layout: cv.Layout, result: cv.CVResult, base: dict,
              directory: Path) -> hm.HazardModel:
    """Refit v4-int on all development rows exactly as v3-live was (`v31_challenger.fit_final`) and mark its card."""
    model = vc.fit_final(candidate, dev, layout, result, base, NO_KEYS, directory)
    model.card.update(protocol="v2 (year-blocked CV over 2007-2017); W3 rain-intensity challenger, spec 2026-11-06",
                      description=f"W3 challenger {candidate.name}: {candidate.description}")
    model.save(directory)
    return model


def run_dev(study: dict, features_dir: Path | None = None, say=print) -> dict:
    """Stage 1: cross-validate the reference (it must reproduce the frozen v3-live FA@90) and v4-int, compare them by the
    paired bootstrap, apply the pre-declared rule and refit v4-int when it passes. test_2018 is not read."""
    started = time.perf_counter()
    base, out = study["base"], output_dir(study)
    selected = frozen_selection(study)
    dev = hd.load_development(features_dir, extra_groups(study), groups_used(study), base["meta_columns"])
    layout = cv.make_layout(dev, base["cv"]["folds"])
    say(f"development rows: {len(layout.positives)} positives, {len(layout.negatives):,} universe negatives, "
        f"{len(layout.matched)} matched negatives")
    candidates = make_candidates(study, selected["columns"], dev.column_map)
    reference = study["reference"]
    results, frames, reproduction = {}, {}, None
    for name in [reference, *[n for n in candidates if n != reference]]:
        candidate = candidates[name]
        result = cv.run_cv(dev, layout, candidate.columns, candidate.constraints, selected["hp"], selected["neg_mix"], base, name)
        say(f"{name}: FA@90 {result.pooled[HEADLINE]:.4f}, {result.n_trees} trees, {len(candidate.columns)} inputs, "
            f"{result.seconds:.0f}s")
        if name == reference:
            reproduction = vc.check_reproduction(result, selected)
            say(f"  reproduces frozen v3-live: |difference| {reproduction['abs_difference']:.2e}")
        results[name], frames[name] = result, ch.oof_frame(layout, result.oof)
        vc.save_oof(out / OOF_SUBDIR, frames[name], result)
    comparison = compare(frames, study)
    stage = stage_one(comparison["difference"])
    say(f"stage 1: v4_int - C0 FA@90 {stage['difference']:+.4f} [{stage['ci'][0]:+.4f}, {stage['ci'][1]:+.4f}] "
        f"-> {'passed' if stage['passed'] else 'FAILED'} ({stage['verdict']})")
    model_dir = None
    if stage["passed"]:
        model_dir = out / MODEL_SUBDIR / study["challenger"]
        fit_model(candidates[study["challenger"]], dev, layout, results[study["challenger"]], base, model_dir)
        say(f"refitted {study['challenger']} -> {hm.display_path(model_dir)}")
    payload = {
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "development": {"positives": len(layout.positives), "universe_rows": len(layout.negatives),
                        "matched_rows": len(layout.matched), "folds": layout.folds},
        "frozen_reference": hm.display_path(hm.configured_model_dir(base)), "reproduction": reproduction,
        "candidates": {n: {"description": c.description, "n_inputs": len(c.columns), "columns": c.columns,
                           "constraints": dict(zip(c.columns, c.constraints)), "n_trees": results[n].n_trees,
                           "fold_best_iterations": results[n].fold_best_iterations, "seconds": results[n].seconds}
                       for n, c in candidates.items()},
        "comparison": comparison, "stage_one": stage, "decision": None if stage["passed"] else decide(stage),
        "model_dir": None if model_dir is None else hm.display_path(model_dir),
        "seconds": time.perf_counter() - started}
    dump_json(out / DEV_RESULTS, payload)
    say(f"wrote {hm.display_path(out / DEV_RESULTS)} in {payload['seconds']:.0f}s")
    return payload


def load_dev_results(study: dict) -> dict:
    path = output_dir(study) / DEV_RESULTS
    if not path.is_file():
        raise FileNotFoundError(f"{path} not found; run the `dev` stage first")
    return json.loads(path.read_text(encoding="utf-8"))


# ------------------------------------------------------------------------------------------ the decision

def decide(stage: dict, scores: dict | None = None) -> dict:
    """The pre-declared adoption criterion of spec section 3, literally.

    Stage 1 failed: not adopted, the held-out set is not evaluated. Otherwise `scores` (`operating_point.score_heldout`)
    must hold, in both tolerances and at Warning+ and Emergency, the independent-slide detection (`group_hits`) of v3 and of
    the candidate: adopted when the candidate's is >= v3's in all four comparisons and > in at least one. Watch+ is reported
    in the scores but does not decide.
    """
    if not stage["passed"]:
        return {"adopt": False, "stage": 1, "conditions": [], "failed": ["stage 1"],
                "reason": "the paired FA@90 interval of v4_int - C0 lies wholly above 0: v4-int is not evaluated on the "
                          "held-out set and is not adopted"}
    if scores is None:
        raise ValueError("stage 1 passed: the held-out scores are required to decide")
    conditions, failed = [], []
    for tolerance in op.TOLERANCES:
        for level, label in DECIDING_LEVELS.items():
            v3 = int(scores[tolerance]["v3"][level]["group_hits"])
            candidate = int(scores[tolerance]["candidate"][level]["group_hits"])
            conditions.append({"tolerance": tolerance, "level": label, "v3": v3, "candidate": candidate,
                               "difference": candidate - v3, "not_lower": candidate >= v3, "higher": candidate > v3})
            if candidate < v3:
                failed.append(f"{tolerance}: {label} detection lower ({candidate} against {v3})")
    if not any(c["higher"] for c in conditions):
        failed.append(NO_GAIN)
    return {"adopt": not failed, "stage": 2, "conditions": conditions, "failed": failed,
            "reason": "adopted: no independent-slide detection is lower than v3's and one is higher" if not failed
            else "not adopted: " + "; ".join(failed)}


# ------------------------------------------------------------------------------- season panels with iint

def season_iint(study: dict, directory: Path, year: int, cell_ids, days: list[date]) -> np.ndarray:
    """The six iint features (float32, cells x days x 6) of a held-out season from its frozen table, verified against the
    manifest, the panel's cells (and their order) and its days."""
    directory = Path(directory)
    path = directory / ii.season_name(year)
    manifest = directory / study["extra_groups"][ii.GROUP]["manifest_file"]
    if not path.is_file() or not manifest.is_file():
        raise FileNotFoundError(f"{path} or {manifest} not found; build the iint tables first "
                                "(python -m aetherguard.features.imerg_intensity tables)")
    entry = json.loads(manifest.read_text(encoding="utf-8"))["files"].get(path.name)
    if entry is None:
        raise IintTableError(f"{path.name} is not listed in {manifest.name}")
    if sha256_file(path) != entry["sha256"]:
        raise IintTableError(f"{path.name} does not match the checksum in {manifest.name}")
    table = pd.read_parquet(path)
    cell_ids = np.asarray(cell_ids, dtype=np.int64)
    if len(table) != len(cell_ids) * len(days):
        raise IintTableError(f"{path.name} has {len(table)} rows; {len(cell_ids)} cells x {len(days)} days need "
                             f"{len(cell_ids) * len(days)}")
    if not np.array_equal(table["cell_id"].to_numpy(dtype=np.int64), np.repeat(cell_ids, len(days))):
        raise IintTableError(f"{path.name}: its cells differ from the panel's cells or their order")
    if not np.array_equal(table["date"].to_numpy(dtype="datetime64[ns]"), np.tile(np.array(days, dtype="datetime64[ns]"), len(cell_ids))):
        raise IintTableError(f"{path.name}: its days differ from the panel's days")
    return table[ii.feature_names()].to_numpy(dtype=np.float32).reshape(len(cell_ids), len(days), -1)


def season_path(directory: Path, year: int) -> Path:
    return Path(directory) / f"season_{year}_{SEASON_TAG}.npz"


def score_season(model, card_sha: str, study: dict, year: int, features_dir: Path, out_dir: Path, say=print,
                 force: bool = False) -> Path:
    """Score June-December `year` (plus the backtest warm-up days) of the 2018 set's cells with v4-int and the training-style
    features joined to the frozen iint season table, as `verify.seasons.score_season` scores v3; returns the panel's path.
    An existing panel is kept unless `force`."""
    path = season_path(out_dir, year)
    if path.is_file() and not force:
        say(f"season {year}: {path} exists, skipped")
        return path
    started = time.perf_counter()
    cfg = live_run.load_run_config()
    spec = bt.load_set(f"season_{year}", date(year, *vs.SEASON_START), date(year, *vs.SEASON_END), cfg)
    days = bt.set_days(spec)
    intensity = season_iint(study, iint_dir(study, features_dir), year, spec.cells["cell_id"].to_numpy(), days)
    column = {day: j for j, day in enumerate(days)}
    stores = bt.build_stores(spec.cells, cfg)
    say(f"season {year}: {len(spec.cells)} cells, {spec.start} to {spec.end}")

    def features(day: date) -> pd.DataFrame:
        base = bt.training_style_features(day, spec.cells, stores).reset_index(drop=True)
        return pd.concat([base, pd.DataFrame(intensity[:, column[day], :], columns=ii.feature_names())], axis=1)

    panel = H.score_panel(days, spec.cells.assign(in_universe=True), lambda day: model, features, say)
    seconds = time.perf_counter() - started
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    dump_json(path.with_suffix(".json"), {
        "year": year, "features": "training_style+iint", "n_days": len(panel.days), "n_cells": int(len(panel.cells)),
        "first_day": panel.days[0].isoformat(), "last_day": panel.days[-1].isoformat(), "warmup_days": bt.WARMUP_DAYS,
        "n_members": panel.n_members, "scored_share_per_day": vs.scored_share_summary(panel),
        "model_card_sha256": card_sha, "seconds": seconds})
    H.save_panel(path, panel)
    say(f"season {year}: written {path} in {seconds:.0f}s")
    return path


def load_model(study: dict) -> tuple[hm.HazardModel, str]:
    directory = output_dir(study) / MODEL_SUBDIR / study["challenger"]
    if not (directory / hm.CARD_FILE).is_file():
        raise StageOneError(f"no {study['challenger']} model under {directory}: stage 1 has not passed (run `dev`)")
    return hm.HazardModel.load(directory), sha256_file(directory / hm.CARD_FILE)


def run_seasons(study: dict, features_dir: Path | None = None, years=bt.SEASON_YEARS, say=print, force: bool = False) -> list[Path]:
    """Score the held-out seasons with v4-int (no outcome is read; this is not the look)."""
    model, card_sha = load_model(study)
    features_dir = Path(features_dir or hd.features_dir())
    return [score_season(model, card_sha, study, year, features_dir, seasons_dir(study), say, force) for year in years]


# ---------------------------------------------------------------------------------------- burden matching

def match_burden(risk: np.ndarray, scored: np.ndarray, v3_levels: np.ndarray) -> tuple[np.ndarray, dict]:
    """v4-int's levels (cells x days) for one season: the scored cell-days ranked by `risk` and cut to the Watch+ / Warning+ /
    Emergency shares that `v3_levels` realised on them (`baselines.burden_matched_levels`, the W1 rule). Also the target and
    the realised shares."""
    target = realised_shares(v3_levels, scored)
    levels = burden_matched_levels(risk, scored, target)
    return levels, {"target": list(target), "realised": list(realised_shares(levels, scored))}


def season_levels(part: vr.Part, panel: H.Panel, first: int, year: int) -> tuple[np.ndarray, dict]:
    """v4-int's burden-matched levels over the days of `part` (a v3 season from 1 June) from its panel. The panel must be of
    the same cells, days and scored cell-days, or the levels would not be compared like for like."""
    if not np.array_equal(panel.cells["cell_id"].to_numpy(dtype=np.int64), part.cell_ids):
        raise ValueError(f"season {year}: the v4-int panel's cells or their order differ from the v3 season's")
    if list(panel.days[first:]) != list(part.days):
        raise ValueError(f"season {year}: the v4-int panel's days differ from the v3 season's")
    if not np.array_equal(panel.scored[:, first:], part.scored):
        raise ValueError(f"season {year}: the v4-int panel's scored cell-days differ from the v3 season's")
    return match_burden(np.asarray(panel["risk"], dtype=np.float64)[:, first:], part.scored, part.v3)


def build_heldout(study: dict, say=print) -> tuple[op.HeldOut, dict]:
    """The POOLED 2018-2025 held-out set as `verify.operating_point.build_heldout` assembles it, with v3's levels and v4-int's
    burden-matched ones; also the per-season shares."""
    cfg = live_run.load_run_config()
    v3_model, config, base_rules = ps.load_inputs(cfg)
    reference = H.load_panel(H.alerts_dir(H.HELDOUT_DIR) / H.HELDOUT_FILE).cells["cell_id"].to_numpy()
    events = vh.load_event_table(cfg)
    events = events[pd.to_datetime(events["date"]).dt.year.isin(bt.SEASON_YEARS)]
    v3, candidate, scored, days, shares = [], [], [], [], {}
    for year in bt.SEASON_YEARS:
        say(f"held-out season {year}: v3 and v4-int")
        path = season_path(seasons_dir(study), year)
        if not path.is_file():
            raise FileNotFoundError(f"{path} not found; score the seasons first (python -m aetherguard.hazard.v4_int seasons)")
        season = vh.load_panel_season(year, reference, v3_model)
        part = vr.extract(season, config, base_rules)
        levels, shares[str(year)] = season_levels(part, H.load_panel(path), season.first, year)
        v3.append(part.v3)
        candidate.append(levels)
        scored.append(part.scored)
        days += part.days
        del season, part
    kept, outside = vh.events_on_days(events, days)
    return (op.HeldOut(reference, days, np.concatenate(scored, axis=1), np.concatenate(v3, axis=1),
                       np.concatenate(candidate, axis=1), kept, outside), {"seasons": shares})


# ---------------------------------------------------------------------------------------- the held-out look

def refuse_second_look(*paths: Path) -> None:
    for path in paths:
        if Path(path).exists():
            raise FileExistsError(f"{Path(path).name} exists: the held-out look has been taken and is not repeated ({path})")


def evaluate_once(path: Path, committed: Path, build: Callable[[], tuple[op.HeldOut, dict]], boot: dict = bt.BOOTSTRAP,
                  published: dict | None = None, context: dict | None = None) -> dict:
    """The single held-out look: score `build()` (the pool and what to record with it), decide, and store the result at `path`.

    Raises FileExistsError, before `build` loads anything, when `path` (the result in data/) or `committed` (the committed
    report, which guards a fresh clone without data/) exists. A failure before the result is stored (a pool that does not
    reproduce v3's published numbers) leaves nothing behind and may be rerun; the file is created exclusively, so two runs
    cannot both store a result.
    """
    path = Path(path)
    refuse_second_look(path, committed)
    pool, info = build()
    scores = op.score_heldout(pool, boot, published)
    context = context or {}
    result = {**context, **info, "scores": scores, "decision": decide(context["stage_one"], scores)}
    text = json.dumps(jsonable(result), indent=2, allow_nan=False)
    with open(path, "x", encoding="utf-8") as handle:
        handle.write(text + "\n")
    return result


def run_heldout(study: dict, say=print, build: Callable[[dict, Callable], tuple[op.HeldOut, dict]] = build_heldout) -> dict:
    """Stage 2: refuses a second look, and any look at all while stage 1 has not passed; otherwise the one look."""
    out = output_dir(study)
    refuse_second_look(out / HELDOUT, report_path(study))
    dev = load_dev_results(study)
    if not dev["stage_one"]["passed"]:
        raise StageOneError("stage 1 has not passed: v4-int is not evaluated on the held-out set (spec section 3)")
    say("held-out look (once)")
    result = evaluate_once(out / HELDOUT, report_path(study), lambda: build(study, say), bt.BOOTSTRAP, published_v3_numbers(),
                           {"created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                            "stage_one": dev["stage_one"], "model_dir": dev["model_dir"]})
    decision = result["decision"]
    say(f"decision: {decision['reason']}")
    say(f"wrote {hm.display_path(out / HELDOUT)}")
    return result


# ----------------------------------------------------------------------------------------------- report

def _fa(entry: dict) -> str:
    return f"{entry['value']:.4f} [{entry['lo']:.4f}, {entry['hi']:.4f}]"


def _pct(values) -> str:
    return " / ".join(f"{100 * v:.2f}%" for v in values)


def markdown(result: dict) -> str:
    dev, stage, decision, heldout = result["dev"], result["stage_one"], result["decision"], result["heldout"]
    metrics = result["comparison"]["metrics"]
    verdict = "adopted" if decision["adopt"] else "not adopted"
    lines = [
        "# Rain-intensity inputs: challenger v4-int (phase 7, W3)", "",
        f"**v4-int is {verdict}.** {decision['reason']}.", "",
        "v4-int is the frozen v3-live configuration (same folds, seeds, hyper-parameters, 20-member ensemble, per-region "
        "isotonic calibration and monotone constraints) plus six rain-intensity inputs from the half-hourly IMERG Late run, "
        "each constrained non-decreasing: " + ", ".join(f"`{c}`" for c in dev["added_inputs"]) + ". Nothing else differs. "
        "The criterion was fixed before any result (`docs/superpowers/specs/2026-11-06-aetherguard-w3-rain-intensity.md` "
        "section 3).", "",
        "## Stage 1: development (year-blocked CV 2007-2017)", "",
        f"The reference `C0` is the v3-live refit; it reproduces the frozen pooled OOF FA@90 to "
        f"{dev['reproduction']['abs_difference']:.1e}.", "",
        "| model | inputs | trees | pooled OOF FA@90 (95% CI) |", "|---|---|---|---|",
        *[f"| {name} | {c['n_inputs']} | {c['n_trees']} | {_fa(metrics[name][ch.HEADLINE])} |"
          for name, c in dev["candidates"].items()], "",
        f"FA@90 is a false-alarm share, so lower is better. v4_int - C0 = {stage['difference']:+.4f}, 95% paired-bootstrap "
        f"interval [{stage['ci'][0]:+.4f}, {stage['ci'][1]:+.4f}]. Rule: {stage['rule']}. Stage 1 "
        f"**{'passed' if stage['passed'] else 'failed'}** ({stage['verdict']}).", ""]
    if heldout is None:
        lines += ["## Stage 2: held-out", "",
                  "v4-int is not evaluated on the held-out set: stage 1 failed, so the held-out seasons were not scored "
                  "with v4-int and no look was taken.", ""]
        return "\n".join(lines)
    scores = heldout["scores"]
    lines += [
        "## Stage 2: held-out (pooled 2018-2025, the W1 assembly)", "",
        f"{scores['events']} events in {scores['slides']} independent slides (records within 10 km and a day are one slide). "
        "v4-int's levels are burden-matched to the shares v3 realised in each season: the scored cell-days are ranked by "
        "v4-int's own calibrated risk and cut to v3's Watch+ / Warning+ / Emergency shares, so the comparison is at equal "
        "burden. v3's levels carry the section 11 rules and the hysteresis; v4-int's do not. Detection is the number of "
        "independent slides with an alert at the level within tolerance (`tolerant`: 10 km, 1 day; `cell_exact`: the same "
        "cell and day).", "",
        "| tolerance | level | v3 slides detected | v4-int slides detected | difference | not lower | higher |",
        "|---|---|---|---|---|---|---|",
        *[f"| {c['tolerance']} | {c['level']} | {c['v3']} | {c['candidate']} | {c['difference']:+d} | "
          f"{'yes' if c['not_lower'] else 'NO'} | {'yes' if c['higher'] else 'no'} |" for c in decision["conditions"]], "",
        "Adoption needs every row \"not lower\" and at least one \"higher\".", "",
        "Alert cell-days at the matched burden (v3 / v4-int):", "",
        "| tolerance | Watch+ | Warning+ | Emergency |", "|---|---|---|---|",
        *[f"| {t} | " + " | ".join(f"{scores[t]['v3'][k]['alert_cell_days']} / {scores[t]['candidate'][k]['alert_cell_days']}"
                                   for k in ("1", "2", "3")) + " |" for t in op.TOLERANCES], "",
        "Burden matching per season, target (v3 realised) against v4-int realised, Watch+ / Warning+ / Emergency:", "",
        "| season | target | v4-int realised |", "|---|---|---|",
        *[f"| {year} | {_pct(s['target'])} | {_pct(s['realised'])} |" for year, s in heldout["seasons"].items()], "",
        "Ground truth after 2018 is very incomplete, so detection counts are relative (between models at equal burden), not "
        "absolute.", ""]
    return "\n".join(lines)


def write_report(study: dict, out_dir: Path | None = None, say=print) -> dict:
    """reports/phase7_rain_intensity.{md,json} from the stored stage results. Refuses while stage 1 has passed and the look has
    not been taken: a committed report blocks the look."""
    dev = load_dev_results(study)
    held_path = output_dir(study) / HELDOUT
    if dev["stage_one"]["passed"] and not held_path.is_file():
        raise StageOneError("stage 1 passed: take the held-out look first (`heldout`); a report written before it would block it")
    heldout = json.loads(held_path.read_text(encoding="utf-8")) if held_path.is_file() else None
    decision = dev["decision"] if heldout is None else heldout["decision"]
    result = {"created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "spec": "docs/superpowers/specs/2026-11-06-aetherguard-w3-rain-intensity.md",
              "dev": {"reproduction": dev["reproduction"], "candidates": dev["candidates"],
                      "added_inputs": study["candidates"][study["challenger"]]["add_increasing"],
                      "development": dev["development"], "seconds": dev["seconds"]},
              "comparison": dev["comparison"], "stage_one": dev["stage_one"], "heldout": heldout, "decision": decision}
    out_dir = Path(out_dir or report_path(study).parent)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = study["report_stem"]
    dump_json(out_dir / f"{stem}.json", result)
    (out_dir / f"{stem}.md").write_text(markdown(result), encoding="utf-8")
    say(f"wrote {hm.display_path(out_dir / stem)}.{{json,md}}")
    return result


# ------------------------------------------------------------------------------------------------- main

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("stage", choices=["dev", "seasons", "heldout", "report"])
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--features", type=Path, default=None, help="feature store directory")
    parser.add_argument("--force", action="store_true", help="seasons: rescore panels that exist")
    args = parser.parse_args(argv)
    study = load_study(args.config)

    def say(message: str) -> None:
        print(message, flush=True)
    if args.stage == "dev":
        run_dev(study, args.features, say)
    elif args.stage == "seasons":
        run_seasons(study, args.features, say=say, force=args.force)
    elif args.stage == "heldout":
        run_heldout(study, say)
    else:
        write_report(study, say=say)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
