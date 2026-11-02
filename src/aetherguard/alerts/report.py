"""Phase 4 alerts report from a replay store.

    python -m aetherguard.alerts.report [--store DIR] [--stem phase4_alerts_report] [--reports-dir DIR]

Writes `<reports-dir>/<stem>.json` and `.md`: per replayed set the event detection with lead time (Watch+ within
`evaluation.lead_days` days before and including the event day), alerted area per day, flapping with and without
hysteresis, blind escalations and how many coincide with events, and for the test_2018 universe the alerts per 1000
cell-days, recall per level and the cost-loss table. A store built from a model that is not the frozen one carries a
`provisional` label in its manifest; its report is labelled provisional and may not be written under the final stem.
"""
from __future__ import annotations

import argparse
import math
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ..cases import series as cases
from ..config import PROJECT_ROOT
from ..hazard.jsonio import dump_json
from . import evaluate as ev
from . import levels as lv
from .config import alerts_settings
from .store import ReplayStore

FINAL_STEM = "phase4_alerts_report"
TEST_UNIVERSE, TEST_SAMPLES = "universe_test_2018", "test_2018_samples"
WINDOW, KERALA, WAYANAD = "window_2023_samples", "case_kerala_2018_samples", "case_wayanad_2024_samples"
DISASTER_DAY = "2024-07-30"
WAYANAD_POINT = (11.47, 76.13)      # Mundakkai, the focus point of the case-input tables


