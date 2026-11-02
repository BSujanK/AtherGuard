"""Forecast-day skill (aetherguard.live.forecast_skill): GFS vs IMERG rain metrics, the forecast-feature risk pair, the
interval-widening factors and the freeze gate. Synthetic inputs in tmp_path; no network, no project data."""
import json
from datetime import date, timedelta

import lightgbm as lgb
import numpy as np
import pandas as pd
import pytest

from aetherguard.features import imerg_features as F
from aetherguard.grid import latlon_to_cell
from aetherguard.hazard.calibration import MonotoneCalibrator
from aetherguard.hazard.model import HazardModel
from aetherguard.ingest import gfs, imerg
from aetherguard.live import forecast_skill as FS
from aetherguard.live import run as live_run

import live_run_helpers as H

DAY = H.DAY
THRESHOLDS = H.THRESHOLDS


def many_cells(per_point=12) -> pd.DataFrame:
    """The four helper points and a row of neighbouring cells beside each (same region and terrain columns)."""
    base = H.tiny_cells()
    rows = []
    for _, row in base.iterrows():
        for k in range(per_point):
            lon = row["lon"] + 0.1 * k
            rows.append({**row, "cell_id": int(latlon_to_cell(row["lat"], lon)), "lon": lon})
    return pd.DataFrame(rows).drop_duplicates("cell_id").reset_index(drop=True)


CELLS = many_cells()
CLIM = H.tiny_clim(CELLS)


def rain_model() -> HazardModel:
    """A small monotone model whose risk reacts to the 1-day and the 3-day rain separately (the helper model's inputs are
    all multiples of one another, so it ignores all but one of them)."""
    rng = np.random.default_rng(5)
    n = 6000
    acc1, acc3 = rng.uniform(0, 150, n), rng.uniform(0, 300, n)
    frame = pd.DataFrame({"irain_acc_1": acc1, "irain_acc_3": acc3 + acc1, "irain_acc_7": acc3 * 1.5 + rng.uniform(0, 100, n),
                          "iapi_90": rng.uniform(0, 400, n), "inbr_max_acc_1": acc1 * 1.1,
                          "stat_slope_mean": rng.uniform(5, 40, n)}).astype(np.float32)
    y = (acc3 + 2 * acc1 + rng.normal(0, 30, n) > 220).astype(int)
    constraints = [1, 1, 1, 1, 1, 0]
    params = dict(objective="binary", num_leaves=7, min_data_in_leaf=20, learning_rate=0.2, verbosity=-1, seed=1,
                  deterministic=True, force_row_wise=True, monotone_constraints=constraints)
    booster = lgb.train(params, lgb.Dataset(frame, y), num_boost_round=40)
    members = [lgb.train({**params, "seed": 10 + k}, lgb.Dataset(frame.iloc[idx], y[idx]), num_boost_round=40)
               for k, idx in enumerate(np.random.default_rng(10 + j).integers(0, n, n) for j in range(3))]
    return HazardModel(H.MODEL_COLUMNS, constraints, booster, 40, members,
                       MonotoneCalibrator.fit(booster.predict(frame), y, np.ones(n)), {})


class RandomStore:
    """Deterministic UTC-day rain at every pixel; days listed in `planted` are replaced by a constant."""

    def __init__(self, planted=None):
        self.planted = dict(planted or {})

    def gather(self, rows, cols, first_day, length):
        rows, cols = np.asarray(rows, dtype=np.int64), np.asarray(cols, dtype=np.int64)
        out = np.empty((rows.size, length), dtype=np.float32)
        for k in range(length):
            d = first_day + timedelta(days=k)
            if d in self.planted:
                out[:, k] = self.planted[d]
            else:
                mix = (d.toordinal() * 7919 + rows * 104729 + cols * 1299709) % 997
                out[:, k] = np.where(mix % 5 == 0, 0.0, mix / 997 * 90.0)
        return out


