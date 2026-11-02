"""Cell country / region assignment from admin-0 polygons (design D1), on synthetic polygons."""
import json

import numpy as np
import pandas as pd
import pytest

from aetherguard.config import load_config
from aetherguard.features import regions
from aetherguard.grid import cell_center, latlon_to_cell
from aetherguard.manifest import Manifest


def _box(lon0, lat0, lon1, lat1):
    return {"type": "Polygon", "coordinates": [[[lon0, lat0], [lon1, lat0], [lon1, lat1], [lon0, lat1], [lon0, lat0]]]}


def _feature(geometry, iso2, eh="-99", a3="XXX"):
    return {"type": "Feature", "properties": {"ISO_A2": iso2, "ISO_A2_EH": eh, "ADM0_A3": a3}, "geometry": geometry}


@pytest.fixture
def geojson_path(tmp_path):
    features = [
        _feature(_box(76, 8, 90, 34), "IN", "IN", "IND"),          # ghats box part (76..78.5) + himalaya box part
        _feature(_box(66, 8, 76, 36), "PK", "PK", "PAK"),          # overlaps both region boxes, out of scope
        _feature(_box(90, 26, 95, 30), "NP", "NP", "NPL"),
        _feature(_box(95, 26, 98, 30), "BT", "BT", "BTN"),
        _feature(_box(100, 40, 105, 45), "-99", "FR", "FRA"),      # ISO_A2 missing -> ISO_A2_EH
        _feature(_box(110, 40, 115, 45), "-99", "-99", "KAS"),     # both missing -> ADM0_A3
    ]
    path = tmp_path / "countries.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8")
    return path


@pytest.fixture
def countries(geojson_path):
    return regions.load_countries(geojson_path)


def _cells(*points):
    lat, lon = zip(*points)
    return latlon_to_cell(np.array(lat), np.array(lon))


def test_country_code_uses_iso_a2_then_eh_then_adm0_a3():
    assert regions.country_code({"ISO_A2": "IN", "ISO_A2_EH": "IN", "ADM0_A3": "IND"}) == "IN"
    assert regions.country_code({"ISO_A2": "-99", "ISO_A2_EH": "NO", "ADM0_A3": "NOR"}) == "NO"
    assert regions.country_code({"ISO_A2": "-99", "ISO_A2_EH": "-99", "ADM0_A3": "KAS"}) == "KAS"
    assert regions.country_code({"ISO_A2": "", "ISO_A2_EH": None, "ADM0_A3": "SOL"}) == "SOL"


def test_country_code_without_any_code_is_an_error():
    with pytest.raises(ValueError, match="no usable country code"):
        regions.country_code({"ISO_A2": "-99", "ISO_A2_EH": "-99", "ADM0_A3": "-99"})


def test_load_countries_codes_and_missing_file(countries, tmp_path):
    assert sorted(countries.codes) == ["BT", "FR", "IN", "KAS", "NP", "PK"]
    with pytest.raises(FileNotFoundError):
        regions.load_countries(tmp_path / "missing.geojson")


def test_countries_at_assigns_polygon_codes_and_none_outside(countries):
    lat = np.array([30.0, 30.0, 28.0, 28.0, 42.0, 42.0, 0.0])
    lon = np.array([80.0, 70.0, 92.0, 96.0, 102.0, 112.0, 0.0])
    got = regions.countries_at(lat, lon, countries)
    assert list(got) == ["IN", "PK", "NP", "BT", "FR", "KAS", None]


def test_countries_at_on_shared_border_is_deterministic(tmp_path):
    features = [_feature(_box(0, 0, 10, 10), "AA", "AA", "AAA"), _feature(_box(10, 0, 20, 10), "BB", "BB", "BBB")]
    path = tmp_path / "border.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8")
    loaded = regions.load_countries(path)
    got = regions.countries_at(np.array([5.0, 5.0]), np.array([10.0, 10.0]), loaded)
    assert list(got) == ["AA", "AA"]


