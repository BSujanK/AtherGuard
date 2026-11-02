"""Year-blocked cross-validation over the 2007-2017 development rows (protocol v2, docs/phase3-design.md).

Folds are contiguous year blocks (configs/hazard.yaml `cv.folds`). For fold F, the model is fitted on the in-domain
positives, matched negatives (and, for `matched_plus_universe`, drawn universe negatives) dated OUTSIDE F's years,
then scores F's in-domain positives, F's matched negatives and F's universe negatives. Universe weights are fixed per
calendar year (data.year_weighted_negatives), so F's universe rows are a correctly weighted sample of F's own period.
Pooling the held-out scores of all folds gives the out-of-fold (OOF) scores that every choice is made on: the
false-alarm share at 90% recall (weighted universe), its bootstrap CI, the calibrator and the alert thresholds.

Trees: per fold, early stopping on that fold's held-out weighted log-loss over its positives and matched negatives
(the training design); the candidate's tree count is the median over folds, and every fold model is then trained or
cut to exactly that many trees before scoring, so OOF scores and the final refit use the same setting.
"""
from __future__ import annotations

import itertools
import time
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import baselines as bl
from . import calibration as cal
from . import data as hd
from . import metrics as mt
from . import model as hm

HEADLINE_RECALL = 0.9


@dataclass(frozen=True)
class Layout:
    """The evaluation rows every candidate is scored on, in a fixed order (so candidates are paired)."""
    folds: list[list[int]]
    positives: pd.DataFrame        # in-domain positive cell-days
    negatives: pd.DataFrame        # year-weighted universe negatives
    matched: pd.DataFrame          # matched negatives of the sample files
    pos_fold: np.ndarray
    neg_fold: np.ndarray
    matched_fold: np.ndarray
    strata: np.ndarray             # "<year>-<region>" per negative (weights are constant within a stratum)

    @property
    def neg_weight(self) -> np.ndarray:
        return self.negatives["weight"].to_numpy(dtype=np.float64)


@dataclass
class Oof:
    """Out-of-fold scores aligned with a Layout."""
    pos: np.ndarray
    neg: np.ndarray
    matched: np.ndarray

    @classmethod
    def empty(cls, layout: Layout) -> "Oof":
        return cls(np.full(len(layout.positives), np.nan), np.full(len(layout.negatives), np.nan),
                   np.full(len(layout.matched), np.nan))

    def complete(self) -> bool:
        return not (np.isnan(self.pos).any() or np.isnan(self.neg).any() or np.isnan(self.matched).any())

    def score_set(self, layout: Layout) -> mt.ScoreSet:
        return mt.ScoreSet(self.pos, self.neg, layout.neg_weight)


@dataclass
class CVResult:
    name: str
    columns: list[str]
    constraints: list[int]
    hp: dict
    neg_mix: str
    n_trees: int
    fold_best_iterations: list[int]
    oof: Oof
    pooled: dict
    per_fold: list[dict]
    seconds: float
    train_counts: list[dict] = field(default_factory=list)

    def summary(self) -> dict:
        return {"name": self.name, "n_inputs": len(self.columns), "hp": self.hp, "neg_mix": self.neg_mix,
                "n_trees": self.n_trees, "fold_best_iterations": self.fold_best_iterations, "pooled": self.pooled,
                "per_fold": self.per_fold, "seconds": self.seconds}


def make_layout(dev: hd.Development, folds) -> Layout:
    folds = [list(map(int, block)) for block in folds]
    fold_of_year = {year: k for k, block in enumerate(folds) for year in block}
    if len(fold_of_year) != sum(len(b) for b in folds):
        raise ValueError("a year appears in more than one fold")
    positives = dev.positives.reset_index(drop=True)
    negatives = dev.negatives.reset_index(drop=True)
    matched = dev.samples[dev.samples["kind"] == "negative"].reset_index(drop=True)
    arrays = []
    for frame in (positives, negatives, matched):
        unknown = sorted(set(frame["year"].unique()) - set(fold_of_year))
        if unknown:
            raise ValueError(f"years {unknown} are not assigned to any fold")
        arrays.append(frame["year"].map(fold_of_year).to_numpy())
    strata = (negatives["year"].astype(str) + "-" + negatives["region"].astype(str)).to_numpy()
    return Layout(folds, positives, negatives, matched, *arrays, strata)


