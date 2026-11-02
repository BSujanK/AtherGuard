"""Phase 2 gate: train the integrity engine, evaluate it against the baselines and ablations, write the
out-of-fold outputs and reports/phase2_integrity_report.md and .json.

    python -m aetherguard.integrity.engine_report [--n-boot 1000] [--raw-dir DIR] [--reports-dir DIR]

Needs the outputs of `baseline_report` (frozen station split) and `engine_data` (fault_dataset_2007, features,
reference cache). Nothing is tuned on the TEST stations: hyper-parameters, calibration and tau use VAL only.
"""
from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from . import baselines, checks, engine_data, evaluate, grids, inject, model, neighbours, oof
from .baseline_report import (FOREST_SEED, NEIGHBOUR_SETTINGS, RETENTION_VARIANTS, _VARIANT_LABELS, _ci, _f, _retention_cell,
                              _window, evaluate_method, real_flag_calibration)
from .common import display_path, dumps_strict, integrity_dir, reports_dir
from .engine import IntegrityEngine, lookup, reference_arrays, rows_to_matrix
from .splits import SPLIT_SEED, make_station_splits
from .stations import StationSet, load_station_set

MODEL_SEED = 20261010
ENGINE_DIR_NAME = "model"
OOF_NAME = "engine_outputs_2007_oof.parquet"
OOF_INJECTED_NAME = "engine_outputs_2007_oof_injected.parquet"
FPR = 0.01
N_BOOT = 1000
EVAL_SPLITS = ("val", "test")
BASELINE_ROWS = ("range_check", "l1", "noaa_style_qa", "noaa_style_qa_wide", "robust_zscore", "isolation_forest")
ENGINE_ROWS = ("engine_score", "engine", "engine_no_arbiter", "engine_arbiter_no_imd")
ABLATIONS = {"own_only": {"groups": ("own_",)},
             "no_grid": {"groups": ("own_", "nbr_", "wet_")},
             "no_nbr": {"groups": ("own_", "grid_", "wet_")},
             "no_wet": {"groups": ("own_", "nbr_", "grid_")},
             "no_dropout": {"dropout": False},
             "no_extra_seeds": {"extra_seeds": False}}
REAL_FLAG_YEARS = (2007, 2024)


@dataclass
class Data:
    window: StationSet
    splits: dict
    calibration: dict
    refs: grids.GridRefs
    tables: dict
    table: pd.DataFrame
    feats: pd.DataFrame
    mats: evaluate.FaultMatrices
    ids: list

    @property
    def obs(self) -> pd.DataFrame:
        return self.mats.value_obs[self.ids]

    def cols(self, split: str) -> np.ndarray:
        return np.array([i for i, sid in enumerate(self.ids) if self.mats.split_of[sid] == split])


def load_data(raw_dir=None) -> Data:
    """Stations, frozen splits, references and the frozen-seed 2007 fault dataset with its features."""
    full = load_station_set(raw_dir, start=None, end=None)
    window = _window(full, *engine_data.ENGINE_PERIOD)
    splits = make_station_splits(full.meta, seed=SPLIT_SEED)           # reads the frozen file
    out = integrity_dir()
    refs = engine_data.load_or_build_refs(window.meta, window.values.index, out / engine_data.REFS_CACHE_NAME, False)
    tables = {name: neighbours.neighbour_table(window.meta, k, km) for name, (k, km) in NEIGHBOUR_SETTINGS.items()}
    table = pd.read_parquet(out / engine_data.ENGINE_DATASET_NAME)
    feats = pd.read_parquet(out / engine_data.FEATURES_NAME)
    model.check_aligned(feats, table)
    mats = evaluate.to_matrices(table)
    ids = list(window.meta["id"])
    return Data(window, splits, real_flag_calibration(full, window), refs, tables, table, feats, mats, ids)


def _rows(data: Data, stations, groups, extra_seeds: bool, split_names=("train",)):
    parts = [model.assemble_rows(data.feats, data.table, stations, groups)]
    if extra_seeds:
        for seed in engine_data.TRAIN_EXTRA_SEEDS:
            table, feats = engine_data.load_or_build_seed_set(seed, data.window, data.splits, data.calibration,
                                                              data.refs, data.tables["wide"], split_names)
            parts.append(model.assemble_rows(feats, table, stations, groups))
    return model.concat_rows(parts)


def train_engine(data: Data, groups=("own_", "nbr_", "grid_", "wet_"), dropout=True, extra_seeds=True,
                 params=None) -> IntegrityEngine:
    """Train one engine variant on the TRAIN stations (VAL for early stopping / calibration / tau / repair)."""
    train = _rows(data, data.splits["train"], groups, extra_seeds)
    val = model.assemble_rows(data.feats, data.table, data.splits["val"], groups)
    truth, refs = oof.truth_and_refs(data.feats, data.table, val, data.refs)
    engine = IntegrityEngine.fit(train, val, truth, refs, MODEL_SEED, params=params, dropout=dropout,
                                 extra_card={"groups": list(groups), "extra_seeds": extra_seeds,
                                             "seeds": {"model": MODEL_SEED, "dataset": engine_data.DATASET_SEED,
                                                       "extra_train": list(engine_data.TRAIN_EXTRA_SEEDS),
                                                       "stability": list(engine_data.STABILITY_SEEDS)}})
    engine.select_tau(data.feats, data.obs, data.refs, val.idx, val.y == 0)   # combined decision on VAL clean days
    return engine


def model_score_matrix(engine: IntegrityEngine, feats: pd.DataFrame, observed: pd.DataFrame) -> np.ndarray:
    """Raw P(any fault) per station-day (NaN without an observed value) as a (days, stations) matrix."""
    n = len(feats)
    obs = lookup(observed, feats["station"].to_numpy(), feats["date"].to_numpy())
    rows = np.flatnonzero(np.isfinite(obs))
    p = np.full(n, np.nan)
    p[rows] = engine.bundle.p_any_raw(engine.bundle.proba(feats[engine.bundle.columns].to_numpy(np.float32)[rows]))
    frame = pd.DataFrame({"station": feats["station"].to_numpy(), "date": feats["date"].to_numpy(), "p": p})
    return rows_to_matrix(frame, "p", observed.index, list(observed.columns))


