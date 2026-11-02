import json
import os
import stat

import numpy as np
import pandas as pd
import pytest

from aetherguard.corrector import cells
from aetherguard.corrector import evaluate as ce
from aetherguard.corrector.model import fit_corrector


def rows(n_stations=4, per=60, seed=0):
    rng = np.random.default_rng(seed)
    parts = []
    for s in range(n_stations):
        gauge = np.where(rng.random(per) < 0.6, rng.gamma(0.8, 10.0, per), 0.0)
        parts.append(pd.DataFrame({"station": f"S{s}", "gauge": gauge, "chirps_1": gauge * rng.uniform(0.3, 1.0, per),
                                   "exceed": (gauge >= 25.0).astype(float)}))
    return pd.concat(parts, ignore_index=True)


def perfect(df):
    return pd.DataFrame({"q50": df["gauge"], "q90": df["gauge"], "q99": df["gauge"]})


def test_pinball_table_known_answer_and_paired_difference():
    df = rows()
    methods = {"raw_chirps": ce.raw_baseline(df["chirps_1"]), "oracle": perfect(df)}
    table = ce.pinball_table(df, methods, n_boot=50)
    assert table["oracle"]["0.9"]["mean"] == 0.0 and table["oracle"]["0.9"]["skill_vs_reference"] == 1.0
    raw = table["raw_chirps"]["0.5"]["mean"]
    assert raw == pytest.approx(0.5 * np.abs(df["gauge"] - df["chirps_1"]).mean())
    assert table["oracle"]["0.5"]["diff_vs_reference"] == pytest.approx(-raw)
    lo, hi = table["oracle"]["0.5"]["diff_ci"]
    assert hi < 0 and lo <= -raw * 0.7
    assert "diff_vs_linear" not in table["oracle"]["0.5"]


def test_paired_difference_against_the_linear_baseline_is_reported_when_present():
    df = rows()
    methods = {"raw_chirps": ce.raw_baseline(df["chirps_1"]), "linear_scaling": ce.raw_baseline(df["chirps_1"] * 2),
               "oracle": perfect(df)}
    entry = ce.pinball_table(df, methods, n_boot=30)["oracle"]["0.99"]
    assert entry["diff_vs_linear"] < 0 and len(entry["diff_vs_linear_ci"]) == 2


def test_coverage_counts_gauge_values_at_or_below_the_quantile():
    df = rows()
    pred = pd.DataFrame({"q50": np.zeros(len(df)), "q90": np.full(len(df), df["gauge"].median()),
                         "q99": np.full(len(df), df["gauge"].max())})
    cov = ce.coverage_table(df, {"m": pred}, n_boot=30)["m"]
    assert cov["0.99"]["coverage"] == 1.0
    assert cov["0.9"]["coverage"] == pytest.approx((df["gauge"] <= df["gauge"].median()).mean())
    assert cov["0.9"]["target"] == 0.9


def test_top_one_percent_bias_uses_the_pooled_threshold():
    df = rows(per=200)
    top = ce.top_bias_table(df, {"raw": ce.raw_baseline(df["chirps_1"]), "oracle": perfect(df)}, n_boot=30)
    threshold = np.percentile(df["gauge"], 99)
    assert top["threshold_mm"] == pytest.approx(threshold) and top["rows"] == int((df["gauge"] >= threshold).sum())
    assert top["methods"]["oracle"]["q50"]["mean_bias_mm"] == 0.0
    sel = df["gauge"] >= threshold
    assert top["methods"]["raw"]["q99"]["mean_bias_mm"] == pytest.approx((df["chirps_1"][sel] - df["gauge"][sel]).mean())
    assert top["methods"]["raw"]["q99"]["mean_bias_mm"] < 0


def test_exceedance_table_pr_auc_and_recall_at_fixed_false_flag_rates():
    df = rows(per=300)
    perfect_score = df["exceed"].to_numpy() + 0.001 * np.arange(len(df)) / len(df)
    table = ce.exceedance_table(df, {"perfect": perfect_score, "noise": np.random.default_rng(0).random(len(df))}, n_boot=50)
    assert table["positives"] == int(df["exceed"].sum()) and table["rows"] == len(df)
    perfect_row = table["methods"]["perfect"]
    assert perfect_row["pr_auc"] == pytest.approx(1.0) and perfect_row["recall"]["0.01"]["recall"] == 1.0
    assert perfect_row["recall"]["0.05"]["achieved_false_flag_rate"] <= 0.05
    noise = table["methods"]["noise"]
    assert noise["pr_auc"] < 0.6 and noise["recall"]["0.05"]["recall"] < 0.4


def test_exceedance_rows_without_a_label_are_left_out_and_nan_scores_never_flag():
    df = rows(per=200)
    df.loc[df.index[:100], "exceed"] = np.nan
    score = df["gauge"].to_numpy().copy()
    score[::7] = np.nan
    table = ce.exceedance_table(df, {"s": score}, n_boot=20)
    assert table["rows"] == len(df) - 100 and table["methods"]["s"]["pr_auc"] > 0


def test_bootstrap_resamples_stations_and_is_deterministic():
    df = rows()
    one = ce.pinball_table(df, {"raw_chirps": ce.raw_baseline(df["chirps_1"])}, n_boot=40)
    two = ce.pinball_table(df, {"raw_chirps": ce.raw_baseline(df["chirps_1"])}, n_boot=40)
    assert one == two
    lo, hi = one["raw_chirps"]["0.9"]["ci"]
    assert lo <= one["raw_chirps"]["0.9"]["mean"] <= hi