def _fold_rows(dev: hd.Development, years) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    inside_s = dev.samples["year"].isin(years)
    inside_u = dev.universe["year"].isin(years)
    return (dev.samples[~inside_s], dev.universe[~inside_u], dev.samples[inside_s], dev.universe[inside_u])


def log_loss(labels: np.ndarray, p: np.ndarray, eps: float = 1e-12) -> float:
    p = np.clip(p, eps, 1.0 - eps)
    return float(-np.mean(labels * np.log(p) + (1 - labels) * np.log(1 - p)))


def _design_logloss(pos: np.ndarray, matched: np.ndarray) -> float:
    """Log-loss over positives and matched negatives (weight 1 each): the training design."""
    return log_loss(np.r_[np.ones(len(pos)), np.zeros(len(matched))], np.r_[pos, matched])


def pooled_metrics(layout: Layout, oof: Oof, recalls=(0.8, 0.9, 0.95), fa_shares=(0.01, 0.05)) -> dict:
    out = oof.score_set(layout).point(list(recalls), list(fa_shares))
    out["logloss"] = _design_logloss(oof.pos, oof.matched)
    return out


def per_fold_metrics(layout: Layout, oof: Oof, best_iterations, recall: float = HEADLINE_RECALL) -> list[dict]:
    rows = []
    for k, years in enumerate(layout.folds):
        pos, neg = oof.pos[layout.pos_fold == k], oof.neg[layout.neg_fold == k]
        matched = oof.matched[layout.matched_fold == k]
        weights = layout.neg_weight[layout.neg_fold == k]
        point = mt.ScoreSet(pos, neg, weights).point([recall], [0.01, 0.05])
        rows.append({"fold": k, "years": years, "n_positives": int(len(pos)), "best_iteration": int(best_iterations[k]),
                     f"fa_at_recall_{recall}": point[f"fa_at_recall_{recall}"], "pr_auc": point["pr_auc"],
                     "recall_at_fa_0.01": point["recall_at_fa_0.01"], "recall_at_fa_0.05": point["recall_at_fa_0.05"],
                     "logloss": _design_logloss(pos, matched)})
    return rows


def run_cv(dev: hd.Development, layout: Layout, columns, constraints, hp: dict, neg_mix: str, cfg: dict,
           name: str = "candidate") -> CVResult:
    """Year-blocked CV of one configuration; returns the pooled OOF scores and metrics."""
    started = time.perf_counter()
    settings, seed = cfg["training"], cfg["seed"]
    boosters, best, counts = [], [], []
    for k, years in enumerate(layout.folds):
        train_s, train_u, held_s, _ = _fold_rows(dev, years)
        train = hd.training_frame(train_s, train_u, neg_mix, settings["universe_negatives"], seed + k)
        valid = hd.training_frame(held_s, held_s.iloc[:0], "matched_only", 0, seed)
        booster, best_iteration = hm.fit_booster(train, columns, constraints, hp, seed + k, settings, valid=valid)
        boosters.append(booster)
        best.append(best_iteration)
        counts.append(hm.training_counts(train))
    n_trees = int(round(float(np.median(best))))
    oof = Oof.empty(layout)
    for k, booster in enumerate(boosters):
        hm.extend_booster(booster, n_trees)
        for frame, fold, target in ((layout.positives, layout.pos_fold, oof.pos),
                                    (layout.negatives, layout.neg_fold, oof.neg),
                                    (layout.matched, layout.matched_fold, oof.matched)):
            rows = fold == k
            target[rows] = hm.predict_raw(booster, frame[rows], columns, n_trees)
    return CVResult(name, list(columns), list(constraints), dict(hp), neg_mix, n_trees, best, oof,
                    pooled_metrics(layout, oof), per_fold_metrics(layout, oof, best),
                    time.perf_counter() - started, counts)


# ------------------------------------------------------------------------------------- grid selection

def grid_candidates(grid: dict) -> list[dict]:
    keys = list(grid)
    return [dict(zip(keys, values)) for values in itertools.product(*(grid[k] for k in keys))]


