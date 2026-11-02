"""Phase 3d: fit, evaluate and freeze the extreme-rain corrector; write reports/phase3_corrector_report.md/.json.

    python -m aetherguard.corrector.report [--n-boot 1000] [--reports-dir DIR] [--force-cells]

Headline corrector: CHIRPS-side predictors only. The variant WITH the IMD grid predictors is reported as
'leakage-risk' (the IMD gauge grid probably ingests the same gauges). Station splits are the frozen Phase 2 ones.
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

from ..config import data_root
from ..grid import latlon_to_cell
from ..integrity import engine_data, grids
from ..integrity.common import dumps_strict, display_path, integrity_dir, reports_dir
from ..integrity.splits import SPLIT_SEED, make_station_splits
from ..integrity.stations import load_station_set
from . import cells, data as cdata, evaluate as ceval
from .model import CorrectorModel, apply_linear, fit_corrector, linear_quantile_baseline

SEED = 20261301
WAYANAD = {"lat": 11.51, "lon": 76.13, "date": "2024-07-30", "imd_mm": 179.24,
           "dates": ("2024-07-23", "2024-08-02")}
GAP_CLOSED_FRACTION = 0.5     # the gap counts as closed when q90 reaches at least half of the IMD value
METHODS = ("raw_chirps", "linear_scaling", "corrector", "corrector_with_imd")


def corrector_dir() -> Path:
    return data_root() / "processed" / "corrector"


def load_rows(raw_dir=None):
    """(window, refs, terrain, splits, rows): the usable station-day table with every predictor."""
    window = load_station_set(raw_dir, start="2007-01-01", end="2024-12-31")
    refs = engine_data.load_or_build_refs(window.meta, window.values.index, integrity_dir() / engine_data.REFS_CACHE_NAME, False)
    terrain = pd.read_parquet(data_root() / "processed" / "terrain" / "cell_terrain.parquet")
    oof = pd.read_parquet(integrity_dir() / "engine_outputs_2007_oof.parquet", columns=["station", "date", "flagged"])
    flagged = oof.pivot(index="date", columns="station", values="flagged")
    splits = make_station_splits(window.meta, seed=SPLIT_SEED)
    rows = cdata.station_table(window, refs, terrain, flagged, splits)
    return window, refs, terrain, splits, rows


def fit_variants(rows: pd.DataFrame):
    train, val = rows[rows["split"] == "train"], rows[rows["split"] == "val"]
    headline = fit_corrector(train, val, cdata.PREDICTORS, SEED)
    leakage = fit_corrector(train, val, cdata.PREDICTORS + cdata.IMD_PREDICTORS, SEED)
    coefs = linear_quantile_baseline(train)
    return headline, leakage, coefs


def wayanad_case(models: dict[str, CorrectorModel], terrain: pd.DataFrame) -> dict:
    """Predictions for the Wayanad cell on the IMD days around 2024-07-30, from CHIRPS-side predictors."""
    cell = int(latlon_to_cell(WAYANAD["lat"], WAYANAD["lon"]))
    static = terrain.set_index("cell_id").reindex([cell])
    elevation = float(static["elev_mean"].iloc[0]) if static["elev_mean"].notna().any() else float("nan")
    meta = pd.DataFrame([{"id": "WAYANAD", "lat": WAYANAD["lat"], "lon": WAYANAD["lon"], "elevation_m": elevation}])
    dates = pd.date_range(*WAYANAD["dates"])
    refs = grids.station_grid_refs(meta, dates)
    frames = cdata.station_predictors(SimpleNamespace(meta=meta), refs, terrain)
    table = pd.DataFrame({name: frame["WAYANAD"].to_numpy() for name, frame in frames.items()}, index=dates)
    table.index.name = "date"
    for name, values in cdata.calendar_predictors(dates).items():
        table[name] = values
    out = {"cell_id": cell, "terrain_available": bool(static["elev_mean"].notna().any()), "elevation_m": elevation, "days": {}}
    for date, row in table.iterrows():
        one = row.to_frame().T
        entry = {"imd_mm": float(row["imd_1"]), "chirps_aligned_mm": float(row["chirps_1"]), "chirps_3day_mm": float(row["chirps_3"])}
        for name, model in models.items():
            pred = model.predict(one.astype(float)).iloc[0]
            entry[name] = {k: float(v) for k, v in pred.items()}
        out["days"][str(date.date())] = entry
    target = out["days"][WAYANAD["date"]]
    imd = target["imd_mm"]
    for name in models:
        q = target[name]
        out[f"{name}_summary"] = {
            "q50_share_of_imd": q["q50"] / imd, "q90_share_of_imd": q["q90"] / imd, "q99_share_of_imd": q["q99"] / imd,
            "gap_closed": bool(q["q90"] >= GAP_CLOSED_FRACTION * imd)}
    out["raw_chirps_share_of_imd"] = target["chirps_aligned_mm"] / imd
    return out


def _f(x, d=2):
    return "n/a" if x is None or (isinstance(x, float) and not np.isfinite(x)) else f"{x:.{d}f}"


def _ci(ci):
    if ci is None or not np.isfinite(ci[0]):
        return ""
    return " n/a (degenerate)" if ci[0] == ci[1] else f" [{_f(ci[0])}, {_f(ci[1])}]"


def verdicts(ev: dict) -> list[str]:
    lines = []
    for alpha in ("0.5", "0.9", "0.99"):
        for name in ("corrector", "corrector_with_imd", "linear_scaling"):
            cell = ev["pinball"][name][alpha]
            lo, hi = cell["diff_ci"]
            word = "beats" if hi < 0 else ("loses to" if lo > 0 else "ties (CI of the paired loss difference contains 0)")
            lines.append(f"pinball alpha {alpha}: {name} {word} raw CHIRPS (skill {_f(cell['skill_vs_reference'], 3)}, "
                         f"paired diff {_f(cell['diff_vs_reference'], 3)}{_ci(cell['diff_ci'])})")
    for alpha in ("0.5", "0.9", "0.99"):
        for name in ("corrector", "corrector_with_imd"):
            cell = ev["pinball"][name][alpha]
            lo, hi = cell["diff_vs_linear_ci"]
            word = "beats" if hi < 0 else ("loses to" if lo > 0 else "ties (CI of the paired loss difference contains 0)")
            lines.append(f"pinball alpha {alpha}: {name} {word} the linear quantile scaling "
                         f"(paired diff {_f(cell['diff_vs_linear'], 3)}{_ci(cell['diff_vs_linear_ci'])})")
    exc = ev["exceedance"]["methods"]
    for name in ("corrector", "corrector_with_imd", "linear_scaling"):
        a, b = exc[name], exc["raw_chirps"]
        word = "above" if a["pr_auc_ci"][0] > b["pr_auc"] else ("below" if a["pr_auc_ci"][1] < b["pr_auc"] else "not separable from")
        lines.append(f"exceedance PR-AUC: {name} {_f(a['pr_auc'], 3)}{_ci(a['pr_auc_ci'])} is {word} raw CHIRPS "
                     f"{_f(b['pr_auc'], 3)}{_ci(b['pr_auc_ci'])}")
    return lines


def render_markdown(report: dict) -> str:
    c = report["data"]
    ev = report["evaluation_test"]
    lines = ["# Phase 3d - extreme-rain corrector", "",
             "Target: gauge daily rain (IMD-day) on clean real days (150-valid-day station-years) not flagged by the "
             "out-of-fold integrity engine, on days where aligned CHIRPS exists. Headline predictors exclude IMD; "
             "`corrector_with_imd` is the LEAKAGE-RISK variant (the IMD grid probably ingests these gauges). "
             "Station splits are the frozen Phase 2 ones; 95% CIs resample TEST stations.", "",
             "## Data", "", "| split | stations | rows | exceedance rows | exceedances |", "|---|---|---|---|---|"]
    for split, e in c["by_split"].items():
        lines.append(f"| {split} | {e['stations']} | {e['rows']} | {e['exceedance_rows']} | {e['exceedances']} |")
    lines += ["", f"Only {c['by_split']['test']['stations']} TEST stations (of 140) have clean, unflagged days with CHIRPS; "
              f"{c['by_split']['test']['exceedances']} TEST exceedance days. Share of rows without terrain (station cell not in the "
              f"terrain store): {_f(c['terrain_nan_share'], 3)}. Per-station threshold: 99th percentile of wet days "
              f"(>= 1 mm) in 2007-2015 ({c['stations_with_threshold']} stations have >= 30 wet days).", ""]
    lines += ["## Pinball loss on TEST stations (mean mm [95% CI]; skill = 1 - loss/raw loss)", "",
              "| method | alpha 0.5 | alpha 0.9 | alpha 0.99 |", "|---|---|---|---|"]
    for name in METHODS:
        cells_ = []
        for alpha in ("0.5", "0.9", "0.99"):
            cell = ev["pinball"][name][alpha]
            text = f"{_f(cell['mean'], 3)}{_ci(cell['ci'])}"
            if "skill_vs_reference" in cell:
                text += f"; skill {_f(cell['skill_vs_reference'], 3)}, diff {_f(cell['diff_vs_reference'], 3)}{_ci(cell['diff_ci'])}"
            if "diff_vs_linear" in cell:
                text += f"; vs linear {_f(cell['diff_vs_linear'], 3)}{_ci(cell['diff_vs_linear_ci'])}"
            cells_.append(text)
        lines.append(f"| {name} | " + " | ".join(cells_) + " |")
    lines += ["", "## Coverage of the 0.9 / 0.99 quantiles on TEST (target in header)", "",
              "| method | 0.9 | 0.99 |", "|---|---|---|"]
    for name in METHODS:
        lines.append(f"| {name} | " + " | ".join(
            f"{_f(ev['coverage'][name][a]['coverage'], 3)}{_ci(ev['coverage'][name][a]['ci'])}" for a in ("0.9", "0.99")) + " |")
    top = ev["top1pct_bias"]
    lines += ["", f"## Bias on the top 1% of TEST gauge days (gauge >= {_f(top['threshold_mm'], 1)} mm; {top['rows']} rows at "
              f"{top['stations']} stations; mean gauge {_f(top['mean_gauge_mm'], 1)} mm)", "",
              "| method | q50 mean bias mm | q90 | q99 |", "|---|---|---|---|"]
    for name in METHODS:
        lines.append(f"| {name} | " + " | ".join(
            f"{_f(top['methods'][name][q]['mean_bias_mm'], 1)}{_ci(top['methods'][name][q]['ci'])}" for q in ("q50", "q90", "q99")) + " |")
    exc = ev["exceedance"]
    lines += ["", f"## Exceedance of the station 99th wet-day percentile ({exc['positives']} positives of {exc['rows']} TEST rows at "
              f"{exc['stations_with_positives']} of {exc['stations']} stations)", "",
              "| score | PR-AUC [CI] | recall at 1% false-flag [CI] | recall at 5% false-flag [CI] |", "|---|---|---|---|"]
    for name, m in exc["methods"].items():
        lines.append(f"| {name} | {_f(m['pr_auc'], 3)}{_ci(m['pr_auc_ci'])} | " + " | ".join(
            f"{_f(m['recall'][r]['recall'], 3)}{_ci(m['recall'][r]['ci'])}" for r in ("0.01", "0.05")) + " |")
    case = report["wayanad"]
    lines += ["", f"## Wayanad check (cell {case['cell_id']}, {WAYANAD['lat']} N {WAYANAD['lon']} E; terrain "
              f"{'available' if case['terrain_available'] else 'MISSING'}; elevation {_f(case['elevation_m'], 0)} m)", "",
              "| IMD day | IMD mm | CHIRPS aligned mm | CHIRPS 3-day mm | q50 | q90 | q99 | P(exceed) | with IMD: q50 | q90 | q99 |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
    for date, d in case["days"].items():
        h, i = d["corrector"], d["corrector_with_imd"]
        lines.append(f"| {date} | {_f(d['imd_mm'], 1)} | {_f(d['chirps_aligned_mm'], 1)} | {_f(d['chirps_3day_mm'], 1)} | "
                     f"{_f(h['q50'], 1)} | {_f(h['q90'], 1)} | {_f(h['q99'], 1)} | {_f(h['p_exceed'], 3)} | "
                     f"{_f(i['q50'], 1)} | {_f(i['q90'], 1)} | {_f(i['q99'], 1)} |")
    s = case["corrector_summary"]
    lines += ["", f"On {WAYANAD['date']} the IMD value is {_f(case['days'][WAYANAD['date']]['imd_mm'], 1)} mm; aligned CHIRPS "
              f"gives {_f(case['raw_chirps_share_of_imd'], 2)} of it. The CHIRPS-only corrector predicts q50 {_f(s['q50_share_of_imd'], 2)}, "
              f"q90 {_f(s['q90_share_of_imd'], 2)}, q99 {_f(s['q99_share_of_imd'], 2)} of the IMD value. "
              f"Verdict (the gap counts as closed when q90 >= {GAP_CLOSED_FRACTION:.0%} of IMD): "
              f"{'the corrector closes the gap' if s['gap_closed'] else 'the corrector does NOT close the gap'}.", ""]
    lines += ["## Verdicts (from the CIs above)", ""] + [f"- {v}" for v in report["verdicts"]]
    lines += ["", "## Notes and limits", ""] + [f"- {n}" for n in report["notes"]]
    lines += ["", f"Runtime {report['runtime_seconds']} s.", ""]
    return "\n".join(lines)


def build_report(raw_dir=None, n_boot: int = ceval.N_BOOT, force_cells: bool = False) -> dict:
    started = time.perf_counter()
    window, refs, terrain, splits, rows = load_rows(raw_dir)
    headline, leakage, coefs = fit_variants(rows)
    test = rows[rows["split"] == "test"].reset_index(drop=True)
    methods = {"raw_chirps": ceval.raw_baseline(test["chirps_1"]), "linear_scaling": apply_linear(coefs, test["chirps_1"]),
               "corrector": headline.predict(test), "corrector_with_imd": leakage.predict(test)}
    scores = {"raw_chirps": test["chirps_1"].to_numpy(), "linear_scaling": methods["linear_scaling"]["q99"].to_numpy(),
              "corrector": methods["corrector"]["p_exceed"].to_numpy(),
              "corrector_with_imd": methods["corrector_with_imd"]["p_exceed"].to_numpy()}
    evaluation = ceval.evaluate(test, methods, scores, n_boot)
    case = wayanad_case({"corrector": headline, "corrector_with_imd": leakage}, terrain)
    model_dir = corrector_dir() / "model"
    headline.save(model_dir)
    leakage.save(model_dir / "leakage_risk")
    manifest, reused = cells.build_cell_files(headline, data_root() / "processed" / "features",
                                              data_root() / "processed" / "features" / "corrector", model_dir, force=force_cells)
    by_split = {s: {"stations": int(part["station"].nunique()), "rows": int(len(part)),
                    "exceedance_rows": int(part["exceed"].notna().sum()), "exceedances": int(part["exceed"].sum())}
                for s, part in rows.groupby("split")}
    report = {
        "data": {"by_split": by_split, "terrain_nan_share": float(rows["elev_mean"].isna().mean()),
                 "stations_with_threshold": int(rows.loc[rows["p99"].notna(), "station"].nunique()),
                 "predictors": cdata.PREDICTORS, "imd_predictors": cdata.IMD_PREDICTORS},
        "tuning": {"headline": headline.card["tuning"], "leakage_risk": leakage.card["tuning"]},
        "linear_scaling_coefficients": {str(a): {"slope": c[0], "intercept": c[1]} for a, c in coefs.items()},
        "evaluation_test": evaluation, "wayanad": case, "verdicts": verdicts(evaluation),
        "cell_files": {"reused": reused, "nan_share": manifest.get("nan_share"), "files": list(manifest["files"])},
        "notes": [
            "Headline predictors exclude IMD; `corrector_with_imd` is a leakage-risk variant, not for use.",
            "The exceedance threshold is the station's own 99th wet-day percentile in 2007-2015; on cells the classifier "
            "is applied with the same absolute predictors, so corr_p_exceed99 means 'exceeds a typical station p99', "
            "not a per-cell percentile.",
            "elev_point is the station elevation for stations and the cell's mean elevation for cells.",
            "Terrain is missing for stations whose cell is not in the terrain store (NaN, handled natively by LightGBM).",
            "Few usable stations: TEST has very few stations with clean, unflagged, CHIRPS-covered days, so every CI is wide.",
            "Gauge rain is the target; the corrector can only learn the gauge-vs-satellite relation at the 36 station "
            "sites, mostly lowland: it cannot be assumed to transfer to windward slopes.",
        ],
        "runtime_seconds": round(time.perf_counter() - started, 1)}
    return report


def write_reports(report: dict, out_dir=None) -> tuple[Path, Path]:
    out = Path(out_dir) if out_dir is not None else reports_dir()
    out.mkdir(parents=True, exist_ok=True)
    md, js = out / "phase3_corrector_report.md", out / "phase3_corrector_report.json"
    js.write_text(dumps_strict(report), encoding="utf-8", newline="\n")
    md.write_text(render_markdown(report), encoding="utf-8", newline="\n")
    return md, js


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw-dir", default=None)
    parser.add_argument("--reports-dir", default=None)
    parser.add_argument("--n-boot", type=int, default=ceval.N_BOOT)
    parser.add_argument("--force-cells", action="store_true", help="rebuild the frozen corr tables")
    args = parser.parse_args(argv)
    report = build_report(args.raw_dir, args.n_boot, args.force_cells)
    md, js = write_reports(report, args.reports_dir)
    print(f"wrote {display_path(md)} and {display_path(js)}")
    for line in report["verdicts"][:3]:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
