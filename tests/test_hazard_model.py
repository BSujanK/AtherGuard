import copy

import numpy as np
import pandas as pd
import pytest

from aetherguard.hazard import data as hd
from aetherguard.hazard import model as hm

from hazard_helpers import COLUMN_MAP

CFG = hm.hazard_config()
ALL_COLUMNS = hd.model_columns(CFG["groups"], COLUMN_MAP)


# ------------------------------------------------------------------------------------------ constraints

def test_constraint_vector_from_names():
    vector = dict(zip(ALL_COLUMNS, hm.configured_constraints(ALL_COLUMNS, CFG)))
    for name in ("rain_acc_1", "rain_acc_30", "rain_max1d_7", "rain_acc3_vs_clim", "rain_wetdays_30",
                 "src_imd_acc_1", "src_chi_acc_1", "stat_slope_mean", "stat_relief"):
        assert vector[name] == 1, name
    assert vector["rain_days_since_10mm"] == -1
    for name in ("src_dis_diff_1", "src_dis_ratio_1", "wet_top", "wet_top_chg3", "stat_elev_mean", "stat_aspect_sin"):
        assert vector[name] == 0, name


def test_constraint_vector_on_the_real_feature_names():
    names = ["rain_acc_1", "rain_acc_30", "rain_max1d_7", "rain_max1d_30", "rain_wetdays_30", "rain_days_since_10mm",
             "rain_share1_3", "rain_acc3_vs_clim", "rain_acc7_vs_clim", "rain_acc30_vs_clim", "src_imd_acc_7",
             "src_chi_acc_3", "src_dis_both", "wet_root", "stat_slope_p90", "stat_slope_max", "stat_curvature_mean",
             "stat_twi_proxy"]
    got = dict(zip(names, hm.configured_constraints(names, CFG)))
    assert [n for n, v in got.items() if v == 1] == [
        "rain_acc_1", "rain_acc_30", "rain_max1d_7", "rain_max1d_30", "rain_wetdays_30", "rain_acc3_vs_clim",
        "rain_acc7_vs_clim", "rain_acc30_vs_clim", "src_imd_acc_7", "src_chi_acc_3", "stat_slope_p90",
        "stat_slope_max"]
    assert [n for n, v in got.items() if v == -1] == ["rain_days_since_10mm"]


def test_conflicting_constraints_are_refused():
    with pytest.raises(ValueError, match="both increasing and decreasing"):
        hm.constraint_vector(["a_x"], ["a_*"], ["*_x"])


# --------------------------------------------------------------------------------- monotonicity on a fit

def _band_data(n=1500, seed=0):
    """y rises with x1 overall but is 0 in a middle band: an unconstrained fit is non-monotone in x1."""
    rng = np.random.default_rng(seed)
    x1, x2 = rng.uniform(0, 10, n), rng.normal(size=n)
    p = np.where((x1 > 4) & (x1 < 6), 0.02, np.where(x1 >= 6, 0.7, 0.2))
    frame = pd.DataFrame({"x1": x1, "x2": x2, "label": (rng.random(n) < p).astype(int), "split": "train",
                          "kind": "negative", "sample_weight": 1.0})
    return frame


def _fit_band(constraints):
    settings = copy.deepcopy(CFG["training"])
    hp = {"num_leaves": 8, "min_data_in_leaf": 20, "feature_fraction": 1.0, "learning_rate": 0.1, "lambda_l2": 1.0}
    frame = _band_data()
    booster, rounds = hm.fit_booster(frame, ["x1", "x2"], constraints, hp, 1, settings, num_rounds=60)
    return booster, rounds, frame


def test_monotone_constraint_holds_on_a_synthetic_fit_and_unconstrained_fit_violates():
    constrained, rounds, frame = _fit_band([1, 0])
    check = hm.monotonicity_check(constrained, ["x1", "x2"], [1, 0], frame, rounds)
    assert set(check) == {"x1"} and check["x1"]["holds"] and check["x1"]["max_violation"] == 0.0
    free, rounds, frame = _fit_band([0, 0])
    assert not hm.monotonicity_check(free, ["x1", "x2"], [1, 0], frame, rounds)["x1"]["holds"]


def test_decreasing_constraint_is_checked_in_its_direction():
    frame = _band_data()
    frame["x1"] = -frame["x1"]
    settings = copy.deepcopy(CFG["training"])
    hp = {"num_leaves": 8, "min_data_in_leaf": 20, "feature_fraction": 1.0, "learning_rate": 0.1, "lambda_l2": 1.0}
    booster, rounds = hm.fit_booster(frame, ["x1", "x2"], [-1, 0], hp, 1, settings, num_rounds=40)
    assert hm.monotonicity_check(booster, ["x1", "x2"], [-1, 0], frame, rounds)["x1"]["holds"]
    assert not hm.monotonicity_check(booster, ["x1", "x2"], [1, 0], frame, rounds)["x1"]["holds"]


