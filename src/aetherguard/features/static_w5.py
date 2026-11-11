"""W5 static susceptibility table (docs/superpowers/specs/2026-11-10-aetherguard-w5-static-susceptibility.md section 2).

    python -m aetherguard.features.static_w5 [--sources landcover,roads,soil,steep]

One row per 0.05-degree cell of `cell_terrain.parquet`, eleven columns from four open sources. Each source is reduced
to its own part file under data/processed/features/static_w5/ (so a source can be rebuilt alone, and a network failure
costs one source), then the parts are joined into `cell_static.parquet` with a report. A cell a source does not cover
has NaN for that source's columns; nothing is ever filled with zero.

Sources
  landcover  ESA WorldCover 2021 v200 (CC BY 4.0), 3-degree tiles read at one pixel in eight (about 80 m) from the
             tiles' own overviews; the decimated tiles are cached under data/raw/static_w5/worldcover/.
  roads      GRIP4 total road density, 5 arcmin (CC0): the pixel holding the cell centre.
  soil       ISRIC SoilGrids 2.0 1 km aggregates, 15-30 cm (CC BY 4.0), resampled to a 0.01-degree grid per region box.
  steep      Copernicus DEM GLO-90 tiles already on disk: share of slope-valid pixels at or above 25 and 35 degrees.
"""
from __future__ import annotations

import argparse
import functools
import json
import math
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import PROJECT_ROOT, data_dir, data_root
from ..grid import ID_STRIDE, _axis_index, cell_center
from ..http import download
from ..manifest import Manifest

LC_CLASSES: dict[str, tuple[int, ...]] = {
    "lc_tree": (10,), "lc_shrub_grass": (20, 30), "lc_crop": (40,), "lc_built": (50,), "lc_bare": (60, 70),
}
LC_IGNORED = (0, 80, 90)          # no data, permanent water, herbaceous wetland: not ground an alert is about
SOIL_LAYERS = {"soil_clay": "clay", "soil_sand": "sand", "soil_coarse": "cfvo"}
STEEP_DEGREES = {"ter_steep25": 25.0, "ter_steep35": 35.0}
STATIC_COLUMNS = [*LC_CLASSES, "road_density", *SOIL_LAYERS, *STEEP_DEGREES]
SOURCES = {"landcover": list(LC_CLASSES), "roads": ["road_density"], "soil": list(SOIL_LAYERS), "steep": list(STEEP_DEGREES)}

WORLDCOVER_URL = "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_{tile}_Map.tif"
WORLDCOVER_DECIMATION = 8
GRIP4_URL = "https://dataportaal.pbl.nl/downloads/GRIP4/GRIP4_density_total.zip"
SOILGRIDS_URL = "https://files.isric.org/soilgrids/latest/data_aggregated/1000m/{name}/{name}_15-30cm_mean_1000.tif"
SOIL_GRID_DEG = 0.01
LICENCES = {"landcover": "ESA WorldCover 2021 v200, CC BY 4.0", "roads": "GRIP4 (Meijer et al. 2018), CC0",
            "soil": "ISRIC SoilGrids 2.0, CC BY 4.0", "steep": "Copernicus DEM GLO-90, free and open (ESA/Airbus)"}
MANIFEST_PATH = PROJECT_ROOT / "manifests" / "data_manifest.jsonl"
GROUP = "static_w5"               # the feature group these columns belong to in a model's column map
# Roads and built-up land mark where a slide gets reported, not where the ground fails (W5 spec amendment 2026-11-11).
EXPOSURE_COLUMNS = ("road_density", "lc_built")
HAZARD_COLUMNS = [c for c in STATIC_COLUMNS if c not in EXPOSURE_COLUMNS]


def table_path() -> Path:
    return data_root() / "processed" / "features" / "static_w5" / "cell_static.parquet"


def static_table(path: Path | None = None) -> pd.DataFrame:
    path = path or table_path()
    if not path.is_file():
        raise FileNotFoundError(f"{path} not found; build it first (python -m aetherguard.features.static_w5)")
    table = pd.read_parquet(path)
    if list(table.columns) != ["cell_id", *STATIC_COLUMNS] or table["cell_id"].duplicated().any():
        raise ValueError(f"{path.name} is not the W5 static table (one row per cell, the eleven declared columns)")
    return table


