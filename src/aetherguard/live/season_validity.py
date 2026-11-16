"""Season of validity of the live alert chain: a measurement, no model change (phase 8).

    python -m aetherguard.live.season_validity [--out reports]     # reports/phase8_season_validity.{json,md}

Question: the live run scores every day of the year. Over which months was each part of the published chain developed and
tested, how large is the alert burden outside them, and how many development events exist there to train or test it?

Read, and nothing else (no held-out event outcome is read):
* the frozen split configuration (`splits_manifest.json` `config.day_splits`): which calendar days are development;
* the development positives (`positive_cell_days.parquet`, read with a filter on the train and validation splits only)
  and the development sample tables (positives, matched negatives, universe negatives) by month and region;
* the development out-of-fold scores of v4 (`hazard/v4/oof/oof_v4.parquet`, the cross-validation that adopted it):
  detection of the positives and the weighted share of universe cell-days at the card's raw Watch / Warning / Emergency
  thresholds, by month;
* the months of the panels the post-model rules and the alert parameters were chosen on (`burden.SEASON_START/END`) and
  of the held-out season panels (`verify.seasons.SEASON_START/END`);
* the v4 risk panels of the held-out seasons (`alerts/v4_seasons`, risks only, no events): the point-level share by month
  against the v4 card's thresholds of each region (no post-model rule, no hysteresis);
* the published live days (`<live_dir>/*/run.json`): lead 0 level counts by day and the model that scored them.

The recommendation is written from these numbers (`recommend`); the alert chain is not changed here. The visible flag
it recommends is `live.season.season_record`, wired into the run.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from ..alerts import levels as lv
from ..config import PROJECT_ROOT, data_root
from ..hazard.jsonio import dump_json
from . import burden
from . import season as sn

MONTHS = tuple(range(1, 13))
REPORT_STEM = "phase8_season_validity"
DEV_SPLITS = ("train", "validation")
LEVEL_KEYS = ("watch", "warning", "emergency")
CAVEATS = [
    "Development numbers are out of fold (year-blocked CV 2007-2017) but every month has few events outside June-September, "
    "so the monthly detection there has wide uncertainty (the counts are given).",
    "Detection counts what the catalogues recorded; the catalogues miss most landslides and report them where people live.",
    "Held-out season shares are point levels of the model (risk against the card's thresholds of the region), without the "
    "post-model rules or the hysteresis the live run adds; they read risks only, never an event.",
    "Live shares come from the published run.json of each day; the days before 2026-11-13 were scored by v3, from 2026-11-13 by v4.",
]


def _month_counts(months, values=None) -> dict[str, float]:
    series = pd.Series(np.ones(len(months)) if values is None else values, index=np.asarray(months))
    totals = series.groupby(level=0).sum()
    return {str(m): float(totals.get(m, 0.0)) for m in MONTHS}


# ------------------------------------------------------------------------------------------------- inputs

def split_days(root: Path) -> dict:
    manifest = json.loads((root / "processed" / "splits" / "splits_manifest.json").read_text(encoding="utf-8"))
    return {name: {"start": spec["start"], "end": spec["end"], "role": spec["role"]}
            for name, spec in manifest["config"]["day_splits"].items() if name in DEV_SPLITS}


def development_positives(root: Path) -> pd.DataFrame:
    """The dated positive cell-days of the train and validation splits (read with a filter: no held-out row is loaded)."""
    path = root / "processed" / "splits" / "positive_cell_days.parquet"
    table = pd.read_parquet(path, columns=["cell_id", "event_date", "region", "n_events", "split"],
                            filters=[("split", "in", list(DEV_SPLITS))])
    return table.assign(month=pd.to_datetime(table["event_date"]).dt.month)


def sample_months(root: Path) -> dict:
    """Rows of the development sample tables by kind and month."""
    out = {}
    features = root / "processed" / "features"
    for name in ("train_samples_features.parquet", "validation_samples_features.parquet",
                 "universe_train_features.parquet", "universe_validation_features.parquet"):
        table = pd.read_parquet(features / name, columns=["date", "kind"])
        months = pd.to_datetime(table["date"]).dt.month.to_numpy()
        for kind in sorted(table["kind"].unique()):
            key = f"{kind}"
            counts = _month_counts(months[table["kind"].to_numpy() == kind])
            out[key] = {m: out.get(key, {}).get(m, 0.0) + c for m, c in counts.items()}
    return out


def oof_by_month(root: Path) -> dict:
    """v4's development out-of-fold detection and universe alert shares at the card's raw thresholds, by month."""
    oof = pd.read_parquet(root / "processed" / "hazard" / "v4" / "oof" / "oof_v4.parquet",
                          columns=["kind", "date", "region", "label", "weight", "score"])
    card = json.loads((root / "processed" / "hazard" / "model_v4_live" / "card.json").read_text(encoding="utf-8"))
    raw = {k: float(card["alert_levels"][k]["raw"]) for k in LEVEL_KEYS}
    month = pd.to_datetime(oof["date"]).dt.month.to_numpy()
    positive = oof["label"].to_numpy() == 1
    universe = oof["kind"].to_numpy() == "universe"
    score, weight = oof["score"].to_numpy(dtype=np.float64), oof["weight"].to_numpy(dtype=np.float64)
    out = {"thresholds_raw": raw, "positives": _month_counts(month[positive]), "detected": {}, "universe_share": {},
           "universe_rows": _month_counts(month[universe]), "pooled": {}}
    for key, t in raw.items():
        hits = _month_counts(month[positive], (score[positive] >= t).astype(float))
        alerted = _month_counts(month[universe], weight[universe] * (score[universe] >= t))
        total = _month_counts(month[universe], weight[universe])
        out["detected"][key] = hits
        out["universe_share"][key] = {m: (alerted[m] / total[m] if total[m] else None) for m in total}
        inside = np.isin(month, sn.DEFAULT_MONTHS)
        out["pooled"][key] = {
            "inside": {"positives": int((positive & inside).sum()), "detected": int((positive & inside & (score >= t)).sum()),
                       "universe_share": float((weight * (score >= t))[universe & inside].sum() / weight[universe & inside].sum())},
            "outside": {"positives": int((positive & ~inside).sum()), "detected": int((positive & ~inside & (score >= t)).sum()),
                        "universe_share": float((weight * (score >= t))[universe & ~inside].sum() / weight[universe & ~inside].sum())}}
    return out


def heldout_panel_shares(root: Path) -> dict:
    """Point-level shares by month of v4's held-out season risk panels (risks only), against the v4 card thresholds."""
    card = json.loads((root / "processed" / "hazard" / "model_v4_live" / "card.json").read_text(encoding="utf-8"))
    at_least = defaultdict(lambda: np.zeros(3))
    scored = defaultdict(float)
    years = []
    for path in sorted((root / "processed" / "alerts" / "v4_seasons").glob("season_*_v4.npz")):
        with np.load(path, allow_pickle=False) as data:
            region = data["region"].astype(str)
            days = pd.to_datetime([str(d) for d in data["days"]])
            risk = data["risk"]
        years.append(int(days[-1].year))
        thresholds = lv.card_region_thresholds(card, region)
        level = np.zeros(risk.shape, dtype=np.int8)
        for name, thr in thresholds.items():
            rows = region == name
            level[rows] = lv.level_from_risk(risk[rows], thr)
        known = np.isfinite(risk)
        keep = days >= pd.Timestamp(days[-1].year, 6, 1)
        for m in sorted(set(days.month[keep])):
            cols = np.flatnonzero(keep & (days.month == m))
            k = known[:, cols]
            scored[m] += float(k.sum())
            for i, L in enumerate((lv.WATCH, lv.WARNING, lv.EMERGENCY)):
                at_least[m][i] += float(((level[:, cols] >= L) & k).sum())
        del risk, level, known
    return {"years": years, "cell_days": {str(m): scored[m] for m in sorted(scored)},
            "share": {str(m): {name: at_least[m][i] / scored[m] for i, name in enumerate(LEVEL_KEYS)} for m in sorted(scored)}}


