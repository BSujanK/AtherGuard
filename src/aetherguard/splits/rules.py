"""Pure split rules (Phase 1 design D3/D4): cell-day collapse, split assignment, leakage report."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..grid import ID_STRIDE, LAT_ROWS, LON_COLS

CELL_DAY_KEY = ["cell_id", "event_date"]
WINDOW_KEY = ["cell_id", "date_window_start", "date_window_end"]
CELL_DAY_COLUMNS = ["cell_id", "event_date", "region", "country_code", "n_events", "sources",
                    "min_accuracy_km", "max_accuracy_km"]
WINDOW_COLUMNS = ["cell_id", "window_start", "window_end", "region", "country_code", "n_events", "sources"]


def _stamp(value) -> pd.Timestamp:
    return pd.Timestamp(value)


def _day_bounds(cfg: dict) -> dict[str, tuple[pd.Timestamp, pd.Timestamp]]:
    return {name: (_stamp(spec["start"]), _stamp(spec["end"])) for name, spec in cfg["day_splits"].items()}


def validate_config(cfg: dict) -> None:
    """Reject a splits config whose boundaries are malformed or whose case studies could train a model."""
    bounds = _day_bounds(cfg)
    for name, (start, end) in bounds.items():
        if start > end:
            raise ValueError(f"split {name!r} starts after it ends ({start.date()} > {end.date()})")
    ordered = sorted(bounds.items(), key=lambda item: item[1][0])
    for (left, (_, left_end)), (right, (right_start, _)) in zip(ordered, ordered[1:]):
        if right_start <= left_end:
            raise ValueError(f"splits {left!r} and {right!r} overlap")
    for name, spec in cfg["case_studies"].items():
        for edge in ("start", "end"):
            date = _stamp(spec[edge])
            split = assign_split(date, cfg)
            if cfg["day_splits"][split]["role"] != "test":
                raise ValueError(f"case study {name!r} {edge} {date.date()} is in {split!r}, not a test split")
    window = cfg["window_test"]
    if _stamp(window["window_start"]) > _stamp(window["window_end"]):
        raise ValueError("window_test starts after it ends")


def _modal(df: pd.DataFrame, key: list[str], column: str) -> pd.Series:
    """Most frequent value of `column` per group; ties go to the alphabetically first value."""
    counts = df.groupby([*key, column]).size().rename("n").reset_index()
    counts = counts.sort_values(["n", column], ascending=[False, True], kind="stable")
    return counts.drop_duplicates(key).set_index(key)[column]


def _collapse(rows: pd.DataFrame, key: list[str], extra: dict) -> pd.DataFrame:
    grouped = rows.groupby(key)
    out = grouped.agg(n_events=("uid", "size"),
                      sources=("source", lambda s: ",".join(sorted(s.unique()))),
                      **extra)
    out["region"] = _modal(rows, key, "region")
    out["country_code"] = _modal(rows, key, "country_code")
    return out.reset_index()


def collapse_day_exact(events: pd.DataFrame) -> pd.DataFrame:
    """One row per (cell_id, event_date) that holds at least one day-exact positive event."""
    rows = events.loc[events["is_day_exact_positive"]]
    if rows["cell_id"].isna().any():
        raise ValueError("a day-exact positive has no cell_id")
    rows = rows.assign(cell_id=rows["cell_id"].astype("int64"))
    out = _collapse(rows, CELL_DAY_KEY, {"min_accuracy_km": ("accuracy_km", "min"),
                                         "max_accuracy_km": ("accuracy_km", "max")})
    return out[CELL_DAY_COLUMNS]


def collapse_windows(events: pd.DataFrame) -> pd.DataFrame:
    """One row per (cell_id, window_start, window_end) holding an inventory-window positive."""
    rows = events.loc[events["is_positive"] & (events["date_basis"] == "inventory_window")]
    null_bound = rows["date_window_start"].isna() | rows["date_window_end"].isna()
    if null_bound.any():
        uids = ", ".join(rows.loc[null_bound, "uid"].head(5))
        raise ValueError(f"{int(null_bound.sum())} inventory-window positive(s) have a null window bound "
                         f"(first: {uids})")
    if rows["cell_id"].isna().any():
        raise ValueError("an inventory-window positive has no cell_id")
    rows = rows.assign(cell_id=rows["cell_id"].astype("int64"))
    out = _collapse(rows, WINDOW_KEY, {})
    out = out.rename(columns={"date_window_start": "window_start", "date_window_end": "window_end"})
    return out[WINDOW_COLUMNS]


def assign_splits(event_dates: pd.Series, cfg: dict) -> pd.Series:
    """Split name per date; a date outside every boundary raises (there is no default bucket)."""
    dates = pd.to_datetime(event_dates)
    out = pd.Series(pd.NA, index=dates.index, dtype="object")
    for name, (start, end) in _day_bounds(cfg).items():
        out[(dates >= start) & (dates <= end)] = name
    outside = out.isna()
    if outside.any():
        shown = ", ".join(sorted({d.strftime("%Y-%m-%d") for d in dates[outside]})[:5])
        raise ValueError(f"{int(outside.sum())} date(s) lie outside every split boundary: {shown}")
    return out.astype(str)


def assign_split(event_date, cfg: dict) -> str:
    return assign_splits(pd.Series([_stamp(event_date)]), cfg).iloc[0]


def case_study_labels(regions: pd.Series, event_dates: pd.Series, cfg: dict) -> pd.Series:
    """Case-study name per row, or None."""
    dates = pd.to_datetime(event_dates)
    out = np.full(len(dates), None, dtype=object)
    unassigned = np.ones(len(dates), dtype=bool)
    for name, spec in cfg["case_studies"].items():
        inside = ((regions == spec["region"]) & (dates >= _stamp(spec["start"]))
                  & (dates <= _stamp(spec["end"]))).to_numpy()
        out[inside & unassigned] = name
        unassigned &= ~inside
    return pd.Series(out, index=dates.index, dtype="object")


def assign_case_study(region: str, event_date, cfg: dict) -> str | None:
    return case_study_labels(pd.Series([region]), pd.Series([_stamp(event_date)]), cfg).iloc[0]


def build_tables(events: pd.DataFrame, cfg: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The daily cell-day table (with split and case_study) and the window-positive table."""
    validate_config(cfg)
    day_exact = events["is_day_exact_positive"]
    window = events["is_positive"] & (events["date_basis"] == "inventory_window")
    unaccounted = events["is_positive"] & ~day_exact & ~window
    if unaccounted.any():
        raise ValueError(f"{int(unaccounted.sum())} positive(s) are neither day-exact nor inventory-window "
                         f"(first: {', '.join(events.loc[unaccounted, 'uid'].head(5))})")

    cell_days = collapse_day_exact(events)
    cell_days["split"] = assign_splits(cell_days["event_date"], cfg)
    cell_days["case_study"] = case_study_labels(cell_days["region"], cell_days["event_date"], cfg)
    cell_days = cell_days.sort_values(["event_date", "cell_id"], kind="stable").reset_index(drop=True)

    windows = collapse_windows(events)
    spec = cfg["window_test"]
    outside = ((windows["window_start"] < _stamp(spec["window_start"]))
               | (windows["window_end"] > _stamp(spec["window_end"])))
    if outside.any():
        raise ValueError(f"{int(outside.sum())} window positive(s) lie outside the configured window "
                         f"{spec['window_start']}..{spec['window_end']}")
    windows["split"] = spec["name"]
    windows = windows.sort_values(["window_start", "cell_id"], kind="stable").reset_index(drop=True)
    return cell_days, windows


