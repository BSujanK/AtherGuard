"""The daily bulletin: Markdown rendered from the run summary (run.json) and nothing else, so every number in it is a
number of the run. `render(summary)` is pure; the run writes the text to `<report_dir>/<date>.md`."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..alerts.levels import LEVEL_NAMES
from ..serve import places as pl

CONFIDENCE = ("High", "Degraded", "Insufficient")
SOURCE_LABELS = {"imerg_late": "IMERG Late run", "imerg_early": "IMERG Early run",
                 "gfs": "GFS forecast and 00-03 UTC rain", "imd_rt": "IMD real-time rain", "ghcn": "GHCN-Daily gauges"}
SOURCE_ORDER = tuple(SOURCE_LABELS)
OPTIONAL_LABELS = {"ecmwf": "ECMWF IFS open data forecast rain (CC BY 4.0)"}
ATTRIBUTION = "Contains ECMWF open data (IFS), licensed CC BY 4.0: https://www.ecmwf.int/en/forecasts/datasets/open-data"


def _cell(value) -> str:
    return "-" if value is None else str(value)


def _utc(text: str | None) -> str:
    return "-" if text is None else text.replace("T", " ").replace("+00:00", "")[:16]


def _risk(value) -> str:
    return "no score" if value is None else f"{value:.3g}"


def cell_set_line(cells: dict) -> str:
    """The sentence that says which cells are assessed (the model's candidate cells) and how many are not."""
    if cells["in_scope"] is None:
        return f"Cells assessed: {cells['assessed']} ({cells['definition']})."
    floor = "" if cells["slope_floor_deg"] is None else f", slope floor {cells['slope_floor_deg']:.2f} degrees"
    return (f"Cells assessed: {cells['assessed']} of {cells['in_scope']} cells in the scored regions; not assessed: "
            f"{cells['not_assessed']}, not written to the risk tables. Assessed = {cells['definition']}{floor}.")


def _present(summary: dict) -> list[str]:
    """The sources of the run in display order: the five core ones, then the optional ones the run fetched."""
    return [*SOURCE_ORDER, *(n for n in OPTIONAL_LABELS if n in summary["sources"])]


def _label(name: str) -> str:
    return SOURCE_LABELS.get(name) or OPTIONAL_LABELS[name]


def sources_table(summary: dict) -> list[str]:
    lines = ["| source | state | valid through (UTC) | issued (UTC) | latency (h) |", "|---|---|---|---|---|"]
    for name in _present(summary):
        s = summary["sources"][name]
        lines.append(f"| {_label(name)} (`{name}`) | {s['state']} | {_utc(s['valid_through'])} | "
                     f"{_utc(s['issued'])} | {_cell(s['latency_h'])} |")
    return lines


MONTH_NAMES = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
               "November", "December")


def months_label(months) -> str:
    months = sorted(int(m) for m in months)
    if months == list(range(months[0], months[-1] + 1)):
        return f"{MONTH_NAMES[months[0] - 1]}-{MONTH_NAMES[months[-1] - 1]}" if len(months) > 1 else MONTH_NAMES[months[0] - 1]
    return ", ".join(MONTH_NAMES[m - 1] for m in months)


def season_lines(summary: dict) -> list[str]:
    """The flag of the leads dated outside the declared season of validity (`live.season`); none when every lead is inside
    or the summary predates the record."""
    record = summary.get("season_of_validity")
    if not record or not record["any_outside"]:
        return []
    flagged = ["D" if k == "0" else f"D+{k}" for k, out in sorted(record["leads"].items()) if out]
    return [f"**Outside the validated season ({months_label(record['months'])})**: {', '.join(flagged)}. The alert chain "
            "(post-model rules, alert parameters) was developed on June-September and evaluated on June-December; these "
            "alerts are published unchanged and should be read as outside the validated season "
            f"(`{record['flag']}`, {record['source']}).", ""]


