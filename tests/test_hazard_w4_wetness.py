"""W4 (spec 2026-11-13): the two study configurations, and what `hazard.v4_int` gained to run them by configuration only:
other extra groups beside `iint`, a labelled stage 1, the second development guard against the incumbent's stored OOF,
`requires.stage_one` naming the inputs a stage must have tested, the wetness record of the model card, and the season tables
of an added group joined to the panels. On synthetic data; the W3 behaviour is checked unchanged in test_hazard_v4_int.py."""
import copy
import hashlib
import json
from datetime import date

import numpy as np
import pandas as pd
import pytest

from aetherguard.config import PROJECT_ROOT, load_config_file
from aetherguard.features import imerg_build as B
from aetherguard.features import imerg_intensity as ii
from aetherguard.features import wetness as wt
from aetherguard.hazard import challengers as ch
from aetherguard.hazard import model as hm
from aetherguard.hazard import v4_int as v4
from aetherguard.live import backtest as bt
from aetherguard.live import hardening as H

from hazard_helpers import synthetic_development, write_dev_store
from test_hazard_v4_int import (BOOT, COLUMNS, FOLDS, HEAVY, IINT, SEASON_CELLS, WAYANAD, YEAR, IintModel, add_intensity,
                                difference, frozen, stub_score_rows, toy, world, write_iint_store, write_season_iint)  # noqa: F401

IWET = wt.feature_names()
STATIC = ["lc_tree", "lc_shrub_grass", "lc_crop", "lc_bare", "soil_clay", "soil_sand", "soil_coarse", "ter_steep25", "ter_steep35"]


def small(path: str) -> dict:
    study = load_config_file(PROJECT_ROOT / path)
    base = copy.deepcopy(hm.hazard_config(PROJECT_ROOT / study["base_config"]))
    base["training"].update(max_rounds=40, early_stopping_rounds=5, universe_negatives=600)
    base["cv"]["folds"] = FOLDS
    base["bootstrap"].update(n=40)
    base["ensemble"].update(members=3)
    base["groups"], base["group_stages"] = ["stat"], []
    study["base"] = base
    return study


@pytest.fixture(scope="module")
def study():
    """Stage 1 (w4_wet) as the tests run it."""
    return small("configs/hazard_w4_wet.yaml")


@pytest.fixture(scope="module")
def v5():
    return small("configs/hazard_v5.yaml")


# ------------------------------------------------------------------------------------------ configuration

def test_w4_wet_is_v3_plus_the_three_non_decreasing_wetness_inputs_and_nothing_else(study):
    candidates = v4.make_candidates(study, COLUMNS, {c: "iwet" for c in IWET})
    c0, wet = candidates["C0"], candidates["w4_wet"]
    assert wet.columns == COLUMNS + IWET and wet.constraints == c0.constraints + [1, 1, 1]
    assert study["base_config"] == "configs/hazard_v3.yaml" and study["candidates"]["w4_wet"]["add_groups"] == ["iwet"]
    assert "add_static" not in study["candidates"]["w4_wet"] and v4.static_inputs(study) == []
    assert study["extra_groups"]["iwet"] == {"subdir": "imerg", "suffix": wt.GROUP, "columns_file": B.columns_name(wt.GROUP),
                                             "manifest_file": B.manifest_name(wt.GROUP)}
    assert v4.extra_groups(study, 1)["iwet"] == study["extra_groups"]["iwet"] and v4.extra_groups(study, 1)["iint"]["suffix"] == "iint_lag1"
    assert v4.groups_used(study)[-1] == "iwet" and "iint" not in v4.groups_used(study)
    assert v4.output_dir(study).name == "w4_wet" and study["reproduction_tolerance"] <= 1e-12


