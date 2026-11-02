"""Copernicus GLO-90 terrain ingest: tiles, download, surface maths, per-cell statistics, CLI.

Offline and hermetic (synthetic GeoTIFF tiles in tmp_path); real tiles are marked realdata.
"""
import json
import math

import numpy as np
import pandas as pd
import pytest
import rasterio
from affine import Affine

from aetherguard.config import data_root
from aetherguard.grid import region_labels
from aetherguard.http import DownloadError
from aetherguard.ingest import terrain, terrain_build
from aetherguard.ingest.terrain import (
    ABSENT_FILE,
    M_PER_DEG,
    TerrainIncompleteError,
    TileAbsentError,
    build_terrain,
    cell_terrain,
    cells_in_boxes,
    download_tiles,
    terrain_surface,
    tile_name,
    tile_url,
    tiles_for_bbox,
)
from aetherguard.manifest import Manifest

PX = 1200
STEP = 1.0 / PX
# Four tiles around (12.0 N, 76.0 E): the border lines of tiles and of cells coincide at the box centre.
BOX = {"lat_min": 11.95, "lat_max": 12.05, "lon_min": 75.95, "lon_max": 76.05}
ALL_TILES = [(11, 75), (11, 76), (12, 75), (12, 76)]


def _fail_on_constant(name):
    raise AssertionError(f"report is not strict JSON: {name}")


def write_tile(raw_dir, tile, fn):
    """Write a synthetic GLO-90 tile; fn(lat, lon) gets the pixel-centre coordinate grids (north-up)."""
    lat_floor, lon_floor = tile
    lat = (lat_floor + 1) - np.arange(PX) / PX
    lon = lon_floor + np.arange(PX) / PX
    values = np.asarray(fn(lat[:, None] + 0 * lon[None, :], lon[None, :] + 0 * lat[:, None]), dtype="float32")
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = terrain.tile_path(raw_dir, *tile)
    with rasterio.open(path, "w", driver="GTiff", height=PX, width=PX, count=1, dtype="float32", crs="EPSG:4326",
                       transform=Affine(STEP, 0.0, lon_floor - STEP / 2, 0.0, -STEP, lat_floor + 1 + STEP / 2),
                       compress="deflate") as ds:
        ds.write(values, 1)
    return path


def write_tiles(raw_dir, fn, tiles=ALL_TILES):
    for tile in tiles:
        write_tile(raw_dir, tile, fn)


def record_absent(raw_dir, tiles):
    (raw_dir / ABSENT_FILE).write_text(json.dumps(sorted(tile_name(*t) for t in tiles)), encoding="utf-8")


def plane_east_down(slope_deg):
    """Elevation falling toward the east at the given slope, exact in metres at every latitude."""
    tan = math.tan(math.radians(slope_deg))
    return lambda lat, lon: 8000.0 - tan * M_PER_DEG * np.cos(np.radians(lat)) * (lon - 76.0)


def cell_row(table, lat, lon):
    row = table[np.isclose(table["lat"], lat, atol=1e-9) & np.isclose(table["lon"], lon, atol=1e-9)]
    assert len(row) == 1, f"no cell at ({lat}, {lon})"
    return row.iloc[0]


@pytest.fixture
def manifest(tmp_path):
    return Manifest(tmp_path / "manifest.jsonl", tmp_path / "data")


@pytest.fixture
def raw_dir(tmp_path):
    return tmp_path / "data" / "raw" / "terrain" / "glo90"


# ---------------------------------------------------------------- tile naming and lists
def test_tile_name_and_url_match_the_verified_glo90_pattern():
    assert tile_name(11, 76) == "Copernicus_DSM_COG_30_N11_00_E076_00_DEM"
    assert tile_url(11, 76) == ("https://copernicus-dem-90m.s3.amazonaws.com/"
                                "Copernicus_DSM_COG_30_N11_00_E076_00_DEM/Copernicus_DSM_COG_30_N11_00_E076_00_DEM.tif")


def test_tile_name_hemisphere_and_zero_edges():
    assert tile_name(0, 0) == "Copernicus_DSM_COG_30_N00_00_E000_00_DEM"
    assert tile_name(-1, -1) == "Copernicus_DSM_COG_30_S01_00_W001_00_DEM"
    assert tile_name(-90, -180) == "Copernicus_DSM_COG_30_S90_00_W180_00_DEM"
    assert tile_name(89, 179) == "Copernicus_DSM_COG_30_N89_00_E179_00_DEM"
    assert tile_name(5, -3) == "Copernicus_DSM_COG_30_N05_00_W003_00_DEM"
    for bad in [(90, 0), (0, 180), (-91, 0), (0, -181)]:
        with pytest.raises(ValueError):
            tile_name(*bad)
    with pytest.raises(ValueError):
        tile_name(11.5, 76)


