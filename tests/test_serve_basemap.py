"""India base map: area-averaged elevation, the country mask, the outline, the file schema, the manifest rows.

Everything is synthetic (tiny rasters and hand-made polygons in tmp_path); nothing is downloaded.
"""
import json
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import pytest

from aetherguard.grid import CELL_DEG, cell_center, latlon_to_cell
from aetherguard.manifest import Manifest
from aetherguard.serve import basemap as bm
from aetherguard.serve import terrain_grid as tg

TINY = bm.Grid(lat0=10.0, lon0=70.0, rows=4, cols=6)  # lat 10.0-10.2, lon 70.0-70.3


def square(lon0, lat0, lon1, lat1):
    return [[lon0, lat0], [lon1, lat0], [lon1, lat1], [lon0, lat1], [lon0, lat0]]


def feature(adm0, *polygons):
    """A GeoJSON feature; each polygon is a list of rings (exterior first)."""
    geometry = {"type": "MultiPolygon", "coordinates": list(polygons)}
    return {"type": "Feature", "properties": {"ADM0_A3": adm0}, "geometry": geometry}


def write_tile(path: Path, lat_lo, lat_hi, lon_lo, lon_hi, spacing, fn, fill=None):
    """A netCDF4-style tile (area-registered pixel centres, south first) with z = fn(lat, lon)."""
    lat = np.arange(lat_lo + spacing / 2, lat_hi, spacing)
    lon = np.arange(lon_lo + spacing / 2, lon_hi, spacing)
    z = np.broadcast_to(fn(lat[:, None], lon[None, :]), (len(lat), len(lon))).astype(np.float32)
    with h5py.File(path, "w") as handle:
        handle["lat"], handle["lon"] = lat, lon
        dataset = handle.create_dataset("z", data=z)
        if fill is not None:
            dataset.attrs["_FillValue"] = np.float32(fill)
    return path


# --- grid and orientation ---------------------------------------------------------------------

def test_default_grid_is_the_630_by_600_india_crop_of_the_global_grid():
    grid = bm.INDIA_GRID
    assert (grid.rows, grid.cols) == (630, 600)
    assert (grid.lat1, grid.lon1) == (37.5, 98.0)
    assert bm.GRID_STEP == CELL_DEG
    assert grid.locate(6.01, 68.01) == (0, 0)
    assert grid.locate(37.49, 97.99) == (629, 599)


def test_row_zero_is_south_and_cell_indices_agree_with_the_terrain_payload():
    """Same orientation as terrain_grid: the same cell sits at a constant offset between the two grids."""
    row_offset = round((tg.LAT0 - bm.INDIA_GRID.lat0) / CELL_DEG)
    col_offset = round((tg.LON0 - bm.INDIA_GRID.lon0) / CELL_DEG)
    assert (row_offset, col_offset) == (40, 80)
    for lat, lon in [(8.02, 72.03), (20.26, 80.74), (35.97, 97.96), (27.08, 93.61)]:
        cell = latlon_to_cell(lat, lon)
        table = pd.DataFrame({"cell_id": [cell], tg.ELEVATION_COLUMN: [123.0]})
        terrain_row, terrain_col = np.argwhere(tg.build_terrain_grid(table) == 123)[0]
        assert bm.INDIA_GRID.locate(lat, lon) == (terrain_row + row_offset, terrain_col + col_offset)


def test_locate_rejects_points_outside_the_crop():
    with pytest.raises(ValueError, match="outside"):
        bm.INDIA_GRID.locate(5.9, 80.0)
    with pytest.raises(ValueError, match="outside"):
        bm.INDIA_GRID.locate(20.0, 98.0)


def test_cell_ids_match_the_global_grid():
    ids = bm.INDIA_GRID.cell_ids()
    assert ids.shape == (630, 600)
    assert ids[0, 0] == latlon_to_cell(6.025, 68.025)
    lat, lon = cell_center(int(ids[100, 200]))
    assert (lat, lon) == pytest.approx((6.0 + 100.5 * CELL_DEG, 68.0 + 200.5 * CELL_DEG))


