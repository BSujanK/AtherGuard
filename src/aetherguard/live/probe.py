"""Live data-source spike (Stage A, Task 1): real-network probes that decide formats and access paths.

Every source gets a time-boxed probe whose result becomes one entry of `reports/phase6_live_sources_probe.json`
(and a Markdown rendering). A probe that raises, or runs past its time box, becomes `reachable: false` with the
exception CLASS NAME only: messages can quote URLs, so they are never stored. Earthdata credentials come from the
user's netrc through `requests`; nothing here reads, prints or stores a credential value, and the final report text
is scanned for known secrets before it is written.

Run: `python -m aetherguard.live.probe [--only NAME[,NAME]] [--timeout SECONDS] [--reports-dir DIR]`.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import math
import re
import statistics
import threading
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np
import requests

from ..audit.report import collect_secrets, redact
from ..config import PROJECT_ROOT, data_root, load_config
from ..http import download, fetch_json
from ..manifest import Manifest

DECISIONS = ("use", "fallback", "drop")
SOURCE_FIELDS = ("reachable", "url_pattern", "auth", "format", "variables", "bytes_per_day_domain",
                 "seconds_per_day", "latency_hours", "history_start", "decision", "notes")
PROBE_TIMEOUT_S = 120.0
_DEADLINE_MARGIN_S = 6.0
REPORT_STEM = "phase6_live_sources_probe"
_HEADERS = {"User-Agent": "AetherGuard/0.1 (research prototype)"}
_LICENCE = "NASA / NOAA open data (verify terms before redistribution)"
_MIB = 1024 * 1024

CMR = "https://cmr.earthdata.nasa.gov/search/"
IMERG_HISTORICAL_DAY = date(2018, 8, 15)
WAYANAD = (11.47, 76.13)  # lat, lon
IMERG_ORIGIN = {"lon": -179.95, "lat": -89.95}  # centre of pixel 0 on each axis; step 0.1 deg
IMERG_STEP = 0.1
PRECIP_NAMES = ("precipitation", "precipitationCal")
READ_ENGINES = ("netcdf4", "h5netcdf", "scipy")
HDF5_MAGIC = b"\x89HDF"
NETCDF3_MAGIC = b"CDF"
HISTORY_START, HISTORY_END = date(2006, 10, 1), date(2018, 12, 31)
INTENSITY_MAX_HOURS, INTENSITY_MAX_GB = 12.0, 20.0

NOMADS_PROD = "https://nomads.ncep.noaa.gov/pub/data/nccf/com/gfs/prod/"
NOMADS_FILTER = "https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl"
GFS_AWS = "https://noaa-gfs-bdp-pds.s3.amazonaws.com/"
GFS_FORECAST_HOURS = tuple(range(3, 97, 3))
GFS_ARCHIVE_DAY, GFS_ARCHIVE_CYCLE, GFS_ARCHIVE_HOUR = date(2023, 7, 15), 0, 24
_MONTHS = {m: i for i, m in enumerate(
    ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), start=1)}

NCEI_ACCESS = "https://www.ncei.noaa.gov/access/services/data/v1"
GHCN_STATIONS, GHCN_DAYS = 10, 120


# --------------------------------------------------------------------------- report assembly
def clean(value):
    """Plain, strictly serialisable copy: NaN/inf -> None, numpy scalars -> Python, paths and dates -> text."""
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [clean(v) for v in value]
    if isinstance(value, np.ndarray):
        return clean(value.tolist())
    if isinstance(value, (np.floating, np.integer, np.bool_)):
        return clean(value.item())
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return value.as_posix()
    return value


def _failed(result: dict, error_class: str) -> dict:
    failed = dict(result)
    failed.update(reachable=False, error_class=error_class, decision="drop")
    failed["notes"] = list(failed.get("notes") or []) + [
        f"probe failed with {error_class}; anything not listed below was not measured"]
    return failed


def run_probe(name: str, fn: Callable[[dict, float], None], timeout_s: float = PROBE_TIMEOUT_S) -> dict:
    """Run `fn(result, deadline)` in a thread with a hard time box.

    `fn` fills `result` as it learns things (so a time-boxed probe keeps what it measured) and may stop early at
    `deadline` (a `time.monotonic()` value a few seconds before the box ends). An exception or a timeout yields
    `reachable: false` and the exception class name; the message is never kept.
    """
    result: dict = {"name": name}
    outcome: dict = {}

    def target() -> None:
        try:
            fn(result, time.monotonic() + timeout_s - _DEADLINE_MARGIN_S)
        except Exception as exc:  # a probe bug or a network failure must not stop the other probes
            outcome["error_class"] = type(exc).__name__

    thread = threading.Thread(target=target, name=f"probe-{name}", daemon=True)
    thread.start()
    thread.join(timeout_s)
    if thread.is_alive():
        return _failed(result, "TimeoutError")
    if "error_class" in outcome:
        return _failed(result, outcome["error_class"])
    return dict(result)


def assemble_source(raw: dict) -> dict:
    """One report entry: every field present (None when not measured), decision validated."""
    if not raw.get("name"):
        raise ValueError("a probe result needs a name")
    entry = {"name": raw["name"], "error_class": raw.get("error_class")}
    for field in SOURCE_FIELDS:
        entry[field] = raw.get(field)
    entry["reachable"] = bool(raw.get("reachable", False))
    entry["variables"] = raw.get("variables") or {}
    entry["notes"] = list(raw.get("notes") or [])
    entry["decision"] = raw.get("decision", "drop")
    if entry["decision"] not in DECISIONS:
        raise ValueError(f"decision for {raw['name']!r} must be one of {DECISIONS}, got {entry['decision']!r}")
    entry["decision_basis"] = raw.get("decision_basis")
    entry["needs_user_action"] = raw.get("needs_user_action")
    entry["details"] = raw.get("details") or {}
    return clean(entry)


def build_report(probes: list[dict], generated_utc: datetime, domain: dict, extras: dict | None = None) -> dict:
    sources = [assemble_source(p) for p in probes]
    return clean({
        "generated_utc": generated_utc,
        "domain_bbox": domain,
        "sources": sources,
        "needs_user_action": [{"source": s["name"], "action": s["needs_user_action"]}
                              for s in sources if s["needs_user_action"]],
        "extras": extras or {},
    })


def _fmt(value) -> str:
    if value is None:
        return "not measured"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)


def _cell(value) -> str:
    return " ".join(_fmt(value).split()).replace("|", "\\|")


def render_markdown(report: dict) -> str:
    lines = ["# Phase 6 live-source probe (Stage A, Task 1)", "",
             f"Generated {report['generated_utc']} UTC. Domain bbox {report['domain_bbox']}. "
             "Every number below was measured by `python -m aetherguard.live.probe` and is stored in the JSON "
             "report next to this file; `not measured` means the probe could not obtain it.", ""]
    if report["needs_user_action"]:
        lines += ["## Needs human action", ""]
        lines += [f"- **{item['source']}**: {item['action']}" for item in report["needs_user_action"]]
        lines.append("")
    lines += ["## Decision table", "",
              "| source | reachable | decision | basis | latency h | bytes/day (domain) | s/day | history start |",
              "|---|---|---|---|---|---|---|---|"]
    for s in report["sources"]:
        lines.append("| " + " | ".join(_cell(v) for v in (
            s["name"], s["reachable"], s["decision"], s["decision_basis"], s["latency_hours"],
            s["bytes_per_day_domain"], s["seconds_per_day"], s["history_start"])) + " |")
    lines.append("")
    for s in report["sources"]:
        lines += [f"## {s['name']}", ""]
        for label, key in (("URL pattern", "url_pattern"), ("Auth", "auth"), ("Format", "format"),
                           ("Error class", "error_class")):
            lines.append(f"- {label}: {_fmt(s[key])}")
        lines.append(f"- Variables: `{json.dumps(s['variables'], sort_keys=True)}`")
        if s["details"]:
            lines.append(f"- Details: `{json.dumps(s['details'], sort_keys=True)}`")
        lines += [f"- Note: {note}" for note in s["notes"]]
        lines.append("")
    if report["extras"]:
        lines += ["## Extras", "", f"```json\n{json.dumps(report['extras'], indent=2, sort_keys=True)}\n```", ""]
    return "\n".join(lines)


def write_report(report: dict, reports_dir, secrets: list[str]) -> tuple[Path, Path]:
    """Write `<stem>.json` (strict JSON) and `<stem>.md`; any known secret in the text is redacted first."""
    reports_dir = Path(reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    text_json = redact(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", secrets)
    json.loads(text_json)  # redaction must leave valid JSON
    text_md = redact(render_markdown(report), secrets)
    json_path, md_path = reports_dir / f"{REPORT_STEM}.json", reports_dir / f"{REPORT_STEM}.md"
    json_path.write_text(text_json, encoding="utf-8")
    md_path.write_text(text_md, encoding="utf-8")
    return md_path, json_path


# --------------------------------------------------------------------------- pure helpers
def hours_between(earlier: datetime, later: datetime) -> float:
    return (later - earlier).total_seconds() / 3600.0


def monsoon_days(start: date, end: date) -> int:
    """Calendar days from `start` to `end` inclusive that fall in June-September."""
    return sum(1 for k in range((end - start).days + 1) if 6 <= (start + timedelta(days=k)).month <= 9)


def extrapolate_history(seconds_per_day: float | None, bytes_per_day: float | None,
                        start: date = HISTORY_START, end: date = HISTORY_END) -> dict:
    """Total download time and volume for every day in [start, end] and for the June-September days only."""
    days_all = (end - start).days + 1
    days_monsoon = monsoon_days(start, end)
    out: dict = {"days_all": days_all, "days_monsoon": days_monsoon}
    for label, days in (("all", days_all), ("monsoon", days_monsoon)):
        out[f"hours_{label}"] = None if seconds_per_day is None else seconds_per_day * days / 3600.0
        out[f"gb_{label}"] = None if bytes_per_day is None else bytes_per_day * days / 1e9
    return out


def intensity_decision(hours_monsoon: float | None, gb_monsoon: float | None) -> str:
    """`use` only when BOTH monsoon-only estimates are known and under 12 h and 20 GB; unmeasured is `drop`."""
    if hours_monsoon is None or gb_monsoon is None:
        return "drop"
    return "use" if hours_monsoon < INTENSITY_MAX_HOURS and gb_monsoon < INTENSITY_MAX_GB else "drop"


def parse_cmr_time(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)


def imerg_index_range(lo: float, hi: float, axis: str) -> tuple[int, int]:
    """Inclusive pixel indices whose centres lie inside [lo, hi] on the global 0.1-degree IMERG grid."""
    origin = IMERG_ORIGIN[axis]
    return (math.ceil(round((lo - origin) / IMERG_STEP, 6)), math.floor(round((hi - origin) / IMERG_STEP, 6)))


def granule_info(entry: dict) -> dict:
    """Name, valid interval, CMR ingest time, size and access links of one CMR granule entry."""
    data_url = opendap_url = None
    for link in entry.get("links", []):
        href, rel = link.get("href", ""), link.get("rel", "")
        if rel.endswith("/data#") and "/data/" in href and href.startswith("https://") and data_url is None:
            data_url = href
        elif rel.endswith("/service#") and "opendap.earthdata.nasa.gov/collections" in href:
            opendap_url = href
    size_mib = entry.get("granule_size")
    return {"title": entry["title"], "file_name": entry["title"].split(":", 1)[-1],
            "time_start": parse_cmr_time(entry["time_start"]), "time_end": parse_cmr_time(entry["time_end"]),
            "ingested": parse_cmr_time(entry["updated"]),
            "size_bytes": None if size_mib is None else int(float(size_mib) * _MIB),
            "data_url": data_url, "opendap_url": opendap_url}


def classify_earthdata_access(status: int, urls: list[str], head: bytes) -> tuple[str, str | None]:
    """Judge an Earthdata download attempt from its final status, the redirect chain's URLs and the first bytes.

    Returns (`ok` | `app_not_authorized` | `unauthorized` | `unexpected_response`, resolution URL or None).
    An `error=access_denied` redirect means the account has not approved the data centre's application.
    """
    for url in urls:
        query = parse_qs(urlparse(url).query)
        if query.get("error", [""])[0] == "access_denied":
            return "app_not_authorized", (query.get("resolution_url") or [None])[0]
    if status == 200 and (head.startswith(HDF5_MAGIC) or head.startswith(NETCDF3_MAGIC)):
        return "ok", None
    if status in (401, 403):
        return "unauthorized", None
    return "unexpected_response", None


def preflight_earthdata(url: str) -> tuple[str, str | None]:
    """Open the download and look at the first bytes without transferring the file."""
    with requests.get(url, stream=True, timeout=60, headers=_HEADERS) as response:
        head = next(response.iter_content(chunk_size=8), b"")
        urls = [h.url for h in response.history] + [response.url]
        return classify_earthdata_access(response.status_code, urls, head)


def dmr_dim_order(dmr_xml: str, variable: str) -> list[str]:
    """Dimension names (without the leading '/') of `variable` in an OPeNDAP DAP4 DMR document."""
    for element in ET.fromstring(dmr_xml).iter():
        if element.attrib.get("name") == variable:
            dims = [child.attrib["name"].lstrip("/") for child in element if child.tag.endswith("}Dim")]
            if dims:
                return dims
    raise LookupError(f"variable {variable!r} has no dimensions in the DMR")


def dap4_constraint(variable_path: str, dims: list[str], lon_rng: tuple[int, int],
                    lat_rng: tuple[int, int]) -> str:
    """DAP4 constraint expression for one time step cropped to the pixel ranges, with its coordinate variables."""
    spans = {"time": "[0]", "lon": f"[{lon_rng[0]}:{lon_rng[1]}]", "lat": f"[{lat_rng[0]}:{lat_rng[1]}]"}
    group = variable_path.rsplit("/", 1)[0] + "/" if "/" in variable_path else ""
    name = variable_path.rsplit("/", 1)[-1]
    parts = [f"/{group}{name}" + "".join(spans[d.rsplit("/", 1)[-1]] for d in dims), f"/{group}time",
             f"/{group}lon[{lon_rng[0]}:{lon_rng[1]}]", f"/{group}lat[{lat_rng[0]}:{lat_rng[1]}]"]
    return "dap4.ce=" + ";".join(parts)


def open_dataset_any(path, group: str | None = None):
    """Open a netCDF/HDF5 file with the first xarray engine that works; returns (dataset, engine name)."""
    import xarray as xr
    tried = []
    for engine in READ_ENGINES:
        try:
            kwargs = {"group": group} if group and engine != "scipy" else {}
            return xr.open_dataset(path, engine=engine, **kwargs), engine
        except Exception as exc:  # engine not installed, or it cannot read this format
            tried.append(f"{engine}:{type(exc).__name__}")
    raise OSError("no xarray engine could open the file (" + ", ".join(tried) + ")")


def describe_precipitation(ds, domain: dict, point: tuple[float, float] = WAYANAD) -> dict:
    """Variable name, units, fill value, dims order, axis orientation, crop statistics and the value at `point`."""
    variable = next((n for n in PRECIP_NAMES if n in ds.data_vars), None)
    if variable is None:
        raise LookupError(f"none of {PRECIP_NAMES} in the file (variables: {sorted(ds.data_vars)})")
    da = ds[variable]
    lat, lon = ds["lat"].values, ds["lon"].values
    lat_asc, lon_asc = bool(lat[0] < lat[-1]), bool(lon[0] < lon[-1])
    lat_slice = slice(domain["lat_min"], domain["lat_max"]) if lat_asc else slice(domain["lat_max"], domain["lat_min"])
    lon_slice = slice(domain["lon_min"], domain["lon_max"]) if lon_asc else slice(domain["lon_max"], domain["lon_min"])
    cropped = da.sel(lat=lat_slice, lon=lon_slice)
    values = cropped.values.astype(float)
    nearest = da.sel(lat=point[0], lon=point[1], method="nearest")
    point_value = float(np.asarray(nearest.values).reshape(-1)[0])
    fill = da.encoding.get("_FillValue", da.attrs.get("_FillValue", da.attrs.get("missing_value")))
    return {
        "variable": variable, "units": da.attrs.get("units"), "fill_value": fill,
        "dims_order": list(da.dims), "shape_full": list(da.shape), "shape_domain": list(cropped.shape),
        "lat_ascending": lat_asc, "lon_ascending": lon_asc,
        "lat_range": [float(lat.min()), float(lat.max())], "lon_range": [float(lon.min()), float(lon.max())],
        "domain_valid_share": float(np.isfinite(values).mean()) if values.size else None,
        "point_lat": float(nearest["lat"]), "point_lon": float(nearest["lon"]),
        "point_value": point_value if math.isfinite(point_value) else None,
        "point_plausible": bool(math.isfinite(point_value) and 0.0 <= point_value <= 600.0),
    }


def read_precipitation(path, domain: dict, group: str | None = None) -> dict:
    ds, engine = open_dataset_any(path, group)
    try:
        return {"engine": engine, **describe_precipitation(ds, domain)}
    finally:
        ds.close()


def parse_nomads_listing(html: str) -> dict[int, tuple[datetime, str]]:
    """{forecast hour: (publication time UTC, size text)} from a NOMADS `atmos/` directory listing."""
    out: dict[int, tuple[datetime, str]] = {}
    pattern = re.compile(r'href="gfs\.t\d\dz\.pgrb2\.0p25\.f(\d{3})">[^<]*</a>\s+(\d{2})-([A-Za-z]{3})-(\d{4}) '
                         r'(\d{2}):(\d{2})\s+(\S+)')
    for hour, day, month, year, hh, mm, size in pattern.findall(html):
        out[int(hour)] = (datetime(int(year), _MONTHS[month], int(day), int(hh), int(mm), tzinfo=timezone.utc), size)
    return out


def nomads_filter_params(cycle: datetime, hour: int, domain: dict) -> dict:
    """grib-filter query for APCP at the surface, cropped to the domain, for one forecast hour."""
    hh = f"{cycle.hour:02d}"
    return {"dir": f"/gfs.{cycle:%Y%m%d}/{hh}/atmos", "file": f"gfs.t{hh}z.pgrb2.0p25.f{hour:03d}",
            "var_APCP": "on", "lev_surface": "on", "subregion": "", "leftlon": domain["lon_min"],
            "rightlon": domain["lon_max"], "toplat": domain["lat_max"], "bottomlat": domain["lat_min"]}


def parse_idx(text: str) -> list[dict]:
    """GRIB `.idx` lines -> records with byte offsets; `end` is the next record's offset minus one (None = to EOF)."""
    records = []
    for line in text.splitlines():
        parts = line.split(":")
        if len(parts) >= 7:
            records.append({"number": int(parts[0]), "start": int(parts[1]), "variable": parts[3],
                            "level": parts[4], "step": parts[5]})
    for current, following in zip(records, records[1:] + [None]):
        current["end"] = None if following is None else following["start"] - 1
    return records


