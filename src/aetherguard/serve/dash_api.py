"""Dashboard API (prefix /api): compact typed-array payloads for the React app, read from the replay store and live runs.

  GET /api/mode                       live | replay | none, the set shown, its latest date and dates, the forecast leads
                                      each date can show, the alert thresholds of the model that scored it, and the next run
  GET /api/grid?date=&lead=&set=      all cells of a day and lead as base64 typed arrays (little-endian), with a flag
                                      byte per cell: 1 raised by the blind rule, 2 held by hysteresis, 4 gauges untrusted,
                                      8 capped by the rain trigger, 16 ensemble disagrees;
                                      a forecast lead also carries `certainty` (0 none, 1 firm, 2 depends on the rain
                                      forecast), `level_min` and `level_max` (one byte each) and `forecast`, the rain
                                      source behind it (label, licence attribution, fallback)
  GET /api/terrain                    domain elevation grid (float16), cached
  GET /api/basemap                    whole-India relief: elevation (float16), country mask (uint8) and the India, Nepal
                                      and Bhutan outlines on the 0.05 degree global grid, cached
  GET /api/places                     place name, district, state, country and distance of every labelled cell (string tables
                                      plus per-cell typed arrays), cached; 404 when python -m aetherguard.serve.places build
                                      has not run (the dashboard then shows coordinates)
  GET /api/rain?date=&set=            1-day rain of the cells scored that day, averaged onto a 0.25 degree grid, and the
                                      rain source(s) the day's alert rows name
  GET /api/sources/status             freshness.json of the newest live run
  GET /api/cells/{id}/history?days=&date=&set=   per-day risk, level and 1-day rain by source of one cell, its place, and the
                                      D+1..D+3 forecasts of the live run of the window's last day
  GET /api/stream                     Server-Sent Events: run, sources, heartbeat

A live run is `<live_dir>/<YYYY-MM-DD>/` holding `alerts.parquet` (lead 0), `risk_D{1..3}.parquet` (forecast leads),
`features_D0.parquet` and `freshness.json`. The live set is the replay-store set named `live` and/or those run directories.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import zipfile
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import date as Date, datetime, time as Time, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import yaml
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from ..alerts.store import ALERTS_DIR, ReplayStore, StoreError
from ..config import PROJECT_ROOT, data_root, load_config_file
from ..grid import CELL_DEG
from . import places as pl
from . import terrain_grid as tg
from .jsonsafe import NullNaNJSONResponse

LIVE_SET = "live"
DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"
LEADS = 3
GRID_LAT0, GRID_LON0 = -90.0, -180.0          # origin of the global cell grid: cell_id = lat_index * 10000 + lon_index
CONFIDENCE_CODES = {"High": 0, "Degraded": 1, "Insufficient": 2}
GRID_COLUMNS = ["cell_id", "risk", "risk_hi", "level", "confidence"]
FLAG_BLIND, FLAG_HELD, FLAG_UNTRUSTED = 1, 2, 4   # why a cell sits above its risk band (see grid_flags)
FLAG_CAPPED, FLAG_DISAGREE = 8, 16                 # why its risk is not to be trusted: rain-capped, ensemble disagrees
FLAG_COLUMNS = ("blind_escalated", "reason_codes", "confidence_causes")
CERTAINTY_COLUMNS = ("certainty", "level_min", "level_max")      # forecast leads of a run from section 12 on
CERTAINTY_CODES = {None: 0, "firm": 1, "depends_on_forecast": 2}
ECMWF_ATTRIBUTION = "Contains ECMWF open data (IFS), licensed CC BY 4.0"
RAIN_STEP = 0.25
RAIN_ROWS = round((tg.LAT1 - tg.LAT0) / RAIN_STEP)
RAIN_COLS = round((tg.LON1 - tg.LON0) / RAIN_STEP)
HISTORY_RAIN_COLUMNS = ("imd_acc_1", "chirps_acc_1", "station_trw_1")   # alert-table evidence: IMD, satellite, gauges
RAIN_COLUMNS = ("irain_acc_1", "rain_acc_1")   # IMERG-based when the table has it, else the frozen blend
BASEMAP_NPZ, BASEMAP_JSON = "india_basemap.npz", "india_basemap.json"   # written by python -m aetherguard.serve.basemap
BASEMAP_BUILD = "python -m aetherguard.serve.basemap build"
FRESHNESS_FILE = "freshness.json"
HEARTBEAT_SECONDS = 15.0

IST = timezone(timedelta(hours=5, minutes=30), "IST")  # Asia/Kolkata has no daylight saving, so a fixed offset is exact
DEFAULT_RUN_TIME = "11:00"
RUN_TIME_PATTERN = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", default_response_class=NullNaNJSONResponse)


@dataclass(frozen=True)
class DashConfig:
    live_dir: Path
    features_dir: Path
    terrain_source: Path
    terrain_cache: Path
    basemap_dir: Path
    places_dir: Path
    live_run_config: Path = PROJECT_ROOT / "configs" / "live_run.yaml"
    poll_interval: float = 1.0
    heartbeat_interval: float = HEARTBEAT_SECONDS

    @classmethod
    def default(cls, live_dir: Path | None = None, **fields) -> "DashConfig":
        return cls(live_dir=Path(live_dir or data_root() / "live"), features_dir=data_root() / "processed" / "features",
                   terrain_source=tg.default_source(), terrain_cache=tg.default_cache(),
                   basemap_dir=data_root() / "processed" / "basemap",
                   places_dir=data_root() / "processed" / "places", **fields)


# ---- stores and live runs -------------------------------------------------------------------------------------------

def _config(request: Request) -> DashConfig:
    return request.app.state.dash


def _store(request: Request) -> ReplayStore:
    store = request.app.state.store
    store.refresh()
    return store


def _day(text: str) -> str:
    try:
        return Date.fromisoformat(text).isoformat()
    except ValueError:
        raise HTTPException(422, f"{text!r} is not a valid date (YYYY-MM-DD)") from None


def _sets(store: ReplayStore) -> dict[str, dict]:
    """The manifest's sets that hold at least one day ({} when there is no readable store)."""
    if not store.available:
        return {}
    try:
        return {name: entry for name, entry in store.manifest["sets"].items() if entry["dates"]}
    except ValueError:
        return {}


