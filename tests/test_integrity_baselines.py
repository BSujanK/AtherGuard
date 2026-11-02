import numpy as np
import pandas as pd
import pytest
from integrity_helpers import synthetic_set

from aetherguard.integrity import baselines, neighbours

NAN = np.nan


def frame(columns, start="2000-01-01"):
    """date x station float32 frame from {station: list}."""
    n = len(next(iter(columns.values())))
    index = pd.date_range(start, periods=n, freq="D").as_unit("ns")
    return pd.DataFrame({k: np.asarray(v, dtype=np.float32) for k, v in columns.items()}, index=index)


def cluster(n_days, **series):
    """Stations ~11 km apart (every pair within 150 km) carrying the given series."""
    meta = {sid: (20.0 + 0.1 * k, 75.0, 10.0) for k, sid in enumerate(sorted(series))}
    sset = synthetic_set({k: np.asarray(v, dtype=np.float32) for k, v in series.items()}, meta_rows=meta)
    return sset.values, neighbours.neighbour_table(sset.meta, k=5, max_km=150)


def test_range_check_flags_outside_zero_to_1500():
    v = frame({"a": [0, 1500, 1500.5, -1, NAN, np.inf]})
    assert baselines.range_check(v)["a"].tolist() == [False, False, True, True, False, True]


# ------------------------------------------------------------------ NOAA-style QA

def rainy(n, seed=0, wet=0.4, scale=8.0):
    rng = np.random.default_rng(seed)
    return np.where(rng.random(n) < wet, np.round(rng.gamma(0.7, scale, n) + 1.0, 1), 0.0)


def test_noaa_k_needs_ten_identical_nonzero_values():
    a = rainy(200, 1)
    a[50:60] = 7.5      # ten identical days
    a[100:109] = 4.2    # nine identical days
    v, table = cluster(200, IN_A=a, IN_B=rainy(200, 2), IN_C=rainy(200, 3))
    reasons = baselines.noaa_style_reasons(v, table)
    assert reasons["K"]["IN_A"].iloc[50:60].all() and not reasons["K"]["IN_A"].iloc[100:109].any()
    assert baselines.noaa_style_qa(v, table)["IN_A"].iloc[50:60].all()


def test_noaa_d_flags_a_repeated_month_but_not_a_short_repeat():
    rng = np.random.default_rng(4)
    month = np.round(rng.gamma(0.7, 10, 30) + 1.0, 1)
    short = np.round(rng.gamma(0.7, 10, 10) + 1.0, 1)
    filler1, filler2, filler3 = rainy(40, 5), rainy(40, 6), rainy(40, 7)
    a = np.concatenate([month, filler1, month, filler2, short, filler3, short])
    v, table = cluster(len(a), IN_A=a, IN_B=rainy(len(a), 8), IN_C=rainy(len(a), 9))
    flags = baselines.noaa_style_reasons(v, table)["D"]["IN_A"].to_numpy()
    assert flags[70:100].all() and not flags[:30].any()
    assert not flags[len(a) - 10:].any()  # a 10-day repeat is below NOAA's month-sized blocks


def test_noaa_o_is_one_and_a_half_times_the_stations_own_999th_percentile():
    a = rainy(20000, 11, wet=0.5, scale=10.0)
    p999 = np.percentile(a[a >= 1.0], 99.9)
    a[500], a[900] = 1.3 * p999, 1.8 * p999
    v, table = cluster(20000, IN_A=a, IN_B=rainy(20000, 12), IN_C=rainy(20000, 13))
    flags = baselines.noaa_style_reasons(v, table)["O"]["IN_A"]
    assert not flags.iloc[500] and flags.iloc[900]


def test_noaa_s_zero_while_three_neighbours_report_more_than_ten_mm():
    a = np.zeros(10); b = np.zeros(10); c = np.zeros(10); d = np.zeros(10)
    a[3], b[3], c[3], d[3] = 0.0, 20, 25, 30     # A reads 0, three neighbours > 10 mm
    a[5], b[5], c[5], d[5] = 0.0, 20, 25, 5      # only two neighbours > 10 mm: not flagged
    v, table = cluster(10, IN_A=a, IN_B=b, IN_C=c, IN_D=d)
    s = baselines.noaa_style_reasons(v, table)["S"]["IN_A"]
    assert s.iloc[3] and not s.iloc[5]


def test_noaa_s_wet_while_all_three_or_more_neighbours_are_below_one_mm():
    a = np.zeros(10); b = np.zeros(10); c = np.zeros(10); d = np.zeros(10)
    a[2] = 50.0                                   # wet, neighbours all dry
    a[4], d[4] = 50.0, 3.0                        # one neighbour reports 3 mm: not isolated
    a[6], b[6], c[6], d[6] = 50.0, NAN, NAN, 0.0  # fewer than 3 valid neighbours: no verdict
    v, table = cluster(10, IN_A=a, IN_B=b, IN_C=c, IN_D=d)
    s = baselines.noaa_style_reasons(v, table)["S"]["IN_A"]
    assert s.iloc[2] and not s.iloc[4] and not s.iloc[6]


