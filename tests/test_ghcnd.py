import json

import pytest

from aetherguard.audit import ghcnd
from aetherguard.http import DownloadError


def make_dly_line(station="IN022021900", year=2023, month=2, element="PRCP", days=None):
    """Build a 269-character GHCN-Daily line; `days` maps day -> (raw_value, qflag)."""
    days = days or {}
    body = ""
    for d in range(1, 32):
        raw, q = days.get(d, (-9999, " "))
        body += f"{raw:5d}" + " " + q + "S"  # value, mflag, qflag, sflag
    return f"{station}{year:04d}{month:02d}{element}{body}"


def station_line(sid, lat, lon, elev, state, name):
    return f"{sid:<11} {lat:8.4f} {lon:9.4f} {elev:6.1f} {state:<2} {name:<30}"


def inventory_line(sid, lat, lon, element, first, last):
    return f"{sid:<11} {lat:8.4f} {lon:9.4f} {element:<4} {first:4d} {last:4d}"


def test_line_helper_matches_the_documented_length():
    assert len(make_dly_line()) == ghcnd.DLY_LINE_LENGTH


def test_scaling_and_quality_flags_are_preserved():
    rows = ghcnd.parse_dly_line(make_dly_line(days={1: (125, "K"), 2: (0, " ")}))
    assert rows[0]["value"] == pytest.approx(12.5)
    assert rows[0]["qflag"] == "K"
    assert rows[1]["value"] == 0.0
    assert rows[1]["qflag"] == " "


def test_missing_sentinel_becomes_none_never_a_rainfall_value():
    rows = ghcnd.parse_dly_line(make_dly_line(days={1: (10, " ")}))
    assert rows[2]["value"] is None
    assert all(r["value"] is None or r["value"] >= 0 for r in rows)


def test_month_length_is_respected_including_leap_years():
    assert len(ghcnd.parse_dly_line(make_dly_line(year=2023, month=2))) == 28
    assert len(ghcnd.parse_dly_line(make_dly_line(year=2024, month=2))) == 29
    assert len(ghcnd.parse_dly_line(make_dly_line(month=4))) == 30


def test_short_line_raises_instead_of_guessing():
    with pytest.raises(ValueError):
        ghcnd.parse_dly_line(make_dly_line()[:100])


def test_flag_census_counts_flags_and_missing(tmp_path):
    path = tmp_path / "s.dly"
    path.write_text(
        make_dly_line(month=3, days={1: (0, " "), 2: (500, "K"), 3: (800, "S"), 4: (900, "K")}) + "\n",
        encoding="ascii")
    df = ghcnd.read_dly(path, "PRCP")
    census = ghcnd.flag_census(df)
    assert census["n_values"] == 31
    assert census["n_valid"] == 4
    assert census["n_missing"] == 27
    assert census["n_flagged"] == 3
    assert census["by_flag"] == {"K": 2, "S": 1}


def test_read_dly_filters_by_element(tmp_path):
    path = tmp_path / "s.dly"
    path.write_text(make_dly_line(element="PRCP") + "\n" + make_dly_line(element="TMAX") + "\n",
                    encoding="ascii")
    assert set(ghcnd.read_dly(path, "PRCP")["element"]) == {"PRCP"}


def _station_files():
    stations = [
        station_line("IN000000001", 11.6, 76.1, 900.0, "KL", "WAYANAD UPLAND"),
        station_line("IN000000002", 28.6, 77.2, 216.0, "DL", "DELHI LOWLAND"),
        station_line("NP000000003", 27.7, 85.3, 1400.0, "  ", "KATHMANDU"),
        station_line("US000000004", 40.0, -105.0, 1600.0, "CO", "BOULDER"),
        station_line("IN000000005", 12.0, 76.0, 800.0, "KA", "OLD STATION"),
    ]
    inventory = [
        inventory_line("IN000000001", 11.6, 76.1, "PRCP", 1990, 2025),
        inventory_line("IN000000002", 28.6, 77.2, "PRCP", 1990, 2025),
        inventory_line("NP000000003", 27.7, 85.3, "PRCP", 2010, 2025),
        inventory_line("US000000004", 40.0, -105.0, "PRCP", 1990, 2025),
        inventory_line("IN000000005", 12.0, 76.0, "PRCP", 1990, 2010),  # stopped reporting
        inventory_line("IN000000001", 11.6, 76.1, "TMAX", 1990, 2025),  # wrong element
    ]
    return inventory, stations


