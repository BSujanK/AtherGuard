"""The domain elevation grid served to the dashboard, built once from the per-cell terrain table.

Rows run south to north and columns west to east over the domain box (lat 8-36, lon 72-98) at the 0.05 degree grid,
so `elev[row, col]` is the cell with id `(LAT_INDEX0 + row) * ID_STRIDE + LON_INDEX0 + col`. Cells without a terrain
row (outside the region boxes) are NaN. The grid is cached as float16, the precision it is served at.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ..config import data_root
from ..grid import CELL_DEG, ID_STRIDE, latlon_to_cell

LAT0, LAT1 = 8.0, 36.0
LON0, LON1 = 72.0, 98.0
ROWS = round((LAT1 - LAT0) / CELL_DEG)
COLS = round((LON1 - LON0) / CELL_DEG)
ELEVATION_COLUMN = "elev_mean"
CACHE_FILE = "terrain_grid.npz"
_ORIGIN = int(latlon_to_cell(LAT0, LON0))
LAT_INDEX0, LON_INDEX0 = divmod(_ORIGIN, ID_STRIDE)


def default_source() -> Path:
    return data_root() / "processed" / "terrain" / "cell_terrain.parquet"


def default_cache() -> Path:
    return data_root() / "processed" / "serve" / CACHE_FILE


def build_terrain_grid(table: pd.DataFrame) -> np.ndarray:
    """float16 (ROWS, COLS) elevation grid from a terrain table with `cell_id` and `elev_mean`; NaN where no cell."""
    ids = table["cell_id"].to_numpy(dtype=np.int64)
    rows = ids // ID_STRIDE - LAT_INDEX0
    cols = ids % ID_STRIDE - LON_INDEX0
    inside = (rows >= 0) & (rows < ROWS) & (cols >= 0) & (cols < COLS)
    elev = np.full((ROWS, COLS), np.nan, dtype=np.float32)
    elev[rows[inside], cols[inside]] = table[ELEVATION_COLUMN].to_numpy(dtype=np.float32)[inside]
    return elev.astype(np.float16)


def source_stamp(source: Path) -> tuple[int, int]:
    info = Path(source).stat()
    return info.st_mtime_ns, info.st_size


def load_terrain_grid(source: Path | None = None, cache: Path | None = None) -> np.ndarray:
    """The elevation grid, from the cache when it was built from the current `source`, else built and cached."""
    source, cache = Path(source or default_source()), Path(cache or default_cache())
    stamp = np.array(source_stamp(source), dtype=np.int64)
    if cache.is_file():
        with np.load(cache) as stored:
            if np.array_equal(stored["stamp"], stamp) and stored["elev"].shape == (ROWS, COLS):
                return stored["elev"]
    elev = build_terrain_grid(pd.read_parquet(source, columns=["cell_id", ELEVATION_COLUMN]))
    cache.parent.mkdir(parents=True, exist_ok=True)
    partial = cache.with_name(cache.name + ".tmp")
    with partial.open("wb") as handle:
        np.savez_compressed(handle, elev=elev, stamp=stamp)
    partial.replace(cache)
    return elev
