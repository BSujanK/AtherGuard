"""CLI: protocol-v2 training. Cross-validated selection, OOF calibration and thresholds, final refit, ensemble, save.

    python -m aetherguard.hazard.train [--config configs/hazard.yaml] [--out data/processed/hazard/model]
                                       [--features data/processed/features]

`--config` selects the configuration (v3: configs/hazard_v3.yaml); the model directory defaults to the configuration's
`model_dir` under data/processed/hazard (else `model`) and the stage-1 report stem to its `cv_report_stem`. With
`calibration.per_region` it also fits and saves `calibrator_regions.json` (per-region calibrators, pooled fallback).

Reads only the development rows (train + validation sample / universe feature tables, and the extra feature groups'
files when a candidate uses them); test_2018, the window and the case tables are never opened. Writes model.txt,
ensemble/member_*.txt, calibrator.json, card.json and cv_results.json to the output directory, and the stage-1
cross-validation report to reports/<cv_report_stem>.{md,json} (default phase3_hazard_cv_report).
"""
from __future__ import annotations

import argparse
import dataclasses
import time
from datetime import datetime, timezone
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
import sklearn

from ..config import PROJECT_ROOT
from ..manifest import sha256_file
from . import baselines as bl
from . import cv
from . import data as hd
from . import metrics as mt
from . import model as hm
from .cv_report import render_cv_markdown
from .jsonio import dump_json

BASELINE_NAMES = ("intensity_duration", "lhasa_style", "logistic")


def extra_groups_used(cfg: dict) -> list[str]:
    return [g for g in cv.all_groups(cfg) if g in cfg["extra_groups"]]


def input_checksums(directory: Path, cfg: dict) -> dict:
    names = [f"{hd.SAMPLE_NAMES[s]}_features.parquet" for s in hd.DEVELOPMENT_SPLITS]
    names += [f"{hd.UNIVERSE_NAMES[s]}_features.parquet" for s in hd.DEVELOPMENT_SPLITS] + ["feature_columns.json"]
    paths = [directory / n for n in names]
    for group in extra_groups_used(cfg):
        spec = cfg["extra_groups"][group]
        sub = directory / spec["subdir"]
        paths += [sub / spec["columns_file"], sub / spec["manifest_file"]]
        paths += [sub / f"{hd.SAMPLE_NAMES[s]}_{spec['suffix']}.parquet" for s in hd.DEVELOPMENT_SPLITS]
        paths += [sub / f"{hd.UNIVERSE_NAMES[s]}_{spec['suffix']}.parquet" for s in hd.DEVELOPMENT_SPLITS]
    return {hm.display_path(p): sha256_file(p) for p in paths}


def _summaries(point: dict, samples: dict, level: float) -> dict:
    return {k: mt.summarize(v, samples[k], level) for k, v in point.items() if k in samples}


def evaluate_oofs(layout: cv.Layout, oofs: dict[str, cv.Oof], calibrator, cfg: dict) -> dict:
    """Pooled OOF metrics with CIs, own-OOF thresholds (plain and recall-first) with the recall / FA they realise,
    and paired FA@90 differences between the model and each baseline."""
    ops, level = cfg["operating_points"], cfg["bootstrap"]["level"]
    thresholds = {name: cv.operating_thresholds(layout, oof, calibrator if name == "model" else None, cfg)
                  for name, oof in oofs.items()}
    fixed = {name: {"plain": t["plain_recall_90"]["raw"], "recall_first": t["recall_first"]["raw"]}
             for name, t in thresholds.items()}
    boots = cv.bootstrap_oofs(layout, oofs, cfg, fixed)
    key = f"fa_at_recall_{ops['headline_recall']}"
    out = {"metrics": {}, "thresholds": thresholds, "paired_fa_at_90_vs_model": {}}
    for name, oof in oofs.items():
        point = oof.score_set(layout).point(ops["recalls"], ops["fa_shares"])
        entry = {"pooled": _summaries(point, boots[name], level), "at_thresholds": {}}
        for label in ("plain", "recall_first"):
            scoring = oof.score_set(layout)
            entry["at_thresholds"][label] = {
                "threshold": fixed[name][label],
                "recall": mt.summarize(scoring.recall_at(np.sort(scoring.pos)[::-1], fixed[name][label]),
                                       boots[name][f"fixed_recall_{label}"], level),
                "fa_share": mt.summarize(scoring.fa_at(fixed[name][label]), boots[name][f"fixed_fa_{label}"], level)}
        out["metrics"][name] = entry
    model_point = oofs["model"].score_set(layout).point([ops["headline_recall"]], [])[key]
    for name in oofs:
        if name == "model":
            continue
        point = oofs[name].score_set(layout).point([ops["headline_recall"]], [])[key]
        diff = mt.paired_difference(boots["model"][key], boots[name][key], model_point, point, level)
        diff["verdict"] = {"a_better": "model better", "b_better": f"{name} better", "tie": "tie"}[
            mt.verdict(diff["lo"], diff["hi"])]
        out["paired_fa_at_90_vs_model"][name] = diff
    return out


