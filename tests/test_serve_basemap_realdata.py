"""India base map from the real sources (run with -m realdata): builds into a temporary directory.

The ETOPO tiles and the Natural Earth file are downloaded into data/raw/basemap on first use (about 150 MB) and reused.
"""
import json

import numpy as np
import pytest

from aetherguard.serve import basemap as bm

POINTS = {
    "Leh": (34.15, 77.58, bm.INDIA),
    "Gilgit (India point of view)": (35.92, 74.31, bm.INDIA),
    "Itanagar": (27.08, 93.61, bm.INDIA),
    "Port Blair": (11.62, 92.73, bm.INDIA),
    "Kavaratti": (10.57, 72.64, bm.INDIA),
    "Kathmandu": (27.72, 85.32, bm.NEPAL),
    "Thimphu": (27.47, 89.64, bm.BHUTAN),
    "Dhaka": (23.81, 90.41, bm.OTHER),
    "Colombo": (6.93, 79.85, bm.OTHER),
    "Arabian Sea 15N 65E": (15.0, 65.0, None),
    "Bay of Bengal": (14.0, 88.0, bm.SEA),
}


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out_dir = tmp_path_factory.mktemp("basemap")
    assert bm.main(["build", "--out-dir", str(out_dir)]) == 0
    with np.load(out_dir / bm.NPZ_NAME) as stored:
        arrays = {name: stored[name] for name in stored.files}
    return arrays, json.loads((out_dir / bm.JSON_NAME).read_text(encoding="utf-8"))


@pytest.mark.realdata
def test_real_build_has_the_documented_shape_and_sane_elevations(built):
    arrays, meta = built
    assert arrays["elev"].shape == arrays["mask"].shape == (630, 600)
    assert arrays["elev"].dtype == np.float32 and arrays["mask"].dtype == np.uint8
    assert not np.isnan(arrays["elev"]).any()
    assert meta["elev"]["india_max"] > 6000  # Himalayan cell means (a 5.5 km cell averages away the summits)
    assert meta["elev"]["min"] < -3000  # Bay of Bengal / Arabian Sea bathymetry is kept
    assert [o["name"] for o in meta["outline"]] == ["India", "Nepal", "Bhutan"]
    assert all(len(ring) >= 4 and ring[0] == ring[-1] for o in meta["outline"] for ring in o["rings"])
    assert {s["licence"] for s in meta["sources"]} == {bm.ETOPO_LICENCE, bm.COUNTRIES_LICENCE}


@pytest.mark.realdata
@pytest.mark.parametrize("label", sorted(POINTS))
def test_real_mask_classes_at_known_places(built, label):
    arrays, _ = built
    lat, lon, expected = POINTS[label]
    if expected is None:  # 15N 65E is west of the crop: outside the grid, so sea as far as the map is concerned
        with pytest.raises(ValueError, match="outside"):
            bm.INDIA_GRID.locate(lat, lon)
        return
    row, col = bm.INDIA_GRID.locate(lat, lon)
    assert arrays["mask"][row, col] == expected, label
