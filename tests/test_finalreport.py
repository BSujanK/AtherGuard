import json
import re

import pytest

from aetherguard.finalreport import build
from aetherguard.finalreport import sources as src
from aetherguard.pipeline.stages import load_config

TYPES = build.TYPES


def method(macro, fpr=None, recall=0.5):
    per_type = {t: {"recall": recall, "recall_ci": [recall - 0.1, recall + 0.1], "n_positive": 10} for t in TYPES}
    out = {"macro_recall": macro, "per_type": per_type, "binary": fpr is not None, "achieved_fpr": fpr if fpr is not None else 0.01,
           "retention": {v: {"numerator": 9, "denominator": 10, "retention": 0.9} for v in ("design", "wide", "wide_1neighbour", "uncorroborated")}}
    return out


INTEGRITY = {
    "evaluation": {"test": {"methods": {**{k: method(0.1 * (i + 1)) for i, k in enumerate(
        ("range_check", "l1", "noaa_style_qa", "noaa_style_qa_wide", "robust_zscore", "isolation_forest", "engine_score"))},
        "engine": {**method(0.7012, fpr=0.0492), "macro_recall_ci": [0.6, 0.8]},
        "engine_no_arbiter": method(0.71, fpr=0.05), "engine_oracle_matched_noaa_wide": method(0.54, fpr=0.013)},
        "spike_trade_off": {"flagged_without_arbiter": 20, "flagged_with_arbiter": 19, "retained_by_arbiter": 1}},
        "test_ex_nepal": {"methods": {"engine": method(0.72, fpr=0.0089)}}},
    "tau_combined": {t: {"tau": 0.5, "val": {"achieved_fpr": 0.01, "macro_recall": 0.69}, "test": {"achieved_fpr": 0.05, "macro_recall": 0.7}}
                     for t in ("0.005", "0.01", "0.02")},
    "gate_assessment": {"statement": "FIXTURE STATEMENT about the Nepal stations."},
    "false_flag_diagnosis": {"nepal_false_flags": 496, "test_false_flags": 545, "test_fpr_excluding_nepal": 0.0089},
    "fault_dataset": {"episodes_per_type": {s: {t: 7 for t in TYPES} for s in ("train", "val", "test")}},
    "repair": {"test": {"methods": {k: {"mae": 11.0, "median_abs_error": 6.0} for k in
                                    ("engine_repair", "previous_day", "neighbour_mean", "zero_fill", "no_repair_observed")},
                        "band_coverage": 0.755, "hazard_safe": {"days": 40, "share_repaired_ge_half_truth": 0.425}}},
    "seed_stability": {"summary": {"full_engine_flags": {"macro_recall_mean": 0.68, "macro_recall_min": 0.65, "macro_recall_max": 0.7}}},
    "real_flag_sanity": {"n_flagged_values": 10, "methods": {"engine": {"flagged_real": 9}, "noaa_style_qa_wide": {"flagged_real": 6},
                                                              "l1": {"flagged_real": 0}}},
    "oof": {"outputs": {"rows": 920500, "trust_nan_share": 0.769}},
}
for _v in ("own_only", "no_grid", "no_nbr", "no_wet", "no_dropout", "no_extra_seeds"):
    INTEGRITY["evaluation"]["test"]["methods"][f"ablation_{_v}"] = method(0.3)

CORRECTOR = {"evaluation_test": {"pinball": {"corrector": {"0.9": {"mean": 2.66, "ci": [2.0, 3.4], "skill_vs_reference": 0.432,
                                                                    "diff_vs_reference": -2.02, "diff_ci": [-3.4, -0.5]}}}},
             "wayanad": {"corrector_summary": {"q90_share_of_imd": 0.397, "gap_closed": False}, "days": {"2024-07-30": {"imd_mm": 179.24,
                         "corrector": {"q50": 31.2, "q90": 71.1, "q99": 127.1}}}}, "notes": ["fixture note"]}
DAY_BASIS = {"verdict": ["fixture verdict line"], "products": {p: {"peak_lag_pearson": lag, "lags": {"0": {"median_pearson": 0.5, "pearson_ci": [0.4, 0.6], "n_stations": 11}}}
                                                               for p, lag in (("imd", 0), ("chirps_utc", -1), ("chirps_aligned", 0))}}