def ranking_key(result: CVResult, index: int = 0) -> tuple:
    """Lowest pooled OOF false-alarm share at 90% recall; ties by lower pooled OOF log-loss; then by order."""
    return (result.pooled[f"fa_at_recall_{HEADLINE_RECALL}"], result.pooled["logloss"], index)


def run_grid(dev: hd.Development, layout: Layout, columns, constraints, cfg: dict, progress=None
             ) -> tuple[list[CVResult], CVResult]:
    """CV every regularised grid point with the configured neg_mix, then the other neg_mix at the best grid point.
    Returns all results (grid order, the extra candidate last) and the selected one."""
    base_mix = cfg["neg_mix"]["default"]
    fixed = {"learning_rate": cfg["training"]["learning_rate"]}
    results = []
    for i, point in enumerate(grid_candidates(cfg["grid"])):
        hp = {**point, **fixed}
        results.append(run_cv(dev, layout, columns, constraints, hp, base_mix, cfg, f"grid_{i:02d}"))
        if progress:
            progress(results[-1])
    best = min(range(len(results)), key=lambda i: ranking_key(results[i], i))
    extra = run_cv(dev, layout, columns, constraints, results[best].hp, cfg["neg_mix"]["extra_candidate"], cfg,
                   f"grid_{best:02d}_{cfg['neg_mix']['extra_candidate']}")
    results.append(extra)
    if progress:
        progress(extra)
    selected = min(range(len(results)), key=lambda i: ranking_key(results[i], i))
    return results, results[selected]


# --------------------------------------------------------------------------------- group selection

def resolve_candidate(spec: dict, base: dict | None, cfg: dict, column_map: dict) -> dict:
    """A group candidate as {name, groups, exclude, columns, constraints}. `add_groups` extends `base` (the previous
    stage's winner)."""
    if "add_groups" in spec:
        if base is None:
            raise ValueError(f"candidate {spec['name']!r} extends the previous stage's winner but there is none")
        groups = base["groups"] + [g for g in spec["add_groups"] if g not in base["groups"]]
        exclude = list(base["exclude"])
        name = f"{base['name']}{spec['name']}"
    else:
        groups, exclude, name = list(spec["groups"]), list(spec.get("exclude", [])), spec["name"]
    columns = [c for c in hd.model_columns(groups, column_map) if c not in exclude]
    return {"name": name, "groups": groups, "exclude": exclude, "columns": columns,
            "constraints": hm.configured_constraints(columns, cfg)}


def all_groups(cfg: dict) -> list[str]:
    """Every feature group any candidate may use (base groups plus the extras the stages add)."""
    groups = list(cfg["groups"])
    for stage in cfg["group_stages"]:
        for spec in stage["candidates"]:
            groups += [g for g in spec.get("groups", []) + spec.get("add_groups", []) if g not in groups]
    return groups


def select_simplest(entries: list[dict]) -> dict:
    """The preferred-simpler rule. `entries` carry `n_inputs`, `fa`, `se`, `order`. Candidates are walked from the
    fewest inputs to the most; a more complex candidate replaces the current choice only if its pooled OOF FA@90 is
    lower by MORE than its own bootstrap standard error."""
    ordered = sorted(entries, key=lambda e: (e["n_inputs"], e["order"]))
    current = ordered[0]
    for entry in ordered[1:]:
        if current["fa"] - entry["fa"] > entry["se"]:
            current = entry
    return current


def bootstrap_oofs(layout: Layout, oofs: dict[str, Oof], cfg: dict, fixed_thresholds=None) -> dict:
    """Paired bootstrap of every OOF scoring: positives as events, universe rows iid within each year-region stratum."""
    sets = {name: oof.score_set(layout) for name, oof in oofs.items()}
    ops, boot = cfg["operating_points"], cfg["bootstrap"]
    return mt.bootstrap_metrics(sets, layout.neg_weight, layout.strata, recalls=ops["recalls"],
                                fa_shares=ops["fa_shares"], n_boot=boot["n"], seed=boot["seed"],
                                fixed_thresholds=fixed_thresholds)


