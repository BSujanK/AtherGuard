"""NASA GPM IMERG V07 daily rain (Late and Early runs): CMR discovery, OPeNDAP subset download, daily store.

Access path (measured, reports/phase6_live_sources_probe.md; configured in configs/live.yaml, section `imerg`):
* discovery through CMR; the granule file name carries a version letter (V07B for old days, V07C for new), so the
  name and the OPeNDAP link always come from CMR and are never constructed;
* data through the Hyrax cloud OPeNDAP DAP4 subset of the granule (the domain crop is made by the server, about
  125-220 KB per day), read with xarray's h5netcdf engine.

The subset holds `precipitation` as (time, lon, lat): LON-MAJOR, lat and lon ascending, mm/day, UTC day, fill value
-9999.9. The store transposes it to [row = latitude south -> north, col = longitude west -> east], the 0.1 degree
domain grid shared with the GFS products (configs/live.yaml, `domain_grid`).

Store layout in `processed_dir` (data/processed/rain):
    imerg_<run>_<year>.npy      float32 (days_in_year, rows, cols), NaN where a day is not present
    imerg_<run>_index.json      days present with their source version, days missing / failed, grid, orientation
A day is present only once it is listed in the index, so a crash between a write and the index checkpoint is
repaired by the next `update` (the raw file is manifest-current, so nothing is downloaded again).
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import requests

from ..config import PROJECT_ROOT, data_root, load_config
from ..grid import cell_center
from ..http import DownloadError, download, fetch_json
from ..manifest import Manifest

_LIVE = load_config("live")
_CFG = _LIVE["imerg"]
GRID = dict(_LIVE["domain_grid"])
STEP, LAT_FIRST, LON_FIRST = float(GRID["step"]), float(GRID["lat_first"]), float(GRID["lon_first"])
ROWS, COLS = int(GRID["rows"]), int(GRID["cols"])

RUNS = tuple(_CFG["runs"])
HISTORY_START = date.fromisoformat(_CFG["history_start"])
EARLY_WINDOWS = [(date.fromisoformat(w["start"]), date.fromisoformat(w["end"])) for w in _CFG["early_windows"]]
CMR_URL = _CFG["cmr_url"]
CMR_PAGE_SIZE = int(_CFG["cmr_page_size"])
VARIABLE = _CFG["precipitation_variable"]
MAX_WORKERS = int(_CFG["workers"])
RETRIES = int(_CFG["retries"])
BACKOFF_S = float(_CFG["backoff_s"])
ABORT_AFTER = int(_CFG["abort_after"])
FORMAT_ATTEMPTS = 2           # a file that downloads but does not decode is fetched once more, then the day fails
CHECKPOINT_EVERY = 100        # results between flushes of the year arrays and the index
COORD_TOLERANCE = 1e-3        # degrees; the file stores lon as float32

MANIFEST_PATH = PROJECT_ROOT / "manifests" / "data_manifest.jsonl"
LICENCE = "NASA Earth science data, open access (https://www.earthdata.nasa.gov/engage/open-data-services-software/data-use-policy)"
FILE_DIMS = ("time", "lon", "lat")
NOT_ATTEMPTED = "not attempted: stopped after repeated failures"
ORIENTATION = ("source files hold precipitation as (time, lon, lat), i.e. lon-major; arrays here are "
               "[day, row, col] with row = latitude south -> north (row 0 = lat_first) and col = longitude "
               "west -> east (col 0 = lon_first); NaN = no data")

# Global IMERG lattice: pixel centres at -89.95 + 0.1 k (lat) and -179.95 + 0.1 k (lon).
GLOBAL_LAT0 = int(round((LAT_FIRST + 89.95) / STEP))
GLOBAL_LON0 = int(round((LON_FIRST + 179.95) / STEP))
CONSTRAINT = (f"dap4.ce=/{VARIABLE}[0][{GLOBAL_LON0}:{GLOBAL_LON0 + COLS - 1}][{GLOBAL_LAT0}:{GLOBAL_LAT0 + ROWS - 1}];"
              f"/time;/lon[{GLOBAL_LON0}:{GLOBAL_LON0 + COLS - 1}];/lat[{GLOBAL_LAT0}:{GLOBAL_LAT0 + ROWS - 1}]")

_VERSION = re.compile(r"\.(V\d{2}[A-Z]?)\.nc4?$")
_FETCH_ERRORS = (DownloadError, OSError, ValueError)  # ImergFormatError is a ValueError


class ImergFormatError(ValueError):
    """A downloaded IMERG file is not the expected domain subset."""


def _as_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _check_run(run: str) -> str:
    if run not in RUNS:
        raise ValueError(f"run must be one of {RUNS}, got {run!r}")
    return run


# ------------------------------------------------------------------------------------------ pixel grid

def domain_lat() -> np.ndarray:
    """Pixel-centre latitudes of the domain grid, south -> north."""
    return np.round(LAT_FIRST + STEP * np.arange(ROWS), 6)


def domain_lon() -> np.ndarray:
    """Pixel-centre longitudes of the domain grid, west -> east."""
    return np.round(LON_FIRST + STEP * np.arange(COLS), 6)


def imerg_pixel(cell_id):
    """(row, col) of the 0.1 degree IMERG pixel that contains the centre of a 0.05 degree cell.

    Row 0 is the southern edge, col 0 the western edge of the domain grid. Raises ValueError for a cell outside it.
    An array of cell ids gives a pair of arrays.
    """
    lat, lon = cell_center(cell_id)
    row = np.floor(np.round((np.asarray(lat) - (LAT_FIRST - STEP / 2)) / STEP, 6)).astype(np.int64)
    col = np.floor(np.round((np.asarray(lon) - (LON_FIRST - STEP / 2)) / STEP, 6)).astype(np.int64)
    if np.any((row < 0) | (row >= ROWS) | (col < 0) | (col >= COLS)):
        raise ValueError("cell is outside the IMERG domain grid")
    if row.ndim == 0:
        return int(row), int(col)
    return row, col


# ------------------------------------------------------------------------------------------ CMR discovery

@dataclass(frozen=True)
class Granule:
    day: date           # UTC day
    file_name: str
    version: str        # V07B, V07C, ... ("unknown" when the name carries none)
    opendap_url: str    # Hyrax granule URL from CMR, without suffix
    updated: str        # CMR update time, ISO text


def parse_granule(entry: dict) -> Granule:
    name = entry.get("producer_granule_id") or entry["title"].split(":", 1)[-1]
    opendap = next((link["href"] for link in entry.get("links", [])
                    if link.get("rel", "").endswith("/service#") and "/collections/" in link.get("href", "")
                    and "/granules/" in link["href"]), None)
    if opendap is None:
        raise ValueError(f"no OPeNDAP link in the CMR entry for {name}")
    start = datetime.fromisoformat(entry["time_start"].replace("Z", "+00:00")).astimezone(timezone.utc)
    match = _VERSION.search(name)
    return Granule(day=start.date(), file_name=name, version=match.group(1) if match else "unknown",
                   opendap_url=opendap, updated=entry.get("updated", ""))


def discover(run: str, first: date, last: date) -> dict[date, Granule]:
    """The CMR granule of every UTC day in [first, last] that has one (the latest update wins per day)."""
    concept_id = _CFG["runs"][_check_run(run)]["concept_id"]
    params = {"collection_concept_id": concept_id, "sort_key": "start_date", "page_size": CMR_PAGE_SIZE,
              "temporal": f"{first.isoformat()}T00:00:00Z,{last.isoformat()}T23:59:59Z"}
    found: dict[date, Granule] = {}
    page = 1
    while True:
        entries = fetch_json(CMR_URL, params={**params, "page_num": page}, retries=RETRIES,
                             backoff=BACKOFF_S)["feed"]["entry"]
        for entry in entries:
            granule = parse_granule(entry)
            if first <= granule.day <= last and (granule.day not in found
                                                 or granule.updated >= found[granule.day].updated):
                found[granule.day] = granule
        if len(entries) < CMR_PAGE_SIZE:
            return found
        page += 1


def subset_url(granule: Granule) -> str:
    return f"{granule.opendap_url}.dap.nc4?{CONSTRAINT}"


# ------------------------------------------------------------------------------------------ reading one file

def read_day(path, day: date) -> np.ndarray:
    """One subset file as float32 (rows, cols) in store orientation; fill and negative values become NaN.

    Refuses (ImergFormatError) a file that is unreadable, lacks the variable, is not (time, lon, lat) on the
    domain grid, holds another day, or has no valid pixel.
    """
    import xarray as xr
    path = Path(path)
    try:
        with xr.open_dataset(path, engine="h5netcdf") as ds:
            if VARIABLE not in ds.data_vars:
                raise ImergFormatError(f"{path.name}: variable {VARIABLE!r} is missing")
            array = ds[VARIABLE]
            if array.dims != FILE_DIMS:
                raise ImergFormatError(f"{path.name}: unexpected dimensions {array.dims}, expected {FILE_DIMS}")
            if array.shape != (1, COLS, ROWS):
                raise ImergFormatError(f"{path.name}: unexpected shape {array.shape}, expected {(1, COLS, ROWS)}")
            if not (np.allclose(ds["lat"].values, domain_lat(), atol=COORD_TOLERANCE)
                    and np.allclose(ds["lon"].values, domain_lon(), atol=COORD_TOLERANCE)):
                raise ImergFormatError(f"{path.name}: coordinates are not the domain grid (south -> north, west -> east)")
            stamp = ds["time"].values[0].astype("datetime64[D]").astype(object)
            values = np.ascontiguousarray(array.values[0].T, dtype=np.float32)
    except ImergFormatError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ImergFormatError(f"{path.name}: cannot be read as an IMERG subset ({type(exc).__name__})") from exc
    if stamp != day:
        raise ImergFormatError(f"{path.name}: holds {stamp.isoformat()}, expected {day.isoformat()}")
    values[~np.isfinite(values) | (values < 0)] = np.nan
    if not np.isfinite(values).any():
        raise ImergFormatError(f"{path.name}: no valid pixel in the domain")
    return values


# ------------------------------------------------------------------------------------------ the store

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


def _write_atomic(path: Path, text: str) -> None:
    part = path.with_name(path.name + ".part")
    part.write_text(text, encoding="utf-8")
    os.replace(part, path)


def _days_in_year(year: int) -> int:
    return (date(year + 1, 1, 1) - date(year, 1, 1)).days


class ImergStore:
    """Daily IMERG rain on the 0.1 degree domain grid for one run (`late` or `early`)."""

    def __init__(self, processed_dir, run: str = "late", *, raw_dir=None, manifest: Manifest | None = None) -> None:
        self.run = _check_run(run)
        self.processed_dir = Path(processed_dir)
        self.raw_dir = Path(raw_dir) if raw_dir is not None else data_root() / "raw" / "imerg"
        self.manifest = manifest if manifest is not None else Manifest(MANIFEST_PATH, data_root())
        self._versions: dict[date, str] = {}
        self._missing: set[date] = set()
        self._failed: set[date] = set()
        self._maps: dict[int, np.ndarray] = {}
        self._load_index()

    # ---- paths and index
    @property
    def index_path(self) -> Path:
        return self.processed_dir / f"imerg_{self.run}_index.json"

    def year_path(self, year: int) -> Path:
        return self.processed_dir / f"imerg_{self.run}_{year}.npy"

    def _raw_path(self, granule: Granule) -> Path:
        stem = granule.file_name.rsplit(".", 1)[0]
        return self.raw_dir / self.run / f"{granule.day.year}" / f"{stem}.subset.nc4"

    def _load_index(self) -> None:
        if not self.index_path.exists():
            return
        try:
            years = json.loads(self.index_path.read_text(encoding="utf-8"))["years"]
            for year, entry in years.items():
                versions = {date.fromisoformat(k): str(v) for k, v in entry["versions"].items()}
                if sorted(d.isoformat() for d in versions) != entry["present"] \
                        or any(d.year != int(year) for d in versions):
                    raise ValueError("present days and versions disagree")
                self._versions.update(versions)
                self._missing.update(date.fromisoformat(d) for d in entry["missing"])
                self._failed.update(date.fromisoformat(d) for d in entry["failed"])
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError(f"{self.index_path} is corrupt ({exc})") from exc

    def _save_index(self) -> None:
        years: dict[str, dict] = {}
        for year in sorted({d.year for d in (*self._versions, *self._missing, *self._failed)}):
            versions = {d.isoformat(): v for d, v in sorted(self._versions.items()) if d.year == year}
            years[str(year)] = {
                "n_days": _days_in_year(year), "n_present": len(versions), "present": list(versions),
                "missing": sorted(d.isoformat() for d in self._missing if d.year == year),
                "failed": sorted(d.isoformat() for d in self._failed if d.year == year),
                "versions": versions}
        present = sorted(self._versions)
        index = {
            "source": f"NASA GPM IMERG V07 {self.run} run daily ({_CFG['runs'][self.run]['short_name']}), "
                      "Hyrax OPeNDAP DAP4 subset",
            "run": self.run, "collection_concept_id": _CFG["runs"][self.run]["concept_id"],
            "units": "mm/day", "day_basis": "utc", "dtype": "float32", "grid": GRID, "orientation": ORIENTATION,
            "day_status": "present = in the array; missing = no CMR granule at the last attempt; failed = granule "
                          "found but not fetched or decoded; missing and failed days are retried by every update",
            "days_present": len(present),
            "first_day": present[0].isoformat() if present else None,
            "last_day": present[-1].isoformat() if present else None,
            "years": years}
        self.processed_dir.mkdir(parents=True, exist_ok=True)
        _write_atomic(self.index_path, json.dumps(index, indent=1, allow_nan=False) + "\n")

    # ---- queries
    def dates(self) -> list[date]:
        """Days with data in the store, ascending."""
        return sorted(self._versions)

    def has_date(self, day) -> bool:
        return _as_date(day) in self._versions

    def _year_map(self, year: int) -> np.ndarray | None:
        if year not in self._maps:
            path = self.year_path(year)
            if not path.exists():
                return None
            stack = np.load(path, mmap_mode="r")
            if stack.shape != (_days_in_year(year), ROWS, COLS) or stack.dtype != np.float32:
                raise ValueError(f"{path}: expected float32 {(_days_in_year(year), ROWS, COLS)}, "
                                 f"found {stack.dtype} {stack.shape}")
            self._maps[year] = stack
        return self._maps[year]

    def gather(self, rows, cols, first_day, length: int) -> np.ndarray:
        """Rain (mm/day) at the given pixels for `length` days from `first_day`: float32 (n, length).

        NaN for every day not present in the store (missing upstream, not fetched yet, before the first or after
        the last year), also across year boundaries.
        """
        rows = np.asarray(rows, dtype=np.int64).ravel()
        cols = np.asarray(cols, dtype=np.int64).ravel()
        if rows.shape != cols.shape:
            raise ValueError("rows and cols must have the same length")
        if length < 1:
            raise ValueError("length must be at least 1")
        if np.any((rows < 0) | (rows >= ROWS) | (cols < 0) | (cols >= COLS)):
            raise ValueError(f"pixel outside the {ROWS}x{COLS} domain grid")
        out = np.full((rows.size, length), np.nan, dtype=np.float32)
        day, last, offset = _as_date(first_day), _as_date(first_day) + timedelta(length - 1), 0
        while day <= last:
            segment = (min(date(day.year, 12, 31), last) - day).days + 1
            stack = self._year_map(day.year)
            if stack is not None:
                present = np.fromiter(((day + timedelta(k)) in self._versions for k in range(segment)),
                                      dtype=bool, count=segment)
                if present.any():
                    first = day.timetuple().tm_yday - 1
                    block = np.asarray(stack[first:first + segment, rows, cols])
                    out[:, offset + np.flatnonzero(present)] = block.T[:, present]
            day, offset = day + timedelta(segment), offset + segment
        return out

    def close(self) -> None:
        """Release the memory maps (Windows keeps the files locked while they are open)."""
        self._maps.clear()

    # ---- update
    def _open_year_for_write(self, year: int) -> np.ndarray:
        path = self.year_path(year)
        shape = (_days_in_year(year), ROWS, COLS)
        if not path.exists():
            self.processed_dir.mkdir(parents=True, exist_ok=True)
            part = path.with_name(path.name + ".part")
            stack = np.lib.format.open_memmap(part, mode="w+", dtype=np.float32, shape=shape)
            stack[:] = np.nan
            stack.flush()
            del stack
            os.replace(part, path)
        stack = np.load(path, mmap_mode="r+")
        if stack.shape != shape or stack.dtype != np.float32:
            raise ValueError(f"{path}: expected float32 {shape}, found {stack.dtype} {stack.shape}")
        return stack

    def _fetch(self, granule: Granule, sessions: _Sessions) -> tuple[np.ndarray, int]:
        """Raw subset (cached, manifest-checked) -> store-oriented field, and the bytes downloaded."""
        dest = self._raw_path(granule)
        source = f"NASA GPM IMERG V07 {self.run} daily ({_CFG['runs'][self.run]['short_name']}) OPeNDAP subset"
        for attempt in range(FORMAT_ATTEMPTS):
            fetched = 0
            if not self.manifest.is_current(dest):
                download(subset_url(granule), dest, self.manifest, source, LICENCE, retries=RETRIES,
                         backoff=BACKOFF_S, session=sessions.get())
                fetched = dest.stat().st_size
            try:
                return read_day(dest, granule.day), fetched
            except ImergFormatError:
                dest.unlink(missing_ok=True)  # never keep a file that does not decode
                if attempt == FORMAT_ATTEMPTS - 1:
                    raise
                time.sleep(BACKOFF_S * 2 ** attempt)
        raise AssertionError("unreachable")

    def update(self, days: list[date], *, workers: int = MAX_WORKERS) -> dict:
        """Download, crop and store every requested day that is not present yet; idempotent and resumable.

        Days already present cost no request at all. For the others one CMR search is made; a day without a CMR
        granule is `missing`, a day whose granule cannot be fetched or decoded is `failed`; both are listed in the
        index and tried again by the next call. New days are written into their year array in place, so older
        years are never rewritten. Returns the counts and the lists of missing / failed days (ISO text).
        """
        if not 1 <= workers <= MAX_WORKERS:
            raise ValueError(f"workers must be between 1 and {MAX_WORKERS}, got {workers}")
        wanted = sorted({_as_date(d) for d in days})
        todo = [d for d in wanted if d not in self._versions]
        summary = {"requested": len(wanted), "already_present": len(wanted) - len(todo), "added": 0,
                   "missing": [], "failed": [], "failure_reasons": {}, "bytes_fetched": 0}
        if not todo:
            return summary
        found = discover(self.run, todo[0], todo[-1])
        for day in todo:
            if day in found:
                continue
            self._missing.add(day)
            self._failed.discard(day)
            summary["missing"].append(day.isoformat())

        sessions = _Sessions()
        lock = threading.Lock()
        abort = threading.Event()
        consecutive = [0]

        def task(granule: Granule):
            if abort.is_set():
                return granule, None, 0, NOT_ATTEMPTED
            try:
                field, fetched = self._fetch(granule, sessions)
            except _FETCH_ERRORS as exc:
                with lock:
                    consecutive[0] += 1
                    if consecutive[0] >= ABORT_AFTER:
                        abort.set()
                return granule, None, 0, type(exc).__name__
            with lock:
                consecutive[0] = 0
            return granule, field, fetched, None

        writers: dict[int, np.ndarray] = {}
        log_path = self.raw_dir / self.run / "progress.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        started, done = time.monotonic(), 0

        def checkpoint() -> None:
            for stack in writers.values():
                stack.flush()
            self._save_index()
            stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(f"{stamp} {done}/{len(found)} done, added {summary['added']}, "
                             f"failed {len(summary['failed'])}, {summary['bytes_fetched'] / 1e6:.1f} MB fetched, "
                             f"{time.monotonic() - started:.0f} s\n")

        try:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(task, found[d]) for d in todo if d in found]
                for future in as_completed(futures):
                    granule, field, fetched, reason = future.result()
                    day = granule.day
                    if field is None:
                        self._failed.add(day)
                        self._missing.discard(day)
                        summary["failed"].append(day.isoformat())
                        reasons = summary["failure_reasons"]
                        reasons[reason] = reasons.get(reason, 0) + 1
                    else:
                        if day.year not in writers:
                            writers[day.year] = self._open_year_for_write(day.year)
                        writers[day.year][day.timetuple().tm_yday - 1] = field
                        self._versions[day] = granule.version
                        self._missing.discard(day)
                        self._failed.discard(day)
                        summary["added"] += 1
                        summary["bytes_fetched"] += fetched
                    done += 1
                    if done % CHECKPOINT_EVERY == 0:
                        checkpoint()
        except BaseException:
            abort.set()  # queued days return at once instead of being downloaded while the error propagates
            raise
        finally:
            checkpoint()
            for year in writers:
                self._maps.pop(year, None)
            writers.clear()
            sessions.close()
        summary["failed"].sort()
        return summary