def live_days(live_dir: Path) -> list[dict]:
    rows = []
    for folder in sorted(Path(live_dir).iterdir()):
        path = folder / "run.json"
        if not path.is_file():
            continue
        r = json.loads(path.read_text(encoding="utf-8"))
        lead0 = r["leads"]["0"]
        n = int(lead0["n_cells"])
        levels = lead0["levels"]
        held = None
        alerts = folder / "alerts.parquet"
        if alerts.is_file():
            table = pd.read_parquet(alerts, columns=["level", "raw_level"])
            emergency = table["level"].to_numpy() == lv.EMERGENCY
            held = int((emergency & (table["raw_level"].to_numpy() < lv.EMERGENCY)).sum())
        rows.append({"date": r["date"], "month": int(r["date"][5:7]), "model": (r.get("model") or {}).get("dir"),
                     "n_cells": n, "n_scored": int(lead0["n_scored"]), "levels": levels, "emergency_held": held,
                     "share": {"watch": (n - levels["Normal"]) / n, "warning": (levels["Warning"] + levels["Emergency"]) / n,
                               "emergency": levels["Emergency"] / n}})
    return rows


def live_by_month(rows: list[dict]) -> dict:
    out = {}
    for key in sorted({(r["month"], r["model"]) for r in rows}):
        part = [r for r in rows if (r["month"], r["model"]) == key]
        cells = sum(r["n_cells"] for r in part)
        out[f"{key[0]}|{key[1]}"] = {"month": key[0], "model": key[1], "days": len(part), "cell_days": cells,
                                     "share": {k: sum(r["share"][k] * r["n_cells"] for r in part) / cells for k in LEVEL_KEYS}}
    return out


