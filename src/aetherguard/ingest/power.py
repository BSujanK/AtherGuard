"""NASA POWER (MERRA-2) daily soil wetness: domain slab from the analysis-ready zarr, plus a reader.

The 'utc' store labels days by UTC calendar date (see docs/phase1-design.md D5/D6). Only antecedent wetness
(GWETTOP, GWETROOT) is used; values are fractions in [0, 1]. The zarr is chunked (5844 days, 15 lat, 15 lon), so
a slab read fetches whole-time-range chunks: reading all days of the domain costs only a handful of requests.
"""
from __future__ import annotations

import json
import os
import time
from datetime import date, datetime
from pathlib import Path

import numpy as np

from ..config import load_config
from ..grid import cell_center

FILL_VALUE = -999.0
NPZ_FILE = "power_wetness.npz"
INDEX_FILE = "power_index.json"
LAT_STEP = 0.5  # MERRA-2 grid spacing in degrees
LON_STEP = 0.625


def _atomic_write(path: Path, write) -> None:
    part = path.with_name(path.name + ".part")
    try:
        with part.open("wb") as handle:
            write(handle)
        os.replace(part, path)
    except BaseException:
        part.unlink(missing_ok=True)
        raise


def _open_store(zarr_url: str):
    import xarray as xr

    return xr.open_zarr(zarr_url, storage_options={"anon": True}, consolidated=True)


def _clean(values: np.ndarray) -> tuple[np.ndarray, dict]:
    """float32 copy with the fill value, non-finite and out-of-[0, 1] values replaced by NaN, and counts."""
    out = np.asarray(values, dtype=np.float32).copy()
    is_fill = out == FILL_VALUE
    with np.errstate(invalid="ignore"):
        out_of_range = np.isfinite(out) & ~is_fill & ((out < 0.0) | (out > 1.0))
    counts = {"n_fill_value": int(is_fill.sum()), "n_out_of_range": int(out_of_range.sum()),
              "n_nan_in_source": int((~np.isfinite(out)).sum())}
    out[is_fill | out_of_range] = np.nan
    return out, counts


def build_power_wetness(cfg: dict, out_dir, *, dataset=None, period: tuple[str, str] | None = None) -> dict:
    """Save the domain soil-wetness slab to `<out_dir>/power_wetness.npz` and `power_index.json`; return the index.

    `dataset` is an already opened xarray Dataset (dims time/lat/lon); by default the configured zarr is
    opened anonymously. The slab is padded by one MERRA-2 grid step around the bbox so that every 0.05-degree
    cell centre inside the bbox has its nearest MERRA-2 point in the file.
    """
    started = time.monotonic()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    power_cfg = cfg["power"]
    variables = list(power_cfg["variables"])
    if period is None:
        domain_period = load_config("domain")["period"]
        period = (domain_period["start"], domain_period["end"])
    start, end = period
    box = cfg["domain_bbox"]
    ds = dataset if dataset is not None else _open_store(power_cfg["zarr"])
    chunks = {v: list(ds[v].encoding.get("chunks") or []) for v in variables}

    slab = ds[variables].sel(
        time=slice(start, end),
        lat=slice(box["lat_min"] - LAT_STEP, box["lat_max"] + LAT_STEP),
        lon=slice(box["lon_min"] - LON_STEP, box["lon_max"] + LON_STEP)).load()
    if slab.sizes["time"] == 0 or slab.sizes["lat"] == 0 or slab.sizes["lon"] == 0:
        raise ValueError(f"POWER selection is empty: {dict(slab.sizes)}")
    times = slab["time"].values.astype("datetime64[D]")
    if np.any(np.diff(times) != np.timedelta64(1, "D")):
        raise ValueError("POWER days are not consecutive in the selected period")
    dates = np.datetime_as_string(times, unit="D")
    arrays: dict[str, np.ndarray] = {}
    variable_index: dict[str, dict] = {}
    for name in variables:
        if slab[name].dims != ("time", "lat", "lon"):
            raise ValueError(f"{name}: unexpected dims {slab[name].dims}")
        cleaned, counts = _clean(slab[name].values)
        finite = np.isfinite(cleaned)
        arrays[name] = cleaned
        variable_index[name] = {
            **counts,
            "nan_share": float(1.0 - finite.mean()),
            "min": float(cleaned[finite].min()) if finite.any() else None,
            "max": float(cleaned[finite].max()) if finite.any() else None,
            "share_exactly_one": float((cleaned == 1.0).mean()),
            "n_all_nan_days": int((~finite.any(axis=(1, 2))).sum()),
            "chunks_time_lat_lon": chunks[name],
        }
    lat = slab["lat"].values.astype(np.float64)
    lon = slab["lon"].values.astype(np.float64)

    def write(handle):
        np.savez_compressed(handle, **arrays, lat=lat, lon=lon, dates=dates.astype("U10"))

    _atomic_write(out_dir / NPZ_FILE, write)
    index = {
        "source": power_cfg["zarr"], "day_basis": "utc", "units": "fraction 0..1",
        "variables": variable_index,
        "period": {"start": str(dates[0]), "end": str(dates[-1]), "n_days": int(len(dates))},
        "grid": {"n_lat": len(lat), "n_lon": len(lon), "lat_min": float(lat[0]), "lat_max": float(lat[-1]),
                 "lon_min": float(lon[0]), "lon_max": float(lon[-1]), "lat_step": LAT_STEP, "lon_step": LON_STEP,
                 "bbox": box},
        "elapsed_seconds": round(time.monotonic() - started, 1),
    }
    _atomic_write(out_dir / INDEX_FILE, lambda handle: handle.write((json.dumps(index, indent=1) + "\n").encode()))
    return index


