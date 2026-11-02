import copy
import json

import numpy as np
import pandas as pd
import pytest

from aetherguard.grid import ID_STRIDE, latlon_to_cell, neighbours
from aetherguard.hazard import data as hd
from aetherguard.hazard import evaluate_report as er
from aetherguard.hazard import freeze as fz
from aetherguard.hazard import model as hm
from aetherguard.hazard import train as tr

from hazard_helpers import (EXTRA_GROUPS, synthetic_development, synthetic_samples, synthetic_universe, write_store)

BASE = hm.hazard_config()
FOLDS = [[2007, 2008], [2009, 2010], [2011, 2012], [2013, 2014], [2015], [2016], [2017]]


def tiny_cfg():
    cfg = copy.deepcopy(BASE)
    cfg["extra_groups"] = EXTRA_GROUPS
    cfg["meta_columns"] = ["integ_n_st_100km"]
    cfg["training"].update(max_rounds=25, early_stopping_rounds=5, universe_negatives=500)
    cfg["cv"]["folds"] = FOLDS
    cfg["grid"] = {"num_leaves": [4], "min_data_in_leaf": [10], "feature_fraction": [0.9], "lambda_l2": [0]}
    cfg["ensemble"].update(members=3)
    cfg["bootstrap"].update(n=40)
    return cfg


def _window_frame(features: pd.DataFrame) -> pd.DataFrame:
    p = 2000 * ID_STRIDE + 3000
    cells = {"window_cell": sorted({p, *neighbours(p)}), "window_control": [900_000_000 + i for i in range(20)]}
    rows = [{"cell_id": c, "date": pd.Timestamp("2023-06-16") + pd.Timedelta(days=d), "kind": k,
             "is_window_positive_cell": k == "window_cell" and c == p, "split": "test_2023_india_window",
             "region": "himalaya"} for k, ids in cells.items() for c in ids for d in range(3)]
    window = pd.DataFrame(rows)
    features = features.head(len(window)).reset_index(drop=True)
    for name in [c for c in features.columns if c.startswith(("rain_", "src_", "wet_", "stat_"))]:
        window[name] = features[name].to_numpy()
    return window


def _case_frame(lat0, lon0, side, days, features, positives=()):
    cells = [latlon_to_cell(lat0 + 0.05 * i, lon0 + 0.05 * j) for i in range(side) for j in range(side)]
    rows = [{"cell_id": c, "date": pd.Timestamp("2018-08-01") + pd.Timedelta(days=d), "is_positive_cell_day": False,
             "in_buffer": False} for d in range(days) for c in cells]
    frame = pd.DataFrame(rows)
    for (c, d) in positives:
        frame.loc[(frame["cell_id"] == cells[c]) & (frame["date"] == pd.Timestamp("2018-08-01") + pd.Timedelta(days=d)),
                  "is_positive_cell_day"] = True
    feats = features.head(len(frame)).reset_index(drop=True)
    for name in [c for c in feats.columns if c.startswith(("rain_", "src_", "wet_", "stat_"))]:
        frame[name] = feats[name].to_numpy()
    return frame


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    root = tmp_path_factory.mktemp("final")
    samples, universe = synthetic_development(n_pos_train=110, n_pos_validation=50, n_per_region=2500)
    test_samples = synthetic_samples("test_2018", n_pos=70, seed=21, n_out_of_domain=4, years=[2018])
    test_universe = synthetic_universe("test_2018", n_per_region=2500, seed=22, years=[2018])
    window = _window_frame(synthetic_universe("x", n_per_region=200, seed=23))
    tables = {"train_samples": samples[samples["split"] == "train"].reset_index(drop=True),
              "validation_samples": samples[samples["split"] == "validation"].reset_index(drop=True),
              "universe_train": universe[universe["split"] == "train"].reset_index(drop=True),
              "universe_validation": universe[universe["split"] == "validation"].reset_index(drop=True),
              "test_2018_samples": test_samples, "universe_test_2018": test_universe, "window_2023_samples": window}
    store = write_store(root / "features", tables)
    cfg = tiny_cfg()
    tr.train(store, root / "model", cfg, report_dir=root / "reports")
    feats = synthetic_universe("x", n_per_region=400, seed=24)
    cases = {"kerala_2018": _case_frame(8.0, 77.0, 5, 6, feats, positives=[(12, 3), (3, 4)]),
             "wayanad_2024": _case_frame(11.5, 75.9, 6, 4, feats)}
    return {"root": root, "store": store, "cfg": cfg, "cases": cases}


