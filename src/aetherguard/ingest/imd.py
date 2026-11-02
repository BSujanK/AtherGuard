"""IMD gauge-based daily rainfall grid (0.25 deg, India only): download, read, store, nearest-point lookup.

Source file format (verified in the Phase 0 audit and again by the real-data tests): one binary `.grd` per year,
little-endian float32, shape (ndays, 129, 135) with ndays = 366 in leap years else 365, missing value -999.

Axes (NOT flipped anywhere): latitude index 0 = 6.5 N and increases northwards to index 128 = 38.5 N; longitude
index 0 = 66.5 E to index 134 = 100.0 E. The orientation was checked against known truth: Wayanad's nearest point
(11.5 N, 76.25 E) = index (20, 39) holds 179.24 mm on 2024-07-30 (the Phase 0 gauge audit value), whereas the
mirrored row holds 1.75 mm.

Day label convention: array index k of a year is day-of-year k+1, and the value labelled with calendar date D is
"IMD day D": 08:30 IST on D-1 to 08:30 IST on D (03:00 UTC on D-1 to 03:00 UTC on D). That is the convention
IMD uses for its gridded rainfall, but it is UNCONFIRMED here (no IMD documentation was checked for this grid);
treat it as the working assumption behind `ingest.align`.
"""
from __future__ import annotations

import contextlib
import io
import json
import math
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from ..grid import cell_center
from ..manifest import Manifest

LAT_MIN, LAT_MAX = 6.5, 38.5
LON_MIN, LON_MAX = 66.5, 100.0
STEP = 0.25
N_LAT, N_LON = 129, 135
MISSING_VALUE = -999.0
COVERAGE_MIN_VALID_SHARE = 0.95  # a covered cell is valid on MORE than this share of days in EVERY year

SOURCE = "IMD gridded rainfall 0.25 deg (via imdlib)"
URL = "https://imdpune.gov.in"
LICENCE = "IMD data terms (verify before redistribution)"

INDEX_NAME = "imd_index.json"
MASK_NAME = "imd_coverage_mask.npy"
_ORIENTATION = ("lat index 0 = 6.5 N, ascending northwards (not flipped); lon index 0 = 66.5 E, ascending eastwards; "
                "day index k = day-of-year k+1, labelled with that calendar date (IMD day, 08:30 IST D-1 to "
                "08:30 IST D; convention unconfirmed)")


class ImdError(RuntimeError):
    """Base class for IMD ingest errors."""


class ImdDownloadError(ImdError):
    """A yearly file could not be downloaded."""


class ImdFormatError(ImdError):
    """A yearly file does not have the verified layout; the layout is never guessed."""


class ImdStoreError(ImdError):
    """The processed store is missing, incomplete or does not cover the requested years."""


def days_in_year(year: int) -> int:
    return 366 if (year % 4 == 0 and year % 100 != 0) or year % 400 == 0 else 365


def expected_size_bytes(year: int) -> int:
    return days_in_year(year) * N_LAT * N_LON * 4


def imd_raw_path(raw_dir, year: int) -> Path:
    """Where imdlib (fn_format='yearwise') keeps the year's file: <raw_dir>/rain/<year>.grd."""
    return Path(raw_dir) / "rain" / f"{year}.grd"


def _year_file(year: int) -> str:
    return f"imd_{year}.npy"


def _check_years(start_year: int, end_year: int) -> None:
    if start_year > end_year:
        raise ValueError(f"start_year {start_year} is after end_year {end_year}")


# ------------------------------------------------------------------ download
@dataclass
class ImdDownloadReport:
    downloaded: list[int] = field(default_factory=list)
    skipped: list[int] = field(default_factory=list)     # present, exact size, manifest-current
    registered: list[int] = field(default_factory=list)  # present, exact size, newly added to the manifest
    failed: dict[int, str] = field(default_factory=dict)


def _imdlib_fetch(year: int, raw_dir: Path) -> None:
    """Download one year with imdlib; its prints and its swallowed HTTP errors become exceptions."""
    try:
        import imdlib
    except ImportError as exc:
        raise ImdDownloadError("imdlib is not installed (pip install -e .[audit])") from exc
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        imdlib.get_data("rain", year, year, fn_format="yearwise", file_dir=str(raw_dir))
    path = imd_raw_path(raw_dir, year)
    if not path.is_file():
        raise ImdDownloadError(f"imdlib wrote no file for {year}: {output.getvalue().strip() or 'no output'}")


