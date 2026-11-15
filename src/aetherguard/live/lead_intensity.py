"""Rain-intensity inputs of the forecast leads (W7: the forecast leads scored by the adopted model v4).

v4 reads six `iint_` inputs with a lag of one IMD day (W3 spec section 1): the inputs of IMD day T are the 1-, 3- and 6-hour
maxima and the wet hours of day T-1, and the three-day maxima over T-3..T-1. For a forecast lead L issued on day D the
target is T = D+L, so lead L needs the half-hourly rain of the days D+L-3..D+L-1:
  * lead 1: D-2 and D-1 are complete IMERG Late days (lead 0 already reads them); D has closed at 03:00 UTC but its Late
    half-hours are not out yet, so it comes from the IMERG Early half-hours a run has (the first 44, `--live-window`);
  * leads 2 and 3: D+1 and D+2 have not happened; they come from the sub-daily forecast rain.

Which forecast steps exist (measured, reports/phase8_leads_v4.md): the live run keeps the GFS 00Z cycle's 3-hourly cumulative
APCP files f003..f096 (`raw/gfs/live/<cycle>/`), the GFS archive keeps only the IMD-day boundary hours (f003, f027, f051,
f075), and ECMWF is stored as IMD-day totals only (HRES and the ensemble mean / p10 / p50 / p90; members are not kept). The
sub-daily forecast is therefore GFS at 3-hour steps, for every lead whatever source its daily rain comes from. From 3-hour
blocks the 3- and 6-hour maxima and the wet hours (a block of at least 0.3 mm = 0.1 mm/h on average counts 3 wet hours)
can be formed; a 1-hour maximum cannot, so the 3-hour maximum stands in for it and the quantile mapping puts it on the
distribution of IMERG's 1-hour maximum. v4 never saw a missing intensity input in training (0 NaN in every development
table, `iint_lag1_report.json`), so a missing input is never handed to it as NaN: a lead without its intensity is not
scored by v4.

The archive store (`fetch-gfs`): for the evaluation seasons the 3-hourly cumulative APCP of the 00Z cycle, hours 3..51 (the
forecast days D+1 and D+2 that leads 2 and 3 read), is fetched from the public AWS copy of GFS (`noaa-gfs-bdp-pds`, no
account) by `.idx` byte range, cropped to the domain on its 0.25-degree grid and written as one file per issue day
`<store>/<yyyy>/gfs3h_<yyyy-mm-dd>.npz`; the global records are never kept. A day already written is skipped (resumable).

CLI: python -m aetherguard.live.lead_intensity fetch-gfs --start 2021-06-01 --end 2024-09-30 [--months 6-9] [--workers 6]
         [--store DIR]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, time as clock, timedelta, timezone
from pathlib import Path

import numpy as np

from ..config import PROJECT_ROOT, data_root, load_config_file
from ..features import imerg_intensity as ii
from ..ingest import gfs
from ..live.probe import apcp_byte_ranges, parse_idx
from ..urlredact import redact_url

log = logging.getLogger("aetherguard.live.lead_intensity")

UTC = timezone.utc
STEP_H = 3                              # GFS cumulative APCP steps the live run keeps (configs/live.yaml gfs.live.forecast_hours)
WET_BLOCK_MM = float(ii.imerg_hh.WET_MM_PER_H) * STEP_H     # 0.1 mm/h over a 3-hour block
BLOCKS_PER_DAY = 24 // STEP_H
FORECAST_DAYS = 2                       # D+1 and D+2: the newest day lead 3 reads at lag 1
STORE_SUBDIR = ("processed", "lead_intensity", "gfs3h")
STORE_VERSION = 1


def default_store() -> Path:
    return data_root().joinpath(*STORE_SUBDIR)


# ------------------------------------------------------------------------------------------------ time rules

def day_hours(cycle: datetime, day: date) -> list[int]:
    """Forecast hours of `cycle` that bound the 3-hour blocks of IMD day `day` (03:00 UTC day-1 .. 03:00 UTC day), first
    to last. ValueError when the day opens before the cycle."""
    end = datetime.combine(day, clock(gfs.IMD_DAY_END_UTC_HOUR), tzinfo=UTC)
    first = int((end - timedelta(days=1) - cycle).total_seconds() // 3600)
    if first < 0 or first % STEP_H:
        raise ValueError(f"IMD day {day} does not start on a {STEP_H}-hour step of the {cycle:%Y-%m-%d %HZ} cycle")
    return list(range(first, first + 24 + 1, STEP_H))


def needed_hours(cycle: datetime, issue_day: date, days: int = FORECAST_DAYS) -> list[int]:
    """Every positive hour the forecast days D+1..D+`days` of `issue_day` read."""
    return sorted({h for k in range(1, days + 1) for h in day_hours(cycle, issue_day + timedelta(days=k)) if h > 0})


# ------------------------------------------------------------------------------------------ blocks -> day maps

def blocks_from_cumulative(cumulative: dict[int, np.ndarray], hours: list[int]) -> np.ndarray | None:
    """(len(hours) - 1, ...) mm of the 3-hour blocks between consecutive `hours` from cumulative 0-H fields; hour 0 is zero.
    None when any hour is missing (a gap is never dry). Differences a hair below zero are clipped to 0."""
    fields = []
    for hour in hours:
        if hour == 0:
            fields.append(None)
        elif hour not in cumulative:
            return None
        else:
            fields.append(np.asarray(cumulative[hour], dtype=np.float32))
    shape = next(f.shape for f in fields if f is not None)
    fields = [np.zeros(shape, dtype=np.float32) if f is None else f for f in fields]
    return np.maximum(np.diff(np.stack(fields), axis=0), 0.0).astype(np.float32)


def forecast_day_maps(blocks: np.ndarray) -> dict[str, np.ndarray]:
    """The four day maps of `imerg_intensity.FIELDS` from the eight 3-hour blocks of one IMD day (NaN propagates)."""
    blocks = np.asarray(blocks, dtype=np.float32)
    if blocks.shape[0] != BLOCKS_PER_DAY:
        raise ValueError(f"an IMD day has {BLOCKS_PER_DAY} blocks of {STEP_H} h, got {blocks.shape[0]}")
    finite = np.isfinite(blocks).all(axis=0)
    max3h = blocks.max(axis=0)
    max6h = (blocks[:-1] + blocks[1:]).max(axis=0)
    wet = np.where(finite, (np.where(np.isfinite(blocks), blocks, 0.0) >= WET_BLOCK_MM).sum(axis=0) * float(STEP_H), np.nan)
    return {"max1h": max3h.copy(), "max3h": max3h, "max6h": max6h, "wet_hours": wet.astype(np.float32)}


# ------------------------------------------------------------------------------------------------ the store

@dataclass(frozen=True)
class StoreDay:
    issue_day: date
    cycle: datetime
    cumulative: dict[int, np.ndarray]    # hour -> (nlat, nlon) mm on the domain crop of the source grid
    lats: np.ndarray
    lons: np.ndarray
    failures: dict[str, str]


def store_path(store: Path, issue_day: date) -> Path:
    return Path(store) / f"{issue_day.year}" / f"gfs3h_{issue_day.isoformat()}.npz"


def write_store_day(store: Path, issue_day: date, cycle: datetime, cumulative: dict[int, np.ndarray], lats, lons,
                    failures: dict[str, str]) -> Path:
    hours = sorted(cumulative)
    path = store_path(store, issue_day)
    path.parent.mkdir(parents=True, exist_ok=True)
    stack = (np.stack([np.asarray(cumulative[h], dtype=np.float32) for h in hours]) if hours
             else np.zeros((0, len(lats), len(lons)), dtype=np.float32))
    part = path.with_name(path.name + ".part.npz")
    np.savez_compressed(part, version=np.int32(STORE_VERSION), hours=np.array(hours, dtype=np.int32), cumulative=stack,
                        lats=np.asarray(lats, dtype=np.float64), lons=np.asarray(lons, dtype=np.float64),
                        cycle=np.array(cycle.isoformat()), failures=np.array(json.dumps(failures)))
    os.replace(part, path)
    return path


def load_store_day(store: Path, issue_day: date) -> StoreDay | None:
    path = store_path(store, issue_day)
    if not path.is_file():
        return None
    with np.load(path, allow_pickle=False) as data:
        if int(data["version"]) != STORE_VERSION:
            raise ValueError(f"{path}: store version {int(data['version'])}, expected {STORE_VERSION}")
        hours = [int(h) for h in data["hours"]]
        cumulative = {h: np.asarray(data["cumulative"][i]) for i, h in enumerate(hours)}
        return StoreDay(issue_day, datetime.fromisoformat(str(data["cycle"])), cumulative, np.asarray(data["lats"]),
                        np.asarray(data["lons"]), json.loads(str(data["failures"])))


def live_raw_day(raw_root: Path, issue_day: date, cycle: datetime, bbox: dict) -> StoreDay:
    """The 3-hourly cumulative fields a live run kept for `cycle` (`<raw_root>/raw/gfs/live/<cycle>/fHHH.grib2`), as a store
    day; a file that is missing or cannot be decoded is a failure (that hour is absent)."""
    folder = Path(raw_root) / "raw" / "gfs" / "live" / f"{cycle:%Y%m%d%H}"
    cumulative, failures, axes = {}, {}, None
    for hour in needed_hours(cycle, issue_day):
        path = folder / f"f{hour:03d}.grib2"
        try:
            lats, lons, (start, end, values) = gfs._load_message(path, hour, bbox)
            if start != 0:
                raise gfs.GribDecodeError(f"{path.name}: the record starts at hour {start}, expected the 0-H total")
        except (OSError, ValueError) as exc:
            failures[str(hour)] = type(exc).__name__
            continue
        axes = axes or (lats, lons)
        cumulative[hour] = values
    lats, lons = axes if axes is not None else (np.zeros(0), np.zeros(0))
    return StoreDay(issue_day, cycle, cumulative, lats, lons, failures)


def day_maps_on_grid(day: StoreDay, target: date) -> dict[str, np.ndarray] | None:
    """The four day maps of IMD day `target` on the 0.1-degree IMERG grid from a store day (each 3-hour block regridded
    bilinearly, then reduced); None when an hour of that day is missing."""
    try:
        hours = day_hours(day.cycle, target)
    except ValueError:
        return None
    blocks = blocks_from_cumulative(day.cumulative, hours)
    if blocks is None:
        return None
    fine = np.stack([gfs.regrid_to_imerg(b, day.lats, day.lons) for b in blocks])
    return forecast_day_maps(fine)


# ------------------------------------------------------------------------------------------------ archive fetch

def _fetch_hour(cycle: datetime, hour: int, cfg: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    archive_cfg = cfg["gfs"]["archive"]
    url = f"{archive_cfg['base_url']}/{gfs.archive_key(cycle, hour, archive_cfg)}"
    records = apcp_byte_ranges(parse_idx(gfs._get(f"{url}.idx").text))
    cumulative = [(start, end) for start, end, step in records if step.startswith("0-")]
    if not cumulative:
        raise gfs.NotPublishedError(f"no 0-H APCP record in the .idx of {redact_url(url)}")
    start, end = cumulative[0]
    data = gfs._get(url, headers={"Range": f"bytes={start}-{'' if end is None else end}"}).content
    lats, lons, values, step_start, step_end = gfs.decode_apcp(data)
    if step_start != 0 or step_end != hour:
        raise gfs.GribDecodeError(f"record {step_start}-{step_end} h, expected 0-{hour} h")
    return gfs.crop_to_bbox(lats, lons, values, cfg["domain_bbox"])


def fetch_archive_day(issue_day: date, cfg: dict, store: Path, cycle_hour: int = 0) -> str:
    """Fetch and write one issue day's 3-hourly cumulative fields; 'skipped' when the file exists."""
    if store_path(store, issue_day).is_file():
        return "skipped"
    cycle = datetime(issue_day.year, issue_day.month, issue_day.day, cycle_hour, tzinfo=UTC)
    cumulative, failures, axes = {}, {}, None
    for hour in needed_hours(cycle, issue_day):
        try:
            lats, lons, values = _fetch_hour(cycle, hour, cfg)
        except (gfs.NotPublishedError, gfs.GribDecodeError) as exc:
            failures[str(hour)] = f"{type(exc).__name__}: {str(exc)[:120]}"
            continue
        if axes is None:
            axes = (lats, lons)
        elif not (np.array_equal(axes[0], lats) and np.array_equal(axes[1], lons)):
            failures[str(hour)] = "GribDecodeError: the grid differs from the first hour"
            continue
        cumulative[hour] = values
    lats, lons = axes if axes is not None else (np.zeros(0), np.zeros(0))
    write_store_day(store, issue_day, cycle, cumulative, lats, lons, failures)
    return "written" if not failures else f"written with {len(failures)} missing hours"