@pytest.fixture(scope="module")
def frozen(world):
    fz.write_freeze(world["root"] / "model", {})
    return world


@pytest.fixture(scope="module")
def result(frozen):
    return er.run_evaluation(frozen["store"], frozen["root"] / "model", frozen["cfg"], case_frames=frozen["cases"],
                             reports_dir=frozen["root"] / "no_reports", external={})


def _run(world, **kwargs):
    return er.run_evaluation(world["store"], world["root"] / "model", world["cfg"], case_frames=world["cases"],
                             reports_dir=world["root"] / "no_reports", external={}, **kwargs)


# --------------------------------------------------------------------------------------------- freeze guard

def test_evaluation_refuses_an_unfrozen_model(world, tmp_path):
    import shutil
    copy_dir = tmp_path / "model"
    shutil.copytree(world["root"] / "model", copy_dir)
    if (copy_dir / fz.FROZEN_NAME).exists():
        (copy_dir / fz.FROZEN_NAME).unlink()
    with pytest.raises(fz.FrozenMismatchError, match="not been frozen"):
        er.run_evaluation(world["store"], copy_dir, world["cfg"], case_frames=world["cases"], external={})


def test_evaluation_refuses_a_model_changed_after_the_freeze(frozen, tmp_path):
    import shutil
    world = frozen
    copy_dir = tmp_path / "model"
    shutil.copytree(world["root"] / "model", copy_dir)
    assert (copy_dir / fz.FROZEN_NAME).exists()
    for victim in ("card.json", "calibrator.json", "ensemble/member_00.txt"):
        original = (copy_dir / victim).read_text()
        (copy_dir / victim).write_text(original + "\n")
        with pytest.raises(fz.FrozenMismatchError, match="differs"):
            er.run_evaluation(world["store"], copy_dir, world["cfg"], case_frames=world["cases"], external={})
        (copy_dir / victim).write_text(original)


def test_single_evaluation_record_blocks_a_second_run_unless_rerun(tmp_path):
    report = tmp_path / "r.json"
    report.write_text("{}")
    er.check_single_evaluation(tmp_path, rerun=False)
    assert er.record_evaluation(tmp_path, report, rerun=False) == {"runs": 1}
    with pytest.raises(RuntimeError, match="already evaluated"):
        er.check_single_evaluation(tmp_path, rerun=False)
    er.check_single_evaluation(tmp_path, rerun=True)
    assert er.record_evaluation(tmp_path, report, rerun=True) == {"runs": 2}
    runs = json.loads((tmp_path / er.EVALUATION_RECORD).read_text())["runs"]
    assert [r["rerun"] for r in runs] == [False, True] and len(runs[0]["report_sha256"]) == 64


def test_evaluation_does_not_touch_the_frozen_files(frozen, result):
    fz.verify_freeze(frozen["root"] / "model", {})


# ------------------------------------------------------------------------------------------- thresholds

def test_thresholds_are_the_frozen_stage1_ones_not_re_picked_on_test(frozen, result):
    card = hm.HazardModel.load(frozen["root"] / "model").card
    thr = result["thresholds"]
    assert thr["model"]["watch"] == card["alert_levels"]["watch"]["raw"]
    assert thr["model"]["warning"] == card["alert_levels"]["warning"]["raw"]
    assert thr["model_deployed"]["watch"] == card["alert_levels"]["watch"]["risk"]
    payload = json.loads((frozen["root"] / "model" / "cv_results.json").read_text())
    for name in er.BASELINES:
        assert thr[name]["watch"] == payload["evaluation"]["thresholds"][name]["watch"]["raw"]
    fixed = result["test"]["main"]["fixed_thresholds"]
    for name in ("model", *er.BASELINES):
        assert fixed[name]["watch"]["threshold"] == thr[name]["watch"]
        assert fixed[name]["plain90"]["threshold"] == thr[name]["plain90"]
    assert thr["model"]["watch"] < thr["model"]["warning"] < thr["model"]["emergency"]


