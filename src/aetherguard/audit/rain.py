"""Rain-product probes: what each source returns for the reference point and event dates."""
from __future__ import annotations

import gzip
import os
import shutil
from pathlib import Path

import numpy as np

from ..http import DownloadError, download, fetch_json
from .result import ProbeResult, failure_status

OPEN_METEO_ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
POWER_POINT = "https://power.larc.nasa.gov/api/temporal/daily/point"
POWER_ZARR = "s3://nasa-power/merra2/temporal/power_merra2_daily_temporal_utc.zarr"
CHIRPS_URL = ("https://data.chc.ucsb.edu/products/CHIRPS-2.0/global_daily/tifs/p05/"
              "{y}/chirps-v2.0.{y}.{m}.{d}.tif.gz")

DAY_DEFINITIONS = {
    "open_meteo": ("UTC calendar date (timezone=UTC requested). Open-Meteo hourly precipitation is the "
                   "total of the PRECEDING hour, so the stamps 00:00-23:00 UTC of a date cover "
                   "23:00 UTC of the previous day to 23:00 UTC of that date"),
    "power_zarr": "NASA POWER analysis-ready 'utc' store: UTC calendar day of MERRA-2",
    "chirps": "UTC calendar day (00-24 UTC) per CHIRPS documentation - confirm in review",
    "imd": ("IMD rainfall day: 08:30 IST previous day to 08:30 IST (= 03:00 UTC to 03:00 UTC) "
            "per IMD convention - confirm in review"),
}
_OPEN_METEO_MODELS = ("era5", "era5_land", "ecmwf_ifs")


def daily_sums(times: list[str], values: list) -> dict[str, dict]:
    """Sum hourly values per calendar day (from the leading YYYY-MM-DD) and count nulls explicitly."""
    out: dict[str, dict] = {}
    for stamp, value in zip(times, values):
        slot = out.setdefault(stamp[:10], {"sum_mm": 0.0, "n": 0, "n_null": 0})
        slot["n"] += 1
        if value is None:
            slot["n_null"] += 1
        else:
            slot["sum_mm"] += float(value)
    return {day: {**slot, "sum_mm": round(slot["sum_mm"], 3)} for day, slot in out.items()}


def _open_meteo_hourly(lat, lon, start, end, model, variable):
    data = fetch_json(OPEN_METEO_ARCHIVE, params={
        "latitude": lat, "longitude": lon, "start_date": start, "end_date": end,
        "hourly": variable, "models": model, "timezone": "UTC"})
    hourly = data["hourly"]
    series = hourly[variable] if variable in hourly else hourly[f"{variable}_{model}"]
    return hourly["time"], series


def probe_open_meteo(lat, lon, dates: list[str]) -> ProbeResult:
    start, end = dates[0], dates[-1]
    rows, problems, errors = [], [], []
    for model in _OPEN_METEO_MODELS:
        try:
            times, values = _open_meteo_hourly(lat, lon, start, end, model, "precipitation")
        except (DownloadError, KeyError) as exc:
            errors.append(exc)
            problems.append(f"{model} precipitation: {exc}")
            continue
        daily = daily_sums(times, values)
        n_null = sum(slot["n_null"] for slot in daily.values())
        if n_null:
            problems.append(f"{model} precipitation: {n_null} null hourly values")
        short = [d for d in dates if d not in daily or daily[d]["n"] != 24]
        if short:
            problems.append(f"{model} precipitation: days without 24 hourly values: {short}")
        rows.append({"label": model,
                     "daily_mm": {d: (daily[d]["sum_mm"]
                                      if d in daily and daily[d]["n"] == 24 and daily[d]["n_null"] == 0
                                      else None)
                                  for d in dates}})
    soil = None
    try:
        _, values = _open_meteo_hourly(lat, lon, start, end, "era5_land", "soil_moisture_0_to_7cm")
        soil = {"n": len(values), "n_null": sum(v is None for v in values)}
        if soil["n_null"]:
            problems.append(f"era5_land soil_moisture_0_to_7cm: {soil['n_null']} of {soil['n']} values null")
    except (DownloadError, KeyError) as exc:
        errors.append(exc)
        problems.append(f"era5_land soil_moisture_0_to_7cm: {exc}")

    evidence = {"event_rows": rows, "soil_moisture": soil, "problems": problems}
    if not rows:
        return ProbeResult("open_meteo", failure_status(errors),
                           "no precipitation series could be read", evidence, DAY_DEFINITIONS["open_meteo"])
    healthy = not problems and len(rows) == len(_OPEN_METEO_MODELS)
    complete = sum(all(v is not None for v in row["daily_mm"].values()) for row in rows)
    summary = (f"{complete}/{len(_OPEN_METEO_MODELS)} precipitation models with complete data; "
               f"soil moisture {'ok' if soil and not soil['n_null'] else 'problem'}")
    if problems:
        summary += f"; {len(problems)} problem(s), first: {problems[0]}"
    return ProbeResult("open_meteo", "ok" if healthy else "partial", summary,
                       evidence, DAY_DEFINITIONS["open_meteo"])


