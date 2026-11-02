import json

import numpy as np
import pandas as pd
import pytest
from integrity_helpers import synthetic_raw_years, write_toy_rain_store

from aetherguard.integrity import day_basis

INDEX = pd.date_range("2007-01-01", "2018-12-31", freq="D")


def ref_series(seed=0, n=len(INDEX)):
    rng = np.random.default_rng(seed)
    return np.where(rng.random(n) < 0.5, rng.gamma(0.8, 12.0, n), 0.0)


def frames(station, ref):
    return (pd.DataFrame({"S": station}, index=INDEX), pd.DataFrame({"S": ref}, index=INDEX))


def test_shifted_semantics():
    x = np.arange(5.0)
    assert day_basis.shifted(x, 1).tolist()[:4] == [1, 2, 3, 4] and np.isnan(day_basis.shifted(x, 1)[4])
    assert day_basis.shifted(x, -2)[2:].tolist() == [0, 1, 2] and np.isnan(day_basis.shifted(x, -2)[:2]).all()
    assert day_basis.shifted(x, 0).tolist() == x.tolist()


@pytest.mark.parametrize("shift", [-2, -1, 0, 1, 2])
def test_the_peak_lag_recovers_a_known_shift(shift):
    ref = ref_series(1)
    station = day_basis.shifted(ref, shift)               # station[t] = ref[t + shift]: pairs best at lag +shift
    noise = np.random.default_rng(2).normal(0, 0.5, len(station))
    s, r = frames(np.where(np.isfinite(station), np.maximum(station + noise, 0), np.nan), ref)
    summary = day_basis.summarize(day_basis.lag_table(s, r), n_boot=50)
    assert summary["peak_lag_pearson"] == shift and summary["peak_lag_spearman"] == shift
    assert summary["lags"][str(shift)]["median_pearson"] > 0.9
    assert summary["lags"][str(shift)]["n_stations"] == 1


def test_pairs_need_both_valid_and_at_least_one_positive_and_enough_of_them():
    n = len(INDEX)
    ref = ref_series(3)
    station = ref.copy()
    station[:200] = np.nan                                # invalid days drop out
    s, r = frames(station, ref)
    row = day_basis.lag_correlations(s["S"].to_numpy(), r["S"].to_numpy(), 0, np.ones(n, dtype=bool))
    wet = (ref > 0)
    assert row["n_pairs"] == int(wet[200:].sum())         # shared dry days are excluded
    assert row["pearson"] == pytest.approx(1.0) and row["spearman"] == pytest.approx(1.0)
    few = day_basis.lag_correlations(s["S"].to_numpy(), r["S"].to_numpy(), 0, np.arange(n) < 230)
    assert few["n_pairs"] < day_basis.MIN_PAIRS and np.isnan(few["pearson"]) and np.isnan(few["spearman"])


def test_correlation_rows_outside_the_period_are_ignored():
    ref = ref_series(4)
    station = ref.copy()
    station[INDEX >= "2016-01-01"] = ref_series(9)[INDEX >= "2016-01-01"]   # unrelated after 2015
    s, r = frames(station, ref)
    full = day_basis.lag_table(s, r, lags=(0,), period=("2007-01-01", "2018-12-31"))
    early = day_basis.lag_table(s, r, lags=(0,), period=("2007-01-01", "2015-12-31"))
    assert early["pearson"].iloc[0] == pytest.approx(1.0) and full["pearson"].iloc[0] < 0.95


def test_summary_medians_ci_and_station_peak_counts():
    ref = ref_series(5)
    cols = {}
    for k, shift in enumerate([0, 0, 0, 1]):
        base = day_basis.shifted(ref, shift)
        cols[f"S{k}"] = np.maximum(base + np.random.default_rng(10 + k).normal(0, 0.3, len(ref)), 0)
    station = pd.DataFrame(cols, index=INDEX)
    refs = pd.DataFrame({k: ref for k in cols}, index=INDEX)
    summary = day_basis.summarize(day_basis.lag_table(station, refs), n_boot=100)
    assert summary["per_station_peak_lag_counts"] == {"0": 3, "1": 1}
    assert summary["peak_lag_pearson"] == 0 and summary["lags"]["0"]["n_stations"] == 4
    lo, hi = summary["lags"]["0"]["pearson_ci"]
    assert lo <= summary["lags"]["0"]["median_pearson"] <= hi


def test_exceedance_agreement_counts_by_lag():
    ref = np.zeros(len(INDEX))
    station = np.zeros(len(INDEX))
    ref[[100, 200, 300, 400]] = 80.0
    station[[100, 200, 301]] = 60.0                       # 2 same-day hits; day 301 pairs with ref day 300 (lag -1)
    s, r = frames(station, ref)
    table = day_basis.exceedance_table(s, r, lags=(-1, 0, 1), n_boot=50)
    zero = table["0"]
    assert zero["station_exceedances"] == 3 and zero["reference_also_exceeds"] == 2
    assert zero["share_of_station_days"] == pytest.approx(2 / 3)
    assert zero["reference_exceedances"] == 4 and zero["station_also_exceeds"] == 2
    assert table["-1"]["reference_also_exceeds"] == 1    # station day 301 pairs with ref day 300
    assert table["1"]["reference_also_exceeds"] == 0


def test_report_states_the_peak_lags_and_flags_a_non_zero_imd_peak():
    ref = ref_series(6)
    station = np.maximum(day_basis.shifted(ref, 1) + np.random.default_rng(1).normal(0, 0.3, len(ref)), 0)
    s, r = frames(station, ref)
    refs = {"imd": r, "chirps_utc": r, "chirps_aligned": r}
    report = day_basis.build_day_basis_report(s, refs, n_boot=30)
    text = " ".join(report["verdict"])
    assert "peaks at lag +1" in text and "NOT the maximum" in text and "does NOT peak at lag 0" in text
    assert report["products"]["imd"]["peak_lag_pearson"] == 1
    md = day_basis.render_markdown(report)
    assert "station vs chirps_aligned" in md and "Exceedance" in md and "Verdict" in md
    json.loads(json.dumps(report, allow_nan=True))


def test_end_to_end_cli_on_toy_stores(tmp_path, isolated_data_root):
    raw = synthetic_raw_years(tmp_path)
    write_toy_rain_store(isolated_data_root / "processed" / "rain")
    out = tmp_path / "reports"
    assert day_basis.main(["--raw-dir", str(raw), "--reports-dir", str(out), "--n-boot", "20"]) == 0
    report = json.loads((out / "phase2b_day_basis.json").read_text(encoding="utf-8"))
    assert report["n_stations"] == 10 and set(report["products"]) == {"imd", "chirps_utc", "chirps_aligned"}
    assert (out / "phase2b_day_basis.md").read_text(encoding="utf-8").startswith("# Phase 2b")