def test_baselines_reproduce_the_frozen_fit_or_the_run_fails(frozen):
    dev = hd.load_development(frozen["store"], frozen["cfg"]["extra_groups"], er.extra_groups_used(frozen["cfg"]),
                              frozen["cfg"]["meta_columns"])
    payload = json.loads((frozen["root"] / "model" / "cv_results.json").read_text())
    assert set(er.reproduce_baselines(dev, payload)) == set(er.BASELINES)
    payload["baseline_params_final_fit"]["intensity_duration"]["percentile"] = 99.0
    with pytest.raises(RuntimeError, match="does not reproduce"):
        er.reproduce_baselines(dev, payload)


# ------------------------------------------------------------------------------------------------ test

def test_test_sections_cover_every_requested_view(result):
    test = result["test"]
    main = test["main"]
    assert main["n_positives"] == 70 and main["n_out_of_domain_positives"] == 4
    for name in ("model", "model_deployed", *er.BASELINES):
        for label in er.LABELS:
            entry = main["fixed_thresholds"][name][label]
            assert entry["recall"]["lo"] <= entry["recall"]["value"] <= entry["recall"]["hi"]
            assert entry["fa_share"]["lo"] <= entry["fa_share"]["value"] <= entry["fa_share"]["hi"]
            included = test["buffer_sensitivity"][name][label]
            assert abs(included["fa_share"] - entry["fa_share"]["value"]) < 0.05
            assert included["recall"] == pytest.approx(entry["recall"]["value"])
    assert set(main["paired_fixed_thresholds"]) == set(er.BASELINES)
    assert set(main["paired_fixed_thresholds"]["logistic"]) == set(er.LABELS)
    assert set(test["regions"]) == {"himalaya", "western_ghats"}
    assert set(test["calibration"]) == {"all", "himalaya", "western_ghats"}
    watch = test["overall_recall"]["watch"]["all"]["model"]
    assert watch["in_domain"]["n"] == 70 and watch["overall"]["n"] == 74
    assert watch["overall"]["hits"] == watch["in_domain"]["hits"]
    assert 0.0 <= test["calibration"]["all"]["ece_deciles"]
    assert "paired_fa_at_headline_recall" in main and set(main["paired_fa_at_headline_recall"]) == set(er.BASELINES)


def test_realised_test_numbers_come_from_applying_the_frozen_threshold(frozen, result):
    model = hm.HazardModel.load(frozen["root"] / "model")
    test = er.load_test_split(frozen["store"], frozen["cfg"], er.extra_groups_used(frozen["cfg"]))
    thr = result["thresholds"]["model"]["watch"]
    scores = model.raw_score(test.positives)
    recall = result["test"]["main"]["fixed_thresholds"]["model"]["watch"]["recall"]["value"]
    assert recall == pytest.approx(np.mean(scores >= thr))
    negatives = test.negatives
    fa = float(negatives.loc[model.raw_score(negatives) >= thr, "weight"].sum() / negatives["weight"].sum())
    assert result["test"]["main"]["fixed_thresholds"]["model"]["watch"]["fa_share"]["value"] == pytest.approx(fa)


def test_deployed_rule_uses_calibrated_risk(frozen, result):
    model = hm.HazardModel.load(frozen["root"] / "model")
    test = er.load_test_split(frozen["store"], frozen["cfg"], er.extra_groups_used(frozen["cfg"]))
    risk = model.score(test.positives)["risk"].to_numpy()
    thr = result["thresholds"]["model_deployed"]["watch"]
    got = result["test"]["main"]["fixed_thresholds"]["model_deployed"]["watch"]["recall"]["value"]
    assert got == pytest.approx(np.mean(risk >= thr))
    assert got >= result["test"]["main"]["fixed_thresholds"]["model"]["watch"]["recall"]["value"] - 1e-12


# ----------------------------------------------------------------------------------------- window, cases

def test_window_and_case_sections(result):
    window = result["window_2023"]
    assert set(window) == {"model", "model_deployed", *er.BASELINES}
    assert window["model"]["positive_cells"] == 1 and window["model"]["control_cells"] == 20
    assert window["model"]["threshold"] == result["thresholds"]["model"]["watch"]
    kerala, wayanad = result["cases"]["kerala_2018"], result["cases"]["wayanad_2024"]
    assert kerala["metrics"]["n_events"] == 2 and len(kerala["events"]) == 2
    assert kerala["thresholds"]["watch"] < kerala["thresholds"]["warning"] < kerala["thresholds"]["emergency"]
    assert len(kerala["metrics"]["alerted_area"]["per_day"]) == 6
    assert wayanad["metrics"]["box_cells"] == 36 and len(wayanad["series"]) == 4
    assert "first_watch_plus" in wayanad["metrics"]


