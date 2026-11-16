"""Render reports/phase8_leads_v4_preflight.{json,md} from the preflight of the leads' held-out look (no outcome).

    python tools/leads_v4_preflight_report.py <preflight.json> <event_counts.json>

`preflight.json` is what `python -m aetherguard.live.leads_v4_heldout preflight --candidate a` wrote; `event_counts.json` the
dates-only counts of the W1 and assembly-v2 events on each lead's target days (no level is read).
"""
import json
import sys
from pathlib import Path

REPORTS = Path(__file__).resolve().parents[1] / "reports"


def main() -> int:
    pre = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    counts = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    lines = ["# Forecast leads on v4: preflight of the held-out look (no outcome computed)", "",
             "Spec: docs/superpowers/specs/2026-11-14-aetherguard-leads-v4.md, sections 4-5 and amendments 1-2. Research prototype, "
             "not validated for issuing real public warnings. The preflight joins no event with a level: it burden-matches the "
             "candidate and counts event dates only.", "",
             f"Candidate: **{pre['candidate']}** (chosen by `look_choice` in reports/phase8_leads_v4.json). Years "
             f"{', '.join(map(str, pre['years']))}, June-September issue days. Generated {pre['generated_utc']}.", "",
             "## Panels (frozen by checksum; the look refuses other panels)", "", "| year | sha256 |", "|---|---|"]
    lines += [f"| {y} | `{h}` |" for y, h in pre["panels_sha256"].items()]
    lines += ["", "## Burden matching per season and lead", "",
              "Target = the incumbent's realised Watch+ / Warning+ / Emergency shares of scored cell-days; realised = the "
              "candidate's after `hazard.v4_int.match_burden`. Straddle = tied cell-days left out at a cut.", "",
              "| lead | season | scored cell-days | issue days scored | target W+ / Wa+ / E | realised W+ / Wa+ / E | straddle (W+, Wa+, E) |",
              "|---|---|---|---|---|---|---|"]
    for lead, entry in pre["leads"].items():
        for year, s in entry["seasons"].items():
            t = " / ".join(f"{100 * x:.4f}%" for x in s["target"])
            r = " / ".join(f"{100 * x:.4f}%" for x in s["realised"])
            st = ", ".join(str(c["straddle"]) for c in s["cuts"].values())
            lines.append(f"| {lead} | {year} | {s['scored_cell_days']:,} | {s['issue_days_scored']} | {t} | {r} | {st} |")
    lines += ["", "| lead | target days | scored cell-days |", "|---|---|---|"]
    lines += [f"| {lead} | {e['days']} | {e['scored_cell_days']:,} |" for lead, e in pre["leads"].items()]
    lines += ["", "## Events dated on the target days (dates only)", "",
              "| set | lead | events on days | events outside the days | independent slides |", "|---|---|---|---|---|"]
    for name, by_lead in counts.items():
        for lead, c in by_lead.items():
            lines.append(f"| {name} | {lead} | {c['events_on_days']} | {c['events_outside_days']} | {c['independent_slides_on_days']} |")
    lines += ["", "## Checks", ""]
    lines += [f"- {c['check']}: {'passed' if c['passed'] else 'FAILED'}" for c in pre["checks"]]
    lines += [f"- W1 counts of the preflight equal the dates-only recount: "
              f"{all(counts['w1'][l]['events_on_days'] == pre['leads'][l]['events_on_days'] for l in pre['leads'])}", "",
              "## Caveats", "",
              "- 22 independent W1 slides fall on the target days of each lead (2 records outside). One slide moves a row; ties "
              "are the expected outcome of the 12-row rule.",
              "- The incumbent leads' burden is high (see the target shares), so tolerant matching has a high chance floor; the "
              "cell-exact rows are the stronger test.",
              "- 2021 is the fit season of the GFS intensity maps (rain only, no event). Leads 2-3 use the GFS fallback on every "
              "issue day of 2021-2022 and on part of 2023 (no ECMWF archive), as the live run does when ECMWF fails.",
              "- Assembly v2 without the BIPAD register, and v2 India only, hold the same events as W1 on these days; v2 with all "
              "records adds the BIPAD Nepal register (no stated licence: numbers only, local rows, decides nothing).",
              "- Ground truth after 2018 is very incomplete.", ""]
    (REPORTS / "phase8_leads_v4_preflight.md").write_text("\n".join(lines), encoding="utf-8")
    (REPORTS / "phase8_leads_v4_preflight.json").write_text(json.dumps({"preflight": pre, "event_counts": counts}, indent=1),
                                                             encoding="utf-8")
    print("wrote", REPORTS / "phase8_leads_v4_preflight.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
