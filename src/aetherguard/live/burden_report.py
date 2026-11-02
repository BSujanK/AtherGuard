"""Reports of the alert-burden study: `reports/phase6_alert_burden.{md,json}` (the JSON is the source of truth) and the
'After re-derivation' section of `reports/phase6_backtest.md`."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from ..hazard.jsonio import dump_json
from ..hazard.tables import _num, _table
from .backtest_report import pct, share

REPORT_STEM = "phase6_alert_burden"
SECTION_TITLE = "After re-derivation"
HELDOUT_TITLES = {"season_2018": "2018 monsoon season (test year, 56 events)", "window_2023": "2023 India window",
                  "kerala_2018": "Kerala 2018 case"}
PARAMETER_KEYS = ("exit_factor", "exit_days", "uncertain_percentile")


def heldout_summary(result: dict, mode: str, variant: str = "operational") -> dict:
    """The numbers of one backtest set result that the before/after comparison reports (alert levels, `mode` thresholds)."""
    rules = result["variants"][variant][mode]
    entry, raw = rules["engine"], rules["raw_watch"]
    out = {"watch_plus": entry["alert_share_watch_plus"]["mean_daily_share"],
           "warning_plus": entry["alert_share_warning_plus"]["mean_daily_share"]["value"],
           "emergency": entry["alert_share_emergency"]["mean_daily_share"]["value"],
           "by_region": entry["alert_share_by_region"],
           "raw_rule_watch_plus": raw["alert_share_watch_plus"]["mean_daily_share"]["value"],
           "chance_watch_within_7d": entry["chance_watch_within_7d"], "flapping": entry.get("flapping")}
    events = entry.get("events")
    if events and events["n_events"]:
        own = events["own"]
        out["events"] = {"n": events["n_events"], "own_day": own["detected_of_all_events"],
                         "within_7d": own["detected_within_7d"], "median_lead_days": own["median_lead_days"],
                         "footprint_day": events["footprint"]["detected_of_all_events"]}
    window = entry.get("window_test")
    if window:
        out["window"] = {"detection": window["detection"], "control_any_alert": window["control_any_alert"],
                         "control_cell_day_alert_share": window["control_cell_day_alert_share"]}
    return out


def heldout_comparison(results: dict[str, dict]) -> dict:
    """Per set the conditions compared (operational features): `live_before` what the live runner published (the old
    parameters, pooled thresholds), `new` the v3 parameters with thresholds by region and, when `results` has them,
    `old` (the old parameters, thresholds by region) and `alt` (the costed alternative, thresholds by region)."""
    out = {}
    for name in results["new"]:
        entry = {"live_before": heldout_summary(results["old"][name], "pooled"),
                 "new": heldout_summary(results["new"][name], "region"),
                 "old": heldout_summary(results["old"][name], "region"),
                 "days": results["new"][name]["n_days"], "cells": results["new"][name]["n_cells"]}
        if "alt" in results:
            entry["alt"] = heldout_summary(results["alt"][name], "region")
        out[name] = entry
    return out


def condition_labels(parameters: dict) -> dict[str, str]:
    """Row labels of the held-out tables."""
    same = all(parameters["old"].get(k) == parameters["new"].get(k) for k in PARAMETER_KEYS)
    labels = {"live_before": "published by the live runner before (pooled thresholds, old parameters)",
              "new": "thresholds by region, " + ("old = v3 parameters (unchanged by the re-derivation)" if same
                                                else "v3 parameters"),
              "old": "thresholds by region, old parameters"}
    if "alt" in parameters:
        labels["alt"] = "thresholds by region, costed alternative (not adopted): " + describe(parameters["alt"])
    if same:
        labels.pop("old")
    return labels


def describe(parameters: dict) -> str:
    bound = parameters.get("uncertain_percentile", 90.0)
    return (f"exit factor {parameters['exit_factor']:g}, exit days {parameters['exit_days']}, `uncertain_high` "
            + ("off" if bound is None else f"at the ensemble {bound:g}th percentile"))


def build_report(analysis: dict, frozen: dict, parameters: dict, heldout: dict, meta: dict) -> dict:
    """The report payload. `analysis` is the out-of-fold development analysis (the basis of the choice), `frozen` the one
    of the frozen model on the same seasons, `parameters` the alert configs by label (old, new, alt)."""
    return {"schema": 1, "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), **meta,
            "protocol": analysis["protocol"], "events": analysis["events"],
            "thresholds_by_region": analysis["thresholds_by_region"],
            "raw_score_rule": analysis["raw_score_rule"], "risk_rule_vs_raw_rule": analysis["risk_rule_vs_raw_rule"],
            "decomposition": analysis["decomposition"], "grid": analysis["grid"], "grid_spec": analysis["grid_spec"],
            "selection": analysis["selection"], "allowed_loss_events": analysis["allowed_loss_events"],
            "parameters": parameters,
            "development": {"before": analysis["current"], "after": analysis["chosen"],
                            "alternative": analysis["alternative"]},
            "frozen_model_in_sample": {key: frozen[key] for key in ("protocol", "raw_score_rule", "decomposition", "grid",
                                                                    "selection", "risk_rule_vs_raw_rule", "current")},
            "heldout": heldout}


# ------------------------------------------------------------------------------------------------- markdown

def _detect(d: dict | None) -> str:
    if not d or d.get("value") is None:
        return "n/a"
    se = d.get("se")
    return f"{d['hits']}/{d['n']} = {100 * d['value']:.1f}%" + ("" if se is None else f" (SE {100 * se:.1f})")


def _dev_row(label: str, r: dict) -> list[str]:
    return [label, share(r["watch_plus_share"]), share(r["warning_plus_share"]), share(r["emergency_share"]),
            _detect(r["own_day"]), _detect(r["own_within_7d"]), _num(r["median_lead_days"], 1),
            _num(r["flapping"]["flaps_per_1000_cell_days"], 1)]


DEV_HEADER = ["rule", "Watch+ share", "Warning+", "Emergency", "own cell on the event day", "Watch+ within 7 days up to it",
              "median lead (days)", "flaps per 1000 cell-days"]


def _decomposition_table(raw_rule: dict, steps: list[dict]) -> str:
    rows = [_dev_row("0. frozen Watch rule on the raw score (the model's own rule)", raw_rule)]
    rows += [_dev_row(r["config"]["label"], r) for r in steps]
    return _table(DEV_HEADER, rows)


def _grid_table(report: dict) -> str:
    base = report["development"]["before"]["own_day"]["hits"]
    tags = (("current_key", "old"), ("chosen_key", "chosen"), ("alternative_key", "alternative"))
    rows = []
    for r in report["grid"]:
        c = r["config"]
        bound = "off" if c["bound"] == "off" else f"ensemble {c['bound']}"
        marks = "".join(f" ({tag})" for key, tag in tags if c["key"] == report["selection"][key])
        rows.append([f"{bound}, exit factor {c['exit_factor']:g}, exit days {c['exit_days']}{marks}"]
                    + _dev_row("", r)[1:] + [f"{r['own_day']['hits'] - base:+d}"])
    return _table(["combination", *DEV_HEADER[1:], "events vs old"], rows)


def _parameter_table(parameters: dict) -> str:
    labels = [k for k in ("old", "new", "alt") if k in parameters]
    head = {"old": "old (v2 development)", "new": "v3 (chosen)", "alt": "costed alternative (not adopted)"}
    rows = [[name, *(str(parameters[k].get(name)) for k in labels),
             "yes" if parameters["old"].get(name) != parameters["new"].get(name) else "no"] for name in PARAMETER_KEYS]
    return _table(["parameter", *(head[k] for k in labels), "chosen differs from old"], rows)


def _heldout_table(entry: dict, labels: dict) -> str:
    rows = []
    for key, label in labels.items():
        if key not in entry:
            continue
        s = entry[key]
        row = [label, pct(s["watch_plus"], 1), share(s["warning_plus"]), share(s["emergency"])]
        if s.get("events"):
            row += [pct(s["events"]["own_day"], 1),
                    _num(s["events"]["median_lead_days"], 1) + f" (chance {share(s['chance_watch_within_7d'])})"]
        if s.get("window"):
            row += [pct(s["window"]["detection"], 1), pct(s["window"]["control_any_alert"], 1)]
        flaps = s.get("flapping")
        row.append("n/a" if not flaps else _num(flaps["flaps_per_1000_cell_days"], 1))
        rows.append(row)
    header = ["condition", "Watch+ share [95% CI]", "Warning+", "Emergency"]
    if entry["new"].get("events"):
        header += ["detection, own cell [95% CI]", "median lead (days) vs chance rate"]
    if entry["new"].get("window"):
        header += ["window detection", "control cells alerted"]
    return _table(header + ["flaps per 1000 cell-days"], rows)


def heldout_section(report: dict, level: str = "###") -> list[str]:
    labels = condition_labels(report["parameters"])
    out = []
    for name, entry in report["heldout"].items():
        out += [f"{level} {HELDOUT_TITLES.get(name, name)}", "",
                f"{entry['cells']:,} cells, {entry['days']} days, operational features, one scoring pass. Descriptive "
                "only: nothing was chosen on these data.", "", _heldout_table(entry, labels), ""]
    return out


def render_markdown(report: dict) -> str:
    proto, frozen = report["protocol"], report["frozen_model_in_sample"]
    cur, chosen, alt = (report["development"][k] for k in ("before", "after", "alternative"))
    dec, params, n_events = report["risk_rule_vs_raw_rule"], report["parameters"], report["development"]["before"]["n_events"]
    kept = chosen["config"]["key"] == cur["config"]["key"]
    out = ["# Phase 6 alert burden and the v3 alert parameters", "",
           f"Generated {report['created_utc']}. {proto['note']}.", "",
           "## What was fixed in the live runner", "",
           "`live/run.py` compared the region-calibrated risk with the POOLED card thresholds. It now uses the card's "
           "`risk_by_region` thresholds of each cell's region for a model calibrated per region (pooled thresholds for any "
           "other region and for a pooled model), in the engine, in the hysteresis over the previous days and in the forecast "
           "leads; `run.json` keeps `model.thresholds` (pooled) and adds `model.thresholds_by_region`.", "",
           "## Protocol", "",
           f"- Development seasons: {proto['period']}; every day, with a 7-day warm-up before 1 June for the hysteresis "
           f"state. Shares are over {cur['cell_days']:,} scored cell-days of a seeded sample of 5,000 universe cells in the "
           f"out-of-fold analysis, and over all 36,792 cells in the frozen-model analysis ({frozen['current']['cell_days']:,} "
           "cell-days).",
           f"- Events: {report['events']['in_scored_cells']} in-domain train and validation positives of those seasons "
           f"(of {report['events']['in_season']}; the rest lie in cells the live runner does not score).",
           f"- Model for the choice: {proto['model']}.",
           f"- Why not the frozen model: it was fitted on every one of these positives, so it detects them almost whatever "
           f"the rule (raw-score Watch rule {frozen['raw_score_rule']['own_day']['hits']}/"
           f"{frozen['raw_score_rule']['n_events']}, against {report['raw_score_rule']['own_day']['hits']}/{n_events} out of "
           "fold) and a no-loss constraint measured on it is nearly empty. The year-blocked refits reproduce the card's "
           "out-of-fold recall at Watch exactly (0.917617), so the choice is made on them; the frozen-model analysis, as the "
           "brief specified it, is reported below.",
           f"- Grid: {proto['grid_size']} combinations (limit 30), seeded; bootstrap SE: {proto['bootstrap_se']['n']} event "
           f"resamples, seed {proto['bootstrap_se']['seed']} (reported, not used to choose).",
           f"- Objective: {report['selection']['objective']}; constraints: {report['selection']['constraints']}.", "",
           "## Where the burden comes from (development seasons, out of fold)", "",
           _decomposition_table(report["raw_score_rule"], report["decomposition"]), "",
           "Rows a to d add one rule at a time. (c) is hysteresis with the day count only (exit factor 1: a level steps down "
           "after `exit_days` consecutive days below it); (d) adds the exit factor and is the full alert levels. The side row "
           "keeps hysteresis but drops `uncertain_high`. Detection is the own cell on the event day; the 7-day column counts "
           "a Watch+ day in the 7 days up to and including it.", "",
           f"The calibrated-risk rule (a) is more permissive than the model's own raw-score rule (0): "
           f"{share(dec['risk_rule_only_share'])} of cell-days are at Watch by the risk threshold of the region but below the "
           f"frozen raw threshold, against {share(dec['raw_rule_only_share'])} the other way round. The isotonic calibration "
           "is flat over stretches of the raw score, so the risk threshold admits every raw score on the plateau at the "
           "threshold's risk. This is the largest piece of the burden that is not a tunable parameter: the card defines its "
           "operating points on the raw score, and comparing the raw score with the card's raw thresholds would remove it "
           "together with the recall that comes with it (row 0 against row a). It was not changed.", "",
           "The same decomposition for the frozen model on all universe cells (in-sample detection):", "",
           _decomposition_table(frozen["raw_score_rule"], frozen["decomposition"]), "",
           "## The grid (development seasons, out of fold)", "", _grid_table(report), "", "## Result", ""]
    if kept:
        out += [f"No combination reduces the Watch+ share without losing development events, so the old parameters stay: "
                f"{describe(params['new'])}. The exit factor changes nothing on this grid (the risk of a cell that has "
                "dropped is almost always far below the held level's threshold); a shorter hold and a narrower or removed "
                "`uncertain_high` bound each cost events.", ""]
    else:
        out += [f"The choice differs from the old parameters: {describe(params['new'])}.", ""]
    alt_text = describe(params["alt"]) if "alt" in params else describe(
        {"exit_factor": alt["config"]["exit_factor"], "exit_days": alt["config"]["exit_days"]})
    out += [f"Costed alternative, not adopted: the smallest burden that loses at most {report['allowed_loss_events']} events "
            f"(0.5% of {n_events}) is {alt_text}: Watch+ {share(alt['watch_plus_share'])} against "
            f"{share(cur['watch_plus_share'])}, own-cell detection {alt['own_day']['hits']}/{n_events} against "
            f"{cur['own_day']['hits']}/{n_events}, flaps per 1000 cell-days "
            f"{_num(alt['flapping']['flaps_per_1000_cell_days'], 1)} against "
            f"{_num(cur['flapping']['flaps_per_1000_cell_days'], 1)}.", "",
            "## Parameters", "", _parameter_table(params), "",
            "The data-derived values (source-disagreement range, heavy-rain amounts, station agreement) come from "
            "`aetherguard.alerts.derive`, which reads the development feature tables and no model: re-running it for v3 "
            "returns the v2 values unchanged. `alert_config_v3.json` records this and the grid.", "",
            "## Development before and after (out of fold)", "",
            _table(DEV_HEADER, [_dev_row("old parameters", cur), _dev_row("v3 parameters", chosen),
                                _dev_row("costed alternative (not adopted)", alt)]), "",
            "## 2018, 2023 and Kerala (descriptive, one scoring pass)", ""]
    out += heldout_section(report)
    out += ["## Limits", ""] + [f"- {line}" for line in report.get("limits", [])] + [""]
    return "\n".join(out)


def backtest_section(report: dict) -> str:
    """The 'After re-derivation' section appended to phase6_backtest.md."""
    params = report["parameters"]
    same = all(params["old"].get(k) == params["new"].get(k) for k in PARAMETER_KEYS)
    head = ("The alert parameters were re-derived on the 2007-2017 development seasons for v3-live "
            "(`reports/phase6_alert_burden.md`, year-blocked out-of-fold scoring). "
            + ("No combination of `exit_factor`, `exit_days` and the `uncertain_high` bound reduces the Watch+ share "
               "without losing development events, so the parameters are unchanged "
               "(`data/processed/alerts/alert_config_v3.json` records the derivation)." if same else
               f"Chosen: {describe(params['new'])}; old: {describe(params['old'])}; new config "
               "`data/processed/alerts/alert_config_v3.json`.")
            + " The tables above use the old parameters; the live runner now applies the thresholds of each region. Below, "
              "one scoring pass (operational features) is evaluated as the live runner published it before (pooled "
              "thresholds), with thresholds by region, and with the costed alternative. Nothing was chosen on these data.")
    return "\n".join([f"## {SECTION_TITLE}", "", head, ""] + heldout_section(report, "###"))


def append_section(md_path: Path, text: str) -> None:
    """Add `text` (a section starting `## After re-derivation`) to a markdown report, replacing an earlier copy of it."""
    md_path = Path(md_path)
    body = md_path.read_text(encoding="utf-8")
    body = re.split(rf"\n?## {re.escape(SECTION_TITLE)}\n", body, maxsplit=1)[0].rstrip("\n")
    md_path.write_text(body + "\n\n" + text.rstrip("\n") + "\n", encoding="utf-8")


def write_report(report: dict, out_dir: Path, stem: str = REPORT_STEM) -> tuple[Path, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path, md_path = out_dir / f"{stem}.json", out_dir / f"{stem}.md"
    dump_json(json_path, report)
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path
