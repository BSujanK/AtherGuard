"""Regression fixtures: the two user-confirmed false alarms of the 2026-10-23 live run.

* 23965166 (29.83N 78.32E, himalaya): published Warning, 0 mm of IMERG rain over 1, 3 and 7 days, its point far above
  all 20 ensemble members (interval 0.014-0.15 per 100k around a 1.8 per 100k point).
* 24605098 (Katra, Reasi, J&K, 33.03N 74.93E, himalaya): published Emergency, 0 mm over 1-7 days; Emergency since
  17 Oct and held through the input outage of 20-21 Oct by `hysteresis_hold;model_input_missing`.

The fixture (`tests/fixtures/false_alarms_2026-10-23`, `python -m aetherguard.live.hardening fixture`) holds their stored
`features_D0` rows and published alert rows of 17-23 Oct and the frozen model's scores of 23 Oct, so the tests are
hermetic. The rules are the development-derived ones of `data/processed/alerts/post_rules_v3.json`.
"""
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from aetherguard.alerts import levels as lv
from aetherguard.alerts.config import AlertConfig
from aetherguard.alerts.engine import run_alerts
from aetherguard.config import PROJECT_ROOT
from aetherguard.live import audit
from aetherguard.live import postrules as pr
from aetherguard.live import run as live_run

FIXTURE = Path(__file__).parent / "fixtures" / "false_alarms_2026-10-23"
SHIPPED_RULES = PROJECT_ROOT / "data" / "processed" / "alerts" / "post_rules_v3.json"
RULES = pr.PostRules(agreement_min=0.25, rain=pr.RainRule({7: 11.504499244689944}), gated_levels=(1, 2, 3),
                     hold_window_days=3, hold_windows={1: 2, 2: 1, 3: 1}, blind_hold_days=2,
                     lead_uncertain_bound="unwidened",
                     source="development out-of-fold panels")
UTTARAKHAND, KATRA = 23965166, 24605098
DAY = pd.Timestamp("2026-10-23")


@pytest.fixture(scope="module")
def fixture():
    context = json.loads((FIXTURE / "context.json").read_text(encoding="utf-8"))
    pooled = lv.Thresholds(**{k: context["thresholds"][k] for k in lv.THRESHOLD_NAMES}, source="run.json")
    thresholds = lv.RegionThresholds({r: lv.Thresholds(**{k: t[k] for k in lv.THRESHOLD_NAMES}, source=r)
                                      for r, t in context["thresholds_by_region"].items()}, pooled)
    return {"features": pd.read_parquet(FIXTURE / "features.parquet"),
            "published": pd.read_parquet(FIXTURE / "published.parquet"),
            "scores": pd.read_parquet(FIXTURE / "scores_2026-10-23.parquet"),
            "thresholds": thresholds, "config": AlertConfig.from_dict(context["alert_config"])}


@pytest.mark.skipif(not SHIPPED_RULES.is_file(), reason="the derived rules file is not on disk")
def test_the_rules_under_test_are_the_shipped_development_rules():
    assert pr.load_rules(SHIPPED_RULES) == replace(RULES, source=str(SHIPPED_RULES))


def _day_23(fx):
    features = fx["features"][fx["features"]["date"] == DAY].sort_values("cell_id").reset_index(drop=True)
    scores = fx["scores"].set_index("cell_id").loc[features["cell_id"]].reset_index(drop=True)
    engine = run_alerts(features, scores[["risk", "risk_lo", "risk_hi", "risk_per_100k"]], None,
                        thresholds=fx["thresholds"], config=fx["config"], hysteresis=False)
    return features, scores, engine


def test_the_engine_reproduces_the_published_levels_before_the_rules(fixture):
    _, _, engine = _day_23(fixture)
    assert engine["cell_id"].tolist() == [UTTARAKHAND, KATRA]
    assert engine["level_name"].tolist() == ["Warning", "Emergency"]
    assert engine["reason_codes"].tolist() == ["risk_above_warning", "risk_above_emergency"]
    assert engine["confidence"].tolist() == ["High", "High"]


