"""Markdown rendering of the v3-live evaluation report (the JSON is the source of truth).

The layout follows `report.py` (sections 1 to 10 are the same functions) and adds what a live-capable model that is
compared with a frozen predecessor needs: section 0 (the verdict against v2 from the paired out-of-fold difference, and
both models' test_2018 numbers side by side as a descriptive comparison), the per-region calibration of the
cross-validation (section 11) and the limits (section 12).
"""
from __future__ import annotations

from . import cv_report as cr
from . import report as rp
from .tables import _num, _pct, _table

REGION_LABELS = {"himalaya": "Himalaya", "western_ghats": "Western Ghats"}

VERDICT_TEXT = {
    "better": "**v3-live is better than frozen v2** on the protocol's measure: the paired 95% interval of the "
              "out-of-fold FA@90 difference (v3-live minus v2) lies wholly below zero.",
    "worse": "**v3-live is worse than frozen v2** on the protocol's measure: the paired 95% interval of the "
             "out-of-fold FA@90 difference (v3-live minus v2) lies wholly above zero. It is still the model the live "
             "runner uses, because v2 cannot run live.",
    "not_shown_better": "**v3-live is live-capable and is not shown to be better than v2**: the paired 95% interval of "
                        "the out-of-fold FA@90 difference (v3-live minus v2) includes zero (spec section 4.4). It is the "
                        "model the live runner uses because v2 cannot run live; v2 stays as the archive reference.",
}


def _signed(value: float, digits: int = 4) -> str:
    return f"{value:+.{digits}f}"


def _oof_lines(comparison: dict) -> list[str]:
    oof = comparison["oof_paired"]
    if oof is None:
        return ["The paired out-of-fold comparison (`reports/phase6_challengers.json`) is not available.", ""]
    ci = f"[{_signed(oof['ci_lo'])}, {_signed(oof['ci_hi'])}]"
    return [VERDICT_TEXT[oof["verdict"]], "",
            _table(["pooled OOF FA@90 (share of universe cell-days alerted at 90% recall)", "value"],
                   [["v3-live (this model)", _num(oof["fa_a"])], ["frozen v2", _num(oof["fa_b"])],
                    ["difference, v3-live minus v2 (positive = v3-live has more false alarms)",
                     f"{_signed(oof['point_difference'])} (bootstrap mean {_signed(oof['mean_difference'])}, "
                     f"SE {_num(oof['se'])}), {oof['level']:.0%} CI {ci}"],
                    ["share of paired resamples in which v3-live is better", _num(oof["share_a_better"], 3)]]), "",
            f"{oof['n_boot']} paired bootstrap resamples over the same development rows (year-blocked cross-validation "
            "over 2007-2017). This, not the test year, is the model-selection evidence; the test look below does not "
            "change the verdict.", ""]


def _v2_pair(v2: dict | None, region: str | None) -> list[str]:
    """v2's frozen test detection and alert share (overall, or of one region) as table cells."""
    if v2 is None:
        return ["n/a", "n/a"]
    if region is None:
        return [_pct(v2["test_recall"]), _pct(v2["test_fa_share"])]
    entry = v2["per_region"].get(region)
    return ["n/a", "n/a"] if entry is None else [_pct(entry["recall"]), _pct(entry["fa_share"])]


def _head_to_head(result: dict) -> list[str]:
    target = result["gate"]["recall_first_target"]
    v2 = result["comparison"]["v2_test"]
    counts = result["meta"]["test_counts"]
    below_floor = counts["positives_out_of_domain"]
    below_floor = sum(below_floor.values()) if isinstance(below_floor, dict) else below_floor
    out = ["### test_2018 at the recall-first Watch threshold: v3-live next to v2's frozen result", "",
           f"{counts['positives_in_domain']} in-domain positive cell-days ({below_floor} more below "
           "the slope floor) and the weighted universe. Detection = share of the in-domain positive cell-days whose own "
           "cell scored at or above the Watch threshold; share on alert = weighted share of non-buffer universe "
           "cell-days at or above it. 95% bootstrap intervals (positives resampled as events).", ""]
    rows = [[f"v3-live (raw score {_num(target['watch_threshold_raw'], 5)})", _pct(target["test_recall"]),
             _pct(target["test_fa_share"])],
            ["frozen v2 (raw score " + (_num(v2["watch_threshold_raw"], 5) if v2 else "n/a") + ")", *_v2_pair(v2, None)]]
    for region, entry in target["per_region"].items():
        name = REGION_LABELS.get(region, region)
        rows += [[f"v3-live, {name}", _pct(entry["recall"]), _pct(entry["fa_share"])],
                 [f"frozen v2, {name}", *_v2_pair(v2, region)]]
    rows += [["v3-live, overall recall counting out-of-domain positives as misses",
              _pct(target["overall_recall_incl_out_of_domain"]), "-"],
             ["frozen v2, overall recall counting out-of-domain positives as misses",
              _pct(v2["overall_recall_incl_out_of_domain"]) if v2 else "n/a", "-"]]
    out += [_table(["scorer / threshold", "detection (recall) [95% CI]", "share of cell-days on alert [95% CI]"], rows), "",
            "**This comparison is descriptive, not a hypothesis test.** The two models are separate fits scored on the "
            "same test year, v2's figures are read from its frozen report (`reports/phase3_hazard_report.json`), and no "
            f"paired test between them is made on test_2018 ({counts['positives_in_domain']} positives cannot resolve a "
            "difference of this size). Each model uses its own frozen Watch threshold, so detection "
            "and alert share move together: compare them as a pair.", ""]
    return out


