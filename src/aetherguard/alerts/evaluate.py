"""Evaluation of the alert tables (pure functions over alert frames; `report.py` assembles them from the replay store).

Event detection: an event (cell, date D) is detected when its cell has a Watch-or-higher alert on D or any of the
`lead_days` days before; the lead time is D minus the first such day. Only days present in the table count, so a table
that holds just the event day can only show lead 0 (`days_available` says how many days were there to look at).

Window detection (2023 India window): a window cell is detected when an alert of Watch or higher occurs in it or in
one of its 8 neighbours on any day of the window.

Flapping: `n_changes` is the number of day-to-day level changes inside consecutive-day runs of a cell; a flap is a
Watch+ alert that switches off and on again within `flap_window_days` (counted once per re-activation).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .. import grid
from ..hazard import data as hd
from . import costloss as cl
from . import levels as lv

KM_PER_DEG = 111.195


def cell_area_km2(lat) -> np.ndarray:
    """Area of a 0.05-degree grid cell centred at `lat`."""
    side = grid.CELL_DEG * KM_PER_DEG
    return side * side * np.cos(np.radians(np.asarray(lat, dtype=np.float64)))


def _events(events: pd.DataFrame) -> pd.DataFrame:
    out = events[["cell_id", "date"]].copy()
    out["date"] = pd.to_datetime(out["date"])
    return out.drop_duplicates().reset_index(drop=True)


def event_detection(alerts: pd.DataFrame, events: pd.DataFrame, lead_days: int, min_level: int = lv.WATCH
                    ) -> tuple[pd.DataFrame, dict]:
    """Per-event frame (detected, first_alert_date, lead_days, days_available, peak_level) and its summary."""
    ev = _events(events)
    ev["event"] = np.arange(len(ev))
    cols = alerts[["cell_id", "date", "level"]].rename(columns={"date": "alert_date"})
    joined = ev.merge(cols, on="cell_id", how="left")
    delta = (joined["date"] - joined["alert_date"]).dt.days
    inside = joined[(delta >= 0) & (delta <= lead_days)].assign(lead=lambda f: (f["date"] - f["alert_date"]).dt.days)
    hits = inside[inside["level"] >= min_level]
    first = hits.sort_values("alert_date").groupby("event").first()
    per = ev.set_index("event")
    per["days_available"] = inside.groupby("event").size().reindex(per.index, fill_value=0)
    per["peak_level"] = inside.groupby("event")["level"].max().reindex(per.index)
    per["detected"] = per.index.isin(first.index)
    per["first_alert_date"] = first["alert_date"].reindex(per.index)
    per["lead_days"] = first["lead"].reindex(per.index)
    per = per.reset_index(drop=True)
    n = len(per)
    det = per[per["detected"]]
    summary = {"n_events": n, "n_detected": int(len(det)), "detection_rate": float(len(det) / n) if n else None,
               "n_with_history": int((per["days_available"] > 1).sum()),
               "median_lead_days": float(det["lead_days"].median()) if len(det) else None,
               "mean_lead_days": float(det["lead_days"].mean()) if len(det) else None,
               "n_lead_at_least_1_day": int((det["lead_days"] >= 1).sum()),
               "detected_by_level": {lv.level_name(k): int((per["peak_level"] >= k).sum())
                                     for k in (lv.WATCH, lv.WARNING, lv.EMERGENCY)},
               "lead_days": lead_days}
    return per, summary


def window_detection(alerts: pd.DataFrame, positive_cells, start, end) -> dict:
    """Window-level detection (see the module doc) and the alert behaviour of every other cell in the table."""
    day = pd.to_datetime(alerts["date"])
    inside = alerts[(day >= pd.Timestamp(start)) & (day <= pd.Timestamp(end))]
    alerted = set(inside.loc[inside["level"] >= lv.WATCH, "cell_id"].unique().tolist())
    positives = sorted({int(c) for c in positive_cells})
    detected = [c for c in positives if alerted & {c, *grid.neighbours(c)}]
    others = inside[~inside["cell_id"].isin(positives)]
    other_cells = others["cell_id"].nunique()
    return {"n_positive_cells": len(positives), "n_detected": len(detected),
            "detection_rate": len(detected) / len(positives) if positives else None,
            "n_other_cells": int(other_cells),
            "other_cells_alerted_any_day": (float(others.loc[others["level"] >= lv.WATCH, "cell_id"].nunique() / other_cells)
                                            if other_cells else None),
            "other_cell_days_alerted": float((others["level"] >= lv.WATCH).mean()) if len(others) else None,
            "note": "false alerts are an upper bound: the inventory is partial"}


def alerted_area(alerts: pd.DataFrame) -> dict:
    """Share of the table's cells and their area at Watch+ and Warning+ per day (summarised over the days)."""
    area = cell_area_km2(alerts["lat"])
    watch, warning = (alerts["level"] >= lv.WATCH).to_numpy(), (alerts["level"] >= lv.WARNING).to_numpy()
    daily = pd.DataFrame({"date": alerts["date"].to_numpy(), "cells": 1, "watch": watch, "warning": warning,
                          "watch_km2": area * watch, "warning_km2": area * warning, "total_km2": area}
                         ).groupby("date").agg(cells=("cells", "sum"), watch_share=("watch", "mean"),
                                               warning_share=("warning", "mean"), watch_km2=("watch_km2", "sum"),
                                               warning_km2=("warning_km2", "sum"), total_km2=("total_km2", "sum"))
    peak = daily["watch_km2"].idxmax()
    return {"n_days": int(len(daily)), "cells_per_day_mean": float(daily["cells"].mean()),
            "watch_share_mean": float(daily["watch_share"].mean()), "watch_share_max": float(daily["watch_share"].max()),
            "warning_share_mean": float(daily["warning_share"].mean()),
            "watch_km2_mean": float(daily["watch_km2"].mean()), "watch_km2_max": float(daily["watch_km2"].max()),
            "warning_km2_mean": float(daily["warning_km2"].mean()), "total_km2_mean": float(daily["total_km2"].mean()),
            "peak_day": pd.Timestamp(peak).strftime("%Y-%m-%d")}


