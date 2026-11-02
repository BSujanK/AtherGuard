"""Build the unified landslide label store: one row per source record, nothing dropped silently."""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import PROJECT_ROOT
from ..grid import latlon_to_cell, region_labels
from . import sources
from .policy import assign_regions, normalize_trigger, positive_flags

# Highest priority first; the order decides which record survives a duplicate.
SOURCE_PRIORITY = ("hma", "coolr_reports", "glc", "coolr_events")
# These three share one event_id namespace; coolr_events has its own.
ID_NAMESPACE_SOURCES = ("hma", "coolr_reports", "glc")
DROP_REASONS = ("missing_date", "bad_coordinates", "out_of_scope_region", "missing_country",
                "duplicate_id", "near_duplicate")
NEAR_DUPLICATE_KM = 2.0
EARTH_RADIUS_KM = 6371.0088
REGIONS = ("himalaya", "western_ghats")
EVENT_DAY = "event_day"
INVENTORY_WINDOW = "inventory_window"
ID_CONFLICT_EXAMPLES = 20

SOURCE_FILES = {
    "hma": Path("hma") / "HMA_LS_Cat_point_v02.0.dbf",
    "coolr_reports": Path("coolr_reports_points.csv"),
    "glc": Path("nasa_glc.csv"),
    "coolr_events": Path("coolr_events_points.csv"),
}
_READERS = {
    "hma": sources.read_hma,
    "coolr_reports": sources.read_coolr_reports,
    "glc": sources.read_glc,
    "coolr_events": sources.read_coolr_events,
}
OUTPUT_COLUMNS = ["uid", "source", "event_id", "event_date", "event_date_raw", "date_basis",
                  "date_window_start", "date_window_end", "latitude", "longitude", "cell_id",
                  "accuracy_km", "trigger_raw", "trigger_class", "country_code", "region", "drop_reason",
                  "not_positive_reason", "is_positive", "is_day_exact_positive"]


