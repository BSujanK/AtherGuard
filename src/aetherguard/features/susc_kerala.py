"""Stage 1 of the two-stage susceptibility study: a WHERE surface learned from the imagery-mapped Kerala 2018 inventory
(docs/superpowers/specs/2026-11-17-aetherguard-kerala-susceptibility.md section 3).

    python -m aetherguard.features.susc_kerala [build] [--force]   # stage 1: the surface and stage_one.json
    python -m aetherguard.features.susc_kerala report              # reports/phase9_kerala_susceptibility.{md,json}

Why a mapped inventory. v4's static inputs were learned from reported events, which sit where people and roads are. The
Kerala 2018 monsoon inventory (Hao et al. 2020, ESSD 12, 2899-2918; van Westen 2020, DANS doi:10.17026/dans-x6c-y7x2,
CC-BY-4.0) was mapped from post-event imagery and field survey, so it records slides on empty slopes as well. It is dated
only to the season, so it can teach where, never when.

What is fitted. One row per domain cell of the 14 Kerala districts; label 1 when an inventory point falls in the cell.
Inputs: v3's ten terrain statistics, the nine physical W5 columns and `rain_2018`, the IMERG Late total of the inventory's
window at the cell. The trigger is held at its median over the training cells when the surface is evaluated, so the 2018
storm's footprint is not learned as susceptibility. Roads and built-up share are never inputs.

How it is chosen. Two forms (`S_lr`, `S_gbm`), leave one district out, pooled out-of-fold ROC AUC; the better one must beat
the mean slope alone. The chosen form is refitted on every training cell and evaluated on every cell of
`cell_terrain.parquet`: `data/processed/features/susc_kerala/cell_susc.parquet`. Beside it, and deciding nothing: the same
form fitted on reported development positives (does a surface learned from reports place mapped slides?), the
surfaces' rank correlation with roads and built-up share, and an imagery-only label.

No held-out event, no case-study table and no model output is read here.
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score

from ..config import data_root
from ..events.sources import read_dbf
from ..grid import latlon_to_cell
from ..manifest import sha256_file
from . import static_w5 as sw

KERALA_DISTRICTS = ("Alappuzha", "Ernakulam", "Idukki", "Kannur", "Kasaragod", "Kollam", "Kottayam", "Kozhikode",
                    "Malappuram", "Palakkad", "Pathanamthitta", "Thiruvananthapuram", "Thrissur", "Wayanad")
TERRAIN_INPUTS = {f"stat_{c}": c for c in ("elev_mean", "elev_std", "relief", "slope_mean", "slope_p90", "slope_max",
                                           "curvature_mean", "aspect_sin", "aspect_cos", "twi_proxy")}
PHYSICAL_INPUTS = list(sw.HAZARD_COLUMNS)
RAIN = "rain_2018"
INPUTS = [*TERRAIN_INPUTS, *PHYSICAL_INPUTS, RAIN]
WINDOW = (date(2018, 6, 1), date(2018, 8, 26))          # the inventory's event window (Hao et al. 2020)
SEED = 20261117
N_BOOT = 2000
CANDIDATES = ("S_lr", "S_gbm")
BASELINE = "B_slope"
SURFACE_COLUMNS = ["susc_kerala", "susc_kerala_wg"]
GHATS = "western_ghats"
SELECTION_RULE = ("the candidate with the higher pooled leave-one-district-out ROC AUC of its surface; stage 1 passes when "
                  "that AUC is above B_slope's (stat_slope_mean alone)")
GBM_PARAMS = {"objective": "binary", "learning_rate": 0.03, "num_leaves": 7, "min_data_in_leaf": 20,
              "feature_fraction": 0.8, "bagging_fraction": 0.8, "bagging_freq": 1, "seed": SEED, "deterministic": True,
              "force_col_wise": True, "num_threads": 1, "verbose": -1}
GBM_ROUNDS = 300
LR_C = 1.0
INVENTORY = Path("raw") / "manual" / "kerala2018_hao2020"
COORD_TOLERANCE = 1e-6           # degrees: a point whose geometry and POINT_X / POINT_Y differ by more is counted


def out_dir() -> Path:
    return data_root() / "processed" / "features" / "susc_kerala"


def table_path() -> Path:
    return out_dir() / "cell_susc.parquet"


# ---------------------------------------------------------------------------------------------- inventory

def read_shp_points(path: Path) -> np.ndarray:
    """(x, y) of every record of a point shapefile (Point, PointZ or PointM), in record order; NaN for a null shape."""
    data = Path(path).read_bytes()
    if struct.unpack(">i", data[:4])[0] != 9994:
        raise ValueError(f"{Path(path).name} is not a shapefile")
    out, pos = [], 100
    while pos < len(data):
        _, words = struct.unpack(">2i", data[pos:pos + 8])
        kind = struct.unpack("<i", data[pos + 8:pos + 12])[0]
        if kind == 0:
            out.append((np.nan, np.nan))
        elif kind in (1, 11, 21):        # Point, PointZ, PointM: x and y come first
            out.append(struct.unpack("<2d", data[pos + 12:pos + 28]))
        else:
            raise ValueError(f"{Path(path).name}: shape type {kind} is not a point")
        pos += 8 + 2 * words
    return np.array(out, dtype=np.float64).reshape(-1, 2)


def inventory(directory: Path | None = None) -> pd.DataFrame:
    """The inventory's points (lat, lon) and which source found each (NRSC imagery, GSI field, the authors' Google Earth
    mapping), with the shapefile geometry checked against the coordinate attributes."""
    directory = Path(directory or data_root() / INVENTORY)
    table, deleted = read_dbf(directory / "kerala_landslide.dbf", columns=("POINT_X", "POINT_Y", "NRSC", "GSI", "New"))
    xy = read_shp_points(directory / "kerala_landslide.shp")
    if deleted or len(xy) != len(table):
        raise ValueError(f"{len(xy)} shapes against {len(table)} records ({deleted} deleted)")
    attr = table[["POINT_X", "POINT_Y"]].to_numpy(dtype=np.float64)
    if np.isnan(xy).any():
        raise ValueError("the inventory has a null shape")
    moved = latlon_to_cell(xy[:, 1], xy[:, 0]) != latlon_to_cell(attr[:, 1], attr[:, 0])
    if moved.any():
        raise ValueError(f"{int(moved.sum())} points fall in another cell by their POINT_X / POINT_Y attributes")
    flag = {c: table[c].str.upper().eq("Y").to_numpy() for c in ("NRSC", "GSI", "New")}
    out = pd.DataFrame({"lat": xy[:, 1], "lon": xy[:, 0], "nrsc": flag["NRSC"], "gsi": flag["GSI"], "new": flag["New"]})
    out.attrs["attribute_mismatch_points"] = int((np.abs(xy - attr).max(axis=1) > COORD_TOLERANCE).sum())
    return out


def cell_labels(points: pd.DataFrame, universe: np.ndarray) -> pd.DataFrame:
    """Per cell of `universe` (in its order): inventory points, points found by imagery (NRSC or Google Earth) and the
    label (1 when any point falls in the cell). Points outside `universe` are dropped and counted in `attrs`."""
    cells = latlon_to_cell(points["lat"].to_numpy(), points["lon"].to_numpy())
    imagery = (points["nrsc"] | points["new"]).to_numpy()
    universe = np.asarray(universe, dtype=np.int64)
    inside = np.isin(cells, universe)
    counts = pd.Series(1, index=cells[inside]).groupby(level=0).sum()
    image = pd.Series(imagery[inside].astype(int), index=cells[inside]).groupby(level=0).sum()
    out = pd.DataFrame({"cell_id": universe, "points": counts.reindex(universe).fillna(0).astype(int).to_numpy(),
                        "imagery_points": image.reindex(universe).fillna(0).astype(int).to_numpy()})
    out["label"] = (out["points"] > 0).astype(int)
    out.attrs["dropped_points"] = int((~inside).sum())
    out.attrs["dropped_cells"] = int(len(np.unique(cells[~inside])))
    return out


# ------------------------------------------------------------------------------------------------- inputs

def cell_inputs(cell_ids, terrain: pd.DataFrame, static: pd.DataFrame, rain: np.ndarray | None = None) -> pd.DataFrame:
    """The stage 1 inputs of `cell_ids` (in order): terrain statistics under their `stat_` model names, the nine physical
    W5 columns and, when given, `rain_2018`."""
    ids = np.asarray(cell_ids, dtype=np.int64)
    t = terrain.set_index("cell_id").reindex(ids)[list(TERRAIN_INPUTS.values())]
    t.columns = list(TERRAIN_INPUTS)
    s = static.set_index("cell_id").reindex(ids)[PHYSICAL_INPUTS]
    out = pd.concat([t.reset_index(drop=True), s.reset_index(drop=True)], axis=1)
    if rain is not None:
        out[RAIN] = np.asarray(rain, dtype=np.float64)
    return out


def rain_totals(cell_ids, store) -> tuple[np.ndarray, int]:
    """IMERG rain summed over the inventory's window at each cell's pixel, and how many pixel-days of the window the store
    lacks (a missing one would bias a total, so the caller refuses any)."""
    from ..ingest.imerg import imerg_pixel
    rows, cols = imerg_pixel(np.asarray(cell_ids, dtype=np.int64))
    length = (WINDOW[1] - WINDOW[0]).days + 1
    values = store.gather(rows, cols, WINDOW[0], length)
    missing = int(np.isnan(values).sum())
    return np.nansum(values, axis=1).astype(np.float64), missing


# ------------------------------------------------------------------------------------------- the two forms

@dataclass
class LogisticSurface:
    """L2 logistic regression with the training cells' medians (imputation), ranges (clipping) and scale."""

    columns: list[str]
    median: np.ndarray
    lo: np.ndarray
    hi: np.ndarray
    mean: np.ndarray
    scale: np.ndarray
    model: LogisticRegression

    def _prepare(self, x: pd.DataFrame) -> np.ndarray:
        z = x[self.columns].to_numpy(dtype=np.float64)
        z = np.where(np.isnan(z), self.median, z)
        return (np.clip(z, self.lo, self.hi) - self.mean) / self.scale

    def predict(self, x: pd.DataFrame) -> np.ndarray:
        return self.model.predict_proba(self._prepare(x))[:, 1]


