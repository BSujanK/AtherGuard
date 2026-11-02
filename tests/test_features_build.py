"""Frozen feature tables: build, freeze, reuse, verify and tamper detection, on synthetic stores."""
import json
import os
import stat

import numpy as np
import pandas as pd
import pytest
from features_helpers import block_cell, write_world

from aetherguard.features import build, features_build, features_verify
from aetherguard.features.build import (
    COLUMNS_NAME,
    MANIFEST_NAME,
    REPORT_NAME,
    FeatureInputs,
    FeaturesIntegrityError,
    build_features,
    features_name,
    verify_features,
)
from aetherguard.features.compute import feature_names
from aetherguard.manifest import sha256_file

CFG = {"features": {"climatology": {"split": "train"}, "chunk_rows": 3, "pixel_chunk": 5},
       "splits": {"day_splits": {"train": {"start": "2010-01-01", "end": "2010-12-31"}}}}


def _samples_frame():
    cells = [block_cell(0, 0), block_cell(4, 4), block_cell(9, 2), block_cell(0, 0), block_cell(4, 4), block_cell(2, 2)]
    dates = ["2010-02-20", "2010-07-06", "2011-03-12", "2010-01-10", "2011-08-01", "2013-07-20"]
    frame = pd.DataFrame({"cell_id": np.array(cells, dtype=np.int64),
                          "date": pd.to_datetime(dates).astype("datetime64[ns]"),
                          "split": "train", "region": "himalaya", "label": np.array([1, 0, 0, 1, 0, 0], dtype=np.int8),
                          "kind": ["positive", "negative", "negative", "positive", "negative", "negative"],
                          "terrain_source": "own"})
    frame["terrain_cell_id"] = pd.array(cells, dtype="Int64")
    frame["in_domain"] = True
    frame["rain_ok"] = [True, True, True, False, True, True]
    return frame


def _universe_frame():
    return pd.DataFrame({"cell_id": np.array([block_cell(1, 1), block_cell(7, 7)], dtype=np.int64),
                         "date": pd.to_datetime(["2011-05-05", "2010-09-09"]).astype("datetime64[ns]"),
                         "split": "train", "region": "himalaya", "kind": "universe", "weight": [10.0, 10.0],
                         "universe_size": np.array([20, 20]), "in_buffer": [False, True],
                         "is_positive_cell_day": [False, False]})


@pytest.fixture
def out_dir(tmp_path):
    out = tmp_path / "features"
    yield out
    if out.exists():
        for path in out.rglob("*"):
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)