def apcp_byte_ranges(records: list[dict]) -> list[tuple[int, int | None, str]]:
    return [(r["start"], r["end"], r["step"]) for r in records if r["variable"] == "APCP"]


def decode_grib(path) -> list[dict]:
    """Every message of a GRIB2 file with grid metadata and value statistics (needs `eccodes`)."""
    import eccodes
    messages = []
    with open(path, "rb") as handle:
        while True:
            gid = eccodes.codes_grib_new_from_file(handle)
            if gid is None:
                break
            try:
                values = eccodes.codes_get_values(gid)
                get = lambda key: eccodes.codes_get(gid, key)  # noqa: E731
                messages.append({
                    "short_name": get("shortName"), "step_range": get("stepRange"), "units": get("units"),
                    "ni": get("Ni"), "nj": get("Nj"),
                    "lat_first": get("latitudeOfFirstGridPointInDegrees"),
                    "lat_last": get("latitudeOfLastGridPointInDegrees"),
                    "lon_first": get("longitudeOfFirstGridPointInDegrees"),
                    "lon_last": get("longitudeOfLastGridPointInDegrees"),
                    "j_scans_positively": int(get("jScansPositively")), "packing": get("packingType"),
                    "mean": float(np.mean(values)), "min": float(np.min(values)), "max": float(np.max(values)),
                    "values": values})
            finally:
                eccodes.codes_release(gid)
    return messages


