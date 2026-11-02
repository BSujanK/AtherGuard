import numpy as np
import pandas as pd
import pytest
from integrity_helpers import synthetic_set

from aetherguard.integrity import features, neighbours
from aetherguard.integrity.grids import SOURCES, GridRefs

NAN = np.nan
LAYOUT = {"IN_A": (20.0, 75.0, 10.0), "IN_B": (20.5, 75.0, 10.0), "IN_C": (21.0, 75.0, 10.0)}


def make_refs(index, columns, **given):
    frames = {}
    for name in SOURCES:
        arr = np.full((len(index), len(columns)), np.nan, dtype=np.float32)
        if name in given:
            arr[:] = given[name]
        frames[name] = pd.DataFrame(arr, index=index, columns=columns)
    return GridRefs(frames)


def setup(columns: dict, start="2010-01-01", **refs):
    """(values, meta, refs, neighbour table, climatology) for the given station series."""
    sset = synthetic_set({k: np.asarray(v, dtype=np.float32) for k, v in columns.items()}, start=start,
                         meta_rows={k: LAYOUT[k] for k in columns})
    table = neighbours.neighbour_table(sset.meta, k=10, max_km=300)
    grid = make_refs(sset.values.index, list(sset.values.columns), **refs)
    return sset.values, sset.meta, grid, table


def build(values, meta, grid, table, **kwargs):
    clim = kwargs.pop("climatology", None)
    if clim is None:
        clim = pd.DataFrame({"p50": 5.0, "p90": 20.0, "p99": 60.0}, index=values.columns)
    return features.build_features(values, values.index, meta, grid, table, climatology=clim, **kwargs)


def last(frame, station="IN_A"):
    return frame[frame["station"] == station].iloc[-1]


def rain(n, seed, wet=0.5, scale=8.0):
    rng = np.random.default_rng(seed)
    return np.where(rng.random(n) < wet, np.round(rng.gamma(0.8, scale, n) + 1.0, 1), 0.0)


# ------------------------------------------------------------------ causality

def test_features_at_day_t_ignore_everything_after_t():
    n = 300
    data = {k: rain(n, s) for s, k in enumerate(LAYOUT)}
    data["IN_A"][50:60] = NAN
    imd = np.random.default_rng(5).gamma(0.8, 8.0, (n, 3)).astype(np.float32)
    values, meta, grid, table = setup(data, imd=imd, chirps_aligned=imd[::-1], gw_top=0.5, gw_root=0.4)
    clim = pd.DataFrame({"p50": 5.0, "p90": 20.0, "p99": 60.0}, index=values.columns)
    base = build(values, meta, grid, table, climatology=clim)
    t = 200
    rng = np.random.default_rng(9)
    values2 = values.copy()
    values2.iloc[t + 1:t + 31] = rng.gamma(1.0, 40.0, (30, 3)).astype(np.float32)
    frames = {k: v.copy() for k, v in grid.values.items()}
    for frame in frames.values():
        frame.iloc[t + 1:t + 31] = rng.random((30, 3)).astype(np.float32)
    changed = build(values2, meta, GridRefs(frames), table, climatology=clim)
    keep = base["date"] <= values.index[t]
    pd.testing.assert_frame_equal(base[keep].reset_index(drop=True), changed[keep].reset_index(drop=True))
    assert not base[~keep].reset_index(drop=True).equals(changed[~keep].reset_index(drop=True))


def test_window_edges_are_trailing_not_centred():
    x = np.zeros(40)
    x[30] = 50.0                                 # a spike on day 30
    values, meta, grid, table = setup({"IN_A": x})
    out = build(values, meta, grid, table)
    a = out[out["station"] == "IN_A"].reset_index(drop=True)
    assert a.loc[29, "own_max_7"] == 0.0 and a.loc[30, "own_max_7"] == 50.0 and a.loc[36, "own_max_7"] == 50.0
    assert a.loc[37, "own_max_7"] == 0.0


# ------------------------------------------------------------------ own_

