"""The alert engine: hazard scores + station trust -> one alert row per cell-day.

    alerts = run_alerts(features, scores, station_outputs, stations=stations, thresholds=thresholds, config=config)

`features` is a feature-store frame joined with its `integ_` columns (`frames.load_feature_frame`), `scores` the
hazard model output for the same rows (`risk`, `risk_lo`, `risk_hi`, `risk_per_100k`, same index), `station_outputs`
the integrity engine outputs (flag column as it should be used, i.e. causal) and `stations` their coordinates.
Without station outputs no station is out of distribution (no station information); with them `stations` is required.

Order of decisions per cell-day:
  1. raw level from the calibrated risk vs the card thresholds (the cell's region's, when they are given by region);
     `uncertain_high` raises a below-Watch point to Watch;
  2. data confidence and the blind-escalation rule (confidence not High and any source shows heavy rain -> at least
     Watch);
  3. hysteresis over each cell's consecutive days (`levels.apply_hysteresis`), so the published `level` is the state
     of the machine fed with the raw level of steps 1-2 (`raw_level` keeps it for the flapping comparison).
The rows keep the order of `features`; the result does not depend on that order.
"""
from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd

from . import confidence as cf
from . import levels as lv
from .config import DEFAULT_UNCERTAIN_PERCENTILE, AlertConfig, upper_column
from .stations import nearby_station_summary, station_states

SCORE_COLUMNS = ["risk", "risk_lo", "risk_hi", "risk_per_100k"]
CARRY_COLUMNS = ["region", "split", "kind", "weight", "universe_size", "in_buffer", "is_positive_cell_day", "in_domain",
                 "is_window_positive_cell", "label", "rain_source"]
EVIDENCE = {"imd_acc_1": "src_imd_acc_1", "chirps_acc_1": "src_chi_acc_1", "station_max_1": "integ_max_st_rain_1_100km",
            "imd_acc_3": "src_imd_acc_3", "chirps_acc_3": "src_chi_acc_3", "station_trw_3": "integ_trw_rain_3",
            "station_trw_1": "integ_trw_rain_1", "dis_ratio_3": "src_dis_ratio_3"}
TIER_CODES = ("", "risk_above_watch", "risk_above_warning", "risk_above_emergency")


def _clean(values) -> list:
    """Python numbers with None for NaN, for strict JSON."""
    return [None if (v is None or not math.isfinite(v)) else float(v) for v in np.asarray(values, dtype=np.float64)]


def _split(text: str) -> list[str]:
    return text.split(";") if text else []


def _check_inputs(features: pd.DataFrame, scores: pd.DataFrame, thresholds: lv.Thresholds | lv.RegionThresholds) -> None:
    required = ("cell_id", "date", "lat", "lon") + (("region",) if isinstance(thresholds, lv.RegionThresholds) else ())
    for column in required:
        if column not in features.columns:
            raise ValueError(f"feature frame lacks column {column!r}")
    missing = [c for c in SCORE_COLUMNS if c not in scores.columns]
    if missing:
        raise ValueError(f"scores lack columns {missing}")
    if len(scores) != len(features) or not scores.index.equals(features.index):
        raise ValueError("scores must have the same rows (index) as the feature frame")
    if not np.isfinite(scores[SCORE_COLUMNS].to_numpy(dtype=np.float64)).all():
        raise ValueError("scores contain non-finite values")


def uncertain_bound(scores: pd.DataFrame, config: AlertConfig) -> np.ndarray:
    """The score the `uncertain_high` rule tests against Watch: `risk_hi` (the model's 90th percentile), the column of
    another percentile of the calibrated ensemble (`config.uncertain_percentile`), or the point risk itself when the
    rule is switched off (it then never exceeds the point level)."""
    percentile = config.uncertain_percentile
    if percentile is None:
        return scores["risk"].to_numpy(dtype=np.float64)
    column = "risk_hi" if percentile == DEFAULT_UNCERTAIN_PERCENTILE else upper_column(percentile)
    if column not in scores.columns:
        raise ValueError(f"scores lack column {column!r}, the {percentile:g}th percentile of the ensemble that "
                         "`uncertain_percentile` names")
    return scores[column].to_numpy(dtype=np.float64)


