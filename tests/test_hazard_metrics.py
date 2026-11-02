import math

import numpy as np
import pytest
from sklearn.metrics import average_precision_score

from aetherguard.hazard import metrics as m

POS = [0.9, 0.8, 0.7, 0.4]
NEG = [0.85, 0.6, 0.5, 0.3, 0.2]
W = [1, 1, 2, 2, 4]


def test_fa_share_at_recall_known_answers():
    assert m.fa_share_at_recall(POS, NEG, W, 0.5) == pytest.approx(0.1)
    assert m.fa_share_at_recall(POS, NEG, W, 0.75) == pytest.approx(0.1)
    assert m.fa_share_at_recall(POS, NEG, W, 1.0) == pytest.approx(0.4)
    assert m.fa_share_at_recall(POS, NEG, W, 0.25) == pytest.approx(0.0)


def test_thresholds_and_recall_at_fa_share_known_answers():
    assert m.threshold_for_recall(POS, 0.75) == 0.7
    assert m.threshold_for_fa_share(NEG, W, 0.4) == 0.5
    assert m.threshold_for_fa_share(NEG, W, 0.05) == math.inf
    assert m.recall_at_fa_share(POS, NEG, W, 0.1) == pytest.approx(0.25)
    assert m.recall_at_fa_share(POS, NEG, W, 0.4) == pytest.approx(0.75)
    assert m.recall_at_fa_share(POS, NEG, W, 0.05) == 0.0
    assert m.recall_at_fa_share(POS, NEG, W, 1.0) == 1.0


def test_threshold_application_helpers():
    assert m.recall_at_threshold(POS, 0.7) == 0.75
    assert m.fa_share_at_threshold(NEG, W, 0.5) == pytest.approx(0.4)


def test_weighted_pr_auc_known_answer():
    expected = (1 + 2 / 3 + 3 / 4 + 4 / 8) / 4
    assert m.weighted_pr_auc(POS, NEG, W) == pytest.approx(expected)


def test_weighted_pr_auc_matches_sklearn_with_ties():
    rng = np.random.default_rng(3)
    pos = np.round(rng.normal(1, 1, 60), 1)
    neg = np.round(rng.normal(0, 1, 500), 1)
    weights = rng.integers(1, 9, 500).astype(float)
    y = np.r_[np.ones(60), np.zeros(500)]
    expected = average_precision_score(y, np.r_[pos, neg], sample_weight=np.r_[np.ones(60), weights])
    assert m.weighted_pr_auc(pos, neg, weights) == pytest.approx(expected)


def test_ties_alert_together():
    assert m.fa_share_at_recall([0.5, 0.5], [0.5, 0.1], [1, 1], 1.0) == pytest.approx(0.5)
    assert m.recall_at_fa_share([0.5, 0.2], [0.5, 0.5, 0.1], [1, 1, 2], 0.3) == 0.0


def test_minus_infinity_never_alerts_but_is_reachable_at_full_recall():
    assert m.fa_share_at_recall([-math.inf, 1.0], [-math.inf, 0.0], [1, 1], 1.0) == 1.0
    assert m.fa_share_at_recall([-math.inf, 1.0], [-math.inf, 0.0], [1, 1], 0.5) == 0.0


def test_nan_scores_are_rejected():
    with pytest.raises(ValueError, match="NaN"):
        m.fa_share_at_recall([0.5, np.nan], NEG, W, 0.5)


def test_bad_inputs_are_rejected():
    with pytest.raises(ValueError):
        m.ScoreSet([], NEG, W)
    with pytest.raises(ValueError):
        m.ScoreSet(POS, NEG, [1, 1, 1, 1, 0])
    with pytest.raises(ValueError):
        m.fa_share_at_recall(POS, NEG, W, 0.0)