def second_opinion_line(summary: dict) -> list[str]:
    """Which IMD real-time days the confidence check compared with IMERG; a summary from before the check had a record has
    no line."""
    record = summary.get("second_opinion")
    if not record:
        return []
    due = f"the day due under its declared {record['latency_h']:g} h latency is {record['due_day']}"
    if record["check_day"] is None:
        why = "later than its declared latency" if record["state"] == "late" else "no file at all"
        return [f"Second opinion (IMD real-time against IMERG, used for confidence): none ({why}; {due}); every cell "
                "carries `imd_missing`.", ""]
    lag = "D" if record["lag_days"] == 0 else f"D-{record['lag_days']}"
    return [f"Second opinion (IMD real-time against IMERG, used for confidence): check day {record['check_day']} ({lag}), "
            f"3-day window {record['window'][0]} to {record['window'][1]} (files present: "
            f"{', '.join(record['days_present']) or 'none'}); {due}, so the source is on time.", ""]


def failed_section(summary: dict) -> list[str]:
    """The explicit failed / missing list; every entry says what the run did without it."""
    items = []
    for name in _present(summary):
        s = summary["sources"][name]
        if s["state"] != "ok":
            kind = "FAILED" if s["state"] == "failed" else "LATE or partial"
            fallback = " Forecast leads it cannot supply use GFS." if name == "ecmwf" else ""
            items.append(f"- **{_label(name)}** (`{name}`) {kind}: {s['error'] or 'no detail given'}{fallback}")
    tail = summary["nowcast_tail"]
    if tail["persisted"]:
        items.append("- **00-03 UTC rain of IMD day D persisted from UTC D-1** (no GFS cycle supplied it): confidence of "
                     "every cell is capped at `Degraded` (cause `nowcast_tail_persisted`); heavy rain in any source still "
                     "raises a capped cell to at least Watch.")
    elif tail["product"] != "gfs_00z_0_3h":
        items.append(f"- **00-03 UTC rain of IMD day D came from `{tail['product']}`**, not the 00Z cycle of D "
                     "(the 00Z cycle was not available).")
    gaps = summary["imerg_gaps"]
    if gaps:
        items.append(f"- **IMERG-based rain missing for UTC day(s) {', '.join(gaps)}**: cells whose last three IMD days "
                     "depend on them have no score and are `Insufficient`; the blind-escalation rule was still applied.")
    integrity = summary["integrity"]
    if not integrity["ran"]:
        items.append(f"- **Integrity engine did not run** ({integrity['reason']}): the alert table has no `integ_*` "
                     "columns, i.e. no station information; confidence rests on the two rain sources alone.")
    for lead in ("1", "2", "3"):
        info = summary["leads"][lead]
        if not info["published"]:
            items.append(f"- **Forecast lead D+{lead} not published**: {info['reason']}")
    widening = summary["forecast_widening"]
    if not widening["applied"]:
        items.append(f"- **Forecast intervals not widened**: {widening['reason']}. Forecast cells carry at most "
                     "`Degraded` confidence (cause `forecast_uncertainty_uncalibrated`).")
    if summary["retry_recommended"]:
        items.append(f"- **Retry recommended**: {summary['retry_reason']}.")
    return items or ["None. Every source delivered what the run asked for."]


def counts_table(summary: dict) -> list[str]:
    head = ("| lead | date | cells | scored | " + " | ".join(LEVEL_NAMES) + " | " + " | ".join(CONFIDENCE) + " |")
    lines = [head, "|" + "---|" * (4 + len(LEVEL_NAMES) + len(CONFIDENCE))]
    for key in sorted(summary["leads"]):
        info = summary["leads"][key]
        if not info["published"]:
            lines.append(f"| D+{key} | {info['date']} | not published | | " + " | ".join([""] * (len(LEVEL_NAMES) + len(CONFIDENCE))) + " |")
            continue
        lead = "D" if key == "0" else f"D+{key}"
        lines.append(f"| {lead} | {info['date']} | {info['n_cells']} | {info['n_scored']} | "
                     + " | ".join(str(info["levels"][n]) for n in LEVEL_NAMES) + " | "
                     + " | ".join(str(info["confidence"][n]) for n in CONFIDENCE) + " |")
    return lines