def test_tiles_for_bbox_includes_halo_tiles_at_exact_edges():
    # box edges on whole degrees: the southern edge row and the eastern halo column live in the next tiles over
    tiles = tiles_for_bbox(22.0, 24.0, 72.0, 74.0)
    assert sorted({t[0] for t in tiles}) == [21, 22, 23]
    assert sorted({t[1] for t in tiles}) == [71, 72, 73, 74]
    assert len(tiles) == 12
    # no extra tile to the north or the west beyond the one halo row / column
    assert (24, 72) not in tiles and (22, 70) not in tiles


def test_tiles_for_bbox_between_degrees_and_around_the_box_centre():
    assert tiles_for_bbox(11.95, 12.05, 75.95, 76.05) == ALL_TILES
    # a box strictly inside one tile (not touching its south or east edge) needs only that tile
    assert tiles_for_bbox(11.1, 11.9, 76.1, 76.9) == [(11, 76)]


def test_tiles_for_default_regions_cover_both_boxes_without_duplicates():
    tiles = terrain.tiles_for_boxes(terrain.default_boxes())
    assert len(tiles) == len(set(tiles)) and tiles == sorted(tiles)
    assert (11, 76) in tiles       # Wayanad
    assert (30, 78) in tiles       # Uttarkashi
    assert (7, 76) in tiles        # halo row south of the Ghats box
    assert len(tiles) == 518


def test_cells_in_boxes_matches_grid_region_labels_and_marks_overlap_as_both():
    cells = cells_in_boxes(terrain.default_boxes())
    labels = region_labels(cells["lat"].to_numpy(), cells["lon"].to_numpy())
    assert (labels == cells["region_box"].to_numpy()).all()
    assert cells["cell_id"].is_unique and cells["cell_id"].is_monotonic_increasing
    assert cells["region_box"].value_counts().to_dict() == {"himalaya": 280 * 520, "western_ghats": 270 * 120}
    overlap = cells_in_boxes({"a": {"lat_min": 10.0, "lat_max": 10.2, "lon_min": 70.0, "lon_max": 70.2},
                              "b": {"lat_min": 10.1, "lat_max": 10.3, "lon_min": 70.0, "lon_max": 70.2}})
    assert overlap["region_box"].value_counts().to_dict() == {"a": 8, "b": 8, "both": 8}
    # a centre exactly on the max edge is outside (same rule as grid.region_labels)
    edge = cells_in_boxes({"a": {"lat_min": 10.0, "lat_max": 10.05, "lon_min": 70.0, "lon_max": 70.05}})
    assert len(edge) == 1


# ---------------------------------------------------------------- download
def fake_tile_fetcher(calls, absent=(), failing=(), empty=()):
    def fetch(tile, dest):
        calls.append(tile)
        if tile in absent:
            raise TileAbsentError("HTTP 404")
        if tile in failing:
            raise RuntimeError("server said no")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"" if tile in empty else bytes([tile[0] % 256, tile[1] % 256]) * 50)
    return fetch


def test_download_registers_records_absent_and_is_idempotent(raw_dir, manifest):
    calls = []
    fetch = fake_tile_fetcher(calls, absent={(11, 75)})
    report = download_tiles(ALL_TILES, raw_dir, manifest, workers=3, fetch=fetch)
    assert sorted(calls) == ALL_TILES
    assert report.ok == sorted(tile_name(*t) for t in ALL_TILES[1:])
    assert report.absent == [tile_name(11, 75)] and report.failed == {}
    assert report.bytes_downloaded == 300
    assert sorted(manifest.entries()) == sorted(f"raw/terrain/glo90/{tile_name(*t)}.tif" for t in ALL_TILES[1:])
    assert not terrain.tile_path(raw_dir, 11, 75).exists()
    assert json.loads((raw_dir / ABSENT_FILE).read_text()) == [tile_name(11, 75)]

    again = []
    report = download_tiles(ALL_TILES, raw_dir, manifest, fetch=fake_tile_fetcher(again))
    assert again == []
    assert report.ok == [] and len(report.already_present) == 3 and report.absent == [tile_name(11, 75)]
    assert report.bytes_downloaded == 0


