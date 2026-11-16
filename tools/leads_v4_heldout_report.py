"""Render reports/phase8_leads_v4_heldout.{json,md} from the ONE held-out look of the forecast leads (heldout_result.json).

    python tools/leads_v4_heldout_report.py <heldout_result.json> [<reports dir>]

Every number comes from the result file. The deciding table (licence-clean W1 assembly) comes first; the assembly-v2 sets
follow, labelled as not deciding. The rule is the one pre-declared in docs/superpowers/specs/2026-11-14-aetherguard-leads-v4.md
section 5 (amendment 1 for the computation), applied as written; nothing was changed after the look.
"""
import json
import sys
from pathlib import Path

LEVELS = {"1": "Watch+", "2": "Warning+", "3": "Emergency"}
TOLERANCES = ("tolerant", "cell_exact")
V2_LABELS = {"v2_all": "assembly v2, all records (includes the BIPAD Nepal register: no stated licence, rows local only)",
             "v2_without_bipad": "assembly v2 without the BIPAD register",
             "v2_india": "assembly v2, India only"}


def _pct(x) -> str:
    return "-" if x is None else f"{100 * x:.1f}%"


def detection_rows(by_lead: dict) -> list[str]:
    rows = ["| lead | tolerance | level | slides detected, incumbent (v3) | slides detected, candidate | slides | "
            "alert cell-days, incumbent | alert cell-days, candidate |", "|---|---|---|---|---|---|---|---|"]
    for lead, scores in by_lead.items():
        for tol in TOLERANCES:
            for key, name in LEVELS.items():
                inc, cand = scores[tol]["v3"][key], scores[tol]["candidate"][key]
                rows.append(f"| {lead} | {tol} | {name} | {inc['group_hits']} | {cand['group_hits']} | {inc['groups']} | "
                            f"{inc['alert_cell_days']:,} | {cand['alert_cell_days']:,} |")
    return rows


def headline(result: dict) -> str:
    rows = result["decision"]["rows"]
    lower = [r for r in rows if not r["not_lower"]]
    higher = [r for r in rows if r["higher"]]
    slides = {lead: s["slides"] for lead, s in result["deciding_w1"].items()}
    verdict = "ADOPTED" if result["decision"]["adopt"] else "NOT ADOPTED"
    lower_text = "; ".join(f"lead {r['lead']} {r['tolerance']} {r['level']}+ {r['incumbent']} -> {r['candidate']}" for r in lower)
    return (f"**v4 forecast leads (candidate {result['candidate']}): {verdict}** under the rule declared before the look "
            f"(12 rows: leads 1-3, tolerant and cell-exact, Warning+ and Emergency independent-slide detection not lower than the "
            f"incumbent's in any row and higher in at least one). {len(higher)} of {len(rows)} rows are higher and "
            f"{len(lower)} {'is' if len(lower) == 1 else 'are'} lower" + (f" ({lower_text})" if lower else "") +
            f". The rule was not changed after the look; the incumbent (v3 on forecast rain) stays. Independent W1 slides on "
            f"the target days: {', '.join(f'lead {k} {v}' for k, v in slides.items())}, so one slide moves a row.")


def render(result: dict) -> str:
    lines = ["# Forecast leads on v4: the held-out look (W7)", "", headline(result), "",
             f"Taken once ({result['generated_utc']}); spec docs/superpowers/specs/2026-11-14-aetherguard-leads-v4.md section 5, "
             "amendments 1-2; preflight reports/phase8_leads_v4_preflight.md. Research prototype, not validated for issuing real "
             "public warnings.", "",
             "## Deciding: licence-clean W1 assembly, June-September 2021-2024", "",
             "Each lead's candidate levels are burden-matched per season to the incumbent lead's realised Watch+ / Warning+ / "
             "Emergency shares. Lead L detects a slide of day X when the forecast issued on X-L puts a cell within tolerance at "
             "the level.", ""]
    lines += detection_rows(result["deciding_w1"])
    lines += ["", "### The 12 deciding rows", "", "| lead | tolerance | level | incumbent | candidate | not lower | higher |",
              "|---|---|---|---|---|---|---|"]
    lines += [f"| {r['lead']} | {r['tolerance']} | {r['level']}{'+' if r['level'] == 'Warning' else ''} | {r['incumbent']} | "
              f"{r['candidate']} | {'yes' if r['not_lower'] else 'NO'} | {'yes' if r['higher'] else 'no'} |"
              for r in result["decision"]["rows"]]
    lines += ["", f"Decision: adopt = {str(result['decision']['adopt']).lower()}.", "",
              "## Beside it, NOT deciding: held-out assembly v2", "",
              "Reported as the spec declares; it decides nothing. The BIPAD Nepal register has no stated licence: its rows stay "
              "local and only these derived numbers are shown.", ""]
    for name, by_lead in result["beside_v2"].items():
        slides = {lead: s["slides"] for lead, s in by_lead.items()}
        lines += [f"### {V2_LABELS.get(name, name)}", "", f"Independent slides on the target days: "
                  f"{', '.join(f'lead {k} {v}' for k, v in slides.items())}.", ""]
        lines += detection_rows(by_lead) + [""]
    lines += ["## Caveats", "",
              f"- Low power: {', '.join(str(s['slides']) for s in result['deciding_w1'].values())} independent W1 slides "
              f"(leads 1, 2, 3), {', '.join(str(s['events']) for s in result['deciding_w1'].values())} records, "
              f"{', '.join(str(s['events_outside_panel_days']) for s in result['deciding_w1'].values())} outside the target days. "
              "A single slide decides a row, in either direction.",
              "- The incumbent leads' burden is high (Watch+ about half of the scored cell-days), so tolerant matching has a high "
              "chance floor; the cell-exact rows are the stronger test.",
              "- Only 2021-2024 have archived forecasts; 2018-2020 (most of the held-out slides) could not be used. 2021 is the fit "
              "season of the GFS intensity maps (rain only). Leads 2-3 use the GFS fallback where ECMWF has no archive (2021-2022, "
              "part of 2023).",
              "- Ground truth after 2018 is very incomplete; precision is relative.", ""]
    return "\n".join(lines)


def main() -> int:
    source = Path(sys.argv[1])
    reports = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).resolve().parents[1] / "reports"
    result = json.loads(source.read_text(encoding="utf-8"))
    (reports / "phase8_leads_v4_heldout.md").write_text(render(result), encoding="utf-8")
    (reports / "phase8_leads_v4_heldout.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(headline(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
