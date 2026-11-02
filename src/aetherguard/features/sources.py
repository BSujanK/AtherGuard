"""Vectorised daily readers for the processed IMD, CHIRPS and POWER stores (row-wise window gathers).

A `DailyStore` holds one or more (days, A, B) stacks (memory-mapped year arrays) and addresses a pixel by the flat
index `a * width + b`; pixel -1 means "no pixel" (cell outside the product's grid or domain) and yields NaN. A day that
is in no stack (a year or range the store does not contain) also yields NaN and is counted in
`counters["days_outside_store"]`, so a gap in the store is never mistaken for zero rain.

Day numbers are days since 1970-01-01 (`datetime64[D]` as int64). Day bases are NOT converted here: IMD values are
IMD days, CHIRPS and POWER values are UTC days (see `compute` and docs/phase1-design.md D5).
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..grid import ID_STRIDE, cell_center
from ..ingest import imd as imd_mod
from ..ingest.chirps import INDEX_FILE as CHIRPS_INDEX_FILE
from ..ingest.chirps import TOP_LAT_IDX
from ..ingest.power import PowerWetness

DAY = "datetime64[D]"


class SourceStoreError(RuntimeError):
    """A processed rain / wetness store is missing or does not have the expected layout."""


def day_numbers(values) -> np.ndarray:
    return np.asarray(values).astype(DAY).astype(np.int64)


@dataclass(frozen=True)
class _Stack:
    days: np.ndarray       # sorted int64 day numbers, one per first-axis slice
    array: np.ndarray      # (len(days), A, B), possibly memory-mapped


class DailyStore:
    def __init__(self, stacks: list[_Stack], width: int, pixel_fn: Callable[[np.ndarray], np.ndarray]) -> None:
        self.width = int(width)
        self._pixel_fn = pixel_fn
        self.counters = {"days_outside_store": 0, "rows_without_pixel": 0}
        self._stacks = stacks
        all_days = np.concatenate([s.days for s in stacks])
        stack_id = np.concatenate([np.full(len(s.days), k) for k, s in enumerate(stacks)])
        local = np.concatenate([np.arange(len(s.days)) for s in stacks])
        order = np.argsort(all_days, kind="stable")
        if len(np.unique(all_days)) != len(all_days):
            raise SourceStoreError("a day appears in more than one stack of the store")
        self._days, self._stack_id, self._local = all_days[order], stack_id[order], local[order]

    @property
    def first_day(self) -> int:
        return int(self._days[0])

    @property
    def last_day(self) -> int:
        return int(self._days[-1])

    def pixels(self, cell_ids) -> np.ndarray:
        """Flat pixel index of each cell (centre / own pixel), -1 where the product has none."""
        return self._pixel_fn(np.asarray(cell_ids, dtype=np.int64))

    def gather(self, pix, first_day, length: int) -> np.ndarray:
        """(n, length) float32: row r holds days first_day[r] .. first_day[r] + length - 1 of pixel pix[r]."""
        pix = np.asarray(pix, dtype=np.int64)
        n = len(pix)
        first = np.broadcast_to(np.asarray(first_day, dtype=np.int64), (n,))
        out = np.full((n, length), np.nan, dtype=np.float32)
        ok = pix >= 0
        self.counters["rows_without_pixel"] += int((~ok).sum())
        a, b = np.divmod(np.where(ok, pix, 0), self.width)
        for k in range(length):
            day = first + k
            pos = np.minimum(np.searchsorted(self._days, day), len(self._days) - 1)
            hit = ok & (self._days[pos] == day)
            self.counters["days_outside_store"] += int((ok & ~hit).sum())
            stack_of = self._stack_id[pos]
            for sid in np.unique(stack_of[hit]):
                rows = np.flatnonzero(hit & (stack_of == sid))
                out[rows, k] = self._stacks[sid].array[self._local[pos[rows]], a[rows], b[rows]]
        return out

    def series(self, pix, first_day: int, last_day: int) -> np.ndarray:
        """(P, T) float32 daily series of each pixel for first_day..last_day; NaN for days outside the store."""
        pix = np.asarray(pix, dtype=np.int64)
        out = np.full((len(pix), last_day - first_day + 1), np.nan, dtype=np.float32)
        ok = pix >= 0
        a, b = np.divmod(np.where(ok, pix, 0), self.width)
        for stack in self._stacks:
            inside = np.flatnonzero((stack.days >= first_day) & (stack.days <= last_day))
            if len(inside) == 0:
                continue
            block = stack.array[inside[:, None], a[None, :], b[None, :]]
            out[:, stack.days[inside] - first_day] = np.asarray(block, dtype=np.float32).T
        out[~ok] = np.nan
        return out


# ------------------------------------------------------------------------------------------------- IMD

def _imd_pixels(cell_ids: np.ndarray, lon_offset_columns: int = 0) -> np.ndarray:
    """Nearest 0.25 degree IMD point of each cell centre; the same rounding as `ImdGrid.nearest_index`.

    `lon_offset_columns` moves the column read (negative: west); the frozen stores and the integrity engine use 0. A column
    outside the grid is -1, never the next row (the flat index is built from the shifted column, not shifted itself)."""
    lat, lon = cell_center(cell_ids)
    i = np.floor(np.round((lat - imd_mod.LAT_MIN) / imd_mod.STEP, 6) + 0.5).astype(np.int64)
    j = np.floor(np.round((lon - imd_mod.LON_MIN) / imd_mod.STEP, 6) + 0.5).astype(np.int64) + int(lon_offset_columns)
    inside = (i >= 0) & (i < imd_mod.N_LAT) & (j >= 0) & (j < imd_mod.N_LON)
    return np.where(inside, i * imd_mod.N_LON + j, -1)


def load_imd(processed_dir) -> DailyStore:
    processed_dir = Path(processed_dir)
    try:
        index = json.loads((processed_dir / imd_mod.INDEX_NAME).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SourceStoreError(f"{imd_mod.INDEX_NAME} not found in {processed_dir}") from exc
    stacks = []
    for year in sorted(int(y) for y in index["years"]):
        array = np.load(processed_dir / index["years"][str(year)]["file"], mmap_mode="r")
        expected = (imd_mod.days_in_year(year), imd_mod.N_LAT, imd_mod.N_LON)
        if array.shape != expected:
            raise SourceStoreError(f"IMD {year} has shape {array.shape}, expected {expected}")
        first = int(np.datetime64(f"{year}-01-01", "D").astype(np.int64))
        stacks.append(_Stack(first + np.arange(array.shape[0], dtype=np.int64), array))
    return DailyStore(stacks, imd_mod.N_LON, _imd_pixels)


# ----------------------------------------------------------------------------------------------- CHIRPS

def load_chirps(processed_dir) -> DailyStore:
    processed_dir = Path(processed_dir)
    try:
        index = json.loads((processed_dir / CHIRPS_INDEX_FILE).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SourceStoreError(f"{CHIRPS_INDEX_FILE} not found in {processed_dir}") from exc
    rows, cols, row_off, col_off = index["rows"], index["cols"], index["row_off"], index["col_off"]
    stacks = []
    for year in sorted(int(y) for y in index["days_per_year"]):
        stamps = json.loads((processed_dir / f"chirps_{year}_dates.json").read_text(encoding="utf-8"))
        array = np.load(processed_dir / f"chirps_{year}.npy", mmap_mode="r")
        if array.shape != (len(stamps), rows, cols):
            raise SourceStoreError(f"CHIRPS {year} has shape {array.shape}, expected {(len(stamps), rows, cols)}")
        stacks.append(_Stack(day_numbers(stamps), array))

    def pixels(cell_ids: np.ndarray) -> np.ndarray:
        row = TOP_LAT_IDX - cell_ids // ID_STRIDE - row_off   # the CHIRPS p05 pixel is exactly the 0.05 degree cell
        col = cell_ids % ID_STRIDE - col_off
        inside = (row >= 0) & (row < rows) & (col >= 0) & (col < cols)
        return np.where(inside, row * cols + col, -1)

    return DailyStore(stacks, cols, pixels)


# ------------------------------------------------------------------------------------------------ POWER

def load_wetness(npz_path, cell_ids) -> tuple[DailyStore, DailyStore]:
    """(GWETTOP, GWETROOT) stores for the MERRA-2 points nearest to `cell_ids`; the pixel of a cell is its point.

    GWETTOP is 1.0 over ocean points, where GWETROOT is NaN: GWETTOP is masked to NaN wherever the nearest point's
    GWETROOT is NaN (per day). Only cells passed here can be looked up (others get pixel -1).
    """
    reader = PowerWetness(npz_path)
    dates = reader.dates()
    first, last = dates[0], dates[-1]
    unique_cells = np.unique(np.asarray(cell_ids, dtype=np.int64))
    point_index: dict[tuple[int, int], int] = {}
    representative: list[int] = []
    point_of_cell = np.empty(len(unique_cells), dtype=np.int64)
    for k, cell in enumerate(unique_cells):
        point = reader.nearest_point(int(cell))
        if point not in point_index:
            point_index[point] = len(representative)
            representative.append(int(cell))
        point_of_cell[k] = point_index[point]
    top = np.stack([reader.cell_series(cell, first, last, "GWETTOP") for cell in representative], axis=1)
    root = np.stack([reader.cell_series(cell, first, last, "GWETROOT") for cell in representative], axis=1)
    top = np.where(np.isnan(root), np.nan, top).astype(np.float32)
    days = np.arange(day_numbers([first])[0], day_numbers([last])[0] + 1, dtype=np.int64)

    def pixels(ids: np.ndarray) -> np.ndarray:
        pos = np.minimum(np.searchsorted(unique_cells, ids), len(unique_cells) - 1)
        return np.where(unique_cells[pos] == ids, point_of_cell[pos], -1)

    stacks = [[_Stack(days, values[:, None, :])] for values in (top, root)]
    return DailyStore(stacks[0], len(representative), pixels), DailyStore(stacks[1], len(representative), pixels)