def test_download_collects_failures_without_stopping_and_retries_them_next_run(raw_dir, manifest):
    calls = []
    report = download_tiles(ALL_TILES, raw_dir, manifest, backoff=0,
                            fetch=fake_tile_fetcher(calls, failing={(12, 75)}, empty={(12, 76)}))
    assert sorted(report.failed) == [tile_name(12, 75), tile_name(12, 76)]
    assert "RuntimeError" in report.failed[tile_name(12, 75)] and "empty" in report.failed[tile_name(12, 76)]
    assert len(report.ok) == 2 and calls.count((12, 75)) == 3        # first pass plus two retry passes
    assert not terrain.tile_path(raw_dir, 12, 75).exists()
    retry = []
    report = download_tiles(ALL_TILES, raw_dir, manifest, fetch=fake_tile_fetcher(retry))
    assert sorted(retry) == [(12, 75), (12, 76)] and report.failed == {} and len(report.already_present) == 2


def test_download_retries_a_transient_failure_in_a_later_pass(raw_dir, manifest):
    attempts = []
    good = fake_tile_fetcher([])

    def flaky(tile, dest):
        attempts.append(tile)
        if len(attempts) <= 1:
            raise OSError("[WinError 32] file in use")
        good(tile, dest)

    report = download_tiles([(11, 76)], raw_dir, manifest, backoff=0, fetch=flaky)
    assert report.ok == [tile_name(11, 76)] and report.failed == {} and len(attempts) == 2


def test_download_refetches_a_file_that_no_longer_matches_the_manifest(raw_dir, manifest):
    download_tiles([(11, 76)], raw_dir, manifest, fetch=fake_tile_fetcher([]))
    terrain.tile_path(raw_dir, 11, 76).write_bytes(b"corrupted")
    calls = []
    report = download_tiles([(11, 76)], raw_dir, manifest, fetch=fake_tile_fetcher(calls))
    assert calls == [(11, 76)] and report.ok == [tile_name(11, 76)]


def test_download_validates_workers_and_duplicates(raw_dir, manifest):
    for workers in (0, 7):
        with pytest.raises(ValueError):
            download_tiles(ALL_TILES, raw_dir, manifest, workers=workers, fetch=fake_tile_fetcher([]))
    with pytest.raises(ValueError):
        download_tiles([(11, 76), (11, 76)], raw_dir, manifest, fetch=fake_tile_fetcher([]))


def test_default_fetcher_maps_http_404_to_absent_and_other_errors_to_failed(raw_dir, manifest, monkeypatch):
    seen = []

    def fake_download(url, dest, manifest_arg, source, licence, **kwargs):
        seen.append(url)
        if "N11" in url:
            raise DownloadError("HTTP 404", status=404)
        if "N12" in url:
            raise DownloadError("HTTP 503", retriable=True, status=503)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"x" * 10)
        manifest_arg.add(dest, source, url, licence)

    monkeypatch.setattr(terrain, "download", fake_download)
    report = download_tiles([(11, 76), (12, 76), (13, 76)], raw_dir, manifest, retries=1, backoff=0)
    assert report.absent == [tile_name(11, 76)]
    assert list(report.failed) == [tile_name(12, 76)] and "503" in report.failed[tile_name(12, 76)]
    assert report.ok == [tile_name(13, 76)]
    assert all(url.startswith("https://copernicus-dem-90m.s3.amazonaws.com/") for url in seen)


def test_known_absent_tiles_are_not_requested_again(raw_dir, manifest):
    download_tiles([(11, 75)], raw_dir, manifest, fetch=fake_tile_fetcher([], absent={(11, 75)}))
    calls = []
    report = download_tiles([(11, 75)], raw_dir, manifest, fetch=fake_tile_fetcher(calls))
    assert calls == [] and report.absent == [tile_name(11, 75)]


# ---------------------------------------------------------------- surface maths
def test_surface_of_an_eastward_falling_plane_is_exact_and_faces_east():
    dx, dy = 90.0, 92.0
    x = np.arange(30) * dx
    z = np.tile(1000.0 - 0.2 * x, (30, 1))                      # falls 0.2 m per metre toward +x (east)
    s = terrain_surface(z, dx, dy)
    assert np.nanmax(np.abs(s["slope_deg"] - math.degrees(math.atan(0.2)))) < 1e-9
    assert np.allclose(s["aspect_sin"][1:-1, 1:-1], 1.0) and np.allclose(s["aspect_cos"][1:-1, 1:-1], 0.0)
    assert np.isnan(s["slope_deg"][0]).all() and np.isnan(s["slope_deg"][:, -1]).all()


def test_surface_aspect_faces_north_when_the_plane_falls_northward():
    z = np.tile((1000.0 - 0.3 * np.arange(30) * 92.0)[:, None], (1, 30))   # rows increase northward
    s = terrain_surface(z, 90.0, 92.0)
    assert np.allclose(s["aspect_cos"][1:-1, 1:-1], 1.0) and np.allclose(s["aspect_sin"][1:-1, 1:-1], 0.0)


