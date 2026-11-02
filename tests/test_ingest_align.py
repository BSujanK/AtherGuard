"""Day-basis alignment of rain series (docs/phase1-design.md D5), all with hand-computed numbers."""
import numpy as np
import pandas as pd
import pytest

from aetherguard.ingest.align import (
    align_utc_to_imd_day,
    exact_imd_day_from_hourly_utc,
    trailing_sums,
)


def _days(start, n):
    return pd.date_range(start, periods=n, freq="D")


# ---------------------------------------------------------------- align_utc_to_imd_day
def test_align_weights_previous_utc_day_seven_eighths_and_current_one_eighth():
    out = align_utc_to_imd_day(_days("2024-07-01", 4), [8.0, 16.0, 0.0, 24.0])
    assert out.dtype == np.float64
    assert np.isnan(out[0])  # no D-1 for the first element
    assert out[1] == 0.875 * 8.0 + 0.125 * 16.0 == 9.0
    assert out[2] == 0.875 * 16.0 + 0.125 * 0.0 == 14.0
    assert out[3] == 0.875 * 0.0 + 0.125 * 24.0 == 3.0


def test_align_nan_propagates_to_both_days_that_use_it():
    out = align_utc_to_imd_day(_days("2024-07-01", 5), [1.0, np.nan, 3.0, 4.0, 5.0])
    assert np.isnan(out[0]) and np.isnan(out[1]) and np.isnan(out[2])
    assert out[3] == 0.875 * 3.0 + 0.125 * 4.0
    assert out[4] == 0.875 * 4.0 + 0.125 * 5.0


def test_align_single_element_is_all_nan_and_inputs_are_not_modified():
    assert np.isnan(align_utc_to_imd_day(_days("2024-07-01", 1), [5.0])).all()
    values = np.array([1.0, 2.0, 3.0])
    before = values.copy()
    align_utc_to_imd_day(_days("2024-07-01", 3), values)
    assert np.array_equal(values, before)


def test_align_accepts_date_strings_and_numpy_datetimes():
    expected = align_utc_to_imd_day(_days("2024-07-01", 3), [1.0, 2.0, 3.0])
    by_str = align_utc_to_imd_day(["2024-07-01", "2024-07-02", "2024-07-03"], [1.0, 2.0, 3.0])
    by_np = align_utc_to_imd_day(np.array(["2024-07-01", "2024-07-02", "2024-07-03"], dtype="datetime64[D]"),
                                 [1.0, 2.0, 3.0])
    assert np.array_equal(expected, by_str, equal_nan=True)
    assert np.array_equal(expected, by_np, equal_nan=True)


@pytest.mark.parametrize("dates", [
    ["2024-07-01", "2024-07-03"],                    # a day is missing
    ["2024-07-02", "2024-07-01"],                    # descending
    ["2024-07-01", "2024-07-01"],                    # duplicate
    ["2024-02-28", "2024-03-01"],                    # 2024 is a leap year: 29 Feb is missing
])
def test_align_rejects_non_consecutive_dates(dates):
    with pytest.raises(ValueError, match="consecutive"):
        align_utc_to_imd_day(dates, [1.0, 2.0])


def test_align_rejects_timestamps_that_are_not_whole_days():
    with pytest.raises(ValueError, match="whole days"):
        align_utc_to_imd_day(pd.to_datetime(["2024-07-01 00:00", "2024-07-02 12:00"]), [1.0, 2.0])


def test_align_rejects_timezone_aware_dates():
    with pytest.raises(ValueError, match="timezone"):
        align_utc_to_imd_day(pd.date_range("2024-07-01", periods=2, tz="UTC"), [1.0, 2.0])


def test_align_rejects_length_mismatch_empty_and_non_1d():
    with pytest.raises(ValueError, match="length"):
        align_utc_to_imd_day(_days("2024-07-01", 3), [1.0, 2.0])
    with pytest.raises(ValueError, match="empty"):
        align_utc_to_imd_day([], [])
    with pytest.raises(ValueError, match="1-D"):
        align_utc_to_imd_day(_days("2024-07-01", 2), [[1.0], [2.0]])


def test_align_across_leap_day_and_year_boundary_uses_the_true_previous_day():
    leap = align_utc_to_imd_day(_days("2024-02-28", 3), [10.0, 20.0, 40.0])  # 28, 29 Feb, 1 Mar
    assert leap[1] == 0.875 * 10.0 + 0.125 * 20.0          # 29 Feb uses 28 Feb
    assert leap[2] == 0.875 * 20.0 + 0.125 * 40.0          # 1 Mar uses 29 Feb, not 28 Feb
    year_end = align_utc_to_imd_day(_days("2023-12-31", 2), [16.0, 8.0])
    assert year_end[1] == 0.875 * 16.0 + 0.125 * 8.0       # 1 Jan 2024 uses 31 Dec 2023


def test_align_is_exact_when_rain_rate_is_constant_across_days():
    # constant 1 mm/h: every UTC day is 24 mm and every IMD day is 24 mm
    out = align_utc_to_imd_day(_days("2024-07-01", 5), [24.0] * 5)
    assert np.allclose(out[1:], 24.0)


