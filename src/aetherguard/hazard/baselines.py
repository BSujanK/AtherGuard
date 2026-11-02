"""Reference scorers the hazard model must beat (Phase 3c), all fitted on TRAIN rows only.

Every baseline exposes `fit(...)`, `score(frame) -> float64 array` (higher = more hazardous, so ROC / PR /
alert-share metrics apply) and `params()` (JSON-serialisable fitted values). A frame row whose inputs are missing
scores `-inf` (never alerts) for the two rule baselines; the logistic baseline imputes the train median and adds
missing-value indicators.

1. `IntensityDuration`: threshold_N = 10th percentile of the train in-domain positives' `rain_acc_N`, N in
   {1,3,5,7,14,30} (90% of train positives exceed it); score = max over N of acc_N / threshold_N, ignoring missing
   windows. An alert at score >= 1 is the classic "any duration exceeded" rule. Windows whose threshold is not
   positive carry no information and are skipped.
2. `LhasaStyle`: susceptibility class 1..5 = quintile of `stat_slope_mean` among the train candidate cells (edges
   from the unique cells of the train universe); trigger ratio = `rain_acc3_vs_clim` (3-day rain over the cell's
   train-period mean 3-day total for that month, floored at 1 mm; NOT a true 95th percentile); score =
   class * ratio. The published-style rule alert is class >= 3 and ratio >= 3.
3. `LogisticBaseline`: sklearn logistic regression (median imputation with missing-value indicators, standardised,
   class-weighted) on rain_acc_1/3/7/30, rain_acc3_vs_clim, wet_top, stat_slope_mean.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .data import assert_training_rows, in_domain_positives, training_frame

DURATIONS = (1, 3, 5, 7, 14, 30)
THRESHOLD_PERCENTILE = 10.0
N_SUSCEPTIBILITY_CLASSES = 5
TRIGGER_RATIO = 3.0
RULE_MIN_CLASS = 3
LOGISTIC_COLUMNS = ("rain_acc_1", "rain_acc_3", "rain_acc_7", "rain_acc_30", "rain_acc3_vs_clim", "wet_top",
                    "stat_slope_mean")


def _require(frame: pd.DataFrame, columns) -> None:
    missing = [c for c in columns if c not in frame.columns]
    if missing:
        raise ValueError(f"frame lacks required columns {missing}")


def _nan_to_neg_inf(values: np.ndarray) -> np.ndarray:
    return np.where(np.isnan(values), -np.inf, values)


class IntensityDuration:
    name = "intensity_duration"

    def __init__(self) -> None:
        self.thresholds: dict[int, float] = {}

    def fit(self, train: pd.DataFrame) -> "IntensityDuration":
        assert_training_rows(train)
        columns = [f"rain_acc_{n}" for n in DURATIONS]
        _require(train, columns)
        positives = in_domain_positives(train)
        if positives.empty:
            raise ValueError("no in-domain train positives to fit the intensity-duration thresholds on")
        fitted = {n: float(np.nanpercentile(positives[f"rain_acc_{n}"].to_numpy(np.float64), THRESHOLD_PERCENTILE))
                  for n in DURATIONS}
        self.thresholds = {n: t for n, t in fitted.items() if t > 0}
        if not self.thresholds:
            raise ValueError("no positive intensity-duration threshold could be fitted")
        return self

    def score(self, frame: pd.DataFrame) -> np.ndarray:
        _require(frame, [f"rain_acc_{n}" for n in self.thresholds])
        ratios = np.column_stack([frame[f"rain_acc_{n}"].to_numpy(np.float64) / t for n, t in self.thresholds.items()])
        return _nan_to_neg_inf(ratios).max(axis=1)

    def params(self) -> dict:
        return {"percentile": THRESHOLD_PERCENTILE, "thresholds_mm": {str(n): t for n, t in self.thresholds.items()}}


class LhasaStyle:
    name = "lhasa_style"

    def __init__(self) -> None:
        self.edges: np.ndarray | None = None

    def fit(self, universe_train: pd.DataFrame) -> "LhasaStyle":
        assert_training_rows(universe_train)
        _require(universe_train, ["cell_id", "stat_slope_mean"])
        cells = universe_train.drop_duplicates("cell_id")["stat_slope_mean"].to_numpy(np.float64)
        quantiles = np.arange(1, N_SUSCEPTIBILITY_CLASSES) / N_SUSCEPTIBILITY_CLASSES
        self.edges = np.quantile(cells, quantiles)
        return self

    def susceptibility(self, frame: pd.DataFrame) -> np.ndarray:
        _require(frame, ["stat_slope_mean"])
        return np.searchsorted(self.edges, frame["stat_slope_mean"].to_numpy(np.float64), side="right") + 1.0

    def score(self, frame: pd.DataFrame) -> np.ndarray:
        _require(frame, ["rain_acc3_vs_clim"])
        return _nan_to_neg_inf(self.susceptibility(frame) * frame["rain_acc3_vs_clim"].to_numpy(np.float64))

    def rule_alert(self, frame: pd.DataFrame) -> np.ndarray:
        ratio = frame["rain_acc3_vs_clim"].to_numpy(np.float64)
        return (self.susceptibility(frame) >= RULE_MIN_CLASS) & (ratio >= TRIGGER_RATIO)

    def params(self) -> dict:
        return {"n_classes": N_SUSCEPTIBILITY_CLASSES, "slope_mean_class_edges": self.edges.tolist(),
                "trigger_ratio": TRIGGER_RATIO, "rule_min_class": RULE_MIN_CLASS}


class LogisticBaseline:
    name = "logistic"

    def __init__(self) -> None:
        self.pipeline = None

    def fit(self, train: pd.DataFrame) -> "LogisticBaseline":
        assert_training_rows(train)
        _require(train, list(LOGISTIC_COLUMNS) + ["label"])
        self.pipeline = make_pipeline(
            SimpleImputer(strategy="median", add_indicator=True), StandardScaler(),
            LogisticRegression(class_weight="balanced", max_iter=5000))
        self.pipeline.fit(train[list(LOGISTIC_COLUMNS)].astype(np.float64), train["label"].to_numpy())
        return self

    def score(self, frame: pd.DataFrame) -> np.ndarray:
        _require(frame, LOGISTIC_COLUMNS)
        return self.pipeline.decision_function(frame[list(LOGISTIC_COLUMNS)].astype(np.float64))

    def params(self) -> dict:
        imputer, _, model = (step for _, step in self.pipeline.steps)
        return {"columns": list(LOGISTIC_COLUMNS), "median_fill": imputer.statistics_.tolist(),
                "missing_indicator_columns": [LOGISTIC_COLUMNS[i] for i in imputer.indicator_.features_],
                "coefficients_standardised": model.coef_[0].tolist(), "intercept": float(model.intercept_[0])}


def fit_baselines(train_samples: pd.DataFrame, universe_train: pd.DataFrame) -> dict:
    """All three baselines, fitted on the in-domain train positives + matched negatives and the train universe cells."""
    train = training_frame(train_samples, universe_train, "matched_only", n_universe=0, seed=0)
    return {"intensity_duration": IntensityDuration().fit(train),
            "lhasa_style": LhasaStyle().fit(universe_train),
            "logistic": LogisticBaseline().fit(train)}
