"""Phase 2a evaluation: build (or reuse) the fault dataset, score the baselines on the VALIDATION and TEST
stations, and write reports/phase2a_baselines.md and .json.

    python -m aetherguard.integrity.baseline_report [--rebuild-dataset] [--rebuild-splits] [--fpr 0.01] [--n-boot 1000]

Every table is computed from the observed (fault-injected) matrix; nothing but the isolation forest
learns from data, and it only from the TRAIN stations. Neighbour references use the neighbours'
observed values. The real-flag sanity check runs on the whole recorded history of every station.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from . import baselines, checks, evaluate, inject, neighbours
from .common import display_path, dumps_strict, integrity_dir, reports_dir
from .splits import SPLIT_SEED, make_station_splits
from .stations import StationSet, load_station_set

DATASET_NAME = "fault_dataset.parquet"
DATASET_REPORT_NAME = "fault_dataset_report.json"
DATASET_SEED = 20261001
FOREST_SEED = 20261002
BOOTSTRAP_SEED = 20261003
FPR = 0.01
N_BOOT = 1000
MIN_ELIGIBLE_CLEAN_DAYS = 365   # a station needs this many clean days to count as "eligible" for the split
NEIGHBOUR_SETTINGS = {"design": (5, 150.0), "wide": (10, 300.0)}  # (k, max_km)
EVAL_SPLITS = ("val", "test")
REAL_FLAG_YEARS = (2007, 2024)
SENSITIVITY_MIN_VALID_DAYS = (300, 200, 120)
# genuine-extreme retention variants: (neighbour setting, minimum corroborating neighbours with a value >= 30%
# of the reading). "design" is the definition of the design; the others exist because corroborated extremes
# are very rare in the clean data (see coverage); "uncorroborated" drops the neighbour condition.
RETENTION_VARIANTS = {"design": ("design", 2), "wide": ("wide", 2), "wide_1neighbour": ("wide", 1),
                      "uncorroborated": ("design", 0)}
METHODS = ("range_check", "l1", "noaa_style_qa", "noaa_style_qa_wide", "robust_zscore", "isolation_forest")


@dataclass
class Inputs:
    full: StationSet          # whole recorded history (for the real-flag sanity check and calibration)
    sset: StationSet          # 1990-2024 window
    meta: pd.DataFrame        # sset.meta plus n_clean_days and eligible
    splits: dict
    table: pd.DataFrame
    calibration: dict
    dataset_path: Path
    dataset_report: dict


def _window(full: StationSet, start: str, end: str) -> StationSet:
    return StationSet(values=full.values.loc[start:end], flags=full.flags.loc[start:end], meta=full.meta)


def real_flag_calibration(full: StationSet, sset: StationSet) -> dict:
    """`inject.calibrate_from_real_flags` on the whole recorded history of the set's stations."""
    frames = {sid: pd.DataFrame({"value": full.values[sid], "flag": full.flags[sid]}) for sid in full.meta["id"]}
    return inject.calibrate_from_real_flags(sset, frames)


def eligible_meta(sset: StationSet) -> pd.DataFrame:
    """Station metadata plus the number of clean days and `eligible` (>= MIN_ELIGIBLE_CLEAN_DAYS of them)."""
    meta = sset.meta.assign(n_clean_days=inject.clean_real_mask(sset).sum().to_numpy())
    meta["eligible"] = meta["n_clean_days"] >= MIN_ELIGIBLE_CLEAN_DAYS
    return meta


def prepare(raw_dir=None, rebuild_dataset: bool = False, start: str = "1990-01-01", end: str = "2024-12-31",
            force_splits: bool = False) -> Inputs:
    """Load the stations, freeze/read the splits, calibrate from the real flags, and build or reuse the dataset.

    `force_splits` rebuilds the frozen station split (a deliberate act: it invalidates every earlier result)."""
    full = load_station_set(raw_dir, start=None, end=None)
    sset = _window(full, start, end)
    meta = eligible_meta(sset)
    splits = make_station_splits(meta, seed=SPLIT_SEED, force=force_splits)
    calibration = real_flag_calibration(full, sset)
    path = integrity_dir() / DATASET_NAME
    if rebuild_dataset or not path.is_file():
        table = inject.build_fault_dataset(sset, splits, seed=DATASET_SEED, calibration=calibration)
        table.to_parquet(path, index=False)
    else:
        table = pd.read_parquet(path)
        _check_fresh(table, sset, splits)
    report = inject.dataset_report(table, calibration)
    (integrity_dir() / DATASET_REPORT_NAME).write_text(dumps_strict(report), encoding="utf-8")
    return Inputs(full, sset, meta, splits, table, calibration, path, report)


