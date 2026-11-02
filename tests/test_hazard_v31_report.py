"""v3.1 challenger report: rendered from result files; absent parts say so and missing numbers print as NaN."""
import copy
import json

import numpy as np
import pandas as pd
import pytest

from aetherguard.hazard import challengers as ch
from aetherguard.hazard import cv
from aetherguard.hazard import data as hd
from aetherguard.hazard import v31_challenger as vc
from aetherguard.hazard import v31_eval as ve
from aetherguard.hazard import v31_labels as vl
from aetherguard.hazard import v31_report as vr

from hazard_helpers import COLUMN_MAP, synthetic_development
from test_hazard_v31_challenger import COLUMNS, FOLDS, SELECTED, tiny_study
from test_hazard_v31_labels import events, positives, records


@pytest.fixture(scope="module")
def study():
    return tiny_study()


@pytest.fixture(scope="module")
def labels(study):
    pos = positives(cell_id=[1, 2], date=pd.to_datetime(["2012-07-01", "2012-07-02"]), split=["train", "test_2018"],
                    region=["western_ghats", "himalaya"], stat_slope_mean=[2.0, 20.0], stat_elev_mean=[30.0, 1500.0])
    ev = events([(1, "2012-07-01", "hma", 1, 1.0, True), (2, "2012-07-02", "hma", 2, 1.0, True)])
    ev["event_date"] = pd.to_datetime(ev["event_date"])
    catalog = records({"event_id": 1, "setting": "mine", "description": "Stone quarry | with | pipes"}, {"event_id": 2})
    return vl.audit(pos, ev, catalog, study)[1]


@pytest.fixture(scope="module")
def development(study):
    samples, universe = synthetic_development(n_pos_train=110, n_pos_validation=50, n_per_region=2500)
    dev = hd.build_development(samples, universe, COLUMN_MAP)
    layout = cv.make_layout(dev, FOLDS)
    candidates = vc.make_candidates(study, COLUMNS)
    keys = dev.positives.iloc[:4][["cell_id", "date"]]
    results = {n: vc.run_candidate(c, dev, layout, SELECTED, study["base"], keys) for n, c in candidates.items()}
    frames = {n: ch.oof_frame(layout, r.oof) for n, r in results.items()}
    evaluation = vc.evaluate_candidates(layout, frames, results, study, say=lambda m: None)
    reference = results["C0"]
    return {"development": {"positives": len(layout.positives), "universe_rows": len(layout.negatives), "matched_rows": len(layout.matched),
                            "folds": FOLDS, "implausible_positives_in_audit": 4},
            "reproduction": {"recomputed_fa_at_90": reference.pooled[vc.HEADLINE], "reported_fa_at_90": reference.pooled[vc.HEADLINE],
                             "abs_difference": 0.0, "n_trees": reference.n_trees, "reported_n_trees": reference.n_trees},
            "candidates": {n: {"description": c.description, "n_inputs": len(c.columns), "columns": c.columns,
                               "constraints": dict(zip(c.columns, c.constraints)),
                               "drop_implausible_positives": c.drop_implausible,
                               "positives_dropped": 4 if c.drop_implausible else 0} for n, c in candidates.items()},
            "evaluation": evaluation, "selection": vc.select(evaluation, study)}


def report_of(labels, development, heldout=None, replay=None) -> dict:
    return {"created_utc": "2026-10-24T00:00:00Z", "spec": "spec", "labels": labels, "development": development,
            "heldout_2018": heldout, "replay": replay}


def test_the_report_renders_every_section_from_the_result_files(labels, development):
    text = vr.markdown(report_of(labels, development))
    for heading in ("## Summary", "## 1. Label audit", "## 2. Candidates", "## 3. Development results", "## 4. Pre-declared selection",
                    "## 5. Descriptive follow-up", "## 6. test_2018", "## 7. Offline live replay"):
        assert heading in text
    assert f"**Result: {development['selection']['result']}.**" in text
    assert "Not run." in text and "stone quarry".lower() in text.lower()
    assert text.count("| candidate |") >= 4
    for name in ("C0", "C1", "C2", "C3"):
        assert f"| {name} |" in text
    assert "|" not in vr.cell_text("a | b")


def test_missing_numbers_print_as_nan():
    assert vr.num(None) == "NaN" and vr.pct(None) == "NaN" and vr.ci(None) == "NaN"
    assert vr.with_point(0.5, {"lo": None, "hi": 0.7}) == "0.5000 [NaN, 0.7000]"
    assert vr.ci({"value": 0.25, "lo": 0.2, "hi": 0.3}, 2, percent=True) == "25.00% [20.00%, 30.00%]"


def test_a_skipped_test_look_is_reported_as_not_read(labels, development):
    heldout = {"skipped": True, "reason": "the pre-declared selection named no candidate"}
    text = vr.markdown(report_of(labels, development, heldout))
    assert "Not run: the pre-declared selection named no candidate." in text
    assert "not read (no candidate selected)" in text