def _events(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.loc[frame["is_positive_cell_day"].astype(bool), ["cell_id", "date"]]


def _test_2018(store: ReplayStore, thresholds: lv.Thresholds, settings: dict) -> dict:
    universe = store.read_set(TEST_UNIVERSE)
    samples = store.read_set(TEST_SAMPLES)
    positives = samples[samples["kind"] == "positive"]
    in_domain = positives[positives["in_domain"].astype(bool)]
    events = in_domain[["cell_id", "date"]]
    _, detection = ev.event_detection(samples, events, settings["evaluation"]["lead_days"])
    return {
        "universe_set": TEST_UNIVERSE, "samples_set": TEST_SAMPLES,
        "operating_view": ev.universe_operating_view(universe, in_domain, int(len(positives) - len(in_domain)),
                                                    thresholds, settings["cost_loss"]["ratios"]),
        "layers": ev.universe_layer_view(universe, in_domain, int(len(positives) - len(in_domain)), thresholds),
        "universe_risk_max": float(universe["risk"].max()),
        "confidence_causes_universe": ev.cause_counts(universe),
        "event_detection_same_day": detection,
        "level_and_confidence_mix_universe": ev.level_mix(universe, universe["weight"]),
        "blind_escalations_universe": ev.blind_escalations(universe, events, settings["evaluation"]["lead_days"]),
        "positives_blind_escalated": int(in_domain["blind_escalated"].sum()),
        "note": "the sample files hold the event day only, so lead time is 0 by construction; "
                "the universe rows are random cell-days (not consecutive), so flapping and area per day do not apply"}


def _window(store: ReplayStore, thresholds: lv.Thresholds, settings: dict) -> dict:
    alerts = store.read_set(WINDOW)
    positive = alerts.loc[alerts["is_window_positive_cell"].astype(bool), "cell_id"].unique()
    lead = settings["evaluation"]["lead_days"]
    escalated = alerts[alerts["blind_escalated"]]
    return {
        "set": WINDOW, "window": [alerts["date"].min().strftime("%Y-%m-%d"), alerts["date"].max().strftime("%Y-%m-%d")],
        "window_detection": ev.window_detection(alerts, positive, alerts["date"].min(), alerts["date"].max()),
        "alerted_area_sampled_cells": ev.alerted_area(alerts),
        "flapping": ev.flapping_comparison(alerts, settings["evaluation"]["flap_window_days"]),
        "blind_escalations": {**ev.blind_escalations(alerts, None, lead),
                              "n_escalated_in_positive_cells": int(escalated["cell_id"].isin(positive).sum())},
        "level_and_confidence_mix": ev.level_mix(alerts), "layers": ev.layer_shares(alerts, thresholds),
        "confidence_causes": ev.cause_counts(alerts),
        "note": "window events have no dates, so detection is window-level; the table holds the sampled cells "
                "(positive cells and controls), so area is the sampled share, not a region total"}


def _case(store: ReplayStore, name: str, thresholds: lv.Thresholds, settings: dict, labelled: bool) -> dict:
    alerts = store.read_set(name)
    lead = settings["evaluation"]["lead_days"]
    events = _events(alerts) if labelled else None
    out = {"set": name, "n_cells": int(alerts["cell_id"].nunique()),
           "dates": [alerts["date"].min().strftime("%Y-%m-%d"), alerts["date"].max().strftime("%Y-%m-%d")],
           "alerted_area": ev.alerted_area(alerts),
           "flapping": ev.flapping_comparison(alerts, settings["evaluation"]["flap_window_days"]),
           "blind_escalations": ev.blind_escalations(alerts, events, lead),
           "level_and_confidence_mix": ev.level_mix(alerts), "layers": ev.layer_shares(alerts, thresholds),
           "confidence_causes": ev.cause_counts(alerts)}
    if name == WAYANAD:
        cell, distance = cases.focus_cell(alerts, *WAYANAD_POINT)
        out["saturation"] = {"focus_cell": cell, "focus_distance_km": distance, **ev.saturation(
            alerts[alerts["cell_id"] == cell], ev.emergency_share_by_day(alerts))}
    if labelled:
        per_event, summary = ev.event_detection(alerts, events, lead)
        out["event_detection"] = summary
        out["events"] = [{"cell_id": int(r.cell_id), "date": r.date.strftime("%Y-%m-%d"), "detected": bool(r.detected),
                          "lead_days": None if pd.isna(r.lead_days) else int(r.lead_days),
                          "days_available": int(r.days_available)} for r in per_event.itertuples()]
    else:
        out["note"] = "no landslide label exists for this case (no NASA record), so no detection statistics"
    return out


def build_report(store: ReplayStore) -> dict:
    settings = alerts_settings()
    manifest = store.manifest
    thresholds = lv.Thresholds(**{k: manifest["thresholds"][k] for k in ("watch", "warning", "emergency", "source")})
    sets = set(store.sets())
    report = {"created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "provisional": manifest.get("provisional"), "thresholds": thresholds.to_dict(),
              "model": manifest.get("model"), "freeze": manifest.get("freeze"), "alert_config": manifest.get("alert_config", {}).get("parameters"),
              "store_created_utc": manifest.get("created_utc"), "evaluation": settings["evaluation"], "sections": {}}
    if {TEST_UNIVERSE, TEST_SAMPLES} <= sets:
        report["sections"]["test_2018"] = _test_2018(store, thresholds, settings)
    if WINDOW in sets:
        report["sections"]["window_2023"] = _window(store, thresholds, settings)
    if KERALA in sets:
        report["sections"]["kerala_2018"] = _case(store, KERALA, thresholds, settings, labelled=True)
    if WAYANAD in sets:
        report["sections"]["wayanad_2024"] = _case(store, WAYANAD, thresholds, settings, labelled=False)
    return report


# ------------------------------------------------------------------------------------------------ markdown

def _n(value, digits: int = 3) -> str:
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return "n/a"
    if isinstance(value, int):
        return str(value)
    if value != 0 and abs(value) < 10 ** -digits:
        return f"{value:.2e}"
    return f"{value:.{digits}f}"


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    return (["| " + " | ".join(header) + " |", "|" + "|".join(["---"] * len(header)) + "|"]
            + ["| " + " | ".join(r) + " |" for r in rows] + [""])


def _flapping_rows(flapping: dict) -> list[str]:
    rows = [[label, str(f["cell_days"]), str(f["n_changes"]), _n(f["changes_per_1000_cell_days"], 2), str(f["n_flaps"]),
             _n(f["flaps_per_1000_cell_days"], 2)]
            for label, f in (("with hysteresis", flapping["with_hysteresis"]),
                             ("without hysteresis (raw level)", flapping["without_hysteresis"]))]
    return _table(["level used", "cell-days", "level changes", "per 1000", "flaps", "per 1000"], rows)


def _area_rows(area: dict) -> list[str]:
    return _table(["days", "cells/day", "Watch+ share mean", "Watch+ share max", "Warning+ share mean",
                   "Watch+ km2 mean", "Watch+ km2 max", "peak day"],
                  [[str(area["n_days"]), _n(area["cells_per_day_mean"], 0), _n(area["watch_share_mean"], 4),
                    _n(area["watch_share_max"], 4), _n(area["warning_share_mean"], 4), _n(area["watch_km2_mean"], 0),
                    _n(area["watch_km2_max"], 0), area["peak_day"]]])


def _blind_rows(blind: dict) -> list[str]:
    cells = [str(blind["n_cell_days"]), str(blind["n_blind"]), str(blind["n_escalated"]), str(blind["n_cells_escalated"]),
             _n(blind.get("n_coinciding_event")), _n(blind.get("n_events_covered"))]
    header = ["cell-days", "blind-rule applies", "level actually raised", "cells raised", "raised near an event",
              "events covered"]
    if "n_escalated_in_positive_cells" in blind:
        header.append("raised in positive cells")
        cells.append(str(blind["n_escalated_in_positive_cells"]))
    return _table(header, [cells])


def _mix_rows(mix: dict) -> list[str]:
    return _table(["Normal", "Watch", "Warning", "Emergency", "High conf.", "Degraded", "Insufficient"],
                  [[_n(mix["level"][k], 4) for k in lv.LEVEL_NAMES] + [_n(mix["confidence"][k], 4)
                                                                         for k in ("High", "Degraded", "Insufficient")]])


def _layers_rows(shares: dict) -> list[str]:
    """Share of cell-days (unweighted) at each level after each layer."""
    return _table(["level"] + list(ev.LAYERS), [[k] + [_n(v[name], 4) for name in ev.LAYERS] for k, v in shares.items()])


def _causes_line(causes: dict) -> str:
    return ("Confidence limited by (cell-days): " + ", ".join(f"{k} {v}" for k, v in causes.items()) + "."
            if causes else "No cell-day had a confidence cause.")


def _detection_rows(d: dict) -> list[str]:
    return _table(["events", "detected", "rate", "with history", "median lead (d)", "lead >= 1 d", "Watch+", "Warning+",
                   "Emergency"],
                  [[str(d["n_events"]), str(d["n_detected"]), _n(d["detection_rate"]), str(d["n_with_history"]),
                    _n(d["median_lead_days"], 1), str(d["n_lead_at_least_1_day"]),
                    *(str(d["detected_by_level"][k]) for k in ("Watch", "Warning", "Emergency"))]])


def _cost_loss_statement(view: dict, risk_max: float) -> str:
    table = view["cost_loss"]
    points = table["operating_points"]
    ratios = table["ratios"]
    never = all(r["alerts_per_1000_cell_days"] < 0.01 and r["recall"] < 0.01 for r in ratios)
    text = (f"**What this implies.** The event base rate is {_n(view['base_rate'], 6)} per cell-day, so calibrated risks are "
            f"tiny (the largest risk in the test_2018 universe is {_n(risk_max, 2)}). Alerting is cost-justified when "
            f"risk >= C/L, so the Watch, Warning and Emergency thresholds are optimal only if acting costs at most "
            f"{_n(points['watch']['threshold'], 2)}, {_n(points['warning']['threshold'], 2)} and "
            f"{_n(points['emergency']['threshold'], 2)} of the loss it avoids (relative expense "
            f"{_n(points['watch']['relative_expense'], 2)}, {_n(points['warning']['relative_expense'], 2)}, "
            f"{_n(points['emergency']['relative_expense'], 2)}; below 1 beats both never and always alerting). ")
    if never:
        rates = ", ".join(_n(r["alerts_per_1000_cell_days"], 3) for r in ratios)
        text += (f"At C/L = 1/10, 1/50 and 1/200 the cost-optimal rule is effectively never to alert on these data "
                 f"({rates} alerts per 1000 cell-days, recall 0, relative expense about 1): almost no cell-day reaches a "
                 "risk that high, so at those ratios this model supports no alert at all. The alert levels are "
                 "defensible only where acting is very cheap relative to the loss avoided.")
    else:
        text += "At the requested C/L ratios the cost-optimal rule alerts as the table shows."
    return text


def _saturation_markdown(sat: dict) -> list[str]:
    n, e = sat["n_days"], sat["days_at_emergency"]
    where = "on every one of" if e == n else f"on {e} of"
    share = sat.get("emergency_share_all_cells")
    spread = (f"Over all cells the share at Emergency per day averages {_n(share['mean'], 3)} "
              f"(range {_n(share['min'], 3)} to {_n(share['max'], 3)}). " if share else "")
    tie = " (tied)" if len(sat["max_risk_days"]) > 1 else ""
    others = [d for d in sat["max_risk_days"] if d != DISASTER_DAY]
    event = (f" The landslide struck on {DISASTER_DAY}: that day {'shares the maximum with ' + ', '.join(others) if others else 'holds the maximum'}"
             f" (rank {sat['risk_rank_by_day'][DISASTER_DAY]})." if DISASTER_DAY in sat["risk_rank_by_day"] else "")
    lines = ["### Limitation: the alert levels saturate", "",
             f"Focus cell {sat['focus_cell']} (nearest the Mundakkai point, {_n(sat['focus_distance_km'], 1)} km away) is at "
             f"Emergency {where} the {n} days. {spread}The calibrated risk takes {sat['distinct_risk_values']} distinct "
             f"values over the {n} days and its maximum ({_n(sat['max_risk'], 3)}) is reached on "
             f"{', '.join(sat['max_risk_days'])}{tie}.{event}", "",
             "So the level cannot rank the days of this event, and the risk ordering gives no unique top day. This is a reported limitation of the model and the alert levels, not something tuned away: Wayanad "
             "is a never-tuned case study with no label, and no threshold or rule was changed after seeing it.", ""]
    lines += _table(["date", "level", "risk", "risk rank (1 = highest)"],
                    [[d, sat["level_by_day"][d], _n(sat["risk_by_day"][d], 3), str(sat["risk_rank_by_day"][d])]
                     for d in sat["level_by_day"]])
    return lines


def _test_markdown(s: dict) -> list[str]:
    view = s["operating_view"]
    lines = ["## test_2018 (universe + positives)", "",
             f"{view['n_positives_in_domain']} in-domain positive cell-days plus {view['n_out_of_domain']} out-of-domain "
             f"(counted as misses); event base rate {_n(view['base_rate'], 6)} per cell-day.", ""]
    lines += _table(["level", "alerts / 1000 cell-days", "recall (in domain)", "recall (all, OOD = miss)"],
                    [[k, _n(v["alerts_per_1000_cell_days"], 2), _n(v["recall_in_domain"]), _n(v["recall_all"])]
                     for k, v in view["per_level"].items()])
    lines += ["### Cost-loss", "",
              "An alert is optimal when risk >= C/L, so each threshold is the cost ratio at which it is optimal. "
              "`relative expense` is expense / min(never alert, always alert); below 1 the rule beats both.", ""]
    table = view["cost_loss"]
    rows = [[f"{k} threshold", _n(p["threshold"], 2), _n(p["implied_cost_ratio"], 2), _n(p["alerts_per_1000_cell_days"], 2),
             _n(p["recall"]), _n(p["relative_expense"], 3)] for k, p in table["operating_points"].items()]
    rows += [[f"C/L = 1/{round(1 / r['cost_loss'])}", _n(r["threshold"], 3), _n(r["cost_loss"], 3),
              _n(r["alerts_per_1000_cell_days"], 2), _n(r["recall"]), _n(r["relative_expense"], 3)] for r in table["ratios"]]
    lines += _table(["rule", "threshold", "C/L", "alerts / 1000", "recall", "relative expense"], rows)
    lines += ["", _cost_loss_statement(view, s["universe_risk_max"]), ""]
    lines += ["### What each layer adds (test_2018 universe, alerts per 1000 cell-days / recall)", "",
              "Layers in order: calibrated point risk against the card thresholds; plus the `uncertain_high` rule "
              "(upper interval bound reaches Watch); plus the blind-escalation rule; after hysteresis (the published "
              "level; the universe rows are random cell-days, mostly not on consecutive days, so hysteresis has little to "
              "hold here and its row is a small effect).", ""]
    for level, by_layer in s["layers"].items():
        lines += [f"**{level}+**", ""]
        lines += _table(["layer", "alerts / 1000 cell-days", "recall (in domain)", "recall (all, OOD = miss)"],
                        [[name, _n(v["alerts_per_1000_cell_days"], 2), _n(v["recall_in_domain"]), _n(v["recall_all"])]
                         for name, v in by_layer.items()])
    lines += ["### Same-day event detection (sample positives)", ""] + _detection_rows(s["event_detection_same_day"])
    lines += ["### Level and confidence mix (universe, weighted)", ""] + _mix_rows(s["level_and_confidence_mix_universe"])
    lines += [_causes_line(s["confidence_causes_universe"]), ""]
    lines += ["### Blind escalations (universe)", ""] + _blind_rows(s["blind_escalations_universe"])
    lines += [f"Positives whose level was raised by the blind rule: {s['positives_blind_escalated']}.", "", s["note"], ""]
    return lines


def _window_markdown(s: dict) -> list[str]:
    w = s["window_detection"]
    lines = [f"## Window 2023 ({s['window'][0]} .. {s['window'][1]})", ""]
    lines += _table(["positive cells", "detected (cell or 8 neighbours)", "rate", "other cells", "other cells alerted any day",
                     "other cell-days alerted"],
                    [[str(w["n_positive_cells"]), str(w["n_detected"]), _n(w["detection_rate"]), str(w["n_other_cells"]),
                      _n(w["other_cells_alerted_any_day"]), _n(w["other_cell_days_alerted"], 4)]])
    lines += ["### Alerted area (sampled cells)", ""] + _area_rows(s["alerted_area_sampled_cells"])
    lines += ["### Flapping", ""] + _flapping_rows(s["flapping"])
    lines += ["### Blind escalations", ""] + _blind_rows(s["blind_escalations"])
    lines += ["### Level and confidence mix", ""] + _mix_rows(s["level_and_confidence_mix"]) + [
        _causes_line(s["confidence_causes"]), ""]
    lines += ["### Share of cell-days at each level after each layer", ""] + _layers_rows(s["layers"]) + [s["note"], ""]
    return lines


def _case_markdown(title: str, s: dict) -> list[str]:
    lines = [f"## {title} ({s['dates'][0]} .. {s['dates'][1]}, {s['n_cells']} cells)", ""]
    if "event_detection" in s:
        lines += ["### Event detection with lead time", ""] + _detection_rows(s["event_detection"])
        lines += _table(["cell", "event day", "detected", "lead (d)", "days available"],
                        [[str(e["cell_id"]), e["date"], "yes" if e["detected"] else "no", _n(e["lead_days"]),
                          str(e["days_available"])] for e in s["events"]])
        lines += ["Lead time is limited by the days the case table holds before each event (`days available`).", ""]
    lines += ["### Alerted area per day", ""] + _area_rows(s["alerted_area"])
    lines += ["### Flapping", ""] + _flapping_rows(s["flapping"])
    lines += ["### Blind escalations", ""] + _blind_rows(s["blind_escalations"])
    lines += ["### Level and confidence mix", ""] + _mix_rows(s["level_and_confidence_mix"]) + [
        _causes_line(s["confidence_causes"]), ""]
    lines += ["### Share of cell-days at each level after each layer", ""] + _layers_rows(s["layers"])
    if "saturation" in s:
        lines += _saturation_markdown(s["saturation"])
    if "note" in s:
        lines += [s["note"], ""]
    return lines


def render_markdown(report: dict) -> str:
    t = report["thresholds"]
    lines = ["# Phase 4 alert report", ""]
    if report["provisional"]:
        lines += [f"> **PROVISIONAL: {report['provisional']}.** Numbers below come from a model that is not the frozen "
                  "one; they only demonstrate that the pipeline runs and must not be quoted as results.", ""]
    lines += [f"Thresholds ({t['source']}): Watch {_n(t['watch'], 2)}, Warning {_n(t['warning'], 2)}, "
              f"Emergency {_n(t['emergency'], 2)} (calibrated risk per cell-day).",
              f"Model card sha256: `{(report.get('model') or {}).get('card_sha256', 'n/a')}`; frozen "
              f"{(report.get('freeze') or {}).get('created_utc', 'n/a')} (freeze record verified before the replay was built).",
              f"Lead window: Watch+ on the event day or within {report['evaluation']['lead_days']} days before; "
              f"a flap is a Watch+ alert off and on again within {report['evaluation']['flap_window_days']} days.", ""]
    sections = report["sections"]
    if "test_2018" in sections:
        lines += _test_markdown(sections["test_2018"])
    if "window_2023" in sections:
        lines += _window_markdown(sections["window_2023"])
    if "kerala_2018" in sections:
        lines += _case_markdown("Kerala 2018", sections["kerala_2018"])
    if "wayanad_2024" in sections:
        lines += _case_markdown("Wayanad 2024", sections["wayanad_2024"])
    return "\n".join(lines).rstrip() + "\n"


def write_report(report: dict, reports_dir: Path, stem: str) -> tuple[Path, Path]:
    if report["provisional"] and stem == FINAL_STEM:
        raise ValueError(f"the store is provisional ({report['provisional']!r}); write it under another --stem, "
                         f"not the final {FINAL_STEM!r}")
    reports_dir.mkdir(parents=True, exist_ok=True)
    json_path, md_path = reports_dir / f"{stem}.json", reports_dir / f"{stem}.md"
    dump_json(json_path, report)
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--store", type=Path, default=None, help="replay store directory")
    parser.add_argument("--stem", default=FINAL_STEM, help="output file stem under the reports directory")
    parser.add_argument("--reports-dir", type=Path, default=PROJECT_ROOT / "reports")
    args = parser.parse_args(argv)
    report = build_report(ReplayStore(args.store))
    json_path, md_path = write_report(report, args.reports_dir, args.stem)
    print(f"wrote {md_path} and {json_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