def _check_fresh(table: pd.DataFrame, sset: StationSet, splits: dict) -> None:
    owner = {sid: name for name, ids in splits.items() for sid in ids}
    first = table.drop_duplicates("station")
    stored = dict(zip(first["station"].astype(str), first["split"].astype(str)))
    same_values = len(table) == sset.values.size and np.array_equal(
        table["value_true"].to_numpy(), sset.values.to_numpy().T.ravel(), equal_nan=True)
    if not same_values or stored != owner:
        raise RuntimeError(f"{DATASET_NAME} does not match the current station values/splits; rerun with --rebuild-dataset")


def _rates(flag: np.ndarray, mask: np.ndarray) -> dict:
    n = int(mask.sum())
    k = int((flag & mask).sum())
    return {"flagged": k, "days": n, "rate": k / n if n else float("nan")}


def l1_false_flag_rates(sset: StationSet, tables: dict[str, pd.DataFrame],
                        min_valid_days: int = inject.MIN_VALID_DAYS_PER_YEAR) -> dict:
    """Share of the REAL clean days each rule flags (measured on the unmodified station values)."""
    clean = inject.clean_real_mask(sset, min_valid_days).to_numpy()
    data = sset.values
    cfg = checks.L1Config()
    out = {"clean_days": int(clean.sum()), "min_valid_days_per_year": min_valid_days,
           "thresholds": {"max_mm": cfg.max_mm, "stuck_min_run": cfg.stuck_min_run, "k_min_run": cfg.k_min_run,
                          "dup_min_block": cfg.dup_min_block, "dup_min_positive": cfg.dup_min_positive},
           "rules": {
               "bounds": _rates(checks.bounds(data).to_numpy(), clean),
               "stuck": _rates(checks.stuck(data, cfg.stuck_min_run).to_numpy(), clean),
               "stuck_k10": _rates(checks.stuck(data, cfg.k_min_run).to_numpy(), clean),
               "duplicate_block": _rates(checks.duplicate_block(
                   data, cfg.dup_min_block, cfg.dup_min_positive).to_numpy(), clean),
               "l1_flag": _rates(checks.l1_flag_matrix(data).to_numpy(), clean),
               "range_check": _rates(baselines.range_check(data).to_numpy(), clean)},
           "noaa_style": {}, "sensitivity": {"stuck_min_run": {}, "duplicate_min_positive": {}}}
    for setting, table in tables.items():
        reasons = baselines.noaa_style_reasons(data, table)
        out["noaa_style"][setting] = {name: _rates(frame.to_numpy(), clean) for name, frame in reasons.items()}
        out["noaa_style"][setting]["any"] = _rates(
            baselines.noaa_style_qa(data, table).to_numpy(), clean)
    for run in (2, 3, 4, 5, 10):
        out["sensitivity"]["stuck_min_run"][str(run)] = _rates(checks.stuck(data, run).to_numpy(), clean)
    for positive in (1, 2, 3, 4):
        out["sensitivity"]["duplicate_min_positive"][str(positive)] = _rates(
            checks.duplicate_block(data, cfg.dup_min_block, positive).to_numpy(), clean)
    return out


