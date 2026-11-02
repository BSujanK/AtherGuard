"""Real GHCN-Daily rain-gauge series as a date x station matrix with the NOAA quality flags."""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from ..audit.ghcnd import DIVISOR, DLY_LINE_LENGTH, MISSING, select_stations
from ..config import data_root, load_config

ELEMENT = "PRCP"
DEFAULT_START = "1990-01-01"
DEFAULT_END = "2024-12-31"


@dataclass(frozen=True)
class StationSet:
    """`values` mm/day (float32, NaN = missing) and `flags` (NOAA QFLAG letter, '' = none), both
    date x station on the same continuous daily index; `meta` has one row per station column."""
    values: pd.DataFrame
    flags: pd.DataFrame
    meta: pd.DataFrame


def ghcnd_raw_dir() -> Path:
    return data_root() / "raw" / "ghcnd"


def _daily_index(start, end) -> pd.DatetimeIndex:
    return pd.date_range(start, end, freq="D").as_unit("ns")


def read_prcp_dly(path) -> pd.DataFrame:
    """Parse the PRCP lines of one .dly file into a continuous daily frame with columns
    `value` (mm, float32, NaN for the -9999 sentinel and for months absent from the file) and
    `flag` (NOAA QFLAG letter or ''). Raises ValueError on a short line or a month listed twice."""
    dates, values, flags = [], [], []
    seen: set[tuple[int, int]] = set()
    with Path(path).open("r", encoding="ascii", errors="replace") as handle:
        for line in handle:
            line = line.rstrip("\r\n")
            if not line.strip() or line[17:21] != ELEMENT:
                continue
            if len(line) < DLY_LINE_LENGTH:
                raise ValueError(f"short .dly line ({len(line)} characters, expected {DLY_LINE_LENGTH})")
            year, month = int(line[11:15]), int(line[15:17])
            if (year, month) in seen:
                raise ValueError(f"{Path(path).name}: {year}-{month:02d} listed twice")
            seen.add((year, month))
            n_days = calendar.monthrange(year, month)[1]
            first = np.datetime64(f"{year:04d}-{month:02d}-01", "ns")
            dates.append(first + np.arange(n_days).astype("timedelta64[D]"))
            for day in range(n_days):
                offset = 21 + day * 8
                raw = int(line[offset:offset + 5])
                values.append(np.nan if raw == MISSING else raw / DIVISOR[ELEMENT])
                flags.append(line[offset + 6].strip())
    if not dates:
        raise ValueError(f"{Path(path).name}: no {ELEMENT} lines")
    index = pd.DatetimeIndex(np.concatenate(dates)).as_unit("ns")
    frame = pd.DataFrame({"value": np.asarray(values, dtype=np.float32),
                          "flag": np.asarray(flags, dtype=object)}, index=index).sort_index()
    return frame.reindex(_daily_index(frame.index[0], frame.index[-1])).assign(
        flag=lambda f: f["flag"].fillna("").astype(object))


def load_full_series(station_id: str, raw_dir=None) -> pd.DataFrame:
    """The whole recorded history of one station (first to last recorded day); used only for
    the real-flag sanity check, never for training."""
    raw = Path(raw_dir) if raw_dir is not None else ghcnd_raw_dir()
    path = raw / "dly" / f"{station_id}.dly"
    if not path.is_file():
        raise FileNotFoundError(f"no .dly file for station {station_id} in {raw / 'dly'}")
    return read_prcp_dly(path)


def select_station_meta(raw_dir=None) -> pd.DataFrame:
    """The Phase 0 station selection (configs/audit.yaml) as a sorted metadata frame."""
    raw = Path(raw_dir) if raw_dir is not None else ghcnd_raw_dir()
    g = load_config("audit")["ghcnd"]
    selected = select_stations(
        (raw / "ghcnd-inventory.txt").read_text(encoding="ascii", errors="replace").splitlines(),
        (raw / "ghcnd-stations.txt").read_text(encoding="ascii", errors="replace").splitlines(),
        g["countries"], ELEMENT, g["first_year_max"], g["last_year_min"], g["upland_min_elev_m"])
    columns = ["id", "name", "lat", "lon", "elevation_m", "country", "region", "upland"]
    return selected[columns].sort_values("id").reset_index(drop=True)


def load_station_set(raw_dir=None, start: str | None = DEFAULT_START,
                     end: str | None = DEFAULT_END) -> StationSet:
    """Selected stations on a continuous daily index start..end (inclusive).

    `start`/`end` of None mean the span of the data (first / last recorded day of any station).
    Days a station did not record are NaN with flag ''. A selected station whose .dly file is
    missing raises FileNotFoundError (nothing is silently dropped)."""
    raw = Path(raw_dir) if raw_dir is not None else ghcnd_raw_dir()
    meta = select_station_meta(raw)
    parsed = {sid: load_full_series(sid, raw) for sid in meta["id"]}
    first = pd.Timestamp(start) if start is not None else min(f.index[0] for f in parsed.values())
    last = pd.Timestamp(end) if end is not None else max(f.index[-1] for f in parsed.values())
    index = _daily_index(first, last)
    values = pd.DataFrame({sid: f["value"].reindex(index) for sid, f in parsed.items()}, index=index)
    flags = pd.DataFrame({sid: f["flag"].reindex(index).fillna("").astype(object)
                          for sid, f in parsed.items()}, index=index)
    return StationSet(values=values.astype(np.float32), flags=flags, meta=meta)
