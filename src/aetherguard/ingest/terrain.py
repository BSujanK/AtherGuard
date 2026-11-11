"""Copernicus GLO-90 DEM ingest and per-cell terrain statistics (docs/phase1-design.md D7, ruling for Task 4).

Product: Copernicus DEM GLO-90 (3 arc-second, 1200 x 1200 pixels per 1-degree tile, float32, EPSG:4326, nodata
undeclared) from the public AWS Open Data bucket `copernicus-dem-90m` (no credentials). Ocean-only 1-degree
tiles do not exist (HTTP 404); they are recorded as `absent`, not as failures.

Pixel lattice (verified on real tiles). Pixel CENTRES lie on multiples of 1/1200 degree in both axes, so a pixel
centre coincides with every 0.05-degree cell edge. Global integer pixel indices are therefore exact:
    row i  <-> centre latitude  -90 + i/1200  (increases northward),
    col j  <-> centre longitude -180 + j/1200,
and cell (lat_idx, lon_idx) of `grid.py` owns rows 60*lat_idx .. 60*lat_idx+59 and cols 60*lon_idx .. 60*lon_idx+59
(a pixel centred exactly on a cell edge belongs to the cell above / to the east, like `grid.latlon_to_cell`).
Tile (lat_floor F, lon_floor G), named after its lower-left corner, holds rows (F+90)*1200+1 .. (F+91)*1200 (its
top row is centred ON latitude F+1, not below it) and cols (G+180)*1200 .. (G+181)*1200-1. Cells therefore
straddle tile borders and every cell is computed on a mosaic with a 1-pixel halo.

Validity. A pixel is valid when it is finite, above -100 m, not the declared nodata value and not exactly 0.0:
the DEM stores the sea (and the zero-height shore) as 0.0, while genuine land below sea level (Kuttanad,
Bangladesh delta) is small negative. Missing tiles, nodata and sea pixels are NaN and are counted.

Slope, aspect, curvature use the 3x3 neighbourhood of a pixel and exist only when all nine pixels are valid.
    pixel size in metres: dy = 111_320 / 1200 (constant), dx = 111_320 * cos(latitude of that pixel row) / 1200.
    slope: Horn (Sobel) gradient, degrees. Aspect: unit vector of the DOWNSLOPE direction (sin = east component,
    cos = north component), averaged over pixels steeper than 2 degrees; NaN when no pixel is.
    curvature_mean: mean of -(d2z/dx2 + d2z/dy2) in 1/m (plain 3-point second differences): convex ridge and
    peak positive, valley and bowl negative.
    twi_proxy: mean of ln(1 / tan(max(slope, 0.1 deg))). A proxy for wetness from slope alone, NOT a flow-
    accumulation topographic wetness index.
"""
from __future__ import annotations

import json
import math
import os
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from rasterio.errors import RasterioError
from rasterio.windows import Window

from ..config import data_root
from ..grid import CELL_DEG, ID_STRIDE, cell_center, regions
from ..http import DownloadError, download
from ..manifest import Manifest

SOURCE = "Copernicus DEM GLO-90"
LICENCE = "Copernicus DEM GLO-90: free to use with attribution (ESA / Copernicus); verify terms before redistribution"
URL_BASE = "https://copernicus-dem-90m.s3.amazonaws.com"
TILE_PIXELS = 1200
CELL_PIXELS = 60  # 0.05 degree / (1/1200 degree)
CELL_PIXEL_COUNT = CELL_PIXELS * CELL_PIXELS
CELLS_PER_TILE = TILE_PIXELS // CELL_PIXELS
M_PER_DEG = 111_320.0
MAX_WORKERS = 6
MIN_VALID_FRACTION = 0.9
MIN_SLOPE_VALID_FRACTION = 0.5  # guards slope statistics against speckled voids; the 90 % rule is on elevation
VOID_BELOW_M = -100.0
ASPECT_MIN_SLOPE_DEG = 2.0
TWI_MIN_SLOPE_DEG = 0.1
ABSENT_FILE = "absent_tiles.json"
PARQUET_NAME = "cell_terrain.parquet"
REPORT_NAME = "terrain_report.json"

