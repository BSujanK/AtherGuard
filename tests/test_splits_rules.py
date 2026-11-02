"""Pure split rules: collapse, boundaries, case studies and the leakage report."""
import pandas as pd
import pytest
from splits_helpers import HIMALAYA, cell, event, events_frame, sample_events

from aetherguard.config import load_config
from aetherguard.splits import rules

CFG = load_config("splits")


def test_config_matches_design_d4():
    days = CFG["day_splits"]
    assert {k: (v["start"], v["end"]) for k, v in days.items()} == {
        "train": ("2007-01-01", "2015-12-31"),
        "validation": ("2016-01-01", "2017-12-31"),
        "test_2018": ("2018-01-01", "2018-12-31"),
        "test_sparse": ("2019-01-01", "2024-12-31"),
    }
    assert CFG["window_test"] == {"name": "test_2023_india_window",
                                  "window_start": "2023-06-16", "window_end": "2023-07-31"}
    assert CFG["case_studies"]["kerala_2018"] == {"region": "western_ghats",
                                                  "start": "2018-08-01", "end": "2018-08-31"}
    wayanad = CFG["case_studies"]["wayanad_2024"]
    assert (wayanad["region"], wayanad["start"], wayanad["end"]) == (
        "western_ghats", "2024-07-25", "2024-08-05")
    assert (CFG["leakage"]["days"], CFG["leakage"]["cells"]) == (3, 3)
    rules.validate_config(CFG)


def test_collapse_day_exact_counts_events_and_takes_modal_country():
    out = rules.collapse_day_exact(sample_events())
    big = out[(out["cell_id"] == cell(*HIMALAYA)) & (out["event_date"] == "2010-07-01")]
    assert len(big) == 1 and big["n_events"].iloc[0] == 38
    assert big["sources"].iloc[0] == "hma"
    shared = out[(out["cell_id"] == cell(*HIMALAYA)) & (out["event_date"] == "2012-06-01")].iloc[0]
    assert shared["n_events"] == 3
    assert shared["country_code"] == "NP"  # two NP records vs one IN
    assert shared["sources"] == "coolr_reports,glc,hma"
    assert out["n_events"].sum() == 55 and len(out) == 16
    assert not out.duplicated(["cell_id", "event_date"]).any()
    assert list(out.columns) == ["cell_id", "event_date", "region", "country_code", "n_events",
                                 "sources", "min_accuracy_km", "max_accuracy_km"]


def test_collapse_accuracy_bounds_and_modal_tie_break():
    c = cell(*HIMALAYA)
    df = events_frame([event(1, "2012-06-01", c, accuracy=0.5, country="NP"),
                       event(2, "2012-06-01", c, accuracy=4.0, country="IN")])
    row = rules.collapse_day_exact(df).iloc[0]
    assert (row["min_accuracy_km"], row["max_accuracy_km"]) == (0.5, 4.0)
    assert row["country_code"] == "IN"  # tie -> alphabetical


def test_collapse_ignores_non_positive_and_window_rows():
    out = rules.collapse_day_exact(sample_events())
    assert (out["event_date"] != pd.Timestamp("2011-01-01")).all()  # non-positive
    assert (out["event_date"] != pd.Timestamp("2023-07-01")).all()  # window rows


def test_collapse_day_exact_on_no_positives_is_empty_with_columns():
    out = rules.collapse_day_exact(events_frame([event(1, "2012-06-01", positive=False)]))
    assert out.empty and "n_events" in out.columns


def test_collapse_windows_groups_by_cell_and_window():
    out = rules.collapse_windows(sample_events())
    assert list(out.columns) == ["cell_id", "window_start", "window_end", "region", "country_code",
                                 "n_events", "sources"]
    assert len(out) == 2 and out["n_events"].sum() == 3
    assert set(out["window_start"]) == {pd.Timestamp("2023-06-16")}
    assert set(out["window_end"]) == {pd.Timestamp("2023-07-31")}
    assert out.loc[out["cell_id"] == cell(*HIMALAYA), "n_events"].iloc[0] == 2
    assert (out["sources"] == "coolr_events").all()