# ------------------------------------------------------------------------------------------------ cells

COLUMNS = ["chirps_1", "chirps_3", "wet_top", "elev_mean", "month"]


def tiny_model():
    rng = np.random.default_rng(0)
    n = 1500
    chirps = np.where(rng.random(n) < 0.5, rng.gamma(0.8, 8.0, n), 0.0)
    frame = pd.DataFrame({"station": rng.integers(0, 5, n).astype(str), "chirps_1": chirps, "chirps_3": chirps * 2,
                          "wet_top": rng.random(n), "elev_mean": rng.random(n) * 1000, "month": rng.integers(1, 13, n).astype(float)})
    frame["gauge"] = chirps * rng.lognormal(0, 0.5, n)
    frame["exceed"] = (frame["gauge"] > 20).astype(float)
    small = ({"num_leaves": 7, "min_data_in_leaf": 30},)
    return fit_corrector(frame.iloc[:1000], frame.iloc[1000:], COLUMNS, 1, quantile_grid=small, classifier_grid=small)


def features_frame(n=6):
    rng = np.random.default_rng(1)
    return pd.DataFrame({"cell_id": np.arange(n, dtype=np.int64) + 100, "date": pd.date_range("2018-07-01", periods=n),
                         "src_chi_acc_1": [np.nan, 0.0, 12.0, 50.0, 3.0, 80.0][:n], "src_chi_acc_3": rng.random(n) * 90,
                         "wet_top": rng.random(n), "wet_root": rng.random(n), "stat_elev_mean": rng.random(n) * 900,
                         "stat_relief": 100.0, "stat_slope_mean": 5.0, "stat_aspect_sin": 0.0, "stat_aspect_cos": 1.0,
                         "src_imd_acc_1": 1.0, "src_imd_acc_3": 2.0})


def test_predict_cells_maps_features_and_leaves_nan_where_chirps_is_missing():
    model = tiny_model()
    features = features_frame()
    out = cells.predict_cells(model, features)
    assert list(out.columns) == cells.CORR_COLUMNS and all(out[c].dtype == np.float32 for c in out.columns)
    assert out.iloc[0].isna().all() and out.iloc[1:].notna().all().all()
    assert (out["corr_q50_1"].iloc[1:] <= out["corr_q90_1"].iloc[1:]).all() and (out["corr_q90_1"].iloc[1:] <= out["corr_q99_1"].iloc[1:]).all()
    predictors = pd.DataFrame({c: features[cells.cdata.CELL_COLUMN_MAP[c]] if c in cells.cdata.CELL_COLUMN_MAP else 0.0 for c in COLUMNS})
    predictors["month"] = 7.0
    direct = cells.predict_cells(model, predictors)
    assert list(direct.columns) == cells.CORR_COLUMNS
    with pytest.raises(KeyError, match="wet_top"):
        cells.predict_cells(model, features.drop(columns=["wet_top"]))


def make_features_dir(tmp_path):
    folder = tmp_path / "features"
    folder.mkdir()
    files = {}
    for name, n in (("a_features.parquet", 6), ("b_features.parquet", 4)):
        features_frame(6).head(n).to_parquet(folder / name, index=False)
        files[name] = {"sha256": "x"}
    (folder / "features_manifest.json").write_text(json.dumps({"files": files}), encoding="utf-8")
    return folder


def test_cell_files_keep_keys_and_order_are_frozen_reusable_and_tamper_evident(tmp_path):
    model = tiny_model()
    model_dir = tmp_path / "model"
    model.save(model_dir)
    folder = make_features_dir(tmp_path)
    out = tmp_path / "corr"
    manifest, reused = cells.build_cell_files(model, folder, out, model_dir)
    assert not reused and manifest["frozen"] and manifest["feature_files"] == ["a_features.parquet", "b_features.parquet"]
    for name in manifest["feature_files"]:
        base = pd.read_parquet(folder / name)
        made = pd.read_parquet(out / cells.corr_name(name))
        assert list(made.columns) == ["cell_id", "date"] + cells.CORR_COLUMNS
        assert made[["cell_id", "date"]].equals(base[["cell_id", "date"]])
    assert json.loads((out / cells.COLUMNS_NAME).read_text(encoding="utf-8")) == {c: "corr" for c in cells.CORR_COLUMNS}
    assert manifest["nan_share"]["a_corr.parquet"]["corr_q50_1"] == pytest.approx(1 / 6)
    assert all(not os.access(f, os.W_OK) for f in out.iterdir())
    again, reused = cells.build_cell_files(model, folder, out, model_dir)
    assert reused and again["files"].keys() == manifest["files"].keys()
    target = out / "a_corr.parquet"
    os.chmod(target, stat.S_IWRITE | stat.S_IREAD)
    pd.read_parquet(target).assign(corr_q50_1=1.0).to_parquet(target, index=False)
    with pytest.raises(cells.CorrectorIntegrityError, match="checksum"):
        cells.build_cell_files(model, folder, out, model_dir)
    rebuilt, reused = cells.build_cell_files(model, folder, out, model_dir, force=True)
    assert not reused and cells.verify_cells(out, folder, model_dir)["ok"]
    other = tiny_model()
    other.card["seed"] = 99
    other.save(model_dir)                                         # a changed model invalidates the frozen outputs
    assert not cells.verify_cells(out, folder, model_dir)["ok"]