def _grid_rows(results: list[cv.CVResult], selected: cv.CVResult) -> list[dict]:
    rows = []
    for i, r in enumerate(results):
        rows.append({"index": i, "name": r.name, "selected": r is selected, **r.hp, "neg_mix": r.neg_mix,
                     "n_trees": r.n_trees, "fold_best_iterations": r.fold_best_iterations,
                     "fa_at_90": r.pooled["fa_at_recall_0.9"], "pr_auc": r.pooled["pr_auc"],
                     "logloss": r.pooled["logloss"], "seconds": r.seconds})
    return rows


def train(features_directory: Path | None = None, out_dir: Path | None = None, cfg: dict | None = None,
          progress=None, report_dir: Path | None = None) -> hm.HazardModel:
    started = time.perf_counter()
    directory = Path(features_directory or hd.features_dir())
    cfg = cfg or hm.hazard_config()
    per_region = bool(cfg["calibration"].get("per_region", False))
    say = progress or (lambda message: None)
    dev = hd.load_development(directory, cfg["extra_groups"], extra_groups_used(cfg), cfg["meta_columns"])
    layout = cv.make_layout(dev, cfg["cv"]["folds"])
    base_columns = hd.model_columns(cfg["groups"], dev.column_map)
    base_constraints = hm.configured_constraints(base_columns, cfg)
    say(f"development rows: {len(layout.positives)} positives, {len(layout.matched)} matched negatives, "
        f"{len(layout.negatives):,} universe negatives; {len(layout.folds)} folds")

    stage_one = [cv.resolve_candidate(c, None, cfg, dev.column_map) for c in cfg["group_stages"][0]["candidates"]]
    grid_name = next((c["name"] for c in stage_one if c["columns"] == base_columns), None)  # the candidate the grid ran on
    grid_results, selected_grid = cv.run_grid(
        dev, layout, base_columns, base_constraints, cfg,
        lambda r: say(f"  grid {r.name}: FA@90={r.pooled['fa_at_recall_0.9']:.4f} logloss={r.pooled['logloss']:.4f} "
                      f"trees={r.n_trees} ({r.seconds:.0f}s)"))
    say(f"selected grid point: {selected_grid.name} {selected_grid.hp} {selected_grid.neg_mix}")
    final_cv, group_table, by_name = cv.select_groups(
        dev, layout, cfg, selected_grid.hp, selected_grid.neg_mix, dev.column_map,
        known={grid_name: dataclasses.replace(selected_grid, name=grid_name)} if grid_name else {},
        progress=lambda stage, name, r: say(f"  groups stage {stage} {name}: FA@90={r.pooled['fa_at_recall_0.9']:.4f} "
                                            f"({r.seconds:.0f}s)"))
    say(f"selected feature set: {final_cv.name} ({len(final_cv.columns)} inputs, {final_cv.n_trees} trees)")

    calibrator = cv.fit_calibrator(layout, final_cv.oof)
    regions = sorted(layout.negatives["region"].unique())
    min_positives = cfg["calibration"]["min_region_positives"] if per_region else None
    region_calibrator = cv.fit_region_calibrator(layout, final_cv.oof, regions, min_positives) if per_region else None
    say("baselines under the same protocol")
    baseline_oofs = cv.run_cv_baselines(dev, layout, cfg)
    say("bootstrap of the OOF metrics")
    evaluation = evaluate_oofs(layout, {"model": final_cv.oof, **baseline_oofs}, region_calibrator or calibrator, cfg)
    calibration = cv.calibration_summary(layout, final_cv.oof, calibrator, cfg)
    region_calibration = (cv.region_calibration_summary(layout, final_cv.oof, regions, min_positives, cfg)
                          if per_region else None)
    integ_names = [r["name"] for r in group_table if "integ" in r["groups"]]
    presence = None
    if integ_names:
        incumbent = next(r["name"] for r in group_table if r["stage"] == 0 and r["selected_in_stage"])
        presence = cv.presence_comparison(layout, {n: by_name[n].oof for n in [incumbent] + integ_names},
                                          cfg["presence_column"], cfg)

    say("final refit on all development rows and bootstrap ensemble")
    settings, hp = cfg["training"], final_cv.hp
    train_rows = hd.training_frame(dev.samples, dev.universe, final_cv.neg_mix, settings["universe_negatives"],
                                   cfg["seed"])
    booster, _ = hm.fit_booster(train_rows, final_cv.columns, final_cv.constraints, hp, cfg["seed"], settings,
                                num_rounds=final_cv.n_trees)
    members = hm.fit_ensemble(train_rows, final_cv.columns, final_cv.constraints, hp, final_cv.n_trees,
                              cfg["ensemble"]["members"], cfg["ensemble"]["seed"], settings)
    model = hm.HazardModel(final_cv.columns, final_cv.constraints, booster, final_cv.n_trees, members, calibrator, {},
                           region_calibrator)
    background = layout.negatives
    monotonicity = hm.monotonicity_check(booster, model.columns, model.constraints, background, model.best_iteration)
    seconds = time.perf_counter() - started
    final_baselines = bl.fit_baselines(dev.samples, dev.universe)
    payload = {
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "protocol": "v2: year-blocked CV over 2007-2017; v1 (validation-split selection) is disclosed history",
        "folds": layout.folds,
        "development": {"positives_in_domain": len(layout.positives), "positives_out_of_domain": dev.n_out_of_domain,
                        "matched_negatives": len(layout.matched), "universe_negative_rows": len(layout.negatives),
                        "universe_cell_days": dev.universe_sizes,
                        "positives_by_year": {int(y): int(n) for y, n in
                                              layout.positives.groupby("year").size().items()},
                        "base_rate_per_100k_cell_days": 1e5 * len(layout.positives) / layout.neg_weight.sum()},
        "grid": _grid_rows(grid_results, selected_grid),
        "selected_grid_point": selected_grid.name,
        "groups": group_table, "selected_groups": final_cv.name,
        "selected": final_cv.summary() | {"columns": final_cv.columns},
        "evaluation": evaluation, "calibration": calibration,
        **({"calibration_regions": region_calibration} if per_region else {}),
        "integ_presence": presence,
        "monotonicity": monotonicity,
        "feature_importance_gain": hm.feature_importance(booster, model.columns, model.best_iteration),
        "baseline_params_final_fit": {n: b.params() for n, b in final_baselines.items()},
        "train_seconds": seconds,
    }
    model.card = {
        "created_utc": payload["created_utc"], "protocol": payload["protocol"],
        "description": "Stage-2 landslide hazard model (LightGBM, monotone, cross-validated, OOF-calibrated at the "
                       "true base rate)",
        "monotone_assumptions": {"increasing": cfg["monotone"]["increasing"],
                                 "decreasing": cfg["monotone"]["decreasing"],
                                 "note": "rain_days_since_10mm is constrained decreasing by assumption: more days "
                                         "since a 10 mm day never raises risk"},
        "feature_set": {"name": final_cv.name,
                        "meta_columns_never_inputs": cfg["meta_columns"]},
        "hyperparameters": hp, "neg_mix": final_cv.neg_mix, "n_trees": final_cv.n_trees,
        "folds": layout.folds, "fold_best_iterations": final_cv.fold_best_iterations,
        "selection": {"metric": "pooled out-of-fold false-alarm share at 90% recall (weighted universe), tie-break "
                                "pooled OOF log-loss; groups: simpler candidate unless the more complex one is lower "
                                "by more than its bootstrap SE",
                      "grid": payload["grid"], "groups": group_table},
        "training": {"counts": hm.training_counts(train_rows),
                     "universe_negatives_drawn": settings["universe_negatives"],
                     "weights": "positives 1; matched negatives 1; universe negatives n_matched / n_drawn each (when "
                                "neg_mix=matched_plus_universe)"},
        "seeds": {"model": cfg["seed"], "ensemble_base": cfg["ensemble"]["seed"],
                  "ensemble_members": cfg["ensemble"]["members"]},
        "base_rates": payload["development"],
        "alert_levels": {k: evaluation["thresholds"]["model"][k] for k in ("watch", "warning", "emergency")},
        "thresholds_oof": evaluation["thresholds"]["model"],
        "calibration": {"fit_on": "pooled out-of-fold positives + year-weighted universe negatives",
                        "n_thresholds": int(len(calibrator.x)),
                        "ece_deciles_crossfit": calibration["crossfit"]["ece_deciles"],
                        **(_region_calibration_card(region_calibration, region_calibrator) if per_region else {})},
        "oof_pooled": evaluation["metrics"]["model"]["pooled"],
        "ensemble_spread_oof": _ensemble_spread(model, layout),
        "feature_importance_gain": payload["feature_importance_gain"],
        "monotonicity_all_hold": all(c["holds"] for c in monotonicity.values()),
        "inputs": input_checksums(directory, cfg),
        "versions": {"lightgbm": lgb.__version__, "scikit_learn": sklearn.__version__, "numpy": np.__version__,
                     "pandas": pd.__version__},
        "train_seconds": seconds,
    }
    target = Path(out_dir or hm.configured_model_dir(cfg))
    model.save(target)
    dump_json(target / "cv_results.json", payload)
    reports = Path(report_dir) if report_dir is not None else PROJECT_ROOT / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    stem = hm.cv_report_stem(cfg)
    dump_json(reports / f"{stem}.json", payload)
    (reports / f"{stem}.md").write_text(render_cv_markdown(payload), encoding="utf-8")
    return model


