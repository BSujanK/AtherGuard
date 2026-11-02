"""Challenger experiments against the selected v3-live model (Task 5), all live-consistent (IMERG rain and terrain only).

    python -m aetherguard.hazard.challengers --config configs/hazard_v3.yaml [--only NAME]

Everything reuses the protocol-v2 machinery of `hazard.cv` / `hazard.metrics`: the same year-blocked folds, the same
development rows and universe-negative draws (seed + fold), the same weights, the same pooled FA@90 and the same
bootstrap (positives iid as events, universe rows iid within each year-region stratum). Candidates:

* LightGBM with extra feature groups (`challengers.lightgbm` of the configuration), at the selected hyper-parameters;
* CatBoost on the selected v3 columns with the same monotone constraints, a depth x l2_leaf_reg grid, early stopping per
  fold and the median tree count (`hazard.catboost_learner`);
* a rank-average blend of the best LightGBM and the best CatBoost.

Before any challenger is run, the harness recomputes the OOF scores of the selected v3 configuration and of the frozen
v2 configuration and checks their pooled FA@90 against the values their training runs reported.

Every candidate's out-of-fold scores are saved to `data/processed/hazard/challengers/oof_<name>.parquet` (row keys,
fold, label, weight, stratum and the raw score) so any two can be paired later; `paired_fa_difference` bootstraps
FA@90(a) - FA@90(b) on identical rows with the SAME resample for both. A challenger replaces the selected
configuration only if its pooled OOF FA@90 is lower by MORE than the paired standard error of the difference
(`adoption`). test_2018 is never read here.
"""
from __future__ import annotations

import argparse
import itertools
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import PROJECT_ROOT, data_root
from . import catboost_learner as cbl
from . import cv
from . import data as hd
from . import metrics as mt
from . import model as hm
from . import train as tr
from .jsonio import dump_json

HEADLINE = f"fa_at_recall_{cv.HEADLINE_RECALL}"
POSITIVE, UNIVERSE, MATCHED = "positive", "universe", "matched"
OOF_COLUMNS = ["kind", "cell_id", "date", "region", "year", "stratum", "fold", "label", "weight", "score"]
SAME_ROWS = ["kind", "cell_id", "date", "fold"]
REPRODUCTION_TOLERANCE = 5e-4
ADOPTION_EPS = 1e-12            # "more than one SE" must not hinge on floating-point noise
INCUMBENT = "v3_selected"
FROZEN_V2 = "v2_selected"
BLEND = "blend_rank"
DEFAULT_REPORT_STEM = "phase6_challengers"


class ReproductionError(RuntimeError):
    """The harness does not reproduce the FA@90 a training run reported."""


# ----------------------------------------------------------------------------------------- OOF frames

def oof_frame(layout: cv.Layout, oof: cv.Oof) -> pd.DataFrame:
    """The OOF scores of a layout as one frame: positives, universe negatives, matched negatives (in layout order)."""
    parts = []
    for kind, frame, fold, scores, weight, stratum in (
            (POSITIVE, layout.positives, layout.pos_fold, oof.pos, np.ones(len(layout.positives)), None),
            (UNIVERSE, layout.negatives, layout.neg_fold, oof.neg, layout.neg_weight, layout.strata),
            (MATCHED, layout.matched, layout.matched_fold, oof.matched, np.ones(len(layout.matched)), None)):
        parts.append(pd.DataFrame({
            "kind": kind, "cell_id": frame["cell_id"].to_numpy(dtype=np.int64), "date": frame["date"].to_numpy(),
            "region": frame["region"].to_numpy(), "year": frame["year"].to_numpy(dtype=np.int16),
            "stratum": stratum if stratum is not None else None, "fold": np.asarray(fold, dtype=np.int8),
            "label": np.int8(1 if kind == POSITIVE else 0), "weight": np.asarray(weight, dtype=np.float64),
            "score": np.asarray(scores, dtype=np.float64)}))
    frame = pd.concat(parts, ignore_index=True)[OOF_COLUMNS]
    return frame.assign(stratum=frame["stratum"].astype("str"))