def test_v5_is_exactly_v4_plus_the_wetness_group(v5):
    v4cfg = load_config_file(PROJECT_ROOT / "configs" / "hazard_v4.yaml")
    mine, theirs = v5["candidates"]["v5"], v4cfg["candidates"]["v4"]
    assert mine["add_increasing"] == theirs["add_increasing"] + IWET and mine["add_static"] == theirs["add_static"] == STATIC
    assert mine["add_groups"] == ["iint", "iwet"] and v5["extra_groups"]["iint"] == v4cfg["extra_groups"]["iint"]
    candidates = v4.make_candidates(v5, COLUMNS, {**{c: "iint" for c in IINT}, **{c: "iwet" for c in IWET}})
    assert candidates["v5"].columns == COLUMNS + IINT + IWET + STATIC
    assert candidates["v5"].constraints[len(COLUMNS):] == [1] * 9 + [0] * 9
    assert v5["pool_names"] == ["v4_ranked", "v5"] and v5["incumbent"] == {"seasons_dir": "v4_seasons", "season_tag": "v4"}
    assert v5["requires"] == {"adopted": "v4", "stage_one": {"w4_wet": IWET}}
    assert v5["incumbent_dev"] == {"output_dir": "v4", "candidate": "v4"} and v4.season_groups(v5) == ["iwet"]
    assert v5["preflight"] == v4cfg["preflight"] and v5["tie_seed"] == v4cfg["tie_seed"] == v4.TIE_SEED
    assert v5["report_stem"] != "phase8_wetness"              # the committed development report must not block the look
    for key in ("static_table", *[f"incumbent_season_{y}" for y in range(2018, 2026)], "incumbent_card", "iwet_manifest"):
        assert key in v5["provenance_files"]
    assert v5["provenance_files"]["incumbent_card"] == "processed/hazard/v4/models/v4/card.json"


# ------------------------------------------------------------------------------------------ stage 1 wording

def test_stage_one_keeps_w3_wording_by_default_and_names_the_study_otherwise(study):
    assert v4.stage_one(difference(-0.1, 0.1))["rule"] == v4.STAGE_ONE_RULE
    labelled = v4.study_stage_one(study, difference(-0.1, 0.1))
    assert "w4_wet - C0" in labelled["rule"] and "w4-wet is not significantly worse" in labelled["rule"]
    assert "v4-int" not in labelled["rule"] and labelled["passed"]
    worse = v4.study_stage_one(study, difference(0.01, 0.1), "v4", "v4")
    assert not worse["passed"] and worse["verdict"] == "significantly worse than v4" and "w4_wet - v4" in worse["rule"]
    reason = v4.decide(worse, label="w4-wet")["reason"]
    assert reason.startswith("a pre-declared development guard failed") and "w4-wet is not evaluated" in reason


# ------------------------------------------------------------------------------------------ requires

def write_dev_results(root, name: str, passed: bool, columns):
    directory = root / "processed" / "hazard" / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / v4.DEV_RESULTS).write_text(json.dumps({"stage_one": {"passed": passed},
                                                        "candidates": {"C0": {"columns": COLUMNS}, name: {"columns": columns}}}))


def test_requires_stage_one_by_name_checks_the_inputs_that_stage_tested(v5, isolated_data_root):
    directory = isolated_data_root / "processed" / "hazard" / "v4"
    directory.mkdir(parents=True)
    (directory / v4.HELDOUT).write_text(json.dumps({"decision": {"adopt": True}}))
    write_dev_results(isolated_data_root, "w4_wet", True, COLUMNS + IWET)
    checks = v4.check_requires(v5)
    assert [c["passed"] for c in checks] == [True, True] and "iwet_sat_l2" in checks[1]["name"]
    write_dev_results(isolated_data_root, "w4_wet", True, COLUMNS + IWET[:2])
    assert [c["passed"] for c in v4.check_requires(v5)] == [True, False]
    write_dev_results(isolated_data_root, "w4_wet", False, COLUMNS + IWET)
    assert [c["passed"] for c in v4.check_requires(v5)] == [True, False]
    (directory / v4.HELDOUT).write_text(json.dumps({"decision": {"adopt": False}}))
    assert v4.check_requires(v5)[0]["passed"] is False


# ------------------------------------------------------------------------------------- the incumbent guard

def frames_like(world, seed: int):
    dev, layout = world
    rng = np.random.default_rng(seed)
    oof = type("O", (), {})()
    oof.pos, oof.neg, oof.matched = (rng.random(len(layout.positives)) + 0.5, rng.random(len(layout.negatives)),
                                     rng.random(len(layout.matched)))
    return ch.oof_frame(layout, oof)


def test_the_incumbent_guard_pairs_the_stored_oof_rows_and_refuses_other_rows(v5, world, isolated_data_root):
    mine, theirs = frames_like(world, 1), frames_like(world, 2)
    directory = isolated_data_root / "processed" / "hazard" / "v4" / v4.OOF_SUBDIR
    ch.write_oof(directory / "oof_v4.parquet", theirs)
    out = v4.incumbent_dev_stage(v5, {"C0": theirs, "v5": mine})
    assert out["incumbent"] == "v4" and out["stage"]["rule"].count("v5 - v4") == 1
    assert out["difference"]["point_difference"] == pytest.approx(out["difference"]["fa_a"] - out["difference"]["fa_b"])
    assert v4.incumbent_dev_stage({**v5, "incumbent_dev": None}, {"v5": mine}) is None
    ch.write_oof(directory / "oof_v4.parquet", theirs.iloc[::-1].reset_index(drop=True))
    with pytest.raises(ValueError, match="differ"):
        v4.incumbent_dev_stage(v5, {"v5": mine})


