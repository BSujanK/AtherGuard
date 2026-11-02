"""v3-live IMERG feature tables: D5 conversion, accumulations and the NaN rule, API recursion, 3x3 neighbourhood,
the train-range-only climatology, causality, key/order identity and the files `hazard.data.load_table` accepts.

The numerics are checked against a slow per-row oracle written independently of the vectorised code, on a fake store
with the `ImergStore.gather` interface (NaN days included); one test uses a real `ImergStore` written on disk.
"""
import json
import stat
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from aetherguard.config import PROJECT_ROOT
from aetherguard.features import imerg_build as B
from aetherguard.features import imerg_features as F
from aetherguard.features.compute import ClimTable
from aetherguard.grid import latlon_to_cell
from aetherguard.hazard import data as hd
from aetherguard.hazard import model as hm
from aetherguard.ingest import imerg
from aetherguard.ingest.imerg import ImergStore, imerg_pixel
from aetherguard.manifest import Manifest, sha256_file

from hazard_helpers import synthetic_development, write_store

START, END = date(2006, 10, 1), date(2016, 6, 30)
WAYANAD = latlon_to_cell(11.47, 76.13)
EDGE = latlon_to_cell(8.01, 72.01)         # pixel (0, 0): south-west corner of the domain grid
NORTH_EAST = latlon_to_cell(35.99, 97.99)  # pixel (279, 259)
CELLS = [WAYANAD, WAYANAD + 1, WAYANAD + 2 * 10_000, EDGE, NORTH_EAST]
CLIM_FIRST, CLIM_LAST = date(2007, 1, 1), date(2015, 12, 31)


class FakeStore:
    """`ImergStore.gather` over deterministic per-pixel rain (zero-inflated, `nan_rate` NaN days) on START..END.
    Days after `bump_after` are replaced (finite x3 + 17, NaN -> 5) and days before `bump_before` too."""

    def __init__(self, first=START, last=END, bump_after=None, bump_before=None, seed=3, nan_rate=0.03):
        self.first, self.n, self.seed, self.nan_rate = first, (last - first).days + 1, seed, nan_rate
        self.bump_after, self.bump_before = bump_after, bump_before
        self.cache = {}

    def series(self, row, col):
        if (row, col) not in self.cache:
            rng = np.random.default_rng([self.seed, row, col])
            values = np.where(rng.random(self.n) < 0.45, rng.gamma(1.2, 14.0, self.n), 0.0)
            values[rng.random(self.n) < self.nan_rate] = np.nan
            days = np.array([self.first + timedelta(k) for k in range(self.n)])
            for mask in ((days > self.bump_after) if self.bump_after else None,
                         (days < self.bump_before) if self.bump_before else None):
                if mask is not None:
                    values[mask] = np.where(np.isnan(values[mask]), 5.0, values[mask] * 3 + 17)
            self.cache[(row, col)] = values.astype(np.float32)
        return self.cache[(row, col)]

    def value(self, row, col, day):
        k = (day - self.first).days
        return float(self.series(row, col)[k]) if 0 <= k < self.n else np.nan

    def gather(self, rows, cols, first_day, length):
        out = np.full((len(rows), length), np.nan, dtype=np.float32)
        for i, (r, c) in enumerate(zip(rows, cols)):
            for j in range(length):
                out[i, j] = self.value(int(r), int(c), first_day + timedelta(j))
        return out


# ---------------------------------------------------------------------------------------------- oracle

def oracle_imd(store, r, c, d):
    if not (0 <= r < imerg.ROWS and 0 <= c < imerg.COLS):
        return np.nan
    return 0.875 * store.value(r, c, d - timedelta(1)) + 0.125 * store.value(r, c, d)