def write_oof(path: Path, frame: pd.DataFrame) -> Path:
    if frame["score"].isna().any():
        raise ValueError(f"{Path(path).name}: {int(frame['score'].isna().sum())} NaN scores; a complete OOF is required")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    return path


def read_oof(path: Path) -> pd.DataFrame:
    return pd.read_parquet(path)


def oof_scores(frame: pd.DataFrame) -> cv.Oof:
    by_kind = {k: frame.loc[frame["kind"] == k, "score"].to_numpy(dtype=np.float64) for k in (POSITIVE, UNIVERSE, MATCHED)}
    return cv.Oof(by_kind[POSITIVE], by_kind[UNIVERSE], by_kind[MATCHED])


def score_set(frame: pd.DataFrame) -> mt.ScoreSet:
    """The positives and weighted universe negatives of an OOF frame as a ScoreSet (what FA@90 is computed on)."""
    positives, universe = frame[frame["kind"] == POSITIVE], frame[frame["kind"] == UNIVERSE]
    return mt.ScoreSet(positives["score"].to_numpy(), universe["score"].to_numpy(), universe["weight"].to_numpy())


def assert_same_rows(a: pd.DataFrame, b: pd.DataFrame) -> None:
    """Two OOF frames must score the same rows in the same order (kind, keys, fold, weights)."""
    same = (len(a) == len(b) and all(np.array_equal(a[c].to_numpy(), b[c].to_numpy()) for c in SAME_ROWS)
            and np.allclose(a["weight"].to_numpy(), b["weight"].to_numpy(), rtol=1e-12, atol=0.0))
    if not same:
        raise ValueError(f"OOF frames do not score the same rows ({len(a)} versus {len(b)} rows, or different "
                         "kind / cell_id / date / fold / weight); pairing needs identical rows")


# --------------------------------------------------------------------------------------- paired bootstrap

def bootstrap_frames(frames: dict[str, pd.DataFrame], n_boot: int, seed: int, recalls=(cv.HEADLINE_RECALL,),
                     fa_shares=()) -> dict[str, dict[str, np.ndarray]]:
    """`metrics.bootstrap_metrics` over OOF frames that score the SAME rows: one resample per draw shared by all."""
    names = list(frames)
    first = frames[names[0]]
    for name in names[1:]:
        assert_same_rows(first, frames[name])
    universe = first[first["kind"] == UNIVERSE]
    return mt.bootstrap_metrics({n: score_set(f) for n, f in frames.items()}, universe["weight"].to_numpy(),
                                universe["stratum"].to_numpy(dtype=str), recalls=list(recalls),
                                fa_shares=list(fa_shares), n_boot=n_boot, seed=seed)


def _difference(a_samples: np.ndarray, b_samples: np.ndarray, a_point: float, b_point: float, level: float) -> dict:
    diff = np.asarray(a_samples, dtype=np.float64) - np.asarray(b_samples, dtype=np.float64)
    lo, hi = mt.confidence_interval(diff, level)
    return {"fa_a": float(a_point), "fa_b": float(b_point), "point_difference": float(a_point - b_point),
            "mean_difference": float(diff.mean()), "se": mt.bootstrap_se(diff), "ci_lo": lo, "ci_hi": hi,
            "level": level, "n_boot": int(len(diff)), "excludes_zero": bool(lo > 0 or hi < 0),
            "share_a_better": float(np.mean(diff < 0)), "share_tied": float(np.mean(diff == 0))}


def paired_fa_differences(frames: dict[str, pd.DataFrame], pairs, n_boot: int, seed: int, level: float = 0.95,
                          recalls=(cv.HEADLINE_RECALL,), fa_shares=()) -> dict:
    """FA@90(a) - FA@90(b) for every (a, b) in `pairs` from ONE bootstrap whose resample is shared by all scorings, so
    each pair is paired. Returns {"differences": {"a-b": {...}}, "metrics": {name: {metric: {value, lo, hi, se}}}}.
    Negative differences favour a (lower false-alarm share)."""
    boots = bootstrap_frames(frames, n_boot, seed, recalls, fa_shares)
    points = {n: score_set(f).point(list(recalls), list(fa_shares)) for n, f in frames.items()}
    differences = {f"{a}-{b}": _difference(boots[a][HEADLINE], boots[b][HEADLINE], points[a][HEADLINE],
                                           points[b][HEADLINE], level) for a, b in pairs}
    metrics = {n: {k: {**mt.summarize(points[n][k], boots[n][k], level), "se": mt.bootstrap_se(boots[n][k])}
                   for k in points[n]} for n in frames}
    return {"differences": differences, "metrics": metrics}


