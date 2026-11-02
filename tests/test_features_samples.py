"""Frozen sample tables: build, freeze, reuse, verify and the integrity invariants, on a synthetic world."""
import copy
import json
import os
import stat

import numpy as np
import pandas as pd
import pytest

from aetherguard.features import samples
from aetherguard.features.sampling import EventBuffer, SamplingError
from aetherguard.features.samples import (
    MANIFEST_NAME,
    SampleInputs,
    SamplesIntegrityError,
    build_samples,
    load_configs,
    sample_name,
    universe_name,
    verify_samples,
)
from aetherguard.grid import ID_STRIDE, cell_center
from aetherguard.manifest import sha256_file

HIM = (2349, 5370)   # (lat_index, lon_index) of the himalaya block corner
GHT = (1970, 5150)
SIDE = 20


def cid(lat_index, lon_index):
    return lat_index * ID_STRIDE + lon_index


def block(origin):
    return [cid(origin[0] + i, origin[1] + j) for i in range(SIDE) for j in range(SIDE)]


@pytest.fixture
def samples_out_dir(tmp_path):
    out = tmp_path / "samples"
    yield out
    if out.exists():
        for path in out.rglob("*"):
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)


def _positive(cell, date, split, region):
    return {"cell_id": cell, "event_date": pd.Timestamp(date), "region": region, "country_code": "IN",
            "n_events": 1, "sources": "hma", "min_accuracy_km": 1.0, "max_accuracy_km": 1.0, "split": split,
            "case_study": None}


@pytest.fixture
def world(tmp_path):
    him, ght = block(HIM), block(GHT)
    ids = him + ght
    lat, lon = cell_center(np.array(ids))
    terrain = pd.DataFrame({"cell_id": ids, "lat": lat, "lon": lon,
                            "region_box": ["himalaya"] * len(him) + ["western_ghats"] * len(ght),
                            "slope_mean": [1.0 + (i * 7) % 30 for i in range(len(ids))]})
    regions = pd.DataFrame({"cell_id": ids, "country_code": "IN",
                            "region": ["himalaya"] * len(him) + ["western_ghats"] * len(ght)})
    off_block = cid(HIM[0] + SIDE, HIM[1] + 3)      # one row north of the block: nearest_land
    far = cid(2500, 5000)                            # nothing within 3 cells: none
    rows = []
    for k, d in enumerate(["2010-06-15", "2010-07-02", "2010-07-20", "2011-08-05", "2012-07-09", "2013-09-01"]):
        rows.append(_positive(him[k * 17], d, "train", "himalaya"))
    for k, d in enumerate(["2010-07-05", "2011-07-11", "2012-08-02", "2014-06-30"]):
        rows.append(_positive(ght[k * 23], d, "train", "western_ghats"))
    rows.append(_positive(off_block, "2012-07-30", "train", "himalaya"))
    rows.append(_positive(far, "2012-07-31", "train", "himalaya"))
    for k, d in enumerate(["2016-07-04", "2016-08-19", "2017-07-12"]):
        rows.append(_positive(him[100 + k * 5], d, "validation", "himalaya"))
    for k, d in enumerate(["2016-07-09", "2017-08-15"]):
        rows.append(_positive(ght[100 + k * 5], d, "validation", "western_ghats"))
    for k, d in enumerate(["2018-06-20", "2018-07-14", "2018-09-02"]):
        rows.append(_positive(him[200 + k * 5], d, "test_2018", "himalaya"))
    for k, d in enumerate(["2018-08-09", "2018-08-10", "2018-08-16"]):
        rows.append(_positive(ght[200 + k * 5], d, "test_2018", "western_ghats"))
    rows.append(_positive(him[300], "2023-07-01", "test_sparse", "himalaya"))
    positives = pd.DataFrame(rows)
    positives["event_date"] = positives["event_date"].astype("datetime64[ns]")
    other = pd.DataFrame({
        "cell_id": pd.array([him[50], ght[60], pd.NA, him[70]], dtype="Int64"),
        "event_date": pd.to_datetime(["2010-07-10", "2016-07-20", "2012-01-01", None]),
    })
    events = pd.concat([positives[["cell_id", "event_date"]].astype({"cell_id": "Int64"}), other], ignore_index=True)
    windows = pd.DataFrame({"cell_id": [him[210], him[211]], "window_start": pd.Timestamp("2023-06-16"),
                            "window_end": pd.Timestamp("2023-07-31"), "region": "himalaya"})
    paths = {"terrain": tmp_path / "terrain.parquet", "regions": tmp_path / "regions.parquet",
             "positives": tmp_path / "positives.parquet", "windows": tmp_path / "windows.parquet",
             "events": tmp_path / "events.parquet"}
    for key, frame in (("terrain", terrain), ("regions", regions), ("positives", positives), ("windows", windows),
                       ("events", events)):
        frame.to_parquet(paths[key], index=False)
    return SampleInputs(**paths)