def crop_global_025(values: np.ndarray, ni: int, nj: int, lat_first: float, domain: dict) -> np.ndarray:
    """Domain crop of a global 0.25-degree field stored north-to-south from lon 0 (the AWS archive layout)."""
    field = np.asarray(values).reshape(nj, ni)
    north_row = int(round((lat_first - domain["lat_max"]) / 0.25))
    south_row = int(round((lat_first - domain["lat_min"]) / 0.25))
    west, east = int(round(domain["lon_min"] / 0.25)), int(round(domain["lon_max"] / 0.25))
    return field[north_row:south_row + 1, west:east + 1]


def _summary(messages: list[dict]) -> list[dict]:
    return [{k: v for k, v in m.items() if k != "values"} for m in messages]


# --------------------------------------------------------------------------- probe context and shared fetchers
@dataclass
class Context:
    domain: dict
    now: datetime
    work_dir: Path
    manifest: Manifest
    audit_cfg: dict

    def rel(self, path) -> str:
        return Path(path).resolve().relative_to(PROJECT_ROOT).as_posix()


def _get(url: str, **kwargs) -> requests.Response:
    kwargs.setdefault("timeout", 60)
    headers = {**_HEADERS, **kwargs.pop("headers", {})}
    return requests.get(url, headers=headers, **kwargs)


def _cmr_collection(short_name: str) -> str:
    entries = fetch_json(CMR + "collections.json", params={"short_name": short_name, "version": "07"},
                         retries=2, timeout=40)["feed"]["entry"]
    if not entries:
        raise LookupError(f"no CMR collection for {short_name} version 07")
    return entries[0]["id"]


def _cmr_granules(collection_id: str, sort: str = "-start_date", n: int = 1, temporal: str | None = None) -> list[dict]:
    params = {"collection_concept_id": collection_id, "sort_key": sort, "page_size": n}
    if temporal:
        params["temporal"] = temporal
    entries = fetch_json(CMR + "granules.json", params=params, retries=2, timeout=40)["feed"]["entry"]
    return [granule_info(e) for e in entries]


def _day_window(day: date) -> str:
    return f"{day.isoformat()}T00:00:00Z,{day.isoformat()}T23:59:59Z"