def coverage(inputs: Inputs, tables: dict[str, pd.DataFrame]) -> dict:
    sset, meta = inputs.sset, inputs.meta
    clean = inject.clean_real_mask(sset)
    valid = sset.values.notna().to_numpy()
    out = {
        "n_stations": int(len(meta)),
        "by_country": {k: int(v) for k, v in meta["country"].value_counts().items()},
        "n_stations_with_clean_days": int((meta["n_clean_days"] > 0).sum()),
        "n_eligible_stations": int(meta["eligible"].sum()),
        "eligible_min_clean_days": MIN_ELIGIBLE_CLEAN_DAYS,
        "window": [sset.values.index[0].strftime("%Y-%m-%d"), sset.values.index[-1].strftime("%Y-%m-%d")],
        "valid_share_of_station_days": float(valid.mean()),
        "clean_real_days": int(clean.to_numpy().sum()),
        "clean_days_by_min_valid_days_per_year": {},
        "neighbours": {}}
    for minimum in SENSITIVITY_MIN_VALID_DAYS:
        alt = inject.clean_real_mask(sset, minimum)
        out["clean_days_by_min_valid_days_per_year"][str(minimum)] = {
            "clean_days": int(alt.to_numpy().sum()),
            "stations_with_365_clean_days": int((alt.sum() >= MIN_ELIGIBLE_CLEAN_DAYS).sum())}
    clean_mask = clean.to_numpy()
    for setting, table in tables.items():
        n_valid = neighbours.neighbour_reference(sset.values, table)["n_valid"].to_numpy()
        few = neighbours.stations_with_few_neighbours(table, meta)
        k, km = NEIGHBOUR_SETTINGS[setting]
        out["neighbours"][setting] = {
            "k": k, "max_km": km,
            "stations_with_fewer_than_2_neighbours": len(few),
            "stations_with_no_neighbour": sum(1 for n in few.values() if n == 0),
            "fewer_than_2_neighbours": few,
            "clean_days_with_2plus_valid_neighbours": float((n_valid[clean_mask] >= 2).mean()),
            "clean_days_with_3plus_valid_neighbours": float((n_valid[clean_mask] >= 3).mean())}
    return out


def _delay_summary(delays: pd.DataFrame, types: pd.Series, stations: list[str], n_boot: int, seed: int) -> dict:
    out = {}
    data = delays.assign(fault_type=delays["episode_id"].map(types))
    for name in inject.FAULT_TYPES:
        eps = data[data["fault_type"] == name]
        found = eps[eps["detected"]]
        per_station = [g["delay_days"].to_numpy() for _, g in found.groupby("station_col")]
        lo, hi = evaluate.bootstrap_ci(per_station, np.median, n_boot, seed)
        out[name] = {"episodes": int(len(eps)), "detected": int(len(found)),
                     "detection_rate": len(found) / len(eps) if len(eps) else float("nan"),
                     "median_delay_days": float(found["delay_days"].median()) if len(found) else float("nan"),
                     "median_delay_ci": [lo, hi]}
    return out


def evaluate_method(score: np.ndarray, mats: evaluate.FaultMatrices, cols: np.ndarray, extremes: dict,
                    fpr: float, n_boot: int) -> dict:
    """All metrics of one method (a score or a boolean flag matrix over all stations) on the stations `cols`."""
    s = score[:, cols]
    truth, clean, episode = mats.fault_type[:, cols], mats.clean[:, cols], mats.episode_id[:, cols]
    flag, threshold = evaluate.operating_flags(s, clean, fpr)
    recall = evaluate.recall_at_fpr(s, truth, clean, fpr)
    binary = threshold is None
    for name in inject.FAULT_TYPES:
        hits = evaluate.per_station_hits(flag, truth == name)
        recall["per_type"][name]["recall_ci"] = list(evaluate.bootstrap_ci(hits, np.mean, n_boot, BOOTSTRAP_SEED))
        recall["per_type"][name]["pr_auc"] = None if binary else evaluate.pr_auc(s, truth == name, clean)
    delays = evaluate.detection_delay(flag, episode, truth_mask=truth != "")
    recall["delay"] = _delay_summary(delays, evaluate.episode_types(truth, episode),
                                     [mats.stations[c] for c in cols], n_boot, BOOTSTRAP_SEED)
    recall["retention"] = {}
    for setting, found in extremes.items():
        ext = found[:, cols]
        result = evaluate.retention_from_extremes(flag, ext)
        result["retention_ci"] = list(evaluate.bootstrap_ci(
            evaluate.per_station_hits(~flag, ext), np.mean, n_boot, BOOTSTRAP_SEED))
        recall["retention"][setting] = result
    recall["binary"] = binary
    return recall