def select_groups(dev: hd.Development, layout: Layout, cfg: dict, hp: dict, neg_mix: str, column_map: dict,
                  known: dict[str, CVResult] | None = None, progress=None
                  ) -> tuple[CVResult, list[dict], dict[str, CVResult]]:
    """Greedy, stage by stage group selection by CV with the selected hyper-parameters.

    Returns the selected CVResult, one table row per candidate (all stages) with its pooled OOF FA@90, bootstrap
    SE / CI, inputs and the stage decision, and every candidate's CVResult by name. `known` maps candidate names to
    CVResults that may be reused.
    """
    known = dict(known or {})
    key = f"fa_at_recall_{HEADLINE_RECALL}"
    table, winner_spec, winner_result, every = [], None, None, {}
    for stage_index, stage in enumerate(cfg["group_stages"]):
        specs = [resolve_candidate(s, winner_spec, cfg, column_map) for s in stage["candidates"]]
        results = {}
        if winner_result is not None:
            results[winner_result.name] = winner_result
            specs = [winner_spec] + specs
        for spec in specs:
            if spec["name"] in results:
                continue
            result = known.get(spec["name"]) or run_cv(dev, layout, spec["columns"], spec["constraints"], hp,
                                                       neg_mix, cfg, spec["name"])
            results[spec["name"]] = result
            if progress:
                progress(stage_index, spec["name"], result)
        every.update(results)
        boots = bootstrap_oofs(layout, {n: r.oof for n, r in results.items()}, cfg)
        entries = []
        for order, spec in enumerate(specs):
            r, samples = results[spec["name"]], boots[spec["name"]][key]
            entries.append({"name": spec["name"], "order": order, "n_inputs": len(spec["columns"]),
                            "fa": r.pooled[key], "se": mt.bootstrap_se(samples),
                            "ci": mt.confidence_interval(samples, cfg["bootstrap"]["level"]), "spec": spec})
        chosen = select_simplest(entries)
        for entry in entries:
            table.append({"stage": stage_index, "name": entry["name"], "n_inputs": entry["n_inputs"],
                          "groups": entry["spec"]["groups"], "exclude": entry["spec"]["exclude"],
                          "fa_at_90": entry["fa"], "se": entry["se"], "ci_lo": entry["ci"][0],
                          "ci_hi": entry["ci"][1], "pr_auc": results[entry["name"]].pooled["pr_auc"],
                          "logloss": results[entry["name"]].pooled["logloss"],
                          "n_trees": results[entry["name"]].n_trees, "selected_in_stage": entry is chosen})
        winner_spec, winner_result = chosen["spec"], results[chosen["name"]]
    return winner_result, table, every


def presence_comparison(layout: Layout, oofs: dict[str, Oof], column: str, cfg: dict) -> dict:
    """Pooled OOF metrics of each scoring separately on rows WITH and WITHOUT `column` > 0 (station presence), so a
    gain that only comes from the presence of a nearby station is visible. FA@90 uses the subset's own threshold."""
    key, ops, boot = f"fa_at_recall_{HEADLINE_RECALL}", cfg["operating_points"], cfg["bootstrap"]
    present_pos = (layout.positives[column].to_numpy() > 0)
    present_neg = (layout.negatives[column].to_numpy() > 0)
    out = {"column": column}
    for label, flag in (("with_station", True), ("without_station", False)):
        p_rows, n_rows = present_pos == flag, present_neg == flag
        sets = {name: mt.ScoreSet(oof.pos[p_rows], oof.neg[n_rows], layout.neg_weight[n_rows])
                for name, oof in oofs.items()}
        boots = mt.bootstrap_metrics(sets, layout.neg_weight[n_rows], layout.strata[n_rows], recalls=[HEADLINE_RECALL],
                                     fa_shares=[0.05], n_boot=boot["n"], seed=boot["seed"])
        entry = {"n_positives": int(p_rows.sum()), "universe_share": float(layout.neg_weight[n_rows].sum()
                                                                            / layout.neg_weight.sum()),
                 "metrics": {name: {k: mt.summarize(v, boots[name][k], boot["level"])
                                    for k, v in scoring.point([HEADLINE_RECALL], [0.05]).items() if k in boots[name]}
                             for name, scoring in sets.items()}}
        out[label] = entry
    out["note"] = ("FA@90 within each subset uses that subset's own 90%-recall threshold; recall @ FA 5% likewise; "
                   f"the key metric is {key}")
    return out


