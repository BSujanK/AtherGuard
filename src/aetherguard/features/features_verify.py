"""CLI: python -m aetherguard.features.features_verify [--out-dir DIR].

Verifies the frozen feature tables: checksums, float32 feature columns, grouped columns, unchanged inputs and
configuration, and identical rows / row order versus the sample files.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .build import default_inputs, default_out_dir, load_configs, verify_features


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the frozen Phase 1 feature tables.")
    parser.add_argument("--out-dir", type=Path, help="default: <data>/processed/features")
    args = parser.parse_args(argv)
    out_dir = args.out_dir or default_out_dir()
    try:
        result = verify_features(out_dir, default_inputs(), load_configs())
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if result["ok"]:
        print(f"OK: {out_dir} is frozen and intact (checksums, columns, inputs, configuration and row identity verified)")
        return 0
    print(f"PROBLEMS in {out_dir}:")
    for problem in result["problems"]:
        print(f"  - {problem}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
