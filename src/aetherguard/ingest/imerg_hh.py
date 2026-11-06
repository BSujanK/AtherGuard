"""NASA GPM IMERG V07 half-hourly rain (HHL Late, HHE Early) reduced to daily rain-intensity fields.

Used by the W3 rain-intensity challenger (docs/superpowers/specs/2026-11-06-aetherguard-w3-rain-intensity.md, section 1).

Access path (measured by the W3 pilot): the half-hourly granule is found through CMR (its Hyrax OPeNDAP link comes from
CMR and is never constructed, the version letter varies) and the domain crop of /Grid/precipitation is requested as a
DAP4 subset with the index box of the daily store (`imerg.CONSTRAINT`'s box: 260 lon x 280 lat). About 89 KB and
0.6 s per half-hour at 4 parallel connections. Auth is the Earthdata login from the user's netrc, one
requests.Session per worker thread; credentials and redirect URLs are never logged or stored.

IMD day D = the 48 half-hours that start at 03:00 UTC on D-1 through 02:30 UTC on D. `reduce_day` turns them into
the per-pixel maxima of the 1, 3 and 6 hour rain and the wet duration. Orientation is that of `imerg.ImergStore`:
fields are [half-hour, row, col] with row = latitude south -> north and col = longitude west -> east (the file holds
(time, lon, lat); `_decode` transposes it).

A half-hour that is missing (not in CMR, or not fetched after the retries) is NaN, and NaN is contagious: every
rolling window and every wet count that contains it is NaN for that pixel, so a gap is never read as dry.

Layout: `<root>/<run>/<yyyy>/<yyyymmdd>.npz` with float32 maps max1h, max3h, max6h (mm), wet_hours (h) and
n_halfhours (finite half-hours per pixel; 48 for a complete day). A day file is written atomically once the day is
reduced and the raw subsets are never kept, so re-running the same command resumes where it stopped.

CLI: python -m aetherguard.ingest.imerg_hh --run late|early --start YYYY-MM-DD --end YYYY-MM-DD [--months 6-9]
[--workers 4] [--root DIR]
"""
from __future__ import annotations

import argparse
import io
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import requests

from ..config import data_root
from ..http import DownloadError, fetch_json
from ..manifest import Manifest
from . import imerg

log = logging.getLogger(__name__)

# Half-hourly collections (GES DISC), measured by the W3 pilot.
CONCEPT_IDS = {"late": "C2723754845-GES_DISC", "early": "C2723758340-GES_DISC"}
SHORT_NAMES = {"late": "GPM_3IMERGHHL", "early": "GPM_3IMERGHHE"}

HALF_HOURS = 48                       # per IMD day
SLOT = timedelta(minutes=30)
DAY_START_HOUR_UTC = 3                # an IMD day starts at 03:00 UTC on the previous calendar day
HOURS_PER_SLOT = 0.5
WINDOW_SLOTS = {"max1h": 2, "max3h": 6, "max6h": 12}
WET_MM_PER_H = np.float32(0.1)

MAX_WORKERS = 4                       # politeness limit; the daily live run downloads from the same server
ABORT_AFTER = imerg.ABORT_AFTER       # consecutive failed days before a build stops asking (credentials, outage)
TIMEOUT_S = 120
CMR_PAGE_SIZE = 200                   # 48 half-hours per day, at most a few versions each
VARIABLE_PATH = "/Grid/precipitation"
_HEADERS = {"User-Agent": "AetherGuard/0.1 (research prototype)", "Accept-Encoding": "identity"}
_BOX_LON = f"[{imerg.GLOBAL_LON0}:{imerg.GLOBAL_LON0 + imerg.COLS - 1}]"
_BOX_LAT = f"[{imerg.GLOBAL_LAT0}:{imerg.GLOBAL_LAT0 + imerg.ROWS - 1}]"
CONSTRAINT = (f"dap4.ce={VARIABLE_PATH}[0]{_BOX_LON}{_BOX_LAT};/Grid/time;/Grid/lon{_BOX_LON};/Grid/lat{_BOX_LAT}")


class BuildAborted(RuntimeError):
    """A build stopped after too many consecutive failed days (rejected credentials or an outage)."""


class SubsetFormatError(ValueError):
    """A downloaded body is not the expected domain subset (a login page, a truncated or foreign file)."""


def _check_run(run: str) -> str:
    if run not in CONCEPT_IDS:
        raise ValueError(f"run must be one of {tuple(CONCEPT_IDS)}, got {run!r}")
    return run


# ------------------------------------------------------------------------------------------ reduction

