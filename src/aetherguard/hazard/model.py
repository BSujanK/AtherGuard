"""LightGBM hazard model: monotone constraints, fitting helpers, calibrated scoring with a bootstrap ensemble.

Training population (data.training_frame): in-domain development positives (weight 1), the 10:1 matched negatives
(weight 1) and, for `neg_mix = matched_plus_universe`, 20,000 random non-buffer universe negatives whose weights make
them contribute the SAME total weight as the matched negatives. Hyper-parameters, the number of trees, the feature
groups, the calibrator and the alert thresholds are all chosen by year-blocked cross-validation (cv.py) on the
2007-2017 development rows; nothing from test_2018, the 2023 window or the case studies is read.

Monotone constraints (+1): rain accumulations, 1-day maxima, accumulation anomalies, wet-day count, per-source
accumulations, slope and relief. `rain_days_since_10mm` is constrained to -1 (assumption: more days since a
heavy-rain day never raises risk). Everything else is unconstrained. The raw LightGBM output is a probability under
the training mix; calibration (MonotoneCalibrator) maps it to P(landslide on that cell-day) at the true base rate.
"""
from __future__ import annotations

import fnmatch
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from ..alerts import levels as lv
from ..config import PROJECT_ROOT, data_root, load_config, load_config_file
from . import data as hd
from .calibration import MonotoneCalibrator, RegionCalibrator
from .jsonio import dump_json

MODEL_FILE = "model.txt"
ENSEMBLE_DIR = "ensemble"
CALIBRATOR_FILE = "calibrator.json"
REGION_CALIBRATOR_FILE = "calibrator_regions.json"
CV_REPORT_STEM = "phase3_hazard_cv_report"
EVALUATION_REPORT_STEM = "phase3_hazard_report"
CARD_FILE = "card.json"
INTERVAL_PERCENTILES = (10.0, 90.0)
CENTRE_PERCENTILE = 50.0             # the ensemble spread is measured from the members' median
LOGIT_CLIP = 1e-12                   # raw scores are clipped to [LOGIT_CLIP, 1 - LOGIT_CLIP] before the logit
TOP_CONTRIBUTIONS = 5


def hazard_config(path: Path | str | None = None) -> dict:
    """The hazard configuration: `configs/hazard.yaml`, or the YAML file at `path`."""
    return load_config("hazard") if path is None else load_config_file(Path(path))


def default_model_dir() -> Path:
    return data_root() / "processed" / "hazard" / "model"


def configured_model_dir(cfg: dict) -> Path:
    """`data/processed/hazard/<cfg.model_dir>` when the configuration names one (v3), else the default (v2) directory."""
    name = cfg.get("model_dir")
    if not name:
        return default_model_dir()
    if Path(name).name != name or name in (".", ".."):
        raise ValueError(f"model_dir must be a plain directory name under data/processed/hazard, got {name!r}")
    return data_root() / "processed" / "hazard" / name


def cv_report_stem(cfg: dict) -> str:
    """File stem (under reports/) of the stage-1 CV report; a configuration may name its own so v2's stays untouched."""
    return cfg.get("cv_report_stem", CV_REPORT_STEM)


def evaluation_report_stem(cfg: dict) -> str:
    return cfg.get("evaluation_report_stem", EVALUATION_REPORT_STEM)


def display_path(path: Path) -> str:
    try:
        return Path(path).resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return Path(path).name


# ------------------------------------------------------------------------------------------ constraints

def constraint_vector(columns, increasing, decreasing) -> list[int]:
    """+1 / -1 / 0 per column from fnmatch patterns; a column matching both lists is an error."""
    vector = []
    for column in columns:
        up = any(fnmatch.fnmatchcase(column, p) for p in increasing)
        down = any(fnmatch.fnmatchcase(column, p) for p in decreasing)
        if up and down:
            raise ValueError(f"column {column!r} is constrained both increasing and decreasing")
        vector.append(1 if up else -1 if down else 0)
    return vector


def configured_constraints(columns, cfg: dict) -> list[int]:
    return constraint_vector(columns, cfg["monotone"]["increasing"], cfg["monotone"]["decreasing"])


# ------------------------------------------------------------------------------------------------ fitting

