import numpy as np
import pandas as pd
import pytest
from integrity_helpers import make_engine_world

from aetherguard.integrity import features, model, oof

STATIONS = [f"IN{k:09d}" for k in range(23)]
EPISODES = {sid: k % 3 != 0 for k, sid in enumerate(STATIONS)}      # two thirds have episodes


def test_every_station_lands_in_exactly_one_fold_and_folds_are_balanced():
    folds = oof.assign_folds(STATIONS, EPISODES, seed=1, n_folds=5)
    assert set(folds) == set(STATIONS) and set(folds.values()) == set(range(5))
    sizes = np.bincount(list(folds.values()))
    assert sizes.max() - sizes.min() <= 2
    with_ep = np.bincount([f for s, f in folds.items() if EPISODES[s]], minlength=5)
    assert with_ep.min() >= 1 and with_ep.max() - with_ep.min() <= 1       # episode stations are spread over all folds


def test_fold_assignment_is_deterministic_and_seed_dependent():
    a = oof.assign_folds(STATIONS, EPISODES, seed=1)
    assert a == oof.assign_folds(list(reversed(STATIONS)), EPISODES, seed=1)
    assert a != oof.assign_folds(STATIONS, EPISODES, seed=2)


def test_inner_split_is_disjoint_complete_and_draws_validation_from_episode_stations():
    train = [s for s in STATIONS if s not in STATIONS[:5]]
    fit, val = oof.inner_split(train, EPISODES, seed=3)
    assert not set(fit) & set(val) and set(fit) | set(val) == set(train)
    assert val and all(EPISODES[s] for s in val)
    assert fit and (fit, val) == oof.inner_split(train, EPISODES, seed=3)
    with_ep = [s for s in train if EPISODES[s]]
    assert len(val) == max(1, round(0.2 * len(with_ep)))


def test_inner_split_never_takes_the_only_episode_station():
    fit, val = oof.inner_split(["A", "B"], {"A": True, "B": False}, seed=1)
    assert val == [] and set(fit) == {"A", "B"}


def test_run_oof_holds_each_station_out_exactly_once_and_covers_every_station_day(monkeypatch):
    monkeypatch.setattr(model, "MAX_ROUNDS", 20)
    world = make_engine_world(n_stations=9)
    sset, obs = world["sset"], world["obs"]
    feats_real = features.build_features(sset.values, sset.values.index, sset.meta, world["refs"], world["wide"])
    params = {"num_leaves": 7, "min_child_samples": 10}
    real, injected, info = oof.run_oof(world["feats"], world["table"], feats_real, obs, sset.values, world["refs"],
                                       params, seed=5, n_folds=3)
    assert len(info) == 3
    held = [set(f["held_out"]) for f in info]
    assert set().union(*held) == set(world["ids"]) and sum(len(h) for h in held) == len(world["ids"])
    for f in info:
        trained = set(f["fit_station_ids"]) | set(f["inner_val"])
        assert not set(f["held_out"]) & trained                  # no station is both held out and used by its fold
    for frame in (real, injected):
        assert list(frame.columns) == oof.OOF_COLUMNS and len(frame) == sset.values.size
        assert not frame.duplicated(["station", "date"]).any()
        by_station = frame.groupby("station")["fold"].agg(["nunique", "first"])
        assert by_station["nunique"].eq(1).all()
        for f in info:
            assert set(by_station.index[by_station["first"] == f["fold"]]) == set(f["held_out"])
    assert real["trust"].isna().sum() == int(sset.values.isna().to_numpy().sum())
    assert real["trust"].dropna().between(0, 1).all()