def oracle_row(store, clim_values, cell, d):
    r, c = imerg_pixel(cell)
    imd = [oracle_imd(store, r, c, d - timedelta(k)) for k in range(89, -1, -1)]   # oldest .. D
    out = {}
    for n in F.ACC_WINDOWS:
        out[f"irain_acc_{n}"] = float(np.sum(imd[-n:]))
    out["irain_max1d_7"], out["irain_max1d_30"] = float(np.max(imd[-7:])), float(np.max(imd[-30:]))
    out["irain_wetdays_30"] = np.nan if np.isnan(out["irain_acc_30"]) else float(sum(v >= 1 for v in imd[-30:]))
    since = next((k for k, v in enumerate(reversed(imd)) if v >= 10), 90)
    out["irain_days_since_10mm"] = np.nan if np.isnan(out["irain_acc_90"]) else float(since)
    acc3 = out["irain_acc_3"]
    out["irain_share1_3"] = out["irain_acc_1"] / acc3 if acc3 >= 1 else np.nan
    for w, n in enumerate((3, 7, 30)):
        out[f"irain_acc{n}_vs_clim"] = out[f"irain_acc_{n}"] / max(clim_values[w], 1.0)
    for k in (0.85, 0.90, 0.95):
        acc = 0.0
        for back in range(120, -1, -1):
            p = oracle_imd(store, r, c, d - timedelta(back))
            acc = k * acc + (0.0 if np.isnan(p) else p)
        out[f"iapi_{round(k * 100)}"] = np.nan if np.isnan(imd[-1]) else acc
    for n in (1, 3):
        accs = []
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                accs.append(sum(oracle_imd(store, r + dr, c + dc, d - timedelta(k)) for k in range(n)))
        good = [a for a in accs if not np.isnan(a)]
        out[f"inbr_max_acc_{n}"] = max(good) if good else np.nan
        out[f"inbr_mean_acc_{n}"] = sum(good) / len(good) if good else np.nan
    return out


def oracle_clim(store, r, c):
    """Mean over end days in CLIM_FIRST..CLIM_LAST per calendar month of the N-day IMD accumulation; the IMD series
    is built from the UTC days inside the range only (its first day is NaN)."""
    days = [CLIM_FIRST + timedelta(k) for k in range((CLIM_LAST - CLIM_FIRST).days + 1)]
    imd = [np.nan] + [oracle_imd(store, r, c, d) for d in days[1:]]
    out = np.full((12, 3), np.nan)
    for w, n in enumerate((3, 7, 30)):
        sums = {m: [] for m in range(12)}
        for i in range(n - 1, len(days)):
            s = sum(imd[i - n + 1:i + 1])
            if not np.isnan(s):
                sums[days[i].month - 1].append(s)
        for m, vals in sums.items():
            if vals:
                out[m, w] = np.mean(vals)
    return out


def make_clim(store, cells=CELLS):
    return F.imerg_climatology(store, F.cell_pixels(np.array(cells)), CLIM_FIRST, CLIM_LAST)


def frame_for(dates, cells=CELLS):
    rows = [(cell, pd.Timestamp(d)) for d in dates for cell in cells]
    return pd.DataFrame(rows, columns=["cell_id", "date"])


# ------------------------------------------------------------------------------------------- pure numerics

def test_imd_day_conversion_hand_values():
    utc = np.array([[0.0, 8.0, 16.0, np.nan, 24.0, 48.0]])
    imd = F.imd_day_series(utc)
    assert imd.shape == (1, 5)
    np.testing.assert_allclose(imd[0, :2], [0.875 * 0 + 0.125 * 8, 0.875 * 8 + 0.125 * 16])   # 1.0, 9.0
    assert np.isnan(imd[0, 2]) and np.isnan(imd[0, 3])                                         # either UTC day NaN
    assert imd[0, 4] == pytest.approx(0.875 * 24 + 0.125 * 48)
    assert F.imd_day_series(np.full((1, 4), 10.0)).tolist() == [[10.0] * 3]                    # constant rate is exact