def _timed_download(ctx: Context, url: str, dest: Path, source: str) -> dict:
    started = time.monotonic()
    download(url, dest, ctx.manifest, source, _LICENCE, retries=1, timeout=100, force=True)
    seconds = time.monotonic() - started
    with dest.open("rb") as handle:
        head = handle.read(8)
    if not (head.startswith(HDF5_MAGIC) or head.startswith(NETCDF3_MAGIC)):
        dest.unlink(missing_ok=True)
        raise ValueError("downloaded file is not netCDF/HDF5")
    return {"bytes": dest.stat().st_size, "seconds": seconds}


def _fetch_imerg_subset(ctx: Context, granule: dict, dest: Path, variable_path: str, source: str) -> dict:
    """Try the OPeNDAP subset patterns in order; returns the first that yields a netCDF/HDF5 file."""
    lon_rng = imerg_index_range(ctx.domain["lon_min"], ctx.domain["lon_max"], "lon")
    lat_rng = imerg_index_range(ctx.domain["lat_min"], ctx.domain["lat_max"], "lat")
    dims = ["time", "lon", "lat"]
    try:
        dmr = _get(granule["opendap_url"] + ".dmr", timeout=60)
        dims = dmr_dim_order(dmr.text, variable_path.rsplit("/", 1)[-1])
    except Exception:  # the assumed IMERG order (time, lon, lat) is used and verified on the downloaded file
        pass
    ce = dap4_constraint(variable_path, dims, lon_rng, lat_rng)
    attempts = []
    for label, suffix in (("hyrax_cloud_dap4_dap.nc4", ".dap.nc4"), ("hyrax_cloud_dap4_nc4", ".nc4")):
        try:
            stats = _timed_download(ctx, f"{granule['opendap_url']}{suffix}?{ce}", dest, source)
            return {"pattern": label, "suffix": suffix, "constraint": ce, "dims_assumed_or_read": dims,
                    "pixels": {"lon": lon_rng, "lat": lat_rng}, **stats}
        except Exception as exc:
            attempts.append(f"{label}:{type(exc).__name__}")
    return {"pattern": None, "failed_attempts": attempts}


def _access_failure(state: str, resolution: str | None) -> tuple[str, str]:
    if state == "app_not_authorized":
        return (f"approve the 'NASA GESDISC DATA ARCHIVE' application on the Earthdata account: open "
                f"{resolution or 'https://urs.earthdata.nasa.gov/approve_app?client_id=e2WVk8Pw6weeLUKZYOxvTQ'} "
                "while logged in (Earthdata profile > Applications > Authorized Apps > Approve More Applications), "
                "then rerun `python -m aetherguard.live.probe`",
                "login works but the GES DISC application is not approved")
    return ("check the Earthdata credentials in the netrc file and the account's application approvals",
            f"download refused ({state})")


# --------------------------------------------------------------------------- IMERG probes
def probe_imerg_daily(result: dict, deadline: float, ctx: Context, short_name: str, decision: str, role: str) -> None:
    result.update(
        url_pattern=("CMR discovery https://cmr.earthdata.nasa.gov/search/granules.json"
                     "?collection_concept_id=..., then https://opendap.earthdata.nasa.gov/collections/"
                     "<concept id>/granules/<GranuleUR>.dap.nc4?dap4.ce=<constraint> (subset) "
                     "or https://data.gesdisc.earthdata.nasa.gov/data/GPM_L3/"
                     f"{short_name}.07/<yyyy>/<mm>/<file>.nc4 (full file); the file name carries a version letter "
                     "(V07B for old days, V07C for new) so it must be taken from CMR, never constructed"),
        auth="Earthdata login (netrc) and the account's approval of the GES DISC application",
        format="netCDF4/HDF5, one file per UTC day, global 0.1 degree")
    cid = _cmr_collection(short_name)
    newest = _cmr_granules(cid, n=5)
    oldest = _cmr_granules(cid, sort="start_date", n=1)[0]
    historical = _cmr_granules(cid, temporal=_day_window(IMERG_HISTORICAL_DAY), n=1)[0]
    latencies = [hours_between(g["time_end"], g["ingested"]) for g in newest]
    result.update(reachable=True, history_start=oldest["time_start"].date().isoformat(),
                  latency_hours=latencies[0],
                  bytes_per_day_domain=None, seconds_per_day=None)
    result["details"] = {
        "collection_concept_id": cid, "role": role,
        "newest_day": newest[0]["time_start"].date().isoformat(), "newest_file": newest[0]["file_name"],
        "historical_file": historical["file_name"],
        "latency_hours_last5": latencies, "latency_hours_median": statistics.median(latencies),
        "full_file_bytes_cmr": newest[0]["size_bytes"], "latency_basis": "CMR ingest time minus end of the UTC day",
        "probe_time_utc": ctx.now.isoformat()}
    result["notes"] = [f"CMR first granule of V07 is {result['history_start']} (TRMM era included); "
                       "the project needs 2006-10-01 onwards"]
    state, resolution = preflight_earthdata(newest[0]["data_url"])
    result["details"]["data_access"] = state
    if state != "ok":
        action, why = _access_failure(state, resolution)
        result.update(needs_user_action=action, decision=decision,
                      decision_basis=f"provisional: format, size and value checks not run ({why})")
        result["notes"].append(f"data access blocked: {why}; latency and history come from CMR only")
        return
    days = []
    for label, granule in (("historical", historical), ("newest", newest[0])):
        if time.monotonic() > deadline - 30:
            result["notes"].append(f"time box reached before the {label} day")
            break
        folder = ctx.work_dir / short_name
        subset = _fetch_imerg_subset(ctx, granule, folder / f"subset_{granule['file_name']}", "precipitation",
                                     f"GES DISC {short_name} subset")
        entry: dict = {"which": label, "day": granule["time_start"].date().isoformat(), "subset": subset}
        if subset["pattern"]:
            path = folder / f"subset_{granule['file_name']}"
        else:
            full = _timed_download(ctx, granule["data_url"], folder / granule["file_name"],
                                   f"GES DISC {short_name} full file")
            entry["full_file"] = full
            path = folder / granule["file_name"]
        entry["array"] = read_precipitation(path, ctx.domain)
        days.append(entry)
    result["details"]["days"] = days
    if days:
        best = days[-1]
        path_stats = best["subset"] if best["subset"]["pattern"] else best["full_file"]
        result["bytes_per_day_domain"], result["seconds_per_day"] = path_stats["bytes"], path_stats["seconds"]
        result["variables"] = {"precipitation": {k: best["array"][k] for k in (
            "variable", "units", "fill_value", "dims_order", "lat_ascending", "lon_ascending")}}
    result["decision_basis"] = "measured"
    result["decision"] = decision


