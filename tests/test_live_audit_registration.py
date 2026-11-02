"""The gauge-referenced shift study (live.audit_registration): the correlation table on synthetic fields."""
import numpy as np

from aetherguard.live import audit_registration as ar


def _field(seed=1, days=40, points=200):
    rng = np.random.default_rng(seed)
    return rng.gamma(0.7, 8.0, (days, points + 2))


def test_a_product_sampled_where_the_reference_is_correlates_best_at_zero_shift():
    field = _field()
    reference = field[:, 1:-1]
    table = ar.shift_correlations(reference, lambda dr, dc: field[:, 1 + dc:field.shape[1] - 1 + dc], shifts=((0, -1), (0, 0), (0, 1)))
    assert ar.best_shift(table) == "0,0" and table["0,0"] > 0.999
    assert table["0,1"] < 0.5


def test_a_displaced_product_is_best_at_the_opposite_shift():
    field = _field(2)
    reference = field[:, 2:]            # the reference sits one column east of the product's zero shift
    table = ar.shift_correlations(reference[:, :-1], lambda dr, dc: field[:, 1 + dc:field.shape[1] - 2 + dc], shifts=((0, 0), (0, 1)))
    assert ar.best_shift(table) == "0,1"


def test_missing_and_negative_entries_are_left_out():
    reference = np.array([[1.0, 4.0, np.nan, -1.0], [9.0, 16.0, 25.0, 36.0]])
    other = np.array([[1.0, 4.0, 9.0, 16.0], [9.0, 16.0, np.nan, 36.0]])
    table = ar.shift_correlations(reference, lambda dr, dc: other, shifts=((0, 0),))
    assert table["0,0"] > 0.999


def test_the_lookup_options_pick_the_documented_grid_index():
    position = np.array([38.0, 38.2, 38.5, 38.7])
    assert ar.lookup_index(position, "round").tolist() == [38, 38, 39, 39]
    assert ar.lookup_index(position, "round-1").tolist() == [37, 37, 38, 38]
    assert ar.lookup_index(position, "floor").tolist() == [38, 38, 38, 38]
    assert ar.lookup_index(position, "ceil").tolist() == [38, 39, 39, 39]
