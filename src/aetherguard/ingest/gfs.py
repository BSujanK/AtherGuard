"""NOAA GFS 0.25-degree precipitation forecasts -> IMD-day totals for D+1..D+3 on the 0.1-degree IMERG grid.

Day basis: IMD day X = (03:00 UTC on X-1, 03:00 UTC on X] (08:30 IST on X-1 to 08:30 IST on X), labelled by X.
For a forecast issued on IMD day D the three forecast days are D+1, D+2, D+3.

GFS APCP (kg m-2 = mm) is a running accumulation. In the pgrb2 files every forecast hour carries two APCP messages:
a bucket that restarts every 6 h (`0-3`, `0-6`, `6-9`, `6-12`, `12-15`, `12-18`, ...) and the cumulative `0-H`
message (verified on real NOMADS and AWS files, reports/phase6_live_sources_probe.md). The cumulative message is used
directly; `cumulative_from_messages` also rebuilds the cumulative series from bucket messages alone, so a file that
lacks the `0-H` message does not lose its hour as long as the earlier hours are present.

Access paths (configs/live.yaml, section `gfs`):
* live: NOMADS grib filter, one request per forecast hour, domain crop done by the server (last ~10 days only);
* archive: AWS Open Data `noaa-gfs-bdp-pds`, the global file is never downloaded; the `.idx` gives the byte range of
  the cumulative APCP record, which is fetched with an HTTP Range request and cropped after decoding.

Missing data is explicit: a forecast hour that cannot be fetched or decoded makes every IMD day whose window ends or
starts at that hour NaN (never zero) and is listed in the day file (`missing_hours`, `day_valid`) and in
`gfs_gaps.json` next to it.
"""
from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, time as clock, timedelta, timezone
from pathlib import Path
from typing import NamedTuple

import numpy as np
import requests

from ..config import data_root
from ..http import DownloadError
from ..live.probe import apcp_byte_ranges, parse_idx, parse_nomads_listing
from ..manifest import Manifest
from ..urlredact import redact_url

SOURCE_LIVE = "NOAA GFS 0.25 deg APCP via NOMADS grib filter"
SOURCE_ARCHIVE = "NOAA GFS 0.25 deg APCP via AWS Open Data noaa-gfs-bdp-pds (.idx byte range)"
LICENCE = "NOAA/NCEP open data, no restrictions (https://www.nws.noaa.gov/disclaimer.html)"
GAPS_FILE = "gfs_gaps.json"
MANIFEST_PATH = Path(__file__).resolve().parents[3] / "manifests" / "data_manifest.jsonl"

UTC = timezone.utc
IMD_DAY_END_UTC_HOUR = 3        # an IMD day ends at 03:00 UTC (08:30 IST)
LEAD_DAYS = (1, 2, 3)
CYCLE_STEP_HOURS = 6
MAX_CYCLES_BACK = 4             # newest cycle plus three older ones are tried before giving up
GRIB_MAGIC = b"GRIB"
IST = timezone(timedelta(hours=5, minutes=30))

# The 0.1-degree IMERG domain grid (cell centres; rows south -> north, columns west -> east); documented in
# configs/live.yaml (`domain_grid`) and checked against it by tests/test_ingest_gfs.py.
GRID_STEP = 0.1
TARGET_LATS = np.round(8.05 + GRID_STEP * np.arange(280), 6)
TARGET_LONS = np.round(72.05 + GRID_STEP * np.arange(260), 6)

_HEADERS = {"User-Agent": "AetherGuard/0.1 (research prototype)", "Accept-Encoding": "identity"}
_ECCODES_LOCK = threading.Lock()  # eccodes handles are not shared across threads; decoding a field takes milliseconds
_EDGE_TOLERANCE = 1e-6


class NoCompleteCycleError(RuntimeError):
    """None of the most recent GFS cycles has its last forecast hour published."""


class GfsFetchError(RuntimeError):
    """Nothing usable could be fetched for a forecast."""


class GribDecodeError(ValueError):
    """Bytes that are not a readable GRIB2 APCP field."""


