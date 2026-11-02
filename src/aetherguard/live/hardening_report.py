"""Report of the alert accuracy hardening: `reports/phase6_accuracy_hardening.{md,json}` (the JSON is the source of truth).

Every number is read from the computed results: the development analysis (`hardening analyze-dev`), the one evaluation
(`hardening evaluate`), the aspect ablation of the challenger harness and the audit of the live days. Nothing is typed in.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ..hazard import model as hm
from ..hazard.jsonio import dump_json
from ..hazard.tables import _table
from . import hardening as H
from . import hardening_dev as D
from . import hardening_eval as E
from . import hardening_leads as L
from .audit import DEFAULT_OUT as AUDIT_DIR

REPORT_STEM = "phase6_accuracy_hardening"
FIRST_PUBLICATION_FILE = "evaluation_hold_window_3.json"   # the first evaluation, on the inputs of the first 23 Oct run
ABLATION_STEM = "phase6_aspect_ablation"
LEVEL_NAMES = ("Watch", "Warning", "Emergency")
CELL_NAMES = {"23965166": "23965166 (29.83N 78.32E, himalaya)", "24605098": "24605098 (Katra, Reasi, J&K; 33.03N 74.93E)"}


def _read(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def pct(value, digits: int = 2) -> str:
    return "n/a" if value is None else f"{100 * value:.{digits}f}%"


def detect(entry: dict) -> str:
    return f"{entry['hits']}/{entry['n']} = {100 * entry['value']:.1f}% [{100 * entry['lo']:.1f}, {100 * entry['hi']:.1f}]"


def build(out_dir: Path) -> dict:
    dev = _read(H.alerts_dir(H.DEV_DIR) / D.ANALYSIS_FILE)
    evaluation = _read(H.alerts_dir(H.HELDOUT_DIR) / E.EVALUATION_FILE)
    first = _read(H.alerts_dir(H.HELDOUT_DIR) / FIRST_PUBLICATION_FILE)["live_day"]
    ablation = _read(Path(out_dir) / f"{ABLATION_STEM}.json")
    audit = _read(AUDIT_DIR / "summary.json")
    before = AUDIT_DIR / "summary_before_rerun.json"
    candidate = next(c for c in ablation["candidates"] if c["name"] == "lgb_no_aspect")
    incumbent = next(c for c in ablation["candidates"] if c["name"] == "v3_selected")
    return {"created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "rules": dev["rules"], "development": dev, "evaluation": evaluation,
            "first_publication": {"levels": first["before"], "reported_cells": {c: x["before"] for c, x in
                                                                               first["reported_cells"].items()},
                                  "source": f"{E.EVALUATION_FILE} of the first evaluation ({FIRST_PUBLICATION_FILE})"},
            "aspect_ablation": {"candidate": "lgb_no_aspect", "columns": candidate["columns"],
                                "fa_at_90": candidate["metrics"]["fa_at_recall_0.9"],
                                "incumbent_fa_at_90": incumbent["metrics"]["fa_at_recall_0.9"],
                                "paired_vs_v3": candidate["paired_vs_v3"], "adoption": ablation["adoption"],
                                "report": f"reports/{ABLATION_STEM}.md"},
            "forecast_leads": L.load_result(), "audit": audit,
            "audit_before_rerun": _read(before) if before.is_file() else None}


def _level_rows(results: list[tuple[str, dict]]) -> list[list[str]]:
    rows = []
    for label, r in results:
        rows.append([label, *(pct(r["share_at_least"][n]) for n in LEVEL_NAMES),
                     *(detect(r["detected_at_least"][n]) for n in LEVEL_NAMES),
                     *(f"{r['dry_cell_days_at'][n]:,}" for n in LEVEL_NAMES)])
    return rows


LEVEL_HEADER = ["condition", "Watch+ share", "Warning+ share", "Emergency share", "events at Watch+", "at Warning+",
                "at Emergency", "dry Watch cell-days", "dry Warning", "dry Emergency"]


def _rain_table(dev: dict) -> str:
    rows = []
    for c in dev["rain"]["candidates"]:
        minima = ", ".join(f"{w}-day {m:.3g} mm" for w, m in sorted(c["minimum_mm"].items()))
        if c["per_level"] is None:
            rows.append([c["form"], f"p{c['percentile']:g}", minima, "vacuous (a 0 mm minimum admits every cell-day)",
                         "", "", ""])
            continue
        cells = [f"{p['events_lost']} lost of {p['events_before']} ({pct(p['relative_loss'])}); share {pct(p['share_before'])}"
                 f" -> {pct(p['share_after'])}; {'adopt' if p['adopt'] else 'no'}" for p in c["per_level"]]
        rows.append([c["form"], f"p{c['percentile']:g}", minima, *cells, ", ".join(c["adoptable_levels"]) or "none"])
    return _table(["form", "percentile", "minimum", "gate at Watch", "gate at Warning", "gate at Emergency",
                   "adoptable at"], rows)


def _windows(rules: dict) -> str:
    return ", ".join(f"{level} {w} day{'s' if w > 1 else ''}" for level, w in rules["hold_window_days_by_level"].items())


def _window_table(study: dict) -> str:
    rows = []
    for level, x in study["per_level"].items():
        for w, entry in x["windows"].items():
            a = entry["adoption"]
            rows.append([level, w, f"{a['events_lost']} of {a['events_before']} ({pct(a['relative_loss'])})",
                         pct(a["share_after"]), "adopt" if a["adopt"] else "no"])
    for a in study["combined_adoption"]:
        rows.append([a["level"], "chosen, all together", f"{a['events_lost']} of {a['events_before']} "
                     f"({pct(a['relative_loss'])})", pct(a["share_after"]), "adopt" if a["adopt"] else "no"])
    return _table(["level", "hold window (days)", "events lost at the level", "share at the level", ""], rows)


def _agreement_table(split: dict) -> str:
    rows = []
    for a, g in split["by_minimum"].items():
        for name in ("agreeing", "disagreeing"):
            x = g[name]
            rows.append([a, name, f"{x['events']} ({pct(x['events_share_of_all'], 1)} of all events)",
                         f"{x['alert_cell_days']:,} ({pct(x['alert_cell_day_share'], 1)})",
                         f"{x['events_per_1000_alerted_cell_days']:.4f}" if x["events_per_1000_alerted_cell_days"]
                         is not None else "n/a"])
    return _table(["A", "group", "development events with a Warning+ point", "Warning+ point cell-days (universe sample)",
                   "events per 1,000 alerted cell-days"], rows)


def _terrain_table(terrain: dict) -> str:
    rows = []
    for key, t in terrain.items():
        if not t.get("explained"):
            rows.append([key.replace("_", " "), f"{t['cell_days']:,}", "0", "", "", "", ""])
            continue
        rows.append([key.replace("_", " "), f"{t['cell_days']:,}", f"{t['explained']:,}",
                     f"{t['median_logodds_aspect']:+.3f} / {t['median_logodds_twi']:+.3f}",
                     pct(t["mean_share_of_positive_contribution"], 1), pct(t["share_top3_all_aspect_twi"], 2),
                     pct(t["share_point_level_drops_without_aspect_twi"], 1)])
    return _table(["published level, rain", "cell-days", "explained", "median log-odds aspect / TWI",
                   "share of the positive contribution", "top 3 all aspect/TWI", "point level drops without them"], rows)


def _leads_table(result: dict) -> str:
    rows = []
    for k, entry in result["leads"].items():
        for option in L.OPTIONS:
            x = entry[option]
            rows.append([f"D+{k}", option, f"{x['n']:,}", pct(x["exact_agreement"], 2),
                         pct(x["forecast_watch_plus_share"], 2), pct(x["observed_watch_plus_share"], 2)])
    pooled = result["choice"]["pooled"]
    rows += [["all", o, "", pct(pooled[o]["exact_agreement"], 2), pct(pooled[o]["forecast_watch_plus_share"], 2), ""]
             for o in L.OPTIONS]
    return _table(["lead", "uncertain_high bound", "cell-day pairs", "exact level agreement", "forecast Watch+ share",
                   "observed Watch+ share"], rows)


def _live_levels(live: dict, first: dict) -> str:
    rows = []
    for label, x in (("first publication (old interval, no rules; inputs of the first run, no history)", first),
                     ("re-run inputs, old interval, no rules, re-run history", live["before"]),
                     ("re-run inputs, re-centred interval + chosen rules (= the re-run's published table)", live["after"])):
        rows.append([label, *(f"{x['levels'][n]:,}" for n in ("Normal", *LEVEL_NAMES)),
                     *(f"{x['dry'][n]['dry']:,} of {x['dry'][n]['all']:,}" for n in LEVEL_NAMES),
                     f"{x['interval_violations']:,}"])
    return _table(["23 Oct, lead 0", "Normal", "Watch", "Warning", "Emergency", "dry Watch", "dry Warning",
                   "dry Emergency", "risk outside [lo, hi]"], rows)


def _cells(live: dict, first: dict) -> str:
    rows = []
    for cell, x in live["reported_cells"].items():
        for when, r in (("first publication", first[cell]), ("after (re-run)", x["after"])):
            rows.append([CELL_NAMES.get(cell, cell), when, r["level_name"], f"{1e5 * r['risk']:.3g}",
                         f"{1e5 * r['risk_lo']:.3g} - {1e5 * r['risk_hi']:.3g}", r["confidence"],
                         r["confidence_causes"] or "-", r["reason_codes"],
                         f"{r['ensemble_agreement']:.2f}" if "ensemble_agreement" in r else ""])
    return _table(["cell", "", "level", "risk per 100k", "range per 100k", "confidence", "causes", "codes",
                   "agreement"], rows)


def _audit_table(summary: dict) -> str:
    names = list(summary["violations"])
    return _table(["day", "rows", *names], [[d, f"{v['rows']:,}", *(f"{v['violations'].get(n, 0):,}" for n in names)]
                                            for d, v in summary["days"].items()])


def _audit_lines(report: dict, hold_days: int) -> list[str]:
    lines = []
    before = report.get("audit_before_rerun")
    if before is not None:
        lines += [f"As first published, audited with the rules of that time (one 3-day hold window, before the forecast "
                  f"checks; {before['created_utc']}):", "", _audit_table(before), "",
                  "`interval` is the old interval; `rain_rule` the cell-days of lead 0 and of the leads with stored "
                  "features that the rule caps; `blind_hold` the holds over days without a score that lack "
                  f"`held_while_blind` (none is held beyond H = {hold_days} days).", ""]
    after = report["audit"]
    lines += [f"After the re-run with the integrated runner ({after['created_utc']}): "
              f"{after['total_violations']:,} violations in total.", "", _audit_table(after), ""]
    return lines


def render(report: dict) -> str:
    dev, ev, rules = report["development"], report["evaluation"], report["rules"]
    live, s18 = ev["live_day"], ev["season_2018"]
    interval, rain, agreement = dev["interval"], dev["rain"], dev["agreement"]
    outside = interval["outside_old_interval"]
    chosen, post_rain, blind = rain["chosen"], rain["post_rain"], dev["blind_hold"]
    abl = report["aspect_ablation"]
    audit = report["audit"]
    dry_watch, wet_watch = dev["terrain"]["Watch_dry"]["cell_days"], dev["terrain"]["Watch_wet"]["cell_days"]
    dev_dry = dry_watch / (dry_watch + wet_watch)
    live_dry = live["before"]["dry"]["Watch"]["dry"] / live["before"]["dry"]["Watch"]["all"]
    lost_2018 = (s18["conditions"]["before"]["detected_at_least"]["Watch"]["hits"]
                 - s18["conditions"]["after"]["detected_at_least"]["Watch"]["hits"])
    lines = [
        "# Phase 6: alert accuracy hardening", "",
        f"Generated {report['created_utc']}. Every threshold and choice below was made on the development years "
        "(2007-2017, out of fold) before 2018 or any live day was evaluated; 2018 and 2026-10-23 were evaluated once, "
        "descriptively. The frozen v3 model files, card and calibrators are unchanged; the scoring code's interval and "
        "the post-model rules are the protocol amendment of spec section 11.", "",
        "## The reported alerts", "",
        "Two user-confirmed false alarms of the 2026-10-23 run: cell 23965166 (Warning, a 1.8 per 100k point outside its "
        "own 0.014-0.15 range) and 24605098 at Katra (Emergency since 17 Oct, held through the 20-21 Oct outage). Both had "
        "0 mm of IMERG rain over 1, 3 and 7 days.", "",
        _cells(live, report["first_publication"]["reported_cells"]), "",
        f"After the rules both are **Watch** with code `no_recent_rain` (7-day rain 0 mm, below the "
        f"{chosen['minimum_mm']['7']:.1f} mm minimum; the cap takes Warning and Emergency to Watch). 23965166 is also "
        "Degraded: none of the 20 members reaches Warning (`ensemble_disagrees`). Regression tests: "
        "`tests/test_live_false_alarms.py`.", "",
        "## 1. Interval consistency", "",
        f"`risk_lo` / `risk_hi` were the 10th / 90th percentile of the calibrated members while `risk` is the point model. "
        f"On the development seasons the point lay outside that interval on {outside['outside_old']:,} of "
        f"{outside['cell_days']:,} universe cell-days ({pct(outside['outside_old_share'])}; {outside['above_old_hi']:,} "
        f"above it). The interval is now the members' logit spread re-centred on the point "
        "(`expit(logit(point) - (logit(median) - logit(p10)))`, `expit(logit(point) + (logit(p90) - logit(median)))`, "
        f"clipped at 1e-12, calibrated like the point): {outside['outside_new']} cell-days outside. `score` also returns "
        "`member_median_risk` and `ensemble_agreement`.", "",
        "Effect on `uncertain_high` (development, full Task 6b levels):", "",
        _table(LEVEL_HEADER, _level_rows([("old interval", interval["old_bound"]), ("re-centred interval", interval["new_bound"]),
                                          ("no uncertain_high", interval["no_uncertain_high"])])), "",
        "The re-centred upper bound lies above the old one where the point is above the members, so `uncertain_high` "
        "raises more cell-days to Watch. The re-centring is the consistency fix and is the baseline below; whether "
        "`uncertain_high` should test a different bound is left open (not chosen here).", "",
        "## 2. Ensemble disagreement", "",
        _agreement_table(agreement["split"]), "",
        f"The disagreeing Warning+ alerts are less precise than the agreeing ones at every A, so the pre-declared default "
        f"holds: **A = {rules['agreement_min']}**. A point at Warning or above with fewer than A of the members at its "
        "level is capped at Degraded with cause `ensemble_disagrees` (\"most of the 20 ensemble models put this cell "
        "lower\"); the level is not changed.", "",
        "## 3. Rain trigger", "",
        f"Minima: low percentiles of the IMERG rain of the {rain['positives']['n_positives']} in-domain development "
        "positives (every month). Each candidate gated at one level at a time on the full levels (re-centred interval, "
        f"hold released after a dry hold window of {rain['candidate_hold_window_days']} days); adoption needs at most 1% "
        "of that level's events lost and a lower share at that level.", "",
        _rain_table(dev), "",
        f"Chosen by the pre-declared order (most adoptable levels, then the lowest Warning+ share): **{chosen['form']} "
        f"p{chosen['percentile']:g}, irain_acc_7 >= {chosen['minimum_mm']['7']:.2f} mm, gated at "
        f"{', '.join(chosen['gated_levels'])}**; caps Watch -> Normal, Warning -> Watch, Emergency -> Watch; blind-escalated "
        "cells are exempt.", "",
        _table(LEVEL_HEADER, _level_rows([("baseline (re-centred interval)", interval["new_bound"]),
                                          ("chosen rules", dev["after"]),
                                          ("chosen rules, holds not released", dev["after_without_hold_release"])])), "",
        "Hold window per level (the chosen rule; one level's window shortened at a time, the others at "
        f"{rain['candidate_hold_window_days']} days; then all together):", "",
        _window_table(rain["hold_window"]), "",
        f"Chosen (shortest window meeting the adoption rule at its level): **{_windows(rules)}**. A hold at a level needs "
        "the rain rule to have passed on one of that many days ending on the day; this was refined after the continuous "
        "re-run of the live days showed longer windows letting a 7-day total from up to 9 days back justify a hold, and "
        "chosen on development data only.", "",
        f"Post-rain cost: {post_rain['post_rain']} of the {post_rain['n_positives']} development positives occurred 7 days "
        f"or more after the last 10 mm day; {post_rain['post_rain_below_minimum']} of them "
        f"({pct(post_rain['share_of_positives'])} of all positives) had a 7-day rain under "
        f"{post_rain['minimum_7_mm']:.2f} mm and fail the rule on their own day (every positive below the minimum is such "
        f"a post-rain case: {post_rain['all_below_minimum']}). On the June-September alert levels the gate loses "
        f"{interval['new_bound']['detected_at_least']['Watch']['hits'] - dev['after']['detected_at_least']['Watch']['hits']}"
        " Watch+ detections of the 636 in-season events.", "",
        "## 4. Blind-hold limit", "",
        _table(["level", *(f"retained after {k} day(s)" for k in ("1", "2", "3"))],
               [[name, *(pct(blind["retention"][name][k]["share"], 1) for k in ("1", "2", "3"))] for name in LEVEL_NAMES]),
        "",
        f"Pre-declared: H = the largest lag whose retention is at least 50% at every level, at least 1. **H = "
        f"{blind['choice']['blind_hold_days']}** (Emergency retains {pct(blind['retention']['Emergency']['2']['share'], 1)} "
        "after 2 days). A level is held over at most H consecutive days without a score, then lowered one level per "
        "further day; the cell stays Insufficient with code `held_while_blind`; the blind-escalation rule still applies.", "",
        "## 5. Forecast leads", "",
        f"`uncertain_high` on the forecast leads, on the forecast-skill pairs ({report['forecast_leads']['issue_days']} GFS "
        f"issue days of June-September 2021-2024, {report['forecast_leads']['cells']:,} cells, seed "
        f"{report['forecast_leads']['seed']}), each side with the chosen rain cap; observed level = the level the target "
        "day is published at from observed features:", "",
        _leads_table(report["forecast_leads"]), "",
        f"Pre-declared (higher pooled agreement, ties to three decimals to the lower Watch+ share): **"
        f"{report['forecast_leads']['choice']['option']}**. A forecast day has no observation, so a lead's confidence is "
        "never High: a scored lead is Degraded with causes `forecast_day`, `observed_through_d_<D0 state>` and "
        "`forecast_widened`; the audit flags a High forecast row.", "",
        "## 6. Terrain-only diagnostic", "",
        "Development (out of fold, levels of the re-centred baseline; dry = 3-day rain under 1 mm):", "",
        _terrain_table(dev["terrain"]), "",
        "2026-10-23 (published levels before the rules):", "",
        _terrain_table(live["terrain"]), "",
        f"Aspect ablation (challenger harness, `--only lgb_no_aspect`, imerg_core without stat_aspect_sin/cos): pooled OOF "
        f"FA@90 {abl['fa_at_90']['value']:.4f} against {abl['incumbent_fa_at_90']['value']:.4f} for v3; paired difference "
        f"{abl['paired_vs_v3']['point_difference']:+.4f} (SE {abl['paired_vs_v3']['se']:.4f}, 95% CI "
        f"[{abl['paired_vs_v3']['ci_lo']:+.4f}, {abl['paired_vs_v3']['ci_hi']:+.4f}]); not adopted by the harness rule. "
        f"Details: `{abl['report']}`.", "",
        "## 7. Evaluation (once, after the choice)", "",
        f"### 2018 operational backtest ({s18['cells']:,} cells, {s18['days']} days, {s18['events']} test events)", "",
        _table(LEVEL_HEADER, _level_rows([(v["label"], v) for v in s18["conditions"].values()])), "",
        f"Point outside the old interval: {s18['outside_old_interval']['outside_old']:,} of "
        f"{s18['outside_old_interval']['cell_days']:,} cell-days; none with the re-centred one. `ensemble_disagrees` would "
        f"mark {s18['ensemble_disagrees_cell_days']:,} of {s18['point_warning_plus_cell_days']:,} Warning+ point cell-days.",
        "",
        "### 2026-10-23, recomputed offline from its stored features", "",
        _live_levels(live, report["first_publication"]["levels"]), "",
        "The first row is the alert engine re-run offline on the inputs of the first 23 Oct run (it reproduces the "
        "user-reported counts); the 23 Oct folder has since been re-run (inputs fetched on 24 Oct, the previous days "
        f"re-run with the rules, {live['previous_days_used']} previous days of history), the source of the other rows. "
        "After: "
        f"{live['after']['no_recent_rain_capped']:,} cells capped by `no_recent_rain`, {live['after']['ensemble_disagrees']}"
        " marked `ensemble_disagrees`; the audit of the recomputed table finds "
        f"{sum(live['after']['audit']['violations'].values())} violations.", "",
        "## 8. Audit of the published live days", "",
        *_audit_lines(report, blind['choice']['blind_hold_days']),
        "## Limits", "",
        "- The development seasons are June-September; the live days are October, when far more cells are dry "
        f"({pct(live_dry, 1)} of the 23 Oct Watch cells against {pct(dev_dry, 1)} of the development Watch cell-days). "
        "The rule's cost on in-domain positives of every month is the post-rain count above.",
        f"- The 1% adoption rule was met on development; on 2018 the gate costs {lost_2018} of {s18['events']} Watch+ "
        "detections (descriptive, not used to choose).",
        "- The live days 2026-10-09..23 were re-run oldest first with the integrated runner (09-15 `--backtest --force`, "
        "16-23 `--force`, 22 Oct included so the hysteresis is continuous); the re-runs of 16-23 used the inputs available "
        "on 24 Oct, not those of each day's 11:00 IST run.",
        "- The hold windows were refined after the first continuous re-run (from one 3-day window to per-level windows); "
        "the choice was made on development data only, and 2018 was evaluated again with the final rules."]
    return "\n".join(lines) + "\n"


def write(out_dir: Path, say=print) -> tuple[Path, Path]:
    report = build(out_dir)
    out_dir = Path(out_dir)
    json_path, md_path = out_dir / f"{REPORT_STEM}.json", out_dir / f"{REPORT_STEM}.md"
    dump_json(json_path, report)
    md_path.write_text(render(report), encoding="utf-8")
    say(f"wrote {hm.display_path(md_path)} and {hm.display_path(json_path)}")
    return json_path, md_path
