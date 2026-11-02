"""CLI: python -m aetherguard.events.build [--raw-dir DIR] [--out-dir DIR]."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..config import data_root
from .store import DROP_REASONS, build_events


def _format_summary(report: dict, out_dir: Path) -> str:
    lines = [f"label store written to {out_dir}",
             f"{'source':<14}{'input':>8}{'dropped':>9}{'kept':>8}{'positive':>10}{'day-exact':>11}{'window':>8}"
             "  dropped by reason"]
    for name, counts in report["sources"].items():
        dropped = sum(counts["n_dropped"].values())
        reasons = ", ".join(f"{r}={counts['n_dropped'][r]}" for r in DROP_REASONS if counts["n_dropped"][r])
        lines.append(f"{name:<14}{counts['n_input']:>8}{dropped:>9}{counts['n_kept']:>8}"
                     f"{counts['n_positive']:>10}{counts['n_day_exact_positive']:>11}"
                     f"{counts['n_inventory_window_positive']:>8}  {reasons}")
    for label, key in (("positives", "positives_per_region_per_year"),
                       ("day-exact", "day_exact_positives_per_region_per_year"),
                       ("window", "inventory_window_positives_per_region_per_year")):
        for region, years in report[key].items():
            total = sum(years.values())
            lines.append(f"{label} {region} ({total}): " + (", ".join(f"{y}={n}" for y, n in years.items()) or "none"))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the unified landslide label store.")
    parser.add_argument("--raw-dir", type=Path,
                        help="directory holding the four source files (default: <data>/raw/manual)")
    parser.add_argument("--out-dir", type=Path,
                        help="output directory (default: <data>/processed/labels)")
    args = parser.parse_args(argv)
    raw_dir = args.raw_dir or data_root() / "raw" / "manual"
    out_dir = args.out_dir or data_root() / "processed" / "labels"
    report = build_events(raw_dir, out_dir)
    print(_format_summary(report, out_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
