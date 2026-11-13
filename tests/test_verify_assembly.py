"""Assembly v2 (W1b): cross-source duplicates, storm clusters, the gate views, the development repeats, the QA records and
the freeze guard. Synthetic frames only; nothing reads the data folder or the network."""
import json

import numpy as np
import pandas as pd
import pytest

from aetherguard import grid
from aetherguard.verify import assembly as asm


def cell(lat, lon):
    return int(grid.latlon_to_cell(lat, lon))


def records(*rows):
    """rows: (source, lat, lon, date[, stratum]) -> assembly records at the given points."""
    out = []
    for i, r in enumerate(rows):
        source, lat, lon, day = r[:4]
        out.append({"cell_id": cell(lat, lon), "date": pd.Timestamp(day), "source": source,
                    "stratum": r[4] if len(r) > 4 else "day", "how_found": "reported", "country": "NP", "region": "himalaya",
                    "record_id": f"{source}:{i}", "latitude": lat, "longitude": lon, "accuracy_km": 2.0,
                    "year": pd.Timestamp(day).year})
    return pd.DataFrame(out)


def test_a_lower_priority_twin_within_a_day_and_5_km_is_dropped_and_the_kept_one_takes_the_earliest_date():
    kept, dropped = asm.dedupe(records(("reported", 27.70, 85.30, "2020-07-02"), ("bipad_nepal", 27.72, 85.30, "2020-07-01")))
    assert list(kept["source"]) == ["reported"]
    assert kept["date"].iloc[0] == pd.Timestamp("2020-07-01")
    assert dropped == [{"source": "bipad_nepal", "record_id": "bipad_nepal:1", "date": "2020-07-01",
                        "duplicate_of": "reported:0", "duplicate_source": "reported"}]


def test_records_two_days_apart_or_beyond_5_km_stay_separate():
    kept, _ = asm.dedupe(records(("reported", 27.70, 85.30, "2020-07-01"), ("bipad_nepal", 27.70, 85.30, "2020-07-03"),
                                 ("bipad_nepal", 27.80, 85.30, "2020-07-01")))
    assert len(kept) == 3


def test_a_window_record_never_merges_with_a_day_record():
    kept, _ = asm.dedupe(records(("reported", 27.70, 85.30, "2020-07-01"), ("bipad_nepal", 27.70, 85.30, "2020-07-01", "window")))
    assert len(kept) == 2


def test_storm_clusters_split_a_wet_season_into_fixed_five_day_episodes_per_tile():
    # one tile, slides on days 1, 3, 5 (episode 1), 6 and 9 (episode 2), 11 (episode 3); another tile on day 1 (its own)
    dates = pd.to_datetime(["2020-07-01", "2020-07-03", "2020-07-05", "2020-07-06", "2020-07-09", "2020-07-11", "2020-07-01"])
    cells = [cell(27.5, 85.5)] * 6 + [cell(28.5, 85.5)]
    labels = asm.storm_clusters(np.arange(7), cells, dates)
    assert labels[0] == labels[1] == labels[2]
    assert labels[3] == labels[4] != labels[0]
    assert labels[5] not in (labels[0], labels[3])
    assert labels[6] not in labels[:6]
    assert len(set(labels)) == 4


def test_every_record_of_a_slide_takes_the_cluster_of_its_earliest_record():
    labels = asm.storm_clusters(np.array([7, 7, 8]), [cell(27.5, 85.5), cell(27.5, 86.5), cell(27.5, 86.5)],
                                pd.to_datetime(["2020-07-01", "2020-07-02", "2020-07-02"]))
    assert labels[0] == labels[1] and labels[2] != labels[0]      # slide 7 sits in its first record's tile


def test_two_degree_tiles_merge_neighbouring_one_degree_tiles():
    dates = pd.to_datetime(["2020-07-01", "2020-07-01"])
    cells = [cell(26.5, 84.5), cell(27.5, 85.5)]
    assert len(set(asm.storm_clusters(np.arange(2), cells, dates, 1.0))) == 2
    assert len(set(asm.storm_clusters(np.arange(2), cells, dates, 2.0))) == 1


def gate_frame():
    rows = []
    for k in range(4):                                              # four storms in Nepal, two in India
        rows.append(("bipad_nepal", 27.5, 84.5 + k, "2020-07-01"))
    for k in range(2):
        rows.append(("reported", 30.5, 78.5 + k, "2020-08-01"))
    frame = records(*rows)
    frame.loc[frame["source"] == "reported", "country"] = "IN"
    return frame


def test_gate_views_count_storm_clusters_within_each_view():
    views = asm.gate_views(gate_frame(), gate=5)
    assert {k: v["storm_clusters"] for k, v in views.items()} == {
        "all_sources": 6, "without_bipad": 2, "india_only": 2, "nepal_bhutan_only": 4}
    assert views["all_sources"]["met"] and views["all_sources"]["verdict"] == "MET, 1 over"
    assert views["india_only"]["verdict"] == "NOT MET, 3 short"


