"""v3-live feature groups from the IMERG daily store: `irain`, `iapi`, `inbr` (docs/superpowers/specs/
2026-10-14-aetherguard-live-global-design.md section 4.2). Pure numerics plus `build_imerg_features`, which turns a
frame of (cell_id, date) rows into the float32 feature columns.

Day basis (binding). The row date D is an IMD day. IMERG daily files are UTC days; the IMD-day series is
    x_imd[d] = 0.875 * x_utc[d-1] + 0.125 * x_utc[d]        (NaN when either UTC day is NaN)
so day D needs UTC day D, with weight 0.125 (its first three hours, 00:00-03:00 UTC = 05:30-08:30 IST of D). Nothing
after UTC day D enters a feature at D. A live run at 09:30 IST therefore needs UTC D-1 (Late run) and the first
hours of UTC D (Early run); UTC day D is still running then, so the live runner has to supply that 0.125 term from
the Early data of 00:00-03:00 UTC rather than from a finished daily file.

Groups (all float32, columns listed by `feature_names`):
* `irain`: IMD-day accumulations over 1, 3, 5, 7, 14, 30, 60, 90 days; max 1-day rain in 7 and 30 days; wet days in
  30; days since a 10 mm day (0 when D itself, capped at 90); 1-day share of the 3-day total; 3/7/30-day totals over
  max(climatology, 1 mm), the climatology being the mean of the same accumulation for the same pixel and calendar
  month over the TRAIN range only (2007-01-01..2015-12-31 from the split bounds, no day outside it enters).
* `iapi`: antecedent precipitation index, API[t] = k * API[t-1] + p[t] on the IMD-day series, k = 0.85, 0.90, 0.95.
  Missing days contribute 0 (only the decay carries on); the value on a day whose own rain is missing is NaN. The
  recursion starts from zero `API_SPINUP` (120) days before D, so a row's value does not depend on which other rows
  share its computation chunk (and a single-day live run reproduces it exactly).
* `inbr`: max and mean of the 1- and 3-day IMD-day accumulations over the 3x3 IMERG pixels around the cell's pixel;
  pixels beyond the domain grid are not there, pixels whose accumulation is NaN are ignored, NaN if none is valid.

NaN rule (identical to the v2 feature store): an accumulation window with ANY missing day is NaN; nothing is filled,
interpolated or replaced by zero. Cells outside the IMERG domain grid get NaN in every column.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from ..ingest import imerg as imerg_mod
from ..ingest.align import IMD_SHARE_OF_CURRENT_UTC_DAY, IMD_SHARE_OF_PREVIOUS_UTC_DAY
from .compute import (CLIM_WINDOWS, HEAVY_DAY_MM, MIN_SHARE_ACC3_MM, WET_MM, ClimTable, anomaly, climatology,
                      trailing_window_sums)
from .sources import day_numbers

ACC_WINDOWS = (1, 3, 5, 7, 14, 30, 60, 90)
LOOKBACK = max(ACC_WINDOWS)
API_DECAYS = (0.85, 0.90, 0.95)
API_SPINUP = 120
NBR_WINDOWS = (1, 3)
CENTRE = 4                      # index of the pixel itself in the 3x3 neighbourhood (dr, dc in -1..1, row-major)
CHUNK_DAYS = 120                # rows of one calendar chunk share one store gather
PIXEL_BLOCK = 1000              # centre pixels per gather
EPOCH = date(1970, 1, 1)

GROUPS = ("irain", "iapi", "inbr")


def feature_names() -> dict[str, list[str]]:
    """Feature column names per group, in output order."""
    irain = ([f"irain_acc_{n}" for n in ACC_WINDOWS] + ["irain_max1d_7", "irain_max1d_30", "irain_wetdays_30",
                                                         "irain_days_since_10mm", "irain_share1_3"]
             + [f"irain_acc{n}_vs_clim" for n in CLIM_WINDOWS])
    iapi = [f"iapi_{round(k * 100)}" for k in API_DECAYS]
    inbr = [f"inbr_{stat}_acc_{n}" for stat in ("max", "mean") for n in NBR_WINDOWS]
    return {"irain": irain, "iapi": iapi, "inbr": inbr}


def all_names() -> list[str]:
    return [c for names in feature_names().values() for c in names]


def _to_date(day_number: int) -> date:
    return EPOCH + timedelta(days=int(day_number))


# ------------------------------------------------------------------------------------------ pure numerics

def imd_day_series(utc: np.ndarray) -> np.ndarray:
    """(n, T) UTC-day series -> (n, T-1) IMD-day series; column j is the IMD day of UTC column j+1:
    0.875 * utc[j] + 0.125 * utc[j+1], NaN when either is NaN."""
    utc = np.asarray(utc, dtype=np.float64)
    return IMD_SHARE_OF_PREVIOUS_UTC_DAY * utc[:, :-1] + IMD_SHARE_OF_CURRENT_UTC_DAY * utc[:, 1:]


def accumulation_block(daily: np.ndarray) -> dict[str, np.ndarray]:
    """Rain features of an (n, 90) IMD-day matrix whose last column is day D (any NaN in a window -> NaN)."""
    daily = np.asarray(daily, dtype=np.float64)
    if daily.ndim != 2 or daily.shape[1] != LOOKBACK:
        raise ValueError(f"daily must be (n, {LOOKBACK}), got {daily.shape}")
    out = {f"acc_{n}": daily[:, -n:].sum(axis=1) for n in ACC_WINDOWS}
    out["max1d_7"] = daily[:, -7:].max(axis=1)
    out["max1d_30"] = daily[:, -30:].max(axis=1)
    out["wetdays_30"] = np.where(np.isnan(out["acc_30"]), np.nan, (daily[:, -30:] >= WET_MM).sum(axis=1))
    heavy = (daily >= HEAVY_DAY_MM)[:, ::-1]
    since = np.where(heavy.any(axis=1), heavy.argmax(axis=1), LOOKBACK).astype(np.float64)
    out["days_since_10mm"] = np.where(np.isnan(out["acc_90"]), np.nan, since)
    acc3 = out["acc_3"]
    enough = acc3 >= MIN_SHARE_ACC3_MM
    out["share1_3"] = np.where(enough, out["acc_1"] / np.where(enough, acc3, 1.0), np.nan)
    return out


def api_state(series: np.ndarray, k: float) -> np.ndarray:
    """(n, T) recursion state S[t] = k * S[t-1] + p[t] from zero, NaN days contributing 0."""
    series = np.asarray(series, dtype=np.float64)
    state = np.empty_like(series)
    carry = np.zeros(series.shape[0])
    for t in range(series.shape[1]):
        carry = k * carry + np.nan_to_num(series[:, t], nan=0.0)
        state[:, t] = carry
    return state


def api(series: np.ndarray, k: float) -> np.ndarray:
    """Antecedent precipitation index along (n, T) with the state started from zero before column 0; NaN on a day
    whose own value is NaN (that day contributes 0 to the following days)."""
    series = np.asarray(series, dtype=np.float64)
    return np.where(np.isnan(series), np.nan, api_state(series, k))


def api_at(state: np.ndarray, series: np.ndarray, k: float, rows: np.ndarray, t: np.ndarray,
           spinup: int = API_SPINUP) -> np.ndarray:
    """API at column t[i] of row rows[i], as if the recursion had started from zero `spinup` days before it:
    S[t] - k**(spinup+1) * S[t-spinup-1] (the memory of the longer recursion beyond the spin-up is removed exactly).
    `state` is `api_state(series, k)`; needs t >= spinup + 1. NaN where the series itself is NaN at t."""
    t = np.asarray(t)
    if np.any(t < spinup + 1):
        raise ValueError(f"API needs {spinup + 1} columns before the first requested day")
    value = state[rows, t] - k ** (spinup + 1) * state[rows, t - spinup - 1]
    return np.where(np.isnan(series[rows, t]), np.nan, value)


def neighbourhood_stats(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(max, mean) over axis 1 of an (n, 9) matrix, ignoring NaN; NaN where every entry is NaN."""
    values = np.asarray(values, dtype=np.float64)
    valid = ~np.isnan(values)
    count = valid.sum(axis=1)
    top = np.where(valid, values, -np.inf).max(axis=1)
    mean = np.where(valid, values, 0.0).sum(axis=1) / np.maximum(count, 1)
    return np.where(count > 0, top, np.nan), np.where(count > 0, mean, np.nan)