# ------------------------------------------------------------------------------------------------- study

def recommend(result: dict) -> dict:
    """The recommendation from the numbers (module doc). The model was fitted year-round, so outside June-September it is
    not extrapolating in the strict sense; but the post-model rules and the alert parameters were chosen on June-September
    only, the held-out look covered June-December, and the development events outside June-September are few."""
    pos = result["development"]["positives_by_region_month"]
    outside = {region: int(sum(v for m, v in months.items() if int(m) not in sn.DEFAULT_MONTHS)) for region, months in pos.items()}
    inside = {region: int(sum(v for m, v in months.items() if int(m) in sn.DEFAULT_MONTHS)) for region, months in pos.items()}
    return {"declared_months": list(sn.DEFAULT_MONTHS), "positives_inside": inside, "positives_outside": outside,
            "flag": sn.FLAG,
            "decision": "declare June-September the season of validity of the published alert chain and publish a visible "
                        "flag on every lead whose date falls outside it (no suppression)",
            "alternative": "a year-round study: post-model rules and alert parameters chosen on twelve-month development "
                           "panels, a per-month calibration check, and a held-out look that includes January-May; it needs "
                           "the out-of-season events listed here, which are few"}


def build(root: Path | None = None, live_dir: Path | None = None) -> dict:
    root = Path(root or data_root())
    live_dir = Path(live_dir or root / "live")
    positives = development_positives(root)
    by_region = {region: _month_counts(part["month"].to_numpy()) for region, part in positives.groupby("region")}
    events_by_region = {region: _month_counts(part["month"].to_numpy(), part["n_events"].to_numpy(dtype=float))
                        for region, part in positives.groupby("region")}
    rows = live_days(live_dir)
    result = {
        "created_utc": pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ"),
        "chain": {
            "development_days": split_days(root),
            "model_training": "every calendar day of 2007-2017 (positives, matched negatives and universe negatives "
                              "year-round; configs/splits.yaml day_splits)",
            "post_rules_and_alert_parameters_months": [burden.SEASON_START[0], burden.SEASON_END[0]],
            "heldout_panel_months": [6, 12],
            "live_run": "every day of the year"},
        "development": {"positives_by_region_month": by_region, "events_by_region_month": events_by_region,
                        "sample_rows_by_kind_month": sample_months(root), "oof_v4": oof_by_month(root)},
        "heldout_panels_v4_point_shares": heldout_panel_shares(root),
        "live": {"days": rows, "by_month_model": live_by_month(rows)},
        "caveats": CAVEATS}
    result["recommendation"] = recommend(result)
    return result


