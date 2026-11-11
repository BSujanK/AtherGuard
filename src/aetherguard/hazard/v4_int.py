"""The W3 rain-intensity challenger v4-int (docs/superpowers/specs/2026-11-06-aetherguard-w3-rain-intensity.md sections 2-3,
with the amendment of 2026-11-06).

    python -m aetherguard.hazard.v4_int dev [--force]  # stage 1: CV of the v3-live refit (reference) and v4-int, pooled OOF FA@90
    python -m aetherguard.hazard.v4_int seasons    # v4-int scored on the 2018-2025 season panels (reads no outcome)
    python -m aetherguard.hazard.v4_int preflight  # the held-out assembly and every check of it, computing no outcome
    python -m aetherguard.hazard.v4_int heldout    # stage 2: the single held-out look
    python -m aetherguard.hazard.v4_int report     # reports/phase7_rain_intensity.{md,json}

Configuration: configs/hazard_v4_int.yaml; the frozen v3-live configuration is its `base_config`, so v4-int is trained,
cross-validated and calibrated exactly as v3-live was and differs from it only by the six `iint` inputs, each constrained
non-decreasing. Models and results go to data/processed/hazard/v4_int; no frozen v3 artifact is written.

Lag. The train-serve gap study (`reports/phase7_rain_intensity_gap.json`, `declared_lag_days`) decides whether the live run
reads the intensity of the same IMD day (lag 0) or of the previous complete one (lag 1). `dev`, `seasons`, `preflight` and
`heldout` read it (and refuse without that report), use the matching feature tables (`iint` or `iint_lag1`) for the
development samples and the season panels alike, and record the lag in their results.

Stage 1 (development, year-blocked CV 2007-2017 with v3's folds and seeds): the pooled out-of-fold FA@90 is a false-alarm
share, so lower is better. The paired bootstrap gives the 95% interval of FA@90(v4_int) - FA@90(C0). "Includes or favours
v4-int" is read literally as that interval's LOWER bound being <= 0 (v4-int is not significantly worse). A failed stage 1 is
final: the held-out set is not read.

Stage 2 (held-out, once): the season panels of 2018-2025 are pooled as the W1 report assembles them (87 independent slides,
tolerant and cell-exact matching). The frozen season panels hold v3's scores only, so `seasons` scores v4-int on the same
cells and days with the training-style features plus the frozen iint season tables. The deciding comparison is v4-int
against `v3_ranked`: in each season both rank the scored cell-days by their own calibrated risk (ties by the panel's raw
score) and are cut to the Watch+ / Warning+ / Emergency shares v3 realised in that season with the section 11 rules, so the
comparison isolates the six features. v3 with the rules and the hysteresis is reported beside it and does not decide. v4-int
is adopted only if its independent-slide detection at Warning+ and at Emergency is at least v3_ranked's in all four
comparisons (tolerant and cell-exact) and higher in at least one.

`preflight` runs the same assembly as `heldout` up to, and not including, anything that joins events with levels, and
writes preflight.json (`outcome_computed` false); `heldout` refuses unless it exists, passed, and its card and panel
checksums are the current ones. The look is taken once: `heldout` refuses to run when its result file in data/ or the
committed report exists, and the result is created exclusively. `report` refuses while stage 1 has passed and no look has been
taken, so a report can never be what blocks the look.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

import numpy as np
import pandas as pd

from ..config import PROJECT_ROOT, data_root, load_config_file
from ..features import imerg_build as B
from ..features import imerg_intensity as ii
from ..features import static_w5 as sw
from ..live import backtest as bt
from ..live import hardening as H
from ..live import precision_study as ps
from ..live import run as live_run
from ..manifest import sha256_file
from ..verify import heldout as vh
from ..verify import operating_point as op
from ..verify import report as vr
from ..verify import seasons as vs
from ..verify.baselines import realised_shares
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
STARTED = "heldout.started"         # written, exclusively, once v3 has reproduced the W1 numbers and before any candidate outcome
TIE_SEED = 20261106                 # seed of the final tie-break key of the ranking (configs/hazard_v4_int.yaml `tie_seed`)
PREFLIGHT = "preflight.json"
OOF_SUBDIR = "oof"
MODEL_SUBDIR = "models"
SEASON_TAG = "v4_int"                # season_<year>_v4_int.npz, next to (never in) v3's heldout_seasons
HEADLINE = ch.HEADLINE
LEVELS = (1, 2, 3)
WARNING, EMERGENCY = 2, 3
DECIDING_LEVELS = {WARNING: "Warning+", EMERGENCY: "Emergency"}
NO_GAIN = "no comparison is higher"
NO_KEYS = pd.DataFrame({"cell_id": np.zeros(0, dtype=np.int64), "date": pd.to_datetime([])})   # v4-int drops no positives
FEATURES_TAG = "training_style+iint"
STAGE_ONE_RULE = ("pooled OOF FA@90 is a false-alarm share (lower is better); passes when the paired bootstrap interval of "
                  "v4_int - C0 has lower bound <= 0, i.e. v4-int is not significantly worse")


class StageOneError(RuntimeError):
    """The step needs a stage 1 that has passed (or has been run)."""


class IintTableError(RuntimeError):
    """A frozen iint season table does not match its manifest or the panel it is joined to."""


class BurdenMatchError(RuntimeError):
    """A ranked level set does not realise the target shares of its season."""


class LookStartedError(RuntimeError):
    """A look was started and not completed: only a human decides what happens next."""


class PreflightError(RuntimeError):
    """The held-out look is not allowed: there is no passed, current preflight."""


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


def gap_report_path() -> Path:
    return ii.GAP_REPORT


def declared_lag() -> int:
    """The lag in IMD days the train-serve gap report declares; refuses (FileNotFoundError) without that report."""
    return ii.read_declared_lag(gap_report_path())


def iint_spec(study: dict, lag_days: int) -> dict:
    """The extra-group spec of the iint tables built with `lag_days`: the configured one for lag 0, else the `iint_lag<n>`
    files of the same directory."""
    spec = dict(study["extra_groups"][ii.GROUP])
    if lag_days:
        group = ii.group_name(lag_days)
        spec.update(suffix=group, columns_file=B.columns_name(group), manifest_file=B.manifest_name(group))
    return spec


def extra_groups(study: dict, lag_days: int = 0) -> dict:
    """The feature groups the base configuration knows plus the `iint` group of this study at `lag_days`."""
    return {**study["base"]["extra_groups"], ii.GROUP: iint_spec(study, lag_days)}


def groups_used(study: dict) -> list[str]:
    """The extra groups to join onto the development rows: those v3-live uses, then the groups the candidates add."""
    added = [g for spec in study["candidates"].values() for g in spec.get("add_groups", [])]
    return list(dict.fromkeys([*tr.extra_groups_used(study["base"]), *added]))


def iint_dir(study: dict, features_dir: Path) -> Path:
    return Path(features_dir) / study["extra_groups"][ii.GROUP]["subdir"]


def frozen_selection(study: dict) -> dict:
    return vc.frozen_selection(study)


def pool_names(study: dict) -> tuple[str, str]:
    """(the ranked incumbent, the candidate) as the results name them: v3_ranked and v4_int unless the study says otherwise."""
    return tuple(study.get("pool_names", ("v3_ranked", "v4_int")))


def static_inputs(study: dict) -> list[str]:
    """The per-cell W5 static inputs the challenger adds, unconstrained (none for v4-int)."""
    return list(study["candidates"][study["challenger"]].get("add_static", []))


def season_file(study: dict, year: int) -> Path:
    return season_path(seasons_dir(study), year, study.get("season_tag", SEASON_TAG))


def check_requires(study: dict) -> list[dict]:
    """What a combined study stands on (`requires`): an incumbent adopted on its own look, and groups whose own development
    stage passed with the static inputs this study adds. Empty for a study that requires nothing."""
    requires, root, checks = study.get("requires", {}), data_root() / "processed" / "hazard", []
    if "adopted" in requires:
        path = root / _plain_name(requires["adopted"], "requires.adopted") / HELDOUT
        adopted = path.is_file() and json.loads(path.read_text(encoding="utf-8"))["decision"]["adopt"] is True
        checks.append(_check(f"incumbent {requires['adopted']} was adopted on its own look", adopted, str(path)))
    for name in requires.get("stage_one", []):
        path = root / _plain_name(name, "requires.stage_one") / DEV_RESULTS
        record = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
        passed = record is not None and record["stage_one"]["passed"] is True
        tested = set() if record is None else {c for cand in record["candidates"].values() for c in cand["columns"]}
        checks.append(_check(f"{name} passed its own stage 1 with the static inputs added here",
                             passed and set(static_inputs(study)) <= tested, str(path)))
    return checks


def published_v3_numbers() -> dict:
    """v3's POOLED numbers of the committed W1 report, which the pool assembled here must reproduce."""
    return op.published_v3(op.REPORTS / f"{vh.REPORT_STEM}.json")