def _flaps(on: np.ndarray, window: int) -> int:
    """Number of on -> off (1..window days) -> on patterns in one consecutive-day run."""
    idx = np.flatnonzero(on)
    if len(idx) < 2:
        return 0
    gaps = np.diff(idx) - 1
    return int(((gaps >= 1) & (gaps <= window)).sum())


def flapping(alerts: pd.DataFrame, level_column: str, window: int) -> dict:
    """Level changes and Watch+ flaps of `level_column` inside consecutive-day runs of each cell."""
    ordered = alerts.sort_values(["cell_id", "date"])
    cell = ordered["cell_id"].to_numpy()
    day = ordered["date"].to_numpy("datetime64[D]").astype(np.int64)
    level = ordered[level_column].to_numpy()
    same_run = np.zeros(len(ordered), dtype=bool)
    same_run[1:] = (cell[1:] == cell[:-1]) & (day[1:] - day[:-1] == 1)
    changes = same_run & np.concatenate([[False], level[1:] != level[:-1]])
    starts = np.flatnonzero(~same_run)
    ends = np.append(starts[1:], len(ordered))
    on = level >= lv.WATCH
    flaps = sum(_flaps(on[s:e], window) for s, e in zip(starts, ends))
    n = len(ordered)
    return {"cell_days": int(n), "n_changes": int(changes.sum()), "n_flaps": int(flaps),
            "changes_per_1000_cell_days": float(1000 * changes.sum() / n) if n else None,
            "flaps_per_1000_cell_days": float(1000 * flaps / n) if n else None}


def flapping_comparison(alerts: pd.DataFrame, window: int) -> dict:
    """Flapping of the published level (with hysteresis) and of the raw level (without)."""
    return {"with_hysteresis": flapping(alerts, "level", window), "without_hysteresis": flapping(alerts, "raw_level", window)}


