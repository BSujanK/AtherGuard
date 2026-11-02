import json

import numpy as np
import pandas as pd
import pytest

from aetherguard.integrity import features as feature_mod
from aetherguard.integrity import model
from aetherguard.integrity.inject import FAULT_TYPES

COLUMNS = ["own_a", "own_b", "nbr_a", "grid_a", "wet_a"]


def synth_rows(per_class=(400, 60, 60, 60, 60, 60, 60), seed=0, columns=COLUMNS) -> model.Rows:
    rng = np.random.default_rng(seed)
    ys = np.concatenate([np.full(n, c) for c, n in enumerate(per_class)])
    X = rng.normal(0, 1, (len(ys), len(columns))).astype(np.float32)
    X[:, 0] += ys * 1.5                      # own_a separates the classes
    if X.shape[1] > 2:
        X[:, 2] += (ys > 0) * 1.0            # nbr_a also helps a bit
    order = rng.permutation(len(ys))
    ys, X = ys[order], X[order]
    return model.Rows(X, ys, np.array(["S"] * len(ys)), np.arange(len(ys)).astype("datetime64[D]"), list(columns))


PARAMS = {"num_leaves": 7, "min_child_samples": 10}


def test_labels_ok_fault_and_exclusions():
    dates = pd.date_range("2010-01-01", periods=7)
    table = pd.DataFrame({
        "station": "S", "date": dates,
        "value_obs": [1.0, 2.0, np.nan, 4.0, 5.0, 6.0, 7.0],
        "fault_type": pd.Categorical(["", "spike", "spike", "", "", "zero_fault", ""]),
        "episode_id": [-1, 0, 0, 1, -1, 2, -1],                # row 3: unchanged day inside an episode window
        "clean_real": [True, True, True, True, False, True, True]})
    y = model.label_rows(table)
    assert y.tolist() == [0, FAULT_TYPES.index("spike") + 1, -1, -1, -1, FAULT_TYPES.index("zero_fault") + 1, 0]


def test_class_weights_are_sqrt_inverse_frequency_and_absent_classes_get_one():
    y = np.array([0] * 90 + [1] * 10)
    w = model.class_weights(y)
    assert w[0] == pytest.approx(np.sqrt(100 / (2 * 90))) and w[1] == pytest.approx(np.sqrt(100 / (2 * 10)))
    assert (w[2:] == 1.0).all() and w[1] > w[0]


def test_reference_dropout_hits_only_reference_groups_at_about_30_percent_independently():
    X = np.ones((20000, len(COLUMNS)), dtype=np.float32)
    out = model.reference_dropout(X, COLUMNS, seed=1)
    assert not np.isnan(out[:, :2]).any()                       # own_ untouched
    assert (X == 1).all()                                       # the input is not modified
    nan = np.isnan(out)
    for j in (2, 3, 4):
        assert nan[:, j].mean() == pytest.approx(0.3, abs=0.02)
    both = (nan[:, 2] & nan[:, 3]).mean()
    assert both == pytest.approx(0.09, abs=0.015)               # independent groups
    again = model.reference_dropout(X, COLUMNS, seed=1)
    assert np.array_equal(np.isnan(again), nan)
    assert not np.array_equal(np.isnan(model.reference_dropout(X, COLUMNS, seed=2)), nan)
    assert not np.isnan(model.reference_dropout(X[:, :2], COLUMNS[:2], seed=1)).any()


def test_macro_recall_at_fpr_known_answer():
    p = np.concatenate([np.linspace(0, 0.5, 100), [0.9, 0.2], [0.8, 0.8]])
    y = np.concatenate([np.zeros(100, int), [1, 1], [2, 2]])
    macro, per = model.macro_recall_at_fpr(p, y, 0.05)
    assert per == {"stuck_value": 0.5, "zero_fault": 1.0} and macro == pytest.approx(0.75)


def test_fit_is_deterministic_and_calibration_is_monotone_with_tau_meeting_the_target():
    train, val = synth_rows(seed=1), synth_rows(seed=2)
    a, scores = model.fit_bundle(train, val, PARAMS, seed=3, rounds=40)
    b, _ = model.fit_bundle(train, val, PARAMS, seed=3, rounds=40)
    np.testing.assert_array_equal(a.proba(val.X), b.proba(val.X))
    assert a.tau == b.tau
    assert np.all(np.diff(a.iso_y) >= 0) and np.all(np.diff(a.iso_x) > 0)
    grid = np.linspace(0, 1, 500)
    assert np.all(np.diff(a.calibrate(grid)) >= 0)
    p_cal, _ = a.score(val.X)
    clean = p_cal[val.y == 0]
    for fpr in model.FPR_LEVELS:
        assert (clean > a.tau[str(fpr)]).mean() <= fpr + 1e-12
    assert a.tau["0.005"] >= a.tau["0.01"] >= a.tau["0.02"]
    assert scores["val_macro_recall_at_1pct"] > 0.5 and set(scores["val_recall_by_class"]) == set(FAULT_TYPES)
    c, _ = model.fit_bundle(train, val, PARAMS, seed=4, rounds=40)
    assert not np.array_equal(a.proba(val.X), c.proba(val.X))


