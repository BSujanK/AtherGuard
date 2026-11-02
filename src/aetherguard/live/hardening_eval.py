"""The one evaluation of the post-model rules chosen on the development years (`hardening_dev`): the 2018 operational
backtest set and one live day, before and after. Nothing is chosen here.

* 2018: the panel of `hardening score-heldout` (frozen v3-live model, operational features, 1 June - 30 September 2018
  after the warm-up), the levels of Task 6b with the old interval (before), with the re-centred interval only, and with
  the re-centred interval plus the chosen rules (after): detection of the test_2018 events with bootstrap CIs, the shares
  of cell-days at Watch, Warning and Emergency or above, and the dry alerts (3-day IMERG rain under 1 mm).
* The live day: recomputed offline from its stored `features_D0.parquet` (the alert input of the run) with the frozen
  model, the alert engine run as the live runner runs it (no station outputs are stored, so the station
  out-of-distribution guard is not re-run; the published confidence is compared), before and after, plus the terrain
  contributions of its dry alerts. The live runner is not run.
"""
from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from ..alerts import levels as lv
from ..alerts.config import load_config_file as load_alert_config
from ..alerts.engine import run_alerts
from ..hazard import model as hm
from ..hazard.jsonio import dump_json
from . import audit
from . import backtest as bt
from . import hardening as H
from . import hardening_dev as D
from . import postrules as pr
from . import run as live_run

EVALUATION_FILE = "evaluation.json"
FALSE_ALARMS = (23965166, 24605098)          # the user-reported dry alerts of 2026-10-23 (Uttarakhand; Katra, Reasi)


# ---------------------------------------------------------------------------------------------------- 2018

def season_2018(cfg: dict, model: hm.HazardModel, config, rules: pr.PostRules, say) -> dict:
    spec = bt.load_set("season_2018", cfg=cfg)
    panel = H.load_panel(H.alerts_dir(H.HELDOUT_DIR) / H.HELDOUT_FILE)
    if panel.cells["cell_id"].tolist() != spec.cells["cell_id"].tolist():
        raise ValueError("the 2018 panel does not hold the cells of the season_2018 backtest set")
    season = D.Season(2018, panel, panel.days.index(spec.start), spec.events.reset_index(drop=True),
                      lv.card_region_thresholds(model.card, panel.cells["region"]))
    say("2018: before / interval only / after")
    conditions = {"before": D.evaluate([season], "old_hi", config, label="before: old interval, no post-model rules"),
                  "interval_only": D.evaluate([season], "new_hi", config, label="re-centred interval, no post-model rules"),
                  "after": D.evaluate([season], "new_hi", config, rules, label="re-centred interval + chosen rules")}
    point = D.point_levels(season)
    share = D.agreement(season, point)
    first = season.first
    alerted = (point[:, first:] >= lv.WARNING) & panel.scored[:, first:]
    disagree = alerted & (share[:, first:] < rules.agreement_min) if rules.agreement_min is not None else alerted & False
    return {"cells": int(len(panel.cells)), "days": len(panel.days) - first, "events": int(len(spec.events)),
            "conditions": {k: D.compact(v) for k, v in conditions.items()},
            "ensemble_disagrees_cell_days": int(disagree.sum()), "point_warning_plus_cell_days": int(alerted.sum()),
            "outside_old_interval": D.outside_share([season])}


# ------------------------------------------------------------------------------------------------ live day

def live_engine(features: pd.DataFrame, scores: pd.DataFrame, scorable: np.ndarray, thresholds, config,
                persisted_tail: bool) -> pd.DataFrame:
    """The engine table of the live run (hysteresis off; unscorable rows with the run's placeholder 0 risk), capped at
    Degraded when the run persisted the nowcast tail, as the run does."""
    filled = scores.copy()
    filled.loc[~scorable, :] = 0.0
    table = run_alerts(features, filled[["risk", "risk_lo", "risk_hi", "risk_per_100k"]], None, thresholds=thresholds,
                       config=config, contributions=None, hysteresis=False)
    return live_run.cap_to_degraded(table, config, live_run.CAUSE_NOWCAST_TAIL) if persisted_tail else table


def published_like(table: pd.DataFrame, level: np.ndarray, scorable: np.ndarray) -> pd.DataFrame:
    return live_run.finalize_alerts(table, level, ~scorable)


def level_counts(level) -> dict:
    return {name: int((np.asarray(level) == i).sum()) for i, name in enumerate(lv.LEVEL_NAMES)}


def dry_counts(level, acc3) -> dict:
    dry = np.asarray(acc3, dtype=np.float64) < H.DRY_ACC3_MM
    return {name: {"dry": int(((np.asarray(level) == i) & dry).sum()), "all": int((np.asarray(level) == i).sum())}
            for i, name in enumerate(lv.LEVEL_NAMES) if i}