@dataclass
class GbmSurface:
    columns: list[str]
    booster: lgb.Booster

    def predict(self, x: pd.DataFrame) -> np.ndarray:
        return self.booster.predict(x[self.columns].to_numpy(dtype=np.float64))


def _fit_lr(x: pd.DataFrame, y: np.ndarray) -> LogisticSurface:
    columns = list(x.columns)
    z = x.to_numpy(dtype=np.float64)
    median = np.nanmedian(z, axis=0)
    median = np.where(np.isnan(median), 0.0, median)
    z = np.where(np.isnan(z), median, z)
    lo, hi = z.min(axis=0), z.max(axis=0)
    mean, scale = z.mean(axis=0), z.std(axis=0)
    scale = np.where(scale > 0, scale, 1.0)
    model = LogisticRegression(C=LR_C, max_iter=5000).fit((z - mean) / scale, y)
    return LogisticSurface(columns, median, lo, hi, mean, scale, model)


def _fit_gbm(x: pd.DataFrame, y: np.ndarray) -> GbmSurface:
    columns = list(x.columns)
    params = {**GBM_PARAMS, "monotone_constraints": [1 if c == RAIN else 0 for c in columns]}
    data = lgb.Dataset(x.to_numpy(dtype=np.float64), label=np.asarray(y), feature_name=columns, free_raw_data=False)
    return GbmSurface(columns, lgb.train(params, data, num_boost_round=GBM_ROUNDS))


