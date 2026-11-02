"""Reader integrity: date windows, timezone refusal and typed failures."""
import pandas as pd
import pytest
from events_helpers import COOLR_EVENTS_COLUMNS, GLC_COLUMNS, HMA_FIELDS, write_csv, write_dbf

from aetherguard.audit.landslides import CatalogFormatError
from aetherguard.events import sources


def glc_row(**kw):
    row = {"event_id": "1", "event_date": "2015-01-01", "location_accuracy": "5km",
           "landslide_trigger": "rain", "country_code": "IN", "latitude": "11.5", "longitude": "76.1"}
    row.update(kw)
    return row


def event_row(**kw):
    row = {"event_id": "1", "event_date": "2023-07-09", "landslide_trigger": "Rain", "country_code": "IN",
           "latitude": "30.0", "longitude": "79.0", "sat_date_before": "", "sat_date_after": ""}
    row.update(kw)
    return row


def test_read_coolr_events_keeps_satellite_dates_and_parses_the_window(tmp_path):
    path = write_csv(tmp_path / "events.csv", COOLR_EVENTS_COLUMNS, [
        event_row(event_id="1", sat_date_before="2023-06-16", sat_date_after="2023-07-31"),
        event_row(event_id="2", sat_date_before="2023-07-10, 2023-07-09",
                  sat_date_after="2023-08-12, 2023-08-16"),  # lists: the widest window
        event_row(event_id="3", sat_date_before="", sat_date_after="2023-07-31"),
        event_row(event_id="4", sat_date_before="2023-07-2", sat_date_after="2023-07-31"),  # never guessed
        event_row(event_id="5", sat_date_before="2023-06-16", sat_date_after="2023-02-30"),  # impossible
        event_row(event_id="6", sat_date_before="2023-06-16", sat_date_after="2023-07-31, junk"),
    ])
    df = sources.read_coolr_events(path)
    assert df["sat_date_before"].tolist() == ["2023-06-16", "2023-07-10, 2023-07-09", "", "2023-07-2",
                                              "2023-06-16", "2023-06-16"]
    assert df["sat_date_after"].iloc[1] == "2023-08-12, 2023-08-16"
    start, end = df["date_window_start"], df["date_window_end"]
    assert (start.iloc[0], end.iloc[0]) == (pd.Timestamp("2023-06-16"), pd.Timestamp("2023-07-31"))
    assert (start.iloc[1], end.iloc[1]) == (pd.Timestamp("2023-07-09"), pd.Timestamp("2023-08-16"))
    assert pd.isna(start.iloc[2]) and end.iloc[2] == pd.Timestamp("2023-07-31")
    assert pd.isna(start.iloc[3]) and end.iloc[3] == pd.Timestamp("2023-07-31")
    assert pd.isna(end.iloc[4]) and pd.isna(end.iloc[5])
    assert start.iloc[4] == pd.Timestamp("2023-06-16")


def test_read_coolr_events_requires_the_satellite_date_columns(tmp_path):
    path = write_csv(tmp_path / "events.csv", COOLR_EVENTS_COLUMNS[:-2], [])
    with pytest.raises(CatalogFormatError, match="sat_date_before"):
        sources.read_coolr_events(path)


@pytest.mark.parametrize("value", ["2023-07-09T10:30:00Z", "2023-07-09 10:30:00+05:30",
                                   "2023-07-09T10:30:00-0500", "2023-07-09T10:30z"])
def test_utc_offsets_are_rejected_loudly_and_never_converted(tmp_path, value):
    reports = write_csv(tmp_path / "reports.csv", GLC_COLUMNS,
                        [glc_row(event_id="1"), glc_row(event_id="2", event_date=value)])
    with pytest.raises(CatalogFormatError, match="UTC offset") as err:
        sources.read_coolr_reports(reports)
    assert str(reports) in str(err.value) and value in str(err.value)
    events = write_csv(tmp_path / "events.csv", COOLR_EVENTS_COLUMNS, [event_row(event_date=value)])
    with pytest.raises(CatalogFormatError, match="UTC offset"):
        sources.read_coolr_events(events)


def test_dates_without_an_offset_are_accepted(tmp_path):
    path = write_csv(tmp_path / "reports.csv", GLC_COLUMNS, [
        glc_row(event_id="1"), glc_row(event_id="2", event_date="2015-01-02 10:30:00"),
        glc_row(event_id="3", event_date="2015-01-03T10:30:00")])
    assert sources.read_coolr_reports(path)["event_date"].notna().all()


