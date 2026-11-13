"""W4 source probe: which soil-moisture / antecedent-wetness source can the hazard model use
(docs/superpowers/specs/2026-11-13-aetherguard-w4-wetness.md section 1)?

A source is usable only if ALL hold: (a) history over the development years 2007-2017 and the held-out years 2018-2025;
(b) available to the 11:00 IST run with a declared, measured lag; (c) the same quantity in training and live, or a mapping
between the historical and the live product that passes a check fixed before it is measured; (d) download size and time feasible
on this laptop; (e) no new account, key or licence acceptance.

    python -m aetherguard.features.wetness_probe metadata [--out FILE]   # CMR, ARCO-ERA5, IFS open data and GFS indexes
    python -m aetherguard.features.wetness_probe mapping --cells FILE [--out FILE]  # ERA5 vs IFS and GFS soil water, 2025
    python -m aetherguard.features.wetness_probe render --metadata FILE --mapping FILE  # reports/phase8_wetness_sources_probe.*

Anonymous HTTPS only: CMR search needs no login, the ARCO-ERA5 store, the ECMWF open-data bucket and NOAA's GFS bucket are
public. Nothing here reads a credential. The mapping criterion (`MAPPING_CRITERION`) was written before the first measurement;
the first run had a longitude bug for the IFS grid (its first longitude is 180, i.e. -180) and was rerun with the same
criterion.
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from ..config import PROJECT_ROOT, data_root
from ..hazard.jsonio import dump_json

UA = {"User-Agent": "aetherguard-research-probe"}
CMR = "https://cmr.earthdata.nasa.gov/search"
ARCO = "https://storage.googleapis.com/gcp-public-data-arco-era5/ar/full_37-1h-0p25deg-chunk-1.zarr-v3"
IFS = "https://storage.googleapis.com/ecmwf-open-data"
IFS_LIVE = "https://data.ecmwf.int/forecasts"
GFS = "https://noaa-gfs-bdp-pds.s3.amazonaws.com"
NOMADS = "https://nomads.ncep.noaa.gov/pub/data/nccf/com/gfs/prod"
REPORT = PROJECT_ROOT / "reports" / "phase8_wetness_sources_probe"
COLLECTIONS = [("SPL4SMGP", None), ("SPL4SMAU", None), ("GLDAS_NOAH025_3H", "2.1"), ("GLDAS_NOAH025_3H_EP", None),
               ("GLDAS_CLSM025_DA1_D", "2.2"), ("FLDAS_NOAH01_C_GL_M", None), ("M2T1NXLND", None), ("MOD10C1", "61")]
MAPPING_DAYS = [date(2025, 6, 1) + timedelta(days=4 * k) for k in range(54)]
DEPTH = {1: 7.0, 2: 21.0, 3: 72.0}                      # cm of ERA5 / IFS layers 1-3 within 0-100 cm
GFS_DEPTH = {"0-0.1": 10.0, "0.1-0.4": 30.0, "0.4-1": 60.0}
MAPPING_CRITERION = (
    "over the 0.25-degree pixels that hold panel cells, on the probe days (June-December 2025, every 4th day), for the root "
    "zone (0-100 cm, depth-weighted layers) and the surface layer: (i) median over pixels of the per-pixel Spearman rank "
    "correlation across days >= 0.80, and (ii) median over pixels of the mean absolute difference of per-pixel percentile "
    "ranks (each product ranked within its own series at that pixel, the per-cell quantile transform) <= 0.10. Both must hold "
    "for the live product to stand in for ERA5.")
SPEARMAN_MIN, RANK_DIFF_MAX = 0.80, 0.10


def _session() -> requests.Session:
    session = requests.Session()
    session.headers.update(UA)
    return session


def fetch(session, url: str, headers: dict | None = None, tries: int = 5) -> bytes:
    for k in range(tries):
        try:
            response = session.get(url, headers=headers or {}, timeout=120)
            if response.status_code in (200, 206):
                return response.content
            if response.status_code in (429, 500, 502, 503):
                time.sleep(2 * (k + 1))
                continue
            raise RuntimeError(f"HTTP {response.status_code}")
        except requests.RequestException:
            time.sleep(2 * (k + 1))
    raise RuntimeError(f"no answer after {tries} tries")


# ------------------------------------------------------------------------------------------------ metadata

def cmr_collection(session, short_name: str, version: str | None, now: datetime) -> dict:
    """Coverage, newest granule (its end and the hours from it to `now`, the latency upper bound at probe time) and size."""
    params = {"short_name": short_name, "page_size": 5, **({"version": version} if version else {})}
    entries = session.get(f"{CMR}/collections.json", params=params, timeout=60).json()["feed"]["entry"]
    if not entries:
        return {"short_name": short_name, "error": "no collection"}
    c = entries[0]
    out = {"short_name": short_name, "version": c.get("version_id"), "provider": c.get("data_center"),
           "title": c.get("title"), "time_start": c.get("time_start")}
    for key, sort in (("newest", "-start_date"), ("oldest", "start_date")):
        granules = session.get(f"{CMR}/granules.json", params={"collection_concept_id": c["id"], "sort_key": sort,
                                                                 "page_size": 1}, timeout=60).json()["feed"]["entry"]
        if granules:
            g = granules[0]
            out[key] = {"time_start": g.get("time_start"), "time_end": g.get("time_end"),
                        "granule_size_mb": float(g["granule_size"]) if g.get("granule_size") else None}
    if "newest" in out and out["newest"]["time_end"]:
        end = datetime.fromisoformat(out["newest"]["time_end"].replace("Z", "+00:00"))
        out["hours_since_newest_end"] = round((now - end).total_seconds() / 3600, 1)
    return out


def ifs_soil_start(session, days) -> dict:
    """Whether the 00z oper step-0 open-data index of each day lists `vsw` (soil water), from the Google copy."""
    out = {}
    for day in days:
        ymd = day.strftime("%Y%m%d")
        try:
            text = fetch(session, f"{IFS}/{ymd}/00z/ifs/0p25/oper/{ymd}000000-0h-oper-fc.index").decode()
            out[day.isoformat()] = sum(1 for line in text.splitlines() if '"vsw"' in line)
        except RuntimeError:
            out[day.isoformat()] = None
    return out


def metadata(out: Path) -> dict:
    now = datetime.now(timezone.utc)
    session = _session()
    result = {"probed_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
              "cmr": {f"{n}{'/' + v if v else ''}": cmr_collection(session, n, v, now) for n, v in COLLECTIONS}}
    meta = json.loads(fetch(session, f"{ARCO}/.zmetadata"))["metadata"]
    soil = {k.split("/")[0]: v for k, v in meta.items() if "soil_water" in k and k.endswith(".zarray")}
    result["arco_era5"] = {"store": ARCO.split("/ar/")[1], "attributes": meta.get(".zattrs", {}),
                           "soil_variables": {k: {"shape": v["shape"], "chunks": v["chunks"], "dtype": v["dtype"]}
                                              for k, v in soil.items()}}
    live = None
    for back in range(4):
        ymd = (now - timedelta(days=back)).strftime("%Y%m%d")
        try:
            text = fetch(session, f"{IFS_LIVE}/{ymd}/00z/ifs/0p25/oper/{ymd}000000-0h-oper-fc.index", tries=2).decode()
        except RuntimeError:
            continue
        lines = [json.loads(x) for x in text.splitlines() if x.strip()]
        live = {"day": ymd, "soil": sorted({(x["param"], x.get("levelist")) for x in lines if x.get("levtype") == "sol"})}
        break
    result["ifs_open_data"] = {"live_00z_step0": live, "vsw_messages_by_day": ifs_soil_start(
        session, [date(2024, 9, 1), date(2024, 11, 1), date(2024, 11, 12), date(2024, 11, 15), date(2025, 6, 1)])}
    gfs = {}
    for back in range(3):
        ymd = (now - timedelta(days=back)).strftime("%Y%m%d")
        try:
            text = fetch(session, f"{NOMADS}/gfs.{ymd}/00/atmos/gfs.t00z.pgrb2.0p25.f000.idx", tries=2).decode()
        except RuntimeError:
            continue
        gfs["live_soilw_layers"] = [ln.split(":")[4] for ln in text.splitlines() if ":SOILW:" in ln]
        break
    for ymd, key in (("20210301", "gfs.20210301/00/gfs.t00z.pgrb2.0p25.f000.idx"),
                     ("20180601", "gfs.20180601/00/gfs.t00z.pgrb2.0p25.f000.idx")):
        try:
            gfs[f"aws_{ymd}"] = sum(1 for ln in fetch(session, f"{GFS}/{key}", tries=2).decode().splitlines() if ":SOILW:" in ln)
        except RuntimeError:
            gfs[f"aws_{ymd}"] = None
    result["gfs"] = gfs
    dump_json(out, result)
    return result


# ------------------------------------------------------------------------------------------------- mapping

def _grib_values(blob: bytes) -> tuple[np.ndarray, float]:
    import eccodes

    gid = eccodes.codes_new_from_message(blob)
    try:
        ni, nj = eccodes.codes_get(gid, "Ni"), eccodes.codes_get(gid, "Nj")
        lon0 = eccodes.codes_get(gid, "longitudeOfFirstGridPointInDegrees")
        values = eccodes.codes_get_values(gid).reshape(nj, ni)
        missing = eccodes.codes_get(gid, "missingValue")
    finally:
        eccodes.codes_release(gid)
    return np.where(values == missing, np.nan, values), float(lon0)


def agreement(a: np.ndarray, b: np.ndarray) -> dict:
    """(days, pixels) arrays: per pixel the Spearman correlation across days and the mean absolute difference of the
    percentile ranks (each series ranked within itself), then the medians against `MAPPING_CRITERION`."""
    from scipy.stats import rankdata

    rho, diff = [], []
    for j in range(a.shape[1]):
        m = np.isfinite(a[:, j]) & np.isfinite(b[:, j])
        if m.sum() < 10 or np.ptp(a[m, j]) == 0 or np.ptp(b[m, j]) == 0:
            continue
        ra, rb = rankdata(a[m, j]) / m.sum(), rankdata(b[m, j]) / m.sum()
        rho.append(np.corrcoef(ra, rb)[0, 1])
        diff.append(np.mean(np.abs(ra - rb)))
    rho, diff = np.array(rho), np.array(diff)
    return {"pixels_used": int(len(rho)), "spearman_median": float(np.median(rho)), "spearman_p10": float(np.percentile(rho, 10)),
            "spearman_p90": float(np.percentile(rho, 90)), "abs_rank_diff_median": float(np.median(diff)),
            "abs_rank_diff_p90": float(np.percentile(diff, 90)),
            "passes": bool(np.median(rho) >= SPEARMAN_MIN and np.median(diff) <= RANK_DIFF_MAX)}


def mapping(cells: np.ndarray, out: Path, days=MAPPING_DAYS, workers: int = 4) -> dict:
    import numcodecs

    session, blosc = _session(), numcodecs.Blosc()
    lat = -90.0 + (cells // 10000 + 0.5) * 0.05
    lon = -180.0 + (cells % 10000 + 0.5) * 0.05
    pix = np.unique(np.clip(np.round((90.0 - lat) / 0.25).astype(int), 0, 720) * 1440 + np.round((lon % 360.0) / 0.25).astype(int) % 1440)
    prow, plon = pix // 1440, (pix % 1440) * 0.25
    origin = int(np.frombuffer(blosc.decode(fetch(session, f"{ARCO}/time/0")), dtype="<i8")[0])   # hours since 1900 of index 0
    sizes, lon0s = [], {}

    def columns(lon0: float) -> np.ndarray:
        return np.round(((plon - lon0) % 360.0) / 0.25).astype(int) % 1440

    def era5(day: date, hour: int, layer: int) -> np.ndarray:
        h = int((np.datetime64(day) - np.datetime64("1900-01-01")) / np.timedelta64(1, "h")) + hour - origin
        raw = fetch(session, f"{ARCO}/volumetric_soil_water_layer_{layer}/{h}.0.0")
        sizes.append(len(raw))
        return np.frombuffer(blosc.decode(raw), dtype="<f4").reshape(721, 1440)[prow, columns(0.0)].astype(np.float64)

    def ifs(day: date) -> dict:
        ymd = day.strftime("%Y%m%d")
        base = f"{IFS}/{ymd}/12z/ifs/0p25/oper/{ymd}120000-0h-oper-fc"
        lines = [json.loads(x) for x in fetch(session, f"{base}.index").decode().splitlines() if x.strip()]
        out = {}
        for x in lines:
            if x.get("param") == "vsw" and x.get("levelist") in ("1", "2", "3"):
                a, n = x["_offset"], x["_length"]
                values, lon0 = _grib_values(fetch(session, f"{base}.grib2", {"Range": f"bytes={a}-{a + n - 1}"}))
                lon0s["ifs"] = lon0
                out[int(x["levelist"])] = values[prow, columns(lon0)]
        return out

    def gfs(day: date) -> dict:
        key = f"gfs.{day:%Y%m%d}/00/atmos/gfs.t00z.pgrb2.0p25.f000"
        lines = fetch(session, f"{GFS}/{key}.idx").decode().splitlines()
        out = {}
        for i, line in enumerate(lines):
            parts = line.split(":")
            layer = parts[4].replace(" m below ground", "")
            if parts[3] == "SOILW" and parts[5] == "anl" and layer in GFS_DEPTH:
                a, b = int(parts[1]), int(lines[i + 1].split(":")[1]) - 1
                values, lon0 = _grib_values(fetch(session, f"{GFS}/{key}", {"Range": f"bytes={a}-{b}"}))
                lon0s["gfs"] = lon0
                out[layer] = values[prow, columns(lon0)]
        return out

    def one(day: date) -> dict:
        try:
            return {"day": day, "era5_12": {k: era5(day, 12, k) for k in DEPTH}, "era5_00": {k: era5(day, 0, k) for k in DEPTH},
                    "ifs": ifs(day), "gfs": gfs(day)}
        except RuntimeError as exc:
            return {"day": day, "error": type(exc).__name__}

    started = time.perf_counter()
    with ThreadPoolExecutor(workers) as pool:
        records = list(pool.map(one, days))
    ok = [r for r in records if "error" not in r and len(r["ifs"]) == 3 and len(r["gfs"]) == 3]

    def root(d: dict, weights: dict) -> np.ndarray:
        return sum(weights[k] * d[k] for k in weights) / sum(weights.values())

    def stack(key, fn) -> np.ndarray:
        return np.array([fn(r[key]) for r in ok])

    e12r, e12s = stack("era5_12", lambda d: root(d, DEPTH)), stack("era5_12", lambda d: d[1])
    e00r, e00s = stack("era5_00", lambda d: root(d, DEPTH)), stack("era5_00", lambda d: d[1])
    ir, is_ = stack("ifs", lambda d: root(d, DEPTH)), stack("ifs", lambda d: d[1])
    gr, gs = stack("gfs", lambda d: root(d, GFS_DEPTH)), stack("gfs", lambda d: d["0-0.1"])
    result = {"criterion": MAPPING_CRITERION, "days_requested": len(days), "days_used": len(ok), "pixels": int(len(pix)),
              "cells": int(len(cells)), "failed_days": [r["day"].isoformat() for r in records if r not in ok],
              "era5_chunk_bytes": {"n": len(sizes), "mean": float(np.mean(sizes)) if sizes else None},
              "pairs": {"ifs_vs_era5_root_12utc": agreement(e12r, ir), "ifs_vs_era5_surface_12utc": agreement(e12s, is_),
                        "gfs_vs_era5_root_00utc": agreement(e00r, gr), "gfs_vs_era5_surface_00utc": agreement(e00s, gs),
                        "era5_00_vs_12_root_reference": agreement(e00r, e12r)},
              "level_bias_root_median": {"ifs_minus_era5": float(np.nanmedian(ir - e12r)), "gfs_minus_era5": float(np.nanmedian(gr - e00r))},
              "grid_first_longitude": lon0s, "seconds": time.perf_counter() - started}
    dump_json(out, result)
    return result


# ------------------------------------------------------------------------------------------- local evidence

def live_lag_evidence(live_dir: Path | None = None) -> dict:
    """Which product supplied each UTC day of the last two IMD days in the published live runs (read-only): the 0.875 share of
    IMD day D-1 is UTC day D-2, so 'late' there means the Late daily file of UTC D-2 was in the store at the run's start."""
    live_dir = Path(live_dir or data_root() / "live")
    runs = []
    for path in sorted(glob.glob(str(live_dir / "20*" / "run.json"))):
        record = json.loads(Path(path).read_text(encoding="utf-8"))

        def find(obj, key):
            if isinstance(obj, dict):
                if key in obj:
                    return obj[key]
                for value in obj.values():
                    hit = find(value, key)
                    if hit is not None:
                        return hit
            return None
        inputs = find(record, "imd_day_inputs")
        if inputs:
            runs.append({"day": Path(path).parent.name, "started": record.get("started_utc"),
                         "utc_d_minus_2": inputs.get("D-1", {}).get("utc_day_0.875")})
    late = [r for r in runs if r["utc_d_minus_2"] == "late"]
    return {"runs": runs, "n_runs": len(runs), "n_utc_d_minus_2_from_late": len(late)}


