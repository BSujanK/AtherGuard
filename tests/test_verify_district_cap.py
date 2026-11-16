"""The district frequency cap (verify.district_cap) on tiny synthetic inputs."""
import numpy as np
import pytest

from aetherguard.alerts import frequency_levels as FL
from aetherguard.verify import district_cap as C


def test_district_counts_sum_the_scored_cells_at_each_level():
    levels = np.array([[3, 0], [1, 2], [0, 0], [2, 2]], dtype=np.int8)       # 4 cells x 2 days
    scored = np.array([[True, True], [True, True], [True, False], [True, True]])
    index = np.array([0, 0, 0, 1])
    count, n = C.district_counts(levels, scored, index, 2)
    assert n.tolist() == [[3, 2], [1, 1]]
    assert count[0, 0].tolist() == [2, 1, 1] and count[0, 1].tolist() == [1, 1, 0]
    assert count[1, 0].tolist() == [1, 1, 0]


def test_a_cell_without_a_district_is_left_out():
    count, n = C.district_counts(np.array([[3]], dtype=np.int8), np.array([[True]]), np.array([-1]), 1)
    assert n.tolist() == [[0]] and count.sum() == 0


def test_the_share_threshold_needs_at_least_one_cell_and_meets_the_cap():
    shares = np.array([0.0] * 90 + [0.1] * 5 + [0.5] * 5)
    t = C.share_threshold(shares, 0.05)
    assert (shares >= t).sum() <= 5 and t > 0.1
    assert C.share_threshold(shares, 0.5) == C.MIN_SHARE                  # every alerted day fits: any cell
    assert (shares >= C.MIN_SHARE).sum() == 10


def test_the_district_level_is_the_highest_level_whose_share_is_met():
    f = np.array([[[0.6, 0.2, 0.05]], [[0.1, 0.1, 0.1]]])                  # 2 districts x 1 day x 3 levels
    s = np.array([0.5, 0.3, 0.15])
    assert C.district_level(f, s).tolist() == [[1], [0]]
    assert C.district_level(f, np.broadcast_to(s, (2, 1, 3))).tolist() == [[1], [0]]
    assert C.district_level(f, np.array([0.5, 0.3, 0.04])).tolist() == [[3], [3]]


def test_coverage_reads_the_event_day_and_one_day_either_side():
    alerted = np.array([[False, True, False, False]])
    same, near = C.coverage(alerted, np.array([0, 0]), np.array([0, 3]))
    assert same.tolist() == [False, False] and near.tolist() == [True, False]
    same, near = C.coverage(alerted, np.array([0, -1]), np.array([1, 1]))
    assert same.tolist() == [True, False] and near.tolist() == [True, False]


def test_leave_one_year_out_thresholds_never_see_their_own_year():
    years = {2010: np.full(100, 0.9), 2011: np.zeros(100), 2012: np.zeros(100)}
    out = C.loyo_thresholds(years, 0.1)
    assert out[2010] == C.MIN_SHARE                                        # the other years never alert
    assert out[2011] > 0.9                                                  # 2010's 0.9s exceed a 10% cap


def test_the_criterion_holds_the_rule_to_the_burden_and_the_coverage_loss_declared():
    declared = {"burden": {"himalaya|monsoon|3": 0.02}, "burden_factor": 1.5,
                "loss": {"within_1_day|3": {"share": 0.1, "margin_slides": 5.0}}}
    look = {"burden": {"himalaya|monsoon|3": 0.029},
            "coverage": {"within_1_day|3": {"hits": 60, "of": 87}}, "base_coverage": {"within_1_day|3": {"hits": 73, "of": 87}}}
    assert C.decide(declared, look)["confirmed"]                            # 13 lost <= 8.7 + 5
    look["burden"]["himalaya|monsoon|3"] = 0.031
    assert not C.decide(declared, look)["confirmed"]


def test_the_ladder_has_one_cap_per_step_for_every_level():
    assert set(C.LADDERS) == {1, 2, 3} and len({len(v) for v in C.LADDERS.values()}) == 1
    assert all(list(v) == sorted(v, reverse=True) for v in C.LADDERS.values())
    assert FL.SEASON_NAMES == ("monsoon", "post_monsoon", "rest")


def test_the_within_one_day_mask_spreads_each_alert_to_its_neighbouring_days():
    alerted = np.array([[False, False, True, False, False]])
    assert C.within_1_day(alerted).tolist() == [[False, True, True, True, False]]
