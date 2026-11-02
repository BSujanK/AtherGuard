"""Daily stores, window features, climatology, wetness and the day-basis rules (design D5), on synthetic stores."""
import numpy as np
import pandas as pd
import pytest
from features_helpers import (
    BLOCK,
    CHIRPS_MISSING,
    GAPPED_IMD_POINT,
    IMD_MISSING_DAY,
    POWER_OCEAN_POINT,
    UNCOVERED_IMD_POINT,
    block_cell,
    cid,
    day_number,
    imd_point_of_block,
    write_chirps,
    write_imd,
    write_world,
)

from aetherguard.features import compute, sources
from aetherguard.grid import cell_center
from aetherguard.ingest.align import align_utc_to_imd_day, trailing_sums
from aetherguard.ingest.chirps import ChirpsStore
from aetherguard.ingest.imd import ImdGrid
from aetherguard.ingest.power import PowerWetness

TRAIN = ("2010-01-01", "2010-12-31")


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    return write_world(tmp_path_factory.mktemp("world"))


def same(a, b):
    np.testing.assert_array_equal(np.asarray(a, dtype=float), np.asarray(b, dtype=float))


def cells_with(i_j):
    return np.array([block_cell(i, j) for i, j in i_j], dtype=np.int64)


# ------------------------------------------------------------------------------------------- daily stores