def reasons_json(out: pd.DataFrame, shap: list) -> list[str]:
    risk = {k: _clean(out[c]) for k, c in (("point", "risk"), ("lo", "risk_lo"), ("hi", "risk_hi"),
                                           ("per_100k", "risk_per_100k"))}
    evidence = {name: _clean(out[name]) for name in EVIDENCE}
    rain_source = out["rain_source"].tolist() if "rain_source" in out.columns else [None] * len(out)
    column = {name: out[name].tolist() for name in ("level_name", "raw_level", "reason_codes", "confidence",
                                                    "confidence_causes", "n_stations", "n_trusted", "n_flagged_7d",
                                                    "n_ood_stations", "flagged_types")}   # lists: per-row .iat is slow
    texts = []
    for i in range(len(out)):
        one_day = [v for v in (evidence["imd_acc_1"][i], evidence["chirps_acc_1"][i], evidence["station_max_1"][i])
                   if v is not None]
        sources = {name: evidence[name][i] for name in EVIDENCE}
        sources.update(rain_source=rain_source[i], max_1day=max(one_day) if one_day else None,
                       spread_1day=max(one_day) - min(one_day) if len(one_day) > 1 else None)
        texts.append(json.dumps({
            "level": column["level_name"][i], "raw_level": lv.level_name(column["raw_level"][i]),
            "codes": _split(column["reason_codes"][i]),
            "risk": {k: v[i] for k, v in risk.items()},
            "confidence": {"state": column["confidence"][i], "causes": _split(column["confidence_causes"][i])},
            "sources": sources,
            "sensor_trust": {"n_stations": int(column["n_stations"][i]), "n_trusted": int(column["n_trusted"][i]),
                             "n_flagged_7d": int(column["n_flagged_7d"][i]),
                             "n_out_of_distribution": int(column["n_ood_stations"][i]),
                             "flagged_types": [t for t in column["flagged_types"][i].split(",") if t]},
            "shap": shap[i]}, allow_nan=False))
    return texts


def run_alerts(features: pd.DataFrame, scores: pd.DataFrame, station_outputs: pd.DataFrame | None, *,
               stations: pd.DataFrame | None = None, thresholds: lv.Thresholds | lv.RegionThresholds, config: AlertConfig,
               contributions: list[list[dict]] | None = None, hysteresis: bool = True) -> pd.DataFrame:
    """Alert table, one row per feature row (see the module doc). `hysteresis=False` publishes the raw level."""
    _check_inputs(features, scores, thresholds)
    n = len(features)
    if contributions is not None and len(contributions) != n:
        raise ValueError("contributions must have one entry per row")
    if station_outputs is not None and len(station_outputs):
        if stations is None:
            raise ValueError("station outputs given without station coordinates (`stations`)")
        states = station_states(station_outputs, config)
        n_ood, flagged_types = nearby_station_summary(features["lat"], features["lon"], features["date"], states,
                                                      stations, config.radius_km)
    else:
        n_ood, flagged_types = np.zeros(n, dtype=np.int32), [""] * n
    assessed = cf.assess(features, n_ood, config)
    risk = scores["risk"].to_numpy(dtype=np.float64)
    region = features["region"].to_numpy() if isinstance(thresholds, lv.RegionThresholds) else None
    from_risk, uncertain = lv.raw_level(risk, uncertain_bound(scores, config), thresholds, region)
    raw = np.where(assessed["blind"].to_numpy(), np.maximum(from_risk, lv.WATCH), from_risk).astype(np.int8)
    level = (lv.apply_hysteresis(features["cell_id"].to_numpy(), features["date"], raw, risk, thresholds,
                                 config.exit_factor, config.exit_days, region) if hysteresis else raw)
    point_level = lv.level_from_risk(risk, thresholds, region)
    codes = [";".join(c for c in (TIER_CODES[p], lv.UNCERTAIN_HIGH if u else "", b, "hysteresis_hold" if h else "") if c)
             for p, u, b, h in zip(point_level, uncertain, assessed["blind_codes"], level > raw)]
    out = pd.DataFrame({"cell_id": features["cell_id"].to_numpy(), "date": pd.to_datetime(features["date"]).to_numpy(),
                        "lat": features["lat"].to_numpy(dtype=np.float64),
                        "lon": features["lon"].to_numpy(dtype=np.float64)}, index=features.index)
    for column in CARRY_COLUMNS:
        if column in features.columns:
            out[column] = features[column].to_numpy()
    for column in SCORE_COLUMNS:
        out[column] = scores[column].to_numpy(dtype=np.float64)
    out["raw_level"], out["level"] = raw, level
    out["level_name"] = np.array(lv.LEVEL_NAMES, dtype=object)[level]
    out["uncertain_high"] = uncertain
    out["blind"] = assessed["blind"].to_numpy()
    out["blind_escalated"] = assessed["blind"].to_numpy() & (from_risk < lv.WATCH)
    out["confidence"] = assessed["confidence"].to_numpy()
    out["confidence_causes"] = assessed["causes"].to_numpy()
    out["reason_codes"] = codes
    out["n_stations"], out["n_trusted"] = assessed["n_stations"].to_numpy(), assessed["n_trusted"].to_numpy()
    out["n_flagged_7d"] = (features["integ_n_flagged_100km_7d"].fillna(0).to_numpy(dtype=np.int32)
                           if "integ_n_flagged_100km_7d" in features.columns else np.zeros(n, dtype=np.int32))
    out["n_ood_stations"] = np.asarray(n_ood, dtype=np.int32)
    out["flagged_types"] = flagged_types
    for name, source in EVIDENCE.items():
        out[name] = features[source].to_numpy(dtype=np.float64) if source in features.columns else np.nan
    shap = list(contributions) if contributions is not None else [[] for _ in range(n)]
    out["shap_json"] = [json.dumps(s, allow_nan=False) for s in shap]
    out["reasons_json"] = reasons_json(out, shap)
    return out
