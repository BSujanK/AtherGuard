"""Static-layer probes (terrain, land cover, soil, roads) and tile arithmetic."""
from __future__ import annotations

import math
from pathlib import Path

import requests

from ..grid import regions
from ..http import DownloadError, download
from .result import ProbeResult, failure_status

_DEM_BASE = "https://copernicus-dem-30m.s3.amazonaws.com"
_WORLDCOVER_BASE = "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map"
_SOILGRIDS_VRT = "/vsicurl/https://files.isric.org/soilgrids/latest/data/clay/clay_0-5cm_mean.vrt"
_GEOFABRIK = {"india": "https://download.geofabrik.de/asia/india-latest.osm.pbf",
              "nepal": "https://download.geofabrik.de/asia/nepal-latest.osm.pbf"}


def _hemispheres(lat_index: int, lon_index: int) -> tuple[str, str]:
    return ("N" if lat_index >= 0 else "S"), ("E" if lon_index >= 0 else "W")


def dem_tile_name(lat: float, lon: float) -> str:
    la, lo = int(math.floor(lat)), int(math.floor(lon))
    ns, ew = _hemispheres(la, lo)
    return f"Copernicus_DSM_COG_10_{ns}{abs(la):02d}_00_{ew}{abs(lo):03d}_00_DEM"


def dem_tile_url(lat: float, lon: float) -> str:
    name = dem_tile_name(lat, lon)
    return f"{_DEM_BASE}/{name}/{name}.tif"


def worldcover_tile_name(lat: float, lon: float) -> str:
    la, lo = int(math.floor(lat / 3) * 3), int(math.floor(lon / 3) * 3)
    ns, ew = _hemispheres(la, lo)
    return f"ESA_WorldCover_10m_2021_v200_{ns}{abs(la):02d}{ew}{abs(lo):03d}_Map.tif"


def tiles_needed(box: dict, tile_deg: float) -> int:
    n_lat = math.ceil(box["lat_max"] / tile_deg) - math.floor(box["lat_min"] / tile_deg)
    n_lon = math.ceil(box["lon_max"] / tile_deg) - math.floor(box["lon_min"] / tile_deg)
    return n_lat * n_lon


def domain_tile_count(tile_deg: float) -> int:
    return sum(tiles_needed(box, tile_deg) for box in regions().values())


def _content_length(response) -> int | None:
    """Parsed Content-Length, or None when absent, non-numeric or non-positive (size unknown)."""
    try:
        value = int(response.headers.get("Content-Length"))
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def probe_dem(lat, lon, data_root, manifest) -> ProbeResult:
    try:
        import rasterio
        import rasterio.errors
    except ImportError as exc:
        return ProbeResult("dem", "inconclusive", f"rasterio unavailable: {exc}")
    dest = Path(data_root) / "raw" / "audit" / "dem" / f"{dem_tile_name(lat, lon)}.tif"
    try:
        download(dem_tile_url(lat, lon), dest, manifest, "Copernicus DEM GLO-30",
                 "Copernicus DEM licence (free, attribution; verify in review)")
    except DownloadError as exc:
        return ProbeResult("dem", failure_status([exc]), f"DEM tile download failed: {exc}")
    try:
        with rasterio.open(dest) as ds:
            row, col = ds.index(lon, lat)
            elevation = float(ds.read(1, window=((row, row + 1), (col, col + 1)))[0, 0])
            shape, res = tuple(ds.shape), tuple(round(r, 6) for r in ds.res)
    except (rasterio.errors.RasterioIOError, IndexError, ValueError) as exc:
        return ProbeResult("dem", "fail",
                           f"DEM tile {dest.name} unreadable or does not cover the point: "
                           f"{type(exc).__name__}: {exc}", {"tile": dest.name})
    tiles = domain_tile_count(1.0)
    evidence = {"shape": shape, "res_deg": res, "elevation_m_at_point": elevation,
                "tiles_for_domain": tiles,
                "est_total_gb": round(dest.stat().st_size * tiles / 1e9, 1)}
    plausible = -100.0 < elevation < 9000.0
    return ProbeResult("dem", "ok" if plausible else "fail",
                       f"tile {dest.name}: elevation at point {elevation:.0f} m; "
                       f"~{evidence['est_total_gb']} GB for the domain", evidence)


