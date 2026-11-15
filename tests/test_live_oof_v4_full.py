"""The windows of the full-cell, year-round development panels (live.oof_v4_full)."""
from datetime import date

import pytest

from aetherguard.live import oof_v4_full as F


def test_the_june_december_window_has_the_backtest_warm_up_and_ends_on_new_years_eve():
    days, first = F.window_days(2010, "jun_dec")
    assert days[first] == date(2010, 6, 1) and first == 7 and days[0] == date(2010, 5, 25)
    assert days[-1] == date(2010, 12, 31) and len(days) == 221


def test_the_january_may_window_starts_cold_on_new_years_day():
    days, first = F.window_days(2012, "jan_may")
    assert first == 0 and days[0] == date(2012, 1, 1) and days[-1] == date(2012, 5, 31) and len(days) == 152


def test_scoring_refuses_held_out_years(tmp_path):
    with pytest.raises(ValueError):
        F.score([2018], "jun_dec", {}, tmp_path, print)
