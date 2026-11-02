"""Date basis, inventory windows, trigger table, id conflicts and portability of the label report."""
import json
from pathlib import Path

import pandas as pd
from events_helpers import write_raw_dir

from aetherguard.events import store

BASE = "2015-07-15"
LAT0, LON0 = 30.0, 79.0


def us_date(iso):
    year, month, day = iso.split("-")
    return f"{month}/{day}/{year} 12:00:00 AM"


def glc(ev_id, date=BASE, lat=LAT0, lon=LON0, accu="1km", trig="rain", cc="IN"):
    return {"event_id": str(ev_id), "event_date": us_date(date), "location_accuracy": accu,
            "landslide_trigger": trig, "country_code": cc, "latitude": str(lat), "longitude": str(lon)}


def report(ev_id, date=BASE, lat=LAT0, lon=LON0, accu="1km", trig="rain", cc="IN"):
    return {**glc(ev_id, date, lat, lon, accu, trig, cc), "event_date": date}


def cevent(ev_id, lon, before="2015-07-01", after="2015-07-30", date=BASE, trig="Rain"):
    return {"event_id": str(ev_id), "event_date": date, "landslide_trigger": trig, "country_code": "IN",
            "latitude": str(LAT0), "longitude": str(lon), "sat_date_before": before, "sat_date_after": after}


def hma(ev_id, date="20150715", lat=LAT0, lon=LON0, accu="1km", trig="rain", cc="IN"):
    return {"ev_id": ev_id, "ev_date": date, "loc_accu": accu, "ls_trig": trig, "ctry_code": cc,
            "latitude": lat, "longitude": lon}


def build(tmp_path, **kwargs):
    raw = write_raw_dir(tmp_path / "raw", **kwargs)
    out = tmp_path / "out"
    rep = store.build_events(raw, out)
    return pd.read_parquet(out / "events.parquet"), rep


def test_date_basis_windows_and_day_exact_positives(tmp_path):
    df, rep = build(
        tmp_path,
        hma=[hma(1, lon=LON0)], reports=[report(2, lon=LON0 + 1)], glc=[glc(3, lon=LON0 + 2)],
        events=[cevent(4, LON0 + 3),
                cevent(5, LON0 + 4, before=""),
                cevent(6, LON0 + 5, before="2015-07-30", after="2015-07-01"),  # inverted window
                cevent(7, LON0 + 6, before="2015-07-2", after="x")])
    by_source = {s: g for s, g in df.groupby("source")}
    for name in ("hma", "coolr_reports", "glc"):
        rows = by_source[name]
        assert (rows["date_basis"] == "event_day").all()
        assert rows["date_window_start"].isna().all() and rows["date_window_end"].isna().all()
        assert rows["is_positive"].all() and rows["is_day_exact_positive"].all()
    events = by_source["coolr_events"].set_index("event_id")
    assert (events["date_basis"] == "inventory_window").all()
    assert events["is_positive"].all() and not events["is_day_exact_positive"].any()
    assert events.loc[4, "date_window_start"] == pd.Timestamp("2015-07-01")
    assert events.loc[4, "date_window_end"] == pd.Timestamp("2015-07-30")
    assert pd.isna(events.loc[5, "date_window_start"]) and events.loc[5, "date_window_end"] == pd.Timestamp("2015-07-30")
    assert pd.isna(events.loc[6, "date_window_start"]) and pd.isna(events.loc[6, "date_window_end"])  # inverted
    assert pd.isna(events.loc[7, "date_window_start"]) and pd.isna(events.loc[7, "date_window_end"])
    assert df["date_basis"].notna().all()

    windows = rep["inventory_windows"]
    assert windows["n_input"] == 4
    assert windows["start_missing"] == 1 and windows["start_unparsable"] == 1
    assert windows["end_missing"] == 0 and windows["end_unparsable"] == 1
    assert windows["inverted"] == 1
    assert windows["kept"] == {"n": 4, "min_start": "2015-07-01", "max_end": "2015-07-30",
                               "n_distinct_headline_dates": 1}
    assert windows["positives"]["n"] == 4

    counts = rep["sources"]
    assert (counts["hma"]["n_positive"], counts["hma"]["n_day_exact_positive"],
            counts["hma"]["n_inventory_window_positive"]) == (1, 1, 0)
    assert (counts["coolr_events"]["n_positive"], counts["coolr_events"]["n_day_exact_positive"],
            counts["coolr_events"]["n_inventory_window_positive"]) == (4, 0, 4)
    assert rep["positives_per_region_per_year"]["himalaya"] == {"2015": 7}
    assert rep["day_exact_positives_per_region_per_year"]["himalaya"] == {"2015": 3}
    assert rep["inventory_window_positives_per_region_per_year"]["himalaya"] == {"2015": 4}
    assert rep["positives_per_source_region_year"]["hma"]["himalaya"]["2015"] == {
        "positives": 1, "day_exact": 1, "inventory_window": 0}
    assert rep["positives_per_source_region_year"]["coolr_events"]["himalaya"]["2015"] == {
        "positives": 4, "day_exact": 0, "inventory_window": 4}
    assert rep["positives_per_source_region_year"]["hma"]["western_ghats"] == {}


