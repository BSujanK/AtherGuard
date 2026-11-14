"""The daily live run: fetch, featurise, score, alert, publish.

    python -m aetherguard.live run --date today|YYYY-MM-DD [--force] [--backtest] [--config configs/live_run.yaml]

For IST date D (run at 11:00 IST) the run writes, under `<live_dir>/<D>/`:
    raw/                    source files (IMD real-time grids, the gauge table, ...)
    freshness.json          every source's status and the product behind the last two IMD days (read by the dashboard API)
    features_D0.parquet     one row per scored cell: terrain, `irain_/iapi_/inbr_` model inputs, the alert engine's `src_*`/`integ_*`
    risk_D0.parquet ..      risk, interval, level and confidence per cell for lead 0 (D) and leads 1..3 (D+1..D+3); the
                            forecast leads also hold `reason_codes`, `shap_json` and `reasons_json` (the lead's own input contributions)
    features_D1.parquet ..  forecast leads: the model inputs of that lead's feature day plus `gfs_rain_d1..d<k>`, the GFS
                            IMD-day rain (mm) at the cell for D+1..D+k (what the dashboard shows as "forecast rain")
    alerts.parquet          the alert engine's table for lead 0 (hysteresis continued from the previous days' live state)
    run.json                the run summary; written last, so its presence means the day is complete
plus the bulletin `<report_dir>/<D>.md` and the day's alert table and gauge table (every gauge of the integrity run, with
its state on D and its last reading date; none when the integrity engine did not run) in the replay-store set `live`.

Rules the run follows (spec sections 5 and 10)
* A source that is late or missing never stops the run. A cell whose rain inputs are missing (`irain_acc_3` NaN) gets no
  risk (NaN), confidence `Insufficient` (cause `model_input_missing`), and the blind-escalation rule still applies:
  heavy rain in any other source raises it to at least Watch. A cell without a score keeps the level it had the day
  before (hysteresis never steps down on missing data). IMD real-time missing lowers confidence to `Degraded` only.
* The second-opinion rain check (IMD real-time against IMERG) uses the newest IMD day due by the run time under the
  source's declared latency, D-1 at 11:00 IST, or D when its file is already there (`second_opinion`, the `chk_` columns
  of features_D0, run.json `second_opinion`): a day inside its latency is not a degradation; IMD later than that is.
* The 00-03 UTC rain of IMD day D comes from the GFS 00Z cycle of D, else the 18Z or 12Z cycle of D-1, else is persisted
  from UTC D-1; persisted, every cell is capped at `Degraded` (cause `nowcast_tail_persisted`) and the blind rule is
  applied again. GFS alone therefore never makes lead 0 Insufficient.
* Forecast leads D+1..D+3 need the GFS forecast; without it the lead files are absent and the bulletin says why. Their
  interval is widened by the factors of the forecast-skill report when it exists; otherwise confidence is at most
  `Degraded` (cause `forecast_uncertainty_uncalibrated`) and no factor is invented.
* Idempotent: a day whose run.json exists is skipped unless `--force`, except a day flagged `retry_recommended` (the
  rain of IMD day D could not be assembled), which is recomputed so the scheduler's later attempts can fill the gap.
* `--backtest` admits only inputs issued before the data cut-off (11:00 IST of D).
* Only the model's candidate cells are scored (`load_candidate_cells`); the other cells of the scored regions are not
  assessed and not written, and the bulletin states both counts. A cell is scored (at any lead) only when every rain
  input of the model is known (`scorable_mask`), and a forecast lead only for cells scored on day D.
* The model must be frozen (FROZEN.json verified); otherwise the CLI exits 1 with "v3-live model not frozen yet: ...".
* Two models (W3 live switch): lead 0 is scored by the model `lead0_model_config` names, the forecast leads by the one
  `model_config` names (both by `model_config` when the first is absent; every study reads `model_config`). A model with
  rain-intensity inputs (`iint_`) is never a forecast-lead model, since no forecast lead has an observed intensity day. Lead 0 reads them as training did: the
  complete half-hourly Late days of the model's lag (D-3..D-1 at lag 1), fetched when missing, and the per-cell W5
  static inputs from the static table; while either is missing, lead 0 is scored by the forecast-lead model and
  run.json `intensity` says why.
* Season of validity (`live.season`): a lead dated outside the declared months (`season_of_validity`, June-September)
  is published unchanged and flagged `outside_validated_season` in run.json and the bulletin.
* Post-model rules (spec section 11, `live.postrules`, the file named by `post_rules`): the rain trigger caps cell-days
  without recent rain (`no_recent_rain`) before the hysteresis, which holds a level only while it rained within the hold
  window and over at most `blind_hold_days` days without a score (`held_while_blind`); a Warning+ point the ensemble does
  not support is capped at Degraded (`ensemble_disagrees`). The forecast leads get the rain cap on their own rain windows,
  their `uncertain_high` bound from the rules and a confidence of their own (never High). Every published row is then
  audited (`live.audit`); the result is in run.json and `<report_dir>/audit/<D>.json`.

Exit codes: 0 published (or skipped), 3 published with `retry_recommended`, 1 error (no run.json written).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from ..alerts import levels as lv
from ..alerts.config import DEFAULT_UNCERTAIN_PERCENTILE, AlertConfig, alerts_settings, upper_column
from ..alerts.config import load_config_file as load_alert_config
from ..alerts.engine import EVIDENCE, TIER_CODES, reasons_json, run_alerts, uncertain_bound
from ..alerts.store import ALERTS_DIR, MANIFEST_FILE, SENSORS_DIR, iso, write_set
from ..config import PROJECT_ROOT, load_config_file
from ..features import imerg_build
from ..features import imerg_features as F
from ..features import imerg_intensity as ii
from ..features import static_w5
from ..features.compute import MIN_SHARE_ACC3_MM, STAT_COLUMNS, ClimTable
from ..features.sampling import candidate_cells
from ..hazard import model as hm
from ..hazard.freeze import FROZEN_NAME, FrozenMismatchError, default_external_files, verify_freeze
from ..ingest import imerg as imerg_grid
from ..ingest import imerg_hh
from ..manifest import sha256_file
from . import adapter, audit, bulletin, forecast_choice, forecast_features, forecast_map, season
from . import postrules as pr
from .sources import (PERSIST, SOURCE_NAMES, GfsData, GhcnData, ImergSource, LiveRainView, SourceStatus, default_sources,
                      fetch_all, freshness_record, imd_due_day, local_tz, make_context, project_path, resolve_day,
                      source_state, write_json_atomic)

log = logging.getLogger("aetherguard.live")

UTC = timezone.utc
SCHEMA = 1
CONFIDENCE = ("High", "Degraded", "Insufficient")
CORE_COLUMN = "irain_acc_3"          # the rain of the last three IMD days; `scorable_mask` checks every rain input
RAIN_INPUTS = frozenset(F.all_names())
SHARE_COLUMN = "irain_share1_3"      # NaN by definition when the 3-day rain is under MIN_SHARE_ACC3_MM
CELL_SET_DEFINITION = ("own-terrain cells of the regions in scope with a mean slope at or above the slope floor of the "
                       "frozen samples (the cells the model's universe, sampling and evaluation are drawn from)")
CAUSE_MODEL_INPUT = "model_input_missing"
CAUSE_FORECAST_MISSING = pr.CAUSE_FORECAST_MISSING
CAUSE_UNCALIBRATED = pr.CAUSE_UNCALIBRATED
CAUSE_NOWCAST_TAIL = "nowcast_tail_persisted"
INTENSITY_PREFIX = "iint_"
LEAD0_KEY = "lead0_model_config"
EXIT_RETRY = 3
RISK_COLUMNS = ["risk", "risk_lo", "risk_hi", "risk_per_100k"]
LEAD_COLUMNS = ["cell_id", "date", "lead", "lat", "lon", "region", *RISK_COLUMNS, "level", "level_name", "confidence",
                "confidence_causes", "uncertain_high", "widened", "certainty", "level_min", "level_max"]
REPLAY_STAGE = ".stage-live"
INTEGRITY_NOTE = ("the integrity engine ran with the IMD real-time grid and IMERG in place of the IMD final grid and CHIRPS "
                  "it was trained against, and without soil-wetness references; this substitution is not validated")


class LiveRunError(RuntimeError):
    """The run cannot be carried out at all (configuration, model, inputs); nothing is published."""


class ModelNotFrozen(LiveRunError):
    pass


@dataclass
class LiveDeps:
    """Replaceable parts of a run (tests pass fakes; every None is built from the configuration)."""
    sources: dict | None = None
    model: hm.HazardModel | None = None
    thresholds: lv.Thresholds | lv.RegionThresholds | None = None
    alert_config: AlertConfig | None = None
    cells: pd.DataFrame | None = None            # cell_id, lat, lon, region, stat_*
    clim: ClimTable | None = None
    integrity: Callable[[GhcnData, object, dict], pd.DataFrame] | None = None
    widening: dict | None = None
    now: Callable[[], datetime] | None = None
    cell_set: dict | None = None                 # counts for the bulletin when `cells` is handed in
    post_rules: pr.PostRules | None = None       # None: the file named by `post_rules` (no rules without that key)
    choice: forecast_choice.ForecastChoice | None = None    # None: the file named by `forecast_selection` (GFS everywhere without it)
    maps: forecast_map.ForecastMaps | None = None            # None: the file the choice names
    forecast_model: hm.HazardModel | None = None             # None: `model_config` when `lead0_model_config` is set, else the lead-0 model
    forecast_thresholds: lv.Thresholds | lv.RegionThresholds | None = None    # None: from the forecast-lead model's card
    intensity_root: Path | None = None                       # None: imerg_intensity.default_root()
    intensity_fetch: Callable | None = None                  # None: imerg_hh.fetch_complete_days
    static_table: pd.DataFrame | None = None                 # None: the W5 static table on disk


# ------------------------------------------------------------------------------------------------------ inputs

def load_run_config(path: Path | str | None = None) -> dict:
    return load_config_file(Path(path) if path else PROJECT_ROOT / "configs" / "live_run.yaml")


def live_root(cfg: dict) -> Path:
    return project_path(cfg["live_dir"])


def load_live_model(cfg: dict) -> hm.HazardModel:
    """The frozen v3-live model named by `cfg["model_config"]`; ModelNotFrozen unless its freeze record verifies."""
    config_path = project_path(cfg["model_config"])
    model_dir = hm.configured_model_dir(hm.hazard_config(config_path))
    if not (model_dir / FROZEN_NAME).is_file():
        raise ModelNotFrozen(f"v3-live model not frozen yet: {hm.display_path(model_dir / FROZEN_NAME)} not found "
                             f"(train and freeze it with --config {hm.display_path(config_path)})")
    try:
        verify_freeze(model_dir, default_external_files(config_path))
    except FrozenMismatchError as exc:
        raise ModelNotFrozen(f"v3-live model does not match its freeze record: {exc}") from exc
    return hm.HazardModel.load(model_dir)


def uses_intensity(model) -> bool:
    return any(str(c).startswith(INTENSITY_PREFIX) for c in model.columns)


def lead0_key(cfg: dict) -> str:
    """The configuration key naming the lead-0 model: `lead0_model_config` when set, else `model_config`."""
    return LEAD0_KEY if cfg.get(LEAD0_KEY) else "model_config"


def split_configured(cfg: dict) -> bool:
    return lead0_key(cfg) == LEAD0_KEY and cfg[LEAD0_KEY] != cfg["model_config"]


def load_forecast_model(cfg: dict, deps: LiveDeps, model: hm.HazardModel) -> hm.HazardModel:
    """The model of the forecast leads: handed in, else the frozen model `model_config` names when lead 0 has a model of
    its own, else `model`. It may not read rain intensity: no forecast lead has an observed intensity day."""
    if deps.forecast_model is not None:
        forecast = deps.forecast_model
    elif deps.model is None and split_configured(cfg):
        forecast = load_live_model(cfg)
    else:
        forecast = model
    if uses_intensity(forecast) or set(forecast.columns) & set(static_w5.STATIC_COLUMNS):
        raise LiveRunError("the forecast-lead model reads rain-intensity inputs, which no forecast lead has observed, or "
                           "static inputs, which only lead 0 joins; `model_config` must name a model without them")
    return forecast


def intensity_inputs(day: date, cells: pd.DataFrame, model: hm.HazardModel, deps: LiveDeps) -> tuple[pd.DataFrame | None, dict]:
    """The six `iint_` inputs of IMD day `day` for lead 0, built as training built them: from the complete Late day files of
    the model's lag (`card.intensity.lag_days`), fetched when missing. None, with the reason, while a day is missing."""
    lag = int(model.card.get("intensity", {}).get("lag_days", 0))
    root = Path(deps.intensity_root or ii.default_root())
    days = ii.window_days([day], lag)
    status = {"run": ii.RUN, "lag_days": lag, "days": [d.isoformat() for d in days]}
    problems: dict = {}
    if ii.missing_days(root, days, ii.RUN):
        try:
            problems = (deps.intensity_fetch or imerg_hh.fetch_complete_days)(ii.RUN, days, root)
        except Exception as exc:      # a failing source never stops the run
            problems = {d: f"{type(exc).__name__}: {str(exc)[:160]}" for d in days}
    missing = ii.missing_days(root, days, ii.RUN)
    if missing:
        why = "; ".join(f"{d.isoformat()}: {problems.get(d, 'no day file')}" for d in missing)
        return None, {**status, "used": False, "reason": f"half-hourly Late days missing ({why})"}
    frame = ii.cell_features(day, cells["cell_id"].to_numpy(dtype=np.int64), root, ii.RUN, lag)
    return frame, {**status, "used": True, "reason": None}


