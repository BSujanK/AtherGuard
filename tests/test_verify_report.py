from datetime import date

import numpy as np
import pandas as pd
import pytest

from aetherguard import grid
from aetherguard.verify.baselines import realised_shares, susceptibility_baseline
from aetherguard.verify.matching import CELL_EXACT, Tolerance
from aetherguard.verify.report import model_table, susceptibility_levels

A = grid.latlon_to_cell(30.025, 78.025)
C = A + 1  # 4.8 km east of A
B = A + 5  # 24 km east of A
CELLS = np.array([A, C, B], dtype=np.int64)
DAYS = [date(2018, 7, 1), date(2018, 7, 2), date(2018, 7, 3)]
EVENTS = pd.DataFrame({"cell_id": [A], "date": [DAYS[1]]})
TOLERANCES = {"tolerant": Tolerance(10.0, 1), "cell_exact": CELL_EXACT}
SCORED = np.ones((3, 3), dtype=bool)
LEVELS_A = np.array([[0, 2, 0], [0, 0, 3], [2, 0, 0]], dtype=np.int8)
LEVELS_B = np.array([[0, 0, 0], [0, 0, 0], [0, 0, 1]], dtype=np.int8)


def table(**kwargs) -> dict:
    return model_table({"a": LEVELS_A, "b": LEVELS_B}, SCORED, CELLS, DAYS, EVENTS, TOLERANCES, **kwargs)


def test_both_tolerances_and_all_levels_exist_for_each_model():
    t = table()
    for model in ("a", "b"):
        assert set(t[model]) == {"tolerant", "cell_exact"}
        for tolerance in t[model]:
            assert set(t[model][tolerance]) == {"1", "2", "3"}


def test_tolerant_precision_counts_alerts_within_tolerance_of_the_event():
    t = table()
    assert t["a"]["tolerant"]["2"]["precision"] == pytest.approx(2 / 3)  # A d1 and C d2 verified, B d0 not
    assert t["a"]["tolerant"]["3"]["precision"] == pytest.approx(1.0)
    assert t["a"]["tolerant"]["2"]["pod"] == pytest.approx(1.0)


def test_cell_exact_precision_counts_only_the_event_cell_day():
    t = table()
    assert t["a"]["cell_exact"]["2"]["precision"] == pytest.approx(1 / 3)
    assert t["a"]["cell_exact"]["2"]["hits"] == 1
    assert t["a"]["cell_exact"]["3"]["hits"] == 0


def test_a_model_without_alerts_has_undefined_precision_and_no_detection():
    t = table()
    assert t["b"]["tolerant"]["1"]["precision"] == pytest.approx(0.0)
    assert t["b"]["tolerant"]["1"]["pod"] == pytest.approx(0.0)
    assert np.isnan(t["b"]["tolerant"]["2"]["precision"])


def test_scores_carry_their_bootstrap_intervals():
    scores = table()["a"]["tolerant"]["2"]
    assert {"pod_ci", "precision_ci", "alert_cell_days_ci"} <= set(scores)


def test_universe_restricts_alerts_and_precision_but_not_detection():
    t = table(universe=np.array([True, False, True]))  # C is not in the universe sample
    scores = t["a"]["tolerant"]["2"]
    assert scores["alert_cell_days"] == 2  # A d1 and B d0
    assert scores["precision"] == pytest.approx(1 / 2)
    assert scores["alert_share"] == pytest.approx(2 / 6)
    assert scores["pod"] == pytest.approx(1.0)  # the event is detected from C's alert, which is outside the universe


def test_universe_must_match_the_cells():
    with pytest.raises(ValueError, match="universe"):
        table(universe=np.array([True, False]))


def test_susceptibility_levels_without_a_universe_is_the_plain_baseline():
    static = np.array([3.0, 1.0, 2.0])
    scored = np.ones((3, 2), dtype=bool)
    expected = susceptibility_baseline(static, 2, scored, (0.5, 0.5, 0.0))
    assert np.array_equal(susceptibility_levels(static, 2, scored, (0.5, 0.5, 0.0)), expected)


def test_susceptibility_levels_ranks_among_the_universe_and_extends_to_the_other_cells():
    static = np.array([3.0, 1.0, 4.0])  # the third cell is outside the universe sample
    scored = np.ones((3, 2), dtype=bool)
    universe = np.array([True, True, False])
    levels = susceptibility_levels(static, 2, scored, (0.5, 0.5, 0.0), universe)
    assert levels[:, 0].tolist() == [2, 0, 2]
    assert levels[:, 1].tolist() == [2, 0, 2]
    assert realised_shares(levels[universe], scored[universe]) == pytest.approx((0.5, 0.5, 0.0))
