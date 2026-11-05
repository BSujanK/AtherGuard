"""Held-out expanded report (verify.heldout): event sets, LHASA alignment, the rain-event series, the guards and the gate."""
import runpy
import sys
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from aetherguard import grid
from aetherguard.verify import heldout
from aetherguard.verify.baselines import realised_shares
from aetherguard.verify.report import Part, RainFit

A = int(grid.latlon_to_cell(30.025, 78.025))
NEXT = A + 1                  # 4.8 km east of A
FAR = A + 20                  # 96 km east of A


class SeriesStore:
    """An IMERG-like store of one UTC-day value per day for every pixel (NaN for a day it lacks)."""

    def __init__(self, series: dict[date, float]) -> None:
        self.series = series

    def gather(self, rows, cols, first_day, length) -> np.ndarray:
        out = np.full((np.asarray(rows).size, length), np.nan, dtype=np.float32)
        for k in range(length):
            if first_day + timedelta(days=k) in self.series:
                out[:, k] = self.series[first_day + timedelta(days=k)]
        return out


def plateau(first: date, mm: float = 8.0, wet_days: int = 3, span: int = 40) -> SeriesStore:
    """Zero rain with `mm` on `wet_days` UTC days from `first`."""
    start = first - timedelta(days=15)
    return SeriesStore({start + timedelta(days=k): (mm if 0 <= (start + timedelta(days=k) - first).days < wet_days else 0.0)
                        for k in range(span)})


# ---------------------------------------------------------------------------------------------------- guards

def test_cell_order_guard_accepts_the_same_order_and_rejects_any_other():
    heldout.check_cell_order(np.array([5, 3, 9]), np.array([5, 3, 9]), "season 2019")
    with pytest.raises(ValueError, match="season 2019.*order"):
        heldout.check_cell_order(np.array([3, 5, 9]), np.array([5, 3, 9]), "season 2019")
    with pytest.raises(ValueError, match="season 2019.*order"):
        heldout.check_cell_order(np.array([5, 3]), np.array([5, 3, 9]), "season 2019")


def test_days_below_half_counts_days_on_which_fewer_than_half_the_cells_are_scored():
    scored = np.array([[1, 1, 0, 0], [1, 0, 0, 1], [1, 1, 0, 1], [0, 0, 0, 1]], dtype=bool)
    assert heldout.days_below_half(scored) == 1       # day 2 scores none; day 1 scores exactly half and is not below


def test_gate_line_states_the_count_against_the_gate():
    short = heldout.gate_line(91)
    assert "91" in short and "150" in short and "NOT MET" in short and "59" in short
    met = heldout.gate_line(160)
    assert "MET" in met and "NOT MET" not in met and "160" in met


# -------------------------------------------------------------------------------------------------- the events

def positives(rows) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["cell_id", "event_date", "split"]).assign(event_date=lambda f: pd.to_datetime(f["event_date"]))


def test_held_out_events_hold_the_catalog_2018_the_reported_and_the_in_domain_sparse_events():
    catalog = pd.DataFrame({"cell_id": [A], "date": pd.to_datetime(["2018-08-02"])})
    reported = pd.DataFrame({"cell_id": [NEXT, FAR], "date": pd.to_datetime(["2019-08-08", "2021-07-01"]),
                             "location_text": ["x", "y"]})
    sparse = positives([(A, "2019-07-09", "test_sparse"),
                        (FAR, "2020-07-05", "test_sparse"),          # out of the slope domain
                        (A, "2018-08-02", "test_2018"),              # another split
                        (A, "2012-08-02", "train"),
                        (NEXT, "2026-07-01", "test_sparse")])        # not a held-out year
    events = heldout.held_out_events(catalog, reported, sparse, np.array([A, NEXT]))
    assert list(events.columns) == ["cell_id", "date", "source"]
    got = {(r.source, r.cell_id, r.date.date()) for r in events.itertuples()}
    assert got == {("catalog_2018", A, date(2018, 8, 2)), ("reported", NEXT, date(2019, 8, 8)),
                   ("reported", FAR, date(2021, 7, 1)), ("catalog_sparse", A, date(2019, 7, 9))}