def static_inputs(cells: pd.DataFrame, model: hm.HazardModel, deps: LiveDeps) -> tuple[pd.DataFrame | None, dict | None]:
    """The per-cell W5 static inputs the lead-0 model reads (none: (None, None)), joined at the cell as training joined
    them. (None, status) when the table cannot be read."""
    names = [c for c in model.columns if c in static_w5.STATIC_COLUMNS]
    if not names:
        return None, None
    try:
        table = deps.static_table if deps.static_table is not None else static_w5.static_table()
        frame = static_w5.join_static(cells[["cell_id"]], table)[names]
    except (OSError, ValueError, KeyError) as exc:
        return None, {"used": False, "inputs": names, "reason": f"static table unavailable ({type(exc).__name__}: {str(exc)[:160]})"}
    return frame, {"used": True, "inputs": names, "reason": None, "cells_without_a_value": int(frame.isna().any(axis=1).sum())}


def imd_lon_offset(cfg: dict) -> int:
    """Columns the live IMD sampling is moved east (`imd_lon_offset_columns`, 0 when absent)."""
    return int(cfg.get("imd_lon_offset_columns", 0))


SECOND_OPINION_WINDOW = 3            # days of the source-disagreement ratio the confidence logic reads (dis_ratio_3)
SECOND_OPINION_PARAMETERS = ("dis_ratio_lo", "dis_ratio_hi", "agree_abs_mm", "agree_rel")


def second_opinion(day: date, grids: dict, horizon: datetime, latency_h: float, config: AlertConfig) -> tuple[date | None, dict]:
    """(the check day, its run.json record) of the second-opinion rain check (`alerts.confidence`).

    The check day is the newest IMD day with a real-time file that is no older than the newest day due by `horizon` (the
    run time, or the backtest cut-off) under the declared latency `latency_h` (`sources.imd_due_day`): D-1 at the 11:00
    IST run, D when its file is already there. None when IMD is later than its latency (no file for a due day or a newer
    one: `late`) or has no file at all (`missing`); every cell is then `imd_missing`. The record names the days the
    check used and the parameters the confidence logic judged them with, so the audit can re-derive it."""
    due = imd_due_day(day, horizon, latency_h)
    candidates = [d for d in grids if due <= d <= day]
    check = max(candidates) if candidates else None
    window = None if check is None else [check - timedelta(days=SECOND_OPINION_WINDOW - 1 - k)
                                         for k in range(SECOND_OPINION_WINDOW)]
    state = "on_time" if check is not None else ("late" if grids else "missing")
    return check, {
        "source": "imd_rt", "latency_h": float(latency_h), "due_day": due.isoformat(),
        "check_day": None if check is None else check.isoformat(), "lag_days": None if check is None else (day - check).days,
        "window": None if window is None else [window[0].isoformat(), window[-1].isoformat()],
        "days_present": [] if window is None else [d.isoformat() for d in window if d in grids], "state": state,
        "parameters": {name: getattr(config, name) for name in SECOND_OPINION_PARAMETERS},
        "rule": ("confidence compares IMD real-time with IMERG on the 1- and 3-day totals ending on the check day, the newest "
                 "IMD day due by the run time under the declared latency (or day D when already published); a day still "
                 "inside its latency is not a degradation, IMD later than that is `imd_missing`")}


def load_post_rules(cfg: dict, deps: LiveDeps) -> pr.PostRules:
    """The post-model rules of the run: handed in, else the file `cfg["post_rules"]` names, else none."""
    if deps.post_rules is not None:
        return deps.post_rules
    path = cfg.get("post_rules")
    if not path:
        return pr.NO_RULES
    try:
        return pr.load_rules(project_path(path))
    except (OSError, ValueError) as exc:
        raise LiveRunError(f"post-model rules {path} cannot be loaded: {exc}") from exc