def real_flag_sanity(inputs: Inputs, scores: dict, thresholds: dict, tables: dict) -> dict:
    """How many real NOAA-flagged values (whole history) each method flags; scores use the val-split
    1% false-flag threshold."""
    full = inputs.full
    data = full.values
    flagged_real = ((full.flags.to_numpy(dtype=object) != "") & data.notna().to_numpy())
    valid = data.notna().to_numpy()
    years = np.asarray(data.index.year)[:, None]
    late = flagged_real & (years >= REAL_FLAG_YEARS[0]) & (years <= REAL_FLAG_YEARS[1])
    letters = full.flags.to_numpy(dtype=object)
    flags = {"range_check": baselines.range_check(data).to_numpy(),
             "l1": checks.l1_flag_matrix(data).to_numpy(),
             "noaa_style_qa": baselines.noaa_style_qa(data, tables["design"]).to_numpy(),
             "noaa_style_qa_wide": baselines.noaa_style_qa(data, tables["wide"]).to_numpy()}
    z = baselines.robust_zscore(data).to_numpy()
    flags["robust_zscore"] = np.isfinite(z) & (z > thresholds["robust_zscore"])
    f = baselines.isolation_forest(data, scores["model"]).to_numpy()
    flags["isolation_forest"] = np.isfinite(f) & (f > thresholds["isolation_forest"])
    out = {"total_flagged_values": int(flagged_real.sum()),
           "flagged_values_2007_2024": int(late.sum()),
           "by_flag": {k: int(v) for k, v in pd.Series(letters[flagged_real]).value_counts().sort_index().items()},
           "years": list(REAL_FLAG_YEARS),
           "scores_use_val_thresholds": {k: float(v) for k, v in thresholds.items()},
           "methods": {}}
    for name, flag in flags.items():
        out["methods"][name] = {
            "flagged_real": int((flag & flagged_real).sum()),
            "flagged_real_2007_2024": int((flag & late).sum()),
            "by_flag": {k: int(v) for k, v in pd.Series(letters[flag & flagged_real]).value_counts().sort_index().items()},
            "false_flag_rate_on_unflagged_valid_days": float((flag & valid & ~flagged_real).sum()
                                                             / (valid & ~flagged_real).sum())}
    return out


def build_report(inputs: Inputs, fpr: float = FPR, n_boot: int = N_BOOT) -> dict:
    mats = evaluate.to_matrices(inputs.table)
    ids = list(inputs.sset.meta["id"])
    if mats.stations != ids:
        mats = _reorder(mats, ids)
    obs = mats.value_obs
    tables = {name: neighbours.neighbour_table(inputs.sset.meta, k, km)
              for name, (k, km) in NEIGHBOUR_SETTINGS.items()}
    train_cols = [i for i, sid in enumerate(ids) if mats.split_of[sid] == "train"]
    model = baselines.fit_isolation_forest(obs.iloc[:, train_cols], seed=FOREST_SEED)
    scores = {
        "range_check": baselines.range_check(obs).to_numpy(),
        "l1": checks.l1_flag_matrix(obs).to_numpy(),
        "noaa_style_qa": baselines.noaa_style_qa(obs, tables["design"]).to_numpy(),
        "noaa_style_qa_wide": baselines.noaa_style_qa(obs, tables["wide"]).to_numpy(),
        "robust_zscore": baselines.robust_zscore(obs).to_numpy(),
        "isolation_forest": baselines.isolation_forest(obs, model).to_numpy()}
    extremes = {name: evaluate.genuine_extremes(obs, mats.clean, tables[table], min_neighbours=minimum).to_numpy()
                for name, (table, minimum) in RETENTION_VARIANTS.items()}
    methods: dict = {}
    thresholds: dict = {}
    for split in EVAL_SPLITS:
        cols = np.array([i for i, sid in enumerate(ids) if mats.split_of[sid] == split])
        methods[split] = {"n_stations": int(len(cols)), "stations": [ids[c] for c in cols], "methods": {}}
        for name in METHODS:
            result = evaluate_method(scores[name], mats, cols, extremes, fpr, n_boot)
            methods[split]["methods"][name] = result
            if split == "val" and result["threshold"] is not None:
                thresholds[name] = result["threshold"]
    return {
        "config": {"fpr": fpr, "n_boot": n_boot, "split_seed": SPLIT_SEED, "dataset_seed": DATASET_SEED,
                   "forest_seed": FOREST_SEED, "bootstrap_seed": BOOTSTRAP_SEED,
                   "neighbour_settings": {k: {"k": v[0], "max_km": v[1]} for k, v in NEIGHBOUR_SETTINGS.items()},
                   "methods": list(METHODS), "fault_types": list(inject.FAULT_TYPES),
                   "noaa_style": _config_dict(baselines.NoaaQaConfig()),
                   "robust_zscore": {"window": baselines.ZSCORE_WINDOW, "min_periods": baselines.ZSCORE_MIN_PERIODS,
                                     "eps_mm": baselines.ZSCORE_EPS},
                   "isolation_forest_features": baselines.FEATURE_NAMES,
                   "genuine_extreme": {"percentile": evaluate.EXTREME_PERCENTILE,
                                       "neighbour_fraction": evaluate.EXTREME_NEIGHBOUR_FRAC,
                                       "variants": {k: {"neighbour_setting": v[0], "min_neighbours": v[1]}
                                                    for k, v in RETENTION_VARIANTS.items()}}},
        "coverage": coverage(inputs, tables),
        "fault_dataset": {"path": display_path(inputs.dataset_path), "report": inputs.dataset_report},
        "splits": {name: inputs.splits[name] for name in inputs.splits},
        "l1_real_false_flag_rates": l1_false_flag_rates(inputs.sset, tables),
        "l1_real_false_flag_rates_min_valid_300": l1_false_flag_rates(inputs.sset, tables, 300),
        "evaluation": methods,
        "real_flag_sanity": real_flag_sanity(inputs, {"model": model}, thresholds, tables),
    }


