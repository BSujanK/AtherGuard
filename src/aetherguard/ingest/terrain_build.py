"""CLI: python -m aetherguard.ingest.terrain_build [--workers 6] [--raw-dir DIR] [--out-dir DIR] [--manifest PATH] [--skip-download].

Downloads the Copernicus GLO-90 tiles covering both region boxes (idempotent, resumable), then writes
`cell_terrain.parquet` and `terrain_report.json`. Exit code 1 when a tile failed to download (ocean tiles that do
not exist are expected and are not failures) or the tiles cannot be processed.
"""
from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

from ..config import PROJECT_ROOT, data_root
from ..manifest import Manifest
from .terrain import (MAX_WORKERS, TerrainError, TileDownloadReport, build_terrain, default_boxes, download_tiles,
                      tiles_for_boxes)

PROGRESS_EVERY = 50


def format_download(report: TileDownloadReport) -> str:
    lines = [f"download: {len(report.ok)} fetched ({report.bytes_downloaded / 1e6:.0f} MB), "
             f"{len(report.already_present)} already present, {len(report.absent)} absent (ocean), "
             f"{len(report.failed)} failed"]
    lines += [f"  FAILED {name}: {message}" for name, message in sorted(report.failed.items())]
    return "\n".join(lines)


def format_build(report: dict, out_dir: Path) -> str:
    cells = report["cells"]
    kept = ", ".join(f"{k} {v}" for k, v in cells["kept_by_region_box"].items())
    detail = ", ".join(f"{k} {v}" for k, v in cells["insufficient_dem_detail"].items() if v)
    return "\n".join([
        f"terrain: {cells['cells_kept']} of {cells['cells_considered']} cells kept ({kept}) in {out_dir}",
        f"  dropped insufficient_dem: {cells['cells_dropped']['insufficient_dem']}" + (f" ({detail})" if detail else ""),
    ])


def main(argv: list[str] | None = None, fetch: Callable[[tuple[int, int], Path], None] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download Copernicus GLO-90 tiles and build per-cell terrain.")
    parser.add_argument("--workers", type=int, default=MAX_WORKERS, help=f"parallel downloads, 1..{MAX_WORKERS}")
    parser.add_argument("--raw-dir", type=Path, help="default: <data>/raw/terrain/glo90")
    parser.add_argument("--out-dir", type=Path, help="default: <data>/processed/terrain")
    parser.add_argument("--manifest", type=Path, help="default: <project>/manifests/data_manifest.jsonl")
    parser.add_argument("--skip-download", action="store_true", help="build from the tiles already on disk")
    args = parser.parse_args(argv)
    if not 1 <= args.workers <= MAX_WORKERS:
        parser.error(f"--workers must be between 1 and {MAX_WORKERS}")
    raw_dir = args.raw_dir or data_root() / "raw" / "terrain" / "glo90"
    out_dir = args.out_dir or data_root() / "processed" / "terrain"
    boxes = default_boxes()
    report = None
    if not args.skip_download:
        manifest = Manifest(args.manifest or PROJECT_ROOT / "manifests" / "data_manifest.jsonl", data_root())

        def progress(done: int, total: int) -> None:
            if done % PROGRESS_EVERY == 0 or done == total:
                print(f"  {done}/{total} tiles", file=sys.stderr, flush=True)

        report = download_tiles(tiles_for_boxes(boxes), raw_dir, manifest, args.workers, fetch=fetch,
                                progress=progress)
        print(format_download(report))
        if report.failed:
            print("error: not building the terrain table with failed tiles; re-run to retry them", file=sys.stderr)
            return 1
    try:
        built = build_terrain(raw_dir, out_dir, boxes, download_report=report)
    except TerrainError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(format_build(built, out_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
