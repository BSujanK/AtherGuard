"""The data-derived alert-engine parameters again, on the pair of rain products the live run compares (phase 8).

    python -m aetherguard.alerts.derive_imerg [--out data/processed/alerts/alert_config_v4.json] [--report-dir reports]

Why. `alert_config_v3.json` took its source-disagreement range, heavy-rain amounts and station-agreement tolerances from
the v2 development store, which compares the IMD final grid with CHIRPS and measures stations against the v2 grid. The
live run compares the IMD real-time grid with IMERG and measures stations against IMERG (`live.adapter`), so the
parameters describe a different pair of products.

Development proxy (2007-2017, train + validation, the same weighted universe rows and in-domain positives as
`alerts.derive`):
* IMD side: the IMD final grid (the archive of the same product family as the real-time grid; there is no real-time
  archive for those years), read as the live run reads the real-time grid: the cell's nearest 0.25 degree point moved
  `imd_lon_offset_columns` columns (configs/live_run.yaml), 1- and 3-day totals ending on the row's IMD day;
* satellite side: IMERG Late on the IMD day at the cell's pixel, the frozen `irain_acc_1` / `irain_acc_3` of the row
  (what the model and the live `src_chi_acc_*` slot use);
* stations: |integ_trw_rain_1 - irain_acc_1|, the trust-weighted gauge mean against the IMERG grid, as live.
The percentiles and the weighting are those of configs/alerts.yaml `derivation` and `alerts.derive`, unchanged. The
hysteresis and `uncertain_high` values are those of alert_config_v3.json (they were chosen on the model's risk, not on
the rain products) and are copied.

Validity check of the proxy (no held-out data): on the published live days whose IMD real-time file of day D was there
(`src_dis_both` 1 in features_D0), the share of cells outside each range; on the development proxy, the same share in
the same calendar months. Both are reported; a range that the live pair leaves far more often than development is a sign
that IMD real-time differs from IMD final, and the report says so.

These parameters set confidence, and confidence feeds the blind-escalation rule (a cell that is not High and sees heavy
rain in any source is raised to at least Watch), so they can change levels; the live configuration does not read this
file until that effect has passed its own gate (docs/superpowers/specs/2026-11-13-aetherguard-post-rules-v4.md).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import PROJECT_ROOT, data_root, load_config_file
from ..features import sources as fs
from ..hazard import data as hd
from ..hazard import model as hm
from ..hazard.jsonio import dump_json
from ..manifest import sha256_file
from .config import AlertConfig, alerts_settings, load_config_file as load_alert_config, save_config
from .derive import _assert_development, weighted_quantile
from .frames import INTEG_DIR, group_path, join_group

DATA_DERIVED = ("dis_ratio_lo", "dis_ratio_hi", "heavy_acc1_mm", "heavy_acc3_mm", "agree_abs_mm", "agree_rel")
REPORT_STEM = "phase8_alert_config_v4"
HAZARD_CONFIG = PROJECT_ROOT / "configs" / "hazard_v3.yaml"
WINDOWS = (1, 3)


def load_rows(name: str, root: Path, hazard_cfg: dict) -> pd.DataFrame:
    """A development table with its IMERG (`irain`) and integrity (`integ`) columns."""
    frame = hd.load_table(name, root, hazard_cfg["extra_groups"], ["irain"])
    return join_group(frame, group_path(name, root, INTEG_DIR, "integ"))


def imd_windows(frame: pd.DataFrame, store: fs.DailyStore, lon_offset_columns: int) -> dict[int, np.ndarray]:
    """1- and 3-day IMD totals ending on each row's day at the live sampling point; NaN when a day of the window is missing."""
    pixels = fs._imd_pixels(frame["cell_id"].to_numpy(dtype=np.int64), lon_offset_columns)
    days = fs.day_numbers(pd.to_datetime(frame["date"]).to_numpy())
    series = store.gather(pixels, days - (max(WINDOWS) - 1), max(WINDOWS)).astype(np.float64)
    series[series < 0] = np.nan
    return {n: np.where(np.isfinite(series[:, -n:]).all(axis=1), series[:, -n:].sum(axis=1), np.nan) for n in WINDOWS}


