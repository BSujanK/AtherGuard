"""W5 static table: the code that reads the real files (local stand-ins, no network)."""
import zipfile

import numpy as np
import pandas as pd
import pytest
import rasterio
from affine import Affine

from aetherguard.features import static_w5 as sw
from aetherguard.manifest import Manifest


def test_the_density_grid_is_chosen_not_the_land_area_grid_that_comes_first_in_the_zip():
    names = ["grip4_area_land_km2.asc", "GRIP4_density_m_km2.lyr", "grip4_total_dens_m_km2.asc", "ReadMe.txt"]
    assert sw.grip4_member(names) == "grip4_total_dens_m_km2.asc"


def test_a_zip_without_exactly_one_density_grid_is_refused():
    with pytest.raises(ValueError, match="density"):
        sw.grip4_member(["grip4_area_land_km2.asc", "ReadMe.txt"])
    with pytest.raises(ValueError, match="density"):
        sw.grip4_member(["a_dens.asc", "b_dens.asc"])


def write_density_zip(path):
    """A 2 x 2 global-ish grid of 5-degree pixels with its origin at 75E 15N, inside a zip beside a land-area grid."""
    header = "ncols 2\nnrows 2\nxllcorner 75\nyllcorner 5\ncellsize 5\nNODATA_value -9999\n"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("grip4_area_land_km2.asc", header + "85 85\n85 85\n")
        archive.writestr("grip4_total_dens_m_km2.asc", header + "10 20\n30 -9999\n")


def test_roads_reads_the_density_of_the_pixel_holding_each_cell_centre(tmp_path, monkeypatch):
    monkeypatch.setenv("AETHERGUARD_DATA_DIR", str(tmp_path))
    raw = tmp_path / "raw" / "static_w5"
    raw.mkdir(parents=True)
    write_density_zip(raw / "GRIP4_density_total.zip")
    manifest = Manifest(tmp_path / "manifest.jsonl", tmp_path)
    manifest.add(raw / "GRIP4_density_total.zip", "test", sw.GRIP4_URL, "CC0")      # already downloaded: no network
    cells = pd.DataFrame({"lat": [12.0, 12.0, 7.0, 7.0], "lon": [77.0, 82.0, 77.0, 82.0]})
    out = sw.roads(cells, say=lambda *_: None, manifest=manifest)["road_density"]
    assert out[:3].tolist() == [10.0, 20.0, 30.0] and np.isnan(out[3])              # never the 85 of the area grid


class FakeHead:
    def __init__(self, status):
        self.status_code = status


def write_tile(path, values):
    """A 3-degree, 16 x 16 pixel land-cover tile with its north-west corner at 87E 30N."""
    with rasterio.open(path, "w", driver="GTiff", height=16, width=16, count=1, dtype="uint8", crs="EPSG:4326",
                       transform=Affine(3 / 16, 0, 87.0, 0, -3 / 16, 30.0)) as ds:
        ds.write(values, 1)


def test_a_tile_is_read_at_one_pixel_in_eight_on_the_same_ground_and_cached(tmp_path, monkeypatch):
    values = np.full((16, 16), 10, dtype=np.uint8)
    values[8:, :] = 40                                           # southern half cropland
    write_tile(tmp_path / "tile.tif", values)
    monkeypatch.setattr(sw, "WORLDCOVER_URL", str(tmp_path / "tile.tif").replace("\\", "/"))
    monkeypatch.setattr("requests.head", lambda url, timeout: FakeHead(200))
    manifest = Manifest(tmp_path / "manifest.jsonl", tmp_path)
    got, transform = sw.read_worldcover("N27E087", tmp_path, say=lambda *_: None, manifest=manifest)
    assert got.shape == (2, 2) and got[0].tolist() == [10, 10] and got[1].tolist() == [40, 40]
    assert (transform.c, transform.f) == (87.0, 30.0)
    assert transform.a == pytest.approx(1.5) and transform.e == pytest.approx(-1.5)   # 3 degrees over 2 pixels
    assert manifest.is_current(tmp_path / "N27E087_d8.npz")
    monkeypatch.setattr("requests.head", lambda url, timeout: pytest.fail("a cached tile must not be asked for again"))
    again, _ = sw.read_worldcover("N27E087", tmp_path, say=lambda *_: None, manifest=manifest)
    assert (again == got).all()


def test_only_not_found_means_there_is_no_tile(tmp_path, monkeypatch):
    monkeypatch.setattr("requests.head", lambda url, timeout: FakeHead(404))
    assert sw.read_worldcover("N00E060", tmp_path, say=lambda *_: None) is None
    assert (tmp_path / "N00E060.absent").exists()


def test_a_forbidden_answer_is_an_error_and_marks_nothing_absent(tmp_path, monkeypatch):
    monkeypatch.setattr("requests.head", lambda url, timeout: FakeHead(403))
    with pytest.raises(RuntimeError, match="403"):
        sw.read_worldcover("N27E087", tmp_path, say=lambda *_: None)
    assert not list(tmp_path.glob("*.absent"))


def test_a_part_is_written_whole_or_not_at_all(tmp_path):
    frame = pd.DataFrame({"cell_id": [1, 2], "road_density": [3.0, 4.0]})
    sw.write_part(tmp_path / "part_roads.parquet", frame)
    assert pd.read_parquet(tmp_path / "part_roads.parquet").equals(frame)
    assert not list(tmp_path.glob("*.part"))
