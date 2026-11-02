"""Mathematical integrity checks of published live tables (live.audit_math): the identities hold on tables built with the
real feature functions, and each planted violation is counted under its check."""
import json
from datetime import date

import numpy as np
import pandas as pd

from audit_integrity_helpers import world
from aetherguard.live import audit, audit_math as am

DAY = date(2026, 10, 20)


def _found(table):
    return audit.Findings(len(table))


def _risk_table(n=6, **over):
    risk = np.linspace(1e-6, 1e-3, n)
    table = pd.DataFrame({"cell_id": np.arange(n) + 1, "date": pd.Timestamp(DAY), "lead": np.int8(0), "risk": risk,
                          "risk_lo": risk * 0.5, "risk_hi": risk * 2, "risk_per_100k": 1e5 * risk,
                          "level": np.int8([0, 0, 1, 1, 2, 3][:n]),
                          "level_name": np.array(["Normal", "Normal", "Watch", "Watch", "Warning", "Emergency"][:n], dtype=object)})
    table["level_min"], table["level_max"] = table["level"], table["level"]
    for column, value in over.items():
        table[column] = value
    return table


# ------------------------------------------------------------------------------------------- probability

def test_probability_accepts_a_valid_table_and_unscored_rows():
    table = _risk_table()
    table.loc[0, ["risk", "risk_lo", "risk_hi"]] = np.nan
    found = _found(table)
    am.check_probability(table, found)
    assert found.counts["probability"] == 0 and found.checked["probability"]


def test_probability_flags_each_planted_error():
    table = _risk_table()
    table.loc[0, "risk_hi"] = 1.5                                    # above 1
    table.loc[1, "risk"] = -1e-3                                     # negative
    table.loc[2, "risk"] = np.inf                                    # not finite
    table.loc[3, "level"] = np.int8(4)                               # level out of range
    table.loc[4, "level_name"] = "Watch"                             # name of another level
    table.loc[5, "level_min"] = np.int8(0); table.loc[5, "level_max"] = np.int8(2)      # fine
    table.loc[5, "level_max"] = np.int8(1)                           # level above level_max
    found = _found(table)
    am.check_probability(table, found)
    assert found.counts["probability"] == 6
    assert len(found.examples["probability"]) == 5               # capped at EXAMPLES


def test_probability_flags_a_bound_without_a_risk():
    table = _risk_table()
    table.loc[0, "risk"] = np.nan
    found = _found(table)
    am.check_probability(table, found)
    assert found.counts["probability"] == 1


# ------------------------------------------------------------------------------------------------- dates

def test_dates_match_the_run_date_plus_lead_and_the_file_lead():
    table = _risk_table(date=pd.Timestamp(DAY) + pd.Timedelta(days=2), lead=np.int8(2))
    found = _found(table)
    am.check_dates(table, DAY, 2, found)
    assert found.counts["dates"] == 0
    table.loc[0, "date"] = pd.Timestamp(DAY)
    table.loc[1, "lead"] = np.int8(1)
    table.loc[2, "cell_id"] = table.loc[3, "cell_id"]                # duplicate id
    found = _found(table)
    am.check_dates(table, DAY, 2, found)
    assert found.counts["dates"] == 4                               # wrong date, wrong lead, both duplicate rows


def test_cell_sets_and_positions_must_agree_across_tables():
    base = _risk_table().assign(lat=1.0, lon=2.0, region="himalaya")
    other = base.copy()
    other = other[other["cell_id"] != 3]                              # a missing cell
    other.loc[other["cell_id"] == 4, "lat"] = 1.05                    # a moved cell
    other.loc[other["cell_id"] == 5, "region"] = "western_ghats"
    other = pd.concat([other, base.iloc[[0]].assign(cell_id=99)])     # a cell the reference does not have
    founds = {"alerts": _found(base), "risk_D1": _found(other)}
    am.check_cell_sets({"alerts": base, "risk_D1": other}, founds)
    assert founds["alerts"].counts["dates"] == 0
    assert founds["risk_D1"].counts["dates"] == 4                    # 1 missing + 1 extra + lat + region


# ----------------------------------------------------------------------------------------------- rain_math

def test_rain_math_holds_on_tables_built_from_the_definitions():
    w = world()
    for lead, table in w["features"].items():
        found = _found(table)
        am.check_rain_math(table, found)
        assert found.counts["rain_math"] == 0, (lead, found.examples["rain_math"])
        assert found.checked["rain_math"]


def _planted(column, value, row=0):
    table = world()["features"][0].copy()
    table.loc[row, column] = value
    found = _found(table)
    am.check_rain_math(table, found)
    return found


