"""Markdown rendering of the protocol-v2 hazard report (the JSON is the source of truth)."""
from __future__ import annotations

from . import cv_report as cr
from .tables import _ci, _label, _num, _ordered, _pct, _table

SCORER_ORDER = ("model", "model_deployed", "intensity_duration", "lhasa_style", "logistic")
LABEL_TITLES = {"watch": "Watch (recall-first)", "plain90": "plain 90% recall", "warning": "Warning (75%)",
                "emergency": "Emergency (50%)"}
EXTRA_LABELS = {"model_deployed": "hazard model, deployed rule (risk threshold)"}


def _name(name: str) -> str:
    return EXTRA_LABELS.get(name) or _label(name)


def _history_section(history: dict | None) -> list[str]:
    out = ["## 0. Protocol history", "",
           "**v1** (`reports/phase3_hazard_report_v1.md`, kept) chose hyper-parameters among 48 candidates on the "
           "2016-17 validation split, early-stopped on a noisy false-alarm metric, and used that same split for the "
           "isotonic calibration AND the 90%-recall threshold. It was evaluated on test_2018, and the result was "
           "poor: a model that tied every baseline, a recall shortfall at the validation threshold, an over-confident "
           "calibration, and `stat_elev_mean` as the top feature.", ""]
    if history:
        recall, fa, cal = history["test_recall_at_validation_threshold"], history["test_fa_share_at_that_point"], history[
            "test_calibration"]
        out += [f"- v1 test_2018 recall at its validation-chosen 90% threshold: {_pct(recall)} (target 90%), FA share "
                f"{_pct(fa)}; overall recall incl. out-of-domain {_pct(history['test_overall_recall'])}.",
                "- v1 test FA@90 (own threshold): " + "; ".join(
                    f"{_name(n)} {_pct(v)}" for n, v in history["test_fa_at_90_own_threshold"].items()) + ".",
                f"- v1 test calibration: mean predicted {_num(cal['mean_predicted_risk'] * 1e5, 3)} vs observed "
                f"{_num(cal['base_rate'] * 1e5, 3)} per 100k cell-days (ECE {_num(cal['ece_deciles'] * 1e5, 3)} per 100k).",
                f"- v1 validation FA@90 (in-sample selection): {_pct(history['validation_fa_at_90_model'])}; top feature "
                f"`{history['top_feature']}`.", ""]
    out += ["**v2** (`docs/phase3-design.md`, Protocol v2) was adopted AFTER the v1 test result had been seen, partly "
            "because of it. This is stated plainly: test_2018 has therefore been looked at once under v1, and v2 is "
            "not a clean first look at it. What v2 does is remove the specific reuse that made v1 optimistic: every "
            "choice (hyper-parameters, number of trees, feature groups, calibration, thresholds) is made by year-blocked "
            "cross-validation on 2007-2017 (train + validation), the model and thresholds were frozen "
            "(checksummed `FROZEN.json`) before any test scoring, and test_2018 is evaluated once with nothing changed "
            "afterwards.", ""]
    return out