class NotPublishedError(DownloadError):
    """The requested file (or record) does not exist (yet): HTTP 404, an HTML error page, or no 0-H record."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message, retriable=False, status=status)


# ------------------------------------------------------------------------------------------------ time rules

def _require_utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        raise ValueError("time must be timezone-aware (UTC)")
    return moment.astimezone(UTC)


def latest_complete_cycle(now_utc: datetime, published: Callable[[datetime], bool]) -> datetime:
    """Newest GFS cycle (00/06/12/18Z, not after `now_utc`) for which `published(cycle)` says f096 APCP exists.

    A cycle that is not complete is skipped for the previous one; after `MAX_CYCLES_BACK` cycles the search stops.
    """
    now = _require_utc(now_utc)
    cycle = now.replace(hour=now.hour - now.hour % CYCLE_STEP_HOURS, minute=0, second=0, microsecond=0)
    for _ in range(MAX_CYCLES_BACK):
        if published(cycle):
            return cycle
        cycle -= timedelta(hours=CYCLE_STEP_HOURS)
    raise NoCompleteCycleError(
        f"none of the last {MAX_CYCLES_BACK} cycles up to {now:%Y-%m-%d %H:%M} UTC has its last forecast hour published")


def imd_day_windows(cycle: datetime, issue_day: date) -> list[tuple[int, int]]:
    """(start, end) lead hours of IMD days D+1..D+3, where IMD day X = (03:00 UTC X-1, 03:00 UTC X].

    A negative start means the window opens before the cycle begins: no forecast covers it.
    """
    cycle = _require_utc(cycle)
    windows = []
    for lead in LEAD_DAYS:
        end = datetime.combine(issue_day + timedelta(days=lead), clock(IMD_DAY_END_UTC_HOUR), tzinfo=UTC)
        start = end - timedelta(days=1)
        windows.append((int((start - cycle).total_seconds() // 3600), int((end - cycle).total_seconds() // 3600)))
    return windows


def required_hours(cycle: datetime, issue_day: date) -> list[int]:
    """Forecast hours whose cumulative field the three IMD days need (hour 0 is zero by definition)."""
    return sorted({h for window in imd_day_windows(cycle, issue_day) for h in window if h > 0})


# ------------------------------------------------------------------------- bucket -> cumulative -> IMD days

def cumulative_from_messages(messages: dict[int, tuple[int, int, np.ndarray]]) -> dict[int, np.ndarray]:
    """Cumulative 0-H totals by forecast hour from {hour: (step_start, step_end, field)}.

    A message starting at 0 already is the cumulative total. A bucket (start > 0, e.g. `6-9`) is added to the
    cumulative total at its start hour; if that hour is unknown (missing, or itself lost), the hour is left out
    rather than guessed.
    """
    cumulative: dict[int, np.ndarray] = {}
    for hour in sorted(messages):
        start, end, field = messages[hour]
        if end != hour:
            raise ValueError(f"the message for forecast hour {hour} ends at hour {end}")
        if start == 0:
            cumulative[hour] = np.asarray(field, dtype=np.float32)
        elif start in cumulative:
            cumulative[hour] = cumulative[start] + np.asarray(field, dtype=np.float32)
    return cumulative


def _window_fields(cumulative: dict[int, np.ndarray], window: tuple[int, int]):
    start, end = window
    if start < 0 or end not in cumulative:
        return None
    if start == 0:
        return np.zeros_like(cumulative[end]), cumulative[end]
    if start not in cumulative:
        return None
    return cumulative[start], cumulative[end]


def apcp_imd_days(cumulative: dict[int, np.ndarray], cycle: datetime, issue_day: date) -> np.ndarray:
    """(3, ny, nx) float32 mm for IMD days D+1, D+2, D+3 from cumulative 0-H fields keyed by lead hour.

    A day whose window starts before the cycle, or whose start or end hour is missing, is NaN. Differences of the
    packed cumulative fields can come out a hair below zero; those are clipped to 0 (rain cannot be negative).
    """
    if not cumulative:
        raise ValueError("no cumulative field given")
    shape = next(iter(cumulative.values())).shape
    out = np.full((len(LEAD_DAYS),) + shape, np.nan, dtype=np.float32)
    for i, window in enumerate(imd_day_windows(cycle, issue_day)):
        fields = _window_fields(cumulative, window)
        if fields is not None:
            out[i] = np.maximum(fields[1] - fields[0], 0.0)
    return out


def imd_day_valid(cumulative: dict[int, np.ndarray], cycle: datetime, issue_day: date) -> np.ndarray:
    """Bool (3,): True where the day could be computed from the available hours."""
    return np.array([_window_fields(cumulative, w) is not None for w in imd_day_windows(cycle, issue_day)])


def missing_hours(cumulative: dict[int, np.ndarray], cycle: datetime, issue_day: date) -> list[int]:
    """Forecast hours the three days need that are absent from `cumulative`."""
    return [h for h in required_hours(cycle, issue_day) if h not in cumulative]


# ----------------------------------------------------------------------------------------------- grid work

def _linear_weights(source: np.ndarray, target: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(len(target), len(source)) linear-interpolation matrix and the mask of targets outside the source axis."""
    index = np.clip(np.searchsorted(source, target, side="right") - 1, 0, source.size - 2)
    frac = np.clip((target - source[index]) / (source[index + 1] - source[index]), 0.0, 1.0)
    outside = (target < source[0] - _EDGE_TOLERANCE) | (target > source[-1] + _EDGE_TOLERANCE)
    weights = np.zeros((target.size, source.size))
    rows = np.arange(target.size)
    weights[rows, index] = 1.0 - frac
    weights[rows, index + 1] = frac
    return weights, outside


