"""Re-scoring of a published day with the model (live.audit_rescore): an end-to-end synthetic run, then tampered copies."""
import json
import shutil
from dataclasses import replace
from datetime import timedelta

import numpy as np
import pandas as pd
import pytest

from aetherguard.live import audit
from aetherguard.live import postrules as pr
from aetherguard.live import run as live_run

import live_run_helpers as H
from aetherguard.hazard.calibration import MonotoneCalibrator
from test_live_run_postrules import RULES


def smooth_model():
    """The test model with a calibrator that keeps risks inside (0, 0.6), so intervals are not all clipped to 0 or 1."""
    model = H.tiny_model()
    model.calibrator = MonotoneCalibrator([0.0, 1.0], [0.0, 0.6])
    return model


@pytest.fixture(scope="module")
def published(tmp_path_factory):
    cfg = H.make_cfg(tmp_path_factory.mktemp("rescore"))
    H.write_widening(live_run.project_path(cfg["forecast_widening"]), lo=0.5, hi=3.0)
    summary = live_run.run_day(H.DAY, cfg, deps=H.make_deps(H.healthy_sources(), model=smooth_model(), post_rules=RULES))
    return live_run.live_root(cfg) / H.DAY.isoformat(), summary


def _context():
    return audit.AuditContext(model=smooth_model(), rescore=True, model_columns=tuple(H.MODEL_COLUMNS),
                              alert_config=H.ALERT_CONFIG)


def _copy(published, tmp_path):
    target = tmp_path / H.DAY.isoformat()
    shutil.copytree(published[0], target)
    return target


def test_the_run_itself_rescored_its_day_without_a_difference(published):
    _, summary = published
    assert summary["audit"]["total_violations"] == 0, summary["audit"]
    assert summary["audit"]["rescore_seconds"] is not None


def test_a_published_day_is_reproduced_by_the_model_and_the_widening_factors_are_read_off(published):
    result = audit.audit_day(published[0], RULES, context=_context())
    assert result["total_violations"] == 0, {n: t["examples"] for n, t in result["tables"].items() if t["examples"]}
    assert result["rescore"]["ran"] and set(result["rescore"]["rows_scored"]) == {"alerts", "risk_D1", "risk_D2", "risk_D3"}
    assert result["rescore"]["factors"]["risk_D1"] == pytest.approx([0.5, 3.0])
    assert all(result["tables"][n]["checked"]["reproducible"] for n in ("alerts", "risk_D1"))


def test_a_changed_risk_bound_or_score_is_flagged(published, tmp_path):
    folder = _copy(published, tmp_path)
    alerts = pd.read_parquet(folder / "alerts.parquet")
    scored = int(np.flatnonzero(alerts["risk"].notna())[0])
    alerts.loc[scored, "risk"] *= 1.001
    alerts.to_parquet(folder / "alerts.parquet", index=False)
    lead = pd.read_parquet(folder / "risk_D2.parquet")
    row = int(np.flatnonzero(lead["risk"].notna())[1])
    lead.loc[row, "risk_hi"] = lead.loc[row, "risk_hi"] * 1.5
    lead.to_parquet(folder / "risk_D2.parquet", index=False)
    result = audit.audit_day(folder, RULES, context=_context())
    assert result["tables"]["alerts"]["violations"]["reproducible"] >= 1
    assert result["tables"]["risk_D2"]["violations"]["reproducible"] >= 1
    assert result["tables"]["risk_D1"]["violations"]["reproducible"] == 0


def test_a_score_on_a_row_with_missing_inputs_is_flagged(published, tmp_path):
    folder = _copy(published, tmp_path)
    features = pd.read_parquet(folder / "features_D0.parquet")
    features.loc[0, "irain_acc_3"] = np.nan
    features.to_parquet(folder / "features_D0.parquet", index=False)
    result = audit.audit_day(folder, RULES, context=_context())
    assert result["tables"]["alerts"]["violations"]["reproducible"] >= 1


def test_the_listed_contributions_must_be_the_models_largest(published, tmp_path):
    folder = _copy(published, tmp_path)
    alerts = pd.read_parquet(folder / "alerts.parquet")
    row = int(np.flatnonzero(alerts["risk"].notna())[0])
    listed = json.loads(alerts.loc[row, "shap_json"])
    listed[0]["contribution"] += 0.5
    alerts.loc[row, "shap_json"] = json.dumps(listed)
    alerts.to_parquet(folder / "alerts.parquet", index=False)
    result = audit.audit_day(folder, RULES, context=_context())
    assert result["tables"]["alerts"]["violations"]["shap"] >= 1