def fake_replay():
    levels = {"Normal": 90, "Watch": 5, "Warning": 3, "Emergency": 2}
    names = [ve.V3, "C2"]
    per_day = {n: [levels] for n in ["published", *names]}
    box = {n: levels for n in ["published", *names]}
    return {
        "protocol": {"days": ["2026-10-09", "2026-10-24"], "report_from": "2026-10-16", "written_to_data_live": False, "candidates": ["C2"]},
        "v3_replay_check": {"cell_days_equal_to_published": 100, "cell_days": 100, "per_day_equal": [100], "from_report_start": 0},
        "levels_per_day": per_day, "last_day_classes": {"flat_cell_watch_plus": {n: 3 for n in ["published", *names]}},
        "areas": {"kanyakumari": {n: {"Normal": 0, "Watch": 0, "Warning": 0, "Emergency": 1} for n in ["published", *names]}},
        "area_cell_counts": {"kanyakumari": 1},
        "area_cells": {"kanyakumari": [{"cell_id": 19625150, "lat": 8.1, "lon": 77.5, "slope_mean": 2.8, "elev_mean": 31.0, "acc_3": 12.0,
                                        "levels": {n: "Emergency" for n in ["published", *names]}}]},
        "transitions_last_day": {"C2": {"Emergency->Warning": 4}},
        "leads_last_day": {"v3_equals_published": {"1": 99, "2": 100, "3": 100},
                           "counts": {n: {str(k): levels for k in (1, 2, 3)} for n in names},
                           "published": {str(k): levels for k in (1, 2, 3)}}}


def test_the_replay_section_marks_unselected_candidates_exploratory(labels, development):
    text = vr.markdown(report_of(labels, development, None, fake_replay()))
    assert "EXPLORATORY (C2)" in text and "19625150" in text and "Emergency->Warning 4" in text
    assert "cell 19625150 is published Emergency, v3_live Emergency, C2 Emergency" in text
    selected = vr.replay_section(fake_replay(), "C2")
    assert "EXPLORATORY" not in selected


def test_the_test_look_section_reports_the_criterion(labels, development):
    entry = {"fa_at_90": {"value": 0.3, "lo": 0.2, "hi": 0.4}, "levels": {
        level: {"events": 40, "recall": 0.5, "fa_share": 0.05, "cell_days": 1.2e6, "low_share": 0.07, "precision_per_1000": 0.04,
                "bootstrap": {"low_share": {"lo": 0.05, "hi": 0.09}}} for level in vc.LEVELS}}
    heldout = {"skipped": False, "candidate": "C2", "population": {"positives_in_domain": 80, "universe_rows": 1000},
               "reproduction": {"recomputed_fa_at_90": 0.3, "reported_fa_at_90": 0.3},
               "models": {ve.V3: entry, "candidate": entry},
               "paired_fa_at_90": {"point_difference": -0.01, "ci_lo": -0.05, "ci_hi": 0.03},
               "criterion": {"a_fa_at_90_not_worse": True, "b_lower_warning_low_share": False, "c_warning_events_lost": 1,
                             "c_allowed": 1, "c_within_allowance": True, "recommended": False}}
    text = vr.heldout_section(heldout)
    assert "**Recommended for adoption: no.**" in text and "lost 1: yes" in text and "(b)" in text


def test_write_report_writes_strict_json_and_markdown(study, labels, development, tmp_path, monkeypatch):
    monkeypatch.setenv("AETHERGUARD_DATA_DIR", str(tmp_path / "data"))
    out = vc.output_dir(study)
    out.mkdir(parents=True)
    (out / vc.LABEL_SUMMARY).write_text(json.dumps(labels), encoding="utf-8")
    payload = {"created_utc": "x", "frozen_reference": "model_v3_live", "model_dir": None, "seconds": 1.0, **development}
    from aetherguard.hazard.jsonio import dump_json
    dump_json(out / vc.DEV_RESULTS, payload)
    report = vr.write_report(study, say=lambda m: None, reports_dir=tmp_path / "reports")
    assert report["heldout_2018"] is None and report["replay"] is None
    written = json.loads((tmp_path / "reports" / f"{study['report_stem']}.json").read_text(encoding="utf-8"))
    assert written["development"]["selection"]["result"] == development["selection"]["result"]
    assert (tmp_path / "reports" / f"{study['report_stem']}.md").read_text(encoding="utf-8").startswith("# v3.1 challenger")
    broken = copy.deepcopy(study)
    (out / vc.DEV_RESULTS).unlink()
    with pytest.raises(FileNotFoundError, match="development"):
        vr.write_report(broken, say=lambda m: None, reports_dir=tmp_path / "reports")
    assert np.isfinite(written["development"]["evaluation"]["candidates"]["C0"]["fa_at_90"]["value"])