def flag_matrix(out: pd.DataFrame, index, stations) -> np.ndarray:
    return rows_to_matrix(out.assign(f=out["flagged"].astype(float)), "f", index, stations, fill=0.0) > 0


def baseline_scores(data: Data, train_cols) -> tuple[dict, object]:
    obs, t = data.obs, data.tables
    model_if = baselines.fit_isolation_forest(obs.iloc[:, train_cols], seed=FOREST_SEED)
    scores = {"range_check": baselines.range_check(obs).to_numpy(),
              "l1": checks.l1_flag_matrix(obs).to_numpy(),
              "noaa_style_qa": baselines.noaa_style_qa(obs, t["design"]).to_numpy(),
              "noaa_style_qa_wide": baselines.noaa_style_qa(obs, t["wide"]).to_numpy(),
              "robust_zscore": baselines.robust_zscore(obs).to_numpy(),
              "isolation_forest": baselines.isolation_forest(obs, model_if).to_numpy()}
    return scores, model_if


# ------------------------------------------------------------------------------------------ evaluation parts

def repair_evaluation(pred: pd.DataFrame, data: Data, split: str) -> dict:
    """Repair quality on the injected days (truth known) that the engine flagged and did not retain."""
    ids = data.ids
    keep = {sid for sid in ids if data.mats.split_of[sid] == split}
    sub = pred[pred["station"].isin(keep)]
    dates, stations = pd.DatetimeIndex(sub["date"]), sub["station"].to_numpy()
    truth = lookup(data.mats.value_true, stations, dates)
    obs = lookup(data.mats.value_obs, stations, dates)
    fault = lookup(pd.DataFrame((data.mats.fault_type != "").astype(float), index=data.mats.value_obs.index,
                                columns=data.mats.stations), stations, dates) > 0
    previous = lookup(data.mats.value_obs.shift(1), stations, dates)
    neighbour_mean = sub["_nbr"].to_numpy()
    repaired, lo, hi = (sub[c].to_numpy() for c in ("repaired", "repaired_lo", "repaired_hi"))
    faulty = fault & sub["flagged"].to_numpy()
    have = faulty & np.isfinite(repaired)
    common = have & np.isfinite(previous) & np.isfinite(neighbour_mean)
    err = lambda est, mask: np.abs(est[mask] - truth[mask])  # noqa: E731
    out = {"faulty_days": int(fault.sum()), "flagged_not_retained": int(faulty.sum()), "with_repair": int(have.sum()),
           "common_days": int(common.sum())}
    if common.any():
        methods = {"engine_repair": repaired, "previous_day": previous, "neighbour_mean": neighbour_mean,
                   "zero_fill": np.zeros_like(truth), "no_repair_observed": obs}
        out["methods"] = {name: {"mae": float(err(est, common).mean()), "median_abs_error": float(np.median(err(est, common)))}
                          for name, est in methods.items()}
    out["band_coverage"] = float(((truth >= lo) & (truth <= hi))[have].mean()) if have.any() else float("nan")
    hazard = have & (truth >= 50.0)
    out["hazard_safe"] = {"days": int(hazard.sum()),
                          "share_repaired_ge_half_truth": float((repaired[hazard] >= 0.5 * truth[hazard]).mean())
                          if hazard.any() else float("nan")}
    return out


def seed_stability(engine: IntegrityEngine, data: Data, rebuild: bool = False) -> dict:
    """The engine (trained once) on the TEST stations of the frozen dataset and of three other injection seeds."""
    sets = {"frozen": (data.table, data.feats)}
    for seed in engine_data.STABILITY_SEEDS:
        sets[str(seed)] = engine_data.load_or_build_seed_set(seed, data.window, data.splits, data.calibration,
                                                             data.refs, data.tables["wide"], ("val", "test"), rebuild)
    results = {}
    for name, (table, feats) in sets.items():
        mats = evaluate.to_matrices(table)
        stations = [s for s in mats.stations if mats.split_of[s] == "test"]
        keep = np.array([mats.split_of[s] == "test" for s in mats.stations])
        feats_t = feats[feats["station"].isin(stations)].reset_index(drop=True)
        obs = mats.value_obs[mats.stations]
        pred = engine.predict(feats_t, obs, data.refs)
        score = model_score_matrix(engine, feats_t, obs)
        flags = flag_matrix(pred, obs.index, mats.stations)
        entry = {}
        for label, matrix in (("score_at_1pct", score), ("full_engine_flags", flags)):
            r = evaluate.recall_at_fpr(matrix[:, keep], mats.fault_type[:, keep], mats.clean[:, keep], FPR)
            entry[label] = {"macro_recall": r["macro_recall"], "achieved_fpr": r["achieved_fpr"],
                            "recall": {t: v["recall"] for t, v in r["per_type"].items()},
                            "episodes": {t: int(len(set(mats.episode_id[:, keep][mats.fault_type[:, keep] == t])))
                                         for t in inject.FAULT_TYPES}}
        results[name] = entry
    summary = {}
    for label in ("score_at_1pct", "full_engine_flags"):
        macro = np.array([results[n][label]["macro_recall"] for n in results])
        summary[label] = {"macro_recall_mean": float(np.nanmean(macro)), "macro_recall_min": float(np.nanmin(macro)),
                          "macro_recall_max": float(np.nanmax(macro)),
                          "per_type": {t: {"mean": float(np.nanmean([results[n][label]["recall"][t] for n in results])),
                                           "min": float(np.nanmin([results[n][label]["recall"][t] for n in results])),
                                           "max": float(np.nanmax([results[n][label]["recall"][t] for n in results]))}
                                       for t in inject.FAULT_TYPES}}
    return {"seeds": list(results), "by_seed": results, "summary": summary}