def feature_matrix(frame: pd.DataFrame, columns) -> pd.DataFrame:
    """The model inputs as float32 (the dtype of the feature store); missing values stay NaN."""
    missing = [c for c in columns if c not in frame.columns]
    if missing:
        raise ValueError(f"frame lacks required model columns {missing}")
    selected = frame[list(columns)]
    bad = [c for c in selected.columns if not pd.api.types.is_numeric_dtype(selected[c])]
    if bad:
        raise ValueError(f"model columns {bad} are not numeric")
    return selected.astype(np.float32)


def lgb_params(hp: dict, constraints, seed: int, settings: dict, metric: str = "None") -> dict:
    params = dict(settings["fixed"])
    params.update(hp)
    params.update(seed=seed, metric=metric, monotone_constraints=list(constraints),
                  monotone_constraints_method="intermediate")
    return params


def fit_booster(train: pd.DataFrame, columns, constraints, hp: dict, seed: int, settings: dict, *,
                valid: pd.DataFrame | None = None, num_rounds: int | None = None) -> tuple[lgb.Booster, int]:
    """Fit on `train` (in-domain development rows only).

    With `valid` (rows carrying `label` and `sample_weight`), train up to `settings.max_rounds` trees and stop when the
    weighted held-out log-loss has not improved for `settings.early_stopping_rounds` rounds; the booster keeps its
    training state so `extend_booster` can add trees, and the best iteration is returned. Without `valid`, train
    exactly `num_rounds` trees.
    """
    hd.assert_training_rows(train)
    dtrain = lgb.Dataset(feature_matrix(train, columns), label=train["label"].to_numpy(),
                         weight=train["sample_weight"].to_numpy(), free_raw_data=False)
    if valid is None:
        if num_rounds is None:
            raise ValueError("either `valid` (early stopping) or `num_rounds` is required")
        return lgb.train(lgb_params(hp, constraints, seed, settings), dtrain, num_boost_round=num_rounds), num_rounds
    hd.assert_training_rows(valid)
    dvalid = lgb.Dataset(feature_matrix(valid, columns), label=valid["label"].to_numpy(),
                         weight=valid["sample_weight"].to_numpy(), reference=dtrain, free_raw_data=False)
    booster = lgb.train(lgb_params(hp, constraints, seed, settings, metric="binary_logloss"), dtrain,
                        num_boost_round=settings["max_rounds"], valid_sets=[dvalid], valid_names=["heldout"],
                        callbacks=[lgb.early_stopping(settings["early_stopping_rounds"], verbose=False)],
                        keep_training_booster=True)
    return booster, booster.best_iteration or booster.current_iteration()


def extend_booster(booster: lgb.Booster, rounds: int) -> lgb.Booster:
    """Continue training an early-stopped booster (kept with its training state) up to `rounds` trees."""
    while booster.current_iteration() < rounds:
        booster.update()
    return booster


def predict_raw(booster: lgb.Booster, frame: pd.DataFrame, columns, num_iteration: int) -> np.ndarray:
    return booster.predict(feature_matrix(frame, columns), num_iteration=num_iteration)


def training_counts(train: pd.DataFrame) -> dict:
    kinds = train.groupby("kind")["sample_weight"].agg(["size", "sum"])
    return {kind: {"rows": int(row["size"]), "total_weight": float(row["sum"])} for kind, row in kinds.iterrows()}


def fit_ensemble(train: pd.DataFrame, columns, constraints, hp: dict, rounds: int, n_members: int, seed: int,
                 settings: dict) -> list[lgb.Booster]:
    """Bagging ensemble: member k is fitted for `rounds` trees on a bootstrap resample of the training rows."""
    members = []
    for k in range(n_members):
        rows = np.random.default_rng(seed + k).integers(0, len(train), len(train))
        members.append(fit_booster(train.iloc[rows].reset_index(drop=True), columns, constraints, hp, seed + k,
                                   settings, num_rounds=rounds)[0])
    return members


# ------------------------------------------------------------------------------------ ensemble interval

def logit(p) -> np.ndarray:
    p = np.clip(np.asarray(p, dtype=np.float64), LOGIT_CLIP, 1.0 - LOGIT_CLIP)
    return np.log(p) - np.log1p(-p)


def expit(x) -> np.ndarray:
    return 0.5 * (1.0 + np.tanh(0.5 * np.asarray(x, dtype=np.float64)))