@pytest.fixture
def cfg():
    out = copy.deepcopy(load_configs())
    out["samples"]["universe"]["n_per_region"] = 300
    out["samples"]["window_2023"]["control_n"] = 20
    lat, lon = cell_center(np.array([cid(GHT[0] + 2, GHT[1] + 2), cid(GHT[0] + 9, GHT[1] + 9)]))
    out["samples"]["case_studies"]["wayanad_2024"].update(
        lat_min=float(lat[0]) - 0.01, lat_max=float(lat[1]) + 0.01, lon_min=float(lon[0]) - 0.01,
        lon_max=float(lon[1]) + 0.01)
    return out


@pytest.fixture
def built(world, cfg, samples_out_dir):
    manifest, reused = build_samples(world, samples_out_dir, cfg=cfg)
    assert not reused
    return samples_out_dir, manifest


def read(out_dir, name):
    return pd.read_parquet(out_dir / name)


def test_build_writes_every_table_and_a_manifest_with_checksums(built, cfg):
    out_dir, manifest = built
    assert set(manifest["files"]) == set(samples.output_names(cfg))
    for name, entry in manifest["files"].items():
        assert sha256_file(out_dir / name) == entry["sha256"]
        assert len(read(out_dir, name)) == entry["n_rows"]
    assert manifest["seed"] == cfg["samples"]["seed"] and manifest["frozen"] is True
    assert manifest["slope_floor"] == manifest["report"]["slope_floor"]["floor"]
    assert set(manifest["inputs"]) == {"terrain", "regions", "positives", "windows", "events"}


def test_files_are_read_only_after_build(built):
    out_dir, _ = built
    for path in out_dir.iterdir():
        assert not os.access(path, os.W_OK)


def test_positives_are_present_exactly_once_with_terrain_source_and_flags(built, world):
    out_dir, _ = built
    positives = pd.read_parquet(world.positives)
    for split in ("train", "validation", "test_2018"):
        frame = read(out_dir, sample_name(split))
        stored = frame[frame["kind"] == "positive"]
        expected = positives[positives["split"] == split]
        assert len(stored) == len(expected) and not stored.duplicated(["cell_id", "date"]).any()
        assert set(zip(stored["cell_id"], stored["date"])) == set(zip(expected["cell_id"], expected["event_date"]))
        assert (stored["label"] == 1).all()
    train = read(out_dir, sample_name("train"))
    train_pos = train[train["kind"] == "positive"].set_index("cell_id")
    off_block = cid(HIM[0] + SIDE, HIM[1] + 3)
    assert train_pos.loc[off_block, "terrain_source"] == "nearest_land"
    assert train_pos.loc[off_block, "terrain_cell_id"] != off_block
    assert train_pos.loc[cid(2500, 5000), "terrain_source"] == "none"
    assert pd.isna(train_pos.loc[cid(2500, 5000), "terrain_cell_id"]) and not train_pos.loc[cid(2500, 5000), "in_domain"]


