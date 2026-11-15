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


def v1(ogimet_dir: Path, start: str, end: str, alert_config: Path, isd_presence: dict | None = None) -> dict:
    """V1 of the spec: SYNOP July 2024 against the local GHCN-Daily archive (same station, same IMD day).

    `isd_presence` ({wmo: [ISO dates whose 03 UTC FM-12 record is in ISD]}) adds a POST-HOC diagnostic, not the
    criterion: the same metrics on the station-days whose 03 UTC report GSOD (and so GHCN-Daily) could have read."""
    from ..alerts.config import load_config_file
    from ..integrity.stations import load_full_series
    cfg = load_config_file(alert_config)
    wmo = station_wmo()
    days = pd.date_range(start, end, freq="D")
    versions = S.latest_versions(read_ogimet_dir(ogimet_dir))
    synop, hows = totals_frame(versions, sorted(set(wmo.values())), days)
    pairs_a, pairs_b, present, per_station = [], [], [], {}
    for sid, w in sorted(wmo.items()):
        series = load_full_series(sid).reindex(days)
        ref = series["value"].to_numpy(dtype=float)
        a = synop[w].to_numpy()
        pairs_a.append(a)
        pairs_b.append(ref)
        have = set((isd_presence or {}).get(w, []))
        present.append(np.array([d.date().isoformat() in have for d in days]))
        per_station[sid] = {"wmo": w, "n_ghcn": int(np.isfinite(ref).sum()), "n_both": int((np.isfinite(ref) & np.isfinite(a)).sum())}
    a, b = np.concatenate(pairs_a), np.concatenate(pairs_b)
    metrics = agreement(a, b, cfg.agree_abs_mm, cfg.agree_rel)
    diagnostic = None
    if isd_presence is not None:
        keep = np.concatenate(present)
        diagnostic = {"what": "post-hoc: only station-days whose 03 UTC report is in ISD (not the criterion)",
                      "metrics": agreement(a[keep], b[keep], cfg.agree_abs_mm, cfg.agree_rel),
                      "ghcn_zero_while_synop_wet_and_no_isd_03utc": int(((b == 0) & (a >= WET_MM) & ~keep).sum()),
                      "ghcn_zero_while_synop_wet_with_isd_03utc": int(((b == 0) & (a >= WET_MM) & keep).sum())}
    return {"diagnostic": diagnostic, "check": "V1", "period": [start, end], "stations": len(wmo), "station_days": int(len(a)),
            "ghcn_station_days": int(np.isfinite(b).sum()), "synop_station_days": int(np.isfinite(a).sum()),
            "coverage_of_ghcn_days": float((np.isfinite(a) & np.isfinite(b)).sum() / max(np.isfinite(b).sum(), 1)),
            "how": dict(hows), "tolerance": {"agree_abs_mm": cfg.agree_abs_mm, "agree_rel": cfg.agree_rel,
                                             "source": str(alert_config)},
            "metrics": metrics, "criterion": CRITERION, "criterion_met": criterion_met(metrics),
            "per_station": per_station}


