"""CLI: python -m aetherguard.ingest.chirps_build [--workers N] [--download-only | --crop-only] [--manifest PATH].

Downloads the needed CHIRPS days (resumable: re-run the same command after an interruption), then crops them to
the domain window (float16 per-year arrays in <data>/processed/rain).
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from ..config import PROJECT_ROOT, data_root, load_config
from ..manifest import Manifest
from . import chirps


def main(argv: list[str] | None = None) -> int:
    cfg = load_config("ingest")
    max_workers = int(cfg["chirps"]["workers"])
    parser = argparse.ArgumentParser(description="Download and crop CHIRPS v2.0 daily rainfall.")
    parser.add_argument("--workers", type=int, default=max_workers,
                        help=f"parallel downloads, 1..{max_workers} (default {max_workers}, the configured maximum)")
    stage = parser.add_mutually_exclusive_group()
    stage.add_argument("--download-only", action="store_true", help="download, do not crop")
    stage.add_argument("--crop-only", action="store_true", help="crop already downloaded files")
    parser.add_argument("--manifest", type=Path, default=PROJECT_ROOT / "manifests" / "data_manifest.jsonl",
                        help="download manifest (default: manifests/data_manifest.jsonl)")
    args = parser.parse_args(argv)
    if not 1 <= args.workers <= max_workers:
        parser.error(f"--workers must be between 1 and {max_workers} (the configured politeness limit)")

    root = data_root()
    raw_dir = root / "raw" / "chirps"
    out_dir = root / "processed" / "rain"
    dates = chirps.needed_dates(cfg)
    print(f"[chirps] {len(dates)} needed dates ({dates[0]}..{dates[-1]})", flush=True)
    status = 0
    if not args.crop_only:
        started = time.monotonic()
        summary = chirps.download_chirps(dates, raw_dir, Manifest(args.manifest, root), args.workers)
        print(f"[chirps] download {summary} in {time.monotonic() - started:.0f} s "
              f"(progress log: {raw_dir / chirps.PROGRESS_LOG})", flush=True)
        if summary["failed"]:
            print(f"[chirps] {summary['failed']} failed date(s) listed in {raw_dir / chirps.FAILED_DATES_FILE}; "
                  "re-run the same command to retry them", file=sys.stderr)
            status = 1
    if not args.download_only and status == 0:
        started = time.monotonic()
        index = chirps.crop_chirps(dates, raw_dir, out_dir, cfg)
        print(f"[chirps] crop {index['rows']}x{index['cols']} window, days per year {index['days_per_year']}, "
              f"{len(index['missing_dates'])} missing day(s), NaN share {index['nan_share']:.3f}, "
              f"max {index['max_value']:.1f} mm in {time.monotonic() - started:.0f} s", flush=True)
    return status


if __name__ == "__main__":
    sys.exit(main())
