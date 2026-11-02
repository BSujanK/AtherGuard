"""v3-live configuration, `--config` plumbing, extra-only feature groups, per-region calibration, and the guarantee
that the v2 path (no `calibration.per_region`) is unchanged."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import lightgbm as lgb
import numpy as np
import pandas as pd
import pytest

from aetherguard.config import PROJECT_ROOT
from aetherguard.hazard import calibration as cal
from aetherguard.hazard import cv
from aetherguard.hazard import data as hd
from aetherguard.hazard import evaluate_report as er
from aetherguard.hazard import freeze as fz
from aetherguard.hazard import model as hm
from aetherguard.hazard import train as tr

from hazard_helpers import (COLUMN_MAP, EXTRA_GROUPS, synthetic_development, synthetic_samples, write_dev_store)

V3_PATH = PROJECT_ROOT / "configs" / "hazard_v3.yaml"
V3 = hm.hazard_config(V3_PATH)
V2 = hm.hazard_config()
FOLDS = [[2007, 2008], [2009, 2010], [2011, 2012], [2013, 2014], [2015], [2016], [2017]]
REGIONS = ("himalaya", "western_ghats")


def tiny_cfg(per_region=None, min_region_positives=25, groups=("rain", "src", "wet", "stat"), name="full"):
    """A tiny, fast configuration on the synthetic store; `per_region=None` leaves the key absent (the v2 file)."""
    cfg = copy.deepcopy(V2)
    cfg["extra_groups"] = EXTRA_GROUPS
    cfg["meta_columns"] = ["integ_n_st_100km"]
    cfg["groups"] = list(groups)
    cfg["training"].update(max_rounds=30, early_stopping_rounds=5, universe_negatives=500)
    cfg["cv"]["folds"] = FOLDS
    cfg["grid"] = {"num_leaves": [4], "min_data_in_leaf": [10], "feature_fraction": [0.9], "lambda_l2": [0, 5]}
    cfg["group_stages"] = [{"candidates": [{"name": name, "groups": list(groups)}]}]
    cfg["ensemble"].update(members=3)
    cfg["bootstrap"].update(n=50)
    if per_region is not None:
        cfg["calibration"]["per_region"] = per_region
        cfg["calibration"]["min_region_positives"] = min_region_positives
    return cfg


@pytest.fixture(scope="module")
def store(tmp_path_factory):
    root = tmp_path_factory.mktemp("v3store")
    samples, universe = synthetic_development(n_pos_train=110, n_pos_validation=50, n_per_region=2500)
    return write_dev_store(root / "features", samples, universe)


@pytest.fixture(scope="module")
def runs(store, tmp_path_factory):
    """The same synthetic fit with per_region absent (v2), false and true; each into its own model directory."""
    out = {}
    for label, per_region in (("absent", None), ("false", False), ("true", True)):
        root = tmp_path_factory.mktemp(f"run_{label}")
        cfg = tiny_cfg(per_region)
        model = tr.train(store, root / "model", cfg, report_dir=root / "reports")
        out[label] = SimpleNamespace(model=model, root=root, cfg=cfg)
    return out


@pytest.fixture(scope="module")
def frame():
    samples, universe = synthetic_development(n_pos_train=30, n_pos_validation=20, n_per_region=200)
    return pd.concat([samples.head(80), universe.head(80)], ignore_index=True)


# ------------------------------------------------------------------------------------------ the v3 file

def test_hazard_config_defaults_to_v2_and_loads_a_given_path(tmp_path):
    assert hm.hazard_config() == hm.hazard_config(PROJECT_ROOT / "configs" / "hazard.yaml")
    assert "model_dir" not in V2 and V2["groups"] == ["rain", "src", "wet", "stat"]
    custom = tmp_path / "other.yaml"
    custom.write_text("seed: 1\nmodel_dir: elsewhere\n", encoding="utf-8")
    assert hm.hazard_config(custom) == {"seed": 1, "model_dir": "elsewhere"}
    assert hm.hazard_config(str(custom)) == hm.hazard_config(custom)


def test_v3_extra_groups_stages_and_calibration():
    assert V3["model_dir"] == "model_v3_live"
    for group in ("irain", "iapi", "inbr"):
        assert V3["extra_groups"][group] == {"subdir": "imerg", "suffix": group, "columns_file": f"{group}_columns.json",
                                             "manifest_file": f"{group}_manifest.json"}
    assert {"integ", "corr"} <= set(V3["extra_groups"])
    stage1, stage2 = (s["candidates"] for s in V3["group_stages"])
    assert stage1 == [{"name": "imerg_core", "groups": ["irain", "stat"]},
                      {"name": "imerg_core_noelev", "groups": ["irain", "stat"],
                       "exclude": ["stat_elev_mean", "stat_elev_std"]}]
    assert stage2 == [{"name": "+iapi", "add_groups": ["iapi"]}, {"name": "+inbr", "add_groups": ["inbr"]},
                      {"name": "+iapi+inbr", "add_groups": ["iapi", "inbr"]}]
    assert V3["calibration"]["per_region"] is True and V3["calibration"]["min_region_positives"] == 25
    assert V3["groups"] == ["irain", "stat"]
    assert len(V3["group_stages"]) == 2 and len(V3["grid"]) == len(V2["grid"])
    for key in ("cv", "training", "neg_mix", "recall_first", "alert_levels", "ensemble", "bootstrap", "seed"):
        assert V3[key] == V2[key], key
    assert tr.extra_groups_used(V3) == ["irain", "iapi", "inbr"]
    assert cv.all_groups(V3) == ["irain", "stat", "iapi", "inbr"]


def test_v3_monotone_patterns_cover_the_imerg_columns():
    names = ["irain_acc_1", "irain_acc_90", "irain_max1d_7", "irain_max1d_30", "irain_wetdays_30",
             "irain_acc3_vs_clim", "irain_acc7_vs_clim", "irain_acc30_vs_clim", "iapi_85", "iapi_95",
             "inbr_max_acc_1", "inbr_mean_acc_3", "irain_days_since_10mm", "irain_share1_3", "stat_slope_mean",
             "stat_elev_mean"]
    got = dict(zip(names, hm.configured_constraints(names, V3)))
    assert [n for n, v in got.items() if v == 1] == names[:12] + ["stat_slope_mean"]
    assert [n for n, v in got.items() if v == -1] == ["irain_days_since_10mm"]
    assert got["irain_share1_3"] == 0 and got["stat_elev_mean"] == 0


def test_model_dir_comes_from_the_configuration_under_the_hazard_data_directory(isolated_data_root):
    assert hm.configured_model_dir(V3) == isolated_data_root / "processed" / "hazard" / "model_v3_live"
    assert hm.configured_model_dir(V2) == hm.default_model_dir() == isolated_data_root / "processed" / "hazard" / "model"
    for bad in ("../model", "a/b", ".."):
        with pytest.raises(ValueError, match="plain directory name"):
            hm.configured_model_dir({"model_dir": bad})


def test_v3_reports_and_freeze_labels_do_not_collide_with_the_frozen_v2_ones():
    assert hm.cv_report_stem(V2) == "phase3_hazard_cv_report" and hm.cv_report_stem(V3) == "phase6_v3_cv_report"
    assert hm.evaluation_report_stem(V2) == "phase3_hazard_report"
    assert hm.evaluation_report_stem(V3) == "phase6_live_model_report"
    assert set(fz.default_external_files()) == {"config/hazard.yaml", "report/phase3_hazard_cv_report.json"}
    external = fz.default_external_files(V3_PATH)
    assert set(external) == {"config/hazard_v3.yaml", "report/phase6_v3_cv_report.json"}
    assert external["config/hazard_v3.yaml"] == V3_PATH


# --------------------------------------------------------------------------------------------- CLI

def test_train_cli_loads_the_config_and_defaults_the_model_dir_from_it(monkeypatch, isolated_data_root, capsys):
    seen = {}

    def fake_train(features, out, cfg, progress=None):
        seen.update(features=features, out=out, cfg=cfg)
        return SimpleNamespace(card={"train_seconds": 1.0})

    monkeypatch.setattr(tr, "train", fake_train)
    assert tr.main(["--config", str(V3_PATH)]) == 0
    assert seen["cfg"] == V3 and seen["out"] is None and seen["features"] is None
    assert "model_v3_live" in capsys.readouterr().out
    assert tr.main(["--config", str(V3_PATH), "--out", str(isolated_data_root / "x"), "--features", "f"]) == 0
    assert seen["out"] == isolated_data_root / "x" and seen["features"] == Path("f")
    assert tr.main([]) == 0 and seen["cfg"] == V2


def test_train_writes_to_the_configured_model_dir_and_report_stem(store, isolated_data_root, tmp_path):
    cfg = tiny_cfg(True)
    cfg.update(model_dir="model_test_live", cv_report_stem="phase6_test_cv")
    tr.train(store, None, cfg, report_dir=tmp_path / "reports")
    target = isolated_data_root / "processed" / "hazard" / "model_test_live"
    assert (target / "card.json").is_file() and (target / hm.REGION_CALIBRATOR_FILE).is_file()
    assert (tmp_path / "reports" / "phase6_test_cv.json").is_file() and (tmp_path / "reports" / "phase6_test_cv.md").is_file()
    assert not (tmp_path / "reports" / "phase3_hazard_cv_report.json").exists()
    assert not (isolated_data_root / "processed" / "hazard" / "model").exists()


def test_freeze_cli_takes_config_and_model(tmp_path, monkeypatch, isolated_data_root):
    model = isolated_data_root / "processed" / "hazard" / "model_v3_live"
    (model / "ensemble").mkdir(parents=True)
    for name in (*fz.MODEL_FILES, hm.REGION_CALIBRATOR_FILE):
        (model / name).write_text(f"content of {name}")
    (model / "ensemble" / "member_00.txt").write_text("member")
    monkeypatch.setattr(fz, "PROJECT_ROOT", tmp_path)
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "phase6_v3_cv_report.json").write_text("{}")
    config = tmp_path / "hazard_v3.yaml"
    config.write_text("model_dir: model_v3_live\ncv_report_stem: phase6_v3_cv_report\n")
    assert fz.main(["--config", str(config)]) == 0
    record = json.loads((model / fz.FROZEN_NAME).read_text())
    assert set(record["sha256"]) == {*fz.MODEL_FILES, hm.REGION_CALIBRATOR_FILE, "ensemble/member_00.txt",
                                     "config/hazard_v3.yaml", "report/phase6_v3_cv_report.json"}
    assert fz.verify_freeze(model, fz.default_external_files(config))["sha256"] == record["sha256"]
    (model / hm.REGION_CALIBRATOR_FILE).write_text("tampered")
    with pytest.raises(fz.FrozenMismatchError, match="differs"):
        fz.verify_freeze(model, fz.default_external_files(config))


def test_evaluate_report_cli_takes_config_and_model(tmp_path, monkeypatch, isolated_data_root):
    seen = {}
    monkeypatch.setattr(er, "check_single_evaluation", lambda model_dir, rerun: seen.setdefault("checked", model_dir))
    monkeypatch.setattr(er, "run_evaluation", lambda features, model_dir, cfg, **kw: (
        seen.update(model_dir=model_dir, cfg=cfg, external=kw["external"]) or {"meta": {"evaluation_seconds": 0.0}}))
    monkeypatch.setattr(er, "write_report", lambda result, out, stem=hm.EVALUATION_REPORT_STEM: (
        seen.setdefault("stems", []).append(stem) or (out / f"{stem}.json", out / f"{stem}.md")))
    monkeypatch.setattr(er, "record_evaluation", lambda model_dir, report_json, rerun: {"runs": 1})
    assert er.main(["--config", str(V3_PATH), "--out", str(tmp_path)]) == 0
    expected = isolated_data_root / "processed" / "hazard" / "model_v3_live"
    assert seen["checked"] == seen["model_dir"] == expected and seen["cfg"] == V3
    assert set(seen["external"]) == {"config/hazard_v3.yaml", "report/phase6_v3_cv_report.json"}
    assert seen["stems"] == ["phase6_live_model_report"] * 2
    seen.clear()
    assert er.main(["--config", str(V3_PATH), "--model", str(tmp_path / "m"), "--out", str(tmp_path)]) == 0
    assert seen["model_dir"] == tmp_path / "m"
    seen.clear()
    assert er.main(["--out", str(tmp_path)]) == 0
    assert seen["model_dir"] == hm.default_model_dir() and seen["stems"] == ["phase3_hazard_report"] * 2


# ------------------------------------------------------------------------- extra-only feature groups

def test_groups_that_live_only_in_extra_tables_load_resolve_and_train(store, tmp_path):
    cfg = tiny_cfg(True, groups=("corr", "stat"), name="core")
    cfg["group_stages"].append({"candidates": [{"name": "+integ", "add_groups": ["integ"]}]})
    assert cv.all_groups(cfg) == ["corr", "stat", "integ"] and tr.extra_groups_used(cfg) == ["corr", "integ"]
    dev = hd.load_development(store, cfg["extra_groups"], tr.extra_groups_used(cfg), cfg["meta_columns"])
    assert dev.column_map["corr_q50_1"] == "corr" and dev.column_map["integ_trw_rain_1"] == "integ"
    assert dev.column_map["integ_n_st_100km"] == hd.META
    first = cv.resolve_candidate(cfg["group_stages"][0]["candidates"][0], None, cfg, dev.column_map)
    assert first["columns"] == ["stat_relief", "stat_slope_mean", "stat_elev_mean", "stat_aspect_sin", "corr_q50_1",
                                "corr_p_exceed99"]
    assert not [c for c in first["columns"] if c.startswith(("rain_", "src_", "wet_"))]
    second = cv.resolve_candidate(cfg["group_stages"][1]["candidates"][0], first, cfg, dev.column_map)
    assert second["groups"] == ["corr", "stat", "integ"] and "integ_n_st_100km" not in second["columns"]
    assert set(first["columns"]) < set(second["columns"])
    model = tr.train(store, tmp_path / "model", cfg, report_dir=tmp_path / "reports")
    assert model.card["feature_set"]["name"] in {"core", "core+integ"}
    assert not [c for c in model.columns if c.startswith(("rain_", "src_", "wet_"))]
    grid_names = {r["name"] for r in model.card["selection"]["groups"]}
    assert grid_names == {"core", "core+integ"}
    assert next(r for r in model.card["selection"]["groups"] if r["name"] == "core")["n_inputs"] == 6


def test_the_grid_is_reused_for_whichever_stage_one_candidate_matches_the_base_groups(store, tmp_path, monkeypatch):
    fitted = []
    real = cv.run_cv
    monkeypatch.setattr(cv, "run_cv", lambda *a, **k: fitted.append(a[-1] if len(a) > 6 else k.get("name")) or real(
        *a, **k))
    tr.train(store, tmp_path / "model", tiny_cfg(True, groups=("corr", "stat"), name="core"),
             report_dir=tmp_path / "reports")
    assert "core" not in fitted and any(name.startswith("grid_") for name in fitted)       # reused, not refitted
    fitted.clear()
    cfg = tiny_cfg(True, groups=("corr", "stat"), name="core")
    cfg["group_stages"][0]["candidates"].insert(0, {"name": "other", "groups": ["stat"]})
    tr.train(store, tmp_path / "model", cfg, report_dir=tmp_path / "reports")
    assert "other" in fitted and "core" not in fitted


# ----------------------------------------------------------------------------- the v2 path is unchanged

def legacy_score(model, frame):
    """Pooled scoring as the frozen v2 model had it before per-region calibration existed, with the interval of the spec
    section 11 amendment (the members' spread re-centred on the point, calibrated by the one pooled calibrator)."""
    matrix = hm.feature_matrix(frame, model.columns)
    raw = model.booster.predict(matrix, num_iteration=model.best_iteration)
    risk = model.calibrator.predict(raw)
    members = np.column_stack([m.predict(matrix, num_iteration=model.best_iteration) for m in model.members])
    lo, hi = (model.calibrator.predict(hm.recentred_percentile(raw, members, q)) for q in hm.INTERVAL_PERCENTILES)
    return pd.DataFrame({"risk": risk, "risk_lo": lo, "risk_hi": hi, "risk_per_100k": 1e5 * risk}, index=frame.index)


def test_without_per_region_scoring_and_files_are_the_v2_ones(runs, frame):
    for label in ("absent", "false"):
        run = runs[label]
        assert run.model.region_calibrator is None
        assert not (run.root / "model" / hm.REGION_CALIBRATOR_FILE).exists()
        scored = run.model.score(frame)
        pd.testing.assert_frame_equal(scored[["risk", "risk_lo", "risk_hi", "risk_per_100k"]],
                                      legacy_score(run.model, frame), check_exact=True)
        assert scored.attrs == {} and "region" in frame.columns
        assert "per_region" not in run.model.card["calibration"]
        assert not [t for t in run.model.card["thresholds_oof"].values() if "risk_by_region" in t]
        reloaded = hm.HazardModel.load(run.root / "model")
        pd.testing.assert_frame_equal(reloaded.score(frame), scored, check_exact=True)
        assert (run.root / "reports" / "phase3_hazard_cv_report.md").is_file()
        assert "calibration_regions" not in json.loads((run.root / "model" / "cv_results.json").read_text())


def test_absent_and_false_per_region_train_the_identical_model(runs):
    a, f = (runs[k].root / "model" for k in ("absent", "false"))
    for name in ("model.txt", "calibrator.json", "ensemble/member_00.txt"):
        assert (a / name).read_bytes() == (f / name).read_bytes(), name
    assert runs["absent"].model.card["alert_levels"] == runs["false"].model.card["alert_levels"]


def test_per_region_changes_only_the_calibration_never_the_raw_model_or_thresholds(runs, frame):
    v2, v3 = runs["absent"], runs["true"]
    for name in ("model.txt", "calibrator.json", "ensemble/member_00.txt", "ensemble/member_02.txt"):
        assert (v2.root / "model" / name).read_bytes() == (v3.root / "model" / name).read_bytes(), name
    np.testing.assert_array_equal(v2.model.raw_score(frame), v3.model.raw_score(frame))
    for level in ("watch", "warning", "emergency"):
        assert v2.model.card["alert_levels"][level]["raw"] == v3.model.card["alert_levels"][level]["raw"]
    assert v2.model.card["thresholds_oof"]["plain_recall_90"]["raw"] == v3.model.card["thresholds_oof"][
        "plain_recall_90"]["raw"]
    # without a region column the v3 model scores exactly like v2 and says it fell back to the pooled calibrator
    bare = frame.drop(columns="region")
    scored = v3.model.score(bare)
    pd.testing.assert_frame_equal(scored, v2.model.score(bare), check_exact=True, check_flags=False)
    assert scored.attrs["calibration"] == {"calibration": "pooled", "pooled_rows": len(bare),
                                           "reason": "frame has no `region` column"}


@pytest.mark.realdata
def test_real_frozen_v2_model_scores_byte_identically_and_stays_frozen():
    features, model_dir = hd.features_dir(), hm.default_model_dir()
    if not ((features / "feature_columns.json").is_file() and (model_dir / hm.CARD_FILE).is_file()):
        pytest.skip("real feature store or frozen v2 model not available")
    record = fz.verify_freeze(model_dir)
    assert hm.REGION_CALIBRATOR_FILE not in record["sha256"] and not (model_dir / hm.REGION_CALIBRATOR_FILE).exists()
    model = hm.HazardModel.load(model_dir)
    assert model.region_calibrator is None and "per_region" not in model.card["calibration"]
    dev = hd.load_development(features, V2["extra_groups"], tr.extra_groups_used(V2), V2["meta_columns"])
    rows = dev.positives.head(200)
    assert "region" in rows.columns
    scored = model.score(rows)
    pd.testing.assert_frame_equal(scored, legacy_score(model, rows), check_exact=True)
    booster = lgb.Booster(model_file=str(model_dir / hm.MODEL_FILE))
    raw = booster.predict(hm.feature_matrix(rows, json.loads((model_dir / hm.CARD_FILE).read_text())["columns"]))
    np.testing.assert_array_equal(scored["risk"], model.calibrator.predict(raw))
    assert hm.score_frame(rows, model_dir)["risk"].equals(scored["risk"])


# ------------------------------------------------------------------- per-region calibration, end to end

def test_per_region_training_saves_the_region_calibrator_and_records_it(runs):
    run = runs["true"]
    path = run.root / "model" / hm.REGION_CALIBRATOR_FILE
    saved = cal.RegionCalibrator.from_json(json.loads(path.read_text(encoding="utf-8")))
    assert sorted(saved.by_region) == list(REGIONS) and saved.min_positives == 25
    pooled = cal.MonotoneCalibrator.from_dict(json.loads((run.root / "model" / hm.CALIBRATOR_FILE).read_text()))
    np.testing.assert_array_equal(saved.pooled.x, pooled.x)
    np.testing.assert_array_equal(saved.pooled.y, pooled.y)
    card = run.model.card
    section = card["calibration"]
    assert section["per_region"] is True and section["file"] == "calibrator_regions.json"
    assert section["min_region_positives"] == 25 and section["regions_with_own_calibrator"] == list(REGIONS)
    assert set(section["regions"]) == set(REGIONS)
    assert section["regions"]["himalaya"]["positives"] + section["regions"]["western_ghats"]["positives"] == 160
    for entry in section["regions"].values():
        assert entry["calibrator"] == "own" and np.isfinite(entry["ece_deciles_crossfit_per_region"])
    payload = json.loads((run.root / "model" / "cv_results.json").read_text())
    summary = payload["calibration_regions"]
    assert set(summary["regions"]) == set(REGIONS) and summary["min_region_positives"] == 25
    for entry in summary["regions"].values():
        for label in ("crossfit_per_region", "crossfit_pooled"):
            assert entry[label]["deciles"] and entry[label]["mean_predicted"] > 0
    text = (run.root / "reports" / "phase3_hazard_cv_report.md").read_text(encoding="utf-8")
    assert "## OOF calibration per region" in text
    json.loads((run.root / "reports" / "phase3_hazard_cv_report.json").read_text(),
               parse_constant=lambda c: pytest.fail(f"non-strict constant {c}"))


def test_per_region_risks_differ_between_regions_and_are_monotone_in_each(runs, frame):
    model = runs["true"].model
    rows = frame.drop_duplicates("cell_id").head(60)
    by_region = {r: model.score(rows.assign(region=r)) for r in REGIONS}
    assert not np.array_equal(by_region["himalaya"]["risk"], by_region["western_ghats"]["risk"])
    raw = model.raw_score(rows)
    order = np.argsort(raw, kind="stable")
    for region, scored in by_region.items():
        assert (np.diff(scored["risk"].to_numpy()[order]) >= 0).all(), region
        assert (scored["risk_lo"] <= scored["risk_hi"]).all()
        expected = model.region_calibrator.by_region[region].predict(raw)
        np.testing.assert_array_equal(scored["risk"], expected)
        assert scored.attrs["calibration"] == {"calibration": "per_region", "pooled_rows": 0, "pooled_regions": []}


def test_mixed_and_unknown_regions_use_their_own_or_the_recorded_pooled_calibrator(runs, frame):
    model = runs["true"].model
    rows = frame.drop_duplicates("cell_id").head(8).copy()
    rows["region"] = ["himalaya", "western_ghats", "atlantis", np.nan, "himalaya", "western_ghats", "atlantis",
                      "himalaya"]
    scored = model.score(rows)
    raw = model.raw_score(rows)
    regions = rows["region"].to_numpy()
    for k in range(len(rows)):
        own = model.region_calibrator.by_region.get(regions[k], model.calibrator)
        assert scored["risk"].iloc[k] == own.predict([raw[k]])[0], k
    assert scored.attrs["calibration"] == {"calibration": "per_region", "pooled_rows": 3,
                                           "pooled_regions": ["atlantis", "nan"]}
    np.testing.assert_allclose(scored["risk_per_100k"], 1e5 * scored["risk"])


def test_region_calibrator_survives_save_and_load_and_a_later_v2_save_removes_it(runs, frame, tmp_path):
    model = runs["true"].model
    loaded = hm.HazardModel.load(runs["true"].root / "model")
    pd.testing.assert_frame_equal(loaded.score(frame), model.score(frame), check_exact=True)
    assert hm.score_frame(frame, runs["true"].root / "model")["risk"].equals(model.score(frame)["risk"])
    loaded.save(tmp_path / "copy")
    assert (tmp_path / "copy" / hm.REGION_CALIBRATOR_FILE).is_file()
    loaded.region_calibrator = None
    loaded.save(tmp_path / "copy")
    assert not (tmp_path / "copy" / hm.REGION_CALIBRATOR_FILE).exists()


# ------------------------------------------------------------------------ cv: fit, cross-fit, thresholds

@pytest.fixture(scope="module")
def world():
    samples, universe = synthetic_development(n_pos_train=110, n_pos_validation=50, n_per_region=2500)
    layout = cv.make_layout(hd.build_development(samples, universe, COLUMN_MAP), FOLDS)
    rng = np.random.default_rng(3)
    oof = cv.Oof(rng.beta(5, 2, len(layout.positives)), rng.beta(2, 5, len(layout.negatives)),
                 rng.beta(2, 5, len(layout.matched)))
    return layout, oof


def test_fit_region_calibrator_uses_each_regions_rows_and_the_pooled_fit_otherwise(world):
    layout, oof = world
    counts = cv.region_positive_counts(layout, REGIONS)
    assert sum(counts.values()) == 160 and min(counts.values()) < 60 < max(counts.values())
    both = cv.fit_region_calibrator(layout, oof, REGIONS, 25)
    assert sorted(both.by_region) == list(REGIONS) and both.min_positives == 25
    pooled = cv.fit_calibrator(layout, oof)
    np.testing.assert_array_equal(both.pooled.x, pooled.x)
    np.testing.assert_array_equal(both.pooled.y, pooled.y)
    grid = np.linspace(0, 1, 101)
    assert not np.array_equal(both.predict(grid, "himalaya"), both.predict(grid, "western_ghats"))
    for region in REGIONS:
        assert (np.diff(both.predict(grid, region)) >= 0).all()
    threshold = (min(counts.values()) + max(counts.values())) // 2
    mixed = cv.fit_region_calibrator(layout, oof, REGIONS, threshold)
    big = max(counts, key=counts.get)
    assert list(mixed.by_region) == [big]
    small = min(counts, key=counts.get)
    np.testing.assert_array_equal(mixed.predict(grid, small), pooled.predict(grid))
    assert cv.fit_region_calibrator(layout, oof, REGIONS, 10_000).by_region == {}


def test_crossfit_region_risk_uses_other_folds_only_and_falls_back_to_the_pooled_crossfit(world):
    layout, oof = world
    pooled_pos, pooled_neg = cv.crossfit_risk(layout, oof)
    fallback = cv.crossfit_region_risk(layout, oof, REGIONS, 10_000)
    np.testing.assert_array_equal(fallback[0], pooled_pos)
    np.testing.assert_array_equal(fallback[1], pooled_neg)
    risk_pos, risk_neg = cv.crossfit_region_risk(layout, oof, REGIONS, 25)
    assert np.isfinite(risk_pos).all() and np.isfinite(risk_neg).all()
    assert not np.array_equal(risk_pos, pooled_pos)
    k = 2
    p_in, n_in = layout.pos_fold != k, layout.neg_fold != k
    regions = layout.positives["region"].to_numpy()
    held = (~p_in) & (regions == "himalaya")
    inside = p_in & (regions == "himalaya")
    neg_himalaya = n_in & (layout.negatives["region"].to_numpy() == "himalaya")
    manual = cal.MonotoneCalibrator.fit(
        np.r_[oof.pos[inside], oof.neg[neg_himalaya]], np.r_[np.ones(inside.sum()), np.zeros(neg_himalaya.sum())],
        np.r_[np.ones(inside.sum()), layout.neg_weight[neg_himalaya]])
    np.testing.assert_array_equal(risk_pos[held], manual.predict(oof.pos[held]))


def test_region_calibration_summary_reports_each_regions_ece_and_mean_versus_observed(world):
    layout, oof = world
    cfg = tiny_cfg(True)
    summary = cv.region_calibration_summary(layout, oof, REGIONS, 25, cfg)
    assert summary["min_region_positives"] == 25 and set(summary["regions"]) == set(REGIONS)
    risk_pos, risk_neg = cv.crossfit_region_risk(layout, oof, REGIONS, 25)
    for region, entry in summary["regions"].items():
        p_r = (layout.positives["region"] == region).to_numpy()
        n_r = (layout.negatives["region"] == region).to_numpy()
        population = p_r.sum() + layout.neg_weight[n_r].sum()
        assert entry["positives"] == p_r.sum() and entry["calibrator"] == "own"
        assert entry["observed"] == pytest.approx(p_r.sum() / population)
        expected = (risk_pos[p_r].sum() + np.sum(layout.neg_weight[n_r] * risk_neg[n_r])) / population
        assert entry["crossfit_per_region"]["mean_predicted"] == pytest.approx(expected)
        assert entry["crossfit_pooled"]["ece_deciles"] >= 0 and len(entry["crossfit_per_region"]["deciles"]) >= 1
    small = min(REGIONS, key=lambda r: cv.region_positive_counts(layout, REGIONS)[r])
    pooled_only = cv.region_calibration_summary(layout, oof, REGIONS, 100, cfg)["regions"][small]
    assert pooled_only["calibrator"].startswith("pooled")
    assert pooled_only["crossfit_per_region"]["ece_deciles"] == pytest.approx(pooled_only["crossfit_pooled"]["ece_deciles"])


def test_thresholds_are_raw_scores_and_their_risk_comes_from_the_calibrator_the_model_uses(world):
    layout, oof = world
    cfg = tiny_cfg(True)
    pooled = cv.fit_calibrator(layout, oof)
    regional = cv.fit_region_calibrator(layout, oof, REGIONS, 25)
    plain = cv.operating_thresholds(layout, oof, pooled, cfg)
    per_region = cv.operating_thresholds(layout, oof, regional, cfg)
    none = cv.operating_thresholds(layout, oof, None, cfg)
    for level in plain:
        assert plain[level]["raw"] == per_region[level]["raw"] == none[level]["raw"]
        assert plain[level]["oof_recall"] == per_region[level]["oof_recall"]
        assert plain[level]["oof_fa_share"] == per_region[level]["oof_fa_share"]
        assert "risk_by_region" not in plain[level] and none[level]["risk"] is None
        raw = per_region[level]["raw"]
        assert per_region[level]["risk"] == plain[level]["risk"] == pooled.predict([raw])[0]
        assert sorted(per_region[level]["risk_by_region"]) == list(REGIONS)
        for region in REGIONS:
            assert per_region[level]["risk_by_region"][region] == regional.predict([raw], region)[0]
    assert per_region["watch"]["risk_by_region"]["himalaya"] != per_region["watch"]["risk_by_region"]["western_ghats"]


def test_the_trained_card_records_thresholds_under_the_calibrator_the_model_uses(runs):
    v3 = runs["true"]
    card, model = v3.model.card, v3.model
    explanation = card["calibration"]["threshold_risk"]
    assert "raw scores" in explanation and "pooled" in explanation and "risk_by_region" in explanation
    for level, entry in card["alert_levels"].items():
        assert entry == card["thresholds_oof"][level]
        assert entry["risk"] == model.calibrator.predict([entry["raw"]])[0]
        for region in REGIONS:
            assert entry["risk_by_region"][region] == model.region_calibrator.by_region[region].predict(
                [entry["raw"]])[0]
    v2_levels = runs["absent"].model.card["alert_levels"]
    assert all("risk_by_region" not in e for e in v2_levels.values())
    assert {k: e["risk"] for k, e in v2_levels.items()} == {k: e["risk"] for k, e in card["alert_levels"].items()}


# ----------------------------------------------------------------------------------------- leakage guard

def test_the_leakage_guard_still_refuses_test_window_and_case_rows(runs):
    frame = synthetic_samples("test_2018", n_pos=20)
    with pytest.raises(hd.LeakageError, match="test_2018"):
        hd.assert_development_rows(frame)
    cases = synthetic_samples("train", n_pos=20).assign(kind="case")
    with pytest.raises(hd.LeakageError, match="case"):
        hd.assert_development_rows(cases)
    columns = hd.model_columns(V2["groups"], COLUMN_MAP)
    with pytest.raises(hd.LeakageError):
        hm.fit_booster(frame.assign(sample_weight=1.0), columns, hm.configured_constraints(columns, V2),
                       {"num_leaves": 4, "min_data_in_leaf": 5, "learning_rate": 0.1}, 0, V2["training"], num_rounds=3)


def test_per_region_training_never_opens_test_window_or_case_tables(store, tmp_path, monkeypatch):
    opened = []
    real = pd.read_parquet
    monkeypatch.setattr(pd, "read_parquet", lambda path, *a, **k: opened.append(str(path)) or real(path, *a, **k))
    tr.train(store, tmp_path / "model", tiny_cfg(True), report_dir=tmp_path / "reports")
    assert opened and not [p for p in opened if any(t in p for t in ("test_2018", "window", "case_"))]
