"""CLI: python -m aetherguard.ingest.ecmwf_build (--live | --archive [--start D --end D] | --publication) [--workers N].

--live         newest published ECMWF cycle of each product -> data/processed/rain/ecmwf_imdday_<today IST>.npz
--archive      the 18Z run of D-1 for every issue day of the configured windows (June-September 2023 and 2024 by default)
               from the public buckets (Google Cloud copy first, AWS copy second), one ecmwf_imdday_<day>.npz per issue day; rerun the same command to
               resume after an interruption
--publication  measure when the bucket received the last needed step of each cycle (Last-Modified minus the cycle time) on a
               sample of days and write reports/phase6_ecmwf_publication.{json,md}
All read configs/live.yaml. Every file written is recorded in manifests/data_manifest.jsonl with its URL and licence (CC BY 4.0).
"""
from __future__ import annotations

import argparse
import statistics
import sys
from datetime import date, datetime, time as clock, timedelta
from pathlib import Path

import numpy as np

from ..config import PROJECT_ROOT, load_config
from ..hazard.jsonio import dump_json
from ..http import DownloadError
from . import ecmwf, gfs

REPORT_STEM = "phase6_ecmwf_publication"
SAMPLE_STRIDE_DAYS = 6
PUBLICATION_REQUESTS_PER_S = 3.0      # the AWS copy answers bursts with HTTP 503
CYCLE_LABELS = (("00Z of D", 0, 0), ("18Z of D-1", -1, 18), ("12Z of D-1", -1, 12))