def card_thresholds(model: hm.HazardModel, regions) -> lv.Thresholds | lv.RegionThresholds:
    """The risk thresholds the model's risk is compared with: its calibration decides. A model calibrated per region
    (v3) is compared with the card's `risk_by_region` thresholds of each of `regions`, the pooled ones for any other
    region; a pooled model with the pooled card thresholds."""
    pooled = lv.thresholds_from_card(model.card, alerts_settings()["v1_card_fallback"])
    if model.region_calibrator is None:
        return pooled
    return lv.RegionThresholds(lv.card_region_thresholds(model.card, regions), pooled)


def pooled_thresholds(thresholds: lv.Thresholds | lv.RegionThresholds) -> lv.Thresholds:
    return thresholds.pooled if isinstance(thresholds, lv.RegionThresholds) else thresholds


def load_cells(cfg: dict) -> pd.DataFrame:
    """The scored cells: terrain table cells of the scored regions with their `stat_*` model inputs."""
    terrain = pd.read_parquet(project_path(cfg["terrain_table"]), columns=["cell_id", "lat", "lon", *STAT_COLUMNS])
    regions = pd.read_parquet(project_path(cfg["region_table"]), columns=["cell_id", "region"])
    cells = terrain.merge(regions, on="cell_id", how="inner", validate="one_to_one")
    cells = cells[cells["region"].isin(cfg["scored_regions"])].sort_values("cell_id").reset_index(drop=True)
    cells = cells.rename(columns={c: f"stat_{c}" for c in STAT_COLUMNS})
    return cells.astype({f"stat_{c}": np.float32 for c in STAT_COLUMNS})


def load_candidate_cells(cfg: dict) -> tuple[pd.DataFrame, dict]:
    """The cells the model was trained and evaluated on, with their `stat_*` inputs, and the counts for the bulletin.

    The candidate cells of the frozen samples (`features.sampling.candidate_cells`): own-terrain cells of a region in
    scope whose mean slope is at or above the slope floor stored in the samples manifest. The other cells of the scored
    regions are not assessed and not written. Returns (cells, {assessed, in_scope, not_assessed, slope_floor_deg,
    definition}).
    """
    everything = load_cells(cfg)
    manifest = json.loads(project_path(cfg["samples_manifest"]).read_text(encoding="utf-8"))
    floor = float(manifest["report"]["slope_floor"]["floor"])
    terrain = everything[["cell_id", "stat_slope_mean"]].rename(columns={"stat_slope_mean": "slope_mean"})
    wanted = candidate_cells(terrain, everything[["cell_id", "region"]], floor)["cell_id"]
    cells = everything[everything["cell_id"].isin(wanted)].reset_index(drop=True)
    return cells, {"assessed": int(len(cells)), "in_scope": int(len(everything)),
                   "not_assessed": int(len(everything) - len(cells)), "slope_floor_deg": floor,
                   "definition": CELL_SET_DEFINITION}


def scorable_mask(frame: pd.DataFrame, columns) -> np.ndarray:
    """Rows whose every model rain input (`irain_*`, `iapi_*`, `inbr_*` among `columns`) is finite.

    A model scores a NaN input anyway, along default branches it never saw as a pattern, so a cell with any missing rain
    input gets no score. Exception: `irain_share1_3` is NaN by definition when the 3-day rain is under 1 mm. (Terrain
    inputs are static and may be NaN; `irain_days_since_10mm` is NaN exactly when the 90-day window has a gap, so it
    needs no exception.)
    """
    ok = np.ones(len(frame), dtype=bool)
    for name in (c for c in columns if c in RAIN_INPUTS):
        known = np.isfinite(frame[name].to_numpy(dtype=np.float64))
        if name == SHARE_COLUMN:
            acc3 = frame[CORE_COLUMN].to_numpy(dtype=np.float64)
            with np.errstate(invalid="ignore"):
                known |= acc3 < MIN_SHARE_ACC3_MM
        ok &= known
    return ok


def lead_scorable(frame: pd.DataFrame, columns, scorable_on_day_d: np.ndarray) -> np.ndarray:
    """Forecast-lead rows that can be scored: complete rain inputs, and the cell was scorable on day D (a forecast
    built on observed days that are missing is not a forecast)."""
    return scorable_mask(frame, columns) & np.asarray(scorable_on_day_d, dtype=bool)


def load_climatology(cfg: dict, store, flat_pixels: np.ndarray) -> ClimTable:
    """Train-range IMERG climatology of the cells' pixels, cached under `<live_dir>/cache/` (it never changes)."""
    train = imerg_build.build_config()["climatology"]
    pixels = np.unique(flat_pixels[flat_pixels >= 0])
    cache = live_root(cfg) / "cache" / "imerg_climatology.npz"
    if cache.is_file():
        with np.load(cache, allow_pickle=False) as data:
            if (str(data["first_day"]), str(data["last_day"])) == (train["first_day"], train["last_day"]) \
                    and np.isin(pixels, data["pix"]).all():
                return ClimTable(data["pix"], data["values"])
    log.info("building the IMERG climatology of %d pixels (%s..%s)", len(pixels), train["first_day"], train["last_day"])
    clim = F.imerg_climatology(store, pixels, date.fromisoformat(train["first_day"]), date.fromisoformat(train["last_day"]))
    cache.parent.mkdir(parents=True, exist_ok=True)
    part = cache.with_name(cache.name + ".part.npz")
    np.savez(part, pix=clim.pix, values=clim.values, first_day=train["first_day"], last_day=train["last_day"])
    os.replace(part, cache)
    return clim


def _widening_payload(cfg: dict, deps: LiveDeps) -> tuple[dict | None, str | None]:
    payload = deps.widening
    path = project_path(cfg["forecast_widening"])
    if payload is None:
        if not path.is_file():
            return None, f"{cfg['forecast_widening']} not found (the forecast-skill step has not been run)"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return None, f"{cfg['forecast_widening']} is unreadable ({type(exc).__name__})"
    return payload, None


def _factors(leads: dict) -> dict[int, tuple[float, float]]:
    factors = {int(k): (float(v["lo"]), float(v["hi"])) for k, v in leads.items()}
    if sorted(factors) != [1, 2, 3] or not all(np.isfinite(f).all() and min(f) > 0 for f in factors.values()):
        raise ValueError
    return factors


def load_widening(cfg: dict, deps: LiveDeps) -> tuple[dict | None, str | None]:
    """(factors by lead {1: (lo, hi), ...}, reason it is absent). The file is
    {"leads": {"1": {"lo": f, "hi": f}, "2": ..., "3": ...}}: risk_lo and risk_hi of lead k are multiplied by lo / hi. They
    are the factors of the forecast configuration the file names (section 12); `fallback.leads` holds those of the GFS fallback."""
    payload, why = _widening_payload(cfg, deps)
    if payload is None:
        return None, why
    try:
        return _factors(payload["leads"]), None
    except (KeyError, TypeError, ValueError, AttributeError):
        return None, f"{cfg['forecast_widening']} does not hold positive finite lo/hi factors for leads 1, 2 and 3"


def load_fallback_widening(cfg: dict, deps: LiveDeps) -> dict | None:
    """The factors of the GFS fallback (`fallback.leads` of the widening file); None when the file has none, in which case the
    configuration's own factors are used for a fallback lead too."""
    payload, _ = _widening_payload(cfg, deps)
    try:
        return _factors(payload["fallback"]["leads"])
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


# --------------------------------------------------------------------------------------------- alert tables

def _split(text: str) -> list[str]:
    return text.split(";") if text else []


def _join(parts) -> str:
    return ";".join(dict.fromkeys(p for p in parts if p))


def finalize_alerts(alerts: pd.DataFrame, level: np.ndarray, unscorable: np.ndarray) -> pd.DataFrame:
    """The engine table (run without hysteresis) with the live levels and the cells without a score marked.

    `level` is the level after hysteresis; rows in `unscorable` lose their placeholder risk, get confidence
    Insufficient with cause `model_input_missing`, and keep their reasons consistent with that.
    """
    out = alerts.copy()
    raw = out["raw_level"].to_numpy()
    out["level"] = level.astype(np.int8)
    out["level_name"] = np.array(lv.LEVEL_NAMES, dtype=object)[level]
    for column in RISK_COLUMNS:
        out.loc[unscorable, column] = np.nan
    out.loc[unscorable, "uncertain_high"] = False
    out.loc[unscorable, "shap_json"] = "[]"
    out.loc[unscorable, "confidence"] = CONFIDENCE[2]
    changed = np.flatnonzero((level != raw) | unscorable)
    codes, causes = out["reason_codes"].tolist(), out["confidence_causes"].tolist()
    reasons = out["reasons_json"].tolist()
    for i in changed:
        held = level[i] > raw[i]
        codes[i] = _join([*_split(codes[i]), "hysteresis_hold" if held else "", CAUSE_MODEL_INPUT if unscorable[i] else ""])
        if unscorable[i]:
            causes[i] = _join([*_split(causes[i]), CAUSE_MODEL_INPUT])
        detail = json.loads(reasons[i])
        detail["level"], detail["codes"] = lv.level_name(level[i]), _split(codes[i])
        if unscorable[i]:
            detail["risk"] = {key: None for key in detail["risk"]}
            detail["confidence"] = {"state": CONFIDENCE[2], "causes": _split(causes[i])}
        reasons[i] = json.dumps(detail, allow_nan=False)
    out["reason_codes"], out["confidence_causes"], out["reasons_json"] = codes, causes, reasons
    return out


