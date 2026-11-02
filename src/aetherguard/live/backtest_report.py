"""Reports of the operational backtest: `reports/phase6_backtest.{md,json}` (the JSON is the source of truth)."""
from __future__ import annotations

import json
from pathlib import Path

from ..hazard.jsonio import dump_json
from ..hazard.tables import _num, _table

VARIANT_LABELS = {"operational": "operational (live inputs)", "training_style": "training-style (Late only)"}
RULE_LABELS = {"raw_watch": "model Watch rule (raw score)", "engine": "alert levels (risk, hysteresis)"}
SET_TITLES = {"season_2018": "2018 monsoon season (1 Jun - 30 Sep), universe cells, test_2018 positives",
              "window_2023": "2023 India window (16 Jun - 31 Jul), window cells",
              "kerala_2018": "Kerala 2018 case (1 - 20 Aug), western-ghats universe cells",
              "wayanad_2024": "Wayanad 2024 case (15 Jul - 5 Aug), box cells"}
REPORT_STEM = "phase6_backtest"


def pct(d: dict | None, digits: int = 1) -> str:
    if not d or d.get("value") is None:
        return "n/a"
    return f"{100 * d['value']:.{digits}f}% [{100 * d['lo']:.{digits}f}, {100 * d['hi']:.{digits}f}]"


def share(value) -> str:
    return "n/a" if value is None else f"{100 * value:.2f}%"


def _events_rows(result: dict, mode: str) -> list[list[str]]:
    rows = []
    for rule in ("raw_watch", "engine"):
        for variant in ("operational", "training_style"):
            entry = result["variants"][variant][mode][rule]
            events = entry.get("events")
            if not events or not events["n_events"]:
                continue
            own, foot = events["own"], events["footprint"]
            rows.append([RULE_LABELS[rule], VARIANT_LABELS[variant], str(events["n_events"]), str(events["n_scored"]),
                         pct(own["detected_of_all_events"]), pct(own["detected_of_scored_events"]),
                         pct(foot["detected_of_all_events"]), pct(own["detected_within_7d"]),
                         _num(own["median_lead_days"], 1), share(entry["chance_watch_within_7d"])])
    return rows


def _share_rows(result: dict, mode: str) -> list[list[str]]:
    rows = []
    for rule in ("raw_watch", "engine"):
        for variant in ("operational", "training_style"):
            entry = result["variants"][variant][mode][rule]
            summary = entry["alert_share_watch_plus"]
            mean = summary["mean_daily_share"]
            ci = "n/a" if mean["value"] is None else (f"{100 * mean['value']:.2f}% "
                                                    f"[{100 * mean['lo']:.2f}, {100 * mean['hi']:.2f}]")
            regions = ", ".join(f"{r} {share(v)}" for r, v in entry["alert_share_by_region"].items())
            extra = ""
            if rule == "engine":
                extra = (f"Warning+ {share(entry['alert_share_warning_plus']['mean_daily_share']['value'])}, "
                         f"Emergency {share(entry['alert_share_emergency']['mean_daily_share']['value'])}")
            rows.append([RULE_LABELS[rule], VARIANT_LABELS[variant], ci, share(summary["median_daily_share"]),
                         share(summary["max_daily_share"]), regions, extra or "-"])
    return rows


def _gap_rows(result: dict, mode: str) -> list[list[str]]:
    rows = []
    for rule in ("raw_watch", "engine"):
        gap = result["gap"]["modes"][mode][rule]
        diff = gap["alert_share_difference"]
        paired = gap.get("paired_events_own")
        rows.append([RULE_LABELS[rule],
                     "n/a" if diff["value"] is None else (f"{100 * diff['value']:+.2f} points [{100 * diff['lo']:+.2f}, "
                                                          f"{100 * diff['hi']:+.2f}]"),
                     "n/a" if gap["watch_set_agreement_jaccard"] is None else f"{gap['watch_set_agreement_jaccard']:.3f}",
                     "-" if not paired else (f"both {paired['both']}, only operational {paired['only_operational']}, only "
                                             f"training-style {paired['only_training_style']}, neither {paired['neither']}")])
    return rows