def test_region_rules_follow_design_d1():
    cfg = load_config("samples")
    lat = np.array([30.0, 30.0, 28.0, 28.0, 30.0, 15.0, 15.0, 15.0, 30.0, 25.0, 40.0])
    lon = np.array([80.0, 80.0, 92.0, 96.0, 80.0, 77.0, 77.0, 74.0, 80.0, 99.0, 80.0])
    country = np.array(["IN", "PK", "NP", "BT", "CN", "IN", "NP", "IN", "KAS", "IN", "IN"], dtype=object)
    got = regions.region_for(country, lat, lon, cfg)
    assert list(got) == ["himalaya", "out_of_scope", "himalaya", "himalaya", "out_of_scope",
                         "western_ghats", "out_of_scope", "western_ghats", "out_of_scope", "out_of_scope",
                         "out_of_scope"]


def test_region_for_missing_country_is_out_of_scope():
    cfg = load_config("samples")
    got = regions.region_for(np.array([None, "IN"], dtype=object), np.array([30.0, 30.0]), np.array([80.0, 80.0]), cfg)
    assert list(got) == ["out_of_scope", "himalaya"]


def test_region_box_edges_are_half_open_like_the_grid():
    cfg = load_config("samples")
    country = np.array(["IN", "IN", "IN"], dtype=object)
    got = regions.region_for(country, np.array([22.0, 21.5, 36.0]), np.array([80.0, 77.0, 80.0]), cfg)
    assert list(got) == ["himalaya", "out_of_scope", "out_of_scope"]


def test_cell_regions_table_columns_order_and_determinism(countries):
    cfg = load_config("samples")
    ids = _cells((30.0, 80.0), (30.0, 70.0), (15.0, 77.0), (0.0, 0.0))
    first = regions.cell_regions(ids, countries, cfg)
    second = regions.cell_regions(ids[::-1], countries, cfg).iloc[::-1].reset_index(drop=True)
    assert list(first.columns) == ["cell_id", "country_code", "region"]
    assert list(first["cell_id"]) == list(ids)
    assert first["country_code"].fillna("NONE").tolist() == ["IN", "PK", "IN", "NONE"]
    assert first["region"].tolist() == ["himalaya", "out_of_scope", "western_ghats", "out_of_scope"]
    pd.testing.assert_frame_equal(first, second)


def test_cell_regions_uses_cell_centres(countries):
    cfg = load_config("samples")
    # cell whose centre is just inside the polygon edge (76.0) although its western edge lies outside
    cell = latlon_to_cell(30.0, 76.01)
    lat, lon = cell_center(cell)
    assert lon >= 76.0
    assert regions.cell_regions(np.array([cell]), countries, cfg)["country_code"].iloc[0] == "IN"


def test_positive_agreement_counts_and_lists_disagreements(countries):
    cfg = load_config("samples")
    agree = int(latlon_to_cell(30.0, 80.0))
    flip = int(latlon_to_cell(15.0, 74.0))     # PK-side ghats box point: out_of_scope by polygons
    ghats = int(latlon_to_cell(15.0, 77.0))
    positives = pd.DataFrame({
        "cell_id": [agree, agree, flip, ghats],
        "event_date": pd.to_datetime(["2010-07-01", "2010-07-02", "2010-07-03", "2011-07-01"]),
        "region": ["himalaya", "himalaya", "western_ghats", "himalaya"],
    })
    got = regions.positive_agreement(positives, countries, cfg)
    assert got["n_cells"] == 3 and got["n_cell_days"] == 4
    assert got["agree_cell_days"] == 2 and got["disagree_cell_days"] == 2
    assert got["disagree_cells"] == [
        {"cell_id": flip, "label_region": "western_ghats", "cell_region": "out_of_scope", "country_code": "PK",
         "n_cell_days": 1},
        {"cell_id": ghats, "label_region": "himalaya", "cell_region": "western_ghats", "country_code": "IN",
         "n_cell_days": 1},
    ]
    assert got["no_country_cell_days"] == 0


