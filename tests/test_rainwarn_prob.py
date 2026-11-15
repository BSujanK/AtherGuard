"""Heavy-rain probability engine: quantile CDF, neighbourhoods, predictors, logistic calibration, warning levels."""
import numpy as np
import pytest

from aetherguard.rainwarn import prob as P


def test_thresholds_are_the_imd_categories_and_the_two_percentiles():
    assert P.FIXED_MM == {"heavy": 64.5, "very_heavy": 115.6, "extremely_heavy": 204.5}
    assert P.THRESHOLDS == ("heavy", "very_heavy", "extremely_heavy", "p95", "p99")
    assert P.is_percentile("p95") and not P.is_percentile("heavy")


def test_quantile_exceedance_passes_through_the_stored_quantiles():
    p10, p50, p90 = np.array([10.0]), np.array([40.0]), np.array([100.0])
    for t, expected in ((10.0, 0.9), (40.0, 0.5), (100.0, 0.1), (5.0, 0.95), (70.0, 0.3)):
        assert P.quantile_exceedance(p10, p50, p90, t)[0] == pytest.approx(expected)


def test_quantile_exceedance_tail_is_exponential_through_p50_and_p90():
    p10, p50, p90 = np.array([0.0]), np.array([20.0]), np.array([60.0])
    t = 60.0 + 40.0                 # one more (p90 - p50) above p90: the tail falls by the factor 5 again
    assert P.quantile_exceedance(p10, p50, p90, t)[0] == pytest.approx(0.02)


def test_quantile_exceedance_is_zero_above_a_degenerate_ensemble_and_nan_stays_nan():
    out = P.quantile_exceedance(np.array([0.0, np.nan]), np.array([0.0, 1.0]), np.array([0.0, 2.0]), 64.5)
    assert out[0] == 0.0 and np.isnan(out[1])


def test_quantile_exceedance_falls_with_the_threshold():
    p10, p50, p90 = np.full(1, 5.0), np.full(1, 30.0), np.full(1, 90.0)
    values = [P.quantile_exceedance(p10, p50, p90, t)[0] for t in np.linspace(0.5, 300, 60)]
    assert all(a >= b for a, b in zip(values, values[1:]))


def test_neighbourhood_max_and_mean_ignore_nan():
    grid = np.array([[1.0, np.nan, 3.0], [4.0, 5.0, 6.0], [7.0, 8.0, np.nan]])
    assert P.neighbourhood(grid, 0, "max")[0, 0] == 1.0
    assert P.neighbourhood(grid, 1, "max")[0, 0] == 5.0
    assert P.neighbourhood(grid, 1, "mean")[0, 0] == pytest.approx((1 + 4 + 5) / 3)
    assert P.neighbourhood(grid, 1, "max")[2, 2] == 8.0
    alone = np.full((3, 3), np.nan)
    assert np.isnan(P.neighbourhood(alone, 1, "max")).all() and np.isnan(P.neighbourhood(alone, 1, "mean")).all()


def test_predictors_add_log_threshold_only_for_percentiles():
    fields = {"a": np.array([10.0, 100.0]), "b": np.array([0.0, 50.0])}
    clim = np.array([0.01, 0.2])
    fixed = P.predictors(fields, ("a", "b"), 64.5, clim, percentile=False)
    pct = P.predictors(fields, ("a", "b"), np.array([30.0, 80.0]), clim, percentile=True)
    assert fixed.shape == (2, 3) and pct.shape == (2, 4)
    assert fixed[1, 0] == pytest.approx(np.log1p(100.0) - np.log1p(64.5))
    assert fixed[0, 2] == pytest.approx(np.log(0.01 / 0.99))
    assert pct[1, 3] == pytest.approx(np.log1p(80.0))


def test_clim_logit_is_floored():
    x = P.predictors({"a": np.array([1.0])}, ("a",), 64.5, np.array([0.0]), percentile=False)
    assert x[0, 1] == pytest.approx(np.log(P.CLIM_FLOOR / (1 - P.CLIM_FLOOR)))


def test_logistic_fit_recovers_known_coefficients():
    rng = np.random.default_rng(1)
    x = rng.normal(size=(200_000, 2))
    truth = 1.0 / (1.0 + np.exp(-(-2.0 + 1.5 * x[:, 0] - 0.7 * x[:, 1])))
    y = rng.random(len(truth)) < truth
    model = P.fit_logistic(x, y)
    p = P.predict_logistic(model, x)
    assert np.abs(p - truth).max() < 0.02
    assert model.n == 200_000 and model.n_events == int(y.sum())
    again = P.LogisticModel.from_dict(model.to_dict())
    assert np.allclose(P.predict_logistic(again, x[:5]), p[:5])


def test_logistic_prediction_is_nan_where_a_predictor_is_nan():
    rng = np.random.default_rng(2)
    x = rng.normal(size=(5000, 1))
    model = P.fit_logistic(x, rng.random(5000) < 0.3)
    out = P.predict_logistic(model, np.array([[0.0], [np.nan]]))
    assert np.isfinite(out[0]) and np.isnan(out[1])


def test_warning_levels_first_match_wins():
    def level(**p):
        probs = {name: np.array([p.get(name, 0.0)]) for name in P.THRESHOLDS}
        return int(P.warning_levels(probs)[0])
    assert level() == 0
    assert level(heavy=0.2) == 1
    assert level(p95=0.4) == 1
    assert level(p95=0.39, heavy=0.19) == 0
    assert level(heavy=0.5) == 2
    assert level(very_heavy=0.2) == 2
    assert level(p99=0.4) == 2
    assert level(very_heavy=0.5) == 3
    assert level(extremely_heavy=0.25, heavy=0.1) == 3


def test_warning_levels_are_unavailable_where_a_probability_is_missing():
    probs = {name: np.array([0.9, np.nan]) for name in P.THRESHOLDS}
    out = P.warning_levels(probs)
    assert out[0] == 3 and out[1] == P.LEVEL_UNAVAILABLE
    assert P.LEVEL_NAMES[P.LEVEL_UNAVAILABLE] == "unavailable" and P.LEVEL_NAMES[3] == "red"
