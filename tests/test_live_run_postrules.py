"""The post-model rules inside the daily live run (live.run + live.postrules + live.audit, spec section 11)."""
import json
from dataclasses import replace
from datetime import timedelta

import numpy as np
import pandas as pd
import pytest

from aetherguard.alerts import levels as lv
from aetherguard.live import audit
from aetherguard.live import postrules as pr
from aetherguard.live import run as live_run

import live_run_helpers as H

# a 7-day minimum the light background rain (2 mm a day) never reaches, so only the heavy Wayanad cell passes
RULES = pr.PostRules(agreement_min=0.25, rain=pr.RainRule({7: 100.0}), gated_levels=(1, 2, 3), hold_window_days=3,
                     blind_hold_days=1, lead_uncertain_bound="unwidened", source="test")


def _run(cfg, day=H.DAY, sources=None, rules=RULES):
    now = H.NOW - timedelta(days=(H.DAY - day).days)
    return live_run.run_day(day, cfg, deps=H.make_deps(sources if sources is not None else H.healthy_sources(day),
                                                       now=lambda: now, post_rules=rules))


def _read(cfg, name, day=H.DAY):
    return pd.read_parquet(live_run.live_root(cfg) / day.isoformat() / name)


@pytest.fixture(scope="module")
def ruled(tmp_path_factory):
    cfg = H.make_cfg(tmp_path_factory.mktemp("ruled"))
    H.write_widening(live_run.project_path(cfg["forecast_widening"]))
    return cfg, _run(cfg)


def test_cells_without_recent_rain_are_capped_and_blind_or_wet_cells_are_not(ruled):
    cfg, _ = ruled
    alerts = _read(cfg, "alerts.parquet")
    features = _read(cfg, "features_D0.parquet").set_index("cell_id").loc[alerts["cell_id"]]
    assert alerts["rain_ok"].tolist() == (features["irain_acc_7"] >= 100.0).tolist()
    wayanad = alerts[alerts["rain_ok"]]
    assert len(wayanad) == 1 and wayanad["level"].iat[0] == 3                   # wet: untouched Emergency
    dry = alerts[~alerts["rain_ok"] & ~alerts["blind"]]
    assert dry["level"].isin([0, 1]).all()
    raised = dry["reason_codes"].str.contains("risk_above_|uncertain_high")
    assert dry.loc[raised, "reason_codes"].str.contains("no_recent_rain").all()
    for text in alerts["reasons_json"]:
        detail = json.loads(text)
        assert set(detail) >= {"ensemble", "rain_rule"}


def test_the_run_records_its_rules_and_a_clean_audit(ruled):
    cfg, summary = ruled
    assert summary["post_rules"] == {"source": "test", "parameters": RULES.to_dict()}
    assert summary["audit"]["total_violations"] == 0, summary["audit"]
    assert summary["audit"]["file"] == f"audit/{H.DAY}.json"
    written = json.loads((live_run.project_path(cfg["report_dir"]) / "audit" / f"{H.DAY}.json").read_text(encoding="utf-8"))
    assert written["total_violations"] == 0 and set(written["tables"]) == {"alerts", "risk_D0", "risk_D1", "risk_D2",
                                                                          "risk_D3"}
    assert set(summary["leads"]["0"]["post_rules"]) == {"no_recent_rain", "held_while_blind", "ensemble_disagrees"}
    text = (live_run.project_path(cfg["report_dir"]) / f"{H.DAY}.md").read_text(encoding="utf-8")
    assert "## Post-model rules and audit" in text and "no violation." in text
    # the stand-alone audit of the published day agrees
    assert audit.audit_day(live_run.live_root(cfg) / H.DAY.isoformat(), RULES)["total_violations"] == 0


def test_forecast_leads_are_never_high_and_carry_forecast_causes(ruled):
    cfg, _ = ruled
    for lead in (1, 2, 3):
        table = _read(cfg, f"risk_D{lead}.parquet")
        scored = table["risk"].notna()
        assert not (table["confidence"] == "High").any()
        assert (table.loc[scored, "confidence"] == "Degraded").all()
        assert table.loc[scored, "confidence_causes"].str.startswith("forecast_day;observed_through_d_").all()
        assert table.loc[scored, "confidence_causes"].str.endswith("forecast_widened").all()
        for text in table["reasons_json"]:
            assert {"ensemble", "rain_rule"} <= set(json.loads(text))


