"""Assemble reports/FINAL_REPORT.md (+ .json) from the phase reports.

    python -m aetherguard.finalreport [--config PATH] [--root DIR]

Every number is read from a source file (`Doc.val*` look it up by a dotted path and record it in the `figures` list of the
JSON output with its source file and path); prose from the design documents and phase markdown reports is embedded
verbatim. A source that does not exist renders as `pending: <file>` so the report can be generated now and again at the end.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..config import PROJECT_ROOT, data_root
from ..pipeline.stages import load_config, parse_stages
from .sources import MISSING, Sources, bold_block, extract_sections, get, is_number, sanitize

TYPES = ("stuck_value", "zero_fault", "spike", "scale_drift", "offset_noise", "duplicate_block")
BASELINES = ("range_check", "l1", "noaa_style_qa", "noaa_style_qa_wide", "robust_zscore", "isolation_forest")


class Doc:
    """Markdown under construction plus the registry of every number placed in it."""

    def __init__(self, sources: Sources) -> None:
        self.s = sources
        self.lines: list[str] = []
        self.figures: list[dict] = []
        self.pending: dict[str, str] = {}
        self.titles: list[str] = []
        self.missing_paths: list[str] = []

    # ---- text
    def add(self, *lines: str) -> None:
        self.lines.extend(lines)

    def h(self, level: int, title: str) -> None:
        if level == 2:
            self.titles.append(title)
        self.add("", f"{'#' * level} {title}", "")

    def table(self, header: list[str], rows: list[list[str]]) -> None:
        self.add("| " + " | ".join(header) + " |", "|" + "---|" * len(header))
        self.add(*("| " + " | ".join(row) + " |" for row in rows))
        self.add("")

    def note_pending(self, source: str) -> str:
        text = self.s.pending(source)
        self.pending[source] = text
        return text

    # ---- numbers
    def _record(self, label, source, path, value):
        self.figures.append({"label": label, "source": self.s.label(source), "path": path,
                             "value": value if is_number(value) or isinstance(value, (str, bool)) else None})

    def raw(self, source: str, path: str):
        data = self.s.json(source)
        if data is None:
            return MISSING
        return get(data, path)

    def val(self, source: str, path: str, fmt: str = "{:.2f}", label: str | None = None) -> str:
        value = self.raw(source, path)
        if value is MISSING:
            if self.s.json(source) is None:
                self.note_pending(source)
            else:
                self.missing_paths.append(f"{self.s.label(source)}#{path}")
            self._record(label or path, source, path, None)
            return self.s.pending(source) if self.s.json(source) is None else "n/a (not in source)"
        self._record(label or path, source, path, value)
        if value is None or (isinstance(value, float) and value != value):
            return "n/a"
        if not is_number(value):
            return str(value)
        if fmt.endswith("d}") and isinstance(value, float):
            value = int(value)
        return fmt.format(value)

    def val_ci(self, source: str, path: str, ci_path: str, fmt: str = "{:.2f}", label: str | None = None) -> str:
        head = self.val(source, path, fmt, label)
        ci = self.raw(source, ci_path)
        if ci is MISSING or not isinstance(ci, list) or len(ci) != 2 or not all(is_number(c) for c in ci):
            return head
        self._record(f"{label or path} CI", source, ci_path, ci)
        return f"{head} n/a (degenerate)" if ci[0] == ci[1] else f"{head} [{fmt.format(ci[0])}, {fmt.format(ci[1])}]"

    def val_vlh(self, source: str, path: str, fmt: str = "{:.3f}", label: str | None = None) -> str:
        """A {value, lo, hi} dict."""
        return self.val_ci_triplet(source, path, fmt, label)

    def val_ci_triplet(self, source, path, fmt, label):
        node = self.raw(source, path)
        if node is MISSING or not isinstance(node, dict) or "value" not in node:
            return self.val(source, path + ".value", fmt, label)
        self._record(label or path, source, path, {k: node.get(k) for k in ("value", "lo", "hi")})
        v, lo, hi = node["value"], node.get("lo"), node.get("hi")
        text = fmt.format(v) if is_number(v) else "n/a"
        if is_number(lo) and is_number(hi):
            text += " n/a (degenerate)" if lo == hi else f" [{fmt.format(lo)}, {fmt.format(hi)}]"
        return text

    def md_sections(self, source: str, pattern: str, level: int = 3, limit: int | None = None) -> bool:
        """Embed the sections of a source's markdown companion whose heading matches; False when none."""
        text = self.s.markdown(source)
        if text is None:
            return False
        found = extract_sections(text, pattern, demote_to=level)
        for title, body in found[:limit]:
            self.add(f"{'#' * level} {title}", "", body, "")
        return bool(found)


# ---------------------------------------------------------------------------------------------------------- helpers

def recall_cell(doc: Doc, source: str, base: str, t: str, with_fpr: bool = True) -> str:
    cell = doc.val_ci(source, f"{base}.per_type.{t}.recall", f"{base}.per_type.{t}.recall_ci", label=f"{base} {t} recall")
    binary = doc.raw(source, f"{base}.binary")
    if with_fpr and binary is True:
        cell = cell.replace(" [", f" (fpr {doc.val(source, base + '.achieved_fpr', '{:.3f}')}) [", 1) if " [" in cell else \
            f"{cell} (fpr {doc.val(source, base + '.achieved_fpr', '{:.3f}')})"
    return cell


def recall_table(doc: Doc, source: str, split: str, rows: list[tuple[str, str]]) -> None:
    header = ["method", *TYPES, "macro"]
    body = []
    for label, key in rows:
        base = f"evaluation.{split}.methods.{key}"
        if doc.raw(source, f"{base}.macro_recall") is MISSING and doc.s.json(source) is not None:
            continue
        body.append([label, *(recall_cell(doc, source, base, t) for t in TYPES), doc.val(source, f"{base}.macro_recall")])
    doc.table(header, body)