def _discard(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def download_imd_years(start_year: int, end_year: int, raw_dir, manifest: Manifest,
                       fetch: Callable[[int, Path], None] | None = None) -> ImdDownloadReport:
    """Download the yearly files into `raw_dir` (idempotent) and register each one in the manifest.

    A year is skipped when its file exists with the exact expected byte size and is manifest-current. A complete file
    that the manifest does not know is registered without fetching. A file of the wrong size, or one whose checksum
    no longer matches its manifest entry, is deleted and fetched again (imdlib would keep any file over 1 KiB).
    A downloaded file of the wrong size is deleted and counted as failed. A failing year never stops the others;
    failures are returned in `report.failed` as {year: message}.
    """
    _check_years(start_year, end_year)
    raw_dir = Path(raw_dir)
    fetch = fetch or _imdlib_fetch
    report = ImdDownloadReport()
    for year in range(start_year, end_year + 1):
        path = imd_raw_path(raw_dir, year)
        expected = expected_size_bytes(year)
        if path.is_file() and path.stat().st_size == expected:
            if manifest.is_current(path):
                report.skipped.append(year)
                continue
            if manifest.relpath(path) not in manifest.entries():
                manifest.add(path, SOURCE, URL, LICENCE)
                report.registered.append(year)
                continue
        if path.exists():
            _discard(path)
        error = None
        try:
            fetch(year, raw_dir)
        except Exception as exc:  # per-year isolation: recorded below, unless a valid file was written anyway
            error = f"{type(exc).__name__}: {exc}"
        if not path.is_file():
            report.failed[year] = error or "fetcher produced no file"
            continue
        size = path.stat().st_size
        if size != expected:
            _discard(path)
            report.failed[year] = f"downloaded file is {size} bytes, expected {expected}" + (
                f" ({error})" if error else "")
            continue
        try:
            manifest.add(path, SOURCE, URL, LICENCE)
        except Exception as exc:
            report.failed[year] = f"cannot record {path} in the manifest: {exc}"
            continue
        report.downloaded.append(year)
    return report


# ------------------------------------------------------------------ read
def read_imd_year(path, year: int) -> np.ndarray:
    """Read one year as float32 (ndays, 129, 135); -999 and any other negative value become NaN.

    The byte size must equal ndays * 129 * 135 * 4 exactly (ImdFormatError otherwise); nothing is inferred.
    """
    path = Path(path)
    try:
        size = path.stat().st_size
    except FileNotFoundError as exc:
        raise ImdFormatError(f"IMD file for {year} not found: {path}") from exc
    expected = expected_size_bytes(year)
    if size != expected:
        raise ImdFormatError(
            f"{path}: IMD file for {year} is {size} bytes, expected {expected} "
            f"({days_in_year(year)} days x {N_LAT} x {N_LON} float32)")
    data = np.fromfile(path, dtype="<f4").reshape(days_in_year(year), N_LAT, N_LON)
    data = data.astype(np.float32, copy=False)  # native byte order
    data[data < 0] = np.nan  # covers the -999 missing marker and any other negative
    return data


# ------------------------------------------------------------------ store
def _save_npy_atomic(path: Path, array: np.ndarray) -> None:
    partial = path.with_name(path.name + ".part")
    try:
        with partial.open("wb") as handle:
            np.save(handle, array)
        os.replace(partial, path)
    finally:
        _discard(partial)


def build_imd_store(raw_dir, out_dir, start_year: int, end_year: int) -> dict:
    """Convert the raw yearly files into `imd_<year>.npy` (float32, NaN = missing) plus index and coverage mask.

    The coverage mask (`imd_coverage_mask.npy`, bool (129, 135)) marks grid points valid on more than 95 % of the
    days in EVERY processed year: the India gauge-coverage mask. `imd_index.json` is written last, so its presence
    means the store is complete. Returns the index dict.
    """
    _check_years(start_year, end_year)
    raw_dir, out_dir = Path(raw_dir), Path(out_dir)
    years = list(range(start_year, end_year + 1))
    missing = [y for y in years if not imd_raw_path(raw_dir, y).is_file()]
    if missing:
        raise ImdStoreError(f"raw IMD files missing for years {missing} under {raw_dir} (run the download first)")
    out_dir.mkdir(parents=True, exist_ok=True)
    _discard(out_dir / INDEX_NAME)  # a rebuild must never leave the old index describing new arrays
    coverage = np.ones((N_LAT, N_LON), dtype=bool)
    per_year: dict[str, dict] = {}
    for year in years:
        data = read_imd_year(imd_raw_path(raw_dir, year), year)
        valid_days = np.count_nonzero(~np.isnan(data), axis=0)
        coverage &= valid_days > COVERAGE_MIN_VALID_SHARE * data.shape[0]
        _save_npy_atomic(out_dir / _year_file(year), data)
        per_year[str(year)] = {
            "file": _year_file(year),
            "shape": list(data.shape),
            "nan_share": float(np.count_nonzero(np.isnan(data)) / data.size),
        }
    _save_npy_atomic(out_dir / MASK_NAME, coverage)
    index = {
        "source": SOURCE,
        "grid": {"lat_min": LAT_MIN, "lat_max": LAT_MAX, "lon_min": LON_MIN, "lon_max": LON_MAX,
                 "step": STEP, "n_lat": N_LAT, "n_lon": N_LON},
        "orientation": _ORIENTATION,
        "missing_value_in_source": MISSING_VALUE,
        "coverage_min_valid_share": COVERAGE_MIN_VALID_SHARE,
        "coverage_mask": MASK_NAME,
        "covered_cells": int(coverage.sum()),
        "years": per_year,
    }
    partial = out_dir / (INDEX_NAME + ".part")
    try:
        partial.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        os.replace(partial, out_dir / INDEX_NAME)
    finally:
        _discard(partial)
    return index


def _as_day(value, name: str) -> date:
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is not None or stamp != stamp.normalize():
        raise ValueError(f"{name} must be a timezone-naive calendar date, got {value!r}")
    return stamp.date()


class ImdGrid:
    """Lazy reader of the processed store (year arrays are memory-mapped on first use).

    Values are float32 mm per IMD day (see the module docstring for the day label convention); NaN = missing.
    """

    def __init__(self, processed_dir) -> None:
        self.processed_dir = Path(processed_dir)
        index_path = self.processed_dir / INDEX_NAME
        try:
            self._index = json.loads(index_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ImdStoreError(f"{INDEX_NAME} not found in {self.processed_dir} (build the IMD store first)") from exc
        self._years = {int(year): meta for year, meta in self._index["years"].items()}
        self._arrays: dict[int, np.ndarray] = {}
        self._mask: np.ndarray | None = None

    @property
    def years(self) -> list[int]:
        return sorted(self._years)

    @property
    def covered_cells(self) -> int:
        return int(self._index["covered_cells"])

    @staticmethod
    def nearest_index(lat: float, lon: float) -> tuple[int, int] | None:
        """(lat index, lon index) of the nearest 0.25 deg grid point, or None outside the grid.

        Coordinates are rounded to the nearest grid point; an exact tie (e.g. 11.625 N, halfway between 11.5 and
        11.75) goes to the HIGHER index (northern / eastern point), robust to floating-point noise of ~1e-6 cells.
        So the grid covers lat [6.375, 38.625) and lon [66.375, 100.125): a coordinate whose nearest index would be
        outside 0..128 / 0..134 returns None.
        """
        if not (math.isfinite(lat) and math.isfinite(lon)):
            raise ValueError(f"latitude and longitude must be finite, got {lat}, {lon}")
        i = math.floor(round((lat - LAT_MIN) / STEP, 6) + 0.5)
        j = math.floor(round((lon - LON_MIN) / STEP, 6) + 0.5)
        if 0 <= i < N_LAT and 0 <= j < N_LON:
            return i, j
        return None

    def is_covered(self, lat: float, lon: float) -> bool:
        """True when the nearest grid point is in the coverage mask (gauge data on > 95 % of days every year)."""
        point = self.nearest_index(lat, lon)
        if point is None:
            return False
        if self._mask is None:
            mask_path = self.processed_dir / self._index["coverage_mask"]
            try:
                self._mask = np.load(mask_path)
            except FileNotFoundError as exc:
                raise ImdStoreError(f"coverage mask {mask_path} is missing") from exc
        return bool(self._mask[point])

    def _array(self, year: int) -> np.ndarray:
        if year not in self._arrays:
            path = self.processed_dir / self._years[year]["file"]
            try:
                array = np.load(path, mmap_mode="r")
            except FileNotFoundError as exc:
                raise ImdStoreError(f"{path.name} is listed in {INDEX_NAME} but missing from {path.parent}") from exc
            if array.shape != (days_in_year(year), N_LAT, N_LON):
                raise ImdStoreError(f"{path} has shape {array.shape}, expected "
                                    f"{(days_in_year(year), N_LAT, N_LON)}")
            self._arrays[year] = array
        return self._arrays[year]

    def series(self, lat: float, lon: float, start_date, end_date) -> np.ndarray:
        """Daily float32 values at the nearest grid point for start_date..end_date inclusive, across years.

        NaN where the grid point has no data that day, and for every day when the point is outside the grid. A
        requested year that is not in the store raises ImdStoreError (never NaN: an absent year is not missing data).
        """
        start, end = _as_day(start_date, "start_date"), _as_day(end_date, "end_date")
        if start > end:
            raise ValueError(f"start_date {start} is after end_date {end}")
        absent = [y for y in range(start.year, end.year + 1) if y not in self._years]
        if absent:
            raise ImdStoreError(f"years {absent} are not in the IMD store (has {self.years})")
        out = np.full((end - start).days + 1, np.nan, dtype=np.float32)
        point = self.nearest_index(lat, lon)
        if point is None:
            return out
        for year in range(start.year, end.year + 1):
            first, last = max(start, date(year, 1, 1)), min(end, date(year, 12, 31))
            k0, k1 = first.timetuple().tm_yday - 1, last.timetuple().tm_yday
            out[(first - start).days:(last - start).days + 1] = self._array(year)[k0:k1, point[0], point[1]]
        return out

    def cell_series(self, cell_id: int, start_date, end_date) -> np.ndarray:
        """`series` at the centre of a 0.05 deg cell (aetherguard.grid cell id)."""
        lat, lon = cell_center(int(cell_id))
        return self.series(lat, lon, start_date, end_date)