def observed_imd(store, day, n=3):
    """Observed IMD-day totals of D+1..D+n on the whole grid, (n, rows, cols) float32."""
    rows, cols = np.indices((imerg.ROWS, imerg.COLS))
    utc = store.gather(rows.ravel(), cols.ravel(), day, n + 1)
    return F.imd_day_series(utc).T.reshape(n, imerg.ROWS, imerg.COLS).astype(np.float32)


def write_gfs(rain_dir, day, days, valid=(True, True, True)):
    rain_dir.mkdir(parents=True, exist_ok=True)
    np.savez(rain_dir / f"gfs_imdday_{day.isoformat()}.npz", days=days.astype(np.float32),
             day_valid=np.array(valid), lead_days=np.array([1, 2, 3], dtype=np.int32))


# ------------------------------------------------------------------------------------------------- ratio histogram

def test_ratio_histogram_quantiles_match_numpy_within_the_bin_width():
    rng = np.random.default_rng(1)
    ratios = np.exp(rng.normal(0.0, 0.7, 5000))
    hist = FS.RatioHistogram()
    hist.add(ratios[:2000])
    hist.add(ratios[2000:])
    for q in (0.1, 0.5, 0.9):
        assert hist.quantile(q) == pytest.approx(np.quantile(ratios, q), rel=0.03)


def test_ratio_histogram_counts_zero_ratios_below_every_other_value():
    hist = FS.RatioHistogram()
    hist.add(np.array([0.0, 0.0, 0.0, 2.0]))
    assert hist.n == 4
    assert hist.quantile(0.5) == 0.0
    assert hist.quantile(0.99) == pytest.approx(2.0, rel=0.03)


def test_ratio_histogram_without_data_has_no_quantile():
    assert np.isnan(FS.RatioHistogram().quantile(0.5))


# ----------------------------------------------------------------------------------------------- rain skill metrics

OBS = np.array([0.0, 0.5, 5.0, 20.0, 60.0, 120.0])
FCST = np.array([1.0, 0.0, 10.0, 10.0, 70.0, 40.0])


def test_skill_accumulator_matches_hand_computed_values():
    acc = FS.SkillAccumulator()
    acc.add(OBS, FCST)
    s = acc.summary()
    assert s["n"] == 6
    assert s["bias_mm"] == pytest.approx(-74.5 / 6)          # errors 1, -0.5, 5, -10, 10, -80
    assert s["mae_mm"] == pytest.approx(106.5 / 6)
    assert s["correlation"] == pytest.approx(np.corrcoef(OBS, FCST)[0, 1])
    assert s["mean_obs_mm"] == pytest.approx(205.5 / 6) and s["mean_fcst_mm"] == pytest.approx(131.0 / 6)
    e50, e100 = s["events"]["50"], s["events"]["100"]
    assert (e50["hits"], e50["misses"], e50["false_alarms"], e50["correct_negatives"]) == (1, 1, 0, 4)
    assert e50["hit_rate"] == 0.5 and e50["false_alarm_ratio"] == 0.0
    assert (e100["hits"], e100["misses"], e100["false_alarms"]) == (0, 1, 0)
    assert e100["hit_rate"] == 0.0 and e100["false_alarm_ratio"] is None      # nothing forecast: ratio undefined