FITS: dict[str, Callable] = {"S_lr": _fit_lr, "S_gbm": _fit_gbm}


def fit_candidate(name: str, x: pd.DataFrame, y) -> LogisticSurface | GbmSurface:
    return FITS[name](x, np.asarray(y, dtype=int))


def surface(model, x: pd.DataFrame, rain_ref: float) -> np.ndarray:
    """The model's probability with the trigger covariate held at `rain_ref` for every row."""
    return model.predict(x.assign(**{RAIN: float(rain_ref)}))


def group_oof(x: pd.DataFrame, y, groups, fit: Callable, rain_ref: str | None = "median") -> np.ndarray:
    """Leave-one-group-out scores: each group scored by a model fitted on the other groups. With `rain_ref` "median" the
    score is the surface at the training groups' median trigger; with None the model's own prediction."""
    y, groups = np.asarray(y), np.asarray(groups)
    oof = np.full(len(y), np.nan)
    for g in pd.unique(groups):
        test = groups == g
        model = fit(x[~test], y[~test])
        if rain_ref is None:
            oof[test] = model.predict(x[test])
        else:
            oof[test] = surface(model, x[test], float(np.nanmedian(x.loc[~test, RAIN])))
    return oof


def _metrics(y, score) -> dict[str, float]:
    return {"roc_auc": float(roc_auc_score(y, score)), "average_precision": float(average_precision_score(y, score))}


