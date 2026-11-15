"""Spec section 12 pieces: the season-state predictor, the v2 levels and their cutoffs, the state-aware calibration."""
from datetime import date

import numpy as np
import pytest

from aetherguard.rainwarn import engine as E
from aetherguard.rainwarn import prob as P


def test_state_window_is_the_thirty_days_late_has_seen():
    days = E.state_days(date(2025, 7, 1))
    assert len(days) == 30 and days[0] == date(2025, 5, 31) and days[-1] == date(2025, 6, 29)


def test_season_state_compares_heavy_days_with_climatology_per_group():
    regions = np.array(["himalaya", "himalaya", "western_ghats", ""], dtype=object)
    observed = np.zeros((4, 30))
    observed[2, :10] = 100.0                      # western ghats pixel: 10 heavy days
    clim = np.full((4, 30), 0.1)                  # 3 expected heavy days per pixel
    s = E.season_state(observed, clim, regions)
    assert s[0] == s[1] == pytest.approx(np.log(1 / 7))          # 0 heavy against 6 expected
    assert s[2] == pytest.approx(np.log(11 / 4))
    assert s[3] == pytest.approx(np.log(1 / 4))


def test_season_state_is_neutral_with_too_few_days():
    observed = np.full((2, 30), np.nan)
    observed[:, :19] = 100.0
    assert np.all(E.season_state(observed, np.full((2, 30), 0.1), np.array(["himalaya"] * 2, dtype=object)) == 0)


def test_design_appends_the_state_column():
    fields = {"obs_max_r0": np.array([10.0]), "obs": np.array([5.0]), E.STATE: np.array([0.7])}
    plain = E.design(fields, 0, 0, "heavy", 64.5, np.array([0.01]))
    with_state = E.design(fields, 0, 0, "heavy", 64.5, np.array([0.01]), state=True)
    assert with_state.shape[1] == plain.shape[1] + 1 and with_state[0, -1] == pytest.approx(0.7)


def probs_of(**values):
    return {name: np.asarray(values.get(name, [0.0]), dtype=float) for name in P.THRESHOLDS}


def test_levels_v2_rules():
    cut = {"red": 0.3, "orange": 0.5, "yellow": 0.2}
    assert E.levels_v2(probs_of(heavy=[0.1]), cut)[0] == 0
    assert E.levels_v2(probs_of(p95=[0.25]), cut)[0] == 1
    assert E.levels_v2(probs_of(p99=[0.55]), cut)[0] == 2
    assert E.levels_v2(probs_of(heavy=[0.9], very_heavy=[0.31]), cut)[0] == 3
    assert E.levels_v2(probs_of(heavy=[np.nan]), cut)[0] == P.LEVEL_UNAVAILABLE


def test_derived_cutoffs_hit_the_target_shares():
    rng = np.random.default_rng(7)
    n = 200_000
    heavy = rng.beta(0.5, 8, n)
    probs = {"heavy": heavy, "very_heavy": heavy * rng.uniform(0.1, 0.6, n), "extremely_heavy": heavy * 0.05,
             "p95": rng.beta(0.6, 6, n), "p99": rng.beta(0.4, 9, n)}
    targets = {"red": 0.003, "orange": 0.015, "yellow": 0.06}
    cut = E.derive_levels(probs, targets)
    level = E.levels_v2(probs, cut)
    assert np.mean(level == 3) == pytest.approx(0.003, abs=2e-4)
    assert np.mean(level >= 2) == pytest.approx(0.015, abs=2e-4)
    assert np.mean(level >= 1) == pytest.approx(0.06, abs=2e-4)


def test_state_flag_and_levels_survive_the_round_trip(tmp_path):
    model = P.LogisticModel(coef=np.array([0.0, 1.0, 0.0, 0.0, 0.0, 2.0]), mean=np.zeros(5), scale=np.ones(5), n=1,
                            n_events=1, log_loss=0.1)
    entries = {1: {name: {"radius": 0, "model": model, "log_loss_by_radius": {"0": 0.1}, "state": True}
                   for name in P.FIXED_MM}}
    cal = E.Calibration(fit=[], radii=[0], entries=entries, levels={1: {"red": 0.3, "orange": 0.4, "yellow": 0.1}})
    again = E.Calibration.load(cal.save(tmp_path / "c.json"))
    assert again.uses_state() and again.levels[1]["orange"] == 0.4
    fields = {"p90_max_r0": np.array([50.0]), "p50_max_r0": np.array([20.0]), "mean_mean_r0": np.array([25.0]),
              E.STATE: np.array([1.0])}
    wet = again.probability(fields, 1, "heavy", 64.5, np.array([0.02]))
    fields[E.STATE] = np.array([-1.0])
    assert again.probability(fields, 1, "heavy", 64.5, np.array([0.02]))[0] < wet[0]


def test_log_loss_total_counts_the_scored_pixel_days():
    model = P.LogisticModel(coef=np.zeros(4), mean=np.zeros(3), scale=np.ones(3), n=1, n_events=1, log_loss=0.1)
    entry = {"radius": 0, "model": model, "state": False}
    fields = {"obs_max_r0": np.array([1.0, 100.0, np.nan]), "obs": np.array([1.0, 100.0, 3.0])}
    rows = [(fields, 64.5, np.array([0.01, 0.01, 0.01]), np.array([0.0, 80.0, 1.0]))]
    total, n = E.log_loss_total(entry, rows, 0, "heavy")
    assert n == 2 and total == pytest.approx(2 * np.log(2))