def test_skill_accumulator_bins_and_ratio_quantiles():
    acc = FS.SkillAccumulator()
    acc.add(OBS, FCST)
    bins = {b["label"]: b for b in acc.summary()["bins"]}
    assert [b["n"] for b in bins.values()] == [2, 1, 1, 0, 1, 1]
    assert list(bins) == ["<1", "1-10", "10-25", "25-50", "50-100", ">=100"]
    # forecast / observed where the observed rain is measurable (>= 0.1 mm): 0.5 mm -> 0, 5 -> 2, 20 -> 0.5, 60 -> 7/6, 120 -> 1/3
    assert bins["<1"]["ratio_n"] == 1 and bins["<1"]["ratio_quantiles"]["p50"] == 0.0
    assert bins["1-10"]["ratio_quantiles"]["p50"] == pytest.approx(2.0, rel=0.03)
    assert bins["10-25"]["ratio_quantiles"]["p50"] == pytest.approx(0.5, rel=0.03)
    assert bins["50-100"]["ratio_quantiles"]["p50"] == pytest.approx(70 / 60, rel=0.03)
    assert bins[">=100"]["ratio_quantiles"]["p50"] == pytest.approx(40 / 120, rel=0.03)
    assert bins["25-50"]["n"] == 0 and bins["25-50"]["bias_mm"] is None and bins["25-50"]["ratio_quantiles"]["p50"] is None
    assert bins["10-25"]["bias_mm"] == pytest.approx(-10.0) and bins["10-25"]["mae_mm"] == pytest.approx(10.0)


def test_skill_accumulator_drops_pairs_with_a_missing_value_and_counts_them():
    obs = np.concatenate([OBS, [np.nan, 3.0]])
    fcst = np.concatenate([FCST, [4.0, np.nan]])
    acc = FS.SkillAccumulator()
    acc.add(obs, fcst)
    s = acc.summary()
    assert s["n"] == 6 and s["n_dropped_missing"] == 2
    assert s["bias_mm"] == pytest.approx(-74.5 / 6)


def test_skill_accumulator_is_independent_of_how_the_pairs_are_chunked():
    whole, parts = FS.SkillAccumulator(), FS.SkillAccumulator()
    whole.add(OBS, FCST)
    parts.add(OBS[:2], FCST[:2])
    parts.add(OBS[2:], FCST[2:])
    assert whole.summary() == parts.summary()


def test_skill_accumulator_without_pairs_reports_none_not_zero():
    s = FS.SkillAccumulator().summary()
    assert s["n"] == 0 and s["bias_mm"] is None and s["correlation"] is None
    assert s["events"]["50"]["hit_rate"] is None


def test_correlation_is_none_for_a_constant_series():
    acc = FS.SkillAccumulator()
    acc.add(np.full(5, 3.0), np.arange(5.0))
    assert acc.summary()["correlation"] is None


# ------------------------------------------------------------------------------------------------ region of a pixel

def test_pixel_regions_follow_the_cells_that_fall_in_the_pixel():
    cells = pd.DataFrame({"cell_id": CELLS["cell_id"], "region": CELLS["region"]})
    labels = FS.pixel_region_labels(cells["cell_id"].to_numpy(), cells["region"].to_numpy(), min_cells=1)
    assert labels.shape == (imerg.ROWS * imerg.COLS,)
    for name, (_, _, region) in H.POINTS.items():
        row, col = H.pixel_of(name)
        assert labels[row * imerg.COLS + col] == region
    assert (labels == "").sum() == labels.size - len(np.unique(F.cell_pixels(cells["cell_id"].to_numpy())))


def test_pixel_region_needs_a_majority_of_in_region_cells():
    row, col = H.pixel_of("wayanad")
    lat, lon = imerg.domain_lat()[row], imerg.domain_lon()[col]
    quad = [int(latlon_to_cell(lat + dy, lon + dx)) for dy in (-0.025, 0.025) for dx in (-0.025, 0.025)]
    assert len(set(F.cell_pixels(quad))) == 1
    regions = ["western_ghats", "western_ghats", "out_of_scope", "out_of_scope"]
    flat = row * imerg.COLS + col
    assert FS.pixel_region_labels(np.array(quad), np.array(regions), min_cells=2)[flat] == "western_ghats"
    assert FS.pixel_region_labels(np.array(quad), np.array(regions), min_cells=3)[flat] == ""
    mixed = ["western_ghats", "himalaya", "out_of_scope", "out_of_scope"]
    assert FS.pixel_region_labels(np.array(quad), np.array(mixed), min_cells=1)[flat] == ""    # no plurality


