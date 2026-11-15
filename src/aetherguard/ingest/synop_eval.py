"""Agreement of SYNOP IMD-day totals with a reference (spec 2026-11-14-aetherguard-same-day-gauges.md, section 6).

    python -m aetherguard.ingest.synop_eval v1 --ogimet-dir DIR --start 2024-07-01 --end 2024-07-31 --out FILE

V1 (the declared criterion): raw July 2024 SYNOP reports (OGIMET archive files, one `getsynop` response per file)
against GHCN-Daily of the same station and day from the local archive (source flag S in that period). The metrics are
those the spec declares; `criterion` is evaluated here from them, never by hand.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from . import synop as S

WET_MM = 1.0
CRITERION = {"within_tolerance_min": 0.95, "pearson_min": 0.95, "wet_hit_min": 0.95, "abs_bias_max_mm": 0.5}


def agreement(values: np.ndarray, reference: np.ndarray, abs_mm: float, rel: float) -> dict:
    """The section-6 metrics on the pairs where both are finite."""
    a, b = np.asarray(values, dtype=float), np.asarray(reference, dtype=float)
    ok = np.isfinite(a) & np.isfinite(b)
    a, b = a[ok], b[ok]
    n = int(len(a))
    if n == 0:
        return {"n": 0}
    wet_ref, dry_ref = b >= WET_MM, b < WET_MM
    tol = np.maximum(abs_mm, rel * np.maximum(a, b))
    corr = float(np.corrcoef(a, b)[0, 1]) if n > 2 and a.std() > 0 and b.std() > 0 else None
    return {"n": n, "bias_mm": float((a - b).mean()), "pearson": corr,
            "wet_hit_rate": float((a[wet_ref] >= WET_MM).mean()) if wet_ref.any() else None,
            "n_reference_wet": int(wet_ref.sum()),
            "false_wet_share": float((a[dry_ref] >= WET_MM).mean()) if dry_ref.any() else None,
            "within_tolerance": float((np.abs(a - b) <= tol).mean()),
            "mean_reference_mm": float(b.mean()), "mean_synop_mm": float(a.mean())}


def criterion_met(metrics: dict) -> bool:
    c = CRITERION
    return bool(metrics.get("n", 0) > 0 and metrics["within_tolerance"] >= c["within_tolerance_min"]
                and metrics["pearson"] is not None and metrics["pearson"] >= c["pearson_min"]
                and metrics["wet_hit_rate"] is not None and metrics["wet_hit_rate"] >= c["wet_hit_min"]
                and abs(metrics["bias_mm"]) <= c["abs_bias_max_mm"])


def totals_frame(versions, stations: list[str], days: pd.DatetimeIndex) -> tuple[pd.DataFrame, Counter]:
    """date x WMO station frame of IMD-day totals (NaN = no value) and the count of every `how`."""
    out = pd.DataFrame(np.nan, index=days, columns=stations, dtype=np.float64)
    hows: Counter = Counter()
    for day in days:
        for station in stations:
            value, how = S.imd_day_total(versions, station, day.date())
            hows[how] += 1
            if value is not None:
                out.at[day, station] = value
    return out, hows


def read_ogimet_dir(directory: Path) -> list[S.Report]:
    reports = []
    for path in sorted(Path(directory).glob("*.txt")):
        for line in path.read_text(encoding="latin-1").splitlines():
            report = S.parse_ogimet_line(line)
            if report is not None:
                reports.append(report)
    return reports


def station_wmo(raw_dir: Path | None = None) -> dict[str, str]:
    """GHCN station id -> WMO index (ghcnd-stations.txt columns 81-85) for the project's 140 stations."""
    from ..integrity.stations import ghcnd_raw_dir, select_station_meta
    raw = Path(raw_dir) if raw_dir is not None else ghcnd_raw_dir()
    ids = set(select_station_meta(raw)["id"])
    out = {}
    for line in (raw / "ghcnd-stations.txt").read_text(encoding="ascii", errors="replace").splitlines():
        if line[0:11] in ids and line[80:85].strip():
            out[line[0:11]] = line[80:85].strip()
    return out


def v1(ogimet_dir: Path, start: str, end: str, alert_config: Path) -> dict:
    """V1 of the spec: SYNOP July 2024 against the local GHCN-Daily archive (same station, same IMD day)."""
    from ..alerts.config import load_config_file
    from ..integrity.stations import load_full_series
    cfg = load_config_file(alert_config)
    wmo = station_wmo()
    days = pd.date_range(start, end, freq="D")
    versions = S.latest_versions(read_ogimet_dir(ogimet_dir))
    synop, hows = totals_frame(versions, sorted(set(wmo.values())), days)
    pairs_a, pairs_b, per_station = [], [], {}
    for sid, w in sorted(wmo.items()):
        series = load_full_series(sid).reindex(days)
        ref = series["value"].to_numpy(dtype=float)
        a = synop[w].to_numpy()
        pairs_a.append(a)
        pairs_b.append(ref)
        per_station[sid] = {"wmo": w, "n_ghcn": int(np.isfinite(ref).sum()), "n_both": int((np.isfinite(ref) & np.isfinite(a)).sum())}
    a, b = np.concatenate(pairs_a), np.concatenate(pairs_b)
    metrics = agreement(a, b, cfg.agree_abs_mm, cfg.agree_rel)
    return {"check": "V1", "period": [start, end], "stations": len(wmo), "station_days": int(len(a)),
            "ghcn_station_days": int(np.isfinite(b).sum()), "synop_station_days": int(np.isfinite(a).sum()),
            "coverage_of_ghcn_days": float((np.isfinite(a) & np.isfinite(b)).sum() / max(np.isfinite(b).sum(), 1)),
            "how": dict(hows), "tolerance": {"agree_abs_mm": cfg.agree_abs_mm, "agree_rel": cfg.agree_rel,
                                             "source": str(alert_config)},
            "metrics": metrics, "criterion": CRITERION, "criterion_met": criterion_met(metrics),
            "per_station": per_station}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m aetherguard.ingest.synop_eval")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("v1")
    p1.add_argument("--ogimet-dir", type=Path, required=True)
    p1.add_argument("--start", default="2024-07-01")
    p1.add_argument("--end", default="2024-07-31")
    p1.add_argument("--alert-config", type=Path, required=True)
    p1.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    result = v1(args.ogimet_dir, args.start, args.end, args.alert_config)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=1, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("metrics", "criterion_met", "coverage_of_ghcn_days", "how")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