def probe_power_api(lat, lon, dates: list[str]) -> ProbeResult:
    try:
        data = fetch_json(POWER_POINT, params={
            "parameters": "PRECTOTCORR,GWETTOP,GWETROOT", "community": "AG", "longitude": lon,
            "latitude": lat, "start": dates[0].replace("-", ""), "end": dates[-1].replace("-", ""),
            "format": "JSON"})
        params = data["properties"]["parameter"]
    except (DownloadError, KeyError) as exc:
        return ProbeResult("power_api", failure_status([exc]), f"NASA POWER API failed: {exc}",
                           {"event_rows": []}, "NASA POWER daily point API (time standard unavailable)")
    header = data.get("header", {})
    fill = header.get("fill_value", -999.0)
    time_standard = header.get("time_standard", "unknown")
    day_definition = f"NASA POWER time_standard={time_standard} (MERRA-2 native daily)"

    def clean(series):
        return {f"{k[:4]}-{k[4:6]}-{k[6:]}": (None if v == fill else v) for k, v in series.items()}

    returned = clean(params.get("PRECTOTCORR", {}))
    precip = {d: returned.get(d) for d in dates}
    missing = [d for d in dates if d not in returned]
    soil_ok = all(p in params and all(v != fill for v in params[p].values())
                  for p in ("GWETTOP", "GWETROOT"))
    n_none = sum(v is None for v in precip.values())
    problems = []
    if missing:
        problems.append(f"missing dates: {missing}")
    if n_none - len(missing):
        problems.append(f"{n_none - len(missing)} requested day(s) carry the fill value")
    if not soil_ok:
        problems.append("soil wetness GWETTOP/GWETROOT missing or fill values")
    ok = not n_none and soil_ok
    return ProbeResult("power_api", "ok" if ok else "partial",
                       f"PRECTOTCORR requested days={len(dates)}, missing/fill={n_none}, soil wetness "
                       f"{'ok' if soil_ok else 'missing/fill'}",
                       {"event_rows": [{"label": "merra2_power_api", "daily_mm": precip}],
                        "time_standard": time_standard, "fill_value": fill, "problems": problems},
                       day_definition)


def probe_power_zarr(lat, lon, dates: list[str]) -> ProbeResult:
    day = DAY_DEFINITIONS["power_zarr"]
    try:
        import xarray as xr
    except ImportError:
        return ProbeResult("power_zarr", "inconclusive",
                           "xarray not installed (pip install -e .[audit])", {"event_rows": []}, day)
    try:
        ds = xr.open_zarr(POWER_ZARR, storage_options={"anon": True}, consolidated=True)
        series = ds["PRECTOTCORR"].sel(lat=lat, lon=lon, method="nearest").sel(
            time=slice(dates[0], dates[-1])).load()
        returned = {str(t)[:10]: (None if np.isnan(v) else round(float(v), 2))
                    for t, v in zip(series["time"].values, series.values)}
        daily = {d: returned.get(d) for d in dates}
        problems = []
        missing = [d for d in dates if d not in returned]
        if missing:
            problems.append(f"missing dates: {missing}")
        nan_days = [d for d in dates if d in returned and returned[d] is None]
        if nan_days:
            problems.append(f"NaN values on dates: {nan_days}")
        evidence = {
            "event_rows": [{"label": "merra2_power_zarr_utc", "daily_mm": daily}],
            "problems": problems,
            "dims": {k: int(v) for k, v in ds.sizes.items()},
            "n_variables": len(ds.data_vars),
            "soil_variables_present": [v for v in ("GWETTOP", "GWETROOT", "GWETPROF") if v in ds],
            "prectotcorr_chunks": str(ds["PRECTOTCORR"].encoding.get("chunks")),
        }
    except Exception as exc:  # network vs. library/API-shape problems are told apart in the hint
        return ProbeResult(
            "power_zarr", "inconclusive", f"{type(exc).__name__}: {exc}",
            {"event_rows": [],
             "hint": "If this is AttributeError/KeyError/ValueError the probe code may be wrong: inspect "
                     "xarray.open_zarr on the store and fix the probe before concluding the store is "
                     "unusable. A network error means retry."}, day)
    n_present = sum(v is not None for v in daily.values())
    ok = bool(daily) and n_present == len(daily)
    return ProbeResult("power_zarr", "ok" if ok else "partial",
                       f"bulk MERRA-2 store readable; {n_present}/{len(daily)} requested days have values",
                       evidence, day)


def _extract_gzip(gz: Path, tif: Path) -> None:
    """Decompress to a temporary name and rename into place only when complete."""
    part = tif.with_name(tif.name + ".part")
    try:
        with gzip.open(gz, "rb") as source, part.open("wb") as target:
            shutil.copyfileobj(source, target)
        os.replace(part, tif)
    except BaseException:
        part.unlink(missing_ok=True)
        raise