def forecast_rain_section(summary: dict) -> list[str]:
    """Which forecast rain each forecast lead was built from, and how many of its cells are firm (spec section 12). A summary
    from before section 12 has neither and gets no section."""
    chosen = summary.get("forecast_rain")
    if not chosen:
        return []
    lines = ["## Forecast rain and certainty", "",
             "| lead | forecast rain | cycle (UTC) | upper rain scenario | firm cells | depends on the forecast |",
             "|---|---|---|---|---|---|"]
    for key in sorted(chosen["leads"]):
        info, lead = chosen["leads"][key], summary["leads"][key]
        wet = "ensemble upper spread" if info["wet_bound"] == "ensemble_spread" else "forecast x high widening factor"
        lines.append(f"| D+{key} | {info['label']} | {_utc(info['cycle'])} | {wet} | {lead['certainty']['firm']} | "
                     f"{lead['certainty']['depends_on_forecast']} |")
    fallback = chosen["choice"]["fallback"]
    lines += ["", "Firm: the level is the same with no further rain, with the forecast and with its heavy-rain bound. "
              f"Fallback for a lead whose source is missing: {fallback['source']}."]
    if any(i["source"].startswith("ecmwf") for i in chosen["leads"].values()):
        lines += ["", ATTRIBUTION + "."]
    return [*lines, ""]


def post_rules_section(summary: dict) -> list[str]:
    """The post-model rules of the run (spec section 11) and the consistency audit of what it published. A summary of a
    run before the rules existed has neither and gets no section."""
    rules, checked = summary.get("post_rules"), summary.get("audit")
    if rules is None and checked is None:
        return []
    lines = ["## Post-model rules and audit", ""]
    if rules is not None:
        p = rules["parameters"]
        minimum = p.get("rain_minimum_mm") or {}
        rain = " OR ".join(f"{w}-day IMERG rain >= {m:.3g} mm" for w, m in sorted(minimum.items())) or "none"
        lines.append(f"- Rain trigger: {rain}; capped levels: {', '.join(p.get('gated_levels') or []) or 'none'}; "
                     f"hold window {p.get('hold_window_days')} days; blind hold at most {p.get('blind_hold_days')} day(s); "
                     f"ensemble agreement minimum {p.get('agreement_min')}; forecast `uncertain_high` bound "
                     f"{p.get('lead_uncertain_bound')} (rules: `{rules['source']}`).")
        counts = summary["leads"]["0"].get("post_rules")
        if counts:
            lines.append(f"- D: {counts['no_recent_rain']} cells capped for no recent rain, {counts['held_while_blind']} "
                         f"held while blind, {counts['ensemble_disagrees']} with the ensemble disagreeing (Degraded).")
    if checked is not None:
        found = {k: v for k, v in checked["violations"].items() if v}
        lines.append(f"- Audit of {checked['rows']} published rows: "
                     + ("no violation." if not found else "**violations** " + ", ".join(f"{k} {v}" for k, v in found.items())
                        + f" (`{checked['file']}`)."))
    return [*lines, ""]


def place_labels(path: Path | None, cell_ids) -> dict[int, str]:
    """{cell_id: "Mananthavady, Wayanad, Kerala"} of the `cell_ids` in the place table at `path`; {} when there is no
    table (the bulletin then leaves the place column out) or it cannot be read."""
    if path is None or not Path(path).is_file():
        return {}
    wanted = sorted({int(c) for c in cell_ids})
    try:
        table = pd.read_parquet(path, filters=[("cell_id", "in", wanted)])
        missing = [c for c in pl.TABLE_COLUMNS if c not in table.columns]
        if missing:
            raise pl.PlacesError(f"lacks the columns {missing}")
    except (OSError, ValueError, pl.PlacesError):
        return {}
    return {int(row["cell_id"]): pl.place_name(pl.place_record(row)) for _, row in table.iterrows()}


