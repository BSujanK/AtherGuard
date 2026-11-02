"""Place-name geocoder: ASCII-folded matching of reported places against a GeoNames India table.

Everything is synthetic (a hand-made places frame and a fake IN.zip in tmp_path); nothing is downloaded.
"""
import functools
import io
import zipfile

import numpy as np
import pandas as pd
import pytest

from aetherguard.manifest import Manifest
from aetherguard.verify import geocode as gc

KM_PER_DEG = 6371.0088 * np.pi / 180


def places(*rows):
    """(name, state, district, lat, lon[, feature_class[, alternatenames[, asciiname]]]) -> a places frame."""
    out = []
    for i, (name, state, district, lat, lon, *rest) in enumerate(rows):
        feature_class, alternates, ascii_name = rest + ["P", "", None][len(rest):]
        out.append({"geonameid": i + 1, "name": name, "asciiname": ascii_name if ascii_name is not None else name,
                    "alternatenames": alternates, "feature_class": feature_class, "feature_code": "PPL" if feature_class == "P" else "X",
                    "lat": lat, "lon": lon, "population": 0, "district": district, "state": state})
    return pd.DataFrame(out)


# --- the brief's four cases ---------------------------------------------------------------------

def test_a_unique_village_returns_its_coordinates_and_five_km():
    frame = places(("Puthumala", "Kerala", "Wayanad", 11.52, 76.18), ("Other", "Kerala", "Idukki", 9.9, 77.0))
    assert gc.geocode("Puthumala", None, "Kerala", frame) == (11.52, 76.18, 5.0)


def test_a_name_in_two_districts_of_one_state_is_ambiguous_without_a_district():
    frame = places(("Rampur", "Himachal Pradesh", "Shimla", 31.4, 77.6), ("Rampur", "Himachal Pradesh", "Mandi", 31.9, 76.9))
    assert gc.geocode("Rampur", None, "Himachal Pradesh", frame) is None


def test_the_district_picks_one_of_two_namesakes():
    frame = places(("Rampur", "Himachal Pradesh", "Shimla", 31.4, 77.6), ("Rampur", "Himachal Pradesh", "Mandi", 31.9, 76.9))
    assert gc.geocode("Rampur", "Mandi", "Himachal Pradesh", frame) == (31.9, 76.9, 5.0)


def test_a_state_mismatch_returns_none():
    frame = places(("Puthumala", "Kerala", "Wayanad", 11.52, 76.18))
    assert gc.geocode("Puthumala", None, "Karnataka", frame) is None


# --- state names --------------------------------------------------------------------------------

@pytest.mark.parametrize("written", ["J&K", "Jammu & Kashmir", "jammu and kashmir", "Jammu and Kashmir "])
def test_jammu_and_kashmir_is_written_many_ways(written):
    frame = places(("Ramban", "Jammu and Kashmir", "Ramban", 33.24, 75.24))
    assert gc.geocode("Ramban", None, written, frame) == (33.24, 75.24, 5.0)


def test_uttaranchal_is_uttarakhand():
    frame = places(("Kedarnath", "Uttarakhand", "Rudraprayag", 30.73, 79.07))
    assert gc.geocode("Kedarnath", None, "Uttaranchal", frame) == (30.73, 79.07, 5.0)


def test_an_unknown_state_returns_none():
    frame = places(("Puthumala", "Kerala", "Wayanad", 11.52, 76.18))
    assert gc.geocode("Puthumala", None, "Atlantis", frame) is None
    assert gc.geocode("Puthumala", None, "", frame) is None


def test_every_state_of_the_domain_has_an_alias_entry():
    for state in ("Jammu and Kashmir", "Ladakh", "Himachal Pradesh", "Uttarakhand", "Sikkim", "West Bengal", "Arunachal Pradesh",
                  "Assam", "Meghalaya", "Nagaland", "Manipur", "Mizoram", "Tripura", "Kerala", "Karnataka", "Goa", "Maharashtra",
                  "Tamil Nadu"):
        assert gc.canonical_state(state) == state


# --- name matching ------------------------------------------------------------------------------

