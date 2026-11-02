from datetime import date

import numpy as np
import pandas as pd
import pytest

from aetherguard import grid
from aetherguard.verify.matching import CELL_EXACT, Tolerance, match, rows_within

EVENT_30N = grid.latlon_to_cell(30.025, 78.025)
EVENT_8N = grid.latlon_to_cell(8.025, 77.025)
DAYS = [date(2018, 7, 1), date(2018, 7, 2), date(2018, 7, 3)]


def east(cell: int, k: int) -> int:
    return cell + k


def _block(centre: int) -> list[int]:
    return [centre + di * grid.ID_STRIDE + dj for di in range(-3, 4) for dj in range(-3, 4)]


CELLS = np.array(sorted(_block(EVENT_30N) + _block(EVENT_8N)), dtype=np.int64)
ZERO_LEVELS = np.zeros((len(CELLS), len(DAYS)), dtype=np.int8)


def row(cell: int) -> int:
    return int(np.flatnonzero(CELLS == cell)[0])


def levels_with(cell: int, day: int, level: int) -> np.ndarray:
    out = ZERO_LEVELS.copy()
    out[row(cell), day] = level
    return out


def one_event(cell: int, day: int) -> pd.DataFrame:
    return pd.DataFrame({"cell_id": [cell], "date": [DAYS[day]]})


def events_on(dates: list[str]) -> pd.DataFrame:
    return pd.DataFrame({"cell_id": [EVENT_30N] * len(dates), "date": pd.to_datetime(dates).date})


def test_an_alert_two_cells_east_and_one_day_later_detects_the_event():  # 9.6 km at 30N
    m = match(levels_with(east(EVENT_30N, 2), 2, 2), CELLS, DAYS, one_event(EVENT_30N, 1), Tolerance())
    assert m.event_level.tolist() == [2]


def test_three_cells_east_is_beyond_10_km():  # 14.4 km
    m = match(levels_with(east(EVENT_30N, 3), 1, 3), CELLS, DAYS, one_event(EVENT_30N, 1), Tolerance())
    assert m.event_level.tolist() == [0]


def test_two_cells_east_at_8n_is_beyond_10_km():  # 11.0 km: distance, not cell count
    m = match(levels_with(east(EVENT_8N, 2), 1, 2), CELLS, DAYS, one_event(EVENT_8N, 1), Tolerance())
    assert m.event_level.tolist() == [0]


def test_an_event_outside_the_panel_cells_is_matched_by_distance():
    outside = east(EVENT_30N, 4)
    assert outside not in CELLS
    m = match(levels_with(east(EVENT_30N, 3), 1, 1), CELLS, DAYS, one_event(outside, 1), Tolerance())
    assert m.event_level.tolist() == [1]


def test_events_outside_the_days_are_counted_not_missed():
    m = match(ZERO_LEVELS, CELLS, DAYS, events_on(["2018-06-20", "2018-07-02"]), Tolerance())
    assert m.outside_window == 1 and len(m.events) == 1


def test_duplicate_records_are_one_event():
    m = match(ZERO_LEVELS, CELLS, DAYS, pd.concat([one_event(EVENT_30N, 1)] * 3), Tolerance())
    assert len(m.events) == 1


def test_alert_verified_marks_cell_days_within_tolerance_only():
    m = match(ZERO_LEVELS, CELLS, DAYS, one_event(EVENT_30N, 1), Tolerance())
    assert m.alert_verified[row(EVENT_30N), :].tolist() == [True, True, True]
    assert not m.alert_verified[row(east(EVENT_30N, 3)), :].any()


def test_cell_exact_needs_the_same_cell_and_day():
    m = match(levels_with(east(EVENT_30N, 1), 1, 3), CELLS, DAYS, one_event(EVENT_30N, 1), CELL_EXACT)
    assert m.event_level.tolist() == [0]


def test_tolerance_rejects_negative_values():
    with pytest.raises(ValueError):
        Tolerance(km=-1)
    with pytest.raises(ValueError):
        Tolerance(days=-1)


def test_an_event_with_no_panel_cell_within_the_distance_is_unscored():
    far = grid.latlon_to_cell(45.025, 78.025)
    m = match(ZERO_LEVELS, CELLS, DAYS, one_event(far, 1), Tolerance())
    assert m.event_level.tolist() == [-1]


def test_an_event_the_day_before_the_panel_is_outside_the_window_but_still_verifies_the_alert():
    m = match(levels_with(EVENT_30N, 0, 2), CELLS, DAYS, events_on(["2018-06-30"]), Tolerance())
    assert m.outside_window == 1 and len(m.events) == 0 and m.event_level.tolist() == []
    assert m.alert_verified[row(EVENT_30N), :].tolist() == [True, False, False]
    assert m.alert_verified[row(east(EVENT_30N, 2)), 0]


def test_an_alert_two_days_from_the_event_is_not_a_match():
    m = match(levels_with(EVENT_30N, 2, 3), CELLS, DAYS, one_event(EVENT_30N, 0), Tolerance())
    assert m.event_level.tolist() == [0]


def test_cell_exact_detects_the_same_cell_and_day():
    m = match(levels_with(EVENT_30N, 1, 3), CELLS, DAYS, one_event(EVENT_30N, 1), CELL_EXACT)
    assert m.event_level.tolist() == [3]
    assert m.alert_verified.sum() == 1


def test_levels_must_be_integers():
    with pytest.raises(ValueError, match="integer"):
        match(ZERO_LEVELS.astype(float), CELLS, DAYS, one_event(EVENT_30N, 1), Tolerance())


def test_rows_within_includes_the_own_cell_and_orders_rows_ascending():
    (rows,) = rows_within(np.array([EVENT_30N]), CELLS, 10.0)
    assert row(EVENT_30N) in rows and rows.tolist() == sorted(rows.tolist())
    assert row(east(EVENT_30N, 2)) in rows and row(east(EVENT_30N, 3)) not in rows


def test_rows_within_zero_km_is_the_own_cell_only():
    (rows,) = rows_within(np.array([EVENT_30N]), CELLS, 0.0)
    assert rows.tolist() == [row(EVENT_30N)]


def test_rows_within_wraps_across_the_antimeridian():
    west = grid.latlon_to_cell(0.025, -179.975)
    east_edge = grid.latlon_to_cell(0.025, 179.975)
    (rows,) = rows_within(np.array([west]), np.array([east_edge]), 10.0)
    assert rows.tolist() == [0]
