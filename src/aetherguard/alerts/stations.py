"""Station trust states for the alert engine and the join from stations to cells.

Per station-day state (from the integrity engine outputs): `missing` (no reading), `uncertain` (the station is in the
out-of-distribution state), `faulty` (flagged), `genuine_extreme` (flagged candidate retained by the arbiter), `trusted`.
Phase 2 ruling: a station whose trailing `ood_window_days` flag rate exceeds `ood_multiple` x the engine target is
out of distribution and its state is `uncertain`, never `faulty`; its cells are `Degraded` in data confidence.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..integrity.neighbours import haversine_km
from .config import AlertConfig

STATES = ("trusted", "genuine_extreme", "faulty", "uncertain", "missing")
OUTPUT_REQUIRED = ["station", "date", "trust", "flagged", "genuine_extreme", "fault_type", "reasons"]


def _wide(values: pd.Series, outputs: pd.DataFrame, days: pd.DatetimeIndex) -> pd.DataFrame:
    table = values.groupby([outputs["date"], outputs["station"]]).sum().unstack(fill_value=0.0)
    return table.reindex(days, fill_value=0.0)


def station_states(outputs: pd.DataFrame, config: AlertConfig) -> pd.DataFrame:
    """The engine outputs with `n_observed_window`, `flag_rate_window`, `ood` and `state` added (same row order).

    The flag rate of a station-day is the flagged share of the observed days in the trailing window ending on that day
    (inclusive); `ood` needs `ood_min_observed_days` observed days. `outputs.flagged` is used as given, so pass the
    causal flags when replaying."""
    missing = [c for c in OUTPUT_REQUIRED if c not in outputs.columns]
    if missing:
        raise ValueError(f"station outputs lack columns {missing}")
    out = outputs.reset_index(drop=True).copy()
    out["date"] = pd.to_datetime(out["date"])
    if out.empty:
        return out.assign(n_observed_window=pd.Series(dtype=float), flag_rate_window=pd.Series(dtype=float),
                          ood=pd.Series(dtype=bool), state=pd.Series(dtype=object))
    if out.duplicated(["station", "date"]).any():
        raise ValueError("station outputs must have one row per (station, date)")
    observed = out["trust"].notna()
    flagged = out["flagged"].astype(bool) & observed
    days = pd.date_range(out["date"].min(), out["date"].max(), freq="D")
    n_obs = _wide(observed.astype(float), out, days).rolling(config.ood_window_days, min_periods=1).sum()
    n_flag = _wide(flagged.astype(float), out, days).rolling(config.ood_window_days, min_periods=1).sum()
    rate = (n_flag / n_obs.where(n_obs > 0)).to_numpy()
    di = days.get_indexer(out["date"])
    si = n_obs.columns.get_indexer(out["station"])
    n_window = n_obs.to_numpy()[di, si]
    flag_rate = rate[di, si]
    ood = observed.to_numpy() & (n_window >= config.ood_min_observed_days) & (flag_rate > config.ood_rate)
    state = np.select([~observed.to_numpy(), ood, flagged.to_numpy(), out["genuine_extreme"].astype(bool).to_numpy()],
                      ["missing", "uncertain", "faulty", "genuine_extreme"], default="trusted")
    out["n_observed_window"] = n_window
    out["flag_rate_window"] = flag_rate
    out["ood"] = ood
    out["state"] = state
    return out


def station_coordinates(stations: pd.DataFrame) -> pd.DataFrame:
    """`stations` as (station, lat, lon); accepts the id column named `station` or `id`."""
    key = "station" if "station" in stations.columns else "id" if "id" in stations.columns else None
    if key is None or not {"lat", "lon"} <= set(stations.columns):
        raise ValueError("stations need columns station (or id), lat, lon")
    return stations.rename(columns={key: "station"})[["station", "lat", "lon"]].reset_index(drop=True)


def nearby_station_summary(lat, lon, dates, states: pd.DataFrame, stations: pd.DataFrame, radius_km: float,
                           chunk_rows: int = 20_000) -> tuple[np.ndarray, list[str]]:
    """Per row (cell centre lat/lon, date): the number of observed out-of-distribution stations within `radius_km`
    on that date, and the comma-joined sorted fault types of the stations flagged on that date within the radius."""
    coords = station_coordinates(stations)
    lat, lon = np.asarray(lat, dtype=float), np.asarray(lon, dtype=float)
    n = len(lat)
    days = pd.date_range(states["date"].min(), states["date"].max(), freq="D") if len(states) else pd.DatetimeIndex([])
    ids = pd.Index(coords["station"])
    ood = np.zeros((len(days), len(ids)), dtype=bool)
    fault = np.full((len(days), len(ids)), "", dtype=object)
    di_s, si_s = days.get_indexer(states["date"]), ids.get_indexer(states["station"])
    keep = (di_s >= 0) & (si_s >= 0)
    ood[di_s[keep], si_s[keep]] = states["ood"].to_numpy()[keep]
    flagged = keep & (states["state"].isin(["faulty", "uncertain"]) & states["fault_type"].astype(bool)).to_numpy()
    fault[di_s[flagged], si_s[flagged]] = states["fault_type"].to_numpy()[flagged]
    cells, inverse = np.unique(np.stack([lat, lon], axis=1), axis=0, return_inverse=True)
    inverse = np.asarray(inverse).ravel()
    near = haversine_km(cells[:, [0]], cells[:, [1]], coords["lat"].to_numpy()[None, :],
                        coords["lon"].to_numpy()[None, :]) <= radius_km
    day = days.get_indexer(pd.DatetimeIndex(dates))
    n_ood = np.zeros(n, dtype=np.int32)
    types = [""] * n
    for lo in range(0, n, chunk_rows):
        sel = np.arange(lo, min(lo + chunk_rows, n))
        valid = day[sel] >= 0
        rows, d = sel[valid], day[sel][valid]
        near_rows = near[inverse[rows]]
        n_ood[rows] = (near_rows & ood[d]).sum(axis=1)
        flagged_rows = near_rows & (fault[d] != "")
        for k in np.flatnonzero(flagged_rows.any(axis=1)):
            types[rows[k]] = ",".join(sorted(set(fault[d[k]][flagged_rows[k]])))
    return n_ood, types