def _inputs_section(result: dict) -> list[str]:
    inputs = result["inputs"]
    tails = ", ".join(f"{k} {v}" for k, v in sorted(inputs["tail_products"].items()))
    early = ", ".join(f"{k} {v}" for k, v in sorted(inputs["utc_d-1_products"].items()))
    return [f"Input products over {inputs['days']} days: 00-03 UTC tail of IMD day D: {tails}; UTC D-1: {early}. "
            f"`persist_d1` share: {100 * inputs['persist_d1_share']:.1f}% of days "
            f"({inputs['persist_d1_days']}/{inputs['days']}). Days with no operational score at all: "
            f"{inputs['days_without_operational_scores']}; with no training-style score: "
            f"{inputs['days_without_training_style_scores']}.", ""]


def _window_rows(result: dict, mode: str) -> list[list[str]]:
    rows = []
    for rule in ("raw_watch", "engine"):
        for variant in ("operational", "training_style"):
            w = result["variants"][variant][mode][rule].get("window_test")
            if w is None:
                continue
            rows.append([RULE_LABELS[rule], VARIANT_LABELS[variant], f"{w['detection']['hits']}/{w['detection']['n']}",
                         pct(w["detection"]), f"{w['control_any_alert']['hits']}/{w['control_any_alert']['n']}",
                         pct(w["control_any_alert"]), f"{100 * w['control_cell_day_alert_share']:.1f}%"])
    return rows


def _event_detail(result: dict, mode: str) -> list[str]:
    out = []
    ops = result["variants"]["operational"][mode]["engine"].get("event_table")
    train = result["variants"]["training_style"][mode]["engine"].get("event_table")
    if not ops:
        return out
    rows = []
    for a, b in zip(ops, train):
        rows.append([str(a["cell_id"]), a["date"], str(a["scored"]),
                     "yes" if a["own_detected"] else "no", _num(a["own_lead_days"], 0),
                     "yes" if a["footprint_detected"] else "no",
                     "yes" if b["own_detected"] else "no", _num(b["own_lead_days"], 0),
                     "yes" if b["footprint_detected"] else "no"])
    out += ["Events (alert levels with hysteresis; lead = days from the first Watch+ day within the 7 days up to the event "
            "day, 0 = first alert on the day):", "",
            _table(["cell", "date", "scored (operational)", "operational: own cell", "lead", "operational: 3x3",
                    "training-style: own cell", "lead", "training-style: 3x3"], rows), ""]
    return out


def _series_rows(result: dict, mode: str) -> list[list[str]]:
    rows = []
    for variant in ("operational", "training_style"):
        series = result["variants"][variant][mode]["engine"]["series"]["metrics"]
        rows.append([VARIANT_LABELS[variant], str(series["first_watch_plus"]["focus"]),
                     str(series["first_watch_plus"]["within_10km"]), str(series["first_watch_plus"]["box"]),
                     str(series["first_warning_plus"]["focus"]), str(series["first_warning_plus"]["within_10km"]),
                     _num(series["peak_near_risk"] * 1e5, 2), str(series["peak_near_date"])])
    return rows