def blind_escalations(alerts: pd.DataFrame, events: pd.DataFrame | None, lead_days: int) -> dict:
    """Cell-days where the blind rule applied (`blind`) and where it actually raised the level (`blind_escalated`),
    and how many of the latter precede or coincide with an event of their cell within `lead_days`."""
    out = {"n_blind": int(alerts["blind"].sum()), "n_escalated": int(alerts["blind_escalated"].sum()),
           "n_cell_days": int(len(alerts))}
    escalated = alerts.loc[alerts["blind_escalated"], ["cell_id", "date"]]
    out["n_cells_escalated"] = int(escalated["cell_id"].nunique())
    if events is None:
        out.update(n_coinciding_event=None, n_events_covered=None)
        return out
    ev = _events(events).rename(columns={"date": "event_date"})
    joined = escalated.merge(ev, on="cell_id", how="inner")
    delta = (joined["event_date"] - joined["date"]).dt.days
    near = joined[(delta >= 0) & (delta <= lead_days)]
    out["n_coinciding_event"] = int(len(near.drop_duplicates(["cell_id", "date"])))
    out["n_events_covered"] = int(len(near.drop_duplicates(["cell_id", "event_date"])))
    return out


def level_mix(alerts: pd.DataFrame, weights=None) -> dict:
    """Share of cell-days per level and per confidence state (weighted when `weights` is given)."""
    w = np.ones(len(alerts)) if weights is None else np.asarray(weights, dtype=np.float64)
    return {"level": {lv.level_name(k): float(w[(alerts["level"] == k).to_numpy()].sum() / w.sum()) for k in range(4)},
            "confidence": {s: float(w[(alerts["confidence"] == s).to_numpy()].sum() / w.sum())
                           for s in ("High", "Degraded", "Insufficient")}}


def universe_operating_view(universe_alerts: pd.DataFrame, positive_alerts: pd.DataFrame, n_out_of_domain: int,
                            thresholds: lv.Thresholds, ratios) -> dict:
    """Alerts per 1000 cell-days and recall per level, and the cost-loss table, for a test-universe replay.

    `universe_alerts` are the replayed universe rows (weights, buffer and positive flags carried), `positive_alerts` the
    replayed in-domain positive cell-days; `n_out_of_domain` positives below the slope floor count as misses."""
    negatives = hd.universe_negatives(universe_alerts)
    weight = negatives["weight"].to_numpy(dtype=np.float64)
    sizes = universe_alerts.groupby("region")["universe_size"].first()
    n_pos = len(positive_alerts) + n_out_of_domain
    base_rate = float(n_pos / sizes.sum())
    per_level = {}
    for k in (lv.WATCH, lv.WARNING, lv.EMERGENCY):
        per_level[lv.level_name(k)] = {
            "alerts_per_1000_cell_days": float(1000 * weight[(negatives["level"] >= k).to_numpy()].sum() / weight.sum()),
            "recall_in_domain": float((positive_alerts["level"] >= k).mean()),
            "recall_all": float((positive_alerts["level"] >= k).sum() / n_pos)}
    table = cl.cost_loss_table(positive_alerts["risk"].to_numpy(), negatives["risk"].to_numpy(), weight, base_rate,
                               {"watch": thresholds.watch, "warning": thresholds.warning,
                                "emergency": thresholds.emergency}, ratios)
    return {"n_positives_in_domain": int(len(positive_alerts)), "n_out_of_domain": int(n_out_of_domain),
            "base_rate": base_rate, "per_level": per_level, "cost_loss": table}


LAYERS = ("point_risk", "plus_uncertain_high", "plus_blind_rule", "after_hysteresis")


def layer_levels(alerts: pd.DataFrame, thresholds: lv.Thresholds) -> pd.DataFrame:
    """The level of every row after each layer: the point risk alone, plus the `uncertain_high` rule, plus the blind
    rule (the stored `raw_level`), and after hysteresis (the published `level`)."""
    risk, hi = alerts["risk"].to_numpy(dtype=np.float64), alerts["risk_hi"].to_numpy(dtype=np.float64)
    return pd.DataFrame({"point_risk": lv.level_from_risk(risk, thresholds),
                         "plus_uncertain_high": lv.raw_level(risk, hi, thresholds)[0],
                         "plus_blind_rule": alerts["raw_level"].to_numpy(),
                         "after_hysteresis": alerts["level"].to_numpy()}, index=alerts.index)


