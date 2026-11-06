"""Alert levels, the card threshold adapter and hysteresis (tiny hand-made sequences)."""
import logging

import numpy as np
import pandas as pd
import pytest

from aetherguard.alerts import levels as lv

T = lv.Thresholds(watch=1e-5, warning=4e-5, emergency=1e-4, source="test")
FALLBACK = {"watch": {"recall": 0.9}, "warning": {"fa_share": 0.05}, "emergency": {"fa_share": 0.01}}
V1_CARD = {"operating_points_validation": {
    "recall": {"0.9": {"risk": 1.4e-5}, "0.8": {"risk": 1.9e-5}},
    "fa_share": {"0.05": {"risk": 3.7e-5}, "0.01": {"risk": 1.1e-4}}}}


def test_level_mapping_is_inclusive_at_each_threshold():
    risk = [0.0, 9.9e-6, 1e-5, 3.9e-5, 4e-5, 9.9e-5, 1e-4, 0.5]
    assert lv.level_from_risk(risk, T).tolist() == [0, 0, 1, 1, 2, 2, 3, 3]


def test_equal_thresholds_collapse_levels_without_error():
    same = lv.Thresholds(1e-5, 1e-5, 1e-4, "test")
    assert lv.level_from_risk([1e-5], same).tolist() == [2]


def test_uncertain_high_raises_only_the_level_below_watch():
    raw, uncertain = lv.raw_level([5e-6, 5e-6, 2e-5, 5e-6], [2e-5, 9e-6, 2e-5, 1e-5], T)
    assert raw.tolist() == [1, 0, 1, 1]
    assert uncertain.tolist() == [True, False, False, True]


def test_nan_risk_reaches_no_level():
    assert lv.level_from_risk([np.nan], T).tolist() == [0]


@pytest.mark.parametrize("bad", [(0.0, 1.0, 2.0), (2e-5, 1e-5, 1e-4), (1e-5, 4e-5, np.nan)])
def test_invalid_thresholds_are_rejected(bad):
    with pytest.raises(ValueError):
        lv.Thresholds(*bad, source="x")


def test_parse_level_accepts_names_numbers_and_rejects_others():
    assert lv.parse_level("warning") == 2 and lv.parse_level(3) == 3 and lv.parse_level("1") == 1
    for bad in ("severe", 4, -1):
        with pytest.raises(ValueError):
            lv.parse_level(bad)


def test_named_card_thresholds_are_read_by_name_in_any_case(caplog):
    card = {"alert_thresholds": {"Watch": {"risk": 2e-5}, "WARNING": 5e-5, "emergency": {"risk": 2e-4}}}
    with caplog.at_level(logging.INFO, logger="aetherguard.alerts.levels"):
        out = lv.thresholds_from_card(card, FALLBACK)
    assert (out.watch, out.warning, out.emergency) == (2e-5, 5e-5, 2e-4)
    assert out.source == "card.alert_thresholds"
    assert "card.alert_thresholds" in caplog.text


def test_protocol_v2_card_block_is_found_and_the_first_named_block_wins():
    v2 = {"alert_levels": {"watch": {"risk": 4e-6, "oof_recall": 0.9}, "warning": {"risk": 1.6e-5},
                           "emergency": {"risk": 3.7e-5}},
          "thresholds_oof": {"watch": {"risk": 9e-6}, "warning": {"risk": 2e-5}, "emergency": {"risk": 4e-5},
                             "plain_recall_90": {"risk": 5e-6}}}
    out = lv.thresholds_from_card(v2, FALLBACK)
    assert (out.watch, out.warning, out.emergency) == (4e-6, 1.6e-5, 3.7e-5) and out.source == "card.alert_levels"
    only_oof = lv.thresholds_from_card({"thresholds_oof": v2["thresholds_oof"]}, FALLBACK)
    assert only_oof.source == "card.thresholds_oof" and only_oof.watch == 9e-6


def test_v1_card_falls_back_to_its_named_operating_points(caplog):
    with caplog.at_level(logging.INFO, logger="aetherguard.alerts.levels"):
        out = lv.thresholds_from_card(V1_CARD, FALLBACK)
    assert (out.watch, out.warning, out.emergency) == (1.4e-5, 3.7e-5, 1.1e-4)
    assert out.source.startswith("v1_card_fallback") and "v1_card_fallback" in caplog.text


