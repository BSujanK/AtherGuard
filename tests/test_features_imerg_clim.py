"""`iclim`: climatology-normalised IMERG rain (per-pixel empirical percentile of the 1/3/7-day IMD-day accumulation within
the pixel's own 2007-2015 distribution, and the accumulation over the pixel's mean annual precipitation).

Hand values on a ten-day climatology, a slow per-row oracle on random series, causality (nothing after day D enters a
feature; nothing outside 2007-2015 enters the climatology), NaN handling and the frozen files `hazard.data.load_table`
accepts.
"""
import json
import stat
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from aetherguard.config import PROJECT_ROOT
from aetherguard.features import imerg_build as B
from aetherguard.features import imerg_clim as C
from aetherguard.features import imerg_features as F
from aetherguard.grid import latlon_to_cell
from aetherguard.hazard import data as hd
from aetherguard.hazard import model as hm
from aetherguard.ingest import imerg
from aetherguard.ingest.imerg import imerg_pixel

from test_features_imerg import tiny_store  # noqa: F401  (fixture: a tiny development store, index and fake IMERG store)

WAYANAD = latlon_to_cell(11.47, 76.13)
KATHMANDU = latlon_to_cell(27.70, 85.32)
EDGE = latlon_to_cell(8.01, 72.01)
OUTSIDE = latlon_to_cell(60.0, 10.0)
CLIM_FIRST, CLIM_LAST = date(2007, 1, 1), date(2015, 12, 31)
EXTRAS = hm.hazard_config(PROJECT_ROOT / "configs" / "hazard_v3.yaml")["extra_groups"]


class ArrayStore:
    """`ImergStore.gather` over per-pixel UTC-day arrays that start on `first`; NaN outside them and for unknown pixels."""

    def __init__(self, first, series):
        self.first, self.series = first, series

    def gather(self, rows, cols, first_day, length):
        out = np.full((len(rows), length), np.nan, dtype=np.float32)
        offset = (first_day - self.first).days
        for i, (r, c) in enumerate(zip(rows, cols)):
            s = self.series.get((int(r), int(c)))
            if s is None:
                continue
            lo, hi = max(offset, 0), min(offset + length, len(s))
            if hi > lo:
                out[i, lo - offset:hi - offset] = s[lo:hi]
        return out


def random_store(cells, first=date(2006, 10, 1), last=date(2017, 12, 31), seed=1, nan_rate=0.02):
    n = (last - first).days + 1
    series = {}
    for cell in cells:
        r, c = imerg_pixel(cell)
        rng = np.random.default_rng([seed, r, c])
        values = np.where(rng.random(n) < 0.45, rng.gamma(1.2, 14.0, n), 0.0)
        values[rng.random(n) < nan_rate] = np.nan
        series[(r, c)] = values.astype(np.float32)
    return ArrayStore(first, series)


def pixel_of(cell):
    r, c = imerg_pixel(cell)
    return r * imerg.COLS + c


def frame_for(cells, dates):
    return pd.DataFrame([(cell, pd.Timestamp(d)) for d in dates for cell in cells], columns=["cell_id", "date"])


# ------------------------------------------------------------------------------------------- hand values

HAND_UTC = [0, 8, 16, 0, 0, 24, 8, 0, 0, 16]       # UTC days 2007-01-01..10 of the Wayanad pixel
# IMD day d = 0.875 * UTC(d-1) + 0.125 * UTC(d); the first day of the range is NaN:
HAND_IMD = [np.nan, 1, 9, 14, 0, 3, 22, 7, 0, 2]


def hand_store():
    r, c = imerg_pixel(WAYANAD)
    december = [0.0] * 31                           # 2006-12-01..31, all dry
    low_r, low_c = imerg_pixel(KATHMANDU)
    return ArrayStore(date(2006, 12, 1), {(r, c): np.array(december + HAND_UTC, dtype=np.float32),
                                           (low_r, low_c): np.full(41, 0.1, dtype=np.float32)})


