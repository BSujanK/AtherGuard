import numpy as np
import pandas as pd
import pytest

from aetherguard.integrity import checks

NAN = np.nan


def col(values):
    return np.asarray(values, dtype=np.float32)[:, None]


def flagged(mask):
    return list(np.flatnonzero(mask[:, 0]))


def test_bounds_boundaries_and_non_finite():
    v = col([0.0, 1500.0, 1500.1, -0.1, np.inf, -np.inf, NAN, 12.0])
    assert flagged(checks.bounds(v)) == [2, 3, 4, 5]  # 0 and 1500 are valid; NaN is a gap, not a bounds fault


def test_bounds_limits_are_configurable():
    assert flagged(checks.bounds(col([10.0, 600.0]), max_mm=500.0)) == [1]


@pytest.mark.parametrize("run,expected", [(2, []), (3, [1, 2, 3]), (4, [1, 2, 3, 4])])
def test_stuck_streak_length_boundaries(run, expected):
    v = col([0.0] + [5.0] * run + [1.0, 0.0])
    assert flagged(checks.stuck(v, min_run=3)) == expected


def test_stuck_noaa_k_needs_ten_identical_days():
    nine = col([5.0] * 9 + [1.0])
    ten = col([5.0] * 10 + [1.0])
    assert flagged(checks.stuck(nine, min_run=checks.NOAA_K_MIN_RUN)) == []
    assert flagged(checks.stuck(ten, min_run=checks.NOAA_K_MIN_RUN)) == list(range(10))


def test_stuck_ignores_zero_streaks_and_breaks_on_nan():
    zeros = col([0.0] * 30)
    assert flagged(checks.stuck(zeros, min_run=3)) == []
    broken = col([5.0, 5.0, NAN, 5.0, 5.0])
    assert flagged(checks.stuck(broken, min_run=3)) == []


def test_stuck_runs_are_found_independently_per_station():
    v = np.stack([np.array([4, 4, 4, 1, 2], np.float32), np.array([1, 2, 3, 4, 5], np.float32)], axis=1)
    out = checks.stuck(v, min_run=3)
    assert out[:, 0].tolist() == [True, True, True, False, False]
    assert not out[:, 1].any()


def _block_series(block_len, *, positive=True, overlap=False):
    src = [0.0, 3.0, 0.0, 7.5, 1.0, 0.0, 2.0, 4.0][:block_len]
    if not positive:
        src = [0.0] * block_len
    gap = [9.1, 0.3, 0.0, 6.0, 0.0, 2.2, 1.7, 0.6, 8.0, 0.0]
    return src, gap


@pytest.mark.parametrize("block_len,expect", [(6, False), (7, True)])
def test_duplicate_block_length_boundary(block_len, expect):
    src, gap = _block_series(block_len)
    # make the trailing days different from the block so only block_len days can match
    v = col(src + gap + src + [99.0])
    out = checks.duplicate_block(v, min_block=7)
    start = len(src) + len(gap)
    assert out[start:start + block_len, 0].all() == expect
    assert not out[:len(src), 0].any()  # the earlier copy is the source, not the fault


def test_duplicate_block_needs_enough_positive_days():
    src = [0.0] * 10
    v = col(src + [1.0, 2.0, 3.0] + src + [5.0])
    assert not checks.duplicate_block(v, min_block=7).any()
    # a dry block holding two trace values is common by chance: two positives do not count by default
    two = [0.0, 0.2, 0.0, 0.0, 0.3, 0.0, 0.0]
    v = col(two + [4.0, 3.0, 9.0] + two + [8.0])
    assert not checks.duplicate_block(v, min_block=7).any()
    assert checks.duplicate_block(v, min_block=7, min_positive=2).any()
    three = [0.0, 0.2, 0.0, 0.4, 0.3, 0.0, 0.0]
    v = col(three + [4.0, 3.0, 9.0] + three + [8.0])
    assert checks.duplicate_block(v, min_block=7).sum() == 7


def test_duplicate_block_ignores_blocks_with_missing_values():
    src = [1.0, NAN, 3.0, 2.0, 1.0, 4.0, 5.0]
    v = col(src + [9.0, 8.0] + src)
    assert not checks.duplicate_block(v, min_block=7).any()


def test_duplicate_block_flags_the_whole_longer_copy_and_no_overlap_pairs():
    block = [1.0, 2.5, 0.0, 4.0, 3.0, 0.2, 6.0, 7.0, 1.1, 0.0, 2.0, 5.0]
    v = col(block + [9.9, 8.8, 7.7] + block)
    out = checks.duplicate_block(v, min_block=7)
    second = slice(len(block) + 3, len(block) * 2 + 3)
    assert out[second, 0].all() and out[:len(block), 0].sum() == 0
    # a constant run overlaps itself but is not a *block* repeated at an earlier location
    assert not checks.duplicate_block(col([2.0] * 13 + [1.0]), min_block=7).any()


def test_gap_marks_nan_runs_with_their_length():
    v = col([1.0, NAN, NAN, NAN, 2.0, NAN, 3.0])
    assert flagged(checks.gap(v)) == [1, 2, 3, 5]
    assert checks.gap_run_length(v)[:, 0].tolist() == [0, 3, 3, 3, 0, 1, 0]


def test_dataframe_in_dataframe_out_and_array_in_array_out():
    frame = pd.DataFrame({"a": [0, 5, 5, 5, 1.0], "b": [1, 2, 3, 4, 5.0]},
                         index=pd.date_range("2000-01-01", periods=5), dtype=np.float32)
    out = checks.stuck(frame, min_run=3)
    assert isinstance(out, pd.DataFrame) and out.index.equals(frame.index)
    assert out["a"].tolist() == [False, True, True, True, False]
    assert isinstance(checks.stuck(frame.to_numpy(), min_run=3), np.ndarray)


def test_run_l1_long_table_reasons_and_combined_flag():
    src = [0.0, 3.0, 0.0, 7.5, 1.0, 0.0, 2.0]
    values = np.array(src + [9.1, 0.3, 0.0] + src + [5, 5, 5, 4, 2000.0, -1.0, NAN, NAN, 1.0], np.float32)
    frame = pd.DataFrame({"IN_A": values}, index=pd.date_range("2001-01-01", periods=len(values)))
    out = checks.run_l1(frame)
    assert list(out.columns) == ["station", "date", "bounds", "stuck", "stuck_k10", "duplicate_block",
                                 "gap", "gap_run_length", "l1_flag"]
    assert len(out) == len(values) and (out["station"] == "IN_A").all()
    row = out.set_index("date")
    d = frame.index
    assert row.loc[d[12], "duplicate_block"] and row.loc[d[12], "l1_flag"]
    assert row.loc[d[18], "stuck"] and not row.loc[d[18], "stuck_k10"]
    assert row.loc[d[21], "bounds"] and row.loc[d[22], "bounds"]
    assert row.loc[d[23], "gap"] and row.loc[d[23], "gap_run_length"] == 2
    assert not row.loc[d[23], "l1_flag"]  # a gap is reported, but it is a missing reading, not a bad one
    assert not row.loc[d[0], "l1_flag"]


def test_l1_config_thresholds_documented_in_one_place():
    cfg = checks.L1Config()
    assert (cfg.max_mm, cfg.stuck_min_run, cfg.dup_min_block, cfg.dup_min_positive) == (
        1500.0, checks.STUCK_MIN_RUN, 7, 3)
    assert checks.NOAA_K_MIN_RUN == 10