def proxy_columns(frame: pd.DataFrame, store: fs.DailyStore, lon_offset_columns: int) -> pd.DataFrame:
    """The live-style evidence of each development row: IMD (proxy) and IMERG totals, their ratio and the station gap."""
    imd = imd_windows(frame, store, lon_offset_columns)
    sat = {n: frame[f"irain_acc_{n}"].to_numpy(dtype=np.float64) for n in WINDOWS}
    both = np.isfinite(imd[1]) & np.isfinite(sat[1])
    return pd.DataFrame({"imd_1": imd[1], "imd_3": imd[3], "sat_1": sat[1], "sat_3": sat[3], "both": both,
                         "ratio_3": (imd[3] + 1.0) / (sat[3] + 1.0),
                         "station": frame["integ_trw_rain_1"].to_numpy(dtype=np.float64), "grid": sat[1],
                         "month": pd.to_datetime(frame["date"]).dt.month.to_numpy()}, index=frame.index)


def derive_from_proxy(universe: pd.DataFrame, weights: np.ndarray, settings: dict) -> dict:
    d = settings["derivation"]
    both = universe["both"].to_numpy() & np.isfinite(universe["ratio_3"].to_numpy())
    lo, hi = (weighted_quantile(universe["ratio_3"].to_numpy()[both], weights[both], p) for p in d["dis_ratio_percentiles"])
    heavy = {n: weighted_quantile(np.fmax(universe[f"imd_{n}"].to_numpy(), universe[f"sat_{n}"].to_numpy()), weights,
                                  d["heavy_rain_universe_percentile"]) for n in WINDOWS}
    diff = universe["station"].to_numpy() - universe["grid"].to_numpy()
    agree_abs = weighted_quantile(np.abs(diff), weights, d["station_agree_abs_percentile"])
    larger = np.fmax(universe["station"].to_numpy(), universe["grid"].to_numpy())
    wet = np.isfinite(diff) & (larger >= d["station_agree_rel_min_mm"])
    agree_rel = weighted_quantile(np.abs(diff[wet]) / larger[wet], weights[wet], d["station_agree_rel_percentile"])
    return {"values": {"dis_ratio_lo": lo, "dis_ratio_hi": hi, "heavy_acc1_mm": heavy[1], "heavy_acc3_mm": heavy[3],
                       "agree_abs_mm": agree_abs, "agree_rel": agree_rel},
            "rows": {"universe": int(len(universe)), "both_sources": int(both.sum()), "station": int(np.isfinite(diff).sum()),
                     "station_wet": int(wet.sum())}}


def outside_share(ratio: np.ndarray, both: np.ndarray, lo: float, hi: float, weights=None) -> float | None:
    keep = both & np.isfinite(ratio)
    if not keep.any():
        return None
    out = (ratio[keep] < lo) | (ratio[keep] > hi)
    return float(np.average(out, weights=None if weights is None else weights[keep]))


def live_check(live_dir: Path, ranges: dict[str, tuple[float, float]]) -> dict:
    """On the published days with the IMD real-time file of day D (day-D columns valid), the share of cells whose
    IMD/IMERG 3-day ratio is outside each range."""
    days, ratios, months = [], [], []
    for folder in sorted(Path(live_dir).iterdir()):
        path = folder / "features_D0.parquet"
        if not (folder / "run.json").is_file() or not path.is_file():
            continue
        frame = pd.read_parquet(path, columns=["src_dis_both", "src_dis_ratio_3"])
        keep = (frame["src_dis_both"].to_numpy() == 1) & np.isfinite(frame["src_dis_ratio_3"].to_numpy(dtype=np.float64))
        if keep.sum() == 0:
            continue
        days.append(folder.name)
        ratios.append(frame["src_dis_ratio_3"].to_numpy(dtype=np.float64)[keep])
        months.append(np.full(int(keep.sum()), int(folder.name[5:7])))
    if not days:
        return {"days": [], "cell_days": 0, "outside": {}}
    ratio, month = np.concatenate(ratios), np.concatenate(months)
    both = np.ones(len(ratio), dtype=bool)
    return {"days": days, "cell_days": int(len(ratio)), "months": sorted({int(m) for m in month}),
            "outside": {name: outside_share(ratio, both, lo, hi) for name, (lo, hi) in ranges.items()},
            "ratio_percentiles": {str(p): float(np.percentile(ratio, p)) for p in (1, 5, 25, 50, 75, 95, 99)}}