def test_collapse_windows_separates_different_windows_in_one_cell():
    c = cell(*HIMALAYA)
    df = events_frame([event(1, "2023-07-01", c, source="coolr_events", window=("2023-06-16", "2023-07-31")),
                       event(2, "2023-07-01", c, source="coolr_events", window=("2023-06-20", "2023-07-31"))])
    assert len(rules.collapse_windows(df)) == 2


@pytest.mark.parametrize("which", ["date_window_start", "date_window_end"])
def test_collapse_windows_null_bound_raises(which):
    df = sample_events()
    df.loc[df["uid"] == "coolr_events:301", which] = pd.NaT
    with pytest.raises(ValueError, match="null window bound"):
        rules.collapse_windows(df)


@pytest.mark.parametrize("date, expected", [
    ("2007-01-01", "train"), ("2015-12-31", "train"),
    ("2016-01-01", "validation"), ("2017-12-31", "validation"),
    ("2018-01-01", "test_2018"), ("2018-12-31", "test_2018"),
    ("2019-01-01", "test_sparse"), ("2024-12-31", "test_sparse"),
])
def test_assign_split_boundaries(date, expected):
    assert rules.assign_split(pd.Timestamp(date), CFG) == expected
    assert rules.assign_split(date, CFG) == expected


@pytest.mark.parametrize("date", ["2006-12-31", "2025-01-01"])
def test_assign_split_outside_every_boundary_raises(date):
    with pytest.raises(ValueError, match="outside every split"):
        rules.assign_split(date, CFG)


def test_assign_splits_vectorised_raises_naming_the_date():
    with pytest.raises(ValueError, match="2025-01-01"):
        rules.assign_splits(pd.Series(pd.to_datetime(["2010-01-01", "2025-01-01"])), CFG)


def test_assign_case_study():
    assert rules.assign_case_study("western_ghats", "2018-08-01", CFG) == "kerala_2018"
    assert rules.assign_case_study("western_ghats", "2018-08-31", CFG) == "kerala_2018"
    assert rules.assign_case_study("western_ghats", "2018-09-01", CFG) is None
    assert rules.assign_case_study("himalaya", "2018-08-15", CFG) is None
    assert rules.assign_case_study("western_ghats", "2024-07-25", CFG) == "wayanad_2024"
    assert rules.assign_case_study("western_ghats", "2024-08-05", CFG) == "wayanad_2024"
    assert rules.assign_case_study("western_ghats", "2024-08-06", CFG) is None


def test_validate_config_rejects_overlap_and_training_case_studies():
    days = {**CFG["day_splits"], "validation": {**CFG["day_splits"]["validation"], "start": "2015-12-31"}}
    with pytest.raises(ValueError, match="overlap"):
        rules.validate_config({**CFG, "day_splits": days})
    train_case = {"old": {"region": "himalaya", "start": "2010-01-01", "end": "2010-01-31"}}
    with pytest.raises(ValueError, match="test split"):
        rules.validate_config({**CFG, "case_studies": train_case})


def test_build_tables_splits_windows_and_cases():
    cell_days, windows = rules.build_tables(sample_events(), CFG)
    assert cell_days.groupby("split").size().to_dict() == {
        "train": 3, "validation": 2, "test_2018": 7, "test_sparse": 4}
    assert cell_days["n_events"].sum() == 55
    kerala = cell_days[cell_days["case_study"] == "kerala_2018"]
    assert set(kerala["split"]) == {"test_2018"} and len(kerala) == 3
    assert (cell_days["case_study"] == "wayanad_2024").sum() == 0
    assert windows["split"].eq("test_2023_india_window").all()
    assert pd.MultiIndex.from_frame(cell_days[["event_date", "cell_id"]]).is_monotonic_increasing


def test_build_tables_rejects_window_outside_configured_window():
    df = events_frame([event(1, "2023-07-01", source="coolr_events", window=("2023-06-01", "2023-07-31"))])
    with pytest.raises(ValueError, match="configured window"):
        rules.build_tables(df, CFG)