def _set_section(name: str, result: dict) -> list[str]:
    title = SET_TITLES.get(name, name)
    out = [f"## {title}", "", f"{result['note']}. {result['n_cells']:,} cells ({', '.join(f'{k} {v:,}' for k, v in result['cells_by_region'].items())}), "
           f"{result['n_days']} days from {result['start']}, {result['warmup_days']} warm-up days scored before it for the "
           f"hysteresis state; ran in {result['seconds']:.0f} s.", ""]
    out += _inputs_section(result)
    mode = "region"
    if any(result["variants"]["operational"][mode][r].get("events") for r in ("raw_watch", "engine")):
        out += ["### Detection of the labelled events", "",
                _table(["rule", "features", "events", "scored", "own cell, of all events [95% CI]",
                        "own cell, of scored events", "3x3 footprint, of all events", "Watch+ within 7 days up to the event",
                        "median lead (days)", "chance rate: any scored cell Watch+ within 7 days"],
                       _events_rows(result, mode)), "",
                "The lead time saturates at 7 days whenever the alert share is high. The last column is the share of all scored "
                "cell-days with a Watch+ day among the 7 days before and the day itself, i.e. what an event cell would show by "
                "luck; a lead or a 7-day detection is informative only against that rate.", ""]
        out += _event_detail(result, mode) if name != "season_2018" else []
    if name == "window_2023":
        out += ["### Window test (maximum over the window days of the 3x3 neighbourhood of each window-positive cell)", "",
                _table(["rule", "features", "detected", "detection share [95% CI]", "controls alerted",
                        "control any-alert share [95% CI]", "control cell-days alerted"], _window_rows(result, mode)), ""]
    if name == "wayanad_2024":
        out += ["### Focus-cell series (first Watch+ / Warning+ day; the landslide was on 30 July 2024)", "",
                _table(["features", "Watch+ focus", "Watch+ within 10 km", "Watch+ box", "Warning+ focus",
                        "Warning+ within 10 km", "peak risk within 10 km (per 100k)", "peak date"], _series_rows(result, mode)), ""]
    out += ["### Share of scored cell-days at Watch or above (mean over days, bootstrap over days)", "",
            _table(["rule", "features", "mean daily share [95% CI]", "median", "max", "by region", "levels"],
                   _share_rows(result, mode)), "",
            "### The train/live gap (operational minus training-style, same cells and days)", "",
            _table(["rule", "change in the daily alert share", "Watch+ set overlap (Jaccard, mean over days)", "events"],
                   _gap_rows(result, mode)), "",
            f"Mean absolute difference of the features: 1-day rain {_num(result['gap']['mean_abs_diff_irain_acc_1_mm'], 2)} mm, "
            f"3-day rain {_num(result['gap']['mean_abs_diff_irain_acc_3_mm'], 2)} mm. Rank correlation of the raw scores of "
            f"the two variants over the same cells: mean {_num(result['gap']['raw_rank_correlation']['mean'], 4)}, worst day "
            f"{_num(result['gap']['raw_rank_correlation']['min'], 4)}.", ""]
    p_ops = result["variants"]["operational"]["pooled"]["engine"]
    r_ops = result["variants"]["operational"]["region"]["engine"]
    out += ["Alert levels with the pooled risk thresholds, as `live/run.py` applies them today (region-calibrated risk "
            "against the pooled card thresholds), against the region thresholds above: operational Watch+ share "
            f"{share(p_ops['alert_share_watch_plus']['mean_daily_share']['value'])} (pooled) versus "
            f"{share(r_ops['alert_share_watch_plus']['mean_daily_share']['value'])} (region).", ""]
    if p_ops.get("events") and p_ops["events"]["n_events"]:
        out += [f"Event detection, own cell: {pct(p_ops['events']['own']['detected_of_all_events'])} (pooled) versus "
                f"{pct(r_ops['events']['own']['detected_of_all_events'])} (region).", ""]
    return out