def test_matching_is_case_and_accent_insensitive_and_ignores_punctuation():
    frame = places(("Mundakkai", "Kerala", "Wayanad", 11.47, 76.13), ("Théni", "Tamil Nadu", "Theni", 10.0, 77.5, "P", "", "Theni"))
    assert gc.geocode("MUNDAKKAI", None, "Kerala", frame) == (11.47, 76.13, 5.0)
    assert gc.geocode("  mundakkai. ", None, "Kerala", frame) == (11.47, 76.13, 5.0)
    assert gc.geocode("Theni", None, "Tamil Nadu", frame) == (10.0, 77.5, 5.0)
    assert gc.geocode("Théni", None, "Tamil Nadu", frame) == (10.0, 77.5, 5.0)


def test_double_letters_are_not_fuzzy_matched():
    frame = places(("Mundakkai", "Kerala", "Wayanad", 11.47, 76.13))
    assert gc.geocode("Mundakai", None, "Kerala", frame) is None


def test_hyphens_and_spaces_are_the_same():
    frame = places(("East Jaintia Hills", "Meghalaya", "East Jaintia Hills", 25.4, 92.4, "L"))
    assert gc.geocode("East-Jaintia Hills", None, "Meghalaya", frame) == (25.4, 92.4, 5.0)


def test_an_alternate_name_matches():
    frame = places(("Kavalappara", "Kerala", "Malappuram", 11.2, 76.2, "P", "Kavalappara,കവളപ്പാറ,Kavalapara"))
    assert gc.geocode("Kavalapara", None, "Kerala", frame) == (11.2, 76.2, 5.0)


def test_an_empty_place_returns_none():
    frame = places(("Puthumala", "Kerala", "Wayanad", 11.52, 76.18))
    assert gc.geocode("", None, "Kerala", frame) is None
    assert gc.geocode("  ", None, "Kerala", frame) is None


# --- feature classes ----------------------------------------------------------------------------

def test_a_populated_place_beats_another_feature_of_the_same_name():
    frame = places(("Sangla", "Himachal Pradesh", "Kinnaur", 31.4, 78.3, "T"), ("Sangla", "Himachal Pradesh", "Kinnaur", 31.42, 78.26, "P"))
    assert gc.geocode("Sangla", None, "Himachal Pradesh", frame) == (31.42, 78.26, 5.0)


@pytest.mark.parametrize("feature_class", ["S", "T", "H", "L", "R"])
def test_other_named_features_match_when_no_populated_place_does(feature_class):
    frame = places(("Nathu Pass", "Sikkim", "Gangtok", 27.39, 88.83, feature_class))
    assert gc.geocode("Nathu Pass", None, "Sikkim", frame) == (27.39, 88.83, 5.0)


def test_administrative_divisions_are_not_matched():
    frame = places(("Wayanad", "Kerala", "Wayanad", 11.6, 76.1, "A"))
    assert gc.geocode("Wayanad", None, "Kerala", frame) is None


def test_a_populated_place_in_another_state_does_not_hide_a_feature_in_the_state():
    frame = places(("Rohtang", "Punjab", "Ludhiana", 30.9, 75.8, "P"), ("Rohtang", "Himachal Pradesh", "Kullu", 32.37, 77.24, "T"))
    assert gc.geocode("Rohtang", None, "Himachal Pradesh", frame) == (32.37, 77.24, 5.0)


# --- districts ----------------------------------------------------------------------------------

def test_the_district_is_compared_ascii_folded():
    frame = places(("Rampur", "Himachal Pradesh", "Shimla", 31.4, 77.6), ("Rampur", "Himachal Pradesh", "Mandi", 31.9, 76.9))
    assert gc.geocode("Rampur", " MANDI ", "Himachal Pradesh", frame) == (31.9, 76.9, 5.0)
    assert gc.geocode("Rampur", "Mandi district", "Himachal Pradesh", frame) == (31.9, 76.9, 5.0)