def test_build_tables_rejects_positive_without_a_known_date_basis():
    df = sample_events()
    df.loc[df["uid"] == "hma:1", ["date_basis", "is_day_exact_positive"]] = ["mystery", False]
    with pytest.raises(ValueError, match="neither day-exact nor inventory-window"):
        rules.build_tables(df, CFG)


def _frame(rows):
    """Rows are (split, lat_index, lon_index, date)."""
    return pd.DataFrame({
        "cell_id": [cell(la, lo) for _, la, lo, _ in rows],
        "event_date": pd.to_datetime([d for *_, d in rows]),
        "split": [s for s, *_ in rows],
    })


def test_leakage_report_known_answers():
    t = "2012-06-10"
    rows = [
        ("train", 2000, 5000, t),
        ("validation", 2000, 5000, "2012-06-13"),   # +3 days, same cell -> inside
        ("validation", 2000, 5000, "2012-06-14"),   # +4 days -> outside
        ("validation", 2003, 5003, t),              # Chebyshev distance 3 -> inside
        ("validation", 2004, 5000, t),              # 4 cells in lat -> outside
        ("test_2018", 2000, 4996, t),               # 4 cells in lon -> outside
        ("test_2018", 1997, 4997, "2012-06-07"),    # -3 days and (3, 3) cells -> inside
        ("test_2018", 2001, 5001, "2012-06-07"),    # -3 days -> inside
        ("test_sparse", 2500, 5000, t),             # far away
        ("train", 3000, 3000, t),                   # train rows are never counted as checked
    ]
    out = rules.leakage_report(_frame(rows), CFG)
    assert out["days"] == 3 and out["cells"] == 3 and out["reference_split"] == "train"
    assert out["n_reference"] == 2
    assert out["per_split"]["validation"] == {"n": 4, "n_within": 2, "share": 0.5}
    assert out["per_split"]["test_2018"] == {"n": 3, "n_within": 2, "share": 2 / 3}
    assert out["per_split"]["test_sparse"] == {"n": 1, "n_within": 0, "share": 0.0}
    assert out["total"] == {"n": 8, "n_within": 4, "share": 0.5}


def test_leakage_uses_lat_lon_indices_not_id_difference():
    # ids differ by 9999 yet the cells are diagonal neighbours; the last lon column wraps to 0.
    rows = [
        ("train", 100, 5, "2012-01-01"),
        ("validation", 101, 4, "2012-01-01"),
        ("train", 300, 7199, "2012-01-01"),
        ("validation", 300, 2, "2012-01-01"),        # wrap: distance 3 -> inside
        ("validation", 300, 3, "2012-01-01"),        # wrap: distance 4 -> outside
    ]
    out = rules.leakage_report(_frame(rows), CFG)
    assert out["per_split"]["validation"]["n"] == 3
    assert out["per_split"]["validation"]["n_within"] == 2


def test_leakage_empty_split_share_is_null():
    out = rules.leakage_report(_frame([("train", 100, 5, "2012-01-01")]), CFG)
    assert out["per_split"]["test_2018"] == {"n": 0, "n_within": 0, "share": None}
    assert out["total"]["share"] is None


def test_leakage_with_no_reference_rows():
    out = rules.leakage_report(_frame([("validation", 100, 5, "2016-01-01")]), CFG)
    assert out["n_reference"] == 0 and out["per_split"]["validation"]["n_within"] == 0


def test_leakage_handles_thousands_of_rows():
    n = 4000
    frame = pd.DataFrame({
        "cell_id": [cell(2000 + i % 400, 5000 + i % 350) for i in range(n)],
        "event_date": pd.Timestamp("2010-01-01") + pd.to_timedelta([i % 3000 for i in range(n)], unit="D"),
        "split": ["train"] * (n // 2) + ["validation"] * (n // 2),
    })
    out = rules.leakage_report(frame, CFG)
    assert out["per_split"]["validation"]["n"] == n // 2