# --------------------------------------------------------------------------- leave-region-out, ablations

def test_leave_region_out_uses_frozen_settings_and_only_the_allowed_rows(frozen, monkeypatch):
    seen = []
    real = hm.fit_booster

    def spy(train, columns, constraints, hp, seed, settings, **kwargs):
        seen.append((set(train["region"]), set(train["split"]), kwargs, hp, list(columns)))
        return real(train, columns, constraints, hp, seed, settings, **kwargs)

    monkeypatch.setattr(hm, "fit_booster", spy)
    out = _run(frozen)["leave_region_out"]
    assert set(out) == {"himalaya_to_western_ghats", "western_ghats_to_himalaya"}
    lro_calls = [c for c in seen if len(c[0]) == 1]
    assert len(lro_calls) == 4
    card = hm.HazardModel.load(frozen["root"] / "model").card
    for regions, splits, kwargs, hp, columns in lro_calls:
        assert splits <= {"train", "validation"} and kwargs == {"num_rounds": card["n_trees"]}
        assert hp == card["hyperparameters"]
    no_elev = [c[4] for c in lro_calls if "stat_elev_mean" not in c[4]]
    assert len(no_elev) == 2 and all("stat_slope_mean" in cols for cols in no_elev)
    entry = out["himalaya_to_western_ghats"]
    assert entry["held_out_region"] == "western_ghats" and entry["result"]["n_positives"] == int(
        (er.load_test_split(frozen["store"], frozen["cfg"], ["integ", "corr"]).positives["region"] == "western_ghats").sum())
    assert entry["result"]["warning"] is not None
    assert set(entry["result"]["metrics"]) == {"full_model", "region_only", "region_only_no_elevation"}


def test_ablations_cover_every_stage_one_candidate_at_its_own_threshold(result):
    ab = result["ablations"]
    assert {"full", "stat_no_elevation", "drop_src", "drop_wet"} <= set(ab["variants"])
    assert ab["selected"] in ab["variants"] and ab["variants"][ab["selected"]]["frozen_model"]
    assert len(ab["variants"]) == 7
    fixed = ab["result"]["fixed_thresholds"]
    for name, info in ab["variants"].items():
        assert fixed[name]["watch"]["threshold"] == pytest.approx(info["oof_recall_first"]["raw"])
        assert info["n_inputs"] > 0 and info["n_trees"] >= 1
    others = [n for n, i in ab["variants"].items() if not i["frozen_model"]]
    assert all(ab["variants"][n]["oof_matches_stage1"] for n in others)
    assert set(ab["result"]["paired_fixed_thresholds"]) == set(others)


# ------------------------------------------------------------------------------------- gate and report

def test_gate_assessment_numbers_are_taken_from_the_frozen_threshold(result):
    gate = result["gate"]
    target = gate["recall_first_target"]
    watch = result["test"]["main"]["fixed_thresholds"]["model"]["watch"]
    assert target["test_recall"] == watch["recall"] and target["test_fa_share"] == watch["fa_share"]
    assert target["reached"] == (watch["recall"]["value"] >= 0.9)
    assert target["shortfall"] == pytest.approx(max(0.0, 0.9 - watch["recall"]["value"]))
    assert set(target["per_region"]) == {"himalaya", "western_ghats"}
    assert set(gate["baseline_comparison"]) == set(er.BASELINES) and gate["limits"]
    for comparison in gate["baseline_comparison"].values():
        assert comparison["fa_at_own_90_threshold_descriptive"]["verdict"] in {"model better", "tie"} or "better" in \
            comparison["fa_at_own_90_threshold_descriptive"]["verdict"]


