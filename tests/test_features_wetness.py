"""W4 `iwet` antecedent-wetness features: the radiation and loss terms, the bucket, the NaN rule, the lag (nothing after
IMD day D-2 is read), row independence, a slow per-row oracle, the train-range climatology and anomaly, the live adapter, and
the frozen tables `hazard.data.load_table` accepts.
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
from aetherguard.features import wetness as W
from aetherguard.grid import latlon_to_cell
from aetherguard.hazard import data as hd
from aetherguard.hazard import model as hm
from aetherguard.ingest import imerg
from aetherguard.ingest.imerg import imerg_pixel

from test_features_imerg import START, real_cells, tiny_store  # noqa: F401  (fixture: development store, index, fake store)

WAYANAD = latlon_to_cell(11.47, 76.13)
KATHMANDU = latlon_to_cell(27.70, 85.32)
OUTSIDE = latlon_to_cell(60.0, 10.0)
D = date(2012, 8, 10)
NAMES = ["iwet_sat_l2", "iwet_sat_anom_l2", "iwet_satdays30_l2"]
EXTRAS = hm.hazard_config(PROJECT_ROOT / "configs" / "hazard_v3.yaml")["extra_groups"]
IWET = {"subdir": "imerg", "suffix": "iwet", "columns_file": "iwet_columns.json", "manifest_file": "iwet_manifest.json"}


class FuncStore:
    """`ImergStore.gather` from a function (row, col, day) -> mm; records the newest UTC day ever read."""

    def __init__(self, fn):
        self.fn, self.newest = fn, None

    def gather(self, rows, cols, first_day, length):
        last = first_day + timedelta(length - 1)
        self.newest = last if self.newest is None else max(self.newest, last)
        out = np.empty((len(rows), length), dtype=np.float32)
        for i, (r, c) in enumerate(zip(rows, cols)):
            for j in range(length):
                out[i, j] = self.fn(int(r), int(c), first_day + timedelta(j))
        return out


def light(r, c, day):
    """Light, varying rain that never fills the bucket: changes anywhere in the window show."""
    return float((day.toordinal() * 7 + r * 3 + c) % 5) * 0.6


EMPTY = W.Climatology(np.zeros(0, dtype=np.int64), np.zeros((0, 12)))


# ----------------------------------------------------------------------------------------------- numerics

def test_feature_names_are_the_three_declared_columns():
    assert W.feature_names() == NAMES and W.LAG_DAYS == 2 and W.SPINUP_DAYS == 120


def test_extraterrestrial_radiation_reproduces_the_fao56_worked_example():
    # FAO-56 example 8: 20 degrees south on 3 September (day 246): Ra = 32.2 MJ m-2 day-1
    assert W.extraterrestrial_radiation(-20.0, 246) == pytest.approx(32.2, abs=0.05)


def test_the_climatological_loss_is_in_the_range_of_indian_reference_evapotranspiration():
    monsoon = W.pet_mm(np.array([10.0, 20.0, 30.0]), 196)          # mid July
    winter = W.pet_mm(np.array([10.0, 20.0, 30.0]), 349)           # mid December
    assert ((monsoon > 3.3) & (monsoon < 4.8)).all() and ((winter > 1.2) & (winter < 3.5)).all()
    assert winter[2] < winter[0]                                   # shorter, lower sun further north in winter


def test_the_bucket_fills_caps_and_dries_as_manabe_wrote_it():
    rain = np.array([[100.0, 100.0, 0.0, 0.0]])
    pet = np.array([[0.0, 0.0, 10.0, 10.0]])
    water = W.bucket(rain, pet)
    assert water[0, 0] == 100.0 and water[0, 1] == W.CAPACITY_MM            # full bucket spills the excess
    assert water[0, 2] == W.CAPACITY_MM - 10.0                             # above 75% full the loss is the whole PET
    assert water[0, 3] == pytest.approx(140.0 - 10.0 * min(1.0, 140.0 / (0.75 * 150.0)))
    low = W.bucket(np.array([[30.0, 0.0]]), np.array([[0.0, 4.0]]))
    assert low[0, 1] == pytest.approx(30.0 - 4.0 * 30.0 / 112.5)            # below it the loss falls with the water
    assert (W.bucket(np.array([[0.0, 0.0]]), np.array([[5.0, 5.0]])) == 0.0).all()   # never below empty


def test_nan_rain_adds_nothing_but_nan_in_the_last_thirty_days_makes_the_features_nan():
    rng = np.random.default_rng(1)
    rain = rng.gamma(1.0, 3.0, (3, 120))
    pet = np.full((3, 120), 3.0)
    old, recent = rain.copy(), rain.copy()
    old[1, 10] = np.nan
    recent[2, -30] = np.nan
    sat, days = W.window_features(np.vstack([rain[0], old[1], recent[2]]), pet)
    zero = rain[1].copy()
    zero[10] = 0.0
    ref, ref_days = W.window_features(zero[None, :], pet[:1])
    assert sat[1] == ref[0] and days[1] == ref_days[0]                     # an old gap contributes no rain, no more
    assert np.isnan(sat[2]) and np.isnan(days[2]) and np.isfinite(sat[0])
    assert ((sat[[0, 1]] >= 0) & (sat[[0, 1]] <= 1)).all()


def test_saturated_days_count_the_last_thirty_days_at_95_percent_or_more():
    rain = np.zeros((1, 120))
    rain[0, 100] = 400.0                                                   # fills the bucket on day 100
    sat, days = W.window_features(rain, np.zeros((1, 120)))
    assert sat[0] == 1.0 and days[0] == 20.0                                 # days 100..119
    sat, days = W.window_features(rain, np.full((1, 120), 4.0))
    expected = (W.bucket(rain, np.full((1, 120), 4.0))[0, -30:] >= 0.95 * 150.0).sum()
    assert days[0] == expected and 0 < expected < 30


# ------------------------------------------------------------------------------------------- rows and lag

def oracle(store_fn, cell, day):
    """Slow per-row oracle: the IMD-day series of the 120 days ending at D-2, then the bucket by hand."""
    r, c = imerg_pixel(cell)
    end = day - timedelta(2)
    lat = imerg.LAT_FIRST + imerg.STEP * r
    water, history = 0.0, []
    for k in range(119, -1, -1):
        t = end - timedelta(k)
        p = 0.875 * store_fn(r, c, t - timedelta(1)) + 0.125 * store_fn(r, c, t)
        pet = 0.25 * float(W.extraterrestrial_radiation(lat, t.timetuple().tm_yday)) / 2.45
        loss = pet * min(1.0, water / (0.75 * 150.0))
        water = min(150.0, max(0.0, water - loss + (0.0 if np.isnan(p) else p)))
        history.append(water)
    return water / 150.0, float(sum(w >= 0.95 * 150.0 for w in history[-30:]))


def test_rows_match_the_slow_oracle_for_several_cells_and_days():
    store = FuncStore(light)
    cells = [WAYANAD, KATHMANDU, WAYANAD + 1, KATHMANDU]
    days = [D, D, D + timedelta(40), date(2013, 1, 5)]
    out = W.features_for_rows(cells, np.array(days, dtype="datetime64[ns]"), store, EMPTY)
    for i, (cell, day) in enumerate(zip(cells, days)):
        sat, satdays = oracle(light, cell, day)
        assert out["iwet_sat_l2"][i] == pytest.approx(sat, rel=1e-5) and out["iwet_satdays30_l2"][i] == satdays
    assert list(out.columns) == NAMES and (out.dtypes == np.float32).all()
    assert out["iwet_sat_anom_l2"].isna().all()                             # no climatology: anomaly unknown


def test_nothing_after_imd_day_d_minus_2_is_read_and_utc_d_minus_2_counts():
    base = W.features_for_rows([WAYANAD], [np.datetime64(D)], FuncStore(light), EMPTY)

    def later(r, c, day):
        return light(r, c, day) + (50.0 if day > D - timedelta(2) else 0.0)

    def at_end(r, c, day):
        return light(r, c, day) + (50.0 if day == D - timedelta(2) else 0.0)

    store = FuncStore(later)
    assert W.features_for_rows([WAYANAD], [np.datetime64(D)], store, EMPTY).equals(base)
    assert store.newest == D - timedelta(2) == W.last_utc_day_read(D)
    changed = W.features_for_rows([WAYANAD], [np.datetime64(D)], FuncStore(at_end), EMPTY)
    assert changed["iwet_sat_l2"][0] > base["iwet_sat_l2"][0]               # the 0.125 share of UTC D-2 is in IMD day D-2


def test_a_row_does_not_depend_on_the_other_rows_it_is_computed_with():
    store = FuncStore(light)
    alone = W.features_for_rows([KATHMANDU], [np.datetime64(D)], store, EMPTY)
    many_days = [D - timedelta(300), D + timedelta(200), D] + [D + timedelta(k) for k in range(70)]
    mixed = W.features_for_rows([WAYANAD] * 2 + [KATHMANDU] + [WAYANAD] * 70,
                                np.array(many_days, dtype="datetime64[ns]"), store, EMPTY)
    assert mixed.iloc[[2]].reset_index(drop=True).equals(alone)


def test_a_cell_outside_the_grid_is_nan_and_keeps_its_row():
    out = W.features_for_rows([OUTSIDE, WAYANAD], [np.datetime64(D)] * 2, FuncStore(light), EMPTY)
    assert out.iloc[0][["iwet_sat_l2", "iwet_satdays30_l2"]].isna().all() and out.iloc[1].notna()["iwet_sat_l2"]


def test_the_climatology_is_the_train_range_mean_by_month_and_sets_the_anomaly():
    store = FuncStore(light)
    first, last = date(2010, 1, 1), date(2010, 2, 28)
    pixels = F.cell_pixels(np.array([WAYANAD, KATHMANDU]))
    clim = W.climatology(store, pixels, first, last)
    days = [first + timedelta(k) for k in range((last - first).days + 1)]
    rows = W.features_for_rows([WAYANAD] * len(days), np.array(days, dtype="datetime64[ns]"), store, EMPTY)
    january = rows["iwet_sat_l2"][:31].mean()
    assert clim.lookup(pixels[:1], np.array([1]))[0] == pytest.approx(january, rel=1e-5)
    assert np.isnan(clim.lookup(pixels[:1], np.array([7]))[0])              # no July in the range
    out = W.features_for_rows([WAYANAD, OUTSIDE], [np.datetime64(date(2011, 1, 20))] * 2, store, clim)
    assert out["iwet_sat_anom_l2"][0] == pytest.approx(out["iwet_sat_l2"][0] - january, abs=1e-6)
    assert np.isnan(out["iwet_sat_anom_l2"][1])


def test_the_climatology_round_trips_through_its_file(tmp_path):
    clim = W.Climatology(np.array([3, 7], dtype=np.int64), np.arange(24, dtype=np.float64).reshape(2, 12))
    clim.save(tmp_path / "c.npz")
    back = W.Climatology.load(tmp_path / "c.npz")
    assert (back.pix == clim.pix).all() and (back.mean == clim.mean).all()


def test_the_live_adapter_is_the_training_function_for_one_day():
    store = FuncStore(light)
    clim = W.climatology(store, F.cell_pixels(np.array([WAYANAD])), date(2010, 8, 1), date(2010, 8, 3))
    live = W.live_features(D, [WAYANAD, KATHMANDU], store, clim)
    rows = W.features_for_rows([WAYANAD, KATHMANDU], [np.datetime64(D)] * 2, store, clim)
    assert live.equals(rows) and store.newest == D - timedelta(2)


# ----------------------------------------------------------------------------------------------- frozen tables

def write_panel(directory, year, cells, days):
    directory.mkdir(parents=True, exist_ok=True)
    np.savez(directory / f"season_{year}_training.npz", cell_id=np.asarray(cells, dtype=np.int64),
             days=np.array([d.isoformat() for d in days]), risk=np.zeros((len(cells), len(days))))


@pytest.fixture
def tables(tiny_store, tmp_path):
    inputs, out, store = tiny_store
    panels = tmp_path / "panels"
    write_panel(panels, 2016, real_cells()[:3], [date(2016, 6, 1) + timedelta(k) for k in range(-2, 4)])
    return inputs, out, store, panels


def build(tables, **kwargs):
    inputs, out, store, panels = tables
    pixels = F.cell_pixels(real_cells())
    return W.build_tables(inputs, out, store, panels, years=(2016,), clim_pixels=pixels[pixels >= 0], **kwargs)


def test_tables_have_the_keys_of_the_sample_files_and_load_through_hazard_data(tables):
    inputs, out, store, panels = tables
    manifest, reused = build(tables)
    assert not reused and manifest["group"] == "iwet" and manifest["frozen"] and manifest["lag_days"] == 2
    for stem in ("train_samples", "validation_samples", "universe_train", "universe_validation"):
        base = pd.read_parquet(inputs.features_dir / f"{stem}_features.parquet", columns=["cell_id", "date"])
        table = pd.read_parquet(out / f"{stem}_iwet.parquet")
        assert list(table.columns) == ["cell_id", "date", *NAMES]
        assert table[["cell_id", "date"]].equals(base) and (table[NAMES].dtypes == np.float32).all()
    assert json.loads((out / "iwet_columns.json").read_text()) == {c: "iwet" for c in NAMES}
    table = hd.load_table("train_samples", inputs.features_dir, {**EXTRAS, "iwet": IWET}, ("iwet",))
    assert set(NAMES) <= set(table.columns) and table["iwet_sat_l2"].notna().any()


def test_sample_rows_equal_the_row_function_with_the_frozen_climatology(tables):
    inputs, out, store, panels = tables
    build(tables)
    clim = W.load_climatology(out)
    table = pd.read_parquet(out / "validation_samples_iwet.parquet")
    again = W.features_for_rows(table["cell_id"].to_numpy(), table["date"].to_numpy(), store, clim)
    assert table[NAMES].reset_index(drop=True).equals(again)


def test_the_season_table_is_cells_by_days_in_panel_order(tables):
    inputs, out, store, panels = tables
    build(tables)
    table = pd.read_parquet(out / "season_2016_iwet.parquet")
    cells = real_cells()[:3]
    days = [date(2016, 6, 1) + timedelta(k) for k in range(-2, 4)]
    assert (table["cell_id"].to_numpy() == np.repeat(cells, len(days))).all()
    assert (table["date"].dt.date.to_numpy() == np.tile(np.array(days, dtype=object), len(cells))).all()


def test_files_are_read_only_reused_when_intact_and_tampering_is_found(tables):
    inputs, out, store, panels = tables
    build(tables)
    assert not (out / "iwet_manifest.json").stat().st_mode & stat.S_IWRITE
    assert not (out / "iwet_clim.npz").stat().st_mode & stat.S_IWRITE
    _, reused = build(tables)
    assert reused
    path = out / "season_2016_iwet.parquet"
    path.chmod(stat.S_IWRITE | stat.S_IREAD)
    frame = pd.read_parquet(path)
    frame.loc[0, "iwet_sat_l2"] = 0.5
    frame.to_parquet(path, index=False)
    problems = W.verify_tables(out, inputs, panels)["problems"]
    assert any("checksum mismatch: season_2016_iwet.parquet" in p for p in problems)
    with pytest.raises(W.WetnessIntegrityError):
        build(tables)
    manifest, reused = build(tables, force=True)
    assert not reused and W.verify_tables(out, inputs, panels, W.build_config((2016,)))["ok"]


def test_a_changed_climatology_file_is_refused_when_loaded(tables):
    inputs, out, store, panels = tables
    build(tables)
    path = out / "iwet_clim.npz"
    path.chmod(stat.S_IWRITE | stat.S_IREAD)
    W.Climatology(np.array([1], dtype=np.int64), np.zeros((1, 12))).save(path)
    with pytest.raises(W.WetnessIntegrityError):
        W.load_climatology(out)


def test_existing_groups_are_not_touched(tables):
    inputs, out, store, panels = tables
    B.build_imerg_tables(inputs, out, store)
    before = {p.name: p.stat().st_mtime_ns for p in out.iterdir()}
    build(tables)
    after = {p.name: p.stat().st_mtime_ns for p in out.iterdir() if p.name in before}
    assert before == after
