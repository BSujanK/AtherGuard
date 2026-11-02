import math

import pandas as pd
import pytest
from events_helpers import (COOLR_EVENTS_COLUMNS, GLC_COLUMNS, HMA_FIELDS, write_csv, write_dbf,
                            write_shp_points)

from aetherguard.audit.landslides import CatalogFormatError
from aetherguard.config import PROJECT_ROOT
from aetherguard.events import sources

COMMON = ["source", "row", "event_id", "event_date_raw", "event_date", "latitude", "longitude",
          "accuracy_raw", "accuracy_km", "trigger_raw", "country_code"]
EVENTS_COLUMNS = COMMON + ["sat_date_before", "sat_date_after", "date_window_start", "date_window_end"]


def glc_row(**kw):
    row = {"event_id": "1", "event_date": "08/01/2008 12:00:00 AM", "location_accuracy": "5km",
           "landslide_trigger": "downpour", "country_code": "IN", "latitude": "11.5", "longitude": "76.1"}
    row.update(kw)
    return row


def test_read_glc_common_columns_and_month_first_dates(tmp_path):
    path = write_csv(tmp_path / "glc.csv", GLC_COLUMNS, [
        glc_row(event_id="1", event_date="08/01/2008 12:00:00 AM"),
        glc_row(event_id="2", event_date="08/16/2016 07:22:00 PM", location_accuracy="exact"),
        glc_row(event_id="3", location_accuracy="unknown", latitude="", country_code="in "),
    ])
    df = sources.read_glc(path)
    assert list(df.columns) == COMMON
    assert (df["source"] == "glc").all()
    assert df["row"].tolist() == [0, 1, 2]
    assert df["event_id"].tolist() == [1, 2, 3]
    assert df["event_date"].tolist() == [pd.Timestamp("2008-08-01"), pd.Timestamp("2016-08-16"),
                                         pd.Timestamp("2008-08-01")]
    assert df["event_date_raw"].iloc[0] == "08/01/2008 12:00:00 AM"
    assert df["accuracy_raw"].tolist() == ["5km", "exact", "unknown"]
    assert df["accuracy_km"].iloc[0] == 5.0 and df["accuracy_km"].iloc[1] == 0.0
    assert math.isnan(df["accuracy_km"].iloc[2])
    assert math.isnan(df["latitude"].iloc[2]) and df["longitude"].iloc[2] == 76.1
    assert df["country_code"].tolist() == ["IN", "IN", "IN"]
    assert df["trigger_raw"].iloc[0] == "downpour"
    assert df.attrs["n_rows"] == 3 and df.attrs["n_deleted"] == 0


def test_read_glc_refuses_ambiguous_dates(tmp_path):
    path = write_csv(tmp_path / "glc.csv", GLC_COLUMNS, [glc_row(event_date="01/02/2009 02:00:00 AM")])
    with pytest.raises(CatalogFormatError, match="ambiguous"):
        sources.read_glc(path)


def test_read_glc_missing_column_fails_loudly(tmp_path):
    path = write_csv(tmp_path / "glc.csv", ["event_id", "event_date"], [{"event_id": "1", "event_date": "x"}])
    with pytest.raises(CatalogFormatError, match="missing required column"):
        sources.read_glc(path)


def test_read_coolr_reports_iso_dates_blank_dates_and_verbose_accuracy(tmp_path):
    path = write_csv(tmp_path / "reports.csv", GLC_COLUMNS, [
        glc_row(event_id="10", event_date="2015-12-30", location_accuracy="Known within 5 km"),
        glc_row(event_id="11", event_date="", location_accuracy="Known exactly"),
        glc_row(event_id="12", event_date="2017-06-17", location_accuracy="Known within 1 km"),
        glc_row(event_id="13", event_date="2017-06-18", location_accuracy="Unknown", latitude=""),
        glc_row(event_id="14", event_date="not a date", location_accuracy=""),
    ])
    df = sources.read_coolr_reports(path)
    assert list(df.columns) == COMMON
    assert (df["source"] == "coolr_reports").all()
    assert df["event_date"].iloc[0] == pd.Timestamp("2015-12-30")
    assert pd.isna(df["event_date"].iloc[1]) and df["event_date_raw"].iloc[1] == ""
    assert pd.isna(df["event_date"].iloc[4]) and df["event_date_raw"].iloc[4] == "not a date"
    assert df["accuracy_km"].iloc[:3].tolist() == [5.0, 0.0, 1.0]
    assert df["accuracy_km"].iloc[3:].isna().all()
    assert math.isnan(df["latitude"].iloc[3])
    assert df["event_id"].tolist() == [10, 11, 12, 13, 14]


def test_read_coolr_events_assumes_one_km_accuracy(tmp_path):
    path = write_csv(tmp_path / "events.csv", COOLR_EVENTS_COLUMNS, [
        {"event_id": "40080", "event_date": "2024-04-29", "landslide_trigger": "Heavy Rain",
         "country_code": "BR", "latitude": "-29.1", "longitude": "-51.0"},
        {"event_id": "40081", "event_date": " ", "landslide_trigger": "Cyclone",
         "country_code": "BR", "latitude": "-29.2", "longitude": "-51.1"},
    ])
    df = sources.read_coolr_events(path)
    assert list(df.columns) == EVENTS_COLUMNS
    assert (df["source"] == "coolr_events").all()
    assert sources.COOLR_EVENTS_ACCURACY_KM == 1.0
    assert (df["accuracy_km"] == 1.0).all()
    assert (df["accuracy_raw"] == "").all()
    assert df["trigger_raw"].tolist() == ["Heavy Rain", "Cyclone"]
    assert df["event_date"].iloc[0] == pd.Timestamp("2024-04-29") and pd.isna(df["event_date"].iloc[1])


