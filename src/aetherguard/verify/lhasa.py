"""NASA LHASA v2 daily landslide nowcast as an independent benchmark on the season-panel cells (spec W1).

    python -m aetherguard.verify.lhasa --years 2018-2020 [--out DIR] [--cache DIR] [--workers N]

LHASA v2.0.0 (Global_Landslide_Nowcast, GES DISC, 2015-04-03 to 2021-02-10) gives a landslide probability (0-1) per ~1 km
pixel per day. Access path (measured 2026-11-05): CMR lists the daily granules; the data come from the Hyrax cloud OPeNDAP
DAP4 service, which crops the domain box on the server (about 12 MB a day instead of the 450 MB global file). The file is
`p_landslide` as (time, lat, lon) on a global 1/120 degree lattice (14400 x 43200, latitude descending, pixel edges on the
0.05 degree cell edges, so six pixels per cell side), fill value -9999. Auth: Earthdata login from the user's netrc.

Per day a cell takes the maximum probability of the pixels whose centres fall inside it; NaN when it has no valid pixel.
`build_year` writes `lhasa_<year>.npz` (cell_id, days, prob float32 (cells, days), fetched) plus a JSON sidecar.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import requests

from ..config import PROJECT_ROOT, data_root, load_config
from ..grid import ID_STRIDE, latlon_to_cell
from ..hazard.jsonio import dump_json
from ..http import DownloadError, download, fetch_json
from ..manifest import Manifest

CONCEPT_ID = "C2654319036-GES_DISC"
CMR_URL = "https://cmr.earthdata.nasa.gov/search/granules.json"
CMR_PAGE_SIZE = 2000
OPENDAP_URL = f"https://opendap.earthdata.nasa.gov/collections/{CONCEPT_ID}/granules/Global_Landslide_Nowcast.2.0.0%3A"
VARIABLE = "p_landslide"
FILE_DIMS = ("time", "lat", "lon")
PIXEL = 1 / 120                       # degrees; the global LHASA lattice, latitude 60 -> -60, longitude -180 -> 180
LAT_NORTH, LON_WEST = 60.0, -180.0

SEASON_START, SEASON_END = (6, 1), (12, 31)    # the season panels' window (verify.seasons)
YEARS = (2018, 2019, 2020)                     # archive years overlapping the season panels (archive ends 2021-02-10)
WORKERS = 4                                    # politeness cap for the OPeNDAP server
RETRIES, BACKOFF_S = 3, 2.0
ABORT_AFTER = 10                               # consecutive failed days before a build stops asking (credentials, outage)
FORMAT_ATTEMPTS = 2                            # a file that downloads but does not decode is fetched once more

MANIFEST_PATH = PROJECT_ROOT / "manifests" / "data_manifest.jsonl"
SOURCE = "NASA LHASA v2.0.0 daily global landslide nowcast (Global_Landslide_Nowcast), GES DISC OPeNDAP domain subset"
LICENCE = ("NASA Earth science data, open access (https://www.earthdata.nasa.gov/engage/open-data-services-software/"
           "data-use-policy); cite Stanley, T. A. et al. 2021, Frontiers in Earth Science 9, doi:10.3389/feart.2021.640043")

_GRANULE_DAY = re.compile(r"_(\d{8})\.nc4?$")


class LhasaFormatError(ValueError):
    """A downloaded LHASA file is not the expected domain subset."""


def _index_range(low: float, high: float, origin: float, sign: int) -> tuple[int, int]:
    """First and last pixel index whose centre lies in [low, high] on an axis `origin + sign * PIXEL * (k + 0.5)`."""
    ends = sorted(round(sign * (value - origin) / PIXEL - 0.5, 6) for value in (low, high))
    return math.ceil(ends[0]), math.floor(ends[1])


def _subset_indices() -> tuple[int, int, int, int]:
    box = load_config("live")["domain_bbox"]
    row0, row1 = _index_range(box["lat_min"], box["lat_max"], LAT_NORTH, -1)
    col0, col1 = _index_range(box["lon_min"], box["lon_max"], LON_WEST, 1)
    return row0, row1, col0, col1


ROW0, ROW1, COL0, COL1 = _subset_indices()
CONSTRAINT = (f"dap4.ce=/{VARIABLE}[0][{ROW0}:{ROW1}][{COL0}:{COL1}];/time;/lat[{ROW0}:{ROW1}];/lon[{COL0}:{COL1}]")


def granule_name(day: date) -> str:
    return f"Global_Landslide_Nowcast_v2.0.0_{day:%Y%m%d}.nc4"


def subset_url(day: date) -> str:
    return f"{OPENDAP_URL}{granule_name(day)}.dap.nc4?{CONSTRAINT}"


def season_days(year: int) -> list[date]:
    first, last = date(year, *SEASON_START), date(year, *SEASON_END)
    return [first + timedelta(k) for k in range((last - first).days + 1)]


def available_days(first: date, last: date) -> set[date]:
    """The days in [first, last] for which CMR lists a LHASA v2 granule."""
    params = {"collection_concept_id": CONCEPT_ID, "sort_key": "start_date", "page_size": CMR_PAGE_SIZE,
              "temporal": f"{first.isoformat()}T00:00:00Z,{last.isoformat()}T23:59:59Z"}
    found: set[date] = set()
    page = 1
    while True:
        entries = fetch_json(CMR_URL, params={**params, "page_num": page}, retries=RETRIES,
                             backoff=BACKOFF_S)["feed"]["entry"]
        for entry in entries:
            match = _GRANULE_DAY.search(entry["title"])
            if match:
                day = date.fromisoformat(f"{match[1][:4]}-{match[1][4:6]}-{match[1][6:]}")
                if first <= day <= last:
                    found.add(day)
        if len(entries) < CMR_PAGE_SIZE:
            return found
        page += 1


def fetch_lhasa(day: date, cache: Path, *, manifest: Manifest | None = None,
                session: requests.Session | None = None) -> Path:
    """Download the domain subset of the daily granule into `cache` (atomic, recorded in the manifest, not fetched
    again while the manifest entry is current). Raises DownloadError; its `status` is the HTTP status when there was one."""
    manifest = manifest if manifest is not None else Manifest(MANIFEST_PATH, data_root())
    dest = Path(cache) / granule_name(day).replace(".nc4", ".subset.nc4")
    return download(subset_url(day), dest, manifest, SOURCE, LICENCE, retries=RETRIES, backoff=BACKOFF_S, session=session)


# ------------------------------------------------------------------------------------------ reading one file

def _read(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(lat, lon, probability (lat, lon) float32 with NaN for fill, masked and out-of-range values)."""
    import xarray as xr
    path = Path(path)
    try:
        with xr.open_dataset(path, engine="h5netcdf") as ds:
            if VARIABLE not in ds.data_vars:
                raise LhasaFormatError(f"{path.name}: variable {VARIABLE!r} is missing")
            array = ds[VARIABLE]
            if array.dims != FILE_DIMS or array.shape[0] != 1:
                raise LhasaFormatError(f"{path.name}: unexpected dimensions {array.dims} {array.shape}, "
                                       f"expected {FILE_DIMS} with one time step")
            lat, lon = ds["lat"].values.astype(np.float64), ds["lon"].values.astype(np.float64)
            values = np.asarray(array.values[0], dtype=np.float32)
    except LhasaFormatError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise LhasaFormatError(f"{path.name}: cannot be read as a LHASA subset ({type(exc).__name__})") from exc
    for name, axis in (("lat", lat), ("lon", lon)):
        steps = np.diff(axis)
        if not (np.all(steps > 0) or np.all(steps < 0)):
            raise LhasaFormatError(f"{path.name}: {name} is not strictly monotone")
    values[~np.isfinite(values) | (values < 0) | (values > 1)] = np.nan     # -9999 fill, masked, junk
    return lat, lon, values