def _gate_section(gate: dict) -> list[str]:
    target = gate["recall_first_target"]
    status = ("REACHED" if target["reached"] else
              f"NOT reached (shortfall {100 * target['shortfall']:.1f} points"
              + ("; the 95% CI still contains 90%" if target["ci_contains_target"] else "; the 95% CI excludes 90%") + ")")
    out = ["## 1. Gate assessment", "",
           f"**Recall-first target** (at least {target['target_recall']:.0%} of in-domain test_2018 events at the "
           f"stage-1 Watch threshold, raw score {_num(target['watch_threshold_raw'], 5)} = calibrated risk "
           f"{_num(target['watch_threshold_risk'], 9)}): {status}.", "",
           f"- test recall {_pct(target['test_recall'])}; false-alarm share at that point {_pct(target['test_fa_share'])} "
           f"(universe non-buffer cell-days alerted)",
           f"- plain 90% OOF threshold: recall {_pct(target['plain90_recall'])}, FA share {_pct(target['plain90_fa_share'])}",
           "- per region: " + "; ".join(f"{r}: recall {_pct(v['recall'])}, FA {_pct(v['fa_share'])}"
                                       for r, v in target["per_region"].items()),
           f"- overall recall counting out-of-domain positives as misses: "
           f"{_pct(target['overall_recall_incl_out_of_domain'])} (in-domain {_pct(target['overall_recall_in_domain'])})",
           "", "**Model versus baselines** (paired bootstrap, each scorer at its own frozen Watch threshold; the equal-recall "
           "column re-picks each scorer's threshold on the test labels and is descriptive only):", ""]
    rows = []
    for name, c in gate["baseline_comparison"].items():
        w, d = c["at_frozen_watch"], c["fa_at_own_90_threshold_descriptive"]
        rows.append([_name(name), _pct(w["model_recall"]), _pct(w["baseline_recall"]),
                     _ci(w["recall_model_minus_baseline"]), _pct(w["model_fa"]), _pct(w["baseline_fa"]),
                     _ci(w["fa_baseline_minus_model"]), _ci(d["baseline_minus_model"]), d["verdict"]])
    out += [_table(["baseline", "model recall", "baseline recall", "recall: model minus baseline", "model FA",
                    "baseline FA", "FA: baseline minus model", "equal-recall FA@90: baseline minus model", "verdict"],
                   rows), "",
            "Verdict is read from the equal-recall FA@90 interval: `model better` / `<baseline> better` only when the 95% "
            "interval excludes 0, otherwise `tie`. Intervals that include 0 mean test_2018 cannot separate the scorers.", ""]
    if gate["limits"]:
        out += ["**Limits**", ""] + [f"- {item}" for item in gate["limits"]] + [""]
    return out


def _threshold_section(result: dict) -> list[str]:
    fixed = result["thresholds"]
    rows = [[_name(name)] + [_num(fixed[name].get(label), 5) for label in ("watch", "plain90", "warning", "emergency")]
            for name in _ordered(fixed, SCORER_ORDER)]
    return ["## 3. Frozen thresholds", "",
            "Derived in stage 1 from each scorer's own pooled out-of-fold scores (Watch = recall-first: highest "
            "threshold whose bootstrap 5th-percentile OOF recall is at least 90%; Warning = OOF recall 75%; Emergency "
            "= OOF recall 50%). Raw-score units, except the deployed rule which alerts on calibrated risk >= the risk "
            "threshold (same ranking, but isotonic plateaus make it alert slightly more).", "",
            _table(["scorer", "Watch", "plain 90%", "Warning", "Emergency"], rows), ""]


def _fixed_rows(split: dict) -> list[list[str]]:
    rows = []
    for name in _ordered(split["fixed_thresholds"], SCORER_ORDER):
        for label, entry in split["fixed_thresholds"][name].items():
            rows.append([_name(name), LABEL_TITLES[label], _pct(entry["recall"]), _pct(entry["fa_share"])])
    return rows