def test_select_stations_filters_country_years_element_region_and_upland():
    inventory, stations = _station_files()
    df = ghcnd.select_stations(inventory, stations, ("IN", "NP"), "PRCP", 2015, 2024, 500.0)
    assert sorted(df["id"]) == ["IN000000001", "IN000000002", "NP000000003"]
    by_id = df.set_index("id")
    assert by_id.loc["IN000000001", "region"] == "western_ghats"
    assert bool(by_id.loc["IN000000001", "upland"]) is True
    assert bool(by_id.loc["IN000000002", "upland"]) is False
    assert by_id.loc["NP000000003", "region"] == "himalaya"


def test_probe_ghcnd_aggregates_by_region_and_upland(tmp_path, monkeypatch):
    inventory, stations = _station_files()
    dly = {
        "IN000000001": make_dly_line("IN000000001", month=3, days={1: (0, " "), 2: (500, "K")}),
        "IN000000002": make_dly_line("IN000000002", month=3, days={1: (10, " ")}),
        "NP000000003": make_dly_line("NP000000003", month=3, days={1: (20, "S")}),
    }

    def fake_download(url, dest, manifest, source, licence, **kwargs):
        dest.parent.mkdir(parents=True, exist_ok=True)
        if url.endswith("ghcnd-inventory.txt"):
            dest.write_text("\n".join(inventory) + "\n", encoding="ascii")
        elif url.endswith("ghcnd-stations.txt"):
            dest.write_text("\n".join(stations) + "\n", encoding="ascii")
        else:
            dest.write_text(dly[dest.stem] + "\n", encoding="ascii")
        return dest

    monkeypatch.setattr(ghcnd, "download", fake_download)
    cfg = {"ghcnd": {"countries": ["IN", "NP"], "first_year_max": 2015, "last_year_min": 2024,
                     "upland_min_elev_m": 500}}
    res = ghcnd.probe_ghcnd(tmp_path, manifest=None, cfg=cfg)
    assert res.status == "ok"
    groups = res.evidence["census_by_group"]
    assert groups["western_ghats|upland"]["n_flagged"] == 1
    assert groups["western_ghats|upland"]["by_flag"] == {"K": 1}
    assert groups["himalaya|lowland"]["n_flagged"] == 0
    assert groups["himalaya|upland"]["by_flag"] == {"S": 1}
    assert res.evidence["n_selected"] == 3
    assert res.evidence["by_country"] == {"IN": 2, "NP": 1}


def test_probe_isd_history_counts_active_regional_stations(tmp_path, monkeypatch):
    csv_text = (
        '"USAF","WBAN","STATION NAME","CTRY","STATE","ICAO","LAT","LON","ELEV(M)","BEGIN","END"\n'
        '"430000","99999","KOZHIKODE","IN","","VOCL","11.25","75.78","4.0","19730101","20260929"\n'
        '"424000","99999","KATHMANDU","NP","","VNKT","27.70","85.36","1337.0","19730101","20260929"\n'
        '"999999","99999","DEFUNCT","IN","","","12.0","76.0","10.0","19730101","20100101"\n'
        '"720000","99999","BOULDER","US","CO","KBDU","40.0","-105.2","1600.0","19730101","20260929"\n'
    )

    def fake_download(url, dest, manifest, source, licence, **kwargs):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(csv_text, encoding="utf-8")
        return dest

    monkeypatch.setattr(ghcnd, "download", fake_download)
    cfg = {"ghcnd": {"countries": ["IN", "NP"], "first_year_max": 2015, "last_year_min": 2024,
                     "upland_min_elev_m": 500}}
    res = ghcnd.probe_isd_history(tmp_path, manifest=None, cfg=cfg)
    assert res.status == "ok"
    assert res.evidence["n_selected"] == 2
    assert res.evidence["by_country"] == {"IN": 1, "NP": 1}