def test_a_district_spelled_within_two_edits_still_matches():
    unique = places(("Puthumala", "Kerala", "Wayanad", 11.52, 76.18))
    assert gc.geocode("Puthumala", "Waynad", "Kerala", unique) == (11.52, 76.18, 5.0)
    twin = places(("Rampur", "Himachal Pradesh", "Shimla", 31.4, 77.6), ("Rampur", "Himachal Pradesh", "Mandi", 31.9, 76.9))
    assert gc.geocode("Rampur", "Manadi", "Himachal Pradesh", twin) == (31.9, 76.9, 5.0)


@pytest.mark.parametrize("written, geonames, state", [
    ("Kullu", "Kulu", "Himachal Pradesh"), ("Mumbai", "Mumbai Suburban", "Maharashtra"), ("Shivamogga", "Shimoga", "Karnataka"),
    ("Tehri", "Tehri Garhwal", "Uttarakhand"), ("Kamrup Metropolitan (Guwahati)", "Kamrup Metropolitan", "Assam")])
def test_listed_district_names_and_bracketed_parts_match(written, geonames, state):
    frame = places(("Somewhere", state, geonames, 20.0, 80.0))
    assert gc.geocode("Somewhere", written, state, frame) == (20.0, 80.0, 5.0)


def test_a_district_that_matches_no_candidate_returns_none():
    frame = places(("Puthumala", "Kerala", "Wayanad", 11.52, 76.18))
    assert gc.geocode("Puthumala", "Idukki", "Kerala", frame) is None


def test_a_district_with_no_match_gives_none_even_when_the_name_is_unique_in_the_state():
    frame = places(("Chaura", "Himachal Pradesh", "Shimla", 31.1, 77.3), ("Chaura", "Himachal Pradesh", "Mandi", 31.7, 76.9))
    assert gc.geocode("Chaura", "Kinnaur", "Himachal Pradesh", frame) is None


def test_a_right_district_feature_beats_a_wrong_district_populated_place():
    frame = places(("Sangla", "Himachal Pradesh", "Shimla", 31.1, 77.3, "P"), ("Sangla", "Himachal Pradesh", "Kinnaur", 31.42, 78.26, "T"))
    assert gc.geocode("Sangla", "Kinnaur", "Himachal Pradesh", frame) == (31.42, 78.26, 5.0)
    assert gc.geocode("Sangla", None, "Himachal Pradesh", frame) == (31.1, 77.3, 5.0)


def test_a_later_segment_is_tried_when_the_district_rejects_the_first():
    frame = places(("Chaura", "Himachal Pradesh", "Shimla", 31.1, 77.3), ("Nigulsari", "Himachal Pradesh", "Kinnaur", 31.6, 78.4))
    assert gc.geocode("Chaura village, Nigulsari", "Kinnaur", "Himachal Pradesh", frame) == (31.6, 78.4, 15.0)


def test_several_matches_in_one_district_give_the_centroid_and_the_farthest_distance():
    frame = places(("Chhaten", "Sikkim", "Mangan", 27.0, 88.0), ("Chhaten", "Sikkim", "Mangan", 27.12, 88.0))
    lat, lon, accuracy = gc.geocode("Chhaten", None, "Sikkim", frame)
    assert (lat, lon) == pytest.approx((27.06, 88.0))
    assert accuracy == pytest.approx(0.06 * KM_PER_DEG, rel=1e-3)


def test_matches_closer_than_five_km_still_report_five_km():
    frame = places(("Chhaten", "Sikkim", "Mangan", 27.0, 88.0), ("Chhaten", "Sikkim", "Mangan", 27.001, 88.0))
    assert gc.geocode("Chhaten", None, "Sikkim", frame)[2] == 5.0


def test_matches_spread_over_more_than_ten_km_return_none():
    far = places(("Chhaten", "Sikkim", "Mangan", 27.0, 88.0), ("Chhaten", "Sikkim", "Mangan", 27.25, 88.0))
    assert gc.geocode("Chhaten", None, "Sikkim", far) is None
    assert gc.geocode("Chhaten", "Mangan", "Sikkim", far) is None