def neighbour_pixels(flat: np.ndarray) -> np.ndarray:
    """(n, 9) flat pixel ids (row * COLS + col) of the 3x3 block around each pixel, row-major with the pixel itself
    at index CENTRE; -1 where the neighbour lies outside the domain grid."""
    flat = np.asarray(flat, dtype=np.int64)
    row, col = np.divmod(flat, imerg_mod.COLS)
    out = np.empty((len(flat), 9), dtype=np.int64)
    k = 0
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            r, c = row + dr, col + dc
            inside = (r >= 0) & (r < imerg_mod.ROWS) & (c >= 0) & (c < imerg_mod.COLS)
            out[:, k] = np.where(inside, r * imerg_mod.COLS + c, -1)
            k += 1
    return out


def cell_pixels(cell_ids) -> np.ndarray:
    """Flat IMERG pixel id (row * COLS + col) of each cell; -1 for a cell outside the domain grid."""
    cells = np.asarray(cell_ids, dtype=np.int64)
    unique, inverse = np.unique(cells, return_inverse=True)
    flat = np.full(len(unique), -1, dtype=np.int64)
    try:
        row, col = imerg_mod.imerg_pixel(unique)
        flat[:] = row * imerg_mod.COLS + col
    except ValueError:
        for i, cell in enumerate(unique):
            try:
                row, col = imerg_mod.imerg_pixel(int(cell))
            except ValueError:
                continue
            flat[i] = row * imerg_mod.COLS + col
    return flat[inverse]


# ------------------------------------------------------------------------------------------- climatology

