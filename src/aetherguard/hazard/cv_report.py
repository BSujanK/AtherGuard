"""Markdown rendering of the protocol-v2 stage-1 cross-validation report (the JSON is the source of truth)."""
from __future__ import annotations

from .tables import _ci, _label, _num, _ordered, _pct, _table


def _grid_section(payload: dict, top: int = 10) -> list[str]:
    rows = sorted(payload["grid"], key=lambda r: (r["fa_at_90"], r["logloss"], r["index"]))[:top]
    body = [[r["name"], str(r["num_leaves"]), str(r["min_data_in_leaf"]), str(r["feature_fraction"]),
             str(r["lambda_l2"]), r["neg_mix"], str(r["n_trees"]), f"{100 * r['fa_at_90']:.1f}%",
             _num(r["logloss"], 4), "yes" if r["selected"] else ""] for r in rows]
    return [f"## Hyper-parameter grid (top {top} of {len(payload['grid'])}, pooled OOF)", "",
            _table(["candidate", "leaves", "min leaf", "feat frac", "L2", "neg_mix", "trees", "OOF FA @ 90% recall",
                    "OOF log-loss", "selected"], body), ""]


def _group_section(payload: dict) -> list[str]:
    body = [[str(r["stage"] + 1), r["name"], str(r["n_inputs"]), _num(r["fa_at_90"]), _num(r["se"]),
             f"[{_num(r['ci_lo'])}, {_num(r['ci_hi'])}]", _num(r["pr_auc"], 5), str(r["n_trees"]),
             "selected" if r["selected_in_stage"] else ""] for r in payload["groups"]]
    return ["## Feature-group selection (selected hyper-parameters)", "",
            "A more complex candidate replaces a simpler one only if its pooled OOF FA@90 is lower by more than its own "
            "bootstrap SE. Stage 2 extends the stage-1 winner.", "",
            _table(["stage", "candidate", "inputs", "OOF FA@90", "bootstrap SE", "95% CI", "OOF PR-AUC", "trees",
                    "decision"], body), ""]


def _thresholds_section(payload: dict) -> list[str]:
    thresholds = payload["evaluation"]["thresholds"]["model"]
    rows = [[label, _num(t["raw"], 5), _num(t["risk"], 9) if t["risk"] is not None else "n/a",
             f"{100 * t['oof_recall']:.1f}%", f"{100 * t['oof_fa_share']:.2f}%"]
            for label, t in thresholds.items()]
    return ["## OOF thresholds and alert levels (model)", "",
            "recall_first = highest threshold whose bootstrap 5th-percentile OOF recall is at least 90%; Watch = "
            "recall_first, Warning = OOF recall 75%, Emergency = OOF recall 50%.", "",
            _table(["threshold", "raw score", "calibrated risk", "OOF recall", "OOF FA share"], rows), ""]


def _baseline_section(payload: dict) -> list[str]:
    ev = payload["evaluation"]
    ops = payload["evaluation"]["metrics"]["model"]["pooled"]
    recalls = sorted(k for k in ops if k.startswith("fa_at_recall_"))
    fas = sorted((k for k in ops if k.startswith("recall_at_fa_")), key=lambda k: float(k.rsplit("_", 1)[1]))
    header = ["scorer"] + [f"FA @ {k.rsplit('_', 1)[1]} recall" for k in recalls] + [
        f"recall @ FA {float(k.rsplit('_', 1)[1]):.1%}" for k in fas] + ["PR-AUC"]
    rows = []
    for name in _ordered(ev["metrics"]):
        m = ev["metrics"][name]["pooled"]
        rows.append([_label(name)] + [_pct(m[k]) for k in recalls] + [_pct(m[k]) for k in fas] + [_ci(m["pr_auc"], 5)])
    out = ["## OOF metrics, model versus baselines (same protocol)", "", _table(header, rows), "",
           "Own-OOF thresholds (each scorer's thresholds from its own pooled OOF scores):", ""]
    rows = []
    for name in _ordered(ev["metrics"]):
        for label, entry in ev["metrics"][name]["at_thresholds"].items():
            rows.append([_label(name), label, _num(entry["threshold"], 5), _pct(entry["recall"]),
                         _pct(entry["fa_share"])])
    out += [_table(["scorer", "threshold", "raw score", "OOF recall [95% CI]", "OOF FA share [95% CI]"], rows), "",
            "Paired OOF difference in FA share at 90% recall (comparator minus model; positive favours the model):", ""]
    rows = [[_label(n), _ci({"value": d["value"], "lo": d["lo"], "hi": d["hi"]}), f"{d['share_a_better']:.2f}",
             d["verdict"]] for n, d in ev["paired_fa_at_90_vs_model"].items()]
    out += [_table(["comparator", "difference [95% CI]", "share of resamples model better", "verdict"], rows), ""]
    return out


def _fold_section(payload: dict) -> list[str]:
    rows = [[str(f["fold"]), "-".join(str(y) for y in (f["years"][0], f["years"][-1])) if len(f["years"]) > 1
             else str(f["years"][0]), str(f["n_positives"]), str(f["best_iteration"]),
             _num(f["fa_at_recall_0.9"]), _num(f["recall_at_fa_0.05"]), _num(f["logloss"])]
            for f in payload["selected"]["per_fold"]]
    return ["## Per-fold variability (selected model)", "",
            f"Final tree count = median of fold optima {payload['selected']['fold_best_iterations']} = "
            f"{payload['selected']['n_trees']}.", "",
            _table(["fold", "years", "positives", "early-stop best iteration", "FA@90 (fold only)",
                    "recall @ FA 5%", "design log-loss"], rows), ""]


