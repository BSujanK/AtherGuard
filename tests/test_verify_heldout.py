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


def test_gate_line_states_records_and_independent_slides_against_the_gate():
    short = heldout.gate_line(92, 87)
    assert short.startswith("Held-out events: 92 records of 87 independent slides against the 150-event gate: NOT MET")
    assert "63 short" in short
    met = heldout.gate_line(170, 160)
    assert "MET, 10 over" in met and "NOT MET" not in met


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


def test_events_of_one_slide_in_neighbouring_cells_or_two_sources_form_one_cluster():
    events = pd.DataFrame({"cell_id": [A, NEXT, A, FAR, A], "date": pd.to_datetime(
        ["2019-08-08", "2019-08-09", "2019-08-08", "2019-08-08", "2019-08-20"])})
    labels = heldout.event_clusters(events)
    assert labels[0] == labels[1] == labels[2]          # the same cell and day twice, and the cell next to it a day later
    assert len({labels[0], labels[3], labels[4]}) == 3  # 96 km away, and twelve days later
    assert heldout.event_clusters(events.iloc[:0]).tolist() == []


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
    assert entry["models"]["v3"]["tolerant"]["1"]["groups"] == 1               # one slide, in two neighbouring cells
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


def lhasa_levels(part: Part):
    rng = np.random.default_rng(1)
    return toy_models(part, {shift: rng.random(part.scored.shape) for shift in (-1, 0, 1)})


def markdown_inputs():
    part, _ = toy_season()
    levels, shares = lhasa_levels(part)
    result = heldout.SeasonResult(2018, part.days, part.scored, levels, shares)
    events = toy_events(part)
    entry = heldout.measure_set("S2018", [result], events, part.cell_ids, lambda m: None)
    published = heldout.published_ed_threshold()
    result_json = {
        "protocol": {"sources": heldout.SOURCES, "ed_threshold": {
            "published": {"source": "Brunetti et al. 2021", "alpha_hours": 5.3, "gamma": 0.74, "alpha_days": published[0]},
            "refitted": {"alpha": 4.1, "gamma": 0.8, "events_used": 40, "events": 50}}},
        "seasons": {"2018": heldout.season_summary(part, result, events, True)},
        "sets": {"S2018": entry},
        "gate": {"line": heldout.gate_line(5, 4), "distinct_events": 4},
    }
    return result, entry, result_json


def test_markdown_states_the_gate_the_seasons_and_a_row_for_every_model():
    result, entry, result_json = markdown_inputs()
    text = heldout.markdown(result_json)
    assert "5 records of 4 independent slides" in text and "NOT MET" in text
    assert "POD (independent slides)" in text and "fairer" in text and "boundary day" in text
    assert "1 further event is dated" in text
    assert "| 2018 |" in text and "days below half" in text
    assert "relative" in text and "refitted" in text
    for model in result.levels:
        assert text.count(f"| {model} | tolerant | Warning+ |") == 1
    row = next(line for line in text.splitlines() if line.startswith("| v3 | tolerant | Warning+ |"))
    stats = entry["models"]["v3"]["tolerant"]["2"]
    header = next(line for line in text.splitlines() if "POD (independent slides)" in line and line.startswith("| model"))
    assert f"({stats['group_hits']}/{stats['groups']})" in row and row.count("|") == header.count("|")


def test_markdown_warns_that_tolerant_pod_has_a_chance_floor_and_points_to_the_cell_exact_rows():
    text = heldout.markdown(markdown_inputs()[2])
    bullet = next(line for line in text.splitlines() if "chance floor" in line)
    assert "30-40 cell-days" in bullet and "Watch+ and Warning+" in bullet
    assert "matched burden" in bullet and "cell-exact" in bullet and "scattered alerts" in bullet


