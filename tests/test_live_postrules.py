"""Post-model rules of the live alert levels: the rain trigger with its hold release and the ensemble-disagreement
confidence (live.postrules, spec section 11)."""
import json
from datetime import date

import numpy as np
import pandas as pd
import pytest

from aetherguard.alerts import levels as lv
from aetherguard.alerts.engine import run_alerts
from aetherguard.live import postrules as pr

from alerts_helpers import CONFIG, THRESHOLDS, feature_rows, scores_for

RAIN = pr.RainRule({3: 0.5, 7: 2.0})
RULES = pr.PostRules(agreement_min=0.25, rain=RAIN, gated_levels=(1, 2, 3), source="test")
WET = {"irain_acc_1": 4.0, "irain_acc_3": 9.0, "irain_acc_7": 20.0}
DRY = {"irain_acc_1": 0.0, "irain_acc_3": 0.0, "irain_acc_7": 0.0}


# ----------------------------------------------------------------------------------------------- the rules

def test_the_rain_rule_passes_when_any_window_reaches_its_minimum():
    frame = pd.DataFrame({"irain_acc_3": [0.6, 0.1, 0.1, np.nan, np.nan, 0.0],
                          "irain_acc_7": [0.0, 2.0, 1.9, 5.0, np.nan, np.nan]})
    assert RAIN.passes(frame).tolist() == [True, True, False, True, True, False]
    assert RAIN.describe() == "irain_acc_3 >= 0.5 mm OR irain_acc_7 >= 2 mm"
    with pytest.raises(ValueError, match="needs columns"):
        RAIN.passes(frame.drop(columns="irain_acc_7"))


@pytest.mark.parametrize("minimum", [{3: 0.0}, {3: -1.0}, {3: np.nan}, {}])
def test_a_rain_rule_needs_positive_minima(minimum):
    with pytest.raises(ValueError):
        pr.RainRule(minimum)


def test_post_rules_are_validated():
    with pytest.raises(ValueError, match="agreement_min"):
        pr.PostRules(agreement_min=0.0, rain=None)
    with pytest.raises(ValueError, match="need a rain rule"):
        pr.PostRules(agreement_min=None, rain=None, gated_levels=(2,))
    with pytest.raises(ValueError, match="Watch, Warning or Emergency"):
        pr.PostRules(agreement_min=None, rain=RAIN, gated_levels=(0,))
    with pytest.raises(ValueError, match="below itself"):
        pr.PostRules(agreement_min=None, rain=RAIN, gated_levels=(2,), cap=(0, 1, 2, 1))


def test_the_cap_applies_only_at_the_gated_levels():
    rules = pr.PostRules(agreement_min=None, rain=RAIN, gated_levels=(2, 3))
    assert rules.cap_array().tolist() == [0, 1, 1, 1]
    assert RULES.cap_array().tolist() == [0, 0, 1, 1]
    level, capped = pr.capped_levels([0, 1, 2, 3, 3], [False, False, False, False, True],
                                     [False, False, False, True, False], rules)
    assert level.tolist() == [0, 1, 1, 3, 3] and capped.tolist() == [False, False, True, False, False]


def test_rules_round_trip_through_their_file(tmp_path):
    path = tmp_path / "post_rules.json"
    pr.save_rules(path, RULES, {"note": "test"})
    loaded = pr.load_rules(path)
    assert loaded == pr.PostRules(agreement_min=0.25, rain=RAIN, gated_levels=(1, 2, 3), source=str(path))
    assert loaded.derivation == {"note": "test"}
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["parameters"]["gated_levels"] == ["Watch", "Warning", "Emergency"]
    payload["version"] = 99
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="version"):
        pr.load_rules(path)
    with pytest.raises(FileNotFoundError):
        pr.load_rules(tmp_path / "missing.json")


def test_disagreement_needs_a_warning_point_and_a_known_agreement_below_the_minimum():
    out = pr.disagrees([2, 3, 1, 2, 2], [0.2, 0.0, 0.0, 0.25, np.nan], RULES)
    assert out.tolist() == [True, True, False, False, False]
    assert not pr.disagrees([3], [0.0], pr.NO_RULES).any()


def test_reason_texts_name_the_number_of_members():
    assert pr.reason_text(pr.CAUSE_ENSEMBLE) == "most of the 20 ensemble models put this cell lower"
    assert pr.reason_text(pr.CAUSE_ENSEMBLE, 12) == "most of the 12 ensemble models put this cell lower"
    assert pr.reason_text("imd_missing") is None


# ---------------------------------------------------------------------------------------------- lead 0 table