def test_surface_uses_the_per_row_east_west_pixel_size():
    z = np.tile(1000.0 - np.arange(20) * 50.0, (10, 1))        # 50 m per pixel eastward
    dx = np.linspace(100.0, 50.0, 10)
    s = terrain_surface(z, dx, 90.0)
    expected = np.degrees(np.arctan(50.0 / dx))
    assert np.allclose(s["slope_deg"][1:-1, 5], expected[1:-1])


def test_surface_curvature_sign_convex_ridge_positive_valley_negative():
    dx = dy = 90.0
    x = (np.arange(41) - 20) * dx
    ridge = np.tile(2000.0 - 1e-3 * x ** 2, (41, 1))
    valley = np.tile(1000.0 + 1e-3 * x ** 2, (41, 1))
    assert np.allclose(terrain_surface(ridge, dx, dy)["curvature"][1:-1, 1:-1], 2e-3)
    assert np.allclose(terrain_surface(valley, dx, dy)["curvature"][1:-1, 1:-1], -2e-3)
    yy, xx = np.meshgrid(x, x, indexing="ij")
    cone = 3000.0 - 0.3 * np.hypot(xx, yy)
    curvature = terrain_surface(cone, dx, dy)["curvature"]
    assert curvature[20, 30] > 0 and curvature[20, 10] > 0     # off the apex a cone is convex all around


def test_surface_flat_is_zero_slope_with_nan_aspect_and_invalid_neighbours_propagate():
    z = np.full((12, 12), 500.0)
    z[5, 5] = np.nan
    s = terrain_surface(z, 90.0, 92.0)
    assert np.nanmax(s["slope_deg"]) == 0.0
    assert np.isnan(s["aspect_sin"][1:-1, 1:-1][~np.isnan(s["slope_deg"][1:-1, 1:-1])]).all()
    assert np.isnan(s["slope_deg"][4:7, 4:7]).all() and not np.isnan(s["slope_deg"][3, 3])
    assert np.nanmax(s["twi_proxy"]) == pytest.approx(math.log(1 / math.tan(math.radians(0.1))))


# ---------------------------------------------------------------- per-cell statistics
@pytest.mark.parametrize("lat_floor, slope", [(11, 10.0), (33, 10.0), (33, 25.0)])
def test_tilted_plane_slope_matches_the_analytic_slope_at_two_latitudes(tmp_path, lat_floor, slope):
    raw = tmp_path / "raw"
    tiles = [(lat_floor, 75), (lat_floor, 76)]
    write_tiles(raw, plane_east_down(slope), tiles)
    box = {"lat_min": lat_floor + 0.25, "lat_max": lat_floor + 0.35, "lon_min": 75.95, "lon_max": 76.05}
    table, stats = cell_terrain(raw, {"box": box})
    assert len(table) == 4 and stats["cells_kept"] == 4
    assert table["slope_mean"].to_numpy() == pytest.approx(slope, rel=0.01)
    assert table["slope_max"].to_numpy() == pytest.approx(slope, rel=0.01)
    assert table["aspect_sin"].to_numpy() == pytest.approx(1.0, abs=0.01)     # faces east
    assert table["aspect_cos"].to_numpy() == pytest.approx(0.0, abs=0.01)
    assert table["curvature_mean"].abs().max() < 1e-6
    assert (table["valid_frac"] == 1.0).all() and (table["slope_valid_frac"] == 1.0).all()


def test_flat_plane_has_zero_slope_and_nan_aspect(tmp_path):
    raw = tmp_path / "raw"
    write_tiles(raw, lambda lat, lon: np.full(lat.shape, 500.0))
    table, _ = cell_terrain(raw, {"box": BOX})
    assert (table["slope_mean"] == 0).all() and (table["slope_max"] == 0).all() and (table["slope_p90"] == 0).all()
    assert table["aspect_sin"].isna().all() and table["aspect_cos"].isna().all()
    assert (table["relief"] == 0).all() and (table["elev_mean"] == 500).all() and (table["elev_std"] == 0).all()
    assert table["twi_proxy"].to_numpy() == pytest.approx(math.log(1 / math.tan(math.radians(0.1))))


