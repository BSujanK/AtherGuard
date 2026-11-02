"""Whole-India 3D base map data: elevation and a country mask on the 0.05 degree grid, plus national outlines.

CLI: python -m aetherguard.serve.basemap build [--raw-dir DIR] [--out-dir DIR] [--manifest PATH] [--skip-download]

The grid is the project's 0.05 degree global grid cropped to lat 6.0-37.5 N, lon 68.0-98.0 E (630 rows x 600 cols).
Row 0 is the southernmost row and column 0 the westernmost, as in `terrain_grid`; `elev[row, col]` is the cell with id
`(lat_index0 + row) * id_stride + lon_index0 + col`.

Sources (public domain, no login), every download recorded in the data manifest:
  - NOAA NCEI ETOPO 2022 surface elevation, 15 arc-second tiles, area-averaged to the grid cell (12 x 12 pixels).
    Sea cells keep their bathymetry; the mask marks them as sea.
  - Natural Earth 1:10m admin-0 countries, India point of view, for the mask and the outlines.

Writes `india_basemap.npz` (elev float32, mask uint8, lat0, lon0, step) and `india_basemap.json` (grid, statistics,
sources with licences and checksums, outline polylines for India, Nepal and Bhutan).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import h5py
import numpy as np
import shapely
from shapely.geometry import shape

from ..config import PROJECT_ROOT, data_root
from ..grid import CELL_DEG, ID_STRIDE, latlon_to_cell
from ..http import DownloadError, download
from ..manifest import Manifest, sha256_file

GRID_STEP = CELL_DEG
SCHEMA_VERSION = 1
NPZ_NAME = "india_basemap.npz"
JSON_NAME = "india_basemap.json"

SEA, INDIA, NEPAL, BHUTAN, OTHER = 0, 1, 2, 3, 4
CLASS_NAMES = {SEA: "sea or outside", INDIA: "India", NEPAL: "Nepal", BHUTAN: "Bhutan", OTHER: "other land"}
_CLASS_BY_CODE = {"IND": INDIA, "NPL": NEPAL, "BTN": BHUTAN}
OUTLINE_COUNTRIES = (("IND", "India"), ("NPL", "Nepal"), ("BTN", "Bhutan"))
OUTLINE_TOLERANCE = 0.01  # degrees, Douglas-Peucker
OUTLINE_DECIMALS = 4
SMALL_POLYGON_AREA = (2 * GRID_STEP) ** 2  # deg^2: smaller land can miss every cell centre, so it marks the cells it touches
MIN_OVERLAP = 1e-8  # deg^2: smaller overlaps are touching edges / float noise, not land in the cell
CHUNK_CELL_ROWS = 64  # cell rows read from a tile at a time (bounds memory)

ETOPO_BASE = "https://www.ngdc.noaa.gov/thredds/fileServer/global/ETOPO2022/15s/15s_surface_elev_netcdf/"
ETOPO_LICENCE = "NOAA NCEI open data (public domain)"
ETOPO_TILE_DEG = 15
COUNTRIES_NAME = "ne_10m_admin_0_countries_ind.geojson"
COUNTRIES_URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/" + COUNTRIES_NAME
COUNTRIES_LICENCE = "Natural Earth (public domain)"


class BasemapError(RuntimeError):
    """The base map cannot be built from the inputs; the message names what is wrong."""


@dataclass(frozen=True)
class Grid:
    """A rectangle of the 0.05 degree global grid, south-west corner (lat0, lon0), row 0 = south, col 0 = west."""

    lat0: float
    lon0: float
    rows: int
    cols: int

    @property
    def lat1(self) -> float:
        return round(self.lat0 + self.rows * GRID_STEP, 6)

    @property
    def lon1(self) -> float:
        return round(self.lon0 + self.cols * GRID_STEP, 6)

    @property
    def lat_index0(self) -> int:
        return int(latlon_to_cell(self.lat0, self.lon0)) // ID_STRIDE

    @property
    def lon_index0(self) -> int:
        return int(latlon_to_cell(self.lat0, self.lon0)) % ID_STRIDE

    def lat_centres(self) -> np.ndarray:
        return self.lat0 + (np.arange(self.rows) + 0.5) * GRID_STEP

    def lon_centres(self) -> np.ndarray:
        return self.lon0 + (np.arange(self.cols) + 0.5) * GRID_STEP

    def locate(self, lat: float, lon: float) -> tuple[int, int]:
        """(row, col) of the cell containing the point, by the same rule as the global grid."""
        row, col = divmod(int(latlon_to_cell(lat, lon)), ID_STRIDE)
        row, col = row - self.lat_index0, col - self.lon_index0
        if not (0 <= row < self.rows and 0 <= col < self.cols):
            raise ValueError(f"point ({lat}, {lon}) is outside the base map grid")
        return row, col

    def cell_ids(self) -> np.ndarray:
        rows = (self.lat_index0 + np.arange(self.rows, dtype=np.int64))[:, None]
        cols = (self.lon_index0 + np.arange(self.cols, dtype=np.int64))[None, :]
        return rows * ID_STRIDE + cols


INDIA_GRID = Grid(lat0=6.0, lon0=68.0, rows=630, cols=600)


@dataclass(frozen=True)
class Source:
    name: str
    url: str
    dest: Path
    licence: str
    is_elevation: bool


# --- elevation --------------------------------------------------------------------------------

def area_average(z: np.ndarray, factor: int) -> np.ndarray:
    """float32 mean of each `factor` x `factor` block of `z`, ignoring NaN; NaN where a block has no valid pixel."""
    rows, cols = z.shape
    if rows % factor or cols % factor:
        raise ValueError(f"raster shape {z.shape} is not a multiple of the block size {factor}")
    blocks = z.reshape(rows // factor, factor, cols // factor, factor)
    valid = ~np.isnan(blocks)
    total = np.where(valid, blocks, 0.0).sum(axis=(1, 3), dtype=np.float64)
    count = valid.sum(axis=(1, 3))
    out = np.full(total.shape, np.nan, dtype=np.float64)
    np.divide(total, count, out=out, where=count > 0)
    return out.astype(np.float32)


def tile_names(grid: Grid) -> list[str]:
    """ETOPO 2022 15 arc-second tile file names covering the grid. A name gives the tile's north and west edges."""
    names = []
    south = math.floor(grid.lat0 / ETOPO_TILE_DEG) * ETOPO_TILE_DEG
    while south < grid.lat1:
        top = south + ETOPO_TILE_DEG
        lat_part = f"N{top:02d}" if top >= 0 else f"S{-top:02d}"
        west = math.floor(grid.lon0 / ETOPO_TILE_DEG) * ETOPO_TILE_DEG
        while west < grid.lon1:
            lon_part = f"E{west:03d}" if west >= 0 else f"W{-west:03d}"
            names.append(f"ETOPO_2022_v1_15s_{lat_part}{lon_part}_surface.nc")
            west += ETOPO_TILE_DEG
        south += ETOPO_TILE_DEG
    return names


