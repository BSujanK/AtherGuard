import numpy as np
import pandas as pd
import pytest

from aetherguard.corrector import model as cm

COLUMNS = ["chirps_1", "wet_top", "month"]


def synth(n=3000, seed=0, stations=6):
    rng = np.random.default_rng(seed)
    chirps = np.where(rng.random(n) < 0.5, rng.gamma(0.8, 8.0, n), 0.0)
    gauge = np.where(chirps > 0, chirps * rng.lognormal(0.2, 0.7, n), rng.gamma(0.3, 2.0, n) * (rng.random(n) < 0.2))
    frame = pd.DataFrame({"station": rng.integers(0, stations, n).astype(str), "chirps_1": chirps,
                          "wet_top": rng.random(n), "month": rng.integers(1, 13, n).astype(float), "gauge": gauge})
    frame["exceed"] = (frame["gauge"] >= np.percentile(gauge[gauge >= 1], 97)).astype(float)
    return frame


@pytest.fixture(scope="module")
def fitted():
    train, val = synth(seed=1), synth(seed=2)
    small = ({"num_leaves": 7, "min_data_in_leaf": 30},)
    return train, val, cm.fit_corrector(train, val, COLUMNS, seed=3, quantile_grid=small, classifier_grid=small)


def test_pinball_loss_formula():
    y = np.array([10.0, 10.0])
    pred = np.array([6.0, 14.0])
    assert cm.pinball(y, pred, 0.9).tolist() == pytest.approx([0.9 * 4, 0.1 * 4])
    assert cm.pinball(y, pred, 0.5).tolist() == pytest.approx([2.0, 2.0])
    assert cm.pinball(10.0, 10.0, 0.99) == 0.0


def test_quantiles_are_ordered_non_negative_and_roughly_calibrated(fitted):
    train, val, model = fitted
    test = synth(seed=7)
    pred = model.predict(test)
    assert (pred["q50"] <= pred["q90"]).all() and (pred["q90"] <= pred["q99"]).all() and (pred["q50"] >= 0).all()
    assert (test["gauge"] <= pred["q90"]).mean() == pytest.approx(0.9, abs=0.05)
    assert (test["gauge"] <= pred["q99"]).mean() == pytest.approx(0.99, abs=0.02)
    assert ((pred["p_exceed"] >= 0) & (pred["p_exceed"] <= 1)).all()
    assert pred["p_exceed"][test["exceed"] == 1].mean() > pred["p_exceed"][test["exceed"] == 0].mean()


def test_learned_quantiles_beat_the_raw_value_in_pinball_loss(fitted):
    _, _, model = fitted
    test = synth(seed=9)
    pred = model.predict(test)
    for alpha, name in zip(cm.ALPHAS, ("q50", "q90", "q99")):
        assert cm.pinball(test["gauge"], pred[name], alpha).mean() < cm.pinball(test["gauge"], test["chirps_1"], alpha).mean()


def test_training_is_deterministic_and_only_uses_the_given_columns(fitted):
    train, val, model = fitted
    small = ({"num_leaves": 7, "min_data_in_leaf": 30},)
    again = cm.fit_corrector(train, val, COLUMNS, seed=3, quantile_grid=small, classifier_grid=small)
    test = synth(seed=7)
    pd.testing.assert_frame_equal(model.predict(test), again.predict(test))
    assert model.columns == COLUMNS and set(model.quantiles[0.5].feature_name()) == set(COLUMNS)
    other = cm.fit_corrector(train, val, COLUMNS, seed=4, quantile_grid=small, classifier_grid=small)
    assert not model.predict(test).equals(other.predict(test))
    extra = test.assign(unrelated=123.0)
    pd.testing.assert_frame_equal(model.predict(extra), model.predict(test))        # extra columns are ignored


def test_missing_predictors_are_tolerated(fitted):
    _, _, model = fitted
    test = synth(seed=7).head(50)
    test.loc[test.index[:10], ["wet_top", "month"]] = np.nan
    pred = model.predict(test)
    assert np.isfinite(pred[["q50", "q90", "q99", "p_exceed"]].to_numpy()).all()


def test_tuning_is_recorded_per_target(fitted):
    _, _, model = fitted
    tuning = model.card["tuning"]
    assert set(tuning) >= {"0.5", "0.9", "0.99", "exceedance"}
    assert tuning["0.9"]["selected"] == {"num_leaves": 7, "min_data_in_leaf": 30}
    assert model.card["train_stations"] == 6 and model.card["train_exceedances"] > 0


def test_grid_choice_is_made_on_validation_pinball():
    train, val = synth(seed=1), synth(seed=2)
    grid = ({"num_leaves": 3, "min_data_in_leaf": 30}, {"num_leaves": 15, "min_data_in_leaf": 30})
    model = cm.fit_corrector(train, val, COLUMNS, seed=3, quantile_grid=grid, classifier_grid=grid)
    for alpha in ("0.5", "0.9", "0.99"):
        best = min(model.card["tuning"][alpha]["candidates"], key=lambda c: c["val_pinball"])
        assert model.card["tuning"][alpha]["selected"] == best["params"]


def test_without_exceedances_the_classifier_is_skipped_and_probability_is_nan():
    train, val = synth(seed=1), synth(seed=2)
    train["exceed"] = 0.0
    model = cm.fit_corrector(train, val, COLUMNS, seed=3, quantile_grid=({"num_leaves": 7, "min_data_in_leaf": 30},))
    assert model.classifier is None and model.predict(val.head(5))["p_exceed"].isna().all()


def test_save_and_load_round_trip(fitted, tmp_path):
    _, _, model = fitted
    model.save(tmp_path / "m")
    again = cm.CorrectorModel.load(tmp_path / "m")
    test = synth(seed=7)
    pd.testing.assert_frame_equal(model.predict(test), again.predict(test))
    assert again.columns == model.columns and again.card["seed"] == 3


def test_linear_quantile_baseline_recovers_a_known_scaling():
    rng = np.random.default_rng(0)
    x = rng.gamma(2.0, 5.0, 4000)
    y = 2.0 * x + rng.normal(0, 1.0, 4000)
    coefs = cm.linear_quantile_baseline(pd.DataFrame({"chirps_1": x, "gauge": y}))
    assert coefs[0.5][0] == pytest.approx(2.0, abs=0.05) and abs(coefs[0.5][1]) < 0.3
    assert coefs[0.99][1] > coefs[0.5][1] and coefs[0.99][0] == pytest.approx(2.0, abs=0.2)
    pred = cm.apply_linear(coefs, [0.0, 10.0, 50.0])
    assert (pred["q50"] <= pred["q90"]).all() and (pred["q90"] <= pred["q99"]).all() and (pred >= 0).all().all()