def _valid_coordinates(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """Finite, inside the grid's [-90, 90) x [-180, 180) range and not the (0, 0) "no coordinates" placeholder."""
    with np.errstate(invalid="ignore"):
        return (np.isfinite(lat) & np.isfinite(lon) & (lat >= -90.0) & (lat < 90.0)
                & (lon >= -180.0) & (lon < 180.0) & ~((lat == 0.0) & (lon == 0.0)))


def _haversine_km(lat1: np.ndarray, lon1: np.ndarray, lat2: np.ndarray, lon2: np.ndarray) -> np.ndarray:
    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    a = (np.sin((phi2 - phi1) / 2) ** 2
         + np.cos(phi1) * np.cos(phi2) * np.sin(np.radians(lon2 - lon1) / 2) ** 2)
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def _mark_duplicate_ids(df: pd.DataFrame, live: pd.Series) -> pd.Series:
    """Rows of the shared id namespace that repeat an event_id held by a higher-priority live row."""
    candidates = df[live & df["source"].isin(ID_NAMESPACE_SOURCES) & df["event_id"].notna()].copy()
    candidates["_rank"] = candidates["source"].map({s: i for i, s in enumerate(SOURCE_PRIORITY)})
    candidates = candidates.sort_values(["_rank", "row"], kind="stable")
    duplicate = candidates["event_id"].duplicated(keep="first")
    return pd.Series(df.index.isin(candidates.index[duplicate.to_numpy()]), index=df.index)


def _mark_near_duplicates(df: pd.DataFrame, live: pd.Series) -> pd.Series:
    """Lower-priority rows on the same date within NEAR_DUPLICATE_KM of a higher-priority KEPT row.

    Per date, priority tiers are processed in order; a tier is compared only against the kept rows of
    tiers above it, so same-source neighbours (e.g. points of one mapped inventory) never remove each other
    and a dropped record cannot shadow anything.
    """
    rank = df["source"].map({s: i for i, s in enumerate(SOURCE_PRIORITY)}).to_numpy()
    lat = df["latitude"].to_numpy(dtype=float)
    lon = df["longitude"].to_numpy(dtype=float)
    dropped = np.zeros(len(df), dtype=bool)
    live_positions = np.flatnonzero(live.to_numpy())
    for members in df.iloc[live_positions].groupby("event_date").indices.values():
        idx = live_positions[members]
        tiers = np.unique(rank[idx])
        if len(tiers) < 2:
            continue
        kept_above = np.empty(0, dtype=np.int64)
        for tier in tiers:
            current = idx[rank[idx] == tier]
            if kept_above.size:
                near = np.zeros(current.size, dtype=bool)
                for start in range(0, current.size, 2000):
                    chunk = current[start:start + 2000]
                    dist = _haversine_km(lat[chunk][:, None], lon[chunk][:, None],
                                         lat[kept_above][None, :], lon[kept_above][None, :])
                    near[start:start + 2000] = (dist < NEAR_DUPLICATE_KM).any(axis=1)
                dropped[current[near]] = True
                current = current[~near]
            kept_above = np.concatenate([kept_above, current])
    return pd.Series(dropped, index=df.index)


def assert_reconciled(per_source: dict[str, dict]) -> None:
    """Every input record is either dropped with a reason or kept."""
    for name, counts in per_source.items():
        dropped = sum(counts["n_dropped"].values())
        if counts["n_input"] != dropped + counts["n_kept"]:
            raise RuntimeError(
                f"{name}: n_input {counts['n_input']} != n_dropped {dropped} + n_kept {counts['n_kept']}")


def _pair_keys() -> list[tuple[str, str]]:
    return [(first, second) for i, first in enumerate(ID_NAMESPACE_SOURCES)
            for second in ID_NAMESPACE_SOURCES[i + 1:]]


def _id_overlaps(df: pd.DataFrame) -> dict[str, int]:
    ids = {s: set(df.loc[(df["source"] == s) & df["event_id"].notna(), "event_id"].astype(int))
           for s in ID_NAMESPACE_SOURCES}
    return {f"{a}|{b}": len(ids[a] & ids[b]) for a, b in _pair_keys()}


def _id_conflicts(df: pd.DataFrame) -> dict[str, dict]:
    """How the records sharing an event_id across the id-namespace sources differ (reporting only)."""
    def first_by_id(name: str) -> pd.DataFrame:
        rows = df[(df["source"] == name) & df["event_id"].notna()].sort_values("row")
        return rows.drop_duplicates("event_id")

    out = {}
    for first, second in _pair_keys():
        m = first_by_id(first).merge(first_by_id(second), on="event_id", suffixes=("_a", "_b"))
        date_differs = (m["event_date_a"].notna() & m["event_date_b"].notna()
                        & (m["event_date_a"] != m["event_date_b"]))
        lat_a, lon_a = m["latitude_a"].to_numpy(dtype=float), m["longitude_a"].to_numpy(dtype=float)
        lat_b, lon_b = m["latitude_b"].to_numpy(dtype=float), m["longitude_b"].to_numpy(dtype=float)
        both_valid = _valid_coordinates(lat_a, lon_a) & _valid_coordinates(lat_b, lon_b)
        far = np.zeros(len(m), dtype=bool)
        far[both_valid] = _haversine_km(lat_a[both_valid], lon_a[both_valid],
                                        lat_b[both_valid], lon_b[both_valid]) > NEAR_DUPLICATE_KM
        acc_a, acc_b = m["accuracy_km_a"], m["accuracy_km_b"]
        accuracy_differs = ~((acc_a == acc_b) | (acc_a.isna() & acc_b.isna()))
        trigger_differs = (m["trigger_raw_a"].str.strip().str.lower()
                           != m["trigger_raw_b"].str.strip().str.lower())
        examples = m[date_differs].sort_values("event_id").head(ID_CONFLICT_EXAMPLES)
        out[f"{first}|{second}"] = {
            "shared_ids": int(len(m)),
            "date_differs": int(date_differs.sum()),
            "location_differs_gt_2km": int(far.sum()),
            "accuracy_differs": int(accuracy_differs.sum()),
            "trigger_differs": int(trigger_differs.sum()),
            "date_difference_examples": [
                {"event_id": int(r.event_id),
                 "dates": {first: r.event_date_a.strftime("%Y-%m-%d"), second: r.event_date_b.strftime("%Y-%m-%d")}}
                for r in examples.itertuples()],
        }
    return out


def _window_summary(rows: pd.DataFrame) -> dict:
    start, end = rows["date_window_start"], rows["date_window_end"]
    return {
        "n": int(len(rows)),
        "min_start": None if start.isna().all() else start.min().strftime("%Y-%m-%d"),
        "max_end": None if end.isna().all() else end.max().strftime("%Y-%m-%d"),
        "n_distinct_headline_dates": int(rows["event_date"].nunique()),
    }


def _inventory_windows(df: pd.DataFrame, raw_window_problems: dict[str, int]) -> dict:
    events = df[df["source"] == "coolr_events"]
    kept = events[events["drop_reason"].isna()]
    return {
        "n_input": int(len(events)),
        **raw_window_problems,
        "kept": _window_summary(kept),
        "positives": _window_summary(kept[kept["is_positive"]]),
    }


def _trigger_table(df: pd.DataFrame) -> dict[str, list[dict]]:
    table = {}
    for name in SOURCE_PRIORITY:
        rows = df[df["source"] == name]
        entries = []
        for raw, group in rows.groupby("trigger_raw", sort=False):
            entries.append({"trigger_raw": str(raw), "trigger_class": str(group["trigger_class"].iloc[0]),
                            "n_input": int(len(group)), "n_kept": int(group["drop_reason"].isna().sum())})
        table[name] = sorted(entries, key=lambda e: (-e["n_kept"], -e["n_input"], e["trigger_raw"]))
    return table


def _per_year(positives: pd.DataFrame) -> dict[str, dict[str, int]]:
    by_region = {}
    for region in REGIONS:
        years = positives.loc[positives["region"] == region, "event_date"].dt.year
        by_region[region] = {str(int(y)): int(n) for y, n in years.value_counts().sort_index().items()}
    return by_region


def _positives_by_source_region_year(positives: pd.DataFrame) -> dict:
    out: dict = {}
    for name in SOURCE_PRIORITY:
        out[name] = {}
        for region in REGIONS:
            rows = positives[(positives["source"] == name) & (positives["region"] == region)]
            years = {}
            for year, group in rows.groupby(rows["event_date"].dt.year):
                exact = int(group["is_day_exact_positive"].sum())
                years[str(int(year))] = {"positives": int(len(group)), "day_exact": exact,
                                         "inventory_window": int(len(group)) - exact}
            out[name][region] = years
    return out


def _report(df: pd.DataFrame, inputs: list[dict], raw_window_problems: dict[str, int]) -> dict:
    per_source: dict[str, dict] = {}
    for entry in inputs:
        name = entry["source"]
        rows = df[df["source"] == name]
        kept = rows[rows["drop_reason"].isna()]
        per_source[name] = {
            "n_input": entry["n_rows"],
            "n_dropped": {r: int((rows["drop_reason"] == r).sum()) for r in DROP_REASONS},
            "n_kept": int(len(kept)),
            "n_positive": int(kept["is_positive"].sum()),
            "n_day_exact_positive": int(kept["is_day_exact_positive"].sum()),
            "n_inventory_window_positive": int((kept["is_positive"] & ~kept["is_day_exact_positive"]).sum()),
            "not_positive_reasons": {str(k): int(v) for k, v in
                                     kept["not_positive_reason"].value_counts().sort_index().items()},
        }
    assert_reconciled(per_source)
    positives = df[df["is_positive"]]
    return {
        "inputs": inputs,
        "sources": per_source,
        "positives_per_region_per_year": _per_year(positives),
        "day_exact_positives_per_region_per_year": _per_year(positives[positives["is_day_exact_positive"]]),
        "inventory_window_positives_per_region_per_year": _per_year(
            positives[~positives["is_day_exact_positive"]]),
        "positives_per_source_region_year": _positives_by_source_region_year(positives),
        "inventory_windows": _inventory_windows(df, raw_window_problems),
        "trigger_table": _trigger_table(df),
        "id_overlaps": _id_overlaps(df),
        "id_conflicts": _id_conflicts(df),
        "drop_reasons": list(DROP_REASONS),
    }


def _report_path(path: Path, name: str) -> str:
    """Path relative to the project root with forward slashes, never absolute."""
    try:
        return Path(os.path.relpath(os.path.abspath(path), PROJECT_ROOT)).as_posix()
    except ValueError:  # another drive: fall back to the file's place inside the raw directory
        return SOURCE_FILES[name].as_posix()


def _window_problems(events: pd.DataFrame) -> dict[str, int]:
    """Count unusable inventory-window bounds (blank, unparsable, inverted) before anything is nulled."""
    before = events["sat_date_before"].fillna("")
    after = events["sat_date_after"].fillna("")
    start, end = events["date_window_start"], events["date_window_end"]
    return {
        "start_missing": int((before == "").sum()),
        "start_unparsable": int(((before != "") & start.isna()).sum()),
        "end_missing": int((after == "").sum()),
        "end_unparsable": int(((after != "") & end.isna()).sum()),
        "inverted": int((start.notna() & end.notna() & (start > end)).sum()),
    }


def build_events(raw_dir, out_dir) -> dict:
    """Read the four sources from `raw_dir`, apply the D1/D2 rules and write events.parquet and label_report.json."""
    raw_dir, out_dir = Path(raw_dir), Path(out_dir)
    frames, inputs = [], []
    for name in SOURCE_PRIORITY:
        path = raw_dir / SOURCE_FILES[name]
        frame = _READERS[name](path)
        inputs.append({"source": name, "path": _report_path(path, name), "n_rows": int(frame.attrs["n_rows"]),
                       "n_deleted_records": int(frame.attrs["n_deleted"])})
        frames.append(frame)
    df = pd.concat(frames, ignore_index=True)
    df["uid"] = df["source"] + ":" + df["row"].astype(str)
    if not df["uid"].is_unique:
        raise RuntimeError("uid is not unique across sources")

    is_events = (df["source"] == "coolr_events").to_numpy()
    df["date_basis"] = np.where(is_events, INVENTORY_WINDOW, EVENT_DAY)
    window_problems = _window_problems(df[is_events])
    inverted = is_events & (df["date_window_start"] > df["date_window_end"]).to_numpy()
    df.loc[inverted, ["date_window_start", "date_window_end"]] = pd.NaT  # unusable window: never repaired

    lat = df["latitude"].to_numpy(dtype=float)
    lon = df["longitude"].to_numpy(dtype=float)
    valid_xy = _valid_coordinates(lat, lon)
    cell = pd.array([pd.NA] * len(df), dtype="Int64")
    cell[valid_xy] = latlon_to_cell(lat[valid_xy], lon[valid_xy])
    df["cell_id"] = cell
    df["trigger_class"] = df["trigger_raw"].map(normalize_trigger)
    lat_ok, lon_ok = np.where(valid_xy, lat, np.nan), np.where(valid_xy, lon, np.nan)
    df["region"] = assign_regions(df["country_code"].to_numpy(dtype=object), lat_ok, lon_ok)
    in_a_box = region_labels(lat_ok, lon_ok) != ""

    drop = pd.Series(None, index=df.index, dtype="object")
    drop[df["event_date"].isna()] = "missing_date"
    drop[drop.isna() & ~valid_xy] = "bad_coordinates"
    no_region = drop.isna() & (df["region"] == "")
    drop[no_region & in_a_box & (df["country_code"] == "")] = "missing_country"  # no country is guessed
    drop[no_region & drop.isna()] = "out_of_scope_region"
    drop[_mark_duplicate_ids(df, drop.isna())] = "duplicate_id"
    drop[_mark_near_duplicates(df, drop.isna())] = "near_duplicate"
    df["drop_reason"] = drop.astype("string")

    kept = df["drop_reason"].isna()
    flags, reasons = positive_flags(df.loc[kept, "trigger_class"], df.loc[kept, "accuracy_km"],
                                    df.loc[kept, "event_date"], df.loc[kept, "region"])
    df["is_positive"] = False
    df.loc[kept, "is_positive"] = flags
    df["is_day_exact_positive"] = df["is_positive"] & (df["date_basis"] == EVENT_DAY)
    not_positive = pd.Series(None, index=df.index, dtype="object")
    not_positive[kept] = pd.Series(reasons, index=df.index[kept], dtype="object")
    df["not_positive_reason"] = not_positive.astype("string")

    report = _report(df, inputs, window_problems)
    if len(df) != sum(entry["n_rows"] for entry in inputs):
        raise RuntimeError("the store does not hold every input record")

    out_dir.mkdir(parents=True, exist_ok=True)
    df[OUTPUT_COLUMNS].to_parquet(out_dir / "events.parquet", index=False)
    (out_dir / "label_report.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return report