def recentred_percentile(point_raw, member_raw, percentile: float) -> np.ndarray:
    """The raw score at `percentile` of the ensemble spread, re-centred on the point model (spec section 11).

    The members' spread from their median to their `percentile` is measured in logit space and added to the point's
    logit: expit(logit(point) + logit(q_m) - logit(median_m)). A percentile below the median never lies above the point
    and one above it never below (the bound is clamped to the point against rounding), so a monotone calibration keeps
    risk_lo <= risk <= risk_hi. `member_raw` is (rows, members)."""
    point_raw = np.asarray(point_raw, dtype=np.float64)
    member_raw = np.asarray(member_raw, dtype=np.float64)
    if member_raw.ndim != 2 or member_raw.shape[0] != point_raw.shape[0]:
        raise ValueError(f"member scores must be (rows, members) with {point_raw.shape[0]} rows, got {member_raw.shape}")
    quantile, median = np.percentile(member_raw, [percentile, CENTRE_PERCENTILE], axis=1)
    bound = expit(logit(point_raw) + logit(quantile) - logit(median))
    return np.minimum(bound, point_raw) if percentile <= CENTRE_PERCENTILE else np.maximum(bound, point_raw)


def ensemble_agreement(point_risk, member_risk, threshold_rows) -> np.ndarray:
    """Share of the ensemble members at or above the alert level the point reaches, per row.

    `threshold_rows` (rows, 3) are the calibrated-risk thresholds of Watch, Warning and Emergency of each row. A member is
    at a level when its calibrated risk (same calibrator as the point) reaches that level's threshold, i.e. when its raw
    score reaches the level's raw threshold under the row's calibrator. A point at Normal has agreement 1."""
    point_risk = np.asarray(point_risk, dtype=np.float64)
    member_risk = np.asarray(member_risk, dtype=np.float64)
    threshold_rows = np.asarray(threshold_rows, dtype=np.float64)
    point_level = (point_risk[:, None] >= threshold_rows).sum(axis=1)
    member_level = (member_risk[:, :, None] >= threshold_rows[:, None, :]).sum(axis=2)
    return (member_level >= point_level[:, None]).mean(axis=1)


# ----------------------------------------------------------------------------------------- model object

