import numpy as np
import pytest

from aetherguard import grid


def test_known_cell_and_center():
    cid = grid.latlon_to_cell(11.55, 76.13)
    assert cid == 2031 * 10_000 + 5122
    lat_c, lon_c = grid.cell_center(cid)
    assert lat_c == pytest.approx(11.575)
    assert lon_c == pytest.approx(76.125)


def test_every_cell_edge_maps_to_its_own_index():
    # Regression for binary floating-point error at exact cell edges.
    k = np.arange(0, 3600)
    lat_edges = -90.0 + k * 0.05
    assert (grid.latlon_to_cell(lat_edges, np.zeros(k.shape)) // grid.ID_STRIDE == k).all()
    j = np.arange(0, 7200)
    lon_edges = -180.0 + j * 0.05
    assert (grid.latlon_to_cell(np.zeros(j.shape), lon_edges) % grid.ID_STRIDE == j).all()


def test_just_below_an_edge_stays_in_lower_cell():
    assert grid.latlon_to_cell(11.5499, 76.13) // grid.ID_STRIDE == 2030


def test_negative_coordinates_round_trip_within_half_a_cell():
    cid = grid.latlon_to_cell(-33.9, -70.65)
    lat_c, lon_c = grid.cell_center(cid)
    assert abs(lat_c + 33.9) <= 0.025 + 1e-9
    assert abs(lon_c + 70.65) <= 0.025 + 1e-9


@pytest.mark.parametrize("lat,lon", [(90.0, 0.0), (-91.0, 0.0), (0.0, 180.0), (0.0, -181.0)])
def test_out_of_range_coordinates_rejected(lat, lon):
    with pytest.raises(ValueError):
        grid.latlon_to_cell(lat, lon)


def test_neighbours_interior_and_pole_edge():
    cid = grid.latlon_to_cell(11.55, 76.13)
    n = grid.neighbours(cid)
    assert len(n) == 8 and len(set(n)) == 8 and cid not in n
    top = grid.latlon_to_cell(89.99, 10.0)
    assert len(grid.neighbours(top)) == 5


def test_neighbours_wrap_across_the_antimeridian():
    cid = grid.latlon_to_cell(0.0, 179.99)
    assert 0 in {n % grid.ID_STRIDE for n in grid.neighbours(cid)}


def test_region_labels():
    labels = grid.region_labels([11.55, 27.7, 0.0], [76.13, 85.3, 0.0])
    assert list(labels) == ["western_ghats", "himalaya", ""]
    assert grid.region_of(11.55, 76.13) == "western_ghats"


def test_domain_cell_counts():
    fine = grid.domain_cell_counts(0.05)
    assert fine == {"himalaya": 145_600, "western_ghats": 32_400, "total": 178_000}
    coarse = grid.domain_cell_counts(0.25)
    assert coarse == {"himalaya": 5_824, "western_ghats": 1_296, "total": 7_120}


def test_coordinates_just_below_the_upper_bounds_stay_inside_the_grid():
    # Regression: rounding must not snap valid inputs to lat row 3600 / lon col 7200.
    cid = grid.latlon_to_cell(np.nextafter(90.0, 0.0), np.nextafter(180.0, 0.0))
    assert divmod(cid, grid.ID_STRIDE) == (grid.LAT_ROWS - 1, grid.LON_COLS - 1)
    lat_c, lon_c = grid.cell_center(cid)
    assert -90.0 <= lat_c <= 90.0 and -180.0 <= lon_c <= 180.0
    lat_only = grid.latlon_to_cell(np.nextafter(90.0, 0.0), 0.0)
    assert lat_only // grid.ID_STRIDE == grid.LAT_ROWS - 1
    lon_only = grid.latlon_to_cell(0.0, np.nextafter(180.0, 0.0))
    assert lon_only % grid.ID_STRIDE == grid.LON_COLS - 1
    arr = grid.latlon_to_cell(np.array([np.nextafter(90.0, 0.0)]), np.array([np.nextafter(180.0, 0.0)]))
    assert divmod(int(arr[0]), grid.ID_STRIDE) == (grid.LAT_ROWS - 1, grid.LON_COLS - 1)


@pytest.mark.parametrize(
    "lat,lon",
    [
        (float("nan"), 0.0),
        (0.0, float("nan")),
        (float("inf"), 0.0),
        (0.0, float("-inf")),
        ([float("nan")], [1.0]),
        ([1.0], [float("inf")]),
        (np.array([1.0, float("nan")]), np.array([1.0, 2.0])),
    ],
)
def test_non_finite_coordinates_rejected(lat, lon):
    with pytest.raises(ValueError):
        grid.latlon_to_cell(lat, lon)