def snow_relevance(cells: np.ndarray) -> dict:
    """How many panel cells, and development positives, lie high enough for snow in June-December to matter."""
    terrain = pd.read_parquet(data_root() / "processed" / "terrain" / "cell_terrain.parquet", columns=["cell_id", "elev_mean"])
    elev = terrain.set_index("cell_id")["elev_mean"].reindex(cells)
    samples = pd.concat([pd.read_parquet(data_root() / "processed" / "features" / f"{n}_features.parquet",
                                         columns=["cell_id", "date", "kind", "in_domain", "stat_elev_mean"])
                         for n in ("train_samples", "validation_samples")])
    positive = samples[(samples["kind"] == "positive") & samples["in_domain"].astype(bool)]
    return {"panel_cells": int(len(cells)), "panel_cells_mean_elevation_3000m_or_more": int((elev >= 3000).sum()),
            "development_positives": int(len(positive)),
            "development_positives_mean_elevation_3000m_or_more": int((positive["stat_elev_mean"] >= 3000).sum()),
            "development_positives_from_2015_03_31": int((pd.to_datetime(positive["date"]) >= "2015-03-31").sum())}


def history_priors() -> dict:
    """What earlier development studies said about wetness inputs (the committed CV reports)."""
    v2 = {g["name"]: g for g in json.loads((PROJECT_ROOT / "reports" / "phase3_hazard_cv_report.json").read_text())["groups"]}
    v3 = {g["name"]: g for g in json.loads((PROJECT_ROOT / "reports" / "phase6_v3_cv_report.json").read_text())["groups"]}
    pick = lambda g: {"inputs": g["n_inputs"], "fa_at_90": g["fa_at_90"], "se": g["se"]}   # noqa: E731
    return {"v2_merra2_wetness": {"full": pick(v2["full"]), "drop_wet": pick(v2["drop_wet"])},
            "v3_api": {"imerg_core": pick(v3["imerg_core"]), "imerg_core+iapi": pick(v3["imerg_core+iapi"])}}


