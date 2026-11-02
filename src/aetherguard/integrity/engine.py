"""The integrity engine: L1 checks + learned model + arbiter + repair, per station-day.

    engine = IntegrityEngine.fit(train_rows, val_rows, val_truth, val_refs, seed)
    out = engine.predict(features, observed, refs)      # one row per feature row
    engine.save(dir); IntegrityEngine.load(dir)

Decision logic (documented in `arbiter.py`):
  model flag   = calibrated P(any fault) > tau. tau is chosen on the VAL clean days so that the COMBINED decision
                 below flags at most the target share (1% by default) of them (`select_tau`); `fit` first stores
                 the model-only thresholds (`bundle.tau_model`), which `select_tau` replaces for prediction.
  L1 flag      = bounds | stuck (>= 3 identical positive days) | duplicate_block
  flagged      = model flag | L1 flag, minus the readings the arbiter retains as genuine extremes:
                 model flags by rule E; L1 flags only by rule S (stuck-only flags with >= 2 references within
                 30%); L1 bounds / duplicate_block flags are never overridden.
  repair       = weighted median of the references (+ band) on flagged, non-retained days; the original reading
                 is never changed.
Output rows without an observed value are NaN (trust, p_fault, repaired...) and never flagged.
Causality: the model probabilities at day t use only information up to t. The L1 `stuck` / `duplicate_block`
flags are retroactive: once a streak or block is confirmed, its EARLIER days are flagged too.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import arbiter, checks, model
from .common import dumps_strict
from .grids import GridRefs
from .inject import FAULT_TYPES
from .repair import Repairer

_L1_FAULT = {"stuck": "stuck_value", "duplicate_block": "duplicate_block", "bounds": "spike"}
OUTPUT_COLUMNS = ["station", "date", "trust", "p_fault", "fault_type", "flagged", "genuine_extreme", "repaired",
                  "repaired_lo", "repaired_hi", "reasons", "l1_flag", "l1_reason"]


def lookup(frame: pd.DataFrame, stations, dates) -> np.ndarray:
    """Value of a date x station frame at each (station, date) row (NaN where absent)."""
    di = frame.index.get_indexer(pd.DatetimeIndex(dates))
    si = frame.columns.get_indexer(pd.Index(stations))
    out = np.full(len(di), np.nan, dtype=np.float64)
    ok = (di >= 0) & (si >= 0)
    out[ok] = frame.to_numpy()[di[ok], si[ok]]
    return out


def reference_arrays(features: pd.DataFrame, refs: GridRefs) -> dict[str, np.ndarray]:
    """The independent references per feature row: imd, chirps_aligned and the wide-neighbour idw mean."""
    st, dt = features["station"].to_numpy(), features["date"].to_numpy()
    return {"imd": lookup(refs.values["imd"], st, dt), "chirps_aligned": lookup(refs.values["chirps_aligned"], st, dt),
            "neighbours": features["nbr_idw_mean"].to_numpy(np.float64)}


def rows_to_matrix(rows: pd.DataFrame, column: str, index: pd.DatetimeIndex, stations: list[str], fill=np.nan) -> np.ndarray:
    """Scatter a per-row column back into a (days, stations) matrix."""
    out = np.full((len(index), len(stations)), fill, dtype=object if isinstance(fill, str) else np.float64)
    di = index.get_indexer(pd.DatetimeIndex(rows["date"]))
    si = pd.Index(stations).get_indexer(rows["station"])
    out[di, si] = rows[column].to_numpy()
    return out


class IntegrityEngine:
    def __init__(self, bundle: model.ModelBundle, repairer: Repairer, card: dict | None = None) -> None:
        self.bundle, self.repairer, self.card = bundle, repairer, card or {}

    @classmethod
    def fit(cls, train: model.Rows, val: model.Rows, val_truth, val_refs: dict, seed: int,
            params: dict | None = None, dropout: bool = True, grid=None, rounds: int | None = None,
            extra_card: dict | None = None) -> "IntegrityEngine":
        """Train the model (grid search on VAL unless `params` is given) and fit the repairer on the VAL clean days.

        `val_truth` / `val_refs` are the true values and reference arrays of the rows of `val` (class 0 rows are the
        clean days the repairer uses)."""
        if params is None:
            bundle, params, candidates = model.search(train, val, seed, dropout, grid)
            card = dict(bundle.card)
        else:
            bundle, scores = model.fit_bundle(train, val, params, seed, dropout, rounds)
            card = {"selected_params": params, "candidates": [scores], "val_scores": scores}
        clean = val.y == 0
        repairer = Repairer.fit(np.asarray(val_truth)[clean], {k: np.asarray(v)[clean] for k, v in val_refs.items()})
        card.update({"features": bundle.columns, "thresholds": bundle.tau, "thresholds_model_only": bundle.tau, "seed": seed, "dropout": dropout,
                     "train_rows": {model.CLASSES[c]: int((train.y == c).sum()) for c in range(model.N_CLASSES)},
                     "val_rows": {model.CLASSES[c]: int((val.y == c).sum()) for c in range(model.N_CLASSES)},
                     "class_weights": {model.CLASSES[c]: float(w) for c, w in enumerate(model.class_weights(train.y))},
                     "repair": repairer.to_json(), **(extra_card or {})})
        return cls(bundle, repairer, card)

    def _prepare(self, features: pd.DataFrame, observed: pd.DataFrame, refs: GridRefs) -> dict:
        """Everything the decision needs that does not depend on tau: scores, L1 flags, references."""
        n = len(features)
        stations, dates = features["station"].to_numpy(), features["date"].to_numpy()
        obs = lookup(observed, stations, dates)
        valid = np.isfinite(obs)
        p_cal = np.full(n, np.nan)
        proba = np.full((n, model.N_CLASSES), np.nan)
        rows = np.flatnonzero(valid)
        if len(rows):
            p_cal[rows], proba[rows] = self.bundle.score(features[self.bundle.columns].to_numpy(np.float32)[rows])
        l1 = {name: lookup(frame.astype(float), stations, dates) > 0 for name, frame in (
            ("bounds", checks.bounds(observed)), ("stuck", checks.stuck(observed, checks.STUCK_MIN_RUN)),
            ("duplicate_block", checks.duplicate_block(observed)))}
        l1_flag = valid & (l1["bounds"] | l1["stuck"] | l1["duplicate_block"])
        l1_reason = np.full(n, "", dtype=object)
        for i in np.flatnonzero(l1_flag):
            l1_reason[i] = ",".join(k for k in l1 if l1[k][i])
        return {"n": n, "stations": stations, "dates": dates, "obs": obs, "valid": valid, "p_cal": p_cal,
                "proba": proba, "l1_flag": l1_flag, "l1_reason": l1_reason, "ref": reference_arrays(features, refs)}

    @staticmethod
    def _flags(prep: dict, tau: float, use_arbiter: bool = True, use_imd: bool = True) -> dict:
        """The decision at threshold `tau`: model flag, pre-arbiter flag, retained (arbiter) and final flag."""
        p_cal, l1_flag, obs = prep["p_cal"], prep["l1_flag"], prep["obs"]
        with np.errstate(invalid="ignore"):
            model_flag = prep["valid"] & (p_cal > tau)
        pre = model_flag | l1_flag
        retained = np.zeros(prep["n"], dtype=bool)
        why = np.full(prep["n"], "", dtype=object)
        if use_arbiter and pre.any():
            ret_e, why_e = arbiter.corroborate(obs, prep["ref"], np.nan_to_num(p_cal, nan=1.0), use_imd)
            ret_s, why_s = arbiter.stuck_exception(obs, prep["ref"], use_imd)
            stuck_only = prep["l1_reason"] == "stuck"
            retained = pre & np.where(l1_flag, stuck_only & ret_s, ret_e)
            why = np.where(l1_flag, why_s, why_e)
        return {"model_flag": model_flag, "pre": pre, "retained": retained, "why": why, "final": pre & ~retained}

    def tau_for_rate(self, features: pd.DataFrame, observed: pd.DataFrame, refs: GridRefs, clean_rows: np.ndarray,
                     targets, use_arbiter: bool = True, use_imd: bool = True) -> dict[str, float]:
        """Smallest tau per target such that the COMBINED decision (L1 or model flag, minus the readings the
        arbiter retains) flags at most `target` of the clean days. `clean_rows` are positions in `features` of
        clean days; `features` should hold the calibration stations only. When L1 alone already exceeds a target
        the largest score is returned (no tau can meet it)."""
        prep = self._prepare(features, observed, refs)
        clean = np.asarray(clean_rows)
        candidates = np.unique(prep["p_cal"][clean])
        out = {}
        for target in targets:
            def rate(tau):
                return self._flags(prep, tau, use_arbiter, use_imd)["final"][clean].mean()
            lo, hi = 0, len(candidates) - 1
            if rate(candidates[hi]) > target:
                out[str(target)] = float(candidates[hi])
                continue
            while lo < hi:
                mid = (lo + hi) // 2
                if rate(candidates[mid]) <= target:
                    hi = mid
                else:
                    lo = mid + 1
            out[str(target)] = float(candidates[lo])
        return out

    def select_tau(self, features: pd.DataFrame, observed: pd.DataFrame, refs: GridRefs, rows: np.ndarray,
                   clean: np.ndarray, targets=model.FPR_LEVELS) -> None:
        """Set the thresholds used by `predict` on the COMBINED decision, on the calibration (VAL) rows `rows`
        (positions in `features`) whose `clean` flag is True. The model-only thresholds stay in `bundle.tau_model`."""
        sub = features.iloc[rows].reset_index(drop=True)
        self.bundle.tau = self.tau_for_rate(sub, observed, refs, np.flatnonzero(np.asarray(clean)), targets)
        self.card["thresholds"] = self.bundle.tau
        self.card["thresholds_model_only"] = self.bundle.tau_model

    def predict(self, features: pd.DataFrame, observed: pd.DataFrame, refs: GridRefs, fpr: float = model.HEADLINE_FPR,
                use_arbiter: bool = True, use_imd: bool = True, tau: float | None = None) -> pd.DataFrame:
        """Engine output for every feature row (see the module doc for the decision logic). `tau` overrides the
        stored threshold of the target `fpr` (used for oracle-matched comparisons only)."""
        prep = self._prepare(features, observed, refs)
        tau = self.bundle.tau[str(fpr)] if tau is None else tau
        dec = self._flags(prep, tau, use_arbiter, use_imd)
        n, obs, p_cal, proba, ref = prep["n"], prep["obs"], prep["p_cal"], prep["proba"], prep["ref"]
        l1_flag, l1_reason = prep["l1_flag"], prep["l1_reason"]
        model_flag, pre, retained, why, final = (dec[k] for k in ("model_flag", "pre", "retained", "why", "final"))
        p_fault = np.where(final & l1_flag, 1.0, p_cal)
        fault_type = np.full(n, "", dtype=object)
        argmax = np.full(n, "", dtype=object)
        if final.any():
            fi = np.flatnonzero(final)
            sub = proba[fi][:, 1:]
            argmax[fi] = np.array(FAULT_TYPES, dtype=object)[np.nan_to_num(sub, nan=-1.0).argmax(axis=1)]
        for i in np.flatnonzero(final):
            from_l1 = l1_flag[i] and not model_flag[i]
            fault_type[i] = _L1_FAULT[l1_reason[i].split(",")[0]] if from_l1 else argmax[i]
        repaired = np.full(n, np.nan)
        lo = np.full(n, np.nan)
        hi = np.full(n, np.nan)
        if final.any():
            fi = np.flatnonzero(final)
            repaired[fi], lo[fi], hi[fi] = self.repairer.repair({k: v[fi] for k, v in ref.items()})
        reasons = np.full(n, "", dtype=object)
        for i in np.flatnonzero(pre):
            tokens = (["model"] if model_flag[i] else []) + ([f"l1:{l1_reason[i]}"] if l1_flag[i] else [])
            if retained[i]:
                tokens.append(why[i])
            elif np.isfinite(obs[i]) and obs[i] >= arbiter.EXTREME_MIN_MM and use_arbiter:
                tokens.append("uncorroborated")
            reasons[i] = ";".join(tokens)
        out = pd.DataFrame({"station": prep["stations"], "date": prep["dates"], "trust": 1.0 - p_fault,
                            "p_fault": p_fault, "fault_type": fault_type, "flagged": final, "genuine_extreme": retained,
                            "repaired": repaired, "repaired_lo": lo, "repaired_hi": hi, "reasons": reasons,
                            "l1_flag": l1_flag, "l1_reason": l1_reason})
        for c, name in enumerate(model.CLASSES):
            out[f"p_{name}"] = proba[:, c]
        return out

    def save(self, directory) -> None:
        directory = Path(directory)
        model.save_bundle(self.bundle, directory)
        (directory / "repairer.json").write_text(self.repairer.dumps() + "\n", encoding="utf-8")
        (directory / "card.json").write_text(dumps_strict(self.card), encoding="utf-8")

    @classmethod
    def load(cls, directory) -> "IntegrityEngine":
        directory = Path(directory)
        bundle = model.load_bundle(directory)
        repairer = Repairer.from_json(json.loads((directory / "repairer.json").read_text(encoding="utf-8")))
        card = json.loads((directory / "card.json").read_text(encoding="utf-8"))
        return cls(bundle, repairer, card)