def _run_dates(live_dir: Path, filename: str = "alerts.parquet") -> list[str]:
    """Dates of the live run directories holding `filename`, ascending."""
    if not live_dir.is_dir():
        return []
    found = []
    for child in live_dir.iterdir():
        try:
            Date.fromisoformat(child.name)
        except ValueError:
            continue
        if (child / filename).is_file():
            found.append(child.name)
    return sorted(found)


def resolve_mode(store: ReplayStore, live_dir: Path) -> dict:
    """Live when a `live` replay set or live run directory exists, else the replay set with the newest day, else none."""
    sets = _sets(store)
    live_dates = sorted(set(sets.get(LIVE_SET, {}).get("dates", [])) | set(_run_dates(live_dir)))
    if live_dates:
        return {"mode": "live", "set": LIVE_SET, "latest_date": live_dates[-1], "dates": live_dates}
    if sets:
        name = max(sets, key=lambda n: sets[n]["dates"][-1])      # max keeps the first of equals; ties go to build order
        dates = list(sets[name]["dates"])
        return {"mode": "replay", "set": name, "latest_date": dates[-1], "dates": dates}
    return {"mode": "none", "set": None, "latest_date": None, "dates": []}


def _alert_source(request: Request, day: str, set_name: str | None) -> tuple[str, Path]:
    """(set name, alert table path) answering `day`; a live run directory answers the unnamed and the `live` set."""
    store, config = _store(request), _config(request)
    run = config.live_dir / day / "alerts.parquet"
    if set_name in (None, LIVE_SET) and run.is_file():
        return LIVE_SET, run
    try:
        name = store.resolve_set(day, set_name)
    except StoreError as error:
        runs = _run_dates(config.live_dir)
        extra = f"; live runs available {runs[0]}..{runs[-1]} ({len(runs)} days)" if runs else ""
        raise HTTPException(404, scrub(f"{error}{extra}", store.root)) from None
    return name, store.root / name / ALERTS_DIR / f"{day}.parquet"


def _encode(values, dtype: str) -> str:
    return base64.b64encode(np.ascontiguousarray(values, dtype=dtype).tobytes()).decode("ascii")


def _number(value) -> float | None:
    value = float(value)
    return value if np.isfinite(value) else None


def display_path(path: Path) -> str:
    """`path` for a message the browser shows: relative to the project (`data/live`), else to the data root, else its
    bare name, so no absolute location of this machine leaves the API."""
    for root in (PROJECT_ROOT, data_root()):
        try:
            return path.relative_to(root).as_posix()
        except ValueError:
            continue
    return path.name


ABSOLUTE_PATH = re.compile(r"""(?<![\w/\\])(?:[A-Za-z]:[\\/]|/(?:home|Users|tmp|var|private|mnt)/)[^\s'"<>|]*""")


def scrub(message: str, *roots: Path) -> str:
    """`message` with every location of this machine shown relative: the project root, the data root and any extra
    `roots` (the replay store) by their display form, then any other absolute path by its last component."""
    for root in sorted({*roots, PROJECT_ROOT, data_root()}, key=lambda r: len(r.parts), reverse=True):
        shown = "" if root == PROJECT_ROOT else display_path(root)
        lead = f"{shown}/" if shown else ""
        for form in (str(root), root.as_posix()):
            for separator in ("\\", "/"):
                message = message.replace(form + separator, lead)
            message = message.replace(form, shown or ".")
    return ABSOLUTE_PATH.sub(lambda match: re.split(r"[\\/]", match.group().rstrip("\\/"))[-1], message)


# ---- mode, grid, history --------------------------------------------------------------------------------------------

