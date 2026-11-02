"""Day-basis experiment: which day does a station's daily value belong to, relative to IMD and CHIRPS?

For every IMD-covered station, using CLEAN real days only in 2007-2018, the station value of day t is paired
with a reference value of day t + lag (lags -2..+2): the reference is IMD, CHIRPS on the UTC day (lag -1 is the
UTC day that holds 21 of the 24 hours of an IMD day), and CHIRPS aligned to the IMD day (`align_utc_to_imd_day`).
Only days where both values are valid and at least one is > 0 enter a correlation (shared dry days would
inflate it). Per lag the report gives the median over stations of the per-station Pearson and Spearman
correlation, with a 95% bootstrap CI over stations, and the exceedance agreement for days >= 50 mm.

    python -m aetherguard.integrity.day_basis [--raw-dir DIR] [--reports-dir DIR]

Nothing is assumed: the peak lag of every product is read from the numbers, and the verdict sentences are
generated from them.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import rankdata

from . import evaluate, inject
from .common import display_path, dumps_strict, integrity_dir, reports_dir
from .engine_data import ENGINE_PERIOD, REFS_CACHE_NAME, load_or_build_refs
from .stations import load_station_set

LAGS = (-2, -1, 0, 1, 2)
PERIOD = ("2007-01-01", "2018-12-31")
MIN_PAIRS = 100          # a station-lag needs this many pairs to count
EXCEED_MM = 50.0
N_BOOT = 1000
BOOT_SEED = 20261004
PRODUCTS = ("imd", "chirps_utc", "chirps_aligned")


def shifted(x: np.ndarray, lag: int) -> np.ndarray:
    """out[t] = x[t + lag] (NaN where t + lag is outside the series)."""
    out = np.full(len(x), np.nan, dtype=np.float64)
    if lag >= 0:
        out[:len(x) - lag] = x[lag:]
    else:
        out[-lag:] = x[:lag]
    return out


def lag_correlations(station: np.ndarray, ref: np.ndarray, lag: int, rows: np.ndarray) -> dict:
    """Pearson and Spearman of station[t] vs ref[t + lag] over rows `rows` where both are valid and at least one > 0."""
    r = shifted(ref, lag)
    use = rows & np.isfinite(station) & np.isfinite(r) & ((station > 0) | (r > 0))
    a, b = station[use], r[use]
    out = {"n_pairs": int(use.sum()), "pearson": float("nan"), "spearman": float("nan")}
    if len(a) >= MIN_PAIRS and a.std() > 0 and b.std() > 0:
        out["pearson"] = float(np.corrcoef(a, b)[0, 1])
        ra, rb = rankdata(a), rankdata(b)
        out["spearman"] = float(np.corrcoef(ra, rb)[0, 1])
    return out


def lag_table(station: pd.DataFrame, ref: pd.DataFrame, lags=LAGS, period=PERIOD) -> pd.DataFrame:
    """Per station and lag: n_pairs, pearson, spearman (NaN below MIN_PAIRS). `station` holds only clean values."""
    rows = np.asarray((station.index >= period[0]) & (station.index <= period[1]))
    records = []
    for sid in station.columns:
        s, g = station[sid].to_numpy(np.float64), ref[sid].to_numpy(np.float64)
        for lag in lags:
            records.append({"station": sid, "lag": lag, **lag_correlations(s, g, lag, rows)})
    return pd.DataFrame(records)


def exceedance_table(station: pd.DataFrame, ref: pd.DataFrame, lags=LAGS, period=PERIOD,
                     threshold: float = EXCEED_MM, n_boot: int = N_BOOT) -> dict:
    """Per lag: of the station days >= threshold, the share where the reference (day t + lag) is also >= threshold,
    and of the reference days >= threshold the share where the station is (clean station days with a valid
    reference only); pooled counts plus bootstrap CIs over stations."""
    rows = np.asarray((station.index >= period[0]) & (station.index <= period[1]))
    out = {}
    for lag in lags:
        hits_s, hits_r = [], []
        for sid in station.columns:
            s, r = station[sid].to_numpy(np.float64), shifted(ref[sid].to_numpy(np.float64), lag)
            both = rows & np.isfinite(s) & np.isfinite(r)
            with np.errstate(invalid="ignore"):
                s_ex, r_ex = both & (s >= threshold), both & (r >= threshold)
            hits_s.append((r[s_ex] >= threshold).astype(float))
            hits_r.append((s[r_ex] >= threshold).astype(float))
        pooled = lambda groups: (int(sum(g.sum() for g in groups)), int(sum(len(g) for g in groups)))  # noqa: E731
        (k1, n1), (k2, n2) = pooled(hits_s), pooled(hits_r)
        out[str(lag)] = {
            "station_exceedances": n1, "reference_also_exceeds": k1,
            "share_of_station_days": k1 / n1 if n1 else float("nan"),
            "share_ci": list(evaluate.bootstrap_ci(hits_s, np.mean, n_boot, BOOT_SEED)),
            "reference_exceedances": n2, "station_also_exceeds": k2,
            "share_of_reference_days": k2 / n2 if n2 else float("nan"),
            "reference_share_ci": list(evaluate.bootstrap_ci(hits_r, np.mean, n_boot, BOOT_SEED))}
    return out


def summarize(table: pd.DataFrame, n_boot: int = N_BOOT) -> dict:
    """Per lag: median over stations of Pearson / Spearman with bootstrap CI, station count, pooled pairs, and the
    peak lag (highest median) for each correlation."""
    out: dict = {"lags": {}}
    for lag, part in table.groupby("lag"):
        entry = {"pooled_pairs": int(part["n_pairs"].sum())}
        for kind in ("pearson", "spearman"):
            values = part[kind].dropna().to_numpy()
            entry[f"median_{kind}"] = float(np.median(values)) if len(values) else float("nan")
            entry[f"{kind}_ci"] = list(evaluate.bootstrap_ci([np.array([v]) for v in values], np.median,
                                                             n_boot, BOOT_SEED))
            entry["n_stations"] = int(len(values))
        out["lags"][str(int(lag))] = entry
    for kind in ("pearson", "spearman"):
        medians = {int(k): v[f"median_{kind}"] for k, v in out["lags"].items()}
        finite = {k: v for k, v in medians.items() if np.isfinite(v)}
        out[f"peak_lag_{kind}"] = max(finite, key=finite.get) if finite else None
    best = table.dropna(subset=["pearson"]).sort_values(["station", "pearson"], ascending=[True, False])
    best = best.groupby("station").first()["lag"]
    out["per_station_peak_lag_counts"] = {str(int(k)): int(v) for k, v in best.value_counts().sort_index().items()}
    return out


def _verdict(name: str, summary: dict) -> str:
    lags = summary["lags"]
    peak = summary["peak_lag_pearson"]
    if peak is None:
        return f"{name}: no lag has enough pairs."
    at0, at_peak = lags.get("0"), lags[str(peak)]
    text = (f"{name}: median Pearson peaks at lag {peak:+d} ({at_peak['median_pearson']:.3f}, 95% CI "
            f"[{at_peak['pearson_ci'][0]:.3f}, {at_peak['pearson_ci'][1]:.3f}]; {at_peak['n_stations']} stations); "
            f"Spearman peaks at lag {summary['peak_lag_spearman']:+d}")
    if peak != 0 and at0 is not None:
        text += (f"; lag 0 is NOT the maximum (median Pearson {at0['median_pearson']:.3f}, CI "
                 f"[{at0['pearson_ci'][0]:.3f}, {at0['pearson_ci'][1]:.3f}])")
    return text + f"; per-station peak lags: {summary['per_station_peak_lag_counts']}."


def build_day_basis_report(station: pd.DataFrame, refs: dict[str, pd.DataFrame], n_boot: int = N_BOOT,
                           min_valid_days: int = inject.MIN_VALID_DAYS_PER_YEAR) -> dict:
    """`station`: clean station values only (NaN elsewhere); `refs`: reference frames by product name."""
    products = {}
    for name in PRODUCTS:
        table = lag_table(station, refs[name])
        products[name] = summarize(table, n_boot)
    verdict = [_verdict(name, products[name]) for name in PRODUCTS]
    verdict.append(_implication(products))
    return {"period": list(PERIOD), "lags": list(LAGS), "min_pairs_per_station_lag": MIN_PAIRS,
            "n_stations": int(station.shape[1]), "min_valid_days": min_valid_days,
            "n_stations_with_enough_pairs": max(p["lags"]["0"]["n_stations"] for p in products.values()), "pairs_rule": "both valid and either > 0; clean real days only",
            "lag_convention": "station day t is paired with reference day t + lag",
            "products": products, "exceedance_imd_50mm": exceedance_table(station, refs["imd"], n_boot=n_boot),
            "verdict": verdict}


def _implication(products: dict) -> str:
    imd = products["imd"]["peak_lag_pearson"]
    utc = products["chirps_utc"]["peak_lag_pearson"]
    aligned = products["chirps_aligned"]["peak_lag_pearson"]
    parts = []
    if imd is None or utc is None or aligned is None:
        return "Implication: not all products have enough pairs; no verdict on the D5 alignment."
    parts.append("station vs IMD agrees best at lag 0 (same day label)" if imd == 0 else
                 f"station vs IMD does NOT peak at lag 0 (peak {imd:+d}): the station day label is offset from the "
                 "IMD day label")
    parts.append("CHIRPS on the UTC day is best matched by the previous UTC day (lag -1), as an IMD-day label "
                 "(03:00 UTC D-1 to 03:00 UTC D) predicts" if utc == -1 else
                 f"CHIRPS-UTC peaks at lag {utc:+d}, not the lag -1 that the 03:00 UTC IMD-day boundary predicts")
    parts.append("the D5-aligned CHIRPS agrees best at lag 0, which supports the alignment" if aligned == 0 else
                 f"the D5-aligned CHIRPS peaks at lag {aligned:+d}, not 0: the alignment is not supported as "
                 "implemented")
    return "Implication for D5: " + "; ".join(parts) + "."


def render_markdown(report: dict) -> str:
    lines = ["# Phase 2b - day-basis experiment", "",
             f"{report['n_stations']} IMD-covered stations ({report['n_stations_with_enough_pairs']} with enough clean "
             f"pairs; clean = station-year >= {report['min_valid_days']} valid days), clean real days {report['period'][0]}..{report['period'][1]}; "
             f"{report['pairs_rule']}. {report['lag_convention']}. Medians over stations (>= "
             f"{report['min_pairs_per_station_lag']} pairs per station and lag), 95% bootstrap CI over stations.", ""]
    for name, summary in report["products"].items():
        lines += [f"## station vs {name}", "", "| lag | median Pearson [CI] | median Spearman [CI] | stations | pooled pairs |",
                  "|---|---|---|---|---|"]
        for lag, row in summary["lags"].items():
            pc, sc = row["pearson_ci"], row["spearman_ci"]
            lines.append(f"| {int(lag):+d} | {row['median_pearson']:.3f} [{pc[0]:.3f}, {pc[1]:.3f}] | "
                         f"{row['median_spearman']:.3f} [{sc[0]:.3f}, {sc[1]:.3f}] | {row['n_stations']} | "
                         f"{row['pooled_pairs']} |")
        lines.append("")
    lines += ["## Exceedance agreement, days >= 50 mm (station vs IMD)", "",
              "| lag | station days >= 50 | IMD also >= 50 [CI] | IMD days >= 50 | station also >= 50 [CI] |",
              "|---|---|---|---|---|"]
    for lag, row in report["exceedance_imd_50mm"].items():
        def cell(share, ci):
            return "n/a" if not np.isfinite(share) else f"{share:.3f} [{ci[0]:.3f}, {ci[1]:.3f}]"
        lines.append(f"| {int(lag):+d} | {row['station_exceedances']} | "
                     f"{cell(row['share_of_station_days'], row['share_ci'])} | {row['reference_exceedances']} | "
                     f"{cell(row['share_of_reference_days'], row['reference_share_ci'])} |")
    lines += ["", "Caveat: the IMD grid is interpolated from IMD gauges that probably include some of these stations, so "
              "agreement with IMD at lag 0 shows the day labels are consistent, not that the two are independent; "
              "CHIRPS (satellite plus gauges, UTC day) is the independent check on the timing.", "",
              "## Verdict (generated from the numbers above)", ""] + [f"- {v}" for v in report["verdict"]] + [""]
    sens = report.get("sensitivity")
    if sens:
        lines += [f"## Sensitivity: clean = station-year >= {sens['min_valid_days']} valid days "
                  f"({sens['n_stations_with_enough_pairs']} stations with enough pairs)", ""]
        lines += [f"- {v}" for v in sens["verdict"]] + [""]
    return "\n".join(lines)


SENSITIVITY_MIN_VALID_DAYS = 150   # a looser clean-day rule: more stations, same question


def _report_for(full, refs, min_valid_days: int, n_boot: int) -> dict:
    clean = inject.clean_real_mask(full, min_valid_days)
    imd_ok = refs.values["imd"].loc[PERIOD[0]:PERIOD[1]].notna().any().to_numpy()
    ids = list(full.meta["id"][imd_ok])
    station = full.values[ids].where(clean[ids])
    return build_day_basis_report(station, {name: refs.values[name][ids] for name in PRODUCTS}, n_boot,
                                  min_valid_days)


def run(raw_dir=None, reports=None, n_boot: int = N_BOOT) -> dict:
    full = load_station_set(raw_dir, start=ENGINE_PERIOD[0], end=ENGINE_PERIOD[1])
    refs = load_or_build_refs(full.meta, full.values.index, integrity_dir() / REFS_CACHE_NAME, False)
    report = _report_for(full, refs, inject.MIN_VALID_DAYS_PER_YEAR, n_boot)
    report["sensitivity"] = _report_for(full, refs, SENSITIVITY_MIN_VALID_DAYS, n_boot)
    out = Path(reports) if reports is not None else reports_dir()
    out.mkdir(parents=True, exist_ok=True)
    (out / "phase2b_day_basis.json").write_text(dumps_strict(report), encoding="utf-8", newline="\n")
    (out / "phase2b_day_basis.md").write_text(render_markdown(report), encoding="utf-8", newline="\n")
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw-dir", default=None)
    parser.add_argument("--reports-dir", default=None)
    parser.add_argument("--n-boot", type=int, default=N_BOOT)
    args = parser.parse_args(argv)
    report = run(args.raw_dir, args.reports_dir, args.n_boot)
    out = Path(args.reports_dir) if args.reports_dir else reports_dir()
    print(f"wrote {display_path(out / 'phase2b_day_basis.md')}")
    for line in report["verdict"]:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