def _engine(rows: list[dict], risk, agreement):
    features = feature_rows(rows, cell_id=np.arange(len(rows)) + 1, start="2024-07-01")
    features["date"] = pd.Timestamp("2024-07-01")
    scores = scores_for(features, risk).assign(member_median_risk=np.asarray(risk) / 10,
                                              ensemble_agreement=agreement)
    table = run_alerts(features, scores, None, thresholds=THRESHOLDS, config=CONFIG, hysteresis=False)
    return features, scores, table


def test_a_dry_warning_is_capped_to_watch_and_a_dry_watch_to_normal():
    rows = [DRY, DRY, WET, DRY]
    features, scores, table = _engine(rows, [5e-5, 2e-5, 5e-5, 1e-6], [1.0, 1.0, 1.0, 1.0])
    assert table["level"].tolist() == [2, 1, 2, 0]
    out = pr.apply_post_rules(features, scores, table, RULES, THRESHOLDS)
    assert out["level"].tolist() == [1, 0, 2, 0] and out["raw_level"].tolist() == [1, 0, 2, 0]
    assert out["level_name"].tolist() == ["Watch", "Normal", "Warning", "Normal"]
    assert out["rain_ok"].tolist() == [False, False, True, False]
    assert out["reason_codes"].tolist() == ["risk_above_warning;no_recent_rain", "risk_above_watch;no_recent_rain",
                                            "risk_above_warning", ""]
    detail = json.loads(out["reasons_json"].iat[0])
    assert detail["level"] == "Watch" and detail["codes"] == ["risk_above_warning", "no_recent_rain"]
    assert detail["rain_rule"] == {"passed": False, "exempt": False, "capped": True}
    assert detail["ensemble"] == {"median_risk": pytest.approx(5e-6), "agreement": 1.0}


def test_a_blind_escalated_cell_is_not_capped():
    heavy_imd = {**DRY, "src_imd_acc_1": 60.0, "src_chi_acc_1": np.nan, "integ_trw_rain_1": np.nan}   # Degraded, heavy IMD
    features, scores, table = _engine([heavy_imd], [1e-6], [1.0])
    assert table["blind"].tolist() == [True] and table["level"].tolist() == [1]
    out = pr.apply_post_rules(features, scores, table, RULES, THRESHOLDS)
    assert out["level"].tolist() == [1] and "no_recent_rain" not in out["reason_codes"].iat[0]
    assert json.loads(out["reasons_json"].iat[0])["rain_rule"] == {"passed": False, "exempt": True, "capped": False}


def test_ensemble_disagreement_caps_confidence_at_degraded_without_changing_the_level():
    features, scores, table = _engine([WET, WET, WET], [5e-5, 5e-5, 2e-5], [0.1, 0.5, 0.0])
    assert table["confidence"].tolist() == ["High"] * 3
    out = pr.apply_post_rules(features, scores, table, RULES, THRESHOLDS)
    assert out["level"].tolist() == table["level"].tolist() == [2, 2, 1]
    assert out["confidence"].tolist() == ["Degraded", "High", "High"]
    assert out["confidence_causes"].tolist() == ["ensemble_disagrees", "", ""]
    assert json.loads(out["reasons_json"].iat[0])["confidence"] == {"state": "Degraded", "causes": ["ensemble_disagrees"]}


def test_unscored_rows_get_no_ensemble_values_and_no_disagreement():
    features, scores, table = _engine([WET, WET], [5e-5, 5e-5], [0.0, 0.0])
    out = pr.apply_post_rules(features, scores, table, RULES, THRESHOLDS, scored=np.array([True, False]))
    assert out["ensemble_agreement"].isna().tolist() == [False, True]
    assert out["confidence_causes"].tolist() == ["ensemble_disagrees", ""]


def test_without_rules_only_the_columns_are_added():
    features, scores, table = _engine([DRY, WET], [5e-5, 5e-5], [0.0, 0.0])
    out = pr.apply_post_rules(features, scores, table, pr.NO_RULES, THRESHOLDS)
    for column in ("level", "raw_level", "confidence", "confidence_causes", "reason_codes"):
        assert out[column].tolist() == table[column].tolist()
    assert out["rain_ok"].tolist() == [True, True]


def test_the_rules_take_the_table_before_the_hysteresis_with_matching_rows():
    features, scores, table = _engine([WET], [5e-5], [1.0])
    with pytest.raises(ValueError, match="before the hysteresis"):
        pr.apply_post_rules(features, scores, table.assign(level=np.int8(3)), RULES, THRESHOLDS)
    with pytest.raises(ValueError, match="same rows"):
        pr.apply_post_rules(features.set_axis([7]), scores, table, RULES, THRESHOLDS)


