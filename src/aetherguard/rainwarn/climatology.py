"""Climatology tables of the heavy-rain warnings (spec section 3 and 6): per domain pixel, the 95th and 99th percentile of
the June-September IMD-day totals, and `clim(t)`, the share of IMD days within +-15 days of each day of year whose total
exceeds each threshold. All from IMERG V07 Late over 2007-2022 (2023 and later are test years and stay out).

    python -m aetherguard.rainwarn climatology

The domain is the set of 0.1 degree IMERG pixels that hold at least one assessed cell of the live run. Writes
`data/processed/rainwarn/climatology.npz`; days missing from the store are NaN and drop out of every count.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from ..features import imerg_features as F
from ..ingest import imerg
from ..live.forecast_skill import pixel_region_labels
from . import prob as P

DOY = 366                       # calendar of a leap year: 29 February has its own slot


def calendar_index(day: date) -> int:
    """0-based slot of `day` in a leap-year calendar."""
    return date(2000, day.month, day.day).timetuple().tm_yday - 1


@dataclass(frozen=True)
class Domain:
    pixels: np.ndarray          # flat IMERG pixel ids (row * COLS + col), ascending
    regions: np.ndarray         # region label per pixel ('' for none)

    @property
    def rows(self) -> np.ndarray:
        return self.pixels // imerg.COLS

    @property
    def cols(self) -> np.ndarray:
        return self.pixels % imerg.COLS


def domain_of_cells(cell_ids, regions) -> Domain:
    flat = F.cell_pixels(np.asarray(cell_ids, dtype=np.int64))
    pixels = np.unique(flat[flat >= 0])
    labels = pixel_region_labels(cell_ids, regions)
    return Domain(pixels=pixels, regions=np.asarray(labels[pixels], dtype=object))


def domain_from_parquet(path: Path) -> Domain:
    table = pd.read_parquet(path, columns=["cell_id", "region"])
    return domain_of_cells(table["cell_id"].to_numpy(), table["region"].to_numpy())


def imd_days(store, rows, cols, first: date, last: date) -> np.ndarray:
    """IMD-day totals (n_pixels, n_days) for IMD days first..last: 0.875 UTC(d-1) + 0.125 UTC(d); NaN when either is."""
    length = (last - first).days + 1
    utc = store.gather(rows, cols, first - timedelta(days=1), length + 1)
    return F.imd_day_series(utc).astype(np.float32)


@dataclass
class Climatology:
    pixels: np.ndarray
    regions: np.ndarray
    p95: np.ndarray             # (N,) mm
    p99: np.ndarray
    clim: np.ndarray            # (len(THRESHOLDS), N, DOY) probability
    years: tuple[int, int]
    window_days: int

    def threshold_mm(self, name: str, index: np.ndarray | None = None):
        """The threshold of `name` in mm: a scalar for a fixed category, the per-pixel array for a percentile."""
        if name in P.FIXED_MM:
            return P.FIXED_MM[name]
        values = self.p95 if name == "p95" else self.p99
        return values if index is None else values[index]

    def prob(self, name: str, day: date, index: np.ndarray | None = None) -> np.ndarray:
        values = self.clim[P.THRESHOLDS.index(name), :, calendar_index(day)]
        return values if index is None else values[index]

    def position(self, pixels: np.ndarray) -> np.ndarray:
        """Index of each flat pixel id in this table, -1 for a pixel outside the domain."""
        pixels = np.asarray(pixels, dtype=np.int64)
        where = np.searchsorted(self.pixels, pixels)
        where = np.clip(where, 0, len(self.pixels) - 1)
        return np.where(self.pixels[where] == pixels, where, -1)

    def save(self, path: Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp.npz")
        np.savez(tmp, pixels=self.pixels, regions=self.regions.astype(str), p95=self.p95, p99=self.p99, clim=self.clim,
                 years=np.array(self.years), window_days=np.array(self.window_days), thresholds=np.array(P.THRESHOLDS))
        tmp.replace(path)
        return path

    @classmethod
    def load(cls, path: Path) -> "Climatology":
        with np.load(path, allow_pickle=False) as data:
            if tuple(str(t) for t in data["thresholds"]) != P.THRESHOLDS:
                raise ValueError(f"{path}: thresholds {list(data['thresholds'])} differ from {list(P.THRESHOLDS)}")
            return cls(pixels=data["pixels"].astype(np.int64), regions=data["regions"].astype(object),
                       p95=data["p95"].astype(np.float32), p99=data["p99"].astype(np.float32),
                       clim=data["clim"].astype(np.float32), years=tuple(int(y) for y in data["years"]),
                       window_days=int(data["window_days"]))


def build(store, domain: Domain, first_year: int, last_year: int, *, window_days: int = 15,
          season_months: tuple[int, ...] = (6, 7, 8, 9), progress=None) -> Climatology:
    """Two passes over the years: the June-September percentiles, then the exceedance counts per calendar slot."""
    rows, cols = domain.rows, domain.cols
    n = len(domain.pixels)
    season: list[np.ndarray] = []
    for year in range(first_year, last_year + 1):
        start, end = date(year, season_months[0], 1), date(year, season_months[-1] + 1, 1) - timedelta(days=1)
        season.append(imd_days(store, rows, cols, start, end))
        if progress:
            progress(f"season {year}")
    stacked = np.concatenate(season, axis=1)
    del season
    with np.errstate(all="ignore"):
        p95 = np.nanpercentile(stacked, 95.0, axis=1).astype(np.float32)
        p99 = np.nanpercentile(stacked, 99.0, axis=1).astype(np.float32)
    del stacked
    hits = np.zeros((len(P.THRESHOLDS), n, DOY), dtype=np.float64)
    valid = np.zeros((n, DOY), dtype=np.float64)
    limits = [P.FIXED_MM.get(name) for name in P.THRESHOLDS]
    for year in range(first_year, last_year + 1):
        start, end = date(year, 1, 1), date(year, 12, 31)
        values = imd_days(store, rows, cols, start, end)
        slots = np.array([calendar_index(start + timedelta(days=k)) for k in range(values.shape[1])])
        finite = np.isfinite(values)
        np.add.at(valid.T, slots, finite.T.astype(np.float64))
        for i, name in enumerate(P.THRESHOLDS):
            t = limits[i] if limits[i] is not None else (p95 if name == "p95" else p99)[:, None]
            exceed = (np.where(finite, values, -np.inf) > t).astype(np.float64)
            np.add.at(hits[i].T, slots, exceed.T)
        if progress:
            progress(f"counts {year}")
    kernel = np.ones(2 * window_days + 1)
    smooth_valid = _circular_window(valid, kernel)
    clim = np.empty_like(hits, dtype=np.float32)
    for i in range(len(P.THRESHOLDS)):
        with np.errstate(invalid="ignore", divide="ignore"):
            clim[i] = np.where(smooth_valid > 0, _circular_window(hits[i], kernel) / smooth_valid, np.nan)
    return Climatology(pixels=domain.pixels, regions=domain.regions, p95=p95, p99=p99, clim=clim,
                       years=(first_year, last_year), window_days=window_days)


def _circular_window(values: np.ndarray, kernel: np.ndarray) -> np.ndarray:
    """Sum over a centred window along the last (calendar) axis, wrapping 31 December to 1 January."""
    half = len(kernel) // 2
    padded = np.concatenate([values[:, -half:], values, values[:, :half]], axis=1)
    cumulative = np.concatenate([np.zeros((values.shape[0], 1)), np.cumsum(padded, axis=1)], axis=1)
    width = len(kernel)
    return cumulative[:, width:] - cumulative[:, :-width]
