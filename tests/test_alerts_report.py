"""The alerts report from a fixture replay store: content, markdown, provisional guard and the CLI."""
import json

import pytest

from aetherguard.alerts import report as rp
from aetherguard.alerts import store
from alerts_store_helpers import build_store

SETS = {
    "case_kerala_2018_samples": {"n_cells": 4, "n_days": 8, "start": "2018-08-01", "positive_cells": (1, 3)},
    "case_wayanad_2024_samples": {"n_cells": 3, "n_days": 5, "start": "2024-07-15"},
    "window_2023_samples": {"n_cells": 4, "n_days": 5, "start": "2023-06-16",
                            "extra": {"is_window_positive_cell": lambda c, d: c < 2}},
    "universe_test_2018": {"n_cells": 4, "n_days": 3, "start": "2018-07-01",
                           "extra": {"kind": lambda c, d: "universe", "universe_size": lambda c, d: 1000,
                                     "in_domain": lambda c, d: True}},
    "test_2018_samples": {"n_cells": 3, "n_days": 2, "start": "2018-07-01", "positive_cells": (0, 1),
                          "extra": {"kind": lambda c, d: "positive" if c < 2 and d == 1 else "negative",
                                    "in_domain": lambda c, d: c != 1}},
}


@pytest.fixture(scope="module")
def report_store(tmp_path_factory):
    _, root = build_store(tmp_path_factory.mktemp("report"), SETS)
    return store.ReplayStore(root)


@pytest.fixture(scope="module")
def report(report_store):
    return rp.build_report(report_store)


def test_all_sections_are_built_with_the_designed_metrics(report):
    assert set(report["sections"]) == {"test_2018", "window_2023", "kerala_2018", "wayanad_2024"}
    kerala = report["sections"]["kerala_2018"]
    assert kerala["event_detection"]["n_events"] == 2 and kerala["n_cells"] == 4
    assert {"alerted_area", "flapping", "blind_escalations", "events"} <= set(kerala)
    assert set(kerala["flapping"]) == {"with_hysteresis", "without_hysteresis"}
    assert set(kerala["layers"]["Watch"]) == {"point_risk", "plus_uncertain_high", "plus_blind_rule", "after_hysteresis"}
    sat = report["sections"]["wayanad_2024"]["saturation"]
    assert sat["n_days"] == 5 and sat["focus_cell"] in (1000, 1001, 1002) and "emergency_share_all_cells" in sat
    assert set(report["sections"]["test_2018"]["layers"]["Watch"]) == set(kerala["layers"]["Watch"])
    assert "note" in report["sections"]["wayanad_2024"] and "event_detection" not in report["sections"]["wayanad_2024"]
    assert report["thresholds"]["source"] == "test"


def test_kerala_events_carry_lead_and_available_history(report):
    events = report["sections"]["kerala_2018"]["events"]
    assert [e["cell_id"] for e in events] == [1001, 1003]
    assert all(e["days_available"] == 8 for e in events)
    detected = [e for e in events if e["detected"]]
    assert detected and all(e["lead_days"] is not None and 0 <= e["lead_days"] <= 7 for e in detected)


def test_test_2018_section_counts_out_of_domain_positives_as_misses(report):
    view = report["sections"]["test_2018"]["operating_view"]
    assert view["n_positives_in_domain"] == 1 and view["n_out_of_domain"] == 1
    watch = view["per_level"]["Watch"]
    assert watch["recall_all"] == pytest.approx(watch["recall_in_domain"] / 2)
    assert [r["cost_loss"] for r in view["cost_loss"]["ratios"]] == [0.1, 0.02, 0.005]
    assert report["sections"]["test_2018"]["event_detection_same_day"]["n_events"] == 1


def test_window_section_is_window_level(report):
    w = report["sections"]["window_2023"]["window_detection"]
    assert w["n_positive_cells"] == 2 and w["n_other_cells"] == 2


def test_report_is_strict_json_and_markdown_has_the_tables(report):
    json.dumps(report, allow_nan=False, default=str)
    text = rp.render_markdown(report)
    for heading in ("# Phase 4 alert report", "## test_2018", "### Cost-loss", "## Window 2023", "## Kerala 2018",
                    "### Event detection with lead time", "## Wayanad 2024", "### Flapping", "### Blind escalations",
                    "without hysteresis", "C/L = 1/50", "**What this implies.**", "### What each layer adds",
                    "### Limitation: the alert levels saturate", "risk rank (1 = highest)", "plus_uncertain_high",
                    "Confidence limited by", "freeze record verified"):
        assert heading in text
    assert "PROVISIONAL" not in text


def test_provisional_label_is_shown_and_blocks_the_final_stem(report, tmp_path):
    marked = {**report, "provisional": "v1 smoke"}
    assert "PROVISIONAL: v1 smoke" in rp.render_markdown(marked)
    with pytest.raises(ValueError, match="provisional"):
        rp.write_report(marked, tmp_path, rp.FINAL_STEM)
    json_path, md_path = rp.write_report(marked, tmp_path, "phase4_alerts_report_v1_smoke")
    assert json_path.is_file() and md_path.is_file()
    assert json.loads(json_path.read_text())["provisional"] == "v1 smoke"


def test_cli_writes_both_files(report_store, tmp_path, capsys):
    assert rp.main(["--store", str(report_store.root), "--reports-dir", str(tmp_path), "--stem", "x"]) == 0
    assert (tmp_path / "x.md").is_file() and (tmp_path / "x.json").is_file()
    assert "wrote" in capsys.readouterr().out


def test_sections_are_skipped_for_sets_the_store_lacks(tmp_path):
    _, root = build_store(tmp_path, {"case_wayanad_2024_samples": SETS["case_wayanad_2024_samples"]})
    assert set(rp.build_report(store.ReplayStore(root))["sections"]) == {"wayanad_2024"}


def _view(rates, recall=0.0):
    point = {"threshold": 1e-5, "relative_expense": 0.5}
    return {"base_rate": 6e-6, "cost_loss": {"operating_points": {"watch": point, "warning": point, "emergency": point},
                                             "ratios": [{"alerts_per_1000_cell_days": r, "recall": recall} for r in rates]}}


def test_cost_loss_statement_says_plainly_when_the_requested_ratios_never_alert():
    never = rp._cost_loss_statement(_view([0.0, 0.0, 0.004]), 0.01)
    assert "effectively never to alert" in never and "no alert at all" in never
    assert "as the table shows" in rp._cost_loss_statement(_view([0.0, 2.0, 30.0], recall=0.3), 0.01)


def test_saturation_text_names_the_disaster_day_and_its_tie():
    sat = {"focus_cell": 7, "focus_distance_km": 0.8, "n_days": 2, "days_at_emergency": 2, "distinct_risk_values": 1,
           "max_risk": 1e-3, "max_risk_days": ["2024-07-17", "2024-07-30"],
           "level_by_day": {"2024-07-17": "Emergency", "2024-07-30": "Emergency"},
           "risk_by_day": {"2024-07-17": 1e-3, "2024-07-30": 1e-3}, "risk_rank_by_day": {"2024-07-17": 1, "2024-07-30": 1}}
    text = " ".join(rp._saturation_markdown(sat))
    assert "on every one of the 2 days" in text and "shares the maximum with 2024-07-17" in text
    assert "not something tuned away" in text
