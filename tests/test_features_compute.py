"""compute_features end to end on synthetic stores: values vs the public readers, causality, row identity."""
import numpy as np
import pandas as pd
import pytest
from features_helpers import (
    UNCOVERED_IMD_POINT,
    block_cell,
    day_number,
    imd_point_of_block,
    terrain_table,
    write_chirps,
    write_imd,
    write_power,
    write_world,
)

from aetherguard.features import compute
from aetherguard.features.compute import FeatureContext, compute_features, feature_names
from aetherguard.ingest.align import align_utc_to_imd_day
from aetherguard.ingest.chirps import ChirpsStore
from aetherguard.ingest.imd import ImdGrid
from aetherguard.ingest.power import PowerWetness

TRAIN_FIRST, TRAIN_LAST = day_number("2010-01-01"), day_number("2010-12-31")
ALL_FEATURES = [c for group in feature_names().values() for c in group]
UNCOVERED = [(i, j) for i in range(20) for j in range(20) if imd_point_of_block(i, j) == UNCOVERED_IMD_POINT][0]


def context(paths, cells):
    return FeatureContext.build(cells, paths["imd"], paths["chirps"], paths["power"], terrain_table(),
                                TRAIN_FIRST, TRAIN_LAST)


def frame(rows):
    out = pd.DataFrame(rows, columns=["cell_id", "date"])
    out["date"] = pd.to_datetime(out["date"]).astype("datetime64[ns]")
    return out


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    return write_world(tmp_path_factory.mktemp("world"))


@pytest.fixture(scope="module")
def sample_cells():
    return [block_cell(0, 0), block_cell(5, 9), block_cell(*UNCOVERED), block_cell(19, 19)]


def same(a, b):
    np.testing.assert_allclose(np.asarray(a, dtype=float), np.asarray(b, dtype=float), rtol=1e-5, atol=1e-5,
                               equal_nan=True)


def test_features_equal_the_public_readers_for_an_imd_row_across_a_year_boundary(world, sample_cells):
    ctx = context(world, sample_cells)
    cell = block_cell(5, 9)
    got = compute_features(frame([(cell, "2011-01-12")]), ctx).iloc[0]
    imd = ImdGrid(world["imd"]).cell_series(cell, "2010-12-14", "2011-01-12").astype(float)
    assert got["rain_source"] == "imd"
    assert got["rain_acc_1"] == pytest.approx(imd[-1]) and got["rain_acc_7"] == pytest.approx(imd[-7:].sum(), rel=1e-5)
    assert got["rain_acc_30"] == pytest.approx(imd.sum(), rel=1e-5) and got["rain_max1d_30"] == pytest.approx(imd.max())
    utc = ChirpsStore(world["chirps"]).cell_series(cell, "2010-12-13", "2011-01-12").astype(float)
    aligned = align_utc_to_imd_day(pd.date_range("2010-12-13", periods=31), utc)[1:]
    assert got["src_chi_acc_3"] == pytest.approx(aligned[-3:].sum(), rel=1e-5)
    assert got["src_imd_acc_3"] == pytest.approx(imd[-3:].sum(), rel=1e-5)
    assert got["src_dis_diff_7"] == pytest.approx(imd[-7:].sum() - aligned[-7:].sum(), rel=1e-4, abs=1e-4)
    assert got["src_dis_ratio_1"] == pytest.approx((imd[-1] + 1) / (aligned[-1] + 1), rel=1e-5)
    assert got["src_dis_both"] == 1.0
    assert got["month"] == 1 and got["lat"] == pytest.approx(11.525 + 0.05 * 5)


def test_a_cell_outside_imd_coverage_takes_chirps_aligned_as_primary_and_has_no_imd_source_features(world, sample_cells):
    ctx = context(world, sample_cells)
    cell = block_cell(*UNCOVERED)
    got = compute_features(frame([(cell, "2011-06-20")]), ctx).iloc[0]
    utc = ChirpsStore(world["chirps"]).cell_series(cell, "2011-05-21", "2011-06-20").astype(float)
    aligned = align_utc_to_imd_day(pd.date_range("2011-05-21", periods=31), utc)[1:]
    assert got["rain_source"] == "chirps_aligned"
    assert got["rain_acc_3"] == pytest.approx(aligned[-3:].sum(), rel=1e-5)
    assert got["rain_acc_30"] == pytest.approx(aligned.sum(), rel=1e-5)
    assert np.isnan(got["src_imd_acc_1"]) and np.isnan(got["src_dis_diff_1"]) and got["src_dis_both"] == 0.0
    assert got["src_chi_acc_1"] == pytest.approx(aligned[-1], rel=1e-5)