def test_held_out_events_leave_a_reported_event_outside_the_held_out_years_out():
    reported = pd.DataFrame({"cell_id": [A], "date": pd.to_datetime(["2018-08-02"]), "location_text": ["x"]})
    events = heldout.held_out_events(pd.DataFrame({"cell_id": [], "date": pd.to_datetime([])}), reported,
                                     positives([]), np.array([A]))
    assert events.empty


def test_distinct_events_merge_neighbours_within_the_tolerance_in_space_and_time():
    events = pd.DataFrame({"cell_id": [A, NEXT, A, FAR, A], "date": pd.to_datetime(
        ["2019-08-08", "2019-08-09", "2019-08-20", "2019-08-08", "2019-08-08"])})
    assert heldout.distinct_events(events) == 3        # A with NEXT a day later and its repeat, A on the 20th, FAR
    assert heldout.distinct_events(events.iloc[:0]) == 0


def test_events_on_panel_days_are_kept_and_the_rest_counted_outside():
    days = [date(2019, 6, 1), date(2019, 6, 2), date(2020, 6, 1)]
    events = pd.DataFrame({"cell_id": [A, A, A, A], "date": pd.to_datetime(["2019-06-02", "2019-12-31", "2020-04-18", "2020-06-01"]),
                           "source": "reported"})
    kept, outside = heldout.events_on_days(events, days)
    assert kept["date"].dt.date.tolist() == [date(2019, 6, 2), date(2020, 6, 1)]
    assert outside == 2


# ----------------------------------------------------------------------------------------------- LHASA

def write_lhasa(path, cell_id, days, prob):
    np.savez(path, cell_id=np.asarray(cell_id, dtype=np.int64), days=np.array([d.isoformat() for d in days]),
             prob=np.asarray(prob, dtype=np.float32), fetched=np.ones(len(days), dtype=bool))


@pytest.fixture
def lhasa_file(tmp_path):
    days = [date(2018, 6, 1) + timedelta(days=k) for k in range(3)]
    path = tmp_path / "lhasa_2018.npz"
    # stored in another cell order than the panel: rows are cells 30, 10, 20
    write_lhasa(path, [30, 10, 20], days, [[0.3, 0.31, 0.32], [0.1, 0.11, 0.12], [0.2, 0.21, 0.22]])
    return path, days


def test_lhasa_is_aligned_by_cell_id_and_by_day(lhasa_file):
    path, days = lhasa_file
    prob = heldout.align_lhasa(path, np.array([10, 20, 30]), days, 0)
    assert prob.shape == (3, 3)
    assert prob == pytest.approx(np.array([[0.1, 0.11, 0.12], [0.2, 0.21, 0.22], [0.3, 0.31, 0.32]]), abs=1e-6)


def test_lhasa_day_shift_takes_the_granule_of_the_shifted_day(lhasa_file):
    path, days = lhasa_file
    ahead = heldout.align_lhasa(path, np.array([10, 20, 30]), days, 1)      # panel day d reads LHASA day d + 1
    assert ahead[0, :2] == pytest.approx([0.11, 0.12], abs=1e-6)
    assert np.isnan(ahead[:, 2]).all()
    behind = heldout.align_lhasa(path, np.array([10, 20, 30]), days, -1)
    assert np.isnan(behind[:, 0]).all()
    assert behind[1, 1:] == pytest.approx([0.2, 0.21], abs=1e-6)


