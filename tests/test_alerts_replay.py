"""Replay store: building per-day tables, reading them back, determinism and error paths."""
import json

import pandas as pd
import pytest

from aetherguard.alerts import frames, replay, store
from aetherguard.hazard.freeze import FrozenMismatchError
from alerts_helpers import CONFIG, STATIONS, THRESHOLDS, station_outputs
from alerts_store_helpers import FREEZE, build_store, explainer, rain_scorer, write_feature_fixture

SETS = {"case_a": {"n_cells": 3, "n_days": 6}, "case_b": {"n_cells": 2, "n_days": 4, "start": "2024-07-04"}}


@pytest.fixture
def built(tmp_path):
    manifest, out = build_store(tmp_path, SETS)
    return out, manifest, tmp_path / "features"


def test_manifest_lists_sets_dates_rows_and_the_feature_hash(built):
    out, manifest, _ = built
    assert list(manifest["sets"]) == ["case_a", "case_b"]
    a = manifest["sets"]["case_a"]
    assert a["n_rows"] == 18 and a["n_cells"] == 3 and len(a["dates"]) == 6 and a["has_sensors"]
    assert len(a["features_sha256"]) == 64 and manifest["thresholds"]["source"] == "test"
    assert json.loads((out / "store_manifest.json").read_text())["sets"]["case_b"]["dates"][0] == "2024-07-04"


def test_store_reads_back_days_cells_sensors_and_series(built):
    s = store.ReplayStore(built[0])
    assert s.sets() == ["case_a", "case_b"] and s.dates("case_a")[0] == "2024-07-01" and len(s.dates()) == 7
    name, day = s.alerts("2024-07-02")
    assert name == "case_a" and len(day) == 3 and {"level", "reasons_json", "shap_json"} <= set(day.columns)
    name, cell = s.cell(1001, "2024-07-06")
    assert name == "case_a" and cell["level_name"] in ("Normal", "Watch", "Warning", "Emergency")
    assert json.loads(cell["reasons_json"])["shap"][0]["feature"] == "rain_acc_1"
    _, sensors = s.sensors("2024-07-02")
    assert sorted(sensors["station"]) == ["A", "B"] and sensors["lat"].notna().all()
    series = s.cell_series("case_a", 1000)
    assert series["date"].is_monotonic_increasing and len(series) == 6
    assert list(s.cell_series("case_a", 1000, columns=["date", "risk"]).columns) == ["date", "risk", "cell_id"]
    assert len(s.range("2024-07-02", "2024-07-04", "case_a")) == 9
    assert s.status() == "ok"


def test_the_default_set_is_the_first_one_holding_the_date(built):
    s = store.ReplayStore(built[0])
    assert s.resolve_set("2024-07-05") == "case_a"
    assert s.resolve_set("2024-07-05", "case_b") == "case_b"
    assert s.resolve_set("2024-07-07") == "case_b"


def test_rain_driven_levels_rise_and_the_published_level_never_drops_below_the_raw_one_by_construction(built):
    series = store.ReplayStore(built[0]).cell_series("case_a", 1002)
    assert series["level"].iloc[-1] > series["level"].iloc[0] and series["level"].max() >= 1
    assert (series["level"] >= series["raw_level"]).all()


def test_missing_set_date_cell_and_store_raise_store_errors(built, tmp_path):
    s = store.ReplayStore(built[0])
    with pytest.raises(store.StoreError, match="unknown set"):
        s.dates("nope")
    with pytest.raises(store.StoreError, match="available 2024-07-01"):
        s.alerts("2030-01-01")
    with pytest.raises(store.StoreError, match="no replay data"):
        s.alerts("2024-07-08", "case_a")
    with pytest.raises(store.StoreError, match="cell 5 has no alert row"):
        s.cell(5, "2024-07-02")
    with pytest.raises(store.StoreError, match="not in set"):
        s.cell_series("case_a", 5)
    empty = store.ReplayStore(tmp_path / "none")
    assert not empty.available and empty.status() == "missing"
    with pytest.raises(store.StoreError, match="no replay store"):
        empty.sets()
    with pytest.raises(ValueError, match="start"):
        s.range("2024-07-05", "2024-07-01")


def test_status_reports_an_incomplete_store(built):
    (built[0] / "case_a" / "alerts" / "2024-07-03.parquet").unlink()
    assert store.ReplayStore(built[0]).status() == "incomplete"


def test_rebuilding_gives_identical_tables(built, tmp_path):
    out, _, features = built
    again = tmp_path / "again"
    outputs = station_outputs({"A": {"flag_every": 7}, "B": {}}, days=2400, start="2018-01-01")
    replay.build_replay(["case_a", "case_b"], again, features_dir=features, model_columns=[], scorer=rain_scorer,
                        explainer=explainer, thresholds=THRESHOLDS, config=CONFIG, station_outputs=outputs,
                        stations=STATIONS, freeze=FREEZE)
    for day in ("2024-07-01", "2024-07-04"):
        pd.testing.assert_frame_equal(store.ReplayStore(out).alerts(day)[1], store.ReplayStore(again).alerts(day)[1])


def test_frames_refuse_group_files_that_do_not_match_their_feature_table(tmp_path):
    features = tmp_path / "f"
    write_feature_fixture(features, "x")
    path = features / "integ" / "x_integ.parquet"
    pd.read_parquet(path).iloc[::-1].reset_index(drop=True).to_parquet(path)
    with pytest.raises(ValueError, match="does not match"):
        frames.load_feature_frame("x", features)
    with pytest.raises(FileNotFoundError):
        frames.load_feature_frame("nothing", features)


def test_corr_columns_are_joined_only_when_the_model_uses_them(tmp_path):
    features = tmp_path / "f"
    write_feature_fixture(features, "x")
    assert "corr_q50_1" not in frames.load_feature_frame("x", features, ["rain_acc_1"]).columns
    assert "corr_q50_1" in frames.load_feature_frame("x", features, ["corr_q50_1"]).columns


def test_a_store_cannot_be_built_without_a_freeze_record(tmp_path):
    features = tmp_path / "f"
    write_feature_fixture(features, "x")
    kwargs = dict(features_dir=features, model_columns=[], scorer=rain_scorer, explainer=None, thresholds=THRESHOLDS,
                  config=CONFIG, station_outputs=station_outputs({"A": {}}, 5), stations=STATIONS)
    for bad in ({}, None, {"created_utc": "x"}):
        with pytest.raises(ValueError, match="freeze record"):
            replay.build_replay(["x"], tmp_path / "out", freeze=bad, **kwargs)
    assert not (tmp_path / "out").exists()


def test_the_cli_refuses_an_unfrozen_model_before_building_anything(tmp_path):
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    with pytest.raises(FrozenMismatchError, match="not been frozen"):
        replay.main(["--model", str(model_dir), "--out", str(tmp_path / "out"), "--sets", "x"])
    assert not (tmp_path / "out").exists()


def test_manifest_records_the_freeze_and_case_sets_use_the_case_loader(tmp_path, monkeypatch):
    manifest, _ = build_store(tmp_path, {"case_a": SETS["case_a"]})
    assert manifest["freeze"] == {"created_utc": FREEZE["created_utc"], "card_sha256": "0" * 64}
    seen = []
    monkeypatch.setattr(replay.cases, "load_case_frame", lambda case, directory: seen.append((case, directory)) or "frame")
    assert replay.load_set_frame("case_kerala_2018_samples", tmp_path, []) == "frame"
    assert seen == [("kerala_2018", tmp_path)]