def test_report_files_are_strict_json_and_contain_every_section(result, tmp_path):
    json_path, md_path = er.write_report(result, tmp_path)
    json.loads(json_path.read_text(), parse_constant=lambda c: pytest.fail(f"non-strict constant {c}"))
    text = md_path.read_text(encoding="utf-8")
    for heading in ("## 0. Protocol history", "## 1. Gate assessment", "## 2. Stage-1 cross-validation",
                    "## 3. Frozen thresholds", "## 4. test_2018 at the frozen thresholds", "## 5. Calibration on test_2018",
                    "## 6. 2023 India window test", "## 7. Case studies", "## 8. Leave-region-out",
                    "## 9. Ablations on test_2018", "## 10. Monotonicity"):
        assert heading in text, heading
    assert "adopted AFTER the v1 test result" in text and "integ and corr groups were evaluated and not selected" in text


def test_render_only_rebuilds_the_markdown_from_the_saved_json(result, tmp_path):
    _, md_path = er.write_report(result, tmp_path)
    original = md_path.read_text(encoding="utf-8")
    md_path.unlink()
    assert er.main(["--out", str(tmp_path), "--render-only"]) == 0
    assert md_path.read_text(encoding="utf-8") == original


def test_v1_history_is_read_from_the_saved_v1_report(tmp_path):
    assert er.v1_history(tmp_path) is None
    v1 = {"gate": {"recall_first_target": {"test_recall": {"value": 0.8, "lo": 0.7, "hi": 0.9},
                                           "test_fa_share": {"value": 0.2, "lo": 0.2, "hi": 0.2},
                                           "overall_recall_incl_out_of_domain": {"value": 0.7, "lo": 0.6, "hi": 0.8}}},
          "validation": {"metrics": {"model": {"fa_at_recall_0.9": {"value": 0.18, "lo": 0.1, "hi": 0.2}}}},
          "test_2018": {"metrics": {n: {"fa_at_recall_0.9": {"value": 0.3, "lo": 0.2, "hi": 0.4}}
                                    for n in ("model", "intensity_duration", "lhasa_style", "logistic")}},
          "calibration": {"test_2018": {"base_rate": 6e-6, "mean_predicted_risk": 8e-6, "ece_deciles": 3e-6}},
          "feature_importance_gain": {"stat_elev_mean": 1.0}, "grid": {"candidates": [1, 2, 3]}}
    (tmp_path / er.V1_REPORT).write_text(json.dumps(v1))
    history = er.v1_history(tmp_path)
    assert history["test_recall_at_validation_threshold"]["value"] == 0.8 and history["top_feature"] == "stat_elev_mean"
    assert history["n_grid_candidates"] == 3


# ================================================================================ v3-live (per-region calibration)

def v3_cfg():
    """The v3 shape on the synthetic store: groups that live only in extra tables, a second group stage, per-region
    calibration and a `model_dir` (which makes the evaluation a v3-live one)."""
    cfg = tiny_cfg()
    cfg["model_dir"] = "model_v3_live"
    cfg["groups"] = ["corr", "stat"]
    cfg["group_stages"] = [{"candidates": [{"name": "core", "groups": ["corr", "stat"]},
                                           {"name": "core_noelev", "groups": ["corr", "stat"],
                                            "exclude": ["stat_elev_mean"]}]},
                           {"candidates": [{"name": "+integ", "add_groups": ["integ"]}]}]
    cfg["calibration"]["per_region"] = True
    cfg["calibration"]["min_region_positives"] = 10
    return cfg


def _with_corr(frame: pd.DataFrame, seed: int, region: str = "western_ghats") -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    frame = frame.copy()
    frame["corr_q50_1"] = rng.random(len(frame)).astype(np.float32)
    frame["corr_p_exceed99"] = rng.random(len(frame)).astype(np.float32)
    frame["integ_trw_rain_1"] = rng.random(len(frame)).astype(np.float32)
    frame["integ_frac_trusted_100km"] = rng.random(len(frame)).astype(np.float32)
    frame["region"] = region
    return frame


