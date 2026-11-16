"""District boundaries, the cell-to-district table and the district level rule (serve.districts)."""
import json

import numpy as np
import pandas as pd
import pytest
from shapely.geometry import box, mapping

from aetherguard.grid import latlon_to_cell
from aetherguard.serve import districts as D


def _polygons():
    return pd.DataFrame({
        "country": ["India", "India", "Nepal"],
        "district_id": ["IND-a", "IND-b", "NPL-c"],
        "district": ["A", "B", "C"],
        "geometry": [box(80.0, 20.0, 80.5, 20.5), box(80.5, 20.0, 81.0, 20.5), box(80.4, 20.0, 80.7, 20.5)],
    })


def test_a_cell_takes_the_district_its_centre_lies_in_and_its_own_countrys_where_two_overlap():
    cells = pd.DataFrame({"cell_id": latlon_to_cell([20.22, 20.22, 20.22], [80.12, 80.62, 80.42]),
                          "country": ["India", "Nepal", "India"]})
    out = D.cell_districts(cells, _polygons(), max_nearest_km=5.0)
    assert out["district_id"].tolist() == ["IND-a", "NPL-c", "IND-a"]
    assert out["how"].tolist() == ["inside", "inside", "inside"]


def test_a_cell_outside_every_polygon_takes_the_nearest_of_its_country_within_the_limit_else_none():
    cells = pd.DataFrame({"cell_id": latlon_to_cell([20.52, 21.5], [80.22, 80.22]), "country": ["India", "India"]})
    out = D.cell_districts(cells, _polygons(), max_nearest_km=5.0)
    assert out["district_id"].iloc[0] == "IND-a" and out["how"].iloc[0] == "nearest"
    assert pd.isna(out["district_id"].iloc[1]) and out["how"].iloc[1] == "none"


def test_polygons_are_read_from_geojson_with_their_names(tmp_path):
    feature = {"type": "Feature", "properties": {"shapeName": "Kangra", "shapeID": "IND-1", "shapeGroup": "IND"},
               "geometry": mapping(box(76.0, 32.0, 76.5, 32.5))}
    path = tmp_path / "x.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": [feature]}), encoding="utf-8")
    table = D.read_polygons(path, "India")
    assert table[["country", "district_id", "district"]].values.tolist() == [["India", "IND-1", "Kangra"]]
    assert table["geometry"].iloc[0].contains(box(76.1, 32.1, 76.2, 32.2))


def test_the_district_level_rule_counts_cells_or_their_share():
    # district 0 has 4 cells, district 1 has 2; -1 is a cell without a district
    district = np.array([0, 0, 0, 0, 1, 1, -1])
    levels = np.array([[3], [1], [0], [0], [2], [0], [3]], dtype=np.int8)
    scored = np.ones(levels.shape, dtype=bool)
    any_cell = D.DistrictRule(cells=1, share=None)
    assert D.district_levels(levels, scored, district, 2, any_cell)[:, 0].tolist() == [3, 2]
    two = D.DistrictRule(cells=2, share=None)                # district 0: one cell at Emergency, two at Watch+
    assert D.district_levels(levels, scored, district, 2, two)[:, 0].tolist() == [1, 0]
    half = D.DistrictRule(cells=None, share=0.5)             # district 1: 1 of 2 cells at Warning+
    assert D.district_levels(levels, scored, district, 2, half)[:, 0].tolist() == [1, 2]
    either = D.DistrictRule(cells=2, share=0.5)
    assert D.district_levels(levels, scored, district, 2, either)[:, 0].tolist() == [1, 2]


def test_the_share_is_of_the_scored_cells_of_the_day():
    district = np.array([0, 0, 0, 0])
    levels = np.array([[2, 2], [0, 0], [0, 0], [0, 0]], dtype=np.int8)
    scored = np.array([[True, True], [True, False], [False, False], [False, False]])
    rule = D.DistrictRule(cells=None, share=0.5)
    assert D.district_levels(levels, scored, district, 1, rule)[0].tolist() == [2, 2]


def test_a_rule_needs_a_count_or_a_share():
    with pytest.raises(ValueError):
        D.DistrictRule(cells=None, share=None)
    assert D.DistrictRule(cells=3, share=0.1).name == "3 cells or 10% of cells"
