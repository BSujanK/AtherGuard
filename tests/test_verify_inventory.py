"""Reported-event inventory: admission, rejection reasons, de-duplication, the written files and the report.

Everything is synthetic (raw CSVs in tmp_path and an injected geocoder); nothing touches the network or the data folder.
"""
import csv
import json

import pytest

from aetherguard.verify import inventory as inv
from aetherguard.verify import ledger
from aetherguard.verify.geocode import GeocodeError

HEADER = ["event_date", "date_basis", "place", "district", "state", "source_url", "outlet", "description"]
# (lat, lon, accuracy_km, source) per place text; a missing place is ungeocodable. Wayanad and Mumbai are in the Western Ghats
# box, Gangtok in the Himalaya box, Chennai in neither.
SITES = {
    "Puthumala": (11.5000, 76.1000, 5.0, "geonames"),
    "Puthumala near": (11.5010, 76.1010, 2.0, "osm"),         # the same cell as Puthumala, better accuracy
    "Puthumala hamlet": (11.5100, 76.1100, 5.0, "geonames"),  # about 1.7 km from Puthumala, another cell
    "Meppadi": (11.5600, 76.1300, 5.0, "geonames"),           # about 8 km from Puthumala
    "Vague": (11.9000, 76.0000, 15.0, "geonames"),
    "Ten": (11.4000, 76.2000, 10.0, "osm"),
    "Gangtok": (27.3300, 88.6100, 5.0, "geonames"),
    "Mumbai": (19.0700, 72.8700, 5.0, "geonames"),
    "Chennai": (13.0800, 80.2700, 5.0, "geonames"),
}


def geocoder(place, district, state):
    return SITES.get(place)


def row(date="2024-08-01", basis="stated", place="Puthumala", district="Wayanad", state="Kerala", url="https://a.example/1",
        outlet="A", description="d"):
    return dict(zip(HEADER, [date, basis, place, district, state, url, outlet, description]))


