"""CLI: python -m aetherguard.ingest.imd_build [--start 2007 --end 2024] [--raw-dir DIR] [--out-dir DIR] [--manifest PATH].

Downloads the IMD yearly gridded rainfall files (idempotent), then builds the processed store and coverage mask.
"""
from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

from ..config import PROJECT_ROOT, data_root, load_config
from ..manifest import Manifest
from .imd import INDEX_NAME, ImdDownloadReport, build_imd_store, download_imd_years


def format_download(report: ImdDownloadReport) -> str:
    lines = [f"download: {len(report.downloaded)} fetched, {len(report.skipped)} already present, "
             f"{len(report.registered)} newly registered, {len(report.failed)} failed"]
    lines += [f"  FAILED {year}: {message}" for year, message in sorted(report.failed.items())]
    return "\n".join(lines)


def format_store(index: dict, out_dir: Path) -> str:
    years = index["years"]
    shares = {year: meta["nan_share"] for year, meta in years.items()}
    lowest, highest = min(shares, key=shares.get), max(shares, key=shares.get)
    grid = index["grid"]
    return "\n".join([
        f"store: {len(years)} years {min(years)}..{max(years)} in {out_dir} ({INDEX_NAME})",
        f"  grid {grid['n_lat']} x {grid['n_lon']} at {grid['step']} deg, lat {grid['lat_min']}..{grid['lat_max']}, "
        f"lon {grid['lon_min']}..{grid['lon_max']}",
        f"  NaN share per year: min {shares[lowest]:.1%} ({lowest}), max {shares[highest]:.1%} ({highest})",
        f"  coverage mask (valid on > {index['coverage_min_valid_share']:.0%} of days in every year): "
        f"{index['covered_cells']} of {grid['n_lat'] * grid['n_lon']} grid points",
    ])


def main(argv: list[str] | None = None, fetch: Callable[[int, Path], None] | None = None) -> int:
    imd_config = load_config("ingest")["imd"]
    parser = argparse.ArgumentParser(description="Download the IMD gridded rainfall years and build the store.")
    parser.add_argument("--start", type=int, default=imd_config["start_year"])
    parser.add_argument("--end", type=int, default=imd_config["end_year"])
    parser.add_argument("--raw-dir", type=Path, help="default: <data>/raw/imd")
    parser.add_argument("--out-dir", type=Path, help="default: <data>/processed/rain")
    parser.add_argument("--manifest", type=Path, help="default: <project>/manifests/data_manifest.jsonl")
    args = parser.parse_args(argv)
    raw_dir = args.raw_dir or data_root() / "raw" / "imd"
    out_dir = args.out_dir or data_root() / "processed" / "rain"
    manifest = Manifest(args.manifest or PROJECT_ROOT / "manifests" / "data_manifest.jsonl", data_root())
    report = download_imd_years(args.start, args.end, raw_dir, manifest, fetch=fetch)
    print(format_download(report))
    if report.failed:
        print("error: not building the store with failed years; re-run to retry them", file=sys.stderr)
        return 1
    print(format_store(build_imd_store(raw_dir, out_dir, args.start, args.end), out_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
