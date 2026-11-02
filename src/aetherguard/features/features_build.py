"""CLI: python -m aetherguard.features.features_build [--out-dir DIR] [--force].

Builds and freezes the feature tables for every frozen sample file; a second run verifies and reuses them.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .build import REPORT_NAME, FeaturesIntegrityError, build_features, default_inputs, default_out_dir, load_configs


def format_summary(manifest: dict, report: dict, out_dir: Path, reused: bool) -> str:
    lines = [f"features {'reused (verified intact)' if reused else 'built and frozen'} in {out_dir} "
             f"({manifest['runtime_seconds']} s to build)"]
    for name, entry in report["files"].items():
        nan = ", ".join(f"{g} {v['mean_column_nan_share']:.1%}" for g, v in entry["nan_share"].items())
        sources = ", ".join(f"{k} {v}" for k, v in entry["rain_source"].items())
        lines.append(f"{name}: {entry['rows']} rows; NaN share {nan}; rain_source {sources}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build and freeze the Phase 1 feature tables.")
    parser.add_argument("--out-dir", type=Path, help="default: <data>/processed/features")
    parser.add_argument("--force", action="store_true", help="replace an existing frozen build")
    args = parser.parse_args(argv)
    out_dir = args.out_dir or default_out_dir()
    try:
        manifest, reused = build_features(default_inputs(), out_dir, force=args.force, cfg=load_configs())
    except (FeaturesIntegrityError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    report = json.loads((out_dir / REPORT_NAME).read_text(encoding="utf-8"))
    print(format_summary(manifest, report, out_dir, reused))
    return 0


if __name__ == "__main__":
    sys.exit(main())
