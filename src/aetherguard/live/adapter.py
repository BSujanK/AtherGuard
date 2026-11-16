"""Maps the live sources onto the columns the alert engine's confidence logic reads (`alerts.confidence`).

The engine was built on the v2 feature store: `src_imd_acc_*` (IMD gauge grid), `src_chi_acc_*` (CHIRPS, the satellite
source), `src_dis_*` (their disagreement), `rain_acc_1` (the rain the model used), `rain_source` and the station
summary `integ_*`. Live, the same slots are filled by:

* `src_imd_acc_*`  IMD real-time grid (nearest 0.25 degree point of the cell centre, the lookup of the v2 store);
* `src_chi_acc_*`  IMERG on the IMD day (the satellite source slot), at the cell's 0.1 degree pixel;
* `src_dis_*`      `features.compute.source_block`, the function that builds them for the v2 store;
* `rain_acc_*`     the model's own rain, `irain_acc_*` (IMERG);
* `integ_*`        `integrity.hazard_features.integ_features` from the integrity engine's outputs on the recent gauges.

The windows are the 1-, 3- and 7-day totals ending on IMD day D; a window with a missing day is NaN (never 0), so a
missing source shows up as "invalid" in the confidence logic and nothing is invented.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from ..alerts.config import AlertConfig
from ..alerts.stations import station_states
from ..alerts.store import sensor_table
from ..features import imerg_features as F
from ..features.compute import source_block
from ..features.sources import _imd_pixels
from ..grid import latlon_to_cell
from ..ingest import imerg as imerg_mod
from ..ingest.imd import ImdGrid
from ..integrity import hazard_features as hf
from ..integrity.engine import IntegrityEngine
from ..integrity.features import build_features, station_climatology
from ..integrity.grids import GridRefs
from ..integrity.neighbours import neighbour_table
from .sources import GhcnData

log = logging.getLogger(__name__)

SOURCE_WINDOW = 7            # days of IMD real-time / IMERG series handed to source_block (it reads 1, 3 and 7)
INTEG_COLUMNS = hf.COLUMNS
RAIN_SOURCE_LIVE = "imerg"


def imd_cell_series(grids: dict[date, np.ndarray], cell_ids, day: date, length: int = SOURCE_WINDOW,
                    lon_offset_columns: int = 0) -> np.ndarray:
    """(n, length) IMD real-time rain (mm) of each cell's nearest 0.25 degree point, `lon_offset_columns` columns further
    east (negative: west), for IMD days day-length+1..day. The live configuration reads one column west of the nearest
    point (`imd_lon_offset_columns`): against gauges the grid is registered that far east of its labels.

    NaN for a day without a grid, for a cell outside the IMD grid and where the grid has no value (outside India)."""
    pixels = _imd_pixels(np.asarray(cell_ids, dtype=np.int64), lon_offset_columns)
    out = np.full((len(pixels), length), np.nan)
    inside = pixels >= 0
    for j in range(length):
        grid = grids.get(day - timedelta(days=length - 1 - j))
        if grid is not None:
            out[inside, j] = grid.ravel()[pixels[inside]]
    return out


def imerg_cell_series(store, cell_ids, day: date, length: int = SOURCE_WINDOW) -> np.ndarray:
    """(n, length) IMERG rain on the IMD day (D5: 0.875 UTC(d-1) + 0.125 UTC(d)) at each cell's pixel for IMD days
    day-length+1..day; `store` has the `gather` interface of the IMERG store. NaN for cells outside the domain grid."""
    flat = F.cell_pixels(np.asarray(cell_ids, dtype=np.int64))
    out = np.full((len(flat), length), np.nan)
    inside = flat >= 0
    if inside.any():
        utc = store.gather(flat[inside] // imerg_mod.COLS, flat[inside] % imerg_mod.COLS,
                           day - timedelta(days=length), length + 1)
        out[inside] = F.imd_day_series(utc)
    return out


CHECK_PREFIX = "chk_"
CHECK_LAG = "chk_lag_days"


def check_columns(grids: dict[date, np.ndarray], imerg_store, cell_ids, day: date, check_day: date | None,
                  lon_offset_columns: int = 0) -> dict[str, np.ndarray]:
    """The second-opinion check columns (`alerts.confidence`, module doc): `source_block` of the IMD real-time and IMERG
    IMD-day series ending on `check_day` (the newest IMD day due by the run, `run.second_opinion`), prefixed `chk_`,
    plus `chk_lag_days` = D - check day. Every column is NaN when there is no check day (IMD later than its latency)."""
    n = len(np.asarray(cell_ids))
    if check_day is None:
        names = [f"{CHECK_PREFIX}{k}" for k in source_block(np.full((1, SOURCE_WINDOW), np.nan),
                                                            np.full((1, SOURCE_WINDOW), np.nan))]
        return {**{name: np.full(n, np.nan, dtype=np.float32) for name in names},
                CHECK_LAG: np.full(n, np.nan, dtype=np.float32)}
    imd = imd_cell_series(grids, cell_ids, check_day, lon_offset_columns=lon_offset_columns)
    imerg = imerg_cell_series(imerg_store, cell_ids, check_day)
    out = {f"{CHECK_PREFIX}{k}": v.astype(np.float32) for k, v in source_block(imd, imerg).items()}
    out[CHECK_LAG] = np.full(n, (day - check_day).days, dtype=np.float32)
    return out


def alert_frame(features: pd.DataFrame, imd_rt: np.ndarray, imerg: np.ndarray,
                integ: pd.DataFrame | None = None, check: dict[str, np.ndarray] | None = None) -> pd.DataFrame:
    """`features` (cells of IMD day D with the `irain_*` columns) plus the alert engine's inputs.

    `imd_rt` and `imerg` are (n, 7) IMD-day series ending on D (`imd_cell_series`, `imerg_cell_series`), rows in the
    order of `features`; `integ` the `integ_*` columns of the same rows, or None when no station information exists
    (the columns are then absent, which the confidence logic reads as "no station information"); `check` the
    second-opinion columns of `check_columns` (absent: the confidence logic reads day D's `src_*` columns).
    """
    n = len(features)
    for name, series in (("imd_rt", imd_rt), ("imerg", imerg)):
        if np.shape(series) != (n, SOURCE_WINDOW):
            raise ValueError(f"{name} must have shape ({n}, {SOURCE_WINDOW}), got {np.shape(series)}")
    if integ is not None and (len(integ) != n or not integ.index.equals(features.index)):
        raise ValueError("integ must have the rows (index) of features")
    out = features.copy()
    out["rain_acc_1"] = features["irain_acc_1"]
    out["rain_acc_3"] = features["irain_acc_3"]
    out["rain_source"] = np.where(np.isfinite(features["irain_acc_1"].to_numpy(dtype=np.float64)), RAIN_SOURCE_LIVE, "none")
    for key, values in source_block(np.asarray(imd_rt, dtype=np.float64), np.asarray(imerg, dtype=np.float64)).items():
        out[f"src_{key}"] = values.astype(np.float32)
    if integ is not None:
        for column in INTEG_COLUMNS:
            out[column] = integ[column].to_numpy(dtype=np.float32)
    for name, values in (check or {}).items():
        if np.shape(values) != (n,):
            raise ValueError(f"check column {name} must have shape ({n},), got {np.shape(values)}")
        out[name] = np.asarray(values, dtype=np.float32)
    return out


# --------------------------------------------------------------------------------------------------- integrity

def station_series_imerg(store, meta: pd.DataFrame, index: pd.DatetimeIndex) -> pd.DataFrame:
    """IMERG on the IMD day at each station's pixel (date x station); NaN for a station outside the domain grid."""
    first = index[0].date()
    out = pd.DataFrame(np.nan, index=index, columns=list(meta["id"]), dtype=np.float32)
    for sid, lat, lon in zip(meta["id"], meta["lat"], meta["lon"]):
        try:
            row, col = imerg_mod.imerg_pixel(latlon_to_cell(lat, lon))
        except ValueError:
            continue
        utc = store.gather(np.array([row]), np.array([col]), first - timedelta(days=1), len(index) + 1)
        out[sid] = F.imd_day_series(utc)[0].astype(np.float32)
    return out


def station_series_imd(grids: dict[date, np.ndarray], meta: pd.DataFrame, index: pd.DatetimeIndex) -> pd.DataFrame:
    """IMD real-time rain at each station's nearest point (date x station); NaN on days without a grid."""
    out = pd.DataFrame(np.nan, index=index, columns=list(meta["id"]), dtype=np.float32)
    points = [ImdGrid.nearest_index(lat, lon) for lat, lon in zip(meta["lat"], meta["lon"])]
    for day, grid in grids.items():
        stamp = pd.Timestamp(day)
        if stamp in out.index:
            out.loc[stamp] = [np.nan if p is None else grid[p] for p in points]
    return out


class LiveIntegrity:
    """The integrity engine run on the recent gauges, with the live rain products as its grid references.

    The engine was trained against the IMD final grid and CHIRPS-aligned rain; live, its `imd` reference is the IMD
    real-time grid, its `chirps_aligned` reference is IMERG on the IMD day, and the wetness references (POWER) are
    absent (NaN). The substitution is not validated against the engine's own test, and the bulletin says so.
    The per-station wet-day climatology of the engine's train years is read once from the local gauge archive and cached.
    """

    def __init__(self, engine_dir: Path, cache_dir: Path) -> None:
        self.engine_dir, self.cache_dir = Path(engine_dir), Path(cache_dir)

    def climatology(self, ids: list[str]) -> pd.DataFrame:
        from ..integrity.stations import load_station_set
        path = self.cache_dir / "station_climatology.parquet"
        if path.is_file():
            cached = pd.read_parquet(path)
            if set(ids) <= set(cached.index):
                return cached.loc[ids]
        first, last = (f"{y}-01-01" for y in (2007, 2016))
        window = load_station_set(start=first, end=pd.Timestamp(last) - pd.Timedelta(days=1))
        table = station_climatology(window.values)
        path.parent.mkdir(parents=True, exist_ok=True)
        table.to_parquet(path)
        return table.loc[ids]

    def __call__(self, gauges: GhcnData, imerg_store, imd_grids: dict[date, np.ndarray]) -> pd.DataFrame:
        engine = IntegrityEngine.load(self.engine_dir)
        values, meta = gauges.values, gauges.meta
        refs = GridRefs(values={
            "imd": station_series_imd(imd_grids, meta, values.index),
            "chirps_utc": pd.DataFrame(np.nan, index=values.index, columns=values.columns, dtype=np.float32),
            "chirps_aligned": station_series_imerg(imerg_store, meta, values.index),
            "gw_top": pd.DataFrame(np.nan, index=values.index, columns=values.columns, dtype=np.float32),
            "gw_root": pd.DataFrame(np.nan, index=values.index, columns=values.columns, dtype=np.float32)})
        features = build_features(values, values.index, meta, refs, neighbour_table(meta),
                                  self.climatology(list(values.columns)))
        return engine.predict(features, values, refs)


def station_outputs_with_causal_flags(outputs: pd.DataFrame) -> pd.DataFrame:
    """The engine outputs with `flagged` replaced by the causal flags (the L1 look-ahead of confirmed streaks removed),
    as the alert engine is fed in replay."""
    return outputs.assign(flagged=hf.causal_flags(outputs).astype(bool))


def day_sensor_table(outputs: pd.DataFrame, gauges: GhcnData, config: AlertConfig, day: date) -> pd.DataFrame:
    """The replay-store station table of IMD day `day`: every gauge of the integrity run with the state the alert engine
    reads (`station_states` on the causal-flag outputs), plus `last_reading`, the ISO date of the gauge's newest value in
    the window (None when it has none). Gauge reports reach GHCN days late, so most gauges are `missing` on `day`
    itself; they stay in the table, never dropped, and `last_reading` says how old their newest value is."""
    states = station_states(outputs, config)
    table = sensor_table(states[states["date"] == pd.Timestamp(day)], gauges.meta)
    seen = gauges.values.notna()
    last = {sid: seen.index[seen[sid].to_numpy()].max().date().isoformat() if seen[sid].any() else None
            for sid in seen.columns}
    return table.assign(last_reading=table["station"].map(last))


def integ_columns(outputs: pd.DataFrame, gauges: GhcnData, cells: pd.DataFrame, rain_acc_1) -> pd.DataFrame:
    """The `integ_*` columns for `cells` (lat, lon, date) from the engine outputs on the recent gauges."""
    days = hf.station_days(outputs, gauges.values, gauges.meta)
    table = hf.integ_features(days, cells["lat"].to_numpy(), cells["lon"].to_numpy(), cells["date"], rain_acc_1)
    return table.set_axis(cells.index)