def interval_violations(table: pd.DataFrame) -> int:
    risk, lo, hi = (table[c].to_numpy(dtype=np.float64) for c in ("risk", "risk_lo", "risk_hi"))
    with np.errstate(invalid="ignore"):
        return int((np.isfinite(risk) & ~((lo <= risk) & (risk <= hi))).sum())


def _plain(value):
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (float, np.floating)):
        return float(value) if np.isfinite(value) else None
    return value


def cell_row(table: pd.DataFrame, cell: int) -> dict | None:
    rows = table[table["cell_id"] == cell]
    if rows.empty:
        return None
    row = rows.iloc[0]
    keys = ("risk", "risk_lo", "risk_hi", "level_name", "confidence", "confidence_causes", "reason_codes",
            "ensemble_agreement", "member_median_risk", "rain_ok")
    return {k: _plain(row[k]) for k in keys if k in row.index}


def reported_cells(features: pd.DataFrame, before: pd.DataFrame, after: pd.DataFrame) -> dict:
    out = {}
    for cell in FALSE_ALARMS:
        rows = features[features["cell_id"] == cell]
        if rows.empty:
            continue
        rain = {f"irain_acc_{w}": _plain(rows[f"irain_acc_{w}"].iloc[0]) for w in (1, 3, 7, 30)}
        out[str(cell)] = {**rain, "irain_days_since_10mm": _plain(rows["irain_days_since_10mm"].iloc[0]),
                          "before": cell_row(before, cell), "after": cell_row(after, cell)}
    return out


def live_day(day: date, cfg: dict, model: hm.HazardModel, config, rules: pr.PostRules, say) -> dict:
    live_dir = live_run.live_root(cfg)
    run_dir = live_dir / day.isoformat()
    features = pd.read_parquet(run_dir / "features_D0.parquet")
    published = pd.read_parquet(run_dir / "alerts.parquet")
    summary = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    thresholds = live_run.card_thresholds(model, features["region"])
    scorable = live_run.scorable_mask(features, model.columns)
    say(f"{day}: scoring {int(scorable.sum())} cells")
    fields = H.score_rows(model, features[scorable])
    new = pd.DataFrame(0.0, index=features.index, columns=["risk", "risk_lo", "risk_hi", "risk_per_100k",
                                                           "member_median_risk", "ensemble_agreement"])
    scored_new = model.score(features[scorable])
    new.loc[scorable, scored_new.columns] = scored_new
    old = new[["risk", "risk_lo", "risk_hi", "risk_per_100k"]].copy()
    old.loc[scorable, "risk_lo"], old.loc[scorable, "risk_hi"] = fields["old_lo"], fields["old_hi"]
    history = live_run.previous_state(live_dir, day, int(cfg["hysteresis_history_days"]))
    persisted = bool(summary["nowcast_tail"]["persisted"])

    before_engine = live_engine(features, old, scorable, thresholds, config, persisted)
    before_level = live_run.live_hysteresis(before_engine.assign(risk=np.where(scorable, before_engine["risk"], np.nan)),
                                            history, thresholds, config)
    before = published_like(before_engine, before_level, scorable)

    after_engine = live_engine(features, new, scorable, thresholds, config, persisted)
    after_engine = pr.apply_post_rules(features, new, after_engine, rules, thresholds, scorable)
    rain_history = pr.previous_rain_ok(live_dir, day, int(cfg["hysteresis_history_days"]), rules)
    after_level = pr.live_hysteresis(after_engine.assign(risk=np.where(scorable, after_engine["risk"], np.nan)),
                                     history, rain_history, thresholds, config, rules)
    after = pr.mark_blind_holds(published_like(after_engine, after_level, scorable), ~scorable)

    acc3 = features["irain_acc_3"].to_numpy(dtype=np.float64)
    same_confidence = bool((before["confidence"].to_numpy() == published["confidence"].to_numpy()).all()
                           and (before["confidence_causes"].to_numpy() == published["confidence_causes"].to_numpy()).all())
    checks = audit.audit_table(after.assign(date=pd.Timestamp(day)), 0, thresholds, rules, features, rain_history,
                               audit.previous_alerts(live_dir, day, int(cfg["hysteresis_history_days"])))

    terrain_frame = pd.DataFrame({
        "level": before["level"].to_numpy()[scorable], "region": features["region"].to_numpy()[scorable],
        "acc_3": acc3[scorable], "risk": fields["risk"],
        **{k: fields[k] for k in ("c_aspect_sin", "c_aspect_cos", "c_twi", "c_positive", "margin", "top3_terrain")}})
    terrain_frame = terrain_frame[terrain_frame["level"] >= lv.WATCH].reset_index(drop=True)
    regional = {r: thresholds.of(r) for r in features["region"].unique()} if isinstance(thresholds, lv.RegionThresholds) \
        else {r: thresholds for r in features["region"].unique()}
    terrain = D.terrain_summary(D.with_counterfactual(terrain_frame, model, regional))
    return {"date": day.isoformat(), "run_finished_utc": summary.get("finished_utc"), "cells": int(len(features)),
            "scored": int(scorable.sum()), "previous_days_used": int(history["date"].nunique()),
            "published_levels": level_counts(published["level"]),
            "before": {"levels": level_counts(before["level"]), "dry": dry_counts(before["level"], acc3),
                       "interval_violations": interval_violations(before),
                       "confidence": before["confidence"].value_counts().to_dict(),
                       "confidence_matches_published": same_confidence},
            "after": {"levels": level_counts(after["level"]), "dry": dry_counts(after["level"], acc3),
                      "interval_violations": interval_violations(after),
                      "confidence": after["confidence"].value_counts().to_dict(),
                      "ensemble_disagrees": int(after["confidence_causes"].str.contains(pr.CAUSE_ENSEMBLE).sum()),
                      "no_recent_rain_capped": int(after["reason_codes"].str.contains(pr.CODE_NO_RECENT_RAIN).sum()),
                      "audit": checks.to_dict()},
            "reported_cells": reported_cells(features, before, after),
            "terrain": terrain}