def test_accumulation_block_values_and_nan_rule():
    daily = np.zeros((3, 90))
    daily[0, -1], daily[0, -2], daily[0, -40] = 12.0, 0.5, 30.0
    daily[1, :] = 1.0
    daily[2, -45] = np.nan                  # inside the 60- and 90-day windows only
    daily[2, -1] = 4.0
    b = F.accumulation_block(daily)
    assert b["acc_1"][0] == 12.0 and b["acc_3"][0] == 12.5 and b["acc_30"][0] == 12.5
    assert b["acc_60"][0] == 42.5 and b["acc_90"][0] == 42.5
    assert b["max1d_7"][0] == 12.0 and b["max1d_30"][0] == 12.0
    assert b["wetdays_30"][0] == 1 and b["days_since_10mm"][0] == 0
    assert b["share1_3"][0] == pytest.approx(12.0 / 12.5)
    assert b["acc_90"][1] == 90 and b["wetdays_30"][1] == 30 and b["days_since_10mm"][1] == 90   # none: capped
    assert b["share1_3"][1] == pytest.approx(1 / 3)
    assert b["acc_30"][2] == 4.0 and np.isnan(b["acc_60"][2]) and np.isnan(b["acc_90"][2])
    assert np.isnan(b["days_since_10mm"][2])                              # 90-day window incomplete
    assert b["wetdays_30"][2] == 1.0                                      # the 30-day window is complete
    assert np.isnan(F.accumulation_block(np.where(np.arange(90) == 89, np.nan, 1.0)[None])["max1d_7"][0])


def test_days_since_10mm_counts_back_and_share_needs_one_mm():
    daily = np.zeros((2, 90))
    daily[0, -6] = 10.0                                  # exactly 10 mm counts, 5 days before D
    daily[1, -1] = 0.9
    b = F.accumulation_block(daily)
    assert b["days_since_10mm"].tolist() == [5.0, 90.0]
    assert np.isnan(b["share1_3"][0]) and np.isnan(b["share1_3"][1])   # acc_3 < 1 mm


def test_api_recursion_hand_example_with_nan_day():
    series = np.array([[10.0, 0.0, np.nan, 5.0, 2.0]])
    out = F.api(series, 0.5)
    # 10, 5, (NaN day: value NaN, state 2.5), 2.5*0.5 + 5 = 6.25, 3.125 + 2 = 5.125  (state after the NaN day)
    np.testing.assert_allclose(out, [[10.0, 5.0, np.nan, 6.25, 5.125]], equal_nan=True)
    assert F.api_state(series, 0.5)[0, 2] == 2.5


def test_api_at_equals_recursion_started_spinup_days_earlier():
    rng = np.random.default_rng(0)
    series = rng.gamma(1.0, 10.0, (2, 30))
    series[0, 12] = np.nan
    series[1, 7] = np.nan
    k, spin = 0.9, 4
    state = F.api_state(series, k)
    t = np.array([10, 20])
    rows = np.array([0, 1])
    got = F.api_at(state, series, k, rows, t, spinup=spin)
    for i in range(2):
        acc = 0.0
        for u in range(t[i] - spin, t[i] + 1):
            acc = k * acc + np.nan_to_num(series[rows[i], u], nan=0.0)
        assert got[i] == pytest.approx(acc)
    with pytest.raises(ValueError):
        F.api_at(state, series, k, rows, np.array([3, 3]), spinup=4)
    assert np.isnan(F.api_at(state, series, k, np.array([0]), np.array([12]), spinup=4)[0])


def test_neighbourhood_stats_ignore_nan():
    values = np.array([[1, 2, 3, 4, 5, 6, 7, 8, 9], [np.nan] * 9, [np.nan, 4, np.nan, 2, 6, np.nan, np.nan, np.nan, np.nan]])
    top, mean = F.neighbourhood_stats(values)
    assert top[0] == 9 and mean[0] == 5
    assert np.isnan(top[1]) and np.isnan(mean[1])
    assert top[2] == 6 and mean[2] == 4