def real_flag_sanity(engine: IntegrityEngine, data: Data, feats_real: pd.DataFrame, scores_model, thresholds: dict) -> dict:
    """The real NOAA flags of 2007-2024 (n is tiny) against the engine and the baselines, on the real series."""
    real = data.window
    values = real.values
    flagged_real = (real.flags.to_numpy(dtype=object) != "") & values.notna().to_numpy()
    letters = real.flags.to_numpy(dtype=object)
    valid = values.notna().to_numpy()
    flags = {"range_check": baselines.range_check(values).to_numpy(), "l1": checks.l1_flag_matrix(values).to_numpy(),
             "noaa_style_qa": baselines.noaa_style_qa(values, data.tables["design"]).to_numpy(),
             "noaa_style_qa_wide": baselines.noaa_style_qa(values, data.tables["wide"]).to_numpy()}
    z = baselines.robust_zscore(values).to_numpy()
    flags["robust_zscore"] = np.isfinite(z) & (z > thresholds["robust_zscore"])
    f = baselines.isolation_forest(values, scores_model).to_numpy()
    flags["isolation_forest"] = np.isfinite(f) & (f > thresholds["isolation_forest"])
    for name, kwargs in (("engine", {}), ("engine_no_arbiter", {"use_arbiter": False})):
        pred = engine.predict(feats_real, values, data.refs, **kwargs)
        flags[name] = flag_matrix(pred, values.index, list(values.columns))
    out = {"n_flagged_values": int(flagged_real.sum()), "years": list(REAL_FLAG_YEARS),
           "by_flag": {k: int(v) for k, v in pd.Series(letters[flagged_real]).value_counts().sort_index().items()},
           "note": "only the real NOAA flags inside 2007-2024 can be scored (references exist from 2007): n is tiny",
           "methods": {}}
    for name, flag in flags.items():
        out["methods"][name] = {"flagged_real": int((flag & flagged_real).sum()),
                                "by_flag": {k: int(v) for k, v in pd.Series(letters[flag & flagged_real]).value_counts().sort_index().items()},
                                "false_flag_rate_on_unflagged_valid_days": float((flag & valid & ~flagged_real).sum()
                                                                                  / (valid & ~flagged_real).sum())}
    return out


def verdict(a: dict, b: dict) -> str:
    """Engine cell `a` vs baseline cell `b` (each {recall, recall_ci, n_positive})."""
    if a["n_positive"] == 0:
        return "n/a"
    ra, rb = a["recall"], b["recall"]
    (alo, ahi), (blo, bhi) = a["recall_ci"], b["recall_ci"]
    if ra > rb and alo > bhi:
        return "beats"
    if ra < rb and ahi < blo:
        return "loses"
    return "ties (CIs overlap)" if ra != rb else "ties"


def _assess(methods: dict, row: str, label: str) -> list[str]:
    lines = []
    for t in inject.FAULT_TYPES:
        cell = methods[row]["per_type"][t]
        parts = [f"{name}: {verdict(cell, methods[name]['per_type'][t])}" for name in BASELINE_ROWS]
        lines.append(f"[{label}] {t} (recall {_f(cell['recall'], 2)}{_ci(cell['recall_ci'])}, "
                     f"{cell['n_positive']} days): " + "; ".join(parts))
    return lines


def gate_assessment(report_eval: dict, diagnosis: dict) -> dict:
    """Per fault type on TEST, from the recall CIs. Primary: the combined engine at the VAL-chosen 1% tau (its realised
    TEST false-flag rate is stated); secondary: the model score alone at a matched 1%; the oracle-matched row is a
    comparison at the baseline's own false-flag rate, not a deployable threshold."""
    methods = report_eval["test"]["methods"]
    realised = methods["engine"]["achieved_fpr"]
    primary = _assess(methods, "engine", f"combined engine @ VAL-chosen 1% tau, realised TEST false-flag rate {_f(realised, 4)}")
    secondary = _assess(methods, "engine_score", "model score only, 1% on the TEST clean days")
    oracle = _assess(methods, "engine_oracle_matched_noaa_wide",
                     f"oracle-matched to noaa_style_qa_wide's TEST rate {_f(methods['noaa_style_qa_wide']['achieved_fpr'], 4)}"
                     f" (engine realises {_f(methods['engine_oracle_matched_noaa_wide']['achieved_fpr'], 4)}; not deployable)")
    d = diagnosis
    statement = (f"At the VAL-chosen 1% tau the combined engine flags {_f(d['val_combined_fpr'], 4)} of VAL clean days "
                 f"but {_f(realised, 4)} of TEST clean days. " + (
                     f"{d['nepal_share_of_test_false_flags']:.0%} of the TEST false flags "
                     f"({d['nepal_false_flags']} of {d['test_false_flags']}) come from the two Nepal stations, which hold "
                     f"{d['nepal_share_of_test_clean_days']:.0%} of the TEST clean days and are the only TEST stations "
                     f"outside the training distribution of Indian stations; without them the TEST rate is "
                     f"{_f(d['test_fpr_excluding_nepal'], 4)}. " if d["test_false_flags"] else "")
                 + "The threshold does not transfer to those stations: the engine is NOT at 1% on TEST, so the full-engine "
                   "recalls below are at a higher false-flag rate than the baselines (read the oracle-matched rows and "
                   "the model-score rows for matched-rate comparisons).")
    return {"primary": primary, "secondary_model_score": secondary, "oracle_matched": oracle, "statement": statement}