def _config_dict(cfg) -> dict:
    return {k: getattr(cfg, k) for k in cfg.__dataclass_fields__}


def _reorder(mats: evaluate.FaultMatrices, ids: list[str]) -> evaluate.FaultMatrices:
    order = [mats.stations.index(sid) for sid in ids]
    return evaluate.FaultMatrices(
        ids, mats.value_true[ids], mats.value_obs[ids], mats.fault_type[:, order], mats.episode_id[:, order],
        mats.clean_real[:, order], mats.clean[:, order], mats.real_flag[ids], mats.split_of)


# ------------------------------------------------------------------------------------ markdown

def _f(x, digits: int = 3) -> str:
    return "n/a" if x is None or (isinstance(x, float) and not np.isfinite(x)) else f"{x:.{digits}f}"


def _ci(ci) -> str:
    if ci is None or not np.isfinite(ci[0]):
        return ""
    if ci[0] == ci[1]:
        return " n/a (degenerate)"   # every resampled station agrees (e.g. recall exactly 0 or 1)
    return f" [{_f(ci[0], 2)}, {_f(ci[1], 2)}]"


def _recall_cell(result: dict, name: str) -> str:
    cell = result["per_type"][name]
    if cell["n_positive"] == 0:
        return "n/a (0)"
    if result["binary"]:
        return f"{_f(cell['recall'], 2)} (fpr {_f(result['achieved_fpr'], 3)}){_ci(cell['recall_ci'])}"
    return f"{_f(cell['recall'], 2)}{_ci(cell['recall_ci'])}"


_VARIANT_LABELS = {"design": "design-strict", "wide": "wide", "wide_1neighbour": "wide_1neighbour",
                   "uncorroborated": "uncorroborated (proxy)"}


def _retention_cell(r: dict) -> str:
    if r["denominator"] == 0:
        return "0/0 (not measurable at this density)"
    return f"{r['numerator']}/{r['denominator']} = {_f(r['retention'], 3)}{_ci(r['retention_ci'])}"