def test_elevation_statistics_of_a_known_ramp(tmp_path):
    raw = tmp_path / "raw"
    # elevation = global pixel row index in metres: exactly 1 m per pixel row northward
    write_tiles(raw, lambda lat, lon: np.round((lat + 90.0) * PX))
    table, _ = cell_terrain(raw, {"box": BOX})
    cell = cell_row(table, 12.025, 75.975)
    first_row = round((12.0 + 90.0) * PX)
    assert cell["elev_min"] == first_row and cell["elev_max"] == first_row + 59
    assert cell["relief"] == 59 and cell["elev_mean"] == pytest.approx(first_row + 29.5)
    assert cell["elev_std"] == pytest.approx(np.std(np.arange(60)))
    assert cell["slope_mean"] == pytest.approx(math.degrees(math.atan(1.0 / (M_PER_DEG / PX))), rel=1e-6)


def smooth_terrain(lat, lon):
    return 1500.0 + 800.0 * np.sin(37.0 * lat) * np.cos(29.0 * lon) + 300.0 * np.sin(11.0 * lon + 3.0 * lat)


def test_cells_on_tile_borders_equal_the_same_cells_computed_on_one_large_raster(tmp_path):
    raw = tmp_path / "raw"
    write_tiles(raw, smooth_terrain)
    table, _ = cell_terrain(raw, {"box": BOX})
    assert len(table) == 4

    # reference: the same four tiles stitched by hand into one raster, no windows, no halo logic
    def read(tile):
        with rasterio.open(terrain.tile_path(raw, *tile)) as ds:
            return ds.read(1).astype("float64")

    north_up = np.vstack([np.hstack([read((12, 75)), read((12, 76))]), np.hstack([read((11, 75)), read((11, 76))])])
    big = north_up[::-1]                                            # rows increase northward
    first_row, first_col = (11 + 90) * PX + 1, (75 + 180) * PX      # global index of big[0, 0]
    latitudes = -90.0 + (first_row + np.arange(big.shape[0])) / PX
    surface = terrain_surface(big, M_PER_DEG * np.cos(np.radians(latitudes)) / PX, M_PER_DEG / PX)
    for cell_lat, cell_lon in [(11.975, 75.975), (11.975, 76.025), (12.025, 75.975), (12.025, 76.025)]:
        r0 = round((cell_lat - 0.025 + 90) * PX) - first_row
        c0 = round((cell_lon - 0.025 + 180) * PX) - first_col
        block = (slice(r0, r0 + 60), slice(c0, c0 + 60))
        row = cell_row(table, cell_lat, cell_lon)
        assert row["slope_mean"] == pytest.approx(np.mean(surface["slope_deg"][block]), rel=1e-12)
        assert row["slope_p90"] == pytest.approx(np.percentile(surface["slope_deg"][block], 90), rel=1e-12)
        assert row["curvature_mean"] == pytest.approx(np.mean(surface["curvature"][block]), rel=1e-9, abs=1e-15)
        assert row["twi_proxy"] == pytest.approx(np.mean(surface["twi_proxy"][block]), rel=1e-12)
        assert row["elev_mean"] == pytest.approx(np.mean(big[block]), rel=1e-12)
        assert row["slope_valid_frac"] == 1.0 and row["valid_frac"] == 1.0


def test_void_pixels_the_90_percent_rule_and_sea_level_zeros(tmp_path):
    raw = tmp_path / "raw"
    row_a, col_a = round((12.0 + 90) * PX), round((76.0 + 180) * PX)     # global index of the SW pixel of cell A

    def terrain_with_defects(lat, lon):
        z = 800.0 + 100.0 * (lon - 76.0)
        g = np.round((lat + 90.0) * PX).astype(int) - row_a             # pixel row relative to cell A's first row
        c = np.round((lon + 180.0) * PX).astype(int) - col_a
        z = np.where((c >= 0) & (c < 60) & (g >= 0) & (g < 3), np.nan, z)        # A: 3 of 60 rows void = 5 %
        z = np.where((c >= 60) & (c < 120) & (g >= 0) & (g < 9), np.nan, z)      # B: 15 % void
        z = np.where((c >= 0) & (c < 60) & (g >= 60) & (g < 72), 0.0, z)         # C: 20 % sea level
        return z

    write_tiles(raw, terrain_with_defects)
    box = {"lat_min": 12.0, "lat_max": 12.1, "lon_min": 76.0, "lon_max": 76.1}
    table, stats = cell_terrain(raw, {"box": box})
    assert stats["cells_considered"] == 4 and stats["cells_kept"] == 2
    assert stats["cells_dropped"] == {"insufficient_dem": 2}
    assert stats["insufficient_dem_detail"] == {"absent_tile": 0, "sea_or_water": 1, "void_pixels": 1, "edge_halo": 0}
    kept = cell_row(table, 12.025, 76.025)                              # cell A
    assert kept["valid_frac"] == pytest.approx(0.95)
    assert 0.9 <= kept["slope_valid_frac"] < kept["valid_frac"]         # the ring around the voids has no slope
    assert kept["elev_mean"] == pytest.approx(800.0 + 100.0 * 0.025, abs=0.5)
    analytic = math.degrees(math.atan(100.0 / (M_PER_DEG * math.cos(math.radians(12.025)))))
    assert kept["slope_mean"] == pytest.approx(analytic, rel=0.01)      # voids did not poison the statistic
    assert not np.isnan(cell_row(table, 12.075, 76.075)["slope_mean"])   # cell D, clean apart from its neighbours
    assert stats["pixels_sea_level_zero"] == 12 * 60 and stats["pixels_void"] == (3 + 9) * 60
    assert stats["kept_by_region_box"] == {"box": 2} and stats["dropped_by_region_box"] == {"box": 2}