def configured_run_time(path: Path) -> str:
    """`schedule.run_time` ("HH:MM", IST) of the live runner config; the default when the file or the key is absent
    or the value is not a valid time (the dashboard must keep working while the runner config is being written)."""
    try:
        value = load_config_file(path)["schedule"]["run_time"]
    except (OSError, KeyError, TypeError, ValueError, yaml.YAMLError):
        return DEFAULT_RUN_TIME
    if isinstance(value, str) and RUN_TIME_PATTERN.match(value.strip()):
        return value.strip()
    log.warning("%s: schedule.run_time %r is not HH:MM; using %s", path, value, DEFAULT_RUN_TIME)
    return DEFAULT_RUN_TIME


def next_run_after(now: datetime, run_time: str) -> str:
    """ISO datetime (+05:30) of the first daily run at `run_time` (HH:MM, IST) strictly after `now`."""
    hour, minute = (int(part) for part in run_time.split(":"))
    local = now.astimezone(IST)
    due = datetime.combine(local.date(), Time(hour, minute), tzinfo=IST)
    if due <= local:
        due += timedelta(days=1)
    return due.isoformat()


THRESHOLD_KEYS = ("watch", "warning", "emergency")


def _valid_thresholds(value) -> dict | None:
    """`{watch, warning, emergency, source}` when `value` holds the three finite positive risks, else None."""
    if not isinstance(value, dict):
        return None
    risks = [value.get(key) for key in THRESHOLD_KEYS]
    if not all(isinstance(r, (int, float)) and not isinstance(r, bool) and np.isfinite(r) and r > 0 for r in risks):
        return None
    return {**{key: float(value[key]) for key in THRESHOLD_KEYS}, "source": value.get("source")}


def served_thresholds(store: ReplayStore, live_dir: Path, shown: dict) -> dict | None:
    """The alert thresholds (calibrated risk) of the model behind the set `shown` by resolve_mode: a live set reads
    them from the newest live run's run.json (`model.thresholds`), anything else from the replay store manifest, which
    records the card the store was built with. None when neither holds usable thresholds."""
    if shown["mode"] == "none":
        return None
    if shown["set"] == LIVE_SET:
        runs = _run_dates(live_dir)
        if runs:
            try:
                summary = json.loads((live_dir / runs[-1] / "run.json").read_text(encoding="utf-8"))
                found = _valid_thresholds(summary["model"]["thresholds"])
            except (OSError, ValueError, KeyError, TypeError):
                found = None
            if found:
                return found
    try:
        return _valid_thresholds(store.manifest.get("thresholds"))
    except StoreError:
        return None


def available_leads(shown: dict, live_dir: Path) -> dict[str, list[int]]:
    """{date: forecast leads the grid can show} for the dates of `shown` (resolve_mode): lead 0 always, leads 1..3 where
    the live run directory of that date holds `risk_D<lead>.parquet`. Replay sets hold lead 0 only."""
    live = shown["set"] == LIVE_SET
    return {day: [0, *(lead for lead in range(1, LEADS + 1) if live and (live_dir / day / f"risk_D{lead}.parquet").is_file())]
            for day in shown["dates"]}


@router.get("/mode")
def mode(request: Request) -> dict:
    config = _config(request)
    store = _store(request)
    run_time = configured_run_time(config.live_run_config)
    shown = resolve_mode(store, config.live_dir)
    return {**shown, "leads": available_leads(shown, config.live_dir),
            "thresholds": served_thresholds(store, config.live_dir, shown),
            "next_run": next_run_after(datetime.now(IST), run_time)}


def grid_flags(frame: pd.DataFrame) -> np.ndarray:
    """One byte per row: FLAG_BLIND where the blind rule raised the level (`blind_escalated`), FLAG_HELD where hysteresis
    holds it above the risk band (reason code `hysteresis_hold`), FLAG_UNTRUSTED where the raise was for untrusted
    gauges (reason code `sensors_untrusted_heavy_rain`), FLAG_CAPPED where the rain trigger lowered the level (reason code
    `no_recent_rain`: the risk is then not the basis of the level), FLAG_DISAGREE where most ensemble members put the risk
    lower (confidence cause `ensemble_disagrees`). A table without those columns flags nothing."""
    flags = np.zeros(len(frame), dtype=np.uint8)
    if "blind_escalated" in frame:
        flags |= np.where(frame["blind_escalated"].fillna(False).to_numpy(dtype=bool), FLAG_BLIND, 0).astype(np.uint8)
    if "reason_codes" in frame:
        codes = frame["reason_codes"].fillna("").astype(str)
        flags |= np.where(codes.str.contains("hysteresis_hold", regex=False), FLAG_HELD, 0).astype(np.uint8)
        flags |= np.where(codes.str.contains("sensors_untrusted_heavy_rain", regex=False), FLAG_UNTRUSTED, 0).astype(np.uint8)
        flags |= np.where(codes.str.contains("no_recent_rain", regex=False), FLAG_CAPPED, 0).astype(np.uint8)
    if "confidence_causes" in frame:
        causes = frame["confidence_causes"].fillna("").astype(str)
        flags |= np.where(causes.str.contains("ensemble_disagrees", regex=False), FLAG_DISAGREE, 0).astype(np.uint8)
    return flags


