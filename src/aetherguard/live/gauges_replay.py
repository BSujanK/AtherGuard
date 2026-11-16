"""Scratch replays of real days with and without the same-day SYNOP gauges (spec 2026-11-14-aetherguard-same-day-gauges.md,
section 7), and their report.

    python -m aetherguard.live.gauges_replay run --root DIR --days 2026-11-10 ... 2026-11-15 [--sets before after after_h]
    python -m aetherguard.live.gauges_replay report --root DIR --v1 FILE [--v1-first FILE] [--v2 FILE] [--out reports]

Each set gets its own configuration (a copy of configs/live_run.yaml whose live_dir, report_dir and replay_dir are under
`<root>/<set>/`, never data/live) and replays the days in order in backtest mode (inputs issued before 11:00 IST only),
one `python -m aetherguard.live run` process per day. A day whose run.json exists is not run again, so the command
resumes. Sets: `before` (synop off), `after` (synop on), `after_h` (synop on and GHCN flag-H zeros missing). The first
day starts the hysteresis without history in every set alike. The report compares the sets from the files the runs
wrote; nothing in it is typed by hand.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from ..config import PROJECT_ROOT
from ..hazard.jsonio import dump_json

SETS = {"before": {"synop": False, "h_zero": False}, "after": {"synop": True, "h_zero": False},
        "after_h": {"synop": True, "h_zero": True}}
LABELS = {"before": "before (GHCN-Daily only)", "after": "after (SYNOP merged)",
          "after_h": "after, GHCN flag-H zeros missing"}
LEVELS = ("Normal", "Watch", "Warning", "Emergency")
STATES = ("High", "Degraded", "Insufficient")
REPORT_STEM = "phase8_same_day_gauges"


def set_config(root: Path, name: str, base: Path | None = None) -> Path:
    cfg = yaml.safe_load((base or PROJECT_ROOT / "configs" / "live_run.yaml").read_text(encoding="utf-8"))
    where = Path(root) / name
    cfg.update(live_dir=str(where / "live"), report_dir=str(where / "reports"), replay_dir=str(where / "replay"))
    cfg["synop"] = {**cfg.get("synop", {}), "enabled": SETS[name]["synop"], "collect": False}
    cfg["ghcn"] = {**cfg["ghcn"], "h_zero_as_missing": SETS[name]["h_zero"]}
    path = where / "live_run.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    return path


def day_summary(root: Path, name: str, day: str) -> dict:
    """What one replayed day shows, read from its run.json, alerts.parquet and the replay store's sensor table."""
    where = Path(root) / name
    run = json.loads((where / "live" / day / "run.json").read_text(encoding="utf-8"))
    alerts = pd.read_parquet(where / "live" / day / "alerts.parquet")
    sensors_path = where / "replay" / "live" / "sensors" / f"{day}.parquet"
    sensors = pd.read_parquet(sensors_path) if sensors_path.is_file() else None
    integ = run.get("integrity", {})
    out = {"status": run.get("status"), "audit": int(run.get("audit", {}).get("total_violations", -1)),
           "integrity_ran": bool(integ.get("ran")), "stations_observed_on_day": integ.get("n_stations_observed"),
           "synop": integ.get("synop"),
           "confidence": {s: int((alerts["confidence"] == s).sum()) for s in STATES},
           "levels": {lv: int((alerts["level_name"] == lv).sum()) for lv in LEVELS},
           "n_blind_escalated": int(alerts["blind_escalated"].sum()),
           "cells_with_trusted_station": int((alerts["n_trusted"] > 0).sum()),
           "cells_with_station_flagged_7d": int((alerts["n_flagged_7d"] > 0).sum())}
    if sensors is not None:
        observed = sensors[sensors["state"] != "missing"]
        out["sensors"] = {"states": sensors["state"].value_counts().to_dict(), "observed": int(len(observed)),
                          "flagged": int(observed["flagged"].astype(bool).sum()),
                          "trust_mean_observed": float(observed["trust"].mean()) if len(observed) else None,
                          "trust_min_observed": float(observed["trust"].min()) if len(observed) else None,
                          "fault_types": observed.loc[observed["flagged"].astype(bool), "fault_type"].value_counts().to_dict()}
    return out


