"""Render reports/phase8_leads_v5_heldout.{json,md} from the ONE held-out look of the v4-static leads (heldout_result.json).

    python tools/leads_v5_heldout_report.py <heldout_v5/heldout_result.json> [<reports dir>]

Every number comes from the result file. Order: the deciding 2025 rows and the veto, the development gate, then the sets
beside it, labelled as not deciding. The rule is amendment 2 of docs/superpowers/specs/2026-11-17-aetherguard-leads-v5.md,
applied as written.
"""
import importlib.util
import json
import sys
from pathlib import Path

_V4 = Path(__file__).resolve().parent / "leads_v4_heldout_report.py"
_spec = importlib.util.spec_from_file_location("leads_v4_heldout_report", _V4)
v4report = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(v4report)

BESIDE_LABELS = {
    "w1_2021_2024_already_looked_at": "W1 2021-2024: ALREADY LOOKED AT by the v4-leads look (second look on the same events; decides nothing)",
    "v2_all_2025": "assembly v2 2025, all records (includes the BIPAD Nepal register: no stated licence, rows local only; decides nothing)",
    "v2_without_bipad_2025": "assembly v2 2025 without the BIPAD register (decides nothing)",
    "v2_india_2025": "assembly v2 2025, India only (decides nothing)"}


def headline(result: dict) -> str:
    veto, gate = result["veto"], result["preflight"]["gate"]
    slides = sorted({s["slides"] for s in result["deciding_w1_2025"].values()})
    verdict = "ADOPTED" if result["decision"]["adopt"] else "NOT ADOPTED"
    return (f"**v4-static forecast leads (candidate {result['candidate']}): {verdict}** by the rule of spec amendment 2, "
            f"declared before the look: the development gate {'passed' if gate['passed'] else 'failed'}, and the 2025 no-harm "
            f"veto was {'triggered' if veto['triggered'] else 'not triggered'} (NET_ALL = {veto['net_all']} against the "
            f"threshold {veto['t_all']}, NET_CE = {veto['net_ce']} against {veto['t_ce']}; a negative net means the candidate "
            f"caught more slides than the incumbent). The deciding 2025 set holds only {', '.join(map(str, slides))} independent "
            f"W1 slide(s) per lead, so the look could only have stopped a gross loss; it is no evidence of a gain.")


def render(result: dict) -> str:
    veto, gate = result["veto"], result["preflight"]["gate"]
    lines = ["# Forecast leads on v4-static (leads v5): the held-out look", "", headline(result), "",
             f"Taken once ({result['generated_utc']}). Spec docs/superpowers/specs/2026-11-17-aetherguard-leads-v5.md, amendment 2; "
             "preflight reports/phase8_leads_v5_preflight.md. Research prototype, not validated for issuing real public warnings.", "",
             "## Deciding: licence-clean W1 assembly, June-September 2025 (fresh)", "",
             "Each lead's candidate levels are burden-matched to the incumbent lead's realised 2025 shares.", ""]
    lines += v4report.detection_rows(result["deciding_w1_2025"])
    lines += ["", "### The no-harm veto (amendment 2 b)", "",
              "| lead | tolerance | level | incumbent | candidate | net loss (incumbent - candidate) |", "|---|---|---|---|---|---|"]
    lines += [f"| {r['lead']} | {r['tolerance']} | {r['level']}{'+' if r['level'] == 'Warning' else ''} | {r['incumbent']} | "
              f"{r['candidate']} | {r['net_loss']} |" for r in veto["rows"]]
    lines += ["", f"NET_ALL = {veto['net_all']} (veto at >= {veto['t_all']}); NET_CE = {veto['net_ce']} (veto at >= {veto['t_ce']}). "
              f"Veto triggered: {'yes' if veto['triggered'] else 'no'}.", "",
              "## Development gate (amendment 2 a, no event read)", "",
              f"Gate {'PASSED' if gate['passed'] else 'FAILED'}. Rule: {gate['rule']}." +
              (" Failures: " + "; ".join(gate["failures"]) if gate["failures"] else ""),
              f"Gate file sha256 `{result['preflight']['gate_sha256']}` (reports/phase8_leads_v5_e1.json), frozen by the preflight.", "",
              f"Decision: adopt = {str(result['decision']['adopt']).lower()} (gate passed = {result['decision']['gate_passed']}, "
              f"veto triggered = {result['decision']['veto_triggered']}).", "",
              "## Beside it, NOT deciding", ""]
    for name, by_lead in result["beside"].items():
        slides = {lead: s["slides"] for lead, s in by_lead.items()}
        lines += [f"### {BESIDE_LABELS.get(name, name)}", "",
                  f"Independent slides on the target days: {', '.join(f'lead {k} {v}' for k, v in slides.items())}.", ""]
        lines += v4report.detection_rows(by_lead) + [""]
    lines += ["## Caveats", "",
              f"- Low power: the deciding set has {', '.join(str(s['slides']) for s in result['deciding_w1_2025'].values())} "
              f"independent W1 slides (leads 1, 2, 3) and {', '.join(str(s['events']) for s in result['deciding_w1_2025'].values())} "
              "records. The veto can stop a gross loss only; adoption rests on the development evidence (spec sections 2 and 7).",
              "- GFS fallback: in the development gate, leads 2 and 3 used the GFS fallback on the issue days without an ECMWF "
              "archive (2022 and part of 2023; counts in reports/phase8_leads_v5_e1.json).",
              "- The idea came partly from the pattern of the spent v4-leads look (spec section 1); 2021-2024 is therefore beside "
              "only, as a second look.",
              "- Ground truth after 2018 is very incomplete; precision is relative.", ""]
    return "\n".join(lines)


def main() -> int:
    source = Path(sys.argv[1])
    reports = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).resolve().parents[1] / "reports"
    result = json.loads(source.read_text(encoding="utf-8"))
    (reports / "phase8_leads_v5_heldout.md").write_text(render(result), encoding="utf-8")
    (reports / "phase8_leads_v5_heldout.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(headline(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
