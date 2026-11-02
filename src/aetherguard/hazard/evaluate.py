"""Evaluation of scored splits: operating points, bootstrap CIs, paired comparison, window test, calibration.

A `ScoredSplit` holds, per scorer (the model and the baselines), a `metrics.ScoreSet` over the same rows: the
in-domain positive cell-days of the split and its weighted universe negatives (non-buffer, non-positive, weights
renormalised to the universe size per region). Operating thresholds are always chosen on VALIDATION
(`validation_thresholds`) and then applied unchanged to other sets; metrics that choose their own threshold on the set
(false-alarm share at a recall) are labelled as such by the caller.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..grid import neighbours
from . import calibration as cal
from . import data as hd
from . import metrics as mt


@dataclass
class ScoredSplit:
    name: str
    sets: dict[str, mt.ScoreSet]
    neg_weight: np.ndarray
    neg_region: np.ndarray
    pos_region: np.ndarray
    n_out_of_domain: int
    risk_pos: np.ndarray | None = None
    risk_neg: np.ndarray | None = None
    universe_cell_days: float = field(default=0.0)

    @property
    def n_positives(self) -> int:
        return len(self.pos_region)


def score_universe(data: hd.SplitData, scorers: dict) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """Score the in-domain positives and the FULL universe frame once per scorer (frame -> ranking score)."""
    return {name: (np.asarray(fn(data.positives), dtype=np.float64), np.asarray(fn(data.universe), dtype=np.float64))
            for name, fn in scorers.items()}


def build_view(data: hd.SplitData, raw: dict[str, tuple[np.ndarray, np.ndarray]], *, include_buffer: bool = False,
               region: str | None = None, risk: tuple[np.ndarray, np.ndarray] | None = None) -> ScoredSplit:
    """A ScoredSplit over (optionally) one region; `include_buffer` is the sensitivity variant."""
    universe = data.universe
    keep = hd.universe_negative_mask(universe, include_buffer)
    weights = np.zeros(len(universe))
    weights[keep] = hd.renormalised_weights(universe, keep)
    neg_region_all = universe["region"].to_numpy()
    pos_region_all = data.positives["region"].to_numpy()
    neg_mask = keep & ((neg_region_all == region) if region else True)
    pos_mask = (pos_region_all == region) if region else np.ones(len(pos_region_all), dtype=bool)
    sets = {name: mt.ScoreSet(pos[pos_mask], uni[neg_mask], weights[neg_mask]) for name, (pos, uni) in raw.items()}
    n_ood = data.n_out_of_domain.get(region, 0) if region else sum(data.n_out_of_domain.values())
    return ScoredSplit(
        name=data.split if region is None else f"{data.split}:{region}", sets=sets, neg_weight=weights[neg_mask],
        neg_region=neg_region_all[neg_mask], pos_region=pos_region_all[pos_mask], n_out_of_domain=n_ood,
        risk_pos=None if risk is None else risk[0][pos_mask], risk_neg=None if risk is None else risk[1][neg_mask],
        universe_cell_days=float(weights[neg_mask].sum()))


# ------------------------------------------------------------------------------------- operating points

def validation_thresholds(val: ScoredSplit, cfg: dict) -> dict[str, dict[str, float]]:
    """Per scorer: raw-score thresholds reaching each recall target and each false-alarm share ON VALIDATION."""
    ops = cfg["operating_points"]
    out = {}
    for name, scoring in val.sets.items():
        thresholds = {f"recall_{r}": scoring.threshold_for_recall(r) for r in ops["recalls"]}
        thresholds.update({f"fa_{f}": scoring.threshold_for_fa(f) for f in ops["fa_shares"]})
        out[name] = thresholds
    return out


def _summaries(point: dict[str, float], boot: dict[str, np.ndarray], level: float) -> dict[str, dict]:
    return {key: mt.summarize(value, boot[key], level) for key, value in point.items() if key in boot}


def evaluate_split(scored: ScoredSplit, cfg: dict, *, reference: str = "model",
                   fixed_thresholds: dict[str, dict[str, float]] | None = None, comparators=None) -> dict:
    """Point estimates with bootstrap CIs for every scorer, paired differences to `reference`, and (with
    `fixed_thresholds`) the realised recall / false-alarm share of thresholds chosen elsewhere, with paired differences
    between `reference` and each of `comparators` (default: every other scorer) at those thresholds."""
    ops, boot_cfg = cfg["operating_points"], cfg["bootstrap"]
    recalls, fas, level = ops["recalls"], ops["fa_shares"], boot_cfg["level"]
    boot = mt.bootstrap_metrics(scored.sets, scored.neg_weight, scored.neg_region, recalls=recalls, fa_shares=fas,
                                n_boot=boot_cfg["n"], seed=boot_cfg["seed"], fixed_thresholds=fixed_thresholds)
    headline = f"fa_at_recall_{ops['headline_recall']}"
    result = {"split": scored.name, "n_positives": scored.n_positives, "n_negative_rows": len(scored.neg_weight),
              "n_out_of_domain_positives": scored.n_out_of_domain, "universe_cell_days": scored.universe_cell_days,
              "warning": None if scored.n_positives >= cfg["min_positives_warning"] else
              f"only {scored.n_positives} positive cell-days (< {cfg['min_positives_warning']}): intervals are wide "
              "and unstable", "metrics": {}, "paired_fa_at_headline_recall": {}, "fixed_thresholds": {},
              "paired_fixed_thresholds": {}}
    for name, scoring in scored.sets.items():
        result["metrics"][name] = _summaries(scoring.point(recalls, fas), boot[name], level)
        for label, threshold in (fixed_thresholds or {}).get(name, {}).items():
            ps = np.sort(scoring.pos)[::-1]
            result["fixed_thresholds"].setdefault(name, {})[label] = {
                "threshold": threshold,
                "recall": mt.summarize(scoring.recall_at(ps, threshold), boot[name][f"fixed_recall_{label}"], level),
                "fa_share": mt.summarize(scoring.fa_at(threshold), boot[name][f"fixed_fa_{label}"], level)}
    names = [n for n in scored.sets if n != reference and (comparators is None or n in comparators)]
    if reference in scored.sets:
        for name in names:
            result["paired_fixed_thresholds"][name] = _paired_fixed(scored, boot, reference, name, fixed_thresholds,
                                                                    level)
        ref_point = scored.sets[reference].point([ops["headline_recall"]], [])[headline]
        for name in names:
            scoring = scored.sets[name]
            diff = mt.paired_difference(boot[reference][headline], boot[name][headline], ref_point,
                                        scoring.point([ops["headline_recall"]], [])[headline], level)
            diff["verdict"] = {"a_better": "model better", "b_better": f"{name} better", "tie": "tie"}[
                mt.verdict(diff["lo"], diff["hi"])]
            result["paired_fa_at_headline_recall"][name] = diff
    return result


def _paired_fixed(scored: ScoredSplit, boot: dict, reference: str, name: str, fixed: dict | None, level: float) -> dict:
    """Per threshold label shared by both scorers: baseline-minus-reference FA share (positive = reference fewer false
    alarms) and reference-minus-baseline recall (positive = reference detects more), each with a paired CI."""
    out = {}
    ref_set, other = scored.sets[reference], scored.sets[name]
    ref_ps, other_ps = np.sort(ref_set.pos)[::-1], np.sort(other.pos)[::-1]
    for label in sorted(set((fixed or {}).get(reference, {})) & set((fixed or {}).get(name, {}))):
        t_ref, t_other = fixed[reference][label], fixed[name][label]
        out[label] = {
            "fa_share_baseline_minus_model": mt.paired_difference(
                boot[reference][f"fixed_fa_{label}"], boot[name][f"fixed_fa_{label}"], ref_set.fa_at(t_ref),
                other.fa_at(t_other), level),
            "recall_model_minus_baseline": mt.paired_difference(
                boot[name][f"fixed_recall_{label}"], boot[reference][f"fixed_recall_{label}"],
                other.recall_at(other_ps, t_other), ref_set.recall_at(ref_ps, t_ref), level)}
    return out


def share_with_ci(flags, n_boot: int, seed: int, level: float = 0.95, extra_zeros: int = 0) -> dict:
    """Share of True flags with a percentile-bootstrap CI over the units; `extra_zeros` appends units that count
    as False (e.g. out-of-domain positives, which are misses)."""
    values = np.concatenate([np.asarray(flags, dtype=np.float64), np.zeros(extra_zeros)])
    rng = np.random.default_rng(seed)
    resamples = values[rng.integers(0, len(values), (n_boot, len(values)))].mean(axis=1)
    return {**mt.summarize(values.mean(), resamples, level), "n": int(len(values)), "hits": int(values.sum())}


def overall_recall(scored: ScoredSplit, thresholds: dict[str, dict[str, float]], label: str, cfg: dict) -> dict:
    """Recall counting the out-of-domain positives (below the slope floor, never scored) as misses."""
    out = {}
    for name, scoring in scored.sets.items():
        if label not in thresholds[name]:           # e.g. the per-region deployed rule has a Watch threshold only
            continue
        flags = scoring.pos >= thresholds[name][label]
        out[name] = {"in_domain": share_with_ci(flags, cfg["bootstrap"]["n"], cfg["bootstrap"]["seed"],
                                                cfg["bootstrap"]["level"]),
                     "overall": share_with_ci(flags, cfg["bootstrap"]["n"], cfg["bootstrap"]["seed"],
                                              cfg["bootstrap"]["level"], extra_zeros=scored.n_out_of_domain)}
    return out


# ------------------------------------------------------------------------------------------- window test

def window_detection(frame: pd.DataFrame, scores, threshold: float, n_boot: int, seed: int, level: float = 0.95) -> dict:
    """2023 window test at a fixed threshold (alert = score >= threshold).

    A window-positive cell is detected when the maximum score over the window days of ANY of the 3x3 cells around it
    (the cell and its 8 neighbours, among the window-cell rows) reaches the threshold. False alarms: share of control
    cells whose own maximum over the window reaches it (an upper bound: the inventory is partial; a control cell has
    one cell's chances, a detection has nine), plus the alerted share of control cell-days.
    """
    kind = frame["kind"].to_numpy()
    cell = frame["cell_id"].to_numpy()
    score = np.asarray(scores, dtype=np.float64)
    in_window = kind == "window_cell"
    window_max = pd.Series(score[in_window]).groupby(cell[in_window]).max()
    positive_cells = np.unique(cell[in_window & frame["is_window_positive_cell"].to_numpy(dtype=bool)])
    detected, details = [], []
    for c in positive_cells:
        around = [x for x in [int(c), *neighbours(int(c))] if x in window_max.index]
        best = float(max(window_max[x] for x in around))
        detected.append(best >= threshold)
        details.append({"cell_id": int(c), "neighbourhood_cells": len(around), "max_score": best,
                        "detected": bool(best >= threshold)})
    is_control = kind == "window_control"
    control_max = pd.Series(score[is_control]).groupby(cell[is_control]).max()
    control_flags = (control_max >= threshold).to_numpy()
    return {"threshold": threshold, "positive_cells": len(positive_cells),
            "detection": share_with_ci(detected, n_boot, seed, level),
            "control_cells": int(len(control_max)),
            "control_any_alert": share_with_ci(control_flags, n_boot, seed, level),
            "control_cell_day_alert_share": float(np.mean(score[is_control] >= threshold)),
            "cells": details}


# ------------------------------------------------------------------------------------------- calibration

def calibration_report(scored: ScoredSplit, cfg: dict) -> dict:
    """Weighted reliability table by deciles of risk, a tail split of the top decile, and ECE."""
    if scored.risk_pos is None:
        raise ValueError("this scored split carries no calibrated risk")
    risk = np.concatenate([scored.risk_pos, scored.risk_neg])
    labels = np.concatenate([np.ones(len(scored.risk_pos)), np.zeros(len(scored.risk_neg))])
    weights = np.concatenate([np.ones(len(scored.risk_pos)), scored.neg_weight])
    base_rate = float(len(scored.risk_pos) / scored.neg_weight.sum())
    deciles = cal.reliability_table(risk, labels, weights, cal.decile_edges(cfg["calibration"]["deciles"]))
    tail = cal.reliability_table(risk, labels, weights, [0.0, *cfg["calibration"]["tail_edges"], 1.0])
    ece = cal.expected_calibration_error(deciles)
    return {"base_rate": base_rate, "mean_predicted_risk": float(np.average(risk, weights=weights)),
            "ece_deciles": ece, "ece_deciles_relative_to_base_rate": ece / base_rate,
            "ece_tail_bins": cal.expected_calibration_error(tail), "deciles": deciles, "tail_bins": tail}


# ------------------------------------------------------------------------------------------- case studies

def case_alerts(frame: pd.DataFrame, scores, threshold: float) -> dict:
    """Alerts of a case-study table at a fixed threshold: recall of its positive cell-days (if any) and the alerted
    share of its non-buffer, non-positive cell-days. Case rows are scored only, never fitted or tuned on."""
    score = np.asarray(scores, dtype=np.float64)
    alerted = score >= threshold
    positive = frame["is_positive_cell_day"].to_numpy(dtype=bool)
    eligible = ~frame["in_buffer"].to_numpy(dtype=bool) & ~positive
    return {"threshold": threshold, "rows": int(len(frame)), "positive_cell_days": int(positive.sum()),
            "positives_alerted": int((alerted & positive).sum()),
            "recall": float(alerted[positive].mean()) if positive.any() else None,
            "alerted_share_non_buffer": float(alerted[eligible].mean()), "alerted_cell_days": int(alerted.sum()),
            "max_score": float(score.max())}