def run_sets(root: Path, days: list[str], sets: list[str]) -> None:
    env = {**os.environ, "PYTHONPATH": str(PROJECT_ROOT / "src")}
    for name in sets:
        config = set_config(root, name)
        summary_path = Path(root) / name / "replay_summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.is_file() else {}
        for day in days:
            if not (Path(root) / name / "live" / day / "run.json").is_file():
                log = Path(root) / name / f"run_{day}.log"
                with log.open("w", encoding="utf-8") as handle:
                    code = subprocess.call([sys.executable, "-m", "aetherguard.live", "run", "--date", day, "--backtest",
                                            "--force", "--config", str(config)], cwd=PROJECT_ROOT, env=env,
                                           stdout=handle, stderr=subprocess.STDOUT)
                if code not in (0, 3):
                    raise SystemExit(f"{name} {day}: live run exited {code}, see {log}")
            summary[day] = day_summary(root, name, day)
            dump_json(summary_path, summary)


def level_changes(root: Path, day: str, a: str = "before", b: str = "after") -> dict:
    """Cells whose published level differs between two sets on one day, by direction and by pair of levels."""
    x = pd.read_parquet(Path(root) / a / "live" / day / "alerts.parquet")[["cell_id", "level", "level_name", "confidence"]]
    y = pd.read_parquet(Path(root) / b / "live" / day / "alerts.parquet")[["cell_id", "level", "level_name", "confidence"]]
    m = x.merge(y, on="cell_id", suffixes=("_a", "_b"), validate="one_to_one")
    moved = m[m["level_a"] != m["level_b"]]
    pairs = (moved["level_name_a"] + "->" + moved["level_name_b"]).value_counts().to_dict()
    conf = m[m["confidence_a"] != m["confidence_b"]]
    return {"cells": int(len(m)), "level_changed": int(len(moved)), "up": int((moved["level_b"] > moved["level_a"]).sum()),
            "down": int((moved["level_b"] < moved["level_a"]).sum()), "pairs": pairs,
            "confidence_changed": int(len(conf)),
            "confidence_pairs": (conf["confidence_a"] + "->" + conf["confidence_b"]).value_counts().to_dict()}


def build(root: Path, v1: dict | None, v1_first: dict | None, v2: dict | None) -> dict:
    sets = {}
    for name in SETS:
        path = Path(root) / name / "replay_summary.json"
        if path.is_file():
            sets[name] = json.loads(path.read_text(encoding="utf-8"))
    days = sorted(set().union(*[set(v) for v in sets.values()])) if sets else []
    changes = {day: {b: level_changes(root, day, "before", b) for b in ("after", "after_h")
                     if b in sets and day in sets[b] and "before" in sets and day in sets["before"]} for day in days}
    totals = {name: {"days": len(e), "audit_violations": sum(d["audit"] for d in e.values()),
                     "levels": {lv: sum(d["levels"][lv] for d in e.values()) for lv in LEVELS},
                     "confidence": {s: sum(d["confidence"][s] for d in e.values()) for s in STATES},
                     "blind_escalated": sum(d["n_blind_escalated"] for d in e.values()),
                     "stations_observed_on_day": sum((d["stations_observed_on_day"] or 0) for d in e.values())}
              for name, e in sets.items()}
    any_level_change = any(c.get("level_changed", 0) for per in changes.values() for c in per.values())
    return {"report": REPORT_STEM, "days": days, "sets": sets, "labels": LABELS, "totals": totals,
            "level_changes_vs_before": changes, "levels_changed": any_level_change,
            "model_change": any_level_change, "v1": v1, "v1_first_run": v1_first, "v2": v2}


def _fmt(x, digits=3):
    return "-" if x is None else (f"{x:.{digits}f}" if isinstance(x, float) else str(x))


def _metrics_row(label: str, m: dict) -> str:
    if not m or not m.get("n"):
        return f"| {label} | 0 | - | - | - | - | - |"
    return (f"| {label} | {m['n']} | {_fmt(m['bias_mm'], 2)} | {_fmt(m['pearson'])} | {_fmt(m['wet_hit_rate'])} "
            f"| {_fmt(m['false_wet_share'])} | {_fmt(m['within_tolerance'])} |")