def render_markdown(report: dict) -> str:
    cfg, cov = report["config"], report["coverage"]
    types = cfg["fault_types"]
    lines = ["# Phase 2a - sensor-integrity baselines", "",
             f"Faults are injected into REAL clean station series (seeded); recall is at a {cfg['fpr']:.0%} false-flag "
             "rate on clean days (scores) or reported as (recall, achieved false-flag rate) for rule flags. "
             "Intervals are 95% bootstrap CIs over stations. The real NOAA flags are a separate sanity check.", ""]
    lines += ["## Data coverage", "",
              f"- stations: {cov['n_stations']} ({cov['by_country']}); window {cov['window'][0]}..{cov['window'][1]}; "
              f"valid share of station-days {_f(cov['valid_share_of_station_days'], 3)}",
              f"- clean real days (valid, unflagged, station-year >= {inject.MIN_VALID_DAYS_PER_YEAR} valid days): {cov['clean_real_days']} at "
              f"{cov['n_stations_with_clean_days']} stations; {cov['n_eligible_stations']} stations have >= "
              f"{cov['eligible_min_clean_days']} clean days (eligible)", "",
              "| min valid days per station-year | clean days | stations with >= 365 clean days |", "|---|---|---|"]
    for minimum, row in cov["clean_days_by_min_valid_days_per_year"].items():
        lines.append(f"| {minimum} | {row['clean_days']} | {row['stations_with_365_clean_days']} |")
    lines += ["", "| neighbour setting | k | max km | stations with < 2 neighbours | no neighbour | "
              "clean days with >= 2 valid neighbours | >= 3 |", "|---|---|---|---|---|---|---|"]
    for name, row in cov["neighbours"].items():
        lines.append(f"| {name} | {row['k']} | {row['max_km']:.0f} | {row['stations_with_fewer_than_2_neighbours']} | "
                     f"{row['stations_with_no_neighbour']} | {_f(row['clean_days_with_2plus_valid_neighbours'], 3)} | "
                     f"{_f(row['clean_days_with_3plus_valid_neighbours'], 3)} |")
    lines += ["", "## Fault dataset (episodes / faulty days per type)", "",
              "| split | stations (with episodes) | " + " | ".join(types) + " |", "|---|---|" + "---|" * len(types)]
    for split, row in report["fault_dataset"]["report"]["splits"].items():
        cells = " | ".join(f"{row['by_type'][t]['episodes']} / {row['by_type'][t]['days']}" for t in types)
        lines.append(f"| {split} | {row['n_stations']} ({row['n_stations_with_episodes']}) | {cells} |")
    cal = report["fault_dataset"]["report"].get("calibration", {})
    lines += ["", "Calibration from the real flags: " + "; ".join(
        f"{k} lengths {v['min_len']}-{v['max_len']} ({v['basis']})" for k, v in cal.get("used", {}).items()), ""]
    l1 = report["l1_real_false_flag_rates"]
    lines += ["## L1 and rule false-flag rates on the real clean days", "",
              f"{l1['clean_days']} real clean days; thresholds {l1['thresholds']}.", "",
              "| rule | flagged | rate |", "|---|---|---|"]
    for name, row in l1["rules"].items():
        lines.append(f"| {name} | {row['flagged']} | {_f(row['rate'], 5)} |")
    for setting, rules in l1["noaa_style"].items():
        for name, row in rules.items():
            lines.append(f"| noaa_style {setting} {name} | {row['flagged']} | {_f(row['rate'], 5)} |")
    alt = report["l1_real_false_flag_rates_min_valid_300"]
    lines += ["", f"Sensitivity, clean days under the 300-valid-days rule ({alt['clean_days']} days): " + "; ".join(
        f"{k} {_f(v['rate'], 5)}" for k, v in alt["rules"].items()), ""]
    lines += ["Threshold sensitivity (same clean days): " + "; ".join(
        f"stuck run >= {k}: {_f(v['rate'], 5)}" for k, v in l1["sensitivity"]["stuck_min_run"].items()) + "; " + "; ".join(
        f"duplicate block min positive days {k}: {_f(v['rate'], 5)}"
        for k, v in l1["sensitivity"]["duplicate_min_positive"].items()), ""]
    for split in EVAL_SPLITS:
        block = report["evaluation"][split]
        lines += [f"## {split.upper()} stations ({block['n_stations']})", "",
                  f"### Recall per fault type (95% CI over stations)", "",
                  "| method | " + " | ".join(types) + " | macro |", "|---|" + "---|" * (len(types) + 1)]
        for name, result in block["methods"].items():
            cells = " | ".join(_recall_cell(result, t) for t in types)
            lines.append(f"| {name} | {cells} | {_f(result['macro_recall'], 2)} |")
        lines += ["", "### Detection: episodes detected / total, median delay in days", "",
                  "| method | " + " | ".join(types) + " |", "|---|" + "---|" * len(types)]
        for name, result in block["methods"].items():
            cells = " | ".join(f"{result['delay'][t]['detected']}/{result['delay'][t]['episodes']}, "
                               f"{_f(result['delay'][t]['median_delay_days'], 1)}" for t in types)
            lines.append(f"| {name} | {cells} |")
        lines += ["", "### PR-AUC per fault type (score methods)", "",
                  "| method | " + " | ".join(types) + " |", "|---|" + "---|" * len(types)]
        for name, result in block["methods"].items():
            if not result["binary"]:
                lines.append(f"| {name} | " + " | ".join(_f(result["per_type"][t]["pr_auc"], 3) for t in types) + " |")
        variants = cfg["genuine_extreme"]["variants"]
        lines += ["", "### Genuine-extreme retention: all variants (retained / extremes); no single number is the safety result", "",
                  "Extremes: clean unflagged readings >= the station's 99.5th wet-day percentile. "
                  "`design-strict` and `wide` need >= 2 neighbours reading >= 30% of the value (150 km / 300 km "
                  "neighbour settings); `wide_1neighbour` needs 1 (300 km); `uncorroborated` has no neighbour "
                  "condition: a proxy that includes unverified readings.", "",
                  "| method | clean-day false-flag rate | " + " | ".join(_VARIANT_LABELS[v] for v in variants) + " |",
                  "|---|---|" + "---|" * len(variants)]
        for name, result in block["methods"].items():
            cells = " | ".join(_retention_cell(result["retention"][v]) for v in variants)
            lines.append(f"| {name} | {_f(result['achieved_fpr'], 4)} | {cells} |")
        lines.append("")
    sanity = report["real_flag_sanity"]
    lines += ["## Real NOAA flags (sanity check, whole history)", "",
              f"{sanity['total_flagged_values']} flagged values ({sanity['by_flag']}); "
              f"{sanity['flagged_values_2007_2024']} in {sanity['years'][0]}-{sanity['years'][1]}. Score methods use "
              "the validation-split 1% false-flag thresholds.", "",
              "| method | real flags flagged | of which 2007-2024 | by NOAA flag | false-flag rate on unflagged days |",
              "|---|---|---|---|---|"]
    for name, row in sanity["methods"].items():
        lines.append(f"| {name} | {row['flagged_real']} / {sanity['total_flagged_values']} | "
                     f"{row['flagged_real_2007_2024']} / {sanity['flagged_values_2007_2024']} | {row['by_flag']} | "
                     f"{_f(row['false_flag_rate_on_unflagged_valid_days'], 4)} |")
    lines.append("")
    return "\n".join(lines)