def probe_imerg_halfhourly(result: dict, deadline: float, ctx: Context) -> None:
    result.update(
        url_pattern=("CMR discovery for GPM_3IMERGHHL.07 (48 granules per UTC day), then "
                     "https://opendap.earthdata.nasa.gov/collections/<concept id>/granules/<GranuleUR>.dap.nc4"
                     "?dap4.ce=/Grid/precipitation[...] (subset)"),
        auth="Earthdata login (netrc) and the account's approval of the GES DISC application",
        format="HDF5 (group /Grid), one file per half hour, global 0.1 degree")
    cid = _cmr_collection("GPM_3IMERGHHL")
    day_granules = _cmr_granules(cid, sort="start_date", n=60, temporal=_day_window(IMERG_HISTORICAL_DAY))
    newest = _cmr_granules(cid, n=1)[0]
    oldest = _cmr_granules(cid, sort="start_date", n=1)[0]
    full_bytes = sum(g["size_bytes"] or 0 for g in day_granules)
    full_extra = extrapolate_history(None, full_bytes)
    result.update(reachable=True, history_start=oldest["time_start"].date().isoformat(),
                  latency_hours=hours_between(newest["time_end"], newest["ingested"]))
    result["details"] = {
        "collection_concept_id": cid, "granules_on_2018_08_15": len(day_granules),
        "full_files_bytes_per_day": full_bytes, "full_files_extrapolation": full_extra,
        "newest_file": newest["file_name"], "latency_basis": "CMR ingest time minus end of the half hour",
        "probe_time_utc": ctx.now.isoformat()}
    result["notes"] = [
        f"Without a subset every half-hourly file is global (about {full_bytes / len(day_granules) / _MIB:.1f} MiB): "
        f"{full_extra['gb_monsoon']:.0f} GB for the June-September days of 2007-2018 and "
        f"{full_extra['gb_all']:.0f} GB for every day, so the full-file route cannot meet the 20 GB limit"
        if day_granules else "CMR returned no half-hourly granule for 2018-08-15"]
    state, resolution = preflight_earthdata(day_granules[0]["data_url"])
    result["details"]["data_access"] = state
    if state != "ok":
        action, why = _access_failure(state, resolution)
        result.update(needs_user_action=action, decision=intensity_decision(None, None),
                      decision_basis=f"unmeasured, so dropped by the rule (needs a measured time and size): {why}")
        return
    measured = []
    for granule in day_granules[:3]:
        if time.monotonic() > deadline - 25:
            break
        dest = ctx.work_dir / "GPM_3IMERGHHL" / f"subset_{granule['file_name']}"
        subset = _fetch_imerg_subset(ctx, granule, dest, "Grid/precipitation", "GES DISC GPM_3IMERGHHL subset")
        if not subset["pattern"]:
            result["details"]["subset_failed_attempts"] = subset["failed_attempts"]
            break
        measured.append({**subset, "array": read_precipitation(dest, ctx.domain, group="Grid")})
    result["details"]["measured_granules"] = measured
    if measured:
        per_day_s = statistics.mean(m["seconds"] for m in measured) * len(day_granules)
        per_day_b = statistics.mean(m["bytes"] for m in measured) * len(day_granules)
        extra = extrapolate_history(per_day_s, per_day_b)
        result.update(seconds_per_day=per_day_s, bytes_per_day_domain=per_day_b)
        result["details"]["subset_extrapolation"] = extra
        result["variables"] = {"precipitation": {k: measured[0]["array"][k] for k in (
            "variable", "units", "fill_value", "dims_order", "lat_ascending", "lon_ascending")}}
        result.update(decision=intensity_decision(extra["hours_monsoon"], extra["gb_monsoon"]),
                      decision_basis="measured: rule is use only when June-September download is under "
                                     f"{INTENSITY_MAX_HOURS:g} h and {INTENSITY_MAX_GB:g} GB")
    else:
        result.update(decision="drop", decision_basis="unmeasured: no subset pattern worked")


# --------------------------------------------------------------------------- GFS probes
def _latest_complete_nomads_cycle(ctx: Context) -> dict:
    prod = _get(NOMADS_PROD)
    prod.raise_for_status()
    days = sorted(set(re.findall(r'href="gfs\.(\d{8})/"', prod.text)), reverse=True)[:2]
    for day in days:
        for cycle in (18, 12, 6, 0):
            listing = _get(f"{NOMADS_PROD}gfs.{day}/{cycle:02d}/atmos/")
            if listing.status_code != 200:
                continue
            files = parse_nomads_listing(listing.text)
            if 96 in files:
                start = datetime(int(day[:4]), int(day[4:6]), int(day[6:]), cycle, tzinfo=timezone.utc)
                published = {h: files[h][0] for h in (3, 24, 96) if h in files}
                return {"cycle": start, "f096_published": files[96][0],
                        "latency_hours": hours_between(start, files[96][0]),
                        "published_by_hour": {str(h): t.isoformat() for h, t in published.items()},
                        "f096_size": files[96][1]}
    raise LookupError("no complete GFS cycle found on NOMADS")


def probe_gfs_grib_filter(result: dict, deadline: float, ctx: Context) -> None:
    result.update(
        url_pattern=(f"{NOMADS_FILTER}?dir=/gfs.{{YYYYMMDD}}/{{HH}}/atmos&file=gfs.t{{HH}}z.pgrb2.0p25.f{{FFF}}"
                     "&var_APCP=on&lev_surface=on&subregion=&leftlon=72&rightlon=98&toplat=36&bottomlat=8"),
        auth="none", format="GRIB2 (simple packing), cropped to the domain by the server, 0.25 degree",
        history_start="about 10 days back (directory listing shows the last 10 days)")
    cycle = _latest_complete_nomads_cycle(ctx)
    result.update(reachable=True, latency_hours=cycle["latency_hours"])
    details = {"cycle_utc": cycle["cycle"].isoformat(), "f096_published_utc": cycle["f096_published"].isoformat(),
               "published_by_hour": cycle["published_by_hour"],
               "hours_requested": f"{GFS_FORECAST_HOURS[0]}..{GFS_FORECAST_HOURS[-1]} step 3",
               "latency_basis": "publication of f096 minus cycle time"}
    result["details"] = details
    folder = ctx.work_dir / "gfs_nomads"
    folder.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update(_HEADERS)
    per_request, cumulative_means, bad = [], {}, []
    for hour in GFS_FORECAST_HOURS:
        if time.monotonic() > deadline:
            details["stopped_at_hour"] = hour
            break
        started = time.monotonic()
        response = session.get(NOMADS_FILTER, params=nomads_filter_params(cycle["cycle"], hour, ctx.domain), timeout=40)
        seconds = time.monotonic() - started
        if response.status_code != 200 or not response.content.startswith(b"GRIB"):
            bad.append(hour)
            continue
        path = folder / f"f{hour:03d}.grib2"
        path.write_bytes(response.content)
        per_request.append({"hour": hour, "bytes": len(response.content), "seconds": seconds})
        messages = decode_grib(path)
        if hour in (3, 24, 96):
            details[f"messages_f{hour:03d}"] = _summary(messages)
        cumulative = [m for m in messages if m["step_range"] == f"0-{hour}"]
        if cumulative:
            cumulative_means[hour] = cumulative[0]["mean"]
    details["failed_hours"] = bad
    fetched = len(per_request)
    mean_s = statistics.mean(r["seconds"] for r in per_request)
    mean_b = statistics.mean(r["bytes"] for r in per_request)
    hours_values = [cumulative_means[h] for h in sorted(cumulative_means)]
    details.update(
        requests_made=fetched, seconds_total=sum(r["seconds"] for r in per_request),
        bytes_total=sum(r["bytes"] for r in per_request), mean_seconds_per_request=mean_s,
        cumulative_domain_mean_mm_by_hour=cumulative_means,
        cumulative_mean_non_decreasing=all(b >= a - 1e-9 for a, b in zip(hours_values, hours_values[1:])),
        hourly_request_extrapolation={"requests": 96, "seconds": mean_s * 96, "bytes": mean_b * 96},
        rate_limit_note="NOMADS asks for at most 120 requests per minute")
    result.update(bytes_per_day_domain=mean_b * len(GFS_FORECAST_HOURS),
                  seconds_per_day=mean_s * len(GFS_FORECAST_HOURS),
                  variables={"APCP": {"units": "kg m-2 (mm)", "messages_per_file": 2,
                                      "note": "bucket accumulation (e.g. 6-9) and cumulative 0-H; use the 0-H one"}})
    result["notes"] = [
        "bytes/s per day are for ONE cycle, forecast hours 3..96 step 3 (32 requests); f000 has no APCP",
        "each file holds two APCP messages: the running bucket (resets every 6 h) and the cumulative 0-H total",
        "the grid is south-to-north (jScansPositively=1), latitude 8.0 first, longitude 72.0 first, 113 x 105 points"]
    result.update(decision="use", decision_basis="measured: live path for the latest cycle")