def _calibration_section(payload: dict) -> list[str]:
    c = payload["calibration"]
    out = ["## OOF calibration", "",
           f"Base rate {c['base_rate'] * 1e5:.3f} per 100k cell-days. The saved calibrator is isotonic on the pooled "
           "OOF scores (in-sample); the cross-fitted variant calibrates each fold with a map fitted on the other "
           "folds and is the honest check.", ""]
    rows = [[label, _num(c[label]["mean_predicted"] * 1e5, 3), _num(c[label]["ece_deciles"] * 1e5, 3),
             _num(c[label]["ece_deciles"] / c["base_rate"], 3)] for label in ("insample", "crossfit")]
    out += [_table(["calibrator", "mean predicted per 100k", "ECE (deciles) per 100k", "ECE / base rate"], rows), ""]
    years = c["crossfit"]["per_year"]
    rows = [[str(y), str(v["positives"]), _num(v["mean_predicted"] * 1e5, 3), _num(c["insample"]["per_year"][y]["mean_predicted"]
                                                                          * 1e5, 3), _num(v["observed"] * 1e5, 3)]
            for y, v in years.items()]
    out += ["Per-year mean predicted versus observed risk, per 100k cell-days:", "",
            _table(["year", "positives", "predicted (cross-fitted)", "predicted (saved calibrator)", "observed"], rows),
            ""]
    return out


def _region_calibration_section(payload: dict) -> list[str]:
    summary = payload.get("calibration_regions")
    if not summary:
        return []
    out = ["## OOF calibration per region", "",
           f"Per-region isotonic calibrators (a region with fewer than {summary['min_region_positives']} OOF "
           "positives uses the pooled calibrator). Cross-fitted: each fold is calibrated by maps fitted on the other "
           "folds. Values per 100k cell-days at the region's own base rate; the pooled columns are the pooled "
           "calibrator on the same rows.", ""]
    rows = []
    for region, e in summary["regions"].items():
        own, pooled = e["crossfit_per_region"], e["crossfit_pooled"]
        rows.append([region, str(e["positives"]), e["calibrator"], _num(e["observed"] * 1e5, 3),
                     _num(own["mean_predicted"] * 1e5, 3), _num(own["ece_deciles"] * 1e5, 3),
                     _num(pooled["mean_predicted"] * 1e5, 3), _num(pooled["ece_deciles"] * 1e5, 3)])
    out += [_table(["region", "OOF positives", "calibrator", "observed", "predicted (per region)",
                    "ECE (per region)", "predicted (pooled)", "ECE (pooled)"], rows), ""]
    return out


def _presence_section(payload: dict) -> list[str]:
    presence = payload["integ_presence"]
    if not presence:
        return []
    out = ["## integ candidates with and without a nearby station", "", presence["note"], ""]
    for label in ("with_station", "without_station"):
        entry = presence[label]
        out += [f"**{label.replace('_', ' ')}** ({entry['n_positives']} positives, "
                f"{100 * entry['universe_share']:.1f}% of the universe cell-days)", ""]
        rows = [[name, _pct(m["fa_at_recall_0.9"]), _pct(m["recall_at_fa_0.05"]), _ci(m["pr_auc"], 5)]
                for name, m in entry["metrics"].items()]
        out += [_table(["candidate", "FA@90 (subset threshold)", "recall @ FA 5%", "PR-AUC"], rows), ""]
    return out


def render_cv_markdown(payload: dict) -> str:
    dev, sel = payload["development"], payload["selected"]
    out = ["# Phase 3 hazard model: protocol v2 stage-1 cross-validation report", "",
           f"Generated {payload['created_utc']}. {payload['protocol']}. No test_2018, window or case rows were read. "
           f"Folds: {payload['folds']}. Development: {dev['positives_in_domain']} in-domain positive cell-days "
           f"(+{sum(dev['positives_out_of_domain'].values())} outside the slope domain, excluded), "
           f"{dev['matched_negatives']} matched negatives, {dev['universe_negative_rows']:,} universe negative rows "
           f"({sum(dev['universe_cell_days'].values()):,} cell-days; base rate "
           f"{dev['base_rate_per_100k_cell_days']:.3f} per 100k). Runtime {payload['train_seconds'] / 60:.1f} min.", ""]
    hp = sel["hp"]
    out += [f"**Selected**: feature set `{payload['selected_groups']}` ({sel['n_inputs']} inputs), "
            f"{hp['num_leaves']} leaves, min_data_in_leaf {hp['min_data_in_leaf']}, feature_fraction "
            f"{hp['feature_fraction']}, lambda_l2 {hp['lambda_l2']}, learning_rate {hp['learning_rate']}, neg_mix "
            f"`{sel['neg_mix']}`, {sel['n_trees']} trees.", ""]
    out += _grid_section(payload) + _group_section(payload) + _thresholds_section(payload)
    out += _baseline_section(payload) + _fold_section(payload) + _calibration_section(payload)
    out += _region_calibration_section(payload) + _presence_section(payload)
    out += ["## Monotonicity (final model)", ""]
    rows = [[n, "+1" if c["direction"] > 0 else "-1", "yes" if c["holds"] else "NO", _num(c["max_violation"], 8)]
            for n, c in payload["monotonicity"].items()]
    out += [_table(["feature", "constraint", "held", "max violation"], rows), "", "## Feature importance (gain, top 15)",
            ""]
    importance = list(payload["feature_importance_gain"].items())
    total = sum(v for _, v in importance) or 1.0
    out += [_table(["feature", "share of gain"], [[n, f"{100 * v / total:.1f}%"] for n, v in importance[:15]]), ""]
    return "\n".join(out)
