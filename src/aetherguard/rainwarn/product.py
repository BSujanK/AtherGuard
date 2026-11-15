"""The daily heavy-rain warning product of one run day (spec sections 4, 7 and 8).

    python -m aetherguard.rainwarn run --date D --live-dir <run dir of D> [--out-dir DIR] [--calibration FILE]

Reads only what the live run already has for day D: `features_D0.parquet` of the run directory (the cell list and
`irain_acc_1`, the observed IMD-day total of D with the nowcast tail) and the ECMWF day file of D in the rain store
(`ecmwf_imdday_<D>.npz`, written by the live run's fetch). Writes `rain_warnings.parquet` (one row per cell and lead 0..3)
and `rain_warnings.md` (a bulletin section) into the out directory, by default the run directory. Nothing else in the run
directory is opened for writing; landslide alert levels are not read or changed.

A lead without a valid ensemble day (or lead 0 without the observed total) is written with NaN probabilities, level
`unavailable` and the reason; it is never filled from another source.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import data_root
from ..features import imerg_features as F
from ..ingest import ecmwf
from . import climatology as C
from . import engine as E
from . import prob as P
from .study import pixel_values

PARQUET, BULLETIN = "rain_warnings.parquet", "rain_warnings.md"
PROB_COLUMNS = {name: f"p_{name}" for name in P.THRESHOLDS}
REGIONS = ("himalaya", "western_ghats")


class ProductError(RuntimeError):
    """The run directory cannot give the product its inputs."""


def _cycle(forecast) -> str | None:
    return forecast.ens_cycle.isoformat() if forecast is not None and forecast.ens_cycle is not None else None


def build(day: date, features: pd.DataFrame, forecast, clim: C.Climatology, calibration: E.Calibration) -> pd.DataFrame:
    """Rows of every cell and lead 0..3 from the lead-0 feature table, the ECMWF day (or None) and the tables."""
    domain = C.Domain(pixels=clim.pixels, regions=clim.regions)
    flat = F.cell_pixels(features["cell_id"].to_numpy())
    where = clim.position(flat)
    inside = where >= 0
    frames = []
    for lead in E.LEADS:
        target = day + timedelta(days=lead)
        if lead == 0:
            obs0 = pixel_values(domain, features, "irain_acc_1")
            fields = E.observed_fields(obs0, calibration.radii, domain.pixels) if np.isfinite(obs0).any() else None
            reason = None if fields is not None else "no observed IMD-day total of D (irain_acc_1)"
            source, cycle = "imerg_early+nowcast_tail", None
        else:
            grids = E.ensemble_grids(forecast, lead)
            fields = E.forecast_fields(grids, calibration.radii, domain.pixels) if grids is not None else None
            reason = None if fields is not None else "no valid ECMWF ensemble day for this lead"
            source, cycle = "ecmwf_ens", _cycle(forecast)
        probs = {}
        for name in P.THRESHOLDS:
            values = np.full(len(features), np.nan)
            if fields is not None:
                p = calibration.probability(fields, lead, name, clim.threshold_mm(name), clim.prob(name, target))
                values[inside] = p[where[inside]]
            probs[name] = values
        level = P.warning_levels(probs)
        frame = pd.DataFrame({"cell_id": features["cell_id"].to_numpy(), "date": pd.Timestamp(day), "lead": np.int8(lead),
                              "target_date": pd.Timestamp(target), "lat": features["lat"].to_numpy(),
                              "lon": features["lon"].to_numpy(), "region": features["region"].to_numpy()})
        for name in P.THRESHOLDS:
            frame[PROB_COLUMNS[name]] = probs[name].astype(np.float32)
        thr95, thr99 = np.full(len(features), np.nan), np.full(len(features), np.nan)
        thr95[inside], thr99[inside] = clim.p95[where[inside]], clim.p99[where[inside]]
        frame["thr_p95_mm"], frame["thr_p99_mm"] = thr95.astype(np.float32), thr99.astype(np.float32)
        frame["level"] = level
        frame["level_name"] = [P.LEVEL_NAMES[int(c)] for c in level]
        frame["published"] = fields is not None
        frame["source"], frame["cycle"], frame["reason"] = source, cycle, reason
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)


def bulletin(table: pd.DataFrame, day: date, calibration_path: Path) -> str:
    lines = [f"## Heavy-rain warnings, issued {day.isoformat()} (research prototype)", "",
             "Probability that the IMD-day rain total (03 UTC to 03 UTC) of a cell exceeds the IMD categories heavy "
             "(64.5 mm), very heavy (115.6 mm), extremely heavy (204.5 mm), or the cell's own 95th / 99th monsoon "
             "percentile. Levels: red P(very heavy) >= 0.5 or P(extremely heavy) >= 0.25; orange P(heavy) >= 0.5 or "
             "P(very heavy) >= 0.2 or P(p99) >= 0.4; yellow P(heavy) >= 0.2 or P(p95) >= 0.4. Not validated for public "
             "warnings; it does not change any landslide alert level. Verification: reports/phase8_rain_warnings.md. "
             "Contains ECMWF open data (IFS), licensed CC BY 4.0.", "",
             "| lead | day | source | cells | yellow | orange | red | unavailable | max P(heavy) | max P(very heavy) |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for lead, rows in table.groupby("lead", sort=True):
        counts = rows["level_name"].value_counts()
        target = pd.Timestamp(rows["target_date"].iloc[0]).date().isoformat()
        def top(column):
            values = rows[column].to_numpy(dtype=np.float64)
            return f"{np.nanmax(values):.2f}" if np.isfinite(values).any() else "-"
        lines.append(f"| D+{int(lead)} | {target} | {rows['source'].iloc[0]} | {len(rows)} | {int(counts.get('yellow', 0))} | "
                     f"{int(counts.get('orange', 0))} | {int(counts.get('red', 0))} | {int(counts.get('unavailable', 0))} | "
                     f"{top('p_heavy')} | {top('p_very_heavy')} |")
        reason = rows["reason"].iloc[0]
        if reason:
            lines.append(f"|  | D+{int(lead)} not published: {reason} | | | | | | | | |")
    for region in REGIONS:
        part = table[(table["region"] == region) & (table["level"] >= 1)]
        if len(part):
            by = part.groupby("lead")["level"].count().to_dict()
            lines += ["", f"{region}: cells at yellow or above by lead: " + ", ".join(f"D+{int(k)} {v}" for k, v in by.items())]
    lines += ["", f"Calibration: {calibration_path.name}."]
    return "\n".join(lines) + "\n"


def run_day(cfg: dict, day: date, live_dir: Path, out_dir: Path | None = None, *, calibration: Path | None = None,
            rain_dir: Path | None = None) -> int:
    live_dir = Path(live_dir)
    out_dir = Path(out_dir) if out_dir is not None else live_dir
    features_path = live_dir / "features_D0.parquet"
    if not features_path.is_file():
        raise ProductError(f"{features_path} not found: the run directory of {day} has no lead-0 feature table")
    run_json = live_dir / "run.json"
    if run_json.is_file():
        stated = json.loads(run_json.read_text(encoding="utf-8")).get("date")
        if stated and stated != day.isoformat():
            raise ProductError(f"{run_json} is the run of {stated}, not {day}")
    root = data_root()
    rain_dir = Path(rain_dir) if rain_dir is not None else root / cfg["rain_dir"]
    calibration = Path(calibration) if calibration is not None else root / cfg["out_dir"] / "calibration_shipped.json"
    clim = C.Climatology.load(root / cfg["out_dir"] / cfg["climatology"]["file"])
    features = pd.read_parquet(features_path, columns=["cell_id", "lat", "lon", "region", "irain_acc_1"])
    forecast = ecmwf.load_day(rain_dir / ecmwf.day_file_name(day))
    table = build(day, features, forecast, clim, E.Calibration.load(calibration))
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = out_dir / (PARQUET + ".tmp")
    table.to_parquet(tmp, index=False)
    tmp.replace(out_dir / PARQUET)
    (out_dir / BULLETIN).write_text(bulletin(table, day, calibration), encoding="utf-8")
    counts = table.groupby(["lead", "level_name"]).size().to_dict()
    print(f"[rainwarn] {day}: wrote {out_dir / PARQUET} ({len(table)} rows) {counts}", flush=True)
    return 0
