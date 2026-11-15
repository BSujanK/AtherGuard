"""Frequency-capped alert levels (alerts.frequency_levels): thresholds set by how often a level may fire."""
import numpy as np
import pytest

from aetherguard.alerts import frequency_levels as F
from aetherguard.alerts import levels as lv


def test_the_season_of_a_month():
    assert [F.season_of_month(m) for m in (1, 5, 6, 9, 10, 12)] == \
        ["rest", "rest", "monsoon", "monsoon", "post_monsoon", "post_monsoon"]
    assert F.season_index(np.array([6, 11, 2])).tolist() == [0, 1, 2]


def test_the_cap_threshold_is_the_lowest_that_fires_on_at_most_the_share():
    risk = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, np.nan])
    t = F.cap_threshold(risk, 0.3)                      # 10 finite values: at most 3 may reach it
    assert (risk >= t).sum() == 3 and np.nextafter(t, -np.inf) <= 7.0 < t
    assert F.cap_threshold(risk, 0.0) > 10.0 and (risk >= F.cap_threshold(risk, 0.0)).sum() == 0


def test_ties_at_the_cut_are_left_out_so_the_share_is_never_exceeded():
    risk = np.array([1.0, 2.0, 5.0, 5.0, 5.0, 9.0])
    t = F.cap_threshold(risk, 0.5)                      # 3 may fire; 9 and three 5s would be 4
    assert (risk >= t).sum() == 1 and t > 5.0


def test_a_cap_of_every_cell_day_sets_no_threshold():
    assert F.cap_threshold(np.array([1.0, 2.0]), 1.0) == -np.inf
    assert F.cap_threshold(np.array([np.nan]), 0.1) == -np.inf


def test_thresholds_keep_the_floor_and_rise_from_watch_to_emergency():
    rng = np.random.default_rng(0)
    samples = {("himalaya", "monsoon"): rng.uniform(0, 1, 10_000), ("himalaya", "rest"): rng.uniform(0, 0.1, 10_000)}
    caps = {"monsoon": (0.2, 0.1, 0.01), "rest": (0.2, 0.1, 0.01)}
    floor = {"himalaya": lv.Thresholds(0.5, 0.6, 0.7, source="card")}
    out = F.frequency_thresholds(samples, caps, floor)
    monsoon, rest = out[("himalaya", "monsoon")], out[("himalaya", "rest")]
    assert monsoon[0] == 0.8 or abs(monsoon[0] - 0.8) < 0.01                  # 20% of U(0, 1) is above 0.8
    assert monsoon[2] > 0.98 and list(monsoon) == sorted(monsoon)
    assert rest == (0.5, 0.6, 0.7)                                             # the cap never lowers a threshold


def test_caps_must_not_rise_from_watch_to_emergency():
    with pytest.raises(ValueError):
        F.frequency_thresholds({("himalaya", "monsoon"): np.ones(3)}, {"monsoon": (0.1, 0.2, 0.01)}, None)


def _document():
    thresholds = {("himalaya", "monsoon"): (1.0, 2.0, 3.0), ("western_ghats", "monsoon"): (1.5, 2.5, 3.5),
                  ("himalaya", "post_monsoon"): (4.0, 5.0, 6.0), ("western_ghats", "post_monsoon"): (4.5, 5.5, 6.5),
                  ("himalaya", "rest"): (7.0, 8.0, 9.0), ("western_ghats", "rest"): (7.5, 8.5, 9.5)}
    pooled = {"monsoon": (1.2, 2.2, 3.2), "post_monsoon": (4.2, 5.2, 6.2), "rest": (7.2, 8.2, 9.2)}
    caps = {s: (0.3, 0.1, 0.01) for s in F.SEASONS}
    return F.scheme_document("test", thresholds, pooled, caps, floor="card", provenance={"panels": "x"})


def test_each_season_of_the_document_reads_as_a_card():
    doc = _document()
    card = F.season_card(doc, 7)
    got = lv.card_region_thresholds(card, ["himalaya", "western_ghats", "other"])
    assert got["himalaya"].as_array().tolist() == [1.0, 2.0, 3.0]
    assert got["western_ghats"].as_array().tolist() == [1.5, 2.5, 3.5]
    assert got["other"].as_array().tolist() == [1.2, 2.2, 3.2]                 # the pooled value for an unnamed region
    assert doc["seasons"]["rest"]["months"] == [1, 2, 3, 4, 5]
    assert doc["seasons"]["monsoon"]["alert_levels"]["emergency"]["cap_share"] == 0.01


def test_row_thresholds_follow_the_cells_region_and_the_days_season():
    doc = _document()
    rows = F.row_thresholds(doc, np.array(["himalaya", "western_ghats"]), np.array([6, 10, 3]))
    assert rows.shape == (2, 3, 3)
    assert rows[0, 0].tolist() == [1.0, 2.0, 3.0] and rows[1, 1].tolist() == [4.5, 5.5, 6.5]
    assert rows[0, 2].tolist() == [7.0, 8.0, 9.0]
