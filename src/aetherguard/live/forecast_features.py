"""v3-live features for the forecast leads D+1..D+3: observed IMERG rain through D plus GFS IMD-day totals after D.

For a run on IMD day D and lead k the feature day is T = D + k. Its IMD-day rain series is
  * observed: IMD days up to D from the IMERG UTC days through D, by the same D5 rule as the training features
    (`imerg_features.imd_day_series`: 0.875 UTC(d-1) + 0.125 UTC(d));
  * forecast: IMD days D+1..T from the GFS totals for (03:00 UTC d-1, 03:00 UTC d] (`ingest.gfs`), already on the IMD
    day, so they are taken as they are. Observed rain never enters a day after D and forecast rain never a day up to D
    (the boundary of Review Focus 5): the observed store is read for UTC days up to D only, the forecast array only for
    days D+1..T.
Every feature is then computed from that series with the per-day functions of `features.imerg_features`
(accumulations, API, 3x3 neighbourhood, climatology anomaly), so lead 0 equals `build_imerg_features` exactly (tested).
A missing observed or forecast day is NaN and, by the NaN rule, makes every window containing it NaN.

The pure functions take arrays and frames only; `store` is anything with `gather(rows, cols, first_day, length)` that
returns the IMERG UTC-day rain (mm) of pixels as float32 NaN-filled (an `ImergStore` or `sources.LiveRainView`).
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from ..features import imerg_features as F
from ..features.compute import CLIM_WINDOWS, ClimTable, anomaly, trailing_window_sums
from ..ingest import imerg as imerg_mod

LEADS = (0, 1, 2, 3)
FORECAST_DAYS = 3


def imd_series_with_forecast(utc: np.ndarray, forecast: np.ndarray | None) -> np.ndarray:
    """(n, T) IMD-day series: the IMD days of the (n, L) observed UTC series (columns 1..L-1 of it), then the n x k
    forecast IMD-day totals. The forecast is never mixed into an observed day."""
    observed = F.imd_day_series(utc)
    if forecast is None or forecast.shape[1] == 0:
        return observed
    forecast = np.asarray(forecast, dtype=np.float64)
    if forecast.shape[0] != observed.shape[0]:
        raise ValueError("forecast and observed series must cover the same pixels")
    return np.concatenate([observed, forecast], axis=1)


def features_at_last_day(imd: np.ndarray, position: np.ndarray, centres: np.ndarray, month: int,
                         clim: ClimTable) -> dict[str, np.ndarray]:
    """Feature values per centre pixel for the LAST column of the IMD-day series `imd` ((n_pixels, API_SPINUP + 2)).

    `position` is (n_centres, 9) rows of `imd` for the 3x3 block around each centre (-1 outside the grid, the centre
    itself at index F.CENTRE); `centres` their flat pixel ids; `month` the calendar month of the feature day.
    """
    if imd.shape[1] != F.API_SPINUP + 2:
        raise ValueError(f"the IMD-day series needs {F.API_SPINUP + 2} columns, got {imd.shape[1]}")
    t = imd.shape[1] - 1
    centre_imd = imd[position[:, F.CENTRE]]
    out: dict[str, np.ndarray] = {}
    block = F.accumulation_block(centre_imd[:, t + 1 - F.LOOKBACK:t + 1])
    for name, values in block.items():
        out[f"irain_{name}"] = values
    reference = clim.lookup(centres, np.full(len(centres), month))
    for w, n in enumerate(CLIM_WINDOWS):
        out[f"irain_acc{n}_vs_clim"] = anomaly(block[f"acc_{n}"], reference[:, w])
    everyone, tt = np.arange(len(centres)), np.full(len(centres), t)
    for k in F.API_DECAYS:
        out[f"iapi_{round(k * 100)}"] = F.api_at(F.api_state(centre_imd, k), centre_imd, k, everyone, tt)
    present = position >= 0
    accumulations = {1: imd, 3: trailing_window_sums(imd, 3)}
    for n in F.NBR_WINDOWS:
        values = np.where(present, accumulations[n][np.where(present, position, 0), t], np.nan)
        top, mean = F.neighbourhood_stats(values)
        out[f"inbr_max_acc_{n}"], out[f"inbr_mean_acc_{n}"] = top, mean
    return out


def lead_features(frame: pd.DataFrame, day: date, lead: int, store, forecast: np.ndarray | None,
                  clim: ClimTable) -> pd.DataFrame:
    """The `irain`, `iapi` and `inbr` float32 columns of the cells in `frame` (column `cell_id`) for feature day
    D + `lead`, in `frame` order and with its index; NaN for a cell outside the IMERG domain grid.

    `forecast` is the (>= lead, rows, cols) GFS IMD-day totals for D+1.. on the IMERG domain grid (None for lead 0);
    `clim` the train-range climatology of the cells' pixels (`imerg_features.imerg_climatology`). Lead 0 is the
    feature row of the training pipeline for IMD day D.
    """
    if lead not in LEADS:
        raise ValueError(f"lead must be one of {LEADS}, got {lead}")
    if lead > 0 and (forecast is None or forecast.shape[0] < lead or forecast.shape[1:] != (imerg_mod.ROWS, imerg_mod.COLS)):
        raise ValueError(f"lead {lead} needs forecast IMD-day totals of shape (>= {lead}, {imerg_mod.ROWS}, "
                         f"{imerg_mod.COLS})")
    target = day + timedelta(days=lead)
    flat = F.cell_pixels(frame["cell_id"].to_numpy(dtype=np.int64))
    names = F.all_names()
    out = {name: np.full(len(frame), np.nan, dtype=np.float32) for name in names}
    usable = np.flatnonzero(flat >= 0)
    if len(usable):
        centres = np.unique(flat[usable])
        neighbours = F.neighbour_pixels(centres)
        wanted = np.unique(neighbours[neighbours >= 0])
        first_imd = target - timedelta(days=F.API_SPINUP + 1)
        observed_columns = (day - first_imd).days + 1
        utc = store.gather(wanted // imerg_mod.COLS, wanted % imerg_mod.COLS, first_imd - timedelta(days=1),
                           observed_columns + 1)
        ahead = None if lead == 0 else forecast[:lead, wanted // imerg_mod.COLS, wanted % imerg_mod.COLS].T
        imd = imd_series_with_forecast(utc, ahead)
        position = np.where(neighbours >= 0, np.searchsorted(wanted, neighbours), -1)
        values = features_at_last_day(imd, position, centres, target.month, clim)
        own = np.searchsorted(centres, flat[usable])
        for name in names:
            out[name][usable] = values[name][own]
    return pd.DataFrame(out, index=frame.index)