# ------------------------------------------------------------------------- stage 1 on a synthetic store

def add_wetness(frame: pd.DataFrame, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rain = frame["rain_acc_7"].to_numpy(dtype=np.float64)
    sat = np.clip(rain / (rain.max() + 1) + rng.uniform(0, 0.3, len(frame)), 0, 1)
    return frame.assign(iwet_sat_l2=sat, iwet_sat_anom_l2=sat - 0.4, iwet_satdays30_l2=np.round(sat * 30)).astype(
        {c: np.float32 for c in IWET})


def write_iwet_store(directory, tables: dict) -> None:
    sub = directory / "imerg"
    sub.mkdir(parents=True, exist_ok=True)
    files = {}
    for name, frame in tables.items():
        path = sub / B.table_name(name, wt.GROUP)
        add_wetness(frame, len(name))[["cell_id", "date", *IWET]].to_parquet(path)
        files[path.name] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "n_rows": len(frame)}
    (sub / B.columns_name(wt.GROUP)).write_text(json.dumps({c: wt.GROUP for c in IWET}), encoding="utf-8")
    (sub / B.manifest_name(wt.GROUP)).write_text(json.dumps({"frozen": True, "files": files}), encoding="utf-8")


@pytest.fixture(scope="module")
def wet_store(tmp_path_factory):
    samples, universe = synthetic_development(n_pos_train=110, n_pos_validation=50, n_per_region=2500)
    directory = write_dev_store(tmp_path_factory.mktemp("features"), samples, universe, extras=False)
    tables = {n: pd.read_parquet(directory / f"{n}_features.parquet") for n in
              ("train_samples", "validation_samples", "universe_train", "universe_validation")}
    write_iint_store(directory, tables, lag=1)
    write_iwet_store(directory, tables)
    return directory


def test_stage_one_runs_through_v4_int_with_the_wetness_group_and_writes_a_wetness_card(study, wet_store, frozen,
                                                                                         isolated_data_root, monkeypatch):
    monkeypatch.setattr(v4, "frozen_selection", lambda s: frozen)
    monkeypatch.setattr(v4, "declared_lag", lambda: 1)
    monkeypatch.setattr(v4, "study_stage_one", lambda s, d, *a, **k: {**v4.stage_one(d, "w4_wet", "w4-wet"), "passed": True})
    payload = v4.run_dev(study, wet_store, say=lambda m: None)
    assert payload["candidates"]["w4_wet"]["columns"] == COLUMNS + IWET
    assert payload["candidates"]["w4_wet"]["constraints"]["iwet_satdays30_l2"] == 1
    assert "w4_wet - C0" in payload["stage_one"]["rule"] and "against_incumbent" not in payload["stage_one"]
    model = hm.HazardModel.load(v4.output_dir(study) / v4.MODEL_SUBDIR / "w4_wet")
    assert model.card["wetness"] == {"group": "iwet", "lag_days": 2, "inputs": IWET, "constraints": "non-decreasing"}
    assert "intensity" not in model.card and model.card["protocol"] == study["protocol"]
    assert model.card["description"].startswith("W4 stage 1 w4_wet") and model.card["monotone_assumptions"]["increasing"][-3:] == IWET


def test_stage_two_fails_when_v5_is_significantly_worse_than_the_incumbent(v5, wet_store, frozen, isolated_data_root,
                                                                            monkeypatch):
    monkeypatch.setattr(v4, "frozen_selection", lambda s: frozen)
    monkeypatch.setattr(v4, "declared_lag", lambda: 1)
    monkeypatch.setattr(v4, "check_requires", lambda s: [])
    lean = copy.deepcopy(v5)
    lean["candidates"]["v5"].pop("add_static")                 # the synthetic store has no static table
    calls = []

    def guard(s, d, reference=None, than="v3"):
        calls.append(reference)
        return {**v4.stage_one(d, "v5", "v5", reference or "C0", than), "passed": reference is None}
    monkeypatch.setattr(v4, "study_stage_one", guard)
    monkeypatch.setattr(v4, "incumbent_dev_stage", lambda s, frames: {"incumbent": "v4", "stage": guard(s, difference(0.01, 0.02), "v4", "v4")})
    payload = v4.run_dev(lean, wet_store, say=lambda m: None)
    assert payload["stage_one"]["passed"] is False and payload["stage_one"]["against_incumbent"]["passed"] is False
    assert payload["model_dir"] is None and payload["decision"]["adopt"] is False and calls == [None, "v4"]