def hand_table():
    return C.build_iclim_table(hand_store(), [pixel_of(WAYANAD), pixel_of(KATHMANDU)], date(2007, 1, 1),
                               date(2007, 1, 10))


def test_feature_names_and_constants():
    assert C.feature_names() == ["iclim_pct_1", "iclim_pct_3", "iclim_pct_7", "iclim_acc1_over_map",
                                 "iclim_acc3_over_map", "iclim_acc7_over_map"]
    assert C.PCT_WINDOWS == (1, 3, 7)


def test_climatology_table_hand_values():
    table = hand_table()
    row = int(np.searchsorted(table.pix, pixel_of(WAYANAD)))
    assert table.n_valid[row].tolist() == [9, 7, 3]
    np.testing.assert_array_equal(table.sorted_acc[row, 0, :9], [0, 0, 1, 2, 3, 7, 9, 14, 22])
    np.testing.assert_array_equal(table.sorted_acc[row, 1, :7], [9, 17, 23, 24, 25, 29, 32])
    np.testing.assert_array_equal(table.sorted_acc[row, 2, :3], [48, 55, 56])
    assert np.isnan(table.sorted_acc[row, 0, 9:]).all() and np.isnan(table.sorted_acc[row, 2, 3:]).all()
    assert table.map_mm[row] == pytest.approx(58 / 9 * 365.25)
    assert table.pix.tolist() == sorted(table.pix.tolist())


def test_features_hand_values_mid_rank_and_map_ratio():
    table = hand_table()
    out = C.build_iclim_features(frame_for([WAYANAD], ["2007-01-09"]), hand_store(), table)
    # 2007-01-09 is IMD day index 8: 1-day 0, 3-day 22+7+0 = 29, 7-day 9+14+0+3+22+7+0 = 55
    assert out.loc[0, "iclim_pct_1"] == pytest.approx((0 + 0.5 * 2) / 9)          # two dry days tie -> mid-rank
    assert out.loc[0, "iclim_pct_3"] == pytest.approx((5 + 0.5 * 1) / 7)
    assert out.loc[0, "iclim_pct_7"] == pytest.approx((1 + 0.5 * 1) / 3)
    map_mm = 58 / 9 * 365.25
    assert out.loc[0, "iclim_acc3_over_map"] == pytest.approx(29 / map_mm, rel=1e-6)
    assert out.loc[0, "iclim_acc7_over_map"] == pytest.approx(55 / map_mm, rel=1e-6)
    assert out.loc[0, "iclim_acc1_over_map"] == 0.0
    assert list(out.columns) == C.feature_names() and (out.dtypes == np.float32).all()


def test_values_beyond_the_climatology_range_rank_at_the_ends():
    table = hand_table()
    row = int(np.searchsorted(table.pix, pixel_of(WAYANAD)))
    x = np.array([-1.0, 0.0, 22.0, 22.5, 500.0], dtype=np.float32)
    share = C.mid_rank_share(table.sorted_acc[row, 0], table.n_valid[row, 0], x)
    np.testing.assert_allclose(share, [0.0, 1 / 9, (8 + 0.5) / 9, 1.0, 1.0])


def test_percentile_is_non_decreasing_in_the_accumulation():
    rng = np.random.default_rng(0)
    values = np.sort(np.where(rng.random(400) < 0.4, 0.0, rng.gamma(1.0, 10.0, 400))).astype(np.float32)
    grid = np.linspace(-1, values.max() + 5, 500).astype(np.float32)
    share = C.mid_rank_share(values, len(values), grid)
    assert (np.diff(share) >= 0).all() and share[0] == 0.0 and share[-1] == 1.0


def test_map_floor_applies_to_very_dry_pixels():
    table = hand_table()
    out = C.build_iclim_features(frame_for([KATHMANDU], ["2007-01-09"]), hand_store(), table)
    # constant 0.1 mm/day -> MAP 36.5 mm, below the floor: the ratio uses the floor
    assert C.MAP_FLOOR_MM == 50.0
    assert out.loc[0, "iclim_acc3_over_map"] == pytest.approx(0.3 / 50.0, rel=1e-5)
    assert out.loc[0, "iclim_pct_3"] == pytest.approx(0.5)                          # constant series: every value ties


