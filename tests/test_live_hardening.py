"""The development analysis of the post-model rules (live.hardening, live.hardening_dev) on tiny synthetic panels."""
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from aetherguard.alerts import levels as lv
from aetherguard.live import hardening as H
from aetherguard.live import hardening_dev as D
from aetherguard.live import postrules as pr

from alerts_helpers import CONFIG

T = lv.Thresholds(watch=1e-5, warning=4e-5, emergency=1e-4, source="test")
DAYS = [date(2010, 6, 1) + timedelta(days=k) for k in range(6)]


def _panel(risk, acc7=None, universe=None, members=4):
    risk = np.asarray(risk, dtype=np.float64)
    cells = pd.DataFrame({"cell_id": np.arange(len(risk)) + 1, "region": "himalaya",
                          "in_universe": np.ones(len(risk), bool) if universe is None else universe})
    panel = H.new_panel(cells, DAYS[:risk.shape[1]], members)
    panel.values["risk"][:] = risk
    panel.values["new_hi"][:] = risk
    panel.values["old_hi"][:] = risk
    panel.values["acc_7"][:] = 50.0 if acc7 is None else acc7
    panel.values["acc_3"][:] = 50.0
    return panel


def _season(panel, events=None):
    events = pd.DataFrame({"cell_id": pd.Series(dtype="int64"), "date": pd.Series(dtype="datetime64[ns]")}) \
        if events is None else events
    return D.Season(2010, panel, 0, events, {"himalaya": T})


def test_window_any_looks_back_over_the_window_including_the_day():
    ok = np.array([[True, False, False, False, True]])
    assert D.window_any(ok, 3).tolist() == [[True, True, True, False, True]]
    assert D.window_any(ok, 1).tolist() == ok.tolist()


def test_season_levels_cap_dry_cell_days_and_release_dry_holds():
    risk = [[5e-5, 3.5e-5, 3.5e-5, 3.5e-5]]                      # Warning, then held over a Watch raw level
    wet = _season(_panel(risk))
    assert D.season_levels(wet, "new_hi", CONFIG).tolist() == [[2, 2, 2, 2]]
    dry = _season(_panel(risk, acc7=np.array([[50.0, 0.0, 0.0, 0.0]])))
    rules = pr.PostRules(None, pr.RainRule({7: 10.0}), (1, 2, 3), hold_window_days=2)
    # day 1 rained, so day 2 may hold (window D-1..D); from day 3 the window is dry: the held Warning is released to its
    # cap (Watch), and the next day the held Watch to its cap (Normal); the raw level itself is capped to Normal
    assert D.season_levels(dry, "new_hi", CONFIG, rules).tolist() == [[2, 2, 1, 0]]
    assert D.season_levels(dry, "new_hi", CONFIG, rules, release=False).tolist() == [[2, 2, 2, 2]]


def test_agreement_reads_the_member_count_of_the_points_level():
    panel = _panel([[5e-5, 1e-6]], members=4)
    panel.values["n_watch"][:] = 4
    panel.values["n_warning"][:] = [[1, 0]]
    season = _season(panel)
    point = D.point_levels(season)
    assert point.tolist() == [[2, 0]]
    assert D.agreement(season, point).tolist() == [[0.25, 1.0]]


def test_adoption_needs_at_most_one_percent_loss_and_a_lower_share():
    def result(hits, share):
        return {"detected_at_least": {"Watch": {"hits": hits}}, "share_at_least": {"Watch": share}}
    assert D.adoption(result(200, 0.5), result(198, 0.45), 1)["adopt"]
    assert not D.adoption(result(200, 0.5), result(197, 0.45), 1)["adopt"]
    assert not D.adoption(result(200, 0.5), result(200, 0.5), 1)["adopt"]


