"""CLI: the single frozen evaluation of the v2 (or, with `--config configs/hazard_v3.yaml`, the v3-live) hazard model.

    python -m aetherguard.hazard.evaluate_report [--config configs/hazard.yaml] [--model data/processed/hazard/model]
                                                 [--out reports]

Refuses to run unless the model matches its freeze record (`FROZEN.json`) and no earlier test evaluation is recorded
(`--rerun` overrides the second check and is logged in the report). Everything scored here uses only frozen things:
the saved model, the baselines refitted on all development rows, and thresholds derived from out-of-fold scores in
stage 1. Nothing is tuned: refits (leave-region-out, ablations) use the frozen hyper-parameters and tree counts.
Writes reports/<evaluation_report_stem>.{md,json} (default phase3_hazard_report). `--config` evaluates a model trained
from another configuration (v3): its model directory, freeze files and report stem come from that configuration.

A model with per-region calibration (`calibration.per_region`) is evaluated as deployed: the test-set risk, its
calibration table and the deployed Watch rule use each cell's REGION calibrator, and case studies use the alert risk
thresholds of the case's region (`risk_by_region` of the card). The deployed rule is then reported at Watch only: the
same raw score maps to a different risk in each region, so it is scored as `risk - the region's Watch risk threshold`
against 0. A v3 configuration (it names a `model_dir`) is rendered by `report_live` instead of `report`.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from ..cases.score import score_case
from ..cases.series import load_case_frame
from ..config import PROJECT_ROOT
from ..manifest import sha256_file
from . import baselines as bl
from . import cv
from . import data as hd
from . import evaluate as ev
from . import freeze
from . import metrics as mt
from . import model as hm
from .jsonio import dump_json, jsonable
from .report import render_markdown
from .report_live import render_live_markdown
from .train import extra_groups_used

BASELINES = ("intensity_duration", "lhasa_style", "logistic")
REGIONS = ("himalaya", "western_ghats")
LABELS = ("watch", "plain90", "warning", "emergency")
CARD_KEY = {"watch": "watch", "plain90": "plain_recall_90", "warning": "warning", "emergency": "emergency"}
TARGET_RECALL = 0.9
EVALUATION_RECORD = "TEST_EVALUATION.json"
CASE_TABLES = {"kerala_2018": "case_kerala_2018_samples", "wayanad_2024": "case_wayanad_2024_samples"}
V1_REPORT = "phase3_hazard_report_v1.json"
V2_REPORT = "phase3_hazard_report.json"
CHALLENGERS_REPORT = "phase6_challengers.json"
LIMITS = [
    "Statistical power is low: test_2018 has 80 in-domain positive cell-days (48 Himalaya, 32 Ghats), so every "
    "interval is wide and per-region and per-baseline comparisons are mostly unresolved.",
    "The landslide inventory is partial and rain-triggered only (NASA catalogs); unlabeled landslides sit among the "
    "universe negatives, so false-alarm shares are upper bounds. The inventory's yearly recording rate varies more "
    "than 10-fold across 2007-2017 (8 positives in 2007 and 2008 against 100+ in later years).",
    "Rain is the 0.25 degree IMD gauge grid (CHIRPS 0.05 degree elsewhere) at daily resolution: no hourly "
    "intensity, so short intense bursts are not resolved.",
    "Positives below the slope floor (outside the model domain) are excluded from training and the primary metrics "
    "and counted as misses in the overall recall.",
    "Elevation (`stat_elev_mean`) is the top feature and dropping it worsened cross-validated FA@90 by more than its "
    "standard error; it may act as a location or inventory-reporting proxy. Leave-region-out (with and without "
    "elevation) is the check, and with few positives it is only indicative.",
    "Calibrated probabilities use one pooled base rate; the cross-validated per-year observed rate varied by more than "
    "10x, so the probabilities are uncertain by about a factor of two even where the ranking is good.",
    "Source-disagreement features (`src_`) were not selected; source disagreement is handled by the alert engine. The "
    "integ and corr groups were not selected, so how their features were constructed relative to the CV folds does "
    "not affect the frozen model.",
    "Labels are rain-triggered cell-days only; earthquake, construction and unknown triggers are excluded from "
    "positives and kept as buffer.",
]
LIVE_LIMITS = [
    "Statistical power is low: test_2018 has 80 in-domain positive cell-days (48 Himalaya, 32 Ghats), so every "
    "interval is wide; v3-live and v2 differ by less than those intervals, and the test year cannot separate them.",
    "test_2018 is a second look at the same year: v2 was evaluated on it (twice, the repeat disclosed in its record) "
    "and v1 before that. The v3-live model, its thresholds and its configuration were frozen before this look and "
    "nothing was tuned afterwards, but the year is not untouched. The model-selection evidence is the year-blocked "
    "cross-validation, not this test.",
    "The comparison with v2 on test_2018 is descriptive. The two models are scored on the same rows, but v2's "
    "numbers are read from its frozen report and no paired test between v2 and v3-live is made on the test year.",
    "Rain is IMERG V07 (Late run, 0.1 degree, mapped to the 0.05 degree cells), not the gauge-based IMD grid used by "
    "v2; IMERG daily totals are satellite estimates and can miss or smear short intense bursts on steep terrain.",
    "The landslide inventory is partial and rain-triggered only (NASA catalogs); unlabeled landslides sit among the "
    "universe negatives, so false-alarm shares are upper bounds. Its yearly recording rate varies more than 10-fold.",
    "Elevation (`stat_elev_mean`) is a leading feature and may act as a location or inventory-reporting proxy; "
    "leave-region-out (with and without elevation) is the check and, with few positives, only indicative.",
    "Per-region calibration changes the probabilities, not the ranking: the Watch, Warning and Emergency decisions "
    "are made on the raw score, and each region's risk thresholds are the same raw thresholds seen through its "
    "calibrator. Cross-fitted OOF calibration error is larger than the in-sample figure (see the calibration section).",
    "Operational (live) inputs differ from the training inputs (Early run for the newest day, a GFS or persisted "
    "tail for the 00-03 UTC hours); the train/live gap that causes is measured in `reports/phase6_backtest.md`, not here: "
    "every number on this page uses the training-style inputs.",
]


# ---------------------------------------------------------------------------------------- frozen context

def frozen_thresholds(card: dict, payload: dict, regional: bool = False) -> dict[str, dict[str, float]]:
    """Per scorer the OOF-derived thresholds (raw-score units; the deployed model rule uses calibrated risk).

    With per-region calibration (`regional`) the deployed rule is scored as risk minus the region's Watch risk
    threshold (`_deployed_margin`), so its only threshold is Watch, at 0."""
    raw = {name: {label: float(payload["evaluation"]["thresholds"][name][CARD_KEY[label]]["raw"]) for label in LABELS}
           for name in ("model", *BASELINES)}
    risk_levels = card["thresholds_oof"]
    raw["model_deployed"] = ({"watch": 0.0} if regional else
                             {label: float(risk_levels[CARD_KEY[label]]["risk"]) for label in LABELS})
    return raw


def reproduce_baselines(dev: hd.Development, payload: dict) -> dict:
    fitted = bl.fit_baselines(dev.samples, dev.universe)
    for name, baseline in fitted.items():
        if jsonable(baseline.params()) != payload["baseline_params_final_fit"][name]:
            raise RuntimeError(f"baseline {name} does not reproduce its frozen stage-1 fit; the inputs changed")
    return fitted


def load_test_split(directory: Path, cfg: dict, use) -> hd.SplitData:
    samples = hd.load_table(hd.SAMPLE_NAMES[hd.TEST], directory, cfg["extra_groups"], use)
    universe = hd.load_table(hd.UNIVERSE_NAMES[hd.TEST], directory, cfg["extra_groups"], use)
    return hd.split_data(hd.TEST, samples, universe)


def _risk_of(model: hm.HazardModel, raw_pair, test: hd.SplitData):
    """Calibrated risk of the scored positives and universe rows: each row by its region's calibrator when the model
    has per-region calibration (the rows carry `region`), else the pooled calibrator."""
    return (model.calibrate(raw_pair[0], test.positives)[0], model.calibrate(raw_pair[1], test.universe)[0])


def _deployed_margin(model: hm.HazardModel):
    """Per-region deployed Watch rule as a score: calibrated risk minus the Watch risk threshold of the row's region
    (a region without its own threshold uses the pooled one). `margin >= 0` is exactly `risk >= threshold`."""
    watch = model.card["alert_levels"]["watch"]
    by_region, pooled = watch["risk_by_region"], float(watch["risk"])

    def score(frame: pd.DataFrame) -> np.ndarray:
        risk = model.calibrate(model.raw_score(frame), frame)[0]
        threshold = np.array([by_region.get(region, pooled) for region in frame["region"]], dtype=np.float64)
        return risk - threshold
    return score


def _scorers(model: hm.HazardModel, baselines: dict) -> dict:
    deployed = (_deployed_margin(model) if model.region_calibrator is not None
                else (lambda frame: model.calibrate(model.raw_score(frame), frame)[0]))
    return {"model": model.raw_score, "model_deployed": deployed, **{name: b.score for name, b in baselines.items()}}


# ------------------------------------------------------------------------------------------ test sections

def buffer_sensitivity(test: hd.SplitData, raw: dict, fixed: dict) -> dict:
    """Realised recall and FA share at the frozen thresholds with buffer rows counted as negatives."""
    view = ev.build_view(test, raw, include_buffer=True)
    out = {}
    for name, scoring in view.sets.items():
        ps = np.sort(scoring.pos)[::-1]
        out[name] = {label: {"recall": scoring.recall_at(ps, t), "fa_share": scoring.fa_at(t)}
                     for label, t in fixed[name].items()}
    return out


def test_sections(test: hd.SplitData, raw: dict, model: hm.HazardModel, fixed: dict, cfg: dict) -> dict:
    risk = _risk_of(model, raw["model"], test)
    view = ev.build_view(test, raw, risk=risk)
    main = ev.evaluate_split(view, cfg, fixed_thresholds=fixed, comparators=BASELINES)
    regions = {r: ev.evaluate_split(ev.build_view(test, raw, region=r, risk=risk), cfg, fixed_thresholds=fixed,
                                    comparators=BASELINES) for r in REGIONS}
    overall = {label: {"all": ev.overall_recall(view, fixed, label, cfg),
                       **{r: ev.overall_recall(ev.build_view(test, raw, region=r), fixed, label, cfg)
                          for r in REGIONS}} for label in LABELS}
    calibration = {"all": ev.calibration_report(view, cfg),
                   **{r: ev.calibration_report(ev.build_view(test, raw, region=r, risk=risk), cfg) for r in REGIONS}}
    return {"main": main, "regions": regions, "overall_recall": overall, "calibration": calibration,
            "buffer_sensitivity": buffer_sensitivity(test, raw, fixed)}


def window_section(frame: pd.DataFrame, scorers: dict, fixed: dict, cfg: dict) -> dict:
    boot = cfg["bootstrap"]
    return {name: ev.window_detection(frame, fn(frame), fixed[name]["watch"], boot["n"], boot["seed"], boot["level"])
            for name, fn in scorers.items()}


def case_thresholds(card: dict, frame: pd.DataFrame, regional: bool) -> tuple[dict[str, float], str | None]:
    """(risk thresholds, region) of a case study. Per-region calibration needs the thresholds of the case's region, so
    the case must lie in one region (a mixed frame is an error: one risk threshold would be wrong for part of it)."""
    levels = ("watch", "warning", "emergency")
    if not regional:
        return {k: float(card["alert_levels"][k]["risk"]) for k in levels}, None
    regions = sorted(frame["region"].dropna().astype(str).unique())
    if len(regions) != 1:
        raise ValueError(f"a case study under per-region calibration must lie in one region, found {regions}")
    return {k: float(card["alert_levels"][k]["risk_by_region"][regions[0]]) for k in levels}, regions[0]


def v3_case_loader(directory: Path, cfg: dict, use):
    """Loads a case table with the extra feature groups of the configuration (`irain`, `iapi`, `inbr` for v3-live): the
    v2 case loader joins only the integ and corr groups."""
    return lambda case: hd.load_table(CASE_TABLES[case], directory, cfg["extra_groups"], use)


def case_section(model_dir: Path, card: dict, directory: Path, case_frames: dict | None, regional: bool = False,
                 loader=None) -> dict:
    """Kerala 2018 and Wayanad 2024 scored with the frozen model. A case frame comes from `case_frames`, else from
    `loader(case)` (v3: the case table with the configuration's extra groups joined), else the v2 case loader."""
    out = {}
    for case in ("kerala_2018", "wayanad_2024"):
        frame = (case_frames or {}).get(case)
        if frame is None:
            frame = loader(case) if loader else load_case_frame(case, directory)
        thresholds, region = case_thresholds(card, frame, regional)
        result = score_case(case, lambda f: hm.score_frame(f, model_dir), thresholds, frame=frame)
        entry = {"thresholds": thresholds, "metrics": result.metrics}
        if region is not None:
            entry["region"] = region
        if result.events is not None:
            entry["events"] = result.events.to_dict("records")
        if result.series is not None:
            entry["series"] = result.series.to_dict("records")
        out[case] = entry
    return out


def no_elevation_columns(cfg: dict) -> list[str]:
    """The elevation-like columns the stage-1 `exclude` candidate drops (the leave-region-out variant without them)."""
    for candidate in cfg["group_stages"][0]["candidates"]:
        if candidate.get("exclude"):
            return list(candidate["exclude"])
    raise ValueError("the configuration's first group stage has no candidate with an `exclude` list: the "
                     "leave-region-out check without elevation needs one")


def leave_region_out(dev: hd.Development, test: hd.SplitData, raw: dict, card: dict, cfg: dict, no_elevation: list[str],
                     progress=None) -> dict:
    """Frozen hyper-parameters, neg_mix and tree count refitted on ONE region's development rows (no early stopping),
    scored on the OTHER region's test_2018 rows; with and without the elevation-like columns."""
    settings, hp = cfg["training"], card["hyperparameters"]
    columns, constraints = card["columns"], [card["constraints"][c] for c in card["columns"]]
    keep = [i for i, c in enumerate(columns) if c not in no_elevation]
    variants = {"region_only": (columns, constraints),
                "region_only_no_elevation": ([columns[i] for i in keep], [constraints[i] for i in keep])}
    out = {}
    for train_region, held_out in (("himalaya", "western_ghats"), ("western_ghats", "himalaya")):
        train = hd.training_frame(dev.samples, dev.universe, card["neg_mix"], settings["universe_negatives"],
                                  cfg["seed"], regions=[train_region])
        scorers, counts = {}, hm.training_counts(train)
        for name, (cols, cons) in variants.items():
            booster, _ = hm.fit_booster(train, cols, cons, hp, cfg["seed"], settings, num_rounds=card["n_trees"])
            scorers[name] = (lambda b, c: (lambda frame: hm.predict_raw(b, frame, c, card["n_trees"])))(booster, cols)
            if progress:
                progress(f"leave-region-out {train_region} -> {held_out} ({name})")
        scored = ev.score_universe(test, scorers)
        view = ev.build_view(test, {"full_model": raw["model"], **scored}, region=held_out)
        result = ev.evaluate_split(view, cfg, reference="full_model")
        out[f"{train_region}_to_{held_out}"] = {"train_region": train_region, "held_out_region": held_out,
                                                "train_counts": counts, "n_trees": card["n_trees"],
                                                "no_elevation_columns": no_elevation, "result": result}
    return out


def ablations(dev: hd.Development, test: hd.SplitData, raw: dict, model: hm.HazardModel, payload: dict, cfg: dict,
              layout: cv.Layout, fixed: dict, progress=None) -> dict:
    """The stage-1 group candidates (and the integ / corr extensions) refitted on all development rows with the
    frozen hyper-parameters and each candidate's own cross-validated tree count; each is evaluated at ITS OWN out-of-fold
    recall-first threshold. Reporting only: nothing is selected here."""
    card, settings = model.card, cfg["training"]
    hp, neg_mix, selected = card["hyperparameters"], card["neg_mix"], card["feature_set"]["name"]
    winners = [next(r["name"] for r in payload["groups"] if r["stage"] == s and r["selected_in_stage"])
               for s in range(len(cfg["group_stages"]))]
    specs = cv.resolve_all_candidates(cfg, dev.column_map, winners)
    table = {r["name"]: r for r in payload["groups"]}
    scorers, thresholds, info = {}, {}, {}
    for spec in specs:
        name = spec["name"]
        if progress:
            progress(f"ablation {name}")
        if name == selected:
            thresholds[name] = {"watch": fixed["model"]["watch"]}
            info[name] = {"n_inputs": len(spec["columns"]), "n_trees": card["n_trees"], "frozen_model": True,
                          "oof_matches_stage1": True, "oof_recall_first": payload["evaluation"]["thresholds"]["model"][
                              "recall_first"]}
            continue
        result = cv.run_cv(dev, layout, spec["columns"], spec["constraints"], hp, neg_mix, cfg, name)
        entry = cv.operating_thresholds(layout, result.oof, None, cfg)["recall_first"]
        train = hd.training_frame(dev.samples, dev.universe, neg_mix, settings["universe_negatives"], cfg["seed"])
        booster, _ = hm.fit_booster(train, spec["columns"], spec["constraints"], hp, cfg["seed"], settings,
                                    num_rounds=result.n_trees)
        scorers[name] = (lambda b, c, n: (lambda frame: hm.predict_raw(b, frame, c, n)))(
            booster, spec["columns"], result.n_trees)
        thresholds[name] = {"watch": entry["raw"]}
        info[name] = {"n_inputs": len(spec["columns"]), "n_trees": result.n_trees, "frozen_model": False,
                      "oof_matches_stage1": bool(abs(result.pooled["fa_at_recall_0.9"] - table[name]["fa_at_90"]) < 1e-9),
                      "oof_recall_first": entry}
    variant_raw = ev.score_universe(test, {n: s for n, s in scorers.items() if n != selected})
    variant_raw[selected] = raw["model"]
    result = ev.evaluate_split(ev.build_view(test, variant_raw), cfg, reference=selected, fixed_thresholds=thresholds)
    return {"variants": info, "selected": selected, "result": result}


# --------------------------------------------------------------------------------------------- gate

def gate_assessment(result: dict) -> dict:
    main, fixed = result["test"]["main"], result["thresholds"]
    watch = main["fixed_thresholds"]["model"]["watch"]
    plain = main["fixed_thresholds"]["model"]["plain90"]
    regions = {r: result["test"]["regions"][r]["fixed_thresholds"]["model"]["watch"] for r in REGIONS}
    overall = result["test"]["overall_recall"]["watch"]["all"]["model"]
    reached = watch["recall"]["value"] >= TARGET_RECALL
    watch_card = result["card"]["alert_levels"]["watch"]
    comparisons = {}
    for name in BASELINES:
        paired = main["paired_fixed_thresholds"][name]["watch"]
        equal_recall = main["paired_fa_at_headline_recall"][name]
        comparisons[name] = {
            "fa_at_own_90_threshold_descriptive": {
                "model": main["metrics"]["model"]["fa_at_recall_0.9"], "baseline": main["metrics"][name]["fa_at_recall_0.9"],
                "baseline_minus_model": {k: equal_recall[k] for k in ("value", "lo", "hi")},
                "verdict": equal_recall["verdict"]},
            "at_frozen_watch": {"model_recall": watch["recall"], "model_fa": watch["fa_share"],
                                "baseline_recall": main["fixed_thresholds"][name]["watch"]["recall"],
                                "baseline_fa": main["fixed_thresholds"][name]["watch"]["fa_share"],
                                "fa_baseline_minus_model": paired["fa_share_baseline_minus_model"],
                                "recall_model_minus_baseline": paired["recall_model_minus_baseline"]}}
    return {"recall_first_target": {
                "target_recall": TARGET_RECALL, "watch_threshold_raw": fixed["model"]["watch"],
                "watch_threshold_risk": float(watch_card["risk"]),
                **({"watch_threshold_risk_by_region": watch_card["risk_by_region"]} if "risk_by_region" in watch_card
                   else {}), "test_recall": watch["recall"],
                "reached": bool(reached), "shortfall": 0.0 if reached else TARGET_RECALL - watch["recall"]["value"],
                "ci_contains_target": bool(watch["recall"]["lo"] <= TARGET_RECALL <= watch["recall"]["hi"]),
                "test_fa_share": watch["fa_share"], "plain90_recall": plain["recall"], "plain90_fa_share": plain["fa_share"],
                "per_region": {r: {"recall": v["recall"], "fa_share": v["fa_share"]} for r, v in regions.items()},
                "overall_recall_in_domain": overall["in_domain"],
                "overall_recall_incl_out_of_domain": overall["overall"]},
            "baseline_comparison": comparisons, "limits": LIVE_LIMITS if "variant" in result["meta"] else LIMITS}


def v1_history(reports_dir: Path) -> dict | None:
    path = reports_dir / V1_REPORT
    if not path.is_file():
        return None
    v1 = json.loads(path.read_text(encoding="utf-8"))
    target = v1["gate"]["recall_first_target"]
    return {"file": f"reports/{V1_REPORT.replace('.json', '.md')}",
            "validation_fa_at_90_model": v1["validation"]["metrics"]["model"]["fa_at_recall_0.9"],
            "test_recall_at_validation_threshold": target["test_recall"], "test_fa_share_at_that_point": target["test_fa_share"],
            "test_overall_recall": target["overall_recall_incl_out_of_domain"],
            "test_fa_at_90_own_threshold": {n: v1["test_2018"]["metrics"][n]["fa_at_recall_0.9"]
                                            for n in ("model", "intensity_duration", "lhasa_style", "logistic")},
            "test_calibration": {k: v1["calibration"]["test_2018"][k]
                                 for k in ("base_rate", "mean_predicted_risk", "ece_deciles")},
            "top_feature": next(iter(v1["feature_importance_gain"])), "n_grid_candidates": len(v1["grid"]["candidates"])}


def regional_risk_thresholds(card: dict) -> dict[str, dict[str, float]]:
    """Per alert level the risk threshold under each region's calibrator (`risk_by_region` of the card)."""
    return {label: {region: float(value) for region, value in card["alert_levels"][label]["risk_by_region"].items()}
            for label in ("watch", "warning", "emergency")}


def oof_verdict(difference: dict) -> str:
    """`better` / `worse` only when the paired 95% interval of FA@90 (v3 minus v2) lies wholly below / above zero."""
    if difference["ci_hi"] < 0:
        return "better"
    if difference["ci_lo"] > 0:
        return "worse"
    return "not_shown_better"


def v2_comparison(reports_dir: Path) -> dict:
    """What v3-live is compared with: the paired out-of-fold difference (reports/phase6_challengers.json) and v2's
    frozen test_2018 numbers (reports/phase3_hazard_report.json). Each part is None when its file is absent. The
    verdict follows spec 4.4: v3-live is `better` than v2 only if the paired interval excludes zero in its favour;
    it is `live-capable` regardless."""
    reports_dir = Path(reports_dir)
    out: dict = {"oof_paired": None, "v2_test": None, "files": []}
    challengers = reports_dir / CHALLENGERS_REPORT
    if challengers.is_file():
        diff = json.loads(challengers.read_text(encoding="utf-8"))["v3_vs_v2"]
        out["oof_paired"] = {**diff, "verdict": oof_verdict(diff)}
        out["files"].append(f"reports/{CHALLENGERS_REPORT}")
    v2 = reports_dir / V2_REPORT
    if v2.is_file():
        report = json.loads(v2.read_text(encoding="utf-8"))
        target = report["gate"]["recall_first_target"]
        out["v2_test"] = {k: target[k] for k in ("watch_threshold_raw", "test_recall", "test_fa_share", "per_region",
                                                 "plain90_recall", "plain90_fa_share", "overall_recall_in_domain",
                                                 "overall_recall_incl_out_of_domain")}
        out["v2_test"]["n_positives_in_domain"] = report["test"]["main"]["n_positives"]
        out["files"].append(f"reports/{V2_REPORT}")
    return out


def stage1_summary(payload: dict) -> dict:
    keys = ("selected_groups", "selected_grid_point", "folds", "development", "groups", "calibration")
    out = {k: payload[k] for k in keys}
    out["selected"] = {k: payload["selected"][k] for k in ("name", "n_inputs", "hp", "neg_mix", "n_trees",
                                                            "fold_best_iterations", "per_fold", "pooled")}
    out["grid_top10"] = sorted(payload["grid"], key=lambda r: (r["fa_at_90"], r["logloss"], r["index"]))[:10]
    out["evaluation"] = payload["evaluation"]
    out["feature_importance_gain"] = payload["feature_importance_gain"]
    out["monotonicity"] = payload["monotonicity"]
    out["integ_presence"] = payload["integ_presence"]
    if "calibration_regions" in payload:
        out["calibration_regions"] = payload["calibration_regions"]
    return out


# ------------------------------------------------------------------------------------------- orchestration

def run_evaluation(features_directory: Path | None = None, model_dir: Path | None = None, cfg: dict | None = None,
                   progress=None, case_frames: dict | None = None, reports_dir: Path | None = None,
                   external: dict | None = None) -> dict:
    started = time.perf_counter()
    cfg = cfg or hm.hazard_config()
    model_dir = Path(model_dir or hm.configured_model_dir(cfg))
    record = freeze.verify_freeze(model_dir, external)
    directory = Path(features_directory or hd.features_dir())
    say = progress or (lambda message: None)
    model = hm.HazardModel.load(model_dir)
    card = model.card
    payload = json.loads((model_dir / "cv_results.json").read_text(encoding="utf-8"))
    use = extra_groups_used(cfg)
    dev = hd.load_development(directory, cfg["extra_groups"], use, cfg["meta_columns"])
    baselines = reproduce_baselines(dev, payload)
    regional = model.region_calibrator is not None
    live = "model_dir" in cfg
    fixed = frozen_thresholds(card, payload, regional)
    scorers = _scorers(model, baselines)
    test = load_test_split(directory, cfg, use)
    say("scoring test_2018")
    raw = ev.score_universe(test, scorers)
    result = {"meta": {"created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                       "model_dir": hm.display_path(model_dir), "features_dir": hm.display_path(directory),
                       "model_trained_utc": card["created_utc"], "bootstrap": cfg["bootstrap"],
                       "freeze_created_utc": record["created_utc"], "freeze_sha256": record["sha256"],
                       "test_counts": {"positives_in_domain": len(test.positives),
                                       "positives_out_of_domain": test.n_out_of_domain,
                                       "positives_by_region": {r: int((test.positives["region"] == r).sum())
                                                               for r in REGIONS},
                                       "universe_negative_rows": len(test.negatives),
                                       "universe_cell_days": test.universe_sizes,
                                       "base_rates": hd.base_rates(test)}},
              "thresholds": fixed,
              "card": {k: card[k] for k in ("feature_set", "hyperparameters", "neg_mix", "n_trees", "alert_levels",
                                            "thresholds_oof", "monotone_assumptions")}}
    reports = Path(reports_dir) if reports_dir else PROJECT_ROOT / "reports"
    if live:
        result["meta"]["variant"] = "v3_live"
        result["meta"]["calibration"] = "per_region" if regional else "pooled"
        result["comparison"] = v2_comparison(reports)
    if regional:
        result["thresholds_risk_by_region"] = regional_risk_thresholds(card)
    result["protocol_history"] = v1_history(reports)
    result["stage1"] = stage1_summary(payload)
    say("test_2018 metrics and bootstrap")
    result["test"] = test_sections(test, raw, model, fixed, cfg)
    say("window 2023")
    result["window_2023"] = window_section(hd.load_table(hd.WINDOW_NAME, directory, cfg["extra_groups"], use), scorers,
                                           fixed, cfg)
    say("case studies")
    result["cases"] = case_section(model_dir, card, directory, case_frames, regional,
                                  v3_case_loader(directory, cfg, use) if live else None)
    say("leave-region-out")
    no_elevation = no_elevation_columns(cfg)
    result["leave_region_out"] = leave_region_out(dev, test, raw, card, cfg, no_elevation, say)
    say("ablations")
    layout = cv.make_layout(dev, cfg["cv"]["folds"])
    result["ablations"] = ablations(dev, test, raw, model, payload, cfg, layout, fixed, say)
    result["monotonicity"] = payload["monotonicity"]
    result["feature_importance_gain"] = card["feature_importance_gain"]
    result["gate"] = gate_assessment(result)
    result["meta"]["evaluation_seconds"] = time.perf_counter() - started
    return result


def record_evaluation(model_dir: Path, report_json: Path, rerun: bool) -> dict:
    """Append this run to TEST_EVALUATION.json (the log of test evaluations of this frozen model)."""
    path = Path(model_dir) / EVALUATION_RECORD
    runs = json.loads(path.read_text(encoding="utf-8"))["runs"] if path.is_file() else []
    runs.append({"utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "rerun": rerun,
                 "report_sha256": sha256_file(report_json)})
    dump_json(path, {"runs": runs})
    return {"runs": len(runs)}


def check_single_evaluation(model_dir: Path, rerun: bool) -> None:
    if (Path(model_dir) / EVALUATION_RECORD).is_file() and not rerun:
        raise RuntimeError(f"{EVALUATION_RECORD} exists: test_2018 was already evaluated with this frozen model; "
                           "pass --rerun only to repeat the identical evaluation after fixing a bug, and disclose it")


def render(result: dict) -> str:
    """The markdown of a result: the v3-live layout for a v3 evaluation, the protocol-v2 layout otherwise."""
    return render_live_markdown(result) if result["meta"].get("variant") == "v3_live" else render_markdown(result)


def write_report(result: dict, out_dir: Path, stem: str = hm.EVALUATION_REPORT_STEM) -> tuple[Path, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path, md_path = out_dir / f"{stem}.json", out_dir / f"{stem}.md"
    dump_json(json_path, result)
    md_path.write_text(render(result), encoding="utf-8")
    return json_path, md_path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=None, help="hazard configuration (default configs/hazard.yaml)")
    parser.add_argument("--model", type=Path, default=None,
                        help="frozen model directory (default: the configuration's model_dir, else the v2 model)")
    parser.add_argument("--features", type=Path, default=None, help="feature store directory")
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "reports", help="report output directory")
    parser.add_argument("--rerun", action="store_true", help="repeat an already recorded test evaluation (disclosed)")
    parser.add_argument("--render-only", action="store_true",
                        help="re-render the markdown from the saved JSON without evaluating anything")
    args = parser.parse_args(argv)
    cfg = hm.hazard_config(args.config)
    model_dir = Path(args.model or hm.configured_model_dir(cfg))
    stem = hm.evaluation_report_stem(cfg)
    if args.render_only:
        json_path = args.out / f"{stem}.json"
        (args.out / f"{stem}.md").write_text(render(json.loads(json_path.read_text(encoding="utf-8"))),
                                             encoding="utf-8")
        print(f"re-rendered {hm.display_path(args.out / f'{stem}.md')} from {hm.display_path(json_path)}")
        return 0
    check_single_evaluation(model_dir, args.rerun)
    result = run_evaluation(args.features, model_dir, cfg, progress=lambda m: print(m, flush=True),
                            reports_dir=args.out, external=freeze.default_external_files(args.config))
    json_path, md_path = write_report(result, args.out, stem)
    result["meta"]["test_evaluations_recorded"] = record_evaluation(model_dir, json_path, args.rerun)["runs"]
    write_report(result, args.out, stem)
    print(f"wrote {hm.display_path(md_path)} and {hm.display_path(json_path)} "
          f"in {result['meta']['evaluation_seconds']:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
