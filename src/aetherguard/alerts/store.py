"""The replay store: precomputed per-day alert and sensor tables that the API and the dashboard read from disk.

    <root>/store_manifest.json                 model card hash, thresholds and their source, alert config hash, per set
                                               the dates and row counts
    <root>/<set>/alerts/<YYYY-MM-DD>.parquet   one alert table (engine.run_alerts output) per day
    <root>/<set>/sensors/<YYYY-MM-DD>.parquet  one station table (trust state, fault type, ...) per day

A set is named after its frozen feature table (`case_kerala_2018_samples`, `universe_test_2018`, ...); the manifest keeps
the sets in build order and the first set holding a date is that date's default. A set whose manifest entry has
`sensor_dates` holds gauge tables for those days only (`sensor_gaps` maps a day without one to the reason).
"""
from __future__ import annotations

import json
from datetime import date as Date
from pathlib import Path

import pandas as pd

from ..config import data_root
from ..hazard.jsonio import dump_json

MANIFEST_FILE = "store_manifest.json"
ALERTS_DIR = "alerts"
SENSORS_DIR = "sensors"
SENSOR_COLUMNS = ["station", "name", "lat", "lon", "trust", "fault_type", "flagged", "genuine_extreme", "reasons",
                  "state", "flag_rate_window", "n_observed_window", "ood"]
LIST_COLUMNS = ["cell_id", "date", "lat", "lon", "region", "risk", "risk_per_100k", "level", "level_name", "confidence",
                "blind", "uncertain_high", "reason_codes"]


def default_store_dir() -> Path:
    return data_root() / "processed" / "alerts" / "replay"


class StoreError(LookupError):
    """The requested set, date or cell is not in the replay store."""


class NoSensorsError(StoreError):
    """The set holds the day but no gauge table for it; the message says why."""

    def __init__(self, message: str, set_name: str) -> None:
        super().__init__(message)
        self.set_name = set_name


def iso(day) -> str:
    return pd.Timestamp(day).strftime("%Y-%m-%d")


def sensor_table(states: pd.DataFrame, stations: pd.DataFrame) -> pd.DataFrame:
    """The station table of the dates in `states` (station_states output) with names and coordinates."""
    meta = stations.rename(columns={"id": "station"}) if "station" not in stations.columns else stations
    if "name" not in meta.columns:
        meta = meta.assign(name="")
    out = states.merge(meta[["station", "name", "lat", "lon"]], on="station", how="left", validate="many_to_one")
    return out[["date"] + SENSOR_COLUMNS].reset_index(drop=True)


def write_set(root: Path, name: str, alerts: pd.DataFrame, sensors: pd.DataFrame | None) -> dict:
    """Write the per-day alert (and sensor) tables of one set and return its manifest entry."""
    root = Path(root)
    entry = {"dates": [], "n_rows": int(len(alerts)), "n_cells": int(alerts["cell_id"].nunique())}
    for sub in (ALERTS_DIR, SENSORS_DIR):
        (root / name / sub).mkdir(parents=True, exist_ok=True)
    for day, frame in alerts.groupby(alerts["date"].dt.normalize(), sort=True):
        frame.reset_index(drop=True).to_parquet(root / name / ALERTS_DIR / f"{iso(day)}.parquet", index=False)
        entry["dates"].append(iso(day))
        if sensors is not None:
            sensors[sensors["date"] == day].reset_index(drop=True).to_parquet(
                root / name / SENSORS_DIR / f"{iso(day)}.parquet", index=False)
    entry["has_sensors"] = sensors is not None
    return entry


def write_manifest(root: Path, sets: dict[str, dict], **fields) -> dict:
    manifest = {**fields, "sets": sets}
    Path(root).mkdir(parents=True, exist_ok=True)
    dump_json(Path(root) / MANIFEST_FILE, manifest)
    return manifest


class ReplayStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root or default_store_dir())
        self._manifest: dict | None = None
        self._loaded_stamp: tuple[int, int] | None = None

    def _stamp(self) -> tuple[int, int] | None:
        try:
            info = (self.root / MANIFEST_FILE).stat()
        except OSError:
            return None
        return info.st_mtime_ns, info.st_size

    def refresh(self) -> None:
        """Drop the cached manifest when the file changed on disk, so a long-running reader sees a rebuilt store."""
        if self._manifest is not None and self._stamp() != self._loaded_stamp:
            self._manifest = None

    @property
    def available(self) -> bool:
        return (self.root / MANIFEST_FILE).is_file()

    @property
    def manifest(self) -> dict:
        if self._manifest is None:
            path = self.root / MANIFEST_FILE
            if not path.is_file():
                raise StoreError(f"no replay store at {self.root}; build it (python -m aetherguard.alerts.replay)")
            self._loaded_stamp = self._stamp()
            self._manifest = json.loads(path.read_text(encoding="utf-8"))
        return self._manifest

    def sets(self) -> list[str]:
        return list(self.manifest["sets"])

    def dates(self, set_name: str | None = None) -> list[str]:
        if set_name is not None:
            return list(self._entry(set_name)["dates"])
        return sorted({d for entry in self.manifest["sets"].values() for d in entry["dates"]})

    def _entry(self, set_name: str) -> dict:
        try:
            return self.manifest["sets"][set_name]
        except KeyError:
            raise StoreError(f"unknown set {set_name!r}; available: {self.sets()}") from None

    def resolve_set(self, day: str, set_name: str | None = None) -> str:
        """`set_name` if it holds `day`, else the first set that does."""
        day = iso(day)
        if set_name is not None:
            if day not in self._entry(set_name)["dates"]:
                raise StoreError(self._missing_date(day, set_name))
            return set_name
        for name, entry in self.manifest["sets"].items():
            if day in entry["dates"]:
                return name
        raise StoreError(self._missing_date(day, None))

    def _missing_date(self, day: str, set_name: str | None) -> str:
        dates = self.dates(set_name)
        where = f"set {set_name!r}" if set_name else "the replay store"
        return f"no replay data for {day} in {where}; available {dates[0]}..{dates[-1]} ({len(dates)} days)"

    def alerts(self, day: str, set_name: str | None = None, columns=None, filters=None
               ) -> tuple[str, pd.DataFrame]:
        """One day's alert table; `columns` / `filters` (pyarrow row filters) limit what is read."""
        name = self.resolve_set(day, set_name)
        frame = pd.read_parquet(self.root / name / ALERTS_DIR / f"{iso(day)}.parquet", columns=columns,
                                filters=filters)
        return name, frame

    def sensors(self, day: str, set_name: str | None = None) -> tuple[str, pd.DataFrame]:
        """One day's station table. A set may hold gauge tables for only some of its days (`sensor_dates`, written by
        the live runner); a day without one raises NoSensorsError with the recorded reason (`sensor_gaps`)."""
        name = self.resolve_set(day, set_name)
        entry, day = self._entry(name), iso(day)
        if not entry.get("has_sensors"):
            raise NoSensorsError(entry.get("sensor_gaps", {}).get(day) or f"set {name!r} has no sensor tables", name)
        if day not in entry.get("sensor_dates", entry["dates"]):
            raise NoSensorsError(entry.get("sensor_gaps", {}).get(day) or f"set {name!r} has no sensor table for {day}", name)
        return name, pd.read_parquet(self.root / name / SENSORS_DIR / f"{day}.parquet")

    def cell(self, cell_id: int, day: str, set_name: str | None = None) -> tuple[str, pd.Series]:
        name, frame = self.alerts(day, set_name)
        rows = frame[frame["cell_id"] == cell_id]
        if rows.empty:
            raise StoreError(f"cell {cell_id} has no alert row on {iso(day)} in set {name!r}")
        return name, rows.iloc[0]

    def range(self, start: str, end: str, set_name: str | None = None, columns=None, filters=None) -> pd.DataFrame:
        """Alert rows of every stored day in [start, end] (of `set_name`, or of each day's default set)."""
        lo, hi = iso(start), iso(end)
        if lo > hi:
            raise ValueError("start must not be after end")
        days = [d for d in self.dates(set_name) if lo <= d <= hi] if set_name else [d for d in self.dates() if lo <= d <= hi]
        frames = []
        for day in days:
            name, frame = self.alerts(day, set_name, columns, filters)
            frames.append(frame.assign(set=name))
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    def read_set(self, set_name: str, columns=None) -> pd.DataFrame:
        """Every alert row of one set (all days)."""
        frames = [pd.read_parquet(self.root / set_name / ALERTS_DIR / f"{d}.parquet", columns=columns)
                  for d in self.dates(set_name)]
        return pd.concat(frames, ignore_index=True)

    def cell_series(self, set_name: str, cell_id: int, columns=None) -> pd.DataFrame:
        """One cell's rows over all days of a set, date ordered (`cell_id` is always read)."""
        read = None if columns is None else list(dict.fromkeys([*columns, "cell_id"]))
        parts = []
        for day in self.dates(set_name):
            frame = pd.read_parquet(self.root / set_name / ALERTS_DIR / f"{day}.parquet", columns=read)
            parts.append(frame[frame["cell_id"] == cell_id])
        out = pd.concat(parts, ignore_index=True)
        if out.empty:
            raise StoreError(f"cell {cell_id} is not in set {set_name!r}")
        return out.sort_values("date").reset_index(drop=True)

    def status(self) -> str:
        """`missing` (no manifest), `incomplete` (a listed file is absent) or `ok`."""
        if not self.available:
            return "missing"
        for name, entry in self.manifest["sets"].items():
            for day in entry["dates"]:
                if not (self.root / name / ALERTS_DIR / f"{day}.parquet").is_file():
                    return "incomplete"
            for day in entry.get("sensor_dates", entry["dates"] if entry.get("has_sensors") else []):
                if not (self.root / name / SENSORS_DIR / f"{day}.parquet").is_file():
                    return "incomplete"
        return "ok"


def parse_date(text: str) -> str:
    """Validate a YYYY-MM-DD string (ValueError otherwise) and return it."""
    return Date.fromisoformat(text).isoformat()
