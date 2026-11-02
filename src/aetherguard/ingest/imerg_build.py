"""CLI: python -m aetherguard.ingest.imerg_build --run late|early [--start YYYY-MM-DD] [--end YYYY-MM-DD|yesterday]
[--workers N] [--manifest PATH].

Downloads the domain subset of every missing IMERG day (resumable: re-run the same command after an interruption)
into data/raw/imerg/<run>/ and appends it to the store in data/processed/rain. `--run late` defaults to the whole
history (configs/live.yaml, imerg.history_start) up to yesterday (UTC); `--run early` without --start / --end builds
the configured backtest windows.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from ..config import data_root
from ..manifest import Manifest
from . import imerg

YESTERDAY = "yesterday"


def _day(text: str, today: date) -> date:
    return today - timedelta(days=1) if text == YESTERDAY else date.fromisoformat(text)


def resolve_ranges(run: str, start: str | None, end: str | None, today: date) -> list[tuple[date, date]]:
    """The (first, last) day windows to build. Raises ValueError for an unusable combination."""
    last_allowed = today - timedelta(days=1)
    if run == "early" and start is None and end is None:
        windows = [(first, min(last, last_allowed)) for first, last in imerg.EARLY_WINDOWS]
    else:
        if start is None and run != "late":
            raise ValueError("--start is required for --run early when --end is given")
        first = imerg.HISTORY_START if start is None else _day(start, today)
        windows = [(first, last_allowed if end is None else _day(end, today))]
    for first, last in windows:
        if last < first:
            raise ValueError(f"empty range: {first} is after {last}")
    return windows


def _print_years(store: imerg.ImergStore) -> None:
    index = json.loads(store.index_path.read_text(encoding="utf-8"))
    for year, entry in index["years"].items():
        print(f"[imerg {store.run}] {year}: {entry['n_present']} present, {len(entry['missing'])} missing, "
              f"{len(entry['failed'])} failed of {entry['n_days']} calendar days", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download and store IMERG V07 daily rain for the domain.")
    parser.add_argument("--run", choices=imerg.RUNS, required=True, help="IMERG run: late (model rain) or early")
    parser.add_argument("--start", help="first UTC day, YYYY-MM-DD (late default: the configured history start)")
    parser.add_argument("--end", help="last UTC day, YYYY-MM-DD or 'yesterday' (default yesterday)")
    parser.add_argument("--workers", type=int, default=imerg.MAX_WORKERS,
                        help=f"parallel downloads, 1..{imerg.MAX_WORKERS} (default {imerg.MAX_WORKERS})")
    parser.add_argument("--manifest", type=Path, default=imerg.MANIFEST_PATH,
                        help="download manifest (default: manifests/data_manifest.jsonl)")
    args = parser.parse_args(argv)
    if not 1 <= args.workers <= imerg.MAX_WORKERS:
        parser.error(f"--workers must be between 1 and {imerg.MAX_WORKERS} (the configured politeness limit)")
    try:
        windows = resolve_ranges(args.run, args.start, args.end, datetime.now(timezone.utc).date())
    except ValueError as exc:
        parser.error(str(exc))

    root = data_root()
    store = imerg.ImergStore(root / "processed" / "rain", args.run, raw_dir=root / "raw" / "imerg",
                             manifest=Manifest(args.manifest, root))
    status = 0
    for first, last in windows:
        days = [first + timedelta(d) for d in range((last - first).days + 1)]
        print(f"[imerg {args.run}] {len(days)} days {first}..{last}", flush=True)
        started = time.monotonic()
        summary = store.update(days, workers=args.workers)
        print(f"[imerg {args.run}] requested {summary['requested']}, already present {summary['already_present']}, "
              f"added {summary['added']}, missing {len(summary['missing'])}, failed {len(summary['failed'])}, "
              f"{summary['bytes_fetched'] / 1e6:.1f} MB fetched in {time.monotonic() - started:.0f} s "
              f"(progress log: {store.raw_dir / args.run / 'progress.log'})", flush=True)
        if summary["missing"]:
            print(f"[imerg {args.run}] not published (listed in the index): {', '.join(summary['missing'][:20])}"
                  f"{' ...' if len(summary['missing']) > 20 else ''}", flush=True)
        if summary["failed"]:
            print(f"[imerg {args.run}] {len(summary['failed'])} failed day(s) {summary['failure_reasons']}; "
                  "re-run the same command to retry them", file=sys.stderr)
            status = 1
    if store.index_path.exists():
        _print_years(store)
    return status


if __name__ == "__main__":
    sys.exit(main())
