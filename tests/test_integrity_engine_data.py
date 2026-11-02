import json

import numpy as np
import pandas as pd
import pytest
from integrity_helpers import synthetic_raw_years, synthetic_set, write_toy_rain_store

from aetherguard.integrity import baseline_report as br
from aetherguard.integrity import engine_data, grids, inject, neighbours


def rain(n, seed):
    rng = np.random.default_rng(seed)
    return np.where(rng.random(n) < 0.45, np.round(rng.gamma(0.8, 9.0, n) + 1.0, 1), 0.0)


def make_set(n_stations=8, start="2003-01-01", n=365 * 12 + 3):
    sset = synthetic_set({f"IN{k:09d}": rain(n, k) for k in range(n_stations)}, start=start)
    ids = list(sset.meta["id"])
    return sset, {"train": ids[:5], "val": ids[5:6], "test": ids[6:]}


def test_engine_dataset_is_restricted_to_the_engine_period_with_the_same_splits():
    sset, splits = make_set()                      # data from 2003; the engine period starts 2007
    table, info = engine_data.build_engine_dataset(sset, splits, None)
    assert table["date"].min() == pd.Timestamp(engine_data.ENGINE_PERIOD[0])
    assert table["date"].max() <= pd.Timestamp(engine_data.ENGINE_PERIOD[1])
    owner = {sid: s for s, ids in splits.items() for sid in ids}
    assert (table.drop_duplicates("station").set_index(table["station"].astype(str)[table.drop_duplicates("station").index])
            ["split"].astype(str).to_dict() == owner)
    assert info["chosen"] in {label for label, *_ in engine_data.LADDER}
    assert {"attempts", "min_valid_days", "density", "unresolved_shortfalls"} <= set(info)


def test_episodes_in_the_engine_dataset_do_not_overlap_or_leave_clean_days():
    sset, splits = make_set()
    table, _ = engine_data.build_engine_dataset(sset, splits, None)
    inside = table["episode_id"] >= 0
    assert inside.any() and table.loc[inside, "clean_real"].all()
    for station in table["station"].unique():
        ep = table[(table["station"] == station) & inside].groupby("episode_id", observed=True)["date"].agg(["min", "max"])
        ep = ep.sort_values("min")
        gaps = (ep["min"].iloc[1:].to_numpy() - ep["max"].iloc[:-1].to_numpy()) / np.timedelta64(1, "D") - 1
        assert (gaps >= 5).all()


def test_relaxation_ladder_stops_at_the_first_rung_without_a_shortfall(monkeypatch):
    sset, splits = make_set()
    monkeypatch.setattr(engine_data, "MIN_TEST_EPISODES", 1)
    monkeypatch.setattr(engine_data, "MIN_TRAIN_EPISODES", 1)
    _, info = engine_data.build_engine_dataset(sset, splits, None)
    assert info["chosen"] == "base" and len(info["attempts"]) == 1 and info["unresolved_shortfalls"] == []


def test_relaxation_ladder_relaxes_in_order_then_reports_the_shortfall(monkeypatch):
    sset, splits = make_set()
    monkeypatch.setattr(engine_data, "MIN_TEST_EPISODES", 10_000)
    table, info = engine_data.build_engine_dataset(sset, splits, None)
    assert [a["label"] for a in info["attempts"]] == [
        "base", "min_valid_days_150", "min_valid_days_150_density_0.15"]
    assert [(a["min_valid_days"], a["density"]) for a in info["attempts"]] == [(200, 0.08), (150, 0.08), (150, 0.15)]
    assert info["chosen"] == "min_valid_days_150_density_0.15"
    assert info["unresolved_shortfalls"] and all(s["episodes"] < 10_000 for s in info["unresolved_shortfalls"])
    assert info["attempts"][0]["clean_real_days"] <= info["attempts"][1]["clean_real_days"]
    assert len(table) > 0


def test_shortfall_rule_uses_15_test_and_40_train_episodes():
    assert (engine_data.MIN_TEST_EPISODES, engine_data.MIN_TRAIN_EPISODES) == (15, 40)
    report = {"splits": {s: {"by_type": {t: {"episodes": n} for t in inject.FAULT_TYPES}}
                         for s, n in (("train", 39), ("val", 0), ("test", 15))}}
    short = engine_data.episode_shortfalls(report)
    assert {(x["split"], x["fault_type"]) for x in short} == {("train", t) for t in inject.FAULT_TYPES}


