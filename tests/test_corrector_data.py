import numpy as np
import pandas as pd
import pytest
from integrity_helpers import synthetic_set

from aetherguard.corrector import data as cd
from aetherguard.grid import latlon_to_cell
from aetherguard.integrity.grids import SOURCES, GridRefs

NAN = np.nan
LAYOUT = {"IN_A": (11.5, 76.25, 900.0), "IN_B": (11.6, 76.25, 50.0)}


def refs_for(index, columns, **given):
    frames = {}
    for name in SOURCES:
        arr = np.full((len(index), len(columns)), np.nan, dtype=np.float32)
        if name in given:
            value = np.asarray(given[name], dtype=np.float32)
            arr[:] = value if value.ndim == 0 else value.reshape(len(index), -1)
        frames[name] = pd.DataFrame(arr, index=index, columns=columns)
    return GridRefs(frames)


def terrain_for(*stations):
    rows = []
    for sid in stations:
        lat, lon, _ = LAYOUT[sid]
        rows.append({"cell_id": int(latlon_to_cell(lat, lon)), "elev_mean": 800.0, "relief": 120.0, "slope_mean": 9.0,
                     "aspect_sin": 0.5, "aspect_cos": -0.5})
    return pd.DataFrame(rows)


def window(n=3 * 366, seed=0, wet_scale=9.0):
    rng = np.random.default_rng(seed)
    data = {sid: np.where(rng.random(n) < 0.5, np.round(rng.gamma(0.8, wet_scale, n) + 1.0, 1), 0.0) for sid in LAYOUT}
    return synthetic_set(data, start="2007-01-01", meta_rows=LAYOUT)


def test_calendar_predictors_are_cyclic_and_month_is_numeric():
    out = cd.calendar_predictors(["2020-01-01", "2020-07-01", "2020-12-31"])
    assert out["month"].tolist() == [1.0, 7.0, 12.0]
    assert out["doy_sin"][0] == pytest.approx(0.0, abs=1e-9) and out["doy_cos"][0] == pytest.approx(1.0)
    assert np.hypot(out["doy_sin"], out["doy_cos"]) == pytest.approx(1.0)
    assert abs(out["doy_sin"][2]) < 0.05                       # the year wraps around


def test_cell_side_mapping_uses_the_feature_columns_and_cell_elevation():
    features = pd.DataFrame({"date": pd.to_datetime(["2024-07-30"]), "src_chi_acc_1": [51.6], "src_chi_acc_3": [84.7],
                             "wet_top": [0.9], "wet_root": [1.0], "stat_elev_mean": [1037.0], "stat_relief": [300.0],
                             "stat_slope_mean": [12.0], "stat_aspect_sin": [0.1], "stat_aspect_cos": [0.9],
                             "src_imd_acc_1": [179.0], "src_imd_acc_3": [250.0]})
    out = cd.predictors_from_features(features)
    assert out["chirps_1"][0] == 51.6 and out["chirps_3"][0] == 84.7 and out["imd_1"][0] == 179.0
    assert out["elev_point"][0] == out["elev_mean"][0] == 1037.0 and out["relief"][0] == 300.0
    assert out["month"][0] == 7.0
    assert set(cd.PREDICTORS + cd.IMD_PREDICTORS) == set(out.columns)


def test_station_predictors_shift_wetness_to_d_minus_1_sum_three_days_and_join_terrain():
    w = window(n=10)
    index = w.values.index
    chirps = np.arange(1.0, 11.0).reshape(10, 1) * np.ones((1, 2))
    chirps[4, 0] = NAN
    wet = np.linspace(0.1, 1.0, 10).reshape(10, 1) * np.ones((1, 2))
    refs = refs_for(index, list(w.values.columns), chirps_aligned=chirps, gw_top=wet, gw_root=wet, imd=chirps * 2)
    frames = cd.station_predictors(w, refs, terrain_for("IN_A"))
    assert frames["chirps_1"].iloc[3, 1] == 4.0
    assert frames["chirps_3"].iloc[5, 1] == 4 + 5 + 6 and np.isnan(frames["chirps_3"].iloc[1, 1])
    assert np.isnan(frames["chirps_3"].iloc[5, 0])             # a missing day inside the window: no 3-day total
    assert frames["wet_top"].iloc[3, 0] == pytest.approx(wet[2, 0]) and np.isnan(frames["wet_top"].iloc[0, 0])
    assert frames["imd_3"].iloc[5, 1] == 2 * (4 + 5 + 6)
    assert frames["elev_mean"]["IN_A"].eq(800.0).all() and frames["elev_mean"]["IN_B"].isna().all()   # B's cell is absent
    assert frames["elev_point"]["IN_A"].eq(900.0).all() and frames["elev_point"]["IN_B"].eq(50.0).all()


