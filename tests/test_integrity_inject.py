import json

import numpy as np
import pandas as pd
import pytest
from integrity_helpers import synthetic_set

from aetherguard.integrity import inject
from aetherguard.integrity.inject import FAULT_TYPES, InjectionImpossible


def rain_series(n=400, seed=0):
    rng = np.random.default_rng(seed)
    wet = rng.random(n) < 0.45
    return np.where(wet, np.round(rng.gamma(0.7, 12.0, n) + 1.0, 1), 0.0).astype(np.float32)


@pytest.fixture
def series():
    return rain_series()


@pytest.fixture
def params(series):
    return inject.station_params(series)


def run(name, series, params, start=200, length=None, seed=1):
    spec = inject.DEFAULT_SPECS[name]
    if length is None:
        length = 1 if name == "spike" else spec.min_len + 2
    rng = np.random.default_rng(seed)
    return spec.injector(series, start, length, rng, params), length


@pytest.mark.parametrize("name", FAULT_TYPES)
def test_every_injector_returns_float32_of_the_window_length_within_bounds(name, series, params):
    out, length = run(name, series, params)
    assert out.dtype == np.float32 and out.shape == (length,)
    assert np.isfinite(out).all() and (out >= 0).all() and (out <= 1500).all()
    assert np.allclose(out, np.round(out, 1))  # gauge resolution 0.1 mm


@pytest.mark.parametrize("name", FAULT_TYPES)
def test_every_injector_is_deterministic_for_a_seed_and_varies_across_seeds(name, series, params):
    a, _ = run(name, series, params, seed=7)
    b, _ = run(name, series, params, seed=7)
    np.testing.assert_array_equal(a, b)
    outs = {run(name, series, params, seed=s)[0].tobytes() for s in range(8)}
    if name != "zero_fault":
        assert len(outs) > 1


@pytest.mark.parametrize("name", FAULT_TYPES)
def test_missing_days_inside_the_window_stay_nan(name, series, params):
    holed = series.copy()
    holed[200] = np.nan
    length = 1 if name == "spike" else None
    out, n = run(name, holed, params, start=200, length=length)
    assert np.isnan(out[0]) and np.isfinite(out[1:]).all()


def test_stuck_value_repeats_one_positive_value_from_the_wet_percentile_band(series, params):
    out, length = run("stuck_value", series, params, length=12)
    assert len(set(out.tolist())) == 1 and out[0] > 0
    assert params["wet_p50"] - 0.06 <= out[0] <= params["wet_p90"] + 0.06


def test_zero_fault_reads_zero(series, params):
    out, _ = run("zero_fault", series, params, length=10)
    assert (out == 0).all()


def test_spike_is_implausibly_large_relative_to_local_rain(series, params):
    local = float(np.median(np.concatenate([series[185:200], series[201:216]])[
        np.concatenate([series[185:200], series[201:216]]) >= 1.0]))
    for seed in range(40):
        out, _ = run("spike", series, params, seed=seed)
        assert out[0] <= 1500
        assert out[0] >= 10 * local or out[0] >= 500  # multiplicative (x10..x50, capped) or absolute


def test_scale_drift_moves_the_factor_linearly_to_a_target():
    win = np.full(400, 10.0, dtype=np.float32)
    up = down = 0
    for seed in range(30):
        out = inject.inject_scale_drift(win, 100, 60, np.random.default_rng(seed), {})
        assert out[0] == 10.0
        ratio = out[-1] / 10.0
        assert ratio == pytest.approx(0.3, abs=0.02) or ratio == pytest.approx(2.5, abs=0.02)
        assert np.all(np.diff(out) >= -1e-6) or np.all(np.diff(out) <= 1e-6)
        up += ratio > 1
        down += ratio < 1
    assert up > 0 and down > 0


def test_offset_noise_adds_small_positive_readings_on_dry_days_only(series):
    out = inject.inject_offset_noise(series, 100, 60, np.random.default_rng(3), {})
    window = series[100:160]
    assert (out[window > 0] == window[window > 0]).all()
    dry = out[window == 0]
    assert len(dry) > 0 and (dry >= 0.2 - 1e-6).all() and (dry <= 1.0 + 1e-6).all()