def test_candidate_rules_mark_a_zero_minimum_as_vacuous():
    quantiles = {"quantiles": {"1": {"1": 0.0, "2": 0.0, "5": 0.3}, "3": {"1": 0.0, "2": 0.6, "5": 2.7},
                               "7": {"1": 0.3, "2": 4.0, "5": 11.5}}}
    rules = {(r["form"], r["percentile"]): r for r in D.candidate_rules(quantiles)}
    assert rules[("acc_3", 1.0)]["vacuous_windows"] == [3]
    assert rules[("acc_7", 1.0)]["vacuous_windows"] == []
    assert rules[("acc_1_or_acc_3_or_acc_7", 5.0)]["minimum_mm"] == {1: 0.3, 3: 2.7, 7: 11.5}


def test_the_rule_choice_prefers_more_levels_then_the_lower_warning_share():
    def row(form, q, levels, warning, watch):
        return {"form": form, "percentile": q, "minimum_mm": {7: q}, "adoptable_levels": levels,
                "combined": {"share_at_least": {"Warning": warning, "Watch": watch}},
                "combined_adoption": [{"adopt": True} for _ in levels]}
    rows = [row("acc_3", 2.0, ["Watch", "Warning"], 0.20, 0.5), row("acc_7", 5.0, ["Watch", "Warning"], 0.19, 0.6),
            row("acc_7", 1.0, ["Watch"], 0.10, 0.1), {"form": "acc_3", "percentile": 1.0, "adoptable_levels": []}]
    assert D.choose_rule(rows) == {"form": "acc_7", "percentile": 5.0, "minimum_mm": {7: 5.0},
                                   "gated_levels": ["Watch", "Warning"]}
    assert D.choose_rule([rows[-1]]) is None


def test_retention_and_the_blind_hold_choice():
    # one cell at Emergency for two days then Normal; another at Watch throughout
    season = _season(_panel([[2e-4, 2e-4, 1e-6, 1e-6], [2e-5, 2e-5, 2e-5, 2e-5]]))
    table = D.retention([season])
    assert table["Emergency"]["1"] == {"cell_days": 2, "retained": 1, "share": 0.5}
    assert table["Emergency"]["2"] == {"cell_days": 2, "retained": 0, "share": 0.0}
    assert table["Watch"]["1"]["share"] == pytest.approx(4 / 5)
    assert D.choose_blind_hold(table)["lags_meeting_retention"] == [1]
    assert D.choose_blind_hold(table)["blind_hold_days"] == 1
    full = {name: {str(k): {"share": share} for k, share in zip((1, 2, 3), shares)}
            for name, shares in (("Watch", (0.9, 0.9, 0.9)), ("Warning", (0.8, 0.7, 0.6)), ("Emergency", (0.6, 0.5, 0.4)))}
    assert D.choose_blind_hold(full) == {**D.choose_blind_hold(full), "blind_hold_days": 2,
                                         "lags_meeting_retention": [1, 2]}


def test_post_rain_cost_counts_positives_long_after_rain_below_the_minimum():
    quantiles = {"acc_7": [0.0, 5.0, 20.0, 0.0], "days_since_10mm": [8.0, 9.0, 8.0, 2.0]}
    out = D.post_rain_cost(quantiles, 11.5)
    assert (out["post_rain"], out["post_rain_below_minimum"], out["all_below_minimum"]) == (3, 2, 3)


def test_season_outcome_counts_universe_cell_days_and_event_levels():
    panel = _panel([[2e-4, 1e-6], [5e-5, 5e-5]], universe=np.array([True, False]))
    panel.values["acc_3"][0] = 0.0
    events = pd.DataFrame({"cell_id": [2], "date": pd.to_datetime([DAYS[1]])})
    season = _season(panel, events)
    out = D.season_outcome(season, D.season_levels(season, "new_hi", CONFIG))
    assert out["cell_days"] == 2 and out["at_least"] == {1: 2, 2: 2, 3: 2}      # Emergency held on day 2
    assert out["dry_at"][3] == 2 and out["own_level"].tolist() == [2]


def test_panels_round_trip_through_their_file(tmp_path):
    panel = _panel([[5e-5, 1e-6]])
    H.save_panel(tmp_path / "season.npz", panel)
    loaded = H.load_panel(tmp_path / "season.npz")
    assert loaded.days == panel.days and loaded.n_members == 4
    assert np.array_equal(loaded["risk"], panel["risk"]) and loaded.cells.equals(panel.cells)
