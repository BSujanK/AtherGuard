"""Synthetic parts for the live-run tests: fake IMERG stores, GFS, IMD real-time and gauge sources, a tiny hazard model
and a handful of cells. Nothing here touches the network or the project data."""
from __future__ import annotations

import copy
from datetime import date, datetime, timedelta, timezone

import lightgbm as lgb
import numpy as np
import pandas as pd

from aetherguard.features.compute import STAT_COLUMNS, ClimTable
from aetherguard.features import imerg_features as F
from aetherguard.grid import cell_center, latlon_to_cell
from aetherguard.hazard.calibration import MonotoneCalibrator
from aetherguard.hazard.model import HazardModel
from aetherguard.alerts import levels as lv
from aetherguard.ingest import imerg
from aetherguard.ingest.imd import ImdGrid
from aetherguard.live import run as live_run
from aetherguard.live.early_map import EarlyLateMap, IdentityMap
from aetherguard.live.sources import (FetchContext, ForecastDays, GfsData, GhcnSource, ImdRealtimeSource, ImergSource,
                                      SourceStatus, imd_day_end)

from alerts_helpers import CONFIG as ALERT_CONFIG

DAY = date(2026, 8, 12)
NOW = datetime(2026, 8, 12, 5, 30, tzinfo=timezone.utc)          # 11:00 IST
THRESHOLDS = lv.Thresholds(watch=0.2, warning=0.5, emergency=0.8, source="test")
POINTS = {"wayanad": (11.55, 76.15, "western_ghats"), "idukki": (9.85, 76.95, "western_ghats"),
          "kathmandu": (27.70, 85.30, "himalaya"), "chamoli": (30.40, 79.30, "himalaya")}
MODEL_COLUMNS = ["irain_acc_1", "irain_acc_3", "irain_acc_7", "iapi_90", "inbr_max_acc_1", "stat_slope_mean"]
HEAVY_MM = 90.0
LIGHT_MM = 2.0
FITTED_MAP = EarlyLateMap(np.array([0.5, 200.0]), np.array([0.5, 200.0]))      # a fitted curve that happens to be the identity
STATIONS = pd.DataFrame({"id": ["GH000001", "GH000002"], "name": ["a", "b"], "lat": [11.5, 11.7], "lon": [76.1, 76.3]})


def tiny_cells() -> pd.DataFrame:
    rows = []
    for name, (lat, lon, region) in POINTS.items():
        cell = int(latlon_to_cell(lat, lon))
        centre = cell_center(cell)
        rows.append({"cell_id": cell, "lat": centre[0], "lon": centre[1], "region": region,
                     **{f"stat_{c}": np.float32(20.0 + len(rows)) for c in STAT_COLUMNS}})
    return pd.DataFrame(rows)


def pixel_of(name: str) -> tuple[int, int]:
    lat, lon, _ = POINTS[name]
    return imerg.imerg_pixel(int(latlon_to_cell(lat, lon)))


def heavy_mask(rows, cols, name: str = "wayanad", reach: int = 2) -> np.ndarray:
    row, col = pixel_of(name)
    return (np.abs(np.asarray(rows) - row) <= reach) & (np.abs(np.asarray(cols) - col) <= reach)


class FakeStore:
    """A store of UTC-day rain: `days` are present, the value at a pixel is `LIGHT_MM` or `HEAVY_MM` near Wayanad on the
    days of `heavy_days`; `overrides` maps a day to a constant that replaces the field (planted values)."""

    def __init__(self, days, heavy_days=(), overrides=None) -> None:
        self.days, self.heavy_days, self.overrides = set(days), set(heavy_days), dict(overrides or {})
        self.updated: list[list[date]] = []

    def has_date(self, day) -> bool:
        return day in self.days

    def dates(self) -> list[date]:
        return sorted(self.days)

    def update(self, days) -> dict:
        self.updated.append(list(days))
        return {}

    def gather(self, rows, cols, first_day, length) -> np.ndarray:
        rows, cols = np.asarray(rows).ravel(), np.asarray(cols).ravel()
        out = np.full((rows.size, length), np.nan, dtype=np.float32)
        for k in range(length):
            d = first_day + timedelta(days=k)
            if d not in self.days:
                continue
            if d in self.overrides:
                out[:, k] = self.overrides[d]
            else:
                out[:, k] = np.where(heavy_mask(rows, cols) & (d in self.heavy_days), HEAVY_MM, LIGHT_MM)
        return out


def span(first: date, last: date) -> list[date]:
    return [first + timedelta(days=k) for k in range((last - first).days + 1)]


def imerg_sources(day: date = DAY, heavy_days=None, late_missing=False, early_missing=False,
                  late_overrides=None, early_overrides=None, mapping=None) -> dict[str, ImergSource]:
    """Late through D-2 and Early for D-3..D-1, as published at run time; heavy rain near Wayanad on UTC D-3..D-1."""
    heavy = set(span(day - timedelta(days=3), day - timedelta(days=1))) if heavy_days is None else set(heavy_days)
    late = FakeStore([] if late_missing else span(day - timedelta(days=140), day - timedelta(days=2)), heavy, late_overrides)
    early = FakeStore([] if early_missing else span(day - timedelta(days=3), day - timedelta(days=1)), heavy, early_overrides)
    return {"imerg_late": ImergSource("late", late, latency_h=14.5, window_days=130),
            "imerg_early": ImergSource("early", early, latency_h=4.5, window_days=130,
                                   mapping=IdentityMap() if mapping is None else mapping)}


