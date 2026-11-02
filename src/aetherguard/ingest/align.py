"""Day-basis alignment of rain series (docs/phase1-design.md D5). Pure functions, no I/O.

Three different "days" meet in this project:

* IMD day D: 08:30 IST on D-1 to 08:30 IST on D, which is 03:00 UTC on D-1 to 03:00 UTC on D (IST = UTC+5:30),
  labelled by its END date D. This is the IMD convention; it has not been confirmed from IMD documentation in
  this project and is the working assumption for every function below.
* UTC day D: 00:00 UTC on D to 24:00 UTC on D (CHIRPS, the NASA POWER zarr `utc` store).
* The catalog's local calendar date of an event (labels): treated as the IMD day that ends on that date.

An event at 02:00 IST on date D is inside IMD day D but inside UTC day D-1 (20:30 UTC on D-1).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# IMD day D = last 21 h of UTC day D-1 + first 3 h of UTC day D (see module docstring).
IMD_SHARE_OF_PREVIOUS_UTC_DAY = 21 / 24   # 0.875, exact in binary floating point
IMD_SHARE_OF_CURRENT_UTC_DAY = 3 / 24     # 0.125, exact in binary floating point
HOURS_PER_DAY = 24
# Hour stamp T (UTC) covers the hour (T-1h, T]; the IMD day labelled D has stamps in (03:00 UTC D-1, 03:00 UTC D].
_STAMP_TO_DAY_SHIFT = pd.Timedelta(hours=4)  # (T - 4h).floor("D") is D-1, because T-1h is the hour start
DEFAULT_WINDOWS = (1, 3, 5, 7, 14, 30)


def _naive_index(values, what: str) -> pd.DatetimeIndex:
    index = pd.DatetimeIndex(values)
    if index.tz is not None:
        raise ValueError(f"{what} must be timezone-naive (UTC or calendar dates), got timezone {index.tz}")
    return index


def _values_1d(values, what: str = "values") -> np.ndarray:
    array = np.array(values, dtype=np.float64)  # copy: callers' data is never modified
    if array.ndim != 1:
        raise ValueError(f"{what} must be 1-D, got shape {array.shape}")
    return array


def align_utc_to_imd_day(dates, values) -> np.ndarray:
    """Approximate IMD-day totals from UTC-day totals (CHIRPS, POWER utc store).

    Day basis: `dates[k]` is the UTC calendar day of `values[k]`; the result at k is the total for the IMD day
    LABELLED `dates[k]` (03:00 UTC on dates[k]-1 to 03:00 UTC on dates[k]):

        P_imd(D) = 0.875 * P_utc(D-1) + 0.125 * P_utc(D)

    This is a linear approximation that assumes rain is spread uniformly within each UTC day. It is exact for a
    constant rain rate and conserves mass over a run of days, but it smears timing: a storm that falls entirely in
    the 21 h of UTC day D-1 after 03:00 UTC is wholly inside IMD day D, yet only 87.5 % of it is assigned to D (for
    60 mm: 52.5 mm, an error of 7.5 mm that lands on IMD day D-1). The worst case is a UTC-day total that fell
    entirely between 00:00 and 03:00 UTC (which is IMD day D-1): 87.5 % of it is wrongly assigned to D.

    `dates` must be consecutive daily dates (no gaps, no duplicates, whole days, timezone-naive). The first result is
    NaN (there is no D-1). A NaN in either value of a pair gives NaN. Returns a float64 array, same length as input.
    """
    index = _naive_index(dates, "dates")
    array = _values_1d(values)
    if len(index) != len(array):
        raise ValueError(f"dates and values must have the same length, got {len(index)} and {len(array)}")
    if len(index) == 0:
        raise ValueError("dates and values are empty")
    if not (index == index.normalize()).all():
        raise ValueError("dates must be whole days (midnight timestamps or calendar dates)")
    if not ((index[1:] - index[:-1]) == pd.Timedelta(days=1)).all():
        raise ValueError("dates must be consecutive daily dates (no gaps, duplicates or reordering)")
    out = np.full(len(array), np.nan, dtype=np.float64)
    out[1:] = IMD_SHARE_OF_PREVIOUS_UTC_DAY * array[:-1] + IMD_SHARE_OF_CURRENT_UTC_DAY * array[1:]
    return out


def exact_imd_day_from_hourly_utc(hour_timestamps, values) -> pd.Series:
    """Exact IMD-day totals from hourly data stamped in UTC.

    Hourly convention (as in Open-Meteo): a value stamped T is the total of the PRECEDING hour, (T-1h, T]. The IMD
    day labelled D (03:00 UTC on D-1 to 03:00 UTC on D) therefore sums the 24 stamps from 04:00 UTC on D-1 to
    03:00 UTC on D inclusive: the stamp at 03:00 UTC on D (hour 02:00-03:00) belongs to D, the stamp at 03:00 UTC on
    D-1 belongs to D-1. Hours are never split, so this is exact for hourly-resolved data.

    `hour_timestamps` must be strictly increasing, on the hour and timezone-naive (UTC). A day is returned NaN, never
    a partial sum, unless all 24 stamps are present and finite. The result is indexed by the IMD day label
    (`imd_date`, consecutive days from the first to the last label touched, so missing days show up as NaN rows).
    """
    index = _naive_index(hour_timestamps, "hour_timestamps")
    array = _values_1d(values)
    if len(index) != len(array):
        raise ValueError(f"hour_timestamps and values must have the same length, got {len(index)} and {len(array)}")
    if len(index) == 0:
        raise ValueError("hour_timestamps and values are empty")
    if not (index.is_monotonic_increasing and index.is_unique):
        raise ValueError("hour_timestamps must be strictly increasing (sorted, no duplicates)")
    if not (index == index.floor("h")).all():
        raise ValueError("hour_timestamps must be on whole hours")
    labels = (index - _STAMP_TO_DAY_SHIFT).floor("D") + pd.Timedelta(days=1)
    grouped = pd.Series(array).groupby(labels)
    complete = (grouped.size() == HOURS_PER_DAY) & (grouped.count() == HOURS_PER_DAY)
    totals = grouped.sum().where(complete)
    full = pd.date_range(totals.index[0], totals.index[-1], freq="D", name="imd_date")
    return totals.reindex(full).astype(np.float64)


def trailing_sums(values, windows=DEFAULT_WINDOWS, max_missing: int = 0) -> dict[int, np.ndarray]:
    """Trailing sums over `windows` days ending at, and including, each index.

    Day basis: whatever the input series uses (one value per consecutive day); feed IMD-day series to get sums
    that end on IMD day D. Returns {window: float64 array, same length as `values`}.

    No partial windows: the result is NaN while the window extends before the first element, and NaN when more than
    `max_missing` of its days are NaN or when every day in it is NaN. With `max_missing` > 0 a tolerated missing day
    contributes 0, so the sum is a lower bound; the default 0 never does that. Zero rain is a value, not missing.
    """
    array = _values_1d(values)
    if max_missing < 0:
        raise ValueError(f"max_missing must be >= 0, got {max_missing}")
    result: dict[int, np.ndarray] = {}
    missing = np.isnan(array)
    zero_filled = np.where(missing, 0.0, array)
    for window in windows:
        if int(window) != window or window < 1:
            raise ValueError(f"windows must be positive integers, got {window!r}")
        window = int(window)
        out = np.full(len(array), np.nan, dtype=np.float64)
        if len(array) >= window:
            sums = np.lib.stride_tricks.sliding_window_view(zero_filled, window).sum(axis=1)
            n_missing = np.lib.stride_tricks.sliding_window_view(missing, window).sum(axis=1)
            out[window - 1:] = np.where((n_missing <= max_missing) & (n_missing < window), sums, np.nan)
        result[window] = out
    return result
