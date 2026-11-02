import numpy as np
import pandas as pd
import pytest
from integrity_helpers import synthetic_set

from aetherguard.integrity import evaluate, inject, neighbours


def make_truth():
    """100 clean days scoring 0..99, then positives of two types."""
    score = np.concatenate([np.arange(100.0), [150.0, 99.5, 50.0, 10.0], [200.0, 1.0]])
    truth = np.array([""] * 100 + ["stuck_value"] * 4 + ["spike"] * 2, dtype=object)
    clean = np.array([True] * 100 + [False] * 6)
    return score, truth, clean


def test_recall_at_fpr_on_a_hand_made_score_vector():
    score, truth, clean = make_truth()
    out = evaluate.recall_at_fpr(score, truth, clean, fpr=0.05, fault_types=["stuck_value", "spike"])
    # threshold = 95 (the 95th clean score): clean days 96..99 (4%) are flagged
    assert out["threshold"] == 95.0 and out["achieved_fpr"] == pytest.approx(0.04)
    assert out["per_type"]["stuck_value"]["recall"] == 0.5     # 150 and 99.5 exceed 95
    assert out["per_type"]["stuck_value"]["n_positive"] == 4 and out["per_type"]["stuck_value"]["n_detected"] == 2
    assert out["per_type"]["spike"]["recall"] == 0.5
    assert out["macro_recall"] == pytest.approx(0.5)
    assert out["n_clean"] == 100 and out["n_clean_scored"] == 100


def test_recall_is_nan_not_zero_for_a_type_with_no_positives():
    score, truth, clean = make_truth()
    out = evaluate.recall_at_fpr(score, truth, clean, fpr=0.05)   # default: all six types
    assert np.isnan(out["per_type"]["zero_fault"]["recall"]) and out["per_type"]["zero_fault"]["n_positive"] == 0
    assert out["macro_recall"] == pytest.approx(0.5)  # macro over the types that exist


def test_boolean_flags_report_recall_with_their_own_false_flag_rate():
    _, truth, clean = make_truth()
    flag = np.zeros(106, dtype=bool)
    flag[[3, 4]] = True            # 2 of 100 clean days flagged
    flag[[100, 101, 104]] = True   # 2 of 4 stuck, 1 of 2 spike
    out = evaluate.recall_at_fpr(flag, truth, clean, fpr=0.01)
    assert out["threshold"] is None and out["achieved_fpr"] == pytest.approx(0.02)
    assert out["per_type"]["stuck_value"]["recall"] == 0.5 and out["per_type"]["spike"]["recall"] == 0.5


def test_nan_scores_are_unscored_clean_days_are_dropped_and_positives_are_misses():
    score, truth, clean = make_truth()
    score = score.copy()
    score[:10] = np.nan            # 10 unscored clean days
    score[100] = np.nan            # an unscored positive
    out = evaluate.recall_at_fpr(score, truth, clean, fpr=0.05)
    assert out["n_clean_scored"] == 90 and out["n_clean"] == 100
    assert out["per_type"]["stuck_value"]["n_unscored"] == 1
    assert out["per_type"]["stuck_value"]["n_detected"] <= 3


def test_fpr_must_be_a_proper_fraction_and_clean_days_must_exist():
    score, truth, clean = make_truth()
    with pytest.raises(ValueError):
        evaluate.recall_at_fpr(score, truth, clean, fpr=1.5)
    with pytest.raises(ValueError, match="clean"):
        evaluate.recall_at_fpr(score, truth, np.zeros(106, dtype=bool), fpr=0.01)


def test_recall_works_on_matrices():
    score, truth, clean = make_truth()
    out = evaluate.recall_at_fpr(score.reshape(2, 53), truth.reshape(2, 53), clean.reshape(2, 53), 0.05)
    assert out["per_type"]["stuck_value"]["n_positive"] == 4


def test_detection_delay_counts_days_from_episode_start_and_nan_when_missed():
    episode = np.full((20, 2), -1)
    episode[3:9, 0] = 0            # episode 0: rows 3..8 at station 0
    episode[10:14, 1] = 1          # episode 1: rows 10..13 at station 1
    episode[15:18, 0] = 2          # episode 2: never flagged
    flag = np.zeros((20, 2), dtype=bool)
    flag[6, 0] = True              # delay 3
    flag[11, 1] = True             # delay 1
    flag[0, 0] = True              # a false flag outside any episode is ignored
    out = evaluate.detection_delay(flag, episode).set_index("episode_id")
    assert out.loc[0, "delay_days"] == 3 and out.loc[1, "delay_days"] == 1
    assert np.isnan(out.loc[2, "delay_days"]) and list(out["detected"]) == [True, True, False]


