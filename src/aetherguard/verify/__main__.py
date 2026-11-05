"""`python -m aetherguard.verify baseline|ledger|inventory` (see aetherguard.verify.report, .ledger and .inventory)."""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from ..config import PROJECT_ROOT
from ..live import run as live_run
from . import geocode, inventory, ledger, report
from .geocode import GeocodeError


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m aetherguard.verify", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    baseline = sub.add_parser("baseline", help=f"write reports/{report.REPORT_STEM}.{{json,md}}")
    baseline.add_argument("--out", type=Path, default=PROJECT_ROOT / "reports", help="report directory (default reports/)")
    live = sub.add_parser("ledger", help=f"write reports/{ledger.REPORT_STEM}.{{json,md}}: published alerts against reported events")
    live.add_argument("--out", type=Path, default=PROJECT_ROOT / "reports", help="report directory (default reports/)")
    live.add_argument("--today", type=date.fromisoformat, default=None, help="YYYY-MM-DD, default the IST date today")
    events = sub.add_parser("inventory", help="geocode raw/<year>.csv of the reported-events folder into <year>.csv and "
                                              f"{inventory.REPORT_NAME}")
    events.add_argument("--dir", type=Path, default=ledger.REPORTED_DIR, help="reported-events folder (default data/raw/manual/reported_events/)")
    events.add_argument("--offline", action="store_true",
                        help="answer from the Nominatim cache only: a query that is not cached is an error")
    args = parser.parse_args(argv)
    say = lambda m: print(m, flush=True)
    try:
        if args.command == "baseline":
            report.write_baseline(args.out, say)
        elif args.command == "ledger":
            ledger.write_ledger(args.out, args.today, say)
        else:
            inventory.write_inventory(args.dir, geocode.load_places(), say, offline=args.offline)
    except (live_run.LiveRunError, GeocodeError, ValueError, OSError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


raise SystemExit(main())