@router.get("/grid")
def grid(request: Request, date: str = Query(pattern=DATE_PATTERN), lead: int = Query(0, ge=0, le=LEADS),
         set: str | None = None) -> dict:
    day = _day(date)
    name, path = _alert_source(request, day, set)
    if lead > 0:
        if name != LIVE_SET:
            raise HTTPException(404, f"replay set {name!r} holds lead 0 only (requested lead {lead})")
        path = _config(request).live_dir / day / f"risk_D{lead}.parquet"
        if not path.is_file():
            raise HTTPException(404, f"live run {day} has no lead-{lead} forecast ({path.name} not found)")
    try:
        present = pq.read_schema(path).names
        columns = [*GRID_COLUMNS, *(c for c in (*FLAG_COLUMNS, *CERTAINTY_COLUMNS) if c in present)]
        frame = pd.read_parquet(path, columns=columns).sort_values("cell_id", kind="stable")
    except (KeyError, ValueError, OSError) as error:
        raise HTTPException(500, scrub(f"{display_path(path)} cannot be read as a risk grid: {error}", path.parent)) from None
    codes = frame["confidence"].map(CONFIDENCE_CODES)
    if codes.isna().any():
        unknown = sorted(map(str, frame["confidence"][codes.isna()].unique()))
        raise HTTPException(500, f"{display_path(path)} has unknown confidence labels {unknown}")
    level = frame["level"].to_numpy()
    if level.size and (level.min() < 0 or level.max() > 3):
        raise HTTPException(500, f"{display_path(path)} has alert levels outside 0..3")
    body = {"date": day, "lead": lead, "set": name, "n": int(len(frame)),
            "cells": _encode(frame["cell_id"], "<u4"), "risk": _encode(frame["risk"], "<f4"),
            "level": _encode(level, "u1"), "confidence": _encode(codes, "u1"),
            "risk_hi": _encode(frame["risk_hi"], "<f4"), "flags": _encode(grid_flags(frame), "u1"), "lat0": GRID_LAT0, "lon0": GRID_LON0, "step": CELL_DEG}
    if lead > 0:
        body.update(certainty_arrays(frame))
        body["forecast"] = forecast_source(_config(request).live_dir, day, lead)
    return body


def certainty_arrays(frame: pd.DataFrame) -> dict:
    """The per-cell scenario certainty of a forecast lead as bytes: `certainty` (CERTAINTY_CODES), `level_min`, `level_max`;
    empty for a table written before section 12."""
    if not all(c in frame for c in CERTAINTY_COLUMNS):
        return {}
    kinds = frame["certainty"].map(lambda k: CERTAINTY_CODES.get(k if isinstance(k, str) else None))
    if kinds.isna().any():
        raise HTTPException(500, f"unknown certainty labels {sorted(map(str, frame['certainty'][kinds.isna()].unique()))}")
    return {"certainty": _encode(kinds, "u1"), "level_min": _encode(frame["level_min"], "u1"),
            "level_max": _encode(frame["level_max"], "u1")}


