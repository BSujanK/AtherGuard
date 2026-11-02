"""Tiny synthetic IMD / CHIRPS / POWER stores in the on-disk formats of the ingest modules, plus a terrain table."""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from aetherguard.grid import ID_STRIDE, cell_center
from aetherguard.ingest.imd import N_LAT, N_LON, days_in_year

# Block of 20 x 20 cells at lat 11.5..12.5, lon 81.5..82.5 (India-like latitudes, all inside the IMD grid).
BLOCK = (2030, 5230)
SIDE = 20
IMD_YEARS = (2010, 2011)
CHIRPS_FULL_YEARS = (2010, 2011)
CHIRPS_RANGE_2013 = ("2013-06-01", "2013-08-15")
CHIRPS_MISSING = "2011-03-10"
IMD_MISSING_DAY = "2010-07-05"
CHIRPS_ROW_OFF, CHIRPS_COL_OFF, CHIRPS_ROWS, CHIRPS_COLS = 740, 5220, 40, 40
POWER_LAT = np.arange(11.0, 13.01, 0.5)
POWER_LON = np.array([81.25, 81.875, 82.5, 83.125])
POWER_START, POWER_END = "2009-12-20", "2011-12-31"
POWER_OCEAN_POINT = (1, 1)  # (lat index, lon index): GWETROOT NaN, GWETTOP 1.0


def cid(lat_index: int, lon_index: int) -> int:
    return lat_index * ID_STRIDE + lon_index


def block_cell(i: int, j: int) -> int:
    return cid(BLOCK[0] + i, BLOCK[1] + j)


def block_cells() -> list[int]:
    return [block_cell(i, j) for i in range(SIDE) for j in range(SIDE)]


def day_number(value) -> int:
    return int(np.datetime64(value, "D").astype(np.int64))


def imd_value(year: int, k: np.ndarray, i: np.ndarray, j: np.ndarray) -> np.ndarray:
    return (((k[:, None, None] + 1) * 7 + i[None, :, None] * 3 + j[None, None, :] + year) % 13 * 1.5).astype(np.float32)


def imd_point_of_block(i: int, j: int) -> tuple[int, int]:
    lat, lon = cell_center(block_cell(i, j))
    return int(np.floor(round((lat - 6.5) / 0.25, 6) + 0.5)), int(np.floor(round((lon - 66.5) / 0.25, 6) + 0.5))


UNCOVERED_IMD_POINT = imd_point_of_block(10, 10)       # all-NaN IMD point (Nepal-like)
GAPPED_IMD_POINT = imd_point_of_block(3, 3)            # one missing day


def write_imd(root: Path, years=IMD_YEARS, perturb=None) -> Path:
    """`imd_<year>.npy` + `imd_index.json`. `perturb(year, array)` may edit an array in place before saving."""
    root.mkdir(parents=True, exist_ok=True)
    index_years = {}
    for year in years:
        n = days_in_year(year)
        array = imd_value(year, np.arange(n), np.arange(N_LAT), np.arange(N_LON))
        array[:, UNCOVERED_IMD_POINT[0], UNCOVERED_IMD_POINT[1]] = np.nan
        doy = (date.fromisoformat(IMD_MISSING_DAY) - date(year, 1, 1)).days
        if year == int(IMD_MISSING_DAY[:4]):
            array[doy, GAPPED_IMD_POINT[0], GAPPED_IMD_POINT[1]] = np.nan
        if perturb is not None:
            perturb(year, array)
        np.save(root / f"imd_{year}.npy", array)
        index_years[str(year)] = {"file": f"imd_{year}.npy", "shape": list(array.shape), "nan_share": 0.0}
    index = {"coverage_mask": "imd_coverage_mask.npy", "covered_cells": 0, "years": index_years}
    (root / "imd_index.json").write_text(json.dumps(index), encoding="utf-8")
    return root


def chirps_value(day_numbers: np.ndarray, r: np.ndarray, c: np.ndarray) -> np.ndarray:
    return ((day_numbers[:, None, None] * 5 + r[None, :, None] * 2 + c[None, None, :]) % 11 * 2.0).astype(np.float16)