def _live(cfg: dict) -> int:
    issue_day = datetime.now(gfs.IST).date()
    try:
        path = ecmwf.fetch_live(issue_day, cfg, http=ecmwf.Http())
    except (ecmwf.EcmwfFetchError, DownloadError, gfs.GribDecodeError) as exc:
        print(f"[ecmwf] live fetch for {issue_day} failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    forecast = ecmwf.load_day(path)
    print(f"[ecmwf] live {issue_day}: HRES {forecast.hres_cycle:%Y-%m-%d %HZ} valid {forecast.hres_valid.tolist()}, "
          f"ENS {forecast.ens_cycle} members {forecast.n_members} valid {forecast.ens_valid.tolist()} -> {path}", flush=True)
    return 0


def _archive(cfg: dict, start: date | None, end: date | None, workers: int) -> int:
    archive = cfg["ecmwf"]["archive"]
    days = [d for d in ecmwf.archive_days(archive["windows"]) if (start is None or d >= start) and (end is None or d <= end)]
    print(f"[ecmwf] archive: {len(days)} issue days, cycle {archive['cycle']}, {workers} worker(s)", flush=True)
    http = ecmwf.Http()
    summary = ecmwf.fetch_archive(days, cfg, workers=workers, http=http)
    print(f"[ecmwf] archive: written {len(summary['written'])}, skipped {len(summary['skipped'])}, failed "
          f"{len(summary['failed'])}, incomplete {len(summary['incomplete'])}, {summary['seconds']:.0f} s", flush=True)
    for day, reason in list(summary["failed"].items())[:10]:
        print(f"[ecmwf] failed {day}: {reason}", file=sys.stderr)
    if summary["failed"]:
        print(f"[ecmwf] {len(summary['failed'])} failed day(s); re-run the same command to retry them", file=sys.stderr)
    return 1 if summary["failed"] else 0


def measure_publication(cfg: dict, days: list[date], http) -> dict:
    """Latency (hours after the cycle time) at which the last needed step of each product appeared in the bucket, per cycle."""
    rows = []
    for label, offset, hour in CYCLE_LABELS:
        for kind in ecmwf.KINDS:
            values, missing = [], 0
            for day in days:
                cycle = datetime.combine(day + timedelta(days=offset), clock(hour), tzinfo=ecmwf.UTC)
                hours = ecmwf.publication_latency_h(http, cycle, kind, day, cfg)
                if hours is None:
                    missing += 1
                else:
                    values.append(hours)
            ordered = sorted(values)
            rows.append({"cycle": label, "product": kind, "stream": ecmwf.stream_name(kind, datetime(2024, 1, 1, hour)),
                         "days": len(days), "found": len(values), "missing": missing,
                         "median_h": statistics.median(values) if values else None,
                         "p95_h": ordered[max(int(np.ceil(0.95 * len(ordered))) - 1, 0)] if values else None,
                         "max_h": max(values) if values else None})
    run_utc = "05:30"
    for row in rows:
        offset_h = {label: 24 * off + hr for label, off, hr in CYCLE_LABELS}[row["cycle"]]
        ready = None if row["max_h"] is None else offset_h + row["max_h"]       # hours after 00:00 UTC of the run day D
        if ready is None:
            row["newest_file_at"], row["before_run"] = None, False
            continue
        minutes = int(round(ready * 60))
        row["newest_file_at"] = f"D{'-1' if minutes < 0 else ''} {(minutes % 1440) // 60:02d}:{minutes % 60:02d} UTC"
        row["before_run"] = ready <= 5.5
    return {"run_time_utc": run_utc, "sample_days": [d.isoformat() for d in days], "rows": rows,
            "decision": _decision(rows, run_utc),
            "source": "Last-Modified of the last needed step file in the public bucket ecmwf-forecasts (HTTP HEAD)"}


def _decision(rows: list[dict], run_utc: str) -> str:
    """The cycle the live run uses: the newest one whose HRES and ensemble are both out before the run."""
    by_cycle: dict[str, list[dict]] = {}
    for row in rows:
        by_cycle.setdefault(row["cycle"], []).append(row)
    ready = [label for label, _, _ in CYCLE_LABELS if all(r["before_run"] for r in by_cycle[label])]
    late = [f"{label} ({max(r['newest_file_at'] for r in by_cycle[label])})" for label, _, _ in CYCLE_LABELS
            if label not in ready and all(r["newest_file_at"] for r in by_cycle[label])]
    if not ready:
        return f"No cycle is out before the {run_utc} UTC run."
    return (f"Decision: the live run (05:30 UTC, retries to 07:00 UTC) uses the newest cycle that is out for both products: "
            f"{ready[0]}; {', '.join(late) or 'no cycle'} is not out before the run, so it is never waited for. "
            f"The archive evaluation uses the 12Z run of D-1 (out the evening before on both public copies).")


def render_publication(result: dict) -> str:
    lines = ["# ECMWF open-data publication times", "",
             f"{result['source']}, {len(result['sample_days'])} sample days ({result['sample_days'][0]}..{result['sample_days'][-1]}, "
             f"June-September 2023 and 2024). Latency = Last-Modified minus the cycle time; the daily run starts at "
             f"{result['run_time_utc']} UTC (11:00 IST).", "",
             "| cycle | product | stream | found | median h | p95 h | max h | newest file at (from max) | out before the run |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in result["rows"]:
        f = lambda v: "n/a" if v is None else f"{v:.2f}"
        lines.append(f"| {r['cycle']} | {r['product']} | {r['stream']} | {r['found']}/{r['days']} | {f(r['median_h'])} | "
                     f"{f(r['p95_h'])} | {f(r['max_h'])} | {r['newest_file_at'] or 'n/a'} | {'yes' if r['before_run'] else 'no'} |")
    if result.get("decision"):
        lines += ["", result["decision"]]
    return "\n".join(lines) + "\n"


def _publication(cfg: dict, reports_dir: Path) -> int:
    days = ecmwf.archive_days(cfg["ecmwf"]["archive"]["windows"])[::SAMPLE_STRIDE_DAYS]
    result = measure_publication(cfg, days, ecmwf.Http(requests_per_s=PUBLICATION_REQUESTS_PER_S))
    reports_dir.mkdir(parents=True, exist_ok=True)
    dump_json(reports_dir / f"{REPORT_STEM}.json", result)
    (reports_dir / f"{REPORT_STEM}.md").write_text(render_publication(result), encoding="utf-8")
    print(f"[ecmwf] wrote {reports_dir / (REPORT_STEM + '.md')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    cfg = load_config("live")
    workers_max = int(cfg["ecmwf"]["archive"]["workers"])
    parser = argparse.ArgumentParser(description="Ingest ECMWF IFS open-data precipitation as IMD-day totals on the IMERG grid.")
    parser.add_argument("--live", action="store_true", help="newest published cycle from data.ecmwf.int")
    parser.add_argument("--archive", action="store_true", help="archived runs from the public bucket")
    parser.add_argument("--publication", action="store_true", help="measure the bucket's publication times")
    parser.add_argument("--start", type=date.fromisoformat, default=None, help="first archive issue day (default: the windows' start)")
    parser.add_argument("--end", type=date.fromisoformat, default=None, help="last archive issue day (default: the windows' end)")
    parser.add_argument("--workers", type=int, default=workers_max, help=f"parallel archive days, 1..{workers_max}")
    parser.add_argument("--mirrors", nargs="+", default=None, metavar="TEXT",
                        help="use only the archive base URLs containing one of these texts (e.g. googleapis)")
    parser.add_argument("--reports-dir", type=Path, default=PROJECT_ROOT / "reports")
    args = parser.parse_args(argv)
    if not (args.live or args.archive or args.publication):
        parser.error("choose --live, --archive and/or --publication")
    if not 1 <= args.workers <= workers_max:
        parser.error(f"--workers must be between 1 and {workers_max}")
    if args.mirrors:
        urls = [u for u in cfg["ecmwf"]["archive"]["base_urls"] if any(m in u for m in args.mirrors)]
        if not urls:
            parser.error(f"no archive base URL contains any of {args.mirrors}")
        cfg["ecmwf"]["archive"]["base_urls"] = urls
    status = 0
    if args.publication:
        status |= _publication(cfg, args.reports_dir)
    if args.live:
        status |= _live(cfg)
    if args.archive:
        status |= _archive(cfg, args.start, args.end, args.workers)
    return status


if __name__ == "__main__":
    sys.exit(main())
