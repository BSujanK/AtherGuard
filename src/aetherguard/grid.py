"""0.05-degree global grid anchored on the CHIRPS pixel grid, plus domain regions."""
from __future__ import annotations

import numpy as np

from .config import load_config

CELL_DEG = 0.05
ID_STRIDE = 10_000  # cell_id = lat_index * ID_STRIDE + lon_index
LAT_ROWS = 3600
LON_COLS = 7200


def _axis_index(values, origin: float) -> np.ndarray:
    # Round before flooring so a coordinate sitting exactly on a cell edge
    # (e.g. 11.55 = -90 + 2031 * 0.05) cannot fall into the wrong cell through
    # binary floating-point error. Coordinates within ~2.5e-8 degrees (5e-7 cells)
    # below an edge snap up; callers clip the result so the last cell stays in-grid.
    scaled = (np.asarray(values, dtype=float) - origin) / CELL_DEG
    return np.floor(np.round(scaled, 6)).astype(np.int64)


def latlon_to_cell(lat, lon):
    lat_a = np.asarray(lat, dtype=float)
    lon_a = np.asarray(lon, dtype=float)
    if not (np.all(np.isfinite(lat_a)) and np.all(np.isfinite(lon_a))):
        raise ValueError("latitude and longitude must be finite (missing data is not allowed)")
    if (
        np.any(lat_a < -90.0) or np.any(lat_a >= 90.0)
        or np.any(lon_a < -180.0) or np.any(lon_a >= 180.0)
    ):
        raise ValueError("latitude must be in [-90, 90) and longitude in [-180, 180)")
    lat_idx = np.minimum(_axis_index(lat_a, -90.0), LAT_ROWS - 1)
    lon_idx = np.minimum(_axis_index(lon_a, -180.0), LON_COLS - 1)
    ids = lat_idx * ID_STRIDE + lon_idx
    return int(ids) if ids.ndim == 0 else ids


def cell_center(cell_id):
    ids = np.asarray(cell_id, dtype=np.int64)
    lat = -90.0 + (ids // ID_STRIDE + 0.5) * CELL_DEG
    lon = -180.0 + (ids % ID_STRIDE + 0.5) * CELL_DEG
    if ids.ndim == 0:
        return float(lat), float(lon)
    return lat, lon


def neighbours(cell_id: int) -> list[int]:
    """The (up to) 8 surrounding cells; longitude wraps, latitude does not."""
    ilat, ilon = divmod(int(cell_id), ID_STRIDE)
    out: list[int] = []
    for dlat in (-1, 0, 1):
        for dlon in (-1, 0, 1):
            if dlat == 0 and dlon == 0:
                continue
            nlat = ilat + dlat
            if not 0 <= nlat < LAT_ROWS:
                continue
            out.append(nlat * ID_STRIDE + (ilon + dlon) % LON_COLS)
    return out


def regions() -> dict[str, dict[str, float]]:
    return load_config("domain")["regions"]


def region_labels(lat, lon) -> np.ndarray:
    """Region name per point, or '' when the point is outside every region box."""
    lat_a = np.atleast_1d(np.asarray(lat, dtype=float))
    lon_a = np.atleast_1d(np.asarray(lon, dtype=float))
    labels = np.full(lat_a.shape, "", dtype=object)
    for name, box in regions().items():
        inside = (
            (lat_a >= box["lat_min"]) & (lat_a < box["lat_max"])
            & (lon_a >= box["lon_min"]) & (lon_a < box["lon_max"])
        )
        labels[inside] = name
    return labels


def region_of(lat: float, lon: float) -> str:
    return str(region_labels(lat, lon)[0])


def domain_cell_counts(cell_deg: float) -> dict[str, int]:
    counts: dict[str, int] = {}
    for name, box in regions().items():
        n_lat = round((box["lat_max"] - box["lat_min"]) / cell_deg)
        n_lon = round((box["lon_max"] - box["lon_min"]) / cell_deg)
        counts[name] = n_lat * n_lon
    counts["total"] = sum(counts.values())
    return counts