def test_card_without_any_usable_thresholds_raises():
    with pytest.raises(ValueError, match="operating_points_validation"):
        lv.thresholds_from_card({}, FALLBACK)
    with pytest.raises(ValueError, match="no numeric risk"):
        lv.thresholds_from_card({"thresholds": {"watch": "x", "warning": 1, "emergency": 2}}, FALLBACK)
    with pytest.raises(ValueError, match="available"):
        lv.thresholds_from_card(V1_CARD, {**FALLBACK, "emergency": {"fa_share": 0.5}})


def _run(raw, risk, cells=None, days=None, **kw):
    n = len(raw)
    cells = np.zeros(n, dtype=int) if cells is None else np.asarray(cells)
    days = pd.date_range("2024-07-01", periods=n) if days is None else pd.DatetimeIndex(days)
    return lv.apply_hysteresis(cells, days, raw, risk, T, kw.get("exit_factor", 0.8), kw.get("exit_days", 2)).tolist()


def test_steps_up_immediately_and_down_after_two_qualifying_days():
    # Warning on day 1; then raw drops to Watch with risk below 0.8 * warning threshold (3.2e-5)
    out = _run([2, 1, 1, 1, 1], [5e-5, 2e-5, 2e-5, 2e-5, 2e-5])
    assert out == [2, 2, 1, 1, 1]


def test_risk_between_exit_threshold_and_threshold_holds_the_level_and_resets_the_streak():
    # day 2 qualifies (3e-5 < 3.2e-5), day 3 does not (3.5e-5), so the streak restarts
    out = _run([2, 1, 1, 1, 1], [5e-5, 3e-5, 3.5e-5, 3e-5, 3e-5])
    assert out == [2, 2, 2, 2, 1]


def test_steps_down_one_level_per_streak():
    out = _run([3, 0, 0, 0, 0, 0], [2e-4, 1e-6, 1e-6, 1e-6, 1e-6, 1e-6])
    assert out == [3, 3, 2, 2, 1, 1]


def test_normal_is_reached_after_the_last_step():
    out = _run([1, 0, 0, 0], [2e-5, 1e-6, 1e-6, 1e-6])
    assert out == [1, 1, 0, 0]


def test_step_up_resets_a_running_streak():
    out = _run([2, 1, 2, 1, 1], [5e-5, 2e-5, 5e-5, 2e-5, 2e-5])
    assert out == [2, 2, 2, 2, 1]


def test_a_gap_in_the_dates_restarts_the_state_at_the_raw_level():
    days = ["2024-07-01", "2024-07-02", "2024-07-05"]
    assert _run([2, 2, 0], [5e-5, 5e-5, 1e-7], days=days) == [2, 2, 0]


def test_cells_are_independent_and_row_order_does_not_matter():
    raw = [2, 0, 0, 0, 0, 0]
    risk = [5e-5, 1e-7, 1e-7, 1e-7, 1e-7, 1e-7]
    cells = [1, 1, 1, 2, 2, 2]
    days = pd.to_datetime(["2024-07-01", "2024-07-02", "2024-07-03"] * 2)
    base = _run(raw, risk, cells, days)
    perm = np.array([5, 2, 0, 4, 1, 3])
    shuffled = _run(np.array(raw)[perm], np.array(risk)[perm], np.array(cells)[perm], days[perm])
    assert base == [2, 2, 1, 0, 0, 0]
    assert np.array(shuffled)[np.argsort(perm)].tolist() == base


def test_duplicate_cell_day_is_an_error():
    with pytest.raises(ValueError, match="duplicate"):
        _run([1, 1], [2e-5, 2e-5], cells=[1, 1], days=["2024-07-01", "2024-07-01"])


def test_invalid_hysteresis_parameters_are_rejected():
    with pytest.raises(ValueError):
        _run([1], [2e-5], exit_days=0)
    with pytest.raises(ValueError):
        _run([1], [2e-5], exit_factor=1.5)


def test_empty_input_gives_empty_output():
    assert _run([], []) == []


# ------------------------------------------------------------------------------------- thresholds by region

GHATS = lv.Thresholds(watch=4e-5, warning=8e-5, emergency=2e-4, source="ghats")
REGIONAL = lv.RegionThresholds({"himalaya": T, "western_ghats": GHATS}, pooled=lv.Thresholds(2e-5, 6e-5, 1.5e-4, "pooled"))
REGIONAL_CARD = {"alert_levels": {
    "watch": {"risk": 3.0e-6, "risk_by_region": {"himalaya": 2.8e-6, "western_ghats": 3.8e-6}},
    "warning": {"risk": 1.2e-5, "risk_by_region": {"himalaya": 1.4e-5, "western_ghats": 1.37e-5}},
    "emergency": {"risk": 4.8e-5, "risk_by_region": {"himalaya": 4.9e-5, "western_ghats": 2.6e-5}}}}


