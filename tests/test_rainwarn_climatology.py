"""Climatology tables of the heavy-rain warnings on a fake UTC-day store (no data on disk)."""
from datetime import date, timedelta

import numpy as np
import pytest

from aetherguard.rainwarn import climatology as C
from aetherguard.rainwarn import prob as P


class FakeStore:
    """UTC-day rain from a function of (pixel index, date); NaN on the days in `missing`."""

    def __init__(self, rain, missing=()):
        self.rain, self.missing = rain, set(missing)

    def gather(self, rows, cols, first_day, length):
        out = np.empty((len(rows), length), dtype=np.float32)
        for j in range(length):
            day = first_day + timedelta(days=j)
            out[:, j] = np.nan if day in self.missing else [self.rain(i, day) for i in range(len(rows))]
        return out


def domain(n=2):
    return C.Domain(pixels=np.arange(100, 100 + n, dtype=np.int64), regions=np.array(["himalaya"] * n, dtype=object))


def test_calendar_index_gives_29_february_its_own_slot():
    assert C.calendar_index(date(2021, 1, 1)) == 0
    assert C.calendar_index(date(2020, 2, 29)) == 59
    assert C.calendar_index(date(2021, 3, 1)) == 60
    assert C.calendar_index(date(2021, 12, 31)) == 365


def test_imd_days_mix_the_two_utc_days():
    store = FakeStore(lambda i, d: 8.0 if d == date(2020, 7, 1) else 0.0)
    out = C.imd_days(store, np.array([0]), np.array([0]), date(2020, 7, 1), date(2020, 7, 3))
    assert out[0].tolist() == pytest.approx([1.0, 7.0, 0.0])        # IMD day 2 July holds 21 h of UTC 1 July


def test_percentiles_and_exceedance_shares_of_a_constant_climate():
    # pixel 0: 300 mm on every UTC day (every IMD day exceeds every threshold); pixel 1: dry
    store = FakeStore(lambda i, d: 300.0 if i == 0 else 0.0)
    clim = C.build(store, domain(), 2010, 2011, window_days=3)
    assert clim.p95[0] == pytest.approx(300.0) and clim.p99[1] == pytest.approx(0.0)
    heavy = clim.clim[P.THRESHOLDS.index("heavy")]
    assert np.allclose(heavy[0], 1.0) and np.allclose(heavy[1], 0.0)
    # 300 mm is not strictly above its own 99th percentile
    assert np.allclose(clim.clim[P.THRESHOLDS.index("p99")][0], 0.0)


def test_exceedance_share_follows_the_season_and_skips_missing_days():
    wet = lambda i, d: 100.0 if d.month in (7, 8) else 0.0
    missing = [date(2010, 1, 1) + timedelta(days=k) for k in range(365) if k % 2]
    clim = C.build(FakeStore(wet, missing), domain(1), 2010, 2012, window_days=2)
    heavy = clim.clim[P.THRESHOLDS.index("heavy"), 0]
    assert heavy[C.calendar_index(date(2011, 7, 20))] == pytest.approx(1.0)
    assert heavy[C.calendar_index(date(2011, 4, 20))] == pytest.approx(0.0)
    assert np.isfinite(heavy).all()


def test_save_load_round_trip_and_lookup(tmp_path):
    store = FakeStore(lambda i, d: float(i) * 50.0 + (d.day % 5) * 10.0)
    clim = C.build(store, domain(3), 2015, 2015, window_days=1)
    path = clim.save(tmp_path / "rainwarn" / "climatology.npz")
    again = C.Climatology.load(path)
    assert np.array_equal(again.pixels, clim.pixels) and np.allclose(again.clim, clim.clim, equal_nan=True)
    assert again.position(np.array([101, 7, 102])).tolist() == [1, -1, 2]
    assert again.threshold_mm("heavy") == 64.5
    assert again.threshold_mm("p95", np.array([2]))[0] == pytest.approx(clim.p95[2])
    assert again.prob("heavy", date(2024, 7, 3)).shape == (3,)


def test_percentile_thresholds_are_floored():
    store = FakeStore(lambda i, d: 2.0 if i == 0 else 300.0)
    clim = C.build(store, domain(), 2010, 2010, window_days=1, percentile_floor_mm=15.6)
    assert clim.p95[0] == pytest.approx(15.6) and clim.p99[1] == pytest.approx(300.0)
    assert np.allclose(clim.clim[P.THRESHOLDS.index("p95")][0], 0.0)      # 2 mm days do not exceed the floored threshold