def test_after_the_rules_both_dry_cells_are_capped_at_watch(fixture):
    features, scores, engine = _day_23(fixture)
    capped = pr.apply_post_rules(features, scores, engine, RULES, fixture["thresholds"])
    empty = live_run.previous_state(FIXTURE / "no_live_dir", DAY.date(), 30)         # 22 Oct has no run: no history
    no_rain = pr.previous_rain_ok(FIXTURE / "no_live_dir", DAY.date(), 30, RULES)
    level = pr.live_hysteresis(capped, empty, no_rain, fixture["thresholds"], fixture["config"], RULES)
    final = pr.mark_blind_holds(live_run.finalize_alerts(capped, level, np.zeros(2, dtype=bool)), np.zeros(2, dtype=bool))
    by_cell = final.set_index("cell_id")
    # 23965166: 7-day rain 0 mm < 11.5 mm, Warning capped to Watch; 0 of 20 members reach Warning -> Degraded
    assert by_cell.at[UTTARAKHAND, "level_name"] == "Watch"
    assert by_cell.at[UTTARAKHAND, "reason_codes"] == "risk_above_warning;no_recent_rain"
    assert by_cell.at[UTTARAKHAND, "confidence"] == "Degraded"
    assert by_cell.at[UTTARAKHAND, "confidence_causes"] == "ensemble_disagrees"
    # 24605098: Emergency capped to Watch (16 of 20 members agree, so confidence stays High)
    assert by_cell.at[KATRA, "level_name"] == "Watch"
    assert by_cell.at[KATRA, "reason_codes"] == "risk_above_emergency;no_recent_rain"
    assert by_cell.at[KATRA, "confidence"] == "High"
    # the re-centred interval holds the point, and the day passes the audit
    assert ((final["risk_lo"] <= final["risk"]) & (final["risk"] <= final["risk_hi"])).all()
    found = audit.audit_table(final.assign(date=DAY), 0, fixture["thresholds"], RULES, features, None, [])
    assert sum(found.counts.values()) == 0, found.to_dict()


def _outage(fixture, cell, hold_days, extra_missing=0):
    """The cell's published 17-19 Oct (scored) and the outage days 20, 21 Oct (+ `extra_missing` more) replayed with
    the blind-hold limit `hold_days`."""
    published = fixture["published"]
    rows = published[(published["cell_id"] == cell)].sort_values("date")
    rows = rows[rows["date"] <= pd.Timestamp("2026-10-21")][["cell_id", "date", "raw_level", "risk"]]
    for k in range(extra_missing):
        rows = pd.concat([rows, pd.DataFrame({"cell_id": [cell], "date": [pd.Timestamp("2026-10-22") + pd.Timedelta(days=k)],
                                              "raw_level": [np.int8(0)], "risk": [np.nan]})], ignore_index=True)
    features = fixture["features"]
    feats = features[(features["cell_id"] == cell) & (features["date"] <= pd.Timestamp("2026-10-21"))]
    rain = feats[["cell_id", "date"]].assign(rain_ok=RULES.rain.passes(feats))         # an outage day: unknown rain passes
    missing = rows[rows["date"] > pd.Timestamp("2026-10-21")][["cell_id", "date"]].assign(rain_ok=True)
    rain = pd.concat([rain, missing], ignore_index=True)
    rules = replace(RULES, blind_hold_days=hold_days)
    levels = []
    for i in range(3, len(rows) + 1):            # each day from 20 Oct as the live run would compute it
        history, today = rows.iloc[:i - 1], rows.iloc[i - 1:i].assign(region="himalaya", rain_ok=True)
        levels.append(int(pr.live_hysteresis(today, history, rain, fixture["thresholds"], fixture["config"], rules)[0]))
    return [lv.level_name(x) for x in levels]


def test_katra_was_published_at_emergency_through_the_outage(fixture):
    published = fixture["published"].set_index(["cell_id", "date"])
    for day in ("2026-10-17", "2026-10-18", "2026-10-19", "2026-10-20", "2026-10-21"):
        assert published.at[(KATRA, pd.Timestamp(day)), "level_name"] == "Emergency"
    assert published.at[(KATRA, pd.Timestamp("2026-10-20")), "reason_codes"] == "hysteresis_hold;model_input_missing"


