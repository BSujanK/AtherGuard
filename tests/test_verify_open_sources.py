"""Open inventories (W1b): BIPAD and GFLD records to raw inventory rows, the paging, and the provenance file.

Recorded-shape fixtures only; nothing touches the network or the data folder.
"""
import csv
import json
import math

import pytest

from aetherguard.verify import inventory as inv
from aetherguard.verify import open_sources as o

WARD = {"id": 7, "bbox": [85.30, 27.70, 85.34, 27.73], "centroid": {"type": "Point", "coordinates": [85.32, 27.715]},
        "title": "4", "municipality": 70}
WARDS, MUNICIPALITIES, DISTRICTS = {7: WARD}, {70: {"id": 70, "district": 9}}, {9: {"id": 9, "title_en": "Kaski"}}


def incident(**changes):
    base = {"id": 101, "title": "Landslide at Thulogaau , Rolpa Municipality-10", "wards": [7],
            "point": {"type": "Point", "coordinates": [85.32, 27.71]}, "incidentOn": "2024-07-03T00:00:00+05:45",
            "cause": None, "verified": True, "approved": True, "source": "nepal_police", "hazard": 17,
            "streetAddress": "Thulogaau "}
    return {**base, **changes}


def test_a_bipad_incident_becomes_a_located_raw_row_bounded_by_its_ward():
    row = o.bipad_rows(incident(), WARDS, MUNICIPALITIES, DISTRICTS)
    assert list(row) == list(o.RAW_HEADER)
    assert (row["event_date"], row["date_basis"], row["state"], row["district"]) == ("2024-07-03", "stated", "Nepal", "Kaski")
    assert row["place"] == "Thulogaau , Rolpa Municipality-10"
    assert (row["latitude"], row["longitude"]) == ("27.71000", "85.32000")
    farthest = max(float(o._haversine_km(27.71, 85.32, y, x)) for x in (85.30, 85.34) for y in (27.70, 27.73))
    assert float(row["accuracy_km"]) == pytest.approx(farthest, abs=0.01)
    assert (row["trigger"], row["how_found"], row["record_id"]) == ("unknown", "reported", "bipad:101")
    assert row["source_url"] == "https://bipadportal.gov.np/api/v1/incident/101/"


def test_a_point_outside_its_ward_is_left_unlocated():
    row = o.bipad_rows(incident(point={"type": "Point", "coordinates": [86.0, 27.71]}), WARDS, MUNICIPALITIES, DISTRICTS)
    assert row["latitude"] == "" and "point_outside_ward" in row["description"]


def test_an_unverified_incident_is_left_unlocated():
    row = o.bipad_rows(incident(verified=False), WARDS, MUNICIPALITIES, DISTRICTS)
    assert row["latitude"] == "" and "not verified" in row["description"]


def test_a_stated_cause_is_carried_as_the_trigger():
    assert o.bipad_rows(incident(cause="Earthquake"), WARDS, MUNICIPALITIES, DISTRICTS)["trigger"] == "Earthquake"


def gfld(**changes):
    attributes = {"FID": 18, "Latitude": 26.70861, "Longitude": 87.8562, "LandslideN": 1987, "Country": "Nepal", "Day": 19,
                  "Month": 8, "Year": 2009, "Fatalities": 2, "Trigger_": "rainfall", "Source_1": "http://n.example/1",
                  "Source_2": " ", "Source_3": " ", "Source_4": " ", "Location_M": "Mahamai-9",
                  "Precision_": 29926681.96, "Location_R": " Mahamai-9, Ilam"}
    return {"attributes": {**attributes, **changes}}


def test_a_gfld_point_becomes_a_located_row_with_the_polygon_radius_as_accuracy():
    row = o.gfld_row(gfld())
    assert (row["event_date"], row["state"], row["place"], row["trigger"]) == ("2009-08-19", "Nepal", "Mahamai-9", "rainfall")
    assert float(row["accuracy_km"]) == pytest.approx(math.sqrt(29926681.96 / math.pi) / 1000, abs=0.01)
    assert row["source_url"] == "http://n.example/1" and row["record_id"] == "gfld:1987"


def test_a_gfld_point_without_a_day_is_dropped_and_without_a_url_points_at_the_service():
    assert o.gfld_row(gfld(Day=None)) is None
    row = o.gfld_row(gfld(Source_1=" "))
    assert row["source_url"].startswith(o.GFLD_LAYER) and "FID%3D18" in row["source_url"]


def test_paging_stops_on_a_short_page():
    calls = []

    def get(url, params):
        calls.append(params["offset"])
        return {"results": [{}] * (o.BIPAD_PAGE if params["offset"] == 0 else 3)}
    assert len(o._pages("u", {}, get)) == o.BIPAD_PAGE + 3
    assert calls == [0, o.BIPAD_PAGE]


def test_fetch_and_normalise_bipad_end_to_end(tmp_path):
    tables = {"ward": [WARD], "municipality": [MUNICIPALITIES[70]], "district": [DISTRICTS[9]],
              "incident": [incident(), incident(id=102, incidentOn="2023-06-01T00:00:00+05:45"), incident()]}

    def get(url, params):
        name = url.rstrip("/").rsplit("/", 1)[-1]
        return {"results": tables[name] if params["offset"] == 0 else []}
    o.fetch_bipad(tmp_path, get=get, say=lambda m: None)
    provenance = json.loads((tmp_path / "PROVENANCE.json").read_text(encoding="utf-8"))
    assert "No licence stated" in provenance["licence"] and "api/incidents.json" in provenance["files"]
    assert o.normalise_bipad(tmp_path, say=lambda m: None) == {2023: 1, 2024: 1}      # the repeated id 101 is read once
    with (tmp_path / "raw" / "2024.csv").open(newline="", encoding="utf-8") as handle:
        (row,) = list(csv.DictReader(handle))
    assert row["record_id"] == "bipad:101"
    admitted = inv.build_inventory(tmp_path / "raw", None, out_dir=tmp_path, geocoder=lambda *a: pytest.fail("geocoded"),
                                   max_accuracy_km=5.0)
    assert len(admitted) == 2 and set(admitted["geocode_source"]) == {"source_point"}