def test_trust_probabilities_are_proper_and_faults_score_higher_than_ok():
    train, val = synth_rows(seed=1), synth_rows(seed=2)
    bundle, _ = model.fit_bundle(train, val, PARAMS, seed=3, rounds=40)
    p_cal, proba = bundle.score(val.X)
    assert proba.shape == (len(val.y), 7) and np.allclose(proba.sum(axis=1), 1.0, atol=1e-5)
    assert p_cal[val.y > 0].mean() > p_cal[val.y == 0].mean() + 0.3
    assert ((p_cal >= 0) & (p_cal <= 1)).all()


def test_search_scores_every_candidate_and_picks_the_best_by_val_macro_recall():
    train, val = synth_rows(seed=1), synth_rows(seed=2)
    grid = ({"num_leaves": 3, "min_child_samples": 10}, {"num_leaves": 7, "min_child_samples": 10})
    bundle, params, candidates = model.search(train, val, seed=3, dropout=False, grid=grid)
    assert len(candidates) == 2 and params in list(grid)
    best = max(candidates, key=lambda c: (c["val_macro_recall_at_1pct"], -c["val_logloss"]))
    assert best["params"] == params
    assert bundle.card["candidates"] == candidates


def test_dropout_changes_training_but_not_validation_rows():
    train, val = synth_rows(seed=1), synth_rows(seed=2)
    with_d, _ = model.fit_bundle(train, val, PARAMS, seed=3, dropout=True, rounds=40)
    without, _ = model.fit_bundle(train, val, PARAMS, seed=3, dropout=False, rounds=40)
    assert not np.array_equal(with_d.proba(val.X), without.proba(val.X))
    assert (train.X == synth_rows(seed=1).X).all()              # the caller's training matrix is untouched


def test_model_uses_only_columns_of_the_allowed_groups():
    index = pd.date_range("2010-01-01", periods=6)
    feats = pd.DataFrame({"station": "S", "date": index, "own_x": 1.0, "nbr_x": 2.0, "grid_x": 3.0, "wet_x": 4.0}, copy=True)
    table = pd.DataFrame({"station": "S", "date": index, "value_obs": 1.0, "fault_type": pd.Categorical([""] * 6),
                          "episode_id": -1, "clean_real": True})
    rows = model.assemble_rows(feats, table, ["S"], groups=("own_", "wet_"))
    assert rows.columns == ["own_x", "wet_x"] and rows.X.shape == (6, 2) and (rows.y == 0).all()
    assert rows.idx.tolist() == list(range(6))
    train, val = synth_rows(seed=1, columns=["own_a", "own_b"]), synth_rows(seed=2, columns=["own_a", "own_b"])
    bundle, _ = model.fit_bundle(train, val, PARAMS, seed=1, rounds=10)
    assert bundle.columns == ["own_a", "own_b"] and set(bundle.booster.feature_name()) == {"own_a", "own_b"}
    assert feature_mod.select_columns(rows.columns, ["own_"]) == ["own_x"]


def test_misaligned_features_and_table_are_refused():
    index = pd.date_range("2010-01-01", periods=3)
    feats = pd.DataFrame({"station": "S", "date": index, "own_x": 1.0})
    table = pd.DataFrame({"station": "T", "date": index, "value_obs": 1.0, "fault_type": pd.Categorical([""] * 3),
                          "episode_id": -1, "clean_real": True})
    with pytest.raises(ValueError, match="same station-days"):
        model.assemble_rows(feats, table, ["S"])


def test_save_and_load_round_trip_gives_identical_scores(tmp_path):
    train, val = synth_rows(seed=1), synth_rows(seed=2)
    bundle, _ = model.fit_bundle(train, val, PARAMS, seed=3, rounds=40)
    model.save_bundle(bundle, tmp_path / "m")
    again = model.load_bundle(tmp_path / "m")
    np.testing.assert_array_equal(bundle.proba(val.X), again.proba(val.X))
    np.testing.assert_array_equal(bundle.score(val.X)[0], again.score(val.X)[0])
    assert again.tau == bundle.tau and again.columns == bundle.columns
    assert json.loads((tmp_path / "m" / "bundle.json").read_text(encoding="utf-8"))["classes"][0] == "ok"
