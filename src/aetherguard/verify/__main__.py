"""`python -m aetherguard.verify baseline|heldout|ledger|inventory|seasons|operating-point|sources|assembly|harvest` (see aetherguard.verify.report, .heldout, .ledger, .inventory, .seasons, .operating_point, .open_sources, .assembly and .harvest)."""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from ..config import PROJECT_ROOT
from ..live import run as live_run
from . import assembly, geocode, harvest, heldout, inventory, ledger, open_sources, operating_point, report, seasons
from .geocode import GeocodeError


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m aetherguard.verify", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    baseline = sub.add_parser("baseline", help=f"write reports/{report.REPORT_STEM}.{{json,md}}")
    baseline.add_argument("--out", type=Path, default=PROJECT_ROOT / "reports", help="report directory (default reports/)")
    expanded = sub.add_parser("heldout", help=f"write reports/{heldout.REPORT_STEM}.{{json,md}}: v3 and the benchmarks on the 2018-2025 season panels")
    expanded.add_argument("--out", type=Path, default=PROJECT_ROOT / "reports", help="report directory (default reports/)")
    expanded.add_argument("--assembly", type=Path, default=None,
                          help="a frozen held-out assembly directory (e.g. data/processed/heldout_v2) instead of the W1 events")
    expanded.add_argument("--stem", default=heldout.REPORT_STEM, help="report file name (required with --assembly)")
    live = sub.add_parser("ledger", help=f"write reports/{ledger.REPORT_STEM}.{{json,md}}: published alerts against reported events")
    live.add_argument("--out", type=Path, default=PROJECT_ROOT / "reports", help="report directory (default reports/)")
    live.add_argument("--today", type=date.fromisoformat, default=None, help="YYYY-MM-DD, default the IST date today")
    events = sub.add_parser("inventory", help="geocode raw/<year>.csv of the reported-events folder into <year>.csv and "
                                              f"{inventory.REPORT_NAME}")
    events.add_argument("--dir", type=Path, default=ledger.REPORTED_DIR, help="reported-events folder (default data/raw/manual/reported_events/)")
    events.add_argument("--offline", action="store_true",
                        help="answer from the Nominatim cache only: a query that is not cached is an error")
    events.add_argument("--max-accuracy-km", type=float, default=inventory.MAX_ACCURACY_KM,
                        help="accuracy limit of admission (default 10; the W1b open sources use 5)")
    srcs = sub.add_parser("sources", help="fetch or normalise an open inventory into data/raw/manual/<source>/")
    srcs.add_argument("action", choices=("fetch", "normalise"))
    srcs.add_argument("source", choices=tuple(open_sources.FETCHERS))
    asm = sub.add_parser("assembly", help="held-out assembly v2: rule QA records, freeze, or the expansion report")
    asm.add_argument("action", choices=("qa", "freeze", "report"))
    asm.add_argument("--out", type=Path, default=PROJECT_ROOT / "reports", help="report directory (default reports/)")
    crop = sub.add_parser("harvest", help="GDELT landslide reports of a date range as a review queue (never admitted)")
    crop.add_argument("--start", type=date.fromisoformat, required=True, help="YYYY-MM-DD (UTC day of the first query)")
    crop.add_argument("--end", type=date.fromisoformat, required=True, help="YYYY-MM-DD (UTC day of the last query)")
    crop.add_argument("--out", type=Path, required=True, help="queue directory (keep it out of reported_events/)")
    crop.add_argument("--bipad", action="store_true", help="add the local BIPAD Nepal register rows of the range")
    held = sub.add_parser("seasons", help="score June-December of the held-out years with the frozen model (training-style features)")
    held.add_argument("--years", type=seasons.parse_years, default=seasons.parse_years("2018-2025"), help="YYYY or YYYY-YYYY (default 2018-2025)")
    held.add_argument("--out", type=Path, default=None, help="panel directory (default data/processed/alerts/heldout_seasons)")
    held.add_argument("--force", action="store_true", help="score a season again although its panel exists")
    point = sub.add_parser("operating-point", help=f"write reports/{operating_point.REPORT_STEM}.{{json,md}}: fit region x month thresholds on "
                                                   "development and take the single held-out look (refuses to run twice)")
    point.add_argument("--out", type=Path, default=PROJECT_ROOT / "reports", help="report directory (default reports/)")
    args = parser.parse_args(argv)
    say = lambda m: print(m, flush=True)
    try:
        if args.command == "baseline":
            report.write_baseline(args.out, say)
        elif args.command == "heldout":
            heldout.write_heldout(args.out, say, args.assembly, args.stem)
        elif args.command == "harvest":
            if ledger.REPORTED_DIR.resolve() in [args.out.resolve(), *args.out.resolve().parents]:
                raise ValueError("the review queue must not be written into reported_events/")
            harvest.harvest(args.start, args.end, args.out, geocode.load_places(), universe=harvest.universe_set(),
                            bipad_csv=(open_sources.source_dir(open_sources.BIPAD) / inventory.QA_DIR / inventory.COMBINED_NAME
                                       if args.bipad else None), say=say)
        elif args.command == "sources":
            (open_sources.FETCHERS if args.action == "fetch" else open_sources.NORMALISERS)[args.source](say=say)
        elif args.command == "assembly":
            {"qa": lambda: assembly.write_all_qa(say), "freeze": lambda: assembly.freeze(say),
             "report": lambda: assembly.write_report(args.out, say)}[args.action]()
        elif args.command == "ledger":
            ledger.write_ledger(args.out, args.today, say)
        elif args.command == "seasons":
            seasons.run(args.years, args.out, args.force, say)
        elif args.command == "operating-point":
            operating_point.run(args.out, say)
        else:
            inventory.write_inventory(args.dir, geocode.load_places(), say, offline=args.offline,
                                      max_accuracy_km=args.max_accuracy_km)
    except (live_run.LiveRunError, GeocodeError, ValueError, OSError, RuntimeError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


raise SystemExit(main())