def group_bootstrap(y, scores: dict[str, np.ndarray], groups, n: int = N_BOOT, seed: int = SEED, level: float = 0.95,
                    pairs=()) -> dict:
    """Point metrics and percentile intervals from resampling whole groups with replacement (a resample with one class
    only is drawn again); `pairs` adds the paired differences a - b of each metric."""
    y, groups = np.asarray(y), np.asarray(groups)
    names = sorted(pd.unique(groups))
    members = {g: np.flatnonzero(groups == g) for g in names}
    rng = np.random.default_rng(seed)
    draws = {k: {m: [] for m in ("roc_auc", "average_precision")} for k in scores}
    while len(next(iter(draws.values()))["roc_auc"]) < n:
        rows = np.concatenate([members[g] for g in rng.choice(names, size=len(names), replace=True)])
        if len(np.unique(y[rows])) < 2:
            continue
        for k, s in scores.items():
            for m, v in _metrics(y[rows], np.asarray(s)[rows]).items():
                draws[k][m].append(v)
    q = [(1 - level) / 2 * 100, (1 + level) / 2 * 100]
    out = {k: {m: {"value": _metrics(y, scores[k])[m], "ci": [float(v) for v in np.percentile(draws[k][m], q)]}
               for m in draws[k]} for k in scores}
    if pairs:
        out["differences"] = {f"{a}-{b}": {m: {"value": out[a][m]["value"] - out[b][m]["value"],
                                               "ci": [float(v) for v in np.percentile(np.subtract(draws[a][m], draws[b][m]), q)]}
                                           for m in draws[a]} for a, b in pairs}
    return out


def select(metrics: dict) -> dict:
    """Spec section 3: the candidate with the higher pooled OOF ROC AUC, passing only above the slope baseline."""
    best = max(CANDIDATES, key=lambda c: metrics[c]["roc_auc"]["value"])
    auc, base = metrics[best]["roc_auc"]["value"], metrics[BASELINE]["roc_auc"]["value"]
    return {"selected": best, "passed": bool(auc > base), "selected_auc": auc, "baseline_auc": base, "rule": SELECTION_RULE}


def cell_table(cells: pd.DataFrame, values: np.ndarray) -> pd.DataFrame:
    """`susc_kerala` for every cell and `susc_kerala_wg`, the same value in the Western Ghats region and NaN elsewhere."""
    values = np.asarray(values, dtype=np.float64)
    ghats = cells["region"].to_numpy() == GHATS
    return pd.DataFrame({"cell_id": cells["cell_id"].to_numpy(dtype=np.int64), "susc_kerala": values,
                         "susc_kerala_wg": np.where(ghats, values, np.nan)})


# -------------------------------------------------------------------------------------------------- build

def _spearman(a, b) -> float:
    return float(spearmanr(a, b, nan_policy="omit").statistic)