def _cell_range(lo_edge: float, hi_edge: float, origin: float, count: int) -> tuple[int, int]:
    """Indices of the grid cells that lie wholly inside [lo_edge, hi_edge]."""
    first = math.ceil(round((lo_edge - origin) / GRID_STEP, 6))
    last = math.floor(round((hi_edge - origin) / GRID_STEP, 6))
    return max(first, 0), min(last, count)


def elevation_grid(tiles: list[Path], grid: Grid) -> np.ndarray:
    """float32 (rows, cols) mean elevation per cell from netCDF tiles (`lat`, `lon`, `z`, pixel centres, south first)."""
    elev = np.full((grid.rows, grid.cols), np.nan, dtype=np.float32)
    covered = np.zeros((grid.rows, grid.cols), dtype=bool)
    for path in tiles:
        with h5py.File(path, "r") as handle:
            lat, lon, z = handle["lat"][:], handle["lon"][:], handle["z"]
            spacing = float(lat[1] - lat[0])
            per_cell = GRID_STEP / spacing
            if spacing <= 0 or abs(per_cell - round(per_cell)) > 1e-6 or abs(float(lon[1] - lon[0]) - spacing) > 1e-9:
                raise BasemapError(f"{Path(path).name}: pixel resolution {spacing} does not divide the {GRID_STEP} degree cell")
            per_cell = round(per_cell)
            row0, row1 = _cell_range(lat[0] - spacing / 2, lat[-1] + spacing / 2, grid.lat0, grid.rows)
            col0, col1 = _cell_range(lon[0] - spacing / 2, lon[-1] + spacing / 2, grid.lon0, grid.cols)
            if row1 <= row0 or col1 <= col0:
                continue
            first_pixel_row = round((grid.lat0 + row0 * GRID_STEP - (lat[0] - spacing / 2)) / spacing)
            first_pixel_col = round((grid.lon0 + col0 * GRID_STEP - (lon[0] - spacing / 2)) / spacing)
            fill = z.attrs.get("_FillValue")
            pixel_cols = slice(first_pixel_col, first_pixel_col + (col1 - col0) * per_cell)
            for start in range(row0, row1, CHUNK_CELL_ROWS):
                stop = min(start + CHUNK_CELL_ROWS, row1)
                pixel_rows = slice(first_pixel_row + (start - row0) * per_cell, first_pixel_row + (stop - row0) * per_cell)
                block = z[pixel_rows, pixel_cols].astype(np.float32)
                block[~np.isfinite(block)] = np.nan
                if fill is not None:
                    block[block == np.float32(np.asarray(fill).reshape(-1)[0])] = np.nan
                elev[start:stop, col0:col1] = area_average(block, per_cell)
                covered[start:stop, col0:col1] = True
    if not covered.all():
        raise BasemapError(f"{int((~covered).sum())} of {covered.size} grid cells are not covered by the elevation tiles")
    if np.isnan(elev).any():
        raise BasemapError(f"{int(np.isnan(elev).sum())} grid cells have no valid elevation pixel")
    return elev