# ---------------------------------------------------------------------------------------------- GFS archive reading

def test_gfs_day_file_name_is_the_ingest_one(tmp_path):
    day = date(2023, 7, 1)
    assert FS.gfs_day_path(tmp_path, day).name == gfs.day_file_path(tmp_path, day).name


def test_load_gfs_day_returns_none_for_a_missing_file_and_reads_validity(tmp_path):
    day = date(2023, 7, 1)
    assert FS.load_gfs_day(tmp_path, day) is None
    write_gfs(tmp_path, day, np.ones((3, imerg.ROWS, imerg.COLS)), valid=(True, False, True))
    days, valid = FS.load_gfs_day(tmp_path, day)
    assert days.shape == (3, imerg.ROWS, imerg.COLS) and valid.tolist() == [True, False, True]


# ----------------------------------------------------------------------------------------------- rain skill, end to end

def test_rain_skill_scores_each_lead_against_the_imd_day_of_imerg(tmp_path):
    store = RandomStore()
    issue = [date(2023, 7, 1), date(2023, 7, 2)]
    for d in issue:
        obs = observed_imd(store, d)
        write_gfs(tmp_path, d, np.stack([obs[0], obs[1] * 2.0, obs[2]]), valid=(True, True, d != issue[1]))
    n_pixels = imerg.ROWS * imerg.COLS
    out = FS.rain_skill(store, tmp_path, issue, {"domain": np.arange(n_pixels)})
    assert out["issue_days"] == 2 and out["gfs_files_missing"] == 0
    lead1, lead2, lead3 = (out["leads"][str(k)]["domain"] for k in (1, 2, 3))
    assert lead1["n"] == 2 * n_pixels and lead1["bias_mm"] == pytest.approx(0.0, abs=1e-4)
    assert lead1["correlation"] == pytest.approx(1.0)
    assert lead2["bias_mm"] > 0 and lead2["correlation"] == pytest.approx(1.0)
    assert lead2["mean_fcst_mm"] == pytest.approx(2 * lead2["mean_obs_mm"], rel=1e-4)
    assert lead3["n"] == n_pixels                                    # the second day's lead 3 is flagged invalid
    assert out["leads"]["3"]["days_used"] == 1 and out["leads"]["1"]["days_used"] == 2


def test_rain_skill_alignment_matches_a_hand_read_pixel(tmp_path):
    store = RandomStore()
    day = date(2023, 7, 10)
    row, col = H.pixel_of("wayanad")
    one = store.gather([row], [col], day, 4)[0].astype(np.float64)
    expected = [0.875 * one[k - 1] + 0.125 * one[k] for k in (1, 2, 3)]       # IMD day D+k from UTC D+k-1 and D+k
    write_gfs(tmp_path, day, np.zeros((3, imerg.ROWS, imerg.COLS)))
    out = FS.rain_skill(store, tmp_path, [day], {"point": np.array([row * imerg.COLS + col])})
    for k in (1, 2, 3):
        s = out["leads"][str(k)]["point"]
        assert s["mean_obs_mm"] == pytest.approx(expected[k - 1], rel=1e-5)
        assert s["mean_fcst_mm"] == 0.0


def test_rain_skill_counts_issue_days_without_a_file_and_never_reads_zero_for_them(tmp_path):
    store = RandomStore()
    day = date(2023, 7, 10)
    out = FS.rain_skill(store, tmp_path, [day], {"domain": np.arange(10)})
    assert out["gfs_files_missing"] == 1 and out["leads"]["1"]["days_used"] == 0
    assert out["leads"]["1"]["domain"]["n"] == 0 and out["leads"]["1"]["domain"]["bias_mm"] is None


