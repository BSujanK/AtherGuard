"""CLI: python -m aetherguard.ingest.power_build

Reads the NASA POWER MERRA-2 soil wetness slab for the domain and saves <data>/processed/rain/power_wetness.npz.
"""
from __future__ import annotations

import sys

from ..config import data_root, load_config
from .power import build_power_wetness


def main() -> int:
    cfg = load_config("ingest")
    out_dir = data_root() / "processed" / "rain"
    index = build_power_wetness(cfg, out_dir)
    grid, period = index["grid"], index["period"]
    print(f"[power] {period['n_days']} days {period['start']}..{period['end']} on a "
          f"{grid['n_lat']}x{grid['n_lon']} MERRA-2 grid in {index['elapsed_seconds']} s -> {out_dir}")
    for name, stats in index["variables"].items():
        print(f"[power] {name}: NaN share {stats['nan_share']:.4f}, range {stats['min']}..{stats['max']}, "
              f"fill values {stats['n_fill_value']}, out of range {stats['n_out_of_range']}, "
              f"chunks {stats['chunks_time_lat_lon']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