def test_missing_data_gives_nan_not_zero_and_the_source_is_none_when_both_are_missing(world, sample_cells):
    ctx = context(world, sample_cells)
    cell = block_cell(0, 0)
    rows = frame([(cell, "2011-03-12"),    # CHIRPS UTC 03-10 is missing: it sits in the aligned 3-day window
                  (cell, "2012-07-01"),    # no store year at all (CHIRPS gap year; IMD has no 2012 either)
                  (block_cell(*UNCOVERED), "2012-07-01")])
    got = compute_features(rows, ctx)
    first = got.iloc[0]
    assert first["rain_source"] == "imd" and np.isfinite(first["rain_acc_30"])
    assert np.isfinite(first["src_chi_acc_1"]) and np.isfinite(first["src_dis_diff_1"])
    assert np.isnan(first["src_chi_acc_3"]) and np.isnan(first["src_chi_acc_7"]) and np.isnan(first["src_dis_diff_3"])
    assert (got.iloc[1:]["rain_source"] == "none").all()
    nan_columns = [c for c in ALL_FEATURES if c.startswith(("rain_", "src_")) and c != "src_dis_both"]
    assert got.iloc[1:][nan_columns].isna().all().all() and (got.iloc[1:]["src_dis_both"] == 0.0).all()


def test_chirps_window_that_starts_before_a_store_range_is_nan_but_shorter_windows_are_not(world):
    cell = block_cell(*UNCOVERED)
    ctx = context(world, [cell])
    got = compute_features(frame([(cell, "2013-06-10"), (cell, "2013-07-10")]), ctx)
    # aligned day 2013-06-01 would need UTC 05-31, which the 2013 store (from 06-01) does not have
    assert np.isfinite(got.iloc[0]["rain_acc_7"]) and np.isnan(got.iloc[0]["rain_acc_14"])
    assert np.isnan(got.iloc[0]["rain_acc_30"]) and got.iloc[0]["rain_source"] == "chirps_aligned"
    assert np.isfinite(got.iloc[1]["rain_acc_30"])
    assert ctx.chirps.counters["days_outside_store"] > 0


def test_wetness_comes_from_utc_day_before_and_changes_are_lagged(world, sample_cells):
    ctx = context(world, sample_cells)
    cell = block_cell(0, 0)
    got = compute_features(frame([(cell, "2011-02-10")]), ctx).iloc[0]
    public = PowerWetness(world["power"])
    top = public.cell_series(cell, "2011-02-02", "2011-02-09", "GWETTOP")
    root = public.cell_series(cell, "2011-02-02", "2011-02-09", "GWETROOT")
    assert got["wet_top"] == pytest.approx(top[-1]) and got["wet_root"] == pytest.approx(root[-1])
    assert got["wet_top_chg3"] == pytest.approx(top[-1] - top[-4], abs=1e-6)
    assert got["wet_root_chg7"] == pytest.approx(root[-1] - root[0], abs=1e-6)


def test_static_terrain_is_joined_at_the_terrain_cell_including_nearest_land(world, sample_cells):
    ctx = context(world, sample_cells)
    own, other = block_cell(0, 0), block_cell(3, 4)
    rows = frame([(own, "2011-02-10"), (own, "2011-02-11"), (own, "2011-02-12")])
    rows["terrain_cell_id"] = pd.array([own, other, pd.NA], dtype="Int64")
    got = compute_features(rows, ctx)
    terrain = terrain_table().set_index("cell_id")
    assert got.loc[0, "stat_slope_mean"] == pytest.approx(terrain.loc[own, "slope_mean"])
    assert got.loc[1, "stat_slope_mean"] == pytest.approx(terrain.loc[other, "slope_mean"])
    assert got.loc[1, "stat_elev_mean"] == pytest.approx(terrain.loc[other, "elev_mean"])
    assert np.isnan(got.loc[2, [c for c in ALL_FEATURES if c.startswith("stat_")]].astype(float)).all()
    plain = compute_features(frame([(other, "2011-02-10")]), ctx)    # no terrain_cell_id column: own cell
    assert plain.loc[0, "stat_twi_proxy"] == pytest.approx(terrain.loc[other, "twi_proxy"])


