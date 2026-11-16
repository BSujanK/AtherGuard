"""Leads v5: the ECMWF open-data archive days (HRES and ensemble IMD-day totals) of June-September of one year.

    python tools/leads_v5_fetch_ecmwf.py 2025 [--workers 3]

`ingest.ecmwf_build --archive` only covers the configured windows (2023, 2024); this fetches another season with the same
`ecmwf.fetch_archive` (same cycle, same day files in processed/rain). Resumable: a manifest-current day is skipped.
Exit 1 while any day failed, so the job runner retries.
"""
import argparse
import json
import sys
from datetime import date, timedelta

from aetherguard.config import PROJECT_ROOT, load_config_file
from aetherguard.ingest import ecmwf


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("year", type=int)
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    cfg = load_config_file(PROJECT_ROOT / "configs" / "live.yaml")
    first, last = date(args.year, 6, 1), date(args.year, 9, 30)
    days = [first + timedelta(days=n) for n in range((last - first).days + 1)]
    summary = ecmwf.fetch_archive(days, cfg, workers=args.workers)
    print(json.dumps({k: (v if not isinstance(v, list) else len(v)) for k, v in summary.items()}))
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