def docs_text(sources: Sources, cfg: dict, name: str) -> str | None:
    path = sources.resolve(name)
    return path.read_text(encoding="utf-8") if path.is_file() else None


# ----------------------------------------------------------------------------------------------------------- sections

def section_summary(doc: Doc) -> None:
    doc.h(2, "1. Summary")
    doc.add("AetherGuard is a research prototype of a two-stage early-warning pipeline for rain-triggered landslides in the "
            "Himalaya and Western Ghats: **stage 1** judges whether each rain sensor reading can be trusted (a sensor-integrity "
            "engine trained on faults injected into real gauge series), **stage 2** estimates a calibrated landslide risk per cell-day "
            "from trusted multi-source rain, soil wetness and terrain, with an extreme-rain corrector and an alert engine that never "
            "stays silent when it is blind. All figures below are read from the phase reports; none is typed by hand. It is not "
            "validated for issuing public warnings.", "")
    rows = [
        ["Integrity engine, TEST macro recall (combined decision at the validation-chosen 1% threshold)",
         doc.val_ci("integrity", "evaluation.test.methods.engine.macro_recall", "evaluation.test.methods.engine.macro_recall_ci", label="engine macro")
         if doc.raw("integrity", "evaluation.test.methods.engine.macro_recall_ci") is not MISSING
         else doc.val("integrity", "evaluation.test.methods.engine.macro_recall"), doc.s.label("integrity")],
        ["... realised TEST false-flag rate of that decision", doc.val("integrity", "evaluation.test.methods.engine.achieved_fpr", "{:.3f}"), doc.s.label("integrity")],
        ["... same engine without the two Nepal stations (post hoc), false-flag rate",
         doc.val("integrity", "evaluation.test_ex_nepal.methods.engine.achieved_fpr", "{:.3f}"), doc.s.label("integrity")],
        ["Best rule baseline on TEST (L1 checks), macro recall", doc.val("integrity", "evaluation.test.methods.l1.macro_recall"), doc.s.label("integrity")],
        ["NOAA-style QA with spatial check (wide neighbours), macro recall", doc.val("integrity", "evaluation.test.methods.noaa_style_qa_wide.macro_recall"), doc.s.label("integrity")],
        ["Engine matched to the NOAA-style false-flag rate (oracle, not deployable), macro recall",
         doc.val("integrity", "evaluation.test.methods.engine_oracle_matched_noaa_wide.macro_recall"), doc.s.label("integrity")],
        ["Corrector pinball skill vs raw CHIRPS, alpha 0.9 (TEST stations)", doc.val("corrector", "evaluation_test.pinball.corrector.0.9.skill_vs_reference", "{:.3f}"), doc.s.label("corrector")],
        ["Corrector, Wayanad 2024-07-30: predicted q90 as a share of the IMD value", doc.val("corrector", "wayanad.corrector_summary.q90_share_of_imd"), doc.s.label("corrector")],
        ["Day basis: peak lag of the station-vs-IMD correlation (days)", doc.val("day_basis", "products.imd.peak_lag_pearson", "{:+d}"), doc.s.label("day_basis")],
        ["Day basis: peak lag of station vs CHIRPS on the UTC day", doc.val("day_basis", "products.chirps_utc.peak_lag_pearson", "{:+d}"), doc.s.label("day_basis")],
        ["Hazard v1 (disclosed history): test_2018 recall at the validation threshold",
         doc.val_vlh("hazard_v1", "overall_recall.test_2018.model.in_domain", "{:.3f}"), doc.s.label("hazard_v1")],
        ["Hazard v1: false-alarm share at 90% recall minus best baseline, test_2018 (paired, vs intensity-duration)",
         doc.val_vlh("hazard_v1", "test_2018.paired_fa_at_headline_recall.intensity_duration", "{:.3f}"), doc.s.label("hazard_v1")],
        ["Hazard v2 (frozen, single test look): test_2018 in-domain recall at the Watch threshold (target 0.90)",
         doc.val_vlh("hazard_v2", "gate.recall_first_target.test_recall", "{:.3f}"), doc.s.label("hazard_v2")],
        ["... false-alarm share of all cell-days at that threshold",
         doc.val_vlh("hazard_v2", "gate.recall_first_target.test_fa_share", "{:.3f}"), doc.s.label("hazard_v2")],
        ["... intensity-duration baseline at its own frozen Watch threshold: recall",
         doc.val_vlh("hazard_v2", "gate.baseline_comparison.intensity_duration.at_frozen_watch.baseline_recall", "{:.3f}"),
         doc.s.label("hazard_v2")],
        ["... false-alarm share: intensity-duration minus model (paired)",
         doc.val_vlh("hazard_v2", "gate.baseline_comparison.intensity_duration.at_frozen_watch.fa_baseline_minus_model",
                     "{:.3f}"), doc.s.label("hazard_v2")],
        ["Alert system (model + uncertain_high + blind rule + hysteresis): test_2018 in-domain recall at Watch+",
         doc.val("alerts", "sections.test_2018.operating_view.per_level.Watch.recall_in_domain", "{:.3f}"),
         doc.s.label("alerts")],
        ["... Watch+ alerts per 1000 cell-days",
         doc.val("alerts", "sections.test_2018.operating_view.per_level.Watch.alerts_per_1000_cell_days", "{:.1f}"),
         doc.s.label("alerts")],
        ["Kerala 2018: positive cell-days detected at Watch+ (of 23)",
         doc.val("alerts", "sections.kerala_2018.event_detection.n_detected", "{:d}"), doc.s.label("alerts")],
        ["Wayanad 2024: days the focus cell sits at Emergency (of 22; levels saturate, no day singled out)",
         doc.val("alerts", "sections.wayanad_2024.saturation.days_at_emergency", "{:d}"), doc.s.label("alerts")],
    ]
    doc.table(["headline figure", "value [95% CI where given]", "source"], rows)
    doc.add("**Hazard model v2** (protocol v2) and the **alert engine**: ")
    for name, label in (("hazard_cv", "hazard v2 stage-1 cross-validation report"), ("hazard_v2", "hazard v2 test evaluation"),
                        ("alerts", "alerts report")):
        doc.add(f"- {label}: " + (f"`{doc.s.label(name)}` (sections 5 and 6)" if doc.s.path(name) else doc.note_pending(name)))
    doc.add("")