@pytest.fixture(scope="module")
def world3(tmp_path_factory):
    root = tmp_path_factory.mktemp("v3final")
    samples, universe = synthetic_development(n_pos_train=110, n_pos_validation=50, n_per_region=2500)
    test_samples = synthetic_samples("test_2018", n_pos=70, seed=21, n_out_of_domain=4, years=[2018])
    test_universe = synthetic_universe("test_2018", n_per_region=2500, seed=22, years=[2018])
    window = _window_frame(synthetic_universe("x", n_per_region=200, seed=23))
    tables = {"train_samples": samples[samples["split"] == "train"].reset_index(drop=True),
              "validation_samples": samples[samples["split"] == "validation"].reset_index(drop=True),
              "universe_train": universe[universe["split"] == "train"].reset_index(drop=True),
              "universe_validation": universe[universe["split"] == "validation"].reset_index(drop=True),
              "test_2018_samples": test_samples, "universe_test_2018": test_universe, "window_2023_samples": window}
    store = write_store(root / "features", tables)
    cfg = v3_cfg()
    tr.train(store, root / "model", cfg, report_dir=root / "reports")
    feats = synthetic_universe("x", n_per_region=400, seed=24)
    cases = {"kerala_2018": _with_corr(_case_frame(8.0, 77.0, 5, 6, feats, positives=[(12, 3), (3, 4)]), 1),
             "wayanad_2024": _with_corr(_case_frame(11.5, 75.9, 6, 4, feats), 2)}
    reports = root / "reports_in"
    reports.mkdir()
    challengers = {"v3_vs_v2": {"fa_a": 0.1955, "fa_b": 0.1884, "point_difference": 0.0071, "mean_difference": 0.0059,
                                "se": 0.0149, "ci_lo": -0.0203, "ci_hi": 0.0384, "level": 0.95, "n_boot": 2000,
                                "excludes_zero": False, "share_a_better": 0.3745, "share_tied": 0.0}}
    (reports / er.CHALLENGERS_REPORT).write_text(json.dumps(challengers))
    v2_target = {"watch_threshold_raw": 0.0233,
                 "test_recall": {"value": 0.85, "lo": 0.775, "hi": 0.925},
                 "test_fa_share": {"value": 0.214, "lo": 0.212, "hi": 0.216},
                 "per_region": {r: {"recall": {"value": 0.8, "lo": 0.7, "hi": 0.9},
                                    "fa_share": {"value": 0.2, "lo": 0.19, "hi": 0.21}} for r in er.REGIONS},
                 "plain90_recall": {"value": 0.8, "lo": 0.7, "hi": 0.9},
                 "plain90_fa_share": {"value": 0.19, "lo": 0.18, "hi": 0.2},
                 "overall_recall_in_domain": {"value": 0.85, "lo": 0.77, "hi": 0.92, "n": 80, "hits": 68},
                 "overall_recall_incl_out_of_domain": {"value": 0.8, "lo": 0.72, "hi": 0.88, "n": 85, "hits": 68}}
    (reports / er.V2_REPORT).write_text(json.dumps({"gate": {"recall_first_target": v2_target},
                                                    "test": {"main": {"n_positives": 80}}}))
    fz.write_freeze(root / "model", {})
    return {"root": root, "store": store, "cfg": cfg, "cases": cases, "reports": reports}


@pytest.fixture(scope="module")
def result3(world3):
    return er.run_evaluation(world3["store"], world3["root"] / "model", world3["cfg"], case_frames=world3["cases"],
                             reports_dir=world3["reports"], external={})


def test_v2_evaluation_is_unchanged_by_the_v3_support(result):
    assert "variant" not in result["meta"] and "comparison" not in result
    assert "thresholds_risk_by_region" not in result
    assert "watch_threshold_risk_by_region" not in result["gate"]["recall_first_target"]
    assert set(result["thresholds"]["model_deployed"]) == set(er.LABELS)
    assert er.render(result).startswith("# Phase 3 hazard model report (protocol v2)")
    assert result["gate"]["limits"] == er.LIMITS
    assert all("region" not in entry for entry in result["cases"].values())