def test_speckled_voids_keep_the_90_percent_elevation_rule_but_not_slopes_on_a_few_pixels(tmp_path):
    raw = tmp_path / "raw"
    row_a, col_a = round((12.0 + 90) * PX), round((76.0 + 180) * PX)

    def speckled(lat, lon):
        g = np.round((lat + 90.0) * PX).astype(int) - row_a
        c = np.round((lon + 180.0) * PX).astype(int) - col_a
        void = (c >= 0) & (c < 60) & (g >= 0) & (g < 60) & (g % 4 == 0) & (c % 4 == 0)   # 1 pixel in 16 is void
        return np.where(void, np.nan, 900.0 + 0.0 * lat)

    write_tiles(raw, speckled)
    table, stats = cell_terrain(raw, {"box": {"lat_min": 12.0, "lat_max": 12.05, "lon_min": 76.0, "lon_max": 76.05}})
    assert len(table) == 0 and stats["insufficient_dem_detail"]["edge_halo"] == 1   # 94 % elevation, 6 % slope


def test_a_void_edge_row_costs_slope_pixels_but_keeps_the_cell(tmp_path):
    raw = tmp_path / "raw"
    row_a, col_a = round((12.0 + 90) * PX), round((76.0 + 180) * PX)

    def one_void_row(lat, lon):
        g = np.round((lat + 90.0) * PX).astype(int) - row_a
        c = np.round((lon + 180.0) * PX).astype(int) - col_a
        return np.where((c >= 0) & (c < 60) & (g == 59), np.nan, 900.0 + 0.0 * lat)   # top pixel row void

    write_tiles(raw, one_void_row)
    table, _ = cell_terrain(raw, {"box": {"lat_min": 12.0, "lat_max": 12.05, "lon_min": 76.0, "lon_max": 76.05}})
    assert len(table) == 1
    assert table.iloc[0]["valid_frac"] == pytest.approx(59 / 60)
    assert table.iloc[0]["slope_valid_frac"] == pytest.approx(58 / 60)


def test_absent_tiles_drop_their_cells_and_missing_unrecorded_tiles_are_an_error(tmp_path):
    raw = tmp_path / "raw"
    write_tiles(raw, plane_east_down(10.0), [(11, 75), (11, 76), (12, 75)])
    with pytest.raises(TerrainIncompleteError, match="N12_00_E076"):
        cell_terrain(raw, {"box": BOX})
    record_absent(raw, [(12, 76)])
    table, stats = cell_terrain(raw, {"box": BOX})
    # cell [12.0, 12.05) x [76.0, 76.05) is all tile (12, 76) except one pixel row: dropped, the other three kept
    assert stats["cells_kept"] == 3 and stats["cells_dropped"] == {"insufficient_dem": 1}
    assert stats["insufficient_dem_detail"]["absent_tile"] == 1
    assert sorted(zip(table["lat"].round(3), table["lon"].round(3))) == [(11.975, 75.975), (11.975, 76.025),
                                                                         (12.025, 75.975)]
    assert stats["pixels_absent_tile"] > 3500


def test_a_cell_whose_halo_touches_an_absent_tile_loses_only_the_edge_slopes(tmp_path):
    raw = tmp_path / "raw"
    write_tiles(raw, plane_east_down(10.0))
    full, _ = cell_terrain(raw, {"box": BOX})
    raw2 = tmp_path / "raw2"
    write_tiles(raw2, plane_east_down(10.0), [(11, 75), (11, 76), (12, 75)])
    record_absent(raw2, [(12, 76)])
    partial, _ = cell_terrain(raw2, {"box": BOX})
    untouched = cell_row(partial, 11.975, 76.025)       # every pixel and halo pixel is in a present tile
    assert untouched["slope_valid_frac"] == 1.0
    assert untouched["slope_mean"] == pytest.approx(cell_row(full, 11.975, 76.025)["slope_mean"], rel=1e-12)
    edge = cell_row(partial, 12.025, 75.975)            # its eastern halo column is in the absent tile
    assert edge["valid_frac"] == 1.0 and edge["slope_valid_frac"] == pytest.approx(59 / 60)
    assert edge["slope_mean"] == pytest.approx(cell_row(full, 12.025, 75.975)["slope_mean"], rel=1e-3)