def test_lhasa_panel_day_outside_the_file_is_nan_and_a_cell_it_lacks_is_an_error(lhasa_file):
    path, days = lhasa_file
    wider = [days[0] - timedelta(days=1), *days, days[-1] + timedelta(days=1)]
    prob = heldout.align_lhasa(path, np.array([10]), wider, 0)
    assert np.isnan(prob[0, [0, 4]]).all() and not np.isnan(prob[0, 1:4]).any()
    with pytest.raises(ValueError, match="cell"):
        heldout.align_lhasa(path, np.array([10, 99]), days, 0)


# ---------------------------------------------------------------------------------------- rain-event series

def test_event_series_follow_the_imd_day_rule_on_every_day_of_the_season():
    first = date(2019, 7, 12)
    store = plateau(first)                       # 8 mm on UTC days Jul 12-14: IMD days 1, 8, 8, 7 mm
    days = [date(2019, 7, 10) + timedelta(days=k) for k in range(8)]
    event, duration = heldout.ed_event_series(store, np.array([A, NEXT]), days[0], len(days), lookback=5)
    assert event.shape == duration.shape == (2, 8)
    assert event[0].tolist() == [0.0, 0.0, 1.0, 9.0, 17.0, 24.0, 0.0, 0.0]
    assert duration[0].tolist() == [0, 0, 1, 2, 3, 4, 0, 0]
    assert event[1].tolist() == event[0].tolist()


def test_event_series_run_that_began_before_the_look_back_is_unknown_not_short():
    store = SeriesStore({date(2019, 7, 1) + timedelta(days=k): (8.0 if k <= 13 else 0.0) for k in range(30)})
    event, duration = heldout.ed_event_series(store, np.array([A]), date(2019, 7, 10), 8, lookback=3)
    assert np.isnan(event[0, :6]).all() and np.isnan(duration[0, :6]).all()      # Jul 10-15: the run's start is not seen
    assert event[0, 6:].tolist() == [0.0, 0.0] and duration[0, 6:].tolist() == [0, 0]


def test_event_totals_of_events_read_the_event_ending_on_their_day():
    store = plateau(date(2019, 7, 12))
    cells = np.array([A, A, NEXT])
    dates = pd.to_datetime(["2019-07-15", "2019-07-20", "2019-07-14"])
    event, duration = heldout.ed_event_totals(store, cells, dates, lookback=5)
    assert event.tolist() == [24.0, 0.0, 17.0]
    assert duration.tolist() == [4, 0, 3]


# ---------------------------------------------------------------------------------------- the season models

def toy_part(seed: int = 5, cells: int = 60, n_days: int = 40) -> Part:
    rng = np.random.default_rng(seed)
    days = [date(2019, 6, 1) + timedelta(days=k) for k in range(n_days)]
    scored = rng.random((cells, n_days)) < 0.9
    acc_3 = rng.gamma(1.5, 10.0, (cells, n_days)).astype(np.float32)
    acc_3[rng.random((cells, n_days)) < 0.3] = 0.0
    v3 = np.zeros((cells, n_days), dtype=np.int8)
    v3[(acc_3 > 25) & scored] = 1
    v3[(acc_3 > 40) & scored] = 2
    v3[(acc_3 > 60) & scored] = 3
    return Part(cell_ids=np.arange(cells, dtype=np.int64) + 1000, in_universe=np.ones(cells, dtype=bool), days=days,
                scored=scored, acc_3=acc_3, static_score=rng.random(cells), v3=v3,
                events=pd.DataFrame({"cell_id": [], "date": []}))


def toy_models(part: Part, lhasa=None):
    rng = np.random.default_rng(9)
    duration = rng.integers(0, 6, part.scored.shape).astype(float)
    event = duration * rng.gamma(2.0, 6.0, part.scored.shape)
    fit = RainFit(part.acc_3[:30], part.scored[:30], (0.2, 0.1, 0.05))
    return heldout.season_models(part, event, duration, lhasa, fit, {"ed_threshold": (5.0, 0.8), "ed_threshold_refit": (3.0, 0.9)})