def probe_gfs_opendap(result: dict, deadline: float, ctx: Context) -> None:
    result.update(url_pattern="https://nomads.ncep.noaa.gov/dods/gfs_0p25/gfs{YYYYMMDD}/gfs_0p25_{HH}z.{das|dds|ascii}",
                  auth="none", format="OPeNDAP (DAP2)")
    cycle = _latest_complete_nomads_cycle(ctx)
    start = cycle["cycle"]
    url = f"https://nomads.ncep.noaa.gov/dods/gfs_0p25/gfs{start:%Y%m%d}/gfs_0p25_{start.hour:02d}z.das"
    response = _get(url, timeout=40)
    retired = "retired" in response.text.lower()
    result["details"] = {"http_status": response.status_code, "page_says_retired": retired,
                         "cycle_utc": cycle["cycle"].isoformat()}
    result.update(reachable=not retired and response.status_code == 200, decision="drop",
                  decision_basis="measured: service answers with a retirement notice" if retired
                  else "measured: no usable OPeNDAP response")
    result["notes"] = ["NOMADS OPeNDAP is retired (the response cites NWS Service Change Notice 25-81); "
                       "the grib filter is the replacement"] if retired else []


def _list_aws_prefixes(prefix: str) -> list[str]:
    response = _get(GFS_AWS, params={"list-type": "2", "delimiter": "/", "prefix": prefix, "max-keys": "5"})
    response.raise_for_status()
    return re.findall(r"<Prefix>([^<]+)</Prefix>", response.text)


def probe_gfs_aws_archive(result: dict, deadline: float, ctx: Context) -> None:
    day, hh, hour = GFS_ARCHIVE_DAY, GFS_ARCHIVE_CYCLE, GFS_ARCHIVE_HOUR
    key = f"gfs.{day:%Y%m%d}/{hh:02d}/atmos/gfs.t{hh:02d}z.pgrb2.0p25.f{hour:03d}"
    result.update(
        url_pattern=(f"{GFS_AWS}gfs.{{YYYYMMDD}}/{{HH}}/atmos/gfs.t{{HH}}z.pgrb2.0p25.f{{FFF}} (+ .idx; HTTP Range "
                     "for the APCP records only); before 2021-03-23 the path has no 'atmos/' level"),
        auth="none (public bucket)", format="GRIB2 (complex packing, spatial differencing), global 0.25 degree")
    started = time.monotonic()
    idx = _get(f"{GFS_AWS}{key}.idx")
    idx.raise_for_status()
    ranges = apcp_byte_ranges(parse_idx(idx.text))
    head = requests.head(f"{GFS_AWS}{key}", headers=_HEADERS, timeout=40)
    folder = ctx.work_dir / "gfs_aws"
    folder.mkdir(parents=True, exist_ok=True)
    pieces, got = [], []
    for start, end, step in ranges:
        header = {"Range": f"bytes={start}-{'' if end is None else end}"}
        part = _get(f"{GFS_AWS}{key}", headers=header)
        if part.status_code != 206:
            raise ValueError(f"range request returned HTTP {part.status_code}")
        pieces.append(part.content)
        got.append({"step": step, "bytes": len(part.content)})
    seconds = time.monotonic() - started
    path = folder / "apcp.grib2"
    path.write_bytes(b"".join(pieces))
    messages = decode_grib(path)
    cumulative = next(m for m in messages if m["step_range"].startswith("0-"))
    crop = crop_global_025(cumulative["values"], cumulative["ni"], cumulative["nj"],
                           cumulative["lat_first"], ctx.domain)
    result.update(reachable=True, history_start=_aws_first_day(_list_aws_prefixes("gfs.")))
    last_modified = head.headers.get("Last-Modified")
    published = datetime.strptime(last_modified, "%a, %d %b %Y %H:%M:%S GMT").replace(tzinfo=timezone.utc) \
        if last_modified else None
    cycle_time = datetime(day.year, day.month, day.day, hh, tzinfo=timezone.utc)
    result["latency_hours"] = None if published is None else hours_between(cycle_time, published)
    needed = [3, 27, 51, 75]
    file_bytes = sum(g["bytes"] for g in got if g["step"].startswith("0-"))
    result.update(
        bytes_per_day_domain=file_bytes * len(needed), seconds_per_day=seconds * len(needed),
        variables={"APCP": {"units": "kg m-2 (mm)", "records_per_file": len(ranges),
                            "records": got, "global_grid": [cumulative["nj"], cumulative["ni"]],
                            "lat_first": cumulative["lat_first"], "lon_first": cumulative["lon_first"],
                            "j_scans_positively": cumulative["j_scans_positively"],
                            "domain_crop_shape": list(crop.shape), "domain_crop_mean_mm": float(crop.mean())}})
    result["details"] = {
        "file": key, "full_file_bytes": int(head.headers.get("Content-Length", 0)),
        "idx_records_apcp": [{"start": s, "end": e, "step": st} for s, e, st in ranges],
        "decoded_messages": _summary(messages), "seconds_one_file": seconds,
        "latency_basis": "S3 Last-Modified of the file minus cycle time (availability delay, not a valid-time lag)",
        "files_per_day_for_imd_day_totals": needed}
    result["notes"] = [
        "the archive cannot be cropped server-side: each APCP record is a global field (about 0.4-0.5 MB) cropped "
        "after decoding to rows 216..328 and columns 288..392 of the 721 x 1440 grid",
        "bytes/s per day assume the 00Z cycle and the four files whose cumulative totals bound the IMD days "
        "(f003, f027, f051, f075); the cumulative record is the one whose step starts with '0-' (named "
        "'0-1 day acc fcst' at f024); seconds are measured for the idx plus both APCP records, so slightly high",
        "the grid is north-to-south (jScansPositively=0), longitude 0..359.75"]
    result.update(decision="use", decision_basis="measured: archive path for 2021-2024 (and live fallback)")


def _aws_first_day(prefixes: list[str]) -> str | None:
    """First `gfs.YYYYMMDD/` directory in a bucket listing, as an ISO date."""
    days = sorted(p for p in prefixes if re.fullmatch(r"gfs\.\d{8}/", p))
    return None if not days else f"{days[0][4:8]}-{days[0][8:10]}-{days[0][10:12]}"


def decoder_status() -> dict:
    """Which GRIB2 decoders import on this machine."""
    status = {}
    for name in ("eccodes", "cfgrib"):
        try:
            module = __import__(name)
            status[name] = {"importable": True, "version": str(getattr(module, "__version__", "unknown"))}
        except Exception as exc:
            status[name] = {"importable": False, "error_class": type(exc).__name__}
    return status


def reader_status() -> dict:
    """Which netCDF/HDF5 readers xarray could use for IMERG are importable in this environment."""
    status = {}
    for name in ("netCDF4", "h5netcdf", "h5py", "scipy"):
        try:
            module = __import__(name)
            status[name] = {"importable": True, "version": str(getattr(module, "__version__", "unknown"))}
        except Exception as exc:
            status[name] = {"importable": False, "error_class": type(exc).__name__}
    return status


# --------------------------------------------------------------------------- IMD real-time and GHCN-Daily
IMD_RAIN_URL = "https://imdpune.gov.in/cmpg/Realtimedata/Rainfall/rain.php"
IMD_FILE_BYTES = 129 * 135 * 4