def false_flag_diagnosis(engine: IntegrityEngine, data: Data, scores: dict, evaluation: dict) -> dict:
    """Why the realised TEST false-flag rate differs from the target (numbers, no tuning on TEST)."""
    mats, ids, meta = data.mats, data.ids, data.window.meta
    clean = mats.clean
    out = {}
    for split in EVAL_SPLITS:
        cols = data.cols(split)
        cl = clean[:, cols]
        out[f"{split}_combined_fpr"] = float((scores["engine"][:, cols] & cl).sum() / cl.sum())
        out[f"{split}_combined_no_arbiter_fpr"] = float((scores["engine_no_arbiter"][:, cols] & cl).sum() / cl.sum())
        out[f"{split}_l1_only_fpr"] = float((scores["l1"][:, cols] & cl).sum() / cl.sum())
        raw = scores["engine_score"][:, cols]
        p_cal = np.where(np.isfinite(raw), engine.bundle.calibrate(np.nan_to_num(raw)), np.nan)
        out[f"{split}_model_only_fpr_at_tau_model"] = float(((p_cal > engine.bundle.tau_model["0.01"]) & cl).sum() / cl.sum())
    val_cols = data.cols("val")
    raw = scores["engine_score"][:, val_cols][clean[:, val_cols]]
    p_cal = engine.bundle.calibrate(raw)
    out["val_clean_days"] = int(clean[:, val_cols].sum())
    out["val_clean_unique_scores"] = int(len(np.unique(p_cal)))
    out["val_share_of_clean_scores_equal_to_tau_model"] = float((p_cal == engine.bundle.tau_model["0.01"]).mean())
    out["tau_combined_1pct"] = engine.bundle.tau["0.01"]
    out["tau_model_only_1pct"] = engine.bundle.tau_model["0.01"]
    out["clean_day_definition"] = ("selection and evaluation use the same mask: clean real day (valid, unflagged, station-year "
                                   ">= 150 valid days) outside every episode window, with an observed value")
    test_cols = data.cols("test")
    rows = []
    flag = scores["engine"]
    for j in test_cols:
        n = int(clean[:, j].sum())
        if n:
            rows.append({"station": ids[j], "country": str(meta["country"].iloc[j]), "upland": bool(meta["upland"].iloc[j]),
                         "clean_days": n, "false_flags": int((flag[:, j] & clean[:, j]).sum())})
    table = pd.DataFrame(rows)
    table["rate"] = table["false_flags"] / table["clean_days"]
    top = table.sort_values("false_flags", ascending=False).head(6)
    out["test_top_stations"] = top.to_dict("records")
    nepal = table["country"] == "NP"
    out["test_false_flags"] = int(table["false_flags"].sum())
    out["nepal_false_flags"] = int(table.loc[nepal, "false_flags"].sum())
    out["nepal_share_of_test_false_flags"] = float(out["nepal_false_flags"] / max(out["test_false_flags"], 1))
    out["nepal_share_of_test_clean_days"] = float(table.loc[nepal, "clean_days"].sum() / table["clean_days"].sum())
    rest = table[~nepal]
    out["test_fpr_excluding_nepal"] = float(rest["false_flags"].sum() / rest["clean_days"].sum())
    # does missing reference data explain it? VAL model false-flag rate with a group of columns removed
    val = model.assemble_rows(data.feats, data.table, data.splits["val"])
    base_scores = engine.bundle.calibrate(engine.bundle.p_any_raw(engine.bundle.proba(val.X)))
    checks_ = {"none": lambda c: False, "imd columns": lambda c: c.startswith("grid_") and "imd" in c,
               "all grid_ columns": lambda c: c.startswith("grid_"), "nbr_ columns": lambda c: c.startswith("nbr_")}
    tau_m = engine.bundle.tau_model["0.01"]
    out["val_model_fpr_with_columns_missing"] = {}
    for name, pick in checks_.items():
        X = val.X.copy()
        X[:, [k for k, c in enumerate(val.columns) if pick(c)]] = np.nan
        p = engine.bundle.calibrate(engine.bundle.p_any_raw(engine.bundle.proba(X)))
        out["val_model_fpr_with_columns_missing"][name] = float((p[val.y == 0] > tau_m).mean())
    nep = [s for s in ids if str(meta.set_index("id").loc[s, "country"]) == "NP"]
    lab = model.label_rows(data.table)
    m = data.feats["station"].isin(nep).to_numpy() & (lab == 0)
    out["nepal_model_false_flags_by_month"] = {}
    out["nepal_model_false_flags_by_predicted_class"] = {}
    if m.any():
        X = data.feats.loc[m, engine.bundle.columns].to_numpy(np.float32)
        proba = engine.bundle.proba(X)
        fp = engine.bundle.calibrate(engine.bundle.p_any_raw(proba)) > tau_m
        months = pd.DatetimeIndex(data.feats.loc[m, "date"]).month
        out["nepal_model_false_flags_by_month"] = {str(k): int(v) for k, v in
                                                   pd.Series(months[fp]).value_counts().sort_index().items()}
        cls = np.array(model.CLASSES)[proba[:, 1:].argmax(axis=1) + 1]
        out["nepal_model_false_flags_by_predicted_class"] = {k: int(v) for k, v in pd.Series(cls[fp]).value_counts().items()}
    return out


def tau_table(evaluation: dict, engine: IntegrityEngine) -> dict:
    """The combined engine at the VAL-chosen tau of each target, with the realised false-flag rate and macro recall."""
    rows = {}
    for level, name in ((0.005, "engine_at_0.5pct"), (0.01, "engine"), (0.02, "engine_at_2pct")):
        rows[str(level)] = {"tau": engine.bundle.tau[str(level)], "row": name,
                            **{split: {"achieved_fpr": evaluation[split]["methods"][name]["achieved_fpr"],
                                       "macro_recall": evaluation[split]["methods"][name]["macro_recall"]}
                               for split in EVAL_SPLITS}}
    return rows


def tau_transfer(engine: IntegrityEngine, scores: dict, mats, data: Data) -> dict:
    """Does the VAL-chosen MODEL-ONLY tau keep its false-flag rate on the other stations? (no L1, no arbiter)"""
    raw = scores["engine_score"]
    p_cal = np.where(np.isfinite(raw), engine.bundle.calibrate(np.nan_to_num(raw)), np.nan)
    out = {}
    for level in model.FPR_LEVELS:
        tau = engine.bundle.tau_model[str(level)]
        flags = p_cal > tau
        row = {"tau": tau}
        for split in EVAL_SPLITS:
            cols = data.cols(split)
            r = evaluate.recall_at_fpr(flags[:, cols], mats.fault_type[:, cols], mats.clean[:, cols], level)
            row[split] = {"achieved_fpr": r["achieved_fpr"], "macro_recall": r["macro_recall"]}
        out[str(level)] = row
    return out


# ------------------------------------------------------------------------------------------------ report