def _coverage_rows(doc: Doc) -> list[list[str]]:
    return [
        ["GHCN-Daily rain gauges selected (India + Nepal)", doc.val("phase2a", "coverage.n_stations", "{:,d}"), doc.s.label("phase2a")],
        ["Share of station-days with a value, 1990-2024", doc.val("phase2a", "coverage.valid_share_of_station_days", "{:.3f}"), doc.s.label("phase2a")],
        ["Clean real station-days (valid, unflagged, station-year >= 200 valid days)", doc.val("phase2a", "coverage.clean_real_days", "{:,d}"), doc.s.label("phase2a")],
        ["Stations with >= 365 clean days", doc.val("phase2a", "coverage.n_eligible_stations", "{:,d}"), doc.s.label("phase2a")],
        ["Clean days with >= 2 valid neighbours, design setting (k=5, 150 km)", doc.val("phase2a", "coverage.neighbours.design.clean_days_with_2plus_valid_neighbours", "{:.3f}"), doc.s.label("phase2a")],
        ["Clean days with >= 2 valid neighbours, wide setting (k=10, 300 km)", doc.val("phase2a", "coverage.neighbours.wide.clean_days_with_2plus_valid_neighbours", "{:.3f}"), doc.s.label("phase2a")],
        ["Real NOAA-flagged values inside 2007-2024 (the only ones scorable against references)", doc.val("integrity", "real_flag_sanity.n_flagged_values", "{:,d}"), doc.s.label("integrity")],
    ]


def section_data(doc: Doc) -> None:
    doc.h(2, "2. Data")
    doc.add("Sources (all open, no login except the NASA Earthdata label catalogs): GHCN-Daily gauges (NOAA), IMD gauge-based 0.25 degree "
            "daily grid, CHIRPS v2.0 0.05 degree daily, NASA POWER / MERRA-2 soil wetness, Copernicus GLO-90 terrain, Open-Meteo ERA5 for "
            "the two case-study points, and the NASA GLC, COOLR and High Mountain Asia landslide catalogs for labels. Licences are listed "
            "in the README.", "")
    doc.h(3, "Sensors and rain products")
    doc.table(["item", "value", "source"], _coverage_rows(doc) + [
        ["IMD grid: covered 0.25 degree points (gauge data on > 95% of days every year)", doc.val("imd_index", "covered_cells", "{:,d}"), doc.s.label("imd_index")],
        ["POWER wetness: days in the store", doc.val("power_index", "period.n_days", "{:,d}"), doc.s.label("power_index")],
        ["POWER wetness: first / last day", f"{doc.val('power_index', 'period.start', '{}')} / {doc.val('power_index', 'period.end', '{}')}", doc.s.label("power_index")],
        ["Terrain cells (0.05 degree)", doc.val("terrain", "cells.cells_kept", "{:,d}"), doc.s.label("terrain")],
        ["Cells with a region / country label", doc.val("regions", "n_cells", "{:,d}"), doc.s.label("regions")],
    ])
    doc.h(3, "Labels and frozen splits")
    totals = doc.raw("splits", "totals")
    if totals is MISSING:
        doc.add(doc.note_pending("splits"), "")
    else:
        doc.table(["quantity", "value", "source"], [
            ["Day-exact positive cell-days", doc.val("splits", "totals.day_exact_cell_days", "{:,d}"), doc.s.label("splits")],
            ["Day-exact events", doc.val("splits", "totals.day_exact_events", "{:,d}"), doc.s.label("splits")],
            ["2023 India window: cells / events", f"{doc.val('splits', 'totals.window_cells', '{:,d}')} / {doc.val('splits', 'totals.window_events', '{:,d}')}", doc.s.label("splits")],
            *[[f"Split {name}: cell-days / events", f"{doc.val('splits', f'splits.{name}.cell_days', '{:,d}')} / {doc.val('splits', f'splits.{name}.events', '{:,d}')}",
               doc.s.label("splits")] for name in ("train", "validation", "test_2018", "test_sparse")]])
    doc.add("Splits are by event date (train 2007-2015, validation 2016-2017, test 2018, sparse 2019-2024) and by station for the integrity "
            "engine; both are frozen with checksums. See `docs/phase1-design.md` for the label rules, the day basis and the negatives.", "")
    doc.h(3, "Fault dataset for stage 1")
    eps = doc.raw("integrity", "fault_dataset.episodes_per_type")
    if eps is MISSING:
        doc.add(doc.note_pending("integrity"), "")
    else:
        doc.add("Faults are INJECTED into real clean 2007-2024 series (stuck value, zero fault, spike, scale drift, offset noise, duplicate "
                "block); episodes per type and split:", "")
        doc.table(["split", *TYPES], [[sp, *(doc.val("integrity", f"fault_dataset.episodes_per_type.{sp}.{t}", "{:,d}") for t in TYPES)]
                                      for sp in ("train", "val", "test")])


