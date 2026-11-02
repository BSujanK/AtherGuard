"""Step 4 of the v3.1 challenger study (spec 15.6, 15.7): the selected candidate on test_2018 (one look) and the offline replay
of the stored live days.

    python -m aetherguard.hazard.v31_challenger heldout            # test_2018 for the selected candidate, then its replay
    python -m aetherguard.hazard.v31_challenger replay C1 C2 C3    # exploratory replay of named candidates (no test_2018)

`heldout` opens test_2018 only when the pre-declared selection (15.5) named a candidate, scores it and the frozen v3-live on the
same rows, applies the pre-declared adoption criterion (15.6) and refuses to run again once its result file exists. `replay`
rescored the live days of `data/live` (read only) and writes only under `data/processed/alerts/<replay_dir>/`.
"""
from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from ..alerts import levels as lv
from ..alerts.config import alerts_settings, load_config_file as load_alert_config
from ..config import PROJECT_ROOT, data_root
from ..live import postrules as pr
from ..live import precision_study as ps
from ..live import run as live_run
from . import challengers as ch
from . import data as hd
from . import evaluate_report as er
from . import freeze
from . import model as hm
from . import train as tr
from . import v31_challenger as vc
from . import v31_labels as vl
from .jsonio import dump_json

HELDOUT = "heldout_2018.json"
REPLAY_FILE = "replay.json"
REPLAY_TABLE = "last_day_cells.parquet"
FROZEN_REPORT = "reports/phase6_live_model_report.json"
REPRODUCTION_TOLERANCE = 1e-9
RAIN_WINDOWS = (1, 3, 5, 7)
V3 = "v3_live"


class SingleLookError(RuntimeError):
    """test_2018 has already been read for this study."""


# ------------------------------------------------------------------------------------ test_2018 scoring

def model_thresholds(model: hm.HazardModel, regions) -> lv.RegionThresholds:
    """The risk thresholds of a model's card per region (as `live.run.card_thresholds` reads them)."""
    pooled = lv.thresholds_from_card(model.card, alerts_settings()["v1_card_fallback"])
    return lv.RegionThresholds(lv.card_region_thresholds(model.card, regions), pooled)


def split_frames(test: hd.SplitData) -> tuple[pd.DataFrame, pd.DataFrame, np.ndarray]:
    """(in-domain positives, non-buffer non-positive universe rows, their weights renormalised per region)."""
    keep = hd.universe_negative_mask(test.universe)
    weights = hd.renormalised_weights(test.universe, keep)
    return test.positives.reset_index(drop=True), test.universe[keep].reset_index(drop=True), weights


