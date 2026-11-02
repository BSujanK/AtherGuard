"""Evaluation of the corrector on held-out STATIONS, with station-bootstrap 95% confidence intervals.

Methods are dictionaries {name: DataFrame(q50, q90, q99[, p_exceed])} aligned with the evaluation rows; the raw
CHIRPS baseline predicts `chirps_1` for every quantile. Definitions:
* pinball: mean pinball loss per alpha (CI of the mean; also the CI of the paired difference to the raw baseline
  and, for the learned models, to the linear quantile scaling);
* coverage: share of gauge values <= the predicted quantile (target = alpha);
* top-1% bias: on the rows whose gauge value is in the pooled top 1% of the evaluated rows, mean(pred - gauge);
* exceedance: PR-AUC and recall at a fixed false-flag rate (share of NON-exceedance rows scored above the threshold).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score

from ..integrity.evaluate import bootstrap_ci
from .model import ALPHAS, pinball

QUANTILE_NAMES = {0.5: "q50", 0.9: "q90", 0.99: "q99"}
FALSE_FLAG_RATES = (0.01, 0.05)
N_BOOT = 1000
SEED = 20261201


def _groups(stations: np.ndarray) -> list[np.ndarray]:
    return [np.flatnonzero(stations == s) for s in pd.unique(stations)]


def _ci(values: np.ndarray, groups, n_boot: int) -> list[float]:
    return list(bootstrap_ci([values[g] for g in groups if len(g)], np.mean, n_boot, SEED))


def raw_baseline(chirps) -> pd.DataFrame:
    x = np.asarray(chirps, dtype=np.float64)
    return pd.DataFrame({"q50": x, "q90": x, "q99": x})


def pinball_table(rows: pd.DataFrame, methods: dict, n_boot: int = N_BOOT, reference: str = "raw_chirps",
                  linear: str = "linear_scaling") -> dict:
    y = rows["gauge"].to_numpy()
    groups = _groups(rows["station"].to_numpy())
    out = {}
    for name, pred in methods.items():
        out[name] = {}
        for alpha in ALPHAS:
            loss = pinball(y, pred[QUANTILE_NAMES[alpha]].to_numpy(), alpha)
            entry = {"mean": float(loss.mean()), "ci": _ci(loss, groups, n_boot)}
            if name != reference:
                ref = pinball(y, methods[reference][QUANTILE_NAMES[alpha]].to_numpy(), alpha)
                entry["reference_mean"] = float(ref.mean())
                entry["skill_vs_reference"] = float(1.0 - loss.mean() / ref.mean())
                entry["diff_vs_reference"] = float((loss - ref).mean())
                entry["diff_ci"] = _ci(loss - ref, groups, n_boot)
            if name not in (reference, linear) and linear in methods:
                lin = pinball(y, methods[linear][QUANTILE_NAMES[alpha]].to_numpy(), alpha)
                entry["diff_vs_linear"] = float((loss - lin).mean())
                entry["diff_vs_linear_ci"] = _ci(loss - lin, groups, n_boot)
            out[name][str(alpha)] = entry
    return out


def coverage_table(rows: pd.DataFrame, methods: dict, n_boot: int = N_BOOT) -> dict:
    y = rows["gauge"].to_numpy()
    groups = _groups(rows["station"].to_numpy())
    out = {}
    for name, pred in methods.items():
        out[name] = {}
        for alpha in (0.9, 0.99):
            hit = (y <= pred[QUANTILE_NAMES[alpha]].to_numpy()).astype(float)
            out[name][str(alpha)] = {"coverage": float(hit.mean()), "ci": _ci(hit, groups, n_boot), "target": alpha}
    return out


def top_bias_table(rows: pd.DataFrame, methods: dict, n_boot: int = N_BOOT) -> dict:
    y = rows["gauge"].to_numpy()
    threshold = float(np.percentile(y, 99))
    top = y >= threshold
    sub = rows[top]
    groups = _groups(sub["station"].to_numpy())
    out = {"threshold_mm": threshold, "rows": int(top.sum()), "stations": int(sub["station"].nunique()),
           "mean_gauge_mm": float(y[top].mean()), "methods": {}}
    for name, pred in methods.items():
        out["methods"][name] = {}
        for column in ("q50", "q90", "q99"):
            err = pred[column].to_numpy()[top] - y[top]
            out["methods"][name][column] = {"mean_bias_mm": float(err.mean()), "ci": _ci(err, groups, n_boot),
                                            "median_ratio_to_gauge": float(np.median(pred[column].to_numpy()[top] / y[top]))}
    return out


def _average_precision(y, score, groups, n_boot: int) -> tuple[float, list[float]]:
    point = float(average_precision_score(y, score))
    rng = np.random.default_rng(SEED)
    draws = []
    for _ in range(n_boot):
        idx = np.concatenate([groups[i] for i in rng.integers(0, len(groups), len(groups))])
        if y[idx].any():
            draws.append(average_precision_score(y[idx], score[idx]))
    lo, hi = np.percentile(draws, [2.5, 97.5]) if draws else (np.nan, np.nan)
    return point, [float(lo), float(hi)]


def exceedance_table(rows: pd.DataFrame, scores: dict[str, np.ndarray], n_boot: int = N_BOOT) -> dict:
    """PR-AUC and recall at fixed false-flag rates of exceedance scores (rows need an `exceed` label)."""
    labelled = rows["exceed"].notna().to_numpy()
    sub = rows[labelled]
    y = sub["exceed"].to_numpy().astype(bool)
    groups = _groups(sub["station"].to_numpy())
    out = {"rows": int(len(sub)), "positives": int(y.sum()), "stations": int(sub["station"].nunique()),
           "stations_with_positives": int(sub.loc[y, "station"].nunique()), "prevalence": float(y.mean()), "methods": {}}
    for name, score in scores.items():
        s = np.asarray(score, dtype=np.float64)[labelled]
        finite = np.isfinite(s)
        s = np.where(finite, s, (s[finite].min() - 1.0) if finite.any() else 0.0)   # an unscored row ranks last
        ap, ap_ci = _average_precision(y, s, groups, n_boot)
        entry = {"pr_auc": ap, "pr_auc_ci": ap_ci, "recall": {}}
        for rate in FALSE_FLAG_RATES:
            threshold = np.quantile(s[~y], 1 - rate, method="higher")
            hits = (s > threshold).astype(float)
            positive_groups = [g[y[g]] for g in groups if y[g].any()]
            entry["recall"][str(rate)] = {
                "recall": float(hits[y].mean()), "achieved_false_flag_rate": float((s[~y] > threshold).mean()),
                "ci": list(bootstrap_ci([hits[g] for g in positive_groups], np.mean, n_boot, SEED))}
        out["methods"][name] = entry
    return out


def evaluate(rows: pd.DataFrame, methods: dict, exceed_scores: dict, n_boot: int = N_BOOT) -> dict:
    return {"rows": int(len(rows)), "stations": int(rows["station"].nunique()),
            "pinball": pinball_table(rows, methods, n_boot), "coverage": coverage_table(rows, methods, n_boot),
            "top1pct_bias": top_bias_table(rows, methods, n_boot),
            "exceedance": exceedance_table(rows, exceed_scores, n_boot)}