def paired_fa_difference(oof_a: pd.DataFrame, oof_b: pd.DataFrame, n_boot: int, seed: int, level: float = 0.95) -> dict:
    """Bootstrap of FA@90(a) - FA@90(b) on identical rows, resampling like the protocol-v2 bootstrap (positives as
    events, universe rows iid within each year-region stratum) with the SAME resample indices for both scorings.
    Reports the point and mean difference, its percentile CI, SE and whether the CI excludes zero."""
    out = paired_fa_differences({"a": oof_a, "b": oof_b}, [("a", "b")], n_boot, seed, level)
    return out["differences"]["a-b"]


# ------------------------------------------------------------------------------------------ adoption rule

def adoption(incumbent_fa: float, challenger_fa: float, se: float) -> dict:
    """A challenger replaces the incumbent only if its pooled OOF FA@90 is lower by MORE than `se`, the bootstrap SE
    of the paired difference."""
    gain = float(incumbent_fa - challenger_fa)
    return {"adopt": bool(gain - se > ADOPTION_EPS), "gain": gain, "se": float(se),
            "gain_over_se": gain / se if se > 0 else (float("inf") if gain > 0 else 0.0)}


def choose_adoption(incumbent_fa: float, rows: list[dict]) -> dict | None:
    """Among challengers (dicts with `fa` and the paired `se`) that satisfy the rule, the one with the lowest FA@90."""
    qualifying = [{**r, "decision": adoption(incumbent_fa, r["fa"], r["se"])} for r in rows]
    qualifying = [r for r in qualifying if r["decision"]["adopt"]]
    return min(qualifying, key=lambda r: r["fa"]) if qualifying else None


# -------------------------------------------------------------------------------------------------- blend

def rank_blend(a: pd.DataFrame, b: pd.DataFrame) -> pd.DataFrame:
    """Rank-average of two scorings of the same rows: within each fold, every row's score becomes its mid-rank share
    among that fold's positives and universe negatives under each scoring, and the two are averaged. The result is a
    ranking score in (0, 1), not a probability."""
    assert_same_rows(a, b)
    out = a.copy()
    blended = np.zeros(len(a))
    for frame in (a, b):
        scores = frame["score"].to_numpy(dtype=np.float64)
        for fold in np.unique(frame["fold"]):
            in_fold = (frame["fold"] == fold).to_numpy()
            reference = np.sort(scores[in_fold & (frame["kind"] != MATCHED).to_numpy()])
            ranks = (np.searchsorted(reference, scores[in_fold], side="left")
                     + np.searchsorted(reference, scores[in_fold], side="right")) / (2.0 * len(reference))
            blended[in_fold] += ranks / 2.0
    out["score"] = blended
    return out


# ------------------------------------------------------------------------------------ CatBoost cross-validation

