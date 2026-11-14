"""The v4 re-derivation of the section 11 rules (live.post_rules_v4): what it keeps from v3 and how it reports."""
import pandas as pd

from aetherguard.live import post_rules_v4 as P
from aetherguard.live import postrules as pr


def analysis(rules: dict) -> dict:
    return {"rules": rules}


def test_the_chosen_rules_keep_the_forecast_lead_bound_of_the_v3_rules():
    chosen = pr.PostRules(0.25, pr.RainRule({7: 9.5}), (1, 2, 3), hold_window_days=3, blind_hold_days=2,
                          hold_windows={1: 2, 2: 1, 3: 1}).to_dict()
    v3 = pr.PostRules(0.25, pr.RainRule({7: 11.5}), (1, 2, 3), lead_uncertain_bound="unwidened")
    rules = P.rules_from_analysis(analysis(chosen), v3)
    assert rules.lead_uncertain_bound == "unwidened" and rules.rain.minimum_mm == {7: 9.5}
    assert rules.window_of(1) == 2 and rules.blind_hold_days == 2


def test_the_v4_configuration_points_the_derivation_at_the_v4_card():
    cfg = {"model_config": "configs/hazard_v3.yaml", "alert_config": "x"}
    assert P.v4_cfg(cfg)["model_config"] == P.V4_MODEL_CONFIG and cfg["model_config"] == "configs/hazard_v3.yaml"


def _result(share, hits):
    det = {lvl: {"hits": h, "lo": 0.5, "hi": 0.9, "value": 0.7, "n": 600} for lvl, h in zip(("Watch", "Warning", "Emergency"), hits)}
    return {"n_events": 600, "share_at_least": dict(zip(("Watch", "Warning", "Emergency"), share)), "detected_at_least": det,
            "dry_cell_days_at": {"Watch": 1, "Warning": 2, "Emergency": 3}, "median_lead_days": 0.0}


def test_the_report_renders_every_set_and_the_difference():
    results = {k: _result((0.4, 0.15, 0.05), (590, 500, 350)) for k in
               ("v4_no_rules", "v4_v3_rules", "v4_v4_rules", "v3_no_rules", "v3_v3_rules")}
    results["v4_v4_rules"] = _result((0.38, 0.14, 0.05), (589, 500, 350))
    rules = pr.PostRules(0.25, pr.RainRule({7: 11.5}), (1, 2, 3)).to_dict()
    result = {"protocol": {"panels": "p", "model": "m"}, "oof_check": {"oof_recall_at_watch": 0.9, "card_oof_recall_at_watch": 0.9,
                                                                       "positives": 789},
              "alert_config": "a", "events": {"in_panel_cells": 600}, "parameters": {"v3_rules": rules, "v4_rules": rules},
              "results": results, "caveats": ["c"],
              "derivation_v4": {"agreement": {"choice": {"rule": "r", "agreement_min": 0.25},
                                              "split": {"by_minimum": {"0.25": {"agreeing": {"events_per_1000_alerted_cell_days": 1.0},
                                                                               "disagreeing": {"events_per_1000_alerted_cell_days": 0.5}}}}},
                                "rain_chosen": {"form": "acc_7"}, "hold_window": {"chosen": {"Watch": 2}},
                                "blind_hold": {"choice": {"blind_hold_days": 2, "rule": "b"}}},
              "v4_rules_against_v3_rules": {"Watch": {"share_v3_rules": 0.4, "share_v4_rules": 0.38, "share_change": -0.02,
                                                      "hits_v3_rules": 590, "hits_v4_rules": 589, "hits_change": -1}}}
    text = P.markdown(result)
    assert "v4 with the v3 rules (live today)" in text and "-2.00 pp" in text and "| -1 |" in text
    assert "lead_uncertain_bound" in text and "—" not in text
