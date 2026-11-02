"""reports/phase6_v31_challenger.{md,json}: the v3.1 challenger study (spec section 15), rendered from its result files.

Every number is read from `data/processed/hazard/<output_dir>/` (label audit, development results, the test_2018 record) and
`data/processed/alerts/<replay_dir>/replay.json`; a missing or null value prints as NaN.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ..config import PROJECT_ROOT, data_root
from . import v31_challenger as vc
from . import v31_eval as ve
from .jsonio import dump_json

LEVEL_LABELS = {"watch": "Watch+", "warning": "Warning+", "emergency": "Emergency"}


def _read(path: Path) -> dict | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def build(study: dict) -> dict:
    """The report payload: the label audit, the development results, the test_2018 record and the replay (None when absent)."""
    out = vc.output_dir(study)
    replay = _read(data_root() / "processed" / "alerts" / study["replay_dir"] / ve.REPLAY_FILE)
    return {"created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "spec": "docs/superpowers/specs/2026-10-14-aetherguard-live-global-design.md section 15",
            "labels": _read(out / vc.LABEL_SUMMARY), "development": _read(out / vc.DEV_RESULTS),
            "heldout_2018": _read(out / ve.HELDOUT), "replay": replay}


# ------------------------------------------------------------------------------------------- formatting

def num(value, digits: int = 4) -> str:
    return "NaN" if value is None else f"{value:.{digits}f}"


def pct(value, digits: int = 1) -> str:
    return "NaN" if value is None else f"{100 * value:.{digits}f}%"


def ci(entry: dict | None, digits: int = 4, percent: bool = False) -> str:
    """`value [lo, hi]` of a summary with `value`/`lo`/`hi` (or `lo`/`hi` around a given point)."""
    if not entry:
        return "NaN"
    f = (lambda v: pct(v, digits)) if percent else (lambda v: num(v, digits))
    return f"{f(entry.get('value'))} [{f(entry.get('lo'))}, {f(entry.get('hi'))}]"


def with_point(point, interval: dict | None, digits: int = 4, percent: bool = False) -> str:
    return ci({"value": point, "lo": (interval or {}).get("lo"), "hi": (interval or {}).get("hi")}, digits, percent)


def table(header: list[str], rows: list[list]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def cell_text(text: str, limit: int = 150) -> str:
    text = " ".join(str(text).replace("|", "/").split())
    return text if len(text) <= limit else text[:limit - 1] + "..."


# ------------------------------------------------------------------------------------------- sections

def labels_section(labels: dict | None) -> str:
    if not labels:
        return "## 1. Label audit\n\nNot run.\n"
    scopes = labels["scopes"]
    lines = ["## 1. Label audit (Step 1, no model)", "",
             f"{labels['positive_cell_days']} positive cell-days of the development period and test_2018 from {labels['records']} catalog "
             f"records; {labels['low_terrain']} sit on low-terrain cells (mean slope under 5 degrees or mean elevation under 100 m). "
             f"The pre-declared rule (spec 15.2) marks {labels['implausible']} cell-days as physically implausible.", "",
             table(["population", "positive cell-days", "low terrain", "implausible", "low terrain Himalaya / Western Ghats"],
                   [[name.replace("_", " "), s["positives"], s["low_terrain"], s["implausible"],
                     f"{s['low_terrain_by_region'].get('himalaya', 0)} / {s['low_terrain_by_region'].get('western_ghats', 0)}"]
                    for name, s in scopes.items()]), "",
             "Catalog fields of the records on low-terrain cells against the records elsewhere:", ""]
    rows = []
    for field, parts in labels["records_by_field"].items():
        for value in sorted(set(parts["low_terrain"]) | set(parts["other"]), key=lambda v: -parts["low_terrain"].get(v, 0)):
            rows.append([field, value, parts["low_terrain"].get(value, 0), parts["other"].get(value, 0)])
    lines += [table(["field", "value", "records on low terrain", "records elsewhere"], rows), "",
              f"Location accuracy: no record is coarser than the {num(labels['cell_km'], 2)} km grid cell "
              f"({labels['records_coarser_than_cell']} records), so a coarser-than-cell rule selects nothing.", "",
              "Flags of the rule (a record can carry several):", "",
              table(["flag", "records on low terrain", "records elsewhere"],
                    [[k, labels["records_flagged_by_flag"]["low_terrain"][k], labels["records_flagged_by_flag"]["other"][k]]
                     for k in labels["records_flagged_by_flag"]["low_terrain"]]), "",
              f"Cell-days whose records are all flagged: {labels['flagged_all_records']}, of which {labels['flagged_all_records_not_low_terrain']} "
              f"are not on low terrain; implausible (flagged and on low terrain) {labels['implausible']} by reason "
              f"{json.dumps(labels['implausible_by_reasons'])}, by split {json.dumps(labels['implausible_by_split'])}, "
              f"by region {json.dumps(labels['implausible_by_region'])}.", "",
              f"Concentration: {labels['low_terrain_top_cells']['cell_days']} low-terrain cell-days fall on "
              f"{labels['low_terrain_top_cells']['distinct_cells']} cells; the largest are "
              + ", ".join(f"{c['cell_id']} ({c['cell_days']})" for c in labels["low_terrain_top_cells"]["top"][:5]) + ".", "",
              f"{len(labels['examples'])} example low-terrain positives with their catalog text (seeded sample):", "",
              table(["cell", "date", "region", "slope", "elev m", "source", "category", "trigger", "accuracy", "setting", "flags", "text"],
                    [[e["cell_id"], e["date"], e["region"], num(e["slope_mean"], 1), num(e["elev_mean"], 0), e["sources"],
                      e["categories"], e["triggers"], e["accuracies"], e["settings"], e["reasons"] or "-", cell_text(e["text"])]
                     for e in labels["examples"]]), ""]
    return "\n".join(lines)


def candidates_section(dev: dict) -> str:
    lines = ["## 2. Candidates (Step 2)", "",
             table(["candidate", "inputs", "trees", "description", "positives dropped from training"],
                   [[n, c["n_inputs"], dev["evaluation"]["candidates"][n]["n_trees"], c["description"], c["positives_dropped"]]
                    for n, c in dev["candidates"].items()]), "",
             f"All use the frozen v3-live hyper-parameters, folds, seeds and calibration (spec 15.3). The audit lists "
             f"{dev['development']['implausible_positives_in_audit']} implausible cell-days; only the in-domain development positives "
             "among them can be in the training rows, and those are the ones C3 drops. Every candidate is scored on all "
             f"{dev['development']['positives']} development positives.", "",
             f"Reference reproduction: C0 pooled OOF FA@90 {num(dev['reproduction']['recomputed_fa_at_90'], 6)} against the frozen "
             f"v3-live {num(dev['reproduction']['reported_fa_at_90'], 6)} (difference {dev['reproduction']['abs_difference']:.1e}), "
             f"{dev['reproduction']['n_trees']} trees against {dev['reproduction']['reported_n_trees']}.", ""]
    return "\n".join(lines)


def development_section(dev: dict) -> str:
    evaluation = dev["evaluation"]
    cands = evaluation["candidates"]
    boot = evaluation["bootstrap"]
    ref = evaluation["reference"]
    lines = [f"## 3. Development results (pooled out-of-fold, 2007-2017; bootstrap n={boot['n']}, seed {boot['seed']}, level {boot['level']})", "",
             "### FA@90 (primary metric)", "",
             table(["candidate", "FA@90 [95% CI]", "difference vs " + ref + " [95% paired CI]", "CI excludes 0", "PR-AUC"],
                   [[n, ci(c["fa_at_90"]), "-" if n == ref else with_point(c["fa_diff_vs_reference"]["point_difference"], {
                       "lo": c["fa_diff_vs_reference"]["ci_lo"], "hi": c["fa_diff_vs_reference"]["ci_hi"]}),
                     "-" if n == ref else ("yes" if c["fa_diff_vs_reference"]["excludes_zero"] else "no"), num(c["pr_auc"], 6)]
                    for n, c in cands.items()]), "",
             "### Warning+ alert level (each candidate's own Warning threshold, re-derived as v3's was; point level, no post-model rules)", "",
             table(["candidate", "OOF recall", "false-alarm share", "Warning+ cell-days (millions)",
                    "low-terrain share [95% CI]", "difference vs " + ref + " [95% paired CI]", "low-rain share [95% CI]",
                    "events per 1,000 cell-days [95% CI]"],
                   [[n, pct(c["levels"]["warning"]["recall"]), pct(c["levels"]["warning"]["fa_share"], 2),
                     num(c["levels"]["warning"]["cell_days"] / 1e6, 2),
                     with_point(c["levels"]["warning"]["low_share"], c["levels"]["warning"]["bootstrap"]["low_share"], 1, True),
                     "-" if n == ref else with_point(c["low_share_diff_vs_reference"]["value"], c["low_share_diff_vs_reference"], 3, True),
                     with_point(c["levels"]["warning"]["lowrain_share"], c["levels"]["warning"]["bootstrap"]["lowrain_share"], 1, True),
                     with_point(c["levels"]["warning"]["precision_per_1000"], c["levels"]["warning"]["bootstrap"]["precision_per_1000"], 4)]
                    for n, c in cands.items()]), "",
             "Low-terrain share of Warning+ cell-days by region:", "",
             table(["candidate", "Himalaya", "Western Ghats"],
                   [[n, pct(c["by_region_warning"]["himalaya"]["low_share"]), pct(c["by_region_warning"]["western_ghats"]["low_share"])]
                    for n, c in cands.items()]), "",
             f"### Recall and false-alarm share at {ref}'s raw operating thresholds (and at each candidate's own)", ""]
    rows = []
    for n, c in cands.items():
        row = [n]
        for level in vc.LEVELS:
            at_ref, own = c["at_reference_thresholds"][level], c["levels"][level]
            row.append(f"{pct(at_ref['recall'])} / {pct(at_ref['fa_share'], 2)}; own {pct(own['recall'])} / {pct(own['fa_share'], 2)}")
        rows.append(row)
    lines += [table(["candidate", "Watch: recall / FA share", "Warning: recall / FA share", "Emergency: recall / FA share"], rows), "",
              "### Calibration (cross-fitted over the seven folds, deciles of calibrated risk)", "",
              table(["candidate", "ECE per-region calibrators", "ECE pooled calibrator", "ECE / base rate (per-region)"],
                    [[n, f"{c['ece']['crossfit_per_region']['ece_deciles']:.3e}", f"{c['ece']['crossfit_pooled']['ece_deciles']:.3e}",
                      num(c["ece"]["crossfit_per_region"]["ece_deciles"] / c["ece"]["crossfit_per_region"]["base_rate"], 2)]
                     for n, c in cands.items()]), "",
              "Reliability deciles are in `dev_results.json` (`evaluation.candidates.<name>.ece`).", ""]
    return "\n".join(lines)


def selection_section(dev: dict) -> str:
    selection = dev["selection"]
    lines = ["## 4. Pre-declared selection (spec 15.5)", "",
             f"Reference {selection['reference']} Warning+ low-terrain share {pct(selection['reference_warning_low_share'], 2)}.", "",
             table(["candidate", "FA@90", "difference [95% paired CI]", "not worse than reference", "Warning+ low-terrain share",
                    "below reference share", "eligible"],
                   [[r["candidate"], num(r["fa_at_90"]), with_point(r["fa_difference"], {"lo": r["fa_difference_ci"][0], "hi": r["fa_difference_ci"][1]}),
                     "yes" if r["not_worse_than_reference"] else "no", pct(r["warning_low_share"], 2),
                     "yes" if r["lower_low_share"] else "no", "yes" if r["eligible"] else "no"] for r in selection["candidates"]]), "",
             f"**Result: {selection['result']}.**", ""]
    return "\n".join(lines)


def terrain_section(dev: dict) -> str:
    cands = dev["evaluation"]["candidates"]
    lines = ["## 5. Descriptive follow-up: alerts and events on low-terrain cells (not used for the selection)", "",
             "Added after the selection result was known, from the same OOF rows: how often each candidate alerts at Warning on "
             "low-terrain cells against other cells, and the events per 1,000 alerted cell-days there. The base event rate is the "
             "positives per 1,000 cell-days of each terrain class.", "",
             table(["candidate", "Warning+ rate on low terrain", "on other cells", "events / 1,000 Warning+ cell-days: low terrain",
                    "other cells", "base events / 1,000 cell-days: low terrain", "other cells"],
                   [[n, pct(c["levels"]["warning"]["low_alert_rate"], 2), pct(c["levels"]["warning"]["other_alert_rate"], 2),
                     num(c["levels"]["warning"]["low_precision_per_1000"], 4), num(c["levels"]["warning"]["other_precision_per_1000"], 4),
                     num(c["levels"]["warning"]["low_base_events_per_1000"], 4), num(c["levels"]["warning"]["other_base_events_per_1000"], 4)]
                    for n, c in cands.items()]), ""]
    return "\n".join(lines)


def heldout_section(heldout: dict | None) -> str:
    lines = ["## 6. test_2018 (Step 4, one look)", ""]
    if heldout is None:
        return "\n".join(lines + ["Not run.", ""])
    if heldout.get("skipped"):
        return "\n".join(lines + [f"Not run: {heldout['reason']}.", ""])
    ref, cand = heldout["models"][ve.V3], heldout["models"]["candidate"]
    diff, crit = heldout["paired_fa_at_90"], heldout["criterion"]
    scorings = (("v3-live", ref), (heldout["candidate"], cand))
    lines += [f"Candidate {heldout['candidate']} against the frozen v3-live on {heldout['population']['positives_in_domain']} in-domain positive "
              f"cell-days and {heldout['population']['universe_rows']:,} universe rows. Frozen v3-live re-scored FA@90 "
              f"{num(heldout['reproduction']['recomputed_fa_at_90'], 6)} against its report {num(heldout['reproduction']['reported_fa_at_90'], 6)}.", "",
              table(["scoring", "FA@90 [95% CI]"], [[label, ci(m["fa_at_90"])] for label, m in scorings]), "",
              f"Paired difference FA@90 ({heldout['candidate']} minus v3-live): {with_point(diff['point_difference'], {'lo': diff['ci_lo'], 'hi': diff['ci_hi']})}.", "",
              table(["scoring", "level", "events", "recall", "false-alarm share", "cell-days (millions)", "low-terrain share [95% CI]",
                     "events / 1,000 cell-days"],
                    [[label, LEVEL_LABELS[level], m["levels"][level]["events"], pct(m["levels"][level]["recall"]),
                      pct(m["levels"][level]["fa_share"], 2), num(m["levels"][level]["cell_days"] / 1e6, 2),
                      with_point(m["levels"][level]["low_share"], m["levels"][level]["bootstrap"]["low_share"], 1, True),
                      num(m["levels"][level]["precision_per_1000"], 4)]
                     for label, m in scorings for level in vc.LEVELS]), "",
              "Pre-declared adoption criterion (spec 15.6):", "",
              table(["criterion", "result"],
                    [["(a) FA@90 not worse than v3-live (CI lower end of the difference <= 0)", "yes" if crit["a_fa_at_90_not_worse"] else "no"],
                     ["(b) Warning+ low-terrain share below v3-live's", "yes" if crit["b_lower_warning_low_share"] else "no"],
                     [f"(c) Warning+ events lost at most {crit['c_allowed']}", f"lost {crit['c_warning_events_lost']}: " + ("yes" if crit["c_within_allowance"] else "no")]]), "",
              f"**Recommended for adoption: {'yes' if crit['recommended'] else 'no'}.**", ""]
    return "\n".join(lines)


def replay_section(replay: dict | None, selected: str | None) -> str:
    lines = ["## 7. Offline live replay (spec 15.7)", ""]
    if replay is None:
        return "\n".join(lines + ["Not run.", ""])
    protocol, check = replay["protocol"], replay["v3_replay_check"]
    names = [ve.V3, *protocol["candidates"]]
    exploratory = [n for n in protocol["candidates"] if n != selected]
    lines += [f"Days {protocol['days'][0]}..{protocol['days'][-1]} from the stored `features_D0.parquet` (reported from {protocol['report_from']}); "
              f"nothing was written to `data/live`. " + (f"Replayed candidates {', '.join(protocol['candidates'])}"
              + (f" are EXPLORATORY ({', '.join(exploratory)}): the pre-declared selection did not choose them, no test_2018 is involved, "
                 "and the replay is context for a decision, not a result of the selection." if exploratory else "") + ""), "",
              f"Check of the replay chain: the frozen v3-live replay equals the published level on {check['cell_days_equal_to_published']:,} of "
              f"{check['cell_days']:,} cell-days ({pct(check['cell_days_equal_to_published'] / check['cell_days'], 3)}); "
              f"{check['from_report_start']} cell-days differ from the report start.", "",
              "Cells at each level on the last day (published table, then replays):", "",
              table(["levels", *["Normal", "Watch", "Warning", "Emergency"]],
                    [[name, *[replay["levels_per_day"][name][-1][level] for level in ("Normal", "Watch", "Warning", "Emergency")]]
                     for name in ["published", *names]]), "",
              "Last-day alert counts in the descriptive classes:", "",
              table(["class", *["published", *names]],
                    [[label, *[counts[n] for n in ["published", *names]]] for label, counts in replay["last_day_classes"].items()]), ""]
    area_rows = []
    for area, per in replay["areas"].items():
        for name in ["published", *names]:
            counts = per[name]
            area_rows.append([area, replay["area_cell_counts"][area], name, counts["Watch"], counts["Warning"], counts["Emergency"]])
    lines += ["Named areas on the last day (cells at each level):", "",
              table(["area", "cells", "levels", "Watch", "Warning", "Emergency"], area_rows), "",
              "Highest cells of each area (levels on the last day):", ""]
    for area, rows in replay["area_cells"].items():
        if not rows:
            continue
        lines += [f"{area}:", "", table(["cell", "lat", "lon", "slope", "elev m", "3-day rain mm", *["published", *names]],
                                       [[r["cell_id"], num(r["lat"], 2), num(r["lon"], 2), num(r["slope_mean"], 1), num(r["elev_mean"], 0),
                                         num(r["acc_3"], 1), *[r["levels"][n] for n in ["published", *names]]] for r in rows]), ""]
    lines += ["Last-day transitions from the v3-live replay to each candidate (cells):", ""]
    for name, moves in replay["transitions_last_day"].items():
        lines.append(f"* {name}: " + (", ".join(f"{k} {v}" for k, v in moves.items()) or "none"))
    leads = replay["leads_last_day"]

    def lead_counts(name: str, k: int) -> str:
        counts = leads["published"][str(k)] if name == "published" else leads["counts"][name][str(k)]
        return " / ".join(str(counts[level]) for level in ("Watch", "Warning", "Emergency"))
    lines += ["", "Forecast leads of the last day (point level and rain cap, no hysteresis): the frozen v3 replay equals the published "
              "level on " + ", ".join(f"D+{k}: {v:,}" for k, v in leads["v3_equals_published"].items()) + " cells. Cells at "
              "Watch / Warning / Emergency:", "",
              table(["lead", "published", *names], [[f"D+{k}", *[lead_counts(n, k) for n in ["published", *names]]] for k in (1, 2, 3)]), ""]
    return "\n".join(lines)


def summary_section(report: dict) -> str:
    dev, heldout, replay = report["development"], report["heldout_2018"], report["replay"]
    cands = dev["evaluation"]["candidates"]
    lines = ["## Summary", "",
             f"* Pre-declared selection (spec 15.5): **{dev['selection']['result']}**. " + ", ".join(
                 f"{n} FA@90 {num(c['fa_at_90']['value'])} ({num(c['fa_diff_vs_reference']['point_difference'], 4)} vs C0, CI lower end "
                 f"{num(c['fa_diff_vs_reference']['ci_lo'], 4)})" for n, c in cands.items() if n != dev["evaluation"]["reference"])
             + f"; C0 {num(cands['C0']['fa_at_90']['value'])} reproduces the frozen v3-live.",
             f"* Label audit: {report['labels']['implausible']} of {report['labels']['low_terrain']} low-terrain positive cell-days are implausible by "
             f"the pre-declared catalog-field rule ({report['labels']['scopes']['development_in_domain']['implausible']} of "
             f"{report['labels']['scopes']['development_in_domain']['low_terrain']} in the in-domain development positives); the rest are ordinary "
             "rain-triggered landslide reports.",
             "* test_2018: " + ("not read (no candidate selected)." if heldout and heldout.get("skipped") else
                                "see section 6." if heldout else "not run."),
             "* Live replay: " + ("see section 7." if replay else "not run.")]
    if replay:
        lines.append("* Exploratory replay of the challengers on the last live day (" + replay_headline(replay) + ").")
    return "\n".join(lines) + "\n"


def replay_headline(replay: dict) -> str:
    """One line of the replay: the Kanyakumari cell and the descriptive class counts per level set."""
    names = ["published", ve.V3, *replay["protocol"]["candidates"]]
    kanyakumari = {n: next((level for level, count in replay["areas"]["kanyakumari"][n].items() if count), "NaN") for n in names}
    classes = "; ".join(f"{label}: " + ", ".join(f"{n} {counts[n]}" for n in names)
                        for label, counts in replay["last_day_classes"].items())
    return "cell 19625150 is " + ", ".join(f"{n} {level}" for n, level in kanyakumari.items()) + "; " + classes


def markdown(report: dict) -> str:
    dev = report["development"]
    selected = dev["selection"]["selected"]
    head = ["# v3.1 challenger: label audit and physical constraints", "",
            f"Generated {report['created_utc']}. Design, candidate definitions, selection and adoption criteria: {report['spec']} "
            "(written before any cross-validation or test_2018 number of this study). Analysis only: the frozen v2/v3 artifacts, the live run "
            "and the published tables are unchanged and nothing here is wired. Every number is read from the result files of "
            "`data/processed/hazard/v31_challenger/` and `data/processed/alerts/v31_replay/`.", ""]
    parts = [summary_section(report), labels_section(report["labels"]), candidates_section(dev), development_section(dev),
             selection_section(dev), terrain_section(dev), heldout_section(report["heldout_2018"]),
             replay_section(report["replay"], selected)]
    return "\n".join(head) + "\n" + "\n".join(parts)


def write_report(study: dict, say=print, reports_dir: Path | None = None) -> dict:
    report = build(study)
    for name in ("labels", "development"):
        if report[name] is None:
            raise FileNotFoundError(f"the `{name}` result is missing; run the labels and dev stages first")
    directory = Path(reports_dir) if reports_dir else PROJECT_ROOT / "reports"
    directory.mkdir(parents=True, exist_ok=True)
    stem = study["report_stem"]
    dump_json(directory / f"{stem}.json", report)
    (directory / f"{stem}.md").write_text(markdown(report), encoding="utf-8")
    say(f"wrote reports/{stem}.md and .json")
    return report