def test_duplicate_block_equals_an_earlier_block_of_the_series(series, params):
    out = inject.inject_duplicate_block(series, 200, 14, np.random.default_rng(5), params)
    found = [s for s in range(0, 200 - 14 + 1) if np.array_equal(series[s:s + 14], out)]
    assert found and (out > 0).sum() >= 3


def test_duplicate_block_without_history_is_reported_not_faked(series, params):
    with pytest.raises(InjectionImpossible):
        inject.inject_duplicate_block(series, 5, 14, np.random.default_rng(5), params)
    dry = np.zeros(100, dtype=np.float32)
    with pytest.raises(InjectionImpossible):
        inject.inject_duplicate_block(dry, 60, 10, np.random.default_rng(5), {})


def test_window_outside_the_series_raises(series, params):
    with pytest.raises(ValueError):
        inject.inject_zero_fault(series, 395, 10, np.random.default_rng(0), params)


def test_station_params_needs_wet_days_and_explicit_magnitudes():
    with pytest.raises(ValueError, match="wet days"):
        inject.station_params(np.zeros(100))
    with pytest.raises(KeyError, match="wet_p50"):
        inject.inject_stuck_value(rain_series(), 100, 10, np.random.default_rng(0), {})


# ---------------------------------------------------------------- dataset / placement

def make_set(n_stations=4, years=6, seed=0):
    n = 365 * years + 2
    data, flags = {}, {}
    for k in range(n_stations):
        arr = rain_series(n, seed + k).astype(np.float32)
        arr[500:510] = np.nan          # a gap run inside year 2001 (still >= 200 valid days)
        data[f"IN{k:09d}"] = arr
        flags[f"IN{k:09d}"] = {800: "K", 801: "K", 1500: "O"}
    return synthetic_set(data, flags=flags)


def make_splits(sset):
    ids = list(sset.meta["id"])
    return {"train": ids[:2], "val": ids[2:3], "test": ids[3:]}


@pytest.fixture(scope="module")
def dataset_inputs():
    sset = make_set()
    return sset, make_splits(sset)


@pytest.fixture(scope="module")
def dataset(dataset_inputs):
    sset, splits = dataset_inputs
    return inject.build_fault_dataset(sset, splits, seed=11, density=0.08, min_gap_days=5)


def episodes(table, station):
    sub = table[(table["station"] == station) & (table["episode_id"] >= 0)]
    return sub.groupby("episode_id", observed=True)["date"].agg(["min", "max", "size"])


def test_dataset_columns_and_one_row_per_station_day(dataset, dataset_inputs):
    sset, _ = dataset_inputs
    assert list(dataset.columns) == ["station", "date", "value_true", "value_obs", "fault_type",
                                     "episode_id", "split", "clean_real", "real_flag"]
    assert len(dataset) == sset.values.size
    assert dataset["value_true"].dtype == np.float32


def test_unchanged_everywhere_except_labelled_days(dataset):
    changed = ~np.isclose(dataset["value_true"], dataset["value_obs"], equal_nan=True, rtol=0, atol=0)
    labelled = dataset["fault_type"] != ""
    assert (changed == labelled).all()
    assert labelled.sum() > 0


def test_missing_values_stay_missing_and_are_never_zero(dataset):
    missing = dataset["value_true"].isna()
    assert missing.sum() > 0
    assert dataset.loc[missing, "value_obs"].isna().all()
    assert (dataset.loc[missing, "fault_type"] == "").all() and (dataset.loc[missing, "episode_id"] == -1).all()


def test_episodes_lie_only_on_clean_real_days(dataset):
    in_episode = dataset["episode_id"] >= 0
    assert dataset.loc[in_episode, "clean_real"].all()
    flagged = dataset["real_flag"] != ""
    assert flagged.sum() > 0 and not dataset.loc[flagged, "clean_real"].any()
    assert (dataset.loc[flagged, "episode_id"] == -1).all()


def test_episodes_do_not_overlap_and_keep_the_minimum_gap(dataset):
    for station in dataset["station"].unique():
        ep = episodes(dataset, station).sort_values("min")
        assert len(ep) >= 1
        gaps = (ep["min"].iloc[1:].to_numpy() - ep["max"].iloc[:-1].to_numpy()) / np.timedelta64(1, "D") - 1
        assert (gaps >= 5).all()
        assert (ep["size"] == (ep["max"] - ep["min"]).dt.days + 1).all()  # contiguous windows


