"""Training / evaluation rows of the extreme-rain corrector (station-days) and the cell-side predictor mapping.

Target: the gauge's daily rain (IMD-day basis, confirmed by the day-basis experiment) on CLEAN real days (valid, no
NOAA flag, station-year with >= 150 valid days, the relaxation used for the 2007 fault dataset) that the
out-of-fold integrity engine did not flag, 2007-2024, on days where aligned CHIRPS exists.

Predictors (headline = no IMD, because IMD very likely ingests the same gauges):
  chirps_1, chirps_3   aligned CHIRPS (IMD-day) at the station pixel for D and the trailing 3-day total
  wet_top, wet_root    POWER soil wetness at UTC day D-1
  elev_mean, relief, slope_mean, aspect_sin, aspect_cos   terrain of the station's 0.05 degree cell
  elev_point           the station elevation (for cells: the cell's mean elevation)
  doy_sin, doy_cos, month
The leakage-risk variant adds imd_1, imd_3 (IMD grid at the station, day D and 3-day total).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..grid import latlon_to_cell
from ..integrity import inject
from ..integrity.grids import GridRefs
from ..integrity.stations import StationSet

PREDICTORS = ["chirps_1", "chirps_3", "wet_top", "wet_root", "elev_mean", "relief", "slope_mean", "aspect_sin",
              "aspect_cos", "elev_point", "doy_sin", "doy_cos", "month"]
IMD_PREDICTORS = ["imd_1", "imd_3"]
TERRAIN_COLUMNS = ["elev_mean", "relief", "slope_mean", "aspect_sin", "aspect_cos"]
MIN_VALID_DAYS_PER_YEAR = 150
TRAIN_YEARS = (2007, 2015)
WET_MM = 1.0
MIN_WET_DAYS_FOR_P99 = 30
# feature-file column -> corrector predictor (cell side)
CELL_COLUMN_MAP = {"chirps_1": "src_chi_acc_1", "chirps_3": "src_chi_acc_3", "wet_top": "wet_top", "wet_root": "wet_root",
                   "elev_mean": "stat_elev_mean", "relief": "stat_relief", "slope_mean": "stat_slope_mean",
                   "aspect_sin": "stat_aspect_sin", "aspect_cos": "stat_aspect_cos", "elev_point": "stat_elev_mean",
                   "imd_1": "src_imd_acc_1", "imd_3": "src_imd_acc_3"}


def calendar_predictors(dates) -> dict[str, np.ndarray]:
    index = pd.DatetimeIndex(dates)
    angle = 2 * np.pi * (index.dayofyear.to_numpy() - 1) / 365.25
    return {"doy_sin": np.sin(angle), "doy_cos": np.cos(angle), "month": index.month.to_numpy().astype(float)}


def predictors_from_features(features: pd.DataFrame) -> pd.DataFrame:
    """The corrector predictors of every row of a feature table (station-side names on cell-side columns)."""
    out = {p: features[c].to_numpy(np.float64) for p, c in CELL_COLUMN_MAP.items() if c in features.columns}
    out.update(calendar_predictors(features["date"]))
    return pd.DataFrame(out, index=features.index)


def station_predictors(window: StationSet, refs: GridRefs, terrain: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Date x station frames of every predictor (NaN = unavailable), IMD ones included."""
    chirps = refs.values["chirps_aligned"].astype(np.float64)
    imd = refs.values["imd"].astype(np.float64)
    frames = {"chirps_1": chirps, "chirps_3": chirps.rolling(3, min_periods=3).sum(),
              "imd_1": imd, "imd_3": imd.rolling(3, min_periods=3).sum(),
              "wet_top": refs.values["gw_top"].astype(np.float64).shift(1),
              "wet_root": refs.values["gw_root"].astype(np.float64).shift(1)}
    cells = [int(latlon_to_cell(la, lo)) for la, lo in zip(window.meta["lat"], window.meta["lon"])]
    static = terrain.set_index("cell_id").reindex(cells)
    for column in TERRAIN_COLUMNS:
        frames[column] = pd.DataFrame(np.tile(static[column].to_numpy(np.float64), (len(chirps), 1)),
                                      index=chirps.index, columns=chirps.columns)
    elevation = window.meta["elevation_m"].to_numpy(np.float64)
    frames["elev_point"] = pd.DataFrame(np.tile(elevation, (len(chirps), 1)), index=chirps.index, columns=chirps.columns)
    return frames


def station_table(window: StationSet, refs: GridRefs, terrain: pd.DataFrame, oof_flagged: pd.DataFrame | None,
                  splits: dict[str, list[str]], min_valid_days: int = MIN_VALID_DAYS_PER_YEAR) -> pd.DataFrame:
    """One row per usable station-day: station, date, split, gauge, every predictor, p99 and the exceedance label.

    `oof_flagged` is a date x station boolean frame of days the engine flagged (None: none). The per-station
    exceedance threshold is the 99th percentile of the station's wet days (>= 1 mm) in the TRAIN years 2007-2015 among
    the usable rows (NaN when it has fewer than 30 wet days: such rows get no exceedance label)."""
    clean = inject.clean_real_mask(window, min_valid_days)
    usable = clean & window.values.notna()
    if oof_flagged is not None:
        usable &= ~oof_flagged.reindex(index=window.values.index, columns=window.values.columns).fillna(False).astype(bool)
    frames = station_predictors(window, refs, terrain)
    usable &= frames["chirps_1"].notna()
    owner = {sid: name for name, ids in splits.items() for sid in ids}
    dates, stations = np.nonzero(usable.to_numpy())
    cols = {"station": np.asarray(window.values.columns)[stations], "date": window.values.index.to_numpy()[dates],
            "gauge": window.values.to_numpy(np.float64)[dates, stations]}
    for name, frame in frames.items():
        cols[name] = frame.to_numpy(np.float64)[dates, stations]
    table = pd.DataFrame(cols)
    table["split"] = table["station"].map(owner)
    for name, values in calendar_predictors(table["date"]).items():
        table[name] = values
    years = pd.DatetimeIndex(table["date"]).year
    train_wet = table[(years >= TRAIN_YEARS[0]) & (years <= TRAIN_YEARS[1]) & (table["gauge"] >= WET_MM)]
    p99 = train_wet.groupby("station")["gauge"].agg(["size", lambda s: np.percentile(s, 99)])
    p99.columns = ["n_wet", "p99"]
    p99.loc[p99["n_wet"] < MIN_WET_DAYS_FOR_P99, "p99"] = np.nan
    table["p99"] = table["station"].map(p99["p99"])
    table["exceed"] = np.where(table["p99"].notna(), (table["gauge"] >= table["p99"]).astype(float), np.nan)
    return table