def _blocks(index: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Start of every run of equal values in a monotone index array, and the value of each run."""
    starts = np.flatnonzero(np.concatenate(([True], index[1:] != index[:-1])))
    return starts, index[starts]


def _lookup(unique: np.ndarray, wanted: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Position in `unique` (any order) of each wanted index, and whether it is there at all."""
    order = np.argsort(unique)
    sorted_unique = unique[order]
    at = np.minimum(np.searchsorted(sorted_unique, wanted), sorted_unique.size - 1)
    return order[at], sorted_unique[at] == wanted


def cell_max(path: Path, cell_ids: np.ndarray) -> np.ndarray:
    """Maximum LHASA probability over the pixels whose centres fall inside each 0.05 degree cell: float32, one value per
    id in the given order. NaN where the cell has no valid pixel in the file (outside it, or only fill / masked pixels);
    never 0 for missing."""
    ids = np.asarray(cell_ids, dtype=np.int64)
    lat, lon, values = _read(path)
    lat_cell = latlon_to_cell(lat, np.zeros_like(lat)) // ID_STRIDE
    lon_cell = latlon_to_cell(np.zeros_like(lon), lon) % ID_STRIDE
    lat_starts, lat_unique = _blocks(lat_cell)
    lon_starts, lon_unique = _blocks(lon_cell)
    low = np.float32(-np.inf)
    blocks = np.maximum.reduceat(np.where(np.isnan(values), low, values), lat_starts, axis=0)
    blocks = np.maximum.reduceat(blocks, lon_starts, axis=1)
    blocks[blocks == low] = np.nan
    row, row_ok = _lookup(lat_unique, ids // ID_STRIDE)
    col, col_ok = _lookup(lon_unique, ids % ID_STRIDE)
    return np.where(row_ok & col_ok, blocks[row, col], np.float32(np.nan)).astype(np.float32)


# ------------------------------------------------------------------------------------------ one year

class _Sessions:
    """One requests.Session per worker thread (Earthdata cookies are reused), all closed together."""

    def __init__(self) -> None:
        self._local = threading.local()
        self._lock = threading.Lock()
        self._all: list[requests.Session] = []

    def get(self) -> requests.Session:
        session = getattr(self._local, "session", None)
        if session is None:
            session = self._local.session = requests.Session()
            with self._lock:
                self._all.append(session)
        return session

    def close(self) -> None:
        for session in self._all:
            session.close()


def _write_npz(path: Path, **arrays) -> None:
    part = path.with_name(path.name + ".part")
    with part.open("wb") as handle:
        np.savez_compressed(handle, **arrays)
    os.replace(part, path)


def build_year(year: int, cell_ids: np.ndarray, out_dir: Path, cache: Path, say=print, *,
               workers: int = WORKERS, available: set[date] | None = None, fetch=None) -> Path:
    """`lhasa_<year>.npz` for 1 June - 31 December `year`: `cell_id` (as given), `days` (ISO text, every day of the window),
    `prob` float32 (cells, days) and `fetched` (bool per day). A day the archive lacks, or that failed, is an all-NaN
    column and `fetched` is False; the JSON sidecar lists them with the reason. Raw subsets stay in `cache` (manifest-
    checked), so a repeated build only re-reads them. `available` and `fetch(day, cache_dir)` default to CMR and
    `fetch_lhasa`."""
    ids = np.asarray(cell_ids, dtype=np.int64)
    days = season_days(year)
    if available is None:
        available = available_days(days[0], days[-1])
    sessions = _Sessions()
    if fetch is None:
        manifest = Manifest(MANIFEST_PATH, data_root())
        fetch = lambda day, directory: fetch_lhasa(day, directory, manifest=manifest, session=sessions.get())
    year_cache = Path(cache) / str(year)
    todo = [k for k, day in enumerate(days) if day in available]
    prob = np.full((ids.size, len(days)), np.nan, dtype=np.float32)
    fetched = np.zeros(len(days), dtype=bool)
    failed: dict[str, str] = {}
    lock = threading.Lock()
    abort = threading.Event()
    consecutive = [0]

    def task(k: int):
        if abort.is_set():
            return k, None, "not attempted: stopped after repeated failures"
        try:
            for attempt in range(FORMAT_ATTEMPTS):
                path = fetch(days[k], year_cache)
                try:
                    column = cell_max(path, ids)
                    break
                except LhasaFormatError:
                    Path(path).unlink(missing_ok=True)      # never keep a file that does not decode
                    if attempt == FORMAT_ATTEMPTS - 1:
                        raise
        except (DownloadError, LhasaFormatError, OSError) as exc:
            reason = f"{type(exc).__name__}: {exc}"
            with lock:
                consecutive[0] += 1
                if consecutive[0] >= ABORT_AFTER:
                    abort.set()
            return k, None, reason
        with lock:
            consecutive[0] = 0
        return k, column, ""

    done = 0
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for future in as_completed([pool.submit(task, k) for k in todo]):
                k, column, reason = future.result()
                if column is None:
                    failed[days[k].isoformat()] = reason
                else:
                    prob[:, k] = column
                    fetched[k] = True
                done += 1
                if done % 20 == 0 or done == len(todo):
                    say(f"  {year}: {done}/{len(todo)} days, {len(failed)} failed")
    finally:
        sessions.close()
    if abort.is_set():
        raise DownloadError(f"{ABORT_AFTER} consecutive days failed for {year}; last reason: {_last_reason(failed)}")
    missing = [day.isoformat() for k, day in enumerate(days) if day not in available]
    shown = prob[:, fetched]
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"lhasa_{year}.npz"
    dump_json(path.with_suffix(".json"), {
        "year": year, "source": SOURCE, "licence": LICENCE, "concept_id": CONCEPT_ID,
        "variable": VARIABLE, "reduction": "maximum over the pixels whose centres fall in the 0.05 degree cell",
        "window": [days[0].isoformat(), days[-1].isoformat()], "n_cells": int(ids.size), "n_days": len(days),
        "days_fetched": int(fetched.sum()), "days_missing_in_archive": missing, "days_failed": failed,
        "nan_share_of_fetched_days": float(np.isnan(shown).mean()) if shown.size else None})
    _write_npz(path, cell_id=ids, days=np.array([d.isoformat() for d in days]), prob=prob, fetched=fetched)
    say(f"  {year}: written {path} ({int(fetched.sum())} of {len(days)} days)")
    return path


def _last_reason(failed: dict[str, str]) -> str:
    """The reason of the last failed day (by date) with a real error, for an abort message."""
    real = [reason for _, reason in sorted(failed.items()) if not reason.startswith("not attempted")]
    return real[-1] if real else "unknown"


def parse_years(text: str) -> tuple[int, ...]:
    first, _, last = text.partition("-")
    years = tuple(range(int(first), int(last or first) + 1))
    if not years or not set(years) <= set(YEARS):
        raise ValueError(f"years must lie in {YEARS[0]}-{YEARS[-1]}, got {text}")
    return years


def run(years, out_dir: Path, cache: Path, workers: int, say) -> int:
    """Build the years in turn; returns the number of window days that failed to fetch (0 = complete)."""
    from ..live import backtest as bt
    cells = bt.load_set("season_2018").cells["cell_id"].to_numpy()
    say(f"LHASA v2: {cells.size} cells of season_2018, years {years[0]}-{years[-1]}")
    failures = 0
    for year in years:
        path = build_year(year, cells, out_dir, cache, say, workers=workers)
        failures += len(_sidecar(path)["days_failed"])
    return failures


def _sidecar(path: Path) -> dict:
    return json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m aetherguard.verify.lhasa", description=__doc__.splitlines()[0])
    parser.add_argument("--years", type=parse_years, default=YEARS, help="YYYY or YYYY-YYYY (default 2018-2020)")
    parser.add_argument("--out", type=Path, default=data_root() / "processed" / "benchmarks",
                        help="output directory (default data/processed/benchmarks)")
    parser.add_argument("--cache", type=Path, default=data_root() / "raw" / "lhasa",
                        help="raw subset directory (default data/raw/lhasa)")
    parser.add_argument("--workers", type=int, default=WORKERS, help=f"parallel downloads (default {WORKERS})")
    args = parser.parse_args(argv)
    try:
        failures = run(args.years, args.out, args.cache, args.workers, lambda m: print(m, flush=True))
    except (DownloadError, ValueError, OSError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    if failures:
        print(f"{failures} days failed; run again to retry them (see the sidecar JSON)", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