def _year_days(year: int) -> list[date]:
    if year == 2013:
        start, end = (date.fromisoformat(v) for v in CHIRPS_RANGE_2013)
    else:
        start, end = date(year, 1, 1), date(year, 12, 31)
    return [start + timedelta(d) for d in range((end - start).days + 1)]


def write_chirps(root: Path, perturb=None) -> Path:
    """`chirps_<year>.npy`, `chirps_<year>_dates.json`, `chirps_index.json`; 2012 is absent, one day is missing."""
    root.mkdir(parents=True, exist_ok=True)
    years = (*CHIRPS_FULL_YEARS, 2013)
    per_year, missing = {}, [CHIRPS_MISSING]
    for year in years:
        days = _year_days(year)
        numbers = np.array([day_number(d.isoformat()) for d in days])
        array = chirps_value(numbers, np.arange(CHIRPS_ROWS), np.arange(CHIRPS_COLS))
        for k, d in enumerate(days):
            if d.isoformat() == CHIRPS_MISSING:
                array[k] = np.nan
        if perturb is not None:
            perturb(year, [d.isoformat() for d in days], array)
        np.save(root / f"chirps_{year}.npy", array)
        (root / f"chirps_{year}_dates.json").write_text(json.dumps([d.isoformat() for d in days]), encoding="utf-8")
        per_year[str(year)] = len(days)
    index = {"rows": CHIRPS_ROWS, "cols": CHIRPS_COLS, "row_off": CHIRPS_ROW_OFF, "col_off": CHIRPS_COL_OFF,
             "days_per_year": per_year, "missing_dates": missing, "years": {}}
    (root / "chirps_index.json").write_text(json.dumps(index), encoding="utf-8")
    return root


def power_values(numbers: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    t = numbers[:, None, None]
    i = np.arange(len(POWER_LAT))[None, :, None]
    j = np.arange(len(POWER_LON))[None, None, :]
    top = ((t * 3 + i * 5 + j) % 17 / 20.0).astype(np.float32)
    root = ((t * 7 + i * 2 + j * 3) % 19 / 25.0).astype(np.float32)
    top[:, POWER_OCEAN_POINT[0], POWER_OCEAN_POINT[1]] = 1.0
    root[:, POWER_OCEAN_POINT[0], POWER_OCEAN_POINT[1]] = np.nan
    return top, root


def write_power(path: Path, perturb=None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    days = np.arange(np.datetime64(POWER_START), np.datetime64(POWER_END) + np.timedelta64(1, "D"),
                     dtype="datetime64[D]")
    top, root = power_values(days.astype(np.int64))
    if perturb is not None:
        perturb(days, top, root)
    np.savez_compressed(path, GWETTOP=top, GWETROOT=root, lat=POWER_LAT, lon=POWER_LON, dates=days.astype("U10"))
    return path


def terrain_table() -> pd.DataFrame:
    ids = block_cells()
    lat, lon = cell_center(np.array(ids))
    n = len(ids)
    k = np.arange(n, dtype=float)
    return pd.DataFrame({
        "cell_id": ids, "lat": lat, "lon": lon, "region_box": "himalaya", "elev_mean": 100.0 + k,
        "elev_std": 1.0 + k / 10, "elev_min": 90.0 + k, "elev_max": 110.0 + k, "relief": 20.0 + k / 5,
        "slope_mean": 5.0 + k / 20, "slope_p90": 8.0 + k / 20, "slope_max": 12.0 + k / 20,
        "curvature_mean": k / 1000, "aspect_sin": np.sin(k), "aspect_cos": np.cos(k), "twi_proxy": 3.0 + k / 100,
        "valid_frac": 1.0, "slope_valid_frac": 1.0})


def write_world(root: Path) -> dict[str, Path]:
    root.mkdir(parents=True, exist_ok=True)
    terrain = root / "terrain.parquet"
    terrain_table().to_parquet(terrain, index=False)
    return {"imd": write_imd(root / "imd"), "chirps": write_chirps(root / "chirps"),
            "power": write_power(root / "power_wetness.npz"), "terrain": terrain}