def test_per_region_calibration_is_used_for_test_risk_and_the_deployed_rule(world3, result3):
    model = hm.HazardModel.load(world3["root"] / "model")
    assert model.region_calibrator is not None and result3["meta"]["calibration"] == "per_region"
    test = er.load_test_split(world3["store"], world3["cfg"], er.extra_groups_used(world3["cfg"]))
    raw_pos, raw_uni = model.raw_score(test.positives), model.raw_score(test.universe)
    regional = (model.region_calibrator.predict(raw_pos, test.positives["region"].to_numpy()),
                model.region_calibrator.predict(raw_uni, test.universe["region"].to_numpy()))
    pooled = (model.calibrator.predict(raw_pos), model.calibrator.predict(raw_uni))
    assert not np.allclose(regional[1], pooled[1])
    cfg = world3["cfg"]
    got = result3["test"]["calibration"]["all"]["mean_predicted_risk"]
    from_regional = er.ev.calibration_report(er.ev.build_view(test, {"model": (raw_pos, raw_uni)}, risk=regional), cfg)
    from_pooled = er.ev.calibration_report(er.ev.build_view(test, {"model": (raw_pos, raw_uni)}, risk=pooled), cfg)
    assert got == pytest.approx(from_regional["mean_predicted_risk"])
    assert got != pytest.approx(from_pooled["mean_predicted_risk"])
    watch = model.card["alert_levels"]["watch"]["risk_by_region"]
    margin = regional[0] - np.array([watch[r] for r in test.positives["region"]])
    deployed = result3["test"]["main"]["fixed_thresholds"]["model_deployed"]
    assert set(deployed) == {"watch"} and deployed["watch"]["threshold"] == 0.0
    assert deployed["watch"]["recall"]["value"] == pytest.approx(np.mean(margin >= 0))
    for region, risk in watch.items():
        assert result3["thresholds_risk_by_region"]["watch"][region] == risk
        assert result3["gate"]["recall_first_target"]["watch_threshold_risk_by_region"][region] == risk
    assert watch["himalaya"] != watch["western_ghats"]
    assert result3["gate"]["recall_first_target"]["watch_threshold_risk"] == pytest.approx(
        model.card["alert_levels"]["watch"]["risk"])


def test_the_deployed_score_is_exactly_the_risk_threshold_rule(world3):
    model = hm.HazardModel.load(world3["root"] / "model")
    test = er.load_test_split(world3["store"], world3["cfg"], er.extra_groups_used(world3["cfg"]))
    frame = pd.concat([test.positives, test.universe], ignore_index=True)
    risk = model.calibrate(model.raw_score(frame), frame)[0]
    by_region = {r: float(np.quantile(risk[(frame["region"] == r).to_numpy()], 0.9)) for r in er.REGIONS}
    model.card["alert_levels"]["watch"]["risk_by_region"] = by_region
    margin = er._deployed_margin(model)(frame)
    threshold = np.array([by_region[r] for r in frame["region"]])
    assert ((margin >= 0) == (risk >= threshold)).all() and (margin >= 0).any() and (margin < 0).any()


def test_case_studies_use_the_thresholds_of_their_region(world3, result3):
    card = hm.HazardModel.load(world3["root"] / "model").card
    for case in ("kerala_2018", "wayanad_2024"):
        entry = result3["cases"][case]
        assert entry["region"] == "western_ghats"
        assert entry["thresholds"] == {k: card["alert_levels"][k]["risk_by_region"]["western_ghats"]
                                       for k in ("watch", "warning", "emergency")}
    mixed = world3["cases"]["kerala_2018"].copy()
    mixed.loc[mixed.index[:5], "region"] = "himalaya"
    with pytest.raises(ValueError, match="one region"):
        er.case_thresholds(card, mixed, True)
    assert er.case_thresholds(card, mixed, False)[1] is None


def test_leave_region_out_and_ablations_use_the_v3_groups(world3, result3):
    card = hm.HazardModel.load(world3["root"] / "model").card
    assert not [c for c in card["columns"] if c.startswith(("rain_", "src_", "wet_"))]
    ablations = result3["ablations"]
    assert {"core", "core_noelev"} <= set(ablations["variants"]) and len(ablations["variants"]) == 3
    assert any(name.endswith("+integ") for name in ablations["variants"])
    assert ablations["variants"][ablations["selected"]]["frozen_model"]
    lro = result3["leave_region_out"]
    assert set(lro) == {"himalaya_to_western_ghats", "western_ghats_to_himalaya"}
    assert lro["himalaya_to_western_ghats"]["result"]["n_positives"] > 0


def test_v3_comparison_with_v2_comes_from_the_saved_reports(world3, result3):
    oof = result3["comparison"]["oof_paired"]
    assert oof["verdict"] == "not_shown_better" and oof["point_difference"] == pytest.approx(0.0071)
    assert result3["comparison"]["v2_test"]["test_recall"]["value"] == 0.85
    assert result3["comparison"]["v2_test"]["n_positives_in_domain"] == 80
    assert result3["comparison"]["files"] == [f"reports/{er.CHALLENGERS_REPORT}", f"reports/{er.V2_REPORT}"]
    assert result3["meta"]["variant"] == "v3_live" and result3["gate"]["limits"] == er.LIVE_LIMITS
    assert er.v2_comparison(world3["root"] / "nothing") == {"oof_paired": None, "v2_test": None, "files": []}


