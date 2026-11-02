"""CHIRPS v2.0 daily 0.05-degree rainfall: bulk download, domain crop to float16 arrays, reader.

Our 0.05-degree grid is exactly the CHIRPS p05 lattice. p05 covers lat 50..-50 (2000 rows) and lon -180..180
(7200 cols); row r has centre latitude 49.975 - 0.05 r, so for a cell_id (lat_idx, lon_idx):
    row_global = 2799 - lat_idx,    col_global = lon_idx.
Day basis: UTC calendar day (see docs/phase1-design.md D5).
"""
from __future__ import annotations

import gzip
import json
import os
import shutil
import tempfile
import threading
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import rasterio
from rasterio.errors import RasterioError
from rasterio.windows import Window

from ..config import load_config
from ..grid import CELL_DEG, ID_STRIDE
from ..http import DownloadError, download
from ..manifest import Manifest

SOURCE = "CHIRPS v2.0 daily p05"
LICENCE = "CHIRPS data: see https://www.chc.ucsb.edu/data/chirps (verify terms)"
CHIRPS_ROWS = 2000
CHIRPS_COLS = 7200
TOP_LAT_IDX = 2799  # lat_idx of CHIRPS row 0 (centre latitude 49.975)
MISSING_DATES_FILE = "missing_dates.json"
FAILED_DATES_FILE = "failed_dates.json"
PROGRESS_LOG = "download_progress.log"
PROGRESS_EVERY = 100
FLOAT16_MAX = float(np.finfo(np.float16).max)  # 65504
FLOAT16_RELATIVE_BOUND = 2.0 ** -11  # largest relative rounding error of a float16 value (half an ulp)
INDEX_FILE = "chirps_index.json"


# ----------------------------------------------------------------------------------------------- dates

def _as_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def needed_dates(cfg: dict) -> list[date]:
    """Every day of `full_years` (both years inclusive) plus the `extra_ranges`, sorted and unique."""
    days: set[date] = set()
    years = cfg["full_years"]
    first, last = date(int(years["start"]), 1, 1), date(int(years["end"]), 12, 31)
    days.update(first + timedelta(d) for d in range((last - first).days + 1))
    for window in cfg.get("extra_ranges", []):
        start, end = _as_date(window["start"]), _as_date(window["end"])
        days.update(start + timedelta(d) for d in range((end - start).days + 1))
    return sorted(days)


def raw_path(raw_dir, day: date) -> Path:
    return Path(raw_dir) / f"{day.year}" / f"chirps-v2.0.{day:%Y.%m.%d}.tif.gz"


def chirps_url(template: str, day: date) -> str:
    return template.format(y=f"{day.year:04d}", m=f"{day.month:02d}", d=f"{day.day:02d}")


# ------------------------------------------------------------------------------------------- pixel grid

def cell_to_chirps_pixel(cell_id):
    """(row_global, col_global) of the CHIRPS p05 pixel that is exactly our 0.05-degree cell."""
    ids = np.asarray(cell_id, dtype=np.int64)
    lat_idx, lon_idx = ids // ID_STRIDE, ids % ID_STRIDE
    row = TOP_LAT_IDX - lat_idx
    if np.any((row < 0) | (row >= CHIRPS_ROWS)) or np.any(lon_idx >= CHIRPS_COLS):
        raise ValueError("cell is outside the CHIRPS p05 coverage (lat -50..50)")
    if ids.ndim == 0:
        return int(row), int(lon_idx)
    return row, lon_idx


def _edge_index(value: float, origin: float) -> int:
    scaled = (value - origin) / CELL_DEG
    index = round(scaled)
    if abs(scaled - index) > 1e-6:
        raise ValueError(f"{value} is not on the 0.05-degree lattice")
    return int(index)