def test_output_is_deterministic_sorted_and_has_the_documented_columns(tmp_path):
    raw = tmp_path / "raw"
    write_tiles(raw, smooth_terrain)
    first, _ = cell_terrain(raw, {"box": BOX})
    second, _ = cell_terrain(raw, {"box": BOX})
    pd.testing.assert_frame_equal(first, second)
    assert list(first.columns) == terrain.TERRAIN_COLUMNS
    assert first["cell_id"].is_monotonic_increasing and first["cell_id"].dtype == np.int64
    assert (first["region_box"] == "box").all()


def test_wrong_tile_geometry_is_rejected(tmp_path):
    raw = tmp_path / "raw"
    write_tiles(raw, plane_east_down(5.0), [(11, 76)])
    path = terrain.tile_path(raw, 11, 76)
    with rasterio.open(path, "w", driver="GTiff", height=10, width=10, count=1, dtype="float32", crs="EPSG:4326",
                       transform=Affine(0.1, 0.0, 76.0, 0.0, -0.1, 12.0)) as ds:
        ds.write(np.ones((10, 10), dtype="float32"), 1)
    box = {"lat_min": 11.2, "lat_max": 11.3, "lon_min": 76.2, "lon_max": 76.3}
    with pytest.raises(terrain.TerrainError, match="geometry"):
        cell_terrain(raw, {"box": box})


def test_declared_nodata_values_are_voids(tmp_path):
    raw = tmp_path / "raw"
    write_tile(raw, (11, 76), lambda lat, lon: np.full(lat.shape, 700.0))
    path = terrain.tile_path(raw, 11, 76)
    with rasterio.open(path, "r+") as ds:
        data = ds.read(1)
        data[:, :400] = -32767.0
        ds.write(data, 1)
        ds.nodata = -32767.0
    box = {"lat_min": 11.2, "lat_max": 11.3, "lon_min": 76.2, "lon_max": 76.4}
    table, stats = cell_terrain(raw, {"box": box})
    # columns 0..399 (76.0 .. 76.3325) are nodata: only the cells at lon 76.35..76.4 are intact
    assert stats["cells_kept"] == 2 and stats["cells_dropped"] == {"insufficient_dem": 6}
    assert (table["lon"].round(3) == 76.375).all()
    assert (table["elev_mean"] == 700).all() and (table["slope_mean"] == 0).all()


# ---------------------------------------------------------------- build, report, CLI
def test_build_writes_parquet_and_strict_json_report_with_relative_paths(tmp_path, isolated_data_root):
    raw = isolated_data_root / "raw" / "terrain" / "glo90"
    out = isolated_data_root / "processed" / "terrain"
    write_tiles(raw, lambda lat, lon: np.full(lat.shape, 500.0))
    record_absent(raw, [])
    report = build_terrain(raw, out, {"box": BOX})
    table = pd.read_parquet(out / "cell_terrain.parquet")
    assert len(table) == 4 and report["cells"]["cells_kept"] == 4
    text = (out / "terrain_report.json").read_text(encoding="utf-8")
    parsed = json.loads(text, parse_constant=_fail_on_constant)     # NaN / Infinity would raise
    assert parsed["regions"]["box"]["slope_mean"]["max"] == 0.0
    assert parsed["paths"] == {"raw_dir": "raw/terrain/glo90", "cell_terrain": "processed/terrain/cell_terrain.parquet"}
    assert str(isolated_data_root) not in text and "\\" not in text
    assert parsed["tiles"]["needed"] == 4 and parsed["tiles"]["present"] == 4 and parsed["tiles"]["absent"] == []
    assert parsed["cells"]["cells_dropped"] == {"insufficient_dem": 0}
    assert not list(out.glob("*.part"))


def test_json_safe_turns_nan_and_inf_into_null_and_numpy_scalars_into_numbers():
    assert terrain._json_safe({"a": float("nan"), "b": np.float64("inf"), "c": np.int64(3)}) == {"a": None, "b": None, "c": 3}


@pytest.fixture
def cli_env(isolated_data_root, monkeypatch):
    monkeypatch.setattr(terrain_build, "default_boxes", lambda: {"box": BOX})
    manifest = isolated_data_root.parent / "manifest.jsonl"
    return ["--manifest", str(manifest)], isolated_data_root


