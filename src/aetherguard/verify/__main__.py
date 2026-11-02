"""`python -m aetherguard.verify baseline` (see aetherguard.verify.report)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..config import PROJECT_ROOT
from ..live import run as live_run
from . import report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m aetherguard.verify", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    baseline = sub.add_parser("baseline", help=f"write reports/{report.REPORT_STEM}.{{json,md}}")
    baseline.add_argument("--out", type=Path, default=PROJECT_ROOT / "reports", help="report directory (default reports/)")
    args = parser.parse_args(argv)
    try:
        report.write_baseline(args.out, lambda m: print(m, flush=True))
    except (live_run.LiveRunError, ValueError, OSError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


raise SystemExit(main())