def test_season_models_hold_every_benchmark_to_the_realised_shares_of_v3():
    part = toy_part()
    levels, shares = toy_models(part)
    assert list(levels) == ["v3", "rain_3d", "rain_3d_devcuts", "susceptibility", "ed_threshold", "ed_threshold_refit"]
    v3_shares = realised_shares(part.v3, part.scored)
    assert shares["v3"] == {"target": None, "realised": list(v3_shares)}
    for name in ("rain_3d", "susceptibility", "ed_threshold", "ed_threshold_refit"):
        assert shares[name]["target"] == list(v3_shares)
        assert shares[name]["realised"] == pytest.approx(list(v3_shares), abs=0.01), name
    for name, array in levels.items():
        assert array.dtype == np.int8 and array.shape == part.v3.shape
        assert (array[~part.scored] == 0).all(), name


def test_season_models_keep_the_development_cuts_of_the_rain_baseline_at_their_own_target():
    part = toy_part()
    _, shares = toy_models(part)
    assert shares["rain_3d_devcuts"]["target"] == [0.2, 0.1, 0.05]


def test_season_models_add_the_three_lhasa_shifts_when_the_season_has_them():
    part = toy_part()
    rng = np.random.default_rng(1)
    lhasa = {shift: rng.random(part.scored.shape) for shift in (-1, 0, 1)}
    lhasa[0][:, :5] = np.nan
    levels, shares = toy_models(part, lhasa)
    assert [k for k in levels if k.startswith("lhasa")] == ["lhasa_v2_m1", "lhasa_v2", "lhasa_v2_p1"]
    assert (levels["lhasa_v2"][:, :5] == 0).all()                      # no granule, no alert
    v3_shares = realised_shares(part.v3, part.scored)
    assert shares["lhasa_v2_p1"]["realised"] == pytest.approx(list(v3_shares), abs=0.01)
    assert shares["lhasa_v2"]["realised"][0] < v3_shares[0]            # the NaN days cost it burden


# ------------------------------------------------------------------------------------------- the sets

def season_result(year: int, models: tuple[str, ...], day0: date, n_days: int = 3) -> heldout.SeasonResult:
    days = [day0 + timedelta(days=k) for k in range(n_days)]
    scored = np.ones((2, n_days), dtype=bool)
    return heldout.SeasonResult(year, days, scored, {m: np.full((2, n_days), i, dtype=np.int8) for i, m in enumerate(models)},
                                {m: {"target": None, "realised": [0.0, 0.0, 0.0]} for m in models})


def test_a_set_pools_the_chosen_seasons_over_days_and_keeps_the_models_all_of_them_have():
    results = [season_result(2018, ("v3", "lhasa_v2"), date(2018, 6, 1)),
               season_result(2019, ("v3",), date(2019, 6, 1)),
               season_result(2020, ("v3", "lhasa_v2"), date(2020, 6, 1))]
    levels, scored, days = heldout.pool_seasons(results, (2018, 2019))
    assert list(levels) == ["v3"] and levels["v3"].shape == (2, 6) and scored.shape == (2, 6)
    assert days == results[0].days + results[1].days
    levels, _, _ = heldout.pool_seasons(results, (2018, 2020))
    assert list(levels) == ["v3", "lhasa_v2"]
    with pytest.raises(ValueError, match="2021"):
        heldout.pool_seasons(results, (2018, 2021))


def test_ed_constants_convert_the_published_hourly_threshold_to_days():
    alpha, gamma = heldout.published_ed_threshold()
    assert gamma == 0.74
    assert alpha * 3.0**gamma == pytest.approx(5.3 * 72.0**0.74)         # three days are 72 hours


# ------------------------------------------------------------------------------------- measuring and output

def toy_season(year: int = 2018):
    part = toy_part()
    part.cell_ids = np.arange(len(part.cell_ids), dtype=np.int64) + A
    part.days = [date(year, 6, 1) + timedelta(days=k) for k in range(len(part.days))]
    levels, shares = toy_models(part)
    return part, heldout.SeasonResult(year, part.days, part.scored, levels, shares)


