import json

import numpy as np
import pandas as pd
import pytest
from integrity_helpers import synthetic_raw_years, write_toy_rain_store

from aetherguard.integrity import baseline_report as br
from aetherguard.integrity import engine_data, engine_report, model, oof


@pytest.fixture(scope="module")
def smoke(tmp_path_factory):
    """The whole Phase 2b-ii pipeline on a toy world: tiny grid, few rounds, few seeds."""
    mp = pytest.MonkeyPatch()
    tmp = tmp_path_factory.mktemp("smoke")
    root = tmp / "data"
    root.mkdir()
    mp.setenv("AETHERGUARD_DATA_DIR", str(root))
    mp.setattr(model, "PARAM_GRID", ({"num_leaves": 7, "min_child_samples": 10}, {"num_leaves": 15, "min_child_samples": 10}))
    mp.setattr(model, "MAX_ROUNDS", 25)
    mp.setattr(engine_data, "TRAIN_EXTRA_SEEDS", (11, 12))
    mp.setattr(engine_data, "STABILITY_SEEDS", (21,))
    raw = synthetic_raw_years(tmp, n_stations=12)
    write_toy_rain_store(root / "processed" / "rain")
    br.prepare(raw)
    engine_data.run(raw)
    data = engine_report.load_data(raw)
    report, parts = engine_report.build_report(data, n_boot=10)
    out = tmp / "reports"
    md, js = engine_report.write_reports(report, out)
    yield {"report": report, "md": md, "js": js, "root": root, "data": data, "engine": parts["engine"]}
    mp.undo()


def test_report_files_are_written_with_strict_json_and_all_sections(smoke):
    report = json.loads(smoke["js"].read_text(encoding="utf-8"), parse_constant=lambda c: pytest.fail(c))
    md = smoke["md"].read_text(encoding="utf-8")
    for section in ("recall per fault type", "Ablations", "genuine-extreme retention", "Repair", "Stability across",
                    "Real NOAA flags", "SUPPLEMENT", "Gate assessment", "scale_drift shortfall"):
        assert section in md
    assert set(report["evaluation"]) == {"val", "test", "test_ex_nepal"}
    rows = set(report["config"]["rows"])
    assert {"engine", "engine_score", "engine_no_arbiter", "engine_arbiter_no_imd", "range_check", "l1",
            "noaa_style_qa", "noaa_style_qa_wide", "robust_zscore", "isolation_forest"} <= rows
    assert {f"ablation_{name}" for name in engine_report.ABLATIONS} <= rows
    gate = report["gate_assessment"]
    assert set(gate) == {"primary", "secondary_model_score", "oracle_matched", "statement"}
    assert len(gate["primary"]) == len(gate["secondary_model_score"]) == len(gate["oracle_matched"]) == 6
    assert "realised TEST false-flag rate" in gate["primary"][0] and "not deployable" in gate["oracle_matched"][0]
    assert set(report["tau_combined"]) == {"0.005", "0.01", "0.02"}
    assert set(report["tau_transfer_model_only"]) == {"0.005", "0.01", "0.02"}
    assert "Why the realised TEST false-flag rate differs" in md and "Oracle-matched comparison" in md
    diag = report["false_flag_diagnosis"]
    assert {"val_combined_fpr", "test_combined_fpr", "test_top_stations", "nepal_share_of_test_false_flags",
            "val_model_fpr_with_columns_missing"} <= set(diag)
    assert {"engine_at_0.5pct", "engine_at_2pct"} <= set(report["evaluation"]["test"]["methods"])
    assert "engine_oracle_matched_noaa_wide" in report["evaluation"]["test"]["methods"]
    assert "test_ex_nepal" in report["evaluation"]


def test_trade_off_and_retention_fields_carry_numerators_and_denominators(smoke):
    test = smoke["report"]["evaluation"]["test"]
    for name in ("engine", "engine_no_arbiter"):
        for variant, cell in test["methods"][name]["retention"].items():
            assert {"numerator", "denominator"} <= set(cell) and cell["numerator"] <= cell["denominator"]
    trade = test["spike_trade_off"]
    assert trade["flagged_without_arbiter"] >= trade["flagged_with_arbiter"]
    assert trade["retained_by_arbiter"] == trade["flagged_without_arbiter"] - trade["flagged_with_arbiter"]