def _test_section(test: dict) -> list[str]:
    main = test["main"]
    out = ["## 4. test_2018 at the frozen thresholds", "",
           f"{main['n_positives']} in-domain positive cell-days ({main['n_out_of_domain_positives']} more below the slope "
           f"floor), {main['n_negative_rows']:,} universe negative rows. Realised recall (positives resampled as events) "
           "and FA share (weighted share of non-buffer universe cell-days alerted), 95% bootstrap CIs; no threshold was "
           "re-picked on test.", "",
           _table(["scorer", "threshold", "recall [95% CI]", "FA share [95% CI]"], _fixed_rows(main)), "",
           "Paired differences at the Watch thresholds (model minus / minus model, positive favours the model):", ""]
    rows = []
    for name, labels in main["paired_fixed_thresholds"].items():
        for label in ("watch", "plain90", "warning", "emergency"):
            entry = labels[label]
            rows.append([_name(name), LABEL_TITLES[label], _ci(entry["recall_model_minus_baseline"]),
                         _ci(entry["fa_share_baseline_minus_model"])])
    out += [_table(["baseline", "threshold", "recall: model minus baseline", "FA: baseline minus model"], rows), "",
            "### Buffer rows counted as negatives (sensitivity)", "",
            _table(["scorer", "threshold", "recall", "FA share, buffer excluded", "FA share, buffer included"],
                   [[_name(n), LABEL_TITLES[label], _pct(main["fixed_thresholds"][n][label]["recall"]),
                     _pct(main["fixed_thresholds"][n][label]["fa_share"]),
                     f"{100 * test['buffer_sensitivity'][n][label]['fa_share']:.1f}%"]
                    for n in _ordered(main["fixed_thresholds"], SCORER_ORDER) for label in ("watch", "plain90")
                    if label in main["fixed_thresholds"][n]]), "",
            "### Per region", ""]
    for region, entry in test["regions"].items():
        out += [f"**{region}** ({entry['n_positives']} positives)"
                + (f" - WARNING: {entry['warning']}" if entry["warning"] else ""), "",
                _table(["scorer", "threshold", "recall [95% CI]", "FA share [95% CI]"],
                       [r for r in _fixed_rows(entry) if r[1].startswith(("Watch", "plain"))]), ""]
    out += ["### Overall recall (out-of-domain positives count as misses)", ""]
    rows = []
    for label in ("watch", "plain90"):
        for scope, by_scorer in test["overall_recall"][label].items():
            for name in _ordered(by_scorer, SCORER_ORDER):
                rows.append([LABEL_TITLES[label], scope, _name(name), _pct(by_scorer[name]["in_domain"]),
                             _pct(by_scorer[name]["overall"])])
    out += [_table(["threshold", "scope", "scorer", "in-domain recall", "overall recall"], rows), "",
            "### Descriptive: metrics with thresholds re-picked on test (not an operating result)", "",
            "These choose each scorer's threshold from the test labels themselves; they compare ranking quality at equal "
            "recall or equal alert share. Weighted PR-AUC sits near the base rate for every scorer and its interval is "
            "very wide: read it with caution.", ""]
    rows = []
    for name in _ordered(main["metrics"], SCORER_ORDER):
        m = main["metrics"][name]
        rows.append([_name(name), _pct(m["fa_at_recall_0.8"]), _pct(m["fa_at_recall_0.9"]), _pct(m["fa_at_recall_0.95"]),
                     _pct(m["recall_at_fa_0.01"]), _pct(m["recall_at_fa_0.05"]), _ci(m["pr_auc"], 5)])
    out += [_table(["scorer", "FA @ 80% recall", "FA @ 90% recall", "FA @ 95% recall", "recall @ FA 1%",
                    "recall @ FA 5%", "PR-AUC"], rows), ""]
    rows = [[_name(n), _ci({"value": d["value"], "lo": d["lo"], "hi": d["hi"]}), d["verdict"]]
            for n, d in main["paired_fa_at_headline_recall"].items()]
    out += ["Paired equal-recall FA@90 (baseline minus model):", "",
            _table(["baseline", "difference [95% CI]", "verdict"], rows), ""]
    return out