def test_own_rolling_statistics_on_a_crafted_series():
    x = np.concatenate([np.zeros(26), [0, 0, 3, 3, 3, 1, 0, 2, 2, 5, 0, 0, 4, 0]])  # 40 days
    values, meta, grid, table = setup({"IN_A": x})
    row = last(build(values, meta, grid, table))
    w7 = x[-7:]
    w14 = x[-14:]
    assert row["own_mean_7"] == pytest.approx(w7.mean()) and row["own_std_7"] == pytest.approx(w7.std())
    assert row["own_zero_frac_7"] == pytest.approx((w7 == 0).mean()) and row["own_max_7"] == 5.0
    assert row["own_distinct_7"] == len(set(w7)) and row["own_longest_run_7"] == 2
    assert row["own_distinct_14"] == len(set(w14)) and row["own_longest_run_14"] == 3
    assert row["own_mean_30"] == pytest.approx(x[-30:].mean())
    assert row["own_wet_frac_30"] == pytest.approx((x[-30:] >= 1).mean())
    assert row["own_ratio_7_30"] == pytest.approx(w7.mean() / x[-30:].mean())


def test_run_lengths_and_days_since_wet():
    x = np.concatenate([np.zeros(20), [4.0, 4.0, 4.0, 4.0, 0.0, 0.0, 6.0, 6.0, 6.0, 6.0, 6.0, 6.0]])
    values, meta, grid, table = setup({"IN_A": x})
    a = build(values, meta, grid, table).reset_index(drop=True)
    assert a.loc[23, "own_run_len"] == 4 and a.loc[23, "own_pos_run_len"] == 4
    assert a.loc[25, "own_run_len"] == 2 and a.loc[25, "own_pos_run_len"] == 0      # a dry run is not a stuck run
    assert a.loc[31, "own_run_len"] == 6 and a.loc[31, "own_pos_run_len"] == 6
    assert a.loc[25, "own_days_since_wet"] == 2 and a.loc[26, "own_days_since_wet"] == 0
    assert a["own_days_since_wet"].iloc[:20].isna().all()                          # no wet day seen yet


def test_missing_values_stay_nan_and_windows_need_70_percent_valid_days():
    x = rain(40, 1)
    x[36:40] = NAN                                   # last 4 days missing
    x[20:23] = NAN
    values, meta, grid, table = setup({"IN_A": x})
    a = build(values, meta, grid, table).reset_index(drop=True)
    assert a.loc[39, "own_mean_7"] != a.loc[39, "own_mean_7"]                         # 3 valid of 7 < 5
    assert np.isnan(a.loc[39, "own_run_len"]) and np.isnan(a.loc[39, "own_ratio_p50"])
    assert a.loc[37, "own_mean_14"] == pytest.approx(np.nanmean(x[24:38]))           # 12 valid of 14: ok
    zeros_not_nan = setup({"IN_A": np.zeros(40)})
    z = build(*zeros_not_nan)
    assert (z["own_mean_7"].iloc[4:] == 0).all() and z["own_mean_7"].iloc[:4].isna().all()  # 5 valid days suffice


def test_ratio_to_the_train_climatology_percentiles():
    x = np.concatenate([np.zeros(39), [30.0]])
    values, meta, grid, table = setup({"IN_A": x})
    clim = pd.DataFrame({"p50": [10.0], "p90": [20.0], "p99": [60.0]}, index=["IN_A"])
    row = last(build(values, meta, grid, table, climatology=clim))
    assert (row["own_ratio_p50"], row["own_ratio_p90"], row["own_ratio_p99"]) == (3.0, 1.5, 0.5)
    nan_clim = pd.DataFrame({"p50": [NAN], "p90": [NAN], "p99": [NAN]}, index=["IN_A"])
    assert np.isnan(last(build(values, meta, grid, table, climatology=nan_clim))["own_ratio_p50"])


def test_station_climatology_uses_only_the_train_years():
    index = pd.date_range("2007-01-01", "2020-12-31", freq="D")
    train = np.where(index.year <= 2015, 10.0, 500.0)
    frame = pd.DataFrame({"IN_A": train, "IN_B": np.where(index.year <= 2015, 0.0, 30.0)}, index=index).astype(np.float32)
    clim = features.station_climatology(frame)
    assert clim.loc["IN_A"].tolist() == [10.0, 10.0, 10.0]
    assert clim.loc["IN_B"].isna().all()               # no wet days in the train years


# ------------------------------------------------------------------ nbr_