# -------------------------------------------------------------------------------------------------- render

def verdicts(meta: dict, mapping_result: dict, lag: dict, snow: dict) -> list[dict]:
    """One row per candidate: coverage, latency and how it was measured, size, access, verdict. Every number is read from the
    measurements; the wording around them is fixed."""
    cmr, arco = meta["cmr"], meta["arco_era5"]["attributes"]
    pairs = mapping_result["pairs"]
    chunk_mb = mapping_result["era5_chunk_bytes"]["mean"] / 1e6

    def age(key):
        return cmr[key].get("hours_since_newest_end")

    def size(key):
        return (cmr[key].get("newest") or {}).get("granule_size_mb")

    def pair(name):
        p = pairs[name]
        return f"Spearman {p['spearman_median']:.2f}, rank difference {p['abs_rank_diff_median']:.3f}"

    probed = datetime.fromisoformat(meta["probed_utc"].replace("Z", "+00:00")).date()
    era5t_lag = (probed - date.fromisoformat(arco["valid_time_stop_era5t"])).days
    return [
        {"candidate": "SMAP L4 surface and root-zone soil moisture (SPL4SMGP / SPL4SMAU)",
         "coverage": f"from {cmr['SPL4SMGP']['time_start'][:10]}: 2015-2017 only of the development years",
         "latency": f"newest granule ended {age('SPL4SMGP'):.0f} h before the probe (CMR)",
         "size": f"{size('SPL4SMGP'):.0f} MB per 3-hourly global granule; needs spatial subsetting",
         "access": "Earthdata login (existing)", "verdict": "fails (a)",
         "why": (f"8 of the 11 development years have no data; {snow['development_positives_from_2015_03_31']} of the "
                 f"{snow['development_positives']} development positives fall after its start, and a model would treat the "
                 "absence as a year effect")},
        {"candidate": "ERA5 volumetric soil water, ARCO-ERA5 public store (training) with ERA5T (live)",
         "coverage": f"{arco['valid_time_start']} on; final ERA5 to {arco['valid_time_stop']}, ERA5T to {arco['valid_time_stop_era5t']}",
         "latency": f"ERA5T ends {era5t_lag} days before the probe day (store attribute, last updated {arco['last_updated'][:16]} UTC)",
         "size": f"{chunk_mb:.1f} MB per global hourly field and layer (measured on {mapping_result['era5_chunk_bytes']['n']} chunks)",
         "access": "anonymous (Google public bucket); the CDS route needs an account (not used)",
         "verdict": f"passes (a), (c), (d), (e); (b) only with a declared lag of at least {era5t_lag + 1} days, measured once",
         "why": "not chosen: a week-old state, an update schedule nobody guarantees, one latency observation; kept as a "
                "possible later study if the bucket shows that wetness matters"},
        {"candidate": "ERA5 (training) with ECMWF IFS open-data analysis `vsw` (live, 12 UTC of D-1)",
         "coverage": "IFS open data carries `vsw` from 2024-11-13 (measured by index), so only as the live side",
         "latency": "the 12z run of D-1 is published by about 20 UTC of D-1 (ingest.ecmwf, phase6_ecmwf_publication)",
         "size": "about 0.3-0.5 MB per layer by byte range", "access": "anonymous",
         "verdict": "fails (c)" if not (pairs["ifs_vs_era5_root_12utc"]["passes"] or pairs["ifs_vs_era5_surface_12utc"]["passes"]) else "passes (c)",
         "why": f"mapping check against ERA5 on {mapping_result['days_used']} days of 2025: root zone {pair('ifs_vs_era5_root_12utc')}; "
                f"surface {pair('ifs_vs_era5_surface_12utc')} (criterion {SPEARMAN_MIN:.2f} and {RANK_DIFF_MAX:.2f})"},
        {"candidate": "ERA5 (training) with NOAA GFS analysis SOILW (live, 00 UTC of D)",
         "coverage": "GFS analyses on the public bucket from 2021 (2018 absent), so only as the live side",
         "latency": "the 00z f000 file is out by about 04 UTC (live GFS ingest)", "size": "about 0.5 MB per layer by byte range",
         "access": "anonymous",
         "verdict": "fails (c)" if not (pairs["gfs_vs_era5_root_00utc"]["passes"] or pairs["gfs_vs_era5_surface_00utc"]["passes"]) else "passes (c)",
         "why": f"mapping check: root zone {pair('gfs_vs_era5_root_00utc')}; surface {pair('gfs_vs_era5_surface_00utc')}; "
                f"ERA5 00 UTC against its own 12 UTC, the reference a usable stand-in should approach: {pair('era5_00_vs_12_root_reference')}"},
        {"candidate": "GLDAS Noah 2.1 (main and Early Product), GLDAS CLSM 2.2, FLDAS",
         "coverage": "2000 / 2003 / 1982 on",
         "latency": (f"newest granule ended {age('GLDAS_NOAH025_3H/2.1') / 24:.0f} / {age('GLDAS_NOAH025_3H_EP') / 24:.0f} / "
                     f"{age('GLDAS_CLSM025_DA1_D/2.2') / 24:.0f} / {age('FLDAS_NOAH01_C_GL_M') / 24:.0f} days before the probe (CMR)"),
         "size": f"{size('GLDAS_NOAH025_3H/2.1'):.0f} MB per 3-hourly granule", "access": "Earthdata login (existing)",
         "verdict": "fails (b)", "why": "weeks to months behind real time; no live product of the same quantity"},
        {"candidate": "MERRA-2 land (NASA POWER GWETTOP / GWETROOT, already on disk for v2)",
         "coverage": "1980 on (the local copy 2007-2024)",
         "latency": f"newest M2T1NXLND granule ended {age('M2T1NXLND') / 24:.0f} days before the probe (CMR)",
         "size": "already local", "access": "anonymous / Earthdata", "verdict": "fails (b)",
         "why": "weeks behind; and in v2 dropping these inputs changed development FA@90 by less than its SE (history below)"},
        {"candidate": "Bucket water balance on the IMERG Late store (this project's data), state at the end of IMD day D-2",
         "coverage": "IMERG Late from 2006-10-01, complete (0 missing days)",
         "latency": (f"lag 2 IMD days: in {lag['n_utc_d_minus_2_from_late']} of {lag['n_runs']} published live runs the UTC day "
                     "D-2 came from the Late store (run.json imd_day_inputs)"),
         "size": "no download", "access": "none new", "verdict": "passes (a)-(e); identical in training and live by construction",
         "why": "chosen: the baseline any external product must beat, and no external product passed"},
        {"candidate": "Snow cover, MODIS MOD10C1 v061 (0.05 degree daily)",
         "coverage": f"from {cmr['MOD10C1/61']['time_start'][:10]}",
         "latency": f"newest granule ended {age('MOD10C1/61'):.0f} h before the probe (CMR): lag 3 days at 11:00 IST",
         "size": f"{size('MOD10C1/61'):.1f} MB per global day", "access": "Earthdata login (existing; NSIDC download not tested)",
         "verdict": "not pursued here",
         "why": (f"{snow['panel_cells_mean_elevation_3000m_or_more']:,} of the {snow['panel_cells']:,} panel cells but only "
                 f"{snow['development_positives_mean_elevation_3000m_or_more']} of the {snow['development_positives']} development "
                 "positives lie at 3000 m or more; monsoon cloud cover over the snow map is not measured here; kept out to hold the "
                 "candidate count small. A later study for the high cells, where October-December rain may fall as snow")},
    ]


