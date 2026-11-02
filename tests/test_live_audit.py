"""The consistency audit of published live rows (live.audit): synthetic day folders with planted violations."""
import json
from datetime import date

import numpy as np
import pandas as pd
import pytest

from aetherguard.live import audit
from aetherguard.live import postrules as pr

THRESHOLDS = {"watch": 1e-5, "warning": 4e-5, "emergency": 1e-4}
RULES = pr.PostRules(agreement_min=0.25, rain=pr.RainRule({7: 10.0}), gated_levels=(1, 2, 3), blind_hold_days=1)


def _row(cell, risk, level, raw=None, codes="", confidence="High", causes="", uncertain=False, blind=False, lo=None,
         hi=None):
    return {"cell_id": cell, "region": "himalaya", "risk": risk,
            "risk_lo": risk * 0.5 if lo is None else lo, "risk_hi": risk * 2 if hi is None else hi,
            "risk_per_100k": 1e5 * risk, "level": np.int8(level), "raw_level": np.int8(level if raw is None else raw),
            "confidence": confidence, "confidence_causes": causes, "reason_codes": codes, "uncertain_high": uncertain,
            "blind": blind}


def _write_day(root, day: str, rows: list[dict], acc7: dict | None = None, leads: dict | None = None) -> None:
    folder = root / day
    folder.mkdir(parents=True)
    alerts = pd.DataFrame(rows).assign(date=pd.Timestamp(day))
    alerts.to_parquet(folder / "alerts.parquet", index=False)
    alerts.drop(columns=["raw_level", "reason_codes", "blind"]).to_parquet(folder / "risk_D0.parquet", index=False)
    acc7 = acc7 or {}
    pd.DataFrame({"cell_id": alerts["cell_id"], "date": pd.Timestamp(day),
                  "irain_acc_7": [acc7.get(c, 50.0) for c in alerts["cell_id"]]}).to_parquet(folder / "features_D0.parquet")
    for lead, table in (leads or {}).items():
        table.to_parquet(folder / f"risk_D{lead}.parquet", index=False)
    summary = {"date": day, "model": {"thresholds": {**THRESHOLDS, "source": "test"},
                                      "thresholds_by_region": {"himalaya": {**THRESHOLDS, "source": "test"}}}}
    (folder / "run.json").write_text(json.dumps(summary), encoding="utf-8")


def test_a_consistent_day_has_no_violation(tmp_path):
    _write_day(tmp_path, "2026-10-23", [
        _row(1, 5e-5, 2, codes="risk_above_warning"),
        _row(2, 5e-6, 1, codes="uncertain_high", uncertain=True, hi=2e-5, confidence="Degraded", causes="imd_missing"),
        _row(3, 5e-5, 1, codes="risk_above_warning;no_recent_rain"),
        _row(4, 2e-4, 3, codes="risk_above_emergency", confidence="Degraded", causes="ensemble_disagrees")],
        acc7={3: 0.0})
    result = audit.audit_day(tmp_path / "2026-10-23", RULES)
    assert result["total_violations"] == 0, result["tables"]["alerts"]["examples"]


def test_each_planted_violation_is_counted_under_its_check(tmp_path):
    _write_day(tmp_path, "2026-10-23", [
        _row(1, 5e-5, 2, codes="risk_above_warning", lo=6e-5),                       # interval
        _row(2, 5e-5, 3, codes="risk_above_warning"),                                # level above the point, no code
        _row(3, 5e-5, 2, codes="risk_above_warning"),                                # dry Warning, not capped
        _row(4, 5e-5, 2, codes="risk_above_warning", confidence="Degraded"),         # Degraded without a cause
        _row(5, 5e-5, 2, codes="risk_above_warning", confidence="High", causes="x")],  # High with a cause
        acc7={3: 0.0})
    alerts = pd.read_parquet(tmp_path / "2026-10-23" / "alerts.parquet")
    alerts.loc[0, "risk_per_100k"] = 1.0                                             # per_100k on row 1
    alerts.to_parquet(tmp_path / "2026-10-23" / "alerts.parquet", index=False)
    result = audit.audit_day(tmp_path / "2026-10-23", RULES)
    v = result["violations"]
    assert (v["interval"], v["level"], v["rain_rule"], v["confidence"], v["per_100k"]) == (1, 1, 1, 2, 1)
    assert v["lead0_table"] == 1                     # risk_D0 still has the old per_100k of row 1


def test_without_gating_rules_the_rain_rule_is_not_checked(tmp_path):
    _write_day(tmp_path, "2026-10-23", [_row(1, 5e-5, 2, codes="risk_above_warning")], acc7={1: 0.0})
    result = audit.audit_day(tmp_path / "2026-10-23", pr.NO_RULES)
    assert result["total_violations"] == 0
    assert any("rain rule is not checked" in n for n in result["tables"]["alerts"]["notes"])