# ---------------------------------------------------------------- exact_imd_day_from_hourly_utc
def _hourly(start, end):
    return pd.date_range(start, end, freq="h")


def test_exact_imd_day_window_is_0300_utc_exclusive_to_0300_utc_inclusive():
    stamps = _hourly("2024-07-01 00:00", "2024-07-04 00:00")
    values = np.ones(len(stamps))
    totals = exact_imd_day_from_hourly_utc(stamps, values)
    # IMD day 2 Jul = stamps 04:00 (1 Jul) .. 03:00 (2 Jul) = 24 stamps; same for 3 Jul
    assert totals.loc["2024-07-02"] == 24.0
    assert totals.loc["2024-07-03"] == 24.0
    # the stamp at exactly 03:00 UTC belongs to the day that ENDS at 03:00 UTC (hour 02:00-03:00)
    marked = pd.Series(0.0, index=stamps)
    marked.loc["2024-07-02 03:00"] = 5.0
    marked.loc["2024-07-02 04:00"] = 7.0
    totals = exact_imd_day_from_hourly_utc(marked.index, marked.to_numpy())
    assert totals.loc["2024-07-02"] == 5.0    # 03:00 stamp ends IMD day 2 Jul
    assert totals.loc["2024-07-03"] == 7.0    # 04:00 stamp is the first hour of IMD day 3 Jul


def test_exact_imd_day_marks_incomplete_days_nan_and_reindexes_gaps():
    stamps = _hourly("2024-07-01 10:00", "2024-07-03 12:00")
    totals = exact_imd_day_from_hourly_utc(stamps, np.ones(len(stamps)))
    assert totals.index.name == "imd_date"
    assert list(totals.index) == list(pd.date_range("2024-07-02", "2024-07-04"))
    assert np.isnan(totals.loc["2024-07-02"])         # starts 10:00 UTC on 1 Jul: earlier stamps missing
    assert totals.loc["2024-07-03"] == 24.0
    assert np.isnan(totals.loc["2024-07-04"])         # ends 12:00 UTC on 3 Jul: later stamps missing
    # an interior gap of one hour makes that day NaN instead of a partial sum
    gap = stamps.delete(stamps.get_loc(pd.Timestamp("2024-07-02 09:00")))
    totals = exact_imd_day_from_hourly_utc(gap, np.ones(len(gap)))
    assert np.isnan(totals.loc["2024-07-03"])
    # a whole missing IMD day appears as an explicit NaN row
    wide = _hourly("2024-07-01 04:00", "2024-07-05 03:00")
    keep = (wide <= pd.Timestamp("2024-07-02 03:00")) | (wide > pd.Timestamp("2024-07-04 03:00"))
    totals = exact_imd_day_from_hourly_utc(wide[keep], np.ones(keep.sum()))
    assert list(totals.index) == list(pd.date_range("2024-07-02", "2024-07-05"))
    assert totals.loc["2024-07-02"] == 24.0 and totals.loc["2024-07-05"] == 24.0
    assert np.isnan(totals.loc["2024-07-03"]) and np.isnan(totals.loc["2024-07-04"])


def test_exact_imd_day_nan_hour_makes_the_day_nan():
    stamps = _hourly("2024-07-01 04:00", "2024-07-03 03:00")
    values = np.ones(len(stamps))
    values[5] = np.nan
    totals = exact_imd_day_from_hourly_utc(stamps, values)
    assert np.isnan(totals.loc["2024-07-02"])
    assert totals.loc["2024-07-03"] == 24.0


def test_exact_imd_day_leap_day_and_year_boundary():
    stamps = _hourly("2024-02-28 04:00", "2024-03-01 03:00")
    totals = exact_imd_day_from_hourly_utc(stamps, np.full(len(stamps), 0.5))
    assert list(totals.index) == [pd.Timestamp("2024-02-29"), pd.Timestamp("2024-03-01")]
    assert (totals == 12.0).all()
    stamps = _hourly("2023-12-31 04:00", "2024-01-01 03:00")
    totals = exact_imd_day_from_hourly_utc(stamps, np.ones(len(stamps)))
    assert list(totals.index) == [pd.Timestamp("2024-01-01")] and totals.iloc[0] == 24.0


def test_exact_imd_day_rejects_bad_timestamps():
    with pytest.raises(ValueError, match="strictly increasing"):
        exact_imd_day_from_hourly_utc(pd.to_datetime(["2024-07-01 05:00", "2024-07-01 04:00"]), [1.0, 1.0])
    with pytest.raises(ValueError, match="whole hours"):
        exact_imd_day_from_hourly_utc(pd.to_datetime(["2024-07-01 04:30", "2024-07-01 05:30"]), [1.0, 1.0])
    with pytest.raises(ValueError, match="timezone"):
        exact_imd_day_from_hourly_utc(pd.date_range("2024-07-01", periods=2, freq="h", tz="Asia/Kolkata"),
                                      [1.0, 1.0])
    with pytest.raises(ValueError, match="length"):
        exact_imd_day_from_hourly_utc(_hourly("2024-07-01 04:00", "2024-07-01 06:00"), [1.0])


