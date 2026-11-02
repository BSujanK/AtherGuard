"""CatBoost counterpart of the LightGBM helpers in `hazard.model` (fit with early stopping, raw-score prediction, SHAP).

Same training population and weights as LightGBM (`data.training_frame`), the same monotone-constraint vector
(+1 / -1 / 0 per input, from the configuration's fnmatch patterns), the same learning rate, maximum rounds and early
stopping rule. CatBoost's own regularisation grid is depth x l2_leaf_reg (`challengers.catboost.grid` of the
configuration). Missing values stay NaN (CatBoost's default `nan_mode=Min` sorts them below every observed value, which
is consistent with the monotone constraints). Nothing is written to disk by fitting (`allow_writing_files=False`).

Early stopping trains up to `max_rounds` trees and stops `early_stopping_rounds` after the best held-out weighted
log-loss and returns the best tree COUNT, as in `model.fit_booster`. Unlike LightGBM, a CatBoost model trained for N
rounds is NOT the first N trees of a longer run (the sequence depends on the planned `iterations`), so a model with a
chosen tree count is always refitted with exactly that many rounds (`num_rounds`).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier, Pool

from . import data as hd
from .model import feature_matrix

MAX_THREADS = 6


def catboost_params(hp: dict, constraints, seed: int, settings: dict, thread_count: int = MAX_THREADS) -> dict:
    """Constructor arguments. `hp` carries depth, l2_leaf_reg and learning_rate; `settings` is the `training` section."""
    return {"loss_function": "Logloss", "eval_metric": "Logloss", "iterations": settings["max_rounds"],
            "depth": int(hp["depth"]), "l2_leaf_reg": float(hp["l2_leaf_reg"]),
            "learning_rate": float(hp["learning_rate"]), "random_seed": int(seed),
            "thread_count": min(int(thread_count), MAX_THREADS), "monotone_constraints": [int(c) for c in constraints],
            "allow_writing_files": False, "verbose": 0}


def _pool(frame: pd.DataFrame, columns, weighted: bool = True) -> Pool:
    return Pool(feature_matrix(frame, columns), label=frame["label"].to_numpy(),
                weight=frame["sample_weight"].to_numpy() if weighted else None)


def fit_catboost(train: pd.DataFrame, columns, constraints, hp: dict, seed: int, settings: dict, *,
                 valid: pd.DataFrame | None = None, num_rounds: int | None = None,
                 thread_count: int = MAX_THREADS) -> tuple[CatBoostClassifier, int]:
    """Fit on `train` (in-domain development rows only; rows carry `label` and `sample_weight`).

    With `valid`, train up to `settings.max_rounds` trees and stop when the weighted held-out log-loss has not improved
    for `settings.early_stopping_rounds` rounds; returns the model (all trained trees kept) and the best tree count
    (use it only to choose `num_rounds`). Without `valid`, train exactly `num_rounds` trees.
    """
    hd.assert_training_rows(train)
    params = catboost_params(hp, constraints, seed, settings, thread_count)
    if valid is None:
        if num_rounds is None:
            raise ValueError("either `valid` (early stopping) or `num_rounds` is required")
        model = CatBoostClassifier(**{**params, "iterations": int(num_rounds)})
        model.fit(_pool(train, columns))
        return model, int(num_rounds)
    hd.assert_training_rows(valid)
    model = CatBoostClassifier(**params, od_type="Iter", od_wait=settings["early_stopping_rounds"],
                               use_best_model=False)
    model.fit(_pool(train, columns), eval_set=_pool(valid, columns))
    return model, int(model.get_best_iteration()) + 1


def predict_raw(model: CatBoostClassifier, frame: pd.DataFrame, columns) -> np.ndarray:
    """P(label = 1) under the training mix, all trees of the model."""
    return model.predict(Pool(feature_matrix(frame, columns)), prediction_type="Probability")[:, 1]


def contributions(model: CatBoostClassifier, frame: pd.DataFrame, columns) -> np.ndarray:
    """(n, len(columns)) SHAP values in log-odds of the raw score. The bias column CatBoost appends is dropped."""
    values = model.get_feature_importance(Pool(feature_matrix(frame, columns)), type="ShapValues")
    return values[:, :-1]