def test_each_episode_has_one_type_and_the_injected_length_range(dataset):
    faulty = dataset[dataset["fault_type"] != ""]
    per_episode = faulty.groupby("episode_id", observed=True)["fault_type"].nunique()
    assert (per_episode == 1).all()
    windows = dataset[dataset["episode_id"] >= 0].groupby("episode_id", observed=True).size()
    types = faulty.groupby("episode_id", observed=True)["fault_type"].first().astype(str)
    for ep, name in types.items():
        spec = inject.DEFAULT_SPECS[name]
        assert spec.min_len <= windows[ep] <= spec.max_len


def test_density_is_about_the_requested_share_of_clean_days(dataset):
    for station in dataset["station"].unique():
        sub = dataset[dataset["station"] == station]
        share = (sub["episode_id"] >= 0).sum() / sub["clean_real"].sum()
        assert 0.05 <= share <= 0.13


def test_all_six_types_occur_and_are_roughly_balanced(dataset):
    counts = dataset[dataset["fault_type"] != ""].groupby("fault_type", observed=True)["episode_id"].nunique()
    assert set(counts.index) == set(FAULT_TYPES)
    assert counts.max() <= 3 * counts.min()


def test_split_column_follows_the_station_splits(dataset, dataset_inputs):
    _, splits = dataset_inputs
    for split, ids in splits.items():
        assert set(dataset.loc[dataset["split"] == split, "station"].astype(str)) == set(ids)


def test_duplicate_block_episodes_copy_an_earlier_block(dataset):
    dup = dataset[dataset["fault_type"] == "duplicate_block"]
    assert len(dup) > 0
    ep = dup["episode_id"].iloc[0]
    rows = dataset[dataset["episode_id"] == ep]
    station_rows = dataset[dataset["station"] == rows["station"].iloc[0]]
    true = station_rows["value_true"].to_numpy()
    window = rows["value_obs"].to_numpy()
    first = rows.index[0] - station_rows.index[0]
    hits = [s for s in range(first - len(window) + 1) if np.array_equal(true[s:s + len(window)], window)]
    assert hits


def test_dataset_is_deterministic_for_a_seed_and_differs_across_seeds(dataset_inputs, dataset):
    sset, splits = dataset_inputs
    again = inject.build_fault_dataset(sset, splits, seed=11)
    pd.testing.assert_frame_equal(dataset, again)
    other = inject.build_fault_dataset(sset, splits, seed=12)
    assert not other["episode_id"].equals(dataset["episode_id"])


def test_station_order_does_not_change_a_stations_episodes(dataset_inputs):
    sset, splits = dataset_inputs
    full = inject.build_fault_dataset(sset, splits, seed=3)
    keep = list(sset.meta["id"][2:])
    sub = synthetic_set({sid: sset.values[sid].to_numpy() for sid in keep},
                        flags={sid: {800: "K", 801: "K", 1500: "O"} for sid in keep})
    part = inject.build_fault_dataset(sub, {"train": [], "val": [], "test": keep}, seed=3)
    last = keep[-1]
    a = full[full["station"] == last]["value_obs"].to_numpy()
    b = part[part["station"] == last]["value_obs"].to_numpy()
    np.testing.assert_array_equal(a, b)


def test_splits_must_cover_every_station_once(dataset_inputs):
    sset, splits = dataset_inputs
    with pytest.raises(ValueError, match="both"):
        inject.build_fault_dataset(sset, {**splits, "val": splits["train"][:1]}, seed=1)
    with pytest.raises(ValueError, match="missing"):
        inject.build_fault_dataset(sset, {"train": splits["train"], "val": [], "test": []}, seed=1)


def test_clean_real_needs_value_no_flag_and_a_nearly_complete_year():
    n = 365 * 2
    sparse = np.full(n, np.nan, dtype=np.float32)
    sparse[:199] = 1.0                       # year 1: only 199 valid days (< 200)
    sparse[365:] = 2.0                       # year 2: complete
    sset = synthetic_set({"IN_A": sparse}, flags={"IN_A": {400: "S"}}, start="2001-01-01")
    clean = inject.clean_real_mask(sset)["IN_A"].to_numpy()
    assert not clean[:365].any()
    assert clean[365:].sum() == 365 - 1 and not clean[400]