def run(rules_path: Path, cfg: dict, day: date, say=print) -> dict:
    started = time.perf_counter()
    rules = pr.load_rules(rules_path)
    model = live_run.load_live_model(cfg)
    config = load_alert_config(live_run.project_path(cfg["alert_config"]))
    result = {"rules": rules.to_dict(), "rules_source": hm.display_path(Path(rules_path)),
              "season_2018": season_2018(cfg, model, config, rules, say),
              "live_day": live_day(day, cfg, model, config, rules, say)}
    result["seconds"] = time.perf_counter() - started
    path = H.alerts_dir(H.HELDOUT_DIR) / EVALUATION_FILE
    dump_json(path, result)
    say(f"wrote {hm.display_path(path)}")
    return result


# ------------------------------------------------------------------------------------- regression fixture

FIXTURE_DAYS = ("2026-10-17", "2026-10-18", "2026-10-19", "2026-10-20", "2026-10-21", "2026-10-23")
RERUN_DAYS = ("2026-10-17", "2026-10-18", "2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23")
HISTORY_COLUMNS = ["cell_id", "date", "raw_level", "risk", "level", "level_name", "confidence", "reason_codes"]


def write_false_alarm_fixture(cfg: dict, out: Path, say=print, days=FIXTURE_DAYS) -> Path:
    """The stored rows of the two reported cells as a hermetic test fixture: their `features_D0` rows and published alert
    rows on the days of `FIXTURE_DAYS`, the frozen model's scores of 23 Oct (re-centred interval, member median,
    agreement) and the thresholds and alert parameters the run used."""
    live_dir = live_run.live_root(cfg)
    model = live_run.load_live_model(cfg)
    features, published = [], []
    for day in days:
        run_dir = live_dir / day
        f = pd.read_parquet(run_dir / "features_D0.parquet")
        a = pd.read_parquet(run_dir / "alerts.parquet")
        features.append(f[f["cell_id"].isin(FALSE_ALARMS)])
        published.append(a[a["cell_id"].isin(FALSE_ALARMS)][HISTORY_COLUMNS])
    features = pd.concat(features, ignore_index=True)
    last = features[features["date"] == pd.Timestamp(days[-1])].reset_index(drop=True)
    scores = model.score(last).assign(cell_id=last["cell_id"].to_numpy())
    summary = json.loads((live_dir / days[-1] / "run.json").read_text(encoding="utf-8"))
    context = {"thresholds": summary["model"]["thresholds"], "thresholds_by_region": summary["model"]["thresholds_by_region"],
               "alert_config": load_alert_config(live_run.project_path(cfg["alert_config"])).to_dict(),
               "cells": list(FALSE_ALARMS), "days": list(days),
               "note": "built by `python -m aetherguard.live.hardening fixture` from data/live"}
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    features.to_parquet(out / "features.parquet", index=False)
    pd.concat(published, ignore_index=True).to_parquet(out / "published.parquet", index=False)
    scores.to_parquet(out / "scores_2026-10-23.parquet", index=False)
    dump_json(out / "context.json", context)
    say(f"wrote {hm.display_path(out)}")
    return out