def reduce_day(fields: np.ndarray, n_expected: int = HALF_HOURS) -> dict[str, np.ndarray]:
    """Daily intensity maps from the half-hourly rain rates of one IMD day.

    `fields` is (n_expected, 280, 260) mm/h in store orientation (row = latitude south -> north, col = longitude
    west -> east), the half-hours in time order starting at the beginning of the IMD day. A complete day has 48. A
    live run whose newest half-hours have not been published yet passes the half-hours it has and the same number
    as `n_expected`; the windows then simply end earlier. Fewer fields without a matching `n_expected` are refused.

    Returns float32 (280, 260) maps:
      max1h, max3h, max6h  largest rain (mm) in any 1, 3 or 6 consecutive hours (rolling sums of 2, 6 and 12
                           half-hours x 0.5 h) lying inside the available half-hours; NaN where no window fits
      wet_hours            hours (count x 0.5) with at least 0.1 mm/h
      n_halfhours          finite half-hours at the pixel

    A non-finite half-hour makes every maximum and the wet duration NaN for that pixel (a gap is never dry).
    """
    if not 1 <= n_expected <= HALF_HOURS:
        raise ValueError(f"n_expected must be between 1 and {HALF_HOURS}, got {n_expected}")
    fields = np.asarray(fields)
    if fields.shape != (n_expected, imerg.ROWS, imerg.COLS):
        raise ValueError(f"fields must have shape {(n_expected, imerg.ROWS, imerg.COLS)} "
                         f"({HALF_HOURS} half-hours unless n_expected says fewer), got {fields.shape}")
    fields = fields.astype(np.float32, copy=False)
    out: dict[str, np.ndarray] = {}
    for name, width in WINDOW_SLOTS.items():
        n_windows = n_expected - width + 1
        if n_windows < 1:
            out[name] = np.full((imerg.ROWS, imerg.COLS), np.nan, dtype=np.float32)
            continue
        sums = fields[:n_windows].copy()
        for offset in range(1, width):
            sums += fields[offset:offset + n_windows]
        out[name] = (sums.max(axis=0) * np.float32(HOURS_PER_SLOT)).astype(np.float32)   # NaN propagates
    finite = np.isfinite(fields)
    wet = (fields >= WET_MM_PER_H).sum(axis=0) * np.float32(HOURS_PER_SLOT)
    out["wet_hours"] = np.where(finite.all(axis=0), wet, np.nan).astype(np.float32)
    out["n_halfhours"] = finite.sum(axis=0).astype(np.float32)
    return out


# ------------------------------------------------------------------------------------------ CMR

def day_window(day: date) -> tuple[datetime, datetime]:
    """First half-hour start and the last instant of the IMD day `day` (UTC)."""
    first = datetime(day.year, day.month, day.day, DAY_START_HOUR_UTC, tzinfo=timezone.utc) - timedelta(days=1)
    return first, first + HALF_HOURS * SLOT - timedelta(seconds=1)


def _half_hour_links(run: str, day: date) -> dict[int, str]:
    """Hyrax link of every half-hour CMR lists for the IMD day, keyed by slot 0..47 (the latest update wins)."""
    first, last = day_window(day)
    params = {"collection_concept_id": CONCEPT_IDS[_check_run(run)], "sort_key": "start_date",
              "page_size": CMR_PAGE_SIZE,
              "temporal": f"{first:%Y-%m-%dT%H:%M:%SZ},{last:%Y-%m-%dT%H:%M:%SZ}"}
    entries = fetch_json(imerg.CMR_URL, params=params, retries=imerg.RETRIES, backoff=imerg.BACKOFF_S)["feed"]["entry"]
    found: dict[int, tuple[str, str]] = {}
    for entry in entries:
        start = datetime.fromisoformat(entry["time_start"].replace("Z", "+00:00")).astimezone(timezone.utc)
        slot, remainder = divmod(start - first, SLOT)
        link = next((item["href"] for item in entry.get("links", [])
                     if "/collections/" in item.get("href", "") and "/granules/" in item["href"]), None)
        if remainder or not 0 <= slot < HALF_HOURS or link is None:
            continue
        updated = entry.get("updated", "")
        if slot not in found or updated >= found[slot][1]:
            found[slot] = (link, updated)
    return {slot: link for slot, (link, _) in sorted(found.items())}


def granules(run: str, day: date) -> list[str]:
    """Hyrax OPeNDAP links of the half-hourly granules of the IMD day, in time order (CMR, never constructed)."""
    return list(_half_hour_links(run, day).values())