def tile_writing_fetcher(calls, absent=(), failing=()):
    def fetch(tile, dest):
        calls.append(tile)
        if tile in absent:
            raise TileAbsentError("HTTP 404")
        if tile in failing:
            raise RuntimeError("boom")
        write_tile(dest.parent, tile, plane_east_down(8.0))
    return fetch


def test_cli_downloads_builds_prints_summary_and_is_idempotent(cli_env, capsys):
    common, root = cli_env
    calls = []
    assert terrain_build.main(common, fetch=tile_writing_fetcher(calls)) == 0
    out = capsys.readouterr().out
    assert "download: 4 fetched" in out and "4 of 4 cells kept" in out
    assert sorted(calls) == ALL_TILES
    assert (root / "processed" / "terrain" / "cell_terrain.parquet").is_file()
    assert (root / "processed" / "terrain" / "terrain_report.json").is_file()
    again = []
    assert terrain_build.main(common, fetch=tile_writing_fetcher(again)) == 0
    second = capsys.readouterr().out
    assert again == [] and "0 fetched" in second and "4 already present" in second


def test_cli_exit_codes_absent_is_fine_failed_is_not(cli_env, capsys, monkeypatch):
    monkeypatch.setattr(terrain.time, "sleep", lambda seconds: None)
    common, root = cli_env
    table = root / "processed" / "terrain" / "cell_terrain.parquet"
    assert terrain_build.main(common, fetch=tile_writing_fetcher([], absent={(11, 75)})) == 0
    assert "1 absent" in capsys.readouterr().out and table.is_file()
    table.unlink()
    (root / "raw" / "terrain" / "glo90" / ABSENT_FILE).unlink()
    for tif in (root / "raw" / "terrain" / "glo90").glob("*.tif"):
        tif.unlink()
    assert terrain_build.main(common, fetch=tile_writing_fetcher([], failing={(12, 76)})) == 1
    captured = capsys.readouterr()
    assert "FAILED" in captured.out and "failed tiles" in captured.err and not table.exists()


def test_cli_build_without_tiles_reports_the_incomplete_download(cli_env, capsys):
    common, _ = cli_env
    assert terrain_build.main([*common, "--skip-download"]) == 1
    assert "neither downloaded nor recorded as absent" in capsys.readouterr().err


def test_cli_rejects_more_than_six_workers(cli_env):
    common, _ = cli_env
    for workers in ("7", "0"):
        with pytest.raises(SystemExit) as info:
            terrain_build.main([*common, "--workers", workers], fetch=tile_writing_fetcher([]))
        assert info.value.code == 2


# ---------------------------------------------------------------- real tiles (python -m aetherguard.ingest.terrain_build first)
def _real(box):
    raw = data_root() / "raw" / "terrain" / "glo90"
    for tile in tiles_for_bbox(box["lat_min"], box["lat_max"], box["lon_min"], box["lon_max"]):
        if not terrain.tile_path(raw, *tile).is_file() and tile_name(*tile) not in terrain.read_absent(raw):
            pytest.skip(f"real tile {tile_name(*tile)} not downloaded")
    table, _ = cell_terrain(raw, {"box": box})
    assert len(table) == 1
    return table.iloc[0]


@pytest.mark.realdata
def test_real_wayanad_cell_has_plausible_elevation_and_slope():
    cell = _real({"lat_min": 11.5, "lat_max": 11.55, "lon_min": 76.25, "lon_max": 76.3})
    assert 300 < cell["elev_mean"] < 2000
    assert cell["relief"] > 50 and 2 < cell["slope_mean"] < 45 and cell["slope_p90"] >= cell["slope_mean"]
    assert cell["valid_frac"] == 1.0


@pytest.mark.realdata
def test_real_himalayan_cells_have_far_more_relief_than_a_gangetic_plain_cell():
    plain = _real({"lat_min": 26.5, "lat_max": 26.55, "lon_min": 82.0, "lon_max": 82.05})
    doon = _real({"lat_min": 30.25, "lat_max": 30.3, "lon_min": 78.0, "lon_max": 78.05})   # Dehradun, the Doon valley
    mountain = _real({"lat_min": 30.7, "lat_max": 30.75, "lon_min": 78.4, "lon_max": 78.45})   # Uttarkashi hills
    assert plain["relief"] < 50 and plain["slope_mean"] < 2
    assert doon["relief"] > 5 * plain["relief"] and doon["slope_mean"] > 2 * plain["slope_mean"]
    assert mountain["relief"] > 1000 and mountain["slope_mean"] > 15
    assert mountain["relief"] > 10 * plain["relief"]