# ------------------------------------------------------------------------- calibration and thresholds

def fit_calibrator(layout: Layout, oof: Oof) -> cal.MonotoneCalibrator:
    """Weighted isotonic regression on the pooled OOF positives (weight 1) and universe negatives (their weights)."""
    scores = np.r_[oof.pos, oof.neg]
    labels = np.r_[np.ones(len(oof.pos)), np.zeros(len(oof.neg))]
    return cal.MonotoneCalibrator.fit(scores, labels, np.r_[np.ones(len(oof.pos)), layout.neg_weight])


def crossfit_risk(layout: Layout, oof: Oof) -> tuple[np.ndarray, np.ndarray]:
    """Calibrated OOF risk where each fold is calibrated by an isotonic map fitted on the OTHER folds only."""
    risk_pos, risk_neg = np.full(len(oof.pos), np.nan), np.full(len(oof.neg), np.nan)
    weights = layout.neg_weight
    for k in range(len(layout.folds)):
        p_in, n_in = layout.pos_fold != k, layout.neg_fold != k
        calibrator = cal.MonotoneCalibrator.fit(
            np.r_[oof.pos[p_in], oof.neg[n_in]], np.r_[np.ones(p_in.sum()), np.zeros(n_in.sum())],
            np.r_[np.ones(p_in.sum()), weights[n_in]])
        risk_pos[~p_in], risk_neg[~n_in] = calibrator.predict(oof.pos[~p_in]), calibrator.predict(oof.neg[~n_in])
    return risk_pos, risk_neg


def calibration_summary(layout: Layout, oof: Oof, calibrator: cal.MonotoneCalibrator, cfg: dict) -> dict:
    """OOF calibration: deciles + ECE for the saved calibrator (in-sample on the pooled OOF) and the cross-fitted one,
    and per-year mean predicted versus observed risk."""
    crossfit = crossfit_risk(layout, oof)
    insample = (calibrator.predict(oof.pos), calibrator.predict(oof.neg))
    labels = np.r_[np.ones(len(oof.pos)), np.zeros(len(oof.neg))]
    weights = np.r_[np.ones(len(oof.pos)), layout.neg_weight]
    edges = cal.decile_edges(cfg["calibration"]["deciles"])
    out = {"base_rate": float(len(oof.pos) / layout.neg_weight.sum())}
    for label, (rp, rn) in (("insample", insample), ("crossfit", crossfit)):
        risk = np.r_[rp, rn]
        table = cal.reliability_table(risk, labels, weights, edges)
        out[label] = {"ece_deciles": cal.expected_calibration_error(table),
                      "mean_predicted": float(np.average(risk, weights=weights)), "deciles": table}
        years = {}
        for year in sorted(set(layout.positives["year"]) | set(layout.negatives["year"])):
            p_y, n_y = (layout.positives["year"] == year).to_numpy(), (layout.negatives["year"] == year).to_numpy()
            population = float(layout.neg_weight[n_y].sum()) + float(p_y.sum())
            predicted = (float(rp[p_y].sum()) + float(np.sum(layout.neg_weight[n_y] * rn[n_y]))) / population
            years[int(year)] = {"positives": int(p_y.sum()), "population": population, "mean_predicted": predicted,
                                "observed": float(p_y.sum()) / population}
        out[label]["per_year"] = years
    return out