HAZARD_V1 = {"overall_recall": {"test_2018": {"model": {"in_domain": {"value": 0.787, "lo": 0.7, "hi": 0.875, "n": 80}}}},
             "test_2018": {"warning": "only 80 positive cell-days", "paired_fa_at_headline_recall": {"intensity_duration": {"value": 0.036, "lo": -0.13, "hi": 0.13}}},
             "validation": {"paired_fa_at_headline_recall": {"intensity_duration": {"value": 0.134, "lo": 0.06, "hi": 0.19}}}}
CASES = {"focus_table": [{"date": "2024-07-30", "imd_mm": 179.2, "chirps_aligned_mm": 43.5, "chirps_utc_mm": 0.0, "era5_utc_mm": 53.3,
                          "era5_imd_exact_mm": 66.9, "near_value_mm": 154.9, "near_dist_km": 45.0, "near_trust": 0.99, "corr_q90_1": 63.8,
                          "corr_q99_1": 134.7}],
         "d5_error": {"wayanad_mundakkai|era5": {"days": 34, "mean_abs_error_mm": 1.85, "max_abs_error_mm": 10.5, "heavy_mean_abs_relative_error": 0.077}},
         "era5_kerala": {}, "unavailable": {"x|era5_land": "all null"}, "notes": ["case note"]}
SPLITS = {"totals": {"day_exact_cell_days": 919, "day_exact_events": 956, "window_cells": 24, "window_events": 176},
          "splits": {n: {"cell_days": 10, "events": 11} for n in ("train", "validation", "test_2018", "test_sparse")}}

DOC_PHASE2 = "# Phase 2\n\n## Gate outcome and controller rulings\n- RULING fixture shortfall text 4.9%.\n\n## Other\nignored\n"
DOC_PHASE3 = ("# Phase 3\n\n## Protocol v2 (controller ruling)\nv2 fixture text.\n\n### sub\nnested\n\n"
              "## Finding: CHIRPS daily artifact at Wayanad\nfixture finding.\n\n## Tasks\nignored\n")
SPEC = ("# Spec\n\n## 3. Where existing systems fail\n\n### 3.1 Evidence\nEVIDENCE LINE\n\n### 3.2 Failure → design response\n| # | f |\n|---|---|\n| F1 | x |\n\n"
        "## 4. Data\nignored\n")
ALERTS_MD = "# Alerts\n\n## Gate assessment\nALERT GATE FIXTURE\n\n## Kerala 2018 replay\nKERALA FIXTURE\n\n## Wayanad replay\nWAYANAD FIXTURE\n"


def write(root, relative, content):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")
    return path


def populate(root, skip=(), extras=True):
    files = {"reports/phase2_integrity_report.json": INTEGRITY, "reports/phase3_corrector_report.json": CORRECTOR,
             "reports/phase2b_day_basis.json": DAY_BASIS, "reports/phase3_hazard_report_v1.json": HAZARD_V1,
             "reports/phase3e_case_inputs.json": CASES, "data/processed/splits/splits_manifest.json": SPLITS,
             "docs/phase2-design.md": DOC_PHASE2, "docs/phase3-design.md": DOC_PHASE3,
             "docs/superpowers/specs/2026-09-30-aetherguard-design.md": SPEC}
    if extras:
        files["reports/phase4_alerts_report.json"] = {"x": 1}
        files["reports/phase4_alerts_report.md"] = ALERTS_MD
    for relative, content in files.items():
        if relative not in skip:
            write(root, relative, content)


def assemble(root):
    return build.assemble(load_config(), root, root / "data", root / "reports")


def figures_match_sources(root, payload):
    cfg = load_config()
    srcs = src.Sources(cfg, root, root / "data", root / "reports")
    checked = 0
    for fig in payload["figures"]:
        if fig["value"] is None or isinstance(fig["value"], (str, bool, dict, list)):
            continue
        name = next(n for n in srcs._candidates if srcs.label(n) == fig["source"])
        assert src.get(srcs.json(name), fig["path"]) == fig["value"], fig
        checked += 1
    return checked


