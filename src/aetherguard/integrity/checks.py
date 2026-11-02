"""L1 deterministic integrity checks: transparent rules, one boolean matrix per reason code.

Every rule takes a date x station frame (or a 2-D array, rows = days) and returns the same
kind of object with the same shape. Missing values (NaN) are never treated as 0: they end
streaks and blocks and are reported by `gap`. Thresholds (their false-flag rate on the real
clean days is measured by `baseline_report` and written to reports/phase2a_baselines.*):

* bounds: value < 0 or > 1500 mm/day, or +-inf. 1500 mm is above every gauge record in the
  selected stations' 1990-2024 history (and is far above the 99.9th percentile), so it is
  expected never to fire on real data. NaN is a missing reading, not a bounds fault.
* stuck: a run of >= STUCK_MIN_RUN identical POSITIVE values. Zeros are excluded because dry
  spells are genuinely constant. NOAA's own K check needs NOAA_K_MIN_RUN identical values.
* duplicate_block: a block of >= 7 consecutive days identical (and fully observed, with at
  least DUPLICATE_MIN_POSITIVE positive days) to an earlier, non-overlapping block of the same
  station. Measured on the real clean days (1990-2024): with only one positive day required
  6.3% of clean days fire (dry blocks holding one identical trace value), with two 0.17%,
  with three 0.00%, hence 3.
* gap: NaN runs, reported with their run length; not part of `l1_flag`.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

MAX_MM = 1500.0
STUCK_MIN_RUN = 3
NOAA_K_MIN_RUN = 10
DUPLICATE_MIN_BLOCK = 7
DUPLICATE_MIN_POSITIVE = 3


@dataclass(frozen=True)
class L1Config:
    max_mm: float = MAX_MM
    stuck_min_run: int = STUCK_MIN_RUN
    k_min_run: int = NOAA_K_MIN_RUN
    dup_min_block: int = DUPLICATE_MIN_BLOCK
    dup_min_positive: int = DUPLICATE_MIN_POSITIVE


def _prepare(values):
    """(float32 2-D array, rebuild) where rebuild(array) wraps a result like the input."""
    if isinstance(values, pd.DataFrame):
        array = values.to_numpy(np.float32)
        return array, lambda out: pd.DataFrame(out, index=values.index, columns=values.columns)
    array = np.asarray(values, dtype=np.float32)
    if array.ndim != 2:
        raise ValueError("values must be 2-D (days x stations)")
    return array, lambda out: out


def run_length_map(mask: np.ndarray) -> np.ndarray:
    """Per cell, the length of the run of True (down the days axis) that contains it, else 0."""
    out = np.zeros(mask.shape, dtype=np.int32)
    for j in range(mask.shape[1]):
        column = mask[:, j]
        edges = np.diff(np.concatenate(([0], column.astype(np.int8), [0])))
        lengths = np.flatnonzero(edges == -1) - np.flatnonzero(edges == 1)
        out[column, j] = np.repeat(lengths, lengths)
    return out


def bounds(values, max_mm: float = MAX_MM):
    data, rebuild = _prepare(values)
    with np.errstate(invalid="ignore"):
        out = (data < 0) | (data > max_mm) | np.isinf(data)
    return rebuild(out)


def stuck(values, min_run: int = STUCK_MIN_RUN):
    """True on every day of a run of at least `min_run` identical positive values."""
    if min_run < 2:
        raise ValueError("min_run must be at least 2")
    data, rebuild = _prepare(values)
    same = np.zeros(data.shape, dtype=bool)
    with np.errstate(invalid="ignore"):
        same[1:] = (data[1:] == data[:-1]) & (data[1:] > 0) & np.isfinite(data[1:])
    long_enough = same & (run_length_map(same) >= min_run - 1)
    out = long_enough.copy()
    starts = long_enough.copy()
    starts[1:] &= ~same[:-1]
    out[:-1] |= starts[1:]  # the day before the first repeat belongs to the streak too
    return rebuild(out)


def _duplicate_column(column: np.ndarray, block: int, min_positive: int) -> np.ndarray:
    n = len(column)
    out = np.zeros(n, dtype=bool)
    if n < 2 * block:
        return out
    windows = sliding_window_view(column, block)
    with np.errstate(invalid="ignore"):
        usable = np.isfinite(windows).all(axis=1) & ((windows > 0).sum(axis=1) >= min_positive)
    positions = np.flatnonzero(usable)
    if len(positions) < 2:
        return out
    rows = np.ascontiguousarray(windows[positions]).view(np.dtype((np.void, block * 4))).ravel()
    _, first_index, inverse = np.unique(rows, return_index=True, return_inverse=True)
    earliest = positions[first_index[inverse]]
    copies = positions[earliest + block <= positions]  # earlier, non-overlapping occurrence exists
    cover = np.zeros(n + 1, dtype=np.int32)
    np.add.at(cover, copies, 1)
    np.add.at(cover, copies + block, -1)
    return np.cumsum(cover[:n]) > 0


def duplicate_block(values, min_block: int = DUPLICATE_MIN_BLOCK,
                    min_positive: int = DUPLICATE_MIN_POSITIVE):
    """True on every day of a block (>= min_block days, >= min_positive of them positive)
    repeating an earlier, non-overlapping block of the same station."""
    if min_block < 2:
        raise ValueError("min_block must be at least 2")
    if min_positive < 1:
        raise ValueError("min_positive must be at least 1")
    data, rebuild = _prepare(values)
    out = np.zeros(data.shape, dtype=bool)
    for j in range(data.shape[1]):
        out[:, j] = _duplicate_column(np.ascontiguousarray(data[:, j]), min_block, min_positive)
    return rebuild(out)


def gap(values):
    data, rebuild = _prepare(values)
    return rebuild(np.isnan(data))


def gap_run_length(values):
    """Length of the NaN run containing each missing day (0 on observed days)."""
    data, rebuild = _prepare(values)
    return rebuild(run_length_map(np.isnan(data)))


def l1_flag_matrix(values, cfg: L1Config | None = None):
    """The combined reading-level flag: bounds | stuck | duplicate_block (gaps excluded)."""
    cfg = cfg or L1Config()
    data, rebuild = _prepare(values)
    return rebuild(bounds(data, cfg.max_mm) | stuck(data, cfg.stuck_min_run)
                   | duplicate_block(data, cfg.dup_min_block, cfg.dup_min_positive))


def run_l1(values: pd.DataFrame, cfg: L1Config | None = None) -> pd.DataFrame:
    """Long table (station, date, one boolean column per reason, gap_run_length, l1_flag).

    `stuck` uses cfg.stuck_min_run, `stuck_k10` the NOAA K length; `l1_flag` is
    bounds | stuck | duplicate_block. A gap is reported but is a missing reading, not a bad one."""
    cfg = cfg or L1Config()
    data = values.to_numpy(np.float32)
    reasons = {
        "bounds": bounds(data, cfg.max_mm),
        "stuck": stuck(data, cfg.stuck_min_run),
        "stuck_k10": stuck(data, cfg.k_min_run),
        "duplicate_block": duplicate_block(data, cfg.dup_min_block, cfg.dup_min_positive),
        "gap": gap(data),
    }
    n_days, n_stations = data.shape
    table = pd.DataFrame({
        "station": np.tile(values.columns.to_numpy(), n_days),
        "date": np.repeat(values.index.to_numpy(), n_stations),
        **{name: mask.ravel() for name, mask in reasons.items()},
        "gap_run_length": gap_run_length(data).ravel(),
    })
    table["l1_flag"] = table["bounds"] | table["stuck"] | table["duplicate_block"]
    return table
