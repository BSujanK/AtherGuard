import numpy as np
import pytest

from aetherguard.integrity import repair
from aetherguard.integrity.repair import Repairer, weighted_median

NAN = np.nan


def test_weighted_median_basics_and_nan_handling():
    values = np.array([[1.0, 5.0, NAN, NAN], [2.0, 6.0, 7.0, NAN], [10.0, 7.0, NAN, NAN]])
    weights = np.ones_like(values)
    out = weighted_median(values, weights)
    assert out[0] == 2.0 and out[1] == 6.0 and out[2] == 7.0 and np.isnan(out[3])


def test_weighted_median_respects_weights():
    values = np.array([[1.0], [2.0], [100.0]])
    assert weighted_median(values, np.array([[1.0], [1.0], [1.0]]))[0] == 2.0
    assert weighted_median(values, np.array([[1.0], [1.0], [5.0]]))[0] == 100.0    # a heavy source dominates
    assert weighted_median(values, np.array([[5.0], [1.0], [1.0]]))[0] == 1.0


def calibration_data(n=2000, seed=0):
    rng = np.random.default_rng(seed)
    truth = np.where(rng.random(n) < 0.5, rng.gamma(1.0, 10.0, n), 0.0)
    return truth, {"imd": truth + rng.normal(0, 1.0, n),                     # accurate
                   "chirps_aligned": truth + rng.normal(0, 4.0, n),         # noisier
                   "neighbours": truth + rng.normal(0, 8.0, n)}             # noisiest


def test_weights_are_inverse_validation_mae_and_sum_to_one():
    truth, refs = calibration_data()
    rep = Repairer.fit(truth, refs)
    assert sum(rep.weights.values()) == pytest.approx(1.0)
    assert rep.weights["imd"] > rep.weights["chirps_aligned"] > rep.weights["neighbours"]
    inverse = {n: 1 / m for n, m in rep.mae.items()}
    for n in repair.SOURCES:
        assert rep.weights[n] == pytest.approx(inverse[n] / sum(inverse.values()))
    assert rep.mae["imd"] == pytest.approx(np.abs(truth - refs["imd"]).mean())


def test_repair_is_the_weighted_median_with_a_band_around_it():
    truth, refs = calibration_data()
    rep = Repairer.fit(truth, refs)
    probe = {"imd": np.array([40.0]), "chirps_aligned": np.array([42.0]), "neighbours": np.array([90.0])}
    fixed, lo, hi = rep.repair(probe)
    assert fixed[0] == pytest.approx(42.0) or fixed[0] == pytest.approx(40.0)    # the median of the three, never 90
    assert lo[0] < fixed[0] < hi[0] and lo[0] >= 0


def test_repair_is_nan_without_any_reference_and_uses_what_is_available():
    truth, refs = calibration_data()
    rep = Repairer.fit(truth, refs)
    probe = {"imd": np.array([NAN, 30.0]), "chirps_aligned": np.array([NAN, NAN]), "neighbours": np.array([NAN, NAN])}
    fixed, lo, hi = rep.repair(probe)
    assert np.isnan(fixed[0]) and np.isnan(lo[0]) and np.isnan(hi[0])
    assert fixed[1] == 30.0 and np.isfinite(lo[1]) and np.isfinite(hi[1])


def test_band_quantiles_are_the_empirical_10th_and_90th_residual_percentiles_per_bin():
    truth, refs = calibration_data(6000, 1)
    rep = Repairer.fit(truth, refs)
    ens = rep.ensemble(refs)
    residual = truth - ens
    for b, mask in enumerate([ens < 1.0, (ens >= 1.0) & (ens < 10.0), ens >= 10.0]):
        lo_q, hi_q = np.quantile(residual[mask], [0.1, 0.9])
        assert rep.quantiles[str(b)] == pytest.approx([lo_q, hi_q])
    fixed, lo, hi = rep.repair({k: v[:5] for k, v in refs.items()})
    assert (lo <= fixed + 1e-9).all() or (lo >= 0).all()


def test_small_bins_fall_back_to_the_pooled_quantiles():
    truth = np.concatenate([np.zeros(200), np.array([50.0] * 5)])
    refs = {k: truth + np.random.default_rng(i).normal(0, 1, len(truth)) for i, k in enumerate(repair.SOURCES)}
    rep = Repairer.fit(truth, refs)
    assert rep.quantiles["2"] == rep.quantiles["pooled"]            # fewer than 30 heavy-rain residuals


def test_band_is_clipped_at_zero_and_json_round_trips():
    truth, refs = calibration_data()
    rep = Repairer.fit(truth, refs)
    fixed, lo, hi = rep.repair({"imd": np.array([0.0]), "chirps_aligned": np.array([0.0]), "neighbours": np.array([0.0])})
    assert lo[0] == 0.0 and hi[0] >= 0.0
    again = Repairer.from_json(rep.to_json())
    assert again.weights == rep.weights and again.quantiles == rep.quantiles
    f2, l2, h2 = again.repair({"imd": np.array([12.0]), "chirps_aligned": np.array([9.0]), "neighbours": np.array([NAN])})
    f1, l1, h1 = rep.repair({"imd": np.array([12.0]), "chirps_aligned": np.array([9.0]), "neighbours": np.array([NAN])})
    assert (f1, l1, h1) == (f2, l2, h2)


def test_fit_needs_overlap_between_truth_and_every_source():
    truth, refs = calibration_data(100)
    refs["imd"] = np.full(100, NAN)
    with pytest.raises(ValueError, match="imd"):
        Repairer.fit(truth, refs)