def _calibration_section(test: dict, stage1: dict) -> list[str]:
    cal = test["calibration"]
    rows = [[scope, _num(c["base_rate"] * 1e5, 3), _num(c["mean_predicted_risk"] * 1e5, 3), _num(c["ece_deciles"] * 1e5, 3),
             _num(c["ece_deciles_relative_to_base_rate"], 3)] for scope, c in cal.items()]
    out = ["## 5. Calibration on test_2018", "",
           "Calibrated probability that a cell-day has a landslide, at the test year's operating base rate; per 100k "
           "cell-days. Stage-1 cross-fitted calibration over-predicted by "
           f"{100 * (stage1['calibration']['crossfit']['mean_predicted'] / stage1['calibration']['base_rate'] - 1):.0f}% "
           "and varied by more than 10x across years (the inventory's yearly recording rate), so a factor-of-two "
           "uncertainty on the probabilities is expected and a single test year cannot narrow it.", "",
           _table(["scope", "observed base rate", "mean predicted", "ECE (deciles)", "ECE / base rate"], rows), ""]
    for scope in ("all",):
        tail = cal[scope]["tail_bins"]
        out += ["Reliability, risk tail bins (low to high), per 100k cell-days:", "",
                _table(["bin", "population", "positives", "mean predicted", "observed"],
                       [[str(r["bin"]), f"{100 * r['population_share']:.2f}%", str(r["positives"]),
                         _num(r["mean_risk"] * 1e5, 3), _num(r["observed_rate"] * 1e5, 3)] for r in tail]), "",
                "Reliability by deciles of risk:", "",
                _table(["decile", "population", "positives", "mean predicted", "observed"],
                       [[str(r["bin"]), f"{100 * r['population_share']:.2f}%", str(r["positives"]),
                         _num(r["mean_risk"] * 1e5, 3), _num(r["observed_rate"] * 1e5, 3)]
                        for r in cal[scope]["deciles"]]), ""]
    return out


def _window_section(window: dict) -> list[str]:
    rows = []
    for name in _ordered(window, SCORER_ORDER):
        w = window[name]
        rows.append([_name(name), _num(w["threshold"], 5), f"{w['detection']['hits']}/{w['detection']['n']}",
                     _pct(w["detection"]), f"{w['control_any_alert']['hits']}/{w['control_any_alert']['n']}",
                     _pct(w["control_any_alert"]), f"{100 * w['control_cell_day_alert_share']:.1f}%"])
    return ["## 6. 2023 India window test (Watch threshold)", "",
            "A window-positive cell is detected if the maximum score over the 46 window days of any of its 3x3 neighbourhood "
            "cells reaches the Watch threshold. Control cells are scored on their own cell only, so their any-alert share "
            "is an upper bound on false alarms: the inventory is partial and a control cell has one cell's chance where a "
            "detection has nine.", "",
            _table(["scorer", "Watch threshold", "detected", "detection share [95% CI]", "controls alerted",
                    "control any-alert share [95% CI]", "control cell-days alerted"], rows), ""]