def subset_url(link: str) -> str:
    """DAP4 subset of one half-hourly granule: the domain box of the daily store, with its coordinate variables."""
    return f"{link}.dap.nc4?{CONSTRAINT}"


# ------------------------------------------------------------------------------------------ one half-hour

def _decode(data: bytes) -> np.ndarray:
    """A subset body as float32 (rows, cols) in store orientation; fill and negative values become NaN."""
    import h5netcdf
    try:
        with h5netcdf.File(io.BytesIO(data), "r") as handle:
            grid = handle["Grid"]
            raw = grid["precipitation"]
            if tuple(raw.dimensions) != imerg.FILE_DIMS or raw.shape != (1, imerg.COLS, imerg.ROWS):
                raise SubsetFormatError(f"unexpected dimensions {tuple(raw.dimensions)} or shape {raw.shape}")
            if not (np.allclose(grid["lat"][:], imerg.domain_lat(), atol=imerg.COORD_TOLERANCE)
                    and np.allclose(grid["lon"][:], imerg.domain_lon(), atol=imerg.COORD_TOLERANCE)):
                raise SubsetFormatError("coordinates are not the domain grid")
            values = np.ascontiguousarray(np.asarray(raw[0]).T, dtype=np.float32)
    except SubsetFormatError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise SubsetFormatError(f"not a netCDF4 subset ({type(exc).__name__})") from exc
    values[~np.isfinite(values) | (values < 0)] = np.nan
    return values


def _fetch_half_hour(link: str, session: requests.Session) -> np.ndarray:
    """One half-hour as (rows, cols) mm/h. Transport errors, HTTP 429/5xx and undecodable bodies are retried with
    backoff; other HTTP errors fail at once. The error text never contains the URL."""
    url = subset_url(link)
    error: DownloadError | None = None
    for attempt in range(imerg.RETRIES):
        try:
            response = session.get(url, timeout=TIMEOUT_S, headers=_HEADERS)
            status = response.status_code
            if status == 429 or status >= 500:
                error = DownloadError(f"HTTP {status}", retriable=True, status=status)
            elif status >= 400:
                raise DownloadError(f"HTTP {status}", retriable=False, status=status)
            else:
                return _decode(response.content)
        except requests.RequestException as exc:
            error = DownloadError(type(exc).__name__, retriable=True)
        except SubsetFormatError as exc:
            error = DownloadError(str(exc), retriable=True)
        if attempt < imerg.RETRIES - 1:
            time.sleep(imerg.BACKOFF_S * 2 ** attempt)
    raise error


# ------------------------------------------------------------------------------------------ the build

def _day_path(root: Path, run: str, day: date) -> Path:
    return root / run / f"{day.year}" / f"{day:%Y%m%d}.npz"