@pytest.fixture
def inputs(tmp_path):
    paths = write_world(tmp_path / "world")
    samples_dir = tmp_path / "samples"
    samples_dir.mkdir()
    files = {"train_samples.parquet": _samples_frame(), "universe_train.parquet": _universe_frame()}
    manifest = {"files": {}}
    for name, frame in files.items():
        frame.to_parquet(samples_dir / name, index=False)
        manifest["files"][name] = {"sha256": sha256_file(samples_dir / name), "n_rows": len(frame)}
    (samples_dir / "samples_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return FeatureInputs(samples_dir, paths["terrain"], paths["imd"], paths["chirps"], paths["power"])


@pytest.fixture
def built(inputs, out_dir):
    manifest, reused = build_features(inputs, out_dir, cfg=CFG)
    assert not reused
    return out_dir, manifest


def make_writable(path):
    os.chmod(path, stat.S_IWRITE | stat.S_IREAD)


def test_every_sample_file_gets_a_matching_features_file_with_identical_rows_and_order(built, inputs):
    out_dir, manifest = built
    for sample in ("train_samples.parquet", "universe_train.parquet"):
        samples = pd.read_parquet(inputs.samples_dir / sample)
        table = pd.read_parquet(out_dir / features_name(sample))
        assert features_name(sample) == sample.replace(".parquet", "_features.parquet")
        assert list(table.columns[:len(samples.columns)]) == list(samples.columns)
        pd.testing.assert_frame_equal(table[list(samples.columns)], samples)
        for column in [c for names in feature_names().values() for c in names]:
            assert table[column].dtype == np.float32
        assert {"lat", "lon", "month", "rain_source"} <= set(table.columns)
    assert manifest["files"][features_name("train_samples.parquet")]["n_rows"] == 6


def test_feature_columns_json_maps_every_column_to_a_group_with_meta_for_the_rest(built):
    out_dir, _ = built
    groups = json.loads((out_dir / COLUMNS_NAME).read_text(encoding="utf-8"))
    table = pd.read_parquet(out_dir / features_name("train_samples.parquet"))
    assert set(table.columns) <= set(groups)
    assert {groups[c] for c in table.columns} == {"meta", "rain", "src", "wet", "stat"}
    for column in ("cell_id", "date", "split", "label", "kind", "terrain_source", "in_domain", "rain_ok", "lat", "lon",
                   "month", "rain_source"):
        assert groups[column] == "meta"
    assert groups["rain_acc_3"] == "rain" and groups["src_dis_diff_1"] == "src"
    assert groups["wet_top"] == "wet" and groups["stat_slope_mean"] == "stat"
    assert "weight" in groups and groups["weight"] == "meta"


def test_report_has_rows_nan_shares_by_kind_sources_rain_ok_reasons_and_runtime(built):
    out_dir, manifest = built
    report = json.loads((out_dir / REPORT_NAME).read_text(encoding="utf-8"))
    entry = report["files"][features_name("train_samples.parquet")]
    assert entry["rows"] == 6 and set(entry["by_kind"]) == {"positive", "negative"}
    assert set(entry["nan_share"]) == {"rain", "src", "wet", "stat"}
    assert 0.0 <= entry["nan_share"]["rain"]["mean_column_nan_share"] <= 1.0
    assert sum(entry["rain_source"].values()) == 6
    bad = entry["rain_ok_false"]
    assert bad["rows"] == 1 and bad["source_but_30_day_window_incomplete"] == 1 and bad["by_split"] == {"train": 1}
    assert "by_kind" in report["files"][features_name("universe_train.parquet")]
    assert report["seconds"]["total"] >= 0 and report["source_usage"]["imd"]["days_outside_store"] >= 0
    assert manifest["runtime_seconds"] == report["seconds"]["total"]
    assert set(manifest["inputs"]) == {"samples_manifest", "terrain", "imd_index", "chirps_index", "power"}


def test_files_are_read_only_and_checksums_match(built):
    out_dir, manifest = built
    for name, entry in manifest["files"].items():
        assert sha256_file(out_dir / name) == entry["sha256"]
        assert not os.access(out_dir / name, os.W_OK)
    assert not os.access(out_dir / MANIFEST_NAME, os.W_OK)


def test_features_that_exist_are_used_and_the_gap_rows_are_explicit(built):
    out_dir, _ = built
    table = pd.read_parquet(out_dir / features_name("train_samples.parquet"))
    assert table.loc[0, "rain_source"] == "imd" and np.isfinite(table.loc[0, "rain_acc_7"])
    assert np.isnan(table.loc[3, "rain_acc_30"])        # 2010-01-10: the 30-day look-back starts before the store
    assert table.loc[5, "rain_source"] == "chirps_aligned"   # 2013-07-20: no IMD year, CHIRPS 2013 range


def test_second_build_verifies_and_reuses_without_rewriting(built, inputs):
    out_dir, first = built
    stamps = {p.name: p.stat().st_mtime_ns for p in out_dir.iterdir()}
    manifest, reused = build_features(inputs, out_dir, cfg=CFG)
    assert reused and manifest == first
    assert {p.name: p.stat().st_mtime_ns for p in out_dir.iterdir()} == stamps


def test_force_rebuild_is_deterministic(built, inputs):
    out_dir, first = built
    manifest, reused = build_features(inputs, out_dir, force=True, cfg=CFG)
    assert not reused
    for name in first["files"]:
        if name != REPORT_NAME:    # the report records timings
            assert manifest["files"][name]["sha256"] == first["files"][name]["sha256"]


def test_verify_passes_and_detects_a_tampered_file_and_blocks_reuse(built, inputs):
    out_dir, _ = built
    assert verify_features(out_dir, inputs, CFG) == {"ok": True, "problems": []}
    target = out_dir / features_name("train_samples.parquet")
    make_writable(target)
    target.write_bytes(target.read_bytes() + b"x")
    result = verify_features(out_dir, inputs, CFG)
    assert not result["ok"] and any("checksum mismatch" in p for p in result["problems"])
    with pytest.raises(FeaturesIntegrityError, match="force=True"):
        build_features(inputs, out_dir, cfg=CFG)


def test_verify_detects_missing_file_changed_input_and_changed_config(built, inputs):
    out_dir, _ = built
    changed = json.loads(json.dumps(CFG))
    changed["features"]["chunk_rows"] = 7
    assert any("configuration changed" in p for p in verify_features(out_dir, inputs, changed)["problems"])
    pd.read_parquet(inputs.terrain).iloc[:50].to_parquet(inputs.terrain, index=False)
    assert any("input changed" in p for p in verify_features(out_dir, inputs, CFG)["problems"])
    make_writable(out_dir / COLUMNS_NAME)
    (out_dir / COLUMNS_NAME).unlink()
    assert any(f"missing: {COLUMNS_NAME}" in p for p in verify_features(out_dir)["problems"])


def test_verify_detects_rows_that_no_longer_match_the_samples_and_non_float32_features(built, inputs):
    out_dir, manifest = built
    name = features_name("train_samples.parquet")
    table = pd.read_parquet(out_dir / name)
    table = table.iloc[::-1].reset_index(drop=True)
    make_writable(out_dir / name)
    table.to_parquet(out_dir / name, index=False)
    manifest["files"][name]["sha256"] = sha256_file(out_dir / name)
    make_writable(out_dir / MANIFEST_NAME)
    (out_dir / MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")
    assert any("row order differ" in p for p in verify_features(out_dir, inputs, CFG)["problems"])
    table["rain_acc_1"] = table["rain_acc_1"].astype("float64")
    table.to_parquet(out_dir / name, index=False)
    manifest["files"][name]["sha256"] = sha256_file(out_dir / name)
    (out_dir / MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")
    assert any("not float32" in p for p in verify_features(out_dir, inputs, CFG)["problems"])


def test_missing_samples_manifest_and_corrupted_samples_are_errors(inputs, out_dir, tmp_path):
    (inputs.samples_dir / "train_samples.parquet").write_bytes(b"junk")
    with pytest.raises(FeaturesIntegrityError, match="does not match"):
        build_features(inputs, out_dir, cfg=CFG)
    (inputs.samples_dir / "samples_manifest.json").unlink()
    with pytest.raises(FileNotFoundError, match="samples_manifest.json"):
        build_features(inputs, out_dir, cfg=CFG)
    with pytest.raises(FileNotFoundError):
        verify_features(tmp_path / "nowhere")


def test_cli_build_then_verify(inputs, out_dir, monkeypatch, capsys):
    for module in (features_build, features_verify):
        monkeypatch.setattr(module, "default_inputs", lambda: inputs)
        monkeypatch.setattr(module, "load_configs", lambda: CFG)
    assert features_build.main(["--out-dir", str(out_dir)]) == 0
    assert "built and frozen" in capsys.readouterr().out
    assert features_build.main(["--out-dir", str(out_dir)]) == 0
    assert "reused" in capsys.readouterr().out
    assert features_verify.main(["--out-dir", str(out_dir)]) == 0
    assert capsys.readouterr().out.startswith("OK")
    target = out_dir / features_name("universe_train.parquet")
    make_writable(target)
    target.write_bytes(b"junk")
    assert features_verify.main(["--out-dir", str(out_dir)]) == 1
    assert features_build.main(["--out-dir", str(out_dir)]) == 1
    assert features_verify.main(["--out-dir", str(out_dir / "none")]) == 1


def test_default_inputs_point_at_the_processed_tree():
    inputs = build.default_inputs()
    assert inputs.samples_dir.name == "samples" and inputs.power_npz.name == "power_wetness.npz"