def test_rain_skill_skips_pixels_the_observed_store_lacks(tmp_path):
    store = RandomStore(planted={date(2023, 7, 11): np.nan})
    day = date(2023, 7, 10)
    write_gfs(tmp_path, day, np.zeros((3, imerg.ROWS, imerg.COLS)))
    out = FS.rain_skill(store, tmp_path, [day], {"domain": np.arange(100)})
    assert out["leads"]["1"]["domain"]["n"] == 0                       # IMD D+1 needs UTC D and D+1
    assert out["leads"]["1"]["domain"]["n_dropped_missing"] == 100


# --------------------------------------------------------------------------- forecast features: observed <= D, forecast > D

def pair(store, forecast, lead, day=DAY):
    return FS.risk_pair(rain_model(), CELLS, day, lead, store, forecast, CLIM)


def test_forecast_risk_ignores_observed_rain_after_day_d():
    store = RandomStore()
    forecast = observed_imd(store, DAY)
    future = {DAY + timedelta(days=k): 9999.0 for k in range(1, 8)}
    for lead in (1, 2, 3):
        clean, planted = pair(store, forecast, lead), pair(RandomStore(planted=future), forecast, lead)
        np.testing.assert_allclose(clean["fcst_risk"], planted["fcst_risk"], rtol=1e-6)
        assert not np.allclose(clean["obs_risk"], planted["obs_risk"])        # the observed side does read them


def test_forecast_risk_reads_forecast_only_for_the_days_after_d():
    store = RandomStore()
    forecast = observed_imd(store, DAY)
    base = pair(store, forecast, 1)
    huge = pair(store, forecast + 300.0, 1)
    assert (huge["fcst_risk"] >= base["fcst_risk"]).all() and (huge["fcst_risk"] > base["fcst_risk"]).any()
    np.testing.assert_allclose(huge["obs_risk"], base["obs_risk"], rtol=1e-6)         # observed side does not read it
    past = {DAY - timedelta(days=1): 400.0}                                           # observed rain up to D is read
    assert (pair(RandomStore(planted=past), forecast, 1)["fcst_risk"] != base["fcst_risk"]).any()


@pytest.mark.parametrize("lead", [1, 2, 3])
def test_a_perfect_forecast_gives_the_observed_risk(lead):
    store = RandomStore()
    got = pair(store, observed_imd(store, DAY), lead)
    np.testing.assert_allclose(got["fcst_risk"], got["obs_risk"], rtol=1e-5)


def test_risk_pair_is_nan_where_either_side_cannot_be_scored():
    store = RandomStore()
    forecast = observed_imd(store, DAY)
    forecast[0] = np.nan
    got = pair(store, forecast, 1)
    assert got["fcst_risk"].isna().all() and got["obs_risk"].notna().all()
    assert list(got.columns) == ["cell_id", "obs_risk", "fcst_risk"]


# ---------------------------------------------------------------------------------------------- widening factors

def test_widening_factors_are_the_10th_and_90th_percentile_of_the_ratio():
    ratio = np.linspace(0.5, 2.5, 1001)
    out = FS.widening_factors({1: ratio, 2: ratio, 3: ratio}, min_n=100)
    lead = out["leads"]["1"]
    assert lead["lo"] == pytest.approx(np.percentile(ratio, 10)) and lead["hi"] == pytest.approx(np.percentile(ratio, 90))
    assert lead["lo"] == pytest.approx(0.7) and lead["hi"] == pytest.approx(2.3)
    assert lead["n"] == 1001 and out["quantiles"] == [10, 90]


def test_widening_factors_clamp_so_that_lo_is_at_most_one_and_hi_at_least_one():
    above = np.linspace(1.2, 3.0, 500)                     # the forecast always under-predicts
    below = np.linspace(0.2, 0.9, 500)                     # the forecast always over-predicts
    out = FS.widening_factors({1: above, 2: below, 3: np.linspace(0.8, 1.25, 500)}, min_n=100)["leads"]
    assert out["1"]["lo"] == 1.0 and out["1"]["hi"] == pytest.approx(np.percentile(above, 90))
    assert out["2"]["hi"] == 1.0 and out["2"]["lo"] == pytest.approx(np.percentile(below, 10))
    assert out["3"]["lo"] < 1.0 < out["3"]["hi"]
    assert out["1"]["raw_lo"] == pytest.approx(np.percentile(above, 10))               # the unclamped value stays on record