class _ImergSeries:
    """The `series(pix, first_day, last_day)` view of an IMERG store that `compute.climatology` reads."""

    def __init__(self, store) -> None:
        self.store = store

    def series(self, pix, first_day: int, last_day: int) -> np.ndarray:
        pix = np.asarray(pix, dtype=np.int64)
        return self.store.gather(pix // imerg_mod.COLS, pix % imerg_mod.COLS, _to_date(first_day),
                                 last_day - first_day + 1)


def imerg_climatology(store, flat_pixels, first_day: date, last_day: date, windows=CLIM_WINDOWS,
                      pixel_chunk: int = 1500) -> ClimTable:
    """Mean trailing IMD-day accumulation per (pixel, calendar month) over first_day..last_day ONLY.

    Same definition as the v2 climatology (`compute.climatology`, aligned): the IMD-day series is built from the UTC
    days inside the range, so its first day is NaN and a window is valid only when it lies wholly in the range and
    has no missing day. `flat_pixels` are row * COLS + col; the table is sorted by pixel."""
    pix = np.unique(np.asarray(flat_pixels, dtype=np.int64))
    pix = pix[pix >= 0]
    first, last = int(day_numbers([first_day])[0]), int(day_numbers([last_day])[0])
    values = climatology(_ImergSeries(store), pix, first, last, aligned=True, windows=tuple(windows),
                         pixel_chunk=pixel_chunk)
    return ClimTable(pix, values)


# ------------------------------------------------------------------------------------------------ features

def _block_features(store, clim: ClimTable, centres: np.ndarray, flat: np.ndarray, days: np.ndarray) -> dict:
    """Feature columns of the rows whose pixel is in `centres` (sorted unique flat ids) and day numbers `days`."""
    own = np.searchsorted(centres, flat)
    first_imd = int(days.min()) - (API_SPINUP + 1)           # IMD day of IMD-series column 0
    n_imd = int(days.max()) - first_imd + 1
    neighbours = neighbour_pixels(centres)
    wanted = np.unique(neighbours[neighbours >= 0])
    utc = store.gather(wanted // imerg_mod.COLS, wanted % imerg_mod.COLS, _to_date(first_imd - 1), n_imd + 1)
    imd = imd_day_series(utc)
    position = np.where(neighbours >= 0, np.searchsorted(wanted, neighbours), -1)
    t = days - first_imd
    out: dict[str, np.ndarray] = {}

    centre_imd = imd[position[:, CENTRE]]
    window = centre_imd[own[:, None], t[:, None] + np.arange(1 - LOOKBACK, 1)]
    block = accumulation_block(window)
    for name, values in block.items():
        out[f"irain_{name}"] = values
    months = pd.DatetimeIndex(days.astype("datetime64[D]")).month.to_numpy()
    reference = clim.lookup(flat, months)
    for w, n in enumerate(CLIM_WINDOWS):
        out[f"irain_acc{n}_vs_clim"] = anomaly(block[f"acc_{n}"], reference[:, w])

    for k in API_DECAYS:
        out[f"iapi_{round(k * 100)}"] = api_at(api_state(centre_imd, k), centre_imd, k, own, t)

    around = position[own]
    present = around >= 0
    accumulations = {1: imd, 3: trailing_window_sums(imd, 3)}
    for n in NBR_WINDOWS:
        values = np.where(present, accumulations[n][np.where(present, around, 0), t[:, None]], np.nan)
        top, mean = neighbourhood_stats(values)
        out[f"inbr_max_acc_{n}"], out[f"inbr_mean_acc_{n}"] = top, mean
    return out


def build_imerg_features(frame: pd.DataFrame, store, clim: ClimTable, chunk_days: int = CHUNK_DAYS,
                         pixel_block: int = PIXEL_BLOCK) -> pd.DataFrame:
    """The `irain`, `iapi` and `inbr` float32 columns for the (cell_id, date) rows of `frame`, in its row order and
    with its index. `store` needs `gather(rows, cols, first_day, length) -> float32 (n, length)` (NaN where missing),
    `clim` is the train-range climatology of every pixel of the frame (`imerg_climatology`).

    Rows are grouped by calendar chunk (`chunk_days` of date) and, within it, by blocks of `pixel_block` centre
    pixels; each block gathers the union of its 3x3 neighbourhoods once, from 122 days before its first date to its
    last date, so memory is bounded by the block and not by the frame."""
    cells = frame["cell_id"].to_numpy(dtype=np.int64)
    days = day_numbers(frame["date"].to_numpy())
    flat = cell_pixels(cells)
    names = all_names()
    out = {name: np.full(len(frame), np.nan, dtype=np.float32) for name in names}
    usable = np.flatnonzero(flat >= 0)
    chunk = days[usable] // chunk_days
    for c in np.unique(chunk):
        in_chunk = usable[chunk == c]
        centres, inverse = np.unique(flat[in_chunk], return_inverse=True)
        block_of = inverse // pixel_block
        for b in np.unique(block_of):
            sel = in_chunk[block_of == b]
            values = _block_features(store, clim, centres[b * pixel_block:(b + 1) * pixel_block], flat[sel], days[sel])
            for name in names:
                out[name][sel] = values[name]
    return pd.DataFrame(out, index=frame.index)
