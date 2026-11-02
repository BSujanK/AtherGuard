"""Model-agnostic case scoring: levels per cell-day and the case metrics, for any hazard scorer.

    result = score_case("kerala_2018", scorer, thresholds)

`scorer` is a callable `scorer(frame) -> DataFrame[risk, risk_lo, risk_hi, risk_per_100k]` (same length and order as the
frame) or an object with a `score_frame(frame)` method (the `aetherguard.hazard` contract). `thresholds` maps `watch`,
`warning`, `emergency` to calibrated-risk thresholds (strictly increasing); a day's level is the highest threshold its
`risk` reaches: 0 Normal, 1 Watch, 2 Warning, 3 Emergency (`level_hi` does the same with the upper bound `risk_hi`, as
information only). The alert engine's hysteresis and blind-escalation rules are NOT applied here.

Kerala 2018 (positive cell-days of the case file):
  * an event is DETECTED when the cell or any of its 8 neighbours is at Watch+ on the event day;
  * `alert_days_before` = consecutive days at Watch+ (footprint = cell + 8 neighbours) immediately before the event day,
    looking back at most 7 days and only over days present in the case table;
  * `first_alert_lead_days` = event day minus the first Watch+ day within the 7 days before and including the event day
    (0 = first alert on the event day; NaN = no alert in that span);
  * alerted area per day: cells and share of the case cells at Watch+ / Warning+ / Emergency.
Wayanad 2024: the risk / level series of the cells within 10 km of the focus point, the maximum over the whole box, and
the first day at Watch+ and Warning+ for each.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..grid import cell_center, neighbours
from ..integrity.neighbours import haversine_km
from . import openmeteo as om
from .series import load_case_frame

LEVEL_NAMES = ("Normal", "Watch", "Warning", "Emergency")
THRESHOLD_KEYS = ("watch", "warning", "emergency")
SCORE_COLUMNS = ("risk", "risk_lo", "risk_hi", "risk_per_100k")
LOOKBACK_DAYS = 7
WAYANAD_RADIUS_KM = 10.0


@dataclass
class CaseResult:
    case: str
    levels: pd.DataFrame                       # cell_id, date, scores, level, level_name, level_hi
    metrics: dict
    events: pd.DataFrame | None = None         # Kerala: one row per positive cell-day
    series: pd.DataFrame | None = None         # Wayanad: one row per day
    thresholds: dict = field(default_factory=dict)


def check_thresholds(thresholds: dict) -> dict[str, float]:
    missing = [k for k in THRESHOLD_KEYS if k not in thresholds]
    if missing:
        raise ValueError(f"thresholds need {THRESHOLD_KEYS}, missing {missing}")
    values = [float(thresholds[k]) for k in THRESHOLD_KEYS]
    if not all(np.isfinite(values)) or any(b <= a for a, b in zip(values, values[1:])):
        raise ValueError(f"thresholds must be finite and strictly increasing (watch < warning < emergency), got {values}")
    return dict(zip(THRESHOLD_KEYS, values))


def levels_from_risk(risk, thresholds: dict) -> np.ndarray:
    """Level 0..3 per value; NaN risk is level 0 (never an alert)."""
    t = check_thresholds(thresholds)
    risk = np.asarray(risk, dtype=np.float64)
    with np.errstate(invalid="ignore"):
        level = (risk >= t["watch"]).astype(np.int8) + (risk >= t["warning"]) + (risk >= t["emergency"])
    return level.astype(np.int8)


def run_scorer(scorer, frame: pd.DataFrame) -> pd.DataFrame:
    scores = scorer.score_frame(frame) if hasattr(scorer, "score_frame") else scorer(frame)
    missing = [c for c in SCORE_COLUMNS if c not in scores.columns]
    if missing:
        raise ValueError(f"the scorer did not return {missing}")
    if len(scores) != len(frame):
        raise ValueError(f"the scorer returned {len(scores)} rows for {len(frame)} cell-days")
    return scores[list(SCORE_COLUMNS)].reset_index(drop=True)


def _level_matrix(levels: pd.DataFrame, column: str = "level"):
    wide = levels.pivot(index="cell_id", columns="date", values=column)
    return wide, {int(c): i for i, c in enumerate(wide.index)}, {pd.Timestamp(d): j for j, d in enumerate(wide.columns)}


def kerala_metrics(levels: pd.DataFrame, frame: pd.DataFrame) -> tuple[dict, pd.DataFrame]:
    wide, row_of, col_of = _level_matrix(levels)
    matrix = wide.to_numpy(dtype=np.float64)                       # NaN = the cell-day is not in the case table
    dates = sorted(col_of)
    events = frame[frame["is_positive_cell_day"].astype(bool)][["cell_id", "date"]].reset_index(drop=True)
    rows = []
    for event in events.itertuples():
        cell, day = int(event.cell_id), pd.Timestamp(event.date)
        footprint = [row_of[c] for c in (cell, *neighbours(cell)) if c in row_of]

        def alert(d):
            j = col_of.get(d)
            if j is None or not footprint:
                return None
            return bool(np.nanmax(np.where(np.isnan(matrix[footprint, j]), -1, matrix[footprint, j])) >= 1)

        own_level = matrix[row_of[cell], col_of[day]] if cell in row_of and day in col_of else np.nan
        on_day = alert(day)
        before = 0
        for back in range(1, LOOKBACK_DAYS + 1):
            state = alert(day - pd.Timedelta(days=back))
            if state is not True:
                break
            before += 1
        span = [alert(day - pd.Timedelta(days=back)) for back in range(LOOKBACK_DAYS, -1, -1)]
        first = next((LOOKBACK_DAYS - i for i, state in enumerate(span) if state), None)
        rows.append({"cell_id": cell, "date": day, "own_level": own_level, "detected": bool(on_day),
                     "alert_days_before": before, "first_alert_lead_days": np.nan if first is None else float(first),
                     "detected_within_7d": first is not None,
                     "days_available_before": sum(1 for back in range(1, LOOKBACK_DAYS + 1)
                                                  if day - pd.Timedelta(days=back) in col_of)})
    table = pd.DataFrame(rows)
    area = []
    for day in dates:
        column = matrix[:, col_of[day]]
        present = ~np.isnan(column)
        n = int(present.sum())
        area.append({"date": str(day.date()), "cells": n,
                     **{f"{name.lower()}_cells": int((column[present] >= k).sum()) for k, name in ((1, "Watch"), (2, "Warning"), (3, "Emergency"))},
                     **{f"{name.lower()}_share": float((column[present] >= k).mean()) if n else float("nan")
                        for k, name in ((1, "Watch"), (2, "Warning"), (3, "Emergency"))}})
    area_frame = pd.DataFrame(area)
    leads = table.loc[table["first_alert_lead_days"].notna(), "first_alert_lead_days"]
    metrics = {"n_events": int(len(table)), "detected_on_event_day": int(table["detected"].sum()),
               "detected_share": float(table["detected"].mean()) if len(table) else float("nan"),
               "own_cell_at_watch": int((table["own_level"] >= 1).sum()),
               "detected_within_7d": int(table["detected_within_7d"].sum()),
               "median_first_alert_lead_days": float(leads.median()) if len(leads) else float("nan"),
               "median_alert_days_before": float(table["alert_days_before"].median()) if len(table) else float("nan"),
               "alerted_area": {"cells_in_case": int(matrix.shape[0]), "days": len(dates),
                                "mean_watch_share": float(area_frame["watch_share"].mean()),
                                "max_watch_share": float(area_frame["watch_share"].max()),
                                "mean_warning_share": float(area_frame["warning_share"].mean()),
                                "mean_watch_cells": float(area_frame["watch_cells"].mean()),
                                "per_day": area}}
    return metrics, table


def wayanad_metrics(levels: pd.DataFrame, frame: pd.DataFrame, lat: float, lon: float,
                    radius_km: float = WAYANAD_RADIUS_KM) -> tuple[dict, pd.DataFrame]:
    cells = frame["cell_id"].unique()
    lats, lons = cell_center(cells)
    distance = pd.Series(haversine_km(lat, lon, lats, lons), index=cells)
    near = distance[distance <= radius_km].index
    focus = int(distance.idxmin())
    rows = []
    for day, part in levels.groupby("date"):
        around = part[part["cell_id"].isin(near)]
        at_focus = part[part["cell_id"] == focus]
        rows.append({"date": day, "focus_risk": float(at_focus["risk"].iloc[0]) if len(at_focus) else np.nan,
                     "focus_level": int(at_focus["level"].iloc[0]) if len(at_focus) else 0,
                     "near_max_risk": float(around["risk"].max()) if len(around) else np.nan,
                     "near_max_level": int(around["level"].max()) if len(around) else 0,
                     "near_max_risk_hi": float(around["risk_hi"].max()) if len(around) else np.nan,
                     "box_max_risk": float(part["risk"].max()), "box_max_level": int(part["level"].max()),
                     "box_cells_watch_plus": int((part["level"] >= 1).sum()), "box_cells": int(len(part))})
    series = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)

    def first(column, k):
        hit = series.loc[series[column] >= k, "date"]
        return str(hit.iloc[0].date()) if len(hit) else None

    metrics = {"focus_cell": focus, "focus_distance_km": float(distance.min()), "cells_within_radius": int(len(near)),
               "radius_km": radius_km, "box_cells": int(len(cells)),
               "first_watch_plus": {"focus": first("focus_level", 1), "within_10km": first("near_max_level", 1),
                                    "box": first("box_max_level", 1)},
               "first_warning_plus": {"focus": first("focus_level", 2), "within_10km": first("near_max_level", 2),
                                      "box": first("box_max_level", 2)},
               "peak_near_risk": float(series["near_max_risk"].max()),
               "peak_near_date": str(series.loc[series["near_max_risk"].idxmax(), "date"].date()),
               "peak_box_risk": float(series["box_max_risk"].max())}
    return metrics, series


def score_case(case_name: str, scorer, thresholds: dict, frame: pd.DataFrame | None = None,
               focus: tuple[float, float] | None = None) -> CaseResult:
    """Levels per cell-day and the case metrics (see the module doc). `frame` defaults to the frozen case frame."""
    if case_name not in ("kerala_2018", "wayanad_2024"):
        raise ValueError(f"unknown case {case_name!r}")
    t = check_thresholds(thresholds)
    frame = load_case_frame(case_name) if frame is None else frame
    scores = run_scorer(scorer, frame)
    levels = pd.concat([frame[["cell_id", "date"]].reset_index(drop=True), scores], axis=1)
    levels["level"] = levels_from_risk(levels["risk"], t)
    levels["level_name"] = pd.Categorical.from_codes(levels["level"].to_numpy(), LEVEL_NAMES)
    levels["level_hi"] = levels_from_risk(levels["risk_hi"], t)
    if case_name == "kerala_2018":
        metrics, events = kerala_metrics(levels, frame)
        return CaseResult(case_name, levels, metrics, events=events, thresholds=t)
    point = focus or (om.WAYANAD["lat"], om.WAYANAD["lon"])
    metrics, series = wayanad_metrics(levels, frame, *point)
    return CaseResult(case_name, levels, metrics, series=series, thresholds=t)