def test_training_function_raises_on_leaked_rows():
    frame = _band_data()
    hp = {"num_leaves": 4, "min_data_in_leaf": 20, "feature_fraction": 1.0, "learning_rate": 0.1, "lambda_l2": 1.0}
    for column, value in (("split", "test_2018"), ("split", "test_sparse"), ("kind", "case_kerala_2018"),
                          ("kind", "window_cell")):
        bad = frame.copy()
        bad.loc[0, column] = value
        with pytest.raises(hd.LeakageError):
            hm.fit_booster(bad, ["x1", "x2"], [1, 0], hp, 1, CFG["training"], num_rounds=3)
    with pytest.raises(ValueError, match="num_rounds"):
        hm.fit_booster(frame, ["x1", "x2"], [1, 0], hp, 1, CFG["training"])


def _unused(world):
    train, universe, val = world
    wrong = synthetic_samples("validation", n_pos=30)
    with pytest.raises(hd.LeakageError):
        hm.fit_config(wrong, universe, hd.evaluation_frame(val), hp={"num_leaves": 4, "min_data_in_leaf": 10,
                      "feature_fraction": 0.9, "learning_rate": 0.2}, neg_mix="matched_only", columns=ALL_COLUMNS,
                      constraints=hm.configured_constraints(ALL_COLUMNS, CFG), seed=1, settings=tiny_cfg()["training"])


def test_validation_split_rows_are_development_rows_and_may_be_fitted():
    frame = _band_data()
    frame["split"] = "validation"
    hp = {"num_leaves": 4, "min_data_in_leaf": 20, "feature_fraction": 1.0, "learning_rate": 0.1, "lambda_l2": 1.0}
    booster, rounds = hm.fit_booster(frame, ["x1", "x2"], [1, 0], hp, 1, CFG["training"], num_rounds=3)
    assert rounds == 3 and booster.current_iteration() == 3


def test_early_stopping_uses_heldout_logloss_and_can_be_extended():
    frame = _band_data(2000)
    train, valid = frame.iloc[:1400].copy(), frame.iloc[1400:].copy()
    settings = copy.deepcopy(CFG["training"])
    settings.update(max_rounds=400, early_stopping_rounds=15)
    hp = {"num_leaves": 8, "min_data_in_leaf": 20, "feature_fraction": 1.0, "learning_rate": 0.3, "lambda_l2": 0.0}
    booster, best = hm.fit_booster(train, ["x1", "x2"], [1, 0], hp, 1, settings, valid=valid)
    assert 0 < best < 400 and booster.current_iteration() >= best
    target = booster.current_iteration() + 7
    assert hm.extend_booster(booster, target).current_iteration() == target
    assert hm.extend_booster(booster, 3).current_iteration() == target       # never shrinks
    heldout = valid["label"].to_numpy()
    p_best = hm.predict_raw(booster, valid, ["x1", "x2"], best)
    p_last = hm.predict_raw(booster, valid, ["x1", "x2"], target)
    loss = lambda p: -np.mean(heldout * np.log(p) + (1 - heldout) * np.log(1 - p))   # noqa: E731
    assert loss(p_best) <= loss(p_last)


def test_early_stopping_validation_rows_are_guarded():
    frame = _band_data()
    valid = frame.copy()
    valid["split"] = "test_2018"
    hp = {"num_leaves": 4, "min_data_in_leaf": 20, "feature_fraction": 1.0, "learning_rate": 0.1, "lambda_l2": 1.0}
    with pytest.raises(hd.LeakageError):
        hm.fit_booster(frame, ["x1", "x2"], [1, 0], hp, 1, CFG["training"], valid=valid)


def test_feature_matrix_rejects_missing_and_non_numeric_columns():
    frame = _band_data(50)
    with pytest.raises(ValueError, match="lacks required model columns"):
        hm.feature_matrix(frame, ["x1", "nope"])
    with pytest.raises(ValueError, match="not numeric"):
        hm.feature_matrix(frame.assign(x2="a"), ["x1", "x2"])
    assert hm.feature_matrix(frame, ["x1"]).dtypes.iloc[0] == np.float32



def test_ensemble_percentile_is_the_recentred_spread_and_matches_the_reported_interval():
    from live_run_helpers import tiny_model
    model = tiny_model()
    rng = np.random.default_rng(2)
    rows = pd.DataFrame({"irain_acc_1": rng.uniform(0, 100, 40), "irain_acc_3": rng.uniform(0, 300, 40),
                         "irain_acc_7": rng.uniform(0, 400, 40), "iapi_90": rng.uniform(0, 200, 40),
                         "inbr_max_acc_1": rng.uniform(0, 120, 40), "stat_slope_mean": rng.uniform(5, 40, 40)})
    scored = model.score(rows)
    assert np.array_equal(model.ensemble_percentile(rows, hm.INTERVAL_PERCENTILES[1]), scored["risk_hi"].to_numpy())
    assert np.array_equal(model.ensemble_percentile(rows, hm.INTERVAL_PERCENTILES[0]), scored["risk_lo"].to_numpy())
    p75 = model.ensemble_percentile(rows, 75.0)
    assert (model.ensemble_percentile(rows, 60.0) <= p75).all() and (p75 <= scored["risk_hi"].to_numpy()).all()
