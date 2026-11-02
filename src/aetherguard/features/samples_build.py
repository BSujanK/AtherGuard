"""CLI: python -m aetherguard.features.samples_build [--out-dir DIR] [--force].

Builds and freezes the sample tables (negatives, universe, window and case-study sets) from the frozen splits, the
terrain table and the cell regions. A second run verifies the frozen files and reuses them; `--force` rebuilds.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .samples import SamplesIntegrityError, build_samples, default_inputs, default_out_dir, load_configs


def format_summary(manifest: dict, out_dir: Path, reused: bool) -> str:
    report = manifest["report"]
    floor = report["slope_floor"]
    lines = [f"samples {'reused (verified intact)' if reused else 'built and frozen'} in {out_dir} "
             f"(seed {manifest['seed']}, {manifest['elapsed_seconds']} s to build)",
             f"slope floor {floor['floor']:.4f} deg = p{floor['percentile']} of {floor['n_cells']} "
             f"{floor['reference_split']} positive cells; "
             + ", ".join(f"{r} {v['floor']:.2f}" for r, v in floor["per_region"].items())]
    for split, regions in report["negatives"].items():
        for region, s in regions.items():
            lines.append(f"negatives {split}/{region}: {s['accepted']} of {s['target']} (positives {s['positives_for_ratio']}), "
                         f"attempts {s['attempts']}, rejected {s['rejected']}")
    for split, regions in report["universe"].items():
        for region, u in regions.items():
            lines.append(f"universe {split}/{region}: size {u['universe_size']} ({u['n_candidate_cells']} cells x "
                         f"{u['n_days']} days), {u['positives_in_universe']} positives, "
                         f"{u['base_rate_per_100k_cell_days']:.2f} per 100k cell-days")
    window = report["window_2023"]
    lines.append(f"window 2023: {window['n_rows']} rows ({window['n_neighbourhood_cells']} neighbourhood + "
                 f"{window['n_control_cells']} control cells x {window['n_days']} days)")
    for name, case in report["case_studies"].items():
        lines.append(f"case {name}: {case['n_rows']} rows ({case['n_cells']} cells x {case['n_days']} days), "
                     f"{case['positive_cell_days']} positive cell-days")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build and freeze the Phase 1 sample tables.")
    parser.add_argument("--out-dir", type=Path, help="default: <data>/processed/features/samples")
    parser.add_argument("--force", action="store_true", help="replace an existing frozen build")
    args = parser.parse_args(argv)
    out_dir = args.out_dir or default_out_dir()
    try:
        manifest, reused = build_samples(default_inputs(), out_dir, force=args.force, cfg=load_configs())
    except (SamplesIntegrityError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(format_summary(manifest, out_dir, reused))
    return 0


if __name__ == "__main__":
    sys.exit(main())