def build_report(data: Data, n_boot: int, retrain_note: str = "") -> tuple[dict, dict]:
    t0 = time.monotonic()
    timings = {}
    mats, obs, ids = data.mats, data.obs, data.ids
    feats = data.feats
    engine = train_engine(data)
    timings["train_main_s"] = round(time.monotonic() - t0, 1)
    params = engine.card["selected_params"]
    engine.save(integrity_dir() / ENGINE_DIR_NAME)
    ablation_engines = {}
    for name, opts in ABLATIONS.items():
        ablation_engines[name] = train_engine(data, params=params, **opts)
    timings["train_ablations_s"] = round(time.monotonic() - t0 - timings["train_main_s"], 1)
    pred = {"engine": engine.predict(feats, obs, data.refs),
            "engine_no_arbiter": engine.predict(feats, obs, data.refs, use_arbiter=False),
            "engine_arbiter_no_imd": engine.predict(feats, obs, data.refs, use_imd=False),
            "engine_at_0.5pct": engine.predict(feats, obs, data.refs, fpr=0.005),
            "engine_at_2pct": engine.predict(feats, obs, data.refs, fpr=0.02)}
    scores, model_if = baseline_scores(data, [i for i, s in enumerate(ids) if mats.split_of[s] == "train"])
    scores["engine_score"] = model_score_matrix(engine, feats, obs)
    for name, flag_pred in pred.items():
        scores[name] = flag_matrix(flag_pred, obs.index, ids)
    for name, eng in ablation_engines.items():
        scores[f"ablation_{name}"] = model_score_matrix(eng, feats, obs)
    extremes = {name: evaluate.genuine_extremes(obs, mats.clean, data.tables[table], min_neighbours=minimum).to_numpy()
                for name, (table, minimum) in RETENTION_VARIANTS.items()}
    evaluation, thresholds = {}, {}
    for split in EVAL_SPLITS:
        cols = data.cols(split)
        evaluation[split] = {"n_stations": int(len(cols)), "methods": {}}
        for name, matrix in scores.items():
            result = evaluate_method(matrix, mats, cols, extremes, FPR, n_boot)
            evaluation[split]["methods"][name] = result
            if split == "val" and result["threshold"] is not None:
                thresholds[name] = result["threshold"]
        evaluation[split]["spike_trade_off"] = _spike_trade_off(scores, mats, cols)
    oracle_tau = _oracle_tau(engine, data, evaluation["test"]["methods"]["noaa_style_qa_wide"]["achieved_fpr"])
    oracle_pred = engine.predict(feats, obs, data.refs, tau=oracle_tau)
    scores["engine_oracle_matched_noaa_wide"] = flag_matrix(oracle_pred, obs.index, ids)
    evaluation["test"]["methods"]["engine_oracle_matched_noaa_wide"] = evaluate_method(
        scores["engine_oracle_matched_noaa_wide"], mats, data.cols("test"), extremes, FPR, n_boot)
    evaluation["test"]["oracle_tau"] = oracle_tau
    ex_nepal = np.array([i for i in data.cols("test") if str(data.window.meta["country"].iloc[i]) != "NP"])
    evaluation["test_ex_nepal"] = {"n_stations": int(len(ex_nepal)), "methods": {
        name: evaluate_method(matrix, mats, ex_nepal, extremes, FPR, n_boot) for name, matrix in scores.items()
        if name != "engine_oracle_matched_noaa_wide"}}
    diagnosis = false_flag_diagnosis(engine, data, scores, evaluation)
    for name, p in pred.items():
        p["_nbr"] = reference_arrays(feats, data.refs)["neighbours"]
    repair = {split: repair_evaluation(pred["engine"], data, split) for split in EVAL_SPLITS}
    timings["evaluate_s"] = round(time.monotonic() - t0 - timings["train_main_s"] - timings["train_ablations_s"], 1)
    stability = seed_stability(engine, data)
    feats_real = engine_data.load_or_build_real_features(data.window, data.refs, data.tables["wide"])
    sanity = real_flag_sanity(engine, data, feats_real, model_if, thresholds)
    oof_real, oof_inj, oof_info = oof.run_oof(feats, data.table, feats_real, obs, data.window.values, data.refs, params,
                                             MODEL_SEED)
    oof_real.to_parquet(integrity_dir() / OOF_NAME, index=False)
    oof_inj.to_parquet(integrity_dir() / OOF_INJECTED_NAME, index=False)
    supplement = _oof_supplement(oof_inj, scores, data, extremes, n_boot)
    timings["total_s"] = round(time.monotonic() - t0, 1)
    report = {
        "config": {"fpr": FPR, "n_boot": n_boot, "model_seed": MODEL_SEED, "split_seed": SPLIT_SEED,
                   "dataset_seed": engine_data.DATASET_SEED, "extra_train_seeds": list(engine_data.TRAIN_EXTRA_SEEDS),
                   "stability_seeds": list(engine_data.STABILITY_SEEDS), "period": list(engine_data.ENGINE_PERIOD),
                   "dataset_min_valid_days": engine_data.ENGINE_MIN_VALID_DAYS, "dataset_density": engine_data.ENGINE_DENSITY,
                   "rows": list(scores), "fault_types": list(inject.FAULT_TYPES),
                   "retention_variants": {k: {"neighbour_setting": v[0], "min_neighbours": v[1]}
                                          for k, v in RETENTION_VARIANTS.items()}},
        "engine_card": engine.card,
        "fault_dataset": {"episodes_per_type": {s: {t: c["episodes"] for t, c in r["by_type"].items()}
                                                for s, r in inject.dataset_report(data.table)["splits"].items()},
                          "n_stations_with_episodes": {s: r["n_stations_with_episodes"] for s, r in
                                                       inject.dataset_report(data.table)["splits"].items()}},
        "evaluation": evaluation, "repair": repair, "seed_stability": stability, "real_flag_sanity": sanity,
        "oof": {"info": oof_info, "supplement": supplement, "outputs": _oof_stats(oof_real, oof_inj)},
        "timings_s": timings, "note": retrain_note}
    report["false_flag_diagnosis"] = diagnosis
    report["gate_assessment"] = gate_assessment(evaluation, diagnosis)
    report["tau_combined"] = tau_table(evaluation, engine)
    report["tau_transfer_model_only"] = tau_transfer(engine, scores, mats, data)
    return report, {"engine": engine}


def _oracle_tau(engine: IntegrityEngine, data: Data, target: float) -> float:
    """ORACLE: the tau at which the combined decision flags at most `target` of the TEST clean days. Used only for the
    labelled oracle-matched comparison, never as a deployable threshold."""
    lab = model.label_rows(data.table)
    rows = np.flatnonzero(data.feats["station"].isin(set(data.splits["test"])).to_numpy())
    sub = data.feats.iloc[rows].reset_index(drop=True)
    return engine.tau_for_rate(sub, data.obs, data.refs, np.flatnonzero(lab[rows] == 0), [target])[str(target)]