def probe_chirps(dates, lat, lon, data_root, manifest, period_days) -> ProbeResult:
    day = DAY_DEFINITIONS["chirps"]
    try:
        import rasterio
        from rasterio.errors import RasterioIOError
    except ImportError as exc:
        return ProbeResult("chirps", "inconclusive", f"rasterio unavailable: {exc}", {"event_rows": []}, day)
    values, sizes, structure = {}, [], {}
    errors: list[Exception] = []
    problems: list[str] = []
    for d in dates:
        y, m, dd = d.split("-")
        gz = Path(data_root) / "raw" / "audit" / "chirps" / f"chirps-v2.0.{y}.{m}.{dd}.tif.gz"
        tif = gz.with_suffix("")
        try:
            download(CHIRPS_URL.format(y=y, m=m, d=dd), gz, manifest, "CHIRPS v2.0 daily p05",
                     "see https://www.chc.ucsb.edu/data/chirps (verify licence in review)")
            if not tif.exists():
                _extract_gzip(gz, tif)
            with rasterio.open(tif) as ds:
                this = {"shape": tuple(ds.shape), "res": tuple(round(r, 4) for r in ds.res),
                        "bounds": tuple(round(b, 3) for b in ds.bounds), "nodata": ds.nodata}
                row, col = ds.index(lon, lat)
                value = float(ds.read(1, window=((row, row + 1), (col, col + 1)))[0, 0])
        except DownloadError as exc:
            errors.append(exc)
            problems.append(f"{d}: download failed: {exc}")
            values[d] = None
            continue
        except (OSError, EOFError, RasterioIOError) as exc:  # gzip.BadGzipFile is an OSError
            errors.append(exc)
            problems.append(f"{d}: unreadable CHIRPS file ({type(exc).__name__}: {exc})")
            values[d] = None
            continue
        structure = this
        sizes.append(gz.stat().st_size)
        nodata = structure["nodata"]
        if (nodata is not None and value == nodata) or value < 0:
            values[d] = None
            problems.append(f"{d}: nodata/negative value at the reference pixel")
        else:
            values[d] = round(value, 2)
    evidence = {"event_rows": [{"label": "chirps_p05", "daily_mm": values}], **structure,
                "problems": problems}
    if sizes:
        evidence["est_total_gb"] = round(float(np.mean(sizes)) * period_days / 1e9, 1)
    if not sizes:
        all_download = bool(errors) and all(isinstance(e, DownloadError) for e in errors)
        status = failure_status(errors) if all_download else "inconclusive"
        return ProbeResult("chirps", status,
                           f"no CHIRPS file could be read ({len(problems)} problem(s))", evidence, day)
    grid_ok = structure.get("shape") == (2000, 7200) and structure.get("res") == (0.05, 0.05)
    if not grid_ok:
        problems.append(f"grid {structure.get('shape')} at {structure.get('res')} deg differs from the "
                        f"expected (2000, 7200) at (0.05, 0.05)")
    ok = grid_ok and not problems
    summary = (f"grid {structure.get('shape')} at {structure.get('res')} deg; "
               f"~{evidence.get('est_total_gb')} GB for the full period")
    if problems:
        summary += f"; {len(problems)} problem(s)"
    return ProbeResult("chirps", "ok" if ok else "partial", summary, evidence, day)


def probe_imd(lat, lon, dates, data_root, manifest) -> ProbeResult:
    day = DAY_DEFINITIONS["imd"]
    hint = ("If this is a network error, retry. If it is AttributeError/TypeError/KeyError, run "
            "`python -c \"import imdlib; help(imdlib.get_data); help(imdlib.open_data)\"`, correct the "
            "probe, and do NOT report IMD gridded rainfall as unavailable until the probe itself is verified.")
    try:
        import imdlib as imd
    except ImportError:
        return ProbeResult("imd", "inconclusive", "imdlib not installed (pip install -e .[audit])",
                           {"event_rows": []}, day)
    year = int(dates[0][:4])
    target = Path(data_root) / "raw" / "audit" / "imd"
    target.mkdir(parents=True, exist_ok=True)
    try:
        imd.get_data("rain", year, year, fn_format="yearwise", file_dir=str(target))
        ds = imd.open_data("rain", year, year, fn_format="yearwise", file_dir=str(target)).get_xarray()
        point = ds["rain"].sel(lat=lat, lon=lon, method="nearest")
        values = {}
        for d in dates:
            v = float(point.sel(time=d).values)
            values[d] = None if (np.isnan(v) or v < 0) else round(v, 2)
        grid_shape = tuple(int(s) for s in ds["rain"].shape)
    except Exception as exc:
        return ProbeResult("imd", "inconclusive", f"{type(exc).__name__}: {exc}",
                           {"event_rows": [], "hint": hint}, day)
    for path in target.rglob("*"):
        if path.is_file() and manifest is not None and not manifest.is_current(path):
            manifest.add(path, "IMD gridded rainfall 0.25 deg (via imdlib)",
                         "https://imdpune.gov.in", "IMD data terms (verify in review)")
    ok = all(v is not None for v in values.values())
    return ProbeResult("imd", "ok" if ok else "partial",
                       f"IMD {year} gridded rain readable; grid shape {grid_shape}",
                       {"event_rows": [{"label": "imd_gauge_grid_0p25", "daily_mm": values}],
                        "grid_shape": grid_shape}, day)