def test_rows_keep_order_and_columns_and_features_are_float32(world, sample_cells):
    ctx = context(world, sample_cells)
    rows = frame([(sample_cells[3], "2011-08-01"), (sample_cells[0], "2010-02-20"), (sample_cells[1], "2011-01-05")])
    rows["label"] = [1, 0, 0]
    rows["weight"] = [1.5, 2.5, 3.5]
    got = compute_features(rows, ctx, chunk_rows=2)         # several chunks
    assert list(got["cell_id"]) == list(rows["cell_id"]) and list(got["date"]) == list(rows["date"])
    assert list(got["label"]) == [1, 0, 0] and list(got["weight"]) == [1.5, 2.5, 3.5]
    assert all(got[c].dtype == np.float32 for c in ALL_FEATURES)
    assert list(got.columns[:4]) == ["cell_id", "date", "label", "weight"]
    single = compute_features(rows, ctx, chunk_rows=10_000)
    pd.testing.assert_frame_equal(got, single)


def test_anomaly_features_use_the_source_pixel_climatology(world, sample_cells):
    ctx = context(world, sample_cells)
    cell = block_cell(0, 0)
    got = compute_features(frame([(cell, "2011-07-15")]), ctx).iloc[0]
    pix = ctx.imd.pixels(np.array([cell]))
    clim = ctx.clim_imd.lookup(pix, np.array([7]))[0]
    assert got["rain_acc3_vs_clim"] == pytest.approx(got["rain_acc_3"] / max(clim[0], 1.0), rel=1e-5)
    assert got["rain_acc30_vs_clim"] == pytest.approx(got["rain_acc_30"] / max(clim[2], 1.0), rel=1e-5)


@pytest.mark.parametrize("when", ["2011-06-15", "2011-01-20"])
def test_features_at_day_d_do_not_depend_on_anything_dated_after_d(tmp_path, world, sample_cells, when):
    d = day_number(when)

    def imd_after(year, array):
        first = day_number(f"{year}-01-01")
        for k in range(array.shape[0]):
            if first + k > d:
                array[k] = array[k] * 3 + 40

    def chirps_after(year, days, array):
        for k, stamp in enumerate(days):
            if day_number(stamp) > d:
                array[k] = array[k] + np.float16(60)

    def power_from_d(days, top, root):
        late = days.astype(np.int64) >= d          # UTC day D itself and later are not allowed in
        top[late] = 0.01
        root[late] = np.where(np.isnan(root[late]), np.nan, 0.99)

    changed = {"imd": write_imd(tmp_path / "imd", perturb=imd_after),
               "chirps": write_chirps(tmp_path / "chirps", perturb=chirps_after),
               "power": write_power(tmp_path / "power.npz", perturb=power_from_d), "terrain": world["terrain"]}
    rows = frame([(c, when) for c in sample_cells])
    base = compute_features(rows, context(world, sample_cells))
    after = compute_features(rows, context(changed, sample_cells))
    pd.testing.assert_frame_equal(base, after)


def test_the_causality_test_is_sensitive_to_data_at_d_itself(tmp_path, world, sample_cells):
    d = day_number("2011-06-15")

    def imd_from_d(year, array):
        first = day_number(f"{year}-01-01")
        for k in range(array.shape[0]):
            if first + k >= d:
                array[k] = array[k] + 25

    changed = dict(world, imd=write_imd(tmp_path / "imd", perturb=imd_from_d))
    rows = frame([(block_cell(0, 0), "2011-06-15")])
    before = compute_features(rows, context(world, sample_cells)).iloc[0]
    after = compute_features(rows, context(changed, sample_cells)).iloc[0]
    assert after["rain_acc_1"] == pytest.approx(before["rain_acc_1"] + 25)


def test_every_feature_name_is_unique_and_grouped_by_prefix():
    groups = feature_names()
    flat = [c for names in groups.values() for c in names]
    assert len(flat) == len(set(flat))
    assert all(c.startswith(f"{g}_") for g, names in groups.items() for c in names)
    assert compute.LOOKBACK == 30
