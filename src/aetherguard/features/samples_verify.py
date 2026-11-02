"""CLI: python -m aetherguard.features.samples_verify [--out-dir DIR].

Verifies the frozen sample tables: checksums, table invariants, unchanged inputs and configuration, no negative
inside the event buffer, every positive cell-day present exactly once.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .samples import default_inputs, default_out_dir, load_configs, verify_samples


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the frozen Phase 1 sample tables.")
    parser.add_argument("--out-dir", type=Path, help="default: <data>/processed/features/samples")
    args = parser.parse_args(argv)
    out_dir = args.out_dir or default_out_dir()
    try:
        result = verify_samples(out_dir, default_inputs(), load_configs())
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if result["ok"]:
        print(f"OK: {out_dir} is frozen and intact (checksums, invariants, inputs and configuration verified)")
        return 0
    print(f"PROBLEMS in {out_dir}:")
    for problem in result["problems"]:
        print(f"  - {problem}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