def build(root: Path | None = None, live_dir: Path | None = None, run_cfg: dict | None = None) -> tuple[AlertConfig, dict]:
    root = Path(root or hd.features_dir())
    settings = alerts_settings()
    hazard_cfg = hm.hazard_config(HAZARD_CONFIG)
    run_cfg = run_cfg or load_config_file(PROJECT_ROOT / "configs" / "live_run.yaml")
    offset = int(run_cfg.get("imd_lon_offset_columns", 0))
    store = fs.load_imd(data_root() / "processed" / "rain")
    parts, files = [], {}
    for split in settings["derivation"]["dev_splits"]:
        name = hd.UNIVERSE_NAMES[split]
        frame = load_rows(name, root, hazard_cfg)
        _assert_development(frame, name, settings)
        parts.append(pd.concat([proxy_columns(frame, store, offset), frame[["weight"]]], axis=1))
        path = root / f"{name}_features.parquet"
        files[path.name] = {"sha256": sha256_file(path), "n_rows": int(len(frame))}
    universe = pd.concat(parts, ignore_index=True)
    weights = universe["weight"].to_numpy(dtype=np.float64)
    derived = derive_from_proxy(universe, weights, settings)
    v3 = load_alert_config(data_root() / "processed" / "alerts" / "alert_config_v3.json")
    config = AlertConfig.from_dict({**v3.to_dict(), **derived["values"]})
    ranges = {"v3": (v3.dis_ratio_lo, v3.dis_ratio_hi), "v4": (config.dis_ratio_lo, config.dis_ratio_hi)}
    both = universe["both"].to_numpy()
    ratio = universe["ratio_3"].to_numpy()
    month = universe["month"].to_numpy()
    live = live_check(Path(live_dir or data_root() / "live"), ranges)
    same_months = np.isin(month, live.get("months", []))
    proxy_outside = {name: {"all_months": outside_share(ratio, both, lo, hi, weights),
                            "live_months": outside_share(ratio, both & same_months, lo, hi, weights)}
                     for name, (lo, hi) in ranges.items()}
    record = {
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "proxy": {"imd": f"IMD final grid at the live sampling point (nearest 0.25 degree point moved {offset} column(s), "
                         "imd_lon_offset_columns), standing in for the IMD real-time grid (same product family; no "
                         "real-time archive exists for 2007-2017)",
                  "satellite": "IMERG Late on the IMD day at the cell's pixel (irain_acc_1 / irain_acc_3)",
                  "stations": "|integ_trw_rain_1 - irain_acc_1| (trust-weighted gauges against IMERG)"},
        "percentiles": {k: settings["derivation"][k] for k in ("dis_ratio_percentiles", "heavy_rain_universe_percentile",
                                                               "station_agree_abs_percentile", "station_agree_rel_percentile",
                                                               "station_agree_rel_min_mm")},
        "rows": derived["rows"], "inputs": files,
        "copied_from_v3": {k: getattr(v3, k) for k in ("exit_factor", "exit_days", "uncertain_percentile", "radius_km",
                                                       "ood_window_days", "ood_multiple", "ood_min_observed_days",
                                                       "engine_target_flag_rate")},
        "side_by_side": {k: {"v3": getattr(v3, k), "v4": getattr(config, k)} for k in DATA_DERIVED},
        "validity": {"development_share_outside_range": proxy_outside, "live_share_outside_range": live,
                     "expected_share_outside": 1 - (settings["derivation"]["dis_ratio_percentiles"][1]
                                                    - settings["derivation"]["dis_ratio_percentiles"][0]) / 100},
        "period": f"2007-01-01..{settings['derivation']['dev_end']} (train + validation splits)",
        "note": "development data only; no held-out row is read. Not read by the live run until its effect on levels "
                "(blind escalation) has passed its gate."}
    return config, record