def test_neighbour_pixels_interior_and_edges():
    cols = imerg.COLS
    inner = F.neighbour_pixels(np.array([5 * cols + 7]))[0]
    assert inner[F.CENTRE] == 5 * cols + 7 and (inner >= 0).all()
    assert sorted(inner) == sorted(r * cols + c for r in (4, 5, 6) for c in (6, 7, 8))
    corner = F.neighbour_pixels(np.array([0]))[0]
    assert sorted(corner[corner >= 0]) == [0, 1, cols, cols + 1] and (corner < 0).sum() == 5
    top_right = F.neighbour_pixels(np.array([(imerg.ROWS - 1) * cols + cols - 1]))[0]
    assert (top_right >= 0).sum() == 4


def test_cell_pixels_marks_cells_outside_the_grid():
    flat = F.cell_pixels(np.array([WAYANAD, latlon_to_cell(60.0, 10.0), WAYANAD]))
    row, col = imerg_pixel(WAYANAD)
    assert flat.tolist() == [row * imerg.COLS + col, -1, row * imerg.COLS + col]


# ------------------------------------------------------------------------------------ against the oracle

@pytest.fixture(scope="module")
def store():
    return FakeStore()


@pytest.fixture(scope="module")
def clim(store):
    return make_clim(store)


@pytest.mark.parametrize("nan_rate", [0.03, 0.0])
def test_all_columns_match_the_oracle(nan_rate):
    store = FakeStore(nan_rate=nan_rate)
    clim = make_clim(store)
    dates = [date(2009, 1, 3), date(2012, 7, 30), date(2014, 6, 1), date(2016, 6, 30), date(2007, 2, 1)]
    frame = frame_for(dates)
    got = F.build_imerg_features(frame, store, clim)
    assert list(got.columns) == F.all_names() and (got.dtypes == np.float32).all()
    assert got.index.equals(frame.index)
    for i, (cell, ts) in enumerate(zip(frame["cell_id"], frame["date"])):
        r, c = imerg_pixel(cell)
        want = oracle_row(store, clim.lookup(np.array([r * imerg.COLS + c]), np.array([ts.month]))[0], cell, ts.date())
        for name, value in want.items():
            np.testing.assert_allclose(got.loc[i, name], value, rtol=2e-5, atol=1e-4, equal_nan=True,
                                       err_msg=f"{name} cell {cell} {ts.date()}")
    if nan_rate:
        assert got.isna().to_numpy().any()                       # the NaN rule is exercised
    else:
        assert got.notna().to_numpy().sum() > 0.9 * got.size     # long windows and the API are exercised


def test_chunking_does_not_change_values_and_row_order_is_kept(store, clim):
    rng = np.random.default_rng(1)
    pick = rng.permutation(len(CELLS) * 6)
    frame = frame_for([date(2010, 8, 1) + timedelta(int(k)) for k in (0, 1, 40, 200, 400, 900)]).iloc[pick]
    frame = frame.reset_index(drop=True)
    whole = F.build_imerg_features(frame, store, clim)
    small = F.build_imerg_features(frame, store, clim, chunk_days=7, pixel_block=2)
    pd.testing.assert_frame_equal(whole, small)
    single = F.build_imerg_features(frame.iloc[[3]], store, clim)
    pd.testing.assert_frame_equal(single.reset_index(drop=True), whole.iloc[[3]].reset_index(drop=True))


def test_interior_and_edge_neighbourhoods(store, clim):
    frame = frame_for([date(2011, 7, 20)], [WAYANAD, EDGE, NORTH_EAST])
    got = F.build_imerg_features(frame, store, clim)
    for i, cell in enumerate(frame["cell_id"]):
        r, c = imerg_pixel(cell)
        for n in (1, 3):
            accs = [sum(oracle_imd(store, r + dr, c + dc, date(2011, 7, 20) - timedelta(k)) for k in range(n))
                    for dr in (-1, 0, 1) for dc in (-1, 0, 1)]
            good = [a for a in accs if not np.isnan(a)]
            assert got.loc[i, f"inbr_max_acc_{n}"] == pytest.approx(max(good), rel=1e-5)
            assert got.loc[i, f"inbr_mean_acc_{n}"] == pytest.approx(np.mean(good), rel=1e-5)
    assert F.neighbour_pixels(np.array([0]))[0].tolist().count(-1) == 5   # the corner really is an edge case


