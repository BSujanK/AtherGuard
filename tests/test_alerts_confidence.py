"""Data-confidence states and the blind-escalation rule on crafted rows."""
import numpy as np
import pytest

from aetherguard.alerts import confidence as cf
from alerts_helpers import CONFIG, feature_rows

NAN = np.nan


def assess(overrides, n_ood=None):
    frame = feature_rows(overrides)
    return cf.assess(frame, np.zeros(len(frame), dtype=int) if n_ood is None else n_ood, CONFIG)


def test_both_sources_valid_and_agreeing_is_high():
    out = assess([{}])
    assert out["confidence"].tolist() == [cf.HIGH] and out["causes"].tolist() == [""]
    assert not out["blind"].any()


def test_ratio_outside_the_development_range_degrades_without_a_station_to_agree():
    rows = [{"src_dis_ratio_3": 30.0, "integ_n_st_100km": 0.0, "integ_frac_trusted_100km": NAN, "integ_trw_rain_1": NAN},
            {"src_dis_ratio_3": 0.05, "integ_n_st_100km": 0.0, "integ_frac_trusted_100km": NAN, "integ_trw_rain_1": NAN}]
    out = assess(rows)
    assert out["confidence"].tolist() == [cf.DEGRADED, cf.DEGRADED]
    assert out["causes"].tolist() == ["sources_disagree", "sources_disagree"]


def test_an_agreeing_trusted_station_rescues_disagreeing_sources():
    out = assess([{"src_dis_ratio_3": 30.0, "rain_acc_1": 20.0, "integ_trw_rain_1": 21.0}])
    assert out["confidence"].tolist() == [cf.HIGH] and bool(out["station_agrees"].iloc[0])
    assert out["causes"].tolist() == [""]                   # High carries no cause (causes explain why not High)


def test_agreement_uses_an_absolute_floor_and_a_relative_band():
    near = assess([{"rain_acc_1": 0.0, "integ_trw_rain_1": 1.9}])        # within the 2 mm absolute floor
    far = assess([{"rain_acc_1": 0.0, "integ_trw_rain_1": 2.5, "src_dis_ratio_3": 30.0}])
    wet = assess([{"rain_acc_1": 100.0, "integ_trw_rain_1": 140.0, "src_dis_ratio_3": 30.0}])   # 40 <= 0.5*140
    wet_off = assess([{"rain_acc_1": 100.0, "integ_trw_rain_1": 250.0, "src_dis_ratio_3": 30.0}])
    assert near["station_agrees"].iloc[0] and not far["station_agrees"].iloc[0]
    assert wet["station_agrees"].iloc[0] and not wet_off["station_agrees"].iloc[0]


def test_one_missing_source_is_degraded_with_a_named_cause():
    rows = [{"src_imd_acc_1": NAN, "integ_trw_rain_1": NAN, "integ_n_st_100km": 0.0, "integ_frac_trusted_100km": NAN},
            {"src_chi_acc_1": NAN, "integ_trw_rain_1": NAN, "integ_n_st_100km": 0.0, "integ_frac_trusted_100km": NAN}]
    out = assess(rows)
    assert out["confidence"].tolist() == [cf.DEGRADED, cf.DEGRADED]
    assert out["causes"].tolist() == ["imd_missing", "chirps_missing"]


def test_no_valid_source_is_insufficient():
    out = assess([{"src_imd_acc_1": NAN, "src_chi_acc_1": NAN, "src_dis_ratio_3": NAN}])
    assert out["confidence"].tolist() == [cf.INSUFFICIENT] and "no_valid_source" in out["causes"].iloc[0]


def test_all_stations_untrusted_while_sources_disagree_is_insufficient_but_not_when_they_agree():
    bad = {"integ_frac_trusted_100km": 0.0, "integ_trw_rain_1": NAN, "integ_n_flagged_100km_7d": 2.0}
    out = assess([{**bad, "src_dis_ratio_3": 30.0}, {**bad}])
    assert out["confidence"].tolist() == [cf.INSUFFICIENT, cf.DEGRADED]
    assert "all_nearby_stations_untrusted" in out["causes"].iloc[0]


