"""The learned layer of the integrity engine: one LightGBM multiclass model (ok + 6 faults), isotonic calibration
of P(any fault) and the operating thresholds.

Training rows (one per station-day with an observed value):
* class 0 `ok`: clean real days outside every episode window;
* classes 1..6: the days an injector changed a value (`fault_type`);
* EXCLUDED: unchanged days inside an episode window, flagged / not-clean real days, days without a value.

Documented choices
* class weights: sqrt of the inverse class frequency, w_c = sqrt(N / (K n_c)) (the threshold is chosen on clean
  days at a fixed false-flag rate, so full balancing is not needed and it would over-trust rare classes);
* reference dropout (option, default on): each of the nbr_ / grid_ / wet_ groups is independently set to NaN on
  30% of the TRAINING rows, so the model copes with missing references (it never touches VAL / TEST rows);
* hyper-parameter grid: num_leaves {15, 31} x min_child_samples {20, 60}, learning rate 0.1, up to 600 rounds
  with early stopping (30 rounds) on the VAL multiclass log-loss; the winner has the best VAL macro recall at a
  1% clean false-flag rate (ties: lower VAL log-loss). Every candidate's scores are stored;
* calibration: isotonic regression of P(any fault) = 1 - P(ok) on the VAL rows; the stored calibrated value is
  (1 - 1e-6) * isotonic + 1e-6 * raw, which keeps the isotonic plateaus strictly ordered by the raw score;
* tau_model: the calibrated-probability threshold with at most the target false-flag rate on the VAL clean
  days (model flags only); the engine then re-selects tau on the combined decision (see engine.py).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression

from . import features as feature_mod
from .inject import FAULT_TYPES

CLASSES = ("ok",) + FAULT_TYPES
N_CLASSES = len(CLASSES)
DROPOUT_GROUPS = ("nbr_", "grid_", "wet_")
DROPOUT_RATE = 0.3
FPR_LEVELS = (0.005, 0.01, 0.02)
HEADLINE_FPR = 0.01
PARAM_GRID = tuple({"num_leaves": nl, "min_child_samples": mc} for nl in (15, 31) for mc in (20, 60))
BASE_PARAMS = {"objective": "multiclass", "num_class": N_CLASSES, "learning_rate": 0.1, "feature_fraction": 0.8,
               "bagging_fraction": 0.8, "bagging_freq": 1, "lambda_l2": 1.0, "verbosity": -1, "num_threads": 4,
               "deterministic": True, "force_row_wise": True}
MAX_ROUNDS = 600
EARLY_STOPPING_ROUNDS = 30
CALIBRATION_BLEND = 1e-6


def label_rows(table: pd.DataFrame) -> np.ndarray:
    """Class index per row of a fault table: 0 ok, 1..6 fault type, -1 excluded."""
    observed = table["value_obs"].notna().to_numpy()
    changed = (table["fault_type"].astype(str) != "").to_numpy()
    ok = (table["clean_real"] & (table["episode_id"] < 0)).to_numpy()
    y = np.full(len(table), -1, dtype=np.int8)
    y[ok & observed] = 0
    codes = table["fault_type"].astype(str).map({name: i + 1 for i, name in enumerate(FAULT_TYPES)})
    fault = changed & observed
    y[fault] = codes.to_numpy()[fault].astype(np.int8)
    return y


def check_aligned(features: pd.DataFrame, table: pd.DataFrame) -> None:
    if (len(features) != len(table)
            or not (features["station"].to_numpy() == table["station"].astype(str).to_numpy()).all()
            or not (features["date"].to_numpy() == table["date"].to_numpy()).all()):
        raise ValueError("features and fault table must list the same station-days in the same order")


@dataclass
class Rows:
    """Model-ready rows: float32 matrix, class labels (0..6) and the (station, date) keys."""
    X: np.ndarray
    y: np.ndarray
    station: np.ndarray
    date: np.ndarray
    columns: list[str]
    idx: np.ndarray | None = None   # row positions in the source features table (None after concatenation)


def assemble_rows(features: pd.DataFrame, table: pd.DataFrame, stations, groups=feature_mod.PREFIXES) -> Rows:
    """Rows of `stations` with a class label (see module doc), using the columns of `groups` only."""
    check_aligned(features, table)
    columns = feature_mod.select_columns([c for c in features.columns if c not in ("station", "date")], groups)
    y = label_rows(table)
    keep = (y >= 0) & features["station"].isin(set(stations)).to_numpy()
    X = features.loc[keep, columns].to_numpy(np.float32)
    return Rows(X, y[keep].astype(int), features["station"].to_numpy()[keep], features["date"].to_numpy()[keep],
                columns, np.flatnonzero(keep))


def concat_rows(parts: list[Rows]) -> Rows:
    return Rows(np.concatenate([p.X for p in parts]), np.concatenate([p.y for p in parts]),
                np.concatenate([p.station for p in parts]), np.concatenate([p.date for p in parts]), parts[0].columns)


def class_weights(y: np.ndarray) -> np.ndarray:
    """Per-class weight sqrt(N / (K n_c)); classes absent from `y` get weight 1."""
    counts = np.bincount(y, minlength=N_CLASSES).astype(float)
    weights = np.ones(N_CLASSES)
    present = counts > 0
    weights[present] = np.sqrt(len(y) / (present.sum() * counts[present]))
    return weights


def reference_dropout(X: np.ndarray, columns: list[str], seed: int, rate: float = DROPOUT_RATE) -> np.ndarray:
    """Copy of X with each present reference group independently NaN on `rate` of the rows."""
    out = X.copy()
    rng = np.random.default_rng(seed)
    for prefix in DROPOUT_GROUPS:
        idx = [i for i, c in enumerate(columns) if c.startswith(prefix)]
        if idx:
            hit = rng.random(len(out)) < rate
            out[np.ix_(hit, idx)] = np.nan
    return out


def macro_recall_at_fpr(p_any: np.ndarray, y: np.ndarray, fpr: float = HEADLINE_FPR) -> tuple[float, dict]:
    """Row-level macro recall of P(any fault) at `fpr` false flags on the class-0 rows."""
    clean = p_any[y == 0]
    threshold = np.quantile(clean, 1 - fpr, method="higher")
    recalls = {CLASSES[c]: float((p_any[y == c] > threshold).mean()) for c in range(1, N_CLASSES) if (y == c).any()}
    return (float(np.mean(list(recalls.values()))) if recalls else float("nan")), recalls


def _calibration_points(iso: IsotonicRegression) -> tuple[list[float], list[float]]:
    return [float(v) for v in iso.X_thresholds_], [float(v) for v in iso.y_thresholds_]


@dataclass
class ModelBundle:
    """A trained booster with its calibration and thresholds (everything needed to score feature rows)."""
    booster: lgb.Booster
    columns: list[str]
    iso_x: list[float]
    iso_y: list[float]
    tau: dict[str, float]
    card: dict = field(default_factory=dict)
    tau_model: dict[str, float] = field(default_factory=dict)   # model-only thresholds (`tau` is the combined one)

    def proba(self, X: np.ndarray) -> np.ndarray:
        return np.asarray(self.booster.predict(np.asarray(X, dtype=np.float32)))

    @staticmethod
    def p_any_raw(proba: np.ndarray) -> np.ndarray:
        return 1.0 - proba[:, 0]

    def calibrate(self, p_raw: np.ndarray) -> np.ndarray:
        iso = np.interp(p_raw, self.iso_x, self.iso_y)
        return (1 - CALIBRATION_BLEND) * iso + CALIBRATION_BLEND * p_raw

    def score(self, X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """(calibrated P(any fault), class probabilities) per row."""
        proba = self.proba(X)
        return self.calibrate(self.p_any_raw(proba)), proba


def tau_for(p_cal_clean: np.ndarray, fpr: float) -> float:
    """Smallest threshold with at most `fpr` of the clean calibrated scores above it."""
    return float(np.quantile(p_cal_clean, 1 - fpr, method="higher"))


def fit_bundle(train: Rows, val: Rows, params: dict, seed: int, dropout: bool = True,
               rounds: int | None = None) -> tuple[ModelBundle, dict]:
    """Train on `train`, early-stop on `val` (log-loss), calibrate and set thresholds on `val`.

    `rounds` fixes the number of boosting rounds (no early stopping) when given. Returns (bundle, scores)."""
    X = reference_dropout(train.X, train.columns, seed) if dropout else train.X
    weight = class_weights(train.y)[train.y]
    full = {**BASE_PARAMS, **params, "seed": seed, "bagging_seed": seed, "feature_fraction_seed": seed}
    dtrain = lgb.Dataset(X, train.y, weight=weight, feature_name=train.columns, free_raw_data=False)
    dval = lgb.Dataset(val.X, val.y, reference=dtrain, feature_name=train.columns, free_raw_data=False)
    callbacks = [lgb.log_evaluation(0)]
    if rounds is None:
        callbacks.append(lgb.early_stopping(EARLY_STOPPING_ROUNDS, verbose=False))
    booster = lgb.train(full, dtrain, num_boost_round=rounds or MAX_ROUNDS, valid_sets=[dval], callbacks=callbacks)
    proba = np.asarray(booster.predict(val.X, num_iteration=booster.best_iteration or None))
    p_raw = 1.0 - proba[:, 0]
    iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip").fit(p_raw, (val.y > 0).astype(float))
    xs, ys = _calibration_points(iso)
    bundle = ModelBundle(booster, train.columns, xs, ys, {}, {})
    p_cal = bundle.calibrate(p_raw)
    bundle.tau = {str(f): tau_for(p_cal[val.y == 0], f) for f in FPR_LEVELS}
    bundle.tau_model = dict(bundle.tau)
    macro, per_class = macro_recall_at_fpr(p_raw, val.y)
    eps = 1e-12
    logloss = float(-np.log(np.clip(proba[np.arange(len(val.y)), val.y], eps, 1)).mean())
    scores = {"val_macro_recall_at_1pct": macro, "val_recall_by_class": per_class, "val_logloss": logloss,
              "best_iteration": int(booster.best_iteration or booster.current_iteration()), "params": params}
    return bundle, scores


def search(train: Rows, val: Rows, seed: int, dropout: bool = True, grid=None):
    """Fit every candidate of `grid`; choose by VAL macro recall at 1% (ties: lower log-loss).

    Returns (best bundle, best params, list of every candidate's scores)."""
    candidates, best = [], None
    for params in (PARAM_GRID if grid is None else grid):
        bundle, scores = fit_bundle(train, val, dict(params), seed, dropout)
        candidates.append(scores)
        key = (scores["val_macro_recall_at_1pct"], -scores["val_logloss"])
        if best is None or key > best[0]:
            best = (key, bundle, dict(params), scores)
    _, bundle, params, scores = best
    bundle.card = {"selected_params": params, "candidates": candidates, "val_scores": scores}
    return bundle, params, candidates


def save_bundle(bundle: ModelBundle, directory) -> None:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    bundle.booster.save_model(str(directory / "model.txt"))
    (directory / "bundle.json").write_text(json.dumps({
        "columns": bundle.columns, "iso_x": bundle.iso_x, "iso_y": bundle.iso_y, "tau": bundle.tau,
        "tau_model": bundle.tau_model,
        "calibration_blend": CALIBRATION_BLEND, "classes": list(CLASSES)}, indent=1) + "\n", encoding="utf-8")


def load_bundle(directory) -> ModelBundle:
    directory = Path(directory)
    meta = json.loads((directory / "bundle.json").read_text(encoding="utf-8"))
    booster = lgb.Booster(model_file=str(directory / "model.txt"))
    return ModelBundle(booster, meta["columns"], meta["iso_x"], meta["iso_y"], meta["tau"], {},
                       meta.get("tau_model", meta["tau"]))