def test_the_forecast_bound_option_decides_uncertain_high(tmp_path):
    risk, hi, widened = np.array([1.0, 1.0]), np.array([2.0, 3.0]), np.array([8.0, 12.0])
    assert pr.lead_bound(replace(RULES, lead_uncertain_bound="widened"), risk, hi, widened).tolist() == [8.0, 12.0]
    assert pr.lead_bound(replace(RULES, lead_uncertain_bound="unwidened"), risk, hi, widened).tolist() == [2.0, 3.0]
    assert pr.lead_bound(replace(RULES, lead_uncertain_bound="none"), risk, hi, widened).tolist() == [1.0, 1.0]
    cfg = H.make_cfg(tmp_path)
    H.write_widening(live_run.project_path(cfg["forecast_widening"]), lo=0.5, hi=1e6)     # absurdly wide
    _run(cfg, rules=replace(RULES, gated_levels=(), rain=None, lead_uncertain_bound="none"))
    assert not any(_read(cfg, f"risk_D{lead}.parquet")["uncertain_high"].any() for lead in (1, 2, 3))


def test_a_blind_hold_lasts_h_days_then_drops_one_level_per_day(tmp_path):
    cfg = H.make_cfg(tmp_path)
    first, second = H.DAY - timedelta(days=2), H.DAY - timedelta(days=1)
    _run(cfg, first)
    assert H.wayanad_row(_read(cfg, "alerts.parquet", first))["level"] == 3
    for day in (second, H.DAY):                                                  # two days without IMERG Early: no score
        _run(cfg, day, H.healthy_sources(day, early_missing=True))
    held, lowered = (H.wayanad_row(_read(cfg, "alerts.parquet", d)) for d in (second, H.DAY))
    assert held["level"] == 3 and "held_while_blind" in held["reason_codes"]
    assert held["confidence"] == "Insufficient"
    assert lowered["level"] == 2 and "held_while_blind" in lowered["reason_codes"]   # H = 1: one level lower on day 2
    for day in (first, second, H.DAY):
        assert audit.audit_day(live_run.live_root(cfg) / day.isoformat(), RULES)["total_violations"] == 0


def test_rules_named_by_the_configuration_are_loaded_and_a_broken_file_is_an_error(tmp_path):
    path = tmp_path / "rules.json"
    pr.save_rules(path, RULES, {})
    assert live_run.load_post_rules({"post_rules": str(path)}, live_run.LiveDeps()) == replace(RULES, source=str(path))
    assert live_run.load_post_rules({}, live_run.LiveDeps()) is pr.NO_RULES
    path.write_text("{", encoding="utf-8")
    with pytest.raises(live_run.LiveRunError, match="cannot be loaded"):
        live_run.load_post_rules({"post_rules": str(path)}, live_run.LiveDeps())


def test_forecast_leads_carry_the_reason_codes_of_their_reasons_json(ruled):
    cfg, _ = ruled
    for lead in (1, 2, 3):
        table = _read(cfg, f"risk_D{lead}.parquet")
        assert "reason_codes" in table
        for codes, text in zip(table["reason_codes"], table["reasons_json"]):
            detail = json.loads(text)
            assert [c for c in codes.split(";") if c] == detail["codes"]
            assert ("no_recent_rain" in detail["codes"]) == bool(detail["rain_rule"]["capped"])


def test_forecast_codes_join_the_tier_the_uncertain_high_code_and_the_rule_codes():
    thresholds = lv.Thresholds(watch=0.1, warning=0.3, emergency=0.6, source="test")
    table = pd.DataFrame({"risk": [0.7, 0.2, np.nan], "uncertain_high": [False, True, False], "region": ["himalaya"] * 3})
    codes = live_run.forecast_codes(table, thresholds, ["no_recent_rain", "", ""])
    assert codes == ["risk_above_emergency;no_recent_rain", "risk_above_watch;uncertain_high", ""]
    assert live_run.forecast_codes(table, thresholds) == ["risk_above_emergency", "risk_above_watch;uncertain_high", ""]
