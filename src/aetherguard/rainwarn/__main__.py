"""Heavy-rain warnings command line (spec 2026-11-14-aetherguard-rain-warnings.md).

    python -m aetherguard.rainwarn climatology                 build data/processed/rainwarn/climatology.npz
    python -m aetherguard.rainwarn study [--resume]            fit, verify, write reports/phase8_rain_warnings.{json,md}
    python -m aetherguard.rainwarn report                      re-render the markdown from the JSON
    python -m aetherguard.rainwarn v2-dev                      spec section 12 on 2023 + 2024: calibration_v2.json
    python -m aetherguard.rainwarn v2-test2025                 the one test on June-September 2025
    python -m aetherguard.rainwarn run --date D --live-dir DIR [--out-dir DIR]
                                                               rain_warnings.parquet + rain_warnings.md of one run day
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from ..config import PROJECT_ROOT, data_root, load_config_file

CONFIG = PROJECT_ROOT / "configs" / "rainwarn.yaml"


def load_settings(path: Path = CONFIG) -> dict:
    return load_config_file(path)


def data_path(relative: str) -> Path:
    return data_root() / relative


def _progress(message: str) -> None:
    print(f"[rainwarn] {message}", flush=True)


def cmd_climatology(cfg: dict) -> int:
    from ..ingest import imerg
    from . import climatology as C
    domain = C.domain_from_parquet(data_path(cfg["cells_from"]))
    _progress(f"domain: {len(domain.pixels)} pixels")
    c = cfg["climatology"]
    store = imerg.ImergStore(data_path(cfg["rain_dir"]), "late")
    clim = C.build(store, domain, int(c["first_year"]), int(c["last_year"]), window_days=int(c["window_days"]),
                   season_months=tuple(c["season_months"]),
                   percentile_floor_mm=float(c["percentile_floor_mm"]), progress=_progress)
    path = clim.save(data_path(cfg["out_dir"]) / c["file"])
    _progress(f"wrote {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m aetherguard.rainwarn")
    parser.add_argument("--config", type=Path, default=CONFIG)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("climatology")
    study = sub.add_parser("study")
    study.add_argument("--resume", action="store_true", help="reuse the cached per-set tallies in the out directory")
    sub.add_parser("report")
    sub.add_parser("v2-dev", help="spec section 12: choose and fit the shipped calibration, derive the v2 levels")
    sub.add_parser("v2-test2025", help="spec section 12.4: the one test on June-September 2025 (refuses a second run)")
    run = sub.add_parser("run")
    run.add_argument("--date", required=True, type=date.fromisoformat)
    run.add_argument("--live-dir", required=True, type=Path, help="the run directory of the day (features_D0.parquet)")
    run.add_argument("--out-dir", type=Path, default=None, help="where to write (default: the run directory)")
    run.add_argument("--calibration", type=Path, default=None)
    args = parser.parse_args(argv)
    cfg = load_settings(args.config)
    if args.command == "climatology":
        return cmd_climatology(cfg)
    if args.command == "study":
        from . import study as S
        return S.run_study(cfg, resume=args.resume, progress=_progress)
    if args.command == "report":
        from . import report as R
        return R.rerender(cfg)
    if args.command == "v2-dev":
        from . import v2
        return v2.run_dev(cfg, progress=_progress)
    if args.command == "v2-test2025":
        from . import v2
        return v2.run_test2025(cfg, progress=_progress)
    from . import product
    return product.run_day(cfg, args.date, args.live_dir, args.out_dir, calibration=args.calibration)


if __name__ == "__main__":
    sys.exit(main())