def _pct(x) -> str:
    return "-" if x is None else f"{100 * x:.2f}%"


def markdown(r: dict) -> str:
    dev, chain = r["development"], r["chain"]
    oof = dev["oof_v4"]
    rec = r["recommendation"]
    head = " | ".join(str(m) for m in MONTHS)
    lines = ["# Season of validity of the live alert chain (phase 8, a measurement)", "",
             f"**Recommendation:** {rec['decision']}. Flag: `{rec['flag']}`. Alternative: {rec['alternative']}.", "",
             "## Which months each part of the chain was built and tested on", "",
             f"- Model training and cross-validation: {chain['model_training']}.",
             f"- Post-model rules (section 11) and alert-engine parameters: panels of months "
             f"{chain['post_rules_and_alert_parameters_months'][0]}-{chain['post_rules_and_alert_parameters_months'][1]} only.",
             f"- Held-out look (v4 adoption): season panels of months {chain['heldout_panel_months'][0]}-"
             f"{chain['heldout_panel_months'][1]} of 2018-2025.",
             f"- Live run: {chain['live_run']}.", "",
             "## Development positives (2007-2017) by month", "",
             f"| region | {head} | outside June-September |", "|---|" + "---|" * 13]
    for region, months in dev["positives_by_region_month"].items():
        out = sum(v for m, v in months.items() if int(m) not in rec["declared_months"])
        lines.append(f"| {region} (cell-days) | " + " | ".join(f"{months[str(m)]:.0f}" for m in MONTHS) + f" | {out:.0f} |")
    for region, months in dev["events_by_region_month"].items():
        out = sum(v for m, v in months.items() if int(m) not in rec["declared_months"])
        lines.append(f"| {region} (catalogue events) | " + " | ".join(f"{months[str(m)]:.0f}" for m in MONTHS) + f" | {out:.0f} |")
    lines += ["", "Development sample rows by kind (the negatives cover every month):", "",
              f"| kind | {head} |", "|---|" + "---|" * 12]
    for kind, months in dev["sample_rows_by_kind_month"].items():
        lines.append(f"| {kind} | " + " | ".join(f"{months[str(m)]:.0f}" for m in MONTHS) + " |")
    lines += ["", "## v4 out of fold on development, by month (card raw thresholds)", "",
              f"| quantity | {head} |", "|---|" + "---|" * 12,
              "| positives | " + " | ".join(f"{oof['positives'][str(m)]:.0f}" for m in MONTHS) + " |"]
    for key in LEVEL_KEYS:
        lines.append(f"| {key}+ detected | " + " | ".join(f"{oof['detected'][key][str(m)]:.0f}" for m in MONTHS) + " |")
    for key in LEVEL_KEYS:
        lines.append(f"| {key}+ universe share | " + " | ".join(_pct(oof['universe_share'][key][str(m)]) for m in MONTHS) + " |")
    lines += ["", "| level | June-September: detected / positives, universe share | other months: detected / positives, "
              "universe share |", "|---|---|---|"]
    for key in LEVEL_KEYS:
        p = oof["pooled"][key]
        lines.append(f"| {key}+ | {p['inside']['detected']} / {p['inside']['positives']}, {_pct(p['inside']['universe_share'])} | "
                     f"{p['outside']['detected']} / {p['outside']['positives']}, {_pct(p['outside']['universe_share'])} |")
    held = r["heldout_panels_v4_point_shares"]
    lines += ["", f"## v4 point-level shares of the held-out season panels by month ({held['years'][0]}-{held['years'][-1]}, "
              "risks only)", "", "| month | cell-days | Watch+ | Warning+ | Emergency |", "|---|---|---|---|---|"]
    for m, share in held["share"].items():
        lines.append(f"| {m} | {held['cell_days'][m]:,.0f} | {_pct(share['watch'])} | {_pct(share['warning'])} | "
                     f"{_pct(share['emergency'])} |")
    lines += ["", "## Published live days, lead 0, by month and model", "",
              "| month | model | days | Watch+ | Warning+ | Emergency |", "|---|---|---|---|---|---|"]
    for entry in r["live"]["by_month_model"].values():
        s = entry["share"]
        lines.append(f"| {entry['month']} | `{entry['model']}` | {entry['days']} | {_pct(s['watch'])} | {_pct(s['warning'])} | "
                     f"{_pct(s['emergency'])} |")
    lines += ["", "## Reading", "",
              f"- The model is not extrapolating in the strict sense: it was trained on every month. But outside June-September "
              f"the development positives are few ({', '.join(f'{k} {v}' for k, v in rec['positives_outside'].items())} cell-days, "
              f"against {', '.join(f'{k} {v}' for k, v in rec['positives_inside'].items())} inside).",
              "- The rest of the published chain (rain trigger, hold windows, ensemble agreement, blind-hold limit, "
              "hysteresis and `uncertain_high` parameters) was chosen on June-September panels only, and the held-out look "
              "never covered January-May. A level published outside June-September is therefore a level of a chain that was "
              "not developed or tested there.",
              *live_reading(r),
              f"- Hence the flag `{rec['flag']}` on every lead dated outside months {rec['declared_months'][0]}-"
              f"{rec['declared_months'][-1]} (run.json `season_of_validity` and each lead's `outside_validated_season`, "
              "and the bulletin), and no suppression: the alert stands, the reader is told it is outside the validated season.",
              "", "## Caveats", "", *[f"- {c}" for c in r["caveats"]], ""]
    return "\n".join(lines)


