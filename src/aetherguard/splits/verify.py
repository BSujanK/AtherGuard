"""CLI: python -m aetherguard.splits.verify [--events PATH] [--out-dir DIR]."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .build import default_out_dir
from .freeze import verify_splits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the frozen splits against their manifest.")
    parser.add_argument("--events", type=Path,
                        help="label store to also check and reproduce the splits from "
                             "(default: file checksums only)")
    parser.add_argument("--out-dir", type=Path, help="splits directory (default: <data>/processed/splits)")
    args = parser.parse_args(argv)
    out_dir = args.out_dir or default_out_dir()
    try:
        result = verify_splits(out_dir, args.events)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if result["ok"]:
        checked = "files, events checksum and reproduction" if args.events else "file checksums"
        print(f"OK: {out_dir} is frozen and intact ({checked} verified)")
        return 0
    print(f"PROBLEMS in {out_dir}:")
    for problem in result["problems"]:
        print(f"  - {problem}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