def test_too_dry_station_gets_no_episodes_instead_of_failing():
    sset = synthetic_set({"IN_A": np.zeros(365 * 2, dtype=np.float32)}, start="2001-01-01")
    table = inject.build_fault_dataset(sset, {"train": ["IN_A"], "val": [], "test": []}, seed=1)
    assert (table["episode_id"] == -1).all()
    assert inject.dataset_report(table)["splits"]["train"]["n_stations_with_episodes"] == 0


def test_dataset_report_counts_episodes_and_days_per_type_per_split(dataset):
    report = inject.dataset_report(dataset)
    assert set(report["splits"]) == {"train", "val", "test"}
    total_days = sum(v["days"] for s in report["splits"].values() for v in s["by_type"].values())
    assert total_days == int((dataset["fault_type"] != "").sum())
    total_eps = sum(v["episodes"] for s in report["splits"].values() for v in s["by_type"].values())
    assert total_eps == dataset.loc[dataset["fault_type"] != "", "episode_id"].nunique()
    json.dumps(report, allow_nan=False)


# ---------------------------------------------------------------- calibration

def _full(spec_by_station, n=120):
    frames = {}
    for sid, spec in spec_by_station.items():
        value = np.full(n, 0.0, dtype=np.float32)
        lo, hi = spec.get("streak", (0, 0))
        value[lo:hi] = 4.0
        flag = np.full(n, "", dtype=object)
        for (a, b), letter in spec.get("flags", []):
            flag[a:b] = letter
        frames[sid] = pd.DataFrame({"value": value, "flag": flag},
                                   index=pd.date_range("1960-01-01", periods=n, freq="D"))
    return frames


def test_calibration_lists_real_flag_runs_and_natural_streaks():
    sset = synthetic_set({"IN_A": np.zeros(5), "IN_B": np.zeros(5)})
    full = _full({"IN_A": {"flags": [((10, 41), "D"), ((60, 88), "D"), ((100, 101), "K")],
                           "streak": (20, 23)},
                  "IN_B": {"flags": [((5, 6), "K"), ((50, 52), "S")]}})
    cal = inject.calibrate_from_real_flags(sset, full)
    assert cal["runs"]["D"] == [28, 31] and cal["runs"]["K"] == [1, 1] and cal["runs"]["S"] == [2]
    assert cal["flag_days"] == {"D": 59, "K": 2, "S": 2}
    assert cal["identical_positive_streaks"] == {3: 1}
    used = cal["used"]
    assert (used["duplicate_block"]["min_len"], used["duplicate_block"]["max_len"]) == (7, 31)
    assert used["stuck_value"]["min_len"] == 5 and used["stuck_value"]["max_len"] == 30
    json.dumps(cal, allow_nan=False)


def test_calibration_raises_the_stuck_range_above_natural_streaks_and_feeds_the_dataset():
    sset = synthetic_set({"IN_A": np.zeros(5)})
    full = _full({"IN_A": {"streak": (10, 20)}})  # a natural 10-day streak
    cal = inject.calibrate_from_real_flags(sset, full)
    assert cal["used"]["stuck_value"]["min_len"] == 11
    specs = inject.specs_from_calibration(cal)
    assert specs["stuck_value"].min_len == 11 and specs["zero_fault"] == inject.DEFAULT_SPECS["zero_fault"]
    assert inject.specs_from_calibration(None) == inject.DEFAULT_SPECS


def test_valid_days_threshold_is_a_parameter_with_default_200():
    assert inject.MIN_VALID_DAYS_PER_YEAR == 200
    n = 365
    arr = np.full(n, np.nan, dtype=np.float32)
    arr[:250] = 1.0                          # 250 valid days: clean at 200, not at 300
    sset = synthetic_set({"IN_A": arr}, start="2001-01-01")
    assert inject.clean_real_mask(sset)["IN_A"].sum() == 250
    assert inject.clean_real_mask(sset, 300)["IN_A"].sum() == 0