# --- area averaging ---------------------------------------------------------------------------

def test_area_average_means_each_block_and_ignores_missing_pixels():
    z = np.arange(16, dtype=np.float32).reshape(4, 4)
    out = bm.area_average(z, 2)
    assert out.dtype == np.float32
    assert out.tolist() == [[2.5, 4.5], [10.5, 12.5]]
    z[0, 0] = np.nan
    assert bm.area_average(z, 2)[0, 0] == pytest.approx(np.mean([1, 4, 5]))
    z[:2, :2] = np.nan
    assert np.isnan(bm.area_average(z, 2)[0, 0])


def test_area_average_rejects_a_raster_that_is_not_a_whole_number_of_blocks():
    with pytest.raises(ValueError, match="multiple"):
        bm.area_average(np.zeros((5, 4), dtype=np.float32), 2)


def test_elevation_is_the_area_mean_of_the_tile_pixels_per_cell(tmp_path):
    spacing = CELL_DEG / 4  # 4 x 4 pixels per cell
    tile = write_tile(tmp_path / "t.nc", 10.0, 10.2, 70.0, 70.3, spacing, lambda la, lo: (la - 10.0) * 1000 + (lo - 70.0) * 10)
    elev = bm.elevation_grid([tile], TINY)
    assert elev.shape == (4, 6) and elev.dtype == np.float32
    # z is linear, so the 4 x 4 block mean is the value at the cell centre
    centres_lat = 10.0 + (np.arange(4) + 0.5) * CELL_DEG
    centres_lon = 70.0 + (np.arange(6) + 0.5) * CELL_DEG
    expected = (centres_lat[:, None] - 10.0) * 1000 + (centres_lon[None, :] - 70.0) * 10
    assert elev == pytest.approx(expected, abs=1e-3)
    assert elev[3, 0] > elev[0, 0]  # row 0 is the south


def test_elevation_assembles_adjacent_tiles_and_clips_to_the_grid(tmp_path):
    spacing = CELL_DEG / 2
    south = write_tile(tmp_path / "s.nc", 9.9, 10.1, 69.9, 70.4, spacing, lambda la, lo: 100 + 0 * la * lo)
    north = write_tile(tmp_path / "n.nc", 10.1, 10.3, 69.9, 70.4, spacing, lambda la, lo: 200 + 0 * la * lo)
    elev = bm.elevation_grid([north, south], TINY)
    assert elev[:2].tolist() == [[100.0] * 6] * 2
    assert elev[2:].tolist() == [[200.0] * 6] * 2


def test_elevation_treats_the_fill_value_as_missing(tmp_path):
    spacing = CELL_DEG / 2
    tile = write_tile(tmp_path / "t.nc", 10.0, 10.2, 70.0, 70.3, spacing,
                      lambda la, lo: np.where(la < 10.025, -99999.0, 50.0), fill=-99999.0)
    elev = bm.elevation_grid([tile], TINY)
    assert elev[0].tolist() == [50.0] * 6  # one of the two pixel rows is missing, the other is kept
    assert elev.min() == 50.0


def test_elevation_fails_loudly_when_cells_are_not_covered(tmp_path):
    tile = write_tile(tmp_path / "t.nc", 10.0, 10.1, 70.0, 70.3, CELL_DEG / 2, lambda la, lo: la * 0)
    with pytest.raises(bm.BasemapError, match="not covered"):
        bm.elevation_grid([tile], TINY)


def test_elevation_rejects_a_tile_whose_resolution_does_not_divide_the_cell(tmp_path):
    tile = write_tile(tmp_path / "t.nc", 10.0, 10.2, 70.0, 70.3, CELL_DEG / 2.5, lambda la, lo: la * 0)
    with pytest.raises(bm.BasemapError, match="resolution"):
        bm.elevation_grid([tile], TINY)