def test_detection_delay_can_count_only_flags_on_truth_days():
    episode = np.full((10, 1), -1)
    episode[2:8, 0] = 0
    flag = np.zeros((10, 1), dtype=bool)
    flag[3, 0] = flag[6, 0] = True
    truth = np.zeros((10, 1), dtype=bool)
    truth[5:8, 0] = True           # the first 3 window days were not changed by the fault
    assert evaluate.detection_delay(flag, episode)["delay_days"].iloc[0] == 1
    assert evaluate.detection_delay(flag, episode, truth_mask=truth)["delay_days"].iloc[0] == 4


def test_episode_types_come_from_the_changed_days():
    episode = np.array([[-1, 0], [0, 0], [0, 1], [2, 1]])
    fault = np.array([["", "spike"], ["", ""], ["", "zero_fault"], ["stuck_value", ""]], dtype=object)
    assert evaluate.episode_types(fault, episode).to_dict() == {0: "spike", 1: "zero_fault", 2: "stuck_value"}


def test_pr_auc_known_values():
    pos = np.array([True, True, False, False])
    neg = ~pos
    assert evaluate.pr_auc(np.array([0.9, 0.8, 0.2, 0.1]), pos, neg) == pytest.approx(1.0)
    # ranking desc: neg, neg, pos, pos -> precision 1/3 and 2/4 at the two recall steps
    assert evaluate.pr_auc(np.array([0.1, 0.2, 0.8, 0.9]), pos, neg) == pytest.approx((1 / 3 + 1 / 2) / 2)
    assert np.isnan(evaluate.pr_auc(np.array([1.0, 2.0]), np.array([False, False]), np.array([True, True])))


def test_pr_auc_ignores_other_days_and_ranks_nan_positives_last():
    score = np.array([0.9, np.nan, 0.5, 0.7, 5.0])
    pos = np.array([True, True, False, False, False])
    neg = np.array([False, False, True, True, False])   # the last day is neither positive nor clean
    # ranking: pos(0.9), neg(0.7), neg(0.5), pos(NaN -> last): precision 1/1 and 2/4
    assert evaluate.pr_auc(score, pos, neg) == pytest.approx((1.0 + 0.5) / 2)


# ------------------------------------------------------------------ genuine extremes

LAYOUT = {"IN_A": (20.0, 75.0, 10.0), "IN_B": (20.1, 75.0, 10.0), "IN_C": (20.2, 75.0, 10.0)}


def extreme_setup(n=2000):
    rng = np.random.default_rng(0)
    data = {k: np.where(rng.random(n) < 0.45, np.round(rng.gamma(1.0, 3.0, n) + 1.0, 1), 0.0) for k in LAYOUT}
    data["IN_A"][50] = 100.0   # corroborated: B=40, C=50
    data["IN_B"][50], data["IN_C"][50] = 40.0, 50.0
    data["IN_A"][80] = 100.0   # not corroborated: B=0, C=5 (< 30 mm)
    data["IN_B"][80], data["IN_C"][80] = 0.0, 5.0
    sset = synthetic_set(data, meta_rows=LAYOUT)
    return sset.values, neighbours.neighbour_table(sset.meta, k=5, max_km=150)


def test_genuine_extremes_need_the_percentile_and_two_corroborating_neighbours():
    values, table = extreme_setup()
    eligible = np.ones(values.shape, dtype=bool)
    ext = evaluate.genuine_extremes(values, eligible, table)
    assert ext.loc[values.index[50], "IN_A"] and not ext.loc[values.index[80], "IN_A"]
    assert ext.to_numpy().sum() > 1  # B and C have natural corroborated extremes too
    with_one_nb = evaluate.genuine_extremes(values, eligible, table, min_neighbours=3)
    assert not with_one_nb.to_numpy().any()  # only two neighbours exist


def test_extremes_exclude_ineligible_days():
    values, table = extreme_setup()
    eligible = np.ones(values.shape, dtype=bool)
    eligible[50, :] = False
    assert not evaluate.genuine_extremes(values, eligible, table).loc[values.index[50], "IN_A"]


def test_extreme_percentile_is_per_station_and_needs_enough_wet_days():
    values, table = extreme_setup()
    eligible = np.ones(values.shape, dtype=bool)
    assert not evaluate.genuine_extremes(values, eligible, table, min_wet_days=10_000).to_numpy().any()