def test_only_june_to_december_of_the_held_out_years_are_panel_days():
    assert list(asm.on_panel_days(pd.Series(pd.to_datetime(["2018-06-01", "2018-05-31", "2025-12-31", "2026-07-01"])))) == [
        True, False, True, False]


def test_assemble_keeps_scored_cells_splits_held_out_and_development_and_clusters():
    v1 = pd.DataFrame({"cell_id": [cell(27.70, 85.30)], "date": pd.to_datetime(["2020-07-02"]), "source": ["reported"]})
    admitted = pd.DataFrame({
        "date": ["2020-07-01", "2015-07-01", "2021-07-01", "2026-10-10"], "latitude": [27.71, 27.9, 20.0, 27.9],
        "longitude": [85.30, 85.9, 70.0, 85.9], "accuracy_km": [2.0] * 4, "date_basis": ["stated"] * 4,
        "how_found": ["reported"] * 4, "record_id": ["b:1", "b:2", "b:3", "b:4"]})
    universe = np.unique([cell(27.70, 85.30), cell(27.71, 85.30), cell(27.9, 85.9)])
    regions = pd.DataFrame({"cell_id": universe, "country_code": "NP", "region": "himalaya"})
    built = asm.assemble(v1, {"bipad_nepal": admitted}, universe, regions)
    assert [r["record_id"] for r in built["rejected"]] == ["b:3"]
    assert list(built["heldout_day"]["source"]) == ["reported"]          # b:1 is the W1 record's twin
    assert built["heldout_day"]["date"].iloc[0] == pd.Timestamp("2020-07-01")
    assert list(built["dev_added"]["record_id"]) == ["b:2"]               # 2026 is neither held-out nor development
    assert {"slide_id", "storm_id", "storm_id_2deg", "on_panel_day"} <= set(built["heldout_day"].columns)
    assert built["heldout_day"]["country"].iloc[0] == "NP"


def test_a_development_record_repeating_an_existing_positive_is_dropped():
    dev = records(("gfld", 27.70, 85.30, "2012-07-02"), ("gfld", 28.5, 85.30, "2012-07-02"))
    positives = pd.DataFrame({"cell_id": [cell(27.70, 85.30), cell(28.5, 85.3)], "event_date": pd.to_datetime(["2012-07-01"] * 2),
                              "split": ["train", "test_2018"]})
    added, dropped = asm.dev_against_existing(dev, positives)
    assert list(added["record_id"]) == ["gfld:1"] and dropped[0]["duplicate_source"] == "existing_dev"


def test_rule_qa_writes_one_record_per_admitted_row_and_a_manual_spot_check_replaces_its_row(tmp_path):
    qa = tmp_path / "qa"
    qa.mkdir()
    pd.DataFrame({"date": ["2020-07-01", "2020-07-02"], "place": ["A", "B"], "district": ["", ""], "state": ["Nepal"] * 2,
                  "source_url": ["u1", "u2"], "accuracy_km": ["2.0", "3.0"]}).to_csv(qa / "inventory_admitted.csv", index=False)
    pd.DataFrame([{"date": "2020-07-02", "place": "B", "district": "", "state": "Nepal", "source_url": "u2", "date_ok": "yes",
                   "place_ok": "yes", "is_landslide": "yes", "geocode_ok": "yes", "checked_by": "manual",
                   "note": "confirmed"}]).to_csv(qa / "spot_check.csv", index=False)
    assert asm.write_rule_qa(tmp_path, "bipad_nepal") == {"rows": 2, "manual": 1}
    written = pd.read_csv(qa / "qa_results.csv", dtype=str, keep_default_na=False)
    assert list(written["checked_by"]) == ["rule", "manual"] and written["note"].iloc[1] == "confirmed"


def test_a_spot_check_naming_no_admitted_row_is_an_error(tmp_path):
    qa = tmp_path / "qa"
    qa.mkdir()
    pd.DataFrame({"date": ["2020-07-01"], "place": ["A"], "district": [""], "state": ["Nepal"], "source_url": ["u"],
                  "accuracy_km": ["2"]}).to_csv(qa / "inventory_admitted.csv", index=False)
    pd.DataFrame([{"date": "2020-07-09", "place": "Z", "state": "Nepal"}]).to_csv(qa / "spot_check.csv", index=False)
    with pytest.raises(ValueError, match="not an admitted row"):
        asm.write_rule_qa(tmp_path, "bipad_nepal")


def test_a_frozen_directory_is_never_overwritten(tmp_path):
    frame = pd.DataFrame({"a": [1]})
    asm._write_frozen(tmp_path / "v", {"events": frame}, {"version": 2})
    frozen = json.loads((tmp_path / "v" / "FROZEN.json").read_text(encoding="utf-8"))
    assert frozen["frozen"] and set(frozen["files"]) == {"events.parquet"}
    asm._check_frozen(tmp_path / "v")
    with pytest.raises(FileExistsError):
        asm._write_frozen(tmp_path / "v", {"events": frame}, {"version": 2})
    (tmp_path / "v" / "events.parquet").write_bytes(b"changed")
    with pytest.raises(ValueError, match="does not match"):
        asm._check_frozen(tmp_path / "v")