class FakeGfs:
    """The GFS source: forecast IMD-day totals (heavy near Wayanad on `heavy_leads`) and the 00-03 UTC accumulation."""
    name = "gfs"

    def __init__(self, day: date = DAY, heavy_leads=(2,), first_hours_mm: float | None = 0.5, valid=(True, True, True),
                 first_hours_product: str = "gfs_00z_0_3h") -> None:
        self.day, self.valid, self.first_hours_product = day, tuple(valid), first_hours_product
        rows, cols = np.indices((imerg.ROWS, imerg.COLS))
        days = np.full((3, imerg.ROWS, imerg.COLS), 4.0, dtype=np.float32)
        for lead in heavy_leads:
            days[lead - 1][heavy_mask(rows, cols)] = HEAVY_MM
        days[[not v for v in self.valid]] = np.nan
        self.forecast = ForecastDays(days, np.array(self.valid), datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc),
                                     [] if all(valid) else [48])
        self.first_hours = None if first_hours_mm is None else np.full((imerg.ROWS, imerg.COLS), first_hours_mm, np.float32)

    def fetch(self, ctx: FetchContext) -> SourceStatus:
        if not any(self.valid) and self.first_hours is None:
            return SourceStatus("gfs", False, None, None, None, "GFS unavailable")
        cycle = self.forecast.cycle
        issued = cycle + timedelta(hours=3.95)
        last = max([k + 1 for k, v in enumerate(self.valid) if v], default=0)
        return SourceStatus("gfs", all(self.valid) and self.first_hours is not None, imd_day_end(ctx.day + timedelta(days=last)),
                            issued, 3.0, None if self.first_hours is not None and all(self.valid) else "partial GFS")

    def load(self, ctx):
        product = self.first_hours_product if self.first_hours is not None else "persist_d1"
        return GfsData(self.forecast if any(self.valid) else None, self.first_hours, product)


def imd_grid_bytes(heavy_mm: float = 60.0, light_mm: float = LIGHT_MM) -> bytes:
    """An IMD real-time file: light rain everywhere, heavy rain around the nearest point of Wayanad."""
    grid = np.full((129, 135), light_mm, dtype="<f4")
    i, j = ImdGrid.nearest_index(POINTS["wayanad"][0], POINTS["wayanad"][1])
    grid[i - 1:i + 2, j - 1:j + 2] = heavy_mm
    return grid.tobytes()


def imd_post(heavy_mm: float = 60.0, calls: list | None = None):
    def post(day, timeout):
        if calls is not None:
            calls.append(day)
        return imd_grid_bytes(heavy_mm)
    return post


def imd_source(post=None) -> ImdRealtimeSource:
    return ImdRealtimeSource(days=3, timeout_s=1, attempts=1, latency_h=24, post=post or imd_post())


def ghcn_fetch(params: dict) -> list[dict]:
    rows = []
    for station in params["stations"].split(","):
        for stamp in pd.date_range(params["startDate"], params["endDate"]):
            if stamp.date() <= DAY - timedelta(days=6):          # gauge values arrive days late
                rows.append({"DATE": stamp.date().isoformat(), "STATION": station, "PRCP": "3.2", "PRCP_ATTRIBUTES": ",,"})
    return rows


def ghcn_source(fetch=ghcn_fetch) -> GhcnSource:
    return GhcnSource(look_back_days=30, timeout_s=1, per_request=50, latency_h=120, expected_lag_days=7,
                      stations=lambda: STATIONS.copy(), fetch=fetch)


def fake_integrity(gauges, view, imd_grids) -> pd.DataFrame:
    """Engine-shaped outputs for the observed station-days: every reading trusted, none flagged."""
    values = gauges.values
    rows = []
    for station in values.columns:
        for stamp, value in values[station].items():
            observed = bool(np.isfinite(value))
            rows.append({"station": station, "date": stamp, "trust": 0.95 if observed else np.nan,
                         "p_fault": 0.05 if observed else np.nan, "fault_type": "", "flagged": False,
                         "genuine_extreme": False, "reasons": "", "l1_flag": False, "l1_reason": ""})
    return pd.DataFrame(rows)


def healthy_sources(day: date = DAY, **imerg_options) -> dict:
    return {**imerg_sources(day, **imerg_options), "gfs": FakeGfs(day), "imd_rt": imd_source(), "ghcn": ghcn_source()}