def test_engine_model_and_oof_outputs_are_written(smoke):
    integrity = smoke["root"] / "processed" / "integrity"
    assert (integrity / "model" / "model.txt").is_file() and (integrity / "model" / "card.json").is_file()
    real = pd.read_parquet(integrity / engine_report.OOF_NAME)
    injected = pd.read_parquet(integrity / engine_report.OOF_INJECTED_NAME)
    assert list(real.columns) == oof.OOF_COLUMNS
    window = smoke["data"].window
    assert len(real) == window.values.size == len(injected)
    assert real.groupby("station")["fold"].nunique().eq(1).all()
    assert real["trust"].isna().sum() == int(window.values.isna().to_numpy().sum())   # missing days: NaN trust
    assert real["trust"].dropna().between(0, 1).all()


def test_model_selected_on_val_and_stored_with_every_candidate(smoke):
    card = smoke["report"]["engine_card"]
    assert len(card["candidates"]) == 2 and card["selected_params"] in [c["params"] for c in card["candidates"]]
    assert set(card["thresholds"]) == {"0.005", "0.01", "0.02"}
    assert card["seeds"]["extra_train"] == [11, 12]


def test_seed_stability_lists_the_frozen_seed_and_the_others(smoke):
    stab = smoke["report"]["seed_stability"]
    assert stab["seeds"] == ["frozen", "21"]
    assert set(stab["summary"]) == {"score_at_1pct", "full_engine_flags"}


def test_combined_threshold_meets_the_target_on_the_val_clean_days_it_was_chosen_on(smoke):
    data, engine = smoke["data"], smoke["engine"]
    val = model.assemble_rows(data.feats, data.table, data.splits["val"])
    for level in (0.005, 0.01, 0.02):
        pred = engine.predict(data.feats, data.obs, data.refs, fpr=level)
        flagged = pred["flagged"].to_numpy()[val.idx][val.y == 0]
        assert flagged.mean() <= level + 1e-12
    assert set(engine.bundle.tau) == set(engine.bundle.tau_model) == {"0.005", "0.01", "0.02"}
    assert smoke["report"]["engine_card"]["thresholds"] == engine.bundle.tau


def test_verdict_rules():
    cell = lambda r, lo, hi, n=10: {"recall": r, "recall_ci": [lo, hi], "n_positive": n}  # noqa: E731
    assert engine_report.verdict(cell(0.8, 0.7, 0.9), cell(0.2, 0.1, 0.3)) == "beats"
    assert engine_report.verdict(cell(0.1, 0.0, 0.2), cell(0.6, 0.5, 0.7)) == "loses"
    assert engine_report.verdict(cell(0.5, 0.3, 0.7), cell(0.4, 0.2, 0.6)) == "ties (CIs overlap)"
    assert engine_report.verdict(cell(0.5, 0.5, 0.5), cell(0.5, 0.5, 0.5)) == "ties"
    assert engine_report.verdict(cell(0.0, 0.0, 0.0, n=0), cell(0.5, 0.5, 0.5)) == "n/a"


@pytest.mark.realdata
def test_real_engine_runs_end_to_end_and_beats_range_check_on_test():
    from aetherguard.integrity.common import integrity_dir
    out = integrity_dir()
    assert (out / engine_report.OOF_NAME).is_file()
    report = json.loads((engine_report.reports_dir() / "phase2_integrity_report.json").read_text(encoding="utf-8"))
    test = report["evaluation"]["test"]["methods"]
    assert test["engine"]["macro_recall"] > test["range_check"]["macro_recall"]
    assert test["engine_score"]["macro_recall"] > test["range_check"]["macro_recall"]
    oof_real = pd.read_parquet(out / engine_report.OOF_NAME)
    assert list(oof_real.columns) == oof.OOF_COLUMNS and oof_real["trust"].dropna().between(0, 1).all()