def test_nearby_flagged_station_or_ood_station_degrades_even_with_good_sources():
    out = assess([{"integ_n_flagged_100km_7d": 1.0}, {}], n_ood=np.array([0, 1]))
    assert out["confidence"].tolist() == [cf.DEGRADED, cf.DEGRADED]
    assert out["causes"].tolist() == ["stations_flagged_nearby", "station_out_of_distribution"]


def test_missing_station_columns_mean_no_station_information():
    frame = feature_rows([{}]).drop(columns=[c for c in feature_rows([{}]).columns if c.startswith("integ_")])
    out = cf.assess(frame, np.zeros(1, dtype=int), CONFIG)
    assert out["confidence"].tolist() == [cf.HIGH] and out["n_stations"].tolist() == [0]


# ------------------------------------------------------------------------------------------ blind escalation

NO_STATION = {"integ_n_st_100km": 0.0, "integ_frac_trusted_100km": NAN, "integ_trw_rain_1": NAN,
              "integ_trw_rain_3": NAN, "integ_max_st_rain_1_100km": NAN}


def test_blind_uses_the_maximum_of_the_sources_not_the_minimum():
    # IMD says 2 mm, CHIRPS says 80 mm: the sources disagree and the heavier one must escalate
    row = {**NO_STATION, "src_imd_acc_1": 2.0, "src_chi_acc_1": 80.0, "src_dis_ratio_3": 0.02, "rain_acc_1": 2.0}
    out = assess([row, {**row, "src_imd_acc_1": 80.0, "src_chi_acc_1": 2.0, "rain_acc_1": 80.0}])
    assert out["blind"].tolist() == [True, True]
    assert out["blind_codes"].tolist() == [cf.BLIND_SOURCES] * 2


def test_blind_fires_on_the_three_day_total_and_on_a_station_reading():
    sources = {"src_dis_ratio_3": 30.0, "integ_trw_rain_1": NAN}
    three = assess([{**sources, "src_imd_acc_3": 85.0}, {**sources, "src_chi_acc_3": 85.0}])
    station = assess([{**sources, "integ_max_st_rain_1_100km": 45.0, "integ_n_flagged_100km_7d": 1.0}])
    assert three["blind"].tolist() == [True, True] and station["blind"].tolist() == [True]


def test_not_blind_when_confidence_is_high_or_nothing_is_heavy():
    heavy_high = assess([{"src_imd_acc_1": 90.0, "src_chi_acc_1": 95.0, "rain_acc_1": 90.0, "integ_trw_rain_1": 92.0}])
    light_degraded = assess([{"src_dis_ratio_3": 30.0, "integ_trw_rain_1": NAN}])
    assert not heavy_high["blind"].iloc[0] and heavy_high["heavy_rain"].iloc[0]
    assert not light_degraded["blind"].iloc[0]


def test_blind_reason_codes_name_the_cause():
    sensors = assess([{"src_imd_acc_1": 90.0, "src_chi_acc_1": 90.0, "rain_acc_1": 90.0,
                       "integ_n_flagged_100km_7d": 3.0, "integ_trw_rain_1": NAN}])
    both = assess([{"src_imd_acc_1": 90.0, "src_chi_acc_1": 3.0, "rain_acc_1": 90.0, "src_dis_ratio_3": 30.0,
                    "integ_n_flagged_100km_7d": 3.0, "integ_trw_rain_1": NAN}])
    assert sensors["blind_codes"].tolist() == [cf.BLIND_SENSORS]
    assert both["blind_codes"].tolist() == [f"{cf.BLIND_SOURCES};{cf.BLIND_SENSORS}"]


def test_every_degraded_or_insufficient_row_has_a_cause_and_a_blind_code_when_blind():
    rows = [{"src_dis_ratio_3": 30.0, "integ_trw_rain_1": NAN, "src_imd_acc_3": 90.0},
            {"integ_n_flagged_100km_7d": 2.0, "src_chi_acc_3": 90.0},
            {"src_imd_acc_1": NAN, "src_chi_acc_1": NAN, "src_chi_acc_3": 90.0}]
    out = assess(rows)
    assert (out["causes"] != "").all() and (out["blind_codes"] != "").all()