def _region_calibration_card(summary: dict, region_calibrator) -> dict:
    """Card entries for per-region calibration. Alert thresholds stay on the raw score scale; the `risk` stored next to
    each (alert_levels, thresholds_oof) is the POOLED calibrator's value (used for regions without their own
    calibrator and for frames without a region column) and `risk_by_region` the value under each region's calibrator."""
    return {"per_region": True, "file": hm.REGION_CALIBRATOR_FILE,
            "min_region_positives": region_calibrator.min_positives,
            "regions_with_own_calibrator": sorted(region_calibrator.by_region),
            "regions": {r: {"positives": e["positives"], "calibrator": e["calibrator"],
                            "ece_deciles_crossfit_per_region": e["crossfit_per_region"]["ece_deciles"],
                            "ece_deciles_crossfit_pooled": e["crossfit_pooled"]["ece_deciles"]}
                        for r, e in summary["regions"].items()},
            "threshold_risk": "alert thresholds are raw scores, independent of calibration; `risk` beside each "
                              "threshold is the pooled calibrator's value, `risk_by_region` the per-region values"}


def _ensemble_spread(model: hm.HazardModel, layout: cv.Layout, n: int = 20000) -> dict:
    """Ensemble spread on a fixed random sample of the OOF universe rows and all positives (in-sample for the members:
    descriptive only, not a coverage claim)."""
    rng = np.random.default_rng(0)
    rows = rng.choice(len(layout.negatives), min(n, len(layout.negatives)), replace=False)
    sample = pd.concat([layout.positives, layout.negatives.iloc[np.sort(rows)]], ignore_index=True)
    raw = model.member_raw_scores(sample)
    members, _ = model.calibrate(raw, sample)
    return {"mean_std_calibrated": float(members.std(axis=1).mean()),
            "mean_std_raw": float(raw.std(axis=1).mean()), "n_rows": len(sample)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=None, help="hazard configuration (default configs/hazard.yaml)")
    parser.add_argument("--out", type=Path, default=None,
                        help="model output directory (default: the configuration's model_dir, else the v2 model)")
    parser.add_argument("--features", type=Path, default=None, help="feature store directory")
    args = parser.parse_args(argv)
    cfg = hm.hazard_config(args.config)
    model = train(args.features, args.out, cfg, progress=lambda m: print(m, flush=True))
    print(f"saved to {hm.display_path(args.out or hm.configured_model_dir(cfg))} in {model.card['train_seconds']:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