def build(force: bool = False, say=print) -> dict:
    """Stage 1 end to end; writes cell_susc.parquet and stage_one.json under data/processed/features/susc_kerala."""
    from ..ingest.imerg import ImergStore
    from ..live.backtest import universe_cell_ids

    started = time.perf_counter()
    out = out_dir()
    result_path = out / "stage_one.json"
    if result_path.exists() and not force:
        raise FileExistsError(f"{result_path} exists; pass --force to rebuild stage 1 and overwrite it")
    root = data_root()
    districts = pd.read_parquet(root / "processed" / "districts" / "cell_districts.parquet")
    kerala = districts[districts["district"].isin(KERALA_DISTRICTS)].sort_values("cell_id").reset_index(drop=True)
    terrain = pd.read_parquet(root / "processed" / "terrain" / "cell_terrain.parquet")
    static = sw.static_table()
    regions = pd.read_parquet(root / "processed" / "features" / "cell_regions.parquet")
    points = inventory()
    labels = cell_labels(points, kerala["cell_id"].to_numpy())
    rain, missing = rain_totals(labels["cell_id"].to_numpy(), ImergStore(root / "processed" / "rain", "late"))
    if missing:
        raise ValueError(f"the IMERG Late store lacks {missing} pixel-days of the inventory window; the rain totals would be biased")
    x = cell_inputs(labels["cell_id"], terrain, static, rain)
    y, groups = labels["label"].to_numpy(), kerala["district"].to_numpy()
    rain_ref = float(np.median(rain))
    say(f"stage 1 cells: {len(labels)} ({int(y.sum())} with a point, {int(labels['points'].sum())} points); "
        f"{labels.attrs['dropped_points']} points in {labels.attrs['dropped_cells']} cells outside the Kerala districts dropped; "
        f"rain_2018 median {rain_ref:.0f} mm")

    oof = {name: group_oof(x, y, groups, lambda xf, yf, n=name: fit_candidate(n, xf, yf)) for name in CANDIDATES}
    oof_full = {name: group_oof(x, y, groups, lambda xf, yf, n=name: fit_candidate(n, xf, yf), rain_ref=None)
                for name in CANDIDATES}
    oof[BASELINE] = x["stat_slope_mean"].to_numpy(dtype=np.float64)
    if np.isnan(oof[BASELINE]).any():
        raise ValueError("a stage 1 cell has no mean slope")
    pairs = [(c, BASELINE) for c in CANDIDATES] + [("S_gbm", "S_lr")]
    metrics = group_bootstrap(y, oof, groups, pairs=pairs)
    selection = select(metrics)
    chosen = selection["selected"]
    for name in [*CANDIDATES, BASELINE]:
        m = metrics[name]
        say(f"{name}: ROC AUC {m['roc_auc']['value']:.4f} {m['roc_auc']['ci']}, AP {m['average_precision']['value']:.4f}")
    say(f"selection: {chosen}, {'passed' if selection['passed'] else 'FAILED'}")

    # the reporting-bias checks: they decide nothing
    scored = np.sort(universe_cell_ids())
    dev_pos = pd.read_parquet(root / "processed" / "splits" / "positive_cell_days.parquet", columns=["cell_id", "split"])
    dev_cells = np.unique(dev_pos.loc[dev_pos["split"].isin(["train", "validation"]), "cell_id"].to_numpy(dtype=np.int64))
    xr = cell_inputs(scored, terrain, static)
    yr = np.isin(scored, dev_cells).astype(int)
    reported = fit_candidate(chosen, xr, yr)
    reported_on_kerala = reported.predict(x.drop(columns=[RAIN]))
    imagery_keep = ~((labels["points"] > 0) & (labels["imagery_points"] == 0)).to_numpy()
    y_img = (labels["imagery_points"] > 0).to_numpy(dtype=int)[imagery_keep]
    oof_img = group_oof(x[imagery_keep].reset_index(drop=True), y_img, groups[imagery_keep],
                        lambda xf, yf: fit_candidate(chosen, xf, yf))
    final = fit_candidate(chosen, x, y)
    cells = terrain[["cell_id"]].merge(regions[["cell_id", "region"]], on="cell_id", how="left")
    values = surface(final, cell_inputs(cells["cell_id"], terrain, static).assign(**{RAIN: rain_ref}), rain_ref)
    table = cell_table(cells, values)
    exposure = static.set_index("cell_id").reindex(scored)
    on_scored = table.set_index("cell_id").reindex(scored)["susc_kerala"].to_numpy()
    reported_scored = reported.predict(xr)
    checks = {
        "reported_surface": {
            "description": f"{chosen} without rain_2018, fitted on the {len(scored)} scored cells, label = a development "
                           "positive (2007-2017) in the cell; scored on the Kerala cells against the mapped label",
            "training_cells": int(len(scored)), "training_positive_cells": int(yr.sum()),
            "training_positive_cells_by_region": {str(k): int(v) for k, v in regions.set_index("cell_id").reindex(
                scored[yr == 1])["region"].value_counts().sort_index().items()},
            "kerala": _metrics(y, reported_on_kerala)},
        "spearman_with_exposure": {
            name: {c: _spearman(v, exposure[c].to_numpy()) for c in sw.EXPOSURE_COLUMNS}
            for name, v in (("surface", on_scored), ("reported_surface", reported_scored))},
        "imagery_only": {"cells": int(imagery_keep.sum()), "positive_cells": int(y_img.sum()),
                         "left_out_gsi_only_cells": int((~imagery_keep).sum()), **_metrics(y_img, oof_img),
                         "slope_roc_auc": float(roc_auc_score(y_img, oof[BASELINE][imagery_keep]))},
        "full_model_oof": {name: _metrics(y, v) for name, v in oof_full.items()},
    }
    out.mkdir(parents=True, exist_ok=True)
    table.to_parquet(table_path(), index=False)
    pd.DataFrame({"cell_id": labels["cell_id"], "district": groups, "label": y, "points": labels["points"],
                  "imagery_points": labels["imagery_points"], RAIN: rain,
                  **{f"oof_{k}": v for k, v in oof.items()}}).to_parquet(out / "stage_one_oof.parquet", index=False)
    inputs = {"inventory_" + p.name: p for p in sorted((root / INVENTORY).glob("kerala_landslide.*"))}
    inputs.update(cell_districts=root / "processed" / "districts" / "cell_districts.parquet",
                  cell_terrain=root / "processed" / "terrain" / "cell_terrain.parquet", cell_static=sw.table_path(),
                  cell_regions=root / "processed" / "features" / "cell_regions.parquet",
                  imerg_late_2018=root / "processed" / "rain" / "imerg_late_2018.npy",
                  positive_cell_days=root / "processed" / "splits" / "positive_cell_days.parquet")
    payload = {
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "spec": "docs/superpowers/specs/2026-11-17-aetherguard-kerala-susceptibility.md",
        "inventory": {"source": "Hao et al. 2020, ESSD 12, 2899-2918; van Westen 2020, DANS doi:10.17026/dans-x6c-y7x2",
                      "licence": "CC-BY-4.0", "points": int(len(points)), "nrsc": int(points["nrsc"].sum()),
                      "gsi": int(points["gsi"].sum()), "new": int(points["new"].sum()),
                      "gsi_only": int((points["gsi"] & ~points["nrsc"] & ~points["new"]).sum()),
                      "attribute_mismatch_points": points.attrs["attribute_mismatch_points"]},
        "cells": {"training": int(len(labels)), "positive": int(y.sum()), "points_used": int(labels["points"].sum()),
                  "dropped_points": labels.attrs["dropped_points"], "dropped_cells": labels.attrs["dropped_cells"],
                  "districts": {d: {"cells": int((groups == d).sum()), "positive": int(y[groups == d].sum())}
                                for d in KERALA_DISTRICTS}},
        "inputs": INPUTS, "rain_window": [WINDOW[0].isoformat(), WINDOW[1].isoformat()], "rain_ref_mm": rain_ref,
        "forms": {"S_lr": {"C": LR_C, "penalty": "l2"}, "S_gbm": {**GBM_PARAMS, "rounds": GBM_ROUNDS}},
        "bootstrap": {"n": N_BOOT, "seed": SEED, "unit": "district"},
        "metrics": metrics, "selection": selection, "checks": checks,
        "surface": {"cells": int(len(table)), "nan_cells": int(table["susc_kerala"].isna().sum()),
                    "scored_cells_quantiles": {str(q): float(np.nanquantile(on_scored, q)) for q in (0.1, 0.5, 0.9)}},
        "input_sha256": {k: sha256_file(p) for k, p in inputs.items()},
        "table_sha256": sha256_file(table_path()), "seconds": time.perf_counter() - started}
    result_path.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    say(f"wrote {table_path()} and {result_path} in {payload['seconds']:.0f}s")
    return payload