def test_negatives_are_ten_times_positives_per_split_and_region(built):
    out_dir, manifest = built
    for split in ("train", "validation", "test_2018"):
        frame = read(out_dir, sample_name(split))
        for region in ("himalaya", "western_ghats"):
            part = frame[frame["region"] == region]
            n_pos = ((part["kind"] == "positive") & part["terrain_source"].isin(["own", "nearest_land"])).sum()
            assert (part["kind"] == "negative").sum() == 10 * n_pos
            stats = manifest["report"]["negatives"][split][region]
            assert stats["accepted"] == stats["target"] == 10 * n_pos
    train = read(out_dir, sample_name("train"))
    assert ((train["region"] == "himalaya") & (train["kind"] == "negative")).sum() == 10 * 7  # 6 own + 1 nearest_land


def test_negatives_use_only_own_candidate_cells_above_the_floor_and_drawable_dates(built, world):
    out_dir, manifest = built
    terrain = pd.read_parquet(world.terrain).set_index("cell_id")
    floor = manifest["slope_floor"]
    for split in ("train", "validation", "test_2018"):
        frame = read(out_dir, sample_name(split))
        neg = frame[frame["kind"] == "negative"]
        assert (terrain.loc[neg["cell_id"], "slope_mean"].to_numpy() >= floor).all()
        assert (neg["terrain_source"] == "own").all() and neg["in_domain"].all() and neg["rain_ok"].all()
        assert (neg["date"] >= pd.Timestamp("2007-01-31")).all()


def test_no_negative_inside_the_event_buffer(built, world):
    out_dir, _ = built
    positives = pd.read_parquet(world.positives)
    events = pd.read_parquet(world.events)
    pairs = pd.concat([events, positives[["cell_id", "event_date"]].astype({"cell_id": "Int64"})])
    buffer = EventBuffer.from_events(pairs, cells=3, days=3)
    for split in ("train", "validation", "test_2018"):
        frame = read(out_dir, sample_name(split))
        neg = frame[frame["kind"] == "negative"]
        assert not buffer.hits(neg["cell_id"].to_numpy(), neg["date"].to_numpy()).any()


def test_no_cell_date_appears_in_two_splits_and_dates_stay_in_range(built, cfg):
    out_dir, _ = built
    seen = set()
    for split in ("train", "validation", "test_2018"):
        frame = read(out_dir, sample_name(split))
        keys = set(zip(frame["cell_id"], frame["date"]))
        assert not keys & seen
        seen |= keys
        bounds = cfg["splits"]["day_splits"][split]
        assert frame["date"].between(pd.Timestamp(bounds["start"]), pd.Timestamp(bounds["end"])).all()
        assert (frame["split"] == split).all()


def test_universe_has_weights_flags_and_raw_sizes(built, cfg):
    out_dir, manifest = built
    for split in ("train", "validation", "test_2018"):
        frame = read(out_dir, universe_name(split))
        assert not frame.duplicated(["cell_id", "date"]).any()
        for region in ("himalaya", "western_ghats"):
            part = frame[frame["region"] == region]
            entry = manifest["report"]["universe"][split][region]
            assert len(part) == 300 == entry["n_rows"]
            assert (part["universe_size"] == entry["universe_size"]).all()
            assert entry["universe_size"] == entry["n_candidate_cells"] * entry["n_days"]
            assert np.allclose(part["weight"], entry["universe_size"] / 300)
            assert entry["base_rate_per_100k_cell_days"] == pytest.approx(
                entry["positives_in_universe"] / entry["universe_size"] * 1e5)
        assert set(frame["kind"]) == {"universe"}
        bounds = cfg["splits"]["day_splits"][split]
        assert frame["date"].between(pd.Timestamp(bounds["start"]), pd.Timestamp(bounds["end"])).all()
        assert frame["in_buffer"].dtype == bool and frame["is_positive_cell_day"].dtype == bool


def test_train_universe_never_draws_dates_without_lookback(built):
    out_dir, _ = built
    assert read(out_dir, universe_name("train"))["date"].min() >= pd.Timestamp("2007-01-31")