def join_static(frame: pd.DataFrame, static: pd.DataFrame) -> pd.DataFrame:
    """`frame` with the static columns of each row's terrain cell (`terrain_cell_id`, else `cell_id`); a cell the table
    does not hold gets NaN. Row order and count are unchanged."""
    clash = sorted(set(STATIC_COLUMNS) & set(frame.columns))
    if clash:
        raise ValueError(f"the frame already has the static columns {clash}")
    key = frame["cell_id"].to_numpy(dtype=np.float64)
    if "terrain_cell_id" in frame.columns:
        terrain = frame["terrain_cell_id"].astype("Float64").to_numpy(dtype=np.float64, na_value=np.nan)
        key = np.where(np.isfinite(terrain), terrain, key)
    picked = static.set_index("cell_id").reindex(key.astype(np.int64))[STATIC_COLUMNS]
    return pd.concat([frame.reset_index(drop=True), picked.reset_index(drop=True)], axis=1)


# ------------------------------------------------------------------------------------- raster to cells

def cell_positions(transform, height: int, width: int, cells: np.ndarray) -> np.ndarray:
    """For a north-up latitude/longitude raster: the index in sorted `cells` of the cell holding each pixel centre,
    -1 where that cell is not listed. Shape (height, width), int32."""
    if transform.b != 0 or transform.d != 0:
        raise ValueError("only north-up rasters are supported")
    lat_idx = _axis_index(transform.f + (np.arange(height) + 0.5) * transform.e, -90.0)
    lon_idx = _axis_index(transform.c + (np.arange(width) + 0.5) * transform.a, -180.0)
    ids = lat_idx[:, None] * ID_STRIDE + lon_idx[None, :]
    found = np.searchsorted(cells, ids)
    found[found == len(cells)] = 0
    return np.where(cells[found] == ids, found, -1).astype(np.int32)


def new_class_counts(n_cells: int) -> tuple[dict[str, np.ndarray], np.ndarray]:
    return {name: np.zeros(n_cells, dtype=np.int64) for name in LC_CLASSES}, np.zeros(n_cells, dtype=np.int64)


def add_classes(values: np.ndarray, positions: np.ndarray, counts: dict[str, np.ndarray], denom: np.ndarray) -> None:
    """Add one tile's land-cover pixels to the per-cell class counts and to the denominator (in place)."""
    group = np.full(256, len(LC_CLASSES), dtype=np.uint8)            # in the denominator, in no class
    group[list(LC_IGNORED)] = 255
    for k, codes in enumerate(LC_CLASSES.values()):
        group[list(codes)] = k
    pixel_group = group[values]
    used = (positions >= 0) & (pixel_group != 255)
    n = len(denom)
    denom += np.bincount(positions[used], minlength=n)
    for k, name in enumerate(LC_CLASSES):
        counts[name] += np.bincount(positions[used & (pixel_group == k)], minlength=n)


def class_shares(counts: dict[str, np.ndarray], denom: np.ndarray) -> dict[str, np.ndarray]:
    return {name: np.divide(count, denom, out=np.full(len(denom), np.nan), where=denom > 0) for name, count in counts.items()}


def add_means(values: np.ndarray, positions: np.ndarray, total: np.ndarray, count: np.ndarray) -> None:
    """Add one raster's finite pixels to the per-cell sums and counts (in place)."""
    used = (positions >= 0) & np.isfinite(values)
    total += np.bincount(positions[used], weights=values[used], minlength=len(total))
    count += np.bincount(positions[used], minlength=len(count))


def cell_means(total: np.ndarray, count: np.ndarray) -> np.ndarray:
    return np.divide(total, count, out=np.full(len(total), np.nan), where=count > 0)


def sample_at_centres(values: np.ndarray, transform, lat: np.ndarray, lon: np.ndarray, nodata=None) -> np.ndarray:
    """The value of the pixel holding each (lat, lon); NaN outside the raster and where the pixel is `nodata`."""
    col = np.floor((np.asarray(lon) - transform.c) / transform.a).astype(np.int64)
    row = np.floor((np.asarray(lat) - transform.f) / transform.e).astype(np.int64)
    inside = (row >= 0) & (row < values.shape[0]) & (col >= 0) & (col < values.shape[1])
    out = np.full(len(row), np.nan)
    picked = values[row[inside], col[inside]].astype(np.float64)
    if nodata is not None:
        picked[picked == nodata] = np.nan
    out[inside] = picked
    return out


