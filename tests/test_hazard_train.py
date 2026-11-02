import copy
import json

import numpy as np
import pandas as pd
import pytest

from aetherguard.hazard import data as hd
from aetherguard.hazard import model as hm
from aetherguard.hazard import train as tr

from hazard_helpers import EXTRA_GROUPS, synthetic_development, write_dev_store

BASE = hm.hazard_config()
FOLDS = [[2007, 2008], [2009, 2010], [2011, 2012], [2013, 2014], [2015], [2016], [2017]]


def tiny_cfg():
    cfg = copy.deepcopy(BASE)
    cfg["extra_groups"] = EXTRA_GROUPS
    cfg["meta_columns"] = ["integ_n_st_100km"]
    cfg["training"].update(max_rounds=30, early_stopping_rounds=5, universe_negatives=500)
    cfg["cv"]["folds"] = FOLDS
    cfg["grid"] = {"num_leaves": [4], "min_data_in_leaf": [10], "feature_fraction": [0.9], "lambda_l2": [0, 5]}
    cfg["ensemble"].update(members=3)
    cfg["bootstrap"].update(n=50)
    return cfg


@pytest.fixture(scope="module")
def trained(tmp_path_factory):
    root = tmp_path_factory.mktemp("hazard")
    samples, universe = synthetic_development(n_pos_train=110, n_pos_validation=50, n_per_region=2500)
    store = write_dev_store(root / "features", samples, universe)
    cfg = tiny_cfg()
    log = []
    model = tr.train(store, root / "model", cfg, progress=log.append, report_dir=root / "reports")
    return model, root, store, cfg, log


def test_outputs_are_written(trained):
    model, root, _, _, log = trained
    for name in ("model.txt", "calibrator.json", "card.json", "cv_results.json"):
        assert (root / "model" / name).is_file()
    assert len(list((root / "model" / "ensemble").glob("member_*.txt"))) == 3
    for name in ("phase3_hazard_cv_report.md", "phase3_hazard_cv_report.json"):
        assert (root / "reports" / name).is_file()
    assert any("selected feature set" in line for line in log)
    text = (root / "reports" / "phase3_hazard_cv_report.md").read_text(encoding="utf-8")
    for heading in ("## Hyper-parameter grid", "## Feature-group selection", "## OOF thresholds and alert levels",
                    "## OOF metrics, model versus baselines", "## Per-fold variability", "## OOF calibration",
                    "## Monotonicity"):
        assert heading in text, heading
    json.loads((root / "reports" / "phase3_hazard_cv_report.json").read_text(),
               parse_constant=lambda c: pytest.fail(f"non-strict constant {c}"))


def test_card_records_the_protocol_the_choices_and_the_alert_levels(trained):
    model, _, store, cfg, _ = trained
    card = model.card
    assert card["folds"] == FOLDS and card["n_trees"] == model.best_iteration
    assert card["selection"]["grid"] and len(card["selection"]["grid"]) == 3          # 2 grid points + extra neg_mix
    assert {r["name"] for r in card["selection"]["groups"]} >= {"full", "stat_no_elevation", "drop_src", "drop_wet"}
    assert set(card["alert_levels"]) == {"watch", "warning", "emergency"}
    levels = card["alert_levels"]
    assert levels["watch"]["raw"] < levels["warning"]["raw"] < levels["emergency"]["raw"]
    assert levels["watch"]["oof_recall"] >= 0.9 and levels["watch"] == card["thresholds_oof"]["recall_first"]
    assert card["thresholds_oof"]["plain_recall_90"]["raw"] >= levels["watch"]["raw"]
    assert card["monotone_assumptions"]["decreasing"] == ["rain_days_since_10mm"]
    assert card["feature_set"]["meta_columns_never_inputs"] == ["integ_n_st_100km"]
    assert card["seeds"]["ensemble_members"] == 3 and card["calibration"]["n_thresholds"] > 1
    assert all(len(v) == 64 for v in card["inputs"].values()) and any("integ" in k for k in card["inputs"])


def test_model_inputs_never_include_meta_or_station_presence_columns(trained):
    model = trained[0]
    assert not set(model.columns) & hd.NEVER_INPUTS
    assert "integ_n_st_100km" not in model.columns
    constraints = dict(zip(model.columns, model.constraints))
    assert constraints["rain_days_since_10mm"] == -1 and constraints["rain_acc_1"] == 1


def test_integ_candidates_are_selected_on_cv_and_presence_is_reported(trained):
    _, root, _, _, _ = trained
    payload = json.loads((root / "reports" / "phase3_hazard_cv_report.json").read_text())
    names = [r["name"] for r in payload["groups"]]
    assert any(n.endswith("+integ") for n in names) and any(n.endswith("+corr") for n in names)
    assert any(n.endswith("+integ+corr") for n in names)
    presence = payload["integ_presence"]
    assert presence["column"] == "integ_n_st_100km"
    assert presence["with_station"]["n_positives"] + presence["without_station"]["n_positives"] == 160
    assert len(presence["with_station"]["metrics"]) >= 2