def test_namesakes_of_several_districts_narrowed_by_the_district_to_two_in_it_give_their_centroid():
    frame = places(("Rampur", "Himachal Pradesh", "Mandi", 31.9, 76.9), ("Rampur", "Himachal Pradesh", "Mandi", 31.9, 77.1),
                   ("Rampur", "Himachal Pradesh", "Shimla", 31.4, 77.6))
    lat, lon, accuracy = gc.geocode("Rampur", "Mandi", "Himachal Pradesh", frame)
    assert (lat, lon) == pytest.approx((31.9, 77.0))
    assert accuracy == pytest.approx(0.1 * KM_PER_DEG * np.cos(np.radians(31.9)), rel=1e-2)


# --- messy place text ---------------------------------------------------------------------------

def test_the_first_segment_of_a_report_place_is_tried_after_the_whole_text():
    frame = places(("Kavalappara", "Kerala", "Malappuram", 11.2, 76.2), ("Pothukal", "Kerala", "Malappuram", 11.3, 76.2))
    assert gc.geocode("Kavalappara, near Pothukal (Muthappan Hill)", "Malappuram", "Kerala", frame) == (11.2, 76.2, 5.0)


def test_a_trailing_village_word_is_dropped():
    frame = places(("Pakshep", "Sikkim", "Mangan", 27.5, 88.5))
    assert gc.geocode("Pakshep village", "Mangan", "Sikkim", frame) == (27.5, 88.5, 5.0)


def test_a_later_segment_is_good_to_fifteen_km_only():
    frame = places(("Rongyek", "Sikkim", "East Sikkim", 27.3, 88.5), ("Gangtok", "Sikkim", "East Sikkim", 27.33, 88.61))
    assert gc.geocode("Dokan Dara, Rongyek, near Gangtok", None, "Sikkim", frame) == (27.3, 88.5, 15.0)


def test_a_segment_introduced_by_near_is_never_a_query():
    frame = places(("Gangtok", "Sikkim", "East Sikkim", 27.33, 88.61))
    assert gc.geocode("Dokan Dara, Rongyek, near Gangtok", None, "Sikkim", frame) is None
    assert gc.geocode("Near Gangtok", None, "Sikkim", frame) is None
    assert gc.geocode("Dokan Dara, nr Gangtok", None, "Sikkim", frame) is None


def test_a_name_inside_a_segment_after_near_is_not_a_query_either():
    frame = places(("Gangtok", "Sikkim", "East Sikkim", 27.33, 88.61))
    assert gc.geocode("Dokan Dara near Gangtok", None, "Sikkim", frame) is None


def test_segments_shorter_than_three_characters_are_ignored():
    frame = places(("Ur", "Sikkim", "East Sikkim", 27.0, 88.0), ("Gangtok", "Sikkim", "East Sikkim", 27.33, 88.61))
    assert gc.geocode("Dokan Dara, Ur, Gangtok", None, "Sikkim", frame) == (27.33, 88.61, 15.0)


def test_the_whole_text_wins_over_its_segments():
    frame = places(("Sangla Chitkul road", "Himachal Pradesh", "Kinnaur", 31.4, 78.4, "R"), ("Sangla", "Himachal Pradesh", "Kinnaur", 31.42, 78.26))
    assert gc.geocode("Sangla Chitkul road", None, "Himachal Pradesh", frame) == (31.4, 78.4, 5.0)


def test_a_segment_that_is_ambiguous_is_not_skipped_for_the_next_one():
    frame = places(("Rampur", "Himachal Pradesh", "Shimla", 31.4, 77.6), ("Rampur", "Himachal Pradesh", "Mandi", 31.9, 76.9),
                   ("Kalpa", "Himachal Pradesh", "Kinnaur", 31.54, 78.25))
    assert gc.geocode("Rampur, Kalpa", None, "Himachal Pradesh", frame) is None


# --- loading ------------------------------------------------------------------------------------