def test_widening_factors_ignore_non_finite_and_non_positive_ratios():
    ratio = np.concatenate([np.linspace(0.5, 2.0, 400), [np.nan, np.inf, 0.0, -1.0]])
    out = FS.widening_factors({k: ratio for k in (1, 2, 3)}, min_n=100)["leads"]["1"]
    assert out["n"] == 400


def test_widening_factors_refuse_too_few_ratios():
    ratio = np.linspace(0.5, 2.0, 400)
    with pytest.raises(ValueError, match="lead 2"):
        FS.widening_factors({1: ratio, 2: ratio[:50], 3: ratio}, min_n=100)
    with pytest.raises(ValueError, match="lead 3"):
        FS.widening_factors({1: ratio, 2: ratio}, min_n=100)


def test_the_widening_file_is_what_the_runner_reads(tmp_path):
    ratio = np.linspace(0.5, 2.0, 400)
    payload = FS.widening_factors({k: ratio for k in (1, 2, 3)}, min_n=100)
    path = tmp_path / "w.json"
    FS.write_json(path, payload)
    cfg = {"forecast_widening": str(path)}
    factors, why = live_run.load_widening(cfg, live_run.LiveDeps())
    assert why is None and sorted(factors) == [1, 2, 3]
    assert factors[1] == (pytest.approx(payload["leads"]["1"]["lo"]), pytest.approx(payload["leads"]["1"]["hi"]))
    assert all(lo <= 1.0 <= hi for lo, hi in factors.values())


# ------------------------------------------------------------------------------------- levels, agreement, label tables

def test_level_agreement_counts_and_watch_detection():
    obs = np.array([0, 0, 1, 1, 2, 3, 3, 0])
    fcst = np.array([0, 1, 1, 0, 2, 2, 3, 0])
    out = FS.level_agreement(obs, fcst)
    assert out["n"] == 8 and out["confusion"][0][1] == 1 and out["confusion"][3][2] == 1 and out["confusion"][3][3] == 1
    assert out["exact"] == pytest.approx(5 / 8) and out["within_one"] == 1.0
    w = out["watch"]
    assert (w["both"], w["observed_only"], w["forecast_only"], w["neither"]) == (4, 1, 1, 2)
    assert w["recall_of_observed"] == pytest.approx(4 / 5) and w["precision_of_forecast"] == pytest.approx(4 / 5)


def test_level_agreement_with_no_watch_has_no_rates():
    out = FS.level_agreement(np.zeros(4, dtype=int), np.zeros(4, dtype=int))
    assert out["watch"]["recall_of_observed"] is None and out["watch"]["precision_of_forecast"] is None


def test_candidate_cells_keep_every_label_cell_and_are_seeded():
    cells = pd.DataFrame({"cell_id": np.arange(1000, 2000)})
    a = FS.candidate_cells(cells, [1500, 1999], n_sample=50, seed=3)
    b = FS.candidate_cells(cells, [1500, 1999], n_sample=50, seed=3)
    c = FS.candidate_cells(cells, [1500, 1999], n_sample=50, seed=4)
    assert a["cell_id"].tolist() == b["cell_id"].tolist() != c["cell_id"].tolist()
    assert {1500, 1999} <= set(a["cell_id"]) and len(a) >= 50 and a["cell_id"].is_unique
    assert len(FS.candidate_cells(cells, [], n_sample=5000, seed=1)) == 1000