def test_cell_outside_the_grid_is_all_nan(store, clim):
    frame = pd.DataFrame({"cell_id": [latlon_to_cell(60.0, 10.0), WAYANAD], "date": pd.Timestamp("2012-07-01")})
    got = F.build_imerg_features(frame, store, clim)
    assert got.iloc[0].isna().all() and got.iloc[1].notna().any()


def test_missing_store_days_give_nan_not_zero():
    gappy = FakeStore(first=date(2012, 1, 1), last=date(2012, 6, 30), nan_rate=0.0)
    clim = F.imerg_climatology(gappy, F.cell_pixels(np.array([WAYANAD])), date(2012, 1, 1), date(2012, 6, 30))
    frame = frame_for([date(2012, 5, 10)], [WAYANAD])
    got = F.build_imerg_features(frame, gappy, clim)
    # the store starts 130 days before: the 90-day window is complete, the API spin-up before it is missing (0)
    assert got["irain_acc_90"].notna().all() and got["iapi_90"].notna().all()
    early = F.build_imerg_features(frame_for([date(2012, 2, 20)], [WAYANAD]), gappy, clim)
    assert np.isnan(early["irain_acc_90"]).all() and np.isnan(early["irain_acc_60"]).all()
    assert early["irain_acc_30"].notna().all()


def test_climatology_matches_oracle_and_uses_only_the_train_range(store):
    table = make_clim(store, [WAYANAD, EDGE])
    for cell in (WAYANAD, EDGE):
        r, c = imerg_pixel(cell)
        got = table.values[np.searchsorted(table.pix, r * imerg.COLS + c)]
        np.testing.assert_allclose(got, oracle_clim(store, r, c), rtol=1e-5, equal_nan=True)
    perturbed = make_clim(FakeStore(bump_after=CLIM_LAST, bump_before=CLIM_FIRST), [WAYANAD, EDGE])
    np.testing.assert_array_equal(table.pix, perturbed.pix)
    np.testing.assert_array_equal(table.values, perturbed.values)
    inside = make_clim(FakeStore(bump_after=date(2015, 6, 30)), [WAYANAD, EDGE])
    assert not np.array_equal(table.values, inside.values)    # the test would notice a change inside the range


def test_vs_clim_floor_and_clim_lookup(store, clim):
    zero = ClimTable(clim.pix, np.zeros_like(clim.values))
    frame = frame_for([date(2013, 7, 15)], [WAYANAD])
    got = F.build_imerg_features(frame, store, zero)
    acc = got["irain_acc_3"].to_numpy()
    np.testing.assert_allclose(got["irain_acc3_vs_clim"], acc / 1.0, rtol=1e-6, equal_nan=True)   # floor 1 mm
    empty = F.build_imerg_features(frame, store, ClimTable(np.array([], dtype=np.int64), np.empty((0, 12, 3))))
    assert empty[["irain_acc3_vs_clim", "irain_acc7_vs_clim", "irain_acc30_vs_clim"]].isna().all().all()


def test_causality_values_after_day_d_never_enter(clim):
    d = date(2016, 3, 10)
    rows = frame_for([d - timedelta(60), d, d + timedelta(1), d + timedelta(30)])
    base = F.build_imerg_features(rows, FakeStore(), clim)
    after = F.build_imerg_features(rows, FakeStore(bump_after=d), clim)
    at_d = rows["date"] <= pd.Timestamp(d)
    pd.testing.assert_frame_equal(base[at_d], after[at_d])
    assert not base[~at_d].equals(after[~at_d])              # rows after D do see the perturbation
    # the perturbation reaches every value after UTC day D, including UTC day D+1 that IMD day D+1 uses
    assert FakeStore(bump_after=d).value(*imerg_pixel(WAYANAD), d + timedelta(1)) != \
        FakeStore().value(*imerg_pixel(WAYANAD), d + timedelta(1))
    # UTC day D itself IS used (weight 0.125): perturbing day D alone changes the features at D
    shifted = F.build_imerg_features(rows, FakeStore(bump_after=d - timedelta(1)), clim)
    assert not base[at_d].equals(shifted[at_d])