def layer_shares(alerts: pd.DataFrame, thresholds: lv.Thresholds) -> dict:
    """Share of the table's cell-days at Watch+ / Warning+ / Emergency after each layer (unweighted)."""
    layers = layer_levels(alerts, thresholds)
    return {lv.level_name(k): {name: float((layers[name] >= k).mean()) for name in LAYERS}
            for k in (lv.WATCH, lv.WARNING, lv.EMERGENCY)}


def universe_layer_view(universe_alerts: pd.DataFrame, positive_alerts: pd.DataFrame, n_out_of_domain: int,
                        thresholds: lv.Thresholds) -> dict:
    """Per level and layer: alerts per 1000 cell-days (weighted universe negatives) and recall of the positives
    (out-of-domain positives count as misses), showing what each layer adds."""
    negatives = hd.universe_negatives(universe_alerts)
    weight = negatives["weight"].to_numpy(dtype=np.float64)
    neg, pos = layer_levels(negatives, thresholds), layer_levels(positive_alerts, thresholds)
    n_pos = len(positive_alerts) + n_out_of_domain
    return {lv.level_name(k): {name: {
        "alerts_per_1000_cell_days": float(1000 * weight[(neg[name] >= k).to_numpy()].sum() / weight.sum()),
        "recall_in_domain": float((pos[name] >= k).mean()), "recall_all": float((pos[name] >= k).sum() / n_pos)}
        for name in LAYERS} for k in (lv.WATCH, lv.WARNING, lv.EMERGENCY)}


def cause_counts(alerts: pd.DataFrame) -> dict[str, int]:
    """Cell-days per data-confidence cause (a row can carry several)."""
    causes = alerts["confidence_causes"].str.split(";").explode()
    return {k: int(v) for k, v in causes[causes != ""].value_counts().items()}


def saturation(series: pd.DataFrame, area_by_day: pd.DataFrame | None = None) -> dict:
    """How well the levels separate the days of one focus cell: the level per day, the days at Emergency, and the days
    sharing the maximum risk (ties at the top rank). `area_by_day` (date, emergency share of all cells) is passed through."""
    ordered = series.sort_values("date")
    risk = ordered["risk"].to_numpy(dtype=np.float64)
    top = np.flatnonzero(np.isclose(risk, risk.max(), rtol=1e-9, atol=0.0))
    rank = pd.Series(risk, index=ordered["date"].dt.strftime("%Y-%m-%d")).rank(ascending=False, method="min").astype(int)
    out = {"n_days": int(len(ordered)), "days_at_emergency": int((ordered["level"] == lv.EMERGENCY).sum()),
           "days_at_watch_or_above": int((ordered["level"] >= lv.WATCH).sum()),
           "level_by_day": dict(zip(ordered["date"].dt.strftime("%Y-%m-%d"), ordered["level_name"])),
           "risk_by_day": dict(zip(ordered["date"].dt.strftime("%Y-%m-%d"), risk.tolist())),
           "risk_rank_by_day": {d: int(r) for d, r in rank.items()},
           "max_risk": float(risk.max()),
           "max_risk_days": ordered["date"].dt.strftime("%Y-%m-%d").iloc[top].tolist(),
           "distinct_risk_values": int(len(np.unique(np.round(risk, 15))))}
    if area_by_day is not None:
        out["emergency_share_all_cells"] = {"mean": float(area_by_day["emergency_share"].mean()),
                                            "min": float(area_by_day["emergency_share"].min()),
                                            "max": float(area_by_day["emergency_share"].max())}
    return out


def emergency_share_by_day(alerts: pd.DataFrame) -> pd.DataFrame:
    """(date, emergency_share): the share of the table's cells at Emergency per day."""
    share = (alerts["level"] == lv.EMERGENCY).groupby(alerts["date"].dt.normalize()).mean()
    return share.rename("emergency_share").reset_index()