def cap_to_degraded(alerts: pd.DataFrame, config: AlertConfig, cause: str) -> pd.DataFrame:
    """Lower every `High` cell of an engine table (run without hysteresis) to `Degraded` with confidence cause `cause`.

    The blind-escalation rule depends on confidence, so it is applied again to the cells that just stopped being High:
    heavy rain in any source (the engine's own test on the evidence columns) raises their level to at least Watch, with
    reason code `<cause>_heavy_rain`. Rows that were not High are left as they are.
    """
    out = alerts.copy()
    capped = (out["confidence"] == CONFIDENCE[0]).to_numpy()
    if not capped.any():
        return out
    with np.errstate(invalid="ignore"):
        day = np.fmax.reduce([out[c].to_numpy(dtype=np.float64) for c in ("imd_acc_1", "chirps_acc_1", "station_max_1")])
        three = np.fmax.reduce([out[c].to_numpy(dtype=np.float64) for c in ("imd_acc_3", "chirps_acc_3", "station_trw_3")])
        heavy = (day >= config.heavy_acc1_mm) | (three >= config.heavy_acc3_mm)
    newly_blind = capped & heavy & ~out["blind"].to_numpy()
    blind_code = f"{cause}_heavy_rain"
    raw = out["raw_level"].to_numpy()
    out["blind_escalated"] = out["blind_escalated"].to_numpy() | (newly_blind & (raw < lv.WATCH))
    out["blind"] = out["blind"].to_numpy() | newly_blind
    out["raw_level"] = np.where(newly_blind, np.maximum(raw, lv.WATCH), raw).astype(np.int8)
    out["level"] = out["raw_level"]
    out["level_name"] = np.array(lv.LEVEL_NAMES, dtype=object)[out["level"].to_numpy()]
    out.loc[capped, "confidence"] = CONFIDENCE[1]
    codes, causes, reasons = out["reason_codes"].tolist(), out["confidence_causes"].tolist(), out["reasons_json"].tolist()
    for i in np.flatnonzero(capped):
        causes[i] = _join([*_split(causes[i]), cause])
        if newly_blind[i]:
            codes[i] = _join([*_split(codes[i]), blind_code])
        detail = json.loads(reasons[i])
        detail["confidence"] = {"state": CONFIDENCE[1], "causes": _split(causes[i])}
        detail["codes"], detail["raw_level"], detail["level"] = _split(codes[i]), lv.level_name(out["raw_level"].iat[i]), \
            lv.level_name(out["level"].iat[i])
        reasons[i] = json.dumps(detail, allow_nan=False)
    out["reason_codes"], out["confidence_causes"], out["reasons_json"] = codes, causes, reasons
    return out


def previous_state(live_dir: Path, day: date, days: int) -> pd.DataFrame:
    """(cell_id, date, raw_level, risk) of the live alert tables of the consecutive days before `day`."""
    frames = []
    for k in range(1, days + 1):
        path = live_dir / (day - timedelta(days=k)).isoformat() / "alerts.parquet"
        if not path.is_file():
            break
        frames.append(pd.read_parquet(path, columns=["cell_id", "date", "raw_level", "risk"]))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(
        {"cell_id": pd.Series(dtype="int64"), "date": pd.Series(dtype="datetime64[ns]"),
         "raw_level": pd.Series(dtype="int8"), "risk": pd.Series(dtype="float64")})


def live_hysteresis(today: pd.DataFrame, history: pd.DataFrame, thresholds: lv.Thresholds | lv.RegionThresholds,
                    config: AlertConfig) -> np.ndarray:
    """Levels of `today` after the hysteresis state machine run over the previous days' live state, then today.

    The history rows carry the raw level and risk the previous runs published, so a cell that was at Warning keeps
    stepping down by the same rules; a NaN risk (no score) never qualifies for a step down. Thresholds by region apply
    to a cell with the region it has today (a history cell that is not scored today gets the pooled ones)."""
    both = pd.concat([history, today[["cell_id", "date", "raw_level", "risk"]]], ignore_index=True)
    region = (both["cell_id"].map(dict(zip(today["cell_id"], today["region"]))).to_numpy(dtype=object)
              if isinstance(thresholds, lv.RegionThresholds) else None)
    levels = lv.apply_hysteresis(both["cell_id"].to_numpy(), both["date"], both["raw_level"].to_numpy(),
                                 both["risk"].to_numpy(), thresholds, config.exit_factor, config.exit_days, region)
    return levels[len(history):]


def count_levels(level) -> dict:
    counts = Counter(np.asarray(level).tolist())
    return {name: int(counts.get(i, 0)) for i, name in enumerate(lv.LEVEL_NAMES)}


def count_confidence(confidence) -> dict:
    counts = Counter(np.asarray(confidence).tolist())
    return {name: int(counts.get(name, 0)) for name in CONFIDENCE}


def count_causes(causes) -> dict:
    counts = Counter(c for text in causes for c in _split(text))
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def _reason_texts(contribution: list[dict], limit: int = 3) -> list[str]:
    return [f"{c['feature']}" + ("" if c["value"] is None else f"={c['value']:.4g}") + f" ({c['contribution']:+.2f})"
            for c in contribution[:limit]]


def top_cells(table: pd.DataFrame, contributions: Callable[[pd.DataFrame], list[list[dict]]], n: int) -> list[dict]:
    """The `n` cells at Watch or above with the highest level, then risk (no score last), with their top reasons."""
    flagged = table[table["level"] >= 1]
    top = flagged.sort_values(["level", "risk"], ascending=[False, False], na_position="last", kind="stable").head(n)
    reasons = contributions(top) if len(top) else []
    rows = []
    for (_, row), why in zip(top.iterrows(), reasons):
        rows.append({"cell_id": int(row["cell_id"]), "lat": float(row["lat"]), "lon": float(row["lon"]),
                     "region": str(row["region"]), "level": int(row["level"]), "level_name": row["level_name"],
                     "risk": None if not np.isfinite(row["risk"]) else float(row["risk"]),
                     "risk_lo": None if not np.isfinite(row["risk_lo"]) else float(row["risk_lo"]),
                     "risk_hi": None if not np.isfinite(row["risk_hi"]) else float(row["risk_hi"]),
                     "confidence": row["confidence"], "confidence_causes": _split(row["confidence_causes"]),
                     "codes": _split(row["reason_codes"]) if "reason_codes" in row.index else [],
                     "reasons": why})
    return rows


def lead_table(day: date, lead: int, frame: pd.DataFrame, scores: pd.DataFrame | None, level: np.ndarray,
               confidence: np.ndarray, causes: list[str], uncertain: np.ndarray, widened: bool,
               certainty: tuple[np.ndarray, np.ndarray, np.ndarray] | None = None) -> pd.DataFrame:
    """One risk_D{lead} table. `scores` is indexed like `frame` (NaN risk where a cell has no score). `certainty` is
    `postrules.scenario_certainty` of a forecast lead; lead 0 has none (its `level_min` / `level_max` are its level)."""
    out = pd.DataFrame({"cell_id": frame["cell_id"].to_numpy(dtype=np.int64),
                        "date": pd.Timestamp(day + timedelta(days=lead)), "lead": np.int8(lead),
                        "lat": frame["lat"].to_numpy(), "lon": frame["lon"].to_numpy(),
                        "region": frame["region"].to_numpy()}, index=frame.index)
    for column in RISK_COLUMNS:
        out[column] = scores[column].to_numpy(dtype=np.float64)
    out["level"], out["level_name"] = level.astype(np.int8), np.array(lv.LEVEL_NAMES, dtype=object)[level]
    out["confidence"], out["confidence_causes"] = confidence, causes
    out["uncertain_high"], out["widened"] = uncertain, widened
    kind, low, high = certainty if certainty is not None else (np.full(len(out), None, dtype=object), level, level)
    out["certainty"], out["level_min"], out["level_max"] = kind, np.asarray(low, dtype=np.int8), np.asarray(high, dtype=np.int8)
    return out[LEAD_COLUMNS]