def steep_shares(slope: np.ndarray) -> dict[str, np.ndarray]:
    """`slope` is (cells, pixels) in degrees with NaN for invalid pixels: the share of valid pixels at or above each
    threshold, NaN for a cell without a valid pixel."""
    valid = np.isfinite(slope).sum(axis=1)
    with np.errstate(invalid="ignore"):
        return {name: np.divide((slope >= degrees).sum(axis=1), valid, out=np.full(len(valid), np.nan), where=valid > 0)
                for name, degrees in STEEP_DEGREES.items()}


def assemble(cells: pd.DataFrame, parts: dict[str, dict[str, np.ndarray]]) -> pd.DataFrame:
    """`cell_id` plus every declared column in the declared order; a source that is not in `parts` is all NaN."""
    table = pd.DataFrame({"cell_id": cells["cell_id"].to_numpy()})
    have = {name: values for columns in parts.values() for name, values in columns.items()}
    for name in STATIC_COLUMNS:
        table[name] = np.asarray(have[name], dtype=np.float64) if name in have else np.nan
    return table


# --------------------------------------------------------------------------------------------- sources

def worldcover_tile(lat: float, lon: float) -> str:
    south, west = math.floor(lat / 3.0) * 3, math.floor(lon / 3.0) * 3
    return f"{'N' if south >= 0 else 'S'}{abs(south):02d}{'E' if west >= 0 else 'W'}{abs(west):03d}"


def worldcover_tiles(lat: np.ndarray, lon: np.ndarray) -> list[str]:
    corners = np.unique(np.stack([np.floor(np.asarray(lat) / 3.0), np.floor(np.asarray(lon) / 3.0)], axis=1), axis=0)
    return sorted({worldcover_tile(a * 3.0, b * 3.0) for a, b in corners})


def _remote_env():
    import rasterio
    return rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif",
                        GDAL_HTTP_MAX_RETRY="5", GDAL_HTTP_RETRY_DELAY="3", VSI_CACHE="TRUE")