def test_tile_names_cover_the_india_crop_with_nine_15_degree_tiles():
    names = bm.tile_names(bm.INDIA_GRID)
    assert len(names) == 9
    assert {n[len("ETOPO_2022_v1_15s_"):len("ETOPO_2022_v1_15s_") + 7] for n in names} == {
        f"N{top}E{west}" for top in ("15", "30", "45") for west in ("060", "075", "090")}
    assert all(n.endswith("_surface.nc") for n in names)


# --- mask -------------------------------------------------------------------------------------

def test_mask_classes_by_centre_point_with_priority():
    features = [
        feature("PAK", [square(70.0, 10.0, 70.3, 10.2)]),  # other land covers everything
        feature("NPL", [square(70.0, 10.0, 70.15, 10.2)]),  # Nepal over the western half
        feature("BTN", [square(70.15, 10.0, 70.3, 10.1)]),  # Bhutan in the south-east
        feature("IND", [square(70.1, 10.1, 70.3, 10.2)]),  # India in the north-east, overlapping Nepal
    ]
    mask = bm.classify_mask(features, TINY)
    assert mask.dtype == np.uint8 and mask.shape == (4, 6)
    assert mask.tolist() == [
        [2, 2, 2, 3, 3, 3],  # row 0 = south
        [2, 2, 2, 3, 3, 3],
        [2, 2, 1, 1, 1, 1],
        [2, 2, 1, 1, 1, 1],
    ]


def test_mask_is_zero_over_sea_and_outside():
    mask = bm.classify_mask([feature("IND", [square(70.0, 10.0, 70.1, 10.1)])], TINY)
    assert mask.sum() == 4 and mask[:2, :2].tolist() == [[1, 1], [1, 1]]
    assert set(np.unique(mask)) == {0, 1}


def test_mask_honours_holes():
    donut = [square(70.0, 10.0, 70.3, 10.2), square(70.1, 10.05, 70.2, 10.15)]
    mask = bm.classify_mask([feature("IND", donut)], TINY)
    assert mask[1:3, 2:4].tolist() == [[0, 0], [0, 0]]  # the lake / sea in the hole
    assert mask[0].tolist() == [1] * 6 and mask[3].tolist() == [1] * 6


def test_mask_marks_a_hole_filled_by_another_country_with_that_country():
    donut = [square(70.0, 10.0, 70.3, 10.2), square(70.1, 10.05, 70.2, 10.15)]
    mask = bm.classify_mask([feature("IND", donut), feature("NPL", [square(70.1, 10.05, 70.2, 10.15)])], TINY)
    assert mask[1:3, 2:4].tolist() == [[2, 2], [2, 2]]


def test_a_tiny_island_that_misses_every_cell_centre_still_marks_its_cell():
    island = square(70.21, 10.11, 70.23, 10.13)  # inside cell (row 2, col 4), well away from its centre
    mask = bm.classify_mask([feature("IND", [island])], TINY)
    assert mask.sum() == 1 and mask[2, 4] == 1


def test_a_tiny_island_never_overwrites_land_of_another_class():
    island = square(70.01, 10.01, 70.02, 10.02)
    mask = bm.classify_mask([feature("PAK", [square(70.0, 10.0, 70.1, 10.1)]), feature("IND", [island])], TINY)
    assert mask[0, 0] == 4


def test_features_outside_the_grid_are_ignored():
    mask = bm.classify_mask([feature("CHN", [square(100.0, 40.0, 101.0, 41.0)])], TINY)
    assert not mask.any()


def test_class_of_maps_natural_earth_codes():
    assert [bm.class_of(code) for code in ("IND", "NPL", "BTN", "PAK", "LKA")] == [1, 2, 3, 4, 4]


# --- outline ----------------------------------------------------------------------------------