# ---------------------------------------------------------------------------------------------------- publishing

def publish_replay_day(root: Path, set_name: str, alerts: pd.DataFrame, extra: dict, sensors: pd.DataFrame | None = None,
                       sensor_gap: str | None = None) -> dict:
    """Add the alert table (and the gauge table, when there is one) of one day to the replay-store set `set_name`; a
    rewrite replaces the day (stage, then replace). A day without a gauge table keeps `sensor_gap`, why there is none, in
    the entry's `sensor_gaps` and drops a table an earlier run of the day wrote; `sensor_dates` lists the days that have one."""
    root = Path(root)
    day = iso(alerts["date"].iloc[0])
    stage = root / REPLAY_STAGE
    shutil.rmtree(stage, ignore_errors=True)
    write_set(stage, set_name, alerts, sensors)
    folder = root / set_name / ALERTS_DIR
    folder.mkdir(parents=True, exist_ok=True)
    os.replace(stage / set_name / ALERTS_DIR / f"{day}.parquet", folder / f"{day}.parquet")
    sensor_folder = root / set_name / SENSORS_DIR
    sensor_folder.mkdir(parents=True, exist_ok=True)
    if sensors is not None:
        os.replace(stage / set_name / SENSORS_DIR / f"{day}.parquet", sensor_folder / f"{day}.parquet")
    else:
        (sensor_folder / f"{day}.parquet").unlink(missing_ok=True)
    shutil.rmtree(stage, ignore_errors=True)
    files = sorted(folder.glob("*.parquet"))
    sensor_dates = [p.stem for p in sorted(sensor_folder.glob("*.parquet"))]
    manifest_path = root / MANIFEST_FILE
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {"sets": {}}
    previous = manifest["sets"].get(set_name, {})
    gaps = {d: why for d, why in previous.get("sensor_gaps", {}).items() if d not in sensor_dates}
    if sensor_gap is not None:
        gaps[day] = sensor_gap
    entry = {"dates": [p.stem for p in files], "n_rows": int(sum(pq.ParquetFile(p).metadata.num_rows for p in files)),
             "n_cells": max(int(alerts["cell_id"].nunique()), int(previous.get("n_cells", 0))),
             "has_sensors": bool(sensor_dates), "sensor_dates": sensor_dates, "sensor_gaps": dict(sorted(gaps.items())),
             **extra}
    manifest["sets"][set_name] = entry
    write_json_atomic(manifest_path, manifest)
    return entry


def write_parquet_atomic(frame: pd.DataFrame, path: Path, compression: str = "snappy") -> None:
    part = path.with_name(path.name + ".part")
    frame.to_parquet(part, index=False, compression=compression)
    os.replace(part, path)


# ----------------------------------------------------------------------------------------------------- the run

def with_uncertain_bound(scored: pd.DataFrame, model, rows: pd.DataFrame, config: AlertConfig, widen: float = 1.0
                         ) -> pd.DataFrame:
    """`scored` (the model's scores of `rows`) plus the column of the ensemble percentile that `uncertain_high` tests when
    that is not the model's own `risk_hi`; `widen` multiplies it (never below the point risk), as the forecast leads
    widen `risk_hi`."""
    percentile = config.uncertain_percentile
    if percentile is None or percentile == DEFAULT_UNCERTAIN_PERCENTILE:
        return scored
    bound = model.ensemble_percentile(rows, percentile) * widen
    return scored.assign(**{upper_column(percentile): np.maximum(bound, scored["risk"].to_numpy())})


def forecast_codes(table: pd.DataFrame, thresholds, extra_codes=None) -> list[str]:
    """`reason_codes` of a forecast lead (`;`-joined per cell, as lead 0's): the level tier of the risk alone, the
    uncertain-high code, then `extra_codes` (the post-model rule codes, one `;`-joined string per row)."""
    risk = table["risk"].to_numpy(dtype=np.float64)
    known = np.isfinite(risk)
    point = np.zeros(len(table), dtype=np.int8)
    if known.any():
        region = table["region"].to_numpy()[known] if isinstance(thresholds, lv.RegionThresholds) else None
        point[known] = lv.level_from_risk(risk[known], thresholds, region)
    extra = extra_codes if extra_codes is not None else [""] * len(table)
    return [";".join(c for c in (TIER_CODES[p], lv.UNCERTAIN_HIGH if u else "", x) if c)
            for p, u, x in zip(point, table["uncertain_high"], extra)]


def forecast_reasons(table: pd.DataFrame, contributions: list[list[dict]], codes: list[str],
                     annotations: list[dict] | None = None) -> list[str]:
    """`reasons_json` of a forecast lead, built by the same function as lead 0's. A forecast has no rain evidence of the
    target day (no IMD grid, gauges or satellite for a future day) and no stations, so those fields are empty.
    `codes` are the lead's `forecast_codes`; `annotations` ({median, agreement, ok, capped} per row) add the `ensemble`
    and `rain_rule` entries."""
    evidence = {name: np.nan for name in EVIDENCE}
    out = table.assign(raw_level=table["level"], reason_codes=codes, rain_source="gfs", n_stations=0, n_trusted=0,
                       n_flagged_7d=0, n_ood_stations=0, flagged_types="", **evidence)
    texts = reasons_json(out, contributions)
    if annotations is None:
        return texts
    return [json.dumps(pr.annotate(json.loads(t), a["median"], a["agreement"], a["ok"], False, a["capped"]),
                       allow_nan=False) for t, a in zip(texts, annotations)]