_CFG = {"ghcnd": {"countries": ["IN", "NP"], "first_year_max": 2015, "last_year_min": 2024,
                  "upland_min_elev_m": 500}}


def _fake_download_factory(inventory, stations, dly, station_error=None):
    def fake_download(url, dest, manifest, source, licence, **kwargs):
        if url.endswith("ghcnd-inventory.txt"):
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text("\n".join(inventory) + "\n", encoding="ascii")
        elif url.endswith("ghcnd-stations.txt"):
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text("\n".join(stations) + "\n", encoding="ascii")
        else:
            if station_error is not None:
                raise station_error
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(dly[dest.stem] + "\n", encoding="ascii")
        return dest
    return fake_download


@pytest.mark.parametrize("retriable, expected", [(True, "unreachable"), (False, "fail")])
def test_probe_ghcnd_all_station_downloads_failing_is_not_partial(tmp_path, monkeypatch,
                                                                  retriable, expected):
    inventory, stations = _station_files()
    error = DownloadError("boom", retriable=retriable)
    monkeypatch.setattr(ghcnd, "download",
                        _fake_download_factory(inventory, stations, {}, station_error=error))
    res = ghcnd.probe_ghcnd(tmp_path, manifest=None, cfg=_CFG)
    assert res.status == expected
    assert res.evidence["census_by_group"] == {}
    assert res.evidence["n_selected"] == 3
    failed = res.evidence["failed_downloads"]
    assert sorted(f["id"] for f in failed) == ["IN000000001", "IN000000002", "NP000000003"]
    assert all(f["kind"] == "download" and f["error"] == "boom" for f in failed)


def test_probe_ghcnd_corrupt_dly_file_is_recorded_and_others_continue(tmp_path, monkeypatch):
    inventory, stations = _station_files()
    dly = {
        "IN000000001": make_dly_line("IN000000001", month=3, days={1: (0, " "), 2: (500, "K")}),
        "IN000000002": make_dly_line("IN000000002", month=3, days={1: (10, " ")})[:100],  # truncated
        "NP000000003": make_dly_line("NP000000003", month=3, days={1: (20, "S")}),
    }
    monkeypatch.setattr(ghcnd, "download", _fake_download_factory(inventory, stations, dly))
    res = ghcnd.probe_ghcnd(tmp_path, manifest=None, cfg=_CFG)
    assert res.status == "partial"
    groups = res.evidence["census_by_group"]
    assert groups["western_ghats|upland"]["n_flagged"] == 1
    assert groups["himalaya|upland"]["by_flag"] == {"S": 1}
    assert "himalaya|lowland" not in groups and "outside_domain|lowland" not in groups
    failed = res.evidence["failed_downloads"]
    assert len(failed) == 1
    assert failed[0]["id"] == "IN000000002" and failed[0]["kind"] == "parse"
    assert "short .dly line" in failed[0]["error"]
    assert [s["id"] for s in res.evidence["stations"]] == ["IN000000001", "NP000000003"]


def test_probe_ghcnd_unknown_elevation_is_none_and_counted(tmp_path, monkeypatch):
    inventory, stations = _station_files()
    stations[1] = station_line("IN000000002", 28.6, 77.2, -999.9, "DL", "DELHI NO ELEVATION")
    dly = {
        "IN000000001": make_dly_line("IN000000001", month=3, days={1: (0, " "), 2: (500, "K")}),
        "IN000000002": make_dly_line("IN000000002", month=3, days={1: (10, " ")}),
        "NP000000003": make_dly_line("NP000000003", month=3, days={1: (20, "S")}),
    }
    monkeypatch.setattr(ghcnd, "download", _fake_download_factory(inventory, stations, dly))
    res = ghcnd.probe_ghcnd(tmp_path, manifest=None, cfg=_CFG)
    json.dumps(res.evidence, allow_nan=False)  # would raise on a NaN token
    by_id = {s["id"]: s for s in res.evidence["stations"]}
    assert by_id["IN000000002"]["elevation_m"] is None
    assert by_id["IN000000002"]["upland"] is False
    assert by_id["IN000000001"]["elevation_m"] == 900.0
    assert res.evidence["n_unknown_elevation"] == 1
