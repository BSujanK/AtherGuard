"""Gridded rain / wetness references at the stations (IMD, CHIRPS, NASA POWER), as date x station frames.

Sources and day bases (see docs/phase1-design.md D5, `ingest.align`):
* imd             IMD gauge grid at the nearest 0.25 deg point; IMD day D (08:30 IST D-1 .. 08:30 IST D).
                  India only: NaN for a station whose nearest point is outside the coverage mask, and for
                  every day outside the stored years (2007-2024).
* chirps_utc      CHIRPS 0.05 deg pixel containing the station; UTC calendar day D. NaN over water / no data
                  and on days the store does not hold (it holds 2007-2018, 2023 and 2024-06-01..08-15).
* chirps_aligned  `align_utc_to_imd_day`: 0.875 * UTC(D-1) + 0.125 * UTC(D); NaN when either day is missing.
* gw_top, gw_root POWER (MERRA-2) soil wetness fractions at the nearest MERRA-2 point, UTC day. GWETTOP is
                  1.0 over ocean points, so gw_top is set to NaN wherever gw_root is NaN.

Missing is always NaN (never 0); availability is `notna()`.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import data_root
from ..grid import latlon_to_cell
from ..ingest.align import align_utc_to_imd_day
from ..ingest.chirps import ChirpsStore
from ..ingest.imd import ImdGrid
from ..ingest.power import NPZ_FILE, PowerWetness

SOURCES = ("imd", "chirps_utc", "chirps_aligned", "gw_top", "gw_root")


def default_rain_dir() -> Path:
    return data_root() / "processed" / "rain"


@dataclass(frozen=True)
class GridRefs:
    """One float32 date x station frame per source (same index and columns for all)."""
    values: dict[str, pd.DataFrame]

    @property
    def index(self) -> pd.DatetimeIndex:
        return self.values["imd"].index

    @property
    def columns(self) -> pd.Index:
        return self.values["imd"].columns

    def available(self, name: str) -> pd.DataFrame:
        return self.values[name].notna()

    def coverage(self, start=None, end=None) -> dict:
        """Share of station-days with a value, per source, within start..end (default: all dates)."""
        out = {}
        for name, frame in self.values.items():
            part = frame.loc[start:end]
            have = part.notna()
            out[name] = {"station_days": int(have.size), "available": int(have.to_numpy().sum()),
                         "share": float(have.to_numpy().mean()) if have.size else float("nan"),
                         "stations_with_any": int(have.any().sum())}
        return out

    def to_long(self) -> pd.DataFrame:
        """One row per (station, date) with a value and an availability column per source."""
        frames = {}
        for name, frame in self.values.items():
            stacked = frame.stack(future_stack=True)
            frames[name] = stacked
            frames[f"{name}_available"] = stacked.notna()
        long = pd.DataFrame(frames)
        long.index.names = ["date", "station"]
        return long.reset_index()


def _check_dates(dates) -> pd.DatetimeIndex:
    index = pd.DatetimeIndex(dates)
    if index.tz is not None or len(index) == 0:
        raise ValueError("dates must be a non-empty timezone-naive daily index")
    if not ((index[1:] - index[:-1]) == pd.Timedelta(days=1)).all():
        raise ValueError("dates must be consecutive daily dates")
    return index.as_unit("ns")


def _imd_column(grid: ImdGrid, lat: float, lon: float, index: pd.DatetimeIndex) -> np.ndarray:
    out = np.full(len(index), np.nan, dtype=np.float32)
    if not grid.is_covered(lat, lon):
        return out
    for year in grid.years:
        inside = np.flatnonzero(index.year == year)
        if len(inside):
            out[inside] = grid.series(lat, lon, index[inside[0]], index[inside[-1]])
    return out


def station_grid_refs(station_meta: pd.DataFrame, dates, processed_dir=None) -> GridRefs:
    """Gridded references at each station (`station_meta` needs id, lat, lon) for the consecutive `dates`."""
    index = _check_dates(dates)
    rain = Path(processed_dir) if processed_dir is not None else default_rain_dir()
    imd, chirps, power = ImdGrid(rain), ChirpsStore(rain), PowerWetness(rain / NPZ_FILE)
    n, m = len(index), len(station_meta)
    arrays = {name: np.full((n, m), np.nan, dtype=np.float32) for name in SOURCES}
    for j, row in enumerate(station_meta.itertuples(index=False)):
        lat, lon = float(row.lat), float(row.lon)
        arrays["imd"][:, j] = _imd_column(imd, lat, lon, index)
        cell = latlon_to_cell(lat, lon)
        try:
            utc = chirps.cell_series(cell, index[0], index[-1])
        except ValueError:  # the cell lies outside the stored CHIRPS window
            utc = np.full(n, np.nan, dtype=np.float32)
        arrays["chirps_utc"][:, j] = utc
        arrays["chirps_aligned"][:, j] = align_utc_to_imd_day(index, utc) if n > 1 else np.nan
        try:
            root = power.cell_series(cell, index[0], index[-1], "GWETROOT")
            top = power.cell_series(cell, index[0], index[-1], "GWETTOP")
        except ValueError:  # outside the stored POWER grid
            root = top = np.full(n, np.nan, dtype=np.float32)
        top = np.where(np.isnan(root), np.nan, top).astype(np.float32)
        arrays["gw_root"][:, j], arrays["gw_top"][:, j] = root, top
    ids = list(station_meta["id"])
    return GridRefs({name: pd.DataFrame(arr, index=index, columns=ids) for name, arr in arrays.items()})
