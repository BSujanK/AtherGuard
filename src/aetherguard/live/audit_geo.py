"""Geographical integrity checks of published live tables (spec section 13, `live.audit`).

    grid     cell_id == grid.latlon_to_cell(lat, lon), (lat, lon) == grid.cell_center(cell_id) exactly, and the region is
             the one `grid.region_labels` gives (a cell in neither region box, or one the box disagrees with, is wrong).
    land     the centre of every scored cell is land in the base map's country mask (0 sea, 1 India, 2 Nepal, 3 Bhutan,
             4 other land). A cell the mask calls sea is a violation unless the base map's own elevation there is above
             sea level (the 1:10m coastline misses a coastal cell centre: counted as the note
             `land_coastal_masked_as_sea`). Cells in other countries are notes, not violations.
    georef   the terrain input `stat_elev_mean` follows the base map's ETOPO elevation at the same cell: correlation above
             0.95 and higher at zero offset than at every one-cell shift.
    places   every scored cell has a label in the place table; distance_km is the great-circle distance from the cell
             centre to the place (stored as an integer: within 0.5 km + 0.02 km of the rounded place position); the
             country of a cell the mask puts in India, Nepal or Bhutan is that country.

The rain-product registration test (`rain_georef`) compares IMERG with the IMD real-time grid over all published days.
"""
from __future__ import annotations

import glob
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from ..alerts import levels as lv
from ..grid import ID_STRIDE, cell_center, latlon_to_cell, region_labels
from ..ingest import imd as imd_mod
from ..serve import basemap as bm
from ..serve.places import EARTH_RADIUS_KM
from .audit_math import flag

MIN_GEOREF_CELLS = 500
ELEVATION_CORRELATION_MIN = 0.95
DISTANCE_ROUNDING_KM = 0.5 + 0.02       # stored as the nearest integer; the place position is rounded to 1e-4 degrees
FAR_PLACE_KM = 30.0
LOW_SLOPE_DEG = 5.0
LOW_ELEVATION_M = 100.0
COUNTRY_OF_CLASS = {bm.INDIA: "India", bm.NEPAL: "Nepal", bm.BHUTAN: "Bhutan"}
SHIFT_MARGIN = 0.02                      # a shifted product "clearly" beats the unshifted one by more than this correlation
MIN_RAIN_PAIRS = 1000
RAIN_SHIFTS = ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1), (2, 0), (-2, 0), (0, 2), (0, -2))     # IMD grid cells (lat, lon)
RAIN_LAGS = (-1, 0, 1)                   # days of the IMD grid relative to the IMERG IMD day


@dataclass
class Basemap:
    elev: np.ndarray
    mask: np.ndarray
    grid: bm.Grid

    def locate(self, cell_ids) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """(row, col, inside) of each cell in the base map grid."""
        ids = np.asarray(cell_ids, dtype=np.int64)
        row, col = ids // ID_STRIDE - self.grid.lat_index0, ids % ID_STRIDE - self.grid.lon_index0
        inside = (row >= 0) & (row < self.grid.rows) & (col >= 0) & (col < self.grid.cols)
        return row, col, inside


def load_basemap(path: Path) -> Basemap:
    with np.load(path, allow_pickle=False) as data:
        return Basemap(elev=data["elev"], mask=data["mask"], grid=bm.INDIA_GRID)


def _scored(table: pd.DataFrame) -> np.ndarray:
    return np.isfinite(table["risk"].to_numpy(dtype=np.float64)) if "risk" in table.columns else np.ones(len(table), dtype=bool)


# ------------------------------------------------------------------------------------------------------ grid

def check_grid(table: pd.DataFrame, found) -> None:
    if not {"cell_id", "lat", "lon"} <= set(table.columns):
        return
    ids = table["cell_id"].to_numpy(dtype=np.int64)
    lat, lon = table["lat"].to_numpy(dtype=np.float64), table["lon"].to_numpy(dtype=np.float64)
    usable = np.isfinite(lat) & np.isfinite(lon) & (lat >= -90) & (lat < 90) & (lon >= -180) & (lon < 180)
    safe_lat, safe_lon = np.where(usable, lat, 0.0), np.where(usable, lon, 0.0)
    id_of_position = np.asarray(latlon_to_cell(safe_lat, safe_lon))
    centre_lat, centre_lon = cell_center(ids)
    problems = {"lat or lon is not a position on the grid": ~usable,
                "cell_id is not the cell of (lat, lon)": usable & (id_of_position != ids),
                "(lat, lon) is not the centre of cell_id": (centre_lat != lat) | (centre_lon != lon)}
    if "region" in table.columns:
        labels = region_labels(safe_lat, safe_lon)
        region = table["region"].to_numpy(dtype=object)
        problems["cell is in no region box"] = usable & (labels == "")
        problems["region differs from the box the cell centre is in"] = usable & (labels != "") & (labels != region)
    flag(found, "grid", table, problems)