def top_section(summary: dict, places: dict[int, str] | None = None) -> list[str]:
    lines = []
    for key in sorted(summary["leads"]):
        info = summary["leads"][key]
        if not info["published"]:
            continue
        lead = "D" if key == "0" else f"D+{key}"
        lines += ["", f"### {lead} ({info['date']})"]
        if not info["top_cells"]:
            lines.append("No cell at Watch or above.")
            continue
        named = bool(places)
        lines += ["", f"| cell |{' place |' if named else ''} lat, lon | region | level | risk (10-90%) | confidence | reasons |",
                  "|---|" + "---|" * (6 + named)]
        for c in info["top_cells"]:
            band = "" if c["risk_lo"] is None else f" ({c['risk_lo']:.3g}-{c['risk_hi']:.3g})"
            why = "; ".join([*c["codes"], *c["reasons"]]) or "-"
            conf = c["confidence"] + (f" [{', '.join(c['confidence_causes'])}]" if c["confidence_causes"] else "")
            where = f" {places.get(c['cell_id'], '-')} |" if named else ""
            lines.append(f"| {c['cell_id']} |{where} {c['lat']:.3f}, {c['lon']:.3f} | {c['region']} | {c['level_name']} | "
                         f"{_risk(c['risk'])}{band} | {conf} | {why} |")
    return lines


def _region_thresholds(by_region: dict | None) -> str:
    """` By region: ...` when the model is calibrated per region and each region has its own thresholds."""
    if not by_region:
        return ""
    return " By region: " + "; ".join(f"{name} Watch {t['watch']:.3g}, Warning {t['warning']:.3g}, Emergency {t['emergency']:.3g}"
                                      for name, t in by_region.items()) + "."


def render(summary: dict, places: dict[int, str] | None = None) -> str:
    """The bulletin text of one run summary; `places` (cell_id -> place name, see `place_labels`) adds a place column to
    the top-cells tables."""
    mode = "backtest (inputs issued before the data cut-off only)" if summary["backtest"] else "live"
    inputs = summary["imd_day_inputs"]
    lead0 = summary["leads"]["0"]
    lines = [f"# AetherGuard live bulletin, {summary['date']}", "",
             f"Run {summary['run_time_local']} ({mode}); finished {summary['finished_utc']} UTC in {summary['seconds']} s. "
             f"Model: {summary['model']['n_columns']} inputs, {summary['model']['calibration']} calibration; thresholds "
             f"Watch {summary['model']['thresholds']['watch']:.3g}, Warning {summary['model']['thresholds']['warning']:.3g}, "
             f"Emergency {summary['model']['thresholds']['emergency']:.3g} (source: {summary['model']['thresholds']['source']})."
             f"{_region_thresholds(summary['model'].get('thresholds_by_region'))}", "",
             *season_lines(summary), cell_set_line(summary["cell_set"]), "",
             f"Cells scored for D: {lead0['n_scored']} of {lead0['n_cells']}; Watch or above: "
             f"{lead0['n_cells'] - lead0['levels']['Normal']}; blind-rule checks that applied: {lead0['n_blind']}.", "",
             "## Sources", "", *sources_table(summary), "", *second_opinion_line(summary),
             "## Rain behind the last two IMD days", "",
             "| IMD day | UTC day weighted 0.875 | part weighted 0.125 | product |", "|---|---|---|---|"]
    for label in ("D", "D-1"):
        i = inputs[label]
        lines.append(f"| {label} | {i['utc_day_0.875']} | {i['utc_day_0.125']} | {i['product']} |")
    lines += ["", "## Failed / missing sources", "", *failed_section(summary), "",
              "## Alerts by lead", "", *counts_table(summary), "", *forecast_rain_section(summary), *post_rules_section(summary),
              "## Top cells", *top_section(summary, places), ""]
    integrity = summary["integrity"]
    notes = list(summary["notes"])
    if integrity["ran"]:
        notes.insert(0, f"Integrity: {integrity['note']}; stations with a reading on D: {integrity['n_stations_observed']}.")
    hysteresis = summary["hysteresis"]
    notes.append(f"Hysteresis continued from {hysteresis['previous_days_used']} previous live day(s)"
                 + ("." if hysteresis["first_previous"] is None else f" (from {hysteresis['first_previous']})."))
    lines += ["## Notes", "", *[f"- {n}" for n in notes], ""]
    return "\n".join(lines)