def test_read_dbf_types_deleted_records_and_positions(tmp_path):
    fields = [("name", "C", 12, 0), ("count", "N", 6, 0), ("value", "F", 12, 4), ("when", "D", 8, 0)]
    records = [
        {"name": "alpha", "count": 3, "value": 1.5, "when": "20080801"},
        {"name": "gone", "count": 9, "value": 9.0, "when": "20090101"},
        {"name": "beta", "count": None, "value": None, "when": None},
    ]
    path = write_dbf(tmp_path / "t.dbf", fields, records, deleted={1})
    df, n_deleted = sources.read_dbf(path)
    assert n_deleted == 1
    assert df.index.tolist() == [0, 2]  # position in the file, so .shp records stay alignable
    assert df["name"].tolist() == ["alpha", "beta"]
    assert df["count"].iloc[0] == 3 and pd.isna(df["count"].iloc[1])
    assert df["value"].iloc[0] == 1.5 and math.isnan(df["value"].iloc[1])
    assert df["when"].tolist() == ["20080801", ""]


def test_read_dbf_honours_cpg_and_defaults_to_utf8(tmp_path):
    fields = [("name", "C", 12, 0)]
    text = "Café Noir"
    latin = write_dbf(tmp_path / "a.dbf", fields, [{"name": text}], encoding="latin-1", cpg="ISO-8859-1")
    assert sources.read_dbf(latin)[0]["name"].iloc[0] == text
    utf = write_dbf(tmp_path / "b.dbf", fields, [{"name": text}], cpg=None)
    assert sources.read_dbf(utf)[0]["name"].iloc[0] == text


def test_read_dbf_rejects_truncated_files_and_unknown_field_types(tmp_path):
    path = write_dbf(tmp_path / "t.dbf", [("name", "C", 5, 0)], [{"name": "a"}, {"name": "b"}])
    path.write_bytes(path.read_bytes()[:-8])
    with pytest.raises(CatalogFormatError, match="size") as err:
        sources.read_dbf(path)
    assert str(path) in str(err.value)
    blob = write_dbf(tmp_path / "u.dbf", [("pic", "M", 10, 0)], [{"pic": "x"}])
    with pytest.raises(CatalogFormatError, match="unsupported"):
        sources.read_dbf(blob)


def hma_record(**kw):
    rec = {"ev_id": 684, "ev_date": "20080801", "loc_accu": "5km", "ls_trig": "rain",
           "ctry_code": "NP", "latitude": 28.1, "longitude": 84.2}
    rec.update(kw)
    return rec


def test_read_hma_maps_fields_and_counts_deleted(tmp_path):
    path = write_dbf(tmp_path / "hma" / "h.dbf", HMA_FIELDS, [
        hma_record(),
        hma_record(ev_id=685, ev_date="20090230", loc_accu="unknown", ls_trig="downpour"),
        hma_record(ev_id=686, ev_date="", latitude=None),
        hma_record(ev_id=687),
    ], deleted={3})
    df = sources.read_hma(path)
    assert list(df.columns) == COMMON
    assert (df["source"] == "hma").all()
    assert df["row"].tolist() == [0, 1, 2]
    assert df["event_id"].tolist() == [684, 685, 686]
    assert df["event_date"].iloc[0] == pd.Timestamp("2008-08-01")
    assert pd.isna(df["event_date"].iloc[1]) and df["event_date_raw"].iloc[1] == "20090230"  # invalid day
    assert pd.isna(df["event_date"].iloc[2])
    assert df["accuracy_km"].iloc[0] == 5.0 and math.isnan(df["accuracy_km"].iloc[1])
    assert df["latitude"].iloc[0] == pytest.approx(28.1) and math.isnan(df["latitude"].iloc[2])
    assert df["country_code"].iloc[0] == "NP" and df["trigger_raw"].iloc[1] == "downpour"
    assert df.attrs["n_rows"] == 3 and df.attrs["n_deleted"] == 1


def test_read_shp_points_reads_coordinates_and_null_shapes(tmp_path):
    path = write_shp_points(tmp_path / "p.shp", [(107.45, 32.5625), None, (-122.663, 45.42)])
    df = sources.read_shp_points(path)
    assert df.index.tolist() == [0, 1, 2]
    assert df["longitude"].iloc[0] == 107.45 and df["latitude"].iloc[2] == 45.42
    assert math.isnan(df["latitude"].iloc[1]) and math.isnan(df["longitude"].iloc[1])


def test_read_shp_points_rejects_non_point_layers(tmp_path):
    path = write_shp_points(tmp_path / "p.shp", [(1.0, 2.0)])
    blob = bytearray(path.read_bytes())
    blob[32] = 5  # polygon
    path.write_bytes(bytes(blob))
    with pytest.raises(ValueError, match="point"):
        sources.read_shp_points(path)


HMA_DBF = PROJECT_ROOT / "data" / "raw" / "manual" / "hma" / "HMA_LS_Cat_point_v02.0.dbf"


@pytest.mark.skipif(not HMA_DBF.exists() or not HMA_DBF.with_suffix(".shp").exists(),
                    reason="real HMA shapefile not present")
def test_real_hma_dbf_coordinates_match_shp_geometry():
    table, _ = sources.read_dbf(HMA_DBF)
    geometry = sources.read_shp_points(HMA_DBF.with_suffix(".shp"))
    first = table.index[:50]
    assert len(first) == 50
    assert table.loc[first, "latitude"].to_numpy() == pytest.approx(geometry.loc[first, "latitude"].to_numpy(), abs=1e-7)
    assert table.loc[first, "longitude"].to_numpy() == pytest.approx(geometry.loc[first, "longitude"].to_numpy(), abs=1e-7)