def tiny_model() -> HazardModel:
    rng = np.random.default_rng(3)
    n = 4000
    acc3 = rng.uniform(0, 320, n)
    frame = pd.DataFrame({"irain_acc_1": acc3 * 0.4, "irain_acc_3": acc3, "irain_acc_7": acc3 * 1.5, "iapi_90": acc3 * 0.7,
                          "inbr_max_acc_1": acc3 * 0.45, "stat_slope_mean": rng.uniform(5, 40, n)}).astype(np.float32)
    y = (acc3 + rng.normal(0, 25, n) > 140).astype(int)
    constraints = [1, 1, 1, 1, 1, 0]
    params = dict(objective="binary", num_leaves=7, min_data_in_leaf=20, learning_rate=0.2, verbosity=-1, seed=1,
                  deterministic=True, force_row_wise=True, monotone_constraints=constraints)
    booster = lgb.train(params, lgb.Dataset(frame, y), num_boost_round=30)
    members = []
    for k in range(3):
        rows = np.random.default_rng(10 + k).integers(0, n, n)
        members.append(lgb.train({**params, "seed": 10 + k}, lgb.Dataset(frame.iloc[rows], y[rows]), num_boost_round=30))
    calibrator = MonotoneCalibrator.fit(booster.predict(frame), y, np.ones(n))
    return HazardModel(MODEL_COLUMNS, constraints, booster, 30, members, calibrator, {})


def wayanad_row(frame: pd.DataFrame) -> pd.Series:
    """The row of the western-ghats (Wayanad) cell, where the scenarios put the heavy rain."""
    cell = int(tiny_cells().query("region == 'western_ghats'")["cell_id"].iloc[0])
    return frame[frame["cell_id"] == cell].iloc[0]


def tiny_clim(cells: pd.DataFrame) -> ClimTable:
    pix = np.unique(F.cell_pixels(cells["cell_id"].to_numpy()))
    return ClimTable(pix, np.full((len(pix), 12, 3), 40.0))


def make_cfg(tmp_path, **overrides) -> dict:
    cfg = copy.deepcopy(live_run.load_run_config())
    cfg.pop(live_run.LEAD0_KEY, None)      # which model production runs lead 0 with is not what these tests are about
    cfg.update(live_dir=str(tmp_path / "live"), report_dir=str(tmp_path / "reports"), replay_dir=str(tmp_path / "replay"),
               forecast_widening=str(tmp_path / "forecast_widening.json"), forecast_selection=str(tmp_path / "forecast_selection.json"),
               places_table=str(tmp_path / "cell_places.parquet"),
               top_cells=5)
    cfg["imerg"]["processed_dir"] = str(tmp_path / "rain")
    cfg["early_map"]["file"] = str(tmp_path / "imerg_early_to_late.json")
    cfg.update(overrides)
    return cfg


def make_deps(sources=None, **fields) -> live_run.LiveDeps:
    cells = tiny_cells()
    deps = dict(sources=sources if sources is not None else healthy_sources(), model=tiny_model(), thresholds=THRESHOLDS,
                alert_config=ALERT_CONFIG, cells=cells, clim=tiny_clim(cells), integrity=fake_integrity, now=lambda: NOW)
    deps.update(fields)
    return live_run.LiveDeps(**deps)


def write_widening(path, lo=0.5, hi=3.0) -> None:
    import json
    path.write_text(json.dumps({"leads": {str(k): {"lo": lo, "hi": hi} for k in (1, 2, 3)}}), encoding="utf-8")


SLOPE_FLOOR = 5.0


def write_cell_tables(tmp_path, cfg: dict) -> pd.DataFrame:
    """Terrain, region and samples-manifest tables on disk for the four candidate cells plus three that are not: two
    below the slope floor and one outside the regions in scope. Points `cfg` at them; returns the terrain table."""
    import json
    cells = tiny_cells()
    extra = pd.DataFrame([{"cell_id": int(latlon_to_cell(lat, lon)), "lat": lat, "lon": lon, "region": region, "slope": slope}
                          for lat, lon, region, slope in ((11.60, 76.20, "western_ghats", 2.0), (27.80, 85.40, "himalaya", 4.9),
                                                          (20.00, 80.00, "out_of_scope", 30.0))])
    rows = []
    for _, cell in cells.iterrows():
        rows.append({"cell_id": cell["cell_id"], "lat": cell["lat"], "lon": cell["lon"], "region": cell["region"],
                     "slope": float(cell["stat_slope_mean"])})
    table = pd.concat([pd.DataFrame(rows), extra], ignore_index=True)
    terrain = table[["cell_id", "lat", "lon"]].copy()
    for column in STAT_COLUMNS:
        terrain[column] = 10.0
    terrain["slope_mean"] = table["slope"]
    folder = tmp_path / "tables"
    folder.mkdir(exist_ok=True)
    terrain.to_parquet(folder / "terrain.parquet", index=False)
    table[["cell_id", "region"]].assign(country_code="IN").to_parquet(folder / "regions.parquet", index=False)
    (folder / "samples_manifest.json").write_text(json.dumps({"report": {"slope_floor": {"floor": SLOPE_FLOOR}}}), encoding="utf-8")
    cfg.update(terrain_table=str(folder / "terrain.parquet"), region_table=str(folder / "regions.parquet"),
               samples_manifest=str(folder / "samples_manifest.json"))
    return terrain