def _write_day(path: Path, maps: dict[str, np.ndarray]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    with part.open("wb") as handle:
        np.savez_compressed(handle, **maps)
    os.replace(part, path)


def _record(manifest: Manifest, path: Path, run: str) -> None:
    source = f"NASA GPM IMERG V07 half-hourly {run} run ({SHORT_NAMES[run]}), reduced to IMD-day intensity maxima"
    manifest.add(path, source, f"{imerg.CMR_URL}?collection_concept_id={CONCEPT_IDS[run]}", imerg.LICENCE)


def _reduce_from_archive(run: str, day: date, pool: ThreadPoolExecutor, sessions: imerg._Sessions) -> dict:
    """Fetch the half-hours of the IMD day, in parallel, and reduce them. Raises DownloadError when CMR fails or
    when not a single half-hour could be had."""
    links = _half_hour_links(run, day)
    first, _ = day_window(day)
    fields = np.full((HALF_HOURS, imerg.ROWS, imerg.COLS), np.nan, dtype=np.float32)
    futures = {slot: pool.submit(lambda link=link: _fetch_half_hour(link, sessions.get()))
               for slot, link in links.items()}
    got = 0
    for slot in range(HALF_HOURS):
        stamp = f"{first + slot * SLOT:%Y-%m-%d %H:%M} UTC"
        if slot not in futures:
            log.warning("%s %s: half-hour %s is not listed by CMR; its windows are NaN", run, day, stamp)
            continue
        try:
            fields[slot] = futures[slot].result()
            got += 1
        except DownloadError as exc:
            log.warning("%s %s: half-hour %s not fetched (%s); its windows are NaN", run, day, stamp, exc)
    if not got:
        raise DownloadError("no half-hour of the day could be fetched", retriable=True)
    return reduce_day(fields)


def build(run: str, start: date, end: date, root, workers: int = MAX_WORKERS, *, months=None,
          manifest: Manifest | None = None) -> None:
    """Reduce every IMD day in [start, end] (restricted to `months`, a set of month numbers, when given) of the
    half-hourly `run` archive into `<root>/<run>/<yyyy>/<yyyymmdd>.npz`; resumable.

    Days with a day file are skipped (and recorded in the manifest if they are not yet). A day on which no
    half-hour could be had is not written, is logged and counts as failed; `ABORT_AFTER` consecutive failed days
    raise BuildAborted. Half-hours missing on an otherwise fetched day are NaN (logged), never dry.
    """
    _check_run(run)
    if not 1 <= workers <= MAX_WORKERS:
        raise ValueError(f"workers must be between 1 and {MAX_WORKERS}, got {workers}")
    if end < start:
        raise ValueError(f"empty range: {start} is after {end}")
    root = Path(root)
    manifest = manifest if manifest is not None else Manifest(imerg.MANIFEST_PATH, data_root())
    days = [start + timedelta(k) for k in range((end - start).days + 1)]
    if months is not None:
        days = [d for d in days if d.month in months]
    log.info("%s: %d IMD days %s..%s, %d workers, root %s", run, len(days), start, end, workers, root)
    sessions = imerg._Sessions()
    consecutive = skipped = written = failed = 0
    began = time.monotonic()
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for number, day in enumerate(days, start=1):
                path = _day_path(root, run, day)
                if path.exists():
                    if not manifest.is_current(path):     # a crash between the write and the record
                        _record(manifest, path, run)
                    skipped += 1
                    continue
                started = time.monotonic()
                try:
                    maps = _reduce_from_archive(run, day, pool, sessions)
                except DownloadError as exc:
                    failed += 1
                    consecutive += 1
                    log.error("%s %s: day failed (%s); %d consecutive", run, day, exc, consecutive)
                    if consecutive >= ABORT_AFTER:
                        raise BuildAborted(f"{consecutive} consecutive failed days, last {day}: {exc}") from exc
                    continue
                consecutive = 0
                _write_day(path, maps)
                try:
                    _record(manifest, path, run)
                except Exception:
                    path.unlink(missing_ok=True)      # never leave a data file without a manifest entry
                    raise
                written += 1
                log.info("%s %s: written, %d/%d half-hours, %.0f s (day %d/%d, skipped %d, failed %d, %.1f h elapsed)",
                         run, day, int(maps["n_halfhours"].max()), HALF_HOURS, time.monotonic() - started,
                         number, len(days), skipped, failed, (time.monotonic() - began) / 3600)
    finally:
        sessions.close()
    log.info("%s: done, %d written, %d already present, %d failed", run, written, skipped, failed)


# ------------------------------------------------------------------------------------------ CLI

def parse_months(text: str) -> set[int]:
    """'6-9' -> {6, 7, 8, 9}; '7' -> {7}. Raises ValueError for anything else."""
    low, _, high = text.partition("-")
    first, last = int(low), int(high or low)
    if not 1 <= first <= last <= 12:
        raise ValueError(f"months must be M or M-M within 1..12, got {text!r}")
    return set(range(first, last + 1))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reduce IMERG half-hourly rain to daily intensity fields per IMD day.")
    parser.add_argument("--run", choices=tuple(CONCEPT_IDS), required=True, help="late (HHL) or early (HHE)")
    parser.add_argument("--start", type=date.fromisoformat, required=True, help="first IMD day, YYYY-MM-DD")
    parser.add_argument("--end", type=date.fromisoformat, required=True, help="last IMD day, YYYY-MM-DD")
    parser.add_argument("--months", type=parse_months, help="only these months of the year, e.g. 6-9")
    parser.add_argument("--workers", type=int, default=MAX_WORKERS, help=f"parallel requests, 1..{MAX_WORKERS}")
    parser.add_argument("--root", type=Path, default=None,
                        help="output directory (default: <data root>/processed/imerg_intensity)")
    args = parser.parse_args(argv)
    if not 1 <= args.workers <= MAX_WORKERS:
        parser.error(f"--workers must be between 1 and {MAX_WORKERS} (the politeness limit)")
    if args.end < args.start:
        parser.error(f"empty range: {args.start} is after {args.end}")
    logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    root = args.root if args.root is not None else data_root() / "processed" / "imerg_intensity"
    try:
        build(args.run, args.start, args.end, root, workers=args.workers, months=args.months)
    except BuildAborted as exc:
        print(f"aborted: {exc}; re-run the same command to resume", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