def test_markdown_lists_the_data_sources_with_their_attribution():
    text = heldout.markdown(markdown_inputs()[2])
    section = text.split("## Data sources")[1].split("\n## ")[0]
    for source in heldout.SOURCES:
        assert f"- {source}" in section
    assert "GeoNames (CC BY 4.0)" in section and "OpenStreetMap contributors (ODbL)" in section
    assert "Stanley et al. 2021" in section and "Brunetti et al. 2021 (HESS)" in section and "IMERG: NASA GES DISC" in section


def test_markdown_defines_the_imd_day_once():
    text = heldout.markdown(markdown_inputs()[2])
    assert text.count("03 UTC of the previous day to 03 UTC") == 1


def test_lhasa_shift_gap_is_the_largest_burden_shortfall_of_a_shifted_row_in_percentage_points():
    def shares(*realised):
        return {"realised": list(realised)}

    result = {"sets": {
        "S2018": {"shares": {"v3": shares(0.4, 0.16, 0.065), "lhasa_v2_m1": shares(0.3983, 0.1594, 0.0648),
                             "lhasa_v2": shares(0.4, 0.1601, 0.065), "lhasa_v2_p1": shares(0.3985, 0.1595, 0.0647)}},
        "L1820": {"shares": {"v3": shares(0.4, 0.16, 0.065), "lhasa_v2_m1": shares(0.3981, 0.1592, 0.0647),
                             "lhasa_v2_p1": shares(0.3990, 0.1593, 0.0648)}},
        "POOLED": {"shares": {"v3": shares(0.4, 0.16, 0.065)}}}}
    assert heldout.lhasa_shift_gap(result) == pytest.approx([0.19, 0.08, 0.03])
    assert heldout.lhasa_shift_gap({"sets": {"POOLED": {"shares": {"v3": shares(0.4, 0.16, 0.065)}}}}) is None


def test_markdown_reads_the_lhasa_shift_footnote_from_the_shares():
    result, entry, result_json = markdown_inputs()
    gap = heldout.lhasa_shift_gap(result_json)
    text = heldout.markdown(result_json)
    assert f"up to {gap[0]:.1f} points (Watch+; {gap[1]:.2f} at Warning+, {gap[2]:.2f} at Emergency)" in text
    assert "about 0.2" not in text


def test_markdown_leaves_the_lhasa_footnote_out_when_no_set_has_a_shifted_row():
    _, _, result_json = markdown_inputs()
    for model in ("lhasa_v2_m1", "lhasa_v2", "lhasa_v2_p1"):
        for table in ("models", "shares"):
            del result_json["sets"]["S2018"][table][model]
    assert "boundary day" not in heldout.markdown(result_json)


def test_markdown_labels_the_development_cuts_target_as_not_matched():
    _, entry, result_json = markdown_inputs()
    text = heldout.markdown(result_json)
    rows = {line.split("|")[1].strip(): line for line in text.splitlines() if line.startswith("| ") and "%" in line and "tolerant" not in line}
    assert "development shares (not matched)" in rows["rain_3d_devcuts"]
    assert "20.00% / 10.00% / 5.00%" in rows["rain_3d_devcuts"]
    assert "development" not in rows["rain_3d"]


def test_measure_set_counts_the_events_in_cells_off_the_panel():
    part, result = toy_season()
    events = pd.DataFrame({"cell_id": [A + 3, A + 5000, A + 5000], "date": pd.to_datetime(["2018-06-10", "2018-06-10", "2018-06-11"]),
                           "source": "reported"})
    entry = heldout.measure_set("S2018", [result], events, part.cell_ids, lambda m: None)
    assert entry["events"] == 3 and entry["events_off_panel_cells"] == 2
    result_json = markdown_inputs()[2]
    result_json["sets"]["S2018"]["events_off_panel_cells"] = 2
    text = heldout.markdown(result_json)
    assert "2 of the " in text and "outside the panel cells" in text and "only tolerantly" in text