def test_region_thresholds_decide_the_point_level_of_the_disagreement_rule():
    high = lv.Thresholds(1e-3, 2e-3, 3e-3, "high")
    regional = lv.RegionThresholds({"himalaya": high}, THRESHOLDS)
    features, scores, table = _engine([WET, WET], [5e-5, 5e-5], [0.0, 0.0])
    features["region"] = table["region"] = ["himalaya", "western_ghats"]
    out = pr.apply_post_rules(features, scores, table, RULES, regional)
    assert out["confidence_causes"].tolist() == ["", "ensemble_disagrees"]


# --------------------------------------------------------------------------------------------- hold release

def test_hold_release_needs_a_passing_day_inside_the_window():
    rain = pd.DataFrame({"cell_id": [1, 1, 1, 2], "date": pd.to_datetime(["2024-07-01", "2024-07-02", "2024-07-03",
                                                                           "2024-07-01"]),
                         "rain_ok": [True, False, False, False]})
    days = pd.to_datetime(["2024-07-03", "2024-07-04", "2024-07-03"])
    # cell 1: 07-01 passed, inside the 3-day window ending 07-03, outside the one ending 07-04; cell 2 never passed
    assert pr.hold_release([1, 1, 2], days, rain, 3).tolist() == [False, True, True]
    assert pr.hold_release([1], pd.to_datetime(["2024-07-03"]), rain, 1).tolist() == [True]


def _today(levels, risk, rain_ok, day="2024-07-03"):
    return pd.DataFrame({"cell_id": [1], "date": pd.to_datetime([day]), "region": ["western_ghats"],
                         "raw_level": np.array(levels, dtype=np.int8), "risk": risk, "rain_ok": rain_ok})


def _history(levels, risks, start="2024-07-01"):
    return pd.DataFrame({"cell_id": 1, "date": pd.date_range(start, periods=len(levels)),
                         "raw_level": np.array(levels, dtype=np.int8), "risk": risks})


def test_live_hysteresis_holds_only_while_the_window_saw_rain():
    history = _history([2, 1], [5e-5, 3.5e-5])                        # Warning, then held over a Watch raw level
    today = _today([1], [3.5e-5], [False])
    wet_before = pd.DataFrame({"cell_id": [1, 1], "date": pd.to_datetime(["2024-07-01", "2024-07-02"]),
                               "rain_ok": [True, False]})
    dry_before = wet_before.assign(rain_ok=False)
    assert pr.live_hysteresis(today, history, wet_before, THRESHOLDS, CONFIG, RULES).tolist() == [2]
    assert pr.live_hysteresis(today, history, dry_before, THRESHOLDS, CONFIG, RULES).tolist() == [1]
    # without a rain gate the hysteresis is the plain one
    assert pr.live_hysteresis(today, history, dry_before, THRESHOLDS, CONFIG, pr.NO_RULES).tolist() == [2]


def test_previous_rain_ok_reads_the_stored_features_of_consecutive_days(tmp_path):
    for day, acc3 in (("2024-07-02", 9.0), ("2024-07-01", 0.0)):
        folder = tmp_path / day
        folder.mkdir()
        pd.DataFrame({"cell_id": [1], "date": pd.to_datetime([day]), "irain_acc_3": [acc3],
                      "irain_acc_7": [acc3]}).to_parquet(folder / "features_D0.parquet")
    out = pr.previous_rain_ok(tmp_path, date(2024, 7, 3), 5, RULES)
    assert out["rain_ok"].tolist() == [True, False] and len(out) == 2
    assert pr.previous_rain_ok(tmp_path, date(2024, 7, 10), 5, RULES).empty


# -------------------------------------------------------------------------------------------- forecast leads

def test_lead_rules_cap_dry_leads_and_flag_disagreement():
    frame = pd.DataFrame({"region": ["western_ghats"] * 3, "irain_acc_3": [0.0, 9.0, 0.0], "irain_acc_7": [0.0, 9.0, 0.0]})
    scores = pd.DataFrame({"risk": [5e-5, 5e-5, 0.0], "ensemble_agreement": [1.0, 0.0, np.nan]})
    level, confidence, causes, codes = pr.apply_lead_rules(frame, scores, np.array([2, 2, 0], dtype=np.int8),
                                                           ["High", "High", "Insufficient"], ["", "", "x"], RULES,
                                                           THRESHOLDS, np.array([True, True, False]))
    assert level.tolist() == [1, 2, 0]
    assert confidence.tolist() == ["High", "Degraded", "Insufficient"]
    assert causes == ["", "ensemble_disagrees", "x"] and codes == ["no_recent_rain", "", ""]