def test_noaa_qa_is_the_union_of_its_four_reasons():
    a = rainy(120, 21)
    a[10:20] = 6.0
    v, table = cluster(120, IN_A=a, IN_B=rainy(120, 22), IN_C=rainy(120, 23), IN_D=rainy(120, 24))
    reasons = baselines.noaa_style_reasons(v, table)
    union = reasons["K"] | reasons["D"] | reasons["O"] | reasons["S"]
    pd.testing.assert_frame_equal(baselines.noaa_style_qa(v, table), union)
    assert baselines.noaa_style_qa(v, table).dtypes.eq(bool).all()


# ------------------------------------------------------------------ robust z-score

def test_robust_zscore_scores_wet_outliers_high_and_dry_days_zero():
    rng = np.random.default_rng(0)
    a = np.where(rng.random(300) < 0.6, np.round(rng.gamma(2.0, 5.0, 300) + 1.0, 1), 0.0)
    a[200] = 400.0
    v = frame({"IN_A": a})
    score = baselines.robust_zscore(v)["IN_A"]
    assert score.iloc[200] > 20 * np.nanmedian(score[a > 0])
    assert (score[a == 0].dropna() == 0).all()
    assert score.iloc[:29][a[:29] > 0].isna().all()   # wet day with fewer than 30 valid days of history
    assert score.iloc[29:].notna().all()


def test_robust_zscore_matches_the_definition_on_a_hand_computed_window():
    history = np.arange(1.0, 60.0)                    # 59 previous days: 1..59
    v = frame({"IN_A": np.concatenate([history, [100.0]])})
    window = np.concatenate([history, [100.0]])
    med = np.median(window)
    mad = np.median(np.abs(window - med))
    expected = abs(100.0 - med) / (1.4826 * mad + baselines.ZSCORE_EPS)
    assert baselines.robust_zscore(v)["IN_A"].iloc[-1] == pytest.approx(expected, rel=1e-5)


def test_robust_zscore_keeps_missing_missing_and_ignores_nan_history():
    a = np.concatenate([np.full(40, 2.0), [NAN], np.full(20, 2.0), [90.0]])
    score = baselines.robust_zscore(frame({"IN_A": a}))["IN_A"]
    assert np.isnan(score.iloc[40])
    assert score.iloc[-1] > 100
    assert score.iloc[-2] < 1e-3                      # a normal day after the gap


# ------------------------------------------------------------------ isolation forest

def test_window_features_hand_computed():
    x = np.array([0, 0, 3, 3, 3, 1, 0], dtype=np.float32)
    series = np.concatenate([np.full(7, 5.0, dtype=np.float32), x])   # 14 valid days
    row = dict(zip(baselines.FEATURE_NAMES, baselines.window_features(series)[-1]))
    assert row["value"] == 0.0
    assert row["mean_7"] == pytest.approx(x.mean()) and row["std_7"] == pytest.approx(x.std())
    assert row["zero_frac_7"] == pytest.approx(3 / 7) and row["max_7"] == 3.0
    assert row["distinct_7"] == 3 and row["longest_run_7"] == 3
    assert row["mean_14"] == pytest.approx(series.mean()) and row["distinct_14"] == 4
    assert row["longest_run_14"] == 7 and row["zero_frac_14"] == pytest.approx(3 / 14)


def test_features_are_nan_until_a_full_window_of_valid_days():
    x = np.concatenate([rainy(40, 1), [NAN], rainy(20, 2)]).astype(np.float32)
    feats = baselines.window_features(x)
    assert np.isnan(feats[:13]).all()
    assert np.isfinite(feats[13:40]).all()
    assert np.isnan(feats[40:54]).all()               # the missing day poisons the next 14 windows
    assert np.isfinite(feats[54:]).all()


def _train_frame(n=3000):
    return frame({f"IN_{k}": rainy(n, 30 + k, wet=0.45, scale=9.0) for k in range(4)})


def test_isolation_forest_scores_a_stuck_episode_above_normal_days():
    train = _train_frame()
    model = baselines.fit_isolation_forest(train, seed=3)
    test = frame({"IN_T": rainy(400, 99, wet=0.45, scale=9.0)})
    test.iloc[200:230, 0] = 12.0
    score = baselines.isolation_forest(test, model)["IN_T"]
    assert score.iloc[:13].isna().all()
    assert score.iloc[215:230].mean() > score.iloc[20:180].quantile(0.95)


def test_isolation_forest_is_seeded_and_scores_any_matrix():
    train = _train_frame(1500)
    a = baselines.isolation_forest(train, baselines.fit_isolation_forest(train, seed=4))
    b = baselines.isolation_forest(train, baselines.fit_isolation_forest(train, seed=4))
    pd.testing.assert_frame_equal(a, b)
    c = baselines.isolation_forest(train, baselines.fit_isolation_forest(train, seed=5))
    assert not a.equals(c)
    assert a.shape == train.shape and a.index.equals(train.index)
    assert np.isfinite(a.to_numpy()[20:]).all()


def test_isolation_forest_needs_training_rows():
    with pytest.raises(ValueError, match="training"):
        baselines.fit_isolation_forest(frame({"IN_A": [NAN] * 40}), seed=1)