def w1_report() -> dict:
    return json.loads((op.REPORTS / f"{vh.REPORT_STEM}.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------------------------------- candidates

def make_candidates(study: dict, base_columns, column_map: dict[str, str] | None = None) -> dict[str, vc.Candidate]:
    """C0 (the frozen inputs and v3 constraints) and the challenger (C0 plus `add_increasing`, each constrained non-decreasing,
    plus `add_static`, unconstrained).
    With `column_map` the added inputs must be columns of the candidate's `add_groups`."""
    out = {}
    for name, spec in study["candidates"].items():
        added, static = list(spec.get("add_increasing", [])), list(spec.get("add_static", []))
        if len(set(added)) != len(added):
            raise ValueError(f"candidate {name}: add_increasing names an input more than once")
        clash = [c for c in [*added, *static] if c in base_columns]
        if clash:
            raise ValueError(f"candidate {name}: {clash} added, already an input of the frozen model")
        if set(static) - set(sw.HAZARD_COLUMNS) or len(set(static)) != len(static):
            raise ValueError(f"candidate {name}: add_static must name physical columns of the W5 static table, each once")
        if column_map is not None:
            groups = spec.get("add_groups", [])
            stray = [c for c in added if column_map.get(c) not in groups]
            if stray:
                raise ValueError(f"candidate {name}: {stray} are not columns of the groups {groups}")
        columns = [*base_columns, *added, *static]
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


def check_reproduction(result: cv.CVResult, selected: dict, tolerance: float) -> dict:
    """The reference must reproduce the frozen v3-live pooled OOF FA@90 to `tolerance` and its tree count exactly."""
    record = {"recomputed_fa_at_90": result.pooled[HEADLINE], "reported_fa_at_90": selected["pooled"][HEADLINE],
              "abs_difference": abs(result.pooled[HEADLINE] - selected["pooled"][HEADLINE]), "tolerance": tolerance,
              "n_trees": result.n_trees, "reported_n_trees": selected["n_trees"]}
    if record["abs_difference"] > tolerance or result.n_trees != selected["n_trees"]:
        raise ch.ReproductionError(
            f"{result.name}: recomputed FA@90 {record['recomputed_fa_at_90']:.12f} / {result.n_trees} trees versus the frozen "
            f"v3-live {record['reported_fa_at_90']:.12f} / {selected['n_trees']} trees (tolerance {tolerance:g})")
    return record


def fit_model(study: dict, candidate: vc.Candidate, dev: hd.Development, layout: cv.Layout, result: cv.CVResult,
              directory: Path, lag_days: int) -> hm.HazardModel:
    """Refit v4-int on all development rows exactly as v3-live was (`v31_challenger.fit_final`) and mark its card: the W3
    protocol, the six intensity inputs among its monotone-increasing assumptions, and the lag they were built with."""
    base = study["base"]
    model = vc.fit_final(candidate, dev, layout, result, base, NO_KEYS, directory)
    added = list(study["candidates"][candidate.name].get("add_increasing", []))
    model.card.update(
        protocol="v2 (year-blocked CV over 2007-2017); W3 rain-intensity challenger, spec 2026-11-06",
        description=f"W3 challenger {candidate.name}: {candidate.description}",
        monotone_assumptions={"increasing": [*base["monotone"]["increasing"], *added], "decreasing": base["monotone"]["decreasing"]},
        intensity={"group": ii.GROUP, "lag_days": lag_days, "inputs": added})
    if static_inputs(study):
        model.card.update(protocol=study["protocol"],
                          static={"group": sw.GROUP, "inputs": static_inputs(study), "excluded": list(sw.EXPOSURE_COLUMNS),
                                  "constraints": "none"})
    model.save(directory)
    return model


def load_development(study: dict, features_dir: Path | None, lag_days: int) -> hd.Development:
    """The development rows with the iint tables of `lag_days` and, when the challenger adds static inputs, the W5 static
    table joined at each row's terrain cell."""
    extras, use, meta = extra_groups(study, lag_days), groups_used(study), study["base"]["meta_columns"]
    if not static_inputs(study):
        return hd.load_development(features_dir, extras, use, meta)
    root, table = Path(features_dir or hd.features_dir()), sw.static_table()
    samples = pd.concat([hd.load_table(hd.SAMPLE_NAMES[s], root, extras, use) for s in hd.DEVELOPMENT_SPLITS], ignore_index=True)
    universe = pd.concat([hd.load_table(hd.UNIVERSE_NAMES[s], root, extras, use) for s in hd.DEVELOPMENT_SPLITS], ignore_index=True)
    column_map = {**hd.load_column_map(root, extras, use, meta), **{c: sw.GROUP for c in sw.STATIC_COLUMNS}}
    return hd.build_development(sw.join_static(samples, table), sw.join_static(universe, table), column_map)


def run_dev(study: dict, features_dir: Path | None = None, say=print, force: bool = False) -> dict:
    """Stage 1: cross-validate the reference (it must reproduce the frozen v3-live FA@90) and v4-int, compare them by the
    paired bootstrap, apply the pre-declared rule and refit v4-int when it passes. test_2018 is not read.

    Refuses to overwrite earlier results: when a held-out result exists always, when `dev_results.json` exists unless `force`.
    Uses the lag the gap report declares."""
    started = time.perf_counter()
    base, out = study["base"], output_dir(study)
    if (out / HELDOUT).exists() or (out / STARTED).exists():
        raise FileExistsError(f"{out / HELDOUT} or {out / STARTED} exists: the look has been taken (or started) on the models "
                              "of those results; `dev` will not rerun")
    if (out / DEV_RESULTS).exists() and not force:
        raise FileExistsError(f"{out / DEV_RESULTS} exists; pass --force to rerun the development stage and overwrite it")
    unmet = [c["name"] for c in check_requires(study) if not c["passed"]]
    if unmet:
        raise StageOneError(f"this study's requirements are not met: {unmet}")
    lag = declared_lag()
    selected = frozen_selection(study)
    dev = load_development(study, features_dir, lag)
    layout = cv.make_layout(dev, base["cv"]["folds"])
    say(f"lag {lag} d ({ii.group_name(lag)}); development rows: {len(layout.positives)} positives, "
        f"{len(layout.negatives):,} universe negatives, {len(layout.matched)} matched negatives")
    candidates = make_candidates(study, selected["columns"], dev.column_map)
    reference = study["reference"]
    results, frames, reproduction = {}, {}, None
    for name in [reference, *[n for n in candidates if n != reference]]:
        candidate = candidates[name]
        result = cv.run_cv(dev, layout, candidate.columns, candidate.constraints, selected["hp"], selected["neg_mix"], base, name)
        say(f"{name}: FA@90 {result.pooled[HEADLINE]:.4f}, {result.n_trees} trees, {len(candidate.columns)} inputs, "
            f"{result.seconds:.0f}s")
        if name == reference:
            reproduction = check_reproduction(result, selected, float(study["reproduction_tolerance"]))
            say(f"  reproduces frozen v3-live: |difference| {reproduction['abs_difference']:.2e}")
        results[name], frames[name] = result, ch.oof_frame(layout, result.oof)
        vc.save_oof(out / OOF_SUBDIR, frames[name], result)
    comparison = compare(frames, study)
    stage = stage_one(comparison["difference"])
    say(f"stage 1: {study['challenger']} - {reference} FA@90 {stage['difference']:+.4f} [{stage['ci'][0]:+.4f}, {stage['ci'][1]:+.4f}] "
        f"-> {'passed' if stage['passed'] else 'FAILED'} ({stage['verdict']})")
    model_dir = None
    if stage["passed"]:
        model_dir = out / MODEL_SUBDIR / study["challenger"]
        fit_model(study, candidates[study["challenger"]], dev, layout, results[study["challenger"]], model_dir, lag)
        say(f"refitted {study['challenger']} -> {hm.display_path(model_dir)}")
    payload = {
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "lag_days": lag,
        "intensity_group": ii.group_name(lag),
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


def current_lag(dev: dict) -> int:
    """The declared lag, which must be the one the development stage (and so the model) used."""
    lag = declared_lag()
    if dev["lag_days"] != lag:
        raise ValueError(f"the gap report now declares lag {lag}, but the development stage and its model used lag "
                         f"{dev['lag_days']}; rerun `dev --force`")
    return lag


# ------------------------------------------------------------------------------------------ the decision

def decide(stage: dict, scores: dict | None = None, incumbent: str = "v3_ranked") -> dict:
    """The pre-declared adoption criterion of spec section 3, literally.

    Stage 1 failed: not adopted, the held-out set is not evaluated. Otherwise `scores` (`operating_point.score_heldout` of
    the pool whose `v3` is `v3_ranked`) must hold, in both tolerances and at Warning+ and Emergency, the independent-slide
    detection (`group_hits`) of v3_ranked and of the candidate: adopted when the candidate's is >= v3_ranked's in all four
    comparisons and > in at least one. Watch+ is reported in the scores but does not decide.
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
            "reason": f"adopted: no independent-slide detection is lower than {incumbent}'s and one is higher" if not failed
            else "not adopted: " + "; ".join(failed)}


# ------------------------------------------------------------------------------- season panels with iint

def season_iint(study: dict, directory: Path, year: int, cell_ids, days: list[date], lag_days: int = 0) -> np.ndarray:
    """The six iint features (float32, cells x days x 6) of a held-out season from its frozen table built with `lag_days`,
    verified against the manifest, the panel's cells (and their order) and its days."""
    directory = Path(directory)
    path = directory / ii.season_name(year, lag_days)
    manifest = directory / iint_spec(study, lag_days)["manifest_file"]
    if not path.is_file() or not manifest.is_file():
        raise FileNotFoundError(f"{path} or {manifest} not found; build the iint tables first "
                                "(python -m aetherguard.features.imerg_intensity tables)")
    record = json.loads(manifest.read_text(encoding="utf-8"))
    entry = record["files"].get(path.name)
    if entry is None:
        raise IintTableError(f"{path.name} is not listed in {manifest.name}")
    if record.get("lag_days", 0) != lag_days:
        raise IintTableError(f"{manifest.name} was built with lag {record.get('lag_days')}, not {lag_days}")
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


def season_path(directory: Path, year: int, tag: str = SEASON_TAG) -> Path:
    return Path(directory) / f"season_{year}_{tag}.npz"


def score_season(model, card_sha: str, study: dict, year: int, features_dir: Path, out_dir: Path, say=print,
                 force: bool = False, lag_days: int = 0) -> Path:
    """Score June-December `year` (plus the backtest warm-up days) of the 2018 set's cells with v4-int and the training-style
    features joined to the frozen iint season table of `lag_days`, as `verify.seasons.score_season` scores v3; returns the
    panel's path. An existing panel is kept unless `force`."""
    path = season_path(out_dir, year, study.get("season_tag", SEASON_TAG))
    if path.is_file() and not force:
        say(f"season {year}: {path} exists, skipped")
        return path
    started = time.perf_counter()
    cfg = live_run.load_run_config()
    spec = bt.load_set(f"season_{year}", date(year, *vs.SEASON_START), date(year, *vs.SEASON_END), cfg)
    days = bt.set_days(spec)
    intensity = season_iint(study, iint_dir(study, features_dir), year, spec.cells["cell_id"].to_numpy(), days, lag_days)
    column = {day: j for j, day in enumerate(days)}
    static = static_inputs(study)       # per cell, the same every day: what training joined, read from the same table
    ground = sw.join_static(spec.cells[["cell_id"]], sw.static_table())[static] if static else None
    stores = bt.build_stores(spec.cells, cfg)
    say(f"season {year}: {len(spec.cells)} cells, {spec.start} to {spec.end}")

    def features(day: date) -> pd.DataFrame:
        base = bt.training_style_features(day, spec.cells, stores).reset_index(drop=True)
        return pd.concat([base, pd.DataFrame(intensity[:, column[day], :], columns=ii.feature_names()),
                          *([] if ground is None else [ground])], axis=1)

    panel = H.score_panel(days, spec.cells.assign(in_universe=True), lambda day: model, features, say)
    seconds = time.perf_counter() - started
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    dump_json(path.with_suffix(".json"), {
        "year": year, "features": study.get("features_tag", FEATURES_TAG), "lag_days": lag_days, "n_days": len(panel.days),
        **({} if ground is None else {"static_nan_cells": {c: int(ground[c].isna().sum()) for c in static}}),
        "n_cells": int(len(panel.cells)), "first_day": panel.days[0].isoformat(), "last_day": panel.days[-1].isoformat(),
        "warmup_days": bt.WARMUP_DAYS, "n_members": panel.n_members, "scored_share_per_day": vs.scored_share_summary(panel),
        "model_card_sha256": card_sha, "seconds": seconds})
    H.save_panel(path, panel)
    say(f"season {year}: written {path} in {seconds:.0f}s")
    return path


def load_model(study: dict) -> tuple[hm.HazardModel, str]:
    directory = output_dir(study) / MODEL_SUBDIR / study["challenger"]
    if not (directory / hm.CARD_FILE).is_file() or not load_dev_results(study)["stage_one"]["passed"]:
        raise StageOneError(f"no {study['challenger']} model under {directory} from a passed stage 1 (run `dev`)")
    return hm.HazardModel.load(directory), sha256_file(directory / hm.CARD_FILE)


def run_seasons(study: dict, features_dir: Path | None = None, years=bt.SEASON_YEARS, say=print, force: bool = False) -> list[Path]:
    """Score the held-out seasons with v4-int (no outcome is read; this is not the look)."""
    model, card_sha = load_model(study)
    lag = current_lag(load_dev_results(study))
    features_dir = Path(features_dir or hd.features_dir())
    return [score_season(model, card_sha, study, year, features_dir, seasons_dir(study), say, force, lag) for year in years]


# ---------------------------------------------------------------------------------------- burden matching

def _splitmix64(z: np.ndarray) -> np.ndarray:
    """One round of SplitMix64 on a uint64 array (wrapping arithmetic, the same on every platform)."""
    z = z + np.uint64(0x9E3779B97F4A7C15)
    z = (z ^ (z >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
    z = (z ^ (z >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
    return z ^ (z >> np.uint64(31))


def tie_keys(cell_ids, ordinals, seed: int = TIE_SEED) -> np.ndarray:
    """A pseudo-random uint64 per (cell_id, day ordinal) pair, deterministic across runs and platforms: SplitMix64 of the
    seed mixed with the cell and then with the day. It depends on the pair only, never on its position in an array."""
    cells, days = np.asarray(cell_ids).astype(np.uint64), np.asarray(ordinals).astype(np.uint64)
    with np.errstate(over="ignore"):
        z = _splitmix64(np.uint64(seed) ^ (cells * np.uint64(0xD1B54A32D192ED03)))
        return _splitmix64(z ^ (days * np.uint64(0x8CB92BA72F3D8DD7)))


def match_burden(risk: np.ndarray, raw: np.ndarray, scored: np.ndarray, v3_levels: np.ndarray, cell_ids, days: list[date],
                 tolerance: float = 1e-4, seed: int = TIE_SEED) -> tuple[np.ndarray, dict]:
    """Levels (cells x days) for one season by ranking: the scored cell-days sorted by calibrated `risk`, ties by `raw`
    (the panel's raw score), cell-days still tied on both by `tie_keys` of (cell_id, day) (never by array position), and the
    top ones cut to the Watch+ / Warning+ / Emergency shares `v3_levels` realised on them (the cut sizes are those shares of
    the scored cell-days, rounded). `cell_ids` has one entry per row and `days` one date per column. Raises BurdenMatchError
    when a realised share is more than `tolerance` from its target. Also the targets, the realised shares and, per level, the
    tie mass at the cut: how many scored cell-days share the (risk, raw) of the last cell-day taken, how many of them are taken,
    how many of them a straddled tie leaves out (`straddle`), and how many share its risk alone."""
    risk, raw, scored = np.asarray(risk, dtype=np.float64), np.asarray(raw, dtype=np.float64), np.asarray(scored, dtype=bool)
    if not (risk.shape == raw.shape == scored.shape == np.shape(v3_levels)):
        raise ValueError(f"risk {risk.shape}, raw {raw.shape}, scored {scored.shape} and v3 levels {np.shape(v3_levels)} must share one shape")
    cell_ids = np.asarray(cell_ids, dtype=np.int64)
    if cell_ids.shape != (scored.shape[0],) or len(days) != scored.shape[1]:
        raise ValueError(f"cell_ids {cell_ids.shape} and {len(days)} days do not match the {scored.shape} cells x days")
    rows = np.flatnonzero(scored.ravel())
    if not len(rows):
        raise ValueError("no scored cell-day to rank")
    ordinals = np.array([d.toordinal() for d in days], dtype=np.int64)
    keys = tie_keys(cell_ids[rows // scored.shape[1]], ordinals[rows % scored.shape[1]], seed)
    r, w = risk.ravel()[rows], raw.ravel()[rows]
    if not (np.isfinite(r).all() and np.isfinite(w).all()):
        raise ValueError("risk and raw must be finite on every scored cell-day")
    target = realised_shares(v3_levels, scored)
    order = np.lexsort((keys, w, r))[::-1]                            # highest risk first, then raw score, then the seeded key
    flat = np.zeros(scored.size, dtype=np.int8)
    cuts = {}
    for level, share in zip(LEVELS, target):
        k = int(round(share * len(rows)))
        flat[rows[order[:k]]] = level
        if k:
            last = order[k - 1]
            same = (r == r[last]) & (w == w[last])
            tied, taken = int(same.sum()), int(same[order[:k]].sum())
            cuts[level] = {"cell_days_taken": k, "cut_risk": float(r[last]), "cut_raw": float(w[last]),
                           "tied_cell_days": tied, "tied_taken": taken, "straddle": tied - taken if taken else 0,
                           "risk_tied_cell_days": int((r == r[last]).sum())}
        else:
            cuts[level] = {"cell_days_taken": 0, "cut_risk": None, "cut_raw": None, "tied_cell_days": 0, "tied_taken": 0,
                           "straddle": 0, "risk_tied_cell_days": 0}
    levels = flat.reshape(scored.shape)
    realised = realised_shares(levels, scored)
    off = [f"level {k}: {got:.6f} against {want:.6f}" for k, got, want in zip(LEVELS, realised, target) if abs(got - want) > tolerance]
    if off:
        raise BurdenMatchError("realised shares differ from the target by more than " + f"{tolerance:g}: " + "; ".join(off))
    return levels, {"target": list(target), "realised": list(realised), "cuts": cuts}


@dataclass
class SeasonInput:
    """What the assembly reads of one season: v3's season (levels with the rules, and its panel's risk, raw score, days and
    scored cell-days over the whole panel), v4-int's panel, and the share of scored cell-days with a NaN intensity input."""

    year: int
    part: vr.Part
    first: int
    days: list[date]
    v3_scored: np.ndarray
    v3_risk: np.ndarray
    v3_raw: np.ndarray
    v4: H.Panel
    iint_nan_share: dict[str, float]


def iint_nan_share(values: np.ndarray, scored: np.ndarray) -> dict[str, float]:
    """Per iint feature the share of scored cell-days (cells x days) whose value is NaN."""
    scored = np.asarray(scored, dtype=bool)
    return {name: float(np.isnan(values[:, :, j][scored]).mean()) if scored.any() else float("nan")
            for j, name in enumerate(ii.feature_names())}


def check_season(inp: SeasonInput, reference: np.ndarray) -> None:
    """The v4-int panel must be v3's season like for like: the cells of the 2018 operational reference, in its order; the
    same days (warm-up included); the same scored cell-days; and a finite risk and raw score exactly where scored."""
    year, panel = inp.year, inp.v4
    if not np.array_equal(inp.part.cell_ids, reference) or not np.array_equal(panel.cells["cell_id"].to_numpy(dtype=np.int64), reference):
        raise ValueError(f"season {year}: the cells (or their order) of the v3 season or the v4-int panel differ from the 2018 reference")
    if list(panel.days) != list(inp.days) or list(inp.part.days) != list(inp.days[inp.first:]):
        raise ValueError(f"season {year}: the days of the v4-int panel and the v3 season differ")
    if not np.array_equal(panel.scored, inp.v3_scored):
        raise ValueError(f"season {year}: the scored cell-days of the v4-int panel and the v3 season differ")
    for label, fields, scored in (("v3", (inp.v3_risk, inp.v3_raw), inp.v3_scored),
                                  ("v4-int", (np.asarray(panel["risk"]), np.asarray(panel["raw"])), panel.scored)):
        if any(not np.array_equal(np.isfinite(field), scored) for field in fields):
            raise ValueError(f"season {year}: the {label} risk or raw score is not finite exactly where scored")


def events_digest(events: pd.DataFrame) -> str:
    """SHA-256 over the sorted (cell_id, date, source) rows of the held-out events."""
    rows = sorted(f"{int(c)},{pd.Timestamp(d):%Y-%m-%d},{s}" for c, d, s in zip(events["cell_id"], events["date"], events["source"]))
    return hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()


@dataclass
class Assembly:
    """The pooled held-out set before any outcome is computed: `ranked` (v3_ranked against v4-int, the deciding pool) and
    `rules` (v3 with the section 11 rules against v4-int, reported beside it), and the facts the preflight checks."""

    pools: dict[str, op.HeldOut]
    info: dict


def assemble(inputs: Iterable[SeasonInput], reference: np.ndarray, events: pd.DataFrame, tolerance: float = 1e-4,
             seed: int = TIE_SEED, names: tuple[str, str] = ("v3_ranked", "v4_int")) -> Assembly:
    """Pool the seasons as `verify.operating_point.build_heldout` does, with v4-int's and v3_ranked's burden-matched levels
    beside v3's levels with the rules. Nothing here joins an event with a level."""
    reference = np.asarray(reference, dtype=np.int64)
    incumbent, candidate = names
    v3, ranked, v4, scored, days, seasons = [], [], [], [], [], {}
    for inp in inputs:
        check_season(inp, reference)
        first = inp.first
        part = inp.part
        v4_levels, v4_info = match_burden(np.asarray(inp.v4["risk"])[:, first:], np.asarray(inp.v4["raw"])[:, first:], part.scored,
                                          part.v3, reference, part.days, tolerance, seed)
        ranked_levels, ranked_info = match_burden(inp.v3_risk[:, first:], inp.v3_raw[:, first:], part.scored, part.v3,
                                                  reference, part.days, tolerance, seed)
        seasons[str(inp.year)] = {
            "cells": int(len(reference)), "days": len(part.days), "panel_days": len(inp.days),
            "scored_cell_days": int(part.scored.sum()), "v3_realised_shares": list(realised_shares(part.v3, part.scored)),
            incumbent: ranked_info, candidate: v4_info, "iint_nan_share": inp.iint_nan_share}
        v3.append(part.v3)
        ranked.append(ranked_levels)
        v4.append(v4_levels)
        scored.append(part.scored)
        days += part.days
    if not seasons:
        raise ValueError("no season to assemble")
    v3, ranked, v4, scored = (np.concatenate(a, axis=1) for a in (v3, ranked, v4, scored))
    kept, outside = vh.events_on_days(events, days)
    unique = kept.drop_duplicates(["cell_id", "date"])
    info = {
        "seasons": seasons,
        "pooled": {"cells": int(len(reference)), "days": len(days), "scored_cell_days": int(scored.sum()),
                   # counted as the W1 report counts them: every cell-day at the level, held levels on unscored rows included
                   "alert_cell_days": {name: [int((levels >= k).sum()) for k in LEVELS]
                                       for name, levels in (("v3_rules", v3), (incumbent, ranked), (candidate, v4))},
                   # the three on the same scored cell-days, which the pooled burden comparison uses
                   "alert_cell_days_scored": {name: [int(((levels >= k) & scored).sum()) for k in LEVELS]
                                              for name, levels in (("v3_rules", v3), (incumbent, ranked), (candidate, v4))}},
        "events": {"events": int(len(unique)), "outside_panel_days": int(outside), "distinct_slides": vh.distinct_events(kept),
                   "by_source": {k: int(v) for k, v in unique.groupby("source").size().items()}},
        "events_sha256": events_digest(kept)}
    return Assembly({"ranked": op.HeldOut(reference, days, scored, ranked, v4, kept, outside),
                     "rules": op.HeldOut(reference, days, scored, v3, v4, kept, outside)}, info)


def season_inputs(study: dict, lag_days: int, features_dir: Path, say=print) -> tuple[np.ndarray, pd.DataFrame, Iterable[SeasonInput]]:
    """(the 2018 operational reference cells, the held-out events 2018-2025, a generator of the seasons, one panel pair in
    memory at a time) from the stored panels."""
    cfg = live_run.load_run_config()
    v3_model, config, base_rules = ps.load_inputs(cfg)
    reference = H.load_panel(H.alerts_dir(H.HELDOUT_DIR) / H.HELDOUT_FILE).cells["cell_id"].to_numpy()
    events = vh.load_event_table(cfg)
    events = events[pd.to_datetime(events["date"]).dt.year.isin(bt.SEASON_YEARS)]

    incumbent = study.get("incumbent")       # a ranked incumbent other than v3: its own season panels

    def seasons_():
        for year in bt.SEASON_YEARS:
            say(f"held-out season {year}: {pool_names(study)[0]} and {study['challenger']}")
            path = season_file(study, year)
            if not path.is_file():
                raise FileNotFoundError(f"{path} not found; score the seasons first (python -m aetherguard.hazard.v4_int seasons)")
            season = vh.load_panel_season(year, reference, v3_model)
            panel = season.panel
            v4 = H.load_panel(path)
            values = season_iint(study, iint_dir(study, features_dir), year, v4.cells["cell_id"].to_numpy(), v4.days, lag_days)
            ranked = panel
            if incumbent:
                ranked = H.load_panel(season_path(H.alerts_dir(_plain_name(incumbent["seasons_dir"], "incumbent.seasons_dir")),
                                                  year, incumbent["season_tag"]))
                if (list(ranked.days) != list(panel.days) or not np.array_equal(ranked.scored, panel.scored)
                        or not np.array_equal(ranked.cells["cell_id"].to_numpy(dtype=np.int64), reference)):
                    raise ValueError(f"season {year}: the incumbent's panel differs from v3's in cells, days or scored cell-days")
            yield SeasonInput(year, vr.extract(season, config, base_rules), season.first, list(panel.days), panel.scored.copy(),
                              np.asarray(ranked["risk"]), np.asarray(ranked["raw"]), v4,
                              iint_nan_share(values[:, season.first:], v4.scored[:, season.first:]))
            del season, panel, ranked, v4, values
    return reference, events, seasons_()


def load_assembly(study: dict, lag_days: int, features_dir: Path, say=print) -> Assembly:
    reference, events, inputs = season_inputs(study, lag_days, features_dir, say)
    return assemble(inputs, reference, events, seed=int(study.get("tie_seed", TIE_SEED)), names=pool_names(study))


def build_heldout(study: dict, say=print, lag_days: int = 0, features_dir: Path | None = None) -> tuple[dict[str, op.HeldOut], dict]:
    assembly = load_assembly(study, lag_days, Path(features_dir or hd.features_dir()), say)
    return assembly.pools, assembly.info


# ---------------------------------------------------------------------------------------------- preflight

def peak_memory_mb() -> float:
    """Peak working set of this process, in MB."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t)]

        kernel, psapi = ctypes.WinDLL("kernel32"), ctypes.WinDLL("psapi")
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        counters = Counters()
        counters.cb = ctypes.sizeof(Counters)
        if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            raise OSError("GetProcessMemoryInfo failed")
        return counters.PeakWorkingSetSize / 2**20
    import resource
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / 2**20 if sys.platform == "darwin" else peak / 2**10


def non_finite(value, path: str = "$") -> list[str]:
    """Paths of the NaN or infinite numbers in a nested structure."""
    if isinstance(value, dict):
        return [p for k, v in value.items() for p in non_finite(v, f"{path}.{k}")]
    if isinstance(value, (list, tuple)):
        return [p for i, v in enumerate(value) for p in non_finite(v, f"{path}[{i}]")]
    if isinstance(value, (float, np.floating)) and not np.isfinite(value):
        return [path]
    return []


def provenance(study: dict, lag_days: int, features_dir: Path) -> dict:
    """The checksums the look relies on: v4-int's card and season panels, v3's season panels and the iint manifest."""
    directory = output_dir(study) / MODEL_SUBDIR / study["challenger"]
    return {"lag_days": lag_days, "card_sha256": sha256_file(directory / hm.CARD_FILE),
            "v4_panel_sha256": {str(y): sha256_file(season_file(study, y)) for y in bt.SEASON_YEARS},
            **({"files_sha256": {k: sha256_file(data_root() / v) for k, v in study["provenance_files"].items()}}
               if study.get("provenance_files") else {}),
            "v3_panel_sha256": {str(y): sha256_file(vs.season_path(None, y)) for y in bt.SEASON_YEARS},
            "iint_manifest_sha256": sha256_file(iint_dir(study, features_dir) / iint_spec(study, lag_days)["manifest_file"])}


def _check(name: str, passed: bool, detail) -> dict:
    return {"name": name, "passed": bool(passed), "detail": detail}


def check_guard(study: dict, dev: dict, lag_days: int) -> list[dict]:
    out = output_dir(study)
    return [*check_requires(study),
            _check("no held-out result in data/", not (out / HELDOUT).exists(), str(out / HELDOUT)),
            _check("no committed report", not report_path(study).exists(), str(report_path(study))),
            _check("no look-started marker", not (out / STARTED).exists(), str(out / STARTED)),
            _check("stage 1 passed", dev["stage_one"]["passed"], dev["stage_one"]["verdict"]),
            _check("gap report present with its lag, the lag the model was built with", dev["lag_days"] == lag_days,
                   {"gap_report": str(gap_report_path()), "declared_lag_days": lag_days, "dev_lag_days": dev["lag_days"]})]


def check_provenance(study: dict, lag_days: int, prov: dict) -> list[dict]:
    """The season sidecars of v4-int: scored by the current card, with the training-style + iint features at this lag, with
    the same ensemble size as v3."""
    v3_members = json.loads((hm.configured_model_dir(study["base"]) / hm.CARD_FILE).read_text(encoding="utf-8"))["n_members"]
    checks = []
    for year in bt.SEASON_YEARS:
        sidecar = json.loads(season_file(study, year).with_suffix(".json").read_text(encoding="utf-8"))
        ok = (sidecar["model_card_sha256"] == prov["card_sha256"] and sidecar["features"] == study.get("features_tag", FEATURES_TAG)
              and sidecar["n_members"] == v3_members == study["base"]["ensemble"]["members"] and sidecar.get("lag_days") == lag_days)
        checks.append(_check(f"season {year} provenance", ok, {k: sidecar.get(k) for k in (
            "model_card_sha256", "features", "n_members", "lag_days")} | {"card_sha256": prov["card_sha256"], "v3_n_members": v3_members}))
    return checks


def check_iint_tables(study: dict, features_dir: Path, lag_days: int, panels_dir: Path | None = None) -> list[dict]:
    """The frozen iint tables: frozen, built without --allow-missing, no required day missing, built from the current v3 season
    panels, and every file as recorded."""
    directory = iint_dir(study, features_dir)
    panels = Path(panels_dir or H.alerts_dir(vs.OUT_DIR))
    manifest = json.loads((directory / iint_spec(study, lag_days)["manifest_file"]).read_text(encoding="utf-8"))
    stale = [y for y, entry in manifest["inputs"]["season_panels"].items()
             if sha256_file(ii.panel_path(panels, int(y))) != entry["sha256"]]
    verified = ii.verify_iint_tables(directory, None, None, panels, None, lag_days)
    return [_check("iint tables frozen", manifest.get("frozen") is True, manifest.get("created_utc")),
            _check("iint tables built without --allow-missing", manifest.get("allow_missing") is False, manifest.get("allow_missing")),
            _check("no required Late day missing", manifest.get("required_days_missing") == 0, manifest.get("required_days_missing")),
            _check("iint tables built at this lag", manifest.get("lag_days") == lag_days, manifest.get("lag_days")),
            _check("iint tables built from the current v3 season panels", not stale, {"changed": stale}),
            _check("iint tables intact", verified["ok"] and not verified["problems"], verified["problems"])]


def check_assembly(study: dict, info: dict, w1: dict) -> list[dict]:
    """v3 against the W1 report (burden only), the events, and v4-int's and v3_ranked's burden against v3's."""
    expect = study["preflight"]
    checks = []
    for year, season in info["seasons"].items():
        ref = w1["seasons"][year]
        checks.append(_check(f"season {year} v3 burden equals W1",
                             season["v3_realised_shares"] == ref["v3_realised_shares"] and season["scored_cell_days"] == ref["scored_cell_days"]
                             and season["days"] == ref["days"] and season["cells"] == ref["cells"],
                             {"shares": season["v3_realised_shares"], "w1_shares": ref["v3_realised_shares"],
                              "scored_cell_days": season["scored_cell_days"], "w1_scored_cell_days": ref["scored_cell_days"]}))
        tol = float(expect["burden_tolerance"])
        worst = max(abs(a - b) for name in pool_names(study) for a, b in zip(season[name]["realised"], season["v3_realised_shares"]))
        checks.append(_check(f"season {year} burden matched within {tol:g}", worst <= tol, worst))
    pooled = info["pooled"]
    checks.append(_check("pooled cells and days", (pooled["cells"], pooled["days"]) == (expect["cells"], expect["days"]),
                         [pooled["cells"], pooled["days"]]))
    rules = pooled["alert_cell_days"]["v3_rules"]
    checks.append(_check("pooled v3 alert cell-days equal W1", rules == list(expect["v3_alert_cell_days"]), rules))
    for name in pool_names(study):
        scored_counts = pooled["alert_cell_days_scored"]
        gap = max(abs(a - b) / b for a, b in zip(scored_counts[name], scored_counts["v3_rules"]))
        checks.append(_check(f"pooled {name} alert cell-days within {expect['pooled_alert_tolerance']:.2%} of v3's",
                             gap <= float(expect["pooled_alert_tolerance"]), gap))
    checks += check_straddle(study, info)
    events = info["events"]
    checks.append(_check("events: 92 on panel days, 1 outside, 87 independent slides, by source",
                         events == {"events": expect["events"], "outside_panel_days": expect["events_outside_panel_days"],
                                    "distinct_slides": expect["distinct_slides"], "by_source": dict(expect["events_by_source"])}, events))
    return checks


def check_straddle(study: dict, info: dict) -> list[dict]:
    """Per season: the cell-days tied on both calibrated risk and raw score that straddle the Warning+ or Emergency cut (the
    ones the seeded key leaves out of a tie it splits) must be at most `straddle_tolerance` of that level's alert cell-days,
    for v4-int and for v3_ranked. The numbers are reported."""
    limit = float(study["preflight"]["straddle_tolerance"])
    checks = []
    for year, season in info["seasons"].items():
        detail, ok = {}, True
        for name in reversed(pool_names(study)):
            for level, label in DECIDING_LEVELS.items():
                cut = season[name]["cuts"][level]
                share = cut["straddle"] / cut["cell_days_taken"] if cut["cell_days_taken"] else 0.0
                detail[f"{name} {label}"] = {"straddle": cut["straddle"], "tied_cell_days": cut["tied_cell_days"],
                                             "tied_taken": cut["tied_taken"], "alert_cell_days": cut["cell_days_taken"],
                                             "share": share}
                ok = ok and share <= limit
        checks.append(_check(f"season {year} full ties straddling a cut within {limit:.0%} of the alert cell-days", ok, detail))
    return checks


def run_preflight(study: dict, features_dir: Path | None = None, say=print, load: Callable = load_assembly) -> dict:
    """Everything the look relies on, checked without computing an outcome: the guards, the provenance of v4-int's panels,
    the iint tables, the alignment of v4-int's panels with v3's, v3's burden against the W1 report, the events, and the
    burden matching. Writes preflight.json (`outcome_computed` false) whatever the result; `heldout` needs it to have passed."""
    started = time.perf_counter()
    out = output_dir(study)
    features_dir = Path(features_dir or hd.features_dir())
    if (out / HELDOUT).exists() or (out / STARTED).exists():
        raise FileExistsError(f"{out / HELDOUT} or {out / STARTED} exists: the look has been taken (or started); a preflight no "
                              "longer means anything")
    dev = load_dev_results(study)
    lag = declared_lag()
    checks = check_guard(study, dev, lag)
    record = {"outcome_computed": False, "lag_days": lag, "stage_one": dev["stage_one"]}
    if dev["stage_one"]["passed"]:
        prov = provenance(study, lag, features_dir)
        record["provenance"] = prov
        checks += check_provenance(study, lag, prov) + check_iint_tables(study, features_dir, lag)
        try:
            assembly = load(study, lag, features_dir, say)
        except (ValueError, BurdenMatchError, FileNotFoundError, IintTableError) as exc:
            checks.append(_check("assembly (alignment, burden matching)", False, f"{type(exc).__name__}: {exc}"))
        else:
            record.update(seasons=assembly.info["seasons"], pooled=assembly.info["pooled"], events=assembly.info["events"],
                          events_sha256=assembly.info["events_sha256"])
            checks.append(_check("assembly (alignment, burden matching)", True, "cells, days, scored cell-days and finite scores match"))
            checks += check_assembly(study, assembly.info, w1_report())
    record["checks"] = checks
    record["peak_memory_mb"] = peak_memory_mb()
    record["seconds"] = time.perf_counter() - started
    record["created_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    bad = non_finite(record)
    record["checks"].append(_check("JSON serialisable without NaN", not bad, bad))
    record["passed"] = bool(dev["stage_one"]["passed"] and all(c["passed"] for c in record["checks"]))
    out.mkdir(parents=True, exist_ok=True)
    dump_json(out / PREFLIGHT, record)
    failed = [c["name"] for c in record["checks"] if not c["passed"]]
    say(f"preflight {'PASSED' if record['passed'] else 'FAILED'}: {len(record['checks']) - len(failed)}/{len(record['checks'])} checks"
        + (f"; failed: {failed}" if failed else "") + f"; peak memory {record['peak_memory_mb']:.0f} MB; wrote {hm.display_path(out / PREFLIGHT)}")
    return record


def require_preflight(study: dict, lag_days: int, features_dir: Path) -> dict:
    """The stored preflight when it passed, computed no outcome, and its card, panel, lag and iint checksums are current."""
    path = output_dir(study) / PREFLIGHT
    if not path.is_file():
        raise PreflightError(f"{path} not found; run `preflight` before the look")
    record = json.loads(path.read_text(encoding="utf-8"))
    if record.get("passed") is not True or record.get("outcome_computed") is not False:
        raise PreflightError(f"{path.name} did not pass (or computed an outcome); fix it and run `preflight` again")
    if record.get("provenance") != provenance(study, lag_days, features_dir):
        raise PreflightError(f"{path.name} was made for a different card, season panels, iint tables or lag; run `preflight` again")
    return record


# ---------------------------------------------------------------------------------------- the held-out look

def refuse_second_look(*paths: Path) -> None:
    for path in paths:
        if Path(path).exists():
            raise FileExistsError(f"{Path(path).name} exists: the held-out look has been taken and is not repeated ({path})")


def evaluate_once(path: Path, committed: Path, build: Callable[[], tuple[dict[str, op.HeldOut], dict]],
                  boot: dict = bt.BOOTSTRAP, published: dict | None = None, context: dict | None = None,
                  expect: dict | None = None, incumbent: str = "v3_ranked") -> dict:
    """The single held-out look: score `build()` (the pools and what to record with them), decide, and store the result at `path`.

    The deciding scores are those of the `ranked` pool (v3_ranked against v4-int); the `rules` pool (v3 with the section 11
    rules against v4-int) is scored first, checked against `published` (the W1 numbers) and reported beside it. `expect`
    maps keys of the recorded information to the values the preflight froze; a difference raises before anything is scored.

    Raises FileExistsError, before `build` loads anything, when `path` (the result in data/) or `committed` (the committed
    report, which guards a fresh clone without data/) exists, and LookStartedError when the marker `<path>.started` exists
    without a result. The marker is created exclusively, with the time and `context`, once v3 has reproduced the published
    numbers and before any outcome of the candidate is computed. A failure before the marker (a pool that does not reproduce
    v3's published numbers) leaves nothing behind and may be rerun; after it only a human decides. The result file is created
    exclusively, so two runs cannot both store a result.
    """
    path = Path(path)
    refuse_second_look(path, committed)
    marker = path.with_suffix(".started")
    if marker.exists():
        raise LookStartedError(f"{marker.name} exists without {path.name}: a look was started and not completed; "
                               "this needs a human decision, it is not rerun")
    pools, info = build()
    for key, value in (expect or {}).items():
        if info.get(key) != value:
            raise ValueError(f"{key} differs from the value frozen by the preflight; the look is not taken")
    context = context or {}

    def mark_started() -> None:
        record = {"started_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                  "events_sha256": info.get("events_sha256"), **context}
        with open(marker, "x", encoding="utf-8") as handle:
            handle.write(json.dumps(jsonable(record), indent=2, allow_nan=False) + "\n")

    beside = op.score_heldout(pools["rules"], boot, published, before_candidate=mark_started)
    deciding = op.score_heldout(pools["ranked"], boot, None)
    result = {**context, **info, "scores": deciding, "scores_v3_rules": beside,
              "labels": {"scores": f"v3 = {incumbent} (calibrated risk ranked, burden-matched like the candidate); decides",
                         "scores_v3_rules": "v3 = v3 with the section 11 rules and the hysteresis; reported, does not decide"},
              "decision": decide(context["stage_one"], deciding, incumbent)}
    text = json.dumps(jsonable(result), indent=2, allow_nan=False)
    with open(path, "x", encoding="utf-8") as handle:
        handle.write(text + "\n")
    return result


def run_heldout(study: dict, say=print, build: Callable = build_heldout, features_dir: Path | None = None) -> dict:
    """Stage 2: refuses a second look, any look while stage 1 has not passed, and any look without a current passed preflight;
    otherwise the one look."""
    out = output_dir(study)
    refuse_second_look(out / HELDOUT, report_path(study))
    if (out / STARTED).exists():
        raise LookStartedError(f"{STARTED} exists without {HELDOUT}: a look was started and not completed; "
                               "this needs a human decision, it is not rerun")
    dev = load_dev_results(study)
    if not dev["stage_one"]["passed"]:
        raise StageOneError("stage 1 has not passed: v4-int is not evaluated on the held-out set (spec section 3)")
    lag = current_lag(dev)
    features_dir = Path(features_dir or hd.features_dir())
    preflight = require_preflight(study, lag, features_dir)
    say("held-out look (once)")
    result = evaluate_once(out / HELDOUT, report_path(study), lambda: build(study, say, lag, features_dir), bt.BOOTSTRAP,
                           published_v3_numbers(),
                           {"created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "lag_days": lag,
                            "stage_one": dev["stage_one"], "model_dir": dev["model_dir"], "provenance": preflight["provenance"]},
                           {"events_sha256": preflight["events_sha256"]}, pool_names(study)[0])
    say(f"decision: {result['decision']['reason']}")
    say(f"wrote {hm.display_path(out / HELDOUT)}")
    return result


# ----------------------------------------------------------------------------------------------- report

def _fa(entry: dict) -> str:
    return f"{entry['value']:.4f} [{entry['lo']:.4f}, {entry['hi']:.4f}]"


def _pct(values) -> str:
    return " / ".join("n/a" if v is None else f"{100 * v:.2f}%" for v in values)


def _ties(info: dict) -> str:
    return " ; ".join(f"{c['tied_cell_days']:,} ({c['straddle']:,})" for _, c in sorted(info["cuts"].items()))


def _slide_rows(scores: dict, labels: tuple[str, str]) -> list[str]:
    rows = ["| tolerance | level | " + " | ".join(labels) + " | difference |", "|---|---|---|---|---|"]
    for tolerance in op.TOLERANCES:
        for level, label in {"1": "Watch+", "2": "Warning+", "3": "Emergency"}.items():
            a = scores[tolerance]["v3"][level]["group_hits"]
            b = scores[tolerance]["candidate"][level]["group_hits"]
            rows.append(f"| {tolerance} | {label} | {a} | {b} | {b - a:+d} |")
    return rows


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
        f"The intensity inputs lag the target day by {dev['lag_days']} IMD day(s), as the train-serve gap study declared "
        "(development samples and season panels alike). The criterion was fixed before any result "
        "(`docs/superpowers/specs/2026-11-06-aetherguard-w3-rain-intensity.md` section 3 and its amendment).", "",
        "## Stage 1: development (year-blocked CV 2007-2017)", "",
        f"The reference `C0` is the v3-live refit; it reproduces the frozen pooled OOF FA@90 to "
        f"{dev['reproduction']['abs_difference']:.1e} with the same tree count.", "",
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
    scores, beside = heldout["scores"], heldout["scores_v3_rules"]
    seasons = heldout["seasons"]
    lines += [
        "## Stage 2: held-out (pooled 2018-2025, the W1 assembly)", "",
        f"{scores['events']} events in {scores['slides']} independent slides (records within 10 km and a day are one slide). "
        "The deciding comparison is v4-int against `v3_ranked`: in each season both rank the scored cell-days by their own "
        "calibrated risk (ties by the panel's raw score) and are cut to the Watch+ / Warning+ / Emergency shares v3 realised "
        "in that season with the section 11 rules, so the comparison is at equal burden and isolates the six features. "
        "Detection is the number of independent slides with an alert at the level within tolerance (`tolerant`: 10 km, 1 "
        "day; `cell_exact`: the same cell and day).", "",
        "| tolerance | level | v3_ranked slides detected | v4-int slides detected | difference | not lower | higher |",
        "|---|---|---|---|---|---|---|",
        *[f"| {c['tolerance']} | {c['level']} | {c['v3']} | {c['candidate']} | {c['difference']:+d} | "
          f"{'yes' if c['not_lower'] else 'NO'} | {'yes' if c['higher'] else 'no'} |" for c in decision["conditions"]], "",
        "Adoption needs every row \"not lower\" and at least one \"higher\".", "",
        "All levels, independent slides detected (v3_ranked against v4-int):", "", *_slide_rows(scores, ("v3_ranked", "v4-int")), "",
        "Beside it, not deciding: v3 with the section 11 rules and the hysteresis (its own, rule-based levels at the same "
        "burden) against v4-int:", "", *_slide_rows(beside, ("v3 with rules", "v4-int")), "",
        "Alert cell-days at the matched burden, pooled, all three on the same scored cell-days (Watch+ / Warning+ / Emergency):", "",
        "| levels | alert cell-days |", "|---|---|",
        *[f"| {name} | " + " / ".join(f"{n:,}" for n in counts) + " |"
          for name, counts in heldout["pooled"]["alert_cell_days_scored"].items()],
        "| v3_rules, counted as the W1 report counts them (held levels included) | "
        + " / ".join(f"{n:,}" for n in heldout["pooled"]["alert_cell_days"]["v3_rules"]) + " |", "",
        "Burden matching per season: target (v3 with rules realised) and the realised shares of v3_ranked and v4-int, "
        "Watch+ / Warning+ / Emergency. Cell-days tied on both calibrated risk and raw score are ordered by a seeded key of "
        "(cell, day); the last two columns give, at each cut, the cell-days tied with the last one taken, and in brackets "
        "how many of them the cut leaves out (a straddled tie):", "",
        "| season | target | v3_ranked realised | v4-int realised | v3_ranked ties at the cuts | v4-int ties at the cuts |",
        "|---|---|---|---|---|---|",
        *[f"| {year} | {_pct(s['v3_realised_shares'])} | {_pct(s['v3_ranked']['realised'])} | {_pct(s['v4_int']['realised'])} | "
          f"{_ties(s['v3_ranked'])} | {_ties(s['v4_int'])} |" for year, s in seasons.items()], "",
        "Share of scored held-out cell-days with a NaN intensity input, per season (a NaN is learned as missing, never zero):", "",
        "| season | " + " | ".join(dev["added_inputs"]) + " |", "|---" * (len(dev["added_inputs"]) + 1) + "|",
        *[f"| {year} | " + " | ".join(f"{100 * s['iint_nan_share'][c]:.2f}%" for c in dev["added_inputs"]) + " |" for year, s in seasons.items()], "",
        "Ground truth after 2018 is very incomplete, so detection counts are relative (between models at equal burden), not "
        "absolute.", ""]
    return "\n".join(lines)


def write_report(study: dict, out_dir: Path | None = None, say=print, render: Callable[[dict], str] | None = None) -> dict:
    """reports/phase7_rain_intensity.{md,json} from the stored stage results. Refuses while stage 1 has passed and the look has
    not been taken: a committed report blocks the look."""
    dev = load_dev_results(study)
    held_path = output_dir(study) / HELDOUT
    if dev["stage_one"]["passed"] and not held_path.is_file():
        raise StageOneError("stage 1 passed: take the held-out look first (`heldout`); a report written before it would block it")
    heldout = json.loads(held_path.read_text(encoding="utf-8")) if held_path.is_file() else None
    decision = dev["decision"] if heldout is None else heldout["decision"]
    preflight_path = output_dir(study) / PREFLIGHT
    preflight = json.loads(preflight_path.read_text(encoding="utf-8")) if preflight_path.is_file() else None
    result = {"created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "spec": study.get("spec", "docs/superpowers/specs/2026-11-06-aetherguard-w3-rain-intensity.md"),
              "dev": {"lag_days": dev["lag_days"], "reproduction": dev["reproduction"], "candidates": dev["candidates"],
                      "added_inputs": study["candidates"][study["challenger"]]["add_increasing"],
                      **({"static_inputs": static_inputs(study)} if static_inputs(study) else {}),
                      "development": dev["development"], "seconds": dev["seconds"]},
              "comparison": dev["comparison"], "stage_one": dev["stage_one"], "heldout": heldout, "decision": decision,
              "preflight": None if preflight is None else {"passed": preflight["passed"], "checks": len(preflight["checks"]),
                                                          "events_sha256": preflight.get("events_sha256"),
                                                          "peak_memory_mb": preflight["peak_memory_mb"]}}
    out_dir = Path(out_dir or report_path(study).parent)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = study["report_stem"]
    dump_json(out_dir / f"{stem}.json", result)
    (out_dir / f"{stem}.md").write_text((render or markdown)(result), encoding="utf-8")
    say(f"wrote {hm.display_path(out_dir / stem)}.{{json,md}}")
    return result


# ------------------------------------------------------------------------------------------------- main

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("stage", choices=["dev", "seasons", "preflight", "heldout", "report"])
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--features", type=Path, default=None, help="feature store directory")
    parser.add_argument("--force", action="store_true", help="dev: overwrite earlier development results; seasons: rescore panels that exist")
    args = parser.parse_args(argv)
    study = load_study(args.config)

    def say(message: str) -> None:
        print(message, flush=True)
    if args.stage == "dev":
        run_dev(study, args.features, say, args.force)
    elif args.stage == "seasons":
        run_seasons(study, args.features, say=say, force=args.force)
    elif args.stage == "preflight":
        record = run_preflight(study, args.features, say)
        return 0 if record["passed"] else 1
    elif args.stage == "heldout":
        run_heldout(study, say, features_dir=args.features)
    else:
        write_report(study, say=say)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
