"""Frozen leave-station-out train / val / test split for the integrity engine.

Method: stations are grouped into strata (region | upland-or-lowland | eligible), each stratum is
shuffled with a seeded numpy Generator, and the stations are dealt to train, train, val, train,
test in turn (60 / 20 / 20), the dealing position carrying on across strata so the global counts
stay at 60 / 20 / 20. `eligible` (optional meta column: the station has clean days to inject
faults into) is a stratum so every split can be evaluated. A repair pass then makes sure each
split holds at least one upland-or-Nepal station and at least one eligible station whenever the
group has three or more members ("where possible"). The result is written once to
`data/processed/integrity/station_splits.json`, made read-only, and REUSED by every later call.
"""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import numpy as np
import pandas as pd

from .common import integrity_dir

SPLIT_SEED = 20260930
SPLIT_NAMES = ("train", "val", "test")
_DEAL = ("train", "train", "val", "train", "test")
_MIN_GROUP_TO_SPREAD = 3
METHOD = ("strata = region|upland-or-lowland|eligible; seeded shuffle within stratum; deal "
          "train,train,val,train,test; repair so each split has an upland-or-Nepal and an eligible station")


def default_path() -> Path:
    return integrity_dir() / "station_splits.json"


def _flags(meta: pd.DataFrame) -> tuple[pd.Series, pd.Series | None]:
    highland = meta["upland"].astype(bool) | meta["country"].eq("NP")
    eligible = meta["eligible"].astype(bool) if "eligible" in meta.columns else None
    return highland.set_axis(meta["id"]), None if eligible is None else eligible.set_axis(meta["id"])


def _assign(meta: pd.DataFrame, seed: int) -> dict[str, str]:
    meta = meta.sort_values("id").reset_index(drop=True)
    highland, eligible = _flags(meta)
    region = meta["region"].replace("", "outside_domain").fillna("outside_domain")
    stratum = region + "|" + np.where(highland.to_numpy(), "highland", "lowland")
    if eligible is not None:
        stratum = stratum + "|" + np.where(eligible.to_numpy(), "eligible", "ineligible")
    rng = np.random.default_rng(seed)
    owner: dict[str, str] = {}
    position = 0
    for key in sorted(set(stratum)):
        ids = meta.loc[(stratum == key).to_numpy(), "id"].to_numpy()
        for sid in rng.permutation(ids):
            owner[str(sid)] = _DEAL[position % len(_DEAL)]
            position += 1
    for flag in [highland] + ([eligible] if eligible is not None else []):
        _spread(owner, flag)
    return owner


def _spread(owner: dict[str, str], flag: pd.Series) -> None:
    """Swap members of `flag` into splits that have none (keeps split sizes unchanged)."""
    members = [sid for sid in sorted(owner) if flag[sid]]
    if len(members) < _MIN_GROUP_TO_SPREAD:
        return
    for needy in SPLIT_NAMES:
        if any(owner[s] == needy for s in members):
            continue
        donors = {name: [s for s in members if owner[s] == name] for name in SPLIT_NAMES}
        donor = max(SPLIT_NAMES, key=lambda name: len(donors[name]))
        outsiders = [s for s in sorted(owner) if owner[s] == needy and not flag[s]]
        if len(donors[donor]) < 2 or not outsiders:
            continue
        give, take = donors[donor][0], outsiders[0]
        owner[give], owner[take] = needy, donor
        members = [sid for sid in sorted(owner) if flag[sid]]


def _summary(meta: pd.DataFrame, ids: list[str]) -> dict:
    sub = meta[meta["id"].isin(ids)]
    highland, eligible = _flags(sub)
    out = {"stations": len(ids), "upland_or_nepal": int(highland.sum()),
           "nepal": int(sub["country"].eq("NP").sum()),
           "by_region": {str(k) or "outside_domain": int(v) for k, v in sub["region"].value_counts().items()}}
    if eligible is not None:
        out["eligible"] = int(eligible.sum())
    return out


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    path.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    os.chmod(path, stat.S_IREAD)


def make_station_splits(meta: pd.DataFrame, seed: int, path=None, force: bool = False) -> dict[str, list[str]]:
    """{"train": [...], "val": [...], "test": [...]} (sorted station ids).

    `meta` needs id, country, upland, region and optionally a boolean `eligible`. The first call
    writes the frozen file (`path`, default data/processed/integrity/station_splits.json); later
    calls read it and never regenerate: a different seed or station set raises ValueError unless
    `force=True` rebuilds (and overwrites) it."""
    path = Path(path) if path is not None else default_path()
    ids = sorted(meta["id"])
    if path.is_file() and not force:
        stored = json.loads(path.read_text(encoding="utf-8"))
        if stored["seed"] != seed:
            raise ValueError(f"{path.name} was built with seed {stored['seed']}, not {seed}; "
                             "pass force=True to rebuild it")
        listed = sorted(sum((stored[name] for name in SPLIT_NAMES), []))
        if listed != ids:
            raise ValueError(f"the station set differs from the one frozen in {path.name}; "
                             "pass force=True to rebuild it")
        return {name: list(stored[name]) for name in SPLIT_NAMES}
    owner = _assign(meta, seed)
    result = {name: sorted(s for s, o in owner.items() if o == name) for name in SPLIT_NAMES}
    _write(path, {"seed": seed, "method": METHOD,
                  "counts": {name: _summary(meta, result[name]) for name in SPLIT_NAMES}, **result})
    return result
