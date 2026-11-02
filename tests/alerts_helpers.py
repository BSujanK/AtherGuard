"""Hand-made feature rows, scores and station outputs with the schema the alert engine consumes."""
from __future__ import annotations

import numpy as np
import pandas as pd

from aetherguard.alerts import levels as lv
from aetherguard.alerts.config import AlertConfig

CONFIG = AlertConfig(exit_factor=0.8, exit_days=2, radius_km=100.0, ood_window_days=90, ood_multiple=3.0,
                     ood_min_observed_days=30, engine_target_flag_rate=0.01, dis_ratio_lo=0.12, dis_ratio_hi=12.0,
                     heavy_acc1_mm=40.0, heavy_acc3_mm=80.0, agree_abs_mm=2.0, agree_rel=0.5)
THRESHOLDS = lv.Thresholds(watch=1e-5, warning=4e-5, emergency=1e-4, source="test")

HEALTHY = {"rain_source": "imd", "rain_acc_1": 5.0, "rain_acc_3": 9.0, "src_imd_acc_1": 5.0, "src_chi_acc_1": 5.5,
           "src_imd_acc_3": 9.0, "src_chi_acc_3": 9.5, "src_dis_ratio_3": 1.0, "integ_n_st_100km": 2.0,
           "integ_frac_trusted_100km": 1.0, "integ_trw_rain_1": 5.0, "integ_trw_rain_3": 9.0,
           "integ_st_minus_grid_1": 0.0, "integ_max_st_rain_1_100km": 5.5, "integ_n_flagged_100km_7d": 0.0,
           "integ_dist_nearest_km": 12.0}


def feature_rows(overrides: list[dict] | None = None, n: int | None = None, cell_id=1, start="2024-07-01",
                 lat=11.5, lon=76.0, region="western_ghats") -> pd.DataFrame:
    """One row per override dict (merged over HEALTHY), consecutive days of one cell."""
    overrides = overrides if overrides is not None else [{} for _ in range(n or 1)]
    rows = [{**HEALTHY, **o} for o in overrides]
    frame = pd.DataFrame(rows)
    frame.insert(0, "cell_id", np.asarray(cell_id) if np.ndim(cell_id) else cell_id)
    frame.insert(1, "date", pd.date_range(start, periods=len(rows)))
    frame["lat"], frame["lon"], frame["region"] = lat, lon, region
    return frame


def scores_for(frame: pd.DataFrame, risk, hi=None, lo=None) -> pd.DataFrame:
    risk = np.broadcast_to(np.asarray(risk, dtype=float), (len(frame),)).copy()
    hi = risk * 1.5 if hi is None else np.broadcast_to(np.asarray(hi, dtype=float), (len(frame),)).copy()
    lo = risk * 0.5 if lo is None else np.broadcast_to(np.asarray(lo, dtype=float), (len(frame),)).copy()
    return pd.DataFrame({"risk": risk, "risk_lo": lo, "risk_hi": hi, "risk_per_100k": 1e5 * risk}, index=frame.index)


def station_outputs(spec: dict[str, dict], days: int, start="2024-01-01") -> pd.DataFrame:
    """Engine-output-shaped rows. `spec[station]` = {"flag_every": k (flag each k-th day), "fault_type": ...,
    "missing_from": day index from which the station has no readings}."""
    index = pd.date_range(start, periods=days)
    rows = []
    for station, s in spec.items():
        for d, date in enumerate(index):
            observed = d < s.get("missing_from", days)
            flagged = observed and s.get("flag_every") is not None and d % s["flag_every"] == 0
            rows.append({"station": station, "date": date, "trust": (0.1 if flagged else 0.95) if observed else np.nan,
                         "flagged": bool(flagged), "genuine_extreme": False,
                         "fault_type": s.get("fault_type", "spike") if flagged else "", "reasons": "model" if flagged else ""})
    return pd.DataFrame(rows)


STATIONS = pd.DataFrame({"id": ["A", "B", "FAR"], "lat": [11.5, 11.6, 20.0], "lon": [76.0, 76.1, 90.0]})
