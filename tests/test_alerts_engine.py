"""run_alerts: levels, reasons completeness, hysteresis wiring, order independence and input checks."""
import json

import numpy as np
import pandas as pd
import pytest

from aetherguard.alerts import engine as eng
from aetherguard.alerts import levels as lv
from alerts_helpers import CONFIG, STATIONS, THRESHOLDS, feature_rows, scores_for, station_outputs


def alerts(frame, risk, stations_out=None, **kw):
    return eng.run_alerts(frame, scores_for(frame, risk, **{k: kw.pop(k) for k in ("hi", "lo") if k in kw}),
                          stations_out, stations=STATIONS if stations_out is not None else None,
                          thresholds=THRESHOLDS, config=CONFIG, **kw)


def test_levels_follow_the_thresholds_with_good_data():
    frame = feature_rows(n=4, cell_id=[1, 2, 3, 4])
    frame["date"] = pd.Timestamp("2024-07-01")
    out = alerts(frame, [1e-6, 1.2e-5, 5e-5, 2e-4], hi=[1.5e-6, 1.5e-5, 6e-5, 3e-4])
    assert out["level_name"].tolist() == ["Normal", "Watch", "Warning", "Emergency"]
    assert out["confidence"].eq("High").all() and not out["blind"].any()


def test_uncertain_high_gives_watch_with_its_reason():
    frame = feature_rows(n=1)
    out = alerts(frame, 5e-6, hi=2e-5)
    assert out["level_name"].tolist() == ["Watch"] and out["uncertain_high"].tolist() == [True]
    assert "uncertain_high" in out["reason_codes"].iloc[0]


def test_blind_escalation_lifts_a_normal_to_watch_and_names_the_rule():
    frame = feature_rows([{"src_imd_acc_1": 2.0, "src_chi_acc_1": 80.0, "src_dis_ratio_3": 0.02, "rain_acc_1": 2.0,
                           "integ_n_st_100km": 0.0, "integ_frac_trusted_100km": np.nan, "integ_trw_rain_1": np.nan}])
    out = alerts(frame, 1e-7)
    assert out["level_name"].tolist() == ["Watch"] and out["blind"].tolist() == [True]
    assert out["blind_escalated"].tolist() == [True]
    assert "sources_disagree_heavy_rain" in out["reason_codes"].iloc[0]


def test_blind_never_lowers_a_higher_hazard_level():
    frame = feature_rows([{"src_dis_ratio_3": 30.0, "src_imd_acc_3": 90.0, "integ_trw_rain_1": np.nan}])
    out = alerts(frame, 2e-4)
    assert out["level_name"].tolist() == ["Emergency"] and out["blind"].tolist() == [True]
    assert out["blind_escalated"].tolist() == [False]


def test_ood_station_near_a_cell_degrades_its_confidence_and_is_listed_in_the_trust_summary():
    outputs = station_outputs({"A": {"flag_every": 2, "fault_type": "stuck_value"}, "B": {}, "FAR": {}}, 120)
    frame = feature_rows(n=1, start="2024-04-20")
    out = alerts(frame, 1e-7, outputs)
    reasons = json.loads(out["reasons_json"].iloc[0])
    assert out["confidence"].tolist() == ["Degraded"] and out["n_ood_stations"].tolist() == [1]
    assert "station_out_of_distribution" in reasons["confidence"]["causes"]
    assert reasons["sensor_trust"]["n_out_of_distribution"] == 1


def test_reasons_are_complete_and_strict_json():
    frame = feature_rows(n=2, cell_id=[1, 2])
    frame["date"] = pd.Timestamp("2024-07-01")
    frame.loc[1, "integ_max_st_rain_1_100km"] = np.nan
    shap = [[{"feature": f"f{k}", "value": float(k), "contribution": 0.1 * k} for k in range(5)], [
        {"feature": "x", "value": None, "contribution": -0.2}]]
    out = alerts(frame, [2e-5, 1e-7], contributions=shap)
    for text in out["reasons_json"]:
        r = json.loads(text)
        assert set(r) == {"level", "raw_level", "codes", "risk", "confidence", "sources", "sensor_trust", "shap"}
        assert set(r["risk"]) == {"point", "lo", "hi", "per_100k"}
        assert set(r["confidence"]) == {"state", "causes"}
        assert {"imd_acc_1", "chirps_acc_1", "station_max_1", "max_1day", "spread_1day", "dis_ratio_3"} <= set(r["sources"])
        assert set(r["sensor_trust"]) == {"n_stations", "n_trusted", "n_flagged_7d", "n_out_of_distribution",
                                          "flagged_types"}
    first = json.loads(out["reasons_json"].iloc[0])
    assert len(first["shap"]) == 5 and first["shap"][0]["feature"] == "f0" and first["level"] == "Watch"
    assert first["risk"]["lo"] == pytest.approx(1e-5) and first["sources"]["spread_1day"] == pytest.approx(0.5)
    second = json.loads(out["reasons_json"].iloc[1])
    assert second["sources"]["station_max_1"] is None and second["sources"]["spread_1day"] == pytest.approx(0.5)
    assert json.loads(out["shap_json"].iloc[1])[0]["value"] is None


def test_hysteresis_holds_the_level_and_flags_the_hold():
    frame = feature_rows(n=5)
    risk = [5e-5, 2e-5, 2e-5, 2e-5, 2e-5]
    held, raw_only = alerts(frame, risk), alerts(frame, risk, hysteresis=False)
    assert held["level"].tolist() == [2, 2, 1, 1, 1] and raw_only["level"].tolist() == [2, 1, 1, 1, 1]
    assert held["raw_level"].tolist() == raw_only["raw_level"].tolist()
    assert "hysteresis_hold" in held["reason_codes"].iloc[1] and "hysteresis_hold" not in held["reason_codes"].iloc[0]