# --------------------------------------------------------------------------------- against a slow oracle

CELLS = [WAYANAD, KATHMANDU, EDGE, WAYANAD + 3]


def oracle_imd(store, r, c, d):
    if not (0 <= r < imerg.ROWS and 0 <= c < imerg.COLS):
        return np.nan
    s = store.series.get((r, c))

    def utc(day):
        k = (day - store.first).days
        return float(s[k]) if s is not None and 0 <= k < len(s) else np.nan
    return 0.875 * utc(d - timedelta(1)) + 0.125 * utc(d)


def oracle_acc(store, r, c, d, k):
    return sum(oracle_imd(store, r, c, d - timedelta(j)) for j in range(k))


def oracle_clim(store, r, c):
    days = [CLIM_FIRST + timedelta(j) for j in range((CLIM_LAST - CLIM_FIRST).days + 1)]
    imd = [np.nan] + [oracle_imd(store, r, c, d) for d in days[1:]]
    out = {}
    for k in C.PCT_WINDOWS:
        sums = [sum(imd[i - k + 1:i + 1]) for i in range(k - 1, len(days))]
        out[k] = np.array([s for s in sums if not np.isnan(s)], dtype=np.float32)
    daily = np.array([v for v in imd if not np.isnan(v)])
    return out, daily.mean() * 365.25


@pytest.mark.parametrize("nan_rate", [0.02, 0.0])
def test_features_match_the_oracle(nan_rate):
    store = random_store(CELLS, nan_rate=nan_rate)
    table = C.build_iclim_table(store, [pixel_of(c) for c in CELLS], CLIM_FIRST, CLIM_LAST)
    frame = frame_for(CELLS, [date(2007, 1, 3), date(2009, 7, 30), date(2012, 8, 15), date(2016, 6, 30), date(2017, 12, 31)])
    got = C.build_iclim_features(frame, store, table)
    assert got.index.equals(frame.index)
    seen_nan = False
    for i, (cell, ts) in enumerate(zip(frame["cell_id"], frame["date"])):
        r, c = imerg_pixel(cell)
        clim, map_mm = oracle_clim(store, r, c)
        for k in C.PCT_WINDOWS:
            acc = oracle_acc(store, r, c, ts.date(), k)
            if np.isnan(acc):
                seen_nan = True
                want_pct = want_ratio = np.nan
            else:
                ref = clim[k]
                x = np.float32(acc)
                want_pct = ((ref < x).sum() + 0.5 * (ref == x).sum()) / len(ref)
                want_ratio = acc / max(map_mm, 50.0)
            np.testing.assert_allclose(got.loc[i, f"iclim_pct_{k}"], want_pct, atol=1e-6, equal_nan=True,
                                       err_msg=f"pct {k} {cell} {ts.date()}")
            np.testing.assert_allclose(got.loc[i, f"iclim_acc{k}_over_map"], want_ratio, rtol=2e-5, atol=1e-6,
                                       equal_nan=True, err_msg=f"ratio {k} {cell} {ts.date()}")
    assert seen_nan == bool(nan_rate)


def test_nan_window_gives_nan_only_for_windows_that_cover_the_gap():
    r, c = imerg_pixel(WAYANAD)
    series = np.full(4200, 5.0, dtype=np.float32)
    first = date(2006, 10, 1)
    gap = (date(2012, 6, 10) - first).days
    series[gap] = np.nan                                   # UTC 2012-06-10 -> IMD days 06-10 and 06-11 are NaN
    store = ArrayStore(first, {(r, c): series})
    table = C.build_iclim_table(store, [pixel_of(WAYANAD)], CLIM_FIRST, CLIM_LAST)
    frame = frame_for([WAYANAD], ["2012-06-11", "2012-06-12", "2012-06-13", "2012-06-17", "2012-06-18"])
    got = C.build_iclim_features(frame, store, table)
    nan = got.isna()
    assert nan["iclim_pct_1"].tolist() == [True, False, False, False, False]
    assert nan["iclim_pct_3"].tolist() == [True, True, True, False, False]
    assert nan["iclim_pct_7"].tolist() == [True, True, True, True, False]
    assert nan["iclim_acc7_over_map"].tolist() == nan["iclim_pct_7"].tolist()