@pytest.mark.parametrize("lo,hi,verdict", [(-0.04, -0.01, "better"), (-0.02, 0.03, "not_shown_better"),
                                           (0.01, 0.05, "worse"), (0.0, 0.05, "not_shown_better")])
def test_oof_verdict_needs_the_interval_to_exclude_zero(lo, hi, verdict):
    assert er.oof_verdict({"ci_lo": lo, "ci_hi": hi}) == verdict


def test_v3_report_states_the_verdict_comparison_regions_and_limits(result3, tmp_path):
    json_path, md_path = er.write_report(result3, tmp_path, "phase6_live_model_report")
    json.loads(json_path.read_text(), parse_constant=lambda c: pytest.fail(f"non-strict constant {c}"))
    text = md_path.read_text(encoding="utf-8")
    assert text.startswith("# Phase 6 live-capable hazard model report (v3-live)")
    for heading in ("## 0. Verdict: v3-live against frozen v2", "## 1. Gate assessment", "## 2. Stage-1",
                    "## 3. Frozen thresholds", "## 4. test_2018 at the frozen thresholds",
                    "## 5. Calibration on test_2018", "## 6. 2023 India window", "## 7. Case studies",
                    "## 8. Leave-region-out", "## 9. Ablations", "## 10. Monotonicity",
                    "## 11. Per-region calibration", "## 12. Limits"):
        assert heading in text, heading
    assert "live-capable and is not shown to be better than v2" in text
    assert "+0.0071" in text and "[-0.0203, +0.0384]" in text
    assert "descriptive, not a hypothesis test" in text
    watch = result3["test"]["main"]["fixed_thresholds"]["model"]["watch"]
    assert f"{100 * watch['recall']['value']:.1f}%" in text and f"{100 * watch['fa_share']['value']:.1f}%" in text
    assert "frozen v2" in text and "Western Ghats" in text and "test_2018 is a second look" in text
    assert "**Limits**" not in text
    assert "70 in-domain positive cell-days (4 more below the slope floor)" in text
    assert "| frozen v2, Himalaya | 80.0% [70.0, 90.0] | 20.0% [19.0, 21.0] |" in text


def test_v3_render_only_rebuilds_the_live_markdown(result3, tmp_path, monkeypatch):
    monkeypatch.setattr(hm, "hazard_config", lambda path=None: {"model_dir": "m", "evaluation_report_stem": "live_stem"})
    _, md_path = er.write_report(result3, tmp_path, "live_stem")
    original = md_path.read_text(encoding="utf-8")
    md_path.unlink()
    assert er.main(["--config", str(tmp_path / "v3.yaml"), "--out", str(tmp_path), "--render-only"]) == 0
    assert md_path.read_text(encoding="utf-8") == original


def test_leave_region_out_needs_an_elevation_excluding_candidate():
    assert er.no_elevation_columns(v3_cfg()) == ["stat_elev_mean"]
    cfg = v3_cfg()
    cfg["group_stages"][0]["candidates"].pop(1)
    with pytest.raises(ValueError, match="exclude"):
        er.no_elevation_columns(cfg)


def test_v3_case_frames_are_loaded_with_the_configuration_extra_groups(world3, monkeypatch):
    calls = []
    monkeypatch.setattr(er.hd, "load_table", lambda name, directory, extras, use: calls.append((name, list(use))) or name)
    loader = er.v3_case_loader(world3["store"], world3["cfg"], ["corr", "integ"])
    assert [loader("kerala_2018"), loader("wayanad_2024")] == ["case_kerala_2018_samples", "case_wayanad_2024_samples"]
    assert calls == [("case_kerala_2018_samples", ["corr", "integ"]), ("case_wayanad_2024_samples", ["corr", "integ"])]
    card = hm.HazardModel.load(world3["root"] / "model").card
    frames = world3["cases"]
    seen = []
    out = er.case_section(world3["root"] / "model", card, world3["store"], None, True,
                          loader=lambda case: seen.append(case) or frames[case])
    assert seen == ["kerala_2018", "wayanad_2024"] and set(out) == {"kerala_2018", "wayanad_2024"}
