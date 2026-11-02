"""Sampling primitives for negatives and the universe sample (design D3): rain coverage with look-back, the event
exclusion buffer, terrain attachment for positives, the slope floor, and seeded negative / universe draws.

Conventions. Dates are `datetime64[D]` arrays inside the draws and `datetime64[ns]` in returned tables. A
`cell_id` is `lat_index * ID_STRIDE + lon_index` (grid.py). All randomness comes from numpy Generators built by
`stream`, a SeedSequence keyed on (base seed, purpose, split index, region index), so every stream is independent,
documented and reproducible.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..grid import ID_STRIDE, LAT_ROWS, LON_COLS

PURPOSES = {"negatives": 1, "universe": 2, "window_control": 3}
DAY = "datetime64[D]"
_DAY_KEY_SCALE = 10 ** 8  # cell_id < 3.6e7, so day * scale + cell_id is a unique pair key


class SamplingError(RuntimeError):
    """A sample could not be drawn as specified; the message carries the attempt and rejection counts."""


def stream(seed: int, purpose: str, split_index: int, region_index: int) -> np.random.Generator:
    return np.random.default_rng(np.random.SeedSequence(seed, spawn_key=(PURPOSES[purpose], split_index, region_index)))


def _days(values) -> np.ndarray:
    return np.asarray(values).astype(DAY)


def _day_numbers(values) -> np.ndarray:
    return _days(values).astype(np.int64)


def pair_keys(cell_ids, days) -> np.ndarray:
    return _day_numbers(days) * _DAY_KEY_SCALE + np.asarray(cell_ids, dtype=np.int64)


# ---------------------------------------------------------------------------------------- rain coverage

class RainCoverage:
    """Dates that have rain for the day itself and for the `lookback_days` before it inside ONE covered range."""

    def __init__(self, ranges, lookback_days: int) -> None:
        self.ranges = sorted((pd.Timestamp(a), pd.Timestamp(b)) for a, b in ranges)
        self.lookback_days = int(lookback_days)

    @classmethod
    def from_config(cls, ingest_cfg: dict, lookback_days: int) -> RainCoverage:
        years = ingest_cfg["full_years"]
        ranges = [(f"{int(years['start'])}-01-01", f"{int(years['end'])}-12-31")]
        ranges += [(r["start"], r["end"]) for r in ingest_cfg.get("extra_ranges", [])]
        return cls(ranges, lookback_days)

    def drawable(self, days) -> np.ndarray:
        days = _days(days)
        ok = np.zeros(days.shape, dtype=bool)
        lookback = np.timedelta64(self.lookback_days, "D")
        for start, end in self.ranges:
            ok |= (days - lookback >= start.to_datetime64().astype(DAY)) & (days <= end.to_datetime64().astype(DAY))
        return ok

    def drawable_days(self, start, end) -> np.ndarray:
        window = np.arange(pd.Timestamp(start).to_datetime64().astype(DAY),
                           pd.Timestamp(end).to_datetime64().astype(DAY) + np.timedelta64(1, "D"), dtype=DAY)
        return window[self.drawable(window)]


# ---------------------------------------------------------------------------------------- event buffer

class EventBuffer:
    """Cell-days too close to a recorded event to be negatives.

    A (cell, date) is in the buffer when some record has Chebyshev cell distance < `cells` (index distance
    <= cells - 1, so 0.10 degree for the default 3) and |date difference| <= `days`. Each record is expanded to
    its (2 * (cells - 1) + 1)^2 neighbouring cells on its own date into one sorted key array; a lookup checks
    the 2 * days + 1 relevant dates by binary search. Longitude index wraps like `grid.neighbours`, latitude not.
    """

    def __init__(self, cell_ids, event_days, cells: int, days: int) -> None:
        self.cells, self.days = int(cells), int(days)
        ids = np.asarray(cell_ids, dtype=np.int64)
        day = _day_numbers(event_days)
        self.n_records = len(ids)
        reach = np.arange(-(self.cells - 1), self.cells)
        d_lat, d_lon = (a.ravel() for a in np.meshgrid(reach, reach, indexing="ij"))
        n_lat = (ids // ID_STRIDE)[:, None] + d_lat[None, :]
        n_lon = ((ids % ID_STRIDE)[:, None] + d_lon[None, :]) % LON_COLS
        n_day = np.broadcast_to(day[:, None], n_lat.shape)
        inside = (n_lat >= 0) & (n_lat < LAT_ROWS)
        self._keys = np.unique(self._key(n_day[inside], n_lat[inside], n_lon[inside]))

    @staticmethod
    def _key(day, lat, lon):
        return (day * LAT_ROWS + lat) * LON_COLS + lon

    @classmethod
    def from_events(cls, events: pd.DataFrame, cells: int, days: int) -> EventBuffer:
        """Every record with a date and a cell (valid coordinates), whatever its drop_reason."""
        valid = events["cell_id"].notna() & events["event_date"].notna()
        rows = events.loc[valid]
        return cls(rows["cell_id"].to_numpy(dtype=np.int64), rows["event_date"].to_numpy(), cells, days)

    def hits(self, cell_ids, event_days) -> np.ndarray:
        ids = np.asarray(cell_ids, dtype=np.int64)
        day = _day_numbers(event_days)
        out = np.zeros(len(ids), dtype=bool)
        if len(self._keys) == 0:
            return out
        lat, lon = ids // ID_STRIDE, ids % ID_STRIDE
        for offset in range(-self.days, self.days + 1):
            keys = self._key(day + offset, lat, lon)
            position = np.minimum(np.searchsorted(self._keys, keys), len(self._keys) - 1)
            out |= self._keys[position] == keys
        return out


# ---------------------------------------------------------------------------------------- terrain and floor

def attach_terrain(positives: pd.DataFrame, terrain: pd.DataFrame, max_cells: int) -> pd.DataFrame:
    """Add terrain_source ('own' | 'nearest_land' | 'none'), terrain_cell_id and slope_mean to each positive row.

    A positive cell absent from the terrain table takes the nearest kept cell within `max_cells` cells (Chebyshev
    index distance), nearest by Euclidean index distance, ties to the lowest cell id; with none in reach it is
    'none' (null terrain_cell_id, NaN slope) - never silently filled.
    """
    t_ids = terrain["cell_id"].to_numpy(dtype=np.int64)
    t_lat, t_lon = t_ids // ID_STRIDE, t_ids % ID_STRIDE
    slope_of = pd.Series(terrain["slope_mean"].to_numpy(dtype=float), index=t_ids)
    own = set(t_ids.tolist())
    source: dict[int, str] = {}
    terrain_cell: dict[int, int | None] = {}
    for cell in positives["cell_id"].unique().tolist():
        if cell in own:
            source[cell], terrain_cell[cell] = "own", cell
            continue
        d_lat, d_lon = t_lat - cell // ID_STRIDE, t_lon - cell % ID_STRIDE
        near = np.flatnonzero((np.abs(d_lat) <= max_cells) & (np.abs(d_lon) <= max_cells))
        if len(near) == 0:
            source[cell], terrain_cell[cell] = "none", None
            continue
        order = np.lexsort((t_ids[near], d_lat[near] ** 2 + d_lon[near] ** 2))
        source[cell], terrain_cell[cell] = "nearest_land", int(t_ids[near[order[0]]])
    out = positives.copy()
    out["terrain_source"] = out["cell_id"].map(source).astype("str")
    out["terrain_cell_id"] = pd.array(out["cell_id"].map(terrain_cell), dtype="Int64")
    out["slope_mean"] = slope_of.reindex(out["terrain_cell_id"].astype("float64").to_numpy()).to_numpy()
    return out


def slope_floor(positives: pd.DataFrame, percentile: float, reference_split: str) -> dict:
    """Percentile of slope_mean over the unique cells of the reference split's positives with own terrain.

    Returns the global floor (the one used), the cell count, and the same statistic per label region (information
    only).
    """
    rows = positives[(positives["split"] == reference_split) & (positives["terrain_source"] == "own")]
    rows = rows.dropna(subset=["slope_mean"]).drop_duplicates("cell_id")
    if rows.empty:
        raise ValueError(f"no positive cell with own terrain in split {reference_split!r}: cannot set a slope floor")
    per_region = {region: {"floor": float(np.percentile(group["slope_mean"], percentile)), "n_cells": len(group)}
                  for region, group in sorted(rows.groupby("region"))}
    return {"floor": float(np.percentile(rows["slope_mean"], percentile)), "n_cells": len(rows),
            "percentile": percentile, "reference_split": reference_split, "per_region": per_region}


def candidate_cells(terrain: pd.DataFrame, regions: pd.DataFrame, slope_floor: float) -> pd.DataFrame:
    """Own-terrain cells in a region of scope with slope_mean >= slope_floor, sorted by cell_id."""
    merged = terrain[["cell_id", "slope_mean"]].merge(regions[["cell_id", "region"]], on="cell_id", how="left")
    if merged["region"].isna().any():
        raise ValueError(f"{int(merged['region'].isna().sum())} terrain cell(s) have no region row")
    keep = (merged["region"] != "out_of_scope") & (merged["slope_mean"] >= slope_floor)
    out = merged.loc[keep, ["cell_id", "region", "slope_mean"]]
    return out.sort_values("cell_id", kind="stable").reset_index(drop=True)


# ---------------------------------------------------------------------------------------- negatives

def _month_years(start: pd.Timestamp, end: pd.Timestamp) -> tuple[np.ndarray, np.ndarray]:
    """For month number 1..12: the years in which that month intersects [start, end] (padded) and their count."""
    rows = []
    for month in range(1, 13):
        rows.append([year for year in range(start.year, end.year + 1)
                     if pd.Timestamp(year, month, 1) <= end and pd.Timestamp(year, month, 1) + pd.offsets.MonthEnd(0) >= start])
    width = max(1, max(len(r) for r in rows))
    padded = np.zeros((12, width), dtype=np.int64)
    for i, years in enumerate(rows):
        padded[i, :len(years)] = years
    return padded, np.array([len(r) for r in rows], dtype=np.int64)


def draw_negatives(rng: np.random.Generator, n_target: int, candidate_ids, month_probs, start, end,
                   coverage: RainCoverage, buffer: EventBuffer, max_draws_per_target: int = 1000,
                   min_batch: int = 2000) -> tuple[pd.DataFrame, dict]:
    """Draw `n_target` distinct (cell, date) negatives.

    Month of year from `month_probs` (12 weights, January first), year uniform among the years of [start, end] that
    contain that month, day uniform within that month clipped to [start, end], cell uniform among `candidate_ids`.
    A draw is rejected when its date lacks rain with look-back (`no_rain_coverage`), when it is inside the event
    buffer (`in_buffer`), or when it repeats an accepted draw (`duplicate`); each rejected draw is counted once, under
    the first reason in that order. Raises SamplingError, with the counts, when `max_draws_per_target * n_target`
    draws do not yield `n_target` negatives.
    """
    candidate_ids = np.asarray(candidate_ids, dtype=np.int64)
    stats = {"target": int(n_target), "attempts": 0, "accepted": 0,
             "rejected": {"no_rain_coverage": 0, "in_buffer": 0, "duplicate": 0}}
    empty = pd.DataFrame({"cell_id": np.empty(0, dtype=np.int64), "date": pd.Series(dtype="datetime64[ns]")})
    if n_target == 0:
        return empty, stats
    weights = np.asarray(month_probs, dtype=float)
    if weights.sum() <= 0:
        raise ValueError("month distribution has no mass: cannot draw negatives for a split without positives")
    if len(candidate_ids) == 0:
        raise ValueError("no candidate cells to draw negatives from")
    probs = weights / weights.sum()
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    padded_years, n_years = _month_years(start, end)
    if (n_years[probs > 0] == 0).any():
        raise ValueError("a month with positive probability does not occur inside the split range")
    start_d, end_d = start.to_datetime64().astype(DAY), end.to_datetime64().astype(DAY)
    limit = int(max_draws_per_target) * int(n_target)
    chunks_cells, chunks_days = [], []
    accepted_keys = np.empty(0, dtype=np.int64)
    while stats["accepted"] < n_target:
        need = n_target - stats["accepted"]
        left = limit - stats["attempts"]
        if left <= 0:
            raise SamplingError(
                f"could not draw {n_target} negatives within {limit} draws: accepted {stats['accepted']}, "
                f"attempts {stats['attempts']}, rejected {stats['rejected']}")
        size = min(left, max(int(min_batch), 2 * need))
        months = rng.choice(12, size=size, p=probs)
        years = padded_years[months, rng.integers(0, n_years[months])]
        first = ((years - 1970) * 12 + months).astype("datetime64[M]")
        low = np.maximum(first.astype(DAY), start_d)
        high = np.minimum((first + np.timedelta64(1, "M")).astype(DAY) - np.timedelta64(1, "D"), end_d)
        day = low + rng.integers(0, (high - low).astype(np.int64) + 1).astype("timedelta64[D]")
        cell = candidate_ids[rng.integers(0, len(candidate_ids), size)]

        covered = coverage.drawable(day)
        clear = ~buffer.hits(cell, day)
        valid = covered & clear
        keys = pair_keys(cell, day)
        seen = valid & np.isin(keys, accepted_keys)
        fresh = np.flatnonzero(valid & ~seen)
        first_use = np.zeros(size, dtype=bool)
        first_use[fresh[np.unique(keys[fresh], return_index=True)[1]]] = True
        accept = np.flatnonzero(first_use)
        cut = int(accept[need - 1]) + 1 if len(accept) >= need else size
        accept = accept[:need]
        stats["attempts"] += cut
        stats["accepted"] += len(accept)
        stats["rejected"]["no_rain_coverage"] += int((~covered[:cut]).sum())
        stats["rejected"]["in_buffer"] += int((covered[:cut] & ~clear[:cut]).sum())
        stats["rejected"]["duplicate"] += int(valid[:cut].sum() - len(accept))
        chunks_cells.append(cell[accept])
        chunks_days.append(day[accept])
        accepted_keys = np.concatenate([accepted_keys, keys[accept]])
    rows = pd.DataFrame({"cell_id": np.concatenate(chunks_cells),
                         "date": np.concatenate(chunks_days).astype("datetime64[ns]")})
    return rows, stats


# ---------------------------------------------------------------------------------------- universe

def draw_universe(rng: np.random.Generator, candidate_ids, window_days, n: int, buffer: EventBuffer,
                  positives: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """`n` distinct cell-days uniform over candidate cells x window days (all of them when fewer exist).

    Rows carry `universe_size` (cells x days), `weight` = universe_size / rows drawn, `in_buffer` and
    `is_positive_cell_day` (any positive in `positives` on that cell and date). No buffer filtering.
    """
    candidate_ids = np.asarray(candidate_ids, dtype=np.int64)
    window_days = _days(window_days)
    size = len(candidate_ids) * len(window_days)
    if size == 0:
        raise ValueError("empty universe: no candidate cells or no drawable days")
    flat = np.arange(size) if size <= n else np.sort(rng.choice(size, size=n, replace=False))
    cell = candidate_ids[flat // len(window_days)]
    day = window_days[flat % len(window_days)]
    positive_keys = pair_keys(positives["cell_id"].to_numpy(dtype=np.int64), positives["event_date"].to_numpy())
    return pd.DataFrame({
        "cell_id": cell,
        "date": day.astype("datetime64[ns]"),
        "weight": np.full(len(flat), size / len(flat)),
        "universe_size": np.full(len(flat), size, dtype=np.int64),
        "in_buffer": buffer.hits(cell, day),
        "is_positive_cell_day": np.isin(pair_keys(cell, day), positive_keys),
    }), size