def test_cells_outside_the_grid_or_without_climatology_are_all_nan():
    store = random_store([WAYANAD], nan_rate=0.0)
    table = C.build_iclim_table(store, [pixel_of(WAYANAD), -1], CLIM_FIRST, CLIM_LAST)
    assert table.pix.tolist() == [pixel_of(WAYANAD)]
    frame = frame_for([OUTSIDE, KATHMANDU, WAYANAD], ["2012-08-15"])
    got = C.build_iclim_features(frame, store, table)
    assert got.loc[0].isna().all() and got.loc[1].isna().all() and got.loc[2].notna().all()


def test_chunking_does_not_change_values_and_row_order_is_kept():
    store = random_store(CELLS)
    table = C.build_iclim_table(store, [pixel_of(c) for c in CELLS], CLIM_FIRST, CLIM_LAST)
    dates = [date(2008, 3, 1) + timedelta(days=37 * k) for k in range(25)]
    frame = frame_for(CELLS, dates).sample(frac=1.0, random_state=3).reset_index(drop=True)
    whole = C.build_iclim_features(frame, store, table)
    split = C.build_iclim_features(frame, store, table, chunk_days=20, pixel_block=2)
    pd.testing.assert_frame_equal(whole, split)
    single = C.build_iclim_features(frame.iloc[[7]], store, table)
    pd.testing.assert_frame_equal(single, whole.iloc[[7]])


# ------------------------------------------------------------------------------------------------ causality

def test_nothing_after_day_d_enters_a_feature_at_d():
    store = random_store(CELLS)
    table = C.build_iclim_table(store, [pixel_of(c) for c in CELLS], CLIM_FIRST, CLIM_LAST)
    day = date(2012, 8, 15)
    frame = frame_for(CELLS, [day])
    base = C.build_iclim_features(frame, store, table)
    k = (day - store.first).days
    perturbed = {key: np.where(np.arange(len(v)) > k, v * 4 + 9, v).astype(np.float32) for key, v in store.series.items()}
    again = C.build_iclim_features(frame, ArrayStore(store.first, perturbed), table)
    pd.testing.assert_frame_equal(base, again)
    # UTC day D itself carries weight 1/8 of IMD day D, so it is allowed to move the feature
    touched = {key: np.where(np.arange(len(v)) == k, v + 50, v).astype(np.float32) for key, v in store.series.items()}
    assert not C.build_iclim_features(frame, ArrayStore(store.first, touched), table).equals(base)


def test_the_climatology_uses_only_2007_to_2015():
    store = random_store(CELLS)
    pixels = [pixel_of(c) for c in CELLS]
    base = C.build_iclim_table(store, pixels, CLIM_FIRST, CLIM_LAST)
    start, end = (CLIM_FIRST - store.first).days, (CLIM_LAST - store.first).days
    outside = {key: np.where((np.arange(len(v)) < start) | (np.arange(len(v)) > end), v * 5 + 11, v).astype(np.float32)
               for key, v in store.series.items()}
    again = C.build_iclim_table(ArrayStore(store.first, outside), pixels, CLIM_FIRST, CLIM_LAST)
    np.testing.assert_array_equal(base.sorted_acc, again.sorted_acc)
    np.testing.assert_array_equal(base.n_valid, again.n_valid)
    np.testing.assert_array_equal(base.map_mm, again.map_mm)
    inside = {key: np.where(np.arange(len(v)) == start + 400, v + 40, v).astype(np.float32)
              for key, v in store.series.items()}
    changed = C.build_iclim_table(ArrayStore(store.first, inside), pixels, CLIM_FIRST, CLIM_LAST)
    assert not np.array_equal(base.sorted_acc, changed.sorted_acc, equal_nan=True)