def test_neighbour_features_and_correlation_rules():
    n = 60
    b = rain(n, 3)
    c = rain(n, 4)
    a = 0.5 * (b + c) + np.arange(n) % 3                 # tracks the neighbour mean
    values, meta, grid, table = setup({"IN_A": a, "IN_B": b, "IN_C": c})
    out = build(values, meta, grid, table)
    row = last(out, "IN_B")                              # B has neighbours A and C
    idw = row["nbr_idw_mean"]
    assert row["nbr_n_valid"] == 2 and row["nbr_resid"] == pytest.approx(b[-1] - idw, abs=1e-4)
    assert row["nbr_ratio"] == pytest.approx((b[-1] + 1) / (idw + 1), rel=1e-5)
    assert row["nbr_frac_wet"] in (0.0, 0.5, 1.0) and row["nbr_max"] == pytest.approx(max(a[-1], c[-1]))
    series = out[out["station"] == "IN_B"]
    ok = series["nbr_idw_mean"].notna().to_numpy()
    expected = np.corrcoef(b[-30:], series["nbr_idw_mean"].to_numpy()[-30:])[0, 1]
    assert row["nbr_corr_30"] == pytest.approx(expected, abs=1e-4) and ok.all()
    assert out[out["station"] == "IN_B"]["nbr_corr_14"].iloc[:9].isna().all()        # < 10 pairs


def test_neighbour_correlation_is_nan_with_few_pairs_or_constant_series():
    n = 40
    a = np.full(n, NAN)
    a[-8:] = rain(8, 1)                                  # only 8 pairs in any window
    values, meta, grid, table = setup({"IN_A": a, "IN_B": rain(n, 2), "IN_C": rain(n, 3)})
    assert np.isnan(last(build(values, meta, grid, table))["nbr_corr_30"])
    flat = setup({"IN_A": np.full(n, 3.0), "IN_B": rain(n, 2), "IN_C": rain(n, 3)})
    assert np.isnan(last(build(*flat))["nbr_corr_30"])


def test_neighbour_features_are_nan_with_fewer_than_two_valid_neighbours():
    values, meta, grid, table = setup({"IN_A": rain(40, 1), "IN_B": rain(40, 2)})
    row = last(build(values, meta, grid, table))
    assert row["nbr_n_valid"] == 1 and np.isnan(row["nbr_idw_mean"]) and np.isnan(row["nbr_resid"])


# ------------------------------------------------------------------ grid_

def test_grid_residual_ratio_and_sums():
    n = 40
    x = np.full(n, 4.0)
    g = np.full(n, 2.0)
    values, meta, grid, table = setup({"IN_A": x}, imd=g[:, None], chirps_aligned=np.full((n, 1), NAN))
    row = last(build(values, meta, grid, table))
    assert row["grid_resid_imd"] == 2.0 and row["grid_ratio_imd"] == pytest.approx(5 / 3)
    assert row["grid_sumdiff_imd_7"] == 14.0 and row["grid_sumratio_imd_7"] == pytest.approx(29 / 15)
    assert row["grid_sumdiff_imd_30"] == 60.0
    assert np.isnan(row["grid_resid_chirps"]) and np.isnan(row["grid_sumdiff_chirps_14"])
    assert np.isnan(row["grid_corr_imd_30"])                 # a constant series has no correlation


def test_grid_sums_use_only_days_where_both_are_valid_and_need_70_percent_pairs():
    n = 40
    x = np.full(n, 4.0)
    g = np.full(n, 2.0)
    g[-3:] = NAN                                          # 4 valid pairs of 7 in the 7-day window
    values, meta, grid, table = setup({"IN_A": x}, imd=g[:, None])
    row = last(build(values, meta, grid, table))
    assert np.isnan(row["grid_sumdiff_imd_7"])             # needs ceil(0.7*7) = 5 pairs
    assert row["grid_sumdiff_imd_14"] == pytest.approx(2.0 * 11)  # 11 valid pairs of 14 (needs 10)