def test_assembly_on_fixture_reports_has_every_section_and_the_source_numbers(tmp_path):
    populate(tmp_path)
    text, payload = assemble(tmp_path)
    assert payload["sections"] == ["1. Summary", "2. Data", "3. Where existing systems fail, and what AetherGuard does about it",
                                   "4. Stage 1: sensor-integrity results", "5. Stage 2: hazard model and extreme-rain corrector",
                                   "6. Alerts", "7. Case studies", "8. Limitations and honest shortfalls", "9. How to run"]
    assert "0.70 [0.60, 0.80]" in text                          # engine macro recall with its CI, formatted from the fixture
    assert "0.049" in text and "0.787 [0.700, 0.875]" in text and "179.2" in text and "919" in text
    assert "FIXTURE STATEMENT about the Nepal stations." in text and "496 of 545" in text
    assert "ALERT GATE FIXTURE" in text and "KERALA FIXTURE" in text                      # markdown sections embedded verbatim
    assert "EVIDENCE LINE" in text and "| F1 | x |" in text                               # spec section 3 embedded
    assert "RULING fixture shortfall text 4.9%." in text and "v2 fixture text." in text and "fixture finding." in text
    assert "nested" in text                                                               # sub-headings travel with their section
    assert "ignored" not in text
    assert "all null" in text and "fixture note" in text and "case note" in text
    assert "pending: reports/phase2_integrity_report.json" not in payload["pending"]      # present sources are not pending
    assert "pending: reports/phase3_hazard_report_v1.json" not in payload["pending"]
    assert "pending: reports/phase2a_baselines.json" in payload["pending"]                 # absent in the fixture


def test_every_figure_in_the_json_equals_the_value_in_its_source_file(tmp_path):
    populate(tmp_path)
    text, payload = assemble(tmp_path)
    assert payload["n_figures"] == len(payload["figures"]) > 100
    assert figures_match_sources(tmp_path, payload) > 80
    engine = next(f for f in payload["figures"] if f["path"] == "evaluation.test.methods.engine.macro_recall")
    assert engine["value"] == 0.7012 and engine["source"] == "reports/phase2_integrity_report.json"


def test_missing_inputs_render_as_pending_and_the_report_still_assembles(tmp_path):
    text, payload = assemble(tmp_path)                           # an empty project: nothing exists
    assert len(payload["sections"]) == 9
    for name in ("reports/phase2_integrity_report.json", "reports/phase3_corrector_report.json", "reports/phase4_alerts_report.json",
                 "reports/phase3_hazard_report_v1.json", "reports/phase2b_day_basis.json", "reports/phase3e_case_inputs.json"):
        assert f"pending: {name}" in text and f"pending: {name}" in payload["pending"]
    assert "pending: docs/superpowers/specs/2026-09-30-aetherguard-design.md" in text
    assert payload["missing_paths"] == []                        # a missing FILE is pending, not a missing path
    assert all(not s["present"] for s in payload["sources"].values())
    assert "9. How to run" in text and "aetherguard.pipeline" in text


def test_a_missing_path_inside_a_present_source_is_marked_and_listed(tmp_path):
    populate(tmp_path)
    broken = json.loads(json.dumps(INTEGRITY))
    del broken["evaluation"]["test"]["methods"]["l1"]["macro_recall"]
    write(tmp_path, "reports/phase2_integrity_report.json", broken)
    text, payload = assemble(tmp_path)
    assert "n/a (not in source)" in text
    assert "reports/phase2_integrity_report.json#evaluation.test.methods.l1.macro_recall" in payload["missing_paths"]


def test_a_source_identical_to_another_is_skipped_for_hazard_v2(tmp_path):
    populate(tmp_path)
    write(tmp_path, "reports/phase3_hazard_report.json", HAZARD_V1)             # identical to the v1 file
    text, payload = assemble(tmp_path)
    assert payload["sources"]["hazard_v2"]["present"] is False and "pending: reports/phase3_hazard_report.json" in text
    write(tmp_path, "reports/phase3_hazard_report.json", {**HAZARD_V1, "changed": True})
    _, payload = assemble(tmp_path)
    assert payload["sources"]["hazard_v2"]["path"] == "reports/phase3_hazard_report.json" and payload["sources"]["hazard_v2"]["present"]