# ------------------------------------------------------------------------------------------------------ land

def check_land(table: pd.DataFrame, base: Basemap, found) -> None:
    scored = _scored(table)
    ids = table["cell_id"].to_numpy(dtype=np.int64)
    row, col, inside = base.locate(ids)
    safe_row, safe_col = np.where(inside, row, 0), np.where(inside, col, 0)
    klass = np.where(inside, base.mask[safe_row, safe_col], bm.SEA)
    elev = np.where(inside, base.elev[safe_row, safe_col], np.nan).astype(np.float64)
    sea = scored & inside & (klass == bm.SEA)
    with np.errstate(invalid="ignore"):
        coastal = sea & (elev > 0)
    for k, name in bm.CLASS_NAMES.items():
        if k != bm.SEA:
            found.note_count(f"land_{name.split()[0]}", int((scored & inside & (klass == k)).sum()))
    found.note_count("land_outside_basemap", int((scored & ~inside).sum()))
    found.note_count("land_coastal_masked_as_sea", int(coastal.sum()))
    flag(found, "land", table, {"the cell centre is sea in the base map": sea & ~coastal})


# ---------------------------------------------------------------------------------------------- georef (terrain)

def _correlation(a: np.ndarray, b: np.ndarray) -> float:
    ok = np.isfinite(a) & np.isfinite(b)
    if ok.sum() < 3 or np.std(a[ok]) == 0 or np.std(b[ok]) == 0:
        return float("nan")
    return float(np.corrcoef(a[ok], b[ok])[0, 1])


def check_georef_terrain(features: pd.DataFrame, base: Basemap, found, min_cells: int = MIN_GEOREF_CELLS) -> None:
    """`stat_elev_mean` against the base map elevation of the same cell, and of the cells one step away (the eight
    neighbours): above ELEVATION_CORRELATION_MIN and highest at zero offset, else the terrain inputs are misregistered."""
    if "stat_elev_mean" not in features.columns:
        return
    row, col, inside = base.locate(features["cell_id"].to_numpy(dtype=np.int64))
    elevation = features["stat_elev_mean"].to_numpy(dtype=np.float64)
    usable = inside & np.isfinite(elevation)
    if usable.sum() < min_cells:
        found.notes.append(f"georef: only {int(usable.sum())} cells inside the base map (need {min_cells}): not decided")
        return
    table: dict[tuple[int, int], float] = {}
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            r = np.clip(row + dr, 0, base.grid.rows - 1)
            c = np.clip(col + dc, 0, base.grid.cols - 1)
            table[(dr, dc)] = _correlation(elevation[usable], base.elev[r, c].astype(np.float64)[usable])
    zero = table[(0, 0)]
    better = {k: v for k, v in table.items() if k != (0, 0) and v >= zero}
    found.add_count("georef", 0, "")
    if not zero > ELEVATION_CORRELATION_MIN:
        found.add_count("georef", 1, f"stat_elev_mean correlates {zero:.4f} with the base map elevation (needs > {ELEVATION_CORRELATION_MIN})")
    if better:
        found.add_count("georef", 1, f"stat_elev_mean correlates better with the base map at a shifted cell {sorted(better)} "
                                     f"({max(better.values()):.4f}) than at zero offset ({zero:.4f})")
    found.notes.append("georef: elevation correlation at zero offset %.5f, best one-cell shift %.5f" % (
        zero, max(v for k, v in table.items() if k != (0, 0))))


# ------------------------------------------------------------------------------------------------------ places

def _haversine_km(lat1, lon1, lat2, lon2) -> np.ndarray:
    p1, p2 = np.radians(lat1), np.radians(lat2)
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(np.radians(lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a))


