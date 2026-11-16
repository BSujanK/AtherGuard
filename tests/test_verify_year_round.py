"""The year-round study (verify.year_round) on tiny synthetic inputs."""
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from aetherguard.alerts import levels as lv
from aetherguard.live import hardening as H
from aetherguard.live import postrules as pr
from aetherguard.verify import operating_options as O
from aetherguard.verify import year_round as Y

from alerts_helpers import CONFIG

CARD = {"himalaya": lv.Thresholds(1.0, 2.0, 4.0, "test"), "western_ghats": lv.Thresholds(1.0, 2.0, 4.0, "test")}
RULES = pr.PostRules(agreement_min=None, rain=pr.RainRule({7: 10.0}), gated_levels=(1, 2, 3))


def year_of(risk, new_hi, acc7, first_day=date(2010, 9, 28)):
    """A Year of one Himalayan and one Western Ghats cell with the same series over len(risk) days from `first_day`, no
    events, no warm-up; the tests read row 0."""
    days = [first_day + timedelta(days=i) for i in range(len(risk))]
    cells = pd.DataFrame({"cell_id": [1, 2], "region": ["himalaya", "western_ghats"], "in_universe": [True, True]})
    values = {"risk": np.array([risk] * 2, dtype=np.float64), "new_hi": np.array([new_hi] * 2, dtype=np.float64),
              **{f"acc_{w}": np.array([acc7] * 2, dtype=np.float32) for w in (1, 3, 7)}}
    none = pd.DataFrame({"cell_id": np.zeros(0, dtype=np.int64), "date": pd.to_datetime([])})
    return O.Year(2010, "jun_dec", none, panel=H.Panel(cells, days, 20, values), first=0)


def test_the_scale_multiplies_only_the_out_of_season_thresholds():
    out = Y.season_thresholds(CARD, {"post_monsoon": 2.0})
    assert out[("himalaya", "monsoon")] == (1.0, 2.0, 4.0)
    assert out[("himalaya", "post_monsoon")] == (2.0, 4.0, 8.0)
    assert out[("western_ghats", "rest")] == (1.0, 2.0, 4.0)


def test_candidate_keys_round_trip():
    assert Y.parse_key(Y.key(1.25, False)) == (1.25, False)
    assert Y.TODAY_KEY in Y.CANDIDATES and len(Y.CANDIDATES) == len(Y.SCALES) * 2


def test_a_treatment_never_changes_a_monsoon_day():
    # 28-30 September then 1-3 October; risk 3 (Warning at the card, Watch at scale 2) on every day, rain everywhere
    y = year_of([3.0] * 6, [3.0] * 6, [50.0] * 6)
    today = Y.treatment_levels(y, CARD, CONFIG, RULES, {}, True)
    treated = Y.treatment_levels(y, CARD, CONFIG, RULES, {"post_monsoon": 2.0, "rest": 2.0}, True)
    assert today["published"][0, :3].tolist() == treated["published"][0, :3].tolist() == [2, 2, 2]
    assert today["point"][0, 3:].tolist() == [2, 2, 2] and treated["point"][0, 3:].tolist() == [1, 1, 1]


def test_uncertain_high_is_switched_off_out_of_season_only():
    # the point is below Watch, the upper bound reaches it: Watch by uncertain_high on every day unless switched off
    y = year_of([0.5] * 6, [1.5] * 6, [50.0] * 6)
    on = Y.treatment_levels(y, CARD, CONFIG, RULES, {}, True)["published"][0].tolist()
    off = Y.treatment_levels(y, CARD, CONFIG, RULES, {}, False)["published"][0].tolist()
    assert on == [1, 1, 1, 1, 1, 1]
    assert off[:3] == [1, 1, 1] and off[4:] == [0, 0]          # the hold of 30 September may carry into 1 October


def test_the_rain_cap_applies_to_every_candidate():
    y = year_of([5.0] * 4, [5.0] * 4, [0.0] * 4, first_day=date(2010, 10, 5))
    levels = Y.treatment_levels(y, CARD, CONFIG, RULES, {}, True)
    assert levels["point"][0].tolist() == [3, 3, 3, 3] and levels["capped"][0].tolist() == [1, 1, 1, 1]