def test_select_labels_keeps_only_the_covered_years_and_counts_them():
    positives = pd.DataFrame({"cell_id": [1, 2, 3, 4], "event_date": pd.to_datetime(["2020-07-01", "2021-07-22", "2022-08-29", "2024-12-01"])})
    windows = pd.DataFrame({"cell_id": [5, 6], "window_start": pd.to_datetime(["2023-06-16"] * 2),
                            "window_end": pd.to_datetime(["2023-07-31"] * 2)})
    labels = FS.select_labels(positives, windows, first=date(2021, 6, 1), last=date(2024, 9, 30))
    assert labels.day_exact["cell_id"].tolist() == [2, 3]
    assert labels.windows["cell_id"].tolist() == [5, 6]
    assert labels.counts() == {"day_exact_cell_days": 2, "window_cells": 2, "case_cells": 0}
    assert sorted(labels.cell_ids()) == [2, 3, 5, 6]


# ---------------------------------------------------------------------------------------------- hazard skill, end to end

def synthetic_labels():
    way = int(CELLS.loc[CELLS["region"].eq("western_ghats"), "cell_id"].iloc[0])
    him = int(CELLS.loc[CELLS["region"].eq("himalaya"), "cell_id"].iloc[0])
    return FS.Labels(
        day_exact=pd.DataFrame({"cell_id": [way], "event_date": pd.to_datetime([DAY + timedelta(days=2)])}),
        windows=pd.DataFrame({"cell_id": [him], "window_start": pd.to_datetime([DAY]),
                              "window_end": pd.to_datetime([DAY + timedelta(days=4)])}),
        case=pd.DataFrame({"cell_id": [way], "event_date": pd.to_datetime([DAY + timedelta(days=3)]), "name": ["case"]}))


@pytest.fixture
def hazard_inputs(tmp_path):
    store = RandomStore()
    issue = [DAY + timedelta(days=k) for k in range(-1, 3)]
    for d in issue:
        write_gfs(tmp_path, d, observed_imd(store, d) * 1.3)
    return store, issue, tmp_path


def run_hazard(hazard_inputs, **overrides):
    store, issue, rain_dir = hazard_inputs
    settings = dict(min_ratios=5, floor_fraction=0.0, n_sample=10, seed=1)
    settings.update(overrides)
    return FS.hazard_skill(rain_model(), THRESHOLDS, CELLS, CLIM, store, rain_dir, issue, synthetic_labels(), **settings)


def test_hazard_skill_reports_ratios_agreement_and_detection(hazard_inputs):
    result = run_hazard(hazard_inputs)
    widening, report = result["widening"], result["report"]
    assert sorted(widening["leads"]) == ["1", "2", "3"]
    assert all(v["lo"] <= 1.0 <= v["hi"] for v in widening["leads"].values())
    for lead in ("1", "2", "3"):
        r = report["leads"][lead]
        assert r["n_pairs"] > 0 and r["n_ratios"] == widening["leads"][lead]["n"]
        assert r["agreement"]["n"] == r["n_pairs"]
        assert set(r["ratio_quantiles"]) >= {"p10", "p50", "p90"}
    assert report["labels"] == {"day_exact_cell_days": 1, "window_cells": 1, "case_cells": 1}
    detection = report["detection"]
    assert {e["lead"] for e in detection["day_exact"]} == {1, 2, 3}
    assert all(e["available"] for e in detection["day_exact"] + detection["windows"] + detection["case"])
    assert detection["summary"]["2"]["day_exact"]["n"] == 1
    json.dumps(report, allow_nan=False)


def test_hazard_skill_floor_selects_the_informative_cell_days(hazard_inputs):
    open_ = run_hazard(hazard_inputs)["report"]["leads"]["1"]
    assert 0 < open_["n_ratios"] <= open_["n_pairs"]
    with pytest.raises(ValueError, match="lead 1"):
        run_hazard(hazard_inputs, floor_fraction=1e6)