def test_grid_correlation_and_disagreement_fractions():
    n = 60
    g = rain(n, 7)
    x = g * 2 + 1
    values, meta, grid, table = setup({"IN_A": x}, imd=g[:, None])
    assert last(build(values, meta, grid, table))["grid_corr_imd_30"] == pytest.approx(1.0, abs=1e-6)
    x2 = np.zeros(n)
    x2[-14:] = [0, 0, 0, 0, 0, 0, 0, 8, 8, 8, 8, 8, 8, 8]
    g2 = np.zeros(n)
    g2[-14:] = [9, 9, 9, 9, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
    v2, m2, grid2, t2 = setup({"IN_A": x2}, imd=g2[:, None])
    row = last(build(v2, m2, grid2, t2))
    assert row["grid_zero_vs_wet_imd_14"] == pytest.approx(4 / 14)     # obs 0 while the grid says 9 mm
    assert row["grid_wet_vs_zero_imd_14"] == pytest.approx(7 / 14)     # obs 8 mm while the grid says 0


def test_agree_count_and_n_refs():
    n = 40
    x = np.zeros(n)
    x[-1] = 100.0
    imd = np.zeros((n, 1), dtype=np.float32)
    imd[-1] = 40.0                                         # >= 30% of 100: agrees
    chirps = np.zeros((n, 1), dtype=np.float32)
    chirps[-1] = 10.0                                      # < 30: does not agree
    values, meta, grid, table = setup({"IN_A": x}, imd=imd, chirps_aligned=chirps)
    row = last(build(values, meta, grid, table))
    assert row["grid_agree_count"] == 1 and row["grid_n_refs"] == 2   # no neighbours: two refs available
    assert np.isnan(build(values, meta, grid, table).iloc[0]["grid_agree_count"])    # obs < 20 mm -> undefined
    full = setup({"IN_A": x, "IN_B": np.full(n, 50.0), "IN_C": np.full(n, 50.0)}, imd=imd, chirps_aligned=chirps)
    row = last(build(*full))
    assert row["grid_agree_count"] == 2 and row["grid_n_refs"] == 3   # imd and the neighbour idw agree


# ------------------------------------------------------------------ wet_

def test_wetness_level_and_three_day_change_with_masking():
    n = 10
    top = np.linspace(0.2, 0.5, n).astype(np.float32)[:, None]
    root = top - 0.1
    root[-1] = NAN
    values, meta, grid, table = setup({"IN_A": np.zeros(n)}, gw_top=top, gw_root=root)
    a = build(values, meta, grid, table).reset_index(drop=True)
    assert a.loc[5, "wet_top"] == pytest.approx(top[5, 0]) and a.loc[5, "wet_top_chg3"] == pytest.approx(top[5, 0] - top[2, 0])
    assert np.isnan(a.loc[1, "wet_top_chg3"]) and np.isnan(a.loc[9, "wet_root"]) and np.isnan(a.loc[9, "wet_root_chg3"])


# ------------------------------------------------------------------ structure

def test_groups_are_column_filters_and_dtypes_are_float32():
    values, meta, grid, table = setup({"IN_A": rain(40, 1), "IN_B": rain(40, 2)})
    out = build(values, meta, grid, table)
    assert list(out.columns[:2]) == ["station", "date"] and len(out) == 80
    cols = [c for c in out.columns if c not in ("station", "date")]
    assert all(out[c].dtype == np.float32 for c in cols)
    for prefix in features.PREFIXES:
        assert features.select_columns(cols, [prefix]) and all(c.startswith(prefix) for c in features.select_columns(cols, [prefix]))
    assert set(features.select_columns(cols, ["own_", "nbr_"])) == {c for c in cols if c.startswith(("own_", "nbr_"))}
    with pytest.raises(ValueError, match="unknown"):
        features.select_columns(cols, ["foo_"])


def test_stations_subset_and_input_validation():
    values, meta, grid, table = setup({"IN_A": rain(40, 1), "IN_B": rain(40, 2), "IN_C": rain(40, 3)})
    out = build(values, meta, grid, table, stations=["IN_B"])
    assert set(out["station"]) == {"IN_B"} and out["nbr_n_valid"].iloc[-1] == 2   # neighbours still used
    with pytest.raises(ValueError, match="index"):
        features.build_features(values, values.index[:-1], meta, grid, table)
    with pytest.raises(ValueError, match="same stations"):
        features.build_features(values, values.index, meta.iloc[::-1].reset_index(drop=True), grid, table)


def test_feature_report_counts_rows_memory_and_nan_shares():
    values, meta, grid, table = setup({"IN_A": rain(40, 1), "IN_B": rain(40, 2)}, imd=1.0)
    report = features.feature_report(build(values, meta, grid, table))
    assert report["rows"] == 80 and report["memory_mb"] >= 0
    assert set(report["by_group"]) == set(features.PREFIXES)
    assert report["by_group"]["wet_"]["nan_share_mean"] == 1.0           # no wetness given
    assert 0 <= report["nan_share_by_column"]["own_mean_30"] < 1
    assert report["rows_with_observed_value"] == 80
    assert report["by_group"]["own_"]["nan_share_mean_on_observed_days"] <= report["by_group"]["own_"]["nan_share_mean"]
    assert report["nan_share_by_column_on_observed_days"]["own_ratio_p50"] == 0.0