def test_retention_counts_numerator_and_denominator():
    values, table = extreme_setup()
    eligible = np.ones(values.shape, dtype=bool)
    none = evaluate.genuine_extreme_retention(np.zeros(values.shape, dtype=bool), values, table, eligible)
    assert none["retention"] == 1.0 and none["numerator"] == none["denominator"] > 0 and none["n_flagged"] == 0
    flag = np.zeros(values.shape, dtype=bool)
    flag[50, 0] = True                       # flag the corroborated extreme at IN_A
    flag[80, 0] = True                       # flagging a non-extreme must not matter
    out = evaluate.genuine_extreme_retention(flag, values, table, eligible)
    assert out["denominator"] == none["denominator"] and out["numerator"] == none["numerator"] - 1
    assert out["retention"] == pytest.approx(out["numerator"] / out["denominator"]) and out["n_flagged"] == 1
    everything = evaluate.genuine_extreme_retention(np.ones(values.shape, dtype=bool), values, table, eligible)
    assert everything["retention"] == 0.0 and everything["denominator"] == none["denominator"]


def test_retention_is_nan_when_there_are_no_extremes():
    values, table = extreme_setup()
    out = evaluate.genuine_extreme_retention(np.zeros(values.shape, dtype=bool), values, table,
                                             np.zeros(values.shape, dtype=bool))
    assert out["denominator"] == 0 and np.isnan(out["retention"])


# ------------------------------------------------------------------ bootstrap

def test_bootstrap_ci_is_deterministic_and_brackets_the_estimate():
    rng = np.random.default_rng(0)
    stations = [rng.binomial(1, 0.7, 40).astype(float) for _ in range(12)]
    a = evaluate.bootstrap_ci(stations, seed=3)
    assert a == evaluate.bootstrap_ci(stations, seed=3)
    assert a != evaluate.bootstrap_ci(stations, seed=4)
    est = np.mean(np.concatenate(stations))
    assert a[0] <= est <= a[1] and a[1] - a[0] < 0.3


def test_bootstrap_resamples_stations_not_rows():
    # station 0 always detects, station 1 never: resampling stations gives wide intervals, and
    # would be ~0.5 +- tiny if the rows were (wrongly) resampled
    stations = [np.ones(500), np.zeros(500)]
    lo, hi = evaluate.bootstrap_ci(stations, seed=1, n_boot=400)
    assert lo == 0.0 and hi == 1.0


def test_bootstrap_skips_empty_stations_and_returns_nan_when_nothing_is_left():
    assert evaluate.bootstrap_ci([np.array([]), np.array([1.0, 1.0])], seed=1) == (1.0, 1.0)
    lo, hi = evaluate.bootstrap_ci([np.array([]), np.array([])], seed=1)
    assert np.isnan(lo) and np.isnan(hi)


def test_bootstrap_accepts_other_statistics():
    delays = [np.array([1.0, 2.0, 3.0]), np.array([10.0]), np.array([2.0, 2.0])]
    lo, hi = evaluate.bootstrap_ci(delays, statistic=np.median, seed=2)
    assert 1.0 <= lo <= hi <= 10.0


def test_per_station_hits_selects_masked_days_per_column():
    hit = np.array([[True, False], [True, True], [False, True]])
    mask = np.array([[True, True], [False, True], [True, False]])
    out = evaluate.per_station_hits(hit, mask)
    assert [list(x) for x in out] == [[1.0, 0.0], [0.0, 1.0]]


# ------------------------------------------------------------------ dataset pivot

def test_to_matrices_round_trips_the_fault_table():
    n = 365 * 3 + 2
    rng = np.random.default_rng(0)
    data = {f"IN{k:09d}": np.where(rng.random(n) < 0.5, np.round(rng.gamma(0.8, 9.0, n) + 1.0, 1), 0.0)
            for k in range(3)}
    sset = synthetic_set(data, flags={"IN000000000": {100: "K"}})
    ids = list(sset.meta["id"])
    table = inject.build_fault_dataset(sset, {"train": ids[:1], "val": ids[1:2], "test": ids[2:]}, seed=2)
    mats = evaluate.to_matrices(table)
    assert mats.stations == ids and mats.value_obs.shape == sset.values.shape
    np.testing.assert_array_equal(mats.value_true.to_numpy(), sset.values.to_numpy())
    changed = ~np.isclose(mats.value_true.to_numpy(), mats.value_obs.to_numpy(), equal_nan=True, rtol=0, atol=0)
    np.testing.assert_array_equal(changed, mats.fault_type != "")
    assert not mats.clean[mats.episode_id >= 0].any() and not mats.clean_real[100, 0]
    assert (mats.clean <= mats.clean_real).all() and mats.split_of[ids[1]] == "val"
    assert mats.real_flag.iloc[100, 0] == "K"