def _region_calibrator(pos: np.ndarray, pos_region: np.ndarray, neg: np.ndarray, neg_region: np.ndarray,
                       weights: np.ndarray, regions, min_positives: int) -> cal.RegionCalibrator:
    """Pooled isotonic map plus one per region with at least `min_positives` positives among the given rows. Universe
    weights are fixed per year-region, so a region's own map estimates P at that region's own base rate."""
    pooled = cal.MonotoneCalibrator.fit(np.r_[pos, neg], np.r_[np.ones(len(pos)), np.zeros(len(neg))],
                                        np.r_[np.ones(len(pos)), weights])
    by_region = {}
    for region in regions:
        p_r, n_r = pos_region == region, neg_region == region
        if p_r.sum() >= min_positives:
            by_region[region] = cal.MonotoneCalibrator.fit(
                np.r_[pos[p_r], neg[n_r]], np.r_[np.ones(p_r.sum()), np.zeros(n_r.sum())],
                np.r_[np.ones(p_r.sum()), weights[n_r]])
    return cal.RegionCalibrator(by_region, pooled, min_positives)


def region_positive_counts(layout: Layout, regions) -> dict[str, int]:
    """Out-of-fold positives per region (what `fit_region_calibrator` compares with `min_positives`)."""
    return {r: int((layout.positives["region"] == r).sum()) for r in regions}


def fit_region_calibrator(layout: Layout, oof: Oof, regions, min_positives: int) -> cal.RegionCalibrator:
    """Per-region weighted isotonic calibrators on the pooled OOF scores; a region with fewer than `min_positives`
    OOF positives is left to the pooled calibrator (identical to `fit_calibrator`)."""
    return _region_calibrator(oof.pos, layout.positives["region"].to_numpy(), oof.neg,
                              layout.negatives["region"].to_numpy(), layout.neg_weight, list(regions), min_positives)


def crossfit_region_risk(layout: Layout, oof: Oof, regions, min_positives: int) -> tuple[np.ndarray, np.ndarray]:
    """Calibrated OOF risk where each fold is calibrated by a RegionCalibrator fitted on the OTHER folds only (the
    `min_positives` rule applies to those folds' positives)."""
    pos_region, neg_region = layout.positives["region"].to_numpy(), layout.negatives["region"].to_numpy()
    risk_pos, risk_neg = np.full(len(oof.pos), np.nan), np.full(len(oof.neg), np.nan)
    for k in range(len(layout.folds)):
        p_in, n_in = layout.pos_fold != k, layout.neg_fold != k
        calibrator = _region_calibrator(oof.pos[p_in], pos_region[p_in], oof.neg[n_in], neg_region[n_in],
                                        layout.neg_weight[n_in], list(regions), min_positives)
        risk_pos[~p_in] = calibrator.predict(oof.pos[~p_in], pos_region[~p_in])
        risk_neg[~n_in] = calibrator.predict(oof.neg[~n_in], neg_region[~n_in])
    return risk_pos, risk_neg


def region_calibration_summary(layout: Layout, oof: Oof, regions, min_positives: int, cfg: dict) -> dict:
    """Per region, the cross-fitted calibration of the per-region calibrators and, for comparison, of the pooled
    calibrator on the same rows: deciles, ECE, mean predicted versus observed risk (per cell-day at the region's own
    base rate), the OOF positives and which calibrator the saved model uses for the region."""
    regions = list(regions)
    saved = fit_region_calibrator(layout, oof, regions, min_positives)
    scored = {"crossfit_per_region": crossfit_region_risk(layout, oof, regions, min_positives),
              "crossfit_pooled": crossfit_risk(layout, oof)}
    pos_region, neg_region = layout.positives["region"].to_numpy(), layout.negatives["region"].to_numpy()
    edges = cal.decile_edges(cfg["calibration"]["deciles"])
    out = {"min_region_positives": int(min_positives), "regions": {}}
    for region in regions:
        p_r, n_r = pos_region == region, neg_region == region
        weights = np.r_[np.ones(p_r.sum()), layout.neg_weight[n_r]]
        labels = np.r_[np.ones(p_r.sum()), np.zeros(n_r.sum())]
        entry = {"positives": int(p_r.sum()), "population": float(weights.sum()),
                 "observed": float(p_r.sum() / weights.sum()),
                 "calibrator": "own" if region in saved.by_region else "pooled (fewer positives than the minimum)"}
        for label, (risk_pos, risk_neg) in scored.items():
            risk = np.r_[risk_pos[p_r], risk_neg[n_r]]
            table = cal.reliability_table(risk, labels, weights, edges)
            entry[label] = {"ece_deciles": cal.expected_calibration_error(table),
                            "mean_predicted": float(np.average(risk, weights=weights)), "deciles": table}
        out["regions"][region] = entry
    return out