def domain_window(cfg: dict) -> dict:
    """Rows/cols of the config bbox inside the global CHIRPS raster (row 0 = northernmost row)."""
    box = cfg["domain_bbox"]
    lat_lo, lat_hi = _edge_index(box["lat_min"], -90.0), _edge_index(box["lat_max"], -90.0)
    lon_lo, lon_hi = _edge_index(box["lon_min"], -180.0), _edge_index(box["lon_max"], -180.0)
    row_off = TOP_LAT_IDX + 1 - lat_hi
    if not (lat_lo < lat_hi and lon_lo < lon_hi and row_off >= 0 and TOP_LAT_IDX + 1 - lat_lo <= CHIRPS_ROWS
            and lon_lo >= 0 and lon_hi <= CHIRPS_COLS):
        raise ValueError(f"domain_bbox {box} is not inside CHIRPS p05 coverage")
    return {"row_off": row_off, "col_off": lon_lo, "n_rows": lat_hi - lat_lo, "n_cols": lon_hi - lon_lo,
            "lat_idx_lo": lat_lo, "lon_idx_lo": lon_lo}


# ------------------------------------------------------------------------------------------ download

class _ProgressLog:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = path.open("a", encoding="utf-8")
        self._lock = threading.Lock()

    def write(self, message: str) -> None:
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self._lock:
            self._handle.write(f"{stamp} {message}\n")
            self._handle.flush()

    def close(self) -> None:
        self._handle.close()


