"""Verification arithmetic of the heavy-rain warnings: tallies, Murphy terms, ROC area, day bootstrap, statements."""
import numpy as np
import pytest

from aetherguard.rainwarn import verify as V

RULES = {"min_event_pixel_days": 100, "min_event_days": 10, "rel_over_unc_max": 0.10, "calibration_in_the_large": [0.8, 1.25]}


def tally_of(days):
    t = V.Tally(len(days))
    for i, (p, o) in enumerate(days):
        t.add(i, np.asarray(p), np.asarray(o))
    return t


def test_brier_and_murphy_terms_of_a_small_case():
    t = tally_of([([0.0, 0.0, 1.0, 1.0], [0, 0, 1, 0])])
    s = V.point(t)
    assert s["n"] == 4 and s["events"] == 1 and s["event_days"] == 1
    assert s["bs"] == pytest.approx(0.25)
    assert s["base_rate"] == pytest.approx(0.25) and s["unc"] == pytest.approx(0.1875)
    # bins: p=0 (2 pairs, freq 0), p=1 (2 pairs, freq 0.5): REL = 2/4 * 0.25 = 0.125, RES = (2*0.0625 + 2*0.0625)/4
    assert s["rel"] == pytest.approx(0.125) and s["res"] == pytest.approx(0.0625)
    assert s["bs"] == pytest.approx(s["rel"] - s["res"] + s["unc"])


def test_roc_area_of_perfect_random_and_tied_forecasts():
    assert V.point(tally_of([([0.9, 0.8, 0.1, 0.05], [1, 1, 0, 0])]))["auc"] == pytest.approx(1.0)
    assert V.point(tally_of([([0.3, 0.3, 0.3, 0.3], [1, 0, 1, 0])]))["auc"] == pytest.approx(0.5)
    assert V.point(tally_of([([0.0, 1.0, 0.0, 1.0], [1, 1, 0, 0])]))["auc"] == pytest.approx(0.5)


def test_auc_bins_resolve_small_probabilities():
    s = V.point(tally_of([([0.004, 0.003, 0.0004, 0.0002], [1, 1, 0, 0])]))
    assert s["auc"] == pytest.approx(1.0)


def test_bootstrap_weights_resample_days():
    w = V.bootstrap_weights(7, 50, seed=3)
    assert w.shape == (50, 7) and np.all(w.sum(axis=1) == 7)
    assert np.array_equal(w, V.bootstrap_weights(7, 50, seed=3))


def test_arrays_round_trip():
    t = tally_of([([0.2, 0.7], [0, 1]), ([0.1], [0])])
    again = V.Tally.from_arrays(t.arrays())
    assert V.point(again) == V.point(t)


def make_case(rng, n_days=40, n=500, sharp=True):
    """A calibrated sharp forecast, its climatology and a 0/1 baseline on synthetic days."""
    prod, clim, base = V.Tally(n_days), V.Tally(n_days), V.Tally(n_days)
    for d in range(n_days):
        p = rng.beta(0.3, 6.0, n) if sharp else np.full(n, 0.05)
        o = rng.random(n) < p
        prod.add(d, p, o)
        clim.add(d, np.full(n, 0.05), o)
        base.add(d, (p > 0.5).astype(float), o)
    return prod, clim, base


def test_compare_and_statements_on_a_skilful_calibrated_forecast():
    rng = np.random.default_rng(4)
    prod, clim, base = make_case(rng)
    w = V.bootstrap_weights(prod.n_days, 300, seed=1)
    out = V.compare(prod, clim, {"det": base}, w)
    assert out["bss"] > 0 and out["bss_ci"][0] > 0 and out["auc_ci"][0] > 0.5
    assert out["vs"]["det"]["diff_ci"][1] < 0
    s = V.statements(out, RULES)
    assert s == {"enough_events": True, "skilful": True, "beats_baselines": True, "beats": {"det": True},
                 "reliable": True, "discriminates": True}


def test_statements_refuse_with_too_few_events():
    rng = np.random.default_rng(5)
    prod = V.Tally(3)
    for d in range(3):
        prod.add(d, np.full(100, 0.01), rng.random(100) < 0.01)
    out = V.compare(prod, prod, {}, V.bootstrap_weights(3, 20, seed=1))
    assert V.statements(out, RULES) == {"enough_events": False}


def test_sample_reference_uses_the_base_rate_of_the_resample():
    rng = np.random.default_rng(6)
    prod, _, _ = make_case(rng, sharp=False)
    out = V.compare(prod, None, {}, V.bootstrap_weights(prod.n_days, 100, seed=2), sample_reference=True)
    assert out["bs_reference"] == pytest.approx(out["unc"])
    assert abs(out["bss"]) < 0.05          # a constant 0.05 forecast is close to the sample climatology
