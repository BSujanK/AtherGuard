"""The v3.1 challenger study (spec section 15): label audit, physical-constraint candidates, pre-declared selection.

    python -m aetherguard.hazard.v31_challenger labels    # Step 1: the label audit (no model)
    python -m aetherguard.hazard.v31_challenger dev       # Steps 2-3: C0..C3 cross-validated, metrics, selection
    python -m aetherguard.hazard.v31_challenger heldout   # Step 4: the selected candidate on test_2018 (once); nothing when none was selected
    python -m aetherguard.hazard.v31_challenger replay [--candidates C1 C2 C3]   # offline replay of the stored live days
    python -m aetherguard.hazard.v31_challenger report    # reports/phase6_v31_challenger.{md,json}

Configuration: configs/hazard_v31_challenger.yaml; the frozen v3-live configuration is its `base_config`, so the folds, seeds,
hyper-parameters, ensemble, calibration and alert-level derivation are those of v3-live. The development stage reads only the
2007-2017 development rows; test_2018 is first opened by `heldout`, for the selected candidate.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from ..config import PROJECT_ROOT, data_root, load_config_file
from . import challengers as ch
from . import cv
from . import data as hd
from . import metrics as mt
from . import model as hm
from . import train as tr
from . import v31_labels as vl
from .jsonio import dump_json

DEFAULT_CONFIG = PROJECT_ROOT / "configs" / "hazard_v31_challenger.yaml"
LABEL_TABLE = "label_audit.parquet"
LABEL_SUMMARY = "label_audit.json"
DEV_RESULTS = "dev_results.json"
SELECTION = "selection.json"
OOF_SUBDIR = "oof"
MODEL_SUBDIR = "models"
HEADLINE = ch.HEADLINE
LEVELS = ("watch", "warning", "emergency")
WARNING = "warning"
SHARES = ("recall", "fa_share", "cell_days", "low_share", "lowrain_share", "precision_per_1000")
NO_CHALLENGER = "no challenger adopted"


# ---------------------------------------------------------------------------------------------- study

def load_study(path: Path | str | None = None) -> dict:
    """The study configuration with the frozen v3-live configuration under `base`."""
    study = load_config_file(Path(path or DEFAULT_CONFIG))
    study["base"] = hm.hazard_config(PROJECT_ROOT / study["base_config"])
    return study


def output_dir(study: dict) -> Path:
    name = study["output_dir"]
    if Path(name).name != name or name in (".", ".."):
        raise ValueError(f"output_dir must be a plain directory name under data/processed/hazard, got {name!r}")
    return data_root() / "processed" / "hazard" / name


def frozen_selection(study: dict) -> dict:
    """The `selected` entry of the frozen v3-live `cv_results.json`: the inputs, hyper-parameters, negative mix, tree count and
    pooled FA@90 that C0 must reproduce."""
    path = hm.configured_model_dir(study["base"]) / "cv_results.json"
    return json.loads(path.read_text(encoding="utf-8"))["selected"]


# ------------------------------------------------------------------------------------------- candidates

@dataclasses.dataclass(frozen=True)
class Candidate:
    name: str
    description: str
    columns: list[str]
    constraints: list[int]
    drop_implausible: bool


def candidate_constraints(columns, spec: dict, base_cfg: dict) -> list[int]:
    """The v3 monotone vector of `columns` with the candidate's `increasing_extra` inputs set to +1 (an input the v3
    configuration already constrains is an error: the candidate would not be what it says)."""
    constraints = hm.configured_constraints(columns, base_cfg)
    for name in spec.get("increasing_extra", []):
        if name not in columns:
            raise ValueError(f"increasing_extra names {name!r}, which is not an input of the candidate")
        index = list(columns).index(name)
        if constraints[index] != 0:
            raise ValueError(f"{name!r} is already constrained by the v3 configuration")
        constraints[index] = 1
    return constraints


def make_candidates(study: dict, base_columns) -> dict[str, Candidate]:
    out = {}
    for name, spec in study["candidates"].items():
        unknown = [c for c in spec.get("exclude", []) if c not in base_columns]
        if unknown:
            raise ValueError(f"candidate {name}: excluded inputs {unknown} are not inputs of the frozen model")
        columns = [c for c in base_columns if c not in spec.get("exclude", [])]
        out[name] = Candidate(name, spec["description"], columns, candidate_constraints(columns, spec, study["base"]),
                              bool(spec.get("drop_implausible_positives", False)))
    if study["reference"] not in out:
        raise ValueError(f"the reference candidate {study['reference']!r} is not defined")
    return out


def without_positives(dev: hd.Development, keys: pd.DataFrame) -> hd.Development:
    """`dev` minus the positive sample rows whose (cell_id, date) is in `keys`; the universe, matched negatives and
    everything the layout is built from stay, so the cross-validation scores the original rows."""
    samples = dev.samples
    pair = pd.MultiIndex.from_arrays([samples["cell_id"], samples["date"]])
    drop = pair.isin(pd.MultiIndex.from_arrays([keys["cell_id"], keys["date"]])) & (samples["kind"] == "positive").to_numpy()
    return dataclasses.replace(dev, samples=samples[~drop].reset_index(drop=True))


def positives_dropped(dev: hd.Development, keys: pd.DataFrame) -> int:
    """How many in-domain development positives `without_positives` removes from the training rows."""
    return int(len(dev.positives) - len(without_positives(dev, keys).positives))


def run_candidate(candidate: Candidate, dev: hd.Development, layout: cv.Layout, selected: dict, base_cfg: dict,
                  implausible: pd.DataFrame) -> cv.CVResult:
    """`cv.run_cv` of one candidate at the frozen v3 hyper-parameters and negative mix. Candidates that drop positives from
    training are fitted on the filtered development rows and scored on the unfiltered `layout`."""
    training = without_positives(dev, implausible) if candidate.drop_implausible else dev
    return cv.run_cv(training, layout, candidate.columns, candidate.constraints, selected["hp"], selected["neg_mix"],
                     base_cfg, candidate.name)


# ----------------------------------------------------------------------------------- alert-level statistics

@dataclasses.dataclass(frozen=True)
class Population:
    """One scoring of the positives and the weighted universe negatives with the terrain flags of the study."""
    pos_score: np.ndarray
    neg_score: np.ndarray
    neg_weight: np.ndarray
    pos_low: np.ndarray
    neg_low: np.ndarray
    pos_lowrain: np.ndarray
    neg_lowrain: np.ndarray
    pos_region: np.ndarray
    neg_region: np.ndarray


def terrain_flags(frame: pd.DataFrame, study: dict) -> tuple[np.ndarray, np.ndarray]:
    """(low terrain, low rain) per row of a layout frame."""
    rule = vl.LabelRule.from_config(study)
    rain = frame[study["low_rain_column"]].to_numpy(dtype=np.float64)
    with np.errstate(invalid="ignore"):
        lowrain = rain < float(study["low_rain_mm"])
    return vl.low_terrain(frame, rule), lowrain


def population(layout: cv.Layout, oof: cv.Oof, study: dict) -> Population:
    pos_low, pos_lowrain = terrain_flags(layout.positives, study)
    neg_low, neg_lowrain = terrain_flags(layout.negatives, study)
    return Population(oof.pos, oof.neg, layout.neg_weight, pos_low, neg_low, pos_lowrain, neg_lowrain,
                      layout.positives["region"].to_numpy(), layout.negatives["region"].to_numpy())


def _safe_ratio(numerator, denominator):
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(np.asarray(denominator) > 0, np.asarray(numerator) / np.asarray(denominator), np.nan)


def level_statistics(pop: Population, threshold: float, region: str | None = None) -> dict:
    """`alert_statistics` of the alert level at raw `threshold` (an alert is score >= threshold)."""
    return alert_statistics(pop, pop.pos_score >= threshold, pop.neg_score >= threshold, region)


def alert_statistics(pop: Population, p_alert: np.ndarray, n_alert: np.ndarray, region: str | None = None) -> dict:
    """The statistics of an alert level given as flags on the positives (`p_alert`) and the universe rows (`n_alert`),
    optionally within one region: recall, false-alarm share, the alerted cell-days (alerted universe weight plus alerted
    positives), the share of them on low-terrain cells and with a low 3-day rain, the events per 1,000 alerted cell-days, the
    alert rate on low-terrain cells against the rest, and (descriptive) the events per 1,000 alerted cell-days and the base
    events per 1,000 cell-days on low-terrain cells against the rest."""
    p_in = np.ones(len(pop.pos_score), dtype=bool) if region is None else pop.pos_region == region
    n_in = np.ones(len(pop.neg_score), dtype=bool) if region is None else pop.neg_region == region
    p_alert, n_alert = p_in & p_alert, n_in & n_alert
    weight = pop.neg_weight
    hits, w_alert = float(p_alert.sum()), float(weight[n_alert].sum())
    cell_days = hits + w_alert
    low_days = float((p_alert & pop.pos_low).sum() + weight[n_alert & pop.neg_low].sum())
    lowrain_days = float((p_alert & pop.pos_lowrain).sum() + weight[n_alert & pop.neg_lowrain].sum())
    low_pop = float((p_in & pop.pos_low).sum() + weight[n_in & pop.neg_low].sum())
    other_pop = float((p_in & ~pop.pos_low).sum() + weight[n_in & ~pop.neg_low].sum())
    return {"events": int(hits), "recall": float(_safe_ratio(hits, p_in.sum())),
            "fa_share": float(_safe_ratio(w_alert, weight[n_in].sum())), "cell_days": cell_days,
            "low_cell_days": low_days, "low_share": float(_safe_ratio(low_days, cell_days)),
            "lowrain_share": float(_safe_ratio(lowrain_days, cell_days)),
            "precision_per_1000": float(1000.0 * _safe_ratio(hits, cell_days)),
            "low_alert_rate": float(_safe_ratio(low_days, low_pop)),
            "other_alert_rate": float(_safe_ratio(cell_days - low_days, other_pop)),
            "low_precision_per_1000": float(1000.0 * _safe_ratio((p_alert & pop.pos_low).sum(), low_days)),
            "other_precision_per_1000": float(1000.0 * _safe_ratio((p_alert & ~pop.pos_low).sum(), cell_days - low_days)),
            "low_base_events_per_1000": float(1000.0 * _safe_ratio((p_in & pop.pos_low).sum(), low_pop)),
            "other_base_events_per_1000": float(1000.0 * _safe_ratio((p_in & ~pop.pos_low).sum(), other_pop))}


def bootstrap_level_statistics(pops: dict[str, Population], thresholds: dict[str, float], strata: np.ndarray,
                               n_boot: int, seed: int) -> dict[str, dict[str, np.ndarray]]:
    """`bootstrap_alert_statistics` of the alert level at one raw threshold per scoring (an alert is score >= threshold)."""
    alerts = {name: (pop.pos_score >= thresholds[name], pop.neg_score >= thresholds[name]) for name, pop in pops.items()}
    return bootstrap_alert_statistics(pops, alerts, strata, n_boot, seed)


def bootstrap_alert_statistics(pops: dict[str, Population], alerts: dict[str, tuple[np.ndarray, np.ndarray]],
                               strata: np.ndarray, n_boot: int, seed: int) -> dict[str, dict[str, np.ndarray]]:
    """Bootstrap samples of `SHARES` for an alert level given as (positive flags, universe flags) per scoring, with the
    resampling of `metrics.bootstrap_metrics` (positives iid as events; universe rows iid within each stratum; ONE resample
    per draw for all scorings, so differences between them are paired)."""
    first = next(iter(pops.values()))
    weight, n_pos, n_neg = first.neg_weight, len(first.pos_score), len(first.neg_weight)
    groups = [np.flatnonzero(strata == s) for s in np.unique(strata)]
    total = weight.sum()
    masks = {}
    for name, pop in pops.items():
        p_alert, n_alert = alerts[name]
        masks[name] = (np.column_stack([n_alert, n_alert & pop.neg_low, n_alert & pop.neg_lowrain]).astype(np.float64),
                       np.column_stack([p_alert, p_alert & pop.pos_low, p_alert & pop.pos_lowrain]).astype(np.float64))
    out = {name: {key: np.empty(n_boot) for key in SHARES} for name in pops}
    rng = np.random.default_rng(seed)
    for b in range(n_boot):
        pos_mult = np.bincount(rng.integers(0, n_pos, n_pos), minlength=n_pos).astype(np.float64)
        neg_mult = np.zeros(n_neg)
        for index in groups:
            neg_mult[index] = np.bincount(rng.integers(0, len(index), len(index)), minlength=len(index))
        weighted = weight * neg_mult
        for name, (neg_mask, pos_mask) in masks.items():
            w_alert, w_low, w_lowrain = weighted @ neg_mask
            hits, h_low, h_lowrain = pos_mult @ pos_mask
            days = hits + w_alert
            sample = out[name]
            sample["recall"][b] = hits / n_pos
            sample["fa_share"][b] = w_alert / total
            sample["cell_days"][b] = days
            sample["low_share"][b] = (h_low + w_low) / days if days > 0 else np.nan
            sample["lowrain_share"][b] = (h_lowrain + w_lowrain) / days if days > 0 else np.nan
            sample["precision_per_1000"][b] = 1000.0 * hits / days if days > 0 else np.nan
    return out


def interval(samples, level: float) -> dict:
    samples = np.asarray(samples, dtype=np.float64)
    samples = samples[np.isfinite(samples)]
    if not len(samples):
        return {"lo": None, "hi": None, "se": None}
    lo, hi = mt.confidence_interval(samples, level)
    return {"lo": lo, "hi": hi, "se": mt.bootstrap_se(samples) if len(samples) > 1 else None}


# ------------------------------------------------------------------------------------------ calibration

def region_crossfit_ece(layout: cv.Layout, oof: cv.Oof, regions, min_positives: int, deciles: int) -> dict:
    """Cross-fitted ECE (and reliability deciles) of the per-region calibrated OOF risk over all positives and universe rows."""
    from . import calibration as cal
    risk_pos, risk_neg = cv.crossfit_region_risk(layout, oof, regions, min_positives)
    risk = np.r_[risk_pos, risk_neg]
    labels = np.r_[np.ones(len(risk_pos)), np.zeros(len(risk_neg))]
    weights = np.r_[np.ones(len(risk_pos)), layout.neg_weight]
    table = cal.reliability_table(risk, labels, weights, cal.decile_edges(deciles))
    return {"ece_deciles": cal.expected_calibration_error(table), "mean_predicted": float(np.average(risk, weights=weights)),
            "base_rate": float(len(risk_pos) / layout.neg_weight.sum()), "deciles": table}


# ------------------------------------------------------------------------------------------- evaluation

def derive_levels(layout: cv.Layout, oof: cv.Oof, base_cfg: dict):
    """(region calibrator, thresholds) of one candidate's OOF scores, derived as v3-live's were (`train.train`)."""
    regions = sorted(layout.negatives["region"].unique())
    calibrator = cv.fit_region_calibrator(layout, oof, regions, base_cfg["calibration"]["min_region_positives"])
    return calibrator, cv.operating_thresholds(layout, oof, calibrator, base_cfg)


def evaluate_candidates(layout: cv.Layout, frames: dict[str, pd.DataFrame], results: dict[str, cv.CVResult], study: dict,
                        say=print) -> dict:
    """All development metrics of the candidates (module doc, spec 15.4): FA@90 and its paired difference to the reference,
    the levels re-derived per candidate, the alert statistics with bootstrap intervals, recall at the reference's raw
    thresholds, calibration."""
    base, reference = study["base"], study["reference"]
    boot, level = base["bootstrap"], base["bootstrap"]["level"]
    names = list(frames)
    pairs = [(n, reference) for n in names if n != reference]
    say("paired FA@90 bootstrap")
    paired = ch.paired_fa_differences(frames, pairs, boot["n"], boot["seed"], level)
    oofs = {n: ch.oof_scores(f) for n, f in frames.items()}
    pops = {n: population(layout, oofs[n], study) for n in names}
    derived = {n: derive_levels(layout, oofs[n], base) for n in names}
    own = {n: {lv: derived[n][1][lv]["raw"] for lv in LEVELS} for n in names}
    say("alert-level bootstrap")
    boots = {lv: bootstrap_level_statistics(pops, {n: own[n][lv] for n in names}, layout.strata, boot["n"], boot["seed"])
             for lv in LEVELS}
    regions = sorted(layout.negatives["region"].unique())
    candidates = {}
    for name in names:
        calibrator, thresholds = derived[name]
        entry = {
            "n_inputs": len(results[name].columns), "n_trees": results[name].n_trees,
            "fold_best_iterations": results[name].fold_best_iterations, "seconds": results[name].seconds,
            "fa_at_90": {"value": paired["metrics"][name][HEADLINE]["value"], "lo": paired["metrics"][name][HEADLINE]["lo"],
                         "hi": paired["metrics"][name][HEADLINE]["hi"], "se": paired["metrics"][name][HEADLINE]["se"]},
            "thresholds": thresholds, "levels": {}, "at_reference_thresholds": {}, "by_region_warning": {},
            "ece": {"crossfit_per_region": region_crossfit_ece(layout, oofs[name], regions,
                                                               base["calibration"]["min_region_positives"],
                                                               base["calibration"]["deciles"]),
                    "crossfit_pooled": cv.calibration_summary(layout, oofs[name], cv.fit_calibrator(layout, oofs[name]),
                                                              base)["crossfit"]},
            "pr_auc": paired["metrics"][name]["pr_auc"]["value"]}
        if name != reference:
            entry["fa_diff_vs_reference"] = paired["differences"][f"{name}-{reference}"]
        for lv in LEVELS:
            point = level_statistics(pops[name], own[name][lv])
            entry["levels"][lv] = {**point, "raw_threshold": own[name][lv],
                                   "bootstrap": {k: interval(boots[lv][name][k], level) for k in SHARES}}
            ref_raw = derived[reference][1][lv]["raw"]
            entry["at_reference_thresholds"][lv] = {**level_statistics(pops[name], ref_raw), "raw_threshold": ref_raw}
        for region in regions:
            entry["by_region_warning"][region] = level_statistics(pops[name], own[name][WARNING], region)
        candidates[name] = entry
    for name in names:
        if name != reference:
            diff = boots[WARNING][name]["low_share"] - boots[WARNING][reference]["low_share"]
            candidates[name]["low_share_diff_vs_reference"] = {
                "value": candidates[name]["levels"][WARNING]["low_share"]
                - candidates[reference]["levels"][WARNING]["low_share"], **interval(diff, level)}
    return {"reference": reference, "bootstrap": {"n": boot["n"], "seed": boot["seed"], "level": level},
            "candidates": candidates}


# ------------------------------------------------------------------------------------------- selection

def select(evaluation: dict, study: dict) -> dict:
    """The pre-declared selection of spec 15.5 from `evaluate_candidates`: eligible when the paired FA@90 interval against the
    reference does not lie wholly above 0 and the Warning+ low-terrain share is below the reference's; the eligible
    candidate with the lowest share wins, ties by `tie_order`; none eligible -> NO_CHALLENGER."""
    reference = evaluation["reference"]
    base_share = evaluation["candidates"][reference]["levels"][WARNING]["low_share"]
    rows = []
    for name in study["tie_order"]:
        entry = evaluation["candidates"][name]
        diff = entry["fa_diff_vs_reference"]
        share = entry["levels"][WARNING]["low_share"]
        not_worse = bool(diff["ci_lo"] <= 0)
        lower = bool(share < base_share)
        rows.append({"candidate": name, "fa_at_90": entry["fa_at_90"]["value"], "fa_difference": diff["point_difference"],
                     "fa_difference_ci": [diff["ci_lo"], diff["ci_hi"]], "not_worse_than_reference": not_worse,
                     "warning_low_share": share, "lower_low_share": lower, "eligible": not_worse and lower})
    eligible = [r for r in rows if r["eligible"]]
    order = {name: i for i, name in enumerate(study["tie_order"])}
    chosen = min(eligible, key=lambda r: (r["warning_low_share"], order[r["candidate"]]))["candidate"] if eligible else None
    return {"rule": "spec 15.5", "reference": reference, "reference_warning_low_share": base_share, "candidates": rows,
            "selected": chosen, "result": chosen or NO_CHALLENGER}


# ---------------------------------------------------------------------------------------------- final fit

def fit_final(candidate: Candidate, dev: hd.Development, layout: cv.Layout, result: cv.CVResult, base_cfg: dict,
              implausible: pd.DataFrame, directory: Path) -> hm.HazardModel:
    """Refit a candidate on all development rows exactly as `train.train` does (booster, bootstrap ensemble, per-region
    calibrator and thresholds from the candidate's OOF scores, card), and save it to `directory`."""
    started = time.perf_counter()
    training = without_positives(dev, implausible) if candidate.drop_implausible else dev
    settings = base_cfg["training"]
    rows = hd.training_frame(training.samples, training.universe, result.neg_mix, settings["universe_negatives"],
                             base_cfg["seed"])
    booster, _ = hm.fit_booster(rows, candidate.columns, candidate.constraints, result.hp, base_cfg["seed"], settings,
                                num_rounds=result.n_trees)
    members = hm.fit_ensemble(rows, candidate.columns, candidate.constraints, result.hp, result.n_trees,
                              base_cfg["ensemble"]["members"], base_cfg["ensemble"]["seed"], settings)
    regions = sorted(layout.negatives["region"].unique())
    calibrator = cv.fit_calibrator(layout, result.oof)
    region_calibrator, thresholds = derive_levels(layout, result.oof, base_cfg)
    model = hm.HazardModel(candidate.columns, candidate.constraints, booster, result.n_trees, members, calibrator, {},
                           region_calibrator)
    model.card = {
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "protocol": "v2 (year-blocked CV over 2007-2017); v3.1 challenger, spec section 15",
        "description": f"v3.1 challenger {candidate.name}: {candidate.description}",
        "candidate": candidate.name, "feature_set": {"name": candidate.name, "meta_columns_never_inputs": base_cfg["meta_columns"]},
        "hyperparameters": result.hp, "neg_mix": result.neg_mix, "n_trees": result.n_trees, "folds": layout.folds,
        "fold_best_iterations": result.fold_best_iterations, "frozen_reference": hm.display_path(hm.configured_model_dir(base_cfg)),
        "monotone_assumptions": {"increasing": base_cfg["monotone"]["increasing"], "decreasing": base_cfg["monotone"]["decreasing"]},
        "training": {"counts": hm.training_counts(rows),
                     "positives_dropped": int(len(layout.positives) - len(hd.in_domain_positives(training.samples)))},
        "seeds": {"model": base_cfg["seed"], "ensemble_base": base_cfg["ensemble"]["seed"],
                  "ensemble_members": base_cfg["ensemble"]["members"]},
        "alert_levels": {k: thresholds[k] for k in LEVELS}, "thresholds_oof": thresholds,
        "calibration": {"per_region": True, "min_region_positives": region_calibrator.min_positives,
                        "regions_with_own_calibrator": sorted(region_calibrator.by_region)},
        "versions": {"lightgbm": lgb.__version__}, "train_seconds": time.perf_counter() - started}
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    model.save(directory)
    return model


# ----------------------------------------------------------------------------------------------- stages

def run_labels(study: dict, features_dir: Path | None = None, say=print) -> dict:
    """Step 1: audit the positives of the label store against the raw catalogs; writes the cell-day table and the summary."""
    root = data_root()
    events = pd.read_parquet(root / "processed" / "labels" / "events.parquet")
    catalog = vl.read_catalog_records(root / "raw" / "manual")
    table, summary = vl.audit(vl.load_positives(features_dir), events, catalog, study)
    out = output_dir(study)
    out.mkdir(parents=True, exist_ok=True)
    table.to_parquet(out / LABEL_TABLE, index=False)
    dump_json(out / LABEL_SUMMARY, summary)
    say(f"{summary['positive_cell_days']} positive cell-days, {summary['low_terrain']} on low terrain, "
        f"{summary['implausible']} implausible; wrote {hm.display_path(out / LABEL_SUMMARY)}")
    return summary


def check_reproduction(result: cv.CVResult, selected: dict) -> dict:
    """The reference candidate must reproduce the frozen v3-live pooled OOF FA@90 and tree count (spec 15.3)."""
    record = {"recomputed_fa_at_90": result.pooled[HEADLINE], "reported_fa_at_90": selected["pooled"][HEADLINE],
              "abs_difference": abs(result.pooled[HEADLINE] - selected["pooled"][HEADLINE]), "n_trees": result.n_trees,
              "reported_n_trees": selected["n_trees"]}
    if record["abs_difference"] > ch.REPRODUCTION_TOLERANCE or result.n_trees != selected["n_trees"]:
        raise ch.ReproductionError(
            f"{result.name}: recomputed FA@90 {record['recomputed_fa_at_90']:.6f} / {result.n_trees} trees versus the frozen "
            f"v3-live {record['reported_fa_at_90']:.6f} / {selected['n_trees']} trees")
    return record


def save_oof(directory: Path, frame: pd.DataFrame, result: cv.CVResult) -> None:
    ch.write_oof(Path(directory) / f"oof_{result.name}.parquet", frame)
    dump_json(Path(directory) / f"oof_{result.name}.json", {
        "name": result.name, "columns": result.columns, "constraints": result.constraints, "hp": result.hp,
        "neg_mix": result.neg_mix, "n_trees": result.n_trees, "fold_best_iterations": result.fold_best_iterations,
        "seconds": result.seconds, "pooled": result.pooled})


def load_result(directory: Path, name: str) -> cv.CVResult:
    """A saved candidate as a CVResult (OOF scores and settings; no per-fold metrics)."""
    meta = json.loads((Path(directory) / f"oof_{name}.json").read_text(encoding="utf-8"))
    oof = ch.oof_scores(ch.read_oof(Path(directory) / f"oof_{name}.parquet"))
    return cv.CVResult(name, meta["columns"], meta["constraints"], meta["hp"], meta["neg_mix"], meta["n_trees"],
                       meta["fold_best_iterations"], oof, meta["pooled"], [], meta["seconds"])


def run_dev(study: dict, features_dir: Path | None = None, say=print) -> dict:
    """Steps 2-3: cross-validate C0..C3, derive and evaluate their alert levels, apply the pre-declared selection, and refit
    the selected candidate (development rows only; test_2018 is not read)."""
    started = time.perf_counter()
    base = study["base"]
    out = output_dir(study)
    if not (out / LABEL_TABLE).is_file():
        raise FileNotFoundError(f"{out / LABEL_TABLE} not found; run the `labels` stage first (spec 15.2)")
    implausible = vl.implausible_keys(pd.read_parquet(out / LABEL_TABLE))
    selected = frozen_selection(study)
    dev = hd.load_development(features_dir, base["extra_groups"], tr.extra_groups_used(base), base["meta_columns"])
    layout = cv.make_layout(dev, base["cv"]["folds"])
    say(f"development rows: {len(layout.positives)} positives, {len(layout.negatives):,} universe negatives, "
        f"{len(layout.matched)} matched negatives; {len(implausible)} implausible positives in the audit")
    candidates = make_candidates(study, selected["columns"])
    results, frames, reproduction = {}, {}, None
    for name, candidate in candidates.items():
        result = run_candidate(candidate, dev, layout, selected, base, implausible)
        say(f"{name}: FA@90 {result.pooled[HEADLINE]:.4f}, {result.n_trees} trees, {len(candidate.columns)} inputs, "
            f"{result.seconds:.0f}s")
        if name == study["reference"]:
            reproduction = check_reproduction(result, selected)
            say(f"  reproduces frozen v3-live: |difference| {reproduction['abs_difference']:.2e}")
        results[name] = result
        frames[name] = ch.oof_frame(layout, result.oof)
        save_oof(out / OOF_SUBDIR, frames[name], result)
    order = [study["reference"], *[c for c in candidates if c != study["reference"]]]
    evaluation = evaluate_candidates(layout, {n: frames[n] for n in order}, results, study, say)
    selection = select(evaluation, study)
    say(f"selection (spec 15.5): {selection['result']}")
    model_dir = None
    if selection["selected"]:
        model_dir = out / MODEL_SUBDIR / selection["selected"]
        fit_final(candidates[selection["selected"]], dev, layout, results[selection["selected"]], base, implausible,
                  model_dir)
        say(f"refitted {selection['selected']} -> {hm.display_path(model_dir)}")
    payload = {
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "development": {"positives": len(layout.positives), "universe_rows": len(layout.negatives),
                        "matched_rows": len(layout.matched), "folds": layout.folds,
                        "implausible_positives_in_audit": int(len(implausible))},
        "frozen_reference": hm.display_path(hm.configured_model_dir(base)), "reproduction": reproduction,
        "candidates": {n: {"description": c.description, "n_inputs": len(c.columns), "columns": c.columns,
                           "constraints": dict(zip(c.columns, c.constraints)),
                           "drop_implausible_positives": c.drop_implausible,
                           "positives_dropped": positives_dropped(dev, implausible) if c.drop_implausible else 0}
                       for n, c in candidates.items()},
        "evaluation": evaluation, "selection": selection,
        "model_dir": None if model_dir is None else hm.display_path(model_dir),
        "seconds": time.perf_counter() - started}
    dump_json(out / DEV_RESULTS, payload)
    dump_json(out / SELECTION, {"created_utc": payload["created_utc"], **selection})
    say(f"wrote {hm.display_path(out / DEV_RESULTS)} in {payload['seconds']:.0f}s")
    return payload


def fit_missing_models(study: dict, names: list[str], features_dir: Path | None = None, say=print) -> list[Path]:
    """Refit the named candidates that have no model under `models/` yet, from their saved OOF scores (development rows only)."""
    base, out = study["base"], output_dir(study)
    todo = [n for n in names if not (out / MODEL_SUBDIR / n / hm.CARD_FILE).is_file()]
    if todo:
        selected = frozen_selection(study)
        dev = hd.load_development(features_dir, base["extra_groups"], tr.extra_groups_used(base), base["meta_columns"])
        layout = cv.make_layout(dev, base["cv"]["folds"])
        implausible = vl.implausible_keys(pd.read_parquet(out / LABEL_TABLE))
        candidates = make_candidates(study, selected["columns"])
        for name in todo:
            fit_final(candidates[name], dev, layout, load_result(out / OOF_SUBDIR, name), base, implausible,
                      out / MODEL_SUBDIR / name)
            say(f"refitted {name} -> {hm.display_path(out / MODEL_SUBDIR / name)}")
    return [out / MODEL_SUBDIR / n for n in names]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("stage", choices=["labels", "dev", "heldout", "replay", "report"])
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--features", type=Path, default=None, help="feature store directory")
    parser.add_argument("--candidates", nargs="*", default=None, help="replay: candidates to replay (default: the challengers)")
    args = parser.parse_args(argv)
    study = load_study(args.config)

    def say(message: str) -> None:
        print(message, flush=True)
    if args.stage == "labels":
        run_labels(study, args.features, say)
    elif args.stage == "dev":
        run_dev(study, args.features, say)
    elif args.stage == "heldout":
        from . import v31_eval
        v31_eval.run_heldout(study, args.features, say)
    elif args.stage == "replay":
        from . import v31_eval
        names = args.candidates or [c for c in study["candidates"] if c != study["reference"]]
        fit_missing_models(study, names, args.features, say)
        v31_eval.run_replay(study, names, say)
    else:
        from . import v31_report
        v31_report.write_report(study, say)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