def render_markdown(results: dict, meta: dict) -> str:
    out = ["# Phase 6 operational backtest of the v3-live model", "",
           f"Generated {meta['created_utc']} with the frozen model in `{meta['model_dir']}` (card sha256 "
           f"`{meta['model_card_sha256'][:16]}`). For every day of each window the same frozen model is scored twice on "
           "the same cells: with the features the 11:00 IST live run would have had (Late through UTC D-2, Early for "
           "UTC D-1, the GFS or persisted 00-03 UTC tail, nothing issued after the cut-off) and with the training-style "
           "features (Late run for every UTC day including all of UTC D). The difference is the **train/live gap** that "
           "the spec section 10 substitutions cause. Local stores only: no network was used.", "",
           "Reading guide. *Model Watch rule*: raw score at or above the frozen recall-first threshold, the rule of the "
           "test_2018 evaluation. *Alert levels*: calibrated risk against each region's card thresholds, the "
           "`uncertain_high` rule and the hysteresis of the live state, run over consecutive days; the alert engine's "
           "source-agreement, gauge and blind-escalation rules are not applied (no IMD real-time archive or gauge history "
           "is on disk). Events are the labelled cell-days; a cell-day without a score (an input day missing from the "
           "local stores) counts as a miss in the 'of all events' column and is dropped in the 'of scored events' column. "
           "Intervals are 95% percentile bootstraps (events resampled, or days resampled for shares).", ""]
    if meta.get("test_reference"):
        ref = meta["test_reference"]
        out += [f"Reference, test_2018 evaluation (training-style inputs, whole year, `reports/phase6_live_model_report.md`): "
                f"detection {pct(ref['test_recall'])}, share of cell-days on alert {pct(ref['test_fa_share'])}. "
                "The backtest covers the monsoon season only, so its alert share is not the annual one.", ""]
    out += ["## Summary", ""]
    rows = []
    for name, result in results.items():
        for rule in ("raw_watch", "engine"):
            ops = result["variants"]["operational"]["region"][rule]
            train = result["variants"]["training_style"]["region"][rule]
            det = ["-", "-"]
            if ops.get("events") and ops["events"]["n_events"]:
                det = [pct(ops["events"]["own"]["detected_of_all_events"], 0),
                       pct(train["events"]["own"]["detected_of_all_events"], 0)]
            rows.append([name, RULE_LABELS[rule], det[0], det[1],
                         share(ops["alert_share_watch_plus"]["mean_daily_share"]["value"]),
                         share(train["alert_share_watch_plus"]["mean_daily_share"]["value"]),
                         f"{100 * result['inputs']['persist_d1_share']:.0f}%"])
    out += [_table(["set", "rule", "detection, operational (own cell)", "detection, training-style",
                    "alert share, operational", "alert share, training-style", "persist_d1 days"], rows), ""]
    for name, result in results.items():
        out += _set_section(name, result)
    out += ["## Limits", "",
            "- The GFS archive on disk covers 2021-2024 June-September 00Z cycles only. 2018 therefore has no GFS tail at all: "
            "every 2018 day uses `persist_d1` (the 00-03 UTC rain of day D taken as the rain of UTC D-1), the most pessimistic "
            "link of the live fallback chain. The 2023 and 2024 windows use the real 00Z 0-3 h accumulation. The 18Z and 12Z "
            "fall-back cycles are not in the local archive.",
            "- The Early run is used as it is (identity map; the fitted map did not improve the held-out 2018 season). "
            "A day whose Early granule for UTC D-1 is not stored has no operational score.",
            "- The candidate cells are the universe cells of the hazard evaluation (own terrain, slope at or above the frozen "
            "floor), not every scored cell of the live runner.",
            "- Event counts are small (80 test_2018 positives; of them those inside the window), so every detection interval "
            "is wide, and the 2023 window and Kerala/Wayanad cases are qualitative. 2018 is the year v2 and v3-live were both "
            "tested on: this backtest is a further, descriptive view of the same frozen model on that test year, with nothing "
            "tuned on it.",
            "- Labels are partial: alerts on cells without a recorded landslide are counted as alert share, not as errors.", ""]
    return "\n".join(out)


def write_reports(results: dict, meta: dict, out_dir: Path, stem: str = REPORT_STEM) -> tuple[Path, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path, md_path = out_dir / f"{stem}.json", out_dir / f"{stem}.md"
    dump_json(json_path, {"schema": 1, **meta, "sets": results})
    md_path.write_text(render_markdown(results, meta), encoding="utf-8")
    return json_path, md_path


def load_test_reference(reports_dir: Path) -> dict | None:
    """The test_2018 recall and alert share of the v3-live evaluation report, when it exists."""
    path = Path(reports_dir) / "phase6_live_model_report.json"
    if not path.is_file():
        return None
    target = json.loads(path.read_text(encoding="utf-8"))["gate"]["recall_first_target"]
    return {"test_recall": target["test_recall"], "test_fa_share": target["test_fa_share"]}