def test_hazard_skill_days_without_gfs_are_counted_not_zeroed(hazard_inputs):
    store, issue, rain_dir = hazard_inputs
    FS.gfs_day_path(rain_dir, issue[0]).unlink()
    report = run_hazard(hazard_inputs)["report"]
    assert report["gfs_files_missing"] == 1 and report["issue_days"] == len(issue)


# ----------------------------------------------------------------------------------------------- freeze gate and CLI

def test_require_frozen_names_the_missing_record(tmp_path):
    with pytest.raises(FS.NotFrozen, match="v3 model not frozen yet"):
        FS.require_frozen(tmp_path)
    (tmp_path / "FROZEN.json").write_text("{}", encoding="utf-8")
    assert FS.require_frozen(tmp_path) == tmp_path / "FROZEN.json"


def test_hazard_command_refuses_an_unfrozen_model_and_writes_nothing(tmp_path, capsys):
    model_dir = tmp_path / "model"
    rain_model().save(model_dir)
    reports, widening = tmp_path / "reports", tmp_path / "widening.json"
    code = FS.main(["hazard", "--model-dir", str(model_dir), "--reports-dir", str(reports), "--widening-out", str(widening)])
    assert code == 1
    assert "v3 model not frozen yet" in capsys.readouterr().err
    assert not reports.exists() and not widening.exists()


def test_all_command_also_refuses_before_doing_any_work(tmp_path, capsys):
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    reports = tmp_path / "reports"
    code = FS.main(["all", "--model-dir", str(model_dir), "--reports-dir", str(reports), "--rain-dir", str(tmp_path / "none")])
    assert code == 1 and "v3 model not frozen yet" in capsys.readouterr().err
    assert not reports.exists()


def test_the_runner_config_names_the_widening_file():
    cfg = live_run.load_run_config()
    assert FS.default_widening_path(cfg) == live_run.project_path(cfg["forecast_widening"])


# ------------------------------------------------------------------------------------------------------- the report

def rain_section():
    acc = FS.SkillAccumulator()
    acc.add(OBS, FCST)
    summary = acc.summary()
    return {"period": "June-September 2021-2024", "issue_days": 6, "gfs_files_missing": 0,
            "leads": {str(k): {"days_used": 6, "domain": summary, "himalaya": summary, "western_ghats": summary}
                      for k in (1, 2, 3)}}


def test_report_with_only_the_rain_part_marks_the_hazard_part_pending(tmp_path):
    FS.write_report(tmp_path, rain=rain_section())
    payload = json.loads((tmp_path / "phase6_forecast_skill.json").read_text(encoding="utf-8"))
    assert payload["hazard"]["status"] == "pending"
    assert payload["hazard"]["command"] == FS.HAZARD_COMMAND
    text = (tmp_path / "phase6_forecast_skill.md").read_text(encoding="utf-8")
    assert "pending: runs after the v3 freeze" in text and FS.HAZARD_COMMAND in text
    assert "June-September 2021-2024" in text and "| 50-100 |" in text
    assert "NaN" not in text


def test_writing_the_hazard_part_keeps_the_rain_part_and_the_other_way_round(tmp_path, hazard_inputs):
    FS.write_report(tmp_path, rain=rain_section())
    hazard = run_hazard(hazard_inputs)["report"]
    FS.write_report(tmp_path, hazard=hazard)
    payload = json.loads((tmp_path / "phase6_forecast_skill.json").read_text(encoding="utf-8"))
    assert payload["rain"]["issue_days"] == 6 and "status" not in payload["hazard"]
    text = (tmp_path / "phase6_forecast_skill.md").read_text(encoding="utf-8")
    assert "pending" not in text and "Widening factors" in text and "Labels" in text
    FS.write_report(tmp_path, rain={**rain_section(), "issue_days": 7})
    payload = json.loads((tmp_path / "phase6_forecast_skill.json").read_text(encoding="utf-8"))
    assert payload["rain"]["issue_days"] == 7 and payload["hazard"]["leads"]