def test_window_set_has_cells_neighbours_and_control_for_every_day(built, world):
    out_dir, manifest = built
    frame = read(out_dir, samples.WINDOW_NAME)
    days = pd.date_range("2023-06-16", "2023-07-31")
    assert len(days) == 46
    cells = frame[frame["kind"] == "window_cell"]
    control = frame[frame["kind"] == "window_control"]
    assert set(cells["date"]) == set(days) == set(control["date"])
    assert control["cell_id"].nunique() == 20 and (control["region"] == "himalaya").all()
    assert not set(control["cell_id"]) & set(cells["cell_id"])
    windows = pd.read_parquet(world.windows)
    assert set(cells.loc[cells["is_window_positive_cell"], "cell_id"]) == set(windows["cell_id"])
    assert not control["is_window_positive_cell"].any()
    assert cells["cell_id"].nunique() == 12  # two horizontally adjacent cells: a 3 x 4 block
    assert manifest["report"]["window_2023"]["n_rows"] == len(frame)


def test_case_studies_are_complete_grids_with_flags(built, world):
    out_dir, manifest = built
    kerala = read(out_dir, samples.CASE_NAMES["kerala_2018"])
    assert set(kerala["kind"]) == {"case_kerala_2018"} and set(kerala["split"]) == {"test_2018"}
    assert kerala["date"].nunique() == 20 and len(kerala) == kerala["cell_id"].nunique() * 20
    assert kerala["slope_ok"].all()
    t18 = read(out_dir, sample_name("test_2018"))
    in_grid = t18[(t18["kind"] == "positive") & (t18["region"] == "western_ghats") & t18["in_domain"]
                  & t18["date"].between("2018-08-01", "2018-08-20")]
    assert len(in_grid) >= 1  # positives below the slope floor are outside the candidate grid by design
    assert kerala["is_positive_cell_day"].sum() == len(in_grid)
    wayanad = read(out_dir, samples.CASE_NAMES["wayanad_2024"])
    assert wayanad["date"].nunique() == 22 and len(wayanad) == wayanad["cell_id"].nunique() * 22
    assert wayanad["cell_id"].nunique() == 8 * 8
    slope = pd.read_parquet(world.terrain).set_index("cell_id")["slope_mean"]
    assert (wayanad["slope_ok"].to_numpy() == (slope.loc[wayanad["cell_id"]].to_numpy() >= manifest["slope_floor"])).all()
    assert set(wayanad["split"]) == {"test_sparse"} and not wayanad["is_positive_cell_day"].any()
    assert manifest["report"]["case_studies"]["wayanad_2024"]["n_cells"] == 64


def test_report_records_floor_domain_counts_and_missing_rain_lookback(built):
    _, manifest = built
    report = manifest["report"]
    assert report["slope_floor"]["n_cells"] == 10 and report["slope_floor"]["reference_split"] == "train"
    assert set(report["slope_floor"]["per_region"]) == {"himalaya", "western_ghats"}
    cand = report["slope_floor"]["candidate_cells"]
    assert cand["after_floor"]["total"] <= cand["before_floor"]["total"] == 800
    train = report["positives"]["train"]
    assert train["cell_days"]["total"] == 12 and train["terrain_own"]["total"] == 10
    assert train["terrain_nearest_land"]["total"] == 1 and train["terrain_none"]["total"] == 1
    assert (train["in_slope_domain"]["total"] + train["below_slope_floor"]["total"]
            + train["terrain_none"]["total"]) == 12
    assert train["no_rain_lookback"]["total"] == 0


def test_second_build_verifies_and_reuses_without_rewriting(built, world, cfg):
    out_dir, first = built
    stamps = {p.name: p.stat().st_mtime_ns for p in out_dir.iterdir()}
    manifest, reused = build_samples(world, out_dir, cfg=cfg)
    assert reused and manifest == first
    assert {p.name: p.stat().st_mtime_ns for p in out_dir.iterdir()} == stamps


def test_force_rebuild_is_byte_identical_for_the_same_inputs(built, world, cfg):
    out_dir, first = built
    manifest, reused = build_samples(world, out_dir, force=True, cfg=cfg)
    assert not reused
    assert {n: e["sha256"] for n, e in manifest["files"].items()} == {n: e["sha256"] for n, e in first["files"].items()}