def test_card_region_thresholds_follow_the_card_and_fall_back_to_the_pooled_risk():
    by_region = lv.card_region_thresholds(REGIONAL_CARD, ["himalaya", "western_ghats", "himalaya"])
    assert set(by_region) == {"himalaya", "western_ghats"} and by_region["western_ghats"].watch == 3.8e-6
    assert by_region["himalaya"].as_array().tolist() == [2.8e-6, 1.4e-5, 4.9e-5]
    plain = {"alert_levels": {k: {"risk": v} for k, v in zip(("watch", "warning", "emergency"), (1.0, 2.0, 3.0))}}
    assert lv.card_region_thresholds(plain, ["x"])["x"].as_array().tolist() == [1.0, 2.0, 3.0]
    partial = lv.card_region_thresholds(REGIONAL_CARD, ["himalaya", "terai"])
    assert partial["terai"].as_array().tolist() == [3.0e-6, 1.2e-5, 4.8e-5]            # a region the card lacks: pooled


def test_region_thresholds_look_up_a_region_and_use_the_pooled_ones_for_any_other():
    assert REGIONAL.of("western_ghats") is GHATS
    assert REGIONAL.of("terai") is REGIONAL.pooled and REGIONAL.of(np.nan) is REGIONAL.pooled
    matrix = REGIONAL.matrix(["himalaya", "terai", "western_ghats", None])
    assert matrix.shape == (4, 3)
    assert matrix[0].tolist() == T.as_array().tolist() and matrix[2].tolist() == GHATS.as_array().tolist()
    assert matrix[1].tolist() == matrix[3].tolist() == REGIONAL.pooled.as_array().tolist()


def test_region_thresholds_describe_themselves():
    described = REGIONAL.to_dict()
    assert sorted(described) == ["himalaya", "western_ghats"] and described["western_ghats"]["watch"] == 4e-5
    assert described["himalaya"]["source"] == "test"


def test_levels_by_region_use_each_rows_own_thresholds():
    risk = [3e-5, 3e-5, 3e-5, 9e-5, 3e-5]
    region = ["himalaya", "western_ghats", "terai", "western_ghats", None]
    # himalaya Watch at 1e-5 (Watch, risk < 4e-5), ghats Watch at 4e-5 (Normal), pooled Watch at 2e-5 (Watch)
    assert lv.level_from_risk(risk, REGIONAL, region).tolist() == [1, 0, 1, 2, 1]
    raw, uncertain = lv.raw_level(risk[:2], [5e-5, 5e-5], REGIONAL, region[:2])
    assert raw.tolist() == [1, 1] and uncertain.tolist() == [False, True]           # ghats: point below, upper bound at Watch


def test_region_thresholds_need_the_regions_of_the_rows():
    with pytest.raises(ValueError, match="region"):
        lv.level_from_risk([1e-5], REGIONAL)
    with pytest.raises(ValueError, match="region"):
        lv.level_from_risk([1e-5, 1e-5], REGIONAL, ["himalaya"])


def test_hysteresis_by_region_matches_running_each_region_on_its_own_thresholds():
    raw = np.array([2, 1, 1, 1, 1] * 2)
    risk = np.array([1e-4, 5e-5, 5e-5, 5e-5, 5e-5] * 2)          # above 0.8 x Warning of himalaya (3.2e-5), below ghats' (6.4e-5)
    cells = np.repeat([1, 2], 5)
    days = pd.DatetimeIndex(list(pd.date_range("2024-07-01", periods=5)) * 2)
    region = np.repeat(["himalaya", "western_ghats"], 5)
    both = lv.apply_hysteresis(cells, days, raw, risk, REGIONAL, 0.8, 2, region)
    alone = [lv.apply_hysteresis(cells[s], days[s], raw[s], risk[s], t, 0.8, 2)
             for s, t in ((slice(0, 5), T), (slice(5, 10), GHATS))]
    assert both.tolist() == np.concatenate(alone).tolist()
    assert both[:5].tolist() == [2, 2, 2, 2, 2] and both[5:].tolist() == [2, 2, 1, 1, 1]


def test_scalar_thresholds_ignore_the_region_argument():
    risk = [2e-5, 2e-5]
    assert lv.level_from_risk(risk, T, ["himalaya", "western_ghats"]).tolist() == lv.level_from_risk(risk, T).tolist()


# ----------------------------------------------------------------------------------------- hold release