# --- mask and outline -------------------------------------------------------------------------

def class_of(adm0_a3: str) -> int:
    return _CLASS_BY_CODE.get(adm0_a3, OTHER)


def _polygons(feature: dict) -> list:
    geometry = shape(feature["geometry"])
    return list(geometry.geoms) if hasattr(geometry, "geoms") else [geometry]


def _centre_window(bounds: tuple[float, float, float, float], grid: Grid) -> tuple[slice, slice]:
    """Rows and cols of the cells whose centres lie inside `bounds` (empty slices when there are none)."""
    min_lon, min_lat, max_lon, max_lat = bounds
    rows = np.searchsorted(grid.lat_centres(), [min_lat, max_lat])
    cols = np.searchsorted(grid.lon_centres(), [min_lon, max_lon])
    return slice(int(rows[0]), int(rows[1])), slice(int(cols[0]), int(cols[1]))


def _touched_window(bounds: tuple[float, float, float, float], grid: Grid) -> tuple[range, range]:
    """Rows and cols of the cells that `bounds` overlaps."""
    min_lon, min_lat, max_lon, max_lat = bounds

    def span(low: float, high: float, origin: float, count: int) -> range:
        first = math.floor(round((low - origin) / GRID_STEP, 6))
        last = math.ceil(round((high - origin) / GRID_STEP, 6))
        return range(max(first, 0), min(last, count))
    return span(min_lat, max_lat, grid.lat0, grid.rows), span(min_lon, max_lon, grid.lon0, grid.cols)


def classify_mask(features: list[dict], grid: Grid) -> np.ndarray:
    """uint8 (rows, cols): 0 sea, 1 India, 2 Nepal, 3 Bhutan, 4 other land.

    A cell takes the class of the polygon containing its centre; India wins over Nepal and Bhutan, which win over other
    land. A polygon smaller than a few cells (an island) can miss every centre, so it also claims the still-empty cells
    it overlaps. Holes stay unclassified unless another country fills them.
    """
    mask = np.zeros((grid.rows, grid.cols), dtype=np.uint8)
    lat_c, lon_c = grid.lat_centres(), grid.lon_centres()
    polygons = sorted(((class_of(f["properties"]["ADM0_A3"]), polygon) for f in features for polygon in _polygons(f)),
                      key=lambda item: item[0])  # highest priority (lowest class number) first
    for cls, polygon in reversed(polygons):  # paint lowest priority first so higher priority overwrites
        rows, cols = _centre_window(polygon.bounds, grid)
        if rows.stop <= rows.start or cols.stop <= cols.start:
            continue
        shapely.prepare(polygon)
        x, y = np.meshgrid(lon_c[cols], lat_c[rows])
        mask[rows, cols][shapely.contains_xy(polygon, x, y)] = cls
    for cls, polygon in polygons:  # the first claimant of an empty cell keeps it
        if polygon.area >= SMALL_POLYGON_AREA:
            continue
        rows, cols = _touched_window(polygon.bounds, grid)
        for row in rows:
            for col in cols:
                if mask[row, col]:
                    continue
                cell = shapely.box(grid.lon0 + col * GRID_STEP, grid.lat0 + row * GRID_STEP,
                                   grid.lon0 + (col + 1) * GRID_STEP, grid.lat0 + (row + 1) * GRID_STEP)
                if polygon.intersection(cell).area > MIN_OVERLAP:
                    mask[row, col] = cls
    return mask