STAT_COLUMNS = [
    "elev_mean", "elev_std", "elev_min", "elev_max", "relief",
    "slope_mean", "slope_p90", "slope_max",
    "curvature_mean", "aspect_sin", "aspect_cos", "twi_proxy",
]
TERRAIN_COLUMNS = ["cell_id", "lat", "lon", "region_box", *STAT_COLUMNS, "valid_frac", "slope_valid_frac"]
DROP_DETAILS = ("absent_tile", "sea_or_water", "void_pixels", "edge_halo")

Tile = tuple[int, int]  # (lat_floor, lon_floor) of the tile's lower-left corner


class TerrainError(RuntimeError):
    """A DEM tile is unusable (wrong geometry, unreadable)."""


class TerrainIncompleteError(TerrainError):
    """A needed tile has neither been downloaded nor recorded as absent."""


class TileAbsentError(Exception):
    """The server has no tile here (an ocean-only tile): expected, recorded, not a failure."""


# ------------------------------------------------------------------------------------------------- tiles

def tile_name(lat_floor: int, lon_floor: int) -> str:
    if lat_floor != int(lat_floor) or lon_floor != int(lon_floor):
        raise ValueError("tile corners are whole degrees")
    lat_floor, lon_floor = int(lat_floor), int(lon_floor)
    if not (-90 <= lat_floor <= 89 and -180 <= lon_floor <= 179):
        raise ValueError(f"tile corner ({lat_floor}, {lon_floor}) is outside the globe")
    ns = "N" if lat_floor >= 0 else "S"
    ew = "E" if lon_floor >= 0 else "W"
    return f"Copernicus_DSM_COG_30_{ns}{abs(lat_floor):02d}_00_{ew}{abs(lon_floor):03d}_00_DEM"


def tile_url(lat_floor: int, lon_floor: int) -> str:
    name = tile_name(lat_floor, lon_floor)
    return f"{URL_BASE}/{name}/{name}.tif"


def tile_path(raw_dir, lat_floor: int, lon_floor: int) -> Path:
    return Path(raw_dir) / f"{tile_name(lat_floor, lon_floor)}.tif"


def default_boxes() -> dict[str, dict[str, float]]:
    return regions()


def cells_in_boxes(boxes: dict[str, dict[str, float]]) -> pd.DataFrame:
    """Every 0.05-degree cell whose CENTRE lies in a box (lat_min <= c < lat_max, same for lon).

    Columns: cell_id, lat_idx, lon_idx, lat, lon (centre), region_box (the box name; `both` when the centre lies
    in more than one box), sorted by cell_id.
    """
    frames = []
    for name, box in boxes.items():
        lat_idx = np.arange(math.floor((box["lat_min"] + 90.0) / CELL_DEG) - 1,
                            math.ceil((box["lat_max"] + 90.0) / CELL_DEG) + 2, dtype=np.int64)
        lon_idx = np.arange(math.floor((box["lon_min"] + 180.0) / CELL_DEG) - 1,
                            math.ceil((box["lon_max"] + 180.0) / CELL_DEG) + 2, dtype=np.int64)
        ids = (lat_idx[:, None] * ID_STRIDE + lon_idx[None, :]).ravel()
        lat, lon = cell_center(ids)
        inside = ((lat >= box["lat_min"]) & (lat < box["lat_max"])
                  & (lon >= box["lon_min"]) & (lon < box["lon_max"]))
        frames.append(pd.DataFrame({"cell_id": ids[inside], "lat": lat[inside], "lon": lon[inside], "box": name}))
    if not frames:
        raise ValueError("no region boxes given")
    cells = pd.concat(frames, ignore_index=True)
    grouped = cells.groupby("cell_id", sort=True).agg(lat=("lat", "first"), lon=("lon", "first"),
                                                      boxes=("box", list))
    grouped["region_box"] = [names[0] if len(names) == 1 else "both" for names in grouped["boxes"]]
    out = grouped.drop(columns="boxes").reset_index()
    out["lat_idx"] = out["cell_id"] // ID_STRIDE
    out["lon_idx"] = out["cell_id"] % ID_STRIDE
    return out[["cell_id", "lat_idx", "lon_idx", "lat", "lon", "region_box"]]


