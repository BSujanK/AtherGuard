"""Data confidence (High / Degraded / Insufficient) and the blind-escalation rule, per cell-day.

Inputs are columns of the feature frame (`src_imd_acc_*`, `src_chi_acc_*`, `src_dis_ratio_3`, `rain_acc_1` and the
station summary `integ_*`; the `integ_` columns may be absent, which means no station information) plus the number of
out-of-distribution stations near the cell (`n_ood`, from `stations.nearby_station_summary`).

Confidence
  Insufficient  no valid rain source for the cell on D, OR every nearby observed station is flagged while the two
                sources disagree strongly.
  High          (both sources valid AND src_dis_ratio_3 inside its development 5-95% range, OR a trusted station within
                the radius agrees with the grid) AND no nearby station flagged in the last 7 days AND no nearby
                out-of-distribution station.
  Degraded      everything else: a rain source missing or strong disagreement with no agreeing trusted station,
                nearby flagged stations, or a nearby out-of-distribution station.
Causes are listed only for Degraded and Insufficient rows: a High row (for example strong source disagreement that an
agreeing trusted station overrides) carries none. A trusted station "agrees" when |station - grid| <= max(agree_abs_mm, agree_rel x the larger of the two) on day D
(`integ_trw_rain_1` is the trust-weighted mean of the usable, i.e. unflagged, stations; `rain_acc_1` is the grid).

Blind escalation (no silent Normal when blind): confidence Insufficient or Degraded AND ANY independent source shows
heavy rain: the IMD, the CHIRPS or the largest usable station reading of the day >= `heavy_acc1_mm`, or the 3-day IMD,
CHIRPS or trust-weighted station total >= `heavy_acc3_mm`. The test uses every source (the maximum), never the one
the hazard model happened to use. Reason codes: `sources_disagree_heavy_rain` when a source cause is present (missing
source, strong disagreement), `sensors_untrusted_heavy_rain` when a sensor cause is present (flagged or out-of-
distribution or all-untrusted stations); both when both apply.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import AlertConfig

HIGH, DEGRADED, INSUFFICIENT = "High", "Degraded", "Insufficient"
SOURCE_CAUSES = ("no_valid_source", "imd_missing", "chirps_missing", "sources_disagree")
SENSOR_CAUSES = ("stations_flagged_nearby", "station_out_of_distribution", "all_nearby_stations_untrusted")
BLIND_SOURCES = "sources_disagree_heavy_rain"
BLIND_SENSORS = "sensors_untrusted_heavy_rain"
REQUIRED = ["src_imd_acc_1", "src_chi_acc_1", "src_dis_ratio_3", "rain_acc_1"]
OPTIONAL = ["src_imd_acc_3", "src_chi_acc_3", "integ_n_st_100km", "integ_frac_trusted_100km", "integ_trw_rain_1",
            "integ_trw_rain_3", "integ_max_st_rain_1_100km", "integ_n_flagged_100km_7d"]


def _col(frame: pd.DataFrame, name: str) -> np.ndarray:
    return frame[name].to_numpy(dtype=np.float64) if name in frame.columns else np.full(len(frame), np.nan)


def _join_codes(parts: list[tuple[np.ndarray, str]], n: int) -> list[str]:
    out = np.full(n, "", dtype=object)
    for mask, code in parts:
        out = np.where(mask, np.where(out == "", code, out + ";" + code), out)
    return out.tolist()


def _any_at_least(limit: float, *arrays: np.ndarray) -> np.ndarray:
    with np.errstate(invalid="ignore"):
        return np.any([a >= limit for a in arrays], axis=0)


def assess(frame: pd.DataFrame, n_ood, config: AlertConfig) -> pd.DataFrame:
    """Per row: confidence, causes (`;`-joined), blind (bool), blind_codes (`;`-joined) and the boolean components
    imd_valid, chirps_valid, disagree, station_agrees, station_problem, heavy_rain, n_stations, n_trusted."""
    missing = [c for c in REQUIRED if c not in frame.columns]
    if missing:
        raise ValueError(f"feature frame lacks columns {missing}")
    n = len(frame)
    n_ood = np.asarray(n_ood, dtype=np.int64)
    if n_ood.shape != (n,):
        raise ValueError("n_ood must have one entry per row")
    c = {name: _col(frame, name) for name in REQUIRED + OPTIONAL}
    imd_valid, chirps_valid = np.isfinite(c["src_imd_acc_1"]), np.isfinite(c["src_chi_acc_1"])
    any_source, both = imd_valid | chirps_valid, imd_valid & chirps_valid
    ratio = c["src_dis_ratio_3"]
    with np.errstate(invalid="ignore"):
        disagree = both & ((ratio < config.dis_ratio_lo) | (ratio > config.dis_ratio_hi))
    n_st = np.nan_to_num(c["integ_n_st_100km"], nan=0.0)
    frac = c["integ_frac_trusted_100km"]
    n_trusted = np.where(np.isfinite(frac), np.rint(n_st * np.nan_to_num(frac)), 0.0)
    all_untrusted = (n_st >= 1) & (n_trusted == 0)
    station, grid = c["integ_trw_rain_1"], c["rain_acc_1"]
    with np.errstate(invalid="ignore"):
        tolerance = np.maximum(config.agree_abs_mm, config.agree_rel * np.fmax(station, grid))
        station_agrees = np.isfinite(station) & np.isfinite(grid) & (np.abs(station - grid) <= tolerance)
    flagged_nearby = np.nan_to_num(c["integ_n_flagged_100km_7d"], nan=0.0) > 0
    ood_nearby = n_ood > 0
    station_problem = flagged_nearby | ood_nearby

    insufficient = ~any_source | (all_untrusted & disagree)
    high = ~insufficient & ~station_problem & ((both & ~disagree) | station_agrees)
    confidence = np.where(insufficient, INSUFFICIENT, np.where(high, HIGH, DEGRADED))

    causes = _join_codes([
        (~any_source, "no_valid_source"), (any_source & ~imd_valid, "imd_missing"),
        (any_source & ~chirps_valid, "chirps_missing"), (disagree, "sources_disagree"),
        (flagged_nearby, "stations_flagged_nearby"), (ood_nearby, "station_out_of_distribution"),
        (all_untrusted, "all_nearby_stations_untrusted")], n)
    causes = np.where(confidence == HIGH, "", np.asarray(causes, dtype=object)).tolist()   # causes explain why not High
    source_cause = ~any_source | ~both | disagree
    sensor_cause = station_problem | all_untrusted
    heavy = (_any_at_least(config.heavy_acc1_mm, c["src_imd_acc_1"], c["src_chi_acc_1"], c["integ_max_st_rain_1_100km"])
             | _any_at_least(config.heavy_acc3_mm, c["src_imd_acc_3"], c["src_chi_acc_3"], c["integ_trw_rain_3"]))
    blind = (confidence != HIGH) & heavy
    blind_codes = _join_codes([(blind & source_cause, BLIND_SOURCES), (blind & sensor_cause, BLIND_SENSORS)], n)
    return pd.DataFrame({"confidence": confidence, "causes": causes, "blind": blind, "blind_codes": blind_codes,
                         "imd_valid": imd_valid, "chirps_valid": chirps_valid, "disagree": disagree,
                         "station_agrees": station_agrees, "station_problem": station_problem,
                         "heavy_rain": heavy, "n_stations": n_st.astype(np.int32),
                         "n_trusted": n_trusted.astype(np.int32)}, index=frame.index)