def _as_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


class PowerWetness:
    """Reader for `power_wetness.npz`: daily soil wetness at the MERRA-2 point nearest to a cell centre."""

    def __init__(self, path) -> None:
        with np.load(Path(path)) as data:
            self.lat = data["lat"]
            self.lon = data["lon"]
            self._dates = data["dates"].astype("datetime64[D]")
            self._values = {name: data[name] for name in data.files if name not in ("lat", "lon", "dates")}
        self.variables = sorted(self._values)

    def dates(self) -> list[date]:
        return [date.fromisoformat(str(d)) for d in self._dates]

    def nearest_point(self, cell_id: int) -> tuple[int, int]:
        """Indices (lat, lon) of the stored MERRA-2 point nearest to the cell centre.

        Ties (a centre exactly half-way between two points; they cannot occur for centres on the 0.05-degree
        lattice but are resolved anyway) go to the lower index, i.e. the southern / western point.
        """
        lat_c, lon_c = cell_center(int(cell_id))
        i = int(np.argmin(np.round(np.abs(self.lat - lat_c), 9)))
        j = int(np.argmin(np.round(np.abs(self.lon - lon_c), 9)))
        if abs(self.lat[i] - lat_c) > LAT_STEP / 2 + 1e-9 or abs(self.lon[j] - lon_c) > LON_STEP / 2 + 1e-9:
            raise ValueError(f"cell {cell_id} is outside the stored POWER grid")
        return i, j

    def cell_series(self, cell_id: int, start, end, variable: str) -> np.ndarray:
        """float32 wetness for start..end inclusive (UTC days); NaN for days outside the store or missing."""
        if variable not in self._values:
            raise KeyError(f"unknown variable {variable!r}; available: {self.variables}")
        first, last = np.datetime64(_as_date(start), "D"), np.datetime64(_as_date(end), "D")
        if last < first:
            raise ValueError("end is before start")
        wanted = np.arange(first, last + np.timedelta64(1, "D"), dtype="datetime64[D]")
        i, j = self.nearest_point(cell_id)
        out = np.full(len(wanted), np.nan, dtype=np.float32)
        pos = np.searchsorted(self._dates, wanted)
        inside = pos < len(self._dates)
        hit = np.zeros(len(wanted), dtype=bool)
        hit[inside] = self._dates[pos[inside]] == wanted[inside]
        out[hit] = self._values[variable][pos[hit], i, j]
        return out
