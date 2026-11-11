"""The W6 combined model v4 and the one held-out look of W5 and W6
(docs/superpowers/specs/2026-11-10-aetherguard-w5-static-susceptibility.md sections 3, 4 and 6).

    python -m aetherguard.hazard.v4_combined dev [--force] | seasons | preflight | heldout | report

v4 is v3-live plus every group that passed its own development stage: the six rain-intensity inputs (W3) and the nine
physical static inputs (W5, after the amendment that left roads and built-up share out). Every stage is `hazard.v4_int`'s,
run with configs/hazard_v4.yaml: the same folds, seeds, burden matching, tie-break, preflight and one-look guards. What
differs is in that file: the ranked incumbent is v4-int (its W3 season panels), not v3, and the candidate's season
features carry the static columns of each cell. This module adds only the report's wording.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..config import PROJECT_ROOT, data_root
from . import challengers as ch
from . import v4_int as w3

DEFAULT_CONFIG = PROJECT_ROOT / "configs" / "hazard_v4.yaml"


def static_stage(study: dict) -> dict:
    """The W5 group's own development records: the nine-column stage 1 and, when kept, the eleven-column run before the
    amendment."""
    directory = data_root() / "processed" / "hazard" / study["requires"]["stage_one"][0]
    out = {"nine": json.loads((directory / w3.DEV_RESULTS).read_text(encoding="utf-8"))}
    eleven = directory / "dev_results_eleven.json"
    if eleven.is_file():
        out["eleven"] = json.loads(eleven.read_text(encoding="utf-8"))
    return out


def _stage_line(label: str, record: dict) -> str:
    stage, cands = record["stage_one"], record["candidates"]
    name = next(n for n in cands if n != "C0")
    fa = record["comparison"]["metrics"][name][ch.HEADLINE]["value"]
    return (f"| {label} | {cands[name]['n_inputs']} | {fa:.4f} | {stage['difference']:+.4f} "
            f"[{stage['ci'][0]:+.4f}, {stage['ci'][1]:+.4f}] | {'passed' if stage['passed'] else 'failed'} |")


def markdown(result: dict, static: dict, names: tuple[str, str]) -> str:
    incumbent, candidate = names
    dev, stage, decision, heldout = result["dev"], result["stage_one"], result["decision"], result["heldout"]
    metrics = result["comparison"]["metrics"]
    verdict = "adopted" if decision["adopt"] else "not adopted"
    lines = [
        "# Static susceptibility inputs and the combined model v4 (phase 7, W5 and W6)", "",
        f"**v4 is {verdict}.** {decision['reason']}.", "",
        "v4 is the frozen v3-live configuration plus the six rain-intensity inputs of W3 (non-decreasing, lagged "
        f"{dev['lag_days']} IMD day(s)) and nine static inputs, unconstrained: "
        + ", ".join(f"`{c}`" for c in dev["static_inputs"]) + ". The criteria were fixed before any result "
        f"(`{result['spec']}` sections 3-4); section 6 is an amendment made after the development result and before any "
        "held-out look.", "",
        "## W5 stage 1: the static group alone (development, year-blocked CV 2007-2017)", "",
        "| v3 plus | inputs | pooled OOF FA@90 | difference to v3 (95% paired bootstrap) | stage 1 |", "|---|---|---|---|---|",
        *([_stage_line("all eleven columns, as first declared", static["eleven"])] if "eleven" in static else []),
        _stage_line("the nine physical columns (amendment)", static["nine"]), "",
        "FA@90 is a false-alarm share, so lower is better; v3's is "
        f"{static['nine']['comparison']['metrics']['C0'][ch.HEADLINE]['value']:.4f}. Nearly all of the eleven-column gain "
        "came from the built-up share (v3 plus roads and built-up alone: 0.1138). The catalogues place a slide where it "
        "was reported, which is where people and roads are, so those two columns predict that a slide gets recorded at "
        "least as much as that the ground fails, and the held-out events carry the same bias. They were left out of the "
        "hazard model before any held-out look; the cost is that the real effect of road cuts goes with them.", "",
        "## W6: v4 on development", "",
        f"The reference `C0` reproduces the frozen v3-live FA@90 to {dev['reproduction']['abs_difference']:.1e}.", "",
        "| model | inputs | trees | pooled OOF FA@90 (95% CI) |", "|---|---|---|---|",
        *[f"| {name} | {c['n_inputs']} | {c['n_trees']} | {w3._fa(metrics[name][ch.HEADLINE])} |"
          for name, c in dev["candidates"].items()], "",
        f"{candidate} - C0 = {stage['difference']:+.4f}, 95% paired-bootstrap interval [{stage['ci'][0]:+.4f}, "
        f"{stage['ci'][1]:+.4f}] ({'passed' if stage['passed'] else 'failed'} the not-significantly-worse guard).", ""]
    if heldout is None:
        return "\n".join([*lines, "## Held-out", "", "No look was taken.", ""])
    scores, beside, seasons = heldout["scores"], heldout["scores_v3_rules"], heldout["seasons"]
    lines += [
        "## The held-out look (pooled 2018-2025, the W1 assembly, taken once)", "",
        f"{scores['events']} events in {scores['slides']} independent slides. The deciding comparison is {candidate} against "
        f"`{incumbent}`, the incumbent v4-int: in each season both rank the scored cell-days by their own calibrated risk "
        "and are cut to the Watch+ / Warning+ / Emergency shares v3 realised with the section 11 rules, so the comparison "
        "is at equal burden and isolates the nine static inputs. Detection is the number of independent slides with an "
        "alert at the level within tolerance (`tolerant`: 10 km, 1 day; `cell_exact`: the same cell and day).", "",
        f"| tolerance | level | {incumbent} slides detected | {candidate} slides detected | difference | not lower | higher |",
        "|---|---|---|---|---|---|---|",
        *[f"| {c['tolerance']} | {c['level']} | {c['v3']} | {c['candidate']} | {c['difference']:+d} | "
          f"{'yes' if c['not_lower'] else 'NO'} | {'yes' if c['higher'] else 'no'} |" for c in decision["conditions"]], "",
        "Adoption needs every row \"not lower\" and at least one \"higher\".", "",
        f"All levels ({incumbent} against {candidate}):", "", *w3._slide_rows(scores, (incumbent, candidate)), "",
        f"Beside it, not deciding: v3 with the section 11 rules and the hysteresis against {candidate}:", "",
        *w3._slide_rows(beside, ("v3 with rules", candidate)), "",
        "Alert cell-days at the matched burden, pooled, on the same scored cell-days (Watch+ / Warning+ / Emergency):", "",
        "| levels | alert cell-days |", "|---|---|",
        *[f"| {name} | " + " / ".join(f"{n:,}" for n in counts) + " |"
          for name, counts in heldout["pooled"]["alert_cell_days_scored"].items()], "",
        "Burden matching per season (target, then the realised shares; ties at the cuts with the cell-days a straddled tie "
        "leaves out in brackets):", "",
        f"| season | target | {incumbent} realised | {candidate} realised | {incumbent} ties | {candidate} ties |",
        "|---|---|---|---|---|---|",
        *[f"| {year} | {w3._pct(s['v3_realised_shares'])} | {w3._pct(s[incumbent]['realised'])} | {w3._pct(s[candidate]['realised'])} | "
          f"{w3._ties(s[incumbent])} | {w3._ties(s[candidate])} |" for year, s in seasons.items()], "",
        "Ground truth after 2018 is very incomplete, so detection counts are relative (between models at equal burden), not "
        "absolute. Adoption into the live run is a separate, reviewed step.", ""]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("stage", choices=["dev", "seasons", "preflight", "heldout", "report"])
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--features", type=Path, default=None, help="feature store directory")
    parser.add_argument("--force", action="store_true", help="dev: overwrite earlier development results; seasons: rescore panels that exist")
    args = parser.parse_args(argv)
    if args.stage == "report":
        study = w3.load_study(args.config)
        static, names = static_stage(study), w3.pool_names(study)
        w3.write_report(study, render=lambda result: markdown(result, static, names), say=lambda m: print(m, flush=True))
        return 0
    return w3.main([args.stage, "--config", str(args.config), *(["--features", str(args.features)] if args.features else []),
                    *(["--force"] if args.force else [])])


if __name__ == "__main__":
    sys.exit(main())
