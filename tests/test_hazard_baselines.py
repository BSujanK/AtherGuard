import numpy as np
import pandas as pd
import pytest

from aetherguard.hazard import baselines as b
from aetherguard.hazard import data as d

from hazard_helpers import synthetic_samples, synthetic_universe


def _train(seed=0):
    return d.training_frame(synthetic_samples("train", n_pos=100, seed=seed), synthetic_universe("train"),
                            "matched_only", 0, 0)


def _rows(**columns):
    n = len(next(iter(columns.values())))
    base = {f"rain_acc_{k}": np.full(n, 1.0) for k in b.DURATIONS}
    base.update({"rain_acc3_vs_clim": np.full(n, 1.0), "stat_slope_mean": np.full(n, 10.0), "wet_top": np.full(n, 0.5)})
    base.update({k: np.asarray(v, dtype=float) for k, v in columns.items()})
    return pd.DataFrame(base)


def test_intensity_duration_thresholds_are_the_train_positive_10th_percentiles():
    train = _train()
    model = b.IntensityDuration().fit(train)
    positives = train[train["label"] == 1]
    for n in b.DURATIONS:
        assert model.thresholds[n] == pytest.approx(np.percentile(positives[f"rain_acc_{n}"], 10))
    share = np.mean(model.score(positives) >= 1.0)
    assert share >= 0.9


def test_intensity_duration_score_formula_on_crafted_rows():
    model = b.IntensityDuration()
    model.thresholds = {1: 10.0, 3: 20.0, 7: 50.0}
    frame = _rows(rain_acc_1=[5, 10, np.nan, np.nan], rain_acc_3=[10, 10, 60, np.nan], rain_acc_7=[100, 5, 50, np.nan])
    np.testing.assert_allclose(model.score(frame), [2.0, 1.0, 3.0, -np.inf])


def test_intensity_duration_skips_windows_without_a_positive_threshold():
    train = _train()
    train.loc[train["label"] == 1, "rain_acc_1"] = 0.0
    model = b.IntensityDuration().fit(train)
    assert 1 not in model.thresholds and 3 in model.thresholds


def test_lhasa_classes_are_quintiles_of_train_candidate_cells():
    universe = synthetic_universe("train")
    model = b.LhasaStyle().fit(universe)
    cells = universe.drop_duplicates("cell_id")["stat_slope_mean"]
    classes = model.susceptibility(universe)
    assert set(np.unique(classes)) == {1.0, 2.0, 3.0, 4.0, 5.0}
    assert np.bincount(classes.astype(int))[1:].std() / len(cells) < 0.02
    assert model.params()["n_classes"] == 5


def test_lhasa_score_and_rule_on_crafted_rows():
    model = b.LhasaStyle()
    model.edges = np.array([5.0, 10.0, 20.0, 30.0])
    frame = _rows(stat_slope_mean=[2, 12, 25, 40, 40], rain_acc3_vs_clim=[2.0, 3.0, 4.0, np.nan, 5.0])
    np.testing.assert_allclose(model.score(frame), [1 * 2.0, 3 * 3.0, 4 * 4.0, -np.inf, 5 * 5.0])
    np.testing.assert_array_equal(model.rule_alert(frame), [False, True, True, False, True])


def test_logistic_baseline_imputes_scores_and_ranks_positives_higher():
    train = _train()
    train.loc[train.index[::7], "rain_acc3_vs_clim"] = np.nan
    model = b.LogisticBaseline().fit(train)
    scores = model.score(train)
    assert np.isfinite(scores).all()
    assert scores[train["label"] == 1].mean() > scores[train["label"] == 0].mean()
    params = model.params()
    assert params["missing_indicator_columns"] == ["rain_acc3_vs_clim"]
    assert len(params["coefficients_standardised"]) == len(b.LOGISTIC_COLUMNS) + 1


def test_logistic_handles_missing_inputs_at_scoring_time():
    model = b.LogisticBaseline().fit(_train())
    frame = _rows(rain_acc_1=[np.nan, 5.0])
    assert np.isfinite(model.score(frame)).all()


def test_baselines_refuse_test_window_and_case_rows():
    train = _train()
    train.loc[0, "split"] = "test_2018"
    for model in (b.IntensityDuration(), b.LogisticBaseline()):
        with pytest.raises(d.LeakageError):
            model.fit(train)
    with pytest.raises(d.LeakageError):
        b.LhasaStyle().fit(synthetic_universe("test_2018"))
    b.LhasaStyle().fit(synthetic_universe("validation"))      # validation rows are development rows in v2


def test_missing_columns_are_reported():
    model = b.IntensityDuration().fit(_train())
    with pytest.raises(ValueError, match="lacks required columns"):
        model.score(pd.DataFrame({"rain_acc_1": [1.0]}))


def test_fit_baselines_returns_all_three_and_is_deterministic():
    samples = synthetic_samples("train", n_pos=100, n_out_of_domain=3)
    universe = synthetic_universe("train")
    first = b.fit_baselines(samples, universe)
    second = b.fit_baselines(samples, universe)
    assert set(first) == {"intensity_duration", "lhasa_style", "logistic"}
    for name in first:
        np.testing.assert_array_equal(first[name].score(samples), second[name].score(samples))
        assert first[name].params() == second[name].params()