def test_rain_math_flags_a_negative_accumulation():
    assert _planted("irain_acc_1", -1.0).counts["rain_math"] >= 1


def test_rain_math_flags_a_window_that_shrinks_or_is_known_inside_a_missing_one():
    table = world()["features"][0]
    row = int(np.flatnonzero(table["irain_acc_7"] > 1.0)[0])
    assert _planted("irain_acc_14", float(table.loc[row, "irain_acc_7"]) - 1.0, row=row).counts["rain_math"] >= 1
    assert _planted("irain_acc_3", np.nan, row=0).counts["rain_math"] >= 1


def test_rain_math_flags_a_maximum_above_its_total_or_longer_maximum():
    assert _planted("irain_max1d_7", 1e4).counts["rain_math"] >= 1
    assert _planted("irain_max1d_30", -1.0).counts["rain_math"] >= 1


def test_rain_math_flags_wet_days_outside_zero_to_thirty_or_fractional():
    assert _planted("irain_wetdays_30", 31).counts["rain_math"] >= 1
    assert _planted("irain_wetdays_30", 2.5).counts["rain_math"] >= 1


def test_rain_math_flags_a_wrong_share_and_a_share_where_it_must_be_missing():
    table = world()["features"][0]
    big = int(np.flatnonzero(table["irain_acc_3"] >= 1.0)[0])
    assert _planted("irain_share1_3", 0.987, row=big).counts["rain_math"] >= 1
    small = world(heavy=False)["features"][0]
    dry = small.copy()
    dry.loc[0, ["irain_acc_1", "irain_acc_3", "irain_acc_5", "irain_acc_7", "irain_acc_14", "irain_acc_30", "irain_acc_60",
                "irain_acc_90", "irain_max1d_7", "irain_max1d_30"]] = 0.5
    dry.loc[0, "irain_share1_3"] = 0.3
    found = _found(dry)
    am.check_rain_math(dry, found)
    assert found.counts["rain_math"] >= 1


def test_rain_math_flags_a_negative_anomaly_and_a_negative_api_and_api_order():
    assert _planted("irain_acc7_vs_clim", -0.1).counts["rain_math"] >= 1
    assert _planted("iapi_90", -1.0).counts["rain_math"] >= 1
    table = world()["features"][0]
    assert _planted("iapi_85", float(table.loc[0, "iapi_95"]) + 5.0).counts["rain_math"] >= 1


def test_rain_math_flags_days_since_heavy_rain_that_contradicts_the_maxima():
    table = world()["features"][0]
    row = int(np.flatnonzero(table["irain_max1d_7"] >= 10.0)[0])
    assert _planted("irain_days_since_10mm", 20, row=row).counts["rain_math"] >= 1
    assert _planted("irain_days_since_10mm", 91, row=row).counts["rain_math"] >= 1
    assert _planted("irain_days_since_10mm", 3.5, row=row).counts["rain_math"] >= 1


def test_rain_math_flags_a_neighbourhood_below_its_own_cell_or_mean_above_max():
    assert _planted("inbr_max_acc_1", -0.5).counts["rain_math"] >= 1
    table = world()["features"][0]
    assert _planted("inbr_mean_acc_3", float(table.loc[0, "inbr_max_acc_3"]) + 3.0).counts["rain_math"] >= 1


def test_rain_math_skips_columns_a_table_does_not_have():
    table = pd.DataFrame({"cell_id": [1, 2], "irain_acc_7": [3.0, 4.0]})
    found = _found(table)
    am.check_rain_math(table, found)
    assert found.counts["rain_math"] == 0


# ---------------------------------------------------------------------------------------------- rain_chain

def _chain(mutate=None):
    w = world()
    tables = {k: v.copy() for k, v in w["features"].items()}
    if mutate:
        mutate(tables)
    founds = {k: _found(t) for k, t in tables.items()}
    am.check_rain_chain(tables, founds)
    return founds


def test_the_lead_rain_chain_holds_on_tables_built_from_one_series():
    founds = _chain()
    assert all(f.counts["rain_chain"] == 0 for f in founds.values()), {k: f.examples["rain_chain"] for k, f in founds.items()}
    assert all(founds[k].checked["rain_chain"] for k in (1, 2, 3))


def test_the_chain_flags_a_one_day_rain_that_is_not_the_forecast_day():
    def mutate(t):
        t[2].loc[0, "irain_acc_1"] += 5.0
    assert _chain(mutate)[2].counts["rain_chain"] >= 1