def fetch_archive(days: list[date], cfg: dict, store: Path, workers: int = 6) -> dict[str, int]:
    """Fetch every day of `days` (resumable); a day whose transport fails is left unwritten and retried by the next run."""
    counts: dict[str, int] = {}
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch_archive_day, d, cfg, store): d for d in days}
        for n, future in enumerate(as_completed(futures), 1):
            day = futures[future]
            try:
                state = future.result()
            except Exception as exc:          # transport failure after the retries: the day is left for the next run
                state = "failed"
                log.warning("%s: %s: %s", day, type(exc).__name__, str(exc)[:160])
            counts[state.split(" with")[0]] = counts.get(state.split(" with")[0], 0) + 1
            if n % 20 == 0 or n == len(days):
                log.info("%d/%d days (%s) after %.0f s", n, len(days), counts, time.monotonic() - started)
    return counts


def _parse_months(text: str) -> set[int]:
    first, _, last = text.partition("-")
    return set(range(int(first), int(last or first) + 1))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m aetherguard.live.lead_intensity", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    fetch = sub.add_parser("fetch-gfs", help="3-hourly GFS cumulative APCP of the 00Z cycle for the archive seasons")
    fetch.add_argument("--start", type=date.fromisoformat, required=True)
    fetch.add_argument("--end", type=date.fromisoformat, required=True)
    fetch.add_argument("--months", type=_parse_months, default={6, 7, 8, 9})
    fetch.add_argument("--workers", type=int, default=6)
    fetch.add_argument("--store", type=Path, default=None)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_config_file(PROJECT_ROOT / "configs" / "live.yaml")
    days = [args.start + timedelta(days=n) for n in range((args.end - args.start).days + 1)]
    days = [d for d in days if d.month in args.months]
    counts = fetch_archive(days, cfg, args.store or default_store(), args.workers)
    print(json.dumps(counts))
    return 0 if not counts.get("failed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