def test_a_hold_beyond_the_blind_limit_is_flagged(tmp_path):
    nan = np.nan
    _write_day(tmp_path, "2026-10-19", [_row(1, 2e-4, 3, codes="risk_above_emergency"),
                                        _row(2, 2e-4, 3, codes="risk_above_emergency")])
    blind = dict(confidence="Insufficient", causes="model_input_missing")
    _write_day(tmp_path, "2026-10-20", [
        _row(1, nan, 3, raw=0, codes="hysteresis_hold;model_input_missing;held_while_blind", **blind),
        _row(2, nan, 3, raw=0, codes="hysteresis_hold;model_input_missing;held_while_blind", **blind)])
    _write_day(tmp_path, "2026-10-21", [
        _row(1, nan, 3, raw=0, codes="hysteresis_hold;model_input_missing;held_while_blind", **blind),   # 2nd day: over
        _row(2, nan, 2, raw=0, codes="hysteresis_hold;model_input_missing", **blind)])                   # lowered, no code
    assert audit.audit_day(tmp_path / "2026-10-20", RULES)["violations"]["blind_hold"] == 0
    day21 = audit.audit_day(tmp_path / "2026-10-21", RULES)
    assert day21["violations"]["blind_hold"] == 2
    whys = [e["why"] for e in day21["tables"]["alerts"]["examples"]["blind_hold"]]
    assert whys[0] == "held at Emergency on day 2 without a score (limit 1 days, at most Warning)"
    assert whys[1] == "held while blind without the code held_while_blind"


def test_forecast_leads_are_checked_without_hysteresis(tmp_path):
    lead = pd.DataFrame([_row(1, 5e-5, 2), _row(2, 5e-5, 3)]).drop(columns=["raw_level", "reason_codes", "blind"])
    lead["reasons_json"] = [json.dumps({"codes": ["risk_above_warning"]})] * 2
    _write_day(tmp_path, "2026-10-23", [_row(1, 5e-5, 2, codes="risk_above_warning")], leads={1: lead})
    result = audit.audit_day(tmp_path / "2026-10-23", RULES)
    assert result["tables"]["risk_D1"]["violations"]["level"] == 1
    # both lead rows claim High (source agreement) for a day without observations
    assert result["tables"]["risk_D1"]["violations"]["forecast_confidence"] == 2
    assert result["tables"]["alerts"]["violations"]["forecast_confidence"] == 0
    assert any("features of lead 1" in n for n in result["tables"]["risk_D1"]["notes"])


def test_the_cli_writes_summaries_and_exits_two_on_violations(tmp_path, monkeypatch, capsys):
    live = tmp_path / "live"
    _write_day(live, "2026-10-22", [_row(1, 5e-5, 2, codes="risk_above_warning")])
    _write_day(live, "2026-10-23", [_row(1, 5e-5, 2, codes="risk_above_warning", lo=6e-5)])
    from aetherguard.live import run as live_run
    cfg = {**live_run.load_run_config(), "live_dir": str(live), "post_rules": None, "places_table": None, "basemap_file": None}
    monkeypatch.setattr(live_run, "load_run_config", lambda path=None: cfg)
    out = tmp_path / "audit"
    assert audit.main(["--date", "all", "--out", str(out)]) == audit.EXIT_VIOLATIONS
    assert sorted(p.name for p in out.iterdir()) == ["2026-10-22.json", "2026-10-23.json", "summary.json"]
    assert json.loads((out / "summary.json").read_text(encoding="utf-8"))["violations"]["interval"] == 1
    assert audit.main(["--date", "2026-10-22", "--out", str(out)]) == 0
    assert "2026-10-22: 2 rows, violations: none" in capsys.readouterr().out
    assert audit.published_days(live) == [date(2026, 10, 22), date(2026, 10, 23)]


def test_a_day_without_run_json_is_an_error(tmp_path):
    (tmp_path / "2026-10-23").mkdir()
    with pytest.raises(FileNotFoundError, match="not published"):
        audit.audit_day(tmp_path / "2026-10-23", RULES)


def test_a_dry_hold_is_allowed_only_as_the_release_of_a_higher_level(tmp_path):
    rules = pr.PostRules(agreement_min=None, rain=pr.RainRule({7: 10.0}), gated_levels=(1, 2, 3), hold_window_days=1)
    _write_day(tmp_path, "2026-10-22", [_row(1, 5e-5, 2, codes="risk_above_warning"),
                                        _row(2, 2e-5, 1, codes="risk_above_watch")])
    # 23 Oct dry: cell 1's Warning released to its cap (Watch) is fine; cell 2's Watch held without rain is not
    _write_day(tmp_path, "2026-10-23", [_row(1, 1e-6, 1, raw=0, codes="hysteresis_hold"),
                                        _row(2, 1e-6, 1, raw=0, codes="hysteresis_hold")], acc7={1: 0.0, 2: 0.0})
    result = audit.audit_day(tmp_path / "2026-10-23", rules)
    assert result["violations"]["rain_rule"] == 1
    assert result["tables"]["alerts"]["examples"]["rain_rule"][0]["cell_id"] == 2
