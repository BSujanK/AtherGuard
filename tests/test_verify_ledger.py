import json
from datetime import date

import numpy as np
import pandas as pd
import pytest

from aetherguard import grid
from aetherguard.verify.ledger import ledger, live_levels, load_reported, markdown

A = grid.latlon_to_cell(30.025, 78.025)
B = A + 5  # 24 km east of A
CELLS = [A, B]
HEADER = "date,latitude,longitude,location_text,source_url,accuracy_km"


def write_csv(directory, rows, name="reports.csv") -> None:
    lines = [HEADER] + [",".join(str(v) for v in row) for row in rows]
    (directory / name).write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_run(root, day: date, level_by_lead: dict[int, list[int]], risk_nan_cell: int | None = None) -> None:
    """A published day: lead 0 in alerts.parquet, lead k in risk_D{k}.parquet (dated the day it forecasts)."""
    run_dir = root / day.isoformat()
    run_dir.mkdir(parents=True)
    for lead in range(4):
        levels = level_by_lead.get(lead, [0] * len(CELLS))
        risk = [0.1] * len(CELLS)
        if risk_nan_cell is not None:
            risk[risk_nan_cell] = np.nan
        frame = pd.DataFrame({
            "cell_id": CELLS,
            "date": pd.Timestamp(day) + pd.Timedelta(days=lead),
            "lead": np.int8(lead),
            "level": np.array(levels, dtype=np.int8),
            "risk": risk,
        })
        name = "alerts.parquet" if lead == 0 else f"risk_D{lead}.parquet"
        frame.to_parquet(run_dir / name)
    (run_dir / "run.json").write_text(json.dumps({"status": "complete", "date": day.isoformat()}), encoding="utf-8")


@pytest.fixture
def live_root(tmp_path):
    root = tmp_path / "live"
    root.mkdir()
    (root / "cache").mkdir()  # not a day
    write_run(root, date(2026, 10, 22), {0: [0, 1], 2: [3, 0]})
    write_run(root, date(2026, 10, 24), {0: [2, 0], 2: [0, 0]}, risk_nan_cell=1)
    write_run(root, date(2026, 10, 25), {0: [0, 0], 2: [0, 1]})
    (root / "2026-10-26").mkdir()  # no run.json: not published
    return root


@pytest.fixture
def reported(tmp_path):
    directory = tmp_path / "reported"
    directory.mkdir()
    write_csv(directory, [("2026-10-24", 30.025, 78.025, "Chamoli", "https://x/1", 1)])
    return directory


def test_reported_events_outside_the_domain_are_rejected(tmp_path):
    write_csv(tmp_path, [("2026-10-22", 51.5, -0.1, "London", "https://x", 1)])
    with pytest.raises(ValueError, match="line 2"):
        load_reported(tmp_path)


def test_a_missing_day_is_not_an_alert_and_not_scored(live_root):
    levels, scored, _, days = live_levels(live_root)
    j = days.index(date(2026, 10, 23))
    assert (levels[:, j] == -1).all() and not scored[:, j].any()


def test_forecast_lead_rows_are_placed_on_the_day_they_forecast(live_root):
    _, _, _, days = live_levels(live_root, lead=2)
    assert days[0] == date(2026, 10, 24)  # first run 2026-10-22, lead 2


def test_recent_days_are_provisional(live_root, reported):
    out = ledger(live_root, reported, today=date(2026, 11, 2))
    assert out["provisional_from"] == "2026-10-19"


def test_levels_and_scored_follow_the_published_files(live_root):
    levels, scored, cell_ids, days = live_levels(live_root)
    assert cell_ids.tolist() == sorted(CELLS)
    assert days == [date(2026, 10, d) for d in (22, 23, 24, 25)]
    assert levels.dtype == np.int8
    assert levels.tolist() == [[0, -1, 2, 0], [1, -1, 0, 0]]
    assert scored.tolist() == [[True, False, True, True], [True, False, False, True]]


def test_lead_two_levels_sit_on_the_forecast_day(live_root):
    levels, _, _, days = live_levels(live_root, lead=2)
    assert days == [date(2026, 10, d) for d in range(24, 28)]
    assert levels[:, 0].tolist() == [3, 0]  # run 2026-10-22
    assert levels[:, 1].tolist() == [-1, -1]  # run 2026-10-23 missing
    assert levels[:, 2].tolist() == [0, 0]  # run 2026-10-24
    assert levels[:, 3].tolist() == [0, 1]  # run 2026-10-25


def test_a_run_without_its_forecast_file_leaves_that_lead_day_missing(live_root):
    (live_root / "2026-10-24" / "risk_D2.parquet").unlink()
    levels, scored, _, days = live_levels(live_root, lead=2)
    assert days[0] == date(2026, 10, 24) and days[-1] == date(2026, 10, 27)
    assert (levels[:, 2] == -1).all() and not scored[:, 2].any()
    assert live_levels(live_root, lead=0)[0].shape == (2, 4)


def test_a_root_without_published_days_is_empty(tmp_path):
    levels, scored, cell_ids, days = live_levels(tmp_path / "nothing")
    assert levels.shape == scored.shape == (0, 0) and len(cell_ids) == 0 and days == []