def render(result: dict) -> str:
    lines = ["# Same-day SYNOP gauges for the integrity engine (phase 8, gauges-isd)", "",
             "Research prototype, not validated for issuing real public warnings. Spec: "
             "`docs/superpowers/specs/2026-11-14-aetherguard-same-day-gauges.md`; sources: "
             "`reports/phase8_gauge_sources_probe.md`. Every number below is read from `" + REPORT_STEM + ".json`.", ""]
    v1 = result.get("v1")
    if v1:
        c = v1["criterion"]
        lines += ["## V1: SYNOP IMD-day totals against GHCN-Daily, July 2024 (the declared criterion)", "",
                  f"Criterion (declared before measuring): within tolerance >= {c['within_tolerance_min']}, r >= "
                  f"{c['pearson_min']}, wet-day hit rate >= {c['wet_hit_min']}, |bias| <= {c['abs_bias_max_mm']} mm.", "",
                  "| run | n | bias mm | r | wet hit | false wet | within tolerance |", "|---|---|---|---|---|---|---|"]
        if result.get("v1_first_run"):
            lines.append(_metrics_row("first run (decoder of 880bbbc)", result["v1_first_run"]["metrics"]))
        lines.append(_metrics_row("rerun (6RRR/7R24 rounding rule)", v1["metrics"]))
        if v1.get("diagnostic"):
            lines.append(_metrics_row("post-hoc diagnostic: days whose 03 UTC report is in ISD", v1["diagnostic"]["metrics"]))
        met = v1["criterion_met"]
        lines += ["", f"**V1 criterion met: {'yes' if met else 'NO'}** (first run: "
                  f"{'yes' if (result.get('v1_first_run') or {}).get('criterion_met') else 'NO'}). "
                  f"Coverage of GHCN station-days: {_fmt(v1['coverage_of_ghcn_days'])}. How the totals were made: "
                  f"{v1['how']}.", ""]
        if v1.get("diagnostic"):
            d = v1["diagnostic"]
            lines += [f"Diagnostic, not the criterion: GHCN 0.0 while SYNOP >= 1 mm on "
                      f"{d['ghcn_zero_while_synop_wet_and_no_isd_03utc']} station-days whose 03 UTC report is absent "
                      f"from ISD (GSOD wrote a zero for a missing report) and on "
                      f"{d['ghcn_zero_while_synop_wet_with_isd_03utc']} where it is present.", ""]
    v2 = result.get("v2")
    if v2:
        lines += ["## V2: the replay period against GHCN-Daily 2026 and the IMD real-time grid (descriptive)", "",
                  "| reference | n | bias mm | r | wet hit | false wet | within tolerance |", "|---|---|---|---|---|---|---|"]
        for key, m in v2["metrics"].items():
            lines.append(_metrics_row(key, m))
        lines += ["", f"Period {v2['period'][0]} to {v2['period'][1]}, {v2['stations']} stations: SYNOP totals on "
                  f"{v2['synop_station_days']} of {v2['station_days']} station-days ({v2['how']}). GHCN-Daily has "
                  f"{v2['ghcn_h_zero_station_days']} flag-H zeros in the period, {v2['ghcn_h_zero_where_synop_wet']} of them "
                  f"on station-days where the station's own SYNOP has >= 1 mm. IMD real-time days compared: {v2['imd_days']}.",
                  "", v2.get("note", ""), ""]
    lines += ["## Replayed days", "", "| day | set | stations on D | SYNOP how on D | flagged on D | mean trust | "
              "High / Degraded / Insufficient | Normal / Watch / Warning / Emergency | blind-escalated | audit |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for day in result["days"]:
        for name, entries in result["sets"].items():
            e = entries.get(day)
            if not e:
                continue
            s = e.get("sensors") or {}
            how = (e.get("synop") or {}).get("how_on_day", {})
            lines.append(f"| {day} | {LABELS[name]} | {e['stations_observed_on_day']} | {how or '-'} | "
                         f"{s.get('flagged', '-')} | {_fmt(s.get('trust_mean_observed'))} | "
                         f"{' / '.join(str(e['confidence'][k]) for k in STATES)} | "
                         f"{' / '.join(str(e['levels'][k]) for k in LEVELS)} | {e['n_blind_escalated']} | {e['audit']} |")
    for name, entries in result["sets"].items():
        observed = sum((e.get("sensors") or {}).get("observed", 0) for e in entries.values())
        flagged = sum((e.get("sensors") or {}).get("flagged", 0) for e in entries.values())
        uncertain = sum(((e.get("sensors") or {}).get("states") or {}).get("uncertain", 0) for e in entries.values())
        if observed:
            lines += ["", f"**{LABELS[name]}: the engine flags {flagged} of {observed} station readings on the run days "
                      f"({flagged / observed:.2f}); {uncertain} station-days are out of distribution ('uncertain').** "
                      "The readings are mostly dry-day zeros that agree with the IMD real-time grid (V2), so the flags "
                      "point at the engine under its live substitute references, not at the SYNOP values (not verified)."]
    lines += ["", "Integrity-engine verdicts on D (station states of the alert engine and the engine's fault types):", ""]
    for name, entries in result["sets"].items():
        for day, e in entries.items():
            s = e.get("sensors") or {}
            lines.append(f"- {LABELS[name]}, {day}: states {s.get('states')}, fault types {s.get('fault_types') or '-'}, "
                         f"lowest trust {_fmt(s.get('trust_min_observed'))}")
    lines += ["", "## Level and confidence changes against `before`", "",
              "| day | set | cells | level changed (up / down) | level pairs | confidence changed | confidence pairs |",
              "|---|---|---|---|---|---|---|"]
    for day, per in result["level_changes_vs_before"].items():
        for name, c in per.items():
            lines.append(f"| {day} | {LABELS[name]} | {c['cells']} | {c['level_changed']} ({c['up']} / {c['down']}) | "
                         f"{c['pairs'] or '-'} | {c['confidence_changed']} | {c['confidence_pairs'] or '-'} |")
    lines += ["", "## Totals", "", "| set | days | stations on D (sum) | High | Degraded | Insufficient | Watch | Warning | "
              "Emergency | blind-escalated | audit violations |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for name, t in result["totals"].items():
        lines.append(f"| {LABELS[name]} | {t['days']} | {t['stations_observed_on_day']} | "
                     f"{' | '.join(str(t['confidence'][k]) for k in STATES)} | "
                     f"{' | '.join(str(t['levels'][k]) for k in LEVELS[1:])} | {t['blind_escalated']} | "
                     f"{t['audit_violations']} |")
    lines += ["", ("**Published alert levels change in these replays: wiring the SYNOP gauges is a MODEL CHANGE.** "
                   "The lead decides.") if result["model_change"] else
              "Published alert levels do not change on these days; confidence may.", "",
              "## Caveats", "",
              "- The replayed days are November, outside the validated June-September season, and mostly dry: they "
              "show the plumbing (stations seen on D, engine verdicts, confidence) far more than rain-day behaviour.",
              "- Only the newest replayed day has reports with measured arrival times (the NWS ring); earlier days use "
              "OGIMET archive reports, treated as arriving `synop.latency_h` after observation.",
              "- The integrity engine runs with the live substitutes for its references (IMD real-time grid, IMERG), as "
              "every live run does; that substitution is not validated.",
              "- V1 compares two summaries of the same reports; it tests the decoding and the day rule, not the gauges.",
              "- The `after, GHCN flag-H zeros missing` run of 15 Nov was repeated: its first attempt hit a DNS failure "
              "(GHCN failed, IMD real-time late); the failed run.json is kept in the scratch replay directory.", ""]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m aetherguard.live.gauges_replay")
    sub = parser.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--root", type=Path, required=True)
    r.add_argument("--days", nargs="+", required=True)
    r.add_argument("--sets", nargs="+", default=list(SETS), choices=list(SETS))
    p = sub.add_parser("report")
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--v1", type=Path, default=None)
    p.add_argument("--v1-first", type=Path, default=None)
    p.add_argument("--v2", type=Path, default=None)
    p.add_argument("--out", type=Path, default=PROJECT_ROOT / "reports")
    args = parser.parse_args(argv)
    if args.cmd == "run":
        run_sets(args.root, args.days, args.sets)
        return 0
    def load(path):
        if not path:
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload.get("tolerance"), dict):       # keep local paths out of the public report
            payload["tolerance"]["source"] = f"data/processed/alerts/{Path(payload['tolerance']['source']).name}"
        return payload
    result = build(args.root, load(args.v1), load(args.v1_first), load(args.v2))
    args.out.mkdir(parents=True, exist_ok=True)
    dump_json(args.out / f"{REPORT_STEM}.json", result)
    (args.out / f"{REPORT_STEM}.md").write_text(render(result), encoding="utf-8")
    print(args.out / f"{REPORT_STEM}.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