def _ring(coords) -> list[list[float]]:
    return [[round(float(lon), OUTLINE_DECIMALS), round(float(lat), OUTLINE_DECIMALS)] for lon, lat in coords]


def outline_rings(features: list[dict], tolerance: float = OUTLINE_TOLERANCE) -> list[dict]:
    """`[{name, rings: [[[lon, lat], ...]]}]` for India, Nepal and Bhutan: every polygon's exterior and hole rings,
    Douglas-Peucker simplified (topology preserved, so a small island keeps a closed ring)."""
    by_code: dict[str, list] = {}
    for feature in features:
        code = feature["properties"]["ADM0_A3"]
        if code in dict(OUTLINE_COUNTRIES):
            by_code.setdefault(code, []).extend(_polygons(feature))
    outline = []
    for code, name in OUTLINE_COUNTRIES:
        if code not in by_code:
            raise BasemapError(f"no {name} ({code}) polygon in the country file")
        rings = []
        for polygon in by_code[code]:
            simple = shapely.simplify(polygon, tolerance, preserve_topology=True)
            rings.append(_ring(simple.exterior.coords))
            rings.extend(_ring(hole.coords) for hole in simple.interiors)
        outline.append({"name": name, "rings": rings})
    return outline


# --- build ------------------------------------------------------------------------------------

def default_sources(raw_dir: Path, grid: Grid = INDIA_GRID) -> list[Source]:
    tiles = [Source(f"NOAA NCEI ETOPO 2022 15 arc-second surface elevation, tile {name}", ETOPO_BASE + name,
                    raw_dir / "etopo2022_15s" / name, ETOPO_LICENCE, True) for name in tile_names(grid)]
    countries = Source("Natural Earth 1:10m admin-0 countries, India point of view (v5.1.2)", COUNTRIES_URL,
                       raw_dir / COUNTRIES_NAME, COUNTRIES_LICENCE, False)
    return [*tiles, countries]


def _write_atomic(path: Path, write: Callable) -> None:
    partial = path.with_name(path.name + ".tmp")
    try:
        with partial.open("wb") as handle:
            write(handle)
        partial.replace(path)
    finally:
        partial.unlink(missing_ok=True)


def _grid_meta(grid: Grid) -> dict:
    return {"lat0": grid.lat0, "lat1": grid.lat1, "lon0": grid.lon0, "lon1": grid.lon1, "step_deg": GRID_STEP,
            "rows": grid.rows, "cols": grid.cols, "row0": "south", "col0": "west",
            "lat_index0": grid.lat_index0, "lon_index0": grid.lon_index0, "id_stride": ID_STRIDE}