CAP = [0, 0, 1, 1]                      # Watch -> Normal, Warning / Emergency -> Watch (the rain trigger's cap)


def _release(raw, risk, release, cap=CAP, **kw):
    n = len(raw)
    return lv.apply_hysteresis(np.zeros(n, dtype=int), pd.date_range("2024-07-01", periods=n), raw, risk, T,
                               kw.get("exit_factor", 0.8), kw.get("exit_days", 2), None, release, cap).tolist()


def test_without_release_flags_the_hold_is_unchanged():
    raw, risk = [2, 1, 1, 1, 1], [5e-5, 3.5e-5, 3.5e-5, 3.5e-5, 3.5e-5]
    assert _release(raw, risk, [False] * 5) == _run(raw, risk) == [2, 2, 2, 2, 2]


def test_a_released_hold_falls_to_the_capped_level_never_below_the_raw_level():
    # Warning held on risk just under its threshold; from day 3 on no recent rain: the hold falls to the cap (Watch),
    # which is the raw level here
    assert _release([2, 1, 1, 1, 1], [5e-5, 3.5e-5, 3.5e-5, 3.5e-5, 3.5e-5], [False, False, True, True, True]) == \
        [2, 2, 1, 1, 1]
    # an Emergency hold over a raw Normal is capped at Watch, then Watch (capped to Normal) is released too
    assert _release([3, 0, 0], [2e-4, 1e-6, 1e-6], [False, True, True]) == [3, 1, 0]


def test_release_never_lowers_a_level_the_raw_level_supports_and_counters_restart():
    # the raw level itself is never touched (the cap of raw levels is the caller's), only holds above it
    assert _release([2, 2, 2], [5e-5, 5e-5, 5e-5], [True, True, True]) == [2, 2, 2]
    # a level that the cap leaves alone (identity cap) is held as before
    assert _release([2, 1, 1], [5e-5, 3.5e-5, 3.5e-5], [True, True, True], cap=[0, 1, 2, 3]) == [2, 2, 2]


def test_release_and_cap_are_validated():
    with pytest.raises(ValueError, match="go together"):
        _release([1], [2e-5], [True], cap=None)
    with pytest.raises(ValueError, match="one flag per row"):
        _release([1, 1], [2e-5, 2e-5], [True])
    with pytest.raises(ValueError, match="not above it"):
        _release([1], [2e-5], [True], cap=[0, 2, 2, 3])


# --------------------------------------------------------------------------------------- blind-hold limit

def _blind(raw, risk, hold_days, **kw):
    n = len(raw)
    return lv.apply_hysteresis(np.zeros(n, dtype=int), pd.date_range("2024-10-17", periods=n), raw, risk, T,
                               kw.get("exit_factor", 0.8), kw.get("exit_days", 2), None, None, None, hold_days).tolist()


def test_without_a_limit_an_outage_holds_the_level_indefinitely():
    nan = np.nan
    assert _blind([3, 0, 0, 0, 0], [2e-4, nan, nan, nan, nan], None) == [3, 3, 3, 3, 3]


def test_a_blind_hold_lasts_at_most_h_days_then_drops_one_level_per_further_day():
    nan = np.nan
    assert _blind([3, 0, 0, 0, 0], [2e-4, nan, nan, nan, nan], 1) == [3, 3, 2, 1, 0]
    assert _blind([3, 0, 0, 0, 0], [2e-4, nan, nan, nan, nan], 2) == [3, 3, 3, 2, 1]
    assert _blind([3, 0, 0], [2e-4, nan, nan], 0) == [3, 2, 1]


def test_the_blind_limit_never_goes_below_a_blind_escalated_raw_level_and_restarts_after_a_score():
    nan = np.nan
    # raw Watch on the outage days (blind escalation: heavy rain in another source) is a floor
    assert _blind([3, 1, 1, 1], [2e-4, nan, nan, nan], 1) == [3, 3, 2, 1]
    # a scored day between outages restarts the count; scored days follow the plain rules
    assert _blind([3, 0, 3, 0, 0], [2e-4, nan, 2e-4, nan, nan], 1) == [3, 3, 3, 3, 2]
    with pytest.raises(ValueError, match="blind_hold_days"):
        _blind([1], [2e-5], -1)


# ------------------------------------------------------------------------------------ thresholds per row

def _per_row(n, thresholds=T):
    return np.tile(thresholds.as_array(), (n, 1))


