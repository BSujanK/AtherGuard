"""W5 static susceptibility table: the reductions from a raster to 0.05-degree cells (no network)."""
import numpy as np
import pandas as pd
import pytest
from affine import Affine

from aetherguard.features import static_w5 as sw
from aetherguard.grid import cell_center, latlon_to_cell

# Four neighbouring cells: two rows (lat 10.00 and 10.05), two columns (lon 76.00 and 76.05).
CELLS = np.sort(np.array([latlon_to_cell(10.025, 76.025), latlon_to_cell(10.025, 76.075),
                          latlon_to_cell(10.075, 76.025), latlon_to_cell(10.075, 76.075)]))
SW, SE, NW, NE = (int(latlon_to_cell(lat, lon)) for lat, lon in
                  [(10.025, 76.025), (10.025, 76.075), (10.075, 76.025), (10.075, 76.075)])
# A north-up raster of 0.01 degree pixels covering the four cells exactly: 10 rows, 10 columns, 5 x 5 pixels per cell.
TRANSFORM = Affine(0.01, 0, 76.0, 0, -0.01, 10.1)


def at(cell: int) -> int:
    return int(np.searchsorted(CELLS, cell))


def test_every_pixel_lands_in_the_cell_that_holds_its_centre():
    pos = sw.cell_positions(TRANSFORM, 10, 10, CELLS)
    assert pos.shape == (10, 10)
    assert (pos[:5, :5] == at(NW)).all() and (pos[:5, 5:] == at(NE)).all()      # row 0 is the northern edge
    assert (pos[5:, :5] == at(SW)).all() and (pos[5:, 5:] == at(SE)).all()


def test_pixels_of_cells_that_are_not_listed_are_left_out():
    pos = sw.cell_positions(TRANSFORM, 10, 10, np.array([SW, NE]))
    assert (pos[:5, :5] == -1).all() and (pos[5:, 5:] == -1).all()
    assert (pos[5:, :5] == 0).all() and (pos[:5, 5:] == 1).all()


def test_class_shares_leave_water_and_nodata_out_of_the_denominator():
    values = np.full((10, 10), 10, dtype=np.uint8)            # trees everywhere
    values[5:, :5] = 40                                       # SW: cropland ...
    values[5:7, :5] = 80                                      # ... with 10 of its 25 pixels water
    values[:5, 5:] = 0                                        # NE: no data at all
    values[:5, :3] = 50                                       # NW: 15 built pixels, 10 trees
    counts, denom = sw.new_class_counts(len(CELLS))
    sw.add_classes(values, sw.cell_positions(TRANSFORM, 10, 10, CELLS), counts, denom)
    shares = sw.class_shares(counts, denom)
    assert shares["lc_crop"][at(SW)] == pytest.approx(1.0) and denom[at(SW)] == 15
    assert shares["lc_built"][at(NW)] == pytest.approx(0.6) and shares["lc_tree"][at(NW)] == pytest.approx(0.4)
    assert shares["lc_tree"][at(SE)] == pytest.approx(1.0)
    assert all(np.isnan(shares[name][at(NE)]) for name in sw.LC_CLASSES)   # nothing to say is NaN, never 0


def test_shrub_and_grass_share_one_column_and_bare_includes_snow():
    values = np.full((10, 10), 20, dtype=np.uint8)
    values[:, 5:] = 30
    values[5:, :] = np.where(np.arange(10) < 5, 60, 70)[None, :]
    counts, denom = sw.new_class_counts(len(CELLS))
    sw.add_classes(values, sw.cell_positions(TRANSFORM, 10, 10, CELLS), counts, denom)
    shares = sw.class_shares(counts, denom)
    assert shares["lc_shrub_grass"][at(NW)] == shares["lc_shrub_grass"][at(NE)] == pytest.approx(1.0)
    assert shares["lc_bare"][at(SW)] == shares["lc_bare"][at(SE)] == pytest.approx(1.0)


def test_classes_accumulate_over_tiles():
    counts, denom = sw.new_class_counts(len(CELLS))
    pos = sw.cell_positions(TRANSFORM, 10, 10, CELLS)
    sw.add_classes(np.full((10, 10), 10, dtype=np.uint8), pos, counts, denom)
    sw.add_classes(np.full((10, 10), 40, dtype=np.uint8), pos, counts, denom)
    assert sw.class_shares(counts, denom)["lc_tree"][at(SW)] == pytest.approx(0.5)