def _tiles_for_cells(lat_idx: np.ndarray, lon_idx: np.ndarray) -> list[Tile]:
    """Tiles holding the pixels of these cells plus the one-pixel halo around their bounding rectangle."""
    if len(lat_idx) == 0:
        return []
    row_lo, row_hi = CELL_PIXELS * int(lat_idx.min()) - 1, CELL_PIXELS * (int(lat_idx.max()) + 1)
    col_lo, col_hi = CELL_PIXELS * int(lon_idx.min()) - 1, CELL_PIXELS * (int(lon_idx.max()) + 1)
    lat_floors = range((row_lo - 1) // TILE_PIXELS - 90, (row_hi - 1) // TILE_PIXELS - 90 + 1)
    lon_floors = range(col_lo // TILE_PIXELS - 180, col_hi // TILE_PIXELS - 180 + 1)
    return [(f, g) for f in lat_floors for g in lon_floors if -90 <= f <= 89 and -180 <= g <= 179]


def tiles_for_bbox(lat_min: float, lat_max: float, lon_min: float, lon_max: float) -> list[Tile]:
    """Tiles needed to compute every cell whose centre is in the box, including the halo pixels.

    That is the tiles overlapping the box plus one extra tile row at the southern edge (the pixel row centred on
    the edge latitude lives in the tile below) and one extra tile column on the eastern edge (halo column).
    """
    box = {"lat_min": lat_min, "lat_max": lat_max, "lon_min": lon_min, "lon_max": lon_max}
    cells = cells_in_boxes({"bbox": box})
    return _tiles_for_cells(cells["lat_idx"].to_numpy(), cells["lon_idx"].to_numpy())


def tiles_for_boxes(boxes: dict[str, dict[str, float]]) -> list[Tile]:
    needed: set[Tile] = set()
    for box in boxes.values():
        needed.update(tiles_for_bbox(box["lat_min"], box["lat_max"], box["lon_min"], box["lon_max"]))
    return sorted(needed)


# -------------------------------------------------------------------------------------------- download

@dataclass
class TileDownloadReport:
    ok: list[str] = field(default_factory=list)               # fetched in this run
    already_present: list[str] = field(default_factory=list)  # on disk and manifest-current
    absent: list[str] = field(default_factory=list)           # no such tile on the server (ocean)
    failed: dict[str, str] = field(default_factory=dict)      # tile name -> message
    bytes_downloaded: int = 0


def _atomic_write_json(path: Path, payload) -> None:
    part = path.with_name(path.name + ".part")
    try:
        part.write_text(json.dumps(payload, indent=1, allow_nan=False) + "\n", encoding="utf-8")
        os.replace(part, path)
    except BaseException:
        part.unlink(missing_ok=True)
        raise


def read_absent(raw_dir) -> set[str]:
    path = Path(raw_dir) / ABSENT_FILE
    if not path.exists():
        return set()
    return set(json.loads(path.read_text(encoding="utf-8")))


def _http_fetcher(manifest: Manifest, retries: int, backoff: float) -> Callable[[Tile, Path], None]:
    def fetch(tile: Tile, dest: Path) -> None:
        try:
            download(tile_url(*tile), dest, manifest, SOURCE, LICENCE, retries=retries, backoff=backoff, force=True)
        except DownloadError as exc:
            if exc.status == 404:
                raise TileAbsentError(str(exc)) from exc
            raise
    return fetch


def download_tiles(tiles: Sequence[Tile], raw_dir, manifest: Manifest, workers: int = MAX_WORKERS, *,
                   fetch: Callable[[Tile, Path], None] | None = None, retries: int = 3, backoff: float = 2.0,
                   retry_passes: int = 2, progress: Callable[[int, int], None] | None = None) -> TileDownloadReport:
    """Download the tiles into `raw_dir` (idempotent, resumable) and record each file in the manifest.

    A tile that is on disk and manifest-current is not fetched again. A tile the server does not have (HTTP 404,
    `TileAbsentError` from an injected `fetch`) is recorded in `absent_tiles.json` and never asked for again.
    Any other failure, including an empty file, is collected in `report.failed`; one failing tile never stops the
    others, and failed tiles get `retry_passes` more passes (pausing `backoff * 2**k` seconds before each) before
    they stay failed. `fetch(tile, dest)` must write `dest`; the default downloads over HTTP (with retries and backoff).
    """
    if not 1 <= workers <= MAX_WORKERS:
        raise ValueError(f"workers must be between 1 and {MAX_WORKERS}")
    tiles = list(tiles)
    if len(set(tiles)) != len(tiles):
        raise ValueError("tiles must be unique")
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    fetch = fetch or _http_fetcher(manifest, retries, backoff)
    known_absent = read_absent(raw_dir)

    def work(tile: Tile) -> tuple[str, str, int]:
        name, dest = tile_name(*tile), tile_path(raw_dir, *tile)
        if name in known_absent:
            return "absent", "", 0
        try:
            if manifest.is_current(dest):
                return "already_present", "", 0
            fetch(tile, dest)
            if not dest.is_file() or dest.stat().st_size == 0:
                return "failed", "fetcher produced no file or an empty file", 0
            if not manifest.is_current(dest):
                manifest.add(dest, SOURCE, tile_url(*tile), LICENCE)
            return "ok", "", dest.stat().st_size
        except TileAbsentError:
            return "absent", "", 0
        except Exception as exc:  # per-tile isolation: reported, never raised
            return "failed", f"{type(exc).__name__}: {exc}", 0

    report = TileDownloadReport()
    finished = 0
    pending = tiles
    for attempt in range(1 + retry_passes):
        if attempt:
            time.sleep(backoff * 2 ** (attempt - 1))  # transient local errors (file locks) and server hiccups
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(work, tile): tile for tile in pending}
            failed_tiles = []
            for future in as_completed(futures):
                tile = futures[future]
                name = tile_name(*tile)
                outcome, message, size = future.result()
                report.bytes_downloaded += size
                if outcome == "failed":
                    report.failed[name] = message
                    failed_tiles.append(tile)
                else:
                    report.failed.pop(name, None)
                    getattr(report, outcome).append(name)
                if attempt == 0:
                    finished += 1
                    if progress is not None:
                        progress(finished, len(tiles))
        pending = failed_tiles
        if not pending:
            break
    for names in (report.ok, report.already_present, report.absent):
        names.sort()
    requested = {tile_name(*tile) for tile in tiles}
    _atomic_write_json(raw_dir / ABSENT_FILE, sorted((known_absent - requested) | set(report.absent)))
    return report


# -------------------------------------------------------------------------------------- surface maths

def terrain_surface(z: np.ndarray, dx_m, dy_m: float) -> dict[str, np.ndarray]:
    """Slope, downslope-aspect unit vector, curvature and the TWI proxy per pixel.

    `z` is 2-D with rows increasing NORTHWARD and NaN for invalid pixels; `dx_m` is the east-west pixel size in
    metres, a scalar or one value per row; `dy_m` the north-south pixel size. Every output has the shape of `z`;
    the outer ring and every pixel with an invalid pixel in its 3x3 neighbourhood are NaN. `aspect_sin` and
    `aspect_cos` are NaN where the surface is exactly flat.
    """
    z = np.asarray(z, dtype=np.float64)
    dx = np.broadcast_to(np.asarray(dx_m, dtype=np.float64), (z.shape[0],))[1:-1, None]
    nw, n, ne = z[2:, :-2], z[2:, 1:-1], z[2:, 2:]
    w, c, e = z[1:-1, :-2], z[1:-1, 1:-1], z[1:-1, 2:]
    sw, s, se = z[:-2, :-2], z[:-2, 1:-1], z[:-2, 2:]
    dz_dx = ((ne + 2.0 * e + se) - (nw + 2.0 * w + sw)) / (8.0 * dx)
    dz_dy = ((nw + 2.0 * n + ne) - (sw + 2.0 * s + se)) / (8.0 * dy_m)
    gradient = np.where(np.isfinite(c), np.hypot(dz_dx, dz_dy), np.nan)  # Horn skips the centre; we do not
    slope = np.degrees(np.arctan(gradient))
    steepness = np.where(gradient > 0.0, gradient, np.nan)
    curvature = -((e - 2.0 * c + w) / dx ** 2 + (n - 2.0 * c + s) / dy_m ** 2)
    twi = -np.log(np.tan(np.radians(np.maximum(slope, TWI_MIN_SLOPE_DEG))))
    interior = {"slope_deg": slope, "aspect_sin": -dz_dx / steepness, "aspect_cos": -dz_dy / steepness,
                "curvature": curvature, "twi_proxy": twi}
    out = {}
    for key, values in interior.items():
        full = np.full(z.shape, np.nan)
        full[1:-1, 1:-1] = values
        out[key] = full
    return out


# ------------------------------------------------------------------------------------------ cell stats

def _check_geometry(ds, tile: Tile, path: Path) -> None:
    left, top = tile[1] - 0.5 / TILE_PIXELS, tile[0] + 1 + 0.5 / TILE_PIXELS
    step = 1.0 / TILE_PIXELS
    t = ds.transform
    if ((ds.height, ds.width) != (TILE_PIXELS, TILE_PIXELS) or abs(t.a - step) > 1e-9 or abs(t.e + step) > 1e-9
            or abs(t.c - left) > 1e-6 or abs(t.f - top) > 1e-6 or t.b != 0 or t.d != 0):
        raise TerrainError(f"{path.name}: unexpected geometry {ds.height}x{ds.width}, origin ({t.c}, {t.f}); "
                           f"expected {TILE_PIXELS}x{TILE_PIXELS} with pixel centres on multiples of "
                           f"1/{TILE_PIXELS} degree")


def _read_window(raw_dir: Path, absent: set[str], row0: int, row1: int, col0: int, col1: int
                 ) -> tuple[np.ndarray, np.ndarray]:
    """Elevations for global pixel rows row0..row1 and cols col0..col1 (inclusive), rows increasing northward.

    Returns (values, covered): values are NaN where the file declares nodata, and both are NaN / False where
    the tile is absent.
    """
    values = np.full((row1 - row0 + 1, col1 - col0 + 1), np.nan)
    covered = np.zeros(values.shape, dtype=bool)
    for lat_floor in range((row0 - 1) // TILE_PIXELS - 90, (row1 - 1) // TILE_PIXELS - 90 + 1):
        for lon_floor in range(col0 // TILE_PIXELS - 180, col1 // TILE_PIXELS - 180 + 1):
            tile = (lat_floor, lon_floor)
            path = tile_path(raw_dir, *tile)
            if not path.is_file():
                if tile_name(*tile) in absent:
                    continue
                raise TerrainIncompleteError(f"{path.name} is neither downloaded nor recorded as absent; "
                                             f"run the download first")
            top_row = (lat_floor + 91) * TILE_PIXELS            # global row of the tile's first (northern) row
            tile_col0 = (lon_floor + 180) * TILE_PIXELS
            r_lo, r_hi = max(row0, top_row - TILE_PIXELS + 1), min(row1, top_row)
            c_lo, c_hi = max(col0, tile_col0), min(col1, tile_col0 + TILE_PIXELS - 1)
            try:
                with rasterio.open(path) as ds:
                    _check_geometry(ds, tile, path)
                    window = Window(c_lo - tile_col0, top_row - r_hi, c_hi - c_lo + 1, r_hi - r_lo + 1)
                    data = ds.read(1, window=window, out_dtype="float64")
                    nodata = ds.nodata
            except RasterioError as exc:
                raise TerrainError(f"{path.name}: unreadable DEM tile ({type(exc).__name__}: {exc})") from exc
            if nodata is not None:
                data[data == nodata] = np.nan
            rows = slice(r_lo - row0, r_hi - row0 + 1)
            cols = slice(c_lo - col0, c_hi - col0 + 1)
            values[rows, cols] = data[::-1]
            covered[rows, cols] = True
    return values, covered


def _per_cell(array: np.ndarray, n_lat: int, n_lon: int) -> np.ndarray:
    """(n_lat*60, n_lon*60) pixels -> (n_lat*n_lon, 3600), cells in row-major (lat, lon) order."""
    return (array.reshape(n_lat, CELL_PIXELS, n_lon, CELL_PIXELS).transpose(0, 2, 1, 3)
            .reshape(n_lat * n_lon, CELL_PIXEL_COUNT))


def block_surface(raw_dir: Path, absent: set[str], lat_lo: int, lat_hi: int, lon_lo: int, lon_hi: int) -> dict:
    """The pixels of the cell rows lat_lo..lat_hi and columns lon_lo..lon_hi with a one-pixel halo: valid elevation
    `z` (NaN for sea-level zeros, voids and absent tiles), the masks `covered`, `zero`, `void`, and the `surface` of
    `terrain_surface`. Everything that needs per-pixel slope reads it here, so the void rules exist once."""
    row0, col0 = CELL_PIXELS * lat_lo - 1, CELL_PIXELS * lon_lo - 1
    raw, covered = _read_window(raw_dir, absent, row0, CELL_PIXELS * (lat_hi + 1), col0, CELL_PIXELS * (lon_hi + 1))
    zero = covered & (raw == 0.0)
    void = covered & (~np.isfinite(raw) | (raw <= VOID_BELOW_M))
    z = np.where(covered & ~zero & ~void, raw, np.nan)
    latitudes = -90.0 + (row0 + np.arange(z.shape[0])) / TILE_PIXELS
    surface = terrain_surface(z, M_PER_DEG * np.cos(np.radians(latitudes)) / TILE_PIXELS, M_PER_DEG / TILE_PIXELS)
    return {"z": z, "covered": covered, "zero": zero, "void": void, "surface": surface}


def _block_cells(raw_dir: Path, absent: set[str], cells: pd.DataFrame, min_valid: float):
    """Statistics of the given cells (all in one 1-degree block): (kept table, dropped cells, pixel counts)."""
    lat_lo, lat_hi = int(cells["lat_idx"].min()), int(cells["lat_idx"].max())
    lon_lo, lon_hi = int(cells["lon_idx"].min()), int(cells["lon_idx"].max())
    n_lat, n_lon = lat_hi - lat_lo + 1, lon_hi - lon_lo + 1
    block = block_surface(raw_dir, absent, lat_lo, lat_hi, lon_lo, lon_hi)
    z, covered, zero, void, surface = (block[k] for k in ("z", "covered", "zero", "void", "surface"))

    pick = ((cells["lat_idx"] - lat_lo) * n_lon + (cells["lon_idx"] - lon_lo)).to_numpy()

    def per_cell(array: np.ndarray) -> np.ndarray:
        return _per_cell(array[1:-1, 1:-1], n_lat, n_lon)[pick]

    elev, slope = per_cell(z), per_cell(surface["slope_deg"])
    n_valid, n_slope = np.isfinite(elev).sum(axis=1), np.isfinite(slope).sum(axis=1)
    n_zero, n_void = per_cell(zero).sum(axis=1), per_cell(void).sum(axis=1)
    n_uncovered = CELL_PIXEL_COUNT - per_cell(covered).sum(axis=1)
    threshold = min_valid * CELL_PIXEL_COUNT - 1e-9
    keep = (n_valid >= threshold) & (n_slope >= MIN_SLOPE_VALID_FRACTION * CELL_PIXEL_COUNT)
    counts = {"pixels_absent_tile": int(n_uncovered.sum()), "pixels_sea_level_zero": int(n_zero.sum()),
              "pixels_void": int(n_void.sum()), "pixels_total": int(len(pick) * CELL_PIXEL_COUNT)}

    limit = CELL_PIXEL_COUNT - threshold
    detail = np.where(n_uncovered > limit, "absent_tile", np.where(
        n_zero > limit, "sea_or_water", np.where(CELL_PIXEL_COUNT - n_valid > limit, "void_pixels", "edge_halo")))
    dropped = pd.DataFrame({"cell_id": cells["cell_id"].to_numpy()[~keep], "detail": detail[~keep]})

    kept_cells = cells[keep]
    e, s = elev[keep], slope[keep]
    steep = s > ASPECT_MIN_SLOPE_DEG
    steep_count = steep.sum(axis=1)

    def mean_over_steep(name: str) -> np.ndarray:
        total = np.where(steep, per_cell(surface[name])[keep], 0.0).sum(axis=1)
        return np.divide(total, steep_count, out=np.full(len(total), np.nan), where=steep_count > 0)

    table = pd.DataFrame({
        "cell_id": kept_cells["cell_id"].to_numpy(), "lat": kept_cells["lat"].to_numpy(),
        "lon": kept_cells["lon"].to_numpy(), "region_box": kept_cells["region_box"].to_numpy(),
        "elev_mean": np.nanmean(e, axis=1), "elev_std": np.nanstd(e, axis=1),
        "elev_min": np.nanmin(e, axis=1), "elev_max": np.nanmax(e, axis=1),
        "slope_mean": np.nanmean(s, axis=1), "slope_p90": np.nanpercentile(s, 90, axis=1),
        "slope_max": np.nanmax(s, axis=1),
        "curvature_mean": np.nanmean(per_cell(surface["curvature"])[keep], axis=1),
        "aspect_sin": mean_over_steep("aspect_sin"), "aspect_cos": mean_over_steep("aspect_cos"),
        "twi_proxy": np.nanmean(per_cell(surface["twi_proxy"])[keep], axis=1),
        "valid_frac": n_valid[keep] / CELL_PIXEL_COUNT, "slope_valid_frac": n_slope[keep] / CELL_PIXEL_COUNT,
    })
    table["relief"] = table["elev_max"] - table["elev_min"]
    return table[TERRAIN_COLUMNS], dropped, counts


def cell_terrain(raw_dir, boxes: dict[str, dict[str, float]] | None = None,
                 min_valid: float = MIN_VALID_FRACTION) -> tuple[pd.DataFrame, dict]:
    """Terrain statistics for every 0.05-degree cell whose centre is in a box, from the tiles in `raw_dir`.

    Cells with less than `min_valid` of their 3600 pixels valid are omitted and counted under `insufficient_dem`,
    with a detail: `absent_tile` (missing tile), `sea_or_water` (zero-height pixels), `void_pixels` (nodata /
    below -100 m), `edge_halo` (elevation fine but fewer than half the pixels have a valid 3x3 neighbourhood).
    Slope-based statistics use the slope-valid pixels only (`slope_valid_frac` says how many).
    Returns (table sorted by cell_id, stats).
    """
    if not 0.0 < min_valid <= 1.0:
        raise ValueError("min_valid must be in (0, 1]")
    raw_dir = Path(raw_dir)
    cells = cells_in_boxes(boxes or default_boxes())
    absent = read_absent(raw_dir)
    cells["block"] = (cells["lat_idx"] // CELLS_PER_TILE) * 100_000 + cells["lon_idx"] // CELLS_PER_TILE
    tables, dropped_frames = [], []
    pixels = {"pixels_absent_tile": 0, "pixels_sea_level_zero": 0, "pixels_void": 0, "pixels_total": 0}
    for _, block in cells.groupby("block", sort=True):
        table, dropped, counts = _block_cells(raw_dir, absent, block, min_valid)
        tables.append(table)
        dropped_frames.append(dropped)
        for key, value in counts.items():
            pixels[key] += value
    result = pd.concat(tables, ignore_index=True).sort_values("cell_id", kind="stable").reset_index(drop=True)
    dropped_all = pd.concat(dropped_frames, ignore_index=True)
    dropped_boxes = cells[cells["cell_id"].isin(dropped_all["cell_id"])]["region_box"]
    stats = {
        "cells_considered": int(len(cells)),
        "cells_kept": int(len(result)),
        "cells_dropped": {"insufficient_dem": int(len(dropped_all))},
        "insufficient_dem_detail": {key: int((dropped_all["detail"] == key).sum()) for key in DROP_DETAILS},
        "kept_by_region_box": {k: int(v) for k, v in result["region_box"].value_counts().sort_index().items()},
        "dropped_by_region_box": {k: int(v) for k, v in dropped_boxes.value_counts().sort_index().items()},
        **pixels,
    }
    return result, stats


# ----------------------------------------------------------------------------------------------- build

def _json_safe(value):
    """Plain JSON types: numpy scalars become Python numbers and NaN / inf become None."""
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return float(value) if math.isfinite(value) else None
    return value


def _relative(path: Path, root: Path) -> str:
    try:
        return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return Path(path).name


def _summary(values: pd.Series) -> dict:
    if values.dropna().empty:
        return {"n": 0, "min": None, "p05": None, "p25": None, "median": None, "p75": None, "p95": None,
                "max": None, "mean": None}
    q = values.quantile([0.05, 0.25, 0.5, 0.75, 0.95])
    return {"n": int(values.count()), "min": values.min(), "p05": q[0.05], "p25": q[0.25], "median": q[0.5],
            "p75": q[0.75], "p95": q[0.95], "max": values.max(), "mean": values.mean()}


def build_terrain(raw_dir, out_dir, boxes: dict[str, dict[str, float]] | None = None,
                  download_report: TileDownloadReport | None = None,
                  min_valid: float = MIN_VALID_FRACTION) -> dict:
    """Compute the cell table and write `cell_terrain.parquet` and `terrain_report.json` into `out_dir`."""
    raw_dir, out_dir = Path(raw_dir), Path(out_dir)
    boxes = boxes or default_boxes()
    table, stats = cell_terrain(raw_dir, boxes, min_valid)
    out_dir.mkdir(parents=True, exist_ok=True)
    parquet = out_dir / PARQUET_NAME
    part = parquet.with_name(parquet.name + ".part")
    try:
        table.to_parquet(part, index=False)
        os.replace(part, parquet)
    except BaseException:
        part.unlink(missing_ok=True)
        raise

    needed = [tile_name(*tile) for tile in tiles_for_boxes(boxes)]
    absent = read_absent(raw_dir)
    present = [name for name in needed if (raw_dir / f"{name}.tif").is_file()]
    root = data_root()
    summarised = ("elev_mean", "relief", "slope_mean", "slope_p90", "curvature_mean", "twi_proxy")
    report = {
        "product": SOURCE,
        "url_pattern": f"{URL_BASE}/<tile>/<tile>.tif",
        "tiles": {
            "needed": len(needed),
            "present": len(present),
            "absent": sorted(name for name in needed if name in absent),
            "failed": dict(sorted(download_report.failed.items())) if download_report else {},
            "fetched_this_run": len(download_report.ok) if download_report else 0,
            "bytes_on_disk": int(sum((raw_dir / f"{name}.tif").stat().st_size for name in present)),
            "bytes_downloaded_this_run": download_report.bytes_downloaded if download_report else 0,
        },
        "min_valid_fraction": min_valid,
        "cells": stats,
        "regions": {label: {"cells": int(len(group)), **{c: _summary(group[c]) for c in summarised}}
                    for label, group in table.groupby("region_box")},
        "method": {
            "pixel_size_m": f"dy = {M_PER_DEG:.0f}/1200, dx = {M_PER_DEG:.0f}*cos(pixel row latitude)/1200",
            "slope": "Horn 3x3, degrees, over pixels whose 3x3 neighbourhood is valid",
            "curvature_mean": "mean of -(d2z/dx2 + d2z/dy2) in 1/m; convex ridge/peak positive",
            "aspect": f"mean downslope unit vector over pixels steeper than {ASPECT_MIN_SLOPE_DEG} deg; NaN if none",
            "twi_proxy": f"mean ln(1/tan(max(slope, {TWI_MIN_SLOPE_DEG} deg))); slope-only proxy, "
                         f"not a flow-accumulation TWI",
            "invalid_pixels": "missing tile, nodata, elevation <= -100 m, or exactly 0.0 (sea)",
            "region_box": "plain box membership of the cell centre; `both` when in more than one box",
        },
        "paths": {"raw_dir": _relative(raw_dir, root), "cell_terrain": _relative(parquet, root)},
    }
    _atomic_write_json(out_dir / REPORT_NAME, _json_safe(report))
    return report