def _verdict_section(result: dict) -> list[str]:
    comparison = result["comparison"]
    out = ["## 0. Verdict: v3-live against frozen v2", ""]
    out += _oof_lines(comparison)
    out += _head_to_head(result)
    return out


def _thresholds_note(result: dict) -> list[str]:
    by_region = result.get("thresholds_risk_by_region")
    if not by_region:
        return []
    regions = sorted(next(iter(by_region.values())))
    rows = [[label.capitalize(), _num(result["thresholds"]["model"][label], 5)]
            + [_num(by_region[label][r], 9) for r in regions] for label in ("watch", "warning", "emergency")]
    return ["Calibrated-risk thresholds by region (per-region calibration: the same raw score maps to a different risk "
            "in each region, so the deployed rule alerts on `risk >= that region's threshold`, which is the raw "
            "threshold seen through the region's calibrator):", "",
            _table(["level", "raw score", *[REGION_LABELS.get(r, r) for r in regions]], rows), ""]


def _deployed_note(result: dict) -> list[str]:
    if "model_deployed" not in result["window_2023"]:
        return []
    return ["The deployed rule has no single threshold in the table above: it alerts where the calibrated risk reaches the "
            "Watch risk threshold of the cell's own region (section 3).", ""]


def _region_cross_fit(stage1: dict) -> list[str]:
    return [line.replace("## OOF calibration per region", "## 11. Per-region calibration (cross-validation)")
            for line in cr._region_calibration_section(stage1)]


def _limits_section(gate: dict) -> list[str]:
    return ["## 12. Limits", ""] + [f"- {item}" for item in gate["limits"]] + [""]


def render_live_markdown(result: dict) -> str:
    meta, stage1 = result["meta"], result["stage1"]
    out = ["# Phase 6 live-capable hazard model report (v3-live)", "",
           f"Generated {meta['created_utc']} from `{meta['model_dir']}` (trained {meta['model_trained_utc']}, frozen "
           f"{meta['freeze_created_utc']}; calibration: {meta['calibration'].replace('_', ' ')}). Bootstrap: "
           f"{meta['bootstrap']['n']} resamples, {meta['bootstrap']['level']:.0%} percentile intervals; positives "
           "resampled as events, universe rows iid per region. test_2018 was evaluated once with the frozen model, "
           "frozen baselines and frozen thresholds"
           + (f" (evaluations recorded for this model: {meta['test_evaluations_recorded']})."
              if "test_evaluations_recorded" in meta else "."),
           "", "v3-live is the protocol-v2 model retrained on features that exist every morning (NASA IMERG rain, "
           "terrain), with per-region calibration. Its operational behaviour on live-timed inputs is in "
           "`reports/phase6_backtest.md`; everything on this page uses the training-style inputs.", ""]
    out += _verdict_section(result)
    out += rp._gate_section({**result["gate"], "limits": []})
    sel, hp = stage1["selected"], stage1["selected"]["hp"]
    out += ["## 2. Stage-1 cross-validation results (summary; full tables in `reports/phase6_v3_cv_report.md`)", "",
            f"Year-blocked CV over 2007-2017, folds {stage1['folds']}. Selected feature set `{stage1['selected_groups']}` "
            f"({sel['n_inputs']} inputs), {hp['num_leaves']} leaves, min_data_in_leaf {hp['min_data_in_leaf']}, "
            f"feature_fraction {hp['feature_fraction']}, lambda_l2 {hp['lambda_l2']}, learning_rate {hp['learning_rate']}, "
            f"neg_mix `{sel['neg_mix']}`, {sel['n_trees']} trees (median of fold optima).", ""]
    out += cr._group_section(stage1) + cr._thresholds_section(stage1) + cr._baseline_section(stage1)
    out += cr._fold_section(stage1) + cr._calibration_section(stage1)
    thresholds = {k: v for k, v in result["thresholds"].items() if k != "model_deployed"}
    out += rp._threshold_section({**result, "thresholds": thresholds}) + _thresholds_note(result)
    out += rp._test_section(result["test"]) + rp._calibration_section(result["test"], stage1)
    window = {k: {**v, "threshold": float("nan")} if k == "model_deployed" else v
              for k, v in result["window_2023"].items()}
    out += rp._window_section(window) + _deployed_note(result) + rp._cases_section(result["cases"])
    out += rp._lro_section(result["leave_region_out"]) + rp._ablation_section(result["ablations"])
    out += ["## 10. Monotonicity and feature importance (frozen model)", ""]
    rows = [[n, "+1" if c["direction"] > 0 else "-1", "yes" if c["holds"] else "NO", _num(c["max_violation"], 8)]
            for n, c in result["monotonicity"].items()]
    out += [_table(["feature", "constraint", "held", "max violation"], rows), ""]
    importance = list(result["feature_importance_gain"].items())
    total = sum(v for _, v in importance) or 1.0
    out += [_table(["feature", "share of gain"], [[n, f"{100 * v / total:.1f}%"] for n, v in importance[:15]]), ""]
    out += _region_cross_fit(stage1) or ["## 11. Per-region calibration (cross-validation)", "",
                                         "No per-region calibration was fitted.", ""]
    out += _limits_section(result["gate"])
    return "\n".join(out)