def regrid_to_imerg(values: np.ndarray, lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
    """Bilinear interpolation of a (nlat, nlon) field onto the 0.1-degree IMERG domain grid, float32 (280, 260).

    `lats` and `lons` are strictly ascending axes. A pixel whose four surrounding source nodes include a NaN is NaN,
    as is a pixel outside the source grid.
    """
    values = np.asarray(values, dtype=np.float64)
    lats, lons = np.asarray(lats, dtype=np.float64), np.asarray(lons, dtype=np.float64)
    if values.shape != (lats.size, lons.size):
        raise ValueError(f"field shape {values.shape} does not match {lats.size} latitudes x {lons.size} longitudes")
    if lats.size < 2 or lons.size < 2 or np.any(np.diff(lats) <= 0) or np.any(np.diff(lons) <= 0):
        raise ValueError("latitudes and longitudes must be strictly ascending with at least two points")
    wy, outside_y = _linear_weights(lats, TARGET_LATS)
    wx, outside_x = _linear_weights(lons, TARGET_LONS)
    finite = np.isfinite(values)
    out = wy @ np.where(finite, values, 0.0) @ wx.T
    out[(wy @ (~finite).astype(np.float64) @ wx.T) > 1e-9] = np.nan
    out[outside_y, :] = np.nan
    out[:, outside_x] = np.nan
    return out.astype(np.float32)


def crop_to_bbox(lats: np.ndarray, lons: np.ndarray, values: np.ndarray, bbox: dict):
    """Sub-grid inside the closed bbox {lat_min, lat_max, lon_min, lon_max}; (lats, lons, values)."""
    rows = (lats >= bbox["lat_min"] - _EDGE_TOLERANCE) & (lats <= bbox["lat_max"] + _EDGE_TOLERANCE)
    cols = (lons >= bbox["lon_min"] - _EDGE_TOLERANCE) & (lons <= bbox["lon_max"] + _EDGE_TOLERANCE)
    if not rows.any() or not cols.any():
        raise GribDecodeError("the GRIB grid does not intersect the domain")
    return lats[rows], lons[cols], values[np.ix_(rows, cols)]


def imd_days_on_grid(cumulative: dict[int, np.ndarray], lats: np.ndarray | None, lons: np.ndarray | None,
                     cycle: datetime, issue_day: date) -> np.ndarray:
    """(3, 280, 260) IMD-day totals on the IMERG grid; all NaN when no hour is available at all."""
    if not cumulative:
        return np.full((len(LEAD_DAYS), TARGET_LATS.size, TARGET_LONS.size), np.nan, dtype=np.float32)
    coarse = apcp_imd_days(cumulative, cycle, issue_day)
    return np.stack([regrid_to_imerg(day, lats, lons) for day in coarse])


# ---------------------------------------------------------------------------------------------- GRIB decode

class ApcpField(NamedTuple):
    lats: np.ndarray        # (nlat,) ascending
    lons: np.ndarray        # (nlon,) ascending
    values: np.ndarray      # (nlat, nlon) float32 mm; NaN where the file marks a value missing
    step_start_h: int
    step_end_h: int


def _eccodes():
    try:
        import eccodes
    except ImportError as exc:
        raise ImportError("GRIB decoding needs the 'live' extra: pip install -e .[live]") from exc
    return eccodes


def _split_grib(data: bytes) -> list[bytes]:
    messages, pos = [], 0
    while pos < len(data):
        if data[pos:pos + 4] != GRIB_MAGIC:
            raise GribDecodeError(f"not a GRIB message at byte {pos} (first bytes {data[pos:pos + 12]!r})")
        if len(data) < pos + 16 or data[pos + 7] != 2:
            raise GribDecodeError("truncated or non-GRIB2 message header")
        length = int.from_bytes(data[pos + 8:pos + 16], "big")
        if pos + length > len(data):
            raise GribDecodeError(f"truncated GRIB message: {len(data) - pos} of {length} bytes")
        messages.append(data[pos:pos + length])
        pos += length
    return messages


def decode_apcp_fields(grib_bytes: bytes) -> list[ApcpField]:
    """Every APCP message in `grib_bytes` as a regular lat/lon field with ascending axes."""
    eccodes = _eccodes()
    fields = []
    with _ECCODES_LOCK:
        for message in _split_grib(grib_bytes):
            gid = eccodes.codes_new_from_message(message)
            try:
                if eccodes.codes_get(gid, "shortName") != "tp":
                    continue
                if eccodes.codes_get(gid, "stepUnits") != 1:
                    raise GribDecodeError("APCP step is not in hours")
                if eccodes.codes_get(gid, "iScansNegatively") or eccodes.codes_get(gid, "jPointsAreConsecutive"):
                    raise GribDecodeError("unsupported GRIB scanning mode")
                lats = np.asarray(eccodes.codes_get_array(gid, "distinctLatitudes"), dtype=np.float64)
                lons = np.asarray(eccodes.codes_get_array(gid, "distinctLongitudes"), dtype=np.float64)
                values = np.asarray(eccodes.codes_get_values(gid), dtype=np.float64)
                if values.size != lats.size * lons.size:
                    raise GribDecodeError(f"{values.size} values for a {lats.size} x {lons.size} grid")
                if eccodes.codes_get(gid, "bitmapPresent"):
                    values[values == eccodes.codes_get(gid, "missingValue")] = np.nan
                start, end = int(eccodes.codes_get(gid, "startStep")), int(eccodes.codes_get(gid, "endStep"))
            finally:
                eccodes.codes_release(gid)
            grid = values.reshape(lats.size, lons.size)
            if lats[0] > lats[-1]:
                lats, grid = lats[::-1], grid[::-1]
            if np.any(np.diff(lats) <= 0) or np.any(np.diff(lons) <= 0):
                raise GribDecodeError("latitudes or longitudes are not monotonic")
            fields.append(ApcpField(lats, lons, np.ascontiguousarray(grid, dtype=np.float32), start, end))
    if not fields:
        raise GribDecodeError("no APCP message in the GRIB data")
    return fields


def decode_apcp(grib_bytes: bytes) -> tuple[np.ndarray, np.ndarray, np.ndarray, int, int]:
    """(lats, lons, values, step_start_h, step_end_h) of the APCP message that starts earliest (the 0-H total when
    the file has one, else the bucket), latitudes and longitudes ascending, values float32 mm (nlat, nlon)."""
    field = min(decode_apcp_fields(grib_bytes), key=lambda f: (f.step_start_h, -f.step_end_h))
    return field.lats, field.lons, field.values, field.step_start_h, field.step_end_h


# ------------------------------------------------------------------------------------------------ transport

def _get(url: str, *, headers: dict | None = None, params: dict | None = None, retries: int = 3,
         backoff: float = 2.0, timeout: float = 60.0) -> requests.Response:
    """GET with retries on transport errors, HTTP 429 and 5xx; 404 raises NotPublishedError, other 4xx DownloadError."""
    error: DownloadError | None = None
    for attempt in range(retries):
        try:
            response = requests.get(url, params=params, headers={**_HEADERS, **(headers or {})}, timeout=timeout)
            code = response.status_code
            if code == 404:
                raise NotPublishedError(f"HTTP 404 from {redact_url(url)}", status=404)
            if code == 429 or code >= 500:
                raise DownloadError(f"HTTP {code} from {redact_url(url)}", retriable=True, status=code)
            if code >= 400:
                raise DownloadError(f"HTTP {code} from {redact_url(url)}", status=code)
            return response
        except requests.RequestException as exc:
            error = DownloadError(f"{type(exc).__name__}: {exc}", retriable=True)
        except DownloadError as exc:
            error = exc
        if not error.retriable:
            raise error
        if attempt < retries - 1:
            time.sleep(backoff * 2 ** attempt)
    raise error


def _fetch_to_file(url: str, dest: Path, manifest: Manifest, source: str, *, params: dict | None = None,
                   headers: dict | None = None, expect_bytes: int | None = None) -> int:
    """Download a small GRIB payload atomically and record it in the manifest; returns the bytes fetched.

    A file the manifest already holds with matching size and checksum is not fetched again (returns 0). NOMADS
    answers a file that does not exist with an HTML page and status 200, so the GRIB magic is checked.
    """
    if manifest.is_current(dest):
        return 0
    response = _get(url, headers=headers, params=params)
    content = response.content
    if headers and "Range" in headers and response.status_code != 206:
        raise DownloadError(f"range request to {redact_url(url)} answered HTTP {response.status_code}")
    if not content.startswith(GRIB_MAGIC):
        raise NotPublishedError(f"{redact_url(url)} did not return a GRIB message")
    if expect_bytes is not None and len(content) != expect_bytes:
        raise DownloadError(f"truncated range from {redact_url(url)}: got {len(content)} of {expect_bytes} bytes",
                            retriable=True)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    try:
        part.write_bytes(content)
        os.replace(part, dest)
    finally:
        part.unlink(missing_ok=True)
    full_url = requests.Request("GET", url, params=params).prepare().url
    try:
        manifest.add(dest, source, full_url, LICENCE)
    except Exception:
        dest.unlink(missing_ok=True)  # never leave a data file without a manifest entry
        raise
    return len(content)


def _write_npz(path: Path, **arrays) -> None:
    part = path.with_name(path.name + ".part")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with part.open("wb") as handle:
            np.savez_compressed(handle, **arrays)
        os.replace(part, path)
    except BaseException:
        part.unlink(missing_ok=True)
        raise


def _reason(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"


# ------------------------------------------------------------------------------------------- day files

def day_file_path(root: Path, issue_day: date) -> Path:
    return Path(root) / "processed" / "rain" / f"gfs_imdday_{issue_day.isoformat()}.npz"


def _manifest(root: Path, manifest: Manifest | None) -> Manifest:
    return manifest if manifest is not None else Manifest(MANIFEST_PATH, root)


def _load_message(path: Path, hour: int, bbox: dict):
    """Decode the file for forecast hour `hour`; (lats, lons, (start, end, field)) cropped to the domain."""
    lats, lons, values, start, end = decode_apcp(path.read_bytes())
    if end != hour:
        raise GribDecodeError(f"{path.name}: the message ends at hour {end}, expected {hour}")
    lats, lons, values = crop_to_bbox(lats, lons, values, bbox)
    return lats, lons, (start, end, values)


def _write_day_file(root: Path, manifest: Manifest, issue_day: date, cycle: datetime, issued: datetime,
                    messages: dict[int, tuple[int, int, np.ndarray]], axes, failures: dict[int, str],
                    source: str) -> dict:
    cumulative = cumulative_from_messages(messages)
    lats, lons = axes if axes is not None else (None, None)
    days = imd_days_on_grid(cumulative, lats, lons, cycle, issue_day)
    if not cumulative:
        valid, missing = np.zeros(len(LEAD_DAYS), dtype=bool), required_hours(cycle, issue_day)
    else:
        valid, missing = imd_day_valid(cumulative, cycle, issue_day), missing_hours(cumulative, cycle, issue_day)
    path = day_file_path(root, issue_day)
    _write_npz(path, days=days, cycle=np.array(cycle.isoformat()), issued_utc=np.array(issued.isoformat()),
               lead_days=np.array(LEAD_DAYS, dtype=np.int32), day_valid=valid,
               missing_hours=np.array(missing, dtype=np.int32), lats=TARGET_LATS, lons=TARGET_LONS)
    manifest.add(path, source, f"derived: GFS cycle {cycle:%Y-%m-%d %HZ}", LICENCE)
    return {"path": path, "missing_hours": missing, "nan_lead_days": [d for d, ok in zip(LEAD_DAYS, valid) if not ok],
            "fetch_failures": {str(h): r for h, r in sorted(failures.items())}}


def _record_gaps(root: Path, issue_day: date, cycle: datetime, info: dict) -> None:
    """Keep `gfs_gaps.json` current: one entry per issue day that has missing hours or NaN days, none otherwise."""
    path = Path(root) / "processed" / "rain" / GAPS_FILE
    gaps = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    key = issue_day.isoformat()
    if info["missing_hours"] or info["nan_lead_days"] or info["fetch_failures"]:
        gaps[key] = {"cycle": cycle.isoformat(), "missing_hours": info["missing_hours"],
                     "nan_lead_days": info["nan_lead_days"], "fetch_failures": info["fetch_failures"]}
    else:
        gaps.pop(key, None)
    part = path.with_name(path.name + ".part")
    part.write_text(json.dumps(dict(sorted(gaps.items())), indent=1) + "\n", encoding="utf-8")
    os.replace(part, path)


# ----------------------------------------------------------------------------------------------- live path

def forecast_hours(spec: dict) -> list[int]:
    return list(range(int(spec["first"]), int(spec["last"]) + 1, int(spec["step"])))


def nomads_published(cycle: datetime, cfg: dict) -> bool:
    """True when the NOMADS directory of `cycle` lists the last forecast hour (`complete_when_hour`)."""
    gfs_cfg = cfg["gfs"]
    url = f"{gfs_cfg['live']['listing_url']}/gfs.{cycle:%Y%m%d}/{cycle:%H}/atmos/"
    try:
        listing = _get(url).text
    except DownloadError as exc:
        if exc.status in (403, 404):  # NOMADS answers 403 for a cycle directory that does not exist yet
            return False
        raise
    return int(gfs_cfg["complete_when_hour"]) in parse_nomads_listing(listing)


def fetch_nomads_hour(cycle: datetime, hour: int, cfg: dict, dest: Path, manifest: Manifest) -> Path:
    """APCP at forecast `hour` of `cycle` from the NOMADS grib filter (server-side domain crop) into `dest`."""
    box = cfg["domain_bbox"]
    hh = f"{cycle:%H}"
    params = {"dir": f"/gfs.{cycle:%Y%m%d}/{hh}/atmos", "file": f"gfs.t{hh}z.pgrb2.0p25.f{hour:03d}",
              "var_APCP": "on", "lev_surface": "on", "subregion": "", "leftlon": box["lon_min"],
              "rightlon": box["lon_max"], "toplat": box["lat_max"], "bottomlat": box["lat_min"]}
    _fetch_to_file(cfg["gfs"]["live"]["filter_url"], dest, manifest, SOURCE_LIVE, params=params)
    return dest


def fetch_live(issue_day: date, cfg: dict, *, now_utc: datetime | None = None, root: Path | None = None,
               manifest: Manifest | None = None) -> Path:
    """Fetch the latest complete cycle and write `processed/rain/gfs_imdday_<issue_day>.npz`.

    The cycle may not start after 03:00 UTC of `issue_day`: IMD day D+1 opens then, so a later cycle would leave the
    first forecast day without its first hours. Individual hours that fail are recorded as gaps (NaN days); if no
    hour at all can be used, GfsFetchError is raised and nothing is written.
    """
    gfs_cfg, bbox = cfg["gfs"], cfg["domain_bbox"]
    root = Path(root) if root is not None else data_root()
    manifest = _manifest(root, manifest)
    now = _require_utc(now_utc if now_utc is not None else datetime.now(UTC))
    as_of = min(now, datetime.combine(issue_day, clock(IMD_DAY_END_UTC_HOUR), tzinfo=UTC))
    cycle = latest_complete_cycle(as_of, lambda c: nomads_published(c, cfg))
    folder = root / "raw" / "gfs" / "live" / f"{cycle:%Y%m%d%H}"
    pause = float(gfs_cfg["live"]["request_pause_s"])
    messages: dict[int, tuple[int, int, np.ndarray]] = {}
    failures: dict[int, str] = {}
    axes = None
    for hour in forecast_hours(gfs_cfg["live"]["forecast_hours"]):
        dest = folder / f"f{hour:03d}.grib2"
        needs_request = not manifest.is_current(dest)
        try:
            fetch_nomads_hour(cycle, hour, cfg, dest, manifest)
            lats, lons, message = _load_message(dest, hour, bbox)
            if axes is None:
                axes = (lats, lons)
            elif not (np.array_equal(axes[0], lats) and np.array_equal(axes[1], lons)):
                raise GribDecodeError(f"{dest.name}: grid differs from the first forecast hour")
            messages[hour] = message
        except (DownloadError, GribDecodeError) as exc:
            failures[hour] = _reason(exc)
        if needs_request and pause:
            time.sleep(pause)
    if not messages:
        raise GfsFetchError(f"no forecast hour of the {cycle:%Y-%m-%d %HZ} cycle could be fetched "
                            f"(first error: {next(iter(failures.values()), 'none')})")
    info = _write_day_file(root, manifest, issue_day, cycle, now, messages, axes, failures, SOURCE_LIVE)
    _record_gaps(root, issue_day, cycle, info)
    return info["path"]


# -------------------------------------------------------------------------------------------- archive path

def archive_key(cycle: datetime, hour: int, archive_cfg: dict) -> str:
    atmos = "atmos/" if cycle.date() >= date.fromisoformat(archive_cfg["atmos_from"]) else ""
    return archive_cfg["key_template"].format(ymd=f"{cycle:%Y%m%d}", hh=f"{cycle:%H}", atmos=atmos, fff=f"{hour:03d}")


def archive_days(start: date, end: date, archive_cfg: dict) -> list[date]:
    """Every day from `start` to `end` inclusive that falls in the configured months."""
    months = set(archive_cfg["months"])
    return [start + timedelta(days=n) for n in range((end - start).days + 1)
            if (start + timedelta(days=n)).month in months]


def fetch_archive_hour(cycle: datetime, hour: int, cfg: dict, dest: Path, manifest: Manifest) -> int:
    """Cumulative (0-H) APCP record of one archived file, via its .idx byte range; returns the bytes fetched."""
    if manifest.is_current(dest):
        return 0
    archive_cfg = cfg["gfs"]["archive"]
    url = f"{archive_cfg['base_url']}/{archive_key(cycle, hour, archive_cfg)}"
    records = apcp_byte_ranges(parse_idx(_get(f"{url}.idx").text))
    cumulative = [(start, end) for start, end, step in records if step.startswith("0-")]
    if not cumulative:
        raise NotPublishedError(f"no 0-H APCP record in the .idx of {redact_url(url)}")
    start, end = cumulative[0]
    expect = None if end is None else end - start + 1
    return _fetch_to_file(url, dest, manifest, SOURCE_ARCHIVE,
                          headers={"Range": f"bytes={start}-{'' if end is None else end}"}, expect_bytes=expect)


def _archive_day(day: date, cfg: dict, cycle_hour: int, root: Path, manifest: Manifest) -> dict:
    bbox = cfg["domain_bbox"]
    if manifest.is_current(day_file_path(root, day)):
        return {"state": "skipped"}
    cycle = datetime(day.year, day.month, day.day, cycle_hour, tzinfo=UTC)
    folder = root / "raw" / "gfs" / "archive" / f"{cycle:%Y%m%d%H}"
    messages: dict[int, tuple[int, int, np.ndarray]] = {}
    failures: dict[int, str] = {}
    axes = None
    fetched = 0
    for hour in required_hours(cycle, day):
        dest = folder / f"f{hour:03d}_apcp0h.grib2"
        try:
            fetched += fetch_archive_hour(cycle, hour, cfg, dest, manifest)
        except NotPublishedError as exc:
            failures[hour] = _reason(exc)
            continue
        lats, lons, message = _load_message(dest, hour, bbox)
        if message[0] != 0:
            raise GribDecodeError(f"{dest.name}: record starts at hour {message[0]}, expected the 0-H total")
        axes = axes or (lats, lons)
        messages[hour] = message
    info = _write_day_file(root, manifest, day, cycle, datetime.now(UTC), messages, axes, failures, SOURCE_ARCHIVE)
    return {"state": "written", "info": info, "bytes": fetched, "cycle": cycle}


def fetch_archive(days: list[date], cfg: dict, cycle_hour: int = 0, *, workers: int = 1, root: Path | None = None,
                  manifest: Manifest | None = None, abort_after: int = 20) -> dict:
    """Write one `gfs_imdday_<day>.npz` per issue day from the archived `cycle_hour` run; idempotent and resumable.

    A day whose file is manifest-current is skipped. HTTP 404 and a missing 0-H record are gaps (NaN days, listed in
    the file and in `gfs_gaps.json`); any other failure leaves the day unwritten for the next run. After
    `abort_after` consecutive failed days the remaining days are not attempted. Returns {requested, written,
    skipped, failed: {day: reason}, gaps: {day: [hours]}, bytes_downloaded, seconds}.
    """
    root = Path(root) if root is not None else data_root()
    manifest = _manifest(root, manifest)
    started = time.monotonic()
    state = {"consecutive": 0}
    lock = threading.Lock()
    stop = threading.Event()

    def work(day: date) -> dict:
        if stop.is_set():
            return {"state": "failed", "reason": "not attempted: stopped after repeated failures"}
        try:
            result = _archive_day(day, cfg, cycle_hour, root, manifest)
        except (DownloadError, GribDecodeError, OSError) as exc:
            result = {"state": "failed", "reason": _reason(exc)}
        with lock:
            state["consecutive"] = state["consecutive"] + 1 if result["state"] == "failed" else 0
            if state["consecutive"] >= abort_after:
                stop.set()
        return result

    summary = {"requested": len(days), "written": [], "skipped": [], "failed": {}, "gaps": {}, "bytes_downloaded": 0}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(work, day): day for day in days}
        for future in as_completed(futures):
            day, result = futures[future], future.result()
            key = day.isoformat()
            if result["state"] == "failed":
                summary["failed"][key] = result["reason"]
            elif result["state"] == "skipped":
                summary["skipped"].append(key)
            else:
                summary["written"].append(key)
                summary["bytes_downloaded"] += result["bytes"]
                _record_gaps(root, day, result["cycle"], result["info"])
                if result["info"]["missing_hours"]:
                    summary["gaps"][key] = result["info"]["missing_hours"]
    for name in ("written", "skipped"):
        summary[name].sort()
    summary["failed"] = dict(sorted(summary["failed"].items()))
    summary["gaps"] = dict(sorted(summary["gaps"].items()))
    summary["seconds"] = time.monotonic() - started
    return summary