def check_places(table: pd.DataFrame, places: pd.DataFrame, base: Basemap | None, found) -> None:
    scored = _scored(table)
    ids = table["cell_id"].to_numpy(dtype=np.int64)
    label = places.drop_duplicates("cell_id").set_index("cell_id").reindex(ids)
    has = label["place"].notna().to_numpy()
    lat, lon = cell_center(ids)
    with np.errstate(invalid="ignore"):
        distance = _haversine_km(lat, lon, label["place_lat"].to_numpy(dtype=np.float64), label["place_lon"].to_numpy(dtype=np.float64))
        stored = label["distance_km"].to_numpy(dtype=np.float64)
        wrong_distance = has & ~(np.abs(distance - stored) <= DISTANCE_ROUNDING_KM)
    problems = {"the cell has no place label": scored & ~has,
                "the place name is empty": scored & has & (label["place"].fillna("").str.strip() == "").to_numpy(),
                "distance_km is not the distance to the place": scored & wrong_distance}
    if base is not None:
        row, col, inside = base.locate(ids)
        klass = np.where(inside, base.mask[np.where(inside, row, 0), np.where(inside, col, 0)], bm.SEA)
        expected = np.array([COUNTRY_OF_CLASS.get(int(k), "") for k in klass], dtype=object)
        country = label["country"].to_numpy(dtype=object)
        problems["the country of the place is not that of the cell in the base map"] = (
            scored & has & (expected != "") & (country != expected))
    found.note_count("places_over_30km", int((scored & has & (stored > FAR_PLACE_KM)).sum()))
    flag(found, "places", table, problems)


def check_imd_sampling(features: pd.DataFrame, grid: np.ndarray | None, lon_offset_columns: int, found) -> None:
    """`src_imd_acc_1` of lead 0 is the IMD real-time grid of the day read at the cell's nearest point moved
    `lon_offset_columns` columns (`adapter.imd_cell_series`). Compared where a value is stored (a day whose file had not been
    published at run time stores none); `grid` is the day's (129, 135) grid, NaN for missing."""
    from ..features.sources import _imd_pixels
    if "src_imd_acc_1" not in features.columns or grid is None:
        return
    stored = features["src_imd_acc_1"].to_numpy(dtype=np.float64)
    if not np.isfinite(stored).any():
        found.notes.append("georef: no IMD value stored for the day (the file was not published at run time): sampling not checked")
        return
    pixel = _imd_pixels(features["cell_id"].to_numpy(dtype=np.int64), lon_offset_columns)
    flat = np.asarray(grid, dtype=np.float64).ravel()
    expected = np.where(pixel >= 0, flat[np.where(pixel >= 0, pixel, 0)], np.nan)
    flag(found, "georef", features, {f"src_imd_acc_1 is not the IMD grid read {lon_offset_columns:+d} columns from the nearest point":
                                     np.isfinite(stored) & ~(np.abs(stored - expected) <= 1e-4 + 1e-5 * np.abs(expected))})


# ---------------------------------------------------------------------------------------------- the notes

def terrain_notes(table: pd.DataFrame, terrain: pd.DataFrame, found) -> None:
    """NOTES (modelling plausibility, never violations): alerts per level on cells of low slope or low elevation."""
    if not {"stat_slope_mean", "stat_elev_mean"} <= set(terrain.columns) or "level" not in table.columns:
        return
    joined = table[["cell_id", "level"]].merge(terrain.drop_duplicates("cell_id")[["cell_id", "stat_slope_mean", "stat_elev_mean"]],
                                                on="cell_id", how="left")
    with np.errstate(invalid="ignore"):
        for name, mask in (("slope_lt_5deg", joined["stat_slope_mean"].to_numpy() < LOW_SLOPE_DEG),
                           ("elev_lt_100m", joined["stat_elev_mean"].to_numpy() < LOW_ELEVATION_M)):
            for level in range(lv.WATCH, lv.EMERGENCY + 1):
                found.note_count(f"{name}_{lv.level_name(level)}", int((mask & (joined["level"].to_numpy() == level)).sum()))


# ---------------------------------------------------------------------------------------------- rain georef

def imd_grid_files(live_dir: Path) -> dict[date, Path]:
    """Every IMD real-time grid kept under the published days' `raw/imd_rt/` folders, by the IMD day it holds."""
    found: dict[date, Path] = {}
    for name in sorted(glob.glob(str(Path(live_dir) / "*" / "raw" / "imd_rt" / "*.grd"))):
        stem = Path(name).stem
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", stem):
            found.setdefault(date.fromisoformat(stem), Path(name))
    return found


class _Sums:
    """Sufficient statistics of a Pearson correlation over pooled pairs."""

    def __init__(self) -> None:
        self.n = self.sx = self.sy = self.sxx = self.syy = self.sxy = 0.0

    def add(self, x: np.ndarray, y: np.ndarray) -> None:
        ok = np.isfinite(x) & np.isfinite(y)
        x, y = x[ok].astype(np.float64), y[ok].astype(np.float64)
        self.n += len(x)
        self.sx += x.sum(); self.sy += y.sum()
        self.sxx += (x * x).sum(); self.syy += (y * y).sum(); self.sxy += (x * y).sum()

    def correlation(self) -> float:
        if self.n < 3:
            return float("nan")
        vx, vy = self.sxx / self.n - (self.sx / self.n) ** 2, self.syy / self.n - (self.sy / self.n) ** 2
        if vx <= 0 or vy <= 0:
            return float("nan")
        return float((self.sxy / self.n - self.sx / self.n * self.sy / self.n) / np.sqrt(vx * vy))