def test_output_never_contains_absolute_paths(tmp_path):
    populate(tmp_path)
    write(tmp_path, "reports/phase4_alerts_report.md",
          f"# A\n\n## Gate assessment\nwrote {tmp_path}/reports/x.json and C:\\Users\\someone\\secret\\file.txt and D:/data/y\n")
    text, payload = assemble(tmp_path)
    flat = text + json.dumps(payload)
    assert str(tmp_path) not in flat and tmp_path.as_posix() not in flat
    assert not re.search(r"[A-Za-z]:[\\/]", flat)
    assert "reports/x.json" in text


def test_unreadable_json_is_reported_not_raised(tmp_path):
    populate(tmp_path)
    write(tmp_path, "reports/phase3_corrector_report.json", "{not json")
    text, payload = assemble(tmp_path)
    assert payload["sources"]["corrector"]["unreadable"] and "pending: reports/phase3_corrector_report.json" in text


def test_get_handles_dotted_keys_and_list_indices():
    data = {"a": {"0.9": {"x": 1}, "0": {"9": 2}}, "rows": [{"v": 5}, {"v": 6}], "k.l": 3}
    assert src.get(data, "a.0.9.x") == 1 and src.get(data, "a.0.9") == {"x": 1}
    assert src.get(data, "a.0.9.nope") is src.MISSING
    assert src.get(data, "rows.1.v") == 6 and src.get(data, "rows.5.v") is src.MISSING and src.get(data, "k.l") == 3
    assert src.get(data, "zzz", default=None) is None


def test_extract_sections_keeps_nested_headings_and_ignores_code_fences():
    text = "# T\n\n## A matches\nbody\n### nested\ndeep\n\n## B\nother\n\n```\n## A matches in code\n```\n\n## C a match too\nlast\n"
    found = src.extract_sections(text, "match", demote_to=4)
    assert [t for t, _ in found] == ["A matches", "C a match too"]
    assert "#### nested" in found[0][1] and "other" not in found[0][1] and found[1][1] == "last"


def test_formatting_degenerate_intervals_and_integers(tmp_path):
    populate(tmp_path)
    doc = build.Doc(src.Sources(load_config(), tmp_path, tmp_path / "data", tmp_path / "reports"))
    assert doc.val_ci("integrity", "evaluation.test.methods.l1.per_type.stuck_value.recall", "evaluation.test.methods.l1.per_type.stuck_value.recall_ci") == "0.50 [0.40, 0.60]"
    degenerate = json.loads(json.dumps(INTEGRITY))
    degenerate["evaluation"]["test"]["methods"]["l1"]["per_type"]["stuck_value"]["recall_ci"] = [0.2, 0.2]
    write(tmp_path, "reports/phase2_integrity_report.json", degenerate)
    doc = build.Doc(src.Sources(load_config(), tmp_path, tmp_path / "data", tmp_path / "reports"))
    assert doc.val_ci("integrity", "evaluation.test.methods.l1.per_type.stuck_value.recall", "evaluation.test.methods.l1.per_type.stuck_value.recall_ci").endswith("n/a (degenerate)")
    assert doc.val("day_basis", "products.chirps_utc.peak_lag_pearson", "{:+d}") == "-1"
    assert doc.val("cases", "d5_error.wayanad_mundakkai|era5.days", "{:,d}") == "34"


def test_cli_writes_markdown_and_strict_json_with_relative_paths_only(tmp_path, capsys):
    populate(tmp_path)
    assert build.main(["--root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "wrote reports/FINAL_REPORT.md and reports/FINAL_REPORT.json" in out and str(tmp_path) not in out
    md = (tmp_path / "reports" / "FINAL_REPORT.md").read_text(encoding="utf-8")
    js = json.loads((tmp_path / "reports" / "FINAL_REPORT.json").read_text(encoding="utf-8"), parse_constant=lambda c: pytest.fail(c))
    assert md.startswith("# AetherGuard: final report") and js["n_figures"] > 100 and set(js) >= {"sections", "sources", "pending", "figures"}


@pytest.mark.realdata
def test_the_real_report_has_no_missing_paths_and_no_absolute_paths():
    from aetherguard.config import PROJECT_ROOT, data_root
    text, payload = build.assemble(load_config(), PROJECT_ROOT, data_root(), PROJECT_ROOT / "reports")
    assert payload["missing_paths"] == []
    assert not re.search(r"[A-Za-z]:[\\/]", text)
    assert figures_match_sources(PROJECT_ROOT, payload) > 100