def section_failures(doc: Doc, spec_text: str | None) -> None:
    doc.h(2, "3. Where existing systems fail, and what AetherGuard does about it")
    if spec_text is None:
        doc.add("pending: docs/superpowers/specs/2026-09-30-aetherguard-design.md", "")
    else:
        for title, body in extract_sections(spec_text, r"^3\.1 Evidence", demote_to=3):
            doc.add(f"### {title} (from the design spec)", "", body, "")
        for title, body in extract_sections(spec_text, r"^3\.2 Failure", demote_to=3):
            doc.add(f"### {title} (from the design spec)", "", body, "")
    doc.h(3, "Measured here")
    doc.add("**CHIRPS misses the Wayanad event day** (a daily artifact of the product, see the finding quoted in section 8). Wayanad cell, "
            "IMD day 2024-07-30:", "")
    row = doc.raw("cases", "focus_table")
    focus = next((r for r in row if r.get("date") == "2024-07-30"), None) if isinstance(row, list) else None
    if focus is None:
        doc.add(doc.note_pending("cases") if doc.s.json("cases") is None else "pending: the focus table has no 2024-07-30 row", "")
    else:
        idx = row.index(focus)
        names = [("IMD grid", "imd_mm"), ("CHIRPS aligned", "chirps_aligned_mm"), ("CHIRPS UTC day", "chirps_utc_mm"),
                 ("ERA5 UTC day", "era5_utc_mm"), ("ERA5 IMD day (exact)", "era5_imd_exact_mm"),
                 ("nearest trusted gauge (distance below)", "near_value_mm"), ("corrector q90", "corr_q90_1"), ("corrector q99", "corr_q99_1")]
        doc.table(["source", "mm on 2024-07-30", "from"], [[n, doc.val("cases", f"focus_table.{idx}.{k}", "{:.1f}"), doc.s.label("cases")] for n, k in names])
        doc.add("The nearest gauge is " + doc.val("cases", f"focus_table.{idx}.near_dist_km", "{:.0f}") + " km away with out-of-fold trust "
                + doc.val("cases", f"focus_table.{idx}.near_trust", "{:.2f}") + ".", "")
    doc.add("**ERA5 hourly data: UTC day versus IMD day.** The D5 approximation (0.875 x UTC(D-1) + 0.125 x UTC(D)) against the exact IMD-day "
            "total from hourly ERA5 at the Wayanad point:", "")
    doc.table(["measure", "value", "source"], [
        ["days compared", doc.val("cases", "d5_error.wayanad_mundakkai|era5.days", "{:,d}"), doc.s.label("cases")],
        ["mean absolute error (mm)", doc.val("cases", "d5_error.wayanad_mundakkai|era5.mean_abs_error_mm"), doc.s.label("cases")],
        ["largest absolute error (mm)", doc.val("cases", "d5_error.wayanad_mundakkai|era5.max_abs_error_mm", "{:.1f}"), doc.s.label("cases")],
        ["relative error on heavy days (>= 10 mm)", doc.val("cases", "d5_error.wayanad_mundakkai|era5.heavy_mean_abs_relative_error", "{:.3f}"), doc.s.label("cases")]])
    doc.add("**Which day does a gauge value belong to?** Lag correlation of clean station days against IMD and CHIRPS (medians over stations):", "")
    verdicts = doc.raw("day_basis", "verdict")
    if verdicts is MISSING:
        doc.add(doc.note_pending("day_basis"), "")
    else:
        doc.add(*(f"- {v}" for v in verdicts), "")
        doc.table(["product", "peak lag (days)", "median Pearson at lag 0 [95% CI]", "median Pearson at the peak [95% CI]", "stations"],
                  [[p, doc.val("day_basis", f"products.{p}.peak_lag_pearson", "{:+d}"),
                    doc.val_ci("day_basis", f"products.{p}.lags.0.median_pearson", f"products.{p}.lags.0.pearson_ci", "{:.3f}"),
                    doc.val_ci("day_basis", f"products.{p}.lags.{doc.raw('day_basis', f'products.{p}.peak_lag_pearson')}.median_pearson",
                               f"products.{p}.lags.{doc.raw('day_basis', f'products.{p}.peak_lag_pearson')}.pearson_ci", "{:.3f}"),
                    doc.val("day_basis", f"products.{p}.lags.0.n_stations", "{:,d}")] for p in ("imd", "chirps_utc", "chirps_aligned")])
    doc.add("**NOAA-style QA misses the faults that matter for rain gauges.** TEST recall of the NOAA-style re-implementation (streak, duplicate "
            "block, climatological outlier, spatial check) against the engine, injected faults only:", "")
    rows = []
    for t in ("zero_fault", "scale_drift", "offset_noise"):
        rows.append([t, recall_cell(doc, "integrity", "evaluation.test.methods.noaa_style_qa", t),
                     recall_cell(doc, "integrity", "evaluation.test.methods.noaa_style_qa_wide", t),
                     recall_cell(doc, "integrity", "evaluation.test.methods.engine", t)])
    doc.table(["fault type", "NOAA-style, design neighbours", "NOAA-style, wide neighbours", "AetherGuard engine"], rows)
    doc.add("What AetherGuard does about it, in the design's terms: multi-source rain with source disagreement as a feature (F1), a stage-1 "
            "integrity engine with cross-source checks (F2), a calibrated stage-2 model (F3), frozen time- and region-blocked evaluation (F4) and "
            "an alert engine with a data-confidence flag that escalates, never silently stays Normal, when blind (F5).", "")