def test_the_blind_hold_limit_lowers_an_outage_hold_one_level_per_day_after_h_days(fixture):
    # 19 Oct scored Emergency (7-day rain 64 mm passes); 20 Oct is day 1 without a score, 21 Oct day 2
    assert _outage(fixture, KATRA, hold_days=2) == ["Emergency", "Emergency", "Emergency"]     # 19, 20, 21 Oct
    assert _outage(fixture, KATRA, hold_days=2, extra_missing=2) == ["Emergency", "Emergency", "Emergency", "Warning",
                                                                     "Watch"]
    assert _outage(fixture, KATRA, hold_days=1) == ["Emergency", "Emergency", "Warning"]
    assert _outage(fixture, KATRA, hold_days=None, extra_missing=2) == ["Emergency"] * 5       # the old behaviour


def test_a_blind_hold_carries_its_code_and_stays_insufficient():
    alerts = pd.DataFrame({"cell_id": [1, 2], "raw_level": np.int8([0, 0]), "level": np.int8([3, 0]),
                           "reason_codes": ["hysteresis_hold;model_input_missing", "model_input_missing"],
                           "confidence": ["Insufficient", "Insufficient"],
                           "reasons_json": [json.dumps({"codes": []})] * 2})
    out = pr.mark_blind_holds(alerts, np.array([True, True]))
    assert out["reason_codes"].tolist() == ["hysteresis_hold;model_input_missing;held_while_blind", "model_input_missing"]
    assert json.loads(out["reasons_json"].iat[0])["codes"][-1] == "held_while_blind"
    assert out["confidence"].tolist() == ["Insufficient", "Insufficient"]
    assert pr.reason_text(pr.CODE_HELD_WHILE_BLIND, blind_hold_days=2).startswith("held while the model inputs are missing")


RERUN = Path(__file__).parent / "fixtures" / "false_alarms_2026-10-23_rerun"


def test_with_the_continuous_history_of_the_rerun_both_cells_end_at_watch(fixture):
    """The live days re-run oldest first with the rules (22 Oct included, so the hysteresis has its whole history):
    the hold of the reported Warning / Emergency is released once the rain rule fails within the level's hold window."""
    features = pd.read_parquet(RERUN / "features.parquet")
    published = pd.read_parquet(RERUN / "published.parquet")
    today = features[features["date"] == DAY].sort_values("cell_id").reset_index(drop=True)
    scores = pd.read_parquet(RERUN / "scores_2026-10-23.parquet").set_index("cell_id").loc[today["cell_id"]]
    scores = scores.reset_index(drop=True)
    engine = run_alerts(today, scores[["risk", "risk_lo", "risk_hi", "risk_per_100k"]], None,
                        thresholds=fixture["thresholds"], config=fixture["config"], hysteresis=False)
    capped = pr.apply_post_rules(today, scores, engine, RULES, fixture["thresholds"])
    history = published[published["date"] < DAY][["cell_id", "date", "raw_level", "risk"]]
    before = features[features["date"] < DAY]
    rain = before[["cell_id", "date"]].assign(rain_ok=RULES.rain.passes(before))
    level = pr.live_hysteresis(capped, history, rain, fixture["thresholds"], fixture["config"], RULES)
    assert [lv.level_name(x) for x in level] == ["Watch", "Watch"]
    on_23 = published[published["date"] == DAY].set_index("cell_id")
    assert on_23.loc[[UTTARAKHAND, KATRA], "level_name"].tolist() == ["Watch", "Watch"]
    assert on_23.loc[KATRA, "reason_codes"] == "risk_above_emergency;no_recent_rain"
    # Katra was released on 22 Oct already (7-day rain 4.7 mm; an Emergency hold needs rain on the day itself)
    assert published.set_index(["cell_id", "date"]).at[(KATRA, pd.Timestamp("2026-10-22")), "level_name"] == "Watch"
