"""CLI: python -m aetherguard.ingest.gfs_build (--live | --archive [--start D --end D]) [--workers N].

--live     latest complete GFS cycle from NOMADS -> data/processed/rain/gfs_imdday_<today IST>.npz
--archive  archived 00Z runs (June-September by default 2021-06-01..2024-09-30) from AWS Open Data, one
           gfs_imdday_<day>.npz per issue day; rerun the same command to resume after an interruption.
Both read configs/live.yaml. Raw GRIB downloads are recorded in manifests/data_manifest.jsonl.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime

import numpy as np

from ..config import load_config
from ..http import DownloadError
from . import gfs


def _live(cfg: dict) -> int:
    issue_day = datetime.now(gfs.IST).date()
    try:
        path = gfs.fetch_live(issue_day, cfg)
    except (gfs.NoCompleteCycleError, gfs.GfsFetchError, DownloadError, gfs.GribDecodeError) as exc:
        print(f"[gfs] live fetch for {issue_day} failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    with np.load(path) as day:
        valid = [int(d) for d, ok in zip(day["lead_days"], day["day_valid"]) if ok]
        print(f"[gfs] live {issue_day}: cycle {day['cycle']}, valid lead days {valid}, "
              f"missing hours {day['missing_hours'].tolist()} -> {path}", flush=True)
    return 0


def _archive(cfg: dict, start: date, end: date, workers: int) -> int:
    archive_cfg = cfg["gfs"]["archive"]
    days = gfs.archive_days(start, end, archive_cfg)
    print(f"[gfs] archive: {len(days)} issue days ({start}..{end}, months {archive_cfg['months']}), "
          f"cycle {archive_cfg['cycle_hour']:02d}Z, {workers} worker(s)", flush=True)
    summary = gfs.fetch_archive(days, cfg, archive_cfg["cycle_hour"], workers=workers)
    print(f"[gfs] archive: written {len(summary['written'])}, skipped {len(summary['skipped'])}, "
          f"failed {len(summary['failed'])}, days with gaps {len(summary['gaps'])}, "
          f"{summary['bytes_downloaded'] / 1e6:.1f} MB fetched in {summary['seconds']:.0f} s", flush=True)
    for day, reason in list(summary["failed"].items())[:10]:
        print(f"[gfs] failed {day}: {reason}", file=sys.stderr)
    if summary["failed"]:
        print(f"[gfs] {len(summary['failed'])} failed day(s); re-run the same command to retry them", file=sys.stderr)
    return 1 if summary["failed"] else 0


def main(argv: list[str] | None = None) -> int:
    cfg = load_config("live")
    archive_cfg = cfg["gfs"]["archive"]
    max_workers = int(archive_cfg["workers"])
    parser = argparse.ArgumentParser(description="Ingest GFS APCP forecasts as IMD-day totals on the IMERG grid.")
    parser.add_argument("--live", action="store_true", help="latest complete cycle from NOMADS")
    parser.add_argument("--archive", action="store_true", help="archived runs from AWS Open Data")
    parser.add_argument("--start", type=date.fromisoformat, default=date.fromisoformat(archive_cfg["start"]),
                        help=f"first archive issue day (default {archive_cfg['start']})")
    parser.add_argument("--end", type=date.fromisoformat, default=date.fromisoformat(archive_cfg["end"]),
                        help=f"last archive issue day (default {archive_cfg['end']})")
    parser.add_argument("--workers", type=int, default=max_workers,
                        help=f"parallel archive days, 1..{max_workers} (default {max_workers}); live is sequential")
    args = parser.parse_args(argv)
    if not (args.live or args.archive):
        parser.error("choose --live and/or --archive")
    if not 1 <= args.workers <= max_workers:
        parser.error(f"--workers must be between 1 and {max_workers}")
    if args.end < args.start:
        parser.error("--end is before --start")
    status = 0
    if args.live:
        status |= _live(cfg)
    if args.archive:
        status |= _archive(cfg, args.start, args.end, args.workers)
    return status


if __name__ == "__main__":
    sys.exit(main())