def test_levels_with_per_row_thresholds_equal_to_the_uniform_ones_match_the_plain_ones():
    risk = np.array([5e-7, 1e-5, 2e-5, 4e-5, 9e-5, 1e-4, np.nan, 3e-4])
    bound = np.array([2e-5, 1e-5, 2e-5, 4e-5, 9e-5, 1e-4, 5e-5, 3e-4])
    rows = _per_row(len(risk))
    assert lv.level_from_risk(risk, rows).tolist() == lv.level_from_risk(risk, T).tolist()
    assert lv.uncertain_high_mask(risk, bound, rows).tolist() == lv.uncertain_high_mask(risk, bound, T).tolist()
    for per_row, plain in zip(lv.raw_level(risk, bound, rows), lv.raw_level(risk, bound, T)):
        assert per_row.tolist() == plain.tolist()
    grid = np.tile(T.as_array(), (2, 4, 1))                    # a cells x days panel takes thresholds per cell-day
    assert lv.level_from_risk(risk.reshape(2, 4), grid).tolist() == lv.level_from_risk(risk.reshape(2, 4), T).tolist()


def test_hysteresis_with_per_row_thresholds_equal_to_the_uniform_ones_matches_the_plain_run():
    cases = [([2, 1, 1, 1, 1], [5e-5, 2e-5, 2e-5, 2e-5, 2e-5]), ([2, 1, 1, 1, 1], [5e-5, 3e-5, 3.5e-5, 3e-5, 3e-5]),
             ([3, 0, 0, 0, 0, 0], [2e-4, 1e-6, 1e-6, 1e-6, 1e-6, 1e-6]), ([2, 1, 2, 1, 1], [5e-5, 2e-5, 5e-5, 2e-5, 2e-5])]
    for raw, risk in cases:
        n = len(raw)
        cells, days = np.zeros(n, dtype=int), pd.date_range("2024-07-01", periods=n)
        plain = lv.apply_hysteresis(cells, days, raw, risk, T, 0.8, 2)
        assert lv.apply_hysteresis(cells, days, raw, risk, _per_row(n), 0.8, 2).tolist() == plain.tolist()
        release, cap = [False, False, True, True, True, True][:n], CAP
        held = lv.apply_hysteresis(cells, days, raw, risk, T, 0.8, 2, None, release, cap, 1)
        assert lv.apply_hysteresis(cells, days, raw, risk, _per_row(n), 0.8, 2, None, release, cap, 1).tolist() \
            == held.tolist()
    two = np.repeat([1, 2], 5)                                  # several cells, rows in any order
    days = pd.DatetimeIndex(list(pd.date_range("2024-07-01", periods=5)) * 2)
    raw, risk = np.array([2, 1, 1, 1, 1] * 2), np.array([1e-4, 5e-5, 5e-5, 5e-5, 5e-5] * 2)
    perm = np.array([7, 2, 9, 0, 4, 1, 8, 3, 6, 5])
    plain = lv.apply_hysteresis(two[perm], days[perm], raw[perm], risk[perm], T, 0.8, 2)
    assert lv.apply_hysteresis(two[perm], days[perm], raw[perm], risk[perm], _per_row(10), 0.8, 2).tolist() \
        == plain.tolist()


def test_hysteresis_steps_down_against_the_thresholds_of_the_row_it_decides_on():
    raw, risk = [2, 1, 1, 1, 1], [1e-4, 5e-5, 5e-5, 5e-5, 5e-5]
    cells, days = np.zeros(5, dtype=int), pd.date_range("2024-07-01", periods=5)
    low, high = T.as_array(), GHATS.as_array()               # exit thresholds for Warning: 3.2e-5 and 6.4e-5
    rows = np.vstack([low, low, high, high, high])            # the step-down days (2-4) sit under the higher thresholds
    assert lv.apply_hysteresis(cells, days, raw, risk, rows, 0.8, 2).tolist() == [2, 2, 2, 1, 1]
    assert lv.apply_hysteresis(cells, days, raw, risk, np.vstack([high] * 5), 0.8, 2).tolist() == [2, 2, 1, 1, 1]
    assert lv.apply_hysteresis(cells, days, raw, risk, np.vstack([low] * 5), 0.8, 2).tolist() == [2, 2, 2, 2, 2]


def test_per_row_thresholds_need_one_row_of_three_per_score():
    with pytest.raises(ValueError, match="per row"):
        lv.level_from_risk([1e-5, 2e-5], _per_row(3))
    with pytest.raises(ValueError, match="per row"):
        lv.apply_hysteresis(np.zeros(2, dtype=int), pd.date_range("2024-07-01", periods=2), [1, 1], [2e-5, 2e-5],
                            _per_row(3), 0.8, 2)