def live_reading(r: dict) -> list[str]:
    """The live shares of the newest month against the development and held-out shares of the same month."""
    rows = r["live"]["days"]
    if not rows:
        return []
    month = rows[-1]["month"]
    live = [e for e in r["live"]["by_month_model"].values() if e["month"] == month]
    dev = r["development"]["oof_v4"]["universe_share"]["emergency"].get(str(month))
    held = r["heldout_panels_v4_point_shares"]["share"].get(str(month), {}).get("emergency")
    newest = rows[-1]
    shares = "; ".join(f"`{e['model']}` {_pct(e['share']['emergency'])} over {e['days']} day(s)" for e in live)
    hold = ("" if newest["emergency_held"] is None else
            f" On {newest['date']}, {newest['emergency_held']} of the {newest['levels']['Emergency']} Emergency cells were held "
            "by the hysteresis from the day before, not at Emergency on the day's own risk.")
    return [f"- Live Emergency share in month {month}: {shares}; the same month in development (v4 out of fold, universe): "
            f"{_pct(dev)}; in the held-out season panels (v4 point level): {_pct(held)}.{hold} The live days of one month "
            "with a rain event are too few to separate weather from a train/serve gap; the size of the difference is on "
            "record, not explained."]


def write(out_dir: Path, root: Path | None = None, live_dir: Path | None = None) -> dict:
    result = build(root, live_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    dump_json(out_dir / f"{REPORT_STEM}.json", result)
    (out_dir / f"{REPORT_STEM}.md").write_text(markdown(result), encoding="utf-8")
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m aetherguard.live.season_validity", description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "reports")
    parser.add_argument("--live-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        write(args.out, live_dir=args.live_dir)
    except (OSError, ValueError, KeyError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(f"wrote {args.out / REPORT_STEM}.{{json,md}}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