# ------------------------------------------------------------------------------------------------- report

REPORT_STEM = "phase9_kerala_susceptibility"
SCORES = (*CANDIDATES, BASELINE)


def within_district(oof: pd.DataFrame) -> list[dict]:
    """ROC AUC of each score inside each district that has both classes: a diagnostic of the pooled number."""
    rows = []
    for district, f in oof.groupby("district", sort=True):
        if f["label"].nunique() == 2:
            rows.append({"district": district, "cells": int(len(f)), "positive": int(f["label"].sum()),
                         **{k: float(roc_auc_score(f["label"], f[f"oof_{k}"])) for k in SCORES}})
    return rows


def _ci(entry: dict) -> str:
    return f"{entry['value']:.3f} [{entry['ci'][0]:.3f}, {entry['ci'][1]:.3f}]"


def markdown(result: dict, districts: list[dict]) -> str:
    sel, m, checks, inv, cells = result["selection"], result["metrics"], result["checks"], result["inventory"], result["cells"]
    rep, img, exp = checks["reported_surface"], checks["imagery_only"], checks["spearman_with_exposure"]
    medians = {k: float(np.median([d[k] for d in districts])) for k in SCORES}
    verdict = ("passed: stage 2 may follow" if sel["passed"] else
               "FAILED: the study ends here (spec section 3); no stage 2 was run and no held-out number exists")
    lines = [
        "# Two-stage susceptibility from the Kerala 2018 mapped inventory: stage 1", "",
        f"**Stage 1 {verdict}.** Selected form `{sel['selected']}`: pooled leave-one-district-out ROC AUC "
        f"{sel['selected_auc']:.3f} against {sel['baseline_auc']:.3f} for the mean slope alone (`{BASELINE}`). The rule "
        f"was fixed before any number (`{result['spec']}` section 3): {sel['rule']}.", "",
        "## The inventory", "",
        f"{inv['source']}; licence {inv['licence']}. {inv['points']:,} points: {inv['nrsc']:,} found by NRSC imagery, "
        f"{inv['gsi']:,} by GSI field survey, {inv['new']:,} added by the authors from Google Earth; {inv['gsi_only']:,} "
        f"are GSI-only. {inv['attribute_mismatch_points']} point's coordinate attributes differ from its geometry (the "
        "geometry is used; no point changes cell). Dated only to 1 June - 26 August 2018, so it is used for where, never "
        "when. Raw rows stay under `data/` and are not committed.", "",
        f"Training cells: the {cells['training']:,} domain cells of the 14 Kerala districts, {cells['positive']} holding "
        f"at least one point ({cells['points_used']:,} points). {cells['dropped_points']} points in "
        f"{cells['dropped_cells']} cells outside those districts were dropped. Inputs: v3's ten terrain statistics, the "
        "nine physical W5 columns and the IMERG Late rain of the window, held at its training median "
        f"({result['rain_ref_mm']:.0f} mm) when the surface is evaluated. Roads and built-up share are never inputs.", "",
        f"## Spatial-block evaluation (leave one district out; 95% intervals from {result['bootstrap']['n']:,} district resamples)", "",
        "| score | ROC AUC | average precision |", "|---|---|---|",
        *[f"| `{k}` | {_ci(m[k]['roc_auc'])} | {_ci(m[k]['average_precision'])} |" for k in SCORES], "",
        "| difference | ROC AUC | average precision |", "|---|---|---|",
        *[f"| `{k}` | {_ci(v['roc_auc'])} | {_ci(v['average_precision'])} |" for k, v in m["differences"].items()], "",
        "Inside each district (diagnostic, decides nothing; districts with both classes):", "",
        "| district | cells | with a point | " + " | ".join(f"`{k}`" for k in SCORES) + " |", "|---|---|---|---|---|---|",
        *[f"| {d['district']} | {d['cells']} | {d['positive']} | " + " | ".join(f"{d[k]:.3f}" for k in SCORES) + " |"
          for d in districts],
        "| median | | | " + " | ".join(f"{medians[k]:.3f}" for k in SCORES) + " |", "",
        "## Reporting-bias checks (decide nothing)", "",
        f"- A surface of the same form learned from reported development positives ({rep['training_positive_cells']} of "
        f"{rep['training_cells']:,} scored cells; by region "
        + ", ".join(f"{k} {v}" for k, v in rep["training_positive_cells_by_region"].items()) + ") ranks the Kerala mapped cells at ROC AUC "
        f"{rep['kerala']['roc_auc']:.3f} (average precision {rep['kerala']['average_precision']:.3f}).",
        "- Spearman correlation over the scored cells, with road density / built-up share: the mapped surface "
        f"{exp['surface']['road_density']:+.3f} / {exp['surface']['lc_built']:+.3f}; the reported surface "
        f"{exp['reported_surface']['road_density']:+.3f} / {exp['reported_surface']['lc_built']:+.3f}.",
        f"- Imagery-only label ({img['cells']:,} cells, {img['positive_cells']} positive, {img['left_out_gsi_only_cells']} "
        f"GSI-only cells left out): ROC AUC {img['roc_auc']:.3f}; the mean slope alone on the same cells {img['slope_roc_auc']:.3f}.",
        "- The fitted models with each cell's own 2018 rain (not a surface; it carries the storm's footprint): "
        + ", ".join(f"`{k}` {v['roc_auc']:.3f}" for k, v in checks["full_model_oof"].items()) + ".", "",
        "## Caveats", "",
        "- One storm in one state: a surface learned here would also have had to transfer to the Himalaya.",
        "- The cells are 0.05 degree (about 5.5 km); slides are slope-scale, so a cell label is presence somewhere in it.",
        "- No held-out event, case-study table or model output was read. Research prototype, not validated for issuing "
        "public warnings.", ""]
    return "\n".join(lines)


