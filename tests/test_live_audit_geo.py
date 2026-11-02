"""Geographical integrity checks of published live tables (live.audit_geo): synthetic base map and place table."""
import numpy as np
import pandas as pd

from aetherguard.grid import ID_STRIDE, cell_center, latlon_to_cell
from aetherguard.live import audit, audit_geo as ag
from aetherguard.serve import basemap as bm
from aetherguard.serve.places import EARTH_RADIUS_KM

TINY = bm.Grid(lat0=27.0, lon0=84.0, rows=20, cols=40)         # lat 27-28, lon 84-86
LAT = 27.525


def _found(table):
    return audit.Findings(len(table))


def _base(rows=TINY.rows, cols=TINY.cols):
    """Elevation rising to the east; India west of lon 85, Nepal east of it; the row 0 strip is sea."""
    elev = np.tile(np.linspace(100, 3000, cols, dtype=np.float32), (rows, 1)) + 7 * np.arange(rows, dtype=np.float32)[:, None]
    mask = np.full((rows, cols), bm.INDIA, dtype=np.uint8)
    mask[:, cols // 2:] = bm.NEPAL
    return ag.Basemap(elev=elev, mask=mask, grid=TINY)


def _cells(n=30, lat=LAT):
    lon = 84.025 + 0.05 * np.arange(n)
    ids = latlon_to_cell(np.full(n, lat), lon)
    la, lo = cell_center(ids)
    return pd.DataFrame({"cell_id": ids, "lat": la, "lon": lo,
                         "region": "himalaya", "risk": np.linspace(1e-6, 1e-4, n), "level": np.int8(1)})


# ------------------------------------------------------------------------------------------------------ grid

def test_grid_accepts_cells_at_their_centres_and_region_boxes():
    table = _cells()
    found = _found(table)
    ag.check_grid(table, found)
    assert found.counts["grid"] == 0 and found.checked["grid"]


def test_grid_flags_an_id_that_is_not_its_position_a_moved_centre_and_a_wrong_region():
    table = _cells()
    table.loc[0, "cell_id"] += ID_STRIDE                              # the id of the cell one row north
    table.loc[1, "lon"] += 0.01                                       # not exactly the centre
    table.loc[2, "region"] = "western_ghats"                          # the box says himalaya
    table.loc[3, ["lat", "lon"]] = (10.0, 76.0)                       # in the other box (id no longer matches either)
    found = _found(table)
    ag.check_grid(table, found)
    assert found.counts["grid"] == 4


def test_grid_flags_a_cell_in_neither_box():
    table = _cells(lat=15.025)
    found = _found(table)
    ag.check_grid(table, found)
    assert found.counts["grid"] == len(table)                           # lat 15, lon 84: in no region box


# ------------------------------------------------------------------------------------------------------ land

def test_land_counts_the_countries_and_accepts_india_nepal_and_bhutan():
    table = _cells()
    found = _found(table)
    ag.check_land(table, _base(), found)
    assert found.counts["land"] == 0
    assert found.note_counts["land_India"] + found.note_counts["land_Nepal"] == len(table)


def test_land_flags_a_sea_cell_but_notes_a_coastal_cell_with_positive_elevation():
    base = _base()
    r0, c0 = (int(latlon_to_cell(LAT, 84.025)) // ID_STRIDE - base.grid.lat_index0,
              int(latlon_to_cell(LAT, 84.025)) % ID_STRIDE - base.grid.lon_index0)
    base.mask[r0, c0] = bm.SEA
    base.elev[r0, c0] = -20.0                                           # open water
    base.mask[r0, c0 + 1] = bm.SEA                                      # sea by the mask, land by the elevation
    table = _cells()
    found = _found(table)
    ag.check_land(table, base, found)
    assert found.counts["land"] == 1
    assert found.note_counts["land_coastal_masked_as_sea"] == 1


def test_land_ignores_unscored_cells_and_notes_cells_outside_the_map():
    table = _cells()
    table.loc[0, "risk"] = np.nan
    base = _base()
    r0 = int(latlon_to_cell(LAT, 84.025)) // ID_STRIDE - base.grid.lat_index0
    base.mask[r0, 0] = bm.SEA
    found = _found(table)
    ag.check_land(table, base, found)
    assert found.counts["land"] == 0
    far = _cells().assign(lat=60.025)
    far["cell_id"] = latlon_to_cell(far["lat"], far["lon"])
    found = _found(far)
    ag.check_land(far, base, found)
    assert found.counts["land"] == 0 and found.note_counts["land_outside_basemap"] == len(far)


# ------------------------------------------------------------------------------------------------- georef

def _terrain(base, cells, noise=0.0, shift=(0, 0)):
    rows = cells["cell_id"].to_numpy() // ID_STRIDE - base.grid.lat_index0 + shift[0]
    cols = cells["cell_id"].to_numpy() % ID_STRIDE - base.grid.lon_index0 + shift[1]
    elev = base.elev[np.clip(rows, 0, base.grid.rows - 1), np.clip(cols, 0, base.grid.cols - 1)]
    return elev.astype(np.float32) + noise


def _grid_cells():
    """Every cell of the tiny map, so a one-cell shift has a visible effect."""
    ids = (np.arange(TINY.rows)[:, None] + TINY.lat_index0) * ID_STRIDE + TINY.lon_index0 + np.arange(TINY.cols)[None, :]
    la, lo = cell_center(ids.ravel())
    return pd.DataFrame({"cell_id": ids.ravel(), "lat": la, "lon": lo})


def _rough(base, seed):
    rng = np.random.default_rng(seed)
    base.elev[:] = np.cumsum(np.cumsum(rng.normal(0, 1, base.elev.shape), axis=0), axis=1).astype(np.float32)   # smooth field
    return rng


def test_georef_accepts_terrain_that_follows_the_base_map():
    base = _base()
    cells = _grid_cells()
    rng = _rough(base, 1)
    cells["stat_elev_mean"] = _terrain(base, cells, noise=rng.normal(0, 0.5, len(cells)).astype(np.float32))
    found = _found(cells)
    ag.check_georef_terrain(cells, base, found, min_cells=100)
    assert found.counts["georef"] == 0 and found.checked["georef"]


def test_georef_flags_terrain_shifted_by_a_cell_and_terrain_that_does_not_correlate():
    base = _base()
    cells = _grid_cells()
    rng = _rough(base, 2)
    cells["stat_elev_mean"] = _terrain(base, cells, shift=(0, 1))
    found = _found(cells)
    ag.check_georef_terrain(cells, base, found, min_cells=100)
    assert found.counts["georef"] == 1 and "shifted cell" in found.examples["georef"][0]["why"]
    cells["stat_elev_mean"] = rng.normal(0, 1, len(cells)).astype(np.float32)
    found = _found(cells)
    ag.check_georef_terrain(cells, base, found, min_cells=100)
    assert found.counts["georef"] >= 1


def test_georef_is_not_decided_on_too_few_cells():
    base = _base()
    cells = _cells(5).assign(stat_elev_mean=1.0)
    found = _found(cells)
    ag.check_georef_terrain(cells, base, found, min_cells=100)
    assert found.counts["georef"] == 0 and not found.checked["georef"]
    assert any("georef" in n for n in found.notes)


# ------------------------------------------------------------------------------------------------- places

def _haversine(lat1, lon1, lat2, lon2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(np.radians(lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a))


def _places(table, offset_deg=0.05):
    plat, plon = table["lat"].to_numpy() + offset_deg, table["lon"].to_numpy()
    country = np.where(table["lon"] < 85.0, "India", "Nepal")
    return pd.DataFrame({"cell_id": table["cell_id"], "place": "Town", "district": "D", "state": "S", "country": country,
                         "distance_km": np.rint(_haversine(table["lat"].to_numpy(), table["lon"].to_numpy(), plat, plon)).astype(np.int32),
                         "place_lat": plat.round(4), "place_lon": plon.round(4), "population": 1000})


def test_places_accepts_a_consistent_label_table_and_counts_far_places():
    table = _cells()
    places = _places(table)
    places.loc[0, ["place_lat", "distance_km"]] = (table.loc[0, "lat"] + 0.5, 56)
    found = _found(table)
    ag.check_places(table, places, _base(), found)
    assert found.counts["places"] == 0, found.examples["places"]
    assert found.note_counts["places_over_30km"] == 1


def test_places_flags_a_missing_label_a_wrong_distance_and_a_wrong_country():
    table = _cells()
    places = _places(table)
    places = places[places["cell_id"] != table.loc[0, "cell_id"]]
    places.loc[places["cell_id"] == table.loc[1, "cell_id"], "distance_km"] += 3
    places.loc[places["cell_id"] == table.loc[2, "cell_id"], "country"] = "Nepal"        # an India-mask cell
    places.loc[places["cell_id"] == table.loc[3, "cell_id"], "place"] = ""
    found = _found(table)
    ag.check_places(table, places, _base(), found)
    assert found.counts["places"] == 4


# ---------------------------------------------------------------------------------------------- the notes

def test_terrain_notes_count_alert_levels_on_low_slope_and_low_elevation_cells():
    table = _cells(4).assign(level=np.int8([0, 1, 2, 3]))
    terrain = table[["cell_id"]].assign(stat_slope_mean=[2.0, 3.0, 4.0, 40.0], stat_elev_mean=[10.0, 50.0, 500.0, 50.0])
    found = _found(table)
    ag.terrain_notes(table, terrain, found)
    assert {k: v for k, v in found.to_dict()["note_counts"].items()} == {"slope_lt_5deg_Watch": 1, "slope_lt_5deg_Warning": 1, "elev_lt_100m_Watch": 1,
                                 "elev_lt_100m_Emergency": 1}


# --------------------------------------------------------------------------------------------- rain georef

def _imd_world(shift=(0, 0), lag=0, days=3, seed=5):
    """IMD grids of `days` consecutive days (smooth random fields) and the cells' IMERG rain: the grid sampled at the cell's
    nearest point displaced by `shift` cells and by `lag` days."""
    from datetime import date, timedelta

    from aetherguard.features.sources import _imd_pixels
    from aetherguard.ingest import imd as imd_mod
    rng = np.random.default_rng(seed)
    lat = np.repeat(10.025 + 0.25 * np.arange(60), 60)
    lon = np.tile(70.025 + 0.25 * np.arange(60), 60)
    ids = latlon_to_cell(lat, lon)
    pixel = _imd_pixels(ids)
    i, j = np.divmod(pixel, imd_mod.N_LON)
    first = date(2026, 10, 1)
    grids = {first + timedelta(days=k): np.maximum(0, np.cumsum(np.cumsum(rng.normal(0, 1, (imd_mod.N_LAT, imd_mod.N_LON)), axis=0),
                                                                axis=1)).astype(np.float32) for k in range(-1, days + 1)}
    daily = {}
    for k in range(days):
        day = first + timedelta(days=k)
        grid = grids[day + timedelta(days=lag)]
        daily[day] = pd.DataFrame({"cell_id": ids, "irain_acc_1": grid[i + shift[0], j + shift[1]]})
    return daily, grids


def test_rain_georef_accepts_aligned_products_and_reports_the_table():
    daily, grids = _imd_world()
    result = ag.rain_georef(daily, grids)
    assert result["decided"] and result["violations"] == []
    assert result["spatial"]["0,0"] > 0.99 and result["lag"]["0"] > 0.99
    assert result["days"] == 3 and set(result["lag"]) == {"-1", "0", "1"}


def test_rain_georef_flags_a_product_shifted_by_a_grid_cell_or_a_day():
    daily, grids = _imd_world(shift=(0, 1))
    result = ag.rain_georef(daily, grids)
    assert any("(0,1)" in v for v in result["violations"])
    daily, grids = _imd_world(lag=1)
    result = ag.rain_georef(daily, grids)
    assert any("day +1" in v for v in result["violations"])


def test_rain_georef_does_not_decide_on_too_few_pairs():
    daily, grids = _imd_world(shift=(0, 1))
    result = ag.rain_georef(daily, grids, min_pairs=10 ** 9)
    assert not result["decided"] and result["violations"] == []


def test_imd_grid_files_are_found_by_the_day_they_hold(tmp_path):
    for run, held in (("2026-10-10", "2026-10-09"), ("2026-10-11", "2026-10-09"), ("2026-10-11", "2026-10-10")):
        folder = tmp_path / run / "raw" / "imd_rt"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{held}.grd").write_bytes(b"x")
    files = ag.imd_grid_files(tmp_path)
    assert sorted(d.isoformat() for d in files) == ["2026-10-09", "2026-10-10"]


def test_rain_georef_takes_the_live_column_offset_as_the_aligned_sampling():
    daily, grids = _imd_world(shift=(0, -1))
    assert ag.rain_georef(daily, grids)["violations"]                        # read at the nearest point it looks shifted
    result = ag.rain_georef(daily, grids, lon_offset_columns=-1)
    assert result["violations"] == [] and result["spatial"]["0,0"] > 0.99 and result["lon_offset_columns"] == -1
    assert result["spatial"]["0,1"] < result["spatial"]["0,0"]               # the nearest point is now the shifted one


def test_the_stored_imd_rain_must_be_the_grid_read_at_the_configured_column(tmp_path):
    from datetime import date

    from aetherguard.features.sources import _imd_pixels
    from aetherguard.ingest import imd as imd_mod
    daily, grids = _imd_world(days=1)
    day = next(iter(daily))
    ids = daily[day]["cell_id"].to_numpy()
    flat = grids[day].ravel()
    at = lambda offset: np.where((p := _imd_pixels(ids, offset)) >= 0, flat[np.where(p >= 0, p, 0)], np.nan)   # noqa: E731
    features = pd.DataFrame({"cell_id": ids, "src_imd_acc_1": at(-1)})
    found = _found(features)
    ag.check_imd_sampling(features, grids[day], -1, found)
    assert found.counts["georef"] == 0 and found.checked["georef"]
    found = _found(features)
    ag.check_imd_sampling(features, grids[day], 0, found)                      # published with -1, configured 0
    assert found.counts["georef"] > 0
    features.loc[:, "src_imd_acc_1"] = np.nan                                  # the file was not there at run time
    found = _found(features)
    ag.check_imd_sampling(features, grids[day], -1, found)
    assert found.counts["georef"] == 0 and any("no IMD value stored" in n for n in found.notes)
    del date, imd_mod
