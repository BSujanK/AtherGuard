"""Re-scoring of the published feature tables with the frozen model (spec section 13, checks `reproducible` and `shap`).

The scores a run publishes are a function of the stored model inputs, so scoring `features_D<k>.parquet` again with the
same model reproduces them:

  reproducible   risk, risk_lo, risk_hi (and, at lead 0, risk_per_100k, member_median_risk, ensemble_agreement) equal
                 `HazardModel.score` of the stored inputs within 1e-9 relative, before any post-rule (the rules change
                 levels and confidence, never a risk); the rows that carry a score are exactly the rows whose rain inputs
                 are complete (`run.scorable_mask`, and for a forecast lead `run.lead_scorable`). A forecast lead's
                 interval is the model's, widened by the lead's factors (`run.lead_scores`): risk_lo = min(f_lo x raw lo,
                 risk) and risk_hi = max(min(f_hi x raw hi, 1), risk). The factors are not stored, so they are read off the
                 rows the clip does not touch; the same factor must hold for every row.
  uncertain_high the flag is the test of the rules on the model's UNWIDENED interval, recomputed here from the re-scored
                 features and not from the run's own `lead_scores`: lead 0 and a forecast lead under `lead_uncertain_bound`
                 "unwidened" test the model's `risk_hi` (or the configured ensemble percentile), under "widened" that bound
                 times the lead's factor (risk_hi capped at 1), under "none" the point risk; the point is below Watch and
                 the bound reaches it (`levels.uncertain_high_mask`). A bound that is not the rules' (the widened interval
                 under an "unwidened" rule) flags other cells.
  shap           base + the sum of ALL contributions (LightGBM `pred_contrib` of the point model) equals the raw margin
                 (`raw_score`) within 1e-6, and the contributions listed in `shap_json` are the model's five largest.
"""
from __future__ import annotations

import time

import numpy as np
import pandas as pd

from ..alerts import levels as lv
from ..alerts.engine import uncertain_bound
from ..hazard.model import TOP_CONTRIBUTIONS, feature_matrix
from . import postrules as pr
from .audit_math import flag

RTOL = 1e-9
MARGIN_ATOL = 1e-6
SCORE_COLUMNS = ("risk", "risk_lo", "risk_hi")
LEAD0_EXTRA = ("risk_per_100k", "member_median_risk", "ensemble_agreement")


def _differs(stored: np.ndarray, expected: np.ndarray) -> np.ndarray:
    both = np.isfinite(stored) & np.isfinite(expected)
    with np.errstate(invalid="ignore"):
        return (np.isfinite(stored) != np.isfinite(expected)) | (both & (np.abs(stored - expected) > RTOL * np.abs(expected)))


def _infer_factor(stored: np.ndarray, raw: np.ndarray, risk: np.ndarray, lower: bool) -> float:
    """The widening factor of an interval bound: stored / raw over the rows the clip against the point risk leaves alone."""
    with np.errstate(invalid="ignore", divide="ignore"):
        free = np.isfinite(stored) & (raw > 0) & ((stored < risk) if lower else ((stored > risk) & (stored < 1.0)))
        ratio = stored[free] / raw[free]
    return float(np.median(ratio)) if len(ratio) else 1.0


def rescore_table(model, features: pd.DataFrame, scorable: np.ndarray) -> pd.DataFrame:
    """`model.score` of the scorable rows of a stored feature table, NaN elsewhere (index of `features`)."""
    out = pd.DataFrame(np.nan, index=features.index, columns=[*SCORE_COLUMNS, *LEAD0_EXTRA])
    if scorable.any():
        scored = model.score(features[scorable])
        out.loc[scorable, scored.columns.intersection(out.columns)] = scored[scored.columns.intersection(out.columns)]
    return out