def test_missing_required_columns_and_misaligned_n_ood_are_errors():
    frame = feature_rows([{}])
    with pytest.raises(ValueError, match="lacks columns"):
        cf.assess(frame.drop(columns=["src_dis_ratio_3"]), np.zeros(1, dtype=int), CONFIG)
    with pytest.raises(ValueError, match="n_ood"):
        cf.assess(frame, np.zeros(3, dtype=int), CONFIG)


# ------------------------------------------------------------------- second opinion of the newest due IMD day (live)

# The live run's IMD real-time file of day D is published about a day after D ends, so at the 11:00 IST run the second
# opinion is the newest IMD day that is due by then (normally D-1): the `chk_` columns hold that day's comparison.
TODAY_NOT_OUT = {"src_imd_acc_1": NAN, "src_imd_acc_3": NAN, "src_dis_ratio_3": NAN}
CHECK = {"chk_imd_acc_1": 4.0, "chk_imd_acc_3": 8.0, "chk_chi_acc_1": 4.5, "chk_chi_acc_3": 8.5, "chk_dis_ratio_3": 1.0,
         "chk_lag_days": 1.0, **NO_STATION}


def test_the_newest_due_imd_day_agreeing_gives_high_although_day_d_is_not_published_yet():
    out = assess([{**TODAY_NOT_OUT, **CHECK}])
    assert out["confidence"].tolist() == [cf.HIGH] and out["causes"].tolist() == [""]
    assert bool(out["imd_valid"].iloc[0])


def test_without_a_due_imd_day_the_second_opinion_is_missing():
    out = assess([{**TODAY_NOT_OUT, **CHECK, "chk_imd_acc_1": NAN, "chk_imd_acc_3": NAN, "chk_dis_ratio_3": NAN,
                   "chk_lag_days": NAN}])
    assert out["confidence"].tolist() == [cf.DEGRADED] and out["causes"].tolist() == ["imd_missing"]


def test_a_disagreeing_check_window_degrades():
    out = assess([{**TODAY_NOT_OUT, **CHECK, "chk_dis_ratio_3": 30.0}, {**TODAY_NOT_OUT, **CHECK, "chk_dis_ratio_3": 0.05}])
    assert out["confidence"].tolist() == [cf.DEGRADED, cf.DEGRADED]
    assert out["causes"].tolist() == ["sources_disagree", "sources_disagree"]


def test_the_check_columns_decide_the_source_test_and_the_heavy_rain_test_stays_on_day_d():
    # day D's own ratio is ignored once the check columns exist; the satellite of day D still has to be valid
    agree = assess([{**CHECK, "src_dis_ratio_3": 30.0}])
    no_satellite = assess([{**CHECK, "src_chi_acc_1": NAN, "src_chi_acc_3": NAN}])
    assert agree["confidence"].tolist() == [cf.HIGH]
    assert no_satellite["confidence"].tolist() == [cf.DEGRADED] and no_satellite["causes"].tolist() == ["chirps_missing"]
    # heavy rain on day D (satellite) with a disagreeing check window: blind, from the day-D evidence
    heavy = assess([{**TODAY_NOT_OUT, **CHECK, "chk_dis_ratio_3": 30.0, "src_chi_acc_1": 90.0, "rain_acc_1": 90.0}])
    assert heavy["blind"].tolist() == [True] and heavy["blind_codes"].tolist() == [cf.BLIND_SOURCES]
    # heavy rain only on the check day (IMD of D-1) does not escalate by itself
    old_heavy = assess([{**TODAY_NOT_OUT, **CHECK, "chk_dis_ratio_3": 30.0, "chk_imd_acc_1": 90.0}])
    assert old_heavy["blind"].tolist() == [False]


def test_check_columns_need_their_ratio():
    frame = feature_rows([{**CHECK}]).drop(columns=["chk_dis_ratio_3"])
    with pytest.raises(ValueError, match="chk_dis_ratio_3"):
        cf.assess(frame, np.zeros(1, dtype=int), CONFIG)