def _post_imd_day(day: date, dest: Path, attempts: int = 2, timeout: float = 35.0) -> bool:
    """POST for one IMD day with a timeout and a retry; True when the file was written, False when not yet published.

    `imdlib.get_real_data` does the same POST without a timeout, so a stalled server hangs it.
    """
    for attempt in range(attempts):
        try:
            response = requests.post(IMD_RAIN_URL, data={"rain": f"{day:%d%m%Y}"}, headers=_HEADERS, timeout=timeout)
            response.raise_for_status()
        except requests.RequestException:
            if attempt == attempts - 1:
                raise
            continue
        if not response.content:
            return False
        if len(response.content) != IMD_FILE_BYTES:
            raise ValueError(f"unexpected file size {len(response.content)}")
        dest.write_bytes(response.content)
        return True
    return False


def _read_imd_day(day: date, folder: Path, domain: dict) -> dict:
    """Fetch one real-time IMD day (POST with a timeout, then imdlib reads it) and describe the grid."""
    import imdlib
    folder.mkdir(parents=True, exist_ok=True)
    raw_path = folder / f"rain_ind0.25_{day:%y_%m_%d}.grd"
    raw_path.unlink(missing_ok=True)
    started = time.monotonic()
    try:
        published = _post_imd_day(day, raw_path)
    except Exception as exc:
        return {"day": day.isoformat(), "ok": False, "error_class": type(exc).__name__,
                "seconds": time.monotonic() - started}
    seconds = time.monotonic() - started
    if not published:
        return {"day": day.isoformat(), "ok": False, "error_class": "NotPublished", "seconds": seconds}
    with contextlib.redirect_stdout(io.StringIO()):
        data = imdlib.open_real_data("rain", day.isoformat(), day.isoformat(), str(folder))
    rain = data.get_xarray()["rain"]
    grid = rain.values[0]
    raw = np.fromfile(raw_path, dtype="<f4")
    lat, lon = rain["lat"].values, rain["lon"].values
    in_domain = rain.sel(lat=slice(domain["lat_min"], domain["lat_max"]),
                         lon=slice(domain["lon_min"], domain["lon_max"]))
    point = rain.sel(lat=11.5, lon=76.25, method="nearest").values.reshape(-1)[0]
    return {
        "day": day.isoformat(), "ok": True, "seconds": seconds, "file_bytes": raw_path.stat().st_size,
        "dims_order": list(rain.dims), "shape": list(grid.shape), "units": rain.attrs.get("units"),
        "lat_range": [float(lat.min()), float(lat.max())], "lon_range": [float(lon.min()), float(lon.max())],
        "lat_ascending": bool(lat[0] < lat[-1]), "valid_cells": int(np.isfinite(grid).sum()),
        "valid_cells_in_domain": int(np.isfinite(in_domain.values).sum()),
        "missing_sentinel_cells_in_file": int((raw == -999.0).sum()), "file_cells": int(raw.size),
        "max_mm": float(np.nanmax(grid)) if np.isfinite(grid).any() else None,
        "wayanad_nearest_mm": float(point) if np.isfinite(point) else None,
        "imdlib_data_attribute_shape": list(data.data.shape)}


def probe_imd_realtime(result: dict, deadline: float, ctx: Context) -> None:
    result.update(
        url_pattern=(f"POST {IMD_RAIN_URL} with form field rain=DDMMYYYY (what "
                     "imdlib.get_real_data('rain', 'YYYY-MM-DD', 'YYYY-MM-DD', file_dir=...) does), "
                     "then imdlib.open_real_data(...).get_xarray()"),
        auth="none", format="IMD binary .grd: little-endian float32, 129 lat x 135 lon, 0.25 degree, -999 = missing")
    today = ctx.now.date()
    folder = ctx.work_dir / "imd_realtime"
    attempts, newest = [], None
    for back in (1, 2):
        if time.monotonic() > deadline - 30:
            break
        outcome = _read_imd_day(today - timedelta(days=back), folder, ctx.domain)
        attempts.append(outcome)
        if outcome["ok"]:
            newest = outcome
            break
    probe_today = None
    if newest is not None and time.monotonic() < deadline - 45:
        probe_today = _read_imd_day(today, folder, ctx.domain)
        attempts.append(probe_today)
    result["details"] = {"attempts": attempts, "probe_time_utc": ctx.now.isoformat()}
    if newest is None:
        result.update(reachable=False, error_class="NoPublishedDay", decision="drop",
                      decision_basis="measured: neither yesterday nor the day before could be read")
        return
    latest = probe_today if probe_today and probe_today["ok"] else newest
    valid_end = datetime.fromisoformat(latest["day"]).replace(hour=3, tzinfo=timezone.utc)  # 08:30 IST of the day
    result.update(
        reachable=True, bytes_per_day_domain=newest["file_bytes"], seconds_per_day=newest["seconds"],
        latency_hours=hours_between(valid_end, ctx.now),
        variables={"rain": {"units": newest["units"], "fill_value": -999.0, "dims_order": newest["dims_order"],
                            "lat_ascending": newest["lat_ascending"], "lat_range": newest["lat_range"],
                            "lon_range": newest["lon_range"], "valid_cells": newest["valid_cells"],
                            "file_cells": newest["file_cells"]}},
        decision="use", decision_basis="measured: second-opinion rain for the alert engine")
    result["notes"] = [
        f"newest published day at probe time: {latest['day']}; latency is an UPPER bound (probe time minus 03:00 UTC "
        "of that IMD day) because the service gives no publication timestamp",
        "a day that is not yet published answers HTTP 200 with an empty body (imdlib then raises a bare Exception)",
        "the server is slow and flaky (single requests took 15-65 s, with resets and read timeouts); "
        "imdlib.get_real_data has no timeout and hung for 100 s once, so this probe POSTs with a timeout and one "
        "retry and uses imdlib only to read the file (get_real_data itself worked when the server answered)",
        "use `get_xarray()` ((time, lat, lon), latitude ascending from 6.5 N); imdlib's `.data` array is "
        "(time, lon, lat), the transpose of the file layout",
        "only the India land mask is valid (about 29% of the grid); every other cell is the -999 sentinel",
        "no history is offered here; the project already holds the yearly final grids"]