def test_outline_is_simplified_closed_and_named_for_india_nepal_bhutan():
    n = 400
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    wobble = [[70.0 + 0.5 * np.cos(a), 10.0 + 0.5 * np.sin(a)] for a in t]
    wobble.append(wobble[0])
    features = [
        feature("IND", [wobble]),
        feature("NPL", [square(80.0, 28.0, 81.0, 29.0)]),
        feature("BTN", [square(90.0, 27.0, 91.0, 28.0)]),
        feature("PAK", [square(60.0, 30.0, 61.0, 31.0)]),
    ]
    outline = bm.outline_rings(features, tolerance=0.01)
    assert [o["name"] for o in outline] == ["India", "Nepal", "Bhutan"]
    ring = outline[0]["rings"][0]
    assert 8 <= len(ring) < n // 4
    assert ring[0] == ring[-1]
    assert all(len(p) == 2 for p in ring)
    assert max(abs(np.hypot(p[0] - 70.0, p[1] - 10.0) - 0.5) for p in ring) < 0.011
    assert outline[1]["rings"] == [[[80.0, 28.0], [81.0, 28.0], [81.0, 29.0], [80.0, 29.0], [80.0, 28.0]]]


def test_outline_keeps_holes_and_every_polygon_of_a_multipolygon():
    donut = [square(70.0, 10.0, 71.0, 11.0), square(70.4, 10.4, 70.6, 10.6)]
    features = [feature("IND", donut, [square(75.0, 12.0, 75.5, 12.5)]), feature("NPL", [square(80, 28, 81, 29)]),
                feature("BTN", [square(90, 27, 91, 28)])]
    assert len(bm.outline_rings(features, tolerance=0.01)[0]["rings"]) == 3


def test_outline_reports_a_missing_country():
    with pytest.raises(bm.BasemapError, match="Nepal"):
        bm.outline_rings([feature("IND", [square(70, 10, 71, 11)]), feature("BTN", [square(90, 27, 91, 28)])])


# --- build, schema, manifest ------------------------------------------------------------------