def section_integrity(doc: Doc) -> None:
    doc.h(2, "4. Stage 1: sensor-integrity results")
    if doc.s.json("integrity") is None:
        doc.add(doc.note_pending("integrity"), "")
        return
    doc.add("Evaluation is on the TEST stations (frozen, unseen), recall per injected fault type with 95% bootstrap CIs over stations; rule flags show "
            "their realised false-flag rate on clean days, score methods are matched to 1%. The combined engine uses the threshold chosen on the "
            "validation stations.", "")
    rows = [("range check", "range_check"), ("L1 deterministic checks", "l1"), ("NOAA-style QA (design neighbours)", "noaa_style_qa"),
            ("NOAA-style QA (wide neighbours)", "noaa_style_qa_wide"), ("robust z-score", "robust_zscore"), ("isolation forest", "isolation_forest"),
            ("engine, model score only (1%)", "engine_score"), ("**engine, combined, VAL-chosen 1% threshold**", "engine"),
            ("engine, combined, no arbiter", "engine_no_arbiter"), ("engine, oracle-matched to NOAA-wide rate (not deployable)", "engine_oracle_matched_noaa_wide")]
    doc.h(3, "TEST recall per fault type")
    recall_table(doc, "integrity", "test", rows)
    doc.h(3, "Operating points of the combined engine")
    doc.table(["target false-flag rate", "threshold", "VAL realised rate", "VAL macro recall", "TEST realised rate", "TEST macro recall"],
              [[t, doc.val("integrity", f"tau_combined.{t}.tau", "{:.3f}"), doc.val("integrity", f"tau_combined.{t}.val.achieved_fpr", "{:.4f}"),
                doc.val("integrity", f"tau_combined.{t}.val.macro_recall", "{:.3f}"), doc.val("integrity", f"tau_combined.{t}.test.achieved_fpr", "{:.4f}"),
                doc.val("integrity", f"tau_combined.{t}.test.macro_recall", "{:.3f}")] for t in ("0.005", "0.01", "0.02")])
    doc.add(doc.val("integrity", "gate_assessment.statement", "{}"), "")
    diag = "false_flag_diagnosis"
    doc.add("Concentration of the TEST false flags: "
            f"{doc.val('integrity', diag + '.nepal_false_flags', '{:,d}')} of {doc.val('integrity', diag + '.test_false_flags', '{:,d}')} come from the two "
            f"Nepal stations (TEST rate without them {doc.val('integrity', diag + '.test_fpr_excluding_nepal', '{:.4f}')}).", "")
    doc.h(3, "Genuine-extreme retention and the arbiter's cost")
    doc.add("Retained / extremes among clean, unflagged readings at or above each station's 99.5th wet-day percentile; no single number is the safety "
            "result. `design-strict` and `wide` need two corroborating neighbours, `uncorroborated` is a proxy that includes unverified readings.", "")
    variants = ["design", "wide", "wide_1neighbour", "uncorroborated"]
    body = []
    for label, key in (("engine (with arbiter)", "engine"), ("engine without arbiter", "engine_no_arbiter"), ("model score only", "engine_score"),
                       ("robust z-score", "robust_zscore"), ("NOAA-style, wide", "noaa_style_qa_wide")):
        base = f"evaluation.test.methods.{key}.retention"
        body.append([label, *(f"{doc.val('integrity', f'{base}.{v}.numerator', '{:,d}')}/{doc.val('integrity', f'{base}.{v}.denominator', '{:,d}')}" for v in variants)])
    doc.table(["method", *variants], body)
    doc.add("Injected spikes flagged without the arbiter / with it / retained by the arbiter: "
            f"{doc.val('integrity', 'evaluation.test.spike_trade_off.flagged_without_arbiter', '{:,d}')} / "
            f"{doc.val('integrity', 'evaluation.test.spike_trade_off.flagged_with_arbiter', '{:,d}')} / "
            f"{doc.val('integrity', 'evaluation.test.spike_trade_off.retained_by_arbiter', '{:,d}')}.", "")
    doc.h(3, "Repair (flagged, non-retained injected-fault days)")
    doc.table(["estimate", "MAE mm", "median abs error mm"],
              [[label, doc.val("integrity", f"repair.test.methods.{k}.mae"), doc.val("integrity", f"repair.test.methods.{k}.median_abs_error")]
               for label, k in (("engine repair (weighted median of references)", "engine_repair"), ("previous day", "previous_day"),
                                ("neighbour mean", "neighbour_mean"), ("zero fill", "zero_fill"), ("no repair (observed)", "no_repair_observed"))])
    doc.add(f"Band coverage {doc.val('integrity', 'repair.test.band_coverage', '{:.3f}')}; hazard-safe check (repaired >= half of the truth on days with "
            f">= 50 mm): {doc.val('integrity', 'repair.test.hazard_safe.share_repaired_ge_half_truth', '{:.3f}')} of "
            f"{doc.val('integrity', 'repair.test.hazard_safe.days', '{:,d}')} days. Repaired values never feed the rain features.", "")
    doc.h(3, "Ablations, seed stability, real flags")
    doc.table(["variant (model score, TEST macro recall at 1%)", "macro recall"],
              [["full model", doc.val("integrity", "evaluation.test.methods.engine_score.macro_recall", "{:.3f}")],
               *[[v, doc.val("integrity", f"evaluation.test.methods.ablation_{v}.macro_recall", "{:.3f}")]
                 for v in ("own_only", "no_grid", "no_nbr", "no_wet", "no_dropout", "no_extra_seeds")]])
    doc.add("Stability over three further injection seeds (combined engine, TEST macro recall): mean "
            f"{doc.val('integrity', 'seed_stability.summary.full_engine_flags.macro_recall_mean', '{:.3f}')}, min "
            f"{doc.val('integrity', 'seed_stability.summary.full_engine_flags.macro_recall_min', '{:.3f}')}, max "
            f"{doc.val('integrity', 'seed_stability.summary.full_engine_flags.macro_recall_max', '{:.3f}')}.", "")
    doc.add(f"Real NOAA flags 2007-2024 (n = {doc.val('integrity', 'real_flag_sanity.n_flagged_values', '{:,d}')}, too few to rank methods): the engine flags "
            f"{doc.val('integrity', 'real_flag_sanity.methods.engine.flagged_real', '{:,d}')}, NOAA-style QA (wide) "
            f"{doc.val('integrity', 'real_flag_sanity.methods.noaa_style_qa_wide.flagged_real', '{:,d}')}, L1 "
            f"{doc.val('integrity', 'real_flag_sanity.methods.l1.flagged_real', '{:,d}')}.", "")
    doc.add(f"Out-of-fold outputs for the hazard model: {doc.val('integrity', 'oof.outputs.rows', '{:,d}')} station-days, trust NaN on "
            f"{doc.val('integrity', 'oof.outputs.trust_nan_share', '{:.3f}')} (days without a value).", "")
    doc.h(3, "Baselines on the full 1990-2024 history (phase 2a)")
    if doc.s.json("phase2a") is None:
        doc.add(doc.note_pending("phase2a"), "")
    else:
        doc.table(["rule", "false-flag rate on real clean days"],
                  [[r, doc.val("phase2a", f"l1_real_false_flag_rates.rules.{r}.rate", "{:.5f}")] for r in ("bounds", "stuck", "duplicate_block", "l1_flag")])


