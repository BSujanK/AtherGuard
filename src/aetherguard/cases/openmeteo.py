"""Point reanalysis rain for the case studies: Open-Meteo ERA5 / ERA5-Land hourly precipitation, cached raw.

Request: archive-api.open-meteo.com/v1/archive, hourly=precipitation, models=<model>, timezone=GMT. Raw JSON is cached
under data/raw/openmeteo/ with a manifest row (licence: Open-Meteo CC BY 4.0, ERA5 Copernicus); a cached response is
reused and never fetched again. Free-tier weight of a call = max(1, days / 14) * max(1, variables / 10); the number of
calls and their weight are returned so the use stays visible.

Day bases (hourly convention of Open-Meteo: the value stamped T is the total of the PRECEDING hour (T-1h, T]):
* utc_day_mm      UTC calendar day D = stamps 01:00 on D .. 00:00 on D+1;
* imd_exact_mm    IMD day D = stamps 04:00 on D-1 .. 03:00 on D (`ingest.align.exact_imd_day_from_hourly_utc`);
* imd_d5_mm       the D5 approximation 0.875 * UTC(D-1) + 0.125 * UTC(D) (`ingest.align.align_utc_to_imd_day`);
* d5_error_mm     imd_d5_mm - imd_exact_mm.
A day needs all 24 stamps, otherwise it is NaN (never a partial sum).
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlencode

import numpy as np
import pandas as pd

from ..config import PROJECT_ROOT, data_root
from ..http import DownloadError, fetch_json
from ..ingest.align import align_utc_to_imd_day, exact_imd_day_from_hourly_utc
from ..manifest import Manifest

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
SOURCE = "Open-Meteo archive API (ERA5 / ERA5-Land hourly precipitation)"
LICENCE = "Open-Meteo CC BY 4.0; ERA5 / ERA5-Land: Copernicus Climate Change Service (CC BY 4.0)"
MODELS = ("era5", "era5_land")
VARIABLE = "precipitation"
FREE_CALLS_PER_DAY = 10_000
DAYS_PER_CALL_UNIT = 14
VARS_PER_CALL_UNIT = 10

WAYANAD = {"name": "wayanad_mundakkai", "lat": 11.47, "lon": 76.13, "start": "2024-07-01", "end": "2024-08-05"}
KERALA_WINDOW = ("2018-07-15", "2018-08-25")
KERALA_POINT_DATES = ("2018-08-15", "2018-08-16")
N_KERALA_POINTS = 3
HEAVY_MM = 10.0


def call_weight(days: int, n_variables: int = 1) -> float:
    return max(1.0, days / DAYS_PER_CALL_UNIT) * max(1.0, n_variables / VARS_PER_CALL_UNIT)


def raw_dir() -> Path:
    return data_root() / "raw" / "openmeteo"


def processed_dir() -> Path:
    path = data_root() / "processed" / "cases"
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_manifest() -> Manifest:
    return Manifest(PROJECT_ROOT / "manifests" / "data_manifest.jsonl", data_root())


@dataclass
class Usage:
    """Calls made against the API (cache hits are free) and their free-tier weight."""
    calls: int = 0
    weight: float = 0.0
    cached: int = 0
    failures: list[str] = field(default_factory=list)


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def cache_path(directory: Path, tag: str, model: str, lat: float, lon: float, start: str, end: str) -> Path:
    return directory / f"{_slug(tag)}_{model}_{lat:.3f}_{lon:.3f}_{start}_{end}.json"


def request_params(lat: float, lon: float, start: str, end: str, model: str) -> dict:
    return {"latitude": lat, "longitude": lon, "start_date": start, "end_date": end, "hourly": VARIABLE,
            "models": model, "timezone": "GMT"}


def fetch_point(tag: str, lat: float, lon: float, start: str, end: str, model: str, *, directory: Path | None = None,
                manifest: Manifest | None = None, usage: Usage | None = None,
                fetch: Callable[..., dict] = fetch_json) -> dict:
    """The raw API payload for one point and model, from the cache when present, else fetched, written and recorded."""
    directory = Path(directory) if directory is not None else raw_dir()
    usage = usage if usage is not None else Usage()
    path = cache_path(directory, tag, model, lat, lon, start, end)
    if path.is_file():
        usage.cached += 1
        return json.loads(path.read_text(encoding="utf-8"))
    params = request_params(lat, lon, start, end, model)
    days = (pd.Timestamp(end) - pd.Timestamp(start)).days + 1
    usage.calls += 1
    usage.weight += call_weight(days)
    payload = fetch(ARCHIVE_URL, params=params)
    directory.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".part")
    partial.write_text(json.dumps(payload), encoding="utf-8")
    partial.replace(path)
    (manifest if manifest is not None else default_manifest()).add(path, SOURCE, f"{ARCHIVE_URL}?{urlencode(params)}", LICENCE)
    return payload


def cache_summary(directory: Path | None = None) -> dict:
    """Responses in the raw cache (one per API call ever made for them) and their total free-tier weight."""
    directory = Path(directory) if directory is not None else raw_dir()
    weight, files = 0.0, sorted(directory.glob("*.json")) if directory.is_dir() else []
    for path in files:
        match = re.search(r"_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})\.json$", path.name)
        if match:
            weight += call_weight((pd.Timestamp(match.group(2)) - pd.Timestamp(match.group(1))).days + 1)
    return {"cached_responses": len(files), "total_weight": weight}


def parse_hourly(payload: dict, model: str) -> pd.Series:
    """Hourly precipitation (mm) indexed by UTC stamp; null values become NaN. Raises ValueError on a bad series."""
    try:
        hourly = payload["hourly"]
        times = hourly["time"]
    except (KeyError, TypeError) as exc:
        raise ValueError("response has no hourly series") from exc
    key = VARIABLE if VARIABLE in hourly else f"{VARIABLE}_{model}"
    if key not in hourly:
        raise ValueError(f"response has no {VARIABLE!r} series (keys: {sorted(hourly)})")
    values = hourly[key]
    if len(values) != len(times) or not times:
        raise ValueError("time and precipitation series differ in length or are empty")
    index = pd.DatetimeIndex(pd.to_datetime(times)).as_unit("ns")
    if index.tz is not None or not (index[1:] - index[:-1] == pd.Timedelta(hours=1)).all():
        raise ValueError("hourly stamps must be consecutive, timezone-naive GMT hours")
    series = pd.Series([np.nan if v is None else float(v) for v in values], index=index, dtype=np.float64)
    if (series.dropna() < 0).any():
        raise ValueError("negative precipitation in the response")
    return series


def utc_day_totals(hourly: pd.Series) -> pd.Series:
    """UTC-day totals (stamps 01:00 D .. 00:00 D+1); NaN unless all 24 stamps are present and finite."""
    labels = (hourly.index - pd.Timedelta(hours=1)).floor("D")
    grouped = hourly.groupby(labels)
    complete = (grouped.size() == 24) & (grouped.count() == 24)
    totals = grouped.sum().where(complete)
    full = pd.date_range(totals.index[0], totals.index[-1], freq="D").as_unit("ns")
    out = totals.reindex(full)
    out.index.name = "date"
    return out


def derive_daily(hourly: pd.Series) -> pd.DataFrame:
    """Daily table indexed by date: utc_day_mm, imd_exact_mm, imd_d5_mm, d5_error_mm (see the module doc)."""
    utc = utc_day_totals(hourly)
    exact = exact_imd_day_from_hourly_utc(hourly.index, hourly.to_numpy())
    exact.index = exact.index.as_unit("ns")
    first = min(utc.index[0], exact.index[0])
    last = max(utc.index[-1], exact.index[-1])
    days = pd.date_range(first, last, freq="D").as_unit("ns")
    utc_full, exact_full = utc.reindex(days), exact.reindex(days)
    d5 = pd.Series(align_utc_to_imd_day(days, utc_full.to_numpy()), index=days)
    out = pd.DataFrame({"utc_day_mm": utc_full, "imd_exact_mm": exact_full, "imd_d5_mm": d5})
    out["d5_error_mm"] = out["imd_d5_mm"] - out["imd_exact_mm"]
    out.index.name = "date"
    return out.astype(np.float64)


def approximation_error(daily: pd.DataFrame) -> dict:
    """How far the D5 approximation is from the exact IMD-day total, over the days where both exist."""
    both = daily.dropna(subset=["imd_d5_mm", "imd_exact_mm"])
    if both.empty:
        return {"days": 0}
    err = both["d5_error_mm"].to_numpy()
    exact = both["imd_exact_mm"].to_numpy()
    heavy = exact >= HEAVY_MM
    out = {"days": int(len(both)), "mean_error_mm": float(err.mean()), "mean_abs_error_mm": float(np.abs(err).mean()),
           "rmse_mm": float(np.sqrt((err ** 2).mean())), "max_abs_error_mm": float(np.abs(err).max()),
           "correlation": float(np.corrcoef(both["imd_d5_mm"], exact)[0, 1]) if len(both) > 2 and exact.std() > 0 else float("nan"),
           "heavy_days": int(heavy.sum())}
    if heavy.any():
        out["heavy_mean_abs_relative_error"] = float(np.mean(np.abs(err[heavy]) / exact[heavy]))
        out["heavy_mean_error_mm"] = float(err[heavy].mean())
    worst = both.reindex(both["d5_error_mm"].abs().sort_values(ascending=False).index[:3])
    out["worst_days"] = [{"date": str(d.date()), "exact_mm": float(r["imd_exact_mm"]), "d5_mm": float(r["imd_d5_mm"])}
                         for d, r in worst.iterrows()]
    return out


def kerala_points(features: pd.DataFrame, dates=KERALA_POINT_DATES, n: int = N_KERALA_POINTS) -> list[dict]:
    """The `n` positive cells with the highest rain_acc_3 on the given dates (cell centres), from the case features."""
    from ..grid import cell_center
    mask = features["is_positive_cell_day"].astype(bool) & features["date"].isin(pd.to_datetime(list(dates)))
    top = features[mask].sort_values("rain_acc_3", ascending=False).drop_duplicates("cell_id").head(n)
    if len(top) < n:
        raise ValueError(f"only {len(top)} positive cells on {dates}, need {n}")
    points = []
    for row in top.itertuples():
        lat, lon = cell_center(int(row.cell_id))
        points.append({"name": f"kerala_cell_{int(row.cell_id)}", "cell_id": int(row.cell_id), "lat": float(lat),
                       "lon": float(lon), "start": KERALA_WINDOW[0], "end": KERALA_WINDOW[1],
                       "rain_acc_3": float(row.rain_acc_3), "event_date": str(row.date.date())})
    return points


def fetch_series(points: list[dict], models=MODELS, *, directory: Path | None = None, manifest: Manifest | None = None,
                 fetch: Callable[..., dict] = fetch_json, out_dir: Path | None = None) -> dict:
    """Fetch (or reuse) every point x model, derive the daily tables and write them to data/processed/cases/.

    Returns {"daily": {(point, model): DataFrame}, "usage": Usage, "unavailable": {(point, model): message}}. A model
    the API refuses or answers with an unusable series is recorded in `unavailable`, never silently dropped."""
    usage = Usage()
    manifest = manifest if manifest is not None else default_manifest()
    out_dir = Path(out_dir) if out_dir is not None else processed_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    daily, unavailable = {}, {}
    for point in points:
        for model in models:
            try:
                payload = fetch_point(point["name"], point["lat"], point["lon"], point["start"], point["end"], model,
                                      directory=directory, manifest=manifest, usage=usage, fetch=fetch)
                hourly = parse_hourly(payload, model)
                if hourly.notna().sum() == 0:
                    raise ValueError(f"every hourly {VARIABLE} value is null for {model} (variable not provided by the model)")
                table = derive_daily(hourly)
            except (DownloadError, ValueError) as exc:
                unavailable[(point["name"], model)] = str(exc)
                usage.failures.append(f"{point['name']} {model}: {exc}")
                continue
            table.to_parquet(out_dir / f"era5_{_slug(point['name'])}_{model}_daily.parquet")
            daily[(point["name"], model)] = table
    return {"daily": daily, "usage": usage, "unavailable": unavailable}