def test_load_reported_adds_cells_and_all_files(tmp_path):
    write_csv(tmp_path, [("2026-10-22", 30.025, 78.025, "a", "https://x/1", 2), ("2026-10-23", 30.03, 78.03, "b", "https://x/2", "")])
    write_csv(tmp_path, [("2026-10-24", 30.025, 78.075, "c", "https://x/3", 5)], name="more.csv")
    frame = load_reported(tmp_path)
    assert len(frame) == 3
    assert sorted(frame["cell_id"]) == [A, A, A + 1]
    assert frame["accuracy_km"].isna().sum() == 1


def test_an_empty_folder_gives_no_events(tmp_path):
    frame = load_reported(tmp_path)
    assert len(frame) == 0 and {"date", "cell_id"} <= set(frame.columns)


@pytest.mark.parametrize(
    "row, text",
    [
        (("22/10/2026", 30.0, 78.0, "a", "https://x", 1), "date"),
        (("2026-10-22", 30.0, 78.0, "a", "", 1), "source_url"),
        (("2026-10-22", "north", 78.0, "a", "https://x", 1), "latitude"),
        (("2026-10-22", 30.0, 78.0, "a", "https://x", -3), "accuracy_km"),
    ],
)
def test_bad_rows_name_the_file_and_line(tmp_path, row, text):
    write_csv(tmp_path, [("2026-10-21", 30.0, 78.0, "ok", "https://x", 1), row], name="bad.csv")
    with pytest.raises(ValueError, match=rf"bad\.csv.*line 3.*{text}"):
        load_reported(tmp_path)


def test_a_csv_without_the_required_columns_is_rejected(tmp_path):
    (tmp_path / "odd.csv").write_text("date,latitude\n2026-10-22,30\n", encoding="utf-8")
    with pytest.raises(ValueError, match="odd.csv.*longitude"):
        load_reported(tmp_path)


def test_ledger_scores_each_lead_and_level_against_reported_events(live_root, reported):
    out = ledger(live_root, reported, today=date(2026, 11, 2))
    assert out["reported_events"] == 1
    lead0 = out["leads"]["0"]
    assert lead0["days"] == 4 and lead0["published_days"] == 3
    watch = lead0["levels"]["1"]
    assert watch["events"] == 1 and watch["hits"] == 1 and watch["pod"] == 1.0  # level 2 on A on 2026-10-24
    assert watch["alert_cell_days"] == 2  # A 10-24 and B 10-22; B 10-22 is not within a day of 10-24
    assert watch["verified_alert_cell_days"] == 1
    assert lead0["levels"]["3"]["hits"] == 0
    assert set(out["leads"]) == {"0", "1", "2", "3"}


def test_the_ledger_works_with_no_reported_events(live_root, tmp_path):
    empty = tmp_path / "none"
    empty.mkdir()
    out = ledger(live_root, empty, today=date(2026, 11, 2))
    watch = out["leads"]["0"]["levels"]["1"]
    assert out["reported_events"] == 0 and watch["events"] == 0
    assert np.isnan(watch["pod"]) and watch["alert_cell_days"] == 2
    for entry in out["leads"].values():
        for scores in entry["levels"].values():
            assert np.isnan(scores["precision"]) and np.isnan(scores["events_per_1000_alert_cell_days"])
            assert np.isnan(scores["verified_alert_cell_days"])
            assert np.isnan(scores["precision_ci"]).all() and np.isnan(scores["pod"])
    assert out["leads"]["0"]["levels"]["1"]["alert_cell_days"] == 2


def test_forecast_days_after_today_are_not_scored(live_root, reported):
    out = ledger(live_root, reported, today=date(2026, 10, 25))
    assert out["leads"]["2"]["days"] == 2  # 10-24 and 10-25 of 10-24..10-27
    assert out["leads"]["2"]["last_day"] == "2026-10-25"


def test_the_markdown_does_not_show_a_precision_without_events(live_root, tmp_path, reported):
    empty = tmp_path / "none"
    empty.mkdir()
    none = markdown(ledger(live_root, empty, today=date(2026, 11, 2)))
    some = markdown(ledger(live_root, reported, today=date(2026, 11, 2)))
    assert "No reported events yet" in none and "0.000%" not in none and "nan" not in none
    assert "No reported events yet" not in some and "50.000%" in some


def test_a_lead_whose_days_hold_no_event_prints_na_precision(live_root, tmp_path):
    directory = tmp_path / "late"
    directory.mkdir()
    write_csv(directory, [("2026-10-26", 30.025, 78.025, "Chamoli", "https://x/1", 1)])  # after lead 0's last day, inside lead 2's
    out = ledger(live_root, directory, today=date(2026, 10, 27))
    lead0, lead2 = out["leads"]["0"], out["leads"]["2"]
    assert lead0["events_outside_window"] == 1 and lead0["levels"]["1"]["events"] == 0
    assert lead0["levels"]["1"]["alert_cell_days"] == 2 and np.isnan(lead0["levels"]["1"]["precision"])
    assert np.isnan(lead0["levels"]["1"]["verified_alert_cell_days"])
    assert lead2["levels"]["3"]["events"] == 1 and lead2["levels"]["3"]["precision"] == 0.0

    def cell(lead: str, level: str) -> str:
        row = next(r for r in markdown(out).split(f"## Lead {lead}")[1].splitlines() if r.startswith(f"| {level}"))
        return row.split("|")[7].strip()

    assert cell("0", "Watch+") == "n/a"
    assert cell("2", "Emergency").startswith("0.000%")
