import math

import pytest

from aetherguard.audit import landslides as ls


def write_csv(tmp_path, text, name="catalog.csv", encoding="utf-8-sig"):
    path = tmp_path / name
    path.write_text(text, encoding=encoding, newline="")
    return path


HEADER = "event_id,event_date,latitude,longitude,location_accuracy,landslide_trigger,country_name\n"


def test_parse_accuracy_km_variants():
    assert ls.parse_accuracy_km("5km") == 5.0
    assert ls.parse_accuracy_km("10 km") == 10.0
    assert ls.parse_accuracy_km("exact") == 0.0
    assert ls.parse_accuracy_km("25") == 25.0
    for unknown in ("unknown", "", None, float("nan")):
        assert math.isnan(ls.parse_accuracy_km(unknown))


def test_bom_iso_dates_and_unknown_accuracy(tmp_path):
    path = write_csv(tmp_path, HEADER
                     + "1,2018-08-16,11.55,76.13,5km,downpour,India\n"
                     + "2,2018-08-17,27.70,85.30,unknown,downpour,Nepal\n")
    df, report = ls.read_catalog_csv(path)
    assert report.total_rows == 2 and report.kept_rows == 2
    assert df["event_date"].dt.strftime("%Y-%m-%d").tolist() == ["2018-08-16", "2018-08-17"]
    assert df["accuracy_km"].iloc[0] == 5.0 and math.isnan(df["accuracy_km"].iloc[1])
    assert df["region"].tolist() == ["western_ghats", "himalaya"]


def test_slash_dates_are_parsed_month_first_when_unambiguous(tmp_path):
    path = write_csv(tmp_path, HEADER
                     + "1,03/27/2013 12:00:00 AM,11.55,76.13,5km,rain,India\n"
                     + "2,04/02/2013 12:00:00 AM,11.60,76.10,5km,rain,India\n")
    df, _ = ls.read_catalog_csv(path)
    assert df["event_date"].dt.strftime("%Y-%m-%d").tolist() == ["2013-03-27", "2013-04-02"]


def test_slash_dates_are_parsed_day_first_when_unambiguous(tmp_path):
    path = write_csv(tmp_path, HEADER + "1,27/03/2013,11.55,76.13,5km,rain,India\n"
                     + "2,02/04/2013,11.60,76.10,5km,rain,India\n")
    df, _ = ls.read_catalog_csv(path)
    assert df["event_date"].dt.strftime("%Y-%m-%d").tolist() == ["2013-03-27", "2013-04-02"]


def test_ambiguous_slash_dates_raise_instead_of_guessing(tmp_path):
    path = write_csv(tmp_path, HEADER + "1,03/04/2013,11.55,76.13,5km,rain,India\n")
    with pytest.raises(ls.CatalogFormatError, match="ambiguous"):
        ls.read_catalog_csv(path)


def test_inconsistent_slash_dates_raise(tmp_path):
    path = write_csv(tmp_path, HEADER + "1,27/03/2013,11.55,76.13,5km,rain,India\n"
                     + "2,03/27/2013,11.55,76.13,5km,rain,India\n")
    with pytest.raises(ls.CatalogFormatError, match="inconsistent"):
        ls.read_catalog_csv(path)


def test_bad_dates_and_coordinates_are_dropped_but_counted(tmp_path):
    path = write_csv(tmp_path, HEADER
                     + "1,2018-08-16,11.55,76.13,5km,rain,India\n"      # good
                     + "2,not-a-date,11.55,76.13,5km,rain,India\n"       # bad date
                     + "3,2018-08-16,,76.13,5km,rain,India\n"            # blank latitude
                     + "4,2018-08-16,0,0,5km,rain,India\n"               # null island
                     + "5,2018-08-16,95.0,76.13,5km,rain,India\n")       # out of range
    df, report = ls.read_catalog_csv(path)
    assert report.total_rows == 5
    assert report.dropped_bad_date == 1
    assert report.dropped_bad_coordinates == 3
    assert report.kept_rows == 1 and len(df) == 1