def run_cv_catboost(dev: hd.Development, layout: cv.Layout, columns, constraints, hp: dict, neg_mix: str, cfg: dict,
                    name: str, thread_count: int = cbl.MAX_THREADS) -> cv.CVResult:
    """`cv.run_cv` for CatBoost: per fold, early stopping on the held-out weighted log-loss picks a tree count; the
    candidate's count is the median over folds and every fold model is then REFITTED with exactly that many trees
    (a CatBoost model is not a prefix of a longer run), so OOF scores and the final refit use the same setting."""
    started = time.perf_counter()
    settings, seed = cfg["training"], cfg["seed"]
    trains, best, counts = [], [], []
    for k, years in enumerate(layout.folds):
        train_s, train_u, held_s, _ = cv._fold_rows(dev, years)
        train = hd.training_frame(train_s, train_u, neg_mix, settings["universe_negatives"], seed + k)
        valid = hd.training_frame(held_s, held_s.iloc[:0], "matched_only", 0, seed)
        _, best_count = cbl.fit_catboost(train, columns, constraints, hp, seed + k, settings, valid=valid,
                                         thread_count=thread_count)
        trains.append(train)
        best.append(best_count)
        counts.append(hm.training_counts(train))
    n_trees = int(round(float(np.median(best))))
    oof = cv.Oof.empty(layout)
    for k, train in enumerate(trains):
        model, _ = cbl.fit_catboost(train, columns, constraints, hp, seed + k, settings, num_rounds=n_trees,
                                    thread_count=thread_count)
        for frame, fold, target in ((layout.positives, layout.pos_fold, oof.pos),
                                    (layout.negatives, layout.neg_fold, oof.neg),
                                    (layout.matched, layout.matched_fold, oof.matched)):
            rows = fold == k
            target[rows] = cbl.predict_raw(model, frame[rows], columns)
    return cv.CVResult(name, list(columns), list(constraints), dict(hp), neg_mix, n_trees, best, oof,
                       cv.pooled_metrics(layout, oof), cv.per_fold_metrics(layout, oof, best),
                       time.perf_counter() - started, counts)


# ------------------------------------------------------------------------------------------- the harness

def challenger_settings(cfg: dict) -> dict:
    if "challengers" not in cfg:
        raise ValueError("the configuration has no `challengers` section")
    return cfg["challengers"]


def oof_dir(cfg: dict) -> Path:
    name = challenger_settings(cfg).get("oof_dir", "challengers")
    if Path(name).name != name or name in (".", ".."):
        raise ValueError(f"challengers.oof_dir must be a plain directory name under data/processed/hazard, got {name!r}")
    return data_root() / "processed" / "hazard" / name


def catboost_candidates(cfg: dict) -> list[dict]:
    """The CatBoost grid points as {name, hp}; hp carries CatBoost's own learning rate (`challengers.catboost.
    learning_rate`, default the LightGBM one: symmetric trees are weaker, so a higher rate is configured to converge
    within `training.max_rounds`)."""
    settings = challenger_settings(cfg)["catboost"]
    rate = settings.get("learning_rate", cfg["training"]["learning_rate"])
    depths, l2s = settings["grid"]["depth"], settings["grid"]["l2_leaf_reg"]
    return [{"name": f"cb_d{depth}_l2_{l2:g}", "hp": {"depth": depth, "l2_leaf_reg": l2, "learning_rate": rate}}
            for depth, l2 in itertools.product(depths, l2s)]


def lightgbm_candidates(cfg: dict) -> list[dict]:
    return list(challenger_settings(cfg).get("lightgbm", []))


def candidate_names(cfg: dict) -> list[str]:
    return ([INCUMBENT, FROZEN_V2] + [c["name"] for c in lightgbm_candidates(cfg)]
            + [c["name"] for c in catboost_candidates(cfg)] + [BLEND])


def load_world(cfg: dict, groups=(), directory: Path | None = None) -> tuple[hd.Development, cv.Layout]:
    """Development rows with the configuration's extra groups plus those of `groups` that are extra groups (base groups
    need no loading; unknown ones fail when the columns are resolved), and the CV layout."""
    use = list(dict.fromkeys(tr.extra_groups_used(cfg) + [g for g in groups if g in cfg["extra_groups"]]))
    dev = hd.load_development(directory, cfg["extra_groups"], use, cfg["meta_columns"])
    return dev, cv.make_layout(dev, cfg["cv"]["folds"])