def section_hazard(doc: Doc, protocol_text: str | None) -> None:
    doc.h(2, "5. Stage 2: hazard model and extreme-rain corrector")
    doc.h(3, "Hazard model v1 (disclosed history)")
    if doc.s.json("hazard_v1") is None:
        doc.add(doc.note_pending("hazard_v1"), "")
    else:
        doc.add("v1 selected hyper-parameters on the validation split and re-used it for calibration and the threshold; it is kept as disclosed history "
                "because the protocol change that produced v2 was partly prompted by its test result. False-alarm share at 90% recall, model versus each "
                "baseline (paired bootstrap, positive favours the model):", "")
        names = {"intensity_duration": "intensity-duration", "lhasa_style": "LHASA-style", "logistic": "logistic regression"}
        doc.table(["baseline", "validation: baseline minus model [95% CI]", "test_2018: baseline minus model [95% CI]"],
                  [[label, doc.val_vlh("hazard_v1", f"validation.paired_fa_at_headline_recall.{k}"), doc.val_vlh("hazard_v1", f"test_2018.paired_fa_at_headline_recall.{k}")]
                   for k, label in names.items()])
        doc.add("test_2018 recall at the validation-chosen threshold (in-domain events, target 90%): "
                + doc.val_vlh("hazard_v1", "overall_recall.test_2018.model.in_domain") + f" of {doc.val('hazard_v1', 'overall_recall.test_2018.model.in_domain.n', '{:,d}')} events. "
                + doc.val("hazard_v1", "test_2018.warning", "{}"), "")
    doc.h(3, "Protocol v2 and the final hazard model")
    if protocol_text:
        for title, body in extract_sections(protocol_text, r"Protocol v2", demote_to=4):
            doc.add(f"#### {title} (from docs/phase3-design.md)", "", body, "")
    doc.add("**Stage 1 (year-blocked cross-validation on 2007-2017, all choices made out-of-fold):**", "")
    if doc.s.path("hazard_cv"):
        if not doc.md_sections("hazard_cv", r"oof thresholds|oof metrics|integ candidates", level=5):
            doc.add(f"See `{doc.s.label('hazard_cv')}`.", "")
    else:
        doc.add(doc.note_pending("hazard_cv"), "")
    doc.add("**Single frozen test evaluation (test_2018, window 2023, case studies):**", "")
    if doc.s.path("hazard_v2"):
        shown = False
        for pattern in (r"gate assessment", r"headline|summary", r"leave-region-out", r"ablations"):
            shown = doc.md_sections("hazard_v2", pattern, level=5) or shown
        if not shown:
            doc.add(f"See `{doc.s.label('hazard_v2')}`.", "")
    else:
        doc.add(doc.note_pending("hazard_v2"), "")
    doc.h(3, "Extreme-rain corrector")
    if doc.s.json("corrector") is None:
        doc.add(doc.note_pending("corrector"), "")
        return
    doc.add("Gauge daily rain from CHIRPS-side predictors (no IMD: the IMD grid probably ingests the same gauges); LightGBM quantile regression, TEST "
            "stations only, 95% CIs over stations. Pinball loss in mm, lower is better:", "")
    body = []
    for label, key in (("raw CHIRPS", "raw_chirps"), ("linear quantile scaling", "linear_scaling"), ("corrector (headline)", "corrector"),
                       ("corrector with IMD (leakage-risk)", "corrector_with_imd")):
        row = [label]
        for a in ("0.5", "0.9", "0.99"):
            base = f"evaluation_test.pinball.{key}.{a}"
            text = doc.val_ci("corrector", f"{base}.mean", f"{base}.ci", "{:.2f}")
            if key not in ("raw_chirps",) and doc.raw("corrector", f"{base}.diff_ci") is not MISSING:
                text += f"; vs raw {doc.val_ci('corrector', base + '.diff_vs_reference', base + '.diff_ci', '{:.2f}')}"
            row.append(text)
        body.append(row)
    doc.table(["method", "alpha 0.5", "alpha 0.9", "alpha 0.99"], body)
    doc.add("Coverage of the quantiles on TEST (0.9 / 0.99): corrector "
            f"{doc.val('corrector', 'evaluation_test.coverage.corrector.0.9.coverage', '{:.3f}')} / {doc.val('corrector', 'evaluation_test.coverage.corrector.0.99.coverage', '{:.3f}')}; "
            f"raw CHIRPS {doc.val('corrector', 'evaluation_test.coverage.raw_chirps.0.9.coverage', '{:.3f}')}. Bias on the top 1% of gauge days (mm, q99): "
            f"{doc.val_ci('corrector', 'evaluation_test.top1pct_bias.methods.corrector.q99.mean_bias_mm', 'evaluation_test.top1pct_bias.methods.corrector.q99.ci', '{:.1f}')} "
            f"versus raw CHIRPS {doc.val_ci('corrector', 'evaluation_test.top1pct_bias.methods.raw_chirps.q99.mean_bias_mm', 'evaluation_test.top1pct_bias.methods.raw_chirps.q99.ci', '{:.1f}')}.", "")
    doc.add("Exceedance of the station 99th wet-day percentile, PR-AUC: corrector "
            f"{doc.val_ci('corrector', 'evaluation_test.exceedance.methods.corrector.pr_auc', 'evaluation_test.exceedance.methods.corrector.pr_auc_ci', '{:.3f}')} versus raw CHIRPS "
            f"{doc.val_ci('corrector', 'evaluation_test.exceedance.methods.raw_chirps.pr_auc', 'evaluation_test.exceedance.methods.raw_chirps.pr_auc_ci', '{:.3f}')} "
            f"({doc.val('corrector', 'evaluation_test.exceedance.positives', '{:,d}')} TEST exceedance days).", "")
    gap = doc.raw("corrector", "wayanad.corrector_summary.gap_closed")
    doc.add("Wayanad 2024-07-30 (IMD "
            f"{doc.val('corrector', 'wayanad.days.2024-07-30.imd_mm', '{:.1f}')} mm): the CHIRPS-only corrector predicts q50 {doc.val('corrector', 'wayanad.days.2024-07-30.corrector.q50', '{:.1f}')}, "
            f"q90 {doc.val('corrector', 'wayanad.days.2024-07-30.corrector.q90', '{:.1f}')}, q99 {doc.val('corrector', 'wayanad.days.2024-07-30.corrector.q99', '{:.1f}')} mm. "
            + ("It does **not** close the gap." if gap is False else "It closes the gap." if gap is True else ""), "")


