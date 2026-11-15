"""Forecast rain intensity for the forecast leads (live.lead_intensity, W7 leads on v4)."""
from datetime import date, datetime, timezone

import numpy as np
import pytest

from aetherguard.features import imerg_intensity as ii
from aetherguard.ingest import imerg as imerg_mod
from aetherguard.live import lead_intensity as li

UTC = timezone.utc
SHAPE = (imerg_mod.ROWS, imerg_mod.COLS)


def test_day_hours_of_00z_cycle():
    cycle = datetime(2024, 7, 1, 0, tzinfo=UTC)
    # IMD day X = (03 UTC X-1, 03 UTC X]: the first forecast day of the 00Z cycle of D is hours 3..27
    assert li.day_hours(cycle, date(2024, 7, 2)) == list(range(3, 28, 3))
    assert li.day_hours(cycle, date(2024, 7, 3)) == list(range(27, 52, 3))
    assert li.needed_hours(cycle, date(2024, 7, 1), 2) == list(range(3, 52, 3))


def test_day_hours_refuses_a_day_the_cycle_does_not_cover():
    cycle = datetime(2024, 7, 1, 12, tzinfo=UTC)
    with pytest.raises(ValueError):
        li.day_hours(cycle, date(2024, 7, 1))          # opens at 03 UTC 30 June, before the cycle


def test_blocks_from_cumulative():
    c = {3: np.full((2, 2), 1.0), 6: np.full((2, 2), 3.0), 9: np.full((2, 2), 3.5)}
    blocks = li.blocks_from_cumulative(c, [3, 6, 9])
    np.testing.assert_allclose(blocks[:, 0, 0], [2.0, 0.5])
    assert li.blocks_from_cumulative({3: c[3], 9: c[9]}, [3, 6, 9]) is None      # a missing hour: no day
    zero = li.blocks_from_cumulative({3: c[3]}, [0, 3])
    np.testing.assert_allclose(zero[0], 1.0)                                                   # hour 0 is zero


def test_blocks_never_negative():
    c = {3: np.full((1, 1), 2.0), 6: np.full((1, 1), 1.9999)}
    assert li.blocks_from_cumulative(c, [3, 6]).min() == 0.0


def test_forecast_day_maps():
    blocks = np.zeros((8,) + SHAPE, dtype=np.float32)
    blocks[2, 0, 0], blocks[3, 0, 0], blocks[7, 0, 0] = 6.0, 3.0, 0.2
    blocks[:, 1, 1] = np.nan
    maps = li.forecast_day_maps(blocks)
    assert set(maps) == set(ii.FIELDS)
    assert maps["max3h"][0, 0] == 6.0
    assert maps["max6h"][0, 0] == 9.0
    assert maps["wet_hours"][0, 0] == 6.0               # two blocks at or above 0.3 mm (0.1 mm/h); 0.2 mm is not wet
    assert maps["max1h"][0, 0] == 6.0                   # no sub-3-hour step: the 3-hour maximum stands in (then mapped)
    assert all(np.isnan(maps[name][1, 1]) for name in ii.FIELDS)
    with pytest.raises(ValueError):
        li.forecast_day_maps(blocks[:7])


def test_store_round_trip(tmp_path):
    lats, lons = np.array([8.0, 8.25]), np.array([72.0, 72.25, 72.5])
    fields = {h: np.full((2, 3), float(h)) for h in (3, 6)}
    cycle = datetime(2023, 7, 1, tzinfo=UTC)
    path = li.write_store_day(tmp_path, date(2023, 7, 1), cycle, fields, lats, lons, {"9": "NotPublishedError"})
    day = li.load_store_day(tmp_path, date(2023, 7, 1))
    assert path.is_file() and day.cycle == cycle
    assert sorted(day.cumulative) == [3, 6]
    np.testing.assert_array_equal(day.cumulative[6], fields[6])
    np.testing.assert_array_equal(day.lats, lats)
    assert day.failures == {"9": "NotPublishedError"}
    assert li.load_store_day(tmp_path, date(2023, 7, 2)) is None


def test_day_maps_on_grid_from_store(tmp_path):
    lats, lons = np.arange(8.0, 36.01, 0.25), np.arange(72.0, 98.01, 0.25)
    cycle = datetime(2023, 7, 1, tzinfo=UTC)
    hours = li.needed_hours(cycle, date(2023, 7, 1), 2)
    fields = {h: np.full((lats.size, lons.size), 0.5 * h, dtype=np.float32) for h in hours}   # 1.5 mm per 3 h
    li.write_store_day(tmp_path, date(2023, 7, 1), cycle, fields, lats, lons, {})
    day = li.load_store_day(tmp_path, date(2023, 7, 1))
    maps = li.day_maps_on_grid(day, date(2023, 7, 2))
    assert maps["max3h"].shape == SHAPE
    np.testing.assert_allclose(maps["max3h"][100, 100], 1.5, rtol=1e-5)
    np.testing.assert_allclose(maps["max6h"][100, 100], 3.0, rtol=1e-5)
    assert maps["wet_hours"][100, 100] == 24.0
    del fields[30]
    li.write_store_day(tmp_path, date(2023, 7, 1), cycle, fields, lats, lons, {})
    day = li.load_store_day(tmp_path, date(2023, 7, 1))
    assert li.day_maps_on_grid(day, date(2023, 7, 3)) is None          # hour 30 missing: day D+2 has no maps
    assert li.day_maps_on_grid(day, date(2023, 7, 2)) is not None