def test_day_utc_d_enters_with_weight_one_eighth():
    one = FakeStore(first=date(2012, 1, 1), last=date(2012, 12, 31), nan_rate=0.0)
    clim = F.imerg_climatology(one, F.cell_pixels(np.array([WAYANAD])), date(2012, 1, 1), date(2012, 12, 31))
    r, c = imerg_pixel(WAYANAD)
    d = date(2012, 9, 1)
    frame = frame_for([d], [WAYANAD])
    before = F.build_imerg_features(frame, one, clim)
    one.series(r, c)[(d - one.first).days] += 80.0                       # UTC day D only
    after = F.build_imerg_features(frame, one, clim)
    assert after["irain_acc_1"][0] - before["irain_acc_1"][0] == pytest.approx(0.125 * 80.0, rel=1e-4)
    one.series(r, c)[(d - one.first).days - 1] += 80.0                   # UTC day D-1 carries 0.875
    assert F.build_imerg_features(frame, one, clim)["irain_acc_1"][0] - after["irain_acc_1"][0] ==         pytest.approx(0.875 * 80.0, rel=1e-4)


# ------------------------------------------------------------------------------------- build and freeze

EXTRAS = hm.hazard_config(PROJECT_ROOT / "configs" / "hazard_v3.yaml")["extra_groups"]


def real_cells():
    return np.array([WAYANAD, WAYANAD + 1, WAYANAD + 20_000, EDGE], dtype=np.int64)


@pytest.fixture
def tiny_store(tmp_path):
    """A development feature store whose rows sit on real IMERG-grid cells, its features_manifest.json, an IMERG
    index file and a fake store, ready for `build_imerg_tables`."""
    samples, universe = synthetic_development(n_pos_train=15, n_pos_validation=8, n_per_region=60)
    cells = real_cells()
    samples["cell_id"] = cells[np.arange(len(samples)) % len(cells)]
    universe["cell_id"] = cells[np.arange(len(universe)) % len(cells)]
    features = write_store(tmp_path / "features", {"train_samples": samples[samples["split"] == "train"].reset_index(drop=True),
                                                   "validation_samples": samples[samples["split"] == "validation"].reset_index(drop=True),
                                                   "universe_train": universe[universe["split"] == "train"].reset_index(drop=True),
                                                   "universe_validation": universe[universe["split"] == "validation"].reset_index(drop=True)},
                           extras=False)
    names = ["train_samples", "validation_samples", "universe_train", "universe_validation"]
    (features / "features_manifest.json").write_text(json.dumps({
        "sample_files": [f"{n}.parquet" for n in names],
        "files": {f"{n}_features.parquet": {"sha256": sha256_file(features / f"{n}_features.parquet")} for n in names}}),
        encoding="utf-8")
    index = tmp_path / "rain" / "imerg_late_index.json"
    index.parent.mkdir()
    days = [START + timedelta(k) for k in range((date(2017, 12, 31) - START).days + 1)]
    present = [d for d in days if d != date(2010, 5, 5)]
    years = {str(y): {"present": [d.isoformat() for d in present if d.year == y],
                      "versions": {d.isoformat(): "V07B" for d in present if d.year == y},
                      "missing": [], "failed": ["2010-05-05"] if y == 2010 else []} for y in range(2006, 2018)}
    index.write_text(json.dumps({"years": years}), encoding="utf-8")
    out = features / "imerg"
    yield B.ImergInputs(features, index), out, FakeStore(last=date(2017, 12, 31))
    for path in out.rglob("*"):
        path.chmod(stat.S_IWRITE | stat.S_IREAD)