def read_worldcover(tile: str, cache: Path, say=print, manifest: Manifest | None = None):
    """The tile at one pixel in eight as (values uint8, transform), or None where WorldCover has no tile (open sea).
    Cached as an .npz (recorded in `manifest`) next to an `.absent` marker for missing tiles. Only HTTP 404 means
    there is no tile: any other refusal (403 from a proxy or a Wi-Fi login page) is an error, never a silent gap."""
    import rasterio
    import requests
    from affine import Affine
    from rasterio.enums import Resampling
    cached, absent = cache / f"{tile}_d{WORLDCOVER_DECIMATION}.npz", cache / f"{tile}.absent"
    if absent.exists():
        return None
    if not cached.exists():
        url = WORLDCOVER_URL.format(tile=tile)
        status = requests.head(url, timeout=60).status_code
        if status == 404:
            absent.touch()
            return None
        if status != 200:
            raise RuntimeError(f"WorldCover {tile}: HTTP {status}")
        with _remote_env(), rasterio.open(url) as ds:
            shape = (ds.height // WORLDCOVER_DECIMATION, ds.width // WORLDCOVER_DECIMATION)
            values = ds.read(1, out_shape=shape, resampling=Resampling.nearest)
            transform = ds.transform @ Affine.scale(ds.width / shape[1], ds.height / shape[0])
        part = cached.with_name(cached.name + ".part")
        with part.open("wb") as handle:
            np.savez_compressed(handle, values=values, transform=np.array(transform[:6]))
        part.replace(cached)
        say(f"worldcover {tile}: {values.shape[0]}x{values.shape[1]} pixels cached")
    if manifest is not None and not manifest.is_current(cached):
        manifest.add(cached, f"ESA WorldCover 2021 v200 tile {tile}, one pixel in {WORLDCOVER_DECIMATION}",
                     WORLDCOVER_URL.format(tile=tile), LICENCES["landcover"])
    with np.load(cached) as data:
        return data["values"], Affine(*data["transform"])


def landcover(cells: pd.DataFrame, say=print, manifest: Manifest | None = None) -> dict[str, np.ndarray]:
    cache = data_dir("raw", "static_w5", "worldcover")
    ids = cells["cell_id"].to_numpy()
    counts, denom = new_class_counts(len(ids))
    tiles = worldcover_tiles(cells["lat"].to_numpy(), cells["lon"].to_numpy())
    for number, tile in enumerate(tiles, start=1):
        loaded = read_worldcover(tile, cache, say, manifest)
        if loaded is None:
            continue
        values, transform = loaded
        add_classes(values, cell_positions(transform, *values.shape, ids), counts, denom)
        say(f"landcover: tile {number}/{len(tiles)} {tile}")
    return class_shares(counts, denom)


def grip4_member(names: list[str]) -> str:
    """The road-density grid of the GRIP4 zip. The zip also holds a land-area grid (`grip4_area_land_km2.asc`, which
    is 85.7 km2 times the cosine of the latitude): taking that one would feed the model latitude under the name of roads."""
    found = [name for name in names if name.lower().endswith(".asc") and "dens" in name.lower()]
    if len(found) != 1:
        raise ValueError(f"expected exactly one density grid in the GRIP4 zip, found {found} among {names}")
    return found[0]


def roads(cells: pd.DataFrame, say=print, manifest: Manifest | None = None) -> dict[str, np.ndarray]:
    import rasterio
    manifest = manifest if manifest is not None else Manifest(MANIFEST_PATH, data_root())
    path = download(GRIP4_URL, data_dir("raw", "static_w5") / "GRIP4_density_total.zip", manifest,
                    "GRIP4 total road density, 5 arcmin", LICENCES["roads"])
    with zipfile.ZipFile(path) as archive:
        member = grip4_member(archive.namelist())
    with rasterio.open(f"zip://{path.as_posix()}!{member}") as ds:
        values, transform, nodata = ds.read(1), ds.transform, ds.nodata
    say(f"roads: {member} {values.shape[0]}x{values.shape[1]}")
    return {"road_density": sample_at_centres(values, transform, cells["lat"].to_numpy(), cells["lon"].to_numpy(), nodata)}


def soil(cells: pd.DataFrame, say=print, manifest: Manifest | None = None) -> dict[str, np.ndarray]:
    import rasterio
    from affine import Affine
    from rasterio.enums import Resampling
    from rasterio.warp import reproject
    ids = cells["cell_id"].to_numpy()
    out = {}
    for column, name in SOIL_LAYERS.items():
        total, count = np.zeros(len(ids)), np.zeros(len(ids))
        with _remote_env(), rasterio.open(SOILGRIDS_URL.format(name=name)) as src:
            for box, group in cells.groupby("region_box", sort=True):
                south, north = group["lat"].min() - 0.025, group["lat"].max() + 0.025
                west, east = group["lon"].min() - 0.025, group["lon"].max() + 0.025
                shape = (round((north - south) / SOIL_GRID_DEG), round((east - west) / SOIL_GRID_DEG))
                transform = Affine(SOIL_GRID_DEG, 0, west, 0, -SOIL_GRID_DEG, north)
                grid = np.full(shape, np.nan, dtype=np.float32)
                reproject(rasterio.band(src, 1), grid, dst_transform=transform, dst_crs="EPSG:4326",
                          src_nodata=src.nodata, dst_nodata=np.nan, resampling=Resampling.nearest)
                add_means(grid / 10.0, cell_positions(transform, *shape, ids), total, count)   # g/kg, cm3/dm3 -> percent
                say(f"soil: {name} {box} {shape[0]}x{shape[1]}")
        out[column] = cell_means(total, count)
    return out


def steep(cells: pd.DataFrame, say=print, manifest: Manifest | None = None) -> dict[str, np.ndarray]:
    from ..ingest import terrain as tr
    raw_dir = data_root() / "raw" / "terrain" / "glo90"
    absent = tr.read_absent(raw_dir)
    frame = pd.DataFrame({"cell_id": cells["cell_id"].to_numpy()})
    frame["lat_idx"], frame["lon_idx"] = frame["cell_id"] // ID_STRIDE, frame["cell_id"] % ID_STRIDE
    frame["block"] = (frame["lat_idx"] // tr.CELLS_PER_TILE) * 100_000 + frame["lon_idx"] // tr.CELLS_PER_TILE
    out = {name: np.full(len(frame), np.nan) for name in STEEP_DEGREES}
    blocks = list(frame.groupby("block", sort=True))
    for number, (_, block) in enumerate(blocks, start=1):
        # The same pixels, void rules and slope as the terrain table: one function serves both.
        lat_lo, lat_hi = int(block["lat_idx"].min()), int(block["lat_idx"].max())
        lon_lo, lon_hi = int(block["lon_idx"].min()), int(block["lon_idx"].max())
        n_lat, n_lon = lat_hi - lat_lo + 1, lon_hi - lon_lo + 1
        slope = tr.block_surface(raw_dir, absent, lat_lo, lat_hi, lon_lo, lon_hi)["surface"]["slope_deg"]
        pick = ((block["lat_idx"] - lat_lo) * n_lon + (block["lon_idx"] - lon_lo)).to_numpy()
        shares = steep_shares(tr._per_cell(slope[1:-1, 1:-1], n_lat, n_lon)[pick])
        for name in STEEP_DEGREES:
            out[name][block.index.to_numpy()] = shares[name]
        if number % 50 == 0 or number == len(blocks):
            say(f"steep: block {number}/{len(blocks)}")
    return out


REDUCERS = {"landcover": landcover, "roads": roads, "soil": soil, "steep": steep}


# ----------------------------------------------------------------------------------------------- build

def write_part(path: Path, frame: pd.DataFrame) -> None:
    """Whole or not at all: a shutdown mid-write must not leave a broken file that counts as built."""
    part = path.with_name(path.name + ".part")
    frame.to_parquet(part, index=False)
    part.replace(path)


def build(sources: list[str] | None = None, say=print) -> Path:
    out_dir = data_dir("processed", "features", "static_w5")
    cells = pd.read_parquet(data_root() / "processed" / "terrain" / "cell_terrain.parquet",
                            columns=["cell_id", "region_box"]).sort_values("cell_id").reset_index(drop=True)
    cells["lat"], cells["lon"] = cell_center(cells["cell_id"].to_numpy())
    manifest = Manifest(MANIFEST_PATH, data_root())
    for source in sources or [name for name in SOURCES if not (out_dir / f"part_{name}.parquet").exists()]:
        columns = REDUCERS[source](cells, say, manifest)
        write_part(out_dir / f"part_{source}.parquet", pd.DataFrame({"cell_id": cells["cell_id"], **columns}))
        say(f"{source}: part written")
    parts = {}
    for source in SOURCES:
        path = out_dir / f"part_{source}.parquet"
        if path.exists():
            part = pd.read_parquet(path)
            if not part["cell_id"].equals(cells["cell_id"]):
                raise RuntimeError(f"{path.name} is not on the current cell list; rebuild it with --sources {source}")
            parts[source] = {name: part[name].to_numpy() for name in SOURCES[source]}
    table = assemble(cells, parts)
    table.to_parquet(out_dir / "cell_static.parquet", index=False)
    absent = sorted(p.stem for p in (data_root() / "raw" / "static_w5" / "worldcover").glob("*.absent"))
    report = {"cells": int(len(table)), "sources_present": sorted(parts), "licences": LICENCES,
              "worldcover_tiles_absent": absent,
              "columns": {name: {"nan": int(table[name].isna().sum()), "min": float(table[name].min()),
                                 "median": float(table[name].median()), "max": float(table[name].max())}
                          for name in STATIC_COLUMNS if table[name].notna().any()}}
    (out_dir / "cell_static_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    say(f"cell_static.parquet: {len(table)} cells, sources {', '.join(sorted(parts)) or 'none'}")
    return out_dir / "cell_static.parquet"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--sources", help="comma-separated sources to (re)build; default: those without a part file")
    args = parser.parse_args(argv)
    sources = [s.strip() for s in args.sources.split(",")] if args.sources else None
    unknown = [s for s in sources or [] if s not in SOURCES]
    if unknown:
        parser.error(f"unknown source(s): {', '.join(unknown)}; choose from {', '.join(SOURCES)}")
    build(sources, say=functools.partial(print, flush=True))     # a log file must show progress while it runs
    return 0


if __name__ == "__main__":
    sys.exit(main())