def v2(start: str, end: str, alert_config: Path, ghcn_rows: Path, imd_glob: str) -> dict:
    """V2 of the spec (descriptive): the stored SYNOP totals (no cut-off) of `start`..`end` against GHCN-Daily 2026
    (access-service rows with attributes, split by the flag-H zeros) and against the IMD real-time grid at the
    station's nearest 0.25 degree point (the engine's own live `imd` reference)."""
    import glob

    from ..alerts.config import load_config_file
    from ..integrity.stations import select_station_meta
    from ..live.sources import is_h_zero, parse_imd_grid
    from .imd import ImdGrid
    from .synop_store import load_store, station_day_totals, to_reports
    cfg = load_config_file(alert_config)
    wmo = station_wmo()
    meta = select_station_meta().set_index("id")
    days = pd.date_range(start, end, freq="D")
    frame = load_store()
    first = pd.Timestamp(days[0]).tz_localize("UTC") - pd.Timedelta(hours=21)
    frame = frame[(frame["time"] > first) & (frame["time"] <= pd.Timestamp(days[-1]).tz_localize("UTC") + pd.Timedelta(hours=3))]
    synop, how = station_day_totals(to_reports(frame), wmo, days)
    ghcn_all = pd.DataFrame(np.nan, index=days, columns=synop.columns)
    ghcn_measured = ghcn_all.copy()
    for row in json.loads(Path(ghcn_rows).read_text(encoding="utf-8")):
        stamp = pd.Timestamp(row["DATE"])
        if row.get("PRCP") is None or stamp not in ghcn_all.index or row["STATION"] not in ghcn_all.columns:
            continue
        ghcn_all.at[stamp, row["STATION"]] = float(row["PRCP"])
        if not is_h_zero(row):
            ghcn_measured.at[stamp, row["STATION"]] = float(row["PRCP"])
    imd = pd.DataFrame(np.nan, index=days, columns=synop.columns)
    points = {sid: ImdGrid.nearest_index(meta.at[sid, "lat"], meta.at[sid, "lon"]) for sid in synop.columns}
    seen = {}
    for path in glob.glob(imd_glob):
        stamp = pd.Timestamp(Path(path).stem)
        if stamp in imd.index and stamp not in seen:
            seen[stamp] = parse_imd_grid(Path(path).read_bytes())
    for stamp, grid in seen.items():
        imd.loc[stamp] = [np.nan if points[s] is None else grid[points[s]] for s in synop.columns]
    a = synop.to_numpy().ravel()
    m = lambda ref: agreement(a, ref.to_numpy().ravel(), cfg.agree_abs_mm, cfg.agree_rel)  # noqa: E731
    h_zero = ghcn_all.notna() & ghcn_measured.isna()
    monsoon = synop.index.month.isin([6, 7, 8, 9])
    return {"check": "V2", "period": [start, end], "stations": len(wmo),
            "synop_station_days": int(synop.notna().to_numpy().sum()), "station_days": int(synop.size),
            "how": {str(k): int(v) for k, v in pd.Series(how.to_numpy().ravel()).value_counts().items()},
            "ghcn_station_days": int(ghcn_all.notna().to_numpy().sum()),
            "ghcn_h_zero_station_days": int(h_zero.to_numpy().sum()),
            "ghcn_h_zero_where_synop_wet": int((h_zero & (synop >= WET_MM)).to_numpy().sum()),
            "imd_days": len(seen),
            "metrics": {"GHCN-Daily 2026, all values": m(ghcn_all),
                        "GHCN-Daily 2026, flag-H zeros removed": m(ghcn_measured),
                        "IMD real-time grid, nearest point": m(imd)},
            "synop_wet_share_jun_sep": float((synop[monsoon] >= WET_MM).to_numpy().sum()
                                             / max(synop[monsoon].notna().to_numpy().sum(), 1)),
            "note": ("GHCN-Daily 2026 is source flag 2 (Synoptic Summary of the Day v2); its flag-H zeros are not measured "
                     "zeros. The IMD real-time grid is gridded and includes these stations among its inputs: agreement "
                     "with it is not independent evidence.")}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m aetherguard.ingest.synop_eval")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("v1")
    p1.add_argument("--ogimet-dir", type=Path, required=True)
    p1.add_argument("--start", default="2024-07-01")
    p1.add_argument("--end", default="2024-07-31")
    p1.add_argument("--alert-config", type=Path, required=True)
    p1.add_argument("--out", type=Path, required=True)
    p1.add_argument("--isd-presence", type=Path, default=None)
    p2 = sub.add_parser("v2")
    p2.add_argument("--start", default="2026-07-15")
    p2.add_argument("--end", default="2026-11-15")
    p2.add_argument("--alert-config", type=Path, required=True)
    p2.add_argument("--ghcn-rows", type=Path, required=True)
    p2.add_argument("--imd-glob", required=True)
    p2.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.cmd == "v2":
        result = v2(args.start, args.end, args.alert_config, args.ghcn_rows, args.imd_glob)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=1, allow_nan=False) + chr(10), encoding="utf-8")
        print(json.dumps({k: result[k] for k in ("metrics", "ghcn_h_zero_station_days", "ghcn_h_zero_where_synop_wet", "synop_station_days", "how")}, indent=1))
        return 0
    presence = json.loads(args.isd_presence.read_text())["present"] if args.isd_presence else None
    result = v1(args.ogimet_dir, args.start, args.end, args.alert_config, presence)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=1, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("metrics", "criterion_met", "coverage_of_ghcn_days", "how", "diagnostic")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