def test_positive_agreement_counts_cells_without_a_country(countries):
    cfg = load_config("samples")
    sea = int(latlon_to_cell(10.0, 60.0))
    positives = pd.DataFrame({"cell_id": [sea], "event_date": pd.to_datetime(["2010-07-01"]),
                              "region": ["western_ghats"]})
    got = regions.positive_agreement(positives, countries, cfg)
    assert got["no_country_cell_days"] == 1
    assert got["disagree_cells"][0]["country_code"] is None


def test_region_report_counts_per_region_and_country(countries):
    cfg = load_config("samples")
    ids = _cells((30.0, 80.0), (30.5, 80.0), (30.0, 70.0), (15.0, 77.0), (0.0, 0.0))
    table = regions.cell_regions(ids, countries, cfg)
    report = regions.region_report(table)
    assert report["n_cells"] == 5
    assert report["per_region"] == {"himalaya": 2, "out_of_scope": 2, "western_ghats": 1}
    assert report["per_country"]["IN"] == 3 and report["no_country_cells"] == 1


def test_fetch_boundaries_downloads_into_raw_boundaries_and_records_manifest(tmp_path, monkeypatch):
    calls = []

    def fake_download(url, dest, manifest, source, licence, **kwargs):
        calls.append((url, source, licence))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("{}", encoding="utf-8")
        manifest.add(dest, source, url, licence)
        return dest

    monkeypatch.setattr(regions, "download", fake_download)
    root = tmp_path / "data"
    manifest = Manifest(tmp_path / "manifest.jsonl", root)
    cfg = load_config("samples")
    path = regions.fetch_boundaries(root, manifest, cfg)
    assert path == root / "raw" / "boundaries" / "ne_50m_admin_0_countries.geojson"
    assert calls == [(cfg["boundaries"]["url"], "Natural Earth admin-0 countries 1:50m",
                      "Natural Earth: public domain")]
    assert manifest.is_current(path)


def test_build_cell_regions_writes_table_and_report_with_agreement(countries, geojson_path, tmp_path, capsys):
    from aetherguard.features import regions_build
    cfg = load_config("samples")
    ids = _cells((30.0, 80.0), (30.5, 80.0), (30.0, 70.0), (15.0, 77.0))
    terrain = pd.DataFrame({"cell_id": ids, "region_box": ["himalaya", "himalaya", "himalaya", "western_ghats"]})
    terrain.to_parquet(tmp_path / "terrain.parquet", index=False)
    positives = pd.DataFrame({"cell_id": [int(ids[0]), int(ids[2])],
                              "event_date": pd.to_datetime(["2010-07-01", "2010-07-02"]),
                              "region": ["himalaya", "himalaya"]})
    positives.to_parquet(tmp_path / "positives.parquet", index=False)
    out = tmp_path / "out"
    report = regions.build_cell_regions(tmp_path / "terrain.parquet", geojson_path, tmp_path / "positives.parquet",
                                        out, cfg)
    stored = pd.read_parquet(out / regions.CELL_REGIONS_NAME)
    assert list(stored["cell_id"]) == list(ids) and list(stored.columns) == regions.CELL_REGION_COLUMNS
    assert json.loads((out / regions.CELL_REGIONS_REPORT_NAME).read_text(encoding="utf-8")) == report
    assert report["per_region"] == {"himalaya": 2, "out_of_scope": 1, "western_ghats": 1}
    assert report["terrain_cells_by_region_box"]["western_ghats"]["per_region"] == {"western_ghats": 1}
    assert report["positive_agreement"]["disagree_cell_days"] == 1
    text = regions_build.format_report(report, out)
    assert "1 differ in 1 cells" in text and "PK" in text