def render(meta: dict, mapping_result: dict, lag: dict, snow: dict, priors: dict, out_stem: Path = REPORT) -> dict:
    rows = verdicts(meta, mapping_result, lag, snow)
    result = {"created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "criteria": {"a": "history over 2007-2017 and 2018-2025 for the June-December panel days",
                           "b": "available to the 11:00 IST run with a declared, measured lag",
                           "c": "the same quantity in training and live, or a mapping that passes a check fixed before measuring",
                           "d": "download size and time feasible on this laptop", "e": "no new account, key or licence"},
              "candidates": rows, "choice": "iwet: bucket water balance on the IMERG Late store, lag 2 IMD days",
              "metadata": meta, "mapping": mapping_result, "live_lag": lag, "snow": snow, "history": priors}
    dump_json(out_stem.with_suffix(".json"), result)
    v2, v3 = priors["v2_merra2_wetness"], priors["v3_api"]
    lines = [
        "# W4 source probe: soil moisture and antecedent wetness (phase 8)", "",
        f"Probed {meta['probed_utc']} (metadata) and on {mapping_result['days_used']} days of June-December 2025 (mapping). "
        "Anonymous HTTPS only; no credential was read. **Chosen: the bucket water balance on the IMERG Late store**, state "
        "at the end of IMD day D-2, identical in training and live by construction. No external product passed all five "
        "criteria.", "",
        "Criteria: (a) history over 2007-2017 and 2018-2025; (b) available by 11:00 IST with a declared, measured lag; (c) the "
        "same quantity in training and live, or a mapping that passes a check fixed before it is measured; (d) feasible "
        "download; (e) no new account, key or licence.", "",
        "| candidate | coverage | latency (how measured) | size | access | verdict |", "|---|---|---|---|---|---|",
        *[f"| {r['candidate']} | {r['coverage']} | {r['latency']} | {r['size']} | {r['access']} | {r['verdict']}: {r['why']} |"
          for r in rows], "",
        "## Mapping check (criterion fixed before the first measurement)", "",
        MAPPING_CRITERION, "",
        "| pair | pixels | median Spearman [p10, p90] | median rank difference (p90) | passes |", "|---|---|---|---|---|",
        *[f"| {name} | {p['pixels_used']:,} | {p['spearman_median']:.3f} [{p['spearman_p10']:.3f}, {p['spearman_p90']:.3f}] | "
          f"{p['abs_rank_diff_median']:.3f} ({p['abs_rank_diff_p90']:.3f}) | {'yes' if p['passes'] else 'no'} |"
          for name, p in mapping_result["pairs"].items()], "",
        f"Median root-zone level difference (m3/m3): IFS - ERA5 {mapping_result['level_bias_root_median']['ifs_minus_era5']:+.3f}, "
        f"GFS - ERA5 {mapping_result['level_bias_root_median']['gfs_minus_era5']:+.3f}. The first run of the check mapped the IFS "
        "grid with a 180-degree longitude error (its first longitude is 180, i.e. -180); it was rerun with the same criterion "
        "and only the corrected numbers are shown.", "",
        "## What a late start does to SMAP", "",
        "SMAP L4 begins on 2015-03-31. The development years are 2007-2017, so 2007-2014 would have no value: either the "
        f"development set shrinks to 2015-2017 ({snow['development_positives_from_2015_03_31']} of the "
        f"{snow['development_positives']} positives, three of the seven folds, so v3's year-blocked folds and its frozen "
        "reference no longer apply), or the model sees a wetness input that is missing in most years and learns the "
        "missingness as a year effect. Neither is the comparison protocol v3 asks for, so SMAP fails (a).", "",
        "## Lag of the bucket (measured on the published live runs)", "",
        f"In {lag['n_utc_d_minus_2_from_late']} of {lag['n_runs']} live runs (`data/live/<day>/run.json`, `imd_day_inputs`), the "
        "UTC day D-2 came from the IMERG Late store, so IMD day D-2 (0.875 of UTC D-3 and 0.125 of UTC D-2) is all Late at "
        "11:00 IST. The bucket at the end of IMD day D-2 therefore reads exactly the files training reads; the rain of IMD days "
        "D-1 and D stays in the rain inputs. Runs without it: "
        + (", ".join(f"{r['day']} (started {r['started']}, UTC D-2 from {r['utc_d_minus_2']})" for r in lag["runs"]
                     if r["utc_d_minus_2"] != "late") or "none")
        + ". On such a day the live adapter, reading the Late store only, finds IMD day D-2 missing and returns NaN (the strict "
        "rule); what the live run does then is decided when it is wired.", "",
        "## Snow", "",
        f"Panel cells with mean elevation of 3000 m or more: {snow['panel_cells_mean_elevation_3000m_or_more']:,} of "
        f"{snow['panel_cells']:,}; development positives there: {snow['development_positives_mean_elevation_3000m_or_more']} of "
        f"{snow['development_positives']}.", "",
        "## What earlier development studies said", "",
        f"- v2 (IMD rain) with MERRA-2 wetness: FA@90 {v2['full']['fa_at_90']:.4f} (SE {v2['full']['se']:.4f}); without the "
        f"wetness group {v2['drop_wet']['fa_at_90']:.4f} (SE {v2['drop_wet']['se']:.4f}) "
        "(`reports/phase3_hazard_cv_report.json`).",
        f"- v3 group selection: imerg_core {v3['imerg_core']['fa_at_90']:.4f}; with the antecedent precipitation index "
        f"{v3['imerg_core+iapi']['fa_at_90']:.4f} (`reports/phase6_v3_cv_report.json`).",
        "- Both differences are within one bootstrap SE: a linear antecedent index and a coarse reanalysis wetness added little "
        "to the 1-90 day rain accumulations. The bucket differs from both (it saturates and dries with the season), which is "
        "what this study tests; a small or no gain is a plausible outcome.", "",
        "## Decisions for the user", "",
        "- ERA5-Land through the Copernicus CDS would need a CDS account and licence acceptance: not done. The anonymous "
        "ARCO-ERA5 store gives ERA5 (not ERA5-Land, 0.25 degree) without an account.", ""]
    out_stem.with_suffix(".md").write_text("\n".join(lines), encoding="utf-8")
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    m = sub.add_parser("metadata")
    m.add_argument("--out", type=Path, required=True)
    p = sub.add_parser("mapping")
    p.add_argument("--cells", type=Path, required=True, help="npz with `cell_id` (the panel cells)")
    p.add_argument("--out", type=Path, required=True)
    r = sub.add_parser("render")
    r.add_argument("--metadata", type=Path, required=True)
    r.add_argument("--mapping", type=Path, required=True)
    r.add_argument("--cells", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "metadata":
        metadata(args.out)
    elif args.command == "mapping":
        with np.load(args.cells) as data:
            mapping(np.asarray(data["cell_id"], dtype=np.int64), args.out)
    else:
        with np.load(args.cells) as data:
            cells = np.asarray(data["cell_id"], dtype=np.int64)
        render(json.loads(args.metadata.read_text()), json.loads(args.mapping.read_text()), live_lag_evidence(),
               snow_relevance(cells), history_priors())
        print(f"wrote {REPORT}.{{json,md}}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
