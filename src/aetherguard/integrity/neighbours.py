"""Nearest-station tables and reference statistics built from the neighbours' OBSERVED values.

Neighbours may themselves be faulty: that is deliberate (a deployed engine only ever sees
observed values), so no reference here is cleaned with ground truth."""
from __future__ import annotations

import numpy as np
import pandas as pd

EARTH_RADIUS_KM = 6371.0088
MIN_DISTANCE_KM = 1.0   # floor applied to distances in the inverse-distance weights (w = 1/d^2)
MIN_VALID = 2           # a reference needs at least this many valid neighbours, else NaN
WET_MM = 1.0            # a neighbour is "wet" at or above this value
_CHUNK_DAYS = 2048      # time rows processed per vectorised block (bounds peak memory)


def haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = (np.radians(np.asarray(x, dtype=float)) for x in (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a))


def neighbour_table(meta: pd.DataFrame, k: int = 5, max_km: float = 150.0) -> pd.DataFrame:
    """Per station its (up to) k nearest other stations within max_km.

    Long table with columns station, neighbour, rank (1 = nearest), dist_km. A station with no
    neighbour within max_km has no rows (see `stations_with_few_neighbours`)."""
    if k < 1:
        raise ValueError("k must be at least 1")
    ids = meta["id"].to_numpy()
    lat, lon = meta["lat"].to_numpy(float), meta["lon"].to_numpy(float)
    dist = haversine_km(lat[:, None], lon[:, None], lat[None, :], lon[None, :])
    np.fill_diagonal(dist, np.inf)
    rows = []
    for i, sid in enumerate(ids):
        order = np.argsort(dist[i], kind="stable")[:k]
        for rank, j in enumerate(order, start=1):
            if dist[i, j] <= max_km:
                rows.append((sid, ids[j], rank, float(dist[i, j])))
    return pd.DataFrame(rows, columns=["station", "neighbour", "rank", "dist_km"])


def stations_with_few_neighbours(table: pd.DataFrame, meta: pd.DataFrame, min_neighbours: int = 2) -> dict:
    """{station id: neighbour count} for every station with fewer than `min_neighbours`."""
    counts = table.groupby("station").size()
    found = {sid: int(counts.get(sid, 0)) for sid in meta["id"]}
    return {sid: n for sid, n in found.items() if n < min_neighbours}


def _neighbour_arrays(columns, table: pd.DataFrame):
    """(idx, dist): (n_stations, K) neighbour column positions (n_stations = padding) and km."""
    position = {sid: i for i, sid in enumerate(columns)}
    unknown = (set(table["station"]) | set(table["neighbour"])) - set(position)
    if unknown:
        raise KeyError(f"neighbour table names stations missing from the values: {sorted(unknown)[:3]}")
    width = int(table.groupby("station").size().max()) if len(table) else 0
    idx = np.full((len(position), width), len(position), dtype=np.intp)
    dist = np.full((len(position), width), np.nan, dtype=np.float32)
    for sid, group in table.sort_values(["station", "rank"]).groupby("station"):
        row = position[sid]
        idx[row, :len(group)] = [position[n] for n in group["neighbour"]]
        dist[row, :len(group)] = group["dist_km"].to_numpy()
    return idx, dist


def _gather(block: np.ndarray, idx: np.ndarray) -> np.ndarray:
    """(days, stations, K) neighbour values of a (days, stations) block; non-finite -> NaN."""
    padded = np.concatenate([block, np.full((block.shape[0], 1), np.nan, dtype=np.float32)], axis=1)
    gathered = padded[:, idx]
    return np.where(np.isfinite(gathered), gathered, np.float32(np.nan))


def neighbour_reference(values: pd.DataFrame, table: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Per station-day reference from the neighbours' observed values (date x station frames).

    idw_mean (weights 1/max(d, 1 km)^2), median, max and frac_wet (share of valid neighbours
    with a value >= 1 mm) are NaN unless at least 2 neighbours are valid that day; n_valid is
    the count of valid (finite) neighbour values and is never NaN."""
    idx, dist = _neighbour_arrays(values.columns, table)
    data = values.to_numpy(np.float32)
    n_days, n_stations = data.shape
    out = {name: np.full((n_days, n_stations), np.nan, dtype=np.float32)
           for name in ("idw_mean", "median", "max", "frac_wet")}
    n_valid = np.zeros((n_days, n_stations), dtype=np.int16)
    weight = (1.0 / np.maximum(dist, MIN_DISTANCE_KM) ** 2).astype(np.float32)
    for lo in range(0, n_days if idx.shape[1] else 0, _CHUNK_DAYS):  # no neighbours at all: all NaN, n_valid 0
        hi = min(lo + _CHUNK_DAYS, n_days)
        neigh = _gather(data[lo:hi], idx)
        valid = np.isfinite(neigh)
        n = valid.sum(axis=2)
        n_valid[lo:hi] = n
        ok = n >= MIN_VALID
        ordered = np.sort(neigh, axis=2)  # NaN sorts last, so the first n entries are the valid ones
        lo_i, hi_i = np.clip((n - 1) // 2, 0, None), np.clip(n // 2, 0, None)
        median = (np.take_along_axis(ordered, lo_i[..., None], 2)[..., 0]
                  + np.take_along_axis(ordered, hi_i[..., None], 2)[..., 0]) / 2
        top = np.take_along_axis(ordered, np.clip(n - 1, 0, None)[..., None], 2)[..., 0]
        w = np.where(valid, weight[None], np.float32(0.0))
        total_w = w.sum(axis=2)
        idw = np.divide((np.where(valid, neigh, np.float32(0.0)) * w).sum(axis=2), total_w,
                        out=np.zeros_like(total_w), where=total_w > 0)
        wet = np.divide((valid & (neigh >= WET_MM)).sum(axis=2), n,
                        out=np.zeros(n.shape, dtype=np.float32), where=n > 0)
        for name, stat in (("idw_mean", idw), ("median", median), ("max", top), ("frac_wet", wet)):
            out[name][lo:hi] = np.where(ok, stat, np.nan)
    frames = {name: pd.DataFrame(arr, index=values.index, columns=values.columns)
              for name, arr in out.items()}
    frames["n_valid"] = pd.DataFrame(n_valid, index=values.index, columns=values.columns)
    return frames


def neighbour_count(values: pd.DataFrame, table: pd.DataFrame, threshold, strict: bool = False) -> pd.DataFrame:
    """Per station-day number of valid neighbours with a value > threshold (strict) or >= threshold.

    `threshold` is a scalar or a date x station frame/array (e.g. 30% of the station's own reading)."""
    idx, _ = _neighbour_arrays(values.columns, table)
    data = values.to_numpy(np.float32)
    thr = np.asarray(threshold, dtype=np.float32)
    if thr.ndim not in (0, 2) or (thr.ndim == 2 and thr.shape != data.shape):
        raise ValueError("threshold must be a scalar or have the same shape as the values")
    counts = np.zeros(data.shape, dtype=np.int16)
    for lo in range(0, data.shape[0] if idx.shape[1] else 0, _CHUNK_DAYS):
        hi = min(lo + _CHUNK_DAYS, data.shape[0])
        neigh = _gather(data[lo:hi], idx)
        bound = thr if thr.ndim == 0 else thr[lo:hi, :, None]
        with np.errstate(invalid="ignore"):  # NaN compares False: a missing neighbour never counts
            hit = neigh > bound if strict else neigh >= bound
        counts[lo:hi] = hit.sum(axis=2)
    return pd.DataFrame(counts, index=values.index, columns=values.columns)