def probe_worldcover(lat, lon) -> ProbeResult:
    url = f"{_WORLDCOVER_BASE}/{worldcover_tile_name(lat, lon)}"
    try:
        response = requests.head(url, allow_redirects=True, timeout=60)
    except requests.RequestException as exc:
        return ProbeResult("worldcover", "unreachable", f"{type(exc).__name__}: {exc}")
    if response.status_code != 200:
        return ProbeResult("worldcover", "fail", f"HTTP {response.status_code} for {url}")
    size = _content_length(response)
    tiles = domain_tile_count(3.0)
    if size is None:
        evidence = {"tile_bytes": None, "tiles_for_domain": tiles, "est_total_gb": None}
        return ProbeResult("worldcover", "partial",
                           "tile reachable but size unknown (no valid Content-Length); "
                           "domain download size cannot be estimated", evidence)
    evidence = {"tile_bytes": size, "tiles_for_domain": tiles, "est_total_gb": round(size * tiles / 1e9, 1)}
    return ProbeResult("worldcover", "ok", f"tile reachable; ~{evidence['est_total_gb']} GB for the domain", evidence)


def probe_soilgrids(lat, lon) -> ProbeResult:
    try:
        import rasterio
        from pyproj import Transformer
    except ImportError as exc:
        return ProbeResult("soilgrids", "inconclusive", f"library unavailable: {exc}")
    try:
        with rasterio.Env(GDAL_HTTP_TIMEOUT="60", GDAL_HTTP_MAX_RETRY="3",
                          GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
            with rasterio.open(_SOILGRIDS_VRT) as ds:
                x, y = Transformer.from_crs("EPSG:4326", ds.crs, always_xy=True).transform(lon, lat)
                row, col = ds.index(x, y)
                value = float(ds.read(1, window=((row, row + 1), (col, col + 1)))[0, 0])
                evidence = {"crs": ds.crs.to_string()[:80], "nodata": ds.nodata, "value_at_point": value}
    except rasterio.errors.RasterioIOError as exc:
        return ProbeResult("soilgrids", "unreachable", f"GDAL could not read the remote VRT: {exc}")
    except Exception as exc:
        return ProbeResult("soilgrids", "inconclusive", f"{type(exc).__name__}: {exc}")
    ok = evidence["nodata"] is None or value != evidence["nodata"]
    return ProbeResult("soilgrids", "ok" if ok else "partial",
                       f"clay 0-5 cm at point = {value} (nodata={evidence['nodata']})", evidence)


def probe_osm_roads() -> ProbeResult:
    sizes: dict[str, int | None] = {}   # reachable regions only; None = size unknown
    errors: list[str] = []
    retriable: list[bool] = []          # per failed region: connection error / 429 / 5xx
    parts: list[str] = []
    excluded: list[str] = []
    for region, url in _GEOFABRIK.items():
        try:
            response = requests.head(url, allow_redirects=True, timeout=60)
        except requests.RequestException as exc:
            errors.append(f"{region}: {type(exc).__name__}: {exc}")
            retriable.append(True)
            parts.append(f"{region} failed: {type(exc).__name__}")
            excluded.append(region)
            continue
        if response.status_code != 200:
            errors.append(f"{region}: HTTP {response.status_code}")
            retriable.append(response.status_code == 429 or response.status_code >= 500)
            parts.append(f"{region} failed: HTTP {response.status_code}")
            excluded.append(region)
            continue
        size = _content_length(response)
        sizes[region] = size
        if size is None:
            errors.append(f"{region}: Content-Length missing or invalid (size unknown)")
            parts.append(f"{region} reachable (size unknown)")
            excluded.append(region)
        else:
            parts.append(f"{region} reachable ({size / 1e9:.2f} GB)")
    evidence = {"pbf_bytes": sizes, "errors": errors,
                "note": "Reading .pbf files needs an extra dependency (e.g. pyosmium); decide in Phase 1."}
    if not sizes:
        status = "unreachable" if any(retriable) else "fail"
        return ProbeResult("osm_roads", status,
                           "no Geofabrik extract reachable: " + "; ".join(parts), evidence)
    known = [v for v in sizes.values() if v is not None]
    if not errors:
        total_gb = round(sum(known) / 1e9, 2)
        return ProbeResult("osm_roads", "ok", f"Geofabrik extracts reachable, {total_gb} GB combined", evidence)
    combined = f"combined size {sum(known) / 1e9:.2f} GB" if known else "combined size unknown"
    return ProbeResult("osm_roads", "partial",
                       "; ".join(parts) + f"; {combined} excludes {', '.join(excluded)}", evidence)
