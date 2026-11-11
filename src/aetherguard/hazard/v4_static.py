"""The W5 static-susceptibility challenger v4-static, stage 1 only
(docs/superpowers/specs/2026-11-10-aetherguard-w5-static-susceptibility.md sections 3-4).

    python -m aetherguard.hazard.v4_static dev [--force]

Cross-validates the v3-live refit (it must reproduce the frozen number) and v4-static = v3-live plus the nine physical
columns of the W5 static table (the exposure pair is left out, spec amendment 2026-11-11), unconstrained, on the development years with v3's folds and seeds, and applies the pre-declared
rule: the paired-bootstrap interval of pooled OOF FA@90(v4-static) - FA@90(C0) must have its lower bound at or below 0.
The held-out set is not read here, and v4-static never takes a look of its own: a passing group goes into W6's v4.

A static value belongs to the cell the terrain statistics came from: `terrain_cell_id` where a row has one (a positive
moved to the nearest land cell), else `cell_id`, exactly as the `stat_` inputs were joined.
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import PROJECT_ROOT, data_root, load_config_file
from ..features.static_w5 import EXPOSURE_COLUMNS, GROUP, HAZARD_COLUMNS, STATIC_COLUMNS, join_static, static_table
from . import challengers as ch
from . import cv
from . import data as hd
from . import model as hm
from . import train as tr
from . import v31_challenger as vc
from . import v4_int as v4
from .jsonio import dump_json

DEFAULT_CONFIG = PROJECT_ROOT / "configs" / "hazard_v4_static.yaml"
HEADLINE = ch.HEADLINE


def load_study(path: Path | str | None = None) -> dict:
    study = load_config_file(Path(path or DEFAULT_CONFIG))
    study["base"] = hm.hazard_config(PROJECT_ROOT / study["base_config"])
    return study


def load_development(study: dict, features_dir: Path | None = None, static: pd.DataFrame | None = None) -> hd.Development:
    base = study["base"]
    root = Path(features_dir or hd.features_dir())
    extras, use = base["extra_groups"], tr.extra_groups_used(base)
    static = static_table() if static is None else static
    samples = pd.concat([hd.load_table(hd.SAMPLE_NAMES[s], root, extras, use) for s in hd.DEVELOPMENT_SPLITS], ignore_index=True)
    universe = pd.concat([hd.load_table(hd.UNIVERSE_NAMES[s], root, extras, use) for s in hd.DEVELOPMENT_SPLITS], ignore_index=True)
    column_map = {**hd.load_column_map(root, extras, use, base["meta_columns"]), **{c: GROUP for c in STATIC_COLUMNS}}
    return hd.build_development(join_static(samples, static), join_static(universe, static), column_map)


def make_candidates(study: dict, base_columns) -> dict[str, vc.Candidate]:
    """C0 (the frozen inputs and v3 constraints) and v4_static (C0 plus the nine physical static inputs, unconstrained)."""
    clash = [c for c in STATIC_COLUMNS if c in base_columns]
    if clash:
        raise ValueError(f"{clash} are already inputs of the frozen model")
    reference, challenger = study["reference"], study["challenger"]
    c0 = list(base_columns)
    constraints = hm.configured_constraints(c0, study["base"])
    return {
        reference: vc.Candidate(reference, study["candidates"][reference]["description"], c0, constraints, False),
        challenger: vc.Candidate(challenger, study["candidates"][challenger]["description"], [*c0, *HAZARD_COLUMNS],
                                 [*constraints, *[0] * len(HAZARD_COLUMNS)], False),
    }


def run_dev(study: dict, features_dir: Path | None = None, say=print, force: bool = False) -> dict:
    started = time.perf_counter()
    base, out = study["base"], data_root() / "processed" / "hazard" / study["output_dir"]
    if (out / v4.DEV_RESULTS).exists() and not force:
        raise FileExistsError(f"{out / v4.DEV_RESULTS} exists; pass --force to rerun the development stage and overwrite it")
    selected = vc.frozen_selection(study)
    dev = load_development(study, features_dir)
    layout = cv.make_layout(dev, base["cv"]["folds"])
    missing = {c: float(dev.universe[c].isna().mean()) for c in HAZARD_COLUMNS}
    say(f"development rows: {len(layout.positives)} positives, {len(layout.negatives):,} universe negatives, "
        f"{len(layout.matched)} matched negatives; static NaN share of universe rows up to {max(missing.values()):.3f}")
    candidates = make_candidates(study, selected["columns"])
    reference, challenger = study["reference"], study["challenger"]
    results, frames, reproduction = {}, {}, None
    for name in (reference, challenger):
        candidate = candidates[name]
        result = cv.run_cv(dev, layout, candidate.columns, candidate.constraints, selected["hp"], selected["neg_mix"], base, name)
        say(f"{name}: FA@90 {result.pooled[HEADLINE]:.4f}, {result.n_trees} trees, {len(candidate.columns)} inputs, {result.seconds:.0f}s")
        if name == reference:
            reproduction = v4.check_reproduction(result, selected, float(study["reproduction_tolerance"]))
            say(f"  reproduces frozen v3-live: |difference| {reproduction['abs_difference']:.2e}")
        results[name], frames[name] = result, ch.oof_frame(layout, result.oof)
        vc.save_oof(out / v4.OOF_SUBDIR, frames[name], result)
    comparison = v4.compare(frames, study)
    stage = v4.stage_one(comparison["difference"])
    stage["rule"] = stage["rule"].replace("v4_int", challenger).replace("v4-int", "v4-static")
    stage["verdict"] = stage["verdict"].replace("v4-int", "v4-static")
    say(f"stage 1: {challenger} - {reference} FA@90 {stage['difference']:+.4f} [{stage['ci'][0]:+.4f}, {stage['ci'][1]:+.4f}] "
        f"-> {'passed' if stage['passed'] else 'FAILED'} ({stage['verdict']})")
    model_dir = None
    if stage["passed"]:
        model_dir = out / v4.MODEL_SUBDIR / challenger
        model = vc.fit_final(candidates[challenger], dev, layout, results[challenger], base, v4.NO_KEYS, model_dir)
        model.card.update(protocol="v2 (year-blocked CV over 2007-2017); W5 static-susceptibility challenger, spec 2026-11-10",
                          description=f"W5 challenger {challenger}: {candidates[challenger].description}",
                          static={"group": GROUP, "inputs": HAZARD_COLUMNS, "excluded": list(EXPOSURE_COLUMNS), "constraints": "none"})
        model.save(model_dir)
        say(f"refitted {challenger} -> {hm.display_path(model_dir)}")
    payload = {
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "development": {"positives": len(layout.positives), "universe_rows": len(layout.negatives),
                        "matched_rows": len(layout.matched), "folds": layout.folds},
        "static_nan_share_universe": missing,
        "frozen_reference": hm.display_path(hm.configured_model_dir(base)), "reproduction": reproduction,
        "candidates": {n: {"description": c.description, "n_inputs": len(c.columns), "columns": c.columns,
                           "constraints": dict(zip(c.columns, c.constraints)), "n_trees": results[n].n_trees,
                           "fold_best_iterations": results[n].fold_best_iterations, "seconds": results[n].seconds}
                       for n, c in candidates.items()},
        "comparison": comparison, "stage_one": stage,
        "model_dir": None if model_dir is None else hm.display_path(model_dir),
        "seconds": time.perf_counter() - started}
    dump_json(out / v4.DEV_RESULTS, payload)
    say(f"wrote {hm.display_path(out / v4.DEV_RESULTS)} in {payload['seconds']:.0f}s")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("stage", choices=["dev"])
    parser.add_argument("--force", action="store_true", help="overwrite an existing dev_results.json")
    args = parser.parse_args(argv)
    run_dev(load_study(), force=args.force)
    return 0


if __name__ == "__main__":
    sys.exit(main())
