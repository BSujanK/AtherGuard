"""Side-by-side report of scratch replays of real live days (phase 8, live-chain workstream).

    python -m aetherguard.live.replay_report <replay_root> [--out reports]    # reports/phase8_live_replays.{json,md}

Each set directory under `<replay_root>` holds `replay_summary.json`, written by the scratch replay driver: one entry per
day replayed in backtest mode (inputs issued before 11:00 IST of the day only) into a scratch live_dir, never data/live.
The sets compared:
* `before`         the code of dc93f98 (lead 0 v4, confidence on day D's IMD file);
* `after`          the live-chain code (confidence on the newest due IMD day), lead 0 v4, alert_config_v3;
* `after_v3lead0`  the same with lead 0 scored by v3 (the size of the v3/v4 jump between lead 0 and lead 1);
* `after_cfg4`     the same as `after` with alert_config_v4.json (the effect of the IMERG-era alert parameters).
Nothing here is chosen; the numbers are those of the replays. The first replayed day starts the hysteresis without
history, so its levels differ from a day run in sequence.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..config import PROJECT_ROOT
from ..hazard.jsonio import dump_json

SETS = ("before", "after", "after_v3lead0", "after_cfg4")
LABELS = {"before": "before (dc93f98)", "after": "after, v4, alert_config_v3", "after_v3lead0": "after, lead 0 by v3",
          "after_cfg4": "after, v4, alert_config_v4"}
LEVELS = ("Normal", "Watch", "Warning", "Emergency")
STATES = ("High", "Degraded", "Insufficient")
REPORT_STEM = "phase8_live_replays"


def load(root: Path) -> dict:
    out = {}
    for name in SETS:
        path = Path(root) / name / "replay_summary.json"
        if path.is_file():
            out[name] = json.loads(path.read_text(encoding="utf-8"))
    return out


def build(root: Path) -> dict:
    sets = load(root)
    days = sorted(set().union(*[set(v) for v in sets.values()])) if sets else []
    totals = {}
    for name, entries in sets.items():
        totals[name] = {"days": len(entries), "audit_violations": sum(e["audit"] for e in entries.values()),
                        "confidence": {s: sum(e["confidence"][s] for e in entries.values()) for s in STATES},
                        "levels": {lv: sum(e["levels"][lv] for e in entries.values()) for lv in LEVELS},
                        "blind_escalated": sum(e["n_blind_escalated"] for e in entries.values())}
    return {"sets": {n: LABELS[n] for n in sets}, "days": days,
            "per_day": {d: {n: sets[n][d] for n in sets if d in sets[n]} for d in days}, "totals": totals}


def markdown(r: dict) -> str:
    lines = ["# Scratch replays of real live days (phase 8)", "",
             "Backtest mode (inputs issued before 11:00 IST of each day), scratch live_dir; never data/live. The first day "
             "starts the hysteresis without history.", "",
             "## Confidence of lead 0", "", "| day | set | High | Degraded | Insufficient | causes | check day | audit |",
             "|---|---|---|---|---|---|---|---|"]
    for d, row in r["per_day"].items():
        for n, e in row.items():
            causes = ", ".join(f"{k} {v}" for k, v in e["confidence_causes"].items())
            check = (e.get("second_opinion") or {}).get("check_day") or "-"
            lines.append(f"| {d} | {r['sets'][n]} | {e['confidence']['High']} | {e['confidence']['Degraded']} | "
                         f"{e['confidence']['Insufficient']} | {causes} | {check} | {e['audit']} |")
    lines += ["", "## Levels of lead 0 and lead 1", "",
              "| day | set | lead 0 Normal / Watch / Warning / Emergency | blind-escalated | lead 1 Normal / Watch / Warning / Emergency |",
              "|---|---|---|---|---|"]
    for d, row in r["per_day"].items():
        for n, e in row.items():
            l0 = " / ".join(str(e["levels"][k]) for k in LEVELS)
            l1 = " / ".join(str(e["lead1_levels"][k]) for k in LEVELS) if e.get("lead1_levels") else "-"
            lines.append(f"| {d} | {r['sets'][n]} | {l0} | {e['n_blind_escalated']} | {l1} |")
    lines += ["", "## Totals over the replayed days", "",
              "| set | days | High | Degraded | Insufficient | Watch | Warning | Emergency | blind-escalated | audit violations |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for n, t in r["totals"].items():
        lines.append(f"| {r['sets'][n]} | {t['days']} | {t['confidence']['High']} | {t['confidence']['Degraded']} | "
                     f"{t['confidence']['Insufficient']} | {t['levels']['Watch']} | {t['levels']['Warning']} | "
                     f"{t['levels']['Emergency']} | {t['blind_escalated']} | {t['audit_violations']} |")
    lines += ["", "Lead 1 is scored by v3 in every set (forecast rain); lead 0 by v4 except in `after_v3lead0`.", ""]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m aetherguard.live.replay_report", description=__doc__.splitlines()[0])
    parser.add_argument("root", type=Path)
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "reports")
    args = parser.parse_args(argv)
    try:
        result = build(args.root)
    except (OSError, ValueError, KeyError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    args.out.mkdir(parents=True, exist_ok=True)
    dump_json(args.out / f"{REPORT_STEM}.json", result)
    (args.out / f"{REPORT_STEM}.md").write_text(markdown(result), encoding="utf-8")
    print(f"wrote {args.out / REPORT_STEM}.{{json,md}}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