def build_basemap(sources: list[Source], out_dir: Path, manifest: Manifest, grid: Grid = INDIA_GRID,
                  fetch: Callable = download, skip_download: bool = False, tolerance: float = OUTLINE_TOLERANCE) -> dict:
    """Fetch any source that is not current in the manifest, then write the npz and json into `out_dir`; returns the json."""
    for source in sources:
        if manifest.is_current(source.dest):
            continue
        if skip_download:
            raise BasemapError(f"{source.dest} is missing or differs from its manifest entry (run without --skip-download)")
        fetch(source.url, source.dest, manifest, source.name, source.licence)
    entries = manifest.entries()
    recorded = []
    for source in sources:
        entry = entries.get(manifest.relpath(source.dest))
        if entry is None:
            raise BasemapError(f"{source.dest} is not recorded in the manifest")
        recorded.append({"name": source.name, "url": entry.url, "licence": entry.licence, "path": entry.path,
                         "size_bytes": entry.size_bytes, "sha256": entry.sha256})
    countries = [s for s in sources if not s.is_elevation]
    if len(countries) != 1:
        raise BasemapError("exactly one country file source is required")
    with countries[0].dest.open("r", encoding="utf-8") as handle:
        features = json.load(handle)["features"]
    outline = outline_rings(features, tolerance)
    elev = elevation_grid([s.dest for s in sources if s.is_elevation], grid)
    mask = classify_mask(features, grid)
    india = elev[mask == INDIA]
    if not india.size:
        raise BasemapError("no grid cell falls inside India")

    out_dir.mkdir(parents=True, exist_ok=True)
    npz_path = out_dir / NPZ_NAME
    _write_atomic(npz_path, lambda handle: np.savez_compressed(
        handle, elev=elev, mask=mask, lat0=np.float64(grid.lat0), lon0=np.float64(grid.lon0), step=np.float64(GRID_STEP)))
    meta = {
        "schema_version": SCHEMA_VERSION,
        "name": "india_basemap",
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "grid": _grid_meta(grid),
        "elev": {
            "unit": "m", "dtype": "float32", "vertical_datum": "EGM2008 height (ETOPO 2022 surface elevation)",
            "method": "mean of the ETOPO 2022 15 arc-second pixels in each 0.05 degree cell; sea cells keep bathymetry",
            "min": float(elev.min()), "max": float(elev.max()),
            "india_min": float(india.min()), "india_max": float(india.max()),
        },
        "mask": {
            "dtype": "uint8", "classes": {str(k): v for k, v in CLASS_NAMES.items()},
            "method": "class of the Natural Earth India point-of-view polygon containing the cell centre "
                      "(India over Nepal/Bhutan over other land); islands smaller than a few cells mark the cells they touch",
            "counts": {str(k): int((mask == k).sum()) for k in CLASS_NAMES},
        },
        "outline": outline,
        "outline_tolerance_deg": tolerance,
        "sources": recorded,
        "files": {NPZ_NAME: {"size_bytes": npz_path.stat().st_size, "sha256": sha256_file(npz_path)}},
    }
    _write_atomic(out_dir / JSON_NAME, lambda handle: handle.write(json.dumps(meta, separators=(",", ":")).encode("utf-8")))
    return meta


def format_summary(meta: dict, out_dir: Path, seconds: float) -> str:
    grid, elev = meta["grid"], meta["elev"]
    counts = ", ".join(f"{meta['mask']['classes'][k]} {v}" for k, v in meta["mask"]["counts"].items())
    downloaded = sum(s["size_bytes"] for s in meta["sources"]) / 1e6
    return "\n".join([
        f"basemap: {grid['rows']} x {grid['cols']} cells, lat {grid['lat0']}-{grid['lat1']}, lon {grid['lon0']}-{grid['lon1']} "
        f"-> {out_dir} in {seconds:.0f} s",
        f"  elevation {elev['min']:.0f} to {elev['max']:.0f} m (India {elev['india_min']:.0f} to {elev['india_max']:.0f} m)",
        f"  mask: {counts}",
        f"  sources: {len(meta['sources'])} files, {downloaded:.0f} MB",
    ])


def main(argv: list[str] | None = None, fetch: Callable = download) -> int:
    parser = argparse.ArgumentParser(description="Build the whole-India 3D base map data (elevation, mask, outlines).")
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="download the sources (idempotent) and write the base map files")
    build.add_argument("--raw-dir", type=Path, help="default: <data>/raw/basemap")
    build.add_argument("--out-dir", type=Path, help="default: <data>/processed/basemap")
    build.add_argument("--manifest", type=Path, help="default: <project>/manifests/data_manifest.jsonl")
    build.add_argument("--skip-download", action="store_true", help="build from the files already on disk")
    args = parser.parse_args(argv)
    raw_dir = args.raw_dir or data_root() / "raw" / "basemap"
    out_dir = args.out_dir or data_root() / "processed" / "basemap"
    manifest = Manifest(args.manifest or PROJECT_ROOT / "manifests" / "data_manifest.jsonl", data_root())
    started = time.perf_counter()
    try:
        meta = build_basemap(default_sources(raw_dir), out_dir, manifest, fetch=fetch, skip_download=args.skip_download)
    except (BasemapError, DownloadError, ValueError, OSError) as exc:
        print(f"basemap: error: {exc}", file=sys.stderr)
        return 1
    print(format_summary(meta, out_dir, time.perf_counter() - started))
    return 0


if __name__ == "__main__":
    sys.exit(main())