def score_split(model: hm.HazardModel, frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """(raw point score, calibrated risk) of the rows."""
    raw = model.raw_score(frame)
    return raw, model.calibrate(raw, frame)[0]


def oof_style_frame(positives: pd.DataFrame, universe: pd.DataFrame, weights: np.ndarray, pos_score, neg_score) -> pd.DataFrame:
    """The scored rows as a challenger-harness frame, so `challengers.paired_fa_differences` pairs them (stratum = region)."""
    parts = []
    for kind, frame, weight, score in (("positive", positives, np.ones(len(positives)), pos_score),
                                       ("universe", universe, weights, neg_score)):
        parts.append(pd.DataFrame({"kind": kind, "cell_id": frame["cell_id"].to_numpy(dtype=np.int64),
                                   "date": frame["date"].to_numpy(), "fold": np.int8(0), "weight": weight,
                                   "stratum": frame["region"].astype(str).to_numpy(), "score": np.asarray(score, dtype=np.float64)}))
    return pd.concat(parts, ignore_index=True)


def compare_on_split(test: hd.SplitData, reference: hm.HazardModel, candidate: hm.HazardModel, study: dict) -> dict:
    """The frozen reference and the candidate scored on the same test rows with each model's own card thresholds: FA@90 with
    its paired bootstrap difference, the Watch / Warning / Emergency statistics with bootstrap intervals, and the three parts
    of the adoption criterion (spec 15.6)."""
    base, boot = study["base"], study["base"]["bootstrap"]
    positives, universe, weights = split_frames(test)
    models = {V3: reference, "candidate": candidate}
    regions = sorted(universe["region"].unique())
    scored = {name: (score_split(m, positives), score_split(m, universe)) for name, m in models.items()}
    frames = {name: oof_style_frame(positives, universe, weights, pos[0], neg[0]) for name, (pos, neg) in scored.items()}
    paired = ch.paired_fa_differences(frames, [("candidate", V3)], boot["n"], boot["seed"], boot["level"],
                                      recalls=base["operating_points"]["recalls"], fa_shares=base["operating_points"]["fa_shares"])
    pos_low, pos_lowrain = vc.terrain_flags(positives, study)
    neg_low, neg_lowrain = vc.terrain_flags(universe, study)
    pos_region, neg_region = positives["region"].to_numpy(), universe["region"].to_numpy()
    pops, alerts, levels = {}, {}, {}
    for name, (pos, neg) in scored.items():
        thresholds = model_thresholds(models[name], regions)
        pos_level = lv.level_from_risk(pos[1], thresholds, pos_region)
        neg_level = lv.level_from_risk(neg[1], thresholds, neg_region)
        pops[name] = vc.Population(pos[0], neg[0], weights, pos_low, neg_low, pos_lowrain, neg_lowrain, pos_region, neg_region)
        alerts[name] = {lv.LEVEL_NAMES[k].lower(): (pos_level >= k, neg_level >= k) for k in (lv.WATCH, lv.WARNING, lv.EMERGENCY)}
        levels[name] = thresholds.to_dict()
    result = {"population": {"positives_in_domain": len(positives), "positives_out_of_domain": test.n_out_of_domain,
                             "universe_rows": len(universe), "universe_cell_days": float(weights.sum())},
              "models": {}, "paired_fa_at_90": paired["differences"][f"candidate-{V3}"]}
    boots = {level: vc.bootstrap_alert_statistics(pops, {n: alerts[n][level] for n in pops}, neg_region, boot["n"], boot["seed"])
             for level in vc.LEVELS}
    for name in models:
        result["models"][name] = {
            "fa_at_90": paired["metrics"][name][vc.HEADLINE], "metrics": paired["metrics"][name],
            "risk_thresholds_by_region": levels[name],
            "levels": {level: {**vc.alert_statistics(pops[name], *alerts[name][level]),
                               "bootstrap": {k: vc.interval(boots[level][name][k], boot["level"]) for k in vc.SHARES}}
                       for level in vc.LEVELS},
            "by_region_warning": {r: vc.alert_statistics(pops[name], *alerts[name]["warning"], region=r) for r in regions}}
    warning = {name: result["models"][name]["levels"][vc.WARNING] for name in models}
    share_diff = boots[vc.WARNING]["candidate"]["low_share"] - boots[vc.WARNING][V3]["low_share"]
    result["low_share_diff"] = {"value": warning["candidate"]["low_share"] - warning[V3]["low_share"],
                                **vc.interval(share_diff, boot["level"])}
    lost = warning[V3]["events"] - warning["candidate"]["events"]
    allowed = int(study["adoption"]["max_warning_events_lost"])
    criterion = {"a_fa_at_90_not_worse": bool(result["paired_fa_at_90"]["ci_lo"] <= 0),
                 "b_lower_warning_low_share": bool(warning["candidate"]["low_share"] < warning[V3]["low_share"]),
                 "c_warning_events_lost": int(lost), "c_allowed": allowed, "c_within_allowance": bool(lost <= allowed)}
    criterion["recommended"] = bool(criterion["a_fa_at_90_not_worse"] and criterion["b_lower_warning_low_share"]
                                    and criterion["c_within_allowance"])
    result["criterion"] = criterion
    return result


def check_frozen_reproduction(result: dict, frozen_report: dict) -> dict:
    """The frozen v3-live re-scored here must give the FA@90 of its own frozen test report (to 1e-9)."""
    reported = frozen_report["test"]["main"]["metrics"]["model"][vc.HEADLINE]["value"]
    recomputed = result["models"][V3]["fa_at_90"]["value"]
    record = {"recomputed_fa_at_90": recomputed, "reported_fa_at_90": reported, "abs_difference": abs(recomputed - reported)}
    if record["abs_difference"] > REPRODUCTION_TOLERANCE:
        raise ch.ReproductionError(f"frozen v3-live re-scored on test_2018 gives FA@90 {recomputed:.9f}, its report {reported:.9f}")
    return record


def run_heldout(study: dict, features_dir: Path | None = None, say=print) -> dict:
    """Spec 15.6: the selected candidate on test_2018, once; nothing when the selection named none."""
    started = time.perf_counter()
    out = vc.output_dir(study)
    selection = json.loads((out / vc.SELECTION).read_text(encoding="utf-8"))
    path = out / HELDOUT
    if path.is_file() and not json.loads(path.read_text(encoding="utf-8")).get("skipped"):
        raise SingleLookError(f"{path} exists: test_2018 has been read for this study and is not read again")
    created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if selection["selected"] is None:
        record = {"created_utc": created, "skipped": True, "reason": "the pre-declared selection (spec 15.5) named no candidate: "
                  "test_2018 was not read and no selected-candidate replay was made", "selection": selection["result"]}
        dump_json(path, record)
        say("selection named no candidate; test_2018 not read")
        return record
    name, base = selection["selected"], study["base"]
    frozen_dir = hm.configured_model_dir(base)
    freeze_record = freeze.verify_freeze(frozen_dir, freeze.default_external_files(PROJECT_ROOT / study["base_config"]))
    reference = hm.HazardModel.load(frozen_dir)
    candidate = hm.HazardModel.load(out / vc.MODEL_SUBDIR / name)
    directory = Path(features_dir or hd.features_dir())
    say(f"scoring test_2018: frozen v3-live and {name}")
    test = er.load_test_split(directory, base, tr.extra_groups_used(base))
    result = compare_on_split(test, reference, candidate, study)
    frozen_report = json.loads((PROJECT_ROOT / FROZEN_REPORT).read_text(encoding="utf-8"))
    payload = {"created_utc": created, "candidate": name, "skipped": False, "freeze_created_utc": freeze_record["created_utc"],
               "reproduction": check_frozen_reproduction(result, frozen_report), **result,
               "seconds": time.perf_counter() - started}
    dump_json(path, payload)
    verdict = payload["criterion"]
    say(f"{name} on test_2018: FA@90 difference {result['paired_fa_at_90']['point_difference']:+.4f} "
        f"[{result['paired_fa_at_90']['ci_lo']:+.4f}, {result['paired_fa_at_90']['ci_hi']:+.4f}]; recommended {verdict['recommended']}")
    return payload


# ------------------------------------------------------------------------------------------ live replay

def replay_days(live_dir: Path, first: date, last: date) -> list[date]:
    """The consecutive stored live days from `first` through `last` (all must be present)."""
    days, day = [], first
    while day <= last:
        if not ((live_dir / day.isoformat() / "alerts.parquet").is_file() and (live_dir / day.isoformat() / "features_D0.parquet").is_file()):
            raise ValueError(f"the live day {day} is not stored under {live_dir}; the replay needs consecutive days")
        days.append(day)
        day += timedelta(days=1)
    return days


class LiveDays:
    """The stored live days: the D0 feature tables and the published alert tables (read only)."""

    def __init__(self, live_dir: Path, days: list[date]) -> None:
        self.days = days
        self.features = [pd.read_parquet(live_dir / d.isoformat() / "features_D0.parquet") for d in days]
        alerts = [pd.read_parquet(live_dir / d.isoformat() / "alerts.parquet", columns=["cell_id", "level", "blind"]) for d in days]
        ids = self.features[0]["cell_id"].to_numpy(dtype=np.int64)
        for day, features, table in zip(days, self.features, alerts):
            if not (np.array_equal(features["cell_id"].to_numpy(), ids) and np.array_equal(table["cell_id"].to_numpy(), ids)):
                raise ValueError(f"the cells of {day} differ from those of {days[0]}")
        self.ids = ids
        self.region = self.features[-1]["region"].to_numpy(dtype=object)
        self.published = np.column_stack([t["level"].to_numpy() for t in alerts]).astype(np.int8)
        self.blind = np.column_stack([t["blind"].to_numpy(dtype=bool) for t in alerts])
        self.rain = {w: np.column_stack([f[f"irain_acc_{w}"].to_numpy(dtype=np.float64) for f in self.features]) for w in RAIN_WINDOWS}
        self.stamps = pd.DatetimeIndex(pd.to_datetime(days)).to_numpy()
        self.last = self.features[-1]


def score_days(model: hm.HazardModel, lived: LiveDays) -> tuple[np.ndarray, np.ndarray]:
    """(risk, ensemble risk_hi) matrices (cells, days) with NaN where a cell has no score on that day."""
    risk = np.full((len(lived.ids), len(lived.days)), np.nan)
    upper = np.full_like(risk, np.nan)
    for j, features in enumerate(lived.features):
        rows = live_run.scorable_mask(features, model.columns)
        if rows.any():
            scored = model.score(features[rows])
            risk[rows, j], upper[rows, j] = scored["risk"].to_numpy(), scored["risk_hi"].to_numpy()
    return risk, upper


def replay_levels(model: hm.HazardModel, lived: LiveDays, rules: pr.PostRules, alert_config) -> dict:
    """Levels (cells, days) of `model` over the stored days through the live chain (spec 15.7): the level of the point risk
    against its card's region thresholds, raised to Watch by `uncertain_high` and by the published blind flag, the section 11 rain
    cap, then the hysteresis with the section 11 hold windows (`precision_study.candidate_levels` with its baseline candidate)."""
    thresholds = model_thresholds(model, np.unique(lived.region))
    risk, upper = score_days(model, lived)
    raw = np.zeros(risk.shape, dtype=np.int8)
    for j in range(risk.shape[1]):
        raw[:, j] = lv.raw_level(risk[:, j], upper[:, j], thresholds, lived.region)[0]
    raw = np.where(lived.blind, np.maximum(raw, lv.WATCH), raw).astype(np.int8)
    base_ok = rules.rain.passes_arrays({w: lived.rain[w] for w in rules.rain.minimum_mm})
    capped = np.where(base_ok | lived.blind, raw, rules.cap_array()[raw]).astype(np.int8)
    levels = ps.candidate_levels(capped, risk, lived.rain, base_ok, np.zeros(len(lived.ids), dtype=bool),
                                 ps.Candidate("baseline"), rules, lived.region, lived.ids, lived.stamps, thresholds.by_region,
                                 alert_config)
    return {"levels": levels, "risk": risk, "thresholds": thresholds}


def lead_replay(model: hm.HazardModel, live_dir: Path, day: date, lead: int, scorable_d0: np.ndarray, rules: pr.PostRules,
                factor: tuple[float, float] | None) -> tuple[np.ndarray, np.ndarray]:
    """(level, risk) of forecast lead `lead` of `day`: the level of the point risk raised to Watch by `uncertain_high`, and the
    rain cap on the lead's own windows (no hysteresis), as `live.run.lead_scores` computes the stored leads.

    The `uncertain_high` bound is the ensemble `risk_hi` multiplied by the lead's widening `factor` (hi), capped at 1 and never
    below the point risk. `lead_scores` also evaluates its `unwidened` bound after widening: `with_uncertain_bound` returns the
    scored frame itself at the default percentile and the frame is widened in place before the bound is read, so the stored leads
    test the widened `risk_hi` under both `widened` and `unwidened` (only `none` tests the point). The replay reproduces what was
    published; on 2026-10-24 it matches the stored D+1..D+3 levels cell for cell."""
    frame = pd.read_parquet(live_dir / day.isoformat() / f"features_D{lead}.parquet")
    scorable = live_run.lead_scorable(frame, model.columns, scorable_d0)
    thresholds = model_thresholds(model, np.unique(frame["region"]))
    level, risk = np.zeros(len(frame), dtype=np.int8), np.full(len(frame), np.nan)
    if scorable.any():
        scored = model.score(frame[scorable])
        point = scored["risk"].to_numpy()
        upper = scored["risk_hi"].to_numpy() if factor is None else np.minimum(scored["risk_hi"].to_numpy() * factor[1], 1.0)
        bound = point if rules.lead_uncertain_bound == "none" else np.maximum(upper, point)
        level[scorable] = lv.raw_level(point, bound, thresholds, frame["region"].to_numpy()[scorable])[0]
        risk[scorable] = point
    ok = rules.rain.passes(frame) | ~scorable
    return np.where(ok, level, rules.cap_array()[level]).astype(np.int8), risk


def count_levels(levels: np.ndarray) -> list[dict]:
    return [{lv.level_name(k): int((levels[:, j] == k).sum()) for k in range(4)} for j in range(levels.shape[1])]


def box_mask(last: pd.DataFrame, lat: tuple[float, float], lon: tuple[float, float]) -> np.ndarray:
    return ((last["lat"].to_numpy() >= lat[0]) & (last["lat"].to_numpy() <= lat[1])
            & (last["lon"].to_numpy() >= lon[0]) & (last["lon"].to_numpy() <= lon[1]))


def area_summary(mask: np.ndarray, levels: dict[str, np.ndarray]) -> dict:
    """Cells of an area at each level on the last day, per level set."""
    return {name: {lv.level_name(k): int((lev[mask, -1] == k).sum()) for k in range(4)} for name, lev in levels.items()}


def named_rows(last: pd.DataFrame, mask: np.ndarray, levels: dict[str, np.ndarray], rain3: np.ndarray, limit: int = 12) -> list[dict]:
    """The cells of an area with the highest published level (then v3 level), with terrain and rain and every level set."""
    rows = np.flatnonzero(mask)
    order = rows[np.lexsort((-levels[V3][rows, -1], -levels["published"][rows, -1]))][:limit]
    return [{"cell_id": int(last["cell_id"].iloc[i]), "lat": float(last["lat"].iloc[i]), "lon": float(last["lon"].iloc[i]),
             "slope_mean": float(last["stat_slope_mean"].iloc[i]), "elev_mean": float(last["stat_elev_mean"].iloc[i]),
             "acc_3": float(rain3[i]), "levels": {n: lv.level_name(lev[i, -1]) for n, lev in levels.items()}} for i in order]


def run_replay(study: dict, names: list[str], say=print) -> dict:
    """Spec 15.7 for the named candidates (each needs its refitted model under `models/<name>`): the frozen v3-live and every
    candidate over the stored live days, compared with the published levels and with each other. Writes only under
    `data/processed/alerts/<replay_dir>/`."""
    started = time.perf_counter()
    cfg = live_run.load_run_config()
    live_dir = live_run.live_root(cfg)
    spec = study["replay"]
    days = replay_days(live_dir, date.fromisoformat(spec["first_day"]), date.fromisoformat(spec["last_day"]))
    report_from = days.index(date.fromisoformat(spec["report_from"]))
    say(f"replaying {days[0]}..{days[-1]} ({len(days)} days)")
    lived = LiveDays(live_dir, days)
    rules = pr.load_rules(live_run.project_path(cfg["post_rules"]))
    alert_config = load_alert_config(live_run.project_path(cfg["alert_config"]))
    models = {V3: live_run.load_live_model(cfg)}
    for name in names:
        models[name] = hm.HazardModel.load(vc.output_dir(study) / vc.MODEL_SUBDIR / name)
    runs = {}
    for name, model in models.items():
        runs[name] = replay_levels(model, lived, rules, alert_config)
        say(f"  {name} replayed")
    levels = {"published": lived.published, **{n: r["levels"] for n, r in runs.items()}}
    agree = runs[V3]["levels"] == lived.published
    last, rain3 = lived.last, lived.rain[3][:, -1]
    slope = last["stat_slope_mean"].to_numpy()
    elev = last["stat_elev_mean"].to_numpy()
    low_terrain = vl.low_terrain(last, vl.LabelRule.from_config(study))
    classes = {
        "flat_cell_watch_plus (slope_mean < 5 deg)": slope < float(study["low_terrain"]["slope_mean_below_deg"]),
        "low_elevation_watch_plus (elev_mean < 100 m)": elev < float(study["low_terrain"]["elev_mean_below_m"]),
        "low_terrain_warning_plus": low_terrain,
        f"low_rain_warning_plus ({study['low_rain_column']} < {study['low_rain_mm']:g} mm)": rain3 < float(study["low_rain_mm"])}
    class_counts = {}
    for label, mask in classes.items():
        floor = lv.WARNING if "warning_plus" in label else lv.WATCH
        class_counts[label] = {n: int((mask & (lev[:, -1] >= floor)).sum()) for n, lev in levels.items()}
    kanyakumari = last["cell_id"].to_numpy() == int(spec["kanyakumari_cell"])
    areas = {"kanyakumari": kanyakumari}
    for label, (lat, lon, half) in spec["boxes"].items():
        areas[label] = box_mask(last, (lat - half, lat + half), (lon - half, lon + half))
    areas["south_ghats"] = box_mask(last, tuple(spec["south_ghats"]["lat"]), tuple(spec["south_ghats"]["lon"]))
    factors = live_run.load_widening(cfg, live_run.LiveDeps())[0]
    leads = {}
    for name, model in models.items():
        scorable_d0 = live_run.scorable_mask(last, model.columns)
        leads[name] = {k: lead_replay(model, live_dir, days[-1], k, scorable_d0, rules, factors[k] if factors else None)[0]
                       for k in (1, 2, 3)}
    published_leads = {k: pd.read_parquet(live_dir / days[-1].isoformat() / f"risk_D{k}.parquet", columns=["cell_id", "level"])
                       for k in (1, 2, 3)}
    result = {
        "protocol": {"days": [d.isoformat() for d in days], "report_from": days[report_from].isoformat(),
                     "written_to_data_live": False, "candidates": names, "frozen": hm.display_path(hm.configured_model_dir(study["base"]))},
        "v3_replay_check": {"cell_days_equal_to_published": int(agree.sum()), "cell_days": int(agree.size),
                            "per_day_equal": [int(agree[:, j].sum()) for j in range(len(days))],
                            "from_report_start": int((~agree[:, report_from:]).sum())},
        "levels_per_day": {n: count_levels(l) for n, l in levels.items()},
        "thresholds_by_region": {n: r["thresholds"].to_dict() for n, r in runs.items()},
        "last_day_classes": class_counts, "areas": {a: area_summary(m, levels) for a, m in areas.items()},
        "area_cells": {a: named_rows(last, m, levels, rain3) for a, m in areas.items()},
        "area_cell_counts": {a: int(m.sum()) for a, m in areas.items()},
        "transitions_last_day": {n: {f"{lv.level_name(a)}->{lv.level_name(b)}": int(((levels[V3][:, -1] == a) & (levels[n][:, -1] == b)).sum())
                                     for a in range(4) for b in range(4) if a != b and ((levels[V3][:, -1] == a) & (levels[n][:, -1] == b)).any()}
                                 for n in names},
        "leads_last_day": {"v3_equals_published": {str(k): int((leads[V3][k] == published_leads[k]["level"].to_numpy()).sum()) for k in (1, 2, 3)},
                           "counts": {n: {str(k): {lv.level_name(l): int((level == l).sum()) for l in range(4)} for k, level in per.items()}
                                      for n, per in leads.items()},
                           "published": {str(k): {lv.level_name(l): int((t["level"] == l).sum()) for l in range(4)} for k, t in published_leads.items()}},
        "seconds": time.perf_counter() - started}
    out = data_root() / "processed" / "alerts" / study["replay_dir"]
    out.mkdir(parents=True, exist_ok=True)
    table = last[["cell_id", "lat", "lon", "region", "stat_slope_mean", "stat_elev_mean"]].assign(
        acc_3=rain3, **{f"level_{n}": lev[:, -1] for n, lev in levels.items()},
        **{f"risk_{n}": r["risk"][:, -1] for n, r in runs.items()})
    table.to_parquet(out / REPLAY_TABLE, index=False)
    dump_json(out / REPLAY_FILE, result)
    say(f"wrote {hm.display_path(out / REPLAY_FILE)}")
    return result