def reproduce_selected(dev: hd.Development, layout: cv.Layout, cfg: dict, model_dir: Path, name: str
                       ) -> tuple[cv.CVResult, dict]:
    """Re-run the CV of the model saved in `model_dir` (its `cv_results.json` `selected` entry) and compare the pooled
    FA@90 with the one its training run reported."""
    selected = json.loads((Path(model_dir) / "cv_results.json").read_text(encoding="utf-8"))["selected"]
    columns = selected["columns"]
    result = cv.run_cv(dev, layout, columns, hm.configured_constraints(columns, cfg), selected["hp"],
                       selected["neg_mix"], cfg, name)
    reported = selected["pooled"][HEADLINE]
    record = {"name": selected["name"], "model_dir": hm.display_path(model_dir), "recomputed_fa_at_90": result.pooled[HEADLINE],
              "reported_fa_at_90": reported, "abs_difference": abs(result.pooled[HEADLINE] - reported),
              "n_trees": result.n_trees, "reported_n_trees": selected["n_trees"]}
    if record["abs_difference"] > REPRODUCTION_TOLERANCE or result.n_trees != selected["n_trees"]:
        raise ReproductionError(f"{name}: recomputed FA@90 {result.pooled[HEADLINE]:.6f} / {result.n_trees} trees versus "
                                f"reported {reported:.6f} / {selected['n_trees']} trees")
    return result, record


def _meta(result: cv.CVResult, family: str, description: str, **extra) -> dict:
    return {"name": result.name, "family": family, "description": description, "columns": result.columns,
            "n_inputs": len(result.columns), "hp": result.hp, "neg_mix": result.neg_mix, "n_trees": result.n_trees,
            "fold_best_iterations": result.fold_best_iterations, "seconds": result.seconds, "probabilistic": True,
            "adoptable": True, **extra}


def save_candidate(directory: Path, frame: pd.DataFrame, meta: dict) -> None:
    directory = Path(directory)
    write_oof(directory / f"oof_{meta['name']}.parquet", frame)
    dump_json(directory / f"oof_{meta['name']}.json", meta)


def load_candidates(directory: Path, names: list[str]) -> tuple[dict[str, pd.DataFrame], dict[str, dict]]:
    """Saved OOF frames and metadata, in registry order, for those names that have been run."""
    frames, metas = {}, {}
    for name in names:
        path = Path(directory) / f"oof_{name}.parquet"
        if path.is_file():
            frames[name] = read_oof(path)
            metas[name] = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    return frames, metas


def best_of(frames: dict[str, pd.DataFrame], metas: dict[str, dict], family: str) -> str | None:
    """The candidate of `family` with the lowest pooled FA@90 (tie by lower design log-loss, then registry order)."""
    ranked = []
    for order, (name, meta) in enumerate(metas.items()):
        if meta["family"] != family:
            continue
        oof = oof_scores(frames[name])
        point = score_set(frames[name]).point([cv.HEADLINE_RECALL], [])[HEADLINE]
        ranked.append((point, cv.log_loss(np.r_[np.ones(len(oof.pos)), np.zeros(len(oof.matched))],
                                          np.r_[oof.pos, oof.matched]), order, name))
    return min(ranked)[3] if ranked else None


