"""AetherGuard read-only API over the replay store (replay data only; no live inputs, no secrets, local only).

    python -m aetherguard.serve.api [--port 8000]        # binds 127.0.0.1 only
    uvicorn aetherguard.serve.api:app --host 127.0.0.1

The replay store is `AETHERGUARD_REPLAY_DIR` (default data/processed/alerts/replay). Endpoints:
  GET /health                       versions, model card hash, freeze status, replay store status
  GET /risk?date=&region=&bbox=     cells of one day with risk, level, confidence (bbox = min_lon,min_lat,max_lon,max_lat)
  GET /risk/cell/{cell_id}?date=&lead=  full explanation: reasons, SHAP top 5, sources, sensor trust, interval; lead 1..3 is the
                                    forecast of the live run of `date` (ECMWF or GFS rain, no gauges), lead 0 (default) the day itself
  GET /sensors?date=&bbox=          station trust, fault type, genuine_extreme, reasons, out-of-distribution state; a day of
                                    a set without a gauge table answers 200 with no stations and a `reason`
  GET /alerts?start=&end=&min_level=  alert list with reasons
Every data endpoint takes an optional `set` (a replay set); without it the first set holding the date answers.
The dashboard API lives under /api (see dash_api); when dashboard/dist is built it is served at / (single-page app).
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import platform
from datetime import date as Date
from pathlib import Path

import pandas as pd
import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.staticfiles import StaticFiles

from .. import __version__
from ..alerts import levels as lv
from ..alerts.store import LIST_COLUMNS, NoSensorsError, ReplayStore, StoreError, default_store_dir
from ..config import PROJECT_ROOT
from ..hazard.freeze import FROZEN_NAME, FrozenMismatchError, verify_freeze
from . import dash_api
from . import schemas as sc
from .jsonsafe import NullNaNJSONResponse

HOST = "127.0.0.1"
DEFAULT_PORT = 8000
STORE_ENV = "AETHERGUARD_REPLAY_DIR"
MAX_CELLS = 50_000
DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"
DIST_DIR = PROJECT_ROOT / "dashboard" / "dist"
PACKAGES = ("fastapi", "pydantic", "uvicorn", "pandas", "pyarrow", "lightgbm")


def _number(value) -> float | None:
    if value is None:
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _text(value) -> str | None:
    return None if value is None or (isinstance(value, float) and math.isnan(value)) else str(value)


def _codes(text) -> list[str]:
    return text.split(";") if isinstance(text, str) and text else []


def _day(text: str) -> str:
    try:
        return Date.fromisoformat(text).isoformat()
    except ValueError:
        raise HTTPException(422, f"{text!r} is not a valid date (YYYY-MM-DD)") from None


def _bbox(text: str | None) -> tuple[float, float, float, float] | None:
    if text is None:
        return None
    try:
        min_lon, min_lat, max_lon, max_lat = (float(part) for part in text.split(","))
    except ValueError:
        raise HTTPException(422, "bbox must be four comma-separated numbers: min_lon,min_lat,max_lon,max_lat") from None
    if not (-180 <= min_lon < max_lon <= 180 and -90 <= min_lat < max_lat <= 90):
        raise HTTPException(422, "bbox must satisfy -180 <= min_lon < max_lon <= 180 and -90 <= min_lat < max_lat <= 90")
    return min_lon, min_lat, max_lon, max_lat


def _in_box(frame: pd.DataFrame, box) -> pd.DataFrame:
    if box is None:
        return frame
    min_lon, min_lat, max_lon, max_lat = box
    return frame[frame["lon"].between(min_lon, max_lon) & frame["lat"].between(min_lat, max_lat)]


def _thresholds(manifest: dict) -> sc.ThresholdsOut | None:
    t = manifest.get("thresholds")
    return sc.ThresholdsOut(**{k: t[k] for k in ("watch", "warning", "emergency", "source")}) if t else None


def _run_thresholds(thresholds: dict | None) -> sc.ThresholdsOut | None:
    return sc.ThresholdsOut(**{**thresholds, "source": thresholds["source"] or "unknown"}) if thresholds else None


def _shap(text: str) -> list[sc.ShapFactor]:
    return [sc.ShapFactor(feature=f["feature"], value=f["value"], contribution=f["contribution"])
            for f in json.loads(text)]


def _live_card_sha256() -> str | None:
    from ..hazard import model as hm
    path = hm.default_model_dir() / hm.CARD_FILE
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _freeze_status() -> tuple[str, str | None, str | None]:
    """(status, frozen_utc, detail) of the live hazard model against its FROZEN.json."""
    from ..hazard import model as hm
    if not (hm.default_model_dir() / FROZEN_NAME).is_file():
        return "not_frozen", None, f"{FROZEN_NAME} not found"
    try:
        return "verified", verify_freeze().get("created_utc"), None
    except FrozenMismatchError as error:
        return "mismatch", None, str(error)


def _package_versions() -> dict[str, str]:
    out = {}
    for name in PACKAGES:
        try:
            out[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            out[name] = "not installed"
    return out


def _store_error(error: StoreError, store: ReplayStore) -> HTTPException:
    return HTTPException(404, dash_api.scrub(str(error), store.root))


class SinglePageApp(StaticFiles):
    """The built dashboard: unknown paths answer index.html so client-side routes load, except /api and missing files."""

    async def get_response(self, path, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as error:
            parts = path.replace("\\", "/").split("/")             # StaticFiles hands over an OS-normalised path
            if error.status_code != 404 or parts[0] == "api" or "." in parts[-1]:
                raise
            return await super().get_response("index.html", scope)


def create_app(store_dir: Path | None = None, *, live_dir: Path | None = None, dist_dir: Path | None = None,
               poll_interval: float = 1.0, heartbeat_interval: float = dash_api.HEARTBEAT_SECONDS) -> FastAPI:
    """The app reading the replay store at `store_dir` (default: $AETHERGUARD_REPLAY_DIR or the standard location) and the
    live runs under `live_dir` (default data/live). `dist_dir` (default dashboard/dist) is served at / when it holds an
    index.html; `poll_interval` and `heartbeat_interval` pace the /api/stream events."""
    app = FastAPI(title="AetherGuard API", version=__version__,
                  description="Read-only replay API of the AetherGuard prototype. Not for issuing real warnings.",
                  default_response_class=NullNaNJSONResponse)
    app.state.store = ReplayStore(Path(store_dir or os.environ.get(STORE_ENV) or default_store_dir()))
    app.state.dash = dash_api.DashConfig.default(live_dir, poll_interval=poll_interval,
                                                 heartbeat_interval=heartbeat_interval)
    app.include_router(dash_api.router)

    def store_of(request: Request) -> ReplayStore:
        return request.app.state.store

    @app.get("/health", response_model=sc.Health)
    def health(request: Request) -> sc.Health:
        store = store_of(request)
        status = store.status()
        manifest = store.manifest if store.available else {}
        card_hash = (manifest.get("model") or {}).get("card_sha256")
        live = _live_card_sha256()
        freeze, frozen_utc, freeze_detail = _freeze_status()
        sets = {name: sc.StoreSet(first_date=e["dates"][0], last_date=e["dates"][-1], n_days=len(e["dates"]),
                                  n_rows=e["n_rows"]) for name, e in manifest.get("sets", {}).items()}
        return sc.Health(status="ok" if status == "ok" and freeze == "verified" else "degraded", aetherguard_version=__version__,
                         python=platform.python_version(), packages=_package_versions(), model_card_sha256=card_hash,
                         live_model_card_sha256=live,
                         model_card_matches_store=None if card_hash is None or live is None else card_hash == live,
                         model_freeze_status=freeze, model_frozen_utc=frozen_utc, model_freeze_detail=freeze_detail,
                         data_manifest_status=status, replay_store=dash_api.display_path(store.root),
                         provisional=manifest.get("provisional"), thresholds=_thresholds(manifest), sets=sets)

    @app.get("/risk", response_model=sc.RiskResponse)
    def risk(request: Request, date: str = Query(pattern=DATE_PATTERN), region: str | None = None,
             bbox: str | None = None, set: str | None = None, min_level: str = "Normal",
             limit: int = Query(MAX_CELLS, ge=1, le=MAX_CELLS)) -> sc.RiskResponse:
        store, box = store_of(request), _bbox(bbox)
        try:
            level = lv.parse_level(min_level)
        except ValueError as error:
            raise HTTPException(422, str(error)) from None
        try:
            name, frame = store.alerts(_day(date), set, columns=LIST_COLUMNS)
        except StoreError as error:
            raise _store_error(error, store) from None
        frame = _in_box(frame, box)
        if region is not None:
            frame = frame[frame["region"] == region]
        frame = frame[frame["level"] >= level].sort_values("risk", ascending=False, kind="stable")
        counts = {n: int((frame["level"] == k).sum()) for k, n in enumerate(lv.LEVEL_NAMES)}
        cells = [sc.RiskCell(cell_id=int(r.cell_id), lat=r.lat, lon=r.lon, region=_text(r.region), risk=r.risk,
                             risk_per_100k=r.risk_per_100k, level=int(r.level), level_name=r.level_name,
                             confidence=r.confidence, blind=bool(r.blind), uncertain_high=bool(r.uncertain_high),
                             reason_codes=_codes(r.reason_codes)) for r in frame.head(limit).itertuples()]
        return sc.RiskResponse(date=_day(date), set=name, thresholds=_thresholds(store.manifest),
                               provisional=store.manifest.get("provisional"), n_cells=int(len(frame)),
                               level_counts=counts, cells=cells)

    @app.get("/risk/cell/{cell_id}", response_model=sc.CellExplanation)
    def risk_cell(request: Request, cell_id: int, date: str = Query(pattern=DATE_PATTERN),
                  set: str | None = None, lead: int = Query(0, ge=0, le=dash_api.LEADS)) -> sc.CellExplanation:
        store = store_of(request)
        config = request.app.state.dash
        if lead > 0:
            if set not in (None, dash_api.LIVE_SET):
                raise HTTPException(404, f"replay set {set!r} holds lead 0 only (requested lead {lead})")
            store.refresh()
            shown = {"mode": "live", "set": dash_api.LIVE_SET}
            body = dash_api.forecast_cell(config, cell_id, _day(date), lead)
            thresholds, scope = dash_api.cell_thresholds(config.live_dir, _day(date), body["region"], lead)
            if thresholds is None:
                thresholds = dash_api.served_thresholds(store, config.live_dir, shown)
            return sc.CellExplanation(
                **body, thresholds=_run_thresholds(thresholds), thresholds_region=scope,
                provisional=store.manifest.get("provisional") if store.available else None,
                place=dash_api.place_of(config, cell_id))
        try:
            name, row = store.cell(cell_id, _day(date), set)
        except StoreError as error:
            raise _store_error(error, store) from None
        reasons = json.loads(row["reasons_json"])
        region = _text(row.get("region"))
        run_thresholds, scope = dash_api.cell_thresholds(config.live_dir, _day(date), region) if name == dash_api.LIVE_SET else (None, None)
        return sc.CellExplanation(
            cell_id=int(row["cell_id"]), date=_day(date), set=name, lat=row["lat"], lon=row["lon"],
            region=region, level=int(row["level"]), level_name=row["level_name"],
            raw_level=reasons["raw_level"], confidence=row["confidence"],
            confidence_causes=reasons["confidence"]["causes"], reason_codes=_codes(row["reason_codes"]),
            risk=row["risk"], risk_lo=row["risk_lo"], risk_hi=row["risk_hi"], risk_per_100k=row["risk_per_100k"],
            thresholds=_run_thresholds(run_thresholds) or _thresholds(store.manifest), thresholds_region=scope if run_thresholds else None,
            provisional=store.manifest.get("provisional"),
            shap=_shap(row["shap_json"]), sources=reasons["sources"], sensor_trust=reasons["sensor_trust"],
            lead=0, issued_date=_day(date), target_date=_day(date),
            place=dash_api.place_of(config, int(row["cell_id"])),
            ensemble=reasons.get("ensemble"),
            rain_rule=dash_api.rain_rule_detail(config.live_dir, _day(date), 0, int(row["cell_id"]), reasons.get("rain_rule"),
                                                reasons["raw_level"]) if name == dash_api.LIVE_SET else reasons.get("rain_rule"))

    @app.get("/sensors", response_model=sc.SensorsResponse)
    def sensors(request: Request, date: str = Query(pattern=DATE_PATTERN), bbox: str | None = None,
                set: str | None = None) -> sc.SensorsResponse:
        store, box = store_of(request), _bbox(bbox)
        try:
            name, frame = store.sensors(_day(date), set)
        except NoSensorsError as error:                           # the day exists; the answer is "no gauges, and why"
            return sc.SensorsResponse(date=_day(date), set=error.set_name, n_stations=0, state_counts={}, stations=[],
                                      reason=dash_api.scrub(str(error), store.root))
        except StoreError as error:
            raise _store_error(error, store) from None
        frame = _in_box(frame, box)
        rows = [sc.SensorRow(station=r.station, name=_text(r.name), lat=r.lat, lon=r.lon, trust=_number(r.trust),
                             fault_type=r.fault_type, flagged=bool(r.flagged), genuine_extreme=bool(r.genuine_extreme),
                             reasons=r.reasons, state=r.state, flag_rate_window=_number(r.flag_rate_window),
                             ood=bool(r.ood), last_reading=_text(getattr(r, "last_reading", None)))
                for r in frame.itertuples()]
        return sc.SensorsResponse(date=_day(date), set=name, n_stations=len(rows),
                                  state_counts={k: int(v) for k, v in frame["state"].value_counts().items()},
                                  stations=rows)

    @app.get("/alerts", response_model=sc.AlertsResponse)
    def alerts(request: Request, start: str = Query(pattern=DATE_PATTERN), end: str = Query(pattern=DATE_PATTERN),
               min_level: str = "Watch", set: str | None = None,
               limit: int = Query(1000, ge=1, le=MAX_CELLS)) -> sc.AlertsResponse:
        store = store_of(request)
        lo, hi = _day(start), _day(end)
        if lo > hi:
            raise HTTPException(422, "start must not be after end")
        try:
            level = lv.parse_level(min_level)
            frame = store.range(lo, hi, set, columns=LIST_COLUMNS + ["reasons_json", "shap_json"],
                                filters=[("level", ">=", level)])
        except ValueError as error:
            raise HTTPException(422, str(error)) from None
        except StoreError as error:
            raise _store_error(error, store) from None
        if len(frame):
            frame = frame.sort_values(["date", "level", "risk"], ascending=[True, False, False], kind="stable")
        items = []
        for r in frame.head(limit).itertuples():
            reasons = json.loads(r.reasons_json)
            items.append(sc.AlertItem(
                cell_id=int(r.cell_id), date=pd.Timestamp(r.date).strftime("%Y-%m-%d"), set=r.set, lat=r.lat,
                lon=r.lon, region=_text(r.region), risk=r.risk, level=int(r.level), level_name=r.level_name,
                confidence=r.confidence, reason_codes=_codes(r.reason_codes),
                reasons=sc.CellReasons(confidence=reasons["confidence"], sources=reasons["sources"],
                                       sensor_trust=reasons["sensor_trust"], shap=_shap(r.shap_json))))
        return sc.AlertsResponse(start=lo, end=hi, min_level=lv.level_name(level), set=set, n_alerts=int(len(frame)),
                                 truncated=len(frame) > limit, alerts=items)

    dist = Path(dist_dir or DIST_DIR)
    if (dist / "index.html").is_file():                          # last, so it never shadows an API route
        app.mount("/", SinglePageApp(directory=dist, html=True), name="dashboard")
    return app


app = create_app()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args(argv)
    uvicorn.run("aetherguard.serve.api:app", host=HOST, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