def _cases_section(cases: dict) -> list[str]:
    out = ["## 7. Case studies (scored only; deployed rule: calibrated risk against the card's alert levels)", ""]
    kerala = cases["kerala_2018"]
    m = kerala["metrics"]
    area = m["alerted_area"]
    t = kerala["thresholds"]
    out += [f"Thresholds (calibrated risk): Watch {_num(t['watch'], 9)}, Warning {_num(t['warning'], 9)}, "
            f"Emergency {_num(t['emergency'], 9)}.", "", "### Kerala 2018 (2018-08-01 to 08-20)", "",
            f"- {m['n_events']} positive cell-days: detected on the event day (cell or a neighbour at Watch+) "
            f"{m['detected_on_event_day']}/{m['n_events']}; own cell at Watch+ {m['own_cell_at_watch']}; detected within "
            f"7 days before or on the event day {m['detected_within_7d']}.",
            f"- median first-alert lead {_num(m['median_first_alert_lead_days'], 1)} days; median consecutive Watch+ days "
            f"before the event {_num(m['median_alert_days_before'], 1)}.",
            f"- alerted area: mean Watch+ share {100 * area['mean_watch_share']:.1f}% of {area['cells_in_case']:,} cells "
            f"(max {100 * area['max_watch_share']:.1f}%), mean Warning+ share {100 * area['mean_warning_share']:.1f}%.", ""]
    events = kerala["events"]
    out += [_table(["cell", "date", "own level", "detected", "alert days before", "first-alert lead (days)"],
                   [[str(e["cell_id"]), str(e["date"])[:10], _num(e["own_level"], 0), str(e["detected"]),
                     str(e["alert_days_before"]), _num(e["first_alert_lead_days"], 0)] for e in events]), "",
            "Alerted area per day:", "",
            _table(["date", "cells", "Watch+ cells", "Watch+ share", "Warning+ share", "Emergency cells"],
                   [[d["date"], str(d["cells"]), str(d["watch_cells"]), f"{100 * d['watch_share']:.1f}%",
                     f"{100 * d['warning_share']:.1f}%", str(d["emergency_cells"])] for d in area["per_day"]]), ""]
    way = cases["wayanad_2024"]
    wm = way["metrics"]
    out += ["### Wayanad 2024 (no NASA label: qualitative replay)", "",
            f"Focus cell {wm['focus_cell']} ({wm['focus_distance_km']:.1f} km from the focus point), "
            f"{wm['cells_within_radius']} cells within {wm['radius_km']:.0f} km, {wm['box_cells']} cells in the box. "
            f"First Watch+ day: focus {wm['first_watch_plus']['focus']}, within 10 km {wm['first_watch_plus']['within_10km']}, "
            f"box {wm['first_watch_plus']['box']}. First Warning+ day: focus {wm['first_warning_plus']['focus']}, within "
            f"10 km {wm['first_warning_plus']['within_10km']}, box {wm['first_warning_plus']['box']}. Peak risk within 10 km "
            f"{_num(wm['peak_near_risk'] * 1e5, 2)} per 100k on {wm['peak_near_date']}.", "",
            _table(["date", "focus risk /100k", "focus level", "max within 10 km /100k", "level", "box max /100k",
                    "box level", "box cells at Watch+"],
                   [[str(r["date"])[:10], _num(r["focus_risk"] * 1e5, 2), str(r["focus_level"]),
                     _num(r["near_max_risk"] * 1e5, 2), str(r["near_max_level"]), _num(r["box_max_risk"] * 1e5, 2),
                     str(r["box_max_level"]), f"{r['box_cells_watch_plus']}/{r['box_cells']}"] for r in way["series"]]),
            ""]
    return out


def _lro_section(lro: dict) -> list[str]:
    out = ["## 8. Leave-region-out (elevation-as-proxy check)", "",
           "Frozen hyper-parameters, neg_mix and tree count, refitted on ONE region's development rows (no early stopping) "
           "and scored on the other region's test_2018 rows; the full model (trained on both regions) is the "
           "reference. Thresholds are re-picked on the test labels per scorer, so this compares ranking only. "
           "`no_elevation` drops the elevation-like columns "
           f"({', '.join(next(iter(lro.values()))['no_elevation_columns'])}). Warnings flag fewer than 100 positives.", ""]
    for entry in lro.values():
        result = entry["result"]
        out += [f"**{entry['train_region']} development rows -> {entry['held_out_region']} test_2018** "
                f"({result['n_positives']} positives)" + (f" - WARNING: {result['warning']}" if result["warning"] else ""), ""]
        rows = []
        for name in _ordered(result["metrics"], ("full_model", "region_only", "region_only_no_elevation")):
            m = result["metrics"][name]
            paired = result["paired_fa_at_headline_recall"].get(name)
            rows.append([_label(name) if name in ("full_model",) else name, _pct(m["fa_at_recall_0.9"]),
                         _pct(m["recall_at_fa_0.05"]), _ci(m["pr_auc"], 5),
                         "-" if not paired else _ci({"value": paired["value"], "lo": paired["lo"], "hi": paired["hi"]})
                         + f" ({paired['verdict'].replace('model better', 'full model better')})"])
        out += [_table(["scorer", "FA @ 90% recall", "recall @ FA 5%", "PR-AUC", "FA@90: scorer minus full model"], rows), ""]
    return out


