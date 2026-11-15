"""The operating-point options study (verify.operating_options) on tiny synthetic inputs."""
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from aetherguard.alerts import frequency_levels as FL
from aetherguard.grid import latlon_to_cell
from aetherguard.verify import operating_options as O


def test_the_streamed_cap_thresholds_equal_the_exact_ones():
    rng = np.random.default_rng(1)
    parts = [10 ** rng.uniform(-9, -2, 5000) for _ in range(3)] + [np.array([np.nan, 1e-5, 1e-5, 1e-5])]
    pooled = np.concatenate(parts)
    shares = (0.3, 0.05, 0.001)
    got = O.streamed_cap_thresholds(lambda: iter(parts), shares)
    assert got == [FL.cap_threshold(pooled, s) for s in shares]


def test_ladder_levels_count_the_steps_a_risk_reaches():
    risk = np.array([[0.5, 2.5], [np.nan, 9.0]])
    assert O.ladder_levels(risk, np.array([1.0, 2.0, 3.0])).tolist() == [[0, 2], [0, 3]]


def test_the_neighbourhood_maximum_spans_ten_kilometres_and_a_day():
    lat = 20.0
    ids = latlon_to_cell([lat, lat, lat], [80.0, 80.05, 80.5])           # 5 km apart, then 45 km away
    nbr = O.neighbour_index(ids, 10.0)
    levels = np.zeros((3, 4), dtype=np.int8)
    levels[0, 1] = 2
    out = O.within_tolerance_max(levels, nbr, 1)
    assert out[0].tolist() == [2, 2, 2, 0] and out[1].tolist() == [2, 2, 2, 0] and out[2].tolist() == [0, 0, 0, 0]


def test_the_cost_ratio_is_the_alerts_saved_per_event_lost():
    rows = [{"alerts": 1000, "hits": 50}, {"alerts": 400, "hits": 47}, {"alerts": 300, "hits": 47}]
    assert O.cost_ratios(rows) == [None, 200.0, None]                     # no event lost: better at any ratio


def test_the_cluster_bootstrap_resamples_slides():
    hits = np.array([[True, True], [True, False], [False, False], [True, True]])   # events x steps
    clusters = np.array([0, 0, 1, 2])
    out = O.cluster_bootstrap(hits, clusters, {"n": 500, "seed": 3, "level": 0.95})
    assert out["share"] == [0.75, 0.5] and len(out["ci"]) == 2
    assert out["ci"][0][0] <= 0.75 <= out["ci"][0][1]


def test_development_events_keep_every_month_in_domain(tmp_path):
    for split in ("train", "validation"):
        pd.DataFrame({"cell_id": [1, 2, 3], "date": pd.to_datetime(["2010-01-05", "2010-11-02", "2018-07-01"]),
                      "kind": ["positive", "positive", "positive"], "in_domain": [True, split == "train", True]}
                     ).to_parquet(tmp_path / f"{split}_samples_features.parquet")
    events = O.development_events_all((2010,), tmp_path)
    assert sorted(events["cell_id"].tolist()) == [1, 1, 2]


def test_district_week_counts_turn_district_days_into_days_per_week():
    levels = np.array([[3, 0, 1, 0, 0, 0, 0], [0, 0, 0, 0, 0, 0, 0]], dtype=np.int8)     # 2 districts x 7 days
    out = O.district_week(levels)
    assert out["Emergency"]["mean_per_week"] == 0.5 and out["Watch+"]["max_per_week"] == 2.0


def test_the_held_out_look_refuses_a_second_time(tmp_path):
    (tmp_path / "look.json").write_text("{}", encoding="utf-8")
    with pytest.raises(FileExistsError):
        O.refuse_second_look(tmp_path / "look.json")


def test_the_criterion_checks_burden_and_detection_against_the_declared_bounds():
    declared = {"burden": {"himalaya|monsoon|3": 0.01}, "burden_factor": 1.5,
                "detection": {"tolerant|3": 0.40}, "detection_margin_slides": 2}
    look = {"burden": {"himalaya|monsoon|3": 0.014}, "detection": {"tolerant|3": {"hits": 33, "of": 87}}}
    result = O.decide(declared, look)
    assert result["confirmed"]                                      # 0.014 <= 0.015; 33 >= 0.40 * 87 - 2 = 32.8
    look["burden"]["himalaya|monsoon|3"] = 0.016
    assert not O.decide(declared, look)["confirmed"]
