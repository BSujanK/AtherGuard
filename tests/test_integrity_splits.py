import json
import os
import stat

import numpy as np
import pandas as pd
import pytest

from aetherguard.integrity import splits


@pytest.fixture(autouse=True)
def writable_on_teardown(isolated_data_root):
    """The split file is read-only once frozen; restore write permission so tmp_path can be removed."""
    yield
    for path in isolated_data_root.rglob("*.json"):
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)


def make_meta(n=60, n_upland=12, n_np=2, eligible_share=0.4, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for k in range(n):
        upland = k < n_upland
        country = "NP" if k < n_np else "IN"
        rows.append({"id": f"{country}{k:09d}", "country": country, "upland": upland,
                     "region": ["himalaya", "western_ghats", ""][k % 3],
                     "eligible": bool(rng.random() < eligible_share)})
    return pd.DataFrame(rows)


def test_splits_are_disjoint_cover_all_stations_and_are_about_60_20_20():
    meta = make_meta()
    out = splits.make_station_splits(meta, seed=5)
    assert set(out) == {"train", "val", "test"}
    everyone = out["train"] + out["val"] + out["test"]
    assert sorted(everyone) == sorted(meta["id"]) and len(set(everyone)) == len(meta)
    n = len(meta)
    assert abs(len(out["train"]) - 0.6 * n) <= 2 and abs(len(out["val"]) - 0.2 * n) <= 2
    assert abs(len(out["test"]) - 0.2 * n) <= 2
    for ids in out.values():
        assert ids == sorted(ids)


def test_every_split_has_upland_lowland_and_eligible_stations():
    meta = make_meta()
    out = splits.make_station_splits(meta, seed=5)
    info = meta.set_index("id")
    for name, ids in out.items():
        sub = info.loc[ids]
        assert sub["upland"].any() and (~sub["upland"]).any()
        assert sub["eligible"].any()


def test_deterministic_for_a_seed_and_different_for_another():
    meta = make_meta()
    a = splits.make_station_splits(meta, seed=5, path=None, force=True)
    b = splits.make_station_splits(meta, seed=5, force=True)
    assert a == b
    c = splits.make_station_splits(meta, seed=6, force=True)
    assert c != a


def test_input_row_order_does_not_change_the_result():
    meta = make_meta()
    a = splits.make_station_splits(meta, seed=5, force=True)
    b = splits.make_station_splits(meta.sample(frac=1.0, random_state=1), seed=5, force=True)
    assert a == b


def test_file_is_written_once_and_reused_never_regenerated(isolated_data_root, monkeypatch):
    meta = make_meta()
    first = splits.make_station_splits(meta, seed=5)
    path = isolated_data_root / "processed" / "integrity" / "station_splits.json"
    assert path.is_file() and not os.access(path, os.W_OK)  # frozen
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["seed"] == 5 and stored["train"] == first["train"]

    def boom(*args, **kwargs):
        raise AssertionError("the split must be read from the file, not recomputed")
    monkeypatch.setattr(splits, "_assign", boom)
    assert splits.make_station_splits(meta, seed=5) == first


def test_reuse_refuses_a_different_seed_or_a_different_station_set():
    meta = make_meta()
    splits.make_station_splits(meta, seed=5)
    with pytest.raises(ValueError, match="seed"):
        splits.make_station_splits(meta, seed=6)
    with pytest.raises(ValueError, match="station"):
        splits.make_station_splits(make_meta(n=61), seed=5)


def test_force_rebuilds_the_frozen_file(isolated_data_root):
    meta = make_meta()
    splits.make_station_splits(meta, seed=5)
    rebuilt = splits.make_station_splits(meta, seed=6, force=True)
    stored = json.loads((isolated_data_root / "processed" / "integrity" / "station_splits.json").read_text())
    assert stored["seed"] == 6 and stored["test"] == rebuilt["test"]


def test_explicit_path_is_honoured(tmp_path):
    target = tmp_path / "elsewhere" / "s.json"
    splits.make_station_splits(make_meta(), seed=1, path=target)
    assert target.is_file()
    os.chmod(target, stat.S_IWRITE | stat.S_IREAD)


def test_works_without_an_eligibility_column():
    meta = make_meta().drop(columns="eligible")
    out = splits.make_station_splits(meta, seed=2, force=True)
    assert sum(len(v) for v in out.values()) == len(meta)


def test_small_upland_group_is_spread_where_possible():
    meta = make_meta(n=40, n_upland=3, n_np=0)
    out = splits.make_station_splits(meta, seed=9, force=True)
    info = meta.set_index("id")
    assert all(info.loc[ids]["upland"].any() for ids in out.values())


def test_stored_file_carries_counts_for_the_report(isolated_data_root):
    splits.make_station_splits(make_meta(), seed=5)
    stored = json.loads((isolated_data_root / "processed" / "integrity" / "station_splits.json").read_text())
    assert {"seed", "method", "counts", "train", "val", "test"} <= set(stored)
    assert stored["counts"]["train"]["stations"] == len(stored["train"])