def run(config: Path, only: set[str] | None = None, say=print, directory: Path | None = None,
        report: bool = True) -> dict:
    """Run the incumbents, the requested challengers (all when `only` is None) and the blend, saving every OOF; then
    write the report. Returns the report payload."""
    started = time.perf_counter()
    cfg = hm.hazard_config(config)
    names = candidate_names(cfg)
    if only is not None and (unknown := sorted(only - set(names))):
        raise ValueError(f"unknown candidates {unknown}; choose from {names}")

    def wanted(name: str) -> bool:
        return only is None or name in only

    out = oof_dir(cfg)
    lgb_specs = lightgbm_candidates(cfg)
    dev, layout = load_world(cfg, [g for spec in lgb_specs for g in spec["groups"]], directory)
    say(f"development rows: {len(layout.positives)} positives, {len(layout.negatives):,} universe negatives, "
        f"{len(layout.matched)} matched negatives")

    incumbent, repro_v3 = reproduce_selected(dev, layout, cfg, hm.configured_model_dir(cfg), INCUMBENT)
    say(f"v3 reproduced: FA@90 {incumbent.pooled[HEADLINE]:.6f} (reported {repro_v3['reported_fa_at_90']:.6f}), "
        f"{incumbent.n_trees} trees")
    save_candidate(out, oof_frame(layout, incumbent.oof),
                   _meta(incumbent, "lightgbm", "selected v3-live configuration (reproduced)"))
    v2_cfg = hm.hazard_config()
    v2_dev, v2_layout = load_world(v2_cfg, (), directory)
    v2, repro_v2 = reproduce_selected(v2_dev, v2_layout, v2_cfg, hm.default_model_dir(), FROZEN_V2)
    say(f"v2 reproduced: FA@90 {v2.pooled[HEADLINE]:.6f} (reported {repro_v2['reported_fa_at_90']:.6f}), "
        f"{v2.n_trees} trees")
    v2_frame = oof_frame(v2_layout, v2.oof)
    assert_same_rows(oof_frame(layout, incumbent.oof), v2_frame)
    save_candidate(out, v2_frame, _meta(v2, "frozen_v2", "frozen v2 configuration (reproduced from configs/hazard.yaml)",
                                        adoptable=False))

    for spec in lgb_specs:
        if not wanted(spec["name"]):
            continue
        resolved = cv.resolve_candidate(spec, None, cfg, dev.column_map)
        result = cv.run_cv(dev, layout, resolved["columns"], resolved["constraints"], incumbent.hp, incumbent.neg_mix,
                           cfg, spec["name"])
        say(f"{spec['name']}: FA@90 {result.pooled[HEADLINE]:.4f} ({result.n_trees} trees, {result.seconds:.0f}s)")
        save_candidate(out, oof_frame(layout, result.oof),
                       _meta(result, "lightgbm", spec.get("description", f"LightGBM, groups {spec['groups']}")))
    thread_count = challenger_settings(cfg)["catboost"].get("thread_count", cbl.MAX_THREADS)
    for spec in catboost_candidates(cfg):
        if not wanted(spec["name"]):
            continue
        result = run_cv_catboost(dev, layout, incumbent.columns, incumbent.constraints, spec["hp"], incumbent.neg_mix,
                                 cfg, spec["name"], thread_count)
        say(f"{spec['name']}: FA@90 {result.pooled[HEADLINE]:.4f} ({result.n_trees} trees, {result.seconds:.0f}s)")
        save_candidate(out, oof_frame(layout, result.oof), _meta(result, "catboost", f"CatBoost {spec['hp']}"))

    frames, metas = load_candidates(out, names)
    best_lgb, best_cb = best_of(frames, metas, "lightgbm"), best_of(frames, metas, "catboost")
    if wanted(BLEND) and best_lgb and best_cb:
        blend = rank_blend(frames[best_lgb], frames[best_cb])
        meta = {"name": BLEND, "family": "blend", "parents": [best_lgb, best_cb], "columns": [], "n_inputs": None,
                "hp": {}, "neg_mix": None, "n_trees": None, "fold_best_iterations": [], "seconds": 0.0,
                "probabilistic": False, "adoptable": False,
                "description": f"within-fold rank average of {best_lgb} and {best_cb}; a ranking score, so it needs a "
                               "reference distribution and cannot be scored on a single live day"}
        save_candidate(out, blend, meta)
        say(f"{BLEND}: {best_lgb} + {best_cb}")
    payload = {}
    if report:
        from .challengers_report import write_report
        frames, metas = load_candidates(out, names)
        payload = write_report(cfg, config, frames, metas, {INCUMBENT: repro_v3, FROZEN_V2: repro_v2},
                               {"positives": len(layout.positives), "universe": len(layout.negatives),
                                "matched": len(layout.matched), "identical_to_frozen_v2": True},
                               time.perf_counter() - started)
    return payload


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "configs" / "hazard_v3.yaml")
    parser.add_argument("--only", action="append", default=None, metavar="NAME",
                        help="run only this challenger (repeatable); the incumbents are always recomputed and the "
                             "report covers every saved candidate")
    args = parser.parse_args(argv)
    payload = run(args.config, set(args.only) if args.only else None, say=lambda m: print(m, flush=True))
    if payload:
        adoption_ = payload["adoption"]
        print("adopted: " + (adoption_["adopted"]["name"] if adoption_["adopted"] else "none (selected v3 unchanged)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
