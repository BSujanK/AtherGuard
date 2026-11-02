"""Early -> Late IMERG quantile mapping (aetherguard.live.early_map): synthetic rain, no network."""
from datetime import date, timedelta

import numpy as np
import pytest

from aetherguard.live import early_map as em

RNG = np.random.default_rng(7)


def wet_sample(n=20000, scale=8.0):
    return RNG.gamma(0.6, scale, n).astype(np.float32) + 0.2


def test_identical_inputs_give_the_identity_on_wet_values():
    x = wet_sample()
    mapping = em.fit_early_to_late(x, x)
    probe = np.array([0.1, 0.5, 2.0, 15.0, float(x.max())], dtype=np.float32)
    assert np.allclose(mapping.apply(probe), probe, rtol=1e-5)


def test_mapping_is_monotone_and_moves_early_to_the_late_scale():
    early = wet_sample()
    late = early * 1.5
    mapping = em.fit_early_to_late(early, late)
    grid = np.linspace(0.0, 4 * float(early.max()), 5000, dtype=np.float32)
    mapped = mapping.apply(grid)
    assert np.all(np.diff(mapped) >= 0)
    assert mapping.apply(np.array([10.0]))[0] == pytest.approx(15.0, rel=0.05)


def test_dry_early_stays_zero_and_trace_is_dropped():
    mapping = em.fit_early_to_late(wet_sample(), wet_sample())
    out = mapping.apply(np.array([0.0, 0.05, 0.0999, 0.1], dtype=np.float32))
    assert out[0] == 0 and out[1] == 0 and out[2] == 0
    assert out[3] > 0


def test_nan_stays_nan_and_shape_is_kept():
    mapping = em.fit_early_to_late(wet_sample(), wet_sample())
    values = np.array([[np.nan, 3.0], [0.0, np.nan]], dtype=np.float32)
    out = mapping.apply(values)
    assert out.shape == values.shape and out.dtype == np.float32
    assert np.isnan(out[0, 0]) and np.isnan(out[1, 1]) and out[1, 0] == 0 and np.isfinite(out[0, 1])


def test_above_the_top_quantile_scales_by_the_ratio_at_that_quantile():
    early = wet_sample()
    mapping = em.fit_early_to_late(early, early * 2.0)
    top = mapping.early_q[-1]
    assert mapping.apply(np.array([3 * top]))[0] == pytest.approx(3 * top * 2.0, rel=1e-3)


def test_below_the_first_quantile_runs_to_the_origin():
    early = wet_sample()
    mapping = em.fit_early_to_late(early, early * 2.0)
    first = mapping.early_q[0]
    assert mapping.apply(np.array([first / 2], dtype=np.float32))[0] == pytest.approx(first, rel=1e-3)


def test_pairs_with_nan_are_ignored_and_too_few_wet_values_refused():
    early, late = wet_sample(), wet_sample()
    early[:500] = np.nan
    assert em.fit_early_to_late(early, late).info["pairs"] == len(early) - 500
    with pytest.raises(ValueError, match="wet values"):
        em.fit_early_to_late(np.zeros(1000), np.zeros(1000))
    with pytest.raises(ValueError, match="same shape"):
        em.fit_early_to_late(np.zeros(3), np.zeros(4))


def test_json_round_trip_is_strict_and_exact(tmp_path):
    mapping = em.fit_early_to_late(wet_sample(), wet_sample() * 1.2)
    path = tmp_path / "map.json"
    mapping.save(path)
    assert "NaN" not in path.read_text(encoding="utf-8")
    loaded = em.EarlyLateMap.load(path)
    probe = np.array([0.0, 0.3, 4.0, 90.0], dtype=np.float32)
    assert np.array_equal(loaded.apply(probe), mapping.apply(probe))
    assert loaded.info["pairs"] == mapping.info["pairs"]