def write_report(say=print, reports_dir: Path | None = None) -> Path:
    """reports/phase9_kerala_susceptibility.{md,json} from stage_one.json and the stored OOF scores."""
    from ..config import PROJECT_ROOT

    result = json.loads((out_dir() / "stage_one.json").read_text(encoding="utf-8"))
    districts = within_district(pd.read_parquet(out_dir() / "stage_one_oof.parquet"))
    target = Path(reports_dir or PROJECT_ROOT / "reports")
    target.mkdir(parents=True, exist_ok=True)
    payload = {**{k: v for k, v in result.items() if k != "input_sha256"}, "within_district": districts,
               "input_sha256": result["input_sha256"]}
    (target / f"{REPORT_STEM}.json").write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    (target / f"{REPORT_STEM}.md").write_text(markdown(result, districts), encoding="utf-8")
    say(f"wrote {target / REPORT_STEM}.{{md,json}}")
    return target / f"{REPORT_STEM}.md"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("stage", nargs="?", choices=["build", "report"], default="build")
    parser.add_argument("--force", action="store_true", help="rebuild stage 1 and overwrite its results")
    args = parser.parse_args(argv)

    def say(message: str) -> None:
        print(message, flush=True)
    if args.stage == "report":
        write_report(say)
        return 0
    result = build(force=args.force, say=say)
    return 0 if result["selection"]["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