def run_summary(live_dir: Path, day: str) -> dict | None:
    """The run.json of a live run; None when the run has none or it cannot be read."""
    try:
        return json.loads((live_dir / day / "run.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def forecast_source(live_dir: Path, day: str, lead: int) -> dict | None:
    """The rain source behind forecast lead `lead` of the run of `day` ({source, label, mapped, fallback, cycle,
    attribution}); None for a run that did not record one (written before section 12: GFS)."""
    summary = run_summary(live_dir, day)
    info = ((summary or {}).get("leads", {}).get(str(lead)) or {}).get("forecast")
    if not isinstance(info, dict):
        return None
    return {**{k: info.get(k) for k in ("source", "label", "mapped", "fallback", "cycle")},
            "attribution": ECMWF_ATTRIBUTION if str(info.get("source", "")).startswith("ecmwf") else None}


def rain_rule_detail(live_dir: Path, day: str, lead: int, cell_id: int, rule: dict | None, level_name: str) -> dict | None:
    """The rain-trigger entry of a row (`passed`, `exempt`, `capped`) with the numbers behind a cap: the cell's rain over the
    rule's window, the rule's minimum, and the level the cap lowered to (`level_name`). The entry as it is when the run
    keeps no feature table or the rule."""
    if not isinstance(rule, dict) or not rule.get("capped"):
        return rule
    summary = run_summary(live_dir, day)
    minimum = (((summary or {}).get("post_rules") or {}).get("parameters") or {}).get("rain_minimum_mm") or {}
    features = live_dir / day / f"features_D{lead}.parquet"
    if not minimum or not features.is_file():
        return rule
    window, mm = next(iter(sorted(minimum.items(), key=lambda kv: int(kv[0]))))
    column = f"irain_acc_{int(window)}"
    try:
        row = _read_cell_row(features, cell_id, [column])
    except (KeyError, ValueError, OSError):
        return rule
    if row is None or column not in row.index:
        return rule
    return {**rule, "window_days": int(window), "rain_mm": _number(row[column]), "minimum_mm": float(mm),
            "capped_to": level_name}


def forecast_points(live_dir: Path, run_day: str, cell_id: int) -> list[dict]:
    """The D+1..D+3 forecasts of one cell in the live run of `run_day` (risk, interval, level, target day), for the
    leads that run published; empty for a day without a run or a cell the run did not score."""
    points = []
    for lead in range(1, LEADS + 1):
        path = live_dir / run_day / f"risk_D{lead}.parquet"
        if not path.is_file():
            continue
        try:
            row = _read_cell_row(path, cell_id, ["risk", "risk_lo", "risk_hi", "level"])
        except (KeyError, ValueError, OSError):
            continue
        if row is not None:
            points.append({"lead": lead, "target_date": (Date.fromisoformat(run_day) + timedelta(days=lead)).isoformat(),
                           "risk": _number(row["risk"]), "risk_lo": _number(row.get("risk_lo", np.nan)),
                           "risk_hi": _number(row["risk_hi"]), "level": int(row["level"])})
    return points


@router.get("/cells/{cell_id}/history")
def cell_history(request: Request, cell_id: int, days: int = Query(30, ge=1, le=366),
                 date: str | None = Query(None, pattern=DATE_PATTERN), set: str | None = None) -> dict:
    store, config = _store(request), _config(request)
    chosen = resolve_mode(store, config.live_dir)
    name = set or chosen["set"]
    if name is None:
        raise HTTPException(404, "no replay store and no live run; nothing to chart")
    if name == LIVE_SET:
        available = chosen["dates"] if chosen["mode"] == "live" else []
    else:
        try:
            available = store.dates(name)
        except StoreError as error:
            raise HTTPException(404, scrub(str(error), store.root)) from None
    if not available:
        raise HTTPException(404, f"set {name!r} holds no days")
    end = _day(date) if date else available[-1]
    first = (Date.fromisoformat(end) - timedelta(days=days - 1)).isoformat()
    rows = []
    for day in (d for d in available if first <= d <= end):
        _, path = _alert_source(request, day, name)
        present = pq.read_schema(path).names
        columns = ["cell_id", "risk", "level", *(c for c in HISTORY_RAIN_COLUMNS if c in present)]
        part = pd.read_parquet(path, columns=columns, filters=[("cell_id", "==", cell_id)])
        if len(part):
            rows.append((day, part.iloc[0]))
    if not rows:
        raise HTTPException(404, f"cell {cell_id} has no rows in set {name!r} between {first} and {end}")
    rain = {c: [_number(r[c]) if c in r.index else None for _, r in rows] for c in HISTORY_RAIN_COLUMNS}
    return {"cell_id": cell_id, "set": name, "days": days, "dates": [d for d, _ in rows],
            "risk": [_number(r["risk"]) for _, r in rows], "level": [int(r["level"]) for _, r in rows], "rain": rain,
            "place": place_of(config, cell_id), "issued_date": end,
            "forecast": forecast_points(config.live_dir, end, cell_id) if name == LIVE_SET else []}


# ---- forecast detail of one cell -------------------------------------------------------------------------------------

DETAIL_MISSING = "this run predates per-lead detail"
FORECAST_UNAVAILABLE = ("A forecast day has no gauge reading, IMD grid or satellite estimate yet, so those fields are "
                        "empty; the rain behind it is the {label} forecast.")
GFS_COLUMN = re.compile(r"^gfs_rain_d([1-3])$")
NO_TRUST = {"n_stations": 0, "n_trusted": 0, "n_flagged_7d": 0, "n_out_of_distribution": 0, "flagged_types": []}


def _json_or_none(text) -> dict | list | None:
    try:
        return json.loads(text) if isinstance(text, str) else None
    except ValueError:
        return None


def _read_cell_row(path: Path, cell_id: int, columns: list[str]) -> pd.Series | None:
    """The row of `cell_id` in the parquet `path` with the wanted `columns` that it has; None when there is no such row."""
    present = pq.read_schema(path).names
    wanted = ["cell_id", *(c for c in columns if c in present)]
    part = pd.read_parquet(path, columns=wanted, filters=[("cell_id", "==", cell_id)])
    return part.iloc[0] if len(part) else None


def forecast_cell(config: DashConfig, cell_id: int, day: str, lead: int) -> dict:
    """The explanation of one cell for forecast lead `lead` (1..3) of the live run of `day`, shaped like the lead-0
    explanation (`schemas.CellExplanation` fields). A run written before the per-lead detail has the risk row but no
    input contributions or forecast rain: that is returned with `detail_missing`, never as an error."""
    run = config.live_dir / day
    path = run / f"risk_D{lead}.parquet"
    if not path.is_file():
        raise HTTPException(404, f"live run {day} has no lead-{lead} forecast ({path.name} not found)")
    try:
        row = _read_cell_row(path, cell_id, ["date", "lat", "lon", "region", "risk", "risk_lo", "risk_hi", "risk_per_100k",
                                             "level", "level_name", "confidence", "confidence_causes", "widened",
                                             "shap_json", "reasons_json", *CERTAINTY_COLUMNS])
    except (KeyError, ValueError, OSError) as error:
        raise HTTPException(500, scrub(f"{display_path(path)} cannot be read as a forecast: {error}", path.parent)) from None
    if row is None:
        raise HTTPException(404, f"cell {cell_id} has no D+{lead} forecast in the live run {day}")
    reasons = _json_or_none(row.get("reasons_json"))
    shap = _json_or_none(row.get("shap_json"))
    features = run / f"features_D{lead}.parquet"
    gfs_row = None
    if features.is_file():
        try:
            gfs_row = _read_cell_row(features, cell_id, [c for c in pq.read_schema(features).names if GFS_COLUMN.match(c)])
        except (KeyError, ValueError, OSError):
            gfs_row = None
    complete = isinstance(reasons, dict) and isinstance(shap, list) and gfs_row is not None
    forecast_days = []
    if gfs_row is not None:
        for name in sorted(c for c in gfs_row.index if GFS_COLUMN.match(c)):
            step = int(name[-1])
            forecast_days.append({"date": (Date.fromisoformat(day) + timedelta(days=step)).isoformat(), "lead": step,
                                  "mm": _number(gfs_row[name])})
    observed = {}
    try:
        today = _read_cell_row(run / "alerts.parquet", cell_id, ["reasons_json"])
        observed = (_json_or_none(today["reasons_json"]) or {}).get("sources", {}) if today is not None else {}
    except (KeyError, ValueError, OSError):
        observed = {}
    reasons = reasons if isinstance(reasons, dict) else {}
    source = forecast_source(config.live_dir, day, lead)
    causes = row.get("confidence_causes")
    return {
        "cell_id": cell_id, "date": day, "set": LIVE_SET, "lat": float(row["lat"]), "lon": float(row["lon"]),
        "region": None if pd.isna(row.get("region")) else str(row["region"]), "level": int(row["level"]),
        "level_name": str(row["level_name"]), "raw_level": str(row["level_name"]), "confidence": str(row["confidence"]),
        "confidence_causes": [c for c in causes.split(";") if c] if isinstance(causes, str) else [],
        "reason_codes": reasons.get("codes", []),
        "risk": _number(row["risk"]), "risk_lo": _number(row["risk_lo"]), "risk_hi": _number(row["risk_hi"]),
        "risk_per_100k": _number(row["risk_per_100k"]),
        "shap": [f for f in shap if isinstance(f, dict)] if isinstance(shap, list) else [],
        "sources": reasons.get("sources", {}), "sensor_trust": reasons.get("sensor_trust", NO_TRUST),
        "lead": lead, "issued_date": day, "target_date": (Date.fromisoformat(day) + timedelta(days=lead)).isoformat(),
        "forecast": True, "widened": bool(row["widened"]) if "widened" in row.index and pd.notna(row["widened"]) else None,
        "rain": {"unit": "mm/day", "observed_date": day if observed else None, "observed": observed,
                 "forecast": forecast_days},
        "unavailable": FORECAST_UNAVAILABLE.format(label=(source or {}).get("label") or "GFS"), "detail_missing": None if complete else DETAIL_MISSING,
        "ensemble": reasons.get("ensemble"),
        "rain_rule": rain_rule_detail(config.live_dir, day, lead, cell_id, reasons.get("rain_rule"), str(row["level_name"])),
        "certainty": row["certainty"] if isinstance(row.get("certainty"), str) else None,
        "level_min": int(row["level_min"]) if "level_min" in row.index and pd.notna(row["level_min"]) else None,
        "level_max": int(row["level_max"]) if "level_max" in row.index and pd.notna(row["level_max"]) else None,
        "forecast_source": source,
    }


# ---- place names ----------------------------------------------------------------------------------------------------

PLACES_BUILD = "python -m aetherguard.serve.places build"


def _file_stamp(path: Path) -> tuple[int, int]:
    info = path.stat()
    return info.st_mtime_ns, info.st_size


@lru_cache(maxsize=2)
def _places_table(path: str, stamp: tuple[int, int]) -> pd.DataFrame:
    return pl.read_table(Path(path)).set_index("cell_id", drop=False)


def _unique_index(values: pd.Series, reserve_empty: bool) -> tuple[list[str], np.ndarray]:
    """(names, index per value): the distinct names (an empty first one when `reserve_empty`, index 0 = missing)."""
    text = values.astype(object).where(values.notna(), "")
    names = sorted(set(text) - {""})
    lookup = {name: i + (1 if reserve_empty else 0) for i, name in enumerate(names)}
    return ([""] if reserve_empty else []) + names, text.map(lambda name: lookup.get(name, 0)).to_numpy()


@lru_cache(maxsize=2)
def _places_payload(path: str, stamp: tuple[int, int]) -> dict:
    table = _places_table(path, stamp)
    places, place = _unique_index(table["place"], reserve_empty=False)
    districts, district = _unique_index(table["district"], reserve_empty=True)
    states, state = _unique_index(table["state"], reserve_empty=True)
    countries, country = _unique_index(table["country"], reserve_empty=True)
    return {"attribution": pl.ATTRIBUTION, "n": int(len(table)), "far_km": pl.FAR_KM, "places": places,
            "districts": districts, "states": states, "countries": countries,
            "cells": _encode(table["cell_id"], "<u4"), "place": _encode(place, "<u4"), "district": _encode(district, "<u2"),
            "state": _encode(state, "<u2"), "country": _encode(country, "u1"),
            "distance_km": _encode(np.minimum(table["distance_km"], 65535), "<u2")}


def _places_file(request_config: DashConfig) -> tuple[str, tuple[int, int]] | None:
    path = request_config.places_dir / pl.TABLE_NAME
    try:
        return str(path), _file_stamp(path)
    except OSError:
        return None


@router.get("/places")
def places(request: Request) -> dict:
    """Place names for the dashboard. A missing or unreadable table is a 404, never a 500: the dashboard falls back to
    coordinates."""
    config = _config(request)
    found = _places_file(config)
    if found is None:
        raise HTTPException(404, f"no place names at {display_path(config.places_dir)}; build them ({PLACES_BUILD})")
    try:
        return _places_payload(*found)
    except (pl.PlacesError, OSError, ValueError, KeyError, TypeError) as error:
        raise HTTPException(404, scrub(f"the place names in {display_path(config.places_dir)} cannot be read ({error}); "
                                       f"rebuild them ({PLACES_BUILD})", config.places_dir)) from None


def place_of(config: DashConfig, cell_id: int) -> dict | None:
    """The label of one cell (`serve.places.place_record`), or None when there is no table, no row or it cannot be read."""
    found = _places_file(config)
    if found is None:
        return None
    try:
        table = _places_table(*found)
        return pl.place_record(table.loc[int(cell_id)]) if int(cell_id) in table.index else None
    except (pl.PlacesError, OSError, ValueError, KeyError, TypeError) as error:
        log.warning("place names unreadable: %s", error)
        return None


# ---- terrain and rain -----------------------------------------------------------------------------------------------

@lru_cache(maxsize=2)
def _terrain_payload(source: str, cache: str, stamp: tuple[int, int]) -> dict:
    elev = tg.load_terrain_grid(Path(source), Path(cache))
    return {"rows": tg.ROWS, "cols": tg.COLS, "lat0": tg.LAT0, "lon0": tg.LON0, "step": CELL_DEG,
            "elev": _encode(elev, "<f2")}


@router.get("/terrain")
def terrain(request: Request) -> dict:
    config = _config(request)
    try:
        stamp = tg.source_stamp(config.terrain_source)
    except OSError:
        raise HTTPException(404, f"no terrain table at {display_path(config.terrain_source)}; build it "
                                 "(python -m aetherguard.ingest.terrain_build)") from None
    return _terrain_payload(str(config.terrain_source), str(config.terrain_cache), stamp)


@lru_cache(maxsize=2)
def _basemap_payload(npz: str, meta: str, stamp: tuple) -> dict:
    with open(npz, "rb") as handle, np.load(handle) as stored:   # our own handle: a damaged file must not leak one
        elev, mask = stored["elev"], stored["mask"]
        lat0, lon0, step = (float(stored[key]) for key in ("lat0", "lon0", "step"))
    if elev.ndim != 2 or mask.shape != elev.shape:
        raise ValueError(f"elevation {elev.shape} and mask {mask.shape} are not the same 2-D grid")
    outline = json.loads(Path(meta).read_text(encoding="utf-8"))["outline"]
    rows, cols = elev.shape
    return {"rows": rows, "cols": cols, "lat0": lat0, "lon0": lon0, "step": step,
            "elev": _encode(elev, "<f2"), "mask": _encode(mask, "u1"), "outline": outline}


@router.get("/basemap")
def basemap(request: Request) -> dict:
    """The whole-India relief the 3D map is drawn on. Row 0 is the southernmost row (latitude `lat0`) and column 0 the
    westernmost (longitude `lon0`) on the global grid, so a cell's id is `(lat_index0 + row) * 10000 + lon_index0 + col`
    as for `/api/grid`. `mask` is 0 sea, 1 India, 2 Nepal, 3 Bhutan, 4 other land; `outline` holds closed [lon, lat] rings."""
    directory = _config(request).basemap_dir
    npz, meta = directory / BASEMAP_NPZ, directory / BASEMAP_JSON
    try:
        stamp = tuple(value for path in (npz, meta) for value in (path.stat().st_mtime_ns, path.stat().st_size))
    except OSError:
        raise HTTPException(404, f"no base map at {display_path(directory)}; build it ({BASEMAP_BUILD})") from None
    try:
        return _basemap_payload(str(npz), str(meta), stamp)
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as error:   # JSONDecodeError is a ValueError
        raise HTTPException(500, scrub(f"the base map in {display_path(directory)} cannot be read ({error}); "
                                       f"rebuild it ({BASEMAP_BUILD})", directory)) from None


def coarse_rain(lat, lon, rain) -> np.ndarray:
    """Mean of `rain` per 0.25 degree bin of the domain box, float32 (RAIN_ROWS, RAIN_COLS), NaN where no cell fell."""
    lat, lon, rain = (np.asarray(a, dtype=np.float64) for a in (lat, lon, rain))
    row = np.floor((lat - tg.LAT0) / RAIN_STEP).astype(np.int64)
    col = np.floor((lon - tg.LON0) / RAIN_STEP).astype(np.int64)
    keep = (row >= 0) & (row < RAIN_ROWS) & (col >= 0) & (col < RAIN_COLS) & np.isfinite(rain)
    total, count = np.zeros((RAIN_ROWS, RAIN_COLS)), np.zeros((RAIN_ROWS, RAIN_COLS))
    np.add.at(total, (row[keep], col[keep]), rain[keep])
    np.add.at(count, (row[keep], col[keep]), 1.0)
    return np.where(count > 0, total / np.maximum(count, 1.0), np.nan).astype(np.float32)


def _rain_sources(alert_path: Path) -> list[str]:
    """Distinct `rain_source` values of an alert table (`imd`, `chirps_aligned`, `imerg`, ...), most frequent first;
    empty when the table has no such column."""
    if "rain_source" not in pq.read_schema(alert_path).names:
        return []
    counts = pd.read_parquet(alert_path, columns=["rain_source"])["rain_source"].dropna().value_counts()
    return [str(name) for name in counts.index]


@router.get("/rain")
def rain(request: Request, date: str = Query(pattern=DATE_PATTERN), set: str | None = None) -> dict:
    day = _day(date)
    name, alert_path = _alert_source(request, day, set)
    config = _config(request)
    path = (config.live_dir / day / "features_D0.parquet" if name == LIVE_SET
            else config.features_dir / f"{name}_features.parquet")
    if not path.is_file():
        raise HTTPException(404, f"no feature table for {day} in set {name!r} ({display_path(path)} not found)")
    names = pq.read_schema(path).names
    column = next((c for c in RAIN_COLUMNS if c in names), None)
    if column is None:
        raise HTTPException(404, f"{path.name} has none of the rain columns {list(RAIN_COLUMNS)}")
    dated = "date" in names
    frame = pd.read_parquet(path, columns=["lat", "lon", column], filters=[("date", "==", pd.Timestamp(day))] if dated
                            else None)
    if frame.empty:
        raise HTTPException(404, f"{path.name} holds no rows for {day}")
    field = coarse_rain(frame["lat"], frame["lon"], frame[column])
    return {"date": day, "set": name, "column": column, "unit": "mm/day", "n_cells": int(len(frame)),
            "rain_sources": _rain_sources(alert_path), "rows": RAIN_ROWS, "cols": RAIN_COLS, "lat0": tg.LAT0, "lon0": tg.LON0, "step": RAIN_STEP,
            "rain": _encode(field, "<f4")}


# ---- sources and stream ---------------------------------------------------------------------------------------------

def _newest_freshness(live_dir: Path) -> Path | None:
    dates = _run_dates(live_dir, FRESHNESS_FILE)
    return live_dir / dates[-1] / FRESHNESS_FILE if dates else None


def sources_status(live_dir: Path) -> dict:
    path = _newest_freshness(live_dir)
    if path is None:
        return {"available": False, "reason": f"no live run yet (no {FRESHNESS_FILE} under {display_path(live_dir)})"}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        return {"available": False,
                "reason": f"{display_path(path)} is unreadable: {error.strerror or type(error).__name__}"}
    except ValueError as error:
        return {"available": False, "reason": f"{display_path(path)} is unreadable: {error}"}


@router.get("/sources/status")
def sources(request: Request) -> dict:
    return sources_status(_config(request).live_dir)


def _stamp(path: Path | None) -> tuple[str, int, int] | None:
    try:
        info = path.stat() if path is not None else None
    except OSError:
        return None
    return None if info is None else (str(path), info.st_mtime_ns, info.st_size)


def _snapshot(store: ReplayStore, live_dir: Path) -> tuple[tuple, tuple, tuple | None]:
    """(run files, store manifest, freshness file) identities; any change between two snapshots is an event."""
    store.refresh()
    runs = tuple(_stamp(live_dir / d / "alerts.parquet") for d in _run_dates(live_dir))
    return runs, _stamp(store.root / "store_manifest.json"), _stamp(_newest_freshness(live_dir))


def _event(name: str, data: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(data)}\n\n"


async def event_stream(store: ReplayStore, config: DashConfig) -> AsyncIterator[str]:
    """SSE text: a heartbeat on connect and every `heartbeat_interval`, `run` when a run file or the store manifest
    changes, `sources` when the newest freshness.json changes. Ends when the client disconnects (cancellation)."""
    clock = asyncio.get_running_loop().time
    seen, last_beat = _snapshot(store, config.live_dir), clock()
    yield _event("heartbeat", {"time": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    while True:
        await asyncio.sleep(config.poll_interval)
        now = _snapshot(store, config.live_dir)
        if now[:2] != seen[:2]:
            trigger = "live_run" if now[0] != seen[0] else "replay_store"
            yield _event("run", {"trigger": trigger, **resolve_mode(store, config.live_dir)})
        if now[2] != seen[2]:
            yield _event("sources", sources_status(config.live_dir))
        seen = now
        if clock() - last_beat >= config.heartbeat_interval:
            last_beat = clock()
            yield _event("heartbeat", {"time": datetime.now(timezone.utc).isoformat(timespec="seconds")})


@router.get("/stream")
async def stream(request: Request) -> StreamingResponse:
    return StreamingResponse(event_stream(_store(request), _config(request)), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