def _neighbourhood_keys(cell_days: pd.DataFrame, days: int, cells: int) -> np.ndarray:
    """Sorted unique keys of every (day, lat_index, lon_index) within the bounds of each row."""
    day = cell_days["event_date"].to_numpy().astype("datetime64[D]").astype(np.int64)
    ids = cell_days["cell_id"].to_numpy(dtype=np.int64)
    lat, lon = ids // ID_STRIDE, ids % ID_STRIDE
    d_day, d_lat, d_lon = (a.ravel() for a in np.meshgrid(
        np.arange(-days, days + 1), np.arange(-cells, cells + 1), np.arange(-cells, cells + 1),
        indexing="ij"))
    n_lat = lat[:, None] + d_lat[None, :]
    keys = _key(day[:, None] + d_day[None, :], n_lat, (lon[:, None] + d_lon[None, :]) % LON_COLS)
    return np.unique(keys[(n_lat >= 0) & (n_lat < LAT_ROWS)])


def _key(day, lat, lon):
    return (day * LAT_ROWS + lat) * LON_COLS + lon


def _summary(n: int, n_within: int) -> dict:
    return {"n": n, "n_within": n_within, "share": n_within / n if n else None}


def leakage_report(cell_days: pd.DataFrame, cfg: dict) -> dict:
    """Share of checked positives within +-days and +-cells (Chebyshev on lat/lon index) of a train positive.

    Longitude index wraps at the antimeridian, like `grid.neighbours`; latitude does not. Report-only.
    """
    spec = cfg["leakage"]
    days, cells = spec["days"], spec["cells"]
    reference = cell_days.loc[cell_days["split"] == spec["reference_split"]]
    reference_keys = _neighbourhood_keys(reference, days, cells) if len(reference) else np.empty(0, np.int64)
    per_split: dict[str, dict] = {}
    for split in spec["checked_splits"]:
        rows = cell_days.loc[cell_days["split"] == split]
        if len(rows) and len(reference):
            day = rows["event_date"].to_numpy().astype("datetime64[D]").astype(np.int64)
            ids = rows["cell_id"].to_numpy(dtype=np.int64)
            within = int(np.isin(_key(day, ids // ID_STRIDE, ids % ID_STRIDE), reference_keys).sum())
        else:
            within = 0
        per_split[split] = _summary(len(rows), within)
    total = _summary(sum(v["n"] for v in per_split.values()), sum(v["n_within"] for v in per_split.values()))
    return {"days": days, "cells": cells, "reference_split": spec["reference_split"],
            "n_reference": len(reference), "per_split": per_split, "total": total}