def write_reports(report: dict, out_dir=None) -> tuple[Path, Path]:
    out = Path(out_dir) if out_dir is not None else reports_dir()
    out.mkdir(parents=True, exist_ok=True)
    md, js = out / "phase2a_baselines.md", out / "phase2a_baselines.json"
    js.write_text(dumps_strict(report), encoding="utf-8", newline="\n")
    md.write_text(render_markdown(report), encoding="utf-8", newline="\n")
    return md, js


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw-dir", default=None, help="GHCN-Daily directory (default data/raw/ghcnd)")
    parser.add_argument("--reports-dir", default=None, help="output directory (default reports/)")
    parser.add_argument("--rebuild-dataset", action="store_true", help="rebuild the fault dataset even if it exists")
    parser.add_argument("--rebuild-splits", action="store_true",
                        help="rebuild the FROZEN station split (invalidates earlier results; use with --rebuild-dataset)")
    parser.add_argument("--fpr", type=float, default=FPR)
    parser.add_argument("--n-boot", type=int, default=N_BOOT)
    args = parser.parse_args(argv)
    inputs = prepare(args.raw_dir, rebuild_dataset=args.rebuild_dataset, force_splits=args.rebuild_splits)
    report = build_report(inputs, fpr=args.fpr, n_boot=args.n_boot)
    md, js = write_reports(report, args.reports_dir)
    print(f"wrote {display_path(md)} and {display_path(js)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