def markdown(config: AlertConfig, record: dict) -> str:
    v = record["validity"]
    live = v["live_share_outside_range"]
    lines = ["# Alert-engine parameters on IMERG-era data (phase 8, development only)", "",
             "The six data-derived alert-engine parameters again, on the pair of products the live run compares (IMD "
             "against IMERG, gauges against IMERG), with the percentiles and weighting of `alerts.derive` unchanged. The "
             "hysteresis and `uncertain_high` values are copied from `alert_config_v3.json`.", "",
             "## Development proxy", "", *[f"- {k}: {t}" for k, t in record["proxy"].items()], "",
             f"Rows: {record['rows']['universe']:,} weighted universe cell-days, {record['rows']['both_sources']:,} with both "
             f"sources, {record['rows']['station']:,} with a usable station, {record['rows']['station_wet']:,} wet station "
             "cell-days.", "", "## Old and new values", "", "| parameter | v3 (IMD final vs CHIRPS) | v4 (IMD vs IMERG proxy) |",
             "|---|---|---|"]
    for k, pair in record["side_by_side"].items():
        lines.append(f"| `{k}` | {pair['v3']:.4g} | {pair['v4']:.4g} |")
    lines += ["", "## Is the proxy valid?", "",
              f"Share of cell-days outside the disagreement range (expected {100 * v['expected_share_outside']:.0f}% on the "
              "data a range was derived on):", "", "| range | development proxy, all months | development proxy, live months "
              "| live IMD real-time vs IMERG |", "|---|---|---|---|"]
    for name in ("v3", "v4"):
        d = v["development_share_outside_range"][name]
        pct = lambda x: "-" if x is None else f"{100 * x:.1f}%"
        lines.append(f"| {name} | {pct(d['all_months'])} | {pct(d['live_months'])} | {pct(live['outside'].get(name))} |")
    lines += ["", f"Live: {live['cell_days']:,} cell-days on {len(live['days'])} published days whose IMD file of day D was "
              f"there (months {live.get('months')}).", "",
              "## Effect on levels", "",
              "Confidence feeds the blind-escalation rule (a cell that is not High and sees heavy rain in any source is "
              "raised to at least Watch), so these values can change levels, not only confidence. The live configuration "
              "keeps alert_config_v3.json until that effect has passed its gate; the scratch replays that measure it are in "
              "the live-chain ledger.", "", "## Caveats", "",
              "- IMD final has more gauges than IMD real-time; the live pair can disagree more often than the proxy.",
              "- The live check covers the few published days with a day-D IMD file (afternoon runs), October-November only.",
              "- Development data only; nothing here was evaluated on held-out years.", ""]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m aetherguard.alerts.derive_imerg", description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--report-dir", type=Path, default=PROJECT_ROOT / "reports")
    args = parser.parse_args(argv)
    try:
        config, record = build()
    except (OSError, ValueError, KeyError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    out = args.out or data_root() / "processed" / "alerts" / "alert_config_v4.json"
    save_config(out, config, record)
    args.report_dir.mkdir(parents=True, exist_ok=True)
    dump_json(args.report_dir / f"{REPORT_STEM}.json", {"parameters": config.to_dict(), **record})
    (args.report_dir / f"{REPORT_STEM}.md").write_text(markdown(config, record), encoding="utf-8")
    print(f"wrote {out} and {args.report_dir / REPORT_STEM}.{{json,md}}")
    for k, pair in record["side_by_side"].items():
        print(f"  {k}: v3 {pair['v3']:.4g} -> v4 {pair['v4']:.4g}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