def test_cell_means_ignore_missing_pixels_and_are_nan_without_any():
    values = np.full((10, 10), 30.0)
    values[5:, :5] = np.nan                                   # SW: nothing
    values[:5, :5] = 10.0
    values[0, :5] = np.nan                                    # NW: 20 valid pixels of 10
    total, count = np.zeros(len(CELLS)), np.zeros(len(CELLS))
    sw.add_means(values, sw.cell_positions(TRANSFORM, 10, 10, CELLS), total, count)
    means = sw.cell_means(total, count)
    assert means[at(NW)] == pytest.approx(10.0) and count[at(NW)] == 20
    assert means[at(NE)] == pytest.approx(30.0) and np.isnan(means[at(SW)])


def test_sampling_reads_the_pixel_that_holds_the_cell_centre():
    coarse = Affine(0.05, 0, 76.0, 0, -0.05, 10.1)            # one pixel per cell
    values = np.array([[1.0, 2.0], [3.0, -9.0]])              # NW NE / SW SE, SE is nodata
    lat, lon = cell_center(CELLS)
    out = sw.sample_at_centres(values, coarse, lat, lon, nodata=-9.0)
    assert out[at(NW)] == 1.0 and out[at(NE)] == 2.0 and out[at(SW)] == 3.0 and np.isnan(out[at(SE)])


def test_sampling_outside_the_raster_is_nan():
    out = sw.sample_at_centres(np.ones((2, 2)), Affine(0.05, 0, 76.0, 0, -0.05, 10.1), np.array([50.0]), np.array([76.02]))
    assert np.isnan(out[0])


def test_steep_shares_are_over_the_slope_valid_pixels():
    slope = np.full((3, 100), np.nan)
    slope[0, :50] = 40.0                                      # half valid, all of it steep
    slope[1, :] = np.where(np.arange(100) < 30, 30.0, 10.0)   # 30% at 30 degrees
    out = sw.steep_shares(slope)
    assert out["ter_steep25"][0] == 1.0 and out["ter_steep35"][0] == 1.0
    assert out["ter_steep25"][1] == pytest.approx(0.3) and out["ter_steep35"][1] == 0.0
    assert np.isnan(out["ter_steep25"][2]) and np.isnan(out["ter_steep35"][2])


def test_a_slope_exactly_on_a_threshold_counts_as_steep():
    out = sw.steep_shares(np.array([[25.0, 35.0, 24.999, 34.999]]))
    assert out["ter_steep25"][0] == pytest.approx(0.75) and out["ter_steep35"][0] == pytest.approx(0.25)


def test_the_table_holds_every_cell_and_every_declared_column_with_nan_for_an_uncovered_source():
    cells = pd.DataFrame({"cell_id": CELLS})
    parts = {"landcover": {name: np.arange(4, dtype=float) for name in sw.LC_CLASSES},
             "roads": {"road_density": np.array([1.0, np.nan, 3.0, 4.0])}}
    table = sw.assemble(cells, parts)
    assert list(table.columns) == ["cell_id", *sw.STATIC_COLUMNS]
    assert table["cell_id"].tolist() == CELLS.tolist()
    assert np.isnan(table["road_density"][1]) and table["soil_clay"].isna().all() and table["ter_steep25"].isna().all()
    assert table["lc_built"].tolist() == [0.0, 1.0, 2.0, 3.0]


def test_the_declared_columns_are_the_eleven_of_the_spec():
    assert sw.STATIC_COLUMNS == ["lc_tree", "lc_shrub_grass", "lc_crop", "lc_built", "lc_bare", "road_density",
                                 "soil_clay", "soil_sand", "soil_coarse", "ter_steep25", "ter_steep35"]


def test_worldcover_tiles_are_named_by_their_south_west_corner_on_the_three_degree_grid():
    assert sw.worldcover_tile(27.4, 88.9) == "N27E087"
    assert sw.worldcover_tile(8.1, 77.4) == "N06E075"
    assert sw.worldcover_tiles(np.array([8.1, 8.2, 27.4]), np.array([77.4, 77.9, 88.9])) == ["N06E075", "N27E087"]
