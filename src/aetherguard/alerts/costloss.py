"""Cost-loss arithmetic for alert thresholds.

An alert costs C (acting); a missed event costs L. With calibrated risk p = P(event on that cell-day), alerting is
optimal exactly when p >= C/L, so an operating threshold `t` is the cost ratio C/L at which it is optimal.
Expected expense per cell-day in units of L, for threshold t, event base rate b, recall r and alert rate a:

    expense = (C/L) * a + b * (1 - r)

The reference strategies are never alerting (expense b) and always alerting (expense C/L); `relative_expense` divides
by the cheaper of the two, so a value below 1 means the threshold beats both. The alert rate is measured on the
weighted universe negatives (their weights sum to the number of cell-days), recall on the positives.
"""
from __future__ import annotations

import numpy as np


def weighted_alert_rate(risk_neg, weight_neg, threshold: float) -> float:
    risk_neg, weight_neg = np.asarray(risk_neg, dtype=np.float64), np.asarray(weight_neg, dtype=np.float64)
    if risk_neg.shape != weight_neg.shape:
        raise ValueError("negative risks and weights must have the same length")
    total = weight_neg.sum()
    if total <= 0:
        raise ValueError("negative weights must have a positive sum")
    return float(weight_neg[risk_neg >= threshold].sum() / total)


def operating_point(risk_pos, risk_neg, weight_neg, threshold: float, base_rate: float, cost_ratio: float | None = None
                    ) -> dict:
    """Alerts per 1000 cell-days, recall, the implied C/L (= threshold) and the expense at `cost_ratio`
    (default: the implied C/L itself)."""
    if not 0 < base_rate < 1:
        raise ValueError("base_rate must be in (0, 1)")
    risk_pos = np.asarray(risk_pos, dtype=np.float64)
    if len(risk_pos) == 0:
        raise ValueError("no positives to measure recall on")
    rate = weighted_alert_rate(risk_neg, weight_neg, threshold)
    recall = float((risk_pos >= threshold).mean())
    ratio = threshold if cost_ratio is None else cost_ratio
    expense = ratio * rate + base_rate * (1.0 - recall)
    return {"threshold": float(threshold), "alerts_per_1000_cell_days": 1000.0 * rate, "recall": recall,
            "implied_cost_ratio": float(threshold), "cost_ratio": float(ratio), "expense": float(expense),
            "relative_expense": float(expense / min(base_rate, ratio))}


def cost_loss_table(risk_pos, risk_neg, weight_neg, base_rate: float, thresholds: dict[str, float], ratios) -> dict:
    """`operating_points`: the named thresholds with their implied C/L; `ratios`: for each C/L the optimal rule
    (alert iff risk >= C/L) evaluated at that C/L."""
    return {"base_rate": float(base_rate),
            "operating_points": {name: operating_point(risk_pos, risk_neg, weight_neg, t, base_rate)
                                 for name, t in thresholds.items()},
            "ratios": [{"cost_loss": float(r), **operating_point(risk_pos, risk_neg, weight_neg, r, base_rate, r)}
                       for r in ratios]}