# ------------------------------------------------------------------------------ season tables of a group

def write_season_iwet(directory, cells=SEASON_CELLS, tamper=False, frozen_flag=True):
    days = bt.day_range(date(YEAR, 6, 1) - pd.Timedelta(days=bt.WARMUP_DAYS).to_pytimedelta(), date(YEAR, 12, 31))
    frame = ii.panel_frame(cells["cell_id"].to_numpy(dtype=np.int64), days)
    hot = ((frame["cell_id"] == WAYANAD) & (frame["date"] == pd.Timestamp(HEAVY[0]))).to_numpy()
    for name in IWET:
        frame[name] = np.where(hot, 0.9, 0.1).astype(np.float32)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / wt.season_name(YEAR)
    frame.to_parquet(path, index=False)
    (directory / B.columns_name(wt.GROUP)).write_text(json.dumps({c: wt.GROUP for c in IWET}), encoding="utf-8")
    (directory / B.manifest_name(wt.GROUP)).write_text(json.dumps({"frozen": frozen_flag, "files": {
        path.name: {"sha256": hashlib.sha256(path.read_bytes()).hexdigest()}}}), encoding="utf-8")
    if tamper:
        frame[IWET[0]] = np.float32(0.5)
        frame.to_parquet(path, index=False)
    return days


class WetModel(IintModel):
    columns = COLUMNS + IINT + IWET


def test_a_v5_season_carries_the_wetness_table_to_the_model(toy, tmp_path, v5, monkeypatch):
    lean = copy.deepcopy(v5)
    lean["candidates"]["v5"].pop("add_static")
    features = tmp_path / "features" / "imerg"
    write_season_iint(features, lag=1)
    days = write_season_iwet(features)
    seen = {}

    def scorer(model, rows):
        seen.setdefault("columns", list(rows.columns))
        out = stub_score_rows(model, rows)
        out["risk"] = rows["iwet_sat_l2"].to_numpy(dtype=np.float64)
        return out
    monkeypatch.setattr(H, "score_rows", scorer)
    path = v4.score_season(WetModel(), "ab" * 32, lean, YEAR, tmp_path / "features", tmp_path / "panels", say=lambda m: None,
                           lag_days=1)
    assert path.name == f"season_{YEAR}_v5.npz" and set(IWET) <= set(seen["columns"])
    panel = H.load_panel(path)
    wayanad = SEASON_CELLS.index[SEASON_CELLS["cell_id"] == WAYANAD][0]
    assert panel["risk"][wayanad, days.index(HEAVY[0])] == pytest.approx(0.9)
    assert panel["risk"][wayanad, days.index(date(YEAR, 7, 1))] == pytest.approx(0.1)
    assert json.loads(path.with_suffix(".json").read_text())["features"] == "training_style+iint+static_w5+iwet"


def test_the_group_season_table_is_verified_against_its_manifest_cells_and_days(tmp_path, v5):
    features = tmp_path / "features"
    days = write_season_iwet(features / "imerg")
    ids = SEASON_CELLS["cell_id"].to_numpy(dtype=np.int64)
    table = v4.season_group(v5, "iwet", features, YEAR, ids, days)
    assert list(table.columns) == IWET and len(table) == len(ids) * len(days)
    with pytest.raises(v4.IintTableError, match="cells"):
        v4.season_group(v5, "iwet", features, YEAR, ids[::-1], days)
    with pytest.raises(v4.IintTableError, match="days"):
        v4.season_group(v5, "iwet", features, YEAR, ids, days[1:])
    assert all(c["passed"] for c in v4.check_group_tables(v5, features))
    write_season_iwet(features / "imerg", tamper=True)
    with pytest.raises(v4.IintTableError, match="checksum"):
        v4.season_group(v5, "iwet", features, YEAR, ids, days)
    assert [c["name"] for c in v4.check_group_tables(v5, features) if not c["passed"]] == ["iwet tables intact"]
    write_season_iwet(features / "imerg", frozen_flag=False)
    with pytest.raises(v4.IintTableError, match="frozen"):
        v4.season_group(v5, "iwet", features, YEAR, ids, days)
    with pytest.raises(FileNotFoundError, match="iwet"):
        v4.season_group(v5, "iwet", tmp_path / "none", YEAR, ids, days)