def test_reference_coverage_counts_clean_days_with_each_reference():
    sset, splits = make_set(n_stations=4, start="2007-01-01", n=365 * 3)
    splits = {"train": list(sset.meta["id"][:2]), "val": list(sset.meta["id"][2:3]), "test": list(sset.meta["id"][3:])}
    table = inject.build_fault_dataset(sset, splits, seed=1)
    index = sset.values.index
    cols = list(sset.values.columns)
    frames = {n: pd.DataFrame(np.nan, index=index, columns=cols, dtype=np.float32) for n in grids.SOURCES}
    frames["imd"].iloc[:365, :] = 1.0                       # IMD only in year one
    frames["chirps_aligned"].iloc[:, 0] = 1.0               # CHIRPS only at the first station
    refs = grids.GridRefs(frames)
    wide = neighbours.neighbour_table(sset.meta, k=10, max_km=300)
    cov = engine_data.reference_coverage(table, refs, wide)
    assert set(cov) == {"train", "val", "test"}
    for split in cov.values():
        assert split["any_reference"]["days"] >= max(split["imd"]["days"], split["chirps_aligned"]["days"])
        assert split["imd"]["days"] <= split["clean_real_days"]
    clean_train = table[(table["split"] == "train") & table["clean_real"]]
    assert cov["train"]["imd"]["days"] == int((clean_train["date"] < index[365]).sum())
    assert cov["train"]["chirps_aligned"]["days"] == int((clean_train["station"].astype(str) == cols[0]).sum())
    assert cov["test"]["chirps_aligned"]["days"] == 0


def test_end_to_end_run_writes_dataset_refs_features_and_reports(tmp_path, isolated_data_root):
    raw = synthetic_raw_years(tmp_path)
    write_toy_rain_store(isolated_data_root / "processed" / "rain")
    br.prepare(raw)                                          # writes the frozen splits (and the 1990 dataset)
    splits_file = isolated_data_root / "processed" / "integrity" / "station_splits.json"
    stamp = splits_file.stat().st_mtime_ns
    report = engine_data.run(raw)
    integrity = isolated_data_root / "processed" / "integrity"
    for name in (engine_data.ENGINE_DATASET_NAME, engine_data.ENGINE_REPORT_NAME, engine_data.REFS_CACHE_NAME,
                 engine_data.FEATURES_NAME, engine_data.FEATURES_REPORT_NAME):
        assert (integrity / name).is_file(), name
    assert splits_file.stat().st_mtime_ns == stamp           # the frozen split was not regenerated
    json.loads((integrity / engine_data.ENGINE_REPORT_NAME).read_text(encoding="utf-8"),
               parse_constant=lambda c: pytest.fail(c))
    feats = pd.read_parquet(integrity / engine_data.FEATURES_NAME)
    table = pd.read_parquet(integrity / engine_data.ENGINE_DATASET_NAME)
    assert len(feats) == len(table) and report["features"]["rows"] == len(feats)
    assert feats["date"].min() >= pd.Timestamp(engine_data.ENGINE_PERIOD[0])
    cov = report["reference_coverage_clean_days"]
    assert all(c["imd"]["days"] > 0 and c["any_reference"]["days"] >= c["imd"]["days"] for c in cov.values())
    assert report["reference_coverage_all_station_days"]["imd"]["share"] > 0
    again = engine_data.run(raw)                              # reuses the dataset and the refs cache
    assert again["build"] == report["build"]
    assert again["dataset"] == report["dataset"]


@pytest.mark.realdata
def test_real_engine_dataset_invariants():
    from aetherguard.integrity.common import integrity_dir
    out = integrity_dir()
    table = pd.read_parquet(out / engine_data.ENGINE_DATASET_NAME)
    frozen = json.loads((out / "station_splits.json").read_text(encoding="utf-8"))
    owner = {sid: s for s in ("train", "val", "test") for sid in frozen[s]}
    assert table["date"].min() >= pd.Timestamp(engine_data.ENGINE_PERIOD[0])
    assert table["date"].max() <= pd.Timestamp(engine_data.ENGINE_PERIOD[1])
    pairs = table[["station", "split"]].astype(str).drop_duplicates()
    assert pairs["station"].is_unique                                  # one split per station
    assert dict(zip(pairs["station"], pairs["split"])) == owner        # the frozen splits
    inside = table["episode_id"] >= 0
    assert table.loc[inside, "clean_real"].all()
    feats = pd.read_parquet(out / engine_data.FEATURES_NAME, columns=["station", "date"])
    assert len(feats) == len(table)
    report = json.loads((out / engine_data.ENGINE_REPORT_NAME).read_text(encoding="utf-8"))
    assert report["reference_coverage_clean_days"]["test"]["any_reference"]["days"] > 0