def test_written_files_load_through_hazard_data(tiny_store):
    inputs, out, store = tiny_store
    manifests, reused = B.build_imerg_tables(inputs, out, store)
    assert not reused and set(manifests) == {"irain", "iapi", "inbr"}
    use = ("irain", "iapi", "inbr")
    column_map = hd.load_column_map(inputs.features_dir, EXTRAS, use)
    assert {g for c, g in column_map.items() if c.startswith(("irain_", "iapi_", "inbr_"))} == set(use)
    table = hd.load_table("train_samples", inputs.features_dir, EXTRAS, use)
    base = pd.read_parquet(inputs.features_dir / "train_samples_features.parquet")
    assert len(table) == len(base) and (table["cell_id"].to_numpy() == base["cell_id"].to_numpy()).all()
    assert all(c in table.columns for c in F.all_names()) and table[F.all_names()].notna().to_numpy().any()
    development = hd.load_development(inputs.features_dir, EXTRAS, use)
    assert set(F.all_names()) <= set(development.samples.columns) <= set(development.column_map) | set(development.samples.columns)
    assert set(F.all_names()) <= set(development.universe.columns) and set(F.all_names()) <= set(development.column_map)
    columns = json.loads((out / "irain_columns.json").read_text())
    assert set(columns.values()) == {"irain"} and list(columns) == F.feature_names()["irain"]


def test_keys_order_dtypes_and_nan_counts_in_the_report(tiny_store):
    inputs, out, store = tiny_store
    B.build_imerg_tables(inputs, out, store)
    for stem in ("train_samples", "universe_validation"):
        base = pd.read_parquet(inputs.features_dir / f"{stem}_features.parquet", columns=["cell_id", "date"])
        for group, names in F.feature_names().items():
            table = pd.read_parquet(out / f"{stem}_{group}.parquet")
            assert list(table.columns) == ["cell_id", "date", *names]
            assert table[["cell_id", "date"]].equals(base) and (table[names].dtypes == np.float32).all()
    report = json.loads((out / B.REPORT_NAME).read_text())
    assert report["files"]["train_samples_features.parquet"]["rows_outside_grid"] == 0
    assert set(report["files"]["train_samples_features.parquet"]["nan_share"]) == set(F.all_names())
    assert report["imerg_days_missing"]["days"] == ["2010-05-05"]
    assert report["climatology"]["first_day"] == "2007-01-01" and report["climatology"]["last_day"] == "2015-12-31"


def test_freeze_reuse_verify_and_force(tiny_store):
    inputs, out, store = tiny_store
    B.build_imerg_tables(inputs, out, store)
    assert not (out / "irain_manifest.json").stat().st_mode & stat.S_IWRITE          # read-only
    assert not (out / "train_samples_iapi.parquet").stat().st_mode & stat.S_IWRITE
    manifest = json.loads((out / "inbr_manifest.json").read_text())
    assert manifest["frozen"] and manifest["inputs"]["imerg_index"]["signature"]
    assert manifest["files"]["train_samples_inbr.parquet"]["n_rows"] > 0
    _, reused = B.build_imerg_tables(inputs, out, store)
    assert reused
    assert B.verify_imerg_tables(out, inputs, B.build_config())["ok"]
    (out / "train_samples_iapi.parquet").chmod(stat.S_IWRITE)
    with (out / "train_samples_iapi.parquet").open("ab") as handle:
        handle.write(b"x")
    result = B.verify_imerg_tables(out, inputs)
    assert not result["ok"] and any("checksum mismatch" in p for p in result["problems"])
    with pytest.raises(B.ImergFeaturesIntegrityError):
        B.build_imerg_tables(inputs, out, store)
    _, reused = B.build_imerg_tables(inputs, out, store, force=True)
    assert not reused and B.verify_imerg_tables(out, inputs)["ok"]