def test_the_chain_flags_a_three_day_total_that_differs_from_the_days_it_is_made_of():
    def mutate(t):
        t[2].loc[1, "irain_acc_3"] += 2.0        # d1 + d2 + D0 acc_1
        t[3].loc[2, "irain_acc_3"] += 2.0        # d1 + d2 + d3
    founds = _chain(mutate)
    assert founds[2].counts["rain_chain"] >= 1 and founds[3].counts["rain_chain"] >= 1


def test_the_chain_flags_a_longer_window_outside_the_bounds_of_lead_zero():
    def mutate(t):
        t[3].loc[3, "irain_acc_90"] += 100.0
    assert _chain(mutate)[3].counts["rain_chain"] >= 1


def test_the_chain_flags_days_since_heavy_rain_that_ignores_the_forecast_days():
    def mutate(t):
        row = int(np.flatnonzero(t[2]["gfs_rain_d2"] >= 10.0)[0])
        t[2].loc[row, "irain_days_since_10mm"] = 5
    assert _chain(mutate)[2].counts["rain_chain"] >= 1


def test_the_chain_flags_a_date_that_is_not_the_run_date_plus_lead_is_left_to_dates():
    founds = _chain()
    assert founds[1].counts["dates"] == 0


def test_the_chain_needs_lead_zero_and_skips_without_it():
    w = world()
    tables = {1: w["features"][1]}
    founds = {1: _found(tables[1])}
    am.check_rain_chain(tables, founds)
    assert founds[1].counts["rain_chain"] == 0 and not founds[1].checked["rain_chain"]


# ------------------------------------------------------------------------------------------------- shap

COLUMNS = ["stat_elev_mean", "irain_acc_1", "irain_acc_14"]


def _shap_table(features):
    rows = []
    for _, f in features.iterrows():
        listed = [{"feature": c, "value": float(f[c]), "contribution": c_} for c, c_ in
                  zip(COLUMNS, (1.5, -0.7, 0.2))]
        rows.append(listed)
    table = pd.DataFrame({"cell_id": features["cell_id"].to_numpy(), "level": np.int8(1),
                          "level_name": "Watch", "risk": 1e-5, "risk_lo": 5e-6, "risk_hi": 2e-5,
                          "risk_per_100k": 1.0, "confidence": "Degraded", "confidence_causes": "x",
                          "reason_codes": "risk_above_watch"})
    table["shap_json"] = [json.dumps(r) for r in rows]
    table["reasons_json"] = [json.dumps({"level": "Watch", "codes": ["risk_above_watch"],
                                         "risk": {"point": 1e-5, "lo": 5e-6, "hi": 2e-5, "per_100k": 1.0}, "shap": r,
                                         "confidence": {"state": "Degraded", "causes": ["x"]}}) for r in rows]
    return table


def _shap_inputs():
    features = world(n=5)["features"][1].assign(stat_elev_mean=np.float32(100.0))
    return features, _shap_table(features)


def test_shap_accepts_sorted_contributions_that_match_the_features():
    features, table = _shap_inputs()
    found = _found(table)
    am.check_shap(table, features, COLUMNS, found)
    assert found.counts["shap"] == 0 and found.checked["shap"], found.examples["shap"]


def test_shap_flags_each_planted_error():
    features, table = _shap_inputs()
    listed = json.loads(table.loc[0, "shap_json"])
    table.loc[0, "shap_json"] = json.dumps(listed[::-1])                                  # not sorted by |contribution|
    listed = json.loads(table.loc[1, "shap_json"]); listed[0]["feature"] = "not_an_input"
    table.loc[1, "shap_json"] = json.dumps(listed)
    listed = json.loads(table.loc[2, "shap_json"]); listed[1]["value"] += 1.0             # value differs from the features
    table.loc[2, "shap_json"] = json.dumps(listed)
    reasons = json.loads(table.loc[3, "reasons_json"]); reasons["risk"]["point"] = 2e-5   # reasons disagree with the row
    table.loc[3, "reasons_json"] = json.dumps(reasons)
    reasons = json.loads(table.loc[4, "reasons_json"]); reasons["level"] = "Warning"
    table.loc[4, "reasons_json"] = json.dumps(reasons)
    found = _found(table)
    am.check_shap(table, features, COLUMNS, found)
    assert found.counts["shap"] == 5


def test_shap_requires_empty_contributions_exactly_where_there_is_no_score():
    features, table = _shap_inputs()
    table.loc[0, ["risk", "risk_lo", "risk_hi", "risk_per_100k"]] = np.nan
    found = _found(table)
    am.check_shap(table, features, COLUMNS, found)
    assert found.counts["shap"] >= 1                                  # unscored row still lists contributions
