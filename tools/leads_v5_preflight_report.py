"""Render reports/phase8_leads_v5_preflight.{json,md} from the preflight of the v4-static leads' look (no outcome).

    python tools/leads_v5_preflight_report.py <heldout_v5/preflight.json> [<reports/phase8_leads_v5_e1.json>]
"""
import json
import sys
from pathlib import Path

REPORTS = Path(__file__).resolve().parents[1] / "reports"
LABELS = {"w1_2021_2024_already_looked_at": "W1 2021-2024 (ALREADY LOOKED AT by the v4-leads look: a second look, beside only)",
          "v2_all_2025": "assembly v2 2025, all records (includes the BIPAD Nepal register: no stated licence, rows local only)",
          "v2_without_bipad_2025": "assembly v2 2025 without the BIPAD register",
          "v2_india_2025": "assembly v2 2025, India only"}


def gate_md(e1: dict) -> list[str]:
    lines = ["## Development gate: E1 (amendment 2 a; no event read)", "",
             f"Years {', '.join(map(str, e1['years']))}, {e1['cells']} cells (seed {e1['seed']}). Reference: {e1['reference']}.", "",
             "| lead | candidate | days | agreement | Warning+ recall | Emergency recall | Watch / Warning / Emergency share | reference shares |",
             "|---|---|---|---|---|---|---|---|"]
    for lead, by in e1["results"].items():
        for name in ("c", "s"):
            m = by[name]["vs_v4_reference"]
            f, r = m["burden_forecast"], m["burden_reference"]
            share = " / ".join(f"{100 * f[k]:.2f}%" for k in ("watch", "warning", "emergency"))
            ref = " / ".join(f"{100 * r[k]:.2f}%" for k in ("watch", "warning", "emergency"))
            lines.append(f"| {lead} | {name} | {m['days']} | {m['agreement']:.4f} | {m['warning_plus_recall']:.4f} | "
                         f"{m['emergency_recall']:.4f} | {share} | {ref} |")
    gate = e1["gate"]
    lines += ["", f"Gate: **{'PASSED' if gate['passed'] else 'FAILED'}**. Rule: {gate['rule']}."]
    lines += [f"- {x}" for x in gate["failures"]] + [""]
    return lines


def render(pre: dict, e1: dict | None = None) -> str:
    lines = ["# Forecast leads on v4-static (leads v5): preflight of the held-out look (no outcome computed)", "",
             "Spec: docs/superpowers/specs/2026-11-17-aetherguard-leads-v5.md (written before any held-out number). Research "
             "prototype, not validated for issuing real public warnings. The preflight joins no event with a level.", "",
             f"Candidate **{pre['candidate']}** (v4-static at leads 1-3). Deciding season: "
             f"{', '.join(map(str, pre['deciding_years']))} June-September (fresh). Beside only: "
             f"{', '.join(map(str, pre['beside_years']))}. Generated {pre['generated_utc']}.", "",
             "## Frozen inputs", "", "| file | sha256 |", "|---|---|"]
    lines += [f"| panel {y} | `{h}` |" for y, h in pre["panels_sha256"].items()]
    lines += [f"| v4-static {name} | `{h}` |" for name, h in pre["model_sha256"].items()]
    lines += [""] + (gate_md(e1) if e1 is not None else [])
    if "gate" in pre:
        lines += [f"Preflight froze the gate verdict (passed = {pre['gate']['passed']}) and the gate file "
                  f"(sha256 `{pre['gate_sha256']}`). Decision rule: {pre['rule']}.", ""]
    lines += ["## Deciding season: burden matching and events (W1)", "",
              "| lead | target days | scored cell-days | issue days scored | target W+ / Wa+ / E | realised W+ / Wa+ / E | "
              "straddle | W1 events on days | outside | independent slides |", "|---|---|---|---|---|---|---|---|---|---|"]
    for lead, e in pre["leads"].items():
        for year, s in e["seasons"].items():
            t = " / ".join(f"{100 * x:.4f}%" for x in s["target"])
            r = " / ".join(f"{100 * x:.4f}%" for x in s["realised"])
            st = ", ".join(str(c["straddle"]) for c in s["cuts"].values())
            lines.append(f"| {lead} | {e['days']} | {e['scored_cell_days']:,} | {s['issue_days_scored']} | {t} | {r} | {st} | "
                         f"{e['events_on_days']} | {e['events_outside_days']} | {e['independent_slides_on_days']} |")
    lines += ["", "## Beside, deciding nothing (dates only)", "", "| set | lead | events on days | outside | independent slides |",
              "|---|---|---|---|---|"]
    for name, by_lead in pre["beside_event_counts"].items():
        for lead, c in by_lead.items():
            lines.append(f"| {LABELS.get(name, name)} | {lead} | {c['events_on_days']} | {c['events_outside_days']} | "
                         f"{c['independent_slides_on_days']} |")
    slides = sorted({e["independent_slides_on_days"] for e in pre["leads"].values()})
    lines += ["", "## Checks", ""] + [f"- {c['check']}: {'passed' if c['passed'] else 'FAILED'}" for c in pre["checks"]]
    lines += ["", "## Power", "",
              f"The deciding season holds {', '.join(map(str, slides))} independent W1 slide(s) per lead, so the 2025 look can only "
              "veto a gross loss (spec amendment 2: reports/phase8_leads_v5_veto.json gives the pass and block probabilities).", ""]
    return "\n".join(lines)


def main() -> int:
    pre = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    e1 = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8")) if len(sys.argv) > 2 else None
    (REPORTS / "phase8_leads_v5_preflight.md").write_text(render(pre, e1), encoding="utf-8")
    (REPORTS / "phase8_leads_v5_preflight.json").write_text(json.dumps(pre, indent=1), encoding="utf-8")
    print("wrote", REPORTS / "phase8_leads_v5_preflight.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
