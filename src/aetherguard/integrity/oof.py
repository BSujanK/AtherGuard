"""Out-of-fold engine outputs: 5-fold station-grouped cross-validation over ALL stations.

For each fold the engine is trained on the other folds' stations (frozen-seed fault dataset), with an inner
validation set of 20% of those stations (chosen among stations that have injected episodes) used for early
stopping, calibration, the false-flag threshold tau and the repairer, so nothing about the held-out fold
reaches the model or its thresholds. The held-out stations are then scored twice:

* on the REAL series (no injected faults): `engine_outputs_2007_oof.parquet`, the file the hazard model
  consumes (every station-day 2007-2024; days without a value have NaN trust);
* on the fault-injected series: `engine_outputs_2007_oof_injected.parquet`, used only for the grouped-CV
  supplement metrics.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import model
from .engine import IntegrityEngine, reference_arrays
from .grids import GridRefs

N_FOLDS = 5
FOLD_SEED = 20261005
INNER_VAL_SHARE = 0.2
OOF_COLUMNS = ["station", "date", "trust", "p_fault", "fault_type", "flagged", "genuine_extreme", "repaired",
               "repaired_lo", "repaired_hi", "reasons", "l1_flag", "l1_reason", "fold"]


def assign_folds(station_ids, has_episodes, seed: int = FOLD_SEED, n_folds: int = N_FOLDS) -> dict[str, int]:
    """Station -> fold. Stations with episodes are dealt round-robin first (so every fold can be evaluated),
    then the others, each group shuffled with the seeded Generator; fold sizes differ by at most one per group."""
    rng = np.random.default_rng(seed)
    ids = np.asarray(sorted(station_ids))
    flags = np.asarray([bool(has_episodes[sid]) for sid in ids])
    folds: dict[str, int] = {}
    position = 0
    for group in (ids[flags], ids[~flags]):
        for sid in rng.permutation(group):
            folds[str(sid)] = position % n_folds
            position += 1
    return folds


def inner_split(train_stations, has_episodes, seed: int, share: float = INNER_VAL_SHARE) -> tuple[list, list]:
    """(fit stations, inner-validation stations): `share` of the stations with episodes (at least one, never all)."""
    rng = np.random.default_rng(seed)
    pool = np.asarray(sorted(s for s in train_stations if has_episodes[s]))
    n_val = max(1, int(round(share * len(pool)))) if len(pool) > 1 else 0
    val = set(str(s) for s in rng.permutation(pool)[:min(n_val, max(len(pool) - 1, 0))])
    return [s for s in train_stations if s not in val], sorted(val)


def truth_and_refs(features: pd.DataFrame, table: pd.DataFrame, rows: model.Rows, refs: GridRefs):
    """True values and reference arrays of the rows of `rows` (used to fit the repairer)."""
    sub = features.iloc[rows.idx]
    return table["value_true"].to_numpy(np.float64)[rows.idx], reference_arrays(sub, refs)


def run_oof(features_inj: pd.DataFrame, table: pd.DataFrame, features_real: pd.DataFrame, obs_inj: pd.DataFrame,
            obs_real: pd.DataFrame, refs: GridRefs, params: dict, seed: int, n_folds: int = N_FOLDS):
    """(oof_real, oof_injected, info): out-of-fold engine outputs with a `fold` column (see module doc)."""
    stations = list(obs_real.columns)
    episodes = table.loc[table["episode_id"] >= 0, "station"].astype(str).unique()
    has_episodes = {sid: sid in set(episodes) for sid in stations}
    folds = assign_folds(stations, has_episodes, FOLD_SEED, n_folds)
    real_parts, inj_parts, info = [], [], []
    for k in range(n_folds):
        held = [s for s in stations if folds[s] == k]
        train_st = [s for s in stations if folds[s] != k]
        fit_st, val_st = inner_split(train_st, has_episodes, seed + k)
        assert not set(held) & set(train_st)
        train = model.assemble_rows(features_inj, table, fit_st)
        val = model.assemble_rows(features_inj, table, val_st)
        v_truth, v_refs = truth_and_refs(features_inj, table, val, refs)
        engine = IntegrityEngine.fit(train, val, v_truth, v_refs, seed + k, params=params)
        engine.select_tau(features_inj, obs_inj, refs, val.idx, val.y == 0)   # combined decision, inner-val clean days
        for features, observed, parts in ((features_real, obs_real, real_parts), (features_inj, obs_inj, inj_parts)):
            sub = features[features["station"].isin(held)].reset_index(drop=True)
            out = engine.predict(sub, observed, refs)
            out["fold"] = np.int8(k)
            parts.append(out[OOF_COLUMNS])
        info.append({"fold": k, "held_out": held, "fit_stations": len(fit_st), "fit_station_ids": fit_st, "inner_val": val_st,
                     "tau_1pct": engine.bundle.tau["0.01"], "train_rows": int(len(train.y)),
                     "best_iteration": engine.card["val_scores"]["best_iteration"]})
    return pd.concat(real_parts, ignore_index=True), pd.concat(inj_parts, ignore_index=True), info