def fake_sources(tmp_path):
    """Two synthetic source files at the same relative paths a real run would use."""
    raw = tmp_path / "data" / "raw" / "basemap"
    raw.mkdir(parents=True)
    tile = write_tile(raw / "tile.nc", 10.0, 10.2, 70.0, 70.3, CELL_DEG / 2, lambda la, lo: 100 * (la - 10.0))
    countries = raw / "countries.geojson"
    features = [feature("IND", [square(70.0, 10.0, 70.2, 10.2)]), feature("NPL", [square(70.2, 10.0, 70.3, 10.2)]),
                feature("BTN", [square(70.2, 10.2, 70.3, 10.3)])]
    countries.write_text(json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8")
    return [
        bm.Source("ETOPO 2022 tile", "https://example.test/tile.nc", tile, "NOAA public domain", is_elevation=True),
        bm.Source("Natural Earth countries (India POV)", "https://example.test/countries.geojson", countries,
                  "Natural Earth public domain", is_elevation=False),
    ]


def fake_fetch(url, dest, manifest, source, licence):
    manifest.add(dest, source, url, licence)
    return dest


def test_build_writes_npz_and_json_with_the_documented_schema(tmp_path):
    sources = fake_sources(tmp_path)
    manifest = Manifest(tmp_path / "manifests" / "m.jsonl", tmp_path / "data")
    out = tmp_path / "out"
    meta = bm.build_basemap(sources, out, manifest, grid=TINY, fetch=fake_fetch)

    with np.load(out / "india_basemap.npz") as stored:
        assert set(stored.files) == {"elev", "mask", "lat0", "lon0", "step"}
        assert stored["elev"].dtype == np.float32 and stored["elev"].shape == (4, 6)
        assert stored["mask"].dtype == np.uint8 and stored["mask"].shape == (4, 6)
        assert (float(stored["lat0"]), float(stored["lon0"]), float(stored["step"])) == (10.0, 70.0, CELL_DEG)
        mask = stored["mask"]
    on_disk = json.loads((out / "india_basemap.json").read_text(encoding="utf-8"))
    assert on_disk == meta
    assert meta["schema_version"] == 1
    assert meta["grid"] == {
        "lat0": 10.0, "lat1": pytest.approx(10.2), "lon0": 70.0, "lon1": pytest.approx(70.3), "step_deg": CELL_DEG,
        "rows": 4, "cols": 6, "row0": "south", "col0": "west",
        "lat_index0": 2000, "lon_index0": 5000,
        "id_stride": 10000,
    }
    assert meta["mask"]["classes"] == {"0": "sea or outside", "1": "India", "2": "Nepal", "3": "Bhutan", "4": "other land"}
    assert meta["mask"]["counts"] == {"0": int((mask == 0).sum()), "1": int((mask == 1).sum()),
                                      "2": int((mask == 2).sum()), "3": int((mask == 3).sum()),
                                      "4": int((mask == 4).sum())}
    assert sum(meta["mask"]["counts"].values()) == 24
    assert meta["elev"]["unit"] == "m" and meta["elev"]["min"] <= meta["elev"]["max"]
    assert meta["elev"]["india_min"] <= meta["elev"]["india_max"]
    assert [o["name"] for o in meta["outline"]] == ["India", "Nepal", "Bhutan"]
    assert [s["name"] for s in meta["sources"]] == ["ETOPO 2022 tile", "Natural Earth countries (India POV)"]
    for source in meta["sources"]:
        assert set(source) == {"name", "url", "licence", "path", "size_bytes", "sha256"}
        assert len(source["sha256"]) == 64
    assert set(meta["files"]) == {"india_basemap.npz"}
    assert meta["files"]["india_basemap.npz"]["sha256"] == bm.sha256_file(out / "india_basemap.npz")
    assert meta["files"]["india_basemap.npz"]["size_bytes"] == (out / "india_basemap.npz").stat().st_size
    assert not list(out.glob("*.tmp"))


def test_build_records_every_source_in_the_manifest_with_url_and_licence(tmp_path):
    sources = fake_sources(tmp_path)
    manifest_path = tmp_path / "manifests" / "m.jsonl"
    manifest = Manifest(manifest_path, tmp_path / "data")
    bm.build_basemap(sources, tmp_path / "out", manifest, grid=TINY, fetch=fake_fetch)
    rows = [json.loads(line) for line in manifest_path.read_text(encoding="utf-8").splitlines()]
    assert {row["path"] for row in rows} == {"raw/basemap/tile.nc", "raw/basemap/countries.geojson"}
    by_path = {row["path"]: row for row in rows}
    assert by_path["raw/basemap/tile.nc"]["url"] == "https://example.test/tile.nc"
    assert by_path["raw/basemap/tile.nc"]["licence"] == "NOAA public domain"
    assert by_path["raw/basemap/countries.geojson"]["licence"] == "Natural Earth public domain"
    assert manifest.verify() == []


def test_build_does_not_fetch_a_source_that_is_already_current(tmp_path):
    sources = fake_sources(tmp_path)
    manifest = Manifest(tmp_path / "manifests" / "m.jsonl", tmp_path / "data")
    for source in sources:
        manifest.add(source.dest, source.name, source.url, source.licence)
    calls = []
    bm.build_basemap(sources, tmp_path / "out", manifest, grid=TINY, fetch=lambda *a: calls.append(a))
    assert calls == []


def test_build_fails_when_the_country_file_has_no_india(tmp_path):
    sources = fake_sources(tmp_path)
    sources[1].dest.write_text(json.dumps({"type": "FeatureCollection", "features": []}), encoding="utf-8")
    manifest = Manifest(tmp_path / "manifests" / "m.jsonl", tmp_path / "data")
    with pytest.raises(bm.BasemapError, match="India"):
        bm.build_basemap(sources, tmp_path / "out", manifest, grid=TINY, fetch=fake_fetch)


def test_cli_build_requires_the_subcommand_and_reports_failures(tmp_path, capsys):
    with pytest.raises(SystemExit):
        bm.main([])
    code = bm.main(["build", "--skip-download", "--raw-dir", str(tmp_path / "none"), "--out-dir", str(tmp_path / "o"),
                    "--manifest", str(tmp_path / "m.jsonl")])
    assert code == 1
    assert "basemap" in capsys.readouterr().err