def make_table(flagged=None, chirps_nan_from=None, min_valid_days=150, **kwargs):
    w = window(**kwargs)
    index, ids = w.values.index, list(w.values.columns)
    chirps = np.full((len(index), 2), 5.0)
    if chirps_nan_from is not None:
        chirps[chirps_nan_from:, :] = NAN
    refs = refs_for(index, ids, chirps_aligned=chirps, gw_top=0.5, gw_root=0.5, imd=chirps)
    splits = {"train": ["IN_A"], "val": ["IN_B"], "test": []}
    return w, cd.station_table(w, refs, terrain_for("IN_A", "IN_B"), flagged, splits, min_valid_days)


def test_rows_need_a_clean_unflagged_day_with_chirps_and_carry_the_split():
    flagged = pd.DataFrame(False, index=window().values.index, columns=["IN_A", "IN_B"])
    flagged.iloc[100:110, 0] = True
    w, table = make_table(flagged=flagged, chirps_nan_from=900)
    assert set(table["split"]) == {"train", "val"}
    assert (table.loc[table["station"] == "IN_A", "split"] == "train").all()
    day = w.values.index
    a_dates = set(table.loc[table["station"] == "IN_A", "date"])
    assert not a_dates & set(day[100:110].to_numpy())           # engine-flagged days are excluded
    assert not a_dates & set(day[900:].to_numpy())              # no CHIRPS: no row
    assert table["chirps_1"].notna().all() and table["gauge"].notna().all()
    assert table["month"].between(1, 12).all()
    assert len(table) > 1500


def test_clean_rule_uses_the_150_valid_day_relaxation():
    w = window()
    w.values.iloc[:, 0] = np.where(np.arange(len(w.values)) % 365 < 170, w.values.iloc[:, 0], np.nan)   # ~170 valid days a year
    refs = refs_for(w.values.index, list(w.values.columns), chirps_aligned=5.0, gw_top=0.5, gw_root=0.5)
    splits = {"train": ["IN_A"], "val": ["IN_B"], "test": []}
    table = cd.station_table(w, refs, terrain_for("IN_A"), None, splits)
    assert (table["station"] == "IN_A").sum() > 400
    strict = cd.station_table(w, refs, terrain_for("IN_A"), None, splits, min_valid_days=300)
    assert (strict["station"] == "IN_A").sum() == 0


def test_exceedance_threshold_is_the_train_year_wet_day_p99_of_the_station():
    w, table = make_table()
    for sid in ("IN_A", "IN_B"):
        part = table[table["station"] == sid]
        train = part[(pd.DatetimeIndex(part["date"]).year <= 2015) & (part["gauge"] >= 1.0)]
        assert part["p99"].iloc[0] == pytest.approx(np.percentile(train["gauge"], 99))
        assert (part["exceed"] == (part["gauge"] >= part["p99"]).astype(float)).all()
    assert table["exceed"].mean() < 0.05 and table["exceed"].sum() > 0


def test_a_station_with_few_wet_days_gets_no_exceedance_label():
    w = window()
    w.values.iloc[:, 1] = np.where(np.arange(len(w.values)) < 20, 5.0, 0.0)       # only 20 wet days
    refs = refs_for(w.values.index, list(w.values.columns), chirps_aligned=5.0, gw_top=0.5, gw_root=0.5)
    splits = {"train": ["IN_A"], "val": ["IN_B"], "test": []}
    table = cd.station_table(w, refs, terrain_for("IN_A"), None, splits, min_valid_days=1)
    b = table[table["station"] == "IN_B"]
    assert len(b) > 0 and b["p99"].isna().all() and b["exceed"].isna().all()
    assert table.loc[table["station"] == "IN_A", "exceed"].notna().all()
