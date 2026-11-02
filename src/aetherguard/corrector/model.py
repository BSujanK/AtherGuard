"""LightGBM quantile regressors (alpha 0.5 / 0.9 / 0.99) and an exceedance classifier for the corrector.

Training uses the TRAIN stations; a small fixed grid (num_leaves {7, 15} x min_data_in_leaf {50, 200}; {20, 50} for the
rare-event classifier) is chosen per target on the VAL stations (lowest VAL pinball loss / log-loss, early stopping
on the same VAL rows, up to 600 rounds, patience 40); every candidate's score is stored in the card. The exceedance
probability is calibrated by isotonic regression on the VAL rows. Quantile predictions are made monotone
(q50 <= q90 <= q99) and never negative.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression

ALPHAS = (0.5, 0.9, 0.99)
QUANTILE_GRID = tuple({"num_leaves": nl, "min_data_in_leaf": md} for nl in (7, 15) for md in (50, 200))
CLASSIFIER_GRID = tuple({"num_leaves": nl, "min_data_in_leaf": md} for nl in (7, 15) for md in (20, 50))
BASE_PARAMS = {"learning_rate": 0.05, "feature_fraction": 0.8, "bagging_fraction": 0.8, "bagging_freq": 1,
               "lambda_l2": 1.0, "verbosity": -1, "num_threads": 4, "deterministic": True, "force_row_wise": True}
MAX_ROUNDS = 600
PATIENCE = 40
CALIBRATION_BLEND = 1e-6


def pinball(y, pred, alpha: float) -> np.ndarray:
    """Per-row pinball (quantile) loss."""
    diff = np.asarray(y, dtype=np.float64) - np.asarray(pred, dtype=np.float64)
    return np.maximum(alpha * diff, (alpha - 1.0) * diff)


def _train(X, y, Xv, yv, params: dict, seed: int, columns: list[str]):
    full = {**BASE_PARAMS, **params, "seed": seed, "bagging_seed": seed, "feature_fraction_seed": seed}
    dtrain = lgb.Dataset(X, y, feature_name=columns, free_raw_data=False)
    dval = lgb.Dataset(Xv, yv, reference=dtrain, feature_name=columns, free_raw_data=False)
    return lgb.train(full, dtrain, num_boost_round=MAX_ROUNDS, valid_sets=[dval],
                     callbacks=[lgb.early_stopping(PATIENCE, verbose=False), lgb.log_evaluation(0)])


@dataclass
class CorrectorModel:
    columns: list[str]
    quantiles: dict[float, lgb.Booster]
    classifier: lgb.Booster | None
    iso_x: list[float]
    iso_y: list[float]
    card: dict = field(default_factory=dict)

    def predict(self, X: pd.DataFrame) -> pd.DataFrame:
        """q50 / q90 / q99 (mm) and the calibrated exceedance probability for rows of predictor columns."""
        data = X[self.columns].to_numpy(np.float32)
        q = np.column_stack([self.quantiles[a].predict(data) for a in ALPHAS])
        q = np.maximum.accumulate(np.maximum(q, 0.0), axis=1)
        out = pd.DataFrame({"q50": q[:, 0], "q90": q[:, 1], "q99": q[:, 2]}, index=X.index)
        if self.classifier is not None:
            raw = np.asarray(self.classifier.predict(data))
            out["p_exceed"] = (1 - CALIBRATION_BLEND) * np.interp(raw, self.iso_x, self.iso_y) + CALIBRATION_BLEND * raw
        else:
            out["p_exceed"] = np.nan
        return out

    def save(self, directory) -> None:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        for alpha, booster in self.quantiles.items():
            booster.save_model(str(directory / f"quantile_{alpha}.txt"))
        if self.classifier is not None:
            self.classifier.save_model(str(directory / "exceedance.txt"))
        (directory / "model.json").write_text(json.dumps({
            "columns": self.columns, "alphas": list(self.quantiles), "iso_x": self.iso_x, "iso_y": self.iso_y,
            "has_classifier": self.classifier is not None}, indent=1) + "\n", encoding="utf-8")
        (directory / "card.json").write_text(json.dumps(self.card, indent=1, allow_nan=False, default=_plain) + "\n",
                                             encoding="utf-8")

    @classmethod
    def load(cls, directory) -> "CorrectorModel":
        directory = Path(directory)
        meta = json.loads((directory / "model.json").read_text(encoding="utf-8"))
        quantiles = {float(a): lgb.Booster(model_file=str(directory / f"quantile_{a}.txt")) for a in meta["alphas"]}
        classifier = lgb.Booster(model_file=str(directory / "exceedance.txt")) if meta["has_classifier"] else None
        card = json.loads((directory / "card.json").read_text(encoding="utf-8"))
        return cls(meta["columns"], quantiles, classifier, meta["iso_x"], meta["iso_y"], card)


def _plain(obj):
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return None if not np.isfinite(obj) else float(obj)
    raise TypeError(type(obj).__name__)


def fit_corrector(train: pd.DataFrame, val: pd.DataFrame, columns: list[str], seed: int,
                  quantile_grid=QUANTILE_GRID, classifier_grid=CLASSIFIER_GRID) -> CorrectorModel:
    """Fit the three quantile models and the exceedance classifier (see the module doc)."""
    X, Xv = train[columns].to_numpy(np.float32), val[columns].to_numpy(np.float32)
    candidates: dict = {}
    quantiles = {}
    for alpha in ALPHAS:
        best = None
        candidates[str(alpha)] = []
        for params in quantile_grid:
            booster = _train(X, train["gauge"].to_numpy(), Xv, val["gauge"].to_numpy(),
                             {"objective": "quantile", "alpha": alpha, "metric": "quantile", **params}, seed, columns)
            score = float(pinball(val["gauge"], booster.predict(Xv, num_iteration=booster.best_iteration), alpha).mean())
            candidates[str(alpha)].append({"params": params, "val_pinball": score, "best_iteration": int(booster.best_iteration)})
            if best is None or score < best[0]:
                best = (score, booster, params)
        quantiles[alpha] = best[1]
        candidates[str(alpha)] = {"selected": best[2], "candidates": candidates[str(alpha)]}
    tr, va = train[train["exceed"].notna()], val[val["exceed"].notna()]
    classifier, iso_x, iso_y = None, [0.0, 1.0], [0.0, 1.0]
    if tr["exceed"].sum() > 0 and va["exceed"].sum() > 0:
        best = None
        candidates["exceedance"] = []
        for params in classifier_grid:
            booster = _train(tr[columns].to_numpy(np.float32), tr["exceed"].to_numpy(), va[columns].to_numpy(np.float32),
                             va["exceed"].to_numpy(), {"objective": "binary", "metric": "binary_logloss", **params}, seed, columns)
            p = np.clip(booster.predict(va[columns].to_numpy(np.float32), num_iteration=booster.best_iteration), 1e-9, 1 - 1e-9)
            y = va["exceed"].to_numpy()
            score = float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean())
            candidates["exceedance"].append({"params": params, "val_logloss": score, "best_iteration": int(booster.best_iteration)})
            if best is None or score < best[0]:
                best = (score, booster, params)
        classifier = best[1]
        raw = np.asarray(classifier.predict(va[columns].to_numpy(np.float32)))
        iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip").fit(raw, va["exceed"].to_numpy())
        iso_x, iso_y = [float(v) for v in iso.X_thresholds_], [float(v) for v in iso.y_thresholds_]
        candidates["exceedance_selected"] = best[2]
    card = {"columns": columns, "seed": seed, "train_rows": int(len(train)), "val_rows": int(len(val)),
            "train_stations": int(train["station"].nunique()), "val_stations": int(val["station"].nunique()),
            "train_exceedances": int(tr["exceed"].sum()), "val_exceedances": int(va["exceed"].sum()),
            "tuning": candidates}
    return CorrectorModel(columns, quantiles, classifier, iso_x, iso_y, card)


def linear_quantile_baseline(train: pd.DataFrame, column: str = "chirps_1") -> dict[float, tuple[float, float]]:
    """Simple linear quantile scaling q_alpha = a * chirps + b fitted on the TRAIN rows (sklearn QuantileRegressor)."""
    from sklearn.linear_model import QuantileRegressor
    X = train[[column]].to_numpy(np.float64)
    out = {}
    for alpha in ALPHAS:
        fit = QuantileRegressor(quantile=alpha, alpha=0.0, solver="highs").fit(X, train["gauge"].to_numpy())
        out[alpha] = (float(fit.coef_[0]), float(fit.intercept_))
    return out


def apply_linear(coefs: dict[float, tuple[float, float]], chirps) -> pd.DataFrame:
    x = np.asarray(chirps, dtype=np.float64)
    q = np.column_stack([np.maximum(coefs[a][0] * x + coefs[a][1], 0.0) for a in ALPHAS])
    q = np.maximum.accumulate(q, axis=1)
    return pd.DataFrame({"q50": q[:, 0], "q90": q[:, 1], "q99": q[:, 2]})