def _toy(seed=0, n_pos=80, n_neg=4000):
    rng = np.random.default_rng(seed)
    pos = rng.normal(1.5, 1, n_pos)
    neg = rng.normal(0, 1, n_neg)
    strata = np.where(np.arange(n_neg) < n_neg // 2, "a", "b")
    weights = np.where(strata == "a", 50.0, 20.0)
    return pos, neg, weights, strata


def test_bootstrap_is_deterministic_and_seed_dependent():
    pos, neg, weights, strata = _toy()
    sets = {"s": m.ScoreSet(pos, neg, weights)}
    kwargs = dict(recalls=[0.9], fa_shares=[0.05], n_boot=40)
    a = m.bootstrap_metrics(sets, weights, strata, seed=5, **kwargs)
    b = m.bootstrap_metrics(sets, weights, strata, seed=5, **kwargs)
    c = m.bootstrap_metrics(sets, weights, strata, seed=6, **kwargs)
    for key in a["s"]:
        np.testing.assert_array_equal(a["s"][key], b["s"][key])
    assert not np.array_equal(a["s"]["fa_at_recall_0.9"], c["s"]["fa_at_recall_0.9"])


def test_bootstrap_interval_covers_the_point_estimate_and_is_paired():
    pos, neg, weights, strata = _toy(1)
    good = m.ScoreSet(pos, neg, weights)
    bad = m.ScoreSet(pos * 0.0, np.random.default_rng(9).normal(0, 1, len(neg)), weights)
    boot = m.bootstrap_metrics({"good": good, "bad": bad}, weights, strata, recalls=[0.9], fa_shares=[0.05],
                               n_boot=200, seed=1)
    point = good.point([0.9], [0.05])
    lo, hi = m.confidence_interval(boot["good"]["fa_at_recall_0.9"])
    assert lo <= point["fa_at_recall_0.9"] <= hi
    diff = m.paired_difference(boot["good"]["fa_at_recall_0.9"], boot["bad"]["fa_at_recall_0.9"],
                               point["fa_at_recall_0.9"], bad.point([0.9], [])["fa_at_recall_0.9"])
    assert diff["value"] > 0 and diff["lo"] > 0 and diff["share_a_better"] > 0.95
    assert m.verdict(diff["lo"], diff["hi"]) == "a_better"
    same = m.paired_difference(boot["good"]["pr_auc"], boot["good"]["pr_auc"], 0.5, 0.5)
    assert (same["lo"], same["hi"], same["value"]) == (0.0, 0.0, 0.0)
    assert m.verdict(same["lo"], same["hi"]) == "tie"
    assert m.verdict(-0.3, -0.1) == "b_better"


def test_bootstrap_fixed_thresholds():
    pos, neg, weights, strata = _toy(2)
    scoring = m.ScoreSet(pos, neg, weights)
    thr = {"s": {"val90": 0.5}}
    boot = m.bootstrap_metrics({"s": scoring}, weights, strata, recalls=[], fa_shares=[], n_boot=300, seed=2,
                               fixed_thresholds=thr)
    assert abs(boot["s"]["fixed_recall_val90"].mean() - np.mean(pos >= 0.5)) < 0.03
    assert abs(boot["s"]["fixed_fa_val90"].mean() - scoring.fa_at(0.5)) < 0.01


def test_bootstrap_rejects_unequal_weights_in_a_stratum():
    pos, neg, weights, strata = _toy()
    weights = weights.copy()
    weights[0] = 999.0
    with pytest.raises(ValueError, match="constant within a stratum"):
        m.bootstrap_metrics({"s": m.ScoreSet(pos, neg, weights)}, weights, strata, recalls=[0.9], fa_shares=[],
                            n_boot=2, seed=0)


def test_bootstrap_rejects_mismatched_scorings():
    pos, neg, weights, strata = _toy()
    with pytest.raises(ValueError, match="same rows"):
        m.bootstrap_metrics({"a": m.ScoreSet(pos, neg, weights), "b": m.ScoreSet(pos[:-1], neg, weights)},
                            weights, strata, recalls=[0.9], fa_shares=[], n_boot=2, seed=0)


def test_recall_first_threshold_is_more_conservative_than_plain_recall():
    rng = np.random.default_rng(0)
    pos = rng.normal(1.0, 1.0, 120)
    plain = m.threshold_for_recall(pos, 0.9)
    first = m.recall_first_threshold(pos, 0.9, n_boot=500, seed=1)
    assert first < plain
    boot = rng.multinomial(120, np.full(120, 1 / 120), 2000)
    ordered = np.sort(pos)[::-1]
    recalls = (np.cumsum(boot, axis=1) / 120)[:, int(np.sum(ordered >= first)) - 1]
    assert np.percentile(recalls, 5) >= 0.88      # a fresh bootstrap agrees up to Monte Carlo error


def test_recall_first_threshold_is_the_highest_qualifying_score_and_deterministic():
    pos = np.arange(1.0, 101.0)
    a = m.recall_first_threshold(pos, 0.9, 400, 3)
    assert a == m.recall_first_threshold(pos, 0.9, 400, 3)
    assert a in pos and m.recall_first_threshold(pos, 0.9, 400, 3, percentile=50.0) >= a
    assert m.recall_first_threshold(pos, 1.0, 100, 1) == 1.0
    assert m.recall_first_threshold([0.5], 0.9, 50, 1) == 0.5


def test_recall_first_threshold_keeps_tied_positives_together():
    pos = np.r_[np.full(50, 0.7), np.full(50, 0.2)]
    assert m.recall_first_threshold(pos, 0.9, 300, 1) == 0.2
    assert m.recall_first_threshold(pos, 0.4, 300, 1) == 0.7


def test_recall_first_threshold_rejects_bad_input():
    with pytest.raises(ValueError):
        m.recall_first_threshold([], 0.9, 10, 1)
    with pytest.raises(ValueError):
        m.recall_first_threshold([1.0], 0.0, 10, 1)
    with pytest.raises(ValueError, match="NaN"):
        m.recall_first_threshold([1.0, np.nan], 0.9, 10, 1)


def test_bootstrap_se_is_the_sample_standard_deviation():
    assert m.bootstrap_se([1.0, 2.0, 3.0]) == pytest.approx(1.0)