def _read_dates(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return set(json.loads(path.read_text(encoding="utf-8")))


def _write_dates(path: Path, days) -> None:
    tmp = path.with_name(path.name + ".part")
    tmp.write_text(json.dumps(sorted(days), indent=0) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def download_chirps(dates: Sequence[date], raw_dir, manifest: Manifest, workers: int, *,
                    url_template: str | None = None, retries: int = 3, backoff: float = 2.0,
                    retry_pause: float = 30.0, abort_after: int = 30) -> dict[str, int]:
    """Download one gz file per date into `<raw_dir>/<year>/`, resumably, with at most `workers` in parallel.

    Files that are already manifest-current are not fetched. HTTP 404 means the day is not published: it is
    recorded in `missing_dates.json` and the run goes on. Any other failure is recorded, retried once after
    `retry_pause` seconds at the end, and stays in `failed_dates.json` if it fails again. After `abort_after`
    consecutive failures the run stops asking (the server is unwell); the remaining dates count as failed.
    Returns {ok, already_present, missing, failed}, which sum to the number of requested dates.
    """
    dates = [_as_date(d) for d in dates]
    if len(set(dates)) != len(dates):
        raise ValueError("dates must be unique")
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    if url_template is None:
        url_template = load_config("ingest")["chirps"]["url"]
    log = _ProgressLog(raw_dir / PROGRESS_LOG)
    state = {"consecutive": 0}
    state_lock = threading.Lock()
    abort = threading.Event()
    bytes_ok = [0]

    def fetch(day: date) -> tuple[str, str]:
        dest = raw_path(raw_dir, day)
        if abort.is_set():
            return "failed", "not attempted: stopped after repeated failures"
        try:
            if manifest.is_current(dest):
                outcome, detail = "already_present", ""
            else:
                download(chirps_url(url_template, day), dest, manifest, SOURCE, LICENCE,
                         retries=retries, backoff=backoff)
                with state_lock:
                    bytes_ok[0] += dest.stat().st_size
                outcome, detail = "ok", ""
        except DownloadError as exc:
            outcome, detail = ("missing" if exc.status == 404 else "failed"), str(exc)
        except OSError as exc:
            outcome, detail = "failed", f"{type(exc).__name__}: {exc}"
        with state_lock:
            state["consecutive"] = state["consecutive"] + 1 if outcome == "failed" else 0
            if state["consecutive"] >= abort_after:
                abort.set()
        return outcome, detail

    def run_pass(days: list[date], label: str) -> dict[date, tuple[str, str]]:
        results: dict[date, tuple[str, str]] = {}
        started = time.monotonic()
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            futures = {pool.submit(fetch, day): day for day in days}
            for future in as_completed(futures):
                results[futures[future]] = future.result()
                if len(results) % PROGRESS_EVERY == 0 or len(results) == len(days):
                    counts = {k: sum(1 for r in results.values() if r[0] == k)
                              for k in ("ok", "already_present", "missing", "failed")}
                    log.write(f"{label}: {len(results)}/{len(days)} done {counts} "
                              f"{bytes_ok[0] / 1e9:.2f} GB fetched, {time.monotonic() - started:.0f} s")
        return results

    try:
        final = run_pass(dates, "download")
        failed = sorted(d for d, r in final.items() if r[0] == "failed")
        if failed and not abort.is_set():
            log.write(f"retrying {len(failed)} failed date(s) after {retry_pause:.0f} s")
            time.sleep(retry_pause)
            state["consecutive"] = 0
            final.update(run_pass(failed, "retry"))
        for day in sorted(d for d, r in final.items() if r[0] in ("missing", "failed")):
            log.write(f"{final[day][0]} {day.isoformat()}: {final[day][1]}")
        requested = {d.isoformat() for d in dates}
        missing_now = {d.isoformat() for d, r in final.items() if r[0] == "missing"}
        failed_now = {d.isoformat() for d, r in final.items() if r[0] == "failed"}
        _write_dates(raw_dir / MISSING_DATES_FILE,
                     (_read_dates(raw_dir / MISSING_DATES_FILE) - requested) | missing_now)
        _write_dates(raw_dir / FAILED_DATES_FILE,
                     (_read_dates(raw_dir / FAILED_DATES_FILE) - requested) | failed_now)
        summary = {key: sum(1 for r in final.values() if r[0] == key)
                   for key in ("ok", "already_present", "missing", "failed")}
        log.write(f"summary {summary} for {len(dates)} requested dates, {bytes_ok[0] / 1e9:.2f} GB fetched")
        return summary
    finally:
        log.close()


# ------------------------------------------------------------------------------------------ crop

class ChirpsIncompleteError(RuntimeError):
    """Needed days have neither a downloaded file nor a recorded 404."""


class ChirpsReadError(RuntimeError):
    """A downloaded CHIRPS file could not be decoded."""


def _read_raster_window(tif_path: str, window, path: Path) -> np.ndarray:
    with rasterio.open(tif_path) as ds:
        if (ds.height, ds.width) != (CHIRPS_ROWS, CHIRPS_COLS):
            raise ChirpsReadError(f"{path}: raster is {ds.height}x{ds.width}, expected "
                                  f"{CHIRPS_ROWS}x{CHIRPS_COLS}")
        data = ds.read(1, window=window, out_dtype="float32")
        nodata = ds.nodata
    if nodata is not None:
        data[data == nodata] = np.nan
    return data


def read_domain_day(gz_path, win: dict) -> np.ndarray:
    """One day's domain window as float32 (n_rows, n_cols); -9999/negative and non-finite become NaN."""
    gz_path = Path(gz_path)
    window = Window(win["col_off"], win["row_off"], win["n_cols"], win["n_rows"])
    try:
        data = _read_raster_window(f"/vsigzip/{gz_path.resolve().as_posix()}", window, gz_path)
    except RasterioError:
        with tempfile.TemporaryDirectory(prefix="chirps_") as tmp:
            tif = Path(tmp) / "day.tif"
            try:
                with gzip.open(gz_path, "rb") as source, tif.open("wb") as target:
                    shutil.copyfileobj(source, target)
                data = _read_raster_window(str(tif), window, gz_path)
            except (OSError, EOFError, RasterioError) as exc:
                raise ChirpsReadError(f"{gz_path}: unreadable CHIRPS file ({type(exc).__name__}: {exc})") from exc
    data[~np.isfinite(data) | (data < 0)] = np.nan
    return data


def _year_paths(out_dir: Path, year: int) -> tuple[Path, Path]:
    return out_dir / f"chirps_{year}.npy", out_dir / f"chirps_{year}_dates.json"


def _write_atomic(path: Path, write) -> None:
    part = path.with_name(path.name + ".part")
    try:
        with part.open("wb") as handle:
            write(handle)
        os.replace(part, path)
    except BaseException:
        part.unlink(missing_ok=True)
        raise


def _year_is_current(out_dir: Path, year: int, days: list[date], missing: list[str], win: dict,
                     previous_missing: dict[int, list[str]] | None) -> bool:
    """A stored year is reusable when its dates match the needed dates, its array has the expected shape and
    the set of missing days (which are stored as all-NaN) has not changed since it was cropped."""
    npy, dates_json = _year_paths(out_dir, year)
    if not (npy.exists() and dates_json.exists()) or previous_missing is None:
        return False
    try:
        if json.loads(dates_json.read_text(encoding="utf-8")) != [d.isoformat() for d in days]:
            return False
        stored = np.load(npy, mmap_mode="r")
    except (ValueError, OSError):
        return False
    return (stored.shape == (len(days), win["n_rows"], win["n_cols"]) and stored.dtype == np.float16
            and previous_missing.get(year) == missing)


def _year_stats(out_dir: Path, year: int, days: list[date], missing: set[str]) -> dict:
    """Verify a stored year (float16 range, no all-NaN day unless listed missing) and summarise it."""
    stored = np.load(_year_paths(out_dir, year)[0], mmap_mode="r")
    n_nan = n_pixels = 0
    peak = 0.0
    for i, day in enumerate(days):
        nan = np.isnan(stored[i])
        if day.isoformat() in missing:
            if not nan.all():
                raise ValueError(f"{day}: listed as missing but the stored day has data")
            continue
        if nan.all():
            raise ValueError(f"{day}: stored day is all NaN but the date is not listed as missing")
        n_nan += int(nan.sum())
        n_pixels += nan.size
        peak = max(peak, float(np.max(stored[i], where=~nan, initial=0.0)))
    if not peak < FLOAT16_MAX:
        raise ValueError(f"{year}: maximum {peak} does not fit float16 (limit {FLOAT16_MAX})")
    return {"n_days": len(days), "n_missing_days": len(missing), "n_nan_pixels": n_nan,
            "n_pixels": n_pixels, "max_value": peak}


def crop_chirps(dates: Sequence[date], raw_dir, out_dir, cfg: dict, *, workers: int = 4) -> dict:
    """Crop the domain window of every needed day into float16 per-year arrays; resumable.

    Writes `chirps_<year>.npy` (n_days, rows, cols; row 0 = northernmost), `chirps_<year>_dates.json` and
    `chirps_index.json`; returns the index. A day without a downloaded file must be recorded in
    `missing_dates.json` (it is stored as NaN and listed in the index), otherwise ChirpsIncompleteError is
    raised before anything is written.
    """
    raw_dir, out_dir = Path(raw_dir), Path(out_dir)
    days = sorted({_as_date(d) for d in dates})
    win = domain_window(cfg)
    recorded_missing = _read_dates(raw_dir / MISSING_DATES_FILE)
    missing = {d for d in days if not raw_path(raw_dir, d).exists()}
    unexplained = sorted(d.isoformat() for d in missing if d.isoformat() not in recorded_missing)
    if unexplained:
        raise ChirpsIncompleteError(
            f"{len(unexplained)} needed day(s) are neither downloaded nor recorded as missing "
            f"(first: {unexplained[:3]}); run the download first")
    missing_iso = {d.isoformat() for d in missing}
    out_dir.mkdir(parents=True, exist_ok=True)
    by_year: dict[int, list[date]] = {}
    for d in days:
        by_year.setdefault(d.year, []).append(d)
    index_path = out_dir / INDEX_FILE
    previous_missing: dict[int, list[str]] | None = None
    if index_path.exists():
        try:
            previous = json.loads(index_path.read_text(encoding="utf-8"))
            previous_missing = {int(y): v["missing_dates"] for y, v in previous["years"].items()}
        except (ValueError, KeyError, TypeError):
            previous_missing = None

    year_index: dict[int, dict] = {}
    for year, year_days in by_year.items():
        year_missing = [d.isoformat() for d in year_days if d.isoformat() in missing_iso]
        if not _year_is_current(out_dir, year, year_days, year_missing, win, previous_missing):
            stack = np.full((len(year_days), win["n_rows"], win["n_cols"]), np.nan, dtype=np.float16)
            present = [(i, d) for i, d in enumerate(year_days) if d.isoformat() not in missing_iso]

            def read(item):
                i, d = item
                data = read_domain_day(raw_path(raw_dir, d), win)
                peak = float(np.max(data, where=~np.isnan(data), initial=0.0))
                if not peak < FLOAT16_MAX:
                    raise ValueError(f"{d}: value {peak} does not fit float16")
                return i, data

            with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
                for i, data in pool.map(read, present):
                    stack[i] = data  # float32 -> float16; NaN stays NaN
            npy, dates_json = _year_paths(out_dir, year)
            dates_json.unlink(missing_ok=True)  # an array without a dates file is never "complete"
            _write_atomic(npy, lambda handle: np.save(handle, stack))
            _write_atomic(dates_json, lambda handle: handle.write(
                (json.dumps([d.isoformat() for d in year_days]) + "\n").encode("utf-8")))
            del stack
        stats = _year_stats(out_dir, year, year_days, set(year_missing))
        year_index[year] = {**stats, "missing_dates": year_missing}

    n_pixels = sum(v["n_pixels"] for v in year_index.values())
    n_nan = sum(v["n_nan_pixels"] for v in year_index.values())
    peak = max((v["max_value"] for v in year_index.values()), default=0.0)
    index = {
        "source": SOURCE, "units": "mm/day", "day_basis": "utc", "dtype": "float16",
        "bbox": cfg["domain_bbox"], "rows": win["n_rows"], "cols": win["n_cols"],
        "row_off": win["row_off"], "col_off": win["col_off"], "cell_deg": CELL_DEG,
        "days_per_year": {str(y): v["n_days"] for y, v in year_index.items()},
        "years": {str(y): v for y, v in year_index.items()},
        "missing_dates": sorted(missing_iso),
        "nan_share": (n_nan / n_pixels) if n_pixels else None,
        "nan_share_note": "share of NaN pixels over days that have a file (ocean and outside-coverage pixels)",
        "max_value": peak,
        "float16_relative_bound": FLOAT16_RELATIVE_BOUND,
        "float16_abs_bound_at_max": float(np.spacing(np.float16(peak))) / 2,
    }
    _write_atomic(index_path, lambda handle: handle.write((json.dumps(index, indent=1) + "\n").encode("utf-8")))
    return index


# ------------------------------------------------------------------------------------------ reader

class ChirpsStore:
    """Read-only, memory-mapped view of the cropped per-year arrays."""

    def __init__(self, processed_dir) -> None:
        processed_dir = Path(processed_dir)
        self.index = json.loads((processed_dir / INDEX_FILE).read_text(encoding="utf-8"))
        self._missing = set(self.index["missing_dates"])
        self._years: dict[int, tuple[np.ndarray, np.ndarray]] = {}
        self._dates: list[date] = []
        for year in sorted(int(y) for y in self.index["days_per_year"]):
            npy, dates_json = _year_paths(processed_dir, year)
            stamps = json.loads(dates_json.read_text(encoding="utf-8"))
            self._years[year] = (np.array(stamps, dtype="datetime64[D]"), np.load(npy, mmap_mode="r"))
            self._dates.extend(date.fromisoformat(s) for s in stamps if s not in self._missing)
        self._date_set = set(self._dates)

    def dates(self) -> list[date]:
        """Days that have data (days listed as missing are not included)."""
        return list(self._dates)

    def has_date(self, day) -> bool:
        return _as_date(day) in self._date_set

    def _pixel(self, cell_id: int) -> tuple[int, int]:
        row, col = cell_to_chirps_pixel(cell_id)
        row, col = row - self.index["row_off"], col - self.index["col_off"]
        if not (0 <= row < self.index["rows"] and 0 <= col < self.index["cols"]):
            raise ValueError(f"cell {cell_id} is outside the stored domain window")
        return row, col

    def cell_series(self, cell_id: int, start, end) -> np.ndarray:
        """float32 daily rainfall (mm) for start..end inclusive; NaN where the store has no value.

        NaN means unknown: day not in the store, day missing upstream, or a pixel CHIRPS does not cover.
        """
        first, last = np.datetime64(_as_date(start), "D"), np.datetime64(_as_date(end), "D")
        if last < first:
            raise ValueError("end is before start")
        wanted = np.arange(first, last + np.timedelta64(1, "D"), dtype="datetime64[D]")
        row, col = self._pixel(cell_id)
        out = np.full(len(wanted), np.nan, dtype=np.float32)
        for stamps, stack in self._years.values():
            pos = np.searchsorted(stamps, wanted)
            inside = pos < len(stamps)
            hit = np.zeros(len(wanted), dtype=bool)
            hit[inside] = stamps[pos[inside]] == wanted[inside]
            if hit.any():
                out[hit] = np.asarray(stack[pos[hit], row, col], dtype=np.float32)
        return out
