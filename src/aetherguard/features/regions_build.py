"""CLI: python -m aetherguard.features.regions_build [--skip-download] [--out-dir DIR].

Downloads the Natural Earth admin-0 polygons (idempotent), assigns a country and a region to every kept terrain
cell and writes `cell_regions.parquet` plus `cell_regions_report.json`.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..config import PROJECT_ROOT, data_root, load_config
from ..http import DownloadError
from ..manifest import Manifest
from .regions import build_cell_regions, fetch_boundaries


def format_report(report: dict, out_dir: Path) -> str:
    agreement = report["positive_agreement"]
    regions = ", ".join(f"{k} {v}" for k, v in report["per_region"].items())
    lines = [f"cell regions: {report['n_cells']} cells ({regions}); {report['no_country_cells']} without a country; "
             f"written to {out_dir}",
             f"  positives: {agreement['agree_cell_days']} of {agreement['n_cell_days']} cell-days agree with the "
             f"label store region, {agreement['disagree_cell_days']} differ in {len(agreement['disagree_cells'])} cells "
             f"({agreement['no_country_cell_days']} cell-days with no country polygon)"]
    for cell in agreement["disagree_cells"]:
        lines.append(f"    cell {cell['cell_id']}: label {cell['label_region']} vs cell {cell['cell_region']} "
                     f"(country {cell['country_code']}, {cell['n_cell_days']} cell-days)")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Assign a country and region to every terrain cell.")
    parser.add_argument("--skip-download", action="store_true", help="use the boundaries file already on disk")
    parser.add_argument("--out-dir", type=Path, help="default: <data>/processed/features")
    parser.add_argument("--manifest", type=Path, help="default: <project>/manifests/data_manifest.jsonl")
    args = parser.parse_args(argv)
    cfg = load_config("samples")
    root = data_root()
    out_dir = args.out_dir or root / "processed" / "features"
    boundaries = root / "raw" / "boundaries" / cfg["boundaries"]["file"]
    if not args.skip_download:
        manifest = Manifest(args.manifest or PROJECT_ROOT / "manifests" / "data_manifest.jsonl", root)
        try:
            boundaries = fetch_boundaries(root, manifest, cfg)
        except DownloadError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    try:
        report = build_cell_regions(root / "processed" / "terrain" / "cell_terrain.parquet", boundaries,
                                    root / "processed" / "splits" / "positive_cell_days.parquet", out_dir, cfg)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(format_report(report, out_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
