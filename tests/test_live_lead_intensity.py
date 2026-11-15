"""Forecast rain intensity for the forecast leads (live.lead_intensity, W7 leads on v4)."""
from datetime import date, datetime, timezone

import numpy as np
import pytest

from aetherguard.features import imerg_intensity as ii
from aetherguard.grid import latlon_to_cell
from aetherguard.ingest import imerg as imerg_mod
from aetherguard.live import lead_intensity as li

UTC = timezone.utc
SHAPE = (imerg_mod.ROWS, imerg_mod.COLS)
WAYANAD = latlon_to_cell(11.47, 76.13)
KATHMANDU = latlon_to_cell(27.70, 85.32)


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


# ------------------------------------------------------------------------------------------- lead windows and maps

def _maps(value):
    return {name: np.full(SHAPE, value, dtype=np.float32) for name in ii.FIELDS}


def _write_day(root, store, day, value):
    path = root / store / f"{day.year}" / f"{day:%Y%m%d}.npz"
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(path, **_maps(value), n_halfhours=np.full(SHAPE, 48, dtype=np.float32))


class _Doubling:
    """A stand-in for the quantile maps: every value times two, so a mapped day is visible."""
    def apply(self, source, lead, field):
        return np.asarray(field, dtype=np.float32) * 2


def test_window_sources_by_lead(tmp_path):
    day = date(2026, 11, 10)
    for k, d in enumerate((date(2026, 11, 7), date(2026, 11, 8), date(2026, 11, 9))):
        _write_day(tmp_path, "late", d, 1.0 + k)
    _write_day(tmp_path, "early_live", day, 10.0)
    gfs_days = {date(2026, 11, 11): _maps(20.0), date(2026, 11, 12): _maps(30.0)}
    sources = li.LeadSources(late_root=tmp_path, early_root=tmp_path, gfs=lambda d: gfs_days.get(d), maps=_Doubling())
    kinds = {lead: li.window(day, lead, sources)[1]["days"] for lead in (1, 2, 3)}
    assert kinds[1] == {"2026-11-08": "late", "2026-11-09": "late", "2026-11-10": "early_live"}
    assert kinds[2] == {"2026-11-09": "late", "2026-11-10": "early_live", "2026-11-11": "gfs3h"}
    assert kinds[3] == {"2026-11-10": "early_live", "2026-11-11": "gfs3h", "2026-11-12": "gfs3h"}
    maps, _ = li.window(day, 3, sources)
    assert [float(m["max3h"][0, 0]) for m in maps] == [20.0, 40.0, 60.0]     # Early and GFS days mapped, Late as is


def test_lead_frame_matches_the_feature_function(tmp_path):
    day = date(2026, 11, 10)
    for k, d in enumerate((date(2026, 11, 8), date(2026, 11, 9))):
        _write_day(tmp_path, "late", d, 1.0 + k)
    _write_day(tmp_path, "early_live", day, 10.0)
    sources = li.LeadSources(late_root=tmp_path, early_root=tmp_path, gfs=lambda d: None, maps=_Doubling())
    cells = np.array([WAYANAD, KATHMANDU], dtype=np.int64)
    frame, status = li.lead_frame(day, 1, cells, sources)
    assert status["used"] and list(frame.columns) == ii.feature_names()
    assert (frame["iint_max3h_1"] == 20.0).all()                  # day D: the Early day, mapped
    assert (frame["iint_max3h_max3d"] == 20.0).all()


def test_lead_frame_refuses_a_missing_day(tmp_path):
    day = date(2026, 11, 10)
    _write_day(tmp_path, "late", date(2026, 11, 9), 1.0)
    _write_day(tmp_path, "early_live", day, 10.0)
    sources = li.LeadSources(late_root=tmp_path, early_root=tmp_path, gfs=lambda d: None, maps=_Doubling())
    frame, status = li.lead_frame(day, 1, np.array([WAYANAD]), sources)
    assert frame is None and not status["used"]
    assert "2026-11-08" in status["reason"]                       # v4 never saw a missing intensity input: no NaN handed over
    frame, status = li.lead_frame(day, 2, np.array([WAYANAD]), sources)
    assert frame is None and "2026-11-11" in status["reason"]


def test_fit_and_apply_intensity_maps():
    rng = np.random.default_rng(0)
    obs = rng.gamma(0.6, 6.0, size=(4000,)).astype(np.float32)
    fcst = obs * 0.4                                              # a forecast at 40% of IMERG's intensities
    regions = np.array(["himalaya"] * 2000 + ["western_ghats"] * 2000, dtype=object)
    pairs = {(source, lead, field): (fcst, obs, regions) for source, lead in (("gfs3h", 1),) for field in ii.FIELDS}
    maps = li.fit_maps(pairs)
    curve = maps.curves[("gfs3h:max3h", 1, "himalaya")]
    np.testing.assert_allclose(np.median(curve.apply(fcst[:2000][fcst[:2000] > 0.1])),
                               np.median(obs[:2000][fcst[:2000] > 0.1]), rtol=0.05)
    assert ("gfs3h:max3h", 1, "rest") in maps.curves             # every pixel of a field has a curve