def gfs_rain_columns(cell_ids: np.ndarray, forecast_days: np.ndarray, lead: int) -> dict[str, np.ndarray]:
    """`gfs_rain_d1..gfs_rain_d<lead>`: the forecast IMD-day rain (mm) at each cell's IMERG pixel for D+1..D+lead (NaN for a
    cell outside the domain grid). The columns keep their original name; since section 12 they hold the rain of the source the
    lead is built from (`forecast.source` in run.json), bias-corrected when that configuration says so."""
    flat = F.cell_pixels(cell_ids)
    inside = flat >= 0
    columns = {}
    for k in range(1, lead + 1):
        values = np.full(len(flat), np.nan, dtype=np.float32)
        values[inside] = forecast_days[k - 1][flat[inside] // imerg_grid.COLS, flat[inside] % imerg_grid.COLS]
        columns[f"gfs_rain_d{k}"] = values
    return columns


def lead_scores(model, frame: pd.DataFrame, scorable: np.ndarray, thresholds, alert_config: AlertConfig, rules: pr.PostRules,
                factor: tuple[float, float] | None) -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    """(scores, raw level, uncertain_high) of one forecast lead's rows: the model's scores with the interval widened by the
    lead's `factor` (lo, hi) (risk_hi capped at 1), and the level of the point risk with the `uncertain_high` test of the rules, before the rain
    cap. Rows that are not `scorable` have NaN scores and level Normal."""
    scores = pd.DataFrame(np.nan, index=frame.index, columns=[*RISK_COLUMNS, *pr.ENSEMBLE_COLUMNS])
    level = np.zeros(len(frame), dtype=np.int8)
    uncertain = np.zeros(len(frame), dtype=bool)
    if scorable.any():
        scored = model.score(frame[scorable])
        # a copy: the widening below assigns risk_hi in place, and with the default percentile with_uncertain_bound
        # returns `scored` itself, which would turn the unwidened bound into the widened one
        unwidened = with_uncertain_bound(scored.copy(), model, frame[scorable], alert_config)
        lo, hi = factor if factor else (1.0, 1.0)
        scored["risk_lo"] = np.minimum(scored["risk_lo"] * lo, scored["risk"])
        scored["risk_hi"] = np.maximum(np.minimum(scored["risk_hi"] * hi, 1.0), scored["risk"])    # a probability: at most 1
        scores.loc[scorable] = scored.reindex(columns=[*RISK_COLUMNS, *pr.ENSEMBLE_COLUMNS])
        widened = with_uncertain_bound(scored, model, frame[scorable], alert_config, hi)
        bound = pr.lead_bound(rules, scored["risk"], uncertain_bound(unwidened, alert_config),
                              uncertain_bound(widened, alert_config))
        level[scorable], uncertain[scorable] = lv.raw_level(
            scores["risk"].to_numpy()[scorable], bound, thresholds,
            frame["region"].to_numpy()[scorable] if isinstance(thresholds, lv.RegionThresholds) else None)
    return scores, level, uncertain


def scenario_level(model, cells: pd.DataFrame, day: date, lead: int, view, clim: ClimTable, rain: np.ndarray,
                   base_scorable: np.ndarray, thresholds, alert_config: AlertConfig, rules: pr.PostRules,
                   factor: tuple[float, float] | None) -> np.ndarray:
    """The published level of every cell of lead `lead` when the IMD-day rain after day D is `rain` ((lead, rows, cols) mm):
    the same features, model, `uncertain_high` test and rain cap as the forecast row itself."""
    features = forecast_features.lead_features(cells, day, lead, view, rain, clim)
    frame = pd.concat([cells, features], axis=1)
    scorable = lead_scorable(frame, model.columns, base_scorable)
    _, level, _ = lead_scores(model, frame, scorable, thresholds, alert_config, rules, factor)
    ok = pr.rain_ok(frame, rules) | ~scorable
    return pr.capped_levels(level, ok, np.zeros(len(frame), dtype=bool), rules)[0]


def forecast_products(gfs: GfsData | None, ecmwf_forecast) -> dict[str, forecast_choice.ProductDay]:
    """The forecast sources of the run as `forecast_choice.ProductDay`s."""
    products: dict[str, forecast_choice.ProductDay] = {}
    if gfs is not None and gfs.forecast is not None:
        products["gfs"] = forecast_choice.ProductDay(gfs.forecast.days, gfs.forecast.day_valid, gfs.forecast.cycle)
    if ecmwf_forecast is not None:
        if ecmwf_forecast.hres is not None:
            products["ecmwf_hres"] = forecast_choice.ProductDay(ecmwf_forecast.hres, ecmwf_forecast.hres_valid,
                                                                ecmwf_forecast.hres_cycle, ecmwf_forecast.ens_p90,
                                                                ecmwf_forecast.ens_mean)
        if ecmwf_forecast.ens_mean is not None:
            products["ecmwf_ens_mean"] = forecast_choice.ProductDay(ecmwf_forecast.ens_mean, ecmwf_forecast.ens_valid,
                                                                    ecmwf_forecast.ens_cycle, ecmwf_forecast.ens_p90,
                                                                    ecmwf_forecast.ens_mean)
    return products


def load_choice_and_maps(cfg: dict, deps: LiveDeps) -> tuple[forecast_choice.ForecastChoice, forecast_map.ForecastMaps | None]:
    """The forecast configuration of the run (handed in, else the file `forecast_selection` names, else GFS everywhere) and
    the bias-correction curves it needs."""
    choice = deps.choice
    if choice is None:
        try:
            choice = forecast_choice.load_choice(project_path(cfg["forecast_selection"]) if cfg.get("forecast_selection") else None)
        except (OSError, ValueError, KeyError) as exc:
            raise LiveRunError(f"forecast selection {cfg.get('forecast_selection')} cannot be loaded: {exc}") from exc
    if not any(c.mapped for c in (*choice.leads.values(), choice.fallback)):
        return choice, None
    if deps.maps is not None:
        return choice, deps.maps
    try:
        return choice, forecast_map.ForecastMaps.load(project_path(choice.maps_file), forecast_map.pixel_regions_of(cfg))
    except (OSError, ValueError, KeyError) as exc:
        raise LiveRunError(f"forecast mapping {choice.maps_file} cannot be loaded: {exc}") from exc


def count_certainty(certainty) -> dict:
    counts = Counter(c for c in np.asarray(certainty, dtype=object).tolist() if c)
    return {kind: int(counts.get(kind, 0)) for kind in (pr.CERTAINTY_FIRM, pr.CERTAINTY_DEPENDS)}


def _forecast_leads(day: date, cfg: dict, deps: LiveDeps, model, thresholds, alert_config: AlertConfig,
                    cells: pd.DataFrame, view, clim: ClimTable, products: dict, choice: forecast_choice.ForecastChoice, maps,
                    statuses: dict[str, SourceStatus], base: pd.DataFrame, base_scorable: np.ndarray, run_dir: Path,
                    rules: pr.PostRules) -> tuple[dict, dict]:
    """Write risk_D1..3 and return ({lead: summary}, widening info)."""
    factors, why_absent = load_widening(cfg, deps)
    fallback_factors = load_fallback_widening(cfg, deps)
    widening = {"applied": factors is not None, "path": cfg["forecast_widening"], "reason": why_absent}
    summaries: dict[int, dict] = {}
    base_confidence = dict(zip(base["cell_id"].to_numpy(), base["confidence"]))
    for lead in (1, 2, 3):
        target = day + timedelta(days=lead)
        path = run_dir / f"risk_D{lead}.parquet"
        features_path = run_dir / f"features_D{lead}.parquet"
        path.unlink(missing_ok=True)
        features_path.unlink(missing_ok=True)
        field = forecast_choice.resolve_lead(products, choice, maps, lead)
        if field is None:
            reasons = [f"{label} forecast day D+{lead} not available: {statuses[name].error or 'no valid forecast'}"
                       for name, label in (("gfs", "GFS"), ("ecmwf", "ECMWF")) if name in statuses]
            summaries[lead] = {"lead": lead, "date": target.isoformat(), "published": False,
                               "reason": "; ".join(reasons) or f"no forecast source for D+{lead}"}
            continue
        lead_factors = fallback_factors if (field.fallback and fallback_factors) else factors
        factor = lead_factors[lead] if lead_factors else None
        features = forecast_features.lead_features(cells, day, lead, view, field.days, clim)
        frame = pd.concat([cells, features], axis=1)
        scorable = lead_scorable(frame, model.columns, base_scorable)
        scores, level, uncertain = lead_scores(model, frame, scorable, thresholds, alert_config, rules, factor)
        state = [base_confidence.get(int(cell), CONFIDENCE[2]) for cell in frame["cell_id"].to_numpy()]
        confidence, causes = pr.lead_confidence(state, scorable, lead_factors is not None)
        level, confidence, causes, rule_codes = pr.apply_lead_rules(frame, scores, level, confidence, causes, rules,
                                                                    thresholds, scorable)
        scenes = forecast_choice.scenario_fields(field, factor[1] if factor else 1.0)
        others = {name: scenario_level(model, cells, day, lead, view, clim, scenes[name], base_scorable, thresholds,
                                       alert_config, rules, factor) for name in ("dry", "wet")}
        certainty = pr.scenario_certainty(level, others["dry"], others["wet"], scorable)
        ok = pr.rain_ok(frame, rules) | ~scorable
        annotations = [{"median": m, "agreement": a, "ok": o, "capped": bool(c)} for m, a, o, c in
                       zip(scores["member_median_risk"].to_numpy(), scores["ensemble_agreement"].to_numpy(), ok, rule_codes)]
        table = lead_table(day, lead, frame, scores, level, confidence, causes, uncertain, lead_factors is not None, certainty)
        contribution: list[list[dict]] = [[] for _ in range(len(frame))]
        if scorable.any():
            for position, one in zip(np.flatnonzero(scorable), model.contributions(frame[scorable])):
                contribution[position] = one
        table["shap_json"] = [json.dumps(c, allow_nan=False) for c in contribution]
        table["reason_codes"] = forecast_codes(table, thresholds, rule_codes)
        table["reasons_json"] = forecast_reasons(table, contribution, table["reason_codes"].tolist(), annotations)
        detail = (frame[["cell_id"]].assign(date=pd.Timestamp(target)).join(frame[["lat", "lon", "region", *model.columns]])
                  .assign(**gfs_rain_columns(frame["cell_id"].to_numpy(), field.days, lead)))
        write_parquet_atomic(table, path, compression="zstd")
        write_parquet_atomic(detail, features_path)

        def contributions(top: pd.DataFrame, frame=frame) -> list[list[dict]]:
            return [_reason_texts(c) for c in model.contributions(frame.loc[top.index])]
        summaries[lead] = {
            "lead": lead, "date": target.isoformat(), "published": True, "reason": None, "file": path.name,
            "n_cells": int(len(table)), "n_scored": int(scorable.sum()), "levels": count_levels(table["level"]),
            "confidence": count_confidence(table["confidence"]), "confidence_causes": count_causes(table["confidence_causes"]),
            "forecast": {"source": field.config.source, "mapped": field.config.mapped, "label": field.label,
                         "fallback": field.fallback, "cycle": None if field.cycle is None else field.cycle.isoformat(),
                         "wet_bound": "ensemble_spread" if field.spread is not None else "high_factor"},
            "certainty": count_certainty(table["certainty"]),
            "top_cells": top_cells(table, contributions, int(cfg["top_cells"]))}
    return summaries, widening


def model_files(cfg: dict, handed: bool, key: str = "model_config") -> dict:
    """Where the model `cfg[key]` names lives and its card checksum (None for a model handed in directly)."""
    if handed:
        return {"dir": None, "card_sha256": None}
    model_dir = hm.configured_model_dir(hm.hazard_config(project_path(cfg[key])))
    return {"dir": hm.display_path(model_dir), "card_sha256": sha256_file(model_dir / hm.CARD_FILE)}


def model_record(cfg: dict, handed: bool, key: str, model: hm.HazardModel, thresholds) -> dict:
    """run.json's record of one scoring model: its files, inputs, calibration and the thresholds its risk is compared with."""
    return {**model_files(cfg, handed, key), "n_columns": len(model.columns),
            "calibration": "per_region" if model.region_calibrator else "pooled",
            "thresholds": pooled_thresholds(thresholds).to_dict(),
            "thresholds_by_region": thresholds.to_dict() if isinstance(thresholds, lv.RegionThresholds) else None}


def run_day(day: date, cfg: dict, force: bool = False, backtest: bool = False, deps: LiveDeps | None = None) -> dict:
    """Run, publish and return the summary (also written as run.json). See the module doc."""
    deps = deps or LiveDeps()
    started = time.monotonic()
    now = (deps.now() if deps.now else datetime.now(UTC)).astimezone(UTC)
    live_dir = live_root(cfg)
    run_dir = live_dir / day.isoformat()
    summary_path = run_dir / "run.json"
    if summary_path.is_file() and not force:
        previous = json.loads(summary_path.read_text(encoding="utf-8"))
        if not previous.get("retry_recommended"):
            return {**previous, "skipped": True}
    model = deps.model or load_live_model({**cfg, "model_config": cfg[lead0_key(cfg)]})
    forecast_model = load_forecast_model(cfg, deps, model)
    alert_config = deps.alert_config or load_alert_config(project_path(cfg["alert_config"]))
    rules = load_post_rules(cfg, deps)
    if deps.cells is not None:
        cells = deps.cells.reset_index(drop=True)
        cell_set = deps.cell_set or {"assessed": int(len(cells)), "in_scope": None, "not_assessed": None,
                                     "slope_floor_deg": None, "definition": "cells handed to the run"}
    else:
        cells, cell_set = load_candidate_cells(cfg)
    thresholds = deps.thresholds or card_thresholds(model, cells["region"])
    split = forecast_model is not model
    forecast_thresholds = (deps.forecast_thresholds or card_thresholds(forecast_model, cells["region"])) if split else thresholds
    forecast_key = "model_config"
    lead0 = {"key": lead0_key(cfg) if split else "model_config", "handed": deps.model is not None}
    cells = cells.assign(date=pd.Timestamp(day))

    # ---- sources
    sources = deps.sources if deps.sources is not None else default_sources(cfg)
    statuses = fetch_all(day, cfg, sources=sources, now=now, backtest=backtest, raw_dir=run_dir / "raw")
    ctx = make_context(day, cfg, now, backtest, run_dir / "raw")

    def payload(name: str, empty):
        return sources[name].load(ctx) if name in statuses and statuses[name].usable and hasattr(sources.get(name), "load") else empty
    gfs = payload("gfs", None)
    ecmwf_forecast = payload("ecmwf", None)
    imd_grids = payload("imd_rt", {})
    gauges = payload("ghcn", None)
    runs = {name: sources[name] if isinstance(sources.get(name), ImergSource) and statuses[name].usable else None
            for name in ("imerg_late", "imerg_early")}
    view = LiveRainView(day, runs["imerg_late"], runs["imerg_early"], ctx, gfs.first_hours if gfs else None,
                        gfs.first_hours_product if gfs else PERSIST)
    inputs = view.imd_day_inputs()
    write_json_atomic(run_dir / "freshness.json", freshness_record(day, cfg, statuses, now, backtest, inputs))

    # ---- lead 0 features
    store_for_clim = (sources["imerg_late"].store if isinstance(sources.get("imerg_late"), ImergSource) else None)
    flat = F.cell_pixels(cells["cell_id"].to_numpy(dtype=np.int64))
    clim = deps.clim if deps.clim is not None else load_climatology(cfg, store_for_clim, flat)
    irain = F.build_imerg_features(cells[["cell_id", "date"]], view, clim)
    intensity = {"used": False, "reason": "the lead-0 model reads no rain-intensity input"}
    extras = []
    if uses_intensity(model):
        extra, intensity = intensity_inputs(day, cells, model, deps)
        extras.append(extra)
    ground, static = static_inputs(cells, model, deps)
    if static is not None:
        extras.append(ground)
    if any(extra is None for extra in extras):       # an input lead 0's own model needs is missing: the leads' model scores it
        why = next(s["reason"] for s in (intensity, static) if s and s.get("reason") and not s["used"])
        log.warning("lead 0 scored with the forecast-lead model: %s", why)
        model, thresholds, split = forecast_model, forecast_thresholds, False
        lead0 = {"key": forecast_key, "handed": deps.forecast_model is not None or deps.model is not None}
        intensity = {**intensity, "used": False, "fallback": "lead 0 scored with the forecast-lead model", "fallback_reason": why}
    else:
        irain = pd.concat([irain, *extras], axis=1)
    features = pd.concat([cells, irain], axis=1)

    # ---- integrity engine on the recent gauges
    integrity = {"ran": False, "reason": None, "n_stations_observed": None, "note": None}
    station_outputs, integ = None, None
    if not cfg["integrity"]["enabled"]:
        integrity["reason"] = "disabled in configs/live_run.yaml"
    elif gauges is None:
        integrity["reason"] = "GHCN-Daily gauges unavailable"
    else:
        runner = deps.integrity or adapter.LiveIntegrity(project_path(cfg["integrity"]["engine_dir"]), live_dir / "cache")
        try:
            outputs = adapter.station_outputs_with_causal_flags(runner(gauges, view, imd_grids))
            integ = adapter.integ_columns(outputs, gauges, features, features["irain_acc_1"])
            station_outputs = outputs
            integrity.update(ran=True, note=INTEGRITY_NOTE,
                             n_stations_observed=int(gauges.values.iloc[-1:].notna().any().sum()))
        except Exception as exc:
            integrity["reason"] = f"{type(exc).__name__}: {str(exc)[:200]}"
            log.warning("integrity engine did not run: %s", integrity["reason"])

    check_day, opinion = second_opinion(day, imd_grids, ctx.horizon, float(cfg["imd_rt"]["latency_h"]), alert_config)
    alert_input = adapter.alert_frame(features, adapter.imd_cell_series(imd_grids, cells["cell_id"], day,
                                                                          lon_offset_columns=imd_lon_offset(cfg)),
                                      adapter.imerg_cell_series(view, cells["cell_id"], day), integ,
                                      adapter.check_columns(imd_grids, view, cells["cell_id"], day, check_day,
                                                            imd_lon_offset(cfg)))

    # ---- score and alert (lead 0)
    unscorable = ~scorable_mask(alert_input, model.columns)
    scores = pd.DataFrame({"risk": 0.0, "risk_lo": 0.0, "risk_hi": 0.0, "risk_per_100k": 0.0}, index=alert_input.index)
    contributions: list[list[dict]] = [[] for _ in range(len(alert_input))]
    if (~unscorable).any():
        scorable_rows = alert_input[~unscorable]
        scored_rows = with_uncertain_bound(model.score(scorable_rows), model, scorable_rows, alert_config)
        for column in scored_rows.columns.difference(scores.columns):
            scores[column] = 0.0
        scores.loc[~unscorable, scored_rows.columns] = scored_rows
        for position, contribution in zip(np.flatnonzero(~unscorable), model.contributions(scorable_rows)):
            contributions[position] = contribution
    stations = gauges.meta if (gauges is not None and station_outputs is not None) else None
    engine_table = run_alerts(alert_input, scores, station_outputs, stations=stations, thresholds=thresholds,
                              config=alert_config, contributions=contributions, hysteresis=False)
    persisted_tail = inputs["D"]["utc_day_0.125"] == PERSIST
    if persisted_tail:
        engine_table = cap_to_degraded(engine_table, alert_config, CAUSE_NOWCAST_TAIL)
    engine_table = pr.apply_post_rules(alert_input, scores, engine_table, rules, thresholds, ~unscorable)
    history_days = int(cfg["hysteresis_history_days"])
    history = previous_state(live_dir, day, history_days)
    rain_history = pr.previous_rain_ok(live_dir, day, history_days, rules)
    scored_risk = engine_table.assign(risk=np.where(unscorable, np.nan, engine_table["risk"]))
    level = pr.live_hysteresis(scored_risk, history, rain_history, thresholds, alert_config, rules)
    alerts = pr.mark_blind_holds(finalize_alerts(engine_table, level, unscorable), unscorable)

    # ---- write lead 0
    run_dir.mkdir(parents=True, exist_ok=True)
    write_parquet_atomic(alert_input, run_dir / "features_D0.parquet")
    write_parquet_atomic(alerts, run_dir / "alerts.parquet")
    d0 = lead_table(day, 0, alert_input, alerts, alerts["level"].to_numpy(), alerts["confidence"].to_numpy(dtype=object),
                    alerts["confidence_causes"].tolist(), alerts["uncertain_high"].to_numpy(), False)
    write_parquet_atomic(d0, run_dir / "risk_D0.parquet")

    def d0_reasons(top: pd.DataFrame) -> list[list[str]]:
        return [_reason_texts(json.loads(text)) for text in top["shap_json"]]
    leads = {0: {"lead": 0, "date": day.isoformat(), "published": True, "reason": None, "file": "alerts.parquet",
                 "n_cells": int(len(alerts)), "n_scored": int((~unscorable).sum()), "levels": count_levels(alerts["level"]),
                 "confidence": count_confidence(alerts["confidence"]),
                 "confidence_causes": count_causes(alerts["confidence_causes"]),
                 "n_blind": int(alerts["blind"].sum()), "n_blind_escalated": int(alerts["blind_escalated"].sum()),
                 "post_rules": post_rule_counts(alerts["reason_codes"], alerts["confidence_causes"]),
                 "top_cells": top_cells(alerts, d0_reasons, int(cfg["top_cells"]))}}

    # ---- forecast leads
    choice, maps = load_choice_and_maps(cfg, deps)
    forecast_leads, widening = _forecast_leads(day, cfg, deps, forecast_model, forecast_thresholds, alert_config, cells, view, clim,
                                               forecast_products(gfs, ecmwf_forecast), choice, maps, statuses, alerts,
                                               ~unscorable, run_dir, rules)
    leads.update(forecast_leads)
    validity = season.season_record(day, cfg)
    for key, info in leads.items():
        info["outside_validated_season"] = validity["leads"][str(key)]

    # ---- summary, replay set, bulletin
    states = {name: source_state(status, day, cfg) for name, status in statuses.items()}
    gaps = [d.isoformat() for d in view.coverage_gaps()]
    retry = inputs["D"]["product"] == "missing"
    finished = now + timedelta(seconds=time.monotonic() - started)
    summary = {
        "schema": SCHEMA, "date": day.isoformat(), "backtest": backtest, "forced": force, "status": "complete",
        "started_utc": now.isoformat(timespec="seconds"), "finished_utc": finished.isoformat(timespec="seconds"),
        "seconds": round(time.monotonic() - started, 1), "run_time_local": now.astimezone(local_tz(cfg)).isoformat(timespec="minutes"),
        "retry_recommended": retry,
        "retry_reason": ("the rain of IMD day D could not be assembled (" + ", ".join(
            f"{k}: {v}" for k, v in inputs["D"].items() if k != "product") + ")") if retry else None,
        "model": model_record(cfg, lead0["handed"], lead0["key"], model, thresholds),
        **({"forecast_model": model_record(cfg, deps.forecast_model is not None or deps.model is not None, forecast_key,
                                           forecast_model, forecast_thresholds)} if split else {}),
        "intensity": intensity,
        **({"static": static} if static is not None else {}),
        "sources": {name: {**status.to_dict(), "state": states[name]} for name, status in statuses.items()},
        "failed_sources": [n for n in SOURCE_NAMES if states[n] == "failed"],
        "late_sources": [n for n in SOURCE_NAMES if states[n] == "late"],
        "cell_set": cell_set, "imd_day_inputs": inputs, "imerg_gaps": gaps, "second_opinion": opinion,
        "season_of_validity": validity,
        "nowcast_tail": {"product": inputs["D"]["utc_day_0.125"], "persisted": persisted_tail},
        "integrity": integrity, "forecast_widening": widening,
        "forecast_rain": {"choice": choice.to_dict(), "leads": {str(k): v["forecast"] for k, v in forecast_leads.items()
                                                                if v["published"]}},
        "post_rules": {"source": rules.source, "parameters": rules.to_dict()},
        "hysteresis": {"previous_days_used": int(history["date"].nunique()),
                       "first_previous": None if history.empty else history["date"].min().date().isoformat()},
        "leads": {str(k): v for k, v in sorted(leads.items())},
        "files": sorted(p.name for p in run_dir.iterdir() if p.is_file()) + ["run.json"],
        "notes": ["Alert-engine thresholds (source-disagreement range, heavy-rain amounts, station agreement) were derived "
                  "on the v2 development data (IMD final grid and CHIRPS), not on IMERG."]}
    sensors = adapter.day_sensor_table(station_outputs, gauges, alert_config, day) if station_outputs is not None else None
    entry = publish_replay_day(project_path(cfg["replay_dir"]), cfg["replay_set"], alerts,
                               {"source": "live runner", "thresholds": pooled_thresholds(thresholds).to_dict(),
                                **({"thresholds_by_region": thresholds.to_dict()}
                                   if isinstance(thresholds, lv.RegionThresholds) else {})},
                               sensors, None if sensors is not None else
                               f"No gauge table for {day.isoformat()}: {integrity['reason']}.")
    summary["replay"] = {"set": cfg["replay_set"], "dates": len(entry["dates"])}
    report_path = project_path(cfg["report_dir"]) / f"{day.isoformat()}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    top_ids = [c["cell_id"] for info in summary["leads"].values() if info["published"] for c in info["top_cells"]]
    places_table = cfg.get("places_table")
    places = bulletin.place_labels(project_path(places_table) if places_table else None, top_ids)
    summary["audit"] = audit_run(run_dir, rules, summary, project_path(cfg["report_dir"]) / "audit", cfg, model, alert_config,
                                 forecast_model if split else None)
    summary["bulletin"] = report_path.name
    report_path.write_text(bulletin.render(summary, places), encoding="utf-8")
    write_json_atomic(summary_path, summary)
    return summary


def post_rule_counts(codes, causes) -> dict:
    """How many published cells each post-model rule touched."""
    codes, causes = pd.Series(codes, dtype=object).fillna(""), pd.Series(causes, dtype=object).fillna("")
    return {pr.CODE_NO_RECENT_RAIN: int(codes.str.contains(pr.CODE_NO_RECENT_RAIN, regex=False).sum()),
            pr.CODE_HELD_WHILE_BLIND: int(codes.str.contains(pr.CODE_HELD_WHILE_BLIND, regex=False).sum()),
            pr.CAUSE_ENSEMBLE: int(causes.str.contains(pr.CAUSE_ENSEMBLE, regex=False).sum())}


def audit_run(run_dir: Path, rules: pr.PostRules, summary: dict, out_dir: Path, cfg: dict | None = None, model=None,
              alert_config: AlertConfig | None = None, forecast_model=None) -> dict:
    """Audit the rows the run just published (`live.audit`, with the integrity checks of spec section 13: the inputs `cfg`
    names, and the stored features scored again with `model`), write `<out_dir>/<D>.json` and return its totals for
    run.json; a violation is logged, never raised (the day stays published and the bulletin says so)."""
    context = (audit.context_from_config(cfg, rescore=True, model=model, alert_config=alert_config, forecast_model=forecast_model)
               if cfg is not None else None)
    result = audit.audit_day(run_dir, rules, summary, context)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json_atomic(out_dir / f"{summary['date']}.json", result)
    if result["total_violations"]:
        log.warning("audit of %s: %d violations %s", summary["date"], result["total_violations"],
                    {k: v for k, v in result["violations"].items() if v})
    return {"violations": result["violations"], "total_violations": result["total_violations"], "rows": result["rows"],
            "file": f"audit/{summary['date']}.json", "rescore_seconds": result.get("rescore", {}).get("seconds")}


# --------------------------------------------------------------------------------------------------------- CLI

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m aetherguard.live", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run one day")
    run.add_argument("--date", default="today", help="today (the IST date) or YYYY-MM-DD")
    run.add_argument("--force", action="store_true", help="recompute a day that is already complete")
    run.add_argument("--backtest", action="store_true", help="use only inputs issued before the data cut-off of the date")
    run.add_argument("--config", type=Path, default=None, help="configs/live_run.yaml")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        cfg = load_run_config(args.config)
        day = resolve_day(args.date, cfg)
        summary = run_day(day, cfg, force=args.force, backtest=args.backtest)
    except (LiveRunError, ValueError, OSError) as exc:
        print(str(exc) if isinstance(exc, LiveRunError) else f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    published = [k for k, v in summary["leads"].items() if v["published"]]
    print(f"{summary['date']}: {'skipped (already complete)' if summary.get('skipped') else 'published'}; "
          f"leads {','.join(published)}; failed sources: {', '.join(summary['failed_sources']) or 'none'}")
    return EXIT_RETRY if summary["retry_recommended"] and not summary.get("skipped") else 0


if __name__ == "__main__":
    raise SystemExit(main())