def section_alerts(doc: Doc) -> None:
    doc.h(2, "6. Alerts")
    if doc.s.path("alerts") is None:
        doc.add(doc.note_pending("alerts"), "")
        return
    shown = False
    for pattern in (r"gate assessment|summary|headline", r"detection|lead", r"cost.?loss", r"blind|escalat", r"hysteresis|flap"):
        shown = doc.md_sections("alerts", pattern, level=3, limit=1) or shown
    if not shown:
        doc.add(f"See `{doc.s.label('alerts')}`.", "")


def section_cases(doc: Doc) -> None:
    doc.h(2, "7. Case studies")
    if doc.s.json("cases") is None:
        doc.add(doc.note_pending("cases"), "")
    else:
        doc.add("Wayanad (Mundakkai / Chooralmala) 2024-07-25 to 08-02, cell nearest the landslide point; mm per IMD day. No NASA landslide label exists "
                "for this event, so this is a qualitative replay, never trained or tuned on.", "")
        focus = doc.raw("cases", "focus_table")
        rows = []
        if isinstance(focus, list):
            for i, r in enumerate(focus):
                rows.append([r["date"], *(doc.val("cases", f"focus_table.{i}.{k}", "{:.1f}") for k in
                                          ("imd_mm", "chirps_aligned_mm", "chirps_utc_mm", "era5_utc_mm", "era5_imd_exact_mm", "corr_q90_1", "near_value_mm"))])
        doc.table(["day", "IMD", "CHIRPS aligned", "CHIRPS UTC", "ERA5 UTC", "ERA5 IMD day", "corrector q90", "nearest gauge"], rows)
        doc.add("Kerala 2018 points (the three wettest positive cells of 15-16 August), ERA5 on the event day, UTC day versus exact IMD day (mm):", "")
        krows = []
        points = doc.raw("cases", "era5_kerala")
        if isinstance(points, dict):
            for name, p in points.items():
                day = next((i for i, d in enumerate(p["days"]) if d["date"] == p["event_date"]), None)
                if day is not None:
                    base = f"era5_kerala.{name}.days.{day}.era5"
                    krows.append([name, doc.val("cases", f"era5_kerala.{name}.event_date", "{}"), doc.val("cases", f"{base}.utc_day_mm", "{:.1f}"),
                                  doc.val("cases", f"{base}.imd_exact_mm", "{:.1f}"), doc.val("cases", f"{base}.imd_d5_mm", "{:.1f}")])
        doc.table(["point", "event day", "UTC day", "IMD day exact", "D5 approx."], krows)
    if doc.s.path("alerts"):
        doc.add("Case replays with the alert engine (from the alerts report):", "")
        doc.md_sections("alerts", r"kerala|wayanad|case", level=3)
    else:
        doc.add(f"Model replays of both cases: {doc.note_pending('alerts')}", "")