def check_reproducible(model, table: pd.DataFrame, features: pd.DataFrame, lead: int, scorable_on_day_d: np.ndarray | None,
                       found) -> dict:
    """Check one published table against its features table; returns {"factors": (lo, hi) | None, "rows_scored": n}."""
    from .run import lead_scorable, scorable_mask
    features = features.drop_duplicates("cell_id").set_index("cell_id").reindex(table["cell_id"].to_numpy()).reset_index()
    mask = scorable_mask(features, model.columns) if lead == 0 else lead_scorable(features, model.columns, scorable_on_day_d)
    scores = rescore_table(model, features, mask)
    stored = {c: table[c].to_numpy(dtype=np.float64) for c in (*SCORE_COLUMNS, *LEAD0_EXTRA) if c in table.columns}
    problems = {"a score is published for a row whose inputs are incomplete, or none for a complete one":
                np.isfinite(stored["risk"]) != mask}
    factors = None
    expected = {c: scores[c].to_numpy(dtype=np.float64) for c in scores.columns}
    if lead:
        widened = bool(table["widened"].any()) if "widened" in table.columns else False
        f_lo = _infer_factor(stored["risk_lo"], expected["risk_lo"], expected["risk"], True) if widened else 1.0
        f_hi = _infer_factor(stored["risk_hi"], expected["risk_hi"], expected["risk"], False) if widened else 1.0
        factors = (f_lo, f_hi)
        expected["risk_lo"] = np.minimum(expected["risk_lo"] * f_lo, expected["risk"])
        expected["risk_hi"] = np.maximum(np.minimum(expected["risk_hi"] * f_hi, 1.0), expected["risk"])
    for column in (*SCORE_COLUMNS, *(c for c in LEAD0_EXTRA if lead == 0)):
        if column in stored and column in expected:
            reference = expected[column] if column != "risk_per_100k" else 1e5 * expected["risk"]
            problems[f"{column} differs from the model's score of the stored inputs"] = _differs(stored[column], reference)
    flag(found, "reproducible", table, problems)
    return {"factors": factors, "rows_scored": int(mask.sum()), "scorable": mask, "raw": scores, "features": features}


def check_uncertain(model, table: pd.DataFrame, features: pd.DataFrame, raw: pd.DataFrame, scorable: np.ndarray, lead: int,
                    thresholds, alert_config, rules: pr.PostRules, factors: tuple[float, float] | None, found) -> None:
    """`uncertain_high` of a published table against the rules' bound recomputed from the re-scored unwidened interval (module
    doc). `raw` is `rescore_table` of `features` (rows aligned with `table`), `factors` the lead's (lo, hi) widening."""
    from .run import with_uncertain_bound
    rows = features[scorable]
    scored = raw.loc[scorable, [c for c in raw.columns if c in ("risk", "risk_lo", "risk_hi")]].copy()
    risk = scored["risk"].to_numpy(dtype=np.float64)
    unwidened = uncertain_bound(with_uncertain_bound(scored.copy(), model, rows, alert_config), alert_config)
    bound = unwidened
    if lead:
        hi = factors[1] if factors else 1.0
        widened_scored = scored.assign(risk_hi=np.maximum(np.minimum(scored["risk_hi"] * hi, 1.0), scored["risk"]))
        widened = uncertain_bound(with_uncertain_bound(widened_scored, model, rows, alert_config, hi), alert_config)
        bound = pr.lead_bound(rules, risk, unwidened, widened)
    region = rows["region"].to_numpy() if isinstance(thresholds, lv.RegionThresholds) else None
    expected = np.zeros(len(table), dtype=bool)
    expected[np.flatnonzero(scorable)] = lv.uncertain_high_mask(risk, bound, thresholds, region)
    stored = table["uncertain_high"].to_numpy(dtype=bool)
    flag(found, "reproducible", table, {"uncertain_high differs from the test of the rules' bound on the re-scored interval":
                                       stored != expected})


def check_contributions(model, table: pd.DataFrame, features: pd.DataFrame, scorable: np.ndarray, found) -> None:
    """The full contribution vector of the scorable rows: base + sum == margin, and `shap_json` lists the top five."""
    import json
    if "shap_json" not in table.columns or not scorable.any():
        return
    features = features.drop_duplicates("cell_id").set_index("cell_id").reindex(table["cell_id"].to_numpy()).reset_index()
    matrix = feature_matrix(features[scorable], model.columns)
    contribution = model.booster.predict(matrix, num_iteration=model.best_iteration, pred_contrib=True)
    margin = model.booster.predict(matrix, num_iteration=model.best_iteration, raw_score=True)
    off = np.abs(contribution.sum(axis=1) - margin) > MARGIN_ATOL
    rows = np.flatnonzero(scorable)
    wrong = np.zeros(len(table), dtype=bool)
    wrong[rows[off]] = True
    problems = {"base + the sum of all contributions is not the raw margin": wrong}
    listed_wrong = np.zeros(len(table), dtype=bool)
    shap = table["shap_json"].to_numpy()
    for k, row in enumerate(rows):
        order = np.argsort(-np.abs(contribution[k, :-1]), kind="stable")[:TOP_CONTRIBUTIONS]
        try:
            listed = json.loads(shap[row])
        except (TypeError, ValueError):
            listed_wrong[row] = True
            continue
        want = [(model.columns[j], contribution[k, j]) for j in order]
        if len(listed) != len(want) or any(
                item.get("feature") != name or not np.isclose(item.get("contribution", np.nan), value, rtol=1e-9, atol=1e-12)
                for item, (name, value) in zip(listed, want)):
            listed_wrong[row] = True
    problems["shap_json is not the model's five largest contributions"] = listed_wrong
    flag(found, "shap", table, problems)


def timed(function, *args, **kwargs):
    start = time.monotonic()
    result = function(*args, **kwargs)
    return result, time.monotonic() - start