def test_glc_dates_with_an_offset_are_rejected(tmp_path):
    path = write_csv(tmp_path / "glc.csv", GLC_COLUMNS, [
        glc_row(event_id="1", event_date="08/16/2016 07:22:00 PM"),
        glc_row(event_id="2", event_date="08/17/2016 07:22:00 +05:30")])
    with pytest.raises(CatalogFormatError, match="UTC offset"):
        sources.read_glc(path)


@pytest.mark.parametrize("reader", [sources.read_glc, sources.read_coolr_reports, sources.read_coolr_events])
def test_zero_byte_csv_is_a_typed_failure(tmp_path, reader):
    path = tmp_path / "empty.csv"
    path.write_bytes(b"")
    with pytest.raises(CatalogFormatError, match="empty") as err:
        reader(path)
    assert str(path) in str(err.value)


def test_latin1_csv_with_a_bom_parses(tmp_path):
    path = tmp_path / "glc.csv"
    text = (",".join(GLC_COLUMNS) + "\n1,08/16/2016 07:22:00 PM,5km,rain,IN,11.5,76.1\n"
            "2,08/17/2016 07:22:00 PM,5km,café,IN,11.5,76.1\n")
    path.write_bytes(b"\xef\xbb\xbf" + text.encode("latin-1"))
    df = sources.read_glc(path)
    assert df["event_id"].tolist() == [1, 2] and df["trigger_raw"].iloc[1] == "café"


def test_duplicate_column_names_after_normalisation_fail_loudly(tmp_path):
    path = tmp_path / "glc.csv"
    path.write_text(",".join([*GLC_COLUMNS, "Event Date"]) + "\n", encoding="utf-8")  # same as event_date
    with pytest.raises(CatalogFormatError, match="duplicate") as err:
        sources.read_glc(path)
    assert str(path) in str(err.value) and "event_date" in str(err.value)


def test_csv_headers_are_matched_after_normalisation(tmp_path):
    header = [" Event_ID " if c == "event_id" else c.upper() for c in GLC_COLUMNS]
    path = tmp_path / "glc.csv"
    path.write_text(",".join(header) + "\n1,08/16/2016 07:22:00 PM,5km,rain,IN,11.5,76.1\n", encoding="utf-8")
    assert sources.read_glc(path)["event_id"].tolist() == [1]


def test_dbf_size_must_match_the_record_count(tmp_path):
    path = write_dbf(tmp_path / "t.dbf", [("name", "C", 5, 0)], [{"name": "a"}, {"name": "b"}])
    good = path.read_bytes()
    assert good[-1] == 0x1A
    path.write_bytes(good[:-1])  # the EOF marker is optional
    assert len(sources.read_dbf(path)[0]) == 2
    path.write_bytes(good + b"\x1a")  # but a second trailing byte is not allowed
    with pytest.raises(CatalogFormatError, match="size") as err:
        sources.read_dbf(path)
    assert str(path) in str(err.value) and "expected" in str(err.value)
    path.write_bytes(good[:-1] + b"X" * 5 + b"\x1a")  # a record the header does not count
    with pytest.raises(CatalogFormatError, match="size"):
        sources.read_dbf(path)


def test_dbf_invalid_utf8_without_cpg_fails_loudly(tmp_path):
    path = write_dbf(tmp_path / "t.dbf", [("name", "C", 12, 0)], [{"name": "Café"}],
                     encoding="latin-1", cpg=None)
    with pytest.raises(CatalogFormatError, match="decode") as err:
        sources.read_dbf(path)
    assert str(path) in str(err.value) and "name" in str(err.value)


def test_dbf_malformed_number_names_the_field_and_record(tmp_path):
    record = {"ev_id": 2, "ev_date": "20150101", "loc_accu": "1km", "ls_trig": "rain", "ctry_code": "IN",
              "latitude": "12.x", "longitude": 79.0}
    good = {**record, "ev_id": 1, "latitude": 12.0}
    path = write_dbf(tmp_path / "t.dbf", HMA_FIELDS, [good, record])
    with pytest.raises(CatalogFormatError, match="latitude") as err:
        sources.read_hma(path)
    assert str(path) in str(err.value) and "record 1" in str(err.value)


def test_read_dbf_columns_limits_what_is_parsed(tmp_path):
    fields = [("name", "C", 12, 0), ("junk", "N", 6, 0), ("value", "F", 12, 4)]
    path = write_dbf(tmp_path / "t.dbf", fields, [{"name": "a", "junk": "zz", "value": 1.0}])
    with pytest.raises(CatalogFormatError, match="junk"):
        sources.read_dbf(path)
    table, _ = sources.read_dbf(path, columns=["name", "value"])
    assert list(table.columns) == ["name", "value"] and table["value"].iloc[0] == 1.0