def test_invalid_curves_are_refused():
    with pytest.raises(ValueError, match="increasing"):
        em.EarlyLateMap(np.array([1.0, 1.0]), np.array([1.0, 2.0]))
    with pytest.raises(ValueError, match="positive"):
        em.EarlyLateMap(np.array([0.0, 1.0]), np.array([1.0, 2.0]))


def test_agreement_statistics():
    late = np.array([0.0, 2.0, 4.0, np.nan, 10.0])
    stats = em.agreement(np.array([1.0, 3.0, 5.0, 7.0, 10.0]), late)
    assert stats["all"]["n"] == 4
    assert stats["all"]["bias_mm"] == pytest.approx(0.75)
    assert stats["all"]["mae_mm"] == pytest.approx(0.75)
    assert stats["late_wet"]["n"] == 3


class PairStore:
    """The slice of ImergStore that run_fit reads: dates() and gather()."""

    def __init__(self, fields):
        self.fields = fields

    def dates(self):
        return sorted(self.fields)

    def gather(self, rows, cols, first_day, length):
        out = np.full((np.size(rows), length), np.nan, dtype=np.float32)
        for k in range(length):
            field = self.fields.get(first_day + timedelta(days=k))
            if field is not None:
                out[:, k] = field[np.asarray(rows), np.asarray(cols)]
        return out


def season_fields(year, factor, n_days=6):
    from aetherguard.ingest import imerg
    rng = np.random.default_rng(year)
    fields = {}
    for k in range(n_days):
        base = rng.gamma(0.5, 6.0, (imerg.ROWS, imerg.COLS)).astype(np.float32)
        fields[date(year, 7, 1) + timedelta(days=k)] = base * factor
    return fields


def test_run_fit_uses_the_fit_years_only_and_scores_the_holdout():
    early_fields, late_fields = {}, {}
    for year in (2018, 2019, 2020):
        e = season_fields(year, 1.0)
        early_fields.update(e)
        late_fields.update({d: v * 1.4 for d, v in e.items()})
    mapping, report = em.run_fit(PairStore(early_fields), PairStore(late_fields), fit_years=(2019, 2020), holdout_year=2018)
    assert sorted(report["fit"]["fit_days"]) == ["2019", "2020"]
    assert report["holdout_days"] == 6
    before, after = report["holdout"]["before"]["late_wet"], report["holdout"]["after"]["late_wet"]
    assert abs(after["bias_mm"]) < abs(before["bias_mm"])
    assert after["mae_mm"] < before["mae_mm"]
    assert "Hold-out 2018" in em.render_report(report, "map.json")
    with pytest.raises(ValueError, match="must not be in the fit years"):
        em.run_fit(PairStore(early_fields), PairStore(late_fields), fit_years=(2018, 2019), holdout_year=2018)


def test_run_fit_without_overlap_says_what_to_build():
    with pytest.raises(ValueError, match="build them first"):
        em.run_fit(PairStore({}), PairStore({}), fit_years=(2019,), holdout_year=2018)


def test_identity_map_returns_the_early_run_unchanged():
    values = np.array([[0.0, 0.03, np.nan], [5.0, 120.0, 0.1]], dtype=np.float32)
    mapped = em.IdentityMap().apply(values)
    assert np.array_equal(mapped, values, equal_nan=True) and mapped is not values and mapped.dtype == np.float32
    assert em.IdentityMap.label == "early" and em.EarlyLateMap.label == "early_mapped"


def test_report_carries_the_closing_decision_line():
    report = {"fit": {"fit_years": [2019], "pairs": 5, "fit_days": {"2019": 1}}, "dry_mm": 0.1, "holdout_year": 2018,
              "holdout_days": 0, "holdout": None, "curve": [{"early_mm": 1.0, "late_mm": 1.1, "ratio": 1.1}],
              "decision": "Decision (controller, 2026-10-15): identity used; the fitted map did not improve held-out 2018."}
    assert em.render_report(report, "map.json").rstrip().endswith(report["decision"])
    assert "Decision" not in em.render_report({**report, "decision": None}, "map.json")
