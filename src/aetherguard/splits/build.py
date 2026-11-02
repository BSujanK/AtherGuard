"""CLI: python -m aetherguard.splits.build [--events PATH] [--out-dir DIR] [--force]."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..config import data_root
from .freeze import SplitsFrozenError, build_splits


def default_events_path() -> Path:
    return data_root() / "processed" / "labels" / "events.parquet"


def default_out_dir() -> Path:
    return data_root() / "processed" / "splits"


def _share(summary: dict) -> str:
    return "n/a" if summary["share"] is None else f"{summary['share']:.1%}"


def format_summary(manifest: dict, out_dir: Path) -> str:
    splits = manifest["splits"]
    regions = list(next(iter(splits.values()))["regions"])
    lines = [f"splits frozen in {out_dir} (cell-days / events)",
             f"{'split':<24}" + "".join(f"{r:>16}" for r in regions) + f"{'total':>16}  dates"]
    for name, split in splits.items():
        cells = "".join(f"{split['regions'][r]['cell_days']:>8}/{split['regions'][r]['events']:<7}" for r in regions)
        lines.append(f"{name:<24}{cells}{split['cell_days']:>8}/{split['events']:<7}"
                     f"  {split['min_date']}..{split['max_date']}")
    window = manifest["window_test"]
    lines.append(f"{window['name']}: {window['cell_windows']} cell-windows / {window['events']} events "
                 f"({window['window_start_min']}..{window['window_end_max']})")
    for name, case in manifest["case_studies"].items():
        flag = "  <- NO POSITIVES" if case["cell_days"] == 0 else ""
        lines.append(f"case study {name} ({case['region']}, {case['start']}..{case['end']}): "
                     f"{case['cell_days']} cell-days / {case['events']} events{flag}")
    leak = manifest["leakage"]
    lines.append(f"leakage (within {leak['days']} days and {leak['cells']} cells of a "
                 f"{leak['reference_split']} positive; {leak['n_reference']} reference cell-days, report only):")
    for name, summary in (*leak["per_split"].items(), ("all checked", leak["total"])):
        lines.append(f"  {name:<14}{summary['n_within']:>5} of {summary['n']:<5} ({_share(summary)})")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build and freeze the positive cell-days and splits.")
    parser.add_argument("--events", type=Path, help="label store (default: <data>/processed/labels/events.parquet)")
    parser.add_argument("--out-dir", type=Path, help="output directory (default: <data>/processed/splits)")
    parser.add_argument("--force", action="store_true", help="replace an existing frozen build")
    args = parser.parse_args(argv)
    out_dir = args.out_dir or default_out_dir()
    try:
        manifest = build_splits(args.events or default_events_path(), out_dir, force=args.force)
    except SplitsFrozenError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(format_summary(manifest, out_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