def test_rows_may_arrive_in_any_order_and_keep_their_order():
    frame = feature_rows(n=6)
    risk = np.array([5e-5, 2e-5, 2e-5, 1e-7, 1e-7, 1e-7])
    base = alerts(frame, risk)
    perm = np.array([4, 0, 5, 2, 1, 3])
    shuffled = alerts(frame.iloc[perm], risk[perm])
    assert shuffled["date"].tolist() == frame["date"].iloc[perm].tolist()
    assert shuffled.sort_values("date")["level"].tolist() == base["level"].tolist()


def test_carried_columns_and_evidence_are_present():
    frame = feature_rows(n=1)
    frame["split"], frame["weight"] = "test_2018", 123.0
    out = alerts(frame, 1e-6)
    assert out["region"].iloc[0] == "western_ghats" and out["weight"].iloc[0] == 123.0
    assert out["imd_acc_1"].iloc[0] == 5.0 and out["station_max_1"].iloc[0] == 5.5


def test_input_validation():
    frame = feature_rows(n=2)
    good = scores_for(frame, 1e-6)
    with pytest.raises(ValueError, match="station coordinates"):
        eng.run_alerts(frame, good, station_outputs({"A": {}}, 5), thresholds=THRESHOLDS, config=CONFIG)
    with pytest.raises(ValueError, match="same rows"):
        eng.run_alerts(frame, good.iloc[:1], None, thresholds=THRESHOLDS, config=CONFIG)
    with pytest.raises(ValueError, match="non-finite"):
        eng.run_alerts(frame, good.assign(risk=np.nan), None, thresholds=THRESHOLDS, config=CONFIG)
    with pytest.raises(ValueError, match="lacks columns|scores lack"):
        eng.run_alerts(frame, good.drop(columns=["risk_hi"]), None, thresholds=THRESHOLDS, config=CONFIG)
    with pytest.raises(ValueError, match="contributions"):
        eng.run_alerts(frame, good, None, thresholds=THRESHOLDS, config=CONFIG, contributions=[[]])
    with pytest.raises(ValueError, match="lacks column 'lat'"):
        eng.run_alerts(frame.drop(columns=["lat"]), good, None, thresholds=THRESHOLDS, config=CONFIG)


def test_thresholds_by_region_decide_each_cells_level_codes_and_steps():
    ghats = lv.Thresholds(watch=4e-5, warning=8e-5, emergency=2e-4, source="ghats")
    regional = lv.RegionThresholds({"western_ghats": ghats}, pooled=THRESHOLDS)
    frame = feature_rows(n=2, cell_id=[1, 2])
    frame["date"] = pd.Timestamp("2024-07-01")
    frame["region"] = ["himalaya", "western_ghats"]
    scores = scores_for(frame, 3e-5, hi=3.5e-5)
    out = eng.run_alerts(frame, scores, None, thresholds=regional, config=CONFIG)
    assert out["level_name"].tolist() == ["Watch", "Normal"]                 # 3e-5 is Watch at the pooled 1e-5, below 4e-5
    assert "risk_above_watch" in out["reason_codes"].iloc[0] and out["reason_codes"].iloc[1] == ""
    assert out["uncertain_high"].tolist() == [False, False]
    # a risk path of 9e-5, 5e-5, 5e-5: Warning then Watch for the ghats cell (its Warning is 8e-5, held until two days
    # below 0.8 x 8e-5), Warning throughout for the cell on the pooled thresholds (their Warning is 4e-5)
    rows = feature_rows(n=3, cell_id=[1, 1, 1])
    rows["region"] = "western_ghats"
    held = eng.run_alerts(rows, scores_for(rows, [9e-5, 5e-5, 5e-5], hi=[9e-5, 5e-5, 5e-5]), None, thresholds=regional,
                          config=CONFIG)
    assert held["level_name"].tolist() == ["Warning", "Warning", "Watch"]
    rows["region"] = "himalaya"
    plain = eng.run_alerts(rows, scores_for(rows, [9e-5, 5e-5, 5e-5], hi=[9e-5, 5e-5, 5e-5]), None, thresholds=regional,
                           config=CONFIG)
    assert plain["level_name"].tolist() == ["Warning", "Warning", "Warning"]


def test_thresholds_by_region_need_the_region_column():
    frame = feature_rows(n=1).drop(columns="region")
    with pytest.raises(ValueError, match="region"):
        eng.run_alerts(frame, scores_for(frame, 1e-5), None, thresholds=lv.RegionThresholds({}, THRESHOLDS), config=CONFIG)


def test_the_uncertain_high_bound_follows_the_configured_percentile():
    from dataclasses import replace
    frame = feature_rows(n=1)
    scores = scores_for(frame, 5e-6, hi=2e-5).assign(risk_p75=8e-6)                 # Watch is 1e-5
    run = lambda config, s=scores: eng.run_alerts(frame, s, None, thresholds=THRESHOLDS, config=config)
    assert run(CONFIG)["uncertain_high"].tolist() == [True]                          # the 90th percentile (risk_hi) reaches Watch
    assert run(replace(CONFIG, uncertain_percentile=75.0))["uncertain_high"].tolist() == [False]
    assert run(replace(CONFIG, uncertain_percentile=75.0), scores.assign(risk_p75=1.5e-5))["uncertain_high"].tolist() == [True]
    off = run(replace(CONFIG, uncertain_percentile=None))
    assert off["uncertain_high"].tolist() == [False] and off["level_name"].tolist() == ["Normal"]
    with pytest.raises(ValueError, match="risk_p75"):
        run(replace(CONFIG, uncertain_percentile=75.0), scores.drop(columns="risk_p75"))