class HazardModel:
    """Point model + bootstrap ensemble + calibrator, with save / load and the scoring API.

    `region_calibrator` (v3, `calibration.per_region`) replaces the pooled `calibrator` for scored frames that carry a
    `region` column; the pooled calibrator stays the fallback. Alert thresholds are on the raw score scale and do not
    depend on either.
    """

    def __init__(self, columns, constraints, booster: lgb.Booster, best_iteration: int, members: list[lgb.Booster],
                 calibrator: MonotoneCalibrator, card: dict, region_calibrator: RegionCalibrator | None = None) -> None:
        self.columns = list(columns)
        self.constraints = list(constraints)
        self.booster = booster
        self.best_iteration = int(best_iteration)
        self.members = list(members)
        self.calibrator = calibrator
        self.region_calibrator = region_calibrator
        self.card = dict(card)

    def raw_score(self, frame: pd.DataFrame) -> np.ndarray:
        return predict_raw(self.booster, frame, self.columns, self.best_iteration)

    def member_raw_scores(self, frame: pd.DataFrame) -> np.ndarray:
        matrix = feature_matrix(frame, self.columns)
        return np.column_stack([m.predict(matrix, num_iteration=self.best_iteration) for m in self.members])

    def calibrate(self, raw, frame: pd.DataFrame) -> tuple[np.ndarray, dict | None]:
        """Calibrated risk of raw scores (1-D, or 2-D with the frame's rows first) and a record of how it was made.

        Without a region calibrator this is the pooled calibrator and the record is None (v2). With one, rows are
        calibrated by their region's calibrator; rows of regions without their own calibrator (too few positives,
        unseen, missing) and every row of a frame without a `region` column use the pooled one, and the record
        says so.
        """
        if self.region_calibrator is None:
            return self.calibrator.predict(raw), None
        if "region" not in frame.columns:
            return self.calibrator.predict(raw), {"calibration": "pooled", "pooled_rows": int(len(frame)),
                                                  "reason": "frame has no `region` column"}
        regions = frame["region"].to_numpy()
        pooled = self.region_calibrator.uses_pooled(regions)
        record = {"calibration": "per_region", "pooled_rows": int(pooled.sum()),
                  "pooled_regions": sorted({str(r) for r in regions[pooled]})}
        return self.region_calibrator.predict(raw, regions), record

    def level_thresholds(self, frame: pd.DataFrame) -> np.ndarray | None:
        """(rows, 3) calibrated-risk thresholds of Watch, Warning and Emergency of every row as the card gives them: the
        `risk_by_region` value of the row's region for a model calibrated per region scoring a frame with `region` (the
        pooled value for a region the card does not name), the pooled `risk` otherwise; None when the card's
        `alert_levels` do not name all three."""
        levels = self.card.get("alert_levels")
        if not isinstance(levels, dict) or not all(isinstance(levels.get(n), dict) and "risk" in levels[n]
                                                   for n in lv.THRESHOLD_NAMES):
            return None
        pooled = lv.Thresholds(*(float(levels[n]["risk"]) for n in lv.THRESHOLD_NAMES), source="card.alert_levels")
        if self.region_calibrator is None or "region" not in frame.columns:
            return np.tile(pooled.as_array(), (len(frame), 1))
        regions = frame["region"].to_numpy(dtype=object)
        return lv.RegionThresholds(lv.card_region_thresholds(self.card, regions), pooled).matrix(regions)

    def score(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Calibrated scores per row:

        risk                the point model, calibrated;
        risk_lo / risk_hi   the 10th / 90th percentile of the ensemble spread re-centred on the point in logit space
                            (`recentred_percentile`), calibrated like the point, so risk_lo <= risk <= risk_hi;
        member_median_risk  the members' median raw score, calibrated;
        ensemble_agreement  the share of members at or above the alert level the point reaches (`ensemble_agreement`,
                            the card's thresholds per region); NaN when the card names no alert levels.

        With a region calibrator the calibration record is kept in `result.attrs["calibration"]`.
        """
        point_raw = self.raw_score(frame)
        member_raw = self.member_raw_scores(frame)
        raw = np.column_stack([point_raw, recentred_percentile(point_raw, member_raw, INTERVAL_PERCENTILES[0]),
                               recentred_percentile(point_raw, member_raw, INTERVAL_PERCENTILES[1]),
                               np.percentile(member_raw, CENTRE_PERCENTILE, axis=1)])
        calibrated, record = self.calibrate(raw, frame)
        risk = calibrated[:, 0]
        thresholds = self.level_thresholds(frame)
        if thresholds is None:
            agreement = np.full(len(frame), np.nan)
        else:
            members, _ = self.calibrate(member_raw, frame)
            agreement = ensemble_agreement(risk, members, thresholds)
        out = pd.DataFrame({"risk": risk, "risk_lo": calibrated[:, 1], "risk_hi": calibrated[:, 2],
                            "risk_per_100k": 1e5 * risk, "member_median_risk": calibrated[:, 3],
                            "ensemble_agreement": agreement}, index=frame.index)
        if record is not None:
            out.attrs["calibration"] = record
        return out

    def ensemble_percentile(self, frame: pd.DataFrame, percentile: float) -> np.ndarray:
        """The calibrated risk at `percentile` of the ensemble spread re-centred on the point (`recentred_percentile`;
        `score` reports the 10th and 90th as risk_lo / risk_hi)."""
        bound = recentred_percentile(self.raw_score(frame), self.member_raw_scores(frame), percentile)
        return self.calibrate(bound, frame)[0]

    def contributions(self, frame: pd.DataFrame, top: int = TOP_CONTRIBUTIONS) -> list[list[dict]]:
        """Per row the `top` largest-|contribution| inputs as {feature, value, contribution} (log-odds of the raw score;
        value None when the input is missing). Built-in LightGBM SHAP of the point model."""
        matrix = feature_matrix(frame, self.columns)
        contributions = self.booster.predict(matrix, num_iteration=self.best_iteration, pred_contrib=True)[:, :-1]
        values = matrix.to_numpy()
        out = []
        for row in range(len(matrix)):
            order = np.argsort(-np.abs(contributions[row]), kind="stable")[:top]
            out.append([{"feature": self.columns[j],
                         "value": None if np.isnan(values[row, j]) else float(values[row, j]),
                         "contribution": float(contributions[row, j])} for j in order])
        return out

    def save(self, directory: Path) -> None:
        directory = Path(directory)
        (directory / ENSEMBLE_DIR).mkdir(parents=True, exist_ok=True)
        self.booster.save_model(str(directory / MODEL_FILE), num_iteration=self.best_iteration)
        for old in (directory / ENSEMBLE_DIR).glob("member_*.txt"):
            old.unlink()
        for k, member in enumerate(self.members):
            member.save_model(str(directory / ENSEMBLE_DIR / f"member_{k:02d}.txt"), num_iteration=self.best_iteration)
        dump_json(directory / CALIBRATOR_FILE, self.calibrator.to_dict())
        region_path = directory / REGION_CALIBRATOR_FILE
        if self.region_calibrator is not None:
            dump_json(region_path, self.region_calibrator.to_json())
        elif region_path.is_file():
            region_path.unlink()
        card = {**self.card, "columns": self.columns, "constraints": dict(zip(self.columns, self.constraints)),
                "best_iteration": self.best_iteration, "n_members": len(self.members)}
        dump_json(directory / CARD_FILE, card)

    @classmethod
    def load(cls, directory: Path) -> "HazardModel":
        directory = Path(directory)
        card_path = directory / CARD_FILE
        if not card_path.is_file():
            raise FileNotFoundError(f"{card_path} not found; train the model first (python -m aetherguard.hazard.train)")
        card = json.loads(card_path.read_text(encoding="utf-8"))
        columns = card["columns"]
        constraints = [card["constraints"][c] for c in columns]
        booster = lgb.Booster(model_file=str(directory / MODEL_FILE))
        members = [lgb.Booster(model_file=str(directory / ENSEMBLE_DIR / f"member_{k:02d}.txt"))
                   for k in range(card["n_members"])]
        calibrator = MonotoneCalibrator.from_dict(json.loads((directory / CALIBRATOR_FILE).read_text(encoding="utf-8")))
        region_path = directory / REGION_CALIBRATOR_FILE
        region_calibrator = (RegionCalibrator.from_json(json.loads(region_path.read_text(encoding="utf-8")))
                             if region_path.is_file() else None)
        return cls(columns, constraints, booster, card["best_iteration"], members, calibrator, card, region_calibrator)


_LOADED: dict[tuple[str, int], HazardModel] = {}


def load_cached(model_dir: Path | None = None) -> HazardModel:
    directory = Path(model_dir or default_model_dir())
    card = directory / CARD_FILE
    stamp = (str(directory.resolve()), card.stat().st_mtime_ns if card.is_file() else 0)
    if stamp not in _LOADED:
        _LOADED[stamp] = HazardModel.load(directory)
    return _LOADED[stamp]


def score_frame(frame: pd.DataFrame, model_dir: Path | None = None) -> pd.DataFrame:
    """Score feature-store rows with the saved model: DataFrame[risk, risk_lo, risk_hi, risk_per_100k,
    member_median_risk, ensemble_agreement] (`HazardModel.score`).

    Raises ValueError naming any model input column the frame lacks. `risk` is the calibrated probability of a
    landslide on that cell-day at the all-year operating base rate; `risk_per_100k = 1e5 * risk`.
    """
    return load_cached(model_dir).score(frame)


# ------------------------------------------------------------------------------------- model diagnostics

def monotonicity_check(booster: lgb.Booster, columns, constraints, background: pd.DataFrame, num_iteration: int,
                       n_grid: int = 25, n_background: int = 1000, seed: int = 0, tolerance: float = 1e-12) -> dict:
    """Partial dependence of the mean raw score on a grid of each constrained feature; reports whether it moves
    in the constrained direction everywhere (max_violation is the largest move against it)."""
    matrix = feature_matrix(background, columns)
    if len(matrix) > n_background:
        matrix = matrix.iloc[np.random.default_rng(seed).choice(len(matrix), n_background, replace=False)]
    out = {}
    for column, direction in zip(columns, constraints):
        if direction == 0:
            continue
        observed = matrix[column].dropna().to_numpy()
        grid = np.unique(np.percentile(observed, np.linspace(2, 98, n_grid)))
        curve = []
        for value in grid:
            probe = matrix.copy()
            probe[column] = np.float32(value)
            curve.append(float(booster.predict(probe, num_iteration=num_iteration).mean()))
        steps = np.diff(curve) * direction
        violation = float(max(0.0, -steps.min())) if len(steps) else 0.0
        out[column] = {"direction": direction, "holds": bool(violation <= tolerance), "max_violation": violation,
                       "grid": grid.tolist(), "partial_dependence": curve}
    return out


def feature_importance(booster: lgb.Booster, columns, num_iteration: int) -> dict[str, float]:
    gain = booster.feature_importance(importance_type="gain", iteration=num_iteration)
    return dict(sorted(zip(columns, map(float, gain)), key=lambda item: -item[1]))
