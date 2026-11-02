"""The alert-burden reports: held-out summaries of backtest results, the markdown tables and the appended section."""
import json
from dataclasses import replace
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from aetherguard.live import backtest as bt
from aetherguard.live import burden as bu
from aetherguard.live import burden_report as br

from test_live_backtest import EVENT, ALERT_CONFIG, StubModel, make_stores, toy_spec


def season(levels, event_day="2018-06-03"):
    levels = np.asarray(levels, dtype=np.int8)
    events = pd.DataFrame({"cell_id": [1], "date": pd.to_datetime([event_day]), "split": ["train"]})
    days = [date(2018, 6, 1) + timedelta(days=k) for k in range(levels.shape[1])]
    return bu.season_stats(levels, np.ones(levels.shape, dtype=bool), np.ones(len(levels), dtype=bool),
                           np.arange(1, len(levels) + 1), days, events, 3)


def result(bound, hysteresis, levels, label=None):
    return {"config": bu.make_config(bound, hysteresis, label), **bu.combine_seasons({2007: season(levels)})}


def analysis():
    steps = [result("off", None, [[0, 1, 1]], "a. raw point-risk rule"), result("p90", None, [[0, 1, 1]], "b. a + uncertain_high"),
             result("p90", (1.0, 2), [[1, 1, 1]], "c. b + hysteresis"), result("p90", (0.8, 2), [[1, 1, 1]], "d. full"),
             result("off", (0.8, 2), [[1, 1, 1]], "side")]
    grid = [result("p90", (0.8, 2), [[1, 1, 1]]), result("p90", (0.8, 1), [[0, 1, 1]])]
    return {"protocol": {"period": "06-01 to 09-30 of 2007-2007", "model": "the cross-validation models", "grid_size": 2,
                         "basis": "oof", "bootstrap_se": bu.BOOTSTRAP_SE, "note": "chosen on development years only"},
            "events": {"in_season": 2, "in_scored_cells": 1}, "thresholds_by_region": {},
            "raw_score_rule": result("off", None, [[0, 0, 1]]), "risk_rule_vs_raw_rule": {
                "risk_rule_only_share": 0.07, "raw_rule_only_share": 0.0, "note": "x"},
            "decomposition": steps, "grid": grid, "grid_spec": {"exit_days": [1, 2]}, "current": grid[0], "chosen": grid[0],
            "alternative": grid[1], "allowed_loss_events": 3,
            "selection": {"objective": "minimise the Watch+ share", "constraints": "no loss",
                          "current_key": grid[0]["config"]["key"], "chosen_key": grid[0]["config"]["key"],
                          "alternative_key": grid[1]["config"]["key"]}}


@pytest.fixture(scope="module")
def toy_results(tmp_path_factory):
    stores = make_stores(tmp_path_factory.mktemp("pair"), early_heavy=[EVENT - timedelta(days=1)])
    configs = {"old": ALERT_CONFIG, "new": ALERT_CONFIG, "alt": replace(ALERT_CONFIG, exit_days=1)}
    by_label = bu.compare_set(toy_spec(), StubModel(), stores, configs)
    return {label: {"toy": res} for label, res in by_label.items()}


def parameters():
    base = {"exit_factor": 0.8, "exit_days": 2, "uncertain_percentile": 90.0, "radius_km": 100.0}
    return {"old": base, "new": dict(base), "alt": {**base, "exit_days": 1}}


def test_heldout_summary_reads_shares_events_and_flapping(toy_results):
    old, alt = (br.heldout_summary(toy_results[k]["toy"], "region") for k in ("old", "alt"))
    assert old["watch_plus"]["value"] == pytest.approx(4 * 0.25 / 8) and alt["watch_plus"]["value"] == pytest.approx(2 * 0.25 / 8)
    assert old["warning_plus"] == pytest.approx(2 * 0.25 / 8) and old["emergency"] == 0.0
    assert old["events"]["n"] == 2 and old["events"]["own_day"]["hits"] == 1 and old["events"]["median_lead_days"] == 0.0
    assert old["flapping"]["cell_days"] == 32 and "window" not in old
    assert br.heldout_summary(toy_results["old"]["toy"], "pooled")["watch_plus"]["value"] == old["watch_plus"]["value"]


def test_the_comparison_holds_the_conditions_per_set(toy_results):
    comparison = br.heldout_comparison(toy_results)["toy"]
    assert sorted(comparison) == ["alt", "cells", "days", "live_before", "new", "old"]
    assert comparison["alt"]["watch_plus"]["value"] < comparison["new"]["watch_plus"]["value"]
    assert comparison["days"] == 8 and comparison["cells"] == 4
    assert "alt" not in br.heldout_comparison({k: v for k, v in toy_results.items() if k != "alt"})["toy"]


def test_condition_labels_say_when_the_parameters_did_not_change():
    labels = br.condition_labels(parameters())
    assert sorted(labels) == ["alt", "live_before", "new"] and "unchanged" in labels["new"]
    assert "exit days 1" in labels["alt"] and "90th percentile" in labels["alt"]
    changed = parameters()
    changed["new"]["exit_days"] = 1
    assert sorted(br.condition_labels(changed)) == ["alt", "live_before", "new", "old"]


def report_of(toy_results):
    return br.build_report(analysis(), analysis(), parameters(), br.heldout_comparison(toy_results), {"limits": ["A limit."]})


def test_the_report_names_every_section_and_the_tables_carry_the_numbers(toy_results):
    text = br.render_markdown(report_of(toy_results))
    for heading in ("## What was fixed in the live runner", "## Where the burden comes from", "## The grid", "## Result",
                    "## Parameters", "## Development before and after", "## 2018, 2023 and Kerala", "## Limits"):
        assert heading in text
    assert "a. raw point-risk rule" in text and "0. frozen Watch rule on the raw score" in text
    assert "ensemble p90, exit factor 0.8, exit days 2 (old) (chosen)" in text and "exit days 1 (alternative)" in text
    assert "| exit_days | 2 | 2 | 1 | no |" in text and "the old parameters stay" in text
    assert "Costed alternative, not adopted" in text and "at most 3 events" in text
    assert "7.00%" in text and "- A limit." in text
    assert "published by the live runner before (pooled thresholds, old parameters)" in text


def test_the_report_files_are_strict_json_and_markdown(toy_results, tmp_path):
    json_path, md_path = br.write_report(report_of(toy_results), tmp_path, "burden")
    saved = json.loads(json_path.read_text(), parse_constant=lambda c: pytest.fail(f"non-strict constant {c}"))
    assert saved["parameters"]["alt"]["exit_days"] == 1 and saved["development"]["alternative"]["config"]["exit_days"] == 1
    assert saved["frozen_model_in_sample"]["selection"]["chosen_key"] == "p90|0.8|2"
    assert md_path.read_text(encoding="utf-8").startswith("# Phase 6 alert burden")


def test_the_backtest_section_is_appended_once_and_replaced_on_a_rerun(toy_results, tmp_path):
    report = report_of(toy_results)
    md = tmp_path / "phase6_backtest.md"
    md.write_text("# Phase 6 backtest\n\nBody.\n\n## Limits\n\n- a limit\n", encoding="utf-8")
    br.append_section(md, br.backtest_section(report))
    first = md.read_text(encoding="utf-8")
    assert first.startswith("# Phase 6 backtest") and first.count("## After re-derivation") == 1 and "- a limit" in first
    assert "the parameters are unchanged" in first
    br.append_section(md, br.backtest_section(report))
    assert md.read_text(encoding="utf-8") == first
