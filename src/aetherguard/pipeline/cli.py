"""python -m aetherguard.pipeline {run,status} (see configs/pipeline.yaml for the stages)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .runner import format_status, run_pipeline, stage_statuses
from .stages import Paths, PipelineConfigError, load_config, parse_stages, select_stages


def _split(values: list[str] | None) -> list[str] | None:
    if not values:
        return None
    return [name for value in values for name in value.split(",") if name]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m aetherguard.pipeline",
                                     description="Run or inspect the AetherGuard pipeline stages.")
    parser.add_argument("--config", type=Path, default=None, help="pipeline configuration (default configs/pipeline.yaml)")
    parser.add_argument("--root", type=Path, default=None, help="project root (default: this checkout)")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run stages in order, stopping at the first failure")
    run.add_argument("--from", dest="start", metavar="STAGE", help="first stage to run")
    run.add_argument("--to", dest="end", metavar="STAGE", help="last stage to run")
    run.add_argument("--only", action="append", metavar="STAGE", help="run only these stages (repeat or comma-separate)")
    run.add_argument("--include", action="append", metavar="STAGE", help="also run stages that are skipped by default (audit)")
    run.add_argument("--dry-run", action="store_true", help="print what would run, run nothing, write no logs")
    run.add_argument("--offline", action="store_true", help="skip network stages unless their outputs can be reused")
    run.add_argument("--force", action="store_true", help="ignore reuse: rerun the selected stages")
    sub.add_parser("status", help="per stage: outputs present, frozen-manifest verification, last run")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cfg = load_config(args.config)
        stages = parse_stages(cfg)
        paths = Paths.default()
        if args.root is not None:
            paths = Paths(args.root, paths.data, args.root / "reports")
        if args.command == "status":
            print(format_status(stage_statuses(cfg, stages, paths)))
            return 0
        chosen = select_stages(stages, args.start, args.end, _split(args.only), _split(args.include))
    except (PipelineConfigError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if not chosen:
        print("error: no stages selected", file=sys.stderr)
        return 2
    results, code = run_pipeline(cfg, chosen, paths, dry_run=args.dry_run, offline=args.offline, force=args.force)
    counts: dict[str, int] = {}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    print("summary: " + ", ".join(f"{n} {s}" for s, n in sorted(counts.items())))
    return code


if __name__ == "__main__":
    sys.exit(main())