def rain_georef(daily: dict[date, pd.DataFrame], grids: dict[date, np.ndarray], margin: float = SHIFT_MARGIN,
                min_pairs: int = MIN_RAIN_PAIRS, lon_offset_columns: int = 0) -> dict:
    """Is the IMERG rain (`irain_acc_1` of each day's features, an IMD day) registered with the IMD real-time grid
    (`src_imd_acc_1` of the same table is that grid at the cell's nearest 0.25 degree point)?

    For every IMD-grid offset (dlat, dlon) in RAIN_SHIFTS cells, and every day lag in RAIN_LAGS, the Pearson correlation of
    the cells' IMERG rain with the grid sampled there, pooled over all the days with both. A shifted or lagged product
    "clearly" beats the aligned one when its correlation exceeds the zero-offset, zero-lag one by more than `margin`
    (SHIFT_MARGIN, 0.02): then the registration is suspect. The aligned sampling is the live one: the nearest point moved
    `lon_offset_columns` columns (`imd_lon_offset_columns` of the run configuration; offsets are relative to it). Returns {"spatial": {"dlat,dlon": r}, "lag": {lag: r},
    "pairs": {...}, "violations": [text], "days": n, "decided": bool}.
    """
    from ..features.sources import _imd_pixels
    sums = {("s", s): _Sums() for s in RAIN_SHIFTS} | {("l", lag): _Sums() for lag in RAIN_LAGS if lag}
    used = 0
    for day, frame in daily.items():
        if "irain_acc_1" not in frame.columns:
            continue
        pixel = _imd_pixels(frame["cell_id"].to_numpy(dtype=np.int64), lon_offset_columns)
        i, j = np.divmod(np.where(pixel >= 0, pixel, 0), imd_mod.N_LON)
        valid = pixel >= 0
        rain = frame["irain_acc_1"].to_numpy(dtype=np.float64)

        def sample(grid, di=0, dj=0):
            ii, jj = i + di, j + dj
            ok = valid & (ii >= 0) & (ii < imd_mod.N_LAT) & (jj >= 0) & (jj < imd_mod.N_LON)
            out = np.full(len(i), np.nan)
            out[ok] = grid[ii[ok], jj[ok]]
            return out
        got = False
        for lag in RAIN_LAGS:
            grid = grids.get(day + timedelta(days=lag))
            if grid is None:
                continue
            if lag == 0:
                got = True
                for shift in RAIN_SHIFTS:
                    sums[("s", shift)].add(rain, sample(grid, *shift))
            else:
                sums[("l", lag)].add(rain, sample(grid))
        used += got
    spatial = {f"{a},{b}": sums[("s", (a, b))].correlation() for a, b in RAIN_SHIFTS}
    lag = {str(k): (sums[("s", (0, 0))].correlation() if k == 0 else sums[("l", k)].correlation()) for k in RAIN_LAGS}
    pairs = {"spatial": {f"{a},{b}": int(sums[("s", (a, b))].n) for a, b in RAIN_SHIFTS}, "lag": {
        str(k): int(sums[("s", (0, 0))].n if k == 0 else sums[("l", k)].n) for k in RAIN_LAGS}}
    decided = sums[("s", (0, 0))].n >= min_pairs and np.isfinite(spatial["0,0"])
    violations = []
    if decided:
        zero = spatial["0,0"]
        for key, value in spatial.items():
            if key != "0,0" and np.isfinite(value) and value > zero + margin:
                violations.append(f"IMD grid sampled at offset ({key}) cells correlates {value:.4f} with IMERG, more than "
                                  f"{margin} above the aligned {zero:.4f}")
        for key, value in lag.items():
            if key != "0" and np.isfinite(value) and value > zero + margin:
                violations.append(f"IMD grid of day {int(key):+d} correlates {value:.4f} with IMERG, more than {margin} above the same day's {zero:.4f}")
    return {"spatial": spatial, "lag": lag, "pairs": pairs, "violations": violations, "days": used, "decided": bool(decided),
            "margin": margin, "lon_offset_columns": int(lon_offset_columns)}