def test_imd_pixels_match_the_scalar_nearest_index_and_outside_the_grid_is_minus_one(world):
    store = sources.load_imd(world["imd"])
    ids = np.array([block_cell(0, 0), block_cell(7, 13), block_cell(19, 19), cid(100, 100)])
    got = store.pixels(ids)
    for cell, pix in zip(ids[:3], got[:3]):
        lat, lon = cell_center(int(cell))
        assert (pix // 135, pix % 135) == ImdGrid.nearest_index(lat, lon)
    assert got[3] == -1


def test_imd_gather_equals_the_public_reader_across_a_year_boundary(world):
    store = sources.load_imd(world["imd"])
    grid = ImdGrid(world["imd"])
    ids = cells_with([(0, 0), (5, 9), (19, 19)])
    first = day_number("2010-12-20")
    got = store.gather(store.pixels(ids), np.full(3, first), 30)
    for row, cell in enumerate(ids):
        same(got[row], grid.cell_series(int(cell), "2010-12-20", "2011-01-18"))


def test_imd_missing_day_and_uncovered_point_are_nan_and_a_year_outside_the_store_is_counted(world):
    store = sources.load_imd(world["imd"])
    gapped = [(i, j) for i in range(20) for j in range(20) if imd_point_of_block(i, j) == GAPPED_IMD_POINT][0]
    uncovered = [(i, j) for i in range(20) for j in range(20) if imd_point_of_block(i, j) == UNCOVERED_IMD_POINT][0]
    ids = cells_with([gapped, uncovered])
    first = day_number(IMD_MISSING_DAY) - 2
    got = store.gather(store.pixels(ids), np.full(2, first), 5)
    assert np.isnan(got[0, 2]) and np.isfinite(got[0, [0, 1, 3, 4]]).all()
    assert np.isnan(got[1]).all()
    before = store.counters["days_outside_store"]
    out = store.gather(store.pixels(ids[:1]), np.array([day_number("2013-07-15")]), 4)
    assert np.isnan(out).all() and store.counters["days_outside_store"] == before + 4


def test_chirps_gather_equals_the_public_reader_including_missing_day_and_the_year_gap(world):
    store = sources.load_chirps(world["chirps"])
    public = ChirpsStore(world["chirps"])
    ids = cells_with([(0, 0), (4, 11), (19, 19)])
    for start in ("2011-03-01", "2011-12-20", "2013-05-25", "2012-12-25"):
        first = day_number(start)
        got = store.gather(store.pixels(ids), np.full(3, first), 31)
        end = str((np.datetime64(start) + np.timedelta64(30, "D")))
        for row, cell in enumerate(ids):
            same(got[row], public.cell_series(int(cell), start, end))
    assert np.isnan(store.gather(store.pixels(ids[:1]), np.array([day_number(CHIRPS_MISSING)]), 1)).all()


def test_chirps_cell_outside_the_stored_window_has_no_pixel(world):
    store = sources.load_chirps(world["chirps"])
    pix = store.pixels(np.array([block_cell(0, 0), cid(BLOCK[0] + 60, BLOCK[1])]))
    assert pix[0] >= 0 and pix[1] == -1
    assert np.isnan(store.gather(pix[1:], np.array([day_number("2010-06-01")]), 3)).all()


def test_series_equals_gather_for_a_common_first_day(world):
    store = sources.load_chirps(world["chirps"])
    pix = store.pixels(cells_with([(0, 0), (3, 3)]))
    first, last = day_number("2010-12-28"), day_number("2011-01-05")
    series = store.series(pix, first, last)
    assert series.shape == (2, 9)
    same(series, store.gather(pix, np.full(2, first), 9))


def test_wetness_is_masked_where_the_root_zone_is_missing_and_matches_the_public_reader(world):
    public = PowerWetness(world["power"])
    ocean = [(i, j) for i in range(20) for j in range(20)
             if public.nearest_point(block_cell(i, j)) == POWER_OCEAN_POINT][0]
    land = (0, 0)
    ids = cells_with([land, ocean])
    top, root = sources.load_wetness(world["power"], ids)
    pix = top.pixels(ids)
    first = day_number("2010-12-28")
    got_top, got_root = top.gather(pix, np.full(2, first), 8), root.gather(pix, np.full(2, first), 8)
    same(got_top[0], public.cell_series(int(ids[0]), "2010-12-28", "2011-01-04", "GWETTOP"))
    same(got_root[0], public.cell_series(int(ids[0]), "2010-12-28", "2011-01-04", "GWETROOT"))
    assert np.isnan(got_top[1]).all() and np.isnan(got_root[1]).all()   # GWETTOP == 1.0 there in the raw file
    assert (public.cell_series(int(ids[1]), "2010-12-28", "2011-01-04", "GWETTOP") == 1.0).all()


# ------------------------------------------------------------------------------------------- numerics

def test_aligned_chirps_equals_align_utc_to_imd_day_row_by_row():
    rng = np.random.default_rng(1)
    utc = rng.uniform(0, 50, size=(4, 31)).astype(np.float32)
    utc[1, 7] = np.nan
    got = compute.aligned_chirps(utc)
    dates = pd.date_range("2010-01-01", periods=31)
    for row in range(4):
        same(got[row], align_utc_to_imd_day(dates, utc[row].astype(float))[1:])
    assert np.isnan(got[1, 6]) and np.isnan(got[1, 7]) and np.isfinite(got[1, 8])


def test_trailing_window_sums_equal_align_trailing_sums_including_the_nan_rule():
    rng = np.random.default_rng(2)
    daily = rng.uniform(0, 30, size=(3, 60))
    daily[1, 20] = np.nan
    for n in (3, 7, 30):
        got = compute.trailing_window_sums(daily, n)
        for row in range(3):
            np.testing.assert_allclose(got[row], trailing_sums(daily[row], (n,))[n], rtol=0, atol=1e-9, equal_nan=True)


def test_rain_block_windows_and_nan_rule_by_hand():
    daily = np.arange(1.0, 31.0)[None, :].repeat(2, axis=0)      # days D-29..D hold 1..30
    daily[1, 10] = np.nan                                       # 20 days before D: only the 30-day window sees it
    block = compute.rain_block(daily)
    assert block["acc_1"][0] == 30 and block["acc_3"][0] == 30 + 29 + 28 and block["acc_7"][0] == sum(range(24, 31))
    assert block["acc_14"][0] == sum(range(17, 31)) and block["acc_30"][0] == 465
    assert block["max1d_7"][0] == 30 and block["max1d_30"][0] == 30 and block["wetdays_30"][0] == 30
    assert block["acc_14"][1] == block["acc_14"][0] and np.isnan(block["acc_30"][1])
    assert np.isnan(block["max1d_30"][1]) and np.isnan(block["wetdays_30"][1])
    assert block["max1d_7"][1] == 30


def test_rain_block_days_since_10mm_wet_days_and_share():
    daily = np.zeros((4, 30))
    daily[0, -1] = 12.0                    # today >= 10 mm
    daily[1, -4] = 10.0                    # three days ago
    daily[2, :] = 0.5                      # never >= 10 mm, no wet day
    daily[3, -1], daily[3, -2] = 0.4, 0.4  # acc_3 < 1 mm
    block = compute.rain_block(daily)
    assert list(block["days_since_10mm"]) == [0, 3, 30, 30]
    assert list(block["wetdays_30"]) == [1, 1, 0, 0]
    assert block["share1_3"][0] == 1.0 and np.isnan(block["share1_3"][3])
    assert np.isnan(block["share1_3"][1])  # acc_3 = 0 mm: the share is undefined


def test_primary_source_selection_prefers_imd_then_chirps_then_none():
    imd = np.full((4, 30), 2.0)
    chi = np.full((4, 30), 5.0)
    imd[1, -1] = np.nan          # IMD missing on D, CHIRPS valid
    imd[2, :] = np.nan           # uncovered cell
    chi[2, :] = np.nan           # and CHIRPS missing -> none ... except row 3 below
    imd[3, :] = np.nan           # uncovered, CHIRPS valid
    primary, source = compute.select_primary(imd, chi)
    assert list(source) == ["imd", "chirps_aligned", "none", "chirps_aligned"]
    assert (primary[0] == 2.0).all() and (primary[1] == 5.0).all() and (primary[3] == 5.0).all()
    assert np.isnan(primary[2]).all()


def test_source_features_and_disagreement_formulas():
    imd = np.full((3, 30), 2.0)
    chi = np.full((3, 30), 1.0)
    imd[1, -3] = np.nan                    # NaN inside the 7-day window but not the 1-day / 3-day windows
    chi[2, -1] = np.nan
    block = compute.source_block(imd, chi)
    assert block["imd_acc_1"][0] == 2 and block["imd_acc_3"][0] == 6 and block["imd_acc_7"][0] == 14
    assert block["chi_acc_7"][0] == 7
    assert block["dis_diff_3"][0] == 3 and block["dis_ratio_3"][0] == pytest.approx((6 + 1) / (3 + 1))
    assert np.isnan(block["imd_acc_3"][1]) and np.isnan(block["dis_diff_3"][1]) and block["dis_diff_1"][1] == 1
    assert np.isnan(block["chi_acc_1"][2]) and np.isnan(block["dis_ratio_1"][2])
    assert list(block["dis_both"]) == [1.0, 1.0, 0.0]


def test_wetness_block_uses_day_before_and_lagged_changes():
    top = np.tile(np.arange(10, 18, dtype=float), (2, 1)) / 100      # UTC D-8..D-1
    root = top * 2
    top[1, 0] = np.nan                                              # D-8 missing -> only the 7-day change is NaN
    block = compute.wetness_block(top, root)
    assert block["top"][0] == pytest.approx(0.17) and block["root"][0] == pytest.approx(0.34)
    assert block["top_chg3"][0] == pytest.approx(0.17 - 0.14) and block["top_chg7"][0] == pytest.approx(0.07)
    assert block["root_chg7"][0] == pytest.approx(0.14)
    assert block["top"][1] == pytest.approx(0.17) and np.isnan(block["top_chg7"][1]) and np.isfinite(block["top_chg3"][1])


# ------------------------------------------------------------------------------------------- climatology

def _clim(world, source, cells, train=TRAIN, aligned=None):
    store = sources.load_imd(world["imd"]) if source == "imd" else sources.load_chirps(world["chirps"])
    pix = np.unique(store.pixels(cells))
    table = compute.climatology(store, pix, day_number(train[0]), day_number(train[1]),
                                aligned=(source == "chirps") if aligned is None else aligned)
    return pix, table


def test_imd_climatology_is_the_mean_trailing_sum_over_train_days_of_the_month(world):
    cells = cells_with([(0, 0)])
    pix, table = _clim(world, "imd", cells)
    series = ImdGrid(world["imd"]).cell_series(int(cells[0]), "2010-01-01", "2010-12-31")
    for window, column in ((3, 0), (7, 1), (30, 2)):
        sums = pd.Series(trailing_sums(series.astype(float), (window,))[window], index=pd.date_range("2010-01-01", periods=365))
        for month in (1, 7, 12):
            expected = sums[sums.index.month == month].mean()
            assert table[0, month - 1, column] == pytest.approx(expected, rel=1e-5)


def test_chirps_climatology_uses_the_aligned_series(world):
    cells = cells_with([(2, 5)])
    pix, table = _clim(world, "chirps", cells)
    utc = ChirpsStore(world["chirps"]).cell_series(int(cells[0]), "2010-01-01", "2010-12-31").astype(float)
    aligned = align_utc_to_imd_day(pd.date_range("2010-01-01", periods=365), utc)
    sums = pd.Series(trailing_sums(aligned, (7,))[7], index=pd.date_range("2010-01-01", periods=365))
    assert table[0, 6, 1] == pytest.approx(sums[sums.index.month == 7].mean(), rel=1e-5)


def test_climatology_ignores_every_value_dated_after_the_train_range(tmp_path, world):
    def raise_late(year, array):
        if year > 2010:
            array += 100.0

    def raise_late_chirps(year, days, array):
        if year > 2010:
            array += np.float16(100.0)

    perturbed = {"imd": write_imd(tmp_path / "imd", perturb=raise_late),
                 "chirps": write_chirps(tmp_path / "chirps", perturb=raise_late_chirps)}
    cells = cells_with([(0, 0), (6, 7), (19, 19)])
    for source in ("imd", "chirps"):
        _, base = _clim(world, source, cells)
        _, changed = _clim(perturbed, source, cells)
        same(base, changed)
    _, wider = _clim(perturbed, "imd", cells, train=("2010-01-01", "2011-12-31"))
    assert not np.array_equal(np.nan_to_num(base), np.nan_to_num(wider[:, :, :]))


def test_climatology_is_nan_for_months_without_valid_train_days_and_pixels_without_a_pixel(world):
    pix, table = _clim(world, "imd", cells_with([(0, 0)]), train=("2010-03-01", "2010-03-20"))
    assert np.isfinite(table[0, 2, 0]) and np.isnan(table[0, 6, 0])
    assert np.isnan(table[0, 2, 2])        # the 30-day window needs days before the train range


def test_anomaly_is_the_accumulation_over_the_climatology_floored_at_one_mm():
    acc = np.array([30.0, 5.0, np.nan])
    clim = np.array([10.0, 0.2, 3.0])
    got = compute.anomaly(acc, clim)
    assert got[0] == 3.0 and got[1] == 5.0 and np.isnan(got[2])
    assert np.isnan(compute.anomaly(np.array([4.0]), np.array([np.nan]))[0])