def test_stratum_counts_split_regions_and_seasons():
    levels = np.array([[3, 1, 0], [2, 2, 2]], dtype=np.int8)
    scored = np.array([[True, True, False], [True, True, True]])
    out = Y.stratum_counts(levels, scored, np.array(["himalaya", "western_ghats"]), np.array([0, 1, 1]))
    assert out["himalaya|monsoon"] == [1, 1, 1, 1]
    assert out["himalaya|post_monsoon"] == [1, 1, 0, 0]
    assert out["western_ghats|post_monsoon"] == [2, 2, 2, 0]


def test_slide_hits_count_a_slide_once():
    assert Y.slide_hits(np.array([3, 0, 1, 2]), np.array([0, 0, 1, 2]), 2) == 2
    assert Y.slide_hits(np.array([]), np.array([]), 1) == 0


def test_the_allowed_loss_is_one_slide_or_three_percent():
    assert Y.loss_allowed(10) == 1 and Y.loss_allowed(42) == 1 and Y.loss_allowed(93) == 2 and Y.loss_allowed(200) == 6


def test_the_rule_takes_the_fewest_emergency_cell_days_among_candidates_within_the_loss():
    today = {("tolerant", 1): 10, ("tolerant", 3): 5}
    burden = {Y.TODAY_KEY: np.array([100, 50, 20]), "m1.50_uon": np.array([60, 30, 8]),
              "m2.00_uon": np.array([40, 20, 4]), "m1.00_uoff": np.array([80, 50, 20])}
    hits = {Y.TODAY_KEY: today, "m1.50_uon": {("tolerant", 1): 10, ("tolerant", 3): 4},
            "m2.00_uon": {("tolerant", 1): 9, ("tolerant", 3): 3}, "m1.00_uoff": today}
    got = Y.choose(burden, hits, today, slides=20)
    assert got["chosen"] == "m1.50_uon" and got["allowed_loss"] == 1 and got["max_loss"] == 1
    assert "m2.00_uon" not in got["passing"]


def test_the_rule_prefers_the_smaller_change_on_a_tie():
    today = {("tolerant", 1): 10}
    burden = {Y.TODAY_KEY: np.array([100, 50, 20]), "m1.00_uoff": np.array([100, 50, 20])}
    got = Y.choose(burden, {Y.TODAY_KEY: today, "m1.00_uoff": today}, today, slides=5)
    assert got["chosen"] == Y.TODAY_KEY


def test_power_of_a_few_slides():
    assert Y.upper_loss_share(3) == pytest.approx(1 - 0.05 ** (1 / 3))
    assert Y.upper_loss_share(0) is None
    assert Y.veto_power(3, 0.1) == pytest.approx(1 - 0.9 ** 3)
    assert Y.veto_power(0, 0.5) == 0.0


def test_the_look_decides_by_the_declared_rows():
    declared = {"burden": {"himalaya|Watch+": {"required_heldout_reduction": 0.10}}}
    look = {"burden_reduction": {"himalaya|Watch+": 0.2}, "monsoon_differing": 0,
            "detection": {"heldout_w1": {"lost": {"tolerant|1": 0, "cell_exact|1": 0}}}}
    assert Y.decide(declared, look)["adopt"]
    look["detection"]["heldout_w1"]["lost"]["cell_exact|1"] = 1
    assert Y.decide(declared, look)["failed"] == ["detection veto (W1)"]
    look["detection"]["heldout_w1"]["lost"]["cell_exact|1"] = 0
    look["burden_reduction"]["himalaya|Watch+"] = 0.05
    assert Y.decide(declared, look)["failed"] == ["burden himalaya|Watch+"]


def test_a_second_look_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(Y, "results_dir", lambda: tmp_path)
    (tmp_path / "heldout.started").write_text("x")
    with pytest.raises(FileExistsError):
        Y.heldout_look(say=lambda m: None)
    with pytest.raises(FileExistsError):
        Y.preflight(say=lambda m: None)