def write_raw(tmp_path, year, *rows):
    raw = tmp_path / "raw"
    raw.mkdir(exist_ok=True)
    with (raw / f"{year}.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, HEADER)
        writer.writeheader()
        writer.writerows(rows)
    return raw


def report_of(tmp_path):
    return json.loads((tmp_path / "inventory_report.json").read_text(encoding="utf-8"))


def build(tmp_path, *rows, year=2024):
    raw = write_raw(tmp_path, year, *rows)
    admitted = inv.build_inventory(raw, None, out_dir=tmp_path, geocoder=geocoder)
    return admitted, report_of(tmp_path)


def reasons(report):
    return {(r["place"], r["reason"]) for r in report["rejected"]}


def test_a_stated_geocoded_row_is_admitted_in_the_ledger_format(tmp_path):
    admitted, report = build(tmp_path, row())
    assert len(admitted) == 1
    lines = (tmp_path / "2024.csv").read_text(encoding="utf-8").splitlines()
    assert lines[0] == "date,latitude,longitude,location_text,source_url,accuracy_km"
    assert lines[1] == '2024-08-01,11.5,76.1,"Puthumala, Wayanad, Kerala",https://a.example/1,5.0'
    assert report["rejected"] == []


def test_location_text_leaves_out_a_missing_district(tmp_path):
    build(tmp_path, row(district=""))
    assert '"Puthumala, Kerala"' in (tmp_path / "2024.csv").read_text(encoding="utf-8")


def test_report_dated_rows_are_rejected_without_geocoding(tmp_path):
    asked = []
    raw = write_raw(tmp_path, 2024, row(basis="report"))
    admitted = inv.build_inventory(raw, None, out_dir=tmp_path, geocoder=lambda *a: asked.append(a))
    assert admitted.empty and asked == []
    assert reasons(report_of(tmp_path)) == {("Puthumala", "report_dated")}


def test_an_ungeocodable_place_is_rejected_with_its_reason(tmp_path):
    _, report = build(tmp_path, row(place="Nowhere"))
    assert reasons(report) == {("Nowhere", "ungeocodable")}


def test_a_place_outside_the_domain_boxes_is_rejected_and_never_written(tmp_path):
    admitted, report = build(tmp_path, row(place="Chennai", state="Tamil Nadu"), row(place="Gangtok", district="", state="Sikkim"))
    assert list(admitted["place"]) == ["Gangtok"]
    assert reasons(report) == {("Chennai", "outside_domain")}
    assert set(ledger.load_reported(tmp_path)["location_text"]) == {"Gangtok, Sikkim"}


def test_accuracy_over_ten_km_is_kept_in_the_report_not_admitted(tmp_path):
    admitted, report = build(tmp_path, row(place="Vague"))
    assert admitted.empty
    (entry,) = report["rejected"]
    assert entry["reason"] == "accuracy_over_10km" and entry["accuracy_km"] == 15.0
    assert (tmp_path / "2024.csv").read_text(encoding="utf-8").count("\n") == 1   # the header only


def test_ten_km_exactly_is_admitted(tmp_path):
    admitted, _ = build(tmp_path, row(place="Ten"))
    assert len(admitted) == 1


def test_same_cell_and_date_across_outlets_is_one_event_keeping_the_best_accuracy(tmp_path):
    admitted, report = build(tmp_path, row(outlet="A"), row(place="Puthumala near", outlet="B", url="https://b.example/1"))
    assert list(admitted["outlet"]) == ["B"]
    assert reasons(report) == {("Puthumala", "duplicate")}


def test_equal_accuracy_keeps_the_earliest_listed(tmp_path):
    admitted, report = build(tmp_path, row(outlet="A"), row(outlet="B", url="https://b.example/1"))
    assert list(admitted["outlet"]) == ["A"]
    assert [r["outlet"] for r in report["rejected"]] == ["B"]
    assert "Puthumala on 2024-08-01 (A" in report["rejected"][0]["duplicate_of"]


def test_the_same_place_within_a_day_across_outlets_is_one_event(tmp_path):
    admitted, report = build(tmp_path, row(date="2024-08-01"),
                             row(date="2024-08-02", place="Puthumala hamlet", outlet="B"), row(date="2024-08-04", outlet="C"))
    assert sorted(admitted["outlet"]) == ["A", "C"]
    assert reasons(report) == {("Puthumala hamlet", "duplicate")}


def test_a_duplicate_group_keeps_the_best_location_and_the_earliest_stated_date(tmp_path):
    admitted, report = build(tmp_path, row(date="2024-08-01", outlet="A"),
                             row(date="2024-08-02", place="Puthumala near", outlet="B", url="https://b.example/1"))
    (event,) = admitted.to_dict("records")
    assert (event["date"], event["place"], event["outlet"], event["latitude"], event["accuracy_km"]) ==         ("2024-08-01", "Puthumala near", "B", 11.501, 2.0)
    assert "2024-08-01,11.501,76.101," in (tmp_path / "2024.csv").read_text(encoding="utf-8")
    (merged,) = report["merged_events"]
    assert merged["kept"] == {"place": "Puthumala near", "outlet": "B", "source_url": "https://b.example/1"}
    assert (merged["stated_date"], merged["date"], merged["dates"]) == ("2024-08-02", "2024-08-01", ["2024-08-01", "2024-08-02"])
    assert [(d["place"], d["event_date"], d["outlet"]) for d in merged["dropped"]] == [("Puthumala", "2024-08-01", "A")]


def test_a_group_whose_kept_row_is_also_the_earliest_changes_no_date(tmp_path):
    admitted, report = build(tmp_path, row(date="2024-08-01", place="Puthumala near"), row(date="2024-08-02", outlet="B"))
    assert list(admitted["date"]) == ["2024-08-01"]
    (merged,) = report["merged_events"]
    assert merged["stated_date"] == merged["date"] == "2024-08-01"


def test_a_row_without_duplicates_is_not_a_merged_event(tmp_path):
    _, report = build(tmp_path, row())
    assert report["merged_events"] == []


def test_a_non_finite_accuracy_is_ungeocodable(tmp_path):
    raw = write_raw(tmp_path, 2024, row(place="Nan"), row(place="Inf"), row(place="Puthumala"))
    sites = {**SITES, "Nan": (11.5, 76.1, float("nan"), "osm"), "Inf": (11.6, 76.2, float("inf"), "osm")}
    admitted = inv.build_inventory(raw, None, out_dir=tmp_path, geocoder=lambda p, d, s: sites.get(p))
    assert list(admitted["place"]) == ["Puthumala"]
    assert reasons(report_of(tmp_path)) == {("Nan", "ungeocodable"), ("Inf", "ungeocodable")}


def test_a_place_more_than_five_km_away_or_two_days_later_is_a_separate_event(tmp_path):
    admitted, _ = build(tmp_path, row(), row(place="Meppadi", outlet="B"), row(date="2024-08-03", outlet="C"))
    assert len(admitted) == 3


def test_a_rejected_row_does_not_suppress_an_admitted_one(tmp_path):
    admitted, _ = build(tmp_path, row(place="Vague"), row(place="Puthumala"))
    assert list(admitted["place"]) == ["Puthumala"]


def test_the_combined_file_carries_the_qa_columns(tmp_path):
    build(tmp_path, row(outlet="Hindu", description="Slide at dusk"))
    with (tmp_path / "qa" / "inventory_admitted.csv").open(newline="", encoding="utf-8") as handle:
        (record,) = list(csv.DictReader(handle))
    assert list(record) == ["date", "latitude", "longitude", "location_text", "source_url", "accuracy_km", "year", "place",
                            "district", "state", "outlet", "geocode_source", "description"]
    assert (record["year"], record["geocode_source"], record["outlet"]) == ("2024", "geonames", "Hindu")


def test_the_combined_file_is_in_a_folder_the_ledger_does_not_scan(tmp_path):
    admitted, _ = build(tmp_path, row(), row(date="2024-09-01", place="Gangtok", state="Sikkim"))
    assert not (tmp_path / "inventory_admitted.csv").exists()
    assert len(ledger.load_reported(tmp_path)) == len(admitted) == 2   # a count, not a set: no event is read twice


def test_ledger_accepts_the_output(tmp_path):
    build(tmp_path, row(), row(date="2024-09-01", place="Gangtok", state="Sikkim", district="East Sikkim"))
    events = ledger.load_reported(tmp_path)
    assert set(events["location_text"]) == {"Puthumala, Wayanad, Kerala", "Gangtok, East Sikkim, Sikkim"}
    assert events["cell_id"].nunique() == 2


def test_the_report_counts_per_year_and_region(tmp_path):
    raw = write_raw(tmp_path, 2023, row(date="2023-07-01", place="Gangtok", state="Sikkim"),
                    row(date="2023-07-02", basis="report", place="Gangtok", state="Sikkim"))
    write_raw(tmp_path, 2024, row(), row(place="Nowhere"), row(place="Vague"), row(place="Mumbai", state="Maharashtra"),
              row(outlet="B"), row(place="Chennai", state="Tamil Nadu"))
    inv.build_inventory(raw, None, out_dir=tmp_path, geocoder=geocoder)
    report = report_of(tmp_path)
    y23, y24 = report["years"]["2023"], report["years"]["2024"]
    assert (y23["raw"], y23["stated"], y23["geocoded"], y23["admitted"]) == (2, 1, 1, 1)
    assert y23["rejected"] == {"report_dated": 1}
    assert y23["by_region"]["himalaya"] == {"geocoded": 1, "admitted": 1}
    assert (y24["raw"], y24["stated"], y24["geocoded"], y24["admitted"]) == (6, 6, 5, 2)
    assert y24["geocoded_by_source"] == {"geonames": 5}
    assert y24["rejected"] == {"ungeocodable": 1, "accuracy_over_10km": 1, "duplicate": 1, "outside_domain": 1}
    assert y24["by_region"] == {"himalaya": {"geocoded": 0, "admitted": 0}, "western_ghats": {"geocoded": 4, "admitted": 2},
                                "outside_domain": {"geocoded": 1, "admitted": 0}}
    assert (report["totals"]["raw"], report["totals"]["admitted"]) == (8, 3)
    assert report["totals"]["rejected"]["report_dated"] == 1
    assert report["osm_fetched"] == 0


def test_the_default_geocoder_is_geocode_any_with_the_cache_and_counts_fetches(tmp_path, monkeypatch):
    calls = []

    def fake_any(place, district, state, places, fetch=None, cache=None):
        calls.append((place, district, state, places, cache))
        fetch("q")                                          # one query was not cached and went out
        return 11.5, 76.1, 5.0, "osm"

    monkeypatch.setattr(inv, "geocode_any", fake_any)
    raw = write_raw(tmp_path, 2024, row())
    inv.build_inventory(raw, "PLACES", out_dir=tmp_path, fetch=lambda q: [], cache=tmp_path / "cache")
    assert calls == [("Puthumala", "Wayanad", "Kerala", "PLACES", tmp_path / "cache")]
    assert report_of(tmp_path)["osm_fetched"] == 1


def test_offline_raises_on_a_cache_miss_naming_the_query_and_never_fetches(tmp_path, monkeypatch):
    fetched = []

    def fake_any(place, district, state, places, fetch=None, cache=None):
        return fetch(f"{place}, {district}, {state}, India")

    monkeypatch.setattr(inv, "geocode_any", fake_any)
    raw = write_raw(tmp_path, 2024, row())
    with pytest.raises(GeocodeError, match="Puthumala, Wayanad, Kerala, India"):
        inv.build_inventory(raw, "PLACES", out_dir=tmp_path, fetch=fetched.append, offline=True)
    assert fetched == []


def test_offline_with_every_query_cached_builds(tmp_path, monkeypatch):
    monkeypatch.setattr(inv, "geocode_any", lambda place, district, state, places, fetch=None, cache=None: SITES.get(place))
    raw = write_raw(tmp_path, 2024, row())
    admitted = inv.build_inventory(raw, "PLACES", out_dir=tmp_path, offline=True)
    assert len(admitted) == 1 and report_of(tmp_path)["osm_fetched"] == 0


def test_out_dir_defaults_to_the_parent_of_the_raw_folder(tmp_path):
    raw = write_raw(tmp_path, 2024, row())
    inv.build_inventory(raw, None, geocoder=geocoder)
    assert (tmp_path / "2024.csv").exists() and (tmp_path / "inventory_report.json").exists()


@pytest.mark.parametrize("bad", [row(date="01/08/2024"), row(basis="maybe"), row(url=" "), row(date="2023-08-01")])
def test_a_malformed_raw_row_stops_the_build_naming_the_file_and_line(tmp_path, bad):
    raw = write_raw(tmp_path, 2024, row(), bad)
    with pytest.raises(ValueError, match=r"2024\.csv line 3"):
        inv.build_inventory(raw, None, out_dir=tmp_path, geocoder=geocoder)


def test_a_missing_column_stops_the_build(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "2024.csv").write_text("event_date,place\n2024-08-01,X\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing column"):
        inv.build_inventory(raw, None, out_dir=tmp_path, geocoder=geocoder)


def test_a_raw_folder_without_year_files_is_an_error(tmp_path):
    (tmp_path / "raw").mkdir()
    with pytest.raises(ValueError, match=r"no <year>\.csv"):
        inv.build_inventory(tmp_path / "raw", None, out_dir=tmp_path, geocoder=geocoder)


def test_write_inventory_says_one_line_per_year_and_the_fetch_count(tmp_path, monkeypatch):
    monkeypatch.setattr(inv, "geocode_any", lambda place, district, state, places, fetch=None, cache=None: SITES.get(place))
    write_raw(tmp_path, 2023, row(date="2023-07-01", place="Gangtok", state="Sikkim"))
    write_raw(tmp_path, 2024, row(), row(place="Nowhere"))
    said = []
    admitted = inv.write_inventory(tmp_path, None, said.append)
    assert len(admitted) == 2
    assert said[:2] == ["2023: 1 raw, 1 stated, 1 geocoded, 1 admitted", "2024: 2 raw, 2 stated, 1 geocoded, 1 admitted"]
    assert said[2].startswith("2 admitted of 3; 0 Nominatim query(ies) fetched")


def test_a_merged_event_is_filed_under_the_year_of_its_earliest_date(tmp_path):
    raw = write_raw(tmp_path, 2023, row(date="2023-12-31"))
    write_raw(tmp_path, 2024, row(date="2024-01-01", place="Puthumala near", outlet="B"))
    admitted = inv.build_inventory(raw, None, out_dir=tmp_path, geocoder=geocoder)
    assert list(admitted["year"]) == [2023]
    assert "2023-12-31,11.501" in (tmp_path / "2023.csv").read_text(encoding="utf-8")
    assert (tmp_path / "2024.csv").read_text(encoding="utf-8").count("\n") == 1


def test_write_inventory_passes_offline_on(tmp_path, monkeypatch):
    def fake_any(place, district, state, places, fetch=None, cache=None):
        fetch("q")
        return SITES[place]

    monkeypatch.setattr(inv, "geocode_any", fake_any)
    write_raw(tmp_path, 2024, row())
    with pytest.raises(GeocodeError, match="offline"):
        inv.write_inventory(tmp_path, None, lambda m: None, offline=True)


# --- QA corrections ---------------------------------------------------------------------------------------------------

CORRECTION_HEADER = ["date", "place", "state", "action", "latitude", "longitude", "accuracy_km", "reason", "source_url"]


def correction(action="correct", date="2024-08-01", place="Puthumala", state="Kerala", lat="11.4", lon="76.2", accuracy="5",
               reason="namesake elsewhere", url="https://w.example/p"):
    return dict(zip(CORRECTION_HEADER, [date, place, state, action, lat, lon, accuracy, reason, url]))


def write_corrections(tmp_path, *rows):
    (tmp_path / "qa").mkdir(exist_ok=True)
    with (tmp_path / "qa" / "corrections.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, CORRECTION_HEADER)
        writer.writeheader()
        writer.writerows(rows)


def test_a_correction_moves_the_event_and_keeps_it_admitted(tmp_path):
    write_corrections(tmp_path, correction())
    admitted, report = build(tmp_path, row())
    (event,) = admitted.to_dict("records")
    assert (event["latitude"], event["longitude"], event["accuracy_km"], event["geocode_source"]) == (11.4, 76.2, 5.0, "qa_correction")
    assert "2024-08-01,11.4,76.2," in (tmp_path / "2024.csv").read_text(encoding="utf-8")
    (applied,) = report["corrections"]
    assert applied["action"] == "correct" and applied["reason"] == "namesake elsewhere"
    assert applied["source_url"] == "https://w.example/p"
    assert applied["geocoded"] == {"latitude": 11.5, "longitude": 76.1, "accuracy_km": 5.0, "source": "geonames"}
    assert applied["rows"] == 1 and report["rejected"] == []


def test_a_correction_rescues_an_ungeocodable_place(tmp_path):
    write_corrections(tmp_path, correction(place="Nowhere"))
    admitted, report = build(tmp_path, row(place="Nowhere"))
    assert list(admitted["place"]) == ["Nowhere"]
    assert report["corrections"][0]["geocoded"] is None


def test_a_corrected_point_still_goes_through_the_domain_and_accuracy_checks(tmp_path):
    write_corrections(tmp_path, correction(lat="13.08", lon="80.27"),
                      correction(place="Gangtok", lat="27.33", lon="88.61", accuracy="12"))
    _, report = build(tmp_path, row(), row(place="Gangtok", state="Kerala"))
    assert reasons(report) == {("Puthumala", "outside_domain"), ("Gangtok", "accuracy_over_10km")}


def test_an_exclusion_rejects_the_row_with_the_given_reason(tmp_path):
    write_corrections(tmp_path, correction("exclude", lat="", lon="", accuracy="", reason="boundary wall collapse"))
    admitted, report = build(tmp_path, row(), row(place="Gangtok", state="Sikkim"))
    assert list(admitted["place"]) == ["Gangtok"]
    (entry,) = report["rejected"]
    assert (entry["place"], entry["reason"], entry["qa_reason"]) == ("Puthumala", "qa_excluded", "boundary wall collapse")
    assert report["totals"]["rejected"] == {"qa_excluded": 1}
    assert report["corrections"][0]["action"] == "exclude"


def test_an_exclusion_applies_to_the_whole_duplicate_group_whichever_row_is_keyed(tmp_path):
    write_corrections(tmp_path, correction("exclude", place="Puthumala near", lat="", lon="", accuracy="", reason="not a slide"))
    admitted, report = build(tmp_path, row(), row(place="Puthumala near", outlet="B"))
    assert admitted.empty
    by_place = {r["place"]: r for r in report["rejected"]}
    assert {p: r["reason"] for p, r in by_place.items()} == {"Puthumala": "qa_excluded", "Puthumala near": "qa_excluded"}
    assert by_place["Puthumala near"]["qa_reason"] == "not a slide"
    assert by_place["Puthumala"]["qa_reason"] == "not a slide (same event as Puthumala near on 2024-08-01)"


def test_an_exclusion_also_removes_a_differently_spelled_twin_within_a_day_and_five_km(tmp_path):
    write_corrections(tmp_path, correction("exclude", lat="", lon="", accuracy="", reason="wall collapse"))
    admitted, report = build(tmp_path, row(), row(date="2024-08-02", place="Puthumala hamlet", outlet="B"),
                             row(date="2024-08-01", place="Gangtok", district="", state="Sikkim"))
    assert list(admitted["place"]) == ["Gangtok"]
    assert reasons(report) == {("Puthumala", "qa_excluded"), ("Puthumala hamlet", "qa_excluded")}
    assert report["totals"]["rejected"] == {"qa_excluded": 2}
    assert report["corrections"][0]["group_rows"] == 2


def test_an_exclusion_leaves_a_row_beyond_the_duplicate_rule_alone(tmp_path):
    write_corrections(tmp_path, correction("exclude", lat="", lon="", accuracy=""))
    admitted, _ = build(tmp_path, row(), row(place="Meppadi", outlet="B"), row(date="2024-08-03", outlet="C"))
    assert sorted(admitted["outlet"]) == ["B", "C"]


def test_a_correction_moves_the_groups_survivor_and_leaves_no_twin_as_a_separate_event(tmp_path):
    write_corrections(tmp_path, correction(lat="11.4", lon="76.2", accuracy="4"))
    admitted, report = build(tmp_path, row(), row(date="2024-08-02", place="Puthumala hamlet", outlet="B"))
    (event,) = admitted.to_dict("records")
    assert (event["place"], event["date"], event["latitude"], event["geocode_source"]) == ("Puthumala", "2024-08-01", 11.4, "qa_correction")
    assert reasons(report) == {("Puthumala hamlet", "duplicate")}
    (merged,) = report["merged_events"]
    assert merged["dates"] == ["2024-08-01", "2024-08-02"] and [d["place"] for d in merged["dropped"]] == ["Puthumala hamlet"]


def test_a_correction_keyed_on_the_beaten_twin_moves_the_survivor(tmp_path):
    write_corrections(tmp_path, correction(place="Puthumala hamlet", date="2024-08-02", lat="11.4", lon="76.2", accuracy="4"))
    admitted, report = build(tmp_path, row(), row(date="2024-08-02", place="Puthumala hamlet", outlet="B"))
    (event,) = admitted.to_dict("records")
    assert (event["place"], event["latitude"], event["geocode_source"]) == ("Puthumala", 11.4, "qa_correction")
    assert reasons(report) == {("Puthumala hamlet", "duplicate")}


def test_a_corrected_survivor_still_meets_a_duplicate_it_was_moved_onto(tmp_path):
    write_corrections(tmp_path, correction(place="Puthumala", lat="11.56", lon="76.13", accuracy="9"))
    admitted, report = build(tmp_path, row(), row(place="Meppadi", outlet="B"))
    assert list(admitted["place"]) == ["Meppadi"]
    assert reasons(report) == {("Puthumala", "duplicate")}


def test_an_exclusion_wins_over_a_correction_in_the_same_group(tmp_path):
    write_corrections(tmp_path, correction(), correction("exclude", place="Puthumala near", lat="", lon="", accuracy=""))
    admitted, report = build(tmp_path, row(), row(place="Puthumala near", outlet="B"))
    assert admitted.empty and report["totals"]["rejected"] == {"qa_excluded": 2}


def test_two_corrections_in_one_duplicate_group_raise(tmp_path):
    write_corrections(tmp_path, correction(), correction(place="Puthumala near", lat="11.41"))
    with pytest.raises(ValueError, match="same duplicate group"):
        build(tmp_path, row(), row(place="Puthumala near", outlet="B"))


def test_a_correction_matching_no_raw_row_raises_naming_the_key(tmp_path):
    write_corrections(tmp_path, correction(place="Elsewhere"))
    with pytest.raises(ValueError, match=r"2024-08-01.*Elsewhere.*Kerala"):
        build(tmp_path, row())


def test_a_correction_for_a_report_dated_row_raises(tmp_path):
    write_corrections(tmp_path, correction())
    with pytest.raises(ValueError, match="report-dated"):
        build(tmp_path, row(basis="report"))


def test_without_a_corrections_file_nothing_changes(tmp_path):
    admitted, report = build(tmp_path, row())
    assert list(admitted["geocode_source"]) == ["geonames"] and report["corrections"] == []


def test_an_explicit_corrections_path_is_used(tmp_path):
    write_corrections(tmp_path, correction())
    moved = tmp_path / "elsewhere.csv"
    (tmp_path / "qa" / "corrections.csv").rename(moved)
    raw = write_raw(tmp_path, 2024, row())
    admitted = inv.build_inventory(raw, None, out_dir=tmp_path, geocoder=geocoder, corrections=moved)
    assert list(admitted["geocode_source"]) == ["qa_correction"]


@pytest.mark.parametrize("bad, message", [
    (correction("fix"), "action"),
    (correction(lat=""), "latitude"),
    (correction(accuracy="-1"), "accuracy_km"),
    (correction(lat="abc"), "latitude"),
    (correction("exclude"), "empty"),
    (correction(url=" "), "source_url"),
    (correction(reason=""), "reason"),
    (correction(date="1/8/2024"), "date"),
])
def test_a_malformed_correction_stops_the_build_naming_the_line(tmp_path, bad, message):
    write_corrections(tmp_path, bad)
    with pytest.raises(ValueError, match=rf"corrections\.csv line 2: .*{message}"):
        build(tmp_path, row())


def test_two_corrections_for_one_event_raise(tmp_path):
    write_corrections(tmp_path, correction(), correction())
    with pytest.raises(ValueError, match="line 3: .*twice"):
        build(tmp_path, row())


# --- QA coverage ------------------------------------------------------------------------------------------------------

QA_HEADER = ["date", "place", "district", "state", "source_url", "date_ok", "place_ok", "is_landslide", "geocode_ok", "note"]


def write_qa_results(tmp_path, *keys):
    (tmp_path / "qa").mkdir(exist_ok=True)
    with (tmp_path / "qa" / "qa_results.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(QA_HEADER)
        for date, place, state in keys:
            writer.writerow([date, place, "", state, "u", "yes", "yes", "yes", "yes", ""])


def test_admitted_rows_without_a_qa_result_are_listed_as_unchecked(tmp_path):
    write_qa_results(tmp_path, ("2024-08-01", "Puthumala", "Kerala"))
    admitted, report = build(tmp_path, row(), row(date="2024-09-01", place="Gangtok", district="", state="Sikkim"))
    assert len(admitted) == 2
    assert [(u["date"], u["place"], u["state"]) for u in report["unchecked"]] == [("2024-09-01", "Gangtok", "Sikkim")]
    assert report["totals"]["unchecked"] == 1


def test_every_admitted_row_checked_leaves_nothing_unchecked(tmp_path):
    write_qa_results(tmp_path, ("2024-08-01", "Puthumala", "Kerala"), ("2024-07-01", "Elsewhere", "Kerala"))
    _, report = build(tmp_path, row())
    assert report["unchecked"] == [] and report["totals"]["unchecked"] == 0


def test_without_a_qa_results_file_every_admitted_row_is_unchecked(tmp_path):
    _, report = build(tmp_path, row())
    assert [u["place"] for u in report["unchecked"]] == ["Puthumala"]


def test_a_merged_event_is_checked_by_its_admitted_date(tmp_path):
    write_qa_results(tmp_path, ("2024-08-01", "Puthumala near", "Kerala"))
    _, report = build(tmp_path, row(date="2024-08-02"), row(date="2024-08-01", place="Puthumala near", outlet="B"))
    assert report["unchecked"] == []


def test_write_inventory_says_how_many_admitted_rows_are_unchecked(tmp_path, monkeypatch):
    monkeypatch.setattr(inv, "geocode_any", lambda place, district, state, places, fetch=None, cache=None: SITES.get(place))
    write_raw(tmp_path, 2024, row())
    said = []
    inv.write_inventory(tmp_path, None, said.append)
    assert said[-1] == "1 admitted row(s) have no result in qa/qa_results.csv"
    write_qa_results(tmp_path, ("2024-08-01", "Puthumala", "Kerala"))
    said.clear()
    inv.write_inventory(tmp_path, None, said.append)
    assert said[-1] == "every admitted row has a result in qa/qa_results.csv"