def test_without_a_model_the_rescore_is_skipped_with_a_note(published):
    result = audit.audit_day(published[0], RULES, context=audit.AuditContext(rescore=True))
    assert result["rescore"] == {"ran": False}
    assert any("reproducible is not checked" in n for n in result["tables"]["alerts"]["notes"])


# ------------------------------------------------------------------ uncertain_high from the unwidened bound

class StubModel:
    """Scores the rows by `risk` and `hi` columns of the frame: lets a test choose the unwidened interval."""
    columns = ["risk", "hi"]
    region_calibrator = None

    def score(self, frame):
        return pd.DataFrame({"risk": frame["risk"], "risk_lo": frame["risk"] / 2, "risk_hi": frame["hi"],
                             "risk_per_100k": 1e5 * frame["risk"], "member_median_risk": frame["risk"],
                             "ensemble_agreement": 1.0}, index=frame.index)


def _uncertain_inputs(bound_rule):
    from aetherguard.alerts import levels as lv
    thresholds = lv.Thresholds(0.2, 0.5, 0.8, "test")
    features = pd.DataFrame({"cell_id": [1, 2, 3, 4], "region": "himalaya", "risk": [0.05, 0.05, 0.05, 0.3],
                             "hi": [0.1, 0.1, 0.3, 0.9]})        # unwidened hi: below Watch, below Watch, above, above
    return thresholds, features, replace(RULES, lead_uncertain_bound=bound_rule), replace(H.ALERT_CONFIG, uncertain_percentile=90.0)


def _lead_table(uncertain):
    return pd.DataFrame({"cell_id": [1, 2, 3, 4], "risk": [0.05, 0.05, 0.05, 0.3], "uncertain_high": uncertain, "widened": True})


def _check(rule, uncertain, factor_hi=3.0):
    from aetherguard.live import audit_rescore as ar
    thresholds, features, rules, config = _uncertain_inputs(rule)
    found = audit.Findings(4)
    model, mask = StubModel(), np.ones(4, dtype=bool)
    ar.check_uncertain(model, _lead_table(uncertain), features, ar.rescore_table(model, features, mask), mask, 1, thresholds,
                       config, rules, (0.5, factor_hi), found)
    return found


def test_uncertain_high_follows_the_unwidened_bound_when_the_rules_say_unwidened():
    # unwidened hi 0.1 / 0.1 / 0.3 / 0.9 against Watch 0.2 (the point 0.3 is already at Watch)
    found = _check("unwidened", [False, False, True, False])
    assert found.counts["reproducible"] == 0 and found.checked["reproducible"]


def test_a_flag_computed_from_the_widened_bound_is_caught_under_the_unwidened_rule():
    # widened hi = 0.1 x 3 = 0.3 >= Watch: the aliasing bug flags cells 1 and 2 too
    found = _check("unwidened", [True, True, True, False])
    assert found.counts["reproducible"] == 2
    assert "uncertain_high" in found.examples["reproducible"][0]["why"]


def test_under_the_widened_rule_the_widened_flag_is_the_right_one():
    assert _check("widened", [True, True, True, False]).counts["reproducible"] == 0
    assert _check("widened", [False, False, True, False]).counts["reproducible"] == 2


def test_under_the_none_rule_no_interval_raises_a_level():
    assert _check("none", [False, False, False, False]).counts["reproducible"] == 0
    assert _check("none", [False, False, True, False]).counts["reproducible"] == 1


def test_a_published_uncertain_high_flag_that_the_unwidened_interval_does_not_give_is_flagged(published, tmp_path):
    folder = _copy(published, tmp_path)
    lead = pd.read_parquet(folder / "risk_D1.parquet")
    row = int(np.flatnonzero(lead["risk"].notna())[0])
    lead.loc[row, "uncertain_high"] = not bool(lead.loc[row, "uncertain_high"])
    lead.to_parquet(folder / "risk_D1.parquet", index=False)
    result = audit.audit_day(folder, RULES, context=_context())
    assert result["tables"]["risk_D1"]["violations"]["reproducible"] == 1
    assert "uncertain_high" in result["tables"]["risk_D1"]["examples"]["reproducible"][0]["why"]
    assert result["tables"]["risk_D2"]["violations"]["reproducible"] == 0
