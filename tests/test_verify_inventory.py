"""Reported-event inventory: admission, rejection reasons, de-duplication, the written files and the report.

Everything is synthetic (raw CSVs in tmp_path and an injected geocoder); nothing touches the network or the data folder.
"""
import csv
import json

import pytest

from aetherguard.verify import inventory as inv
from aetherguard.verify import ledger

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


def test_a_place_more_than_five_km_away_or_two_days_later_is_a_separate_event(tmp_path):
    admitted, _ = build(tmp_path, row(), row(place="Meppadi", outlet="B"), row(date="2024-08-03", outlet="C"))
    assert len(admitted) == 3


def test_a_rejected_row_does_not_suppress_an_admitted_one(tmp_path):
    admitted, _ = build(tmp_path, row(place="Vague"), row(place="Puthumala"))
    assert list(admitted["place"]) == ["Puthumala"]


def test_the_combined_file_carries_the_qa_columns(tmp_path):
    build(tmp_path, row(outlet="Hindu", description="Slide at dusk"))
    with (tmp_path / "inventory_admitted.csv").open(newline="", encoding="utf-8") as handle:
        (record,) = list(csv.DictReader(handle))
    assert list(record) == ["date", "latitude", "longitude", "location_text", "source_url", "accuracy_km", "year", "place",
                            "district", "state", "outlet", "geocode_source", "description"]
    assert (record["year"], record["geocode_source"], record["outlet"]) == ("2024", "geonames", "Hindu")


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