def _spike_trade_off(scores: dict, mats, cols) -> dict:
    """Spike days the model flags that the arbiter retains (the arbiter's cost in spike recall)."""
    truth = mats.fault_type[:, cols] == "spike"
    before, after = scores["engine_no_arbiter"][:, cols], scores["engine"][:, cols]
    return {"spike_days": int(truth.sum()), "flagged_without_arbiter": int((before & truth).sum()),
            "flagged_with_arbiter": int((after & truth).sum()),
            "retained_by_arbiter": int((before & ~after & truth).sum())}


def _oof_supplement(oof_inj: pd.DataFrame, scores: dict, data: Data, extremes: dict, n_boot: int) -> dict:
    """Grouped-CV metrics over ALL stations with episodes (a supplement: more stations than the 11 TEST ones)."""
    mats = data.mats
    flagged = flag_matrix(oof_inj, mats.value_obs.index, mats.stations)
    cols = np.array([i for i, s in enumerate(mats.stations)
                     if (mats.episode_id[:, i] >= 0).any()])
    out = {"n_stations": int(len(cols)), "methods": {}}
    for name, matrix in (("engine_oof", flagged), ("l1", scores["l1"]), ("noaa_style_qa_wide", scores["noaa_style_qa_wide"]),
                         ("robust_zscore", scores["robust_zscore"])):
        out["methods"][name] = evaluate_method(matrix, mats, cols, extremes, FPR, n_boot)
    return out


def _oof_stats(real: pd.DataFrame, inj: pd.DataFrame) -> dict:
    return {"rows": int(len(real)), "trust_nan_share": float(real["trust"].isna().mean()),
            "flagged_share_of_observed": float(real["flagged"].sum() / max(real["trust"].notna().sum(), 1)),
            "genuine_extreme_days": int(real["genuine_extreme"].sum()),
            "by_fold_rows": {str(k): int(v) for k, v in real["fold"].value_counts().sort_index().items()},
            "memory_mb": round(float(real.memory_usage(deep=True).sum()) / 2**20, 1),
            "injected_rows": int(len(inj))}


def _rec(result: dict, t: str) -> str:
    cell = result["per_type"][t]
    if cell["n_positive"] == 0:
        return "n/a (0)"
    text = _f(cell["recall"], 2)
    if result["binary"]:
        text += f" (fpr {_f(result['achieved_fpr'], 3)})"
    return text + _ci(cell["recall_ci"])