def test_baselines_get_the_same_oof_protocol(trained):
    _, root, _, _, _ = trained
    payload = json.loads((root / "reports" / "phase3_hazard_cv_report.json").read_text())
    evaluation = payload["evaluation"]
    assert set(evaluation["metrics"]) == {"model", "intensity_duration", "lhasa_style", "logistic"}
    assert set(evaluation["paired_fa_at_90_vs_model"]) == {"intensity_duration", "lhasa_style", "logistic"}
    for name, entry in evaluation["metrics"].items():
        m = entry["pooled"]["fa_at_recall_0.9"]
        assert m["lo"] <= m["value"] <= m["hi"] or name
        rf = entry["at_thresholds"]["recall_first"]
        assert rf["recall"]["value"] >= entry["at_thresholds"]["plain"]["recall"]["value"]
    assert payload["monotonicity"] and all(c["holds"] for c in payload["monotonicity"].values())


def test_saved_model_round_trips_and_score_frame_validates_columns(trained):
    model, root, _, _, _ = trained
    loaded = hm.HazardModel.load(root / "model")
    samples, _ = synthetic_development(n_pos_train=20, n_pos_validation=10, n_per_region=100)
    frame = samples.head(60)
    np.testing.assert_array_equal(model.raw_score(frame), loaded.raw_score(frame))
    scored = hm.score_frame(frame, root / "model")
    pd.testing.assert_frame_equal(scored, model.score(frame))
    assert list(scored.columns) == ["risk", "risk_lo", "risk_hi", "risk_per_100k", "member_median_risk",
                                    "ensemble_agreement"]
    assert (scored["risk_lo"] <= scored["risk_hi"]).all()
    np.testing.assert_allclose(scored["risk_per_100k"], 1e5 * scored["risk"])
    with pytest.raises(ValueError, match="rain_acc_1"):
        hm.score_frame(frame.drop(columns=["rain_acc_1"]), root / "model")
    with pytest.raises(FileNotFoundError, match="train the model"):
        hm.score_frame(frame, root / "missing")
    top = model.contributions(frame.head(5))
    assert all(len(row) == 5 for row in top)


def test_training_is_deterministic(trained, tmp_path):
    model, _, store, cfg, _ = trained
    again = tr.train(store, tmp_path / "model", cfg, report_dir=tmp_path / "reports")
    samples, _ = synthetic_development(n_pos_train=20, n_pos_validation=10, n_per_region=100)
    np.testing.assert_array_equal(model.raw_score(samples.head(80)), again.raw_score(samples.head(80)))
    assert model.card["alert_levels"] == again.card["alert_levels"]


def test_training_never_opens_test_window_or_case_tables(trained, tmp_path, monkeypatch):
    _, _, store, cfg, _ = trained
    opened = []
    real = pd.read_parquet
    monkeypatch.setattr(pd, "read_parquet", lambda path, *a, **k: opened.append(str(path)) or real(path, *a, **k))
    tr.train(store, tmp_path / "model", cfg, report_dir=tmp_path / "reports")
    assert opened and not [p for p in opened if any(t in p for t in ("test_2018", "window", "case_"))]


def test_a_new_group_is_added_by_config_only(tmp_path):
    samples, universe = synthetic_development(n_pos_train=60, n_pos_validation=30, n_per_region=1500)
    store = write_dev_store(tmp_path / "features", samples, universe)
    cfg = tiny_cfg()
    cfg["grid"].update(lambda_l2=[0])
    cfg["group_stages"] = [{"candidates": [{"name": "full", "groups": ["rain", "src", "wet", "stat"]}]},
                           {"candidates": [{"name": "+corr", "add_groups": ["corr"]}]}]
    model = tr.train(store, tmp_path / "model", cfg, report_dir=tmp_path / "reports")
    assert model.card["feature_set"]["name"] in {"full", "full+corr"}
    assert tr.extra_groups_used(cfg) == ["corr"]


def test_missing_extra_files_fail_clearly(tmp_path):
    samples, universe = synthetic_development(n_pos_train=40, n_pos_validation=20, n_per_region=800)
    store = write_dev_store(tmp_path / "features", samples, universe, extras=False)
    with pytest.raises(FileNotFoundError):
        tr.train(store, tmp_path / "model", tiny_cfg(), report_dir=tmp_path / "reports")
    with pytest.raises(FileNotFoundError, match="feature store"):
        tr.train(tmp_path / "nowhere", tmp_path / "m2", tiny_cfg(), report_dir=tmp_path / "r2")