def make_writable(path):
    os.chmod(path, stat.S_IWRITE | stat.S_IREAD)


def test_tampered_file_is_detected_and_blocks_reuse(built, world, cfg):
    out_dir, _ = built
    target = out_dir / sample_name("train")
    make_writable(target)
    target.write_bytes(target.read_bytes() + b"x")
    result = verify_samples(out_dir, world, cfg)
    assert not result["ok"] and any("checksum mismatch" in p for p in result["problems"])
    with pytest.raises(SamplesIntegrityError, match="force=True"):
        build_samples(world, out_dir, cfg=cfg)


def test_missing_file_and_missing_manifest(built, world, tmp_path):
    out_dir, _ = built
    make_writable(out_dir / samples.WINDOW_NAME)
    (out_dir / samples.WINDOW_NAME).unlink()
    assert any("missing" in p for p in verify_samples(out_dir)["problems"])
    with pytest.raises(FileNotFoundError):
        verify_samples(tmp_path / "nowhere")


def test_changed_input_or_config_is_reported(built, world, cfg):
    out_dir, _ = built
    changed = copy.deepcopy(cfg)
    changed["samples"]["seed"] += 1
    assert any("configuration changed" in p for p in verify_samples(out_dir, world, changed)["problems"])
    pd.read_parquet(world.windows).iloc[:1].to_parquet(world.windows, index=False)
    assert any("input changed" in p for p in verify_samples(out_dir, world, cfg)["problems"])


def test_a_negative_planted_inside_the_buffer_is_caught_by_verify(built, world, cfg):
    out_dir, manifest = built
    train = read(out_dir, sample_name("train"))
    pos = train[train["kind"] == "positive"].iloc[0]
    neg_idx = train.index[train["kind"] == "negative"][0]
    train.loc[neg_idx, ["cell_id", "date"]] = [pos["cell_id"], pos["date"] + pd.Timedelta(days=2)]
    make_writable(out_dir / sample_name("train"))
    train.to_parquet(out_dir / sample_name("train"), index=False)
    manifest["files"][sample_name("train")]["sha256"] = sha256_file(out_dir / sample_name("train"))
    make_writable(out_dir / MANIFEST_NAME)
    (out_dir / MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")
    result = verify_samples(out_dir, world, cfg)
    assert any("inside the event buffer" in p for p in result["problems"])


def test_unreachable_negative_target_fails_loudly(world, cfg, samples_out_dir):
    cfg["samples"]["negatives"]["max_draws_per_negative"] = 0
    with pytest.raises(SamplingError, match="could not draw"):
        build_samples(world, samples_out_dir, cfg=cfg)
    assert not samples_out_dir.exists() or not any(samples_out_dir.iterdir())


def test_cli_build_then_verify(world, cfg, samples_out_dir, monkeypatch, capsys):
    from aetherguard.features import samples_build, samples_verify
    monkeypatch.setattr(samples_build, "default_inputs", lambda: world)
    monkeypatch.setattr(samples_build, "load_configs", lambda: cfg)
    monkeypatch.setattr(samples_verify, "default_inputs", lambda: world)
    monkeypatch.setattr(samples_verify, "load_configs", lambda: cfg)
    assert samples_build.main(["--out-dir", str(samples_out_dir)]) == 0
    assert "built and frozen" in capsys.readouterr().out
    assert samples_build.main(["--out-dir", str(samples_out_dir)]) == 0
    assert "reused" in capsys.readouterr().out
    assert samples_verify.main(["--out-dir", str(samples_out_dir)]) == 0
    assert capsys.readouterr().out.startswith("OK")
    target = samples_out_dir / sample_name("train")
    make_writable(target)
    target.write_bytes(b"junk")
    assert samples_verify.main(["--out-dir", str(samples_out_dir)]) == 1
    assert samples_build.main(["--out-dir", str(samples_out_dir)]) == 1
    assert samples_verify.main(["--out-dir", str(samples_out_dir / "none")]) == 1