def select_ghcn_stations(audit_cfg: dict, root: Path, count: int = GHCN_STATIONS):
    """The project's GHCN-Daily station selection and `count` of them spread evenly through it."""
    from ..audit.ghcnd import select_stations
    g, raw = audit_cfg["ghcnd"], root / "raw" / "ghcnd"
    selected = select_stations(
        (raw / "ghcnd-inventory.txt").read_text(encoding="ascii", errors="replace").splitlines(),
        (raw / "ghcnd-stations.txt").read_text(encoding="ascii", errors="replace").splitlines(),
        g["countries"], "PRCP", g["first_year_max"], g["last_year_min"], g["upland_min_elev_m"])
    return selected, selected["id"].iloc[::max(1, len(selected) // count)][:count].tolist()


def parse_ncei_rows(rows: list[dict]) -> dict:
    """Newest PRCP date per station and the non-blank quality-flag counts from NCEI access-service JSON rows."""
    newest: dict[str, str] = {}
    flags: dict[str, int] = {}
    n_prcp = 0
    for row in rows:
        if not str(row.get("PRCP", "")).strip():
            continue
        n_prcp += 1
        station = row["STATION"]
        newest[station] = max(newest.get(station, ""), row["DATE"])
        parts = (row.get("PRCP_ATTRIBUTES") or ",,").split(",")
        qflag = parts[1].strip() if len(parts) > 1 else ""
        if qflag:
            flags[qflag] = flags.get(qflag, 0) + 1
    return {"n_rows": len(rows), "n_prcp": n_prcp, "newest_by_station": newest, "qflag_counts": flags}


def probe_ghcnd_recent(result: dict, deadline: float, ctx: Context) -> None:
    result.update(
        url_pattern=(f"{NCEI_ACCESS}?dataset=daily-summaries&stations=<ids>&dataTypes=PRCP&startDate=YYYY-MM-DD"
                     "&endDate=YYYY-MM-DD&format=json&includeAttributes=true&units=metric"),
        auth="none", format="JSON array, one object per station-day: DATE, STATION, PRCP (string), PRCP_ATTRIBUTES")
    selected, ids = select_ghcn_stations(ctx.audit_cfg, data_root())
    end = ctx.now.date() - timedelta(days=1)
    start = end - timedelta(days=GHCN_DAYS - 1)
    params = {"dataset": "daily-summaries", "stations": ",".join(ids), "dataTypes": "PRCP",
              "startDate": start.isoformat(), "endDate": end.isoformat(), "format": "json",
              "includeAttributes": "true", "units": "metric"}
    started = time.monotonic()
    rows = fetch_json(NCEI_ACCESS, params=params, retries=2, timeout=90)
    seconds = time.monotonic() - started
    parsed = parse_ncei_rows(rows)
    newest = parsed["newest_by_station"]
    latencies = [hours_between(datetime.fromisoformat(d).replace(tzinfo=timezone.utc) + timedelta(days=1), ctx.now)
                 for d in newest.values()]
    response_bytes = len(json.dumps(rows))
    result.update(reachable=True, history_start="1990 or earlier per station (GHCN-Daily inventory)")
    result["details"] = {
        "stations_requested": ids, "window": [start.isoformat(), end.isoformat()], "request_seconds": seconds,
        "response_bytes": response_bytes, "rows": parsed["n_rows"], "rows_with_prcp": parsed["n_prcp"],
        "stations_with_prcp": len(newest), "newest_date_by_station": newest,
        "qflag_counts_nonblank": parsed["qflag_counts"],
        "attributes_field": "PRCP_ATTRIBUTES = 'measurement flag,quality flag,source flag'",
        "inventory_stations_selected": int(len(selected)),
        "probe_time_utc": ctx.now.isoformat()}
    if latencies:
        result["latency_hours"] = statistics.median(latencies)
        result["details"]["latency_hours_min"] = min(latencies)
        result["details"]["latency_hours_max"] = max(latencies)
    positive = next((r for r in rows if str(r.get("PRCP", "")).strip() and float(r["PRCP"]) > 0), None)
    if positive is not None:
        default = fetch_json(NCEI_ACCESS, retries=2, timeout=60, params={
            **params, "stations": positive["STATION"], "units": "standard",
            "startDate": positive["DATE"], "endDate": positive["DATE"]})
        result["details"]["default_units_check"] = {
            "units_metric": positive["PRCP"], "units_default": default[0]["PRCP"].strip() if default else None}
    result.update(
        bytes_per_day_domain=response_bytes / GHCN_DAYS, seconds_per_day=seconds / GHCN_DAYS,
        variables={"PRCP": {"units_with_units_metric": "mm", "units_default": "tenths of mm (raw .dly scale)",
                            "missing": "row has no PRCP key", "fill_value": None}},
        decision="use", decision_basis="measured: integrity-engine input; coverage and latency are the limits")
    result["notes"] = [
        f"{len(newest)} of {len(ids)} requested stations returned any PRCP in the window; the others returned "
        "rows without PRCP or nothing",
        "latency_hours is the MEDIAN over stations with data of (probe time minus the end of the newest reported day)",
        "quality flags come back in PRCP_ATTRIBUTES (second field); an empty flag means the value passed the checks",
        "without `units=metric` the service returns tenths of mm, space-padded (for example '   10' for 1.0 mm)",
        "bytes/s per day are the whole 10-station, 120-day request divided by 120"]


# --------------------------------------------------------------------------- registry and command line
def build_probes(ctx: Context) -> dict[str, Callable[[dict, float], None]]:
    return {
        "imerg_late_daily": lambda r, d: probe_imerg_daily(r, d, ctx, "GPM_3IMERGDL", "use", "primary model rain"),
        "imerg_early_daily": lambda r, d: probe_imerg_daily(r, d, ctx, "GPM_3IMERGDE", "fallback",
                                                            "same-morning value for the current UTC day"),
        "imerg_late_halfhourly": lambda r, d: probe_imerg_halfhourly(r, d, ctx),
        "gfs_nomads_grib_filter": lambda r, d: probe_gfs_grib_filter(r, d, ctx),
        "gfs_nomads_opendap": lambda r, d: probe_gfs_opendap(r, d, ctx),
        "gfs_aws_archive": lambda r, d: probe_gfs_aws_archive(r, d, ctx),
        "imd_realtime": lambda r, d: probe_imd_realtime(r, d, ctx),
        "ghcnd_recent": lambda r, d: probe_ghcnd_recent(r, d, ctx),
    }


def chosen_paths(sources: list[dict]) -> dict:
    """Per role, the source whose decision is `use` (None when no source qualifies)."""
    decision = {s["name"]: s["decision"] for s in sources}
    pick = lambda name: name if decision.get(name) == "use" else None  # noqa: E731
    return {"imerg_primary": pick("imerg_late_daily"), "imerg_same_day_decision": decision.get("imerg_early_daily"),
            "imerg_intensity_group_decision": decision.get("imerg_late_halfhourly"),
            "gfs_live": pick("gfs_nomads_grib_filter"), "gfs_archive": pick("gfs_aws_archive"),
            "imd_second_opinion": pick("imd_realtime"), "gauges": pick("ghcnd_recent")}


def run(only: set[str] | None, timeout_s: float, reports_dir: Path) -> dict:
    domain = load_config("ingest")["domain_bbox"]
    work_dir = data_root() / "raw" / "live_probe"
    work_dir.mkdir(parents=True, exist_ok=True)
    ctx = Context(domain, datetime.now(timezone.utc), work_dir,
                  Manifest(work_dir / "manifest.jsonl", data_root()), load_config("audit"))
    probes = build_probes(ctx)
    unknown = (only or set()) - set(probes)
    if unknown:
        raise SystemExit(f"unknown probe name(s): {sorted(unknown)}; choose from {sorted(probes)}")
    results = []
    for name, fn in probes.items():
        if only and name not in only:
            continue
        print(f"[live-probe] {name} ...", flush=True)
        results.append(run_probe(name, fn, timeout_s))
    sources = [assemble_source(r) for r in results]
    decoded = any(k.startswith(("messages_f", "decoded_messages")) for s in sources for k in s["details"])
    extras = {"grib_decoders": decoder_status(), "grib_decoding_worked": decoded,
              "grib_decoder_decision": {
                  "eccodes": "use" if decoded else "drop",
                  "cfgrib": "drop: eccodes reads the messages directly; cfgrib only adds an xarray layer"},
              "netcdf_readers": reader_status(), "chosen_paths": chosen_paths(sources)}
    report = build_report(results, ctx.now, domain, extras)
    md, js = write_report(report, reports_dir, collect_secrets())
    print(f"[live-probe] wrote {md} and {js}")
    return report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Probe the live data sources for the daily AetherGuard run.")
    parser.add_argument("--only", default="", help="comma-separated probe names (default: all)")
    parser.add_argument("--timeout", type=float, default=PROBE_TIMEOUT_S, help="seconds per probe (default 120)")
    parser.add_argument("--reports-dir", type=Path, default=PROJECT_ROOT / "reports")
    args = parser.parse_args(argv)
    only = {n.strip() for n in args.only.split(",") if n.strip()} or None
    report = run(only, args.timeout, args.reports_dir)
    for s in report["sources"]:
        print(f"{s['decision']:>9}  {'ok' if s['reachable'] else 'unreachable':<11} {s['name']}")


if __name__ == "__main__":
    main()