def test_missing_country_is_counted_per_source(tmp_path):
    _, rep = build(tmp_path, glc=[glc(1, cc=""), glc(2, cc="", lat=11.5, lon=76.1), glc(3, cc="MM"),
                                  glc(4, cc="", lat=40.0, lon=100.0), glc(5, lon=LON0 + 1)])
    drops = rep["sources"]["glc"]["n_dropped"]
    assert drops["missing_country"] == 2 and drops["out_of_scope_region"] == 2
    assert rep["sources"]["glc"]["n_kept"] == 1
    assert rep["drop_reasons"] == ["missing_date", "bad_coordinates", "out_of_scope_region", "missing_country",
                                   "duplicate_id", "near_duplicate"]


def test_trigger_table_lists_every_raw_string_with_class_and_kept_count(tmp_path):
    _, rep = build(tmp_path, glc=[
        glc(1, trig="rain", lon=LON0), glc(2, trig="rain", lon=LON0 + 1), glc(3, trig="Downpour", lon=LON0 + 2),
        glc(4, trig="flooding", lon=LON0 + 3), glc(5, trig="mining", lon=20.0, cc="MM"),
        glc(6, trig="", lon=LON0 + 4)])
    table = rep["trigger_table"]["glc"]
    assert table == [
        {"trigger_raw": "rain", "trigger_class": "rain", "n_input": 2, "n_kept": 2},
        {"trigger_raw": "", "trigger_class": "unknown", "n_input": 1, "n_kept": 1},
        {"trigger_raw": "Downpour", "trigger_class": "rain", "n_input": 1, "n_kept": 1},
        {"trigger_raw": "flooding", "trigger_class": "other", "n_input": 1, "n_kept": 1},
        {"trigger_raw": "mining", "trigger_class": "construction_mining", "n_input": 1, "n_kept": 0},
    ]
    assert set(rep["trigger_table"]) == {"hma", "coolr_reports", "glc", "coolr_events"}


def test_id_conflicts_are_reported_but_the_highest_priority_record_is_kept(tmp_path):
    df, rep = build(
        tmp_path,
        hma=[hma(1)],
        reports=[report(1, date="2015-07-16", lat=LAT0 + 0.1, accu="5km", trig="downpour")],
        glc=[glc(1)])
    conflicts = rep["id_conflicts"]
    assert set(conflicts) == {"hma|coolr_reports", "hma|glc", "coolr_reports|glc"}
    assert {k: v for k, v in conflicts["hma|coolr_reports"].items() if k != "date_difference_examples"} == {
        "shared_ids": 1, "date_differs": 1, "location_differs_gt_2km": 1, "accuracy_differs": 1,
        "trigger_differs": 1}
    assert conflicts["hma|coolr_reports"]["date_difference_examples"] == [
        {"event_id": 1, "dates": {"hma": "2015-07-15", "coolr_reports": "2015-07-16"}}]
    assert conflicts["hma|glc"] == {"shared_ids": 1, "date_differs": 0, "location_differs_gt_2km": 0,
                                    "accuracy_differs": 0, "trigger_differs": 0, "date_difference_examples": []}
    assert conflicts["coolr_reports|glc"]["date_differs"] == 1
    assert df[df["drop_reason"].isna()]["source"].tolist() == ["hma"]


def test_id_conflict_examples_are_capped_at_twenty_and_sorted(tmp_path):
    _, rep = build(tmp_path, hma=[hma(i) for i in range(30, 5, -1)],
                   reports=[report(i, date="2015-07-16") for i in range(30, 5, -1)])
    pair = rep["id_conflicts"]["hma|coolr_reports"]
    assert pair["shared_ids"] == 25 and pair["date_differs"] == 25
    assert [e["event_id"] for e in pair["date_difference_examples"]] == list(range(6, 26))


def test_report_paths_are_relative_with_forward_slashes(tmp_path):
    _, rep = build(tmp_path, glc=[glc(1)])
    for entry in rep["inputs"]:
        assert not Path(entry["path"]).is_absolute() and "\\" not in entry["path"]
    assert rep["inputs"][2]["path"].endswith("nasa_glc.csv")
    assert rep["inputs"][0]["path"].endswith("hma/HMA_LS_Cat_point_v02.0.dbf")
    text = json.dumps(rep)
    assert str(tmp_path).replace("\\", "/") not in text and str(tmp_path) not in text