def toy_events(part: Part) -> pd.DataFrame:
    return pd.DataFrame({"cell_id": [A + 3, A + 4, A + 30, A + 5],
                         "date": pd.to_datetime(["2018-06-10", "2018-06-11", "2018-02-01", "2019-06-10"]),
                         "source": ["catalog_2018", "reported", "reported", "reported"]})   # the last is another year's


def test_measure_set_scores_every_model_on_the_events_inside_the_panel_days():
    part, result = toy_season()
    entry = heldout.measure_set("S2018", [result], toy_events(part), part.cell_ids, lambda m: None)
    assert entry["events"] == 2 and entry["events_outside_panel_days"] == 1
    assert entry["distinct_events"] == 1                       # A+3 and A+4 are 4.8 km and a day apart
    assert entry["events_by_source"] == {"catalog_2018": 1, "reported": 1}
    assert set(entry["models"]) == set(result.levels) == set(entry["shares"])
    assert entry["models"]["v3"]["tolerant"]["1"]["events"] == 2
    assert entry["shares"]["rain_3d"]["target"] == pytest.approx(entry["shares"]["v3"]["realised"])


def test_pooled_shares_weight_each_seasons_target_by_its_scored_cell_days():
    part, first = toy_season(2019)
    _, second = toy_season(2020)
    second.scored = second.scored[:, :20]
    second.levels = {k: v[:, :20] for k, v in second.levels.items()}
    first.shares["rain_3d"]["target"] = [0.4, 0.2, 0.1]
    second.shares["rain_3d"]["target"] = [0.1, 0.1, 0.0]
    levels, scored, _ = heldout.pool_seasons([first, second], (2019, 2020))
    shares = heldout.pooled_shares([first, second], (2019, 2020), levels, scored)
    w = first.scored.sum() / (first.scored.sum() + second.scored.sum())
    assert shares["rain_3d"]["target"] == pytest.approx([0.4 * w + 0.1 * (1 - w), 0.2 * w + 0.1 * (1 - w), 0.1 * w])
    assert shares["v3"]["target"] is None
    assert shares["v3"]["realised"] == pytest.approx(list(realised_shares(levels["v3"], scored)))


def test_markdown_states_the_gate_the_seasons_and_a_row_for_every_model():
    part, result = toy_season()
    events = toy_events(part)
    entry = heldout.measure_set("S2018", [result], events, part.cell_ids, lambda m: None)
    published = heldout.published_ed_threshold()
    result_json = {
        "protocol": {"ed_threshold": {
            "published": {"source": "Brunetti et al. 2021", "alpha_hours": 5.3, "gamma": 0.74, "alpha_days": published[0]},
            "refitted": {"alpha": 4.1, "gamma": 0.8, "events_used": 40, "events": 50}}},
        "seasons": {"2018": heldout.season_summary(part, result, events, False)},
        "sets": {"S2018": entry},
        "gate": {"line": heldout.gate_line(2), "distinct_events": 1},
    }
    text = heldout.markdown(result_json)
    assert "NOT MET" in text and "148 short" in text
    assert "| 2018 |" in text and "days below half" in text
    assert "relative" in text and "refitted" in text
    for model in result.levels:
        assert text.count(f"| {model} | tolerant | Warning+ |") == 1


def test_the_heldout_command_writes_the_report_to_the_chosen_folder(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(heldout, "write_heldout", lambda out, say=print: calls.append(out))
    monkeypatch.setattr(sys, "argv", ["aetherguard.verify", "heldout", "--out", str(tmp_path)])
    with pytest.raises(SystemExit) as stop:
        runpy.run_module("aetherguard.verify", run_name="__main__")
    assert stop.value.code == 0 and calls == [tmp_path]