# ---------------------------------------------------------------- the point of the design
def test_night_storm_is_in_imd_day_d_but_in_utc_day_d_minus_1_and_the_approximation_recovers_most_of_it():
    """60 mm falling uniformly 00:00-03:00 IST on D = 18:30-21:30 UTC on D-1 (20 mm/h)."""
    stamps = _hourly("2024-07-25 00:00", "2024-08-03 00:00")
    hourly = pd.Series(0.0, index=stamps)
    # value stamped T is the total of the hour ending at T
    hourly.loc["2024-07-29 19:00"] = 10.0   # 18:30-19:00
    hourly.loc["2024-07-29 20:00"] = 20.0
    hourly.loc["2024-07-29 21:00"] = 20.0
    hourly.loc["2024-07-29 22:00"] = 10.0   # 21:00-21:30
    assert hourly.sum() == 60.0

    exact = exact_imd_day_from_hourly_utc(hourly.index, hourly.to_numpy())
    assert exact.loc["2024-07-30"] == 60.0          # all inside IMD day D
    assert exact.loc["2024-07-29"] == 0.0

    # UTC calendar-day totals: the hour ending at T belongs to the UTC day of its start (T - 1 h)
    utc = hourly.groupby((hourly.index - pd.Timedelta(hours=1)).normalize()).sum()
    utc = utc.loc["2024-07-26":"2024-08-02"]        # complete UTC days only
    assert utc.loc["2024-07-29"] == 60.0            # present in UTC day D-1
    assert utc.loc["2024-07-30"] == 0.0             # absent from UTC day D

    aligned = pd.Series(align_utc_to_imd_day(utc.index, utc.to_numpy()), index=utc.index)
    assert aligned.loc["2024-07-30"] == 0.875 * 60.0 == 52.5
    # quantified approximation error: 7.5 mm (12.5 %) of the storm is pushed into IMD day D-1
    assert exact.loc["2024-07-30"] - aligned.loc["2024-07-30"] == 7.5
    assert aligned.loc["2024-07-29"] - exact.loc["2024-07-29"] == 7.5
    # mass is conserved over the two days
    assert aligned.loc["2024-07-29":"2024-07-30"].sum() == exact.loc["2024-07-29":"2024-07-30"].sum()


# ---------------------------------------------------------------- trailing_sums
def test_trailing_sums_include_the_day_and_are_nan_before_a_full_window():
    values = np.arange(1.0, 11.0)  # 1..10
    out = trailing_sums(values, windows=(1, 3, 5))
    assert set(out) == {1, 3, 5}
    assert np.array_equal(out[1], values)
    assert np.isnan(out[3][:2]).all() and out[3][2] == 1 + 2 + 3 and out[3][9] == 8 + 9 + 10
    assert np.isnan(out[5][:4]).all() and out[5][4] == 15.0 and out[5][9] == 6 + 7 + 8 + 9 + 10
    assert all(arr.dtype == np.float64 and arr.shape == values.shape for arr in out.values())


def test_trailing_sums_default_windows_and_window_longer_than_the_series():
    out = trailing_sums(np.ones(10))
    assert list(out) == [1, 3, 5, 7, 14, 30]
    assert out[7][6] == 7.0 and np.isnan(out[7][:6]).all()
    assert np.isnan(out[14]).all() and np.isnan(out[30]).all()


def test_trailing_sums_nan_policy_is_explicit():
    values = np.array([1.0, 2.0, np.nan, 4.0, 5.0, 6.0])
    strict = trailing_sums(values, windows=(2, 3))
    assert np.isnan(strict[2][2]) and np.isnan(strict[2][3])      # windows containing the NaN day
    assert strict[2][4] == 9.0
    assert np.isnan(strict[3][2]) and np.isnan(strict[3][3]) and np.isnan(strict[3][4])
    assert strict[3][5] == 15.0
    tolerant = trailing_sums(values, windows=(3,), max_missing=1)
    assert tolerant[3][2] == 3.0 and tolerant[3][3] == 6.0 and tolerant[3][4] == 9.0   # missing day adds nothing
    assert tolerant[3][5] == 15.0
    # a window made only of missing days is never 0
    all_missing = trailing_sums(np.array([np.nan, np.nan, 1.0]), windows=(2,), max_missing=2)
    assert np.isnan(all_missing[2][1])


def test_trailing_sums_does_not_mistake_zero_rain_for_missing():
    out = trailing_sums(np.zeros(5), windows=(3,))
    assert out[3][2] == 0.0 and out[3][4] == 0.0


def test_trailing_sums_validation():
    with pytest.raises(ValueError, match="1-D"):
        trailing_sums(np.ones((2, 2)))
    with pytest.raises(ValueError, match="positive"):
        trailing_sums(np.ones(5), windows=(0,))
    with pytest.raises(ValueError, match="max_missing"):
        trailing_sums(np.ones(5), max_missing=-1)
    assert trailing_sums(np.array([]), windows=(3,))[3].shape == (0,)