def test_the_heldout_command_writes_the_report_to_the_chosen_folder(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(heldout, "write_heldout", lambda out, say=print, assembly=None, stem=None: calls.append(out))
    monkeypatch.setattr(sys, "argv", ["aetherguard.verify", "heldout", "--out", str(tmp_path)])
    with pytest.raises(SystemExit) as stop:
        runpy.run_module("aetherguard.verify", run_name="__main__")
    assert stop.value.code == 0 and calls == [tmp_path]


def test_markdown_says_lies_for_one_event_off_the_panel_and_nothing_for_none():
    result_json = markdown_inputs()[2]
    entry = result_json["sets"]["S2018"]
    entry["events_off_panel_cells"] = 1
    assert f"1 of the {entry['events']} events lies outside the panel cells" in heldout.markdown(result_json)
    entry["events_off_panel_cells"] = 0
    assert "outside the panel cells" not in heldout.markdown(result_json)


# --- assembly v2 (W1b) ------------------------------------------------------------------------------------------------

def frozen_assembly(tmp_path, window_rows=0):
    from aetherguard.verify import assembly
    events = pd.DataFrame({"cell_id": np.array([5, 6], dtype=np.int64), "date": pd.to_datetime(["2020-07-01", "2020-07-02"]),
                           "source": ["reported", "bipad_nepal"], "storm_id": np.array([0, 0], dtype=np.int64)})
    window = pd.DataFrame({"cell_id": np.arange(window_rows, dtype=np.int64)})
    assembly._write_frozen(tmp_path / "v2", {"events": events, "window_events": window}, {"version": 2})
    return tmp_path / "v2"


def test_an_assembly_is_read_with_its_storm_ids_and_checked_hashes(tmp_path):
    events = heldout.load_event_table({}, frozen_assembly(tmp_path))
    assert list(events.columns) == ["cell_id", "date", "source", "storm_id"] and len(events) == 2


def test_an_assembly_with_window_records_is_refused(tmp_path):
    with pytest.raises(ValueError, match="window records"):
        heldout.assembly_events(frozen_assembly(tmp_path, window_rows=1))


def test_the_gate_line_reads_storm_clusters_when_given():
    assert heldout.gate_line(200, 160, storms=40) == (
        "Held-out events: 200 records of 160 independent slides in 40 storm clusters against the 150-event gate "
        "(storm clusters): NOT MET, 110 short.")
    assert heldout.gate_line(92, 87).endswith("NOT MET, 63 short.")


def test_an_assembly_run_must_name_its_own_report(tmp_path):
    with pytest.raises(ValueError, match="must not overwrite"):
        heldout.write_heldout(tmp_path, assembly=tmp_path)


def test_the_heldout_command_passes_the_assembly_and_stem(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(heldout, "write_heldout", lambda out, say=print, assembly=None, stem=None: calls.append((assembly, stem)))
    monkeypatch.setattr(sys, "argv", ["aetherguard.verify", "heldout", "--out", str(tmp_path), "--assembly", "a", "--stem", "s"])
    with pytest.raises(SystemExit) as stop:
        runpy.run_module("aetherguard.verify", run_name="__main__")
    assert stop.value.code == 0 and calls == [(heldout.Path("a"), "s")]


def test_measure_set_counts_storm_clusters_when_the_events_carry_them():
    part, result = toy_season()
    events = toy_events(part).assign(storm_id=[4, 4, 9, 7])
    entry = heldout.measure_set("S2018", [result], events, part.cell_ids, lambda m: None)
    assert entry["storm_clusters"] == 1 and entry["events"] == 2
    assert entry["models"]["v3"]["tolerant"]["1"]["events"] == 2
    assert "storm_clusters" not in heldout.measure_set("S2018", [result], toy_events(part), part.cell_ids, lambda m: None)


def test_markdown_of_an_assembly_run_names_the_assembly_and_its_storm_clusters():
    result_json = markdown_inputs()[2]
    result_json["assembly"] = "data/processed/heldout_v2"
    for entry in result_json["sets"].values():
        entry["storm_clusters"] = 3
    text = heldout.markdown(result_json)
    assert "assembly `data/processed/heldout_v2`" in text and "3 storm clusters" in text
    assert "S2018 events are the June-September catalog events" not in text