# ---------------------------------------------------------------------------------------- build and freeze

def test_written_files_load_through_hazard_data(tiny_store):  # noqa: F811
    inputs, out, store = tiny_store
    manifests, reused = C.build_iclim_tables(inputs, out, store)
    assert not reused and manifests["group"] == "iclim"
    column_map = hd.load_column_map(inputs.features_dir, EXTRAS, ("iclim",))
    assert {c: g for c, g in column_map.items() if c.startswith("iclim_")} == {c: "iclim" for c in C.feature_names()}
    table = hd.load_table("train_samples", inputs.features_dir, EXTRAS, ("iclim",))
    base = pd.read_parquet(inputs.features_dir / "train_samples_features.parquet")
    assert len(table) == len(base) and (table["cell_id"].to_numpy() == base["cell_id"].to_numpy()).all()
    assert table[C.feature_names()].notna().to_numpy().any() and (table[C.feature_names()].dtypes == np.float32).all()
    development = hd.load_development(inputs.features_dir, EXTRAS, ("iclim",))
    assert set(C.feature_names()) <= set(development.samples.columns) and set(C.feature_names()) <= set(development.universe.columns)
    report = json.loads((out / C.REPORT_NAME).read_text())
    assert set(report["files"]) == {"train_samples_features.parquet", "validation_samples_features.parquet",
                                    "universe_train_features.parquet", "universe_validation_features.parquet"}
    assert set(report["files"]["train_samples_features.parquet"]["nan_share"]) == set(C.feature_names())
    assert report["climatology"]["pixels"] == len(np.unique(F.cell_pixels(np.array(
        [WAYANAD, WAYANAD + 1, WAYANAD + 20_000, EDGE]))))
    assert not (out / "irain_columns.json").exists()                        # the other IMERG groups are not touched


def test_freeze_reuse_verify_and_force(tiny_store):  # noqa: F811
    inputs, out, store = tiny_store
    C.build_iclim_tables(inputs, out, store)
    path = out / "train_samples_iclim.parquet"
    assert not path.stat().st_mode & stat.S_IWRITE
    before = path.stat().st_mtime_ns
    manifest, reused = C.build_iclim_tables(inputs, out, store)
    assert reused and path.stat().st_mtime_ns == before
    assert C.verify_iclim_tables(out, inputs, C.build_config())["ok"]
    path.chmod(stat.S_IWRITE | stat.S_IREAD)
    pd.read_parquet(path).assign(iclim_pct_1=np.float32(0.5)).to_parquet(path, index=False)
    result = C.verify_iclim_tables(out, inputs)
    assert not result["ok"] and any("checksum mismatch" in p for p in result["problems"])
    with pytest.raises(C.IclimIntegrityError):
        C.build_iclim_tables(inputs, out, store)
    _, reused = C.build_iclim_tables(inputs, out, store, force=True)
    assert not reused and C.verify_iclim_tables(out, inputs)["ok"]


def test_verify_detects_changed_configuration_and_inputs(tiny_store):  # noqa: F811
    inputs, out, store = tiny_store
    C.build_iclim_tables(inputs, out, store)
    assert not C.verify_iclim_tables(out, inputs, {**C.build_config(), "map_floor_mm": 10.0})["ok"]
    manifest_path = inputs.features_dir / "features_manifest.json"
    manifest_path.write_text(manifest_path.read_text() + " ", encoding="utf-8")
    result = C.verify_iclim_tables(out, inputs)
    assert not result["ok"] and any("features_manifest" in p for p in result["problems"])
    with pytest.raises(FileNotFoundError):
        C.verify_iclim_tables(out.parent / "nowhere")


def test_build_config_records_the_train_range_and_the_definition():
    cfg = C.build_config()
    assert cfg["climatology"] == {"first_day": "2007-01-01", "last_day": "2015-12-31"}
    assert cfg["windows"] == [1, 3, 7] and cfg["map_floor_mm"] == 50.0 and cfg["days_per_year"] == 365.25