IN_ROWS = [
    ["1", "Puthumala", "Puthumala", "Puthumala,Pudumala", "11.52", "76.18", "P", "PPL", "IN", "", "13", "012", "", "", "250", "", "", "Asia/Kolkata", "2020-01-01"],
    ["2", "Nathu La", "Nathu La", "Nathula", "27.39", "88.83", "T", "PASS", "IN", "", "29", "", "", "", "0", "", "", "Asia/Kolkata", "2020-01-01"],
    ["3", "Nowhere", "Nowhere", "", "20.0", "80.0", "P", "PPL", "IN", "", "", "", "", "", "0", "", "", "Asia/Kolkata", "2020-01-01"],
]


def fake_sources(raw_dir, manifest):
    """The admin name files already on disk and in the manifest, as after a places build."""
    for name, text in (("admin1CodesASCII.txt", "IN.13\tKerala\tKerala\t1\nIN.29\tSikkim\tSikkim\t2\n"),
                       ("admin2Codes.txt", "IN.13.012\tWayanad\tWayanad\t3\n")):
        (raw_dir / name).write_text(text, encoding="utf-8")
        manifest.add(raw_dir / name, name, "https://example.invalid/" + name, "test")


def fake_fetch(calls):
    def fetch(url, dest, manifest, source, licence):
        calls.append((url, source, licence))
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("IN.txt", "\n".join("\t".join(row) for row in IN_ROWS) + "\n")
            archive.writestr("readme.txt", "ignored")
        dest.write_bytes(buffer.getvalue())
        manifest.add(dest, source, url, licence)
        return dest
    return fetch


def test_build_makes_the_table_from_in_zip_and_records_the_download(tmp_path):
    raw = tmp_path / "data" / "raw" / "geonames"
    raw.mkdir(parents=True)
    manifest = Manifest(tmp_path / "manifest.jsonl", tmp_path / "data")
    fake_sources(raw, manifest)
    calls = []
    table = gc.build_places_table(raw, manifest, fetch=fake_fetch(calls))
    assert calls == [("https://download.geonames.org/export/dump/IN.zip", "GeoNames India dump (all features)", gc.GEONAMES_LICENCE)]
    assert list(table.columns) == gc.PLACE_COLUMNS
    assert table.loc[table["geonameid"] == 1, ["district", "state"]].iloc[0].tolist() == ["Wayanad", "Kerala"]
    assert table.loc[table["geonameid"] == 2, "state"].iloc[0] == "Sikkim"
    assert table.loc[table["geonameid"] == 2, "district"].iloc[0] is None
    assert table.loc[table["geonameid"] == 3, "state"].iloc[0] is None
    assert (raw / gc.TABLE_NAME).exists()
    entries = manifest.entries()
    assert "raw/geonames/IN.zip" in entries and "raw/geonames/" + gc.TABLE_NAME in entries
    assert gc.geocode("Pudumala", "Wayanad", "Kerala", table) == (11.52, 76.18, 5.0)


def test_load_places_reads_the_stored_table_and_does_not_download_again(isolated_data_root):
    raw = isolated_data_root / "raw" / "geonames"
    raw.mkdir(parents=True)
    stored = places(("Puthumala", "Kerala", "Wayanad", 11.52, 76.18))[gc.PLACE_COLUMNS]
    stored.to_parquet(raw / gc.TABLE_NAME, index=False)
    loaded = gc.load_places()
    assert loaded["name"].tolist() == ["Puthumala"]


def test_load_places_builds_the_table_when_it_is_missing(isolated_data_root, monkeypatch):
    raw = isolated_data_root / "raw" / "geonames"
    raw.mkdir(parents=True)
    monkeypatch.setattr(gc, "PROJECT_ROOT", isolated_data_root.parent)
    fake_sources(raw, Manifest(isolated_data_root.parent / "manifests" / "data_manifest.jsonl", isolated_data_root))
    monkeypatch.setattr(gc, "build_places_table", functools.partial(gc.build_places_table, fetch=fake_fetch([])))
    loaded = gc.load_places()
    assert sorted(loaded["geonameid"]) == [1, 2, 3]


def test_a_bad_zip_is_a_geocode_error(tmp_path):
    bad = tmp_path / "IN.zip"
    bad.write_bytes(b"not a zip")
    with pytest.raises(gc.GeocodeError, match="IN.zip"):
        gc.read_in_dump(bad)
