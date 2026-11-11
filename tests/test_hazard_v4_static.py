"""W5 challenger: how the static table reaches the rows, and what v4-static is allowed to differ by."""
import pandas as pd
import pytest

from aetherguard.features.static_w5 import STATIC_COLUMNS
from aetherguard.hazard import v4_static as vs

STATIC = pd.DataFrame({"cell_id": [10, 20, 30], **{c: [1.0, 2.0, 3.0] for c in STATIC_COLUMNS}})


def test_a_row_takes_the_static_values_of_its_terrain_cell_when_it_has_one():
    frame = pd.DataFrame({"cell_id": [10, 20, 30], "terrain_cell_id": pd.array([30, None, 30], dtype="Int64"), "x": [7, 8, 9]})
    out = vs.join_static(frame, STATIC)
    assert out["lc_tree"].tolist() == [3.0, 2.0, 3.0]          # moved to cell 30, own cell, own cell
    assert out["x"].tolist() == [7, 8, 9] and len(out) == 3


def test_rows_without_a_terrain_column_join_on_their_own_cell_and_keep_their_order():
    out = vs.join_static(pd.DataFrame({"cell_id": [30, 10, 30, 20]}), STATIC)
    assert out["soil_clay"].tolist() == [3.0, 1.0, 3.0, 2.0]


def test_a_cell_the_table_does_not_hold_is_nan_never_zero():
    out = vs.join_static(pd.DataFrame({"cell_id": [10, 99]}), STATIC)
    assert out["road_density"][0] == 1.0 and out[STATIC_COLUMNS].iloc[1].isna().all()


def test_joining_twice_is_refused():
    once = vs.join_static(pd.DataFrame({"cell_id": [10]}), STATIC)
    with pytest.raises(ValueError, match="already has"):
        vs.join_static(once, STATIC)


def test_v4_static_is_v3_plus_the_nine_physical_unconstrained_inputs_and_nothing_else():
    study = vs.load_study()
    base = ["stat_slope_mean", "irain_acc_3", "irain_acc_7"]
    candidates = vs.make_candidates(study, base)
    c0, challenger = candidates["C0"], candidates["v4_static"]
    assert c0.columns == base
    assert challenger.columns == [*base, *vs.HAZARD_COLUMNS] and len(vs.HAZARD_COLUMNS) == 9
    assert not {"road_density", "lc_built"} & set(challenger.columns)
    assert challenger.constraints[:3] == c0.constraints and challenger.constraints[3:] == [0] * 9
    assert not c0.drop_implausible and not challenger.drop_implausible


def test_a_static_column_already_in_the_frozen_model_is_an_error():
    with pytest.raises(ValueError, match="already inputs"):
        vs.make_candidates(vs.load_study(), ["irain_acc_3", "lc_tree"])