def render_markdown(report: dict) -> str:
    cfg, types = report["config"], report["config"]["fault_types"]
    ev = report["evaluation"]
    lines = ["# Phase 2 - sensor-integrity engine: gate report", "",
             "Faults are INJECTED into real clean 2007-2024 station series (not real faults); 95% bootstrap CIs over "
             "stations; zero-width intervals print as 'n/a (degenerate)'. Hyper-parameters, calibration and tau use the "
             "VAL stations only. `engine_score` is the model score alone at a 1% false-flag rate on the evaluated split's "
             "clean days (the protocol of the score baselines). `engine` is the COMBINED decision (L1 or model flag, minus "
             "the readings the arbiter retains) at the tau chosen on the VAL clean days so that this combined decision flags "
             "at most 1% of them; `engine_at_0.5pct` / `engine_at_2pct` use the 0.5% / 2% VAL-chosen taus. Rule and "
             "combined rows are shown as recall (realised false-flag rate on that split's clean days). "
             "`engine_oracle_matched_noaa_wide` (TEST only) picks tau ON THE TEST clean days to match noaa_style_qa_wide's "
             "false-flag rate: an oracle comparison, NOT a deployable threshold.", ""]
    ep = report["fault_dataset"]["episodes_per_type"]
    lines += ["## Evaluation data", "", "| split | stations with episodes | " + " | ".join(types) + " |",
              "|---|---|" + "---|" * len(types)]
    for split in ("train", "val", "test"):
        lines.append(f"| {split} | {report['fault_dataset']['n_stations_with_episodes'][split]} | "
                     + " | ".join(str(ep[split][t]) for t in types) + " |")
    lines += ["", "scale_drift shortfall (reported, not hidden): the 150-day / density 0.15 dataset has "
              f"{ep['test']['scale_drift']} TEST and {ep['train']['scale_drift']} TRAIN scale_drift episodes, below the "
              "15 / 40 minimum; its recall rests on that few episodes.", ""]
    card = report["engine_card"]
    lines += ["## Training", "", f"Train rows {card['train_rows']} (frozen seed plus {len(cfg['extra_train_seeds'])} extra "
              f"injection seeds), VAL rows {card['val_rows']}. Selected {card['selected_params']}; every candidate:", "",
              "| params | best iteration | VAL macro recall @1% | VAL log-loss |", "|---|---|---|---|"]
    for c in card["candidates"]:
        lines.append(f"| {c['params']} | {c['best_iteration']} | {_f(c['val_macro_recall_at_1pct'], 3)} | {_f(c['val_logloss'], 4)} |")
    lines.append("")
    for split in ("test", "val"):
        block = ev[split]
        lines += [f"## {split.upper()} stations ({block['n_stations']}): recall per fault type", "",
                  "| method | " + " | ".join(types) + " | macro |", "|---|" + "---|" * (len(types) + 1)]
        for name, result in block["methods"].items():
            lines.append(f"| {name} | " + " | ".join(_rec(result, t) for t in types) + f" | {_f(result['macro_recall'], 2)} |")
        lines += ["", f"### {split.upper()}: detection (episodes detected / total, median delay days)", "",
                  "| method | " + " | ".join(types) + " |", "|---|" + "---|" * len(types)]
        for name, result in block["methods"].items():
            if name.startswith("ablation_"):
                continue
            lines.append(f"| {name} | " + " | ".join(
                f"{result['delay'][t]['detected']}/{result['delay'][t]['episodes']}, {_f(result['delay'][t]['median_delay_days'], 1)}"
                for t in types) + " |")
        lines += ["", f"### {split.upper()}: PR-AUC (score methods)", "", "| method | " + " | ".join(types) + " |",
                  "|---|" + "---|" * len(types)]
        for name, result in block["methods"].items():
            if not result["binary"]:
                lines.append(f"| {name} | " + " | ".join(_f(result["per_type"][t]["pr_auc"], 3) for t in types) + " |")
        lines.append("")
    test = ev["test"]
    full = test["methods"]["engine_score"]["macro_recall"]
    lines += ["## Ablations (TEST macro recall of the model score at 1%; delta against the full model)", "",
              "| variant | macro recall | delta |", "|---|---|---|", f"| full model | {_f(full, 3)} | 0 |"]
    for name in ABLATIONS:
        m = test["methods"][f"ablation_{name}"]["macro_recall"]
        lines.append(f"| {name} | {_f(m, 3)} | {_f(m - full, 3)} |")
    lines.append("")
    for split in ("test", "val"):
        block = ev[split]
        lines += [f"## {split.upper()}: genuine-extreme retention, all variants (retained / extremes), and the spike trade-off", "",
                  "No single number is the safety result. `design-strict` and `wide` need >= 2 neighbours >= 30% of the "
                  "value; `wide_1neighbour` needs 1; `uncorroborated` has no neighbour condition (proxy, includes "
                  "unverified readings).", "",
                  "| method | " + " | ".join(_VARIANT_LABELS[v] for v in RETENTION_VARIANTS) + " | spike recall |",
                  "|---|" + "---|" * (len(RETENTION_VARIANTS) + 1)]
        for name in ("engine", "engine_no_arbiter", "engine_arbiter_no_imd", "engine_score", "robust_zscore",
                     "isolation_forest", "noaa_style_qa_wide", "l1"):
            r = block["methods"][name]
            lines.append(f"| {name} | " + " | ".join(_retention_cell(r["retention"][v]) for v in RETENTION_VARIANTS)
                         + f" | {_rec(r, 'spike')} |")
        st = block["spike_trade_off"]
        lines += ["", f"Spike days {st['spike_days']}: flagged without the arbiter {st['flagged_without_arbiter']}, with it "
                  f"{st['flagged_with_arbiter']}; the arbiter retains {st['retained_by_arbiter']} injected spike days as "
                  "'genuine extremes' (that is its spike-recall cost).", ""]
    lines += ["## Repair (flagged, non-retained injected-fault days with a reference)", ""]
    for split in ("test", "val"):
        r = report["repair"][split]
        lines += [f"### {split.upper()}: {r['faulty_days']} faulty days, {r['flagged_not_retained']} flagged and not retained, "
                  f"{r['with_repair']} with a repair, {r['common_days']} on the common set", ""]
        if "methods" in r:
            lines += ["| estimate | MAE mm | median abs error mm |", "|---|---|---|"]
            lines += [f"| {k} | {_f(v['mae'], 2)} | {_f(v['median_abs_error'], 2)} |" for k, v in r["methods"].items()]
        lines += ["", f"Band (10th-90th residual percentile) coverage {_f(r['band_coverage'], 3)}; hazard-safe: "
                  f"{r['hazard_safe']['days']} repaired days with true rain >= 50 mm, share repaired >= 50% of truth "
                  f"{_f(r['hazard_safe']['share_repaired_ge_half_truth'], 3)}.", ""]
    stab = report["seed_stability"]
    lines += ["## Stability across injection seeds (TEST stations, engine trained once)", "",
              "| seed | macro recall (score @1%) | macro recall (full engine) | full-engine false-flag rate |", "|---|---|---|---|"]
    for name, entry in stab["by_seed"].items():
        lines.append(f"| {name} | {_f(entry['score_at_1pct']['macro_recall'], 3)} | "
                     f"{_f(entry['full_engine_flags']['macro_recall'], 3)} | {_f(entry['full_engine_flags']['achieved_fpr'], 4)} |")
    for label, s in stab["summary"].items():
        lines.append(f"| {label}: mean [min, max] | {_f(s['macro_recall_mean'], 3)} [{_f(s['macro_recall_min'], 3)}, "
                     f"{_f(s['macro_recall_max'], 3)}] | | |")
    lines += ["", "Per-type range (score @1%): " + "; ".join(
        f"{t} {_f(v['mean'], 2)} [{_f(v['min'], 2)}, {_f(v['max'], 2)}]" for t, v in stab["summary"]["score_at_1pct"]["per_type"].items()), ""]
    sanity = report["real_flag_sanity"]
    lines += ["## Real NOAA flags 2007-2024 (sanity check)", "",
              f"n = {sanity['n_flagged_values']} real flagged values ({sanity['by_flag']}), 2007+ only: too few to rank "
              "methods. Real flags are single-day O/G/S extremes, not streaks or duplicates.", "",
              "| method | real flags flagged | by NOAA flag | false-flag rate on unflagged days |", "|---|---|---|---|"]
    for name, row in sanity["methods"].items():
        lines.append(f"| {name} | {row['flagged_real']} / {sanity['n_flagged_values']} | {row['by_flag']} | "
                     f"{_f(row['false_flag_rate_on_unflagged_valid_days'], 4)} |")
    diag = report["false_flag_diagnosis"]
    lines += ["", "## Combined engine at the VAL-chosen threshold: realised false-flag rate and macro recall", "",
              "| target | combined tau | VAL realised fpr | VAL macro recall | TEST realised fpr | TEST macro recall |",
              "|---|---|---|---|---|---|"]
    for level, r in report["tau_combined"].items():
        lines.append(f"| {level} | {_f(r['tau'], 3)} | {_f(r['val']['achieved_fpr'], 4)} | {_f(r['val']['macro_recall'], 3)} | "
                     f"{_f(r['test']['achieved_fpr'], 4)} | {_f(r['test']['macro_recall'], 3)} |")
    lines += ["", "Secondary: the MODEL-ONLY threshold (no L1, no arbiter) at the same targets:", "",
              "| target | model-only tau | VAL realised fpr | VAL macro recall | TEST realised fpr | TEST macro recall |",
              "|---|---|---|---|---|---|"]
    for level, r in report["tau_transfer_model_only"].items():
        lines.append(f"| {level} | {_f(r['tau'], 3)} | {_f(r['val']['achieved_fpr'], 4)} | {_f(r['val']['macro_recall'], 3)} | "
                     f"{_f(r['test']['achieved_fpr'], 4)} | {_f(r['test']['macro_recall'], 3)} |")
    lines += ["", "## Why the realised TEST false-flag rate differs from the target", "",
              f"- Combined engine at the 1% target: VAL {_f(diag['val_combined_fpr'], 4)}, TEST {_f(diag['test_combined_fpr'], 4)} "
              f"(without the arbiter: VAL {_f(diag['val_combined_no_arbiter_fpr'], 4)}, TEST {_f(diag['test_combined_no_arbiter_fpr'], 4)}).",
              f"- Union effect: L1 alone flags {_f(diag['val_l1_only_fpr'], 4)} of VAL and {_f(diag['test_l1_only_fpr'], 4)} of TEST "
              f"clean days; the combined tau ({_f(diag['tau_combined_1pct'], 4)}) vs the model-only tau "
              f"({_f(diag['tau_model_only_1pct'], 4)}) accounts for it on VAL.",
              f"- Isotonic ties: {diag['val_clean_unique_scores']} distinct calibrated scores over {diag['val_clean_days']} VAL clean "
              f"days; {_f(diag['val_share_of_clean_scores_equal_to_tau_model'], 5)} of them equal the model-only tau, so plateau "
              "ties do not move the rate.",
              f"- Clean-day definition: {diag['clean_day_definition']}.",
              f"- Model-only flags at the model-only tau: VAL {_f(diag['val_model_only_fpr_at_tau_model'], 4)}, TEST "
              f"{_f(diag['test_model_only_fpr_at_tau_model'], 4)}.",
              f"- Concentration: {diag['nepal_false_flags']} of {diag['test_false_flags']} TEST false flags "
              f"({diag['nepal_share_of_test_false_flags']:.0%}) come from the two Nepal stations, which hold "
              f"{diag['nepal_share_of_test_clean_days']:.0%} of the TEST clean days; the other TEST stations realise "
              f"{_f(diag['test_fpr_excluding_nepal'], 4)}. Both Nepal stations are in TEST (none in TRAIN or VAL).",
              f"- Nepal model false flags by month: {diag['nepal_model_false_flags_by_month']}; by predicted class: "
              f"{diag['nepal_model_false_flags_by_predicted_class']}.",
              f"- Missing references do not explain it: VAL model false-flag rate with columns removed "
              f"{ {k: round(v, 4) for k, v in diag['val_model_fpr_with_columns_missing'].items()} }.", "",
              "| TEST station | country | upland | clean days | false flags | rate |", "|---|---|---|---|---|---|"]
    for row in diag["test_top_stations"]:
        lines.append(f"| {row['station']} | {row['country']} | {row['upland']} | {row['clean_days']} | {row['false_flags']} | "
                     f"{_f(row['rate'], 4)} |")
    ex = report["evaluation"]["test_ex_nepal"]
    lines += ["", f"### TEST without the two Nepal stations ({ex['n_stations']} stations; post-hoc sensitivity, not used for any "
              "selection)", "", "| method | " + " | ".join(types) + " | macro |", "|---|" + "---|" * (len(types) + 1)]
    for name, result in ex["methods"].items():
        lines.append(f"| {name} | " + " | ".join(_rec(result, t) for t in types) + f" | {_f(result['macro_recall'], 2)} |")
    lines.append("")
    sup = report["oof"]["supplement"]
    lines += ["", f"## SUPPLEMENT: 5-fold station-grouped cross-validation ({sup['n_stations']} stations with episodes)", "",
              "Held-out stations scored by engines trained on the other folds (frozen-seed dataset only); NOT the headline.", "",
              "| method | " + " | ".join(types) + " | macro |", "|---|" + "---|" * (len(types) + 1)]
    for name, result in sup["methods"].items():
        lines.append(f"| {name} | " + " | ".join(_rec(result, t) for t in types) + f" | {_f(result['macro_recall'], 2)} |")
    o = report["oof"]["outputs"]
    lines += ["", f"OOF outputs (real series, `engine_outputs_2007_oof.parquet`): {o['rows']} rows, trust NaN share "
              f"{_f(o['trust_nan_share'], 3)} (days without a value), flagged {_f(o['flagged_share_of_observed'], 4)} of "
              f"observed days, {o['genuine_extreme_days']} genuine-extreme days, {o['memory_mb']} MB.", ""]
    gate = report["gate_assessment"]
    lines += ["## Gate assessment (TEST)", "", gate["statement"], "",
              "### Primary: the combined engine at the VAL-chosen 1% tau against each baseline (recall CIs over stations)", ""]
    lines += [f"- {line}" for line in gate["primary"]]
    lines += ["", "### Secondary: the model score alone at a matched 1% on the TEST clean days", ""]
    lines += [f"- {line}" for line in gate["secondary_model_score"]]
    lines += ["", "### Oracle-matched comparison (tau picked on TEST to equal noaa_style_qa_wide's false-flag rate; not deployable)", ""]
    lines += [f"- {line}" for line in gate["oracle_matched"]]
    lines += ["", "Limits: only 11 TEST stations (and 11 VAL) carry injected episodes and scale_drift has the fewest; the "
              "CHIRPS-aligned reference correlates only about 0.38 with the stations; IMD is not independent of the gauges "
              "(arbiter variants with and without IMD are both reported); every fault is injected into real series, so "
              "recall measures detection of synthetic faults, not of the faults real gauges produce (the 10 real flags "
              "are too few to say); references exist only from 2007, so none of the 1990-2004 clean data is used.", "",
              f"Runtime (s): {report['timings_s']}.", ""]
    return "\n".join(lines)


def write_reports(report: dict, out_dir=None) -> tuple[Path, Path]:
    out = Path(out_dir) if out_dir is not None else reports_dir()
    out.mkdir(parents=True, exist_ok=True)
    md, js = out / "phase2_integrity_report.md", out / "phase2_integrity_report.json"
    js.write_text(dumps_strict(report), encoding="utf-8", newline="\n")
    md.write_text(render_markdown(report), encoding="utf-8", newline="\n")
    return md, js


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw-dir", default=None)
    parser.add_argument("--reports-dir", default=None)
    parser.add_argument("--n-boot", type=int, default=N_BOOT)
    args = parser.parse_args(argv)
    data = load_data(args.raw_dir)
    report, _ = build_report(data, args.n_boot)
    md, js = write_reports(report, args.reports_dir)
    print(f"wrote {display_path(md)} and {display_path(js)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