def test_verify_detects_changed_inputs_and_config(tiny_store):
    inputs, out, store = tiny_store
    B.build_imerg_tables(inputs, out, store)
    changed = B.build_config()
    changed["api_spinup"] = 60
    assert not B.verify_imerg_tables(out, inputs, changed)["ok"]
    index = json.loads(inputs.index_path.read_text())
    index["years"]["2010"]["failed"] = []                       # a failed day was backfilled
    index["years"]["2010"]["present"].append("2010-05-05")
    index["years"]["2010"]["versions"]["2010-05-05"] = "V07B"
    inputs.index_path.write_text(json.dumps(index))
    result = B.verify_imerg_tables(out, inputs)
    assert not result["ok"] and any("IMERG index" in p for p in result["problems"])


def test_index_growth_after_the_last_sample_date_is_not_a_change(tiny_store):
    inputs, out, store = tiny_store
    B.build_imerg_tables(inputs, out, store)
    index = json.loads(inputs.index_path.read_text())
    index["years"]["2018"] = {"present": ["2018-01-01"], "versions": {"2018-01-01": "V07B"}, "missing": [], "failed": []}
    inputs.index_path.write_text(json.dumps(index))
    assert B.verify_imerg_tables(out, inputs)["ok"]


def test_missing_feature_store_manifest_is_reported(tmp_path):
    inputs = B.ImergInputs(tmp_path / "none", tmp_path / "idx.json")
    with pytest.raises(FileNotFoundError):
        B.build_imerg_tables(inputs, tmp_path / "out", FakeStore())


# --------------------------------------------------------------------------------------- a real ImergStore

def write_real_store(root, years, plant):
    """Sparse year arrays + index in the on-disk ImergStore format; `plant` = {(row, col): mm per UTC day}."""
    root.mkdir(parents=True, exist_ok=True)
    versions = {}
    for year in years:
        n = (date(year + 1, 1, 1) - date(year, 1, 1)).days
        stack = np.lib.format.open_memmap(root / f"imerg_late_{year}.npy", mode="w+", dtype=np.float32,
                                          shape=(n, imerg.ROWS, imerg.COLS))
        for (row, col), mm in plant.items():
            stack[:, row, col] = mm
        stack.flush()
        del stack
        versions[year] = {(date(year, 1, 1) + timedelta(k)).isoformat(): "V07B" for k in range(n)}
    index = {"years": {str(y): {"present": list(v), "versions": v, "missing": [], "failed": []}
                       for y, v in versions.items()}}
    (root / "imerg_late_index.json").write_text(json.dumps(index), encoding="utf-8")
    return ImergStore(root, "late", raw_dir=root / "raw", manifest=Manifest(root / "m.jsonl", root))


def test_real_store_constant_rain_gives_known_values(tmp_path):
    row, col = imerg_pixel(WAYANAD)
    store = write_real_store(tmp_path / "rain", range(2006, 2011), {(row, col): 6.0, (row, col + 1): 2.0})
    try:
        table = F.imerg_climatology(store, F.cell_pixels(np.array([WAYANAD])), date(2007, 1, 1), date(2009, 12, 31))
        frame = frame_for([date(2009, 12, 31), date(2010, 3, 1)], [WAYANAD])
        got = F.build_imerg_features(frame, store, table)
    finally:
        store.close()
    assert got["irain_acc_1"].tolist() == [6.0, 6.0] and got["irain_acc_90"].tolist() == [540.0, 540.0]
    assert got["irain_days_since_10mm"].tolist() == [90.0, 90.0] and got["irain_wetdays_30"].tolist() == [30.0, 30.0]
    assert got["iapi_90"].iloc[0] == pytest.approx(6.0 * (1 - 0.9 ** 121) / 0.1, rel=1e-5)
    assert got["inbr_max_acc_1"].tolist() == [6.0, 6.0]                        # neighbours with 0 and 2 mm below
    assert got["inbr_mean_acc_1"].iloc[0] == pytest.approx((6.0 + 2.0) / 9, rel=1e-5)
    assert got["irain_acc3_vs_clim"].iloc[0] == pytest.approx(1.0, rel=1e-5)
    assert got["irain_acc30_vs_clim"].iloc[1] == pytest.approx(1.0, rel=1e-5)