def section_limitations(doc: Doc, docs: dict[str, str]) -> None:
    doc.h(2, "8. Limitations and honest shortfalls")
    doc.add("Stated by the reports themselves; nothing here has been softened.", "")
    for name, text in docs.items():
        for title, body in extract_sections(text, r"shortfall|gate outcome|protocol v2|^finding", demote_to=4):
            doc.add(f"#### {title} ({name})", "", body, "")
    doc.h(3, "From the reports")
    bullets: list[str] = []
    warn = doc.raw("hazard_v1", "test_2018.warning")
    if isinstance(warn, str):
        bullets.append(f"Hazard v1, test_2018: {doc.val('hazard_v1', 'test_2018.warning', '{}')}")
    ep = doc.raw("integrity", "fault_dataset.episodes_per_type.test.scale_drift")
    if ep is not MISSING:
        bullets.append(f"scale_drift has {doc.val('integrity', 'fault_dataset.episodes_per_type.test.scale_drift', '{:,d}')} TEST episodes (below the planned minimum): its "
                       "recall rests on very few episodes.")
    limits = doc.s.markdown("integrity")
    if limits:
        block = bold_block(limits, "Limits") or next((ln for ln in limits.splitlines() if ln.startswith("Limits:")), None)
        if block:
            bullets.append("Stage 1: " + block.replace("Limits:", "").strip())
    for note in (doc.raw("corrector", "notes") if doc.s.json("corrector") else []) or []:
        bullets.append("Corrector: " + str(note))
    doc.figures.append({"label": "corrector notes", "source": doc.s.label("corrector"), "path": "notes", "value": None})
    for note in (doc.raw("cases", "notes") if doc.s.json("cases") else []) or []:
        bullets.append("Case inputs: " + str(note))
    hazard_md = doc.s.markdown("hazard_v1")
    if hazard_md:
        block = bold_block(hazard_md, "Limits")
        if block:
            bullets.append("Hazard v1:\n" + "\n".join("  " + ln for ln in block.splitlines()[1:] if ln.strip()))
    if doc.s.json("cases") and doc.raw("cases", "unavailable") not in (MISSING, {}):
        for key, why in doc.raw("cases", "unavailable").items():
            bullets.append(f"Open-Meteo series unavailable ({key}): {why}")
        doc.figures.append({"label": "unavailable series", "source": doc.s.label("cases"), "path": "unavailable", "value": None})
    doc.add(*(f"- {b}" for b in bullets), "")
    if doc.pending:
        doc.h(3, "Inputs still pending")
        doc.add("These sources did not exist when this report was generated; regenerate it after they are produced:", "")
        doc.add(*(f"- {v}" for v in sorted(doc.pending.values())), "")


def section_run(doc: Doc, cfg: dict) -> None:
    doc.h(2, "9. How to run")
    doc.add("Setup, licences and the layout are in `README.md`. The whole pipeline runs stage by stage from `configs/pipeline.yaml`; stages whose "
            "outputs are frozen and verify intact are reused.", "", "```", "python -m aetherguard.pipeline status", "python -m aetherguard.pipeline run --dry-run",
            "python -m aetherguard.pipeline run [--from STAGE] [--to STAGE] [--only STAGE] [--offline] [--force]", "python -m aetherguard.finalreport", "```", "")
    stages = parse_stages(cfg)
    doc.table(["stage", "module", "network", "runs by default"],
              [[s.name, f"`{s.module}`", "yes" if s.network else "no", "yes" if s.default else "no (use --include)"] for s in stages])


# ---------------------------------------------------------------------------------------------------------- assemble

def assemble(cfg: dict, root: Path, data: Path, reports: Path) -> tuple[str, dict]:
    sources = Sources(cfg, root, data, reports)
    doc = Doc(sources)
    fr = cfg["finalreport"]
    docs = {Path(p).name: text for p in fr["docs"] if (text := docs_text(sources, cfg, p)) is not None}
    spec_text = docs_text(sources, cfg, fr["spec"])
    doc.add("# AetherGuard: final report", "",
            "Assembled by `python -m aetherguard.finalreport` from the phase reports in `reports/` and the frozen data products. Every number is read from "
            "a source file (the JSON output lists each figure with its file and path); a source that is not there yet shows as `pending: <file>`.", "")
    section_summary(doc)
    section_data(doc)
    section_failures(doc, spec_text)
    section_integrity(doc)
    section_hazard(doc, docs.get("phase3-design.md"))
    section_alerts(doc)
    section_cases(doc)
    section_limitations(doc, docs)
    section_run(doc, cfg)
    text = sanitize("\n".join(doc.lines).strip() + "\n", root)
    payload = {"sections": doc.titles,
               "sources": {name: {"path": sources.label(name), "present": sources.path(name) is not None, "sha256": sources.sha256(name),
                                  "unreadable": sources.unreadable.get(name)} for name in sorted(sources._candidates)},
               "pending": sorted(doc.pending.values()), "missing_paths": sorted(set(doc.missing_paths)), "n_figures": len(doc.figures), "figures": doc.figures}
    return text, json.loads(sanitize(json.dumps(payload, default=str), root).replace("\\\\", "/"))


def write(cfg: dict, root: Path, data: Path, reports: Path) -> tuple[Path, Path]:
    text, payload = assemble(cfg, root, data, reports)
    out = cfg["finalreport"].get("outputs", {})
    md = Sources(cfg, root, data, reports).resolve(out.get("markdown", "{reports}/FINAL_REPORT.md"))
    js = Sources(cfg, root, data, reports).resolve(out.get("json", "{reports}/FINAL_REPORT.json"))
    md.parent.mkdir(parents=True, exist_ok=True)
    md.write_text(text, encoding="utf-8", newline="\n")
    js.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    return md, js


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=None, help="configuration with a `finalreport` section (default configs/pipeline.yaml)")
    parser.add_argument("--root", type=Path, default=None, help="project root (default: this checkout)")
    args = parser.parse_args(argv)
    cfg = load_config(args.config)
    root = args.root or PROJECT_ROOT
    data = data_root() if args.root is None else root / "data"
    md, js = write(cfg, root, data, root / "reports")
    payload = json.loads(js.read_text(encoding="utf-8"))
    print(f"wrote {md.relative_to(root).as_posix()} and {js.relative_to(root).as_posix()}: {payload['n_figures']} figures, "
          f"{len(payload['pending'])} pending sources")
    for line in payload["pending"]:
        print(f"  {line}")
    for line in payload["missing_paths"]:
        print(f"  not found in a present source: {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