def threshold_entry(scoring: mt.ScoreSet, threshold: float,
                    calibrator: cal.MonotoneCalibrator | cal.RegionCalibrator | None, regions=()) -> dict:
    """A threshold on the RAW score scale with the risk it corresponds to under `calibrator`. With a RegionCalibrator
    `risk` is the pooled calibrator's value (the one used for regions without their own and for frames without a
    region column) and `risk_by_region` gives the value under each region's calibrator."""
    pooled = calibrator.pooled if isinstance(calibrator, cal.RegionCalibrator) else calibrator
    entry = {"raw": threshold, "risk": None if pooled is None else float(pooled.predict([threshold])[0]),
             "oof_recall": scoring.recall_at(np.sort(scoring.pos)[::-1], threshold),
             "oof_fa_share": scoring.fa_at(threshold)}
    if isinstance(calibrator, cal.RegionCalibrator):
        entry["risk_by_region"] = {r: float(calibrator.predict([threshold], r)[0]) for r in regions}
    return entry


def operating_thresholds(layout: Layout, oof: Oof, calibrator: cal.MonotoneCalibrator | cal.RegionCalibrator | None,
                         cfg: dict) -> dict:
    """Thresholds from the pooled OOF scores: plain 90% recall, the recall-first margin threshold (highest threshold
    whose bootstrap 5th-percentile OOF recall is at least 90%), and the Phase 4 alert levels. Thresholds are raw
    scores, independent of the calibrator; only the `risk` reported next to each depends on the calibrator the model
    actually uses (see `threshold_entry`)."""
    scoring, rf = oof.score_set(layout), cfg["recall_first"]
    regions = sorted(layout.negatives["region"].unique())

    def entry(threshold: float) -> dict:
        return threshold_entry(scoring, threshold, calibrator, regions)

    plain = scoring.threshold_for_recall(rf["recall"])
    first = mt.recall_first_threshold(oof.pos, rf["recall"], cfg["bootstrap"]["n"], cfg["bootstrap"]["seed"],
                                      rf["percentile"])
    levels = cfg["alert_levels"]
    return {"plain_recall_90": entry(plain), "recall_first": entry(first), "watch": entry(first),
            "warning": entry(scoring.threshold_for_recall(levels["warning_recall"])),
            "emergency": entry(scoring.threshold_for_recall(levels["emergency_recall"]))}


# ------------------------------------------------------------------------------------------ baselines

def run_cv_baselines(dev: hd.Development, layout: Layout, cfg: dict) -> dict[str, Oof]:
    """The three baselines under the same protocol: every baseline is refitted inside each fold on that fold's
    training rows (thresholds, classes and coefficients), and scores the fold's held-out rows."""
    oofs: dict[str, Oof] = {}
    for k, years in enumerate(layout.folds):
        train_s, train_u, _, _ = _fold_rows(dev, years)
        fitted = bl.fit_baselines(train_s, train_u)
        for name, baseline in fitted.items():
            target = oofs.setdefault(name, Oof.empty(layout))
            for frame, fold, scores in ((layout.positives, layout.pos_fold, target.pos),
                                        (layout.negatives, layout.neg_fold, target.neg),
                                        (layout.matched, layout.matched_fold, target.matched)):
                rows = fold == k
                scores[rows] = baseline.score(frame[rows])
    return oofs


def resolve_all_candidates(cfg: dict, column_map: dict, winners: list[str]) -> list[dict]:
    """Every group candidate of every stage as resolved specs, given each stage's selected name (`winners[i]` for stage
    `i`), so later stages extend the right base. The earlier winner is not repeated in the next stage's list."""
    out, base = [], None
    for stage, winner in zip(cfg["group_stages"], winners):
        specs = [resolve_candidate(s, base, cfg, column_map) for s in stage["candidates"]]
        out += specs
        chosen = [s for s in ([base] if base else []) + specs if s["name"] == winner]
        if not chosen:
            raise ValueError(f"selected group {winner!r} is not a candidate of its stage")
        base = chosen[0]
    return out