def _ablation_section(ab: dict) -> list[str]:
    result = ab["result"]
    out = ["## 9. Ablations on test_2018 (reporting only; nothing selected)", "",
           "Each stage-1 group candidate is refitted on all development rows with the frozen hyper-parameters and its own "
           "cross-validated tree count, and evaluated at ITS OWN out-of-fold recall-first threshold; the last column is "
           f"the paired FA difference to the frozen model (`{ab['selected']}`, positive = variant has more false "
           "alarms).", ""]
    rows = []
    for name, info in ab["variants"].items():
        fixed = result["fixed_thresholds"][name]["watch"]
        paired = result["paired_fixed_thresholds"].get(name, {}).get("watch")
        diff = "-" if not paired else _ci(paired["fa_share_baseline_minus_model"])
        rows.append([name + (" (frozen model)" if info["frozen_model"] else ""), str(info["n_inputs"]), str(info["n_trees"]),
                     _num(fixed["threshold"], 5), f"{100 * info['oof_recall_first']['oof_recall']:.1f}% / "
                     f"{100 * info['oof_recall_first']['oof_fa_share']:.1f}%", _pct(fixed["recall"]), _pct(fixed["fa_share"]),
                     diff])
    return out + [_table(["variant", "inputs", "trees", "threshold", "OOF recall / FA", "test recall", "test FA share",
                          "FA: variant minus frozen model"], rows), ""]


def render_markdown(result: dict) -> str:
    meta, stage1 = result["meta"], result["stage1"]
    out = ["# Phase 3 hazard model report (protocol v2)", "",
           f"Generated {meta['created_utc']} from "
           f"`{meta['model_dir']}` (trained {meta['model_trained_utc']}, frozen {meta['freeze_created_utc']}). "
           f"Bootstrap: {meta['bootstrap']['n']} resamples, {meta['bootstrap']['level']:.0%} percentile intervals; "
           "positives resampled as events, universe rows iid per region. test_2018 was evaluated once with the frozen "
           "model, frozen baselines and frozen thresholds"
           + (f" (evaluations recorded for this model: {meta['test_evaluations_recorded']})."
              if "test_evaluations_recorded" in meta else "."), ""]
    out += _history_section(result["protocol_history"])
    out += _gate_section(result["gate"])
    sel, hp = stage1["selected"], stage1["selected"]["hp"]
    out += ["## 2. Stage-1 cross-validation results (summary; full tables in `reports/phase3_hazard_cv_report.md`)", "",
            f"Year-blocked CV over 2007-2017, folds {stage1['folds']}. Selected feature set `{stage1['selected_groups']}` "
            f"({sel['n_inputs']} inputs), {hp['num_leaves']} leaves, min_data_in_leaf {hp['min_data_in_leaf']}, "
            f"feature_fraction {hp['feature_fraction']}, lambda_l2 {hp['lambda_l2']}, learning_rate {hp['learning_rate']}, "
            f"neg_mix `{sel['neg_mix']}`, {sel['n_trees']} trees (median of fold optima). The integ and corr groups were "
            "evaluated and not selected.", ""]
    out += cr._group_section(stage1) + cr._thresholds_section(stage1) + cr._baseline_section(stage1)
    out += cr._fold_section(stage1) + cr._calibration_section(stage1) + cr._presence_section(stage1)
    out += _threshold_section(result) + _test_section(result["test"]) + _calibration_section(result["test"], stage1)
    out += _window_section(result["window_2023"]) + _cases_section(result["cases"])
    out += _lro_section(result["leave_region_out"]) + _ablation_section(result["ablations"])
    out += ["## 10. Monotonicity and feature importance (frozen model)", ""]
    rows = [[n, "+1" if c["direction"] > 0 else "-1", "yes" if c["holds"] else "NO", _num(c["max_violation"], 8)]
            for n, c in result["monotonicity"].items()]
    out += [_table(["feature", "constraint", "held", "max violation"], rows), ""]
    importance = list(result["feature_importance_gain"].items())
    total = sum(v for _, v in importance) or 1.0
    out += [_table(["feature", "share of gain"], [[n, f"{100 * v / total:.1f}%"] for n, v in importance[:15]]), ""]
    return "\n".join(out)
