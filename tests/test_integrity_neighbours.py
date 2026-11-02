import numpy as np
import pandas as pd
import pytest
from integrity_helpers import synthetic_set

from aetherguard.integrity import neighbours

# Four stations on the 75 E meridian: A, B, C one degree (111 km) apart, so A and C are 222 km
# apart (outside 150 km); D sits ~1800 km away and has no neighbour at all.
LAYOUT = {"IN_A": (20.0, 75.0, 10.0), "IN_B": (21.0, 75.0, 10.0),
          "IN_C": (22.0, 75.0, 10.0), "IN_D": (38.0, 75.0, 10.0)}


def _meta():
    n = 4
    sset = synthetic_set({k: np.zeros(n) for k in LAYOUT}, meta_rows=LAYOUT)
    return sset.meta


def test_haversine_known_distance():
    # one degree of latitude is 111.19 km
    assert neighbours.haversine_km(20.0, 75.0, 21.0, 75.0) == pytest.approx(111.19, abs=0.05)
    assert neighbours.haversine_km(10.0, 70.0, 10.0, 70.0) == 0.0


def test_table_k_nearest_within_radius_with_distances():
    table = neighbours.neighbour_table(_meta(), k=2, max_km=150)
    assert list(table.columns) == ["station", "neighbour", "rank", "dist_km"]
    a = table[table["station"] == "IN_A"].sort_values("rank")
    assert list(a["neighbour"]) == ["IN_B"]  # C is 222 km away: outside 150 km
    assert a["dist_km"].iloc[0] == pytest.approx(111.19, abs=0.05)
    b = table[table["station"] == "IN_B"].sort_values("rank")
    assert set(b["neighbour"]) == {"IN_A", "IN_C"} and list(b["rank"]) == [1, 2]  # equidistant
    assert "IN_D" not in set(table["station"]) | set(table["neighbour"])


def test_k_limits_the_neighbour_count():
    table = neighbours.neighbour_table(_meta(), k=1, max_km=500)
    assert (table.groupby("station").size() == 1).all()


def test_stations_with_fewer_than_two_neighbours_are_reported():
    table = neighbours.neighbour_table(_meta(), k=5, max_km=150)
    assert neighbours.stations_with_few_neighbours(table, _meta(), min_neighbours=2) == {
        "IN_A": 1, "IN_C": 1, "IN_D": 0}


def _ref_inputs():
    # B has neighbours A and C; A has only B (n_valid < 2 -> NaN); the days exercise NaN and wet share.
    sset = synthetic_set({"IN_A": [0, 4, 8, np.nan], "IN_B": [0, 0, 2, 2],
                          "IN_C": [0, 6, np.nan, 10], "IN_D": [1, 1, 1, 1]}, meta_rows=LAYOUT)
    return sset.values, neighbours.neighbour_table(sset.meta, k=5, max_km=150)


def test_reference_statistics_from_observed_neighbours():
    values, table = _ref_inputs()
    ref = neighbours.neighbour_reference(values, table)
    assert set(ref) == {"idw_mean", "median", "max", "n_valid", "frac_wet"}
    b = "IN_B"
    assert list(ref["n_valid"][b]) == [2, 2, 1, 1]
    # day 1: neighbours A=4 and C=6, both 111 km away: equal weights
    assert ref["idw_mean"].loc[values.index[1], b] == pytest.approx(5.0, abs=1e-4)
    assert ref["median"].loc[values.index[1], b] == pytest.approx(5.0)
    assert ref["max"].loc[values.index[1], b] == pytest.approx(6.0)
    assert ref["frac_wet"].loc[values.index[1], b] == 1.0
    assert ref["frac_wet"].loc[values.index[0], b] == 0.0


def test_fewer_than_two_valid_neighbours_gives_nan_never_zero():
    values, table = _ref_inputs()
    ref = neighbours.neighbour_reference(values, table)
    for name in ("idw_mean", "median", "max", "frac_wet"):
        assert ref[name]["IN_B"].iloc[2:].isna().all()        # only one valid neighbour
        assert ref[name]["IN_A"].isna().all()                  # A has a single neighbour overall
        assert ref[name]["IN_D"].isna().all()                  # D has none
    assert (ref["n_valid"]["IN_D"] == 0).all()
    assert ref["n_valid"].dtypes.map(lambda d: np.issubdtype(d, np.integer)).all()


def test_idw_weights_nearer_neighbours_more():
    meta = {"IN_A": (20.0, 75.0, 0.0), "IN_B": (20.1, 75.0, 0.0), "IN_C": (20.5, 75.0, 0.0)}
    sset = synthetic_set({"IN_A": [0.0], "IN_B": [10.0], "IN_C": [0.0]}, meta_rows=meta)
    table = neighbours.neighbour_table(sset.meta, k=5, max_km=150)
    ref = neighbours.neighbour_reference(sset.values, table)
    d_b, d_c = 11.1195, 55.6
    expected = (10.0 / d_b**2) / (1 / d_b**2 + 1 / d_c**2)
    assert ref["idw_mean"].loc[sset.values.index[0], "IN_A"] == pytest.approx(expected, rel=1e-3)


def test_non_finite_neighbour_values_are_invalid():
    values, table = _ref_inputs()
    values = values.copy()
    values.iloc[1, values.columns.get_loc("IN_A")] = np.inf
    ref = neighbours.neighbour_reference(values, table)
    assert ref["n_valid"].loc[values.index[1], "IN_B"] == 1


def test_reference_is_deterministic_and_vectorised_over_many_days():
    rng = np.random.default_rng(0)
    data = {k: rng.gamma(0.5, 5.0, 5000) for k in LAYOUT}
    sset = synthetic_set(data, meta_rows=LAYOUT)
    table = neighbours.neighbour_table(sset.meta, k=5, max_km=150)
    one = neighbours.neighbour_reference(sset.values, table)
    two = neighbours.neighbour_reference(sset.values, table)
    pd.testing.assert_frame_equal(one["idw_mean"], two["idw_mean"])
    expected = np.median(sset.values[["IN_A", "IN_C"]].to_numpy(), axis=1)
    np.testing.assert_allclose(one["median"]["IN_B"].to_numpy(), expected, rtol=1e-5)


def test_neighbour_count_strict_and_inclusive_and_matrix_threshold():
    values, table = _ref_inputs()
    above = neighbours.neighbour_count(values, table, 4.0, strict=True)
    assert above.loc[values.index[1], "IN_B"] == 1      # A=4 is not > 4, C=6 is
    at_least = neighbours.neighbour_count(values, table, 4.0, strict=False)
    assert at_least.loc[values.index[1], "IN_B"] == 2
    thr = pd.DataFrame(5.0, index=values.index, columns=values.columns)
    per_day = neighbours.neighbour_count(values, table, thr, strict=False)
    assert per_day.loc[values.index[1], "IN_B"] == 1
    assert per_day.loc[values.index[2], "IN_B"] == 1    # A=8, C missing
    assert per_day["IN_D"].eq(0).all()