def test_missing_required_column_lists_what_was_found(tmp_path):
    path = write_csv(tmp_path, "id,when,lat\n1,2018-08-16,11.5\n")
    with pytest.raises(ls.CatalogFormatError) as info:
        ls.read_catalog_csv(path)
    assert "longitude" in str(info.value) and "id" in str(info.value)


def test_semicolon_delimited_file_is_rejected_clearly(tmp_path):
    path = write_csv(tmp_path, "event_date;latitude;longitude\n2018-08-16;11.5;76.1\n")
    with pytest.raises(ls.CatalogFormatError, match="delimiter"):
        ls.read_catalog_csv(path)


def test_latin1_file_is_read(tmp_path):
    path = write_csv(tmp_path, HEADER + "1,2018-08-16,11.55,76.13,5km,rain,Côte\n", encoding="latin-1")
    df, _ = ls.read_catalog_csv(path)
    assert len(df) == 1


def test_summarize_counts_only_accurate_events_as_located(tmp_path):
    path = write_csv(tmp_path, HEADER
                     + "1,2018-08-16,11.55,76.13,5km,downpour,India\n"
                     + "2,2019-08-08,11.60,76.10,25km,downpour,India\n"
                     + "3,2019-08-09,11.62,76.12,unknown,rain,India\n"
                     + "4,2020-07-01,27.70,85.30,1km,rain,Nepal\n"
                     + "5,2020-07-02,0.5,20.0,1km,rain,Elsewhere\n")
    df, _ = ls.read_catalog_csv(path)
    out = ls.summarize_catalog(df, max_accuracy_km=5.0)
    ghats = out["western_ghats"]
    assert ghats["n_total"] == 3 and ghats["n_located"] == 1 and ghats["n_unknown_accuracy"] == 1
    assert ghats["by_year"] == {2018: 1}
    assert ghats["first_date"] == "2018-08-16" and ghats["last_date"] == "2019-08-09"
    assert out["himalaya"]["n_located"] == 1
    assert out["outside_domain"]["n_total"] == 1


def _dates(tmp_path, *date_strings):
    rows = "".join(f"{i},{d},11.55,76.13,5km,rain,India\n" for i, d in enumerate(date_strings, 1))
    df, report = ls.read_catalog_csv(write_csv(tmp_path, HEADER + rows))
    return df["event_date"].dt.strftime("%Y-%m-%d").tolist(), report


def test_iso_rows_are_not_swapped_by_a_day_first_file(tmp_path):
    got, _ = _dates(tmp_path, "2018-08-03", "27/03/2013")
    assert got == ["2013-03-27", "2018-08-03"]


def test_iso_rows_with_time_are_not_swapped_by_a_day_first_file(tmp_path):
    got, _ = _dates(tmp_path, "2018-08-03 14:30:00", "27/03/2013 14:30")
    assert got == ["2013-03-27", "2018-08-03"]


def test_iso_rows_are_kept_in_a_month_first_file(tmp_path):
    got, _ = _dates(tmp_path, "2018-08-03", "03/27/2013")
    assert got == ["2013-03-27", "2018-08-03"]


def test_two_digit_year_ambiguous_slash_date_raises(tmp_path):
    with pytest.raises(ls.CatalogFormatError, match="ambiguous"):
        _dates(tmp_path, "3/4/13")


def test_dash_separated_ambiguous_date_raises(tmp_path):
    with pytest.raises(ls.CatalogFormatError, match="ambiguous"):
        _dates(tmp_path, "03-04-2013")


def test_dash_and_dot_separated_unambiguous_day_first_dates_parse(tmp_path):
    got, _ = _dates(tmp_path, "27-03-2013", "27.03.2013")
    assert got == ["2013-03-27", "2013-03-27"]


def test_unrecognised_date_strings_are_dropped_and_counted(tmp_path):
    got, report = _dates(tmp_path, "2018-08-16", "March 2013", "27/03/2013")
    assert got == ["2013-03-27", "2018-08-16"]
    assert report.dropped_bad_date == 1
    assert report.total_rows == (report.kept_rows + report.dropped_bad_date
                                 + report.dropped_bad_coordinates)
