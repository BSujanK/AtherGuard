"""GHCN-Daily and ISD helpers: station selection, .dly parsing, real quality-flag census."""
from __future__ import annotations

import calendar
from collections import Counter
from datetime import date
from pathlib import Path

import pandas as pd

from ..grid import region_labels
from ..http import DownloadError, download
from .result import ProbeResult, failure_status

GHCND_BASE = "https://www.ncei.noaa.gov/pub/data/ghcn/daily/"
ISD_HISTORY_URL = "https://www.ncei.noaa.gov/pub/data/noaa/isd-history.csv"
DLY_LINE_LENGTH = 269  # 21 header characters + 31 days * 8
MISSING = -9999
DIVISOR = {"PRCP": 10, "TMAX": 10, "TMIN": 10, "TAVG": 10}  # tenths -> mm / degC

# GHCN-Daily QFLAG: a letter means the value FAILED that automated check (the value is kept).
QFLAG_MEANINGS = {
    "D": "duplicate day", "G": "gap check", "I": "internal inconsistency",
    "K": "streak / frequent-value", "L": "multi-day accumulation length",
    "M": "megaconsecutive value", "N": "naught check", "O": "climatological outlier",
    "R": "lagged range", "S": "spatial inconsistency", "T": "temporal inconsistency",
    "W": "temperature too warm for snow", "X": "exceeds bounds / record", "Z": "Datzilla investigation",
}
_STATION_COLUMNS = ["id", "lat", "lon", "elevation_m", "name",
                    "first_year", "last_year", "country", "region", "upland"]
_DLY_COLUMNS = ["station", "date", "element", "value", "mflag", "qflag", "sflag"]
_LICENCE = "NOAA NCEI open data (public domain)"


def parse_inventory_line(line: str) -> dict:
    return {"id": line[0:11], "lat": float(line[12:20]), "lon": float(line[21:30]),
            "element": line[31:35].strip(), "first_year": int(line[36:40]),
            "last_year": int(line[41:45])}


def parse_station_line(line: str) -> dict:
    elevation = float(line[31:37])
    return {"id": line[0:11], "lat": float(line[12:20]), "lon": float(line[21:30]),
            "elevation_m": None if elevation <= -999.0 else elevation, "name": line[41:71].strip()}


def select_stations(inventory_lines, station_lines, countries, element,
                    first_year_max, last_year_min, upland_min_elev_m) -> pd.DataFrame:
    countries = tuple(countries)
    stations = {}
    for line in station_lines:
        if line.strip() and line[0:2] in countries:
            record = parse_station_line(line)
            stations[record["id"]] = record
    rows = []
    for line in inventory_lines:
        if not line.strip() or line[0:2] not in countries:
            continue
        inv = parse_inventory_line(line)
        if (inv["element"] != element or inv["first_year"] > first_year_max
                or inv["last_year"] < last_year_min):
            continue
        station = stations.get(inv["id"])
        if station is None:
            continue
        rows.append({**station, "first_year": inv["first_year"], "last_year": inv["last_year"],
                     "country": inv["id"][0:2]})
    df = pd.DataFrame(rows, columns=_STATION_COLUMNS[:-2])
    if df.empty:
        return df.assign(region=pd.Series(dtype=object), upland=pd.Series(dtype=bool))
    df["region"] = region_labels(df["lat"].to_numpy(), df["lon"].to_numpy())
    # A station with unknown elevation is NOT counted as upland (conservative).
    df["upland"] = df["elevation_m"].fillna(-1e9) >= upland_min_elev_m
    return df[_STATION_COLUMNS]


def parse_dly_line(line: str) -> list[dict]:
    line = line.rstrip("\r\n")
    if len(line) < DLY_LINE_LENGTH:
        raise ValueError(f"short .dly line ({len(line)} characters, expected {DLY_LINE_LENGTH})")
    station, year, month, element = line[0:11], int(line[11:15]), int(line[15:17]), line[17:21]
    divisor = DIVISOR.get(element, 1)
    rows = []
    for day in range(1, calendar.monthrange(year, month)[1] + 1):
        offset = 21 + (day - 1) * 8
        raw = int(line[offset:offset + 5])
        rows.append({
            "station": station, "date": date(year, month, day), "element": element,
            "value": None if raw == MISSING else raw / divisor,
            "mflag": line[offset + 5], "qflag": line[offset + 6], "sflag": line[offset + 7],
        })
    return rows


def read_dly(path, element: str | None = "PRCP") -> pd.DataFrame:
    rows: list[dict] = []
    with Path(path).open("r", encoding="ascii", errors="replace") as handle:
        for line in handle:
            if not line.strip():
                continue
            if element is not None and line[17:21] != element:
                continue
            rows.extend(parse_dly_line(line))
    return pd.DataFrame(rows, columns=_DLY_COLUMNS)


def flag_census(df: pd.DataFrame) -> dict:
    valid = df["value"].notna()
    flags = df["qflag"].astype(str).str.strip()
    flagged = flags.ne("")
    counts = Counter(flags[flagged])
    return {"n_values": int(len(df)), "n_valid": int(valid.sum()), "n_missing": int((~valid).sum()),
            "n_flagged": int(flagged.sum()), "by_flag": {k: int(v) for k, v in sorted(counts.items())}}


def _group_key(region: str, upland: bool) -> str:
    return f"{region or 'outside_domain'}|{'upland' if upland else 'lowland'}"


def probe_ghcnd(data_root, manifest, cfg) -> ProbeResult:
    g = cfg["ghcnd"]
    raw = Path(data_root) / "raw" / "ghcnd"
    inventory = download(GHCND_BASE + "ghcnd-inventory.txt", raw / "ghcnd-inventory.txt",
                         manifest, "NOAA GHCN-Daily inventory", _LICENCE)
    stations = download(GHCND_BASE + "ghcnd-stations.txt", raw / "ghcnd-stations.txt",
                        manifest, "NOAA GHCN-Daily stations", _LICENCE)
    selected = select_stations(
        inventory.read_text(encoding="ascii", errors="replace").splitlines(),
        stations.read_text(encoding="ascii", errors="replace").splitlines(),
        g["countries"], "PRCP", g["first_year_max"], g["last_year_min"], g["upland_min_elev_m"])
    groups: dict[str, dict] = {}
    station_rows, failed, errors = [], [], []
    for rec in selected.to_dict("records"):
        try:
            path = download(f"{GHCND_BASE}all/{rec['id']}.dly", raw / "dly" / f"{rec['id']}.dly",
                            manifest, "NOAA GHCN-Daily station file", _LICENCE)
        except DownloadError as exc:
            errors.append(exc)
            failed.append({"id": rec["id"], "error": str(exc), "kind": "download"})
            continue
        try:
            census = flag_census(read_dly(path, "PRCP"))
        except ValueError as exc:  # truncated / corrupt .dly file: record it, keep the other stations
            errors.append(exc)
            failed.append({"id": rec["id"], "error": str(exc), "kind": "parse"})
            continue
        key = _group_key(rec["region"], bool(rec["upland"]))
        slot = groups.setdefault(key, {"n_stations": 0, "n_valid": 0, "n_flagged": 0, "by_flag": Counter()})
        slot["n_stations"] += 1
        slot["n_valid"] += census["n_valid"]
        slot["n_flagged"] += census["n_flagged"]
        slot["by_flag"].update(census["by_flag"])
        elevation = rec["elevation_m"]
        station_rows.append({k: rec[k] for k in ("id", "name", "lat", "lon", "region")}
                            | {"elevation_m": None if pd.isna(elevation) else float(elevation),
                               "upland": bool(rec["upland"]), "n_valid": census["n_valid"],
                               "n_flagged": census["n_flagged"]})
    for slot in groups.values():
        slot["by_flag"] = dict(sorted(slot["by_flag"].items()))
    total_flagged = sum(s["n_flagged"] for s in groups.values())
    evidence = {
        "n_selected": int(len(selected)),
        "by_country": dict(Counter(selected["country"])) if len(selected) else {},
        "n_unknown_elevation": int(selected["elevation_m"].isna().sum()),  # treated as lowland
        "census_by_group": groups, "stations": station_rows, "failed_downloads": failed,
        "qflag_meanings": QFLAG_MEANINGS,
    }
    if selected.empty:
        return ProbeResult("ghcnd", "fail", "no stations matched the selection", evidence)
    if not station_rows:
        return ProbeResult("ghcnd", failure_status(errors),
                           f"{len(selected)} stations selected, none could be read ({len(failed)} failed)",
                           evidence)
    status = "ok" if total_flagged > 0 and not failed else "partial"
    return ProbeResult("ghcnd", status,
                       f"{len(selected)} stations selected, {total_flagged} real quality-flagged rain values",
                       evidence)


def probe_isd_history(data_root, manifest, cfg) -> ProbeResult:
    g = cfg["ghcnd"]
    path = download(ISD_HISTORY_URL, Path(data_root) / "raw" / "isd" / "isd-history.csv",
                    manifest, "NOAA ISD station history", _LICENCE)
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    df = df[df["CTRY"].isin(g["countries"])].copy()
    begin = pd.to_numeric(df["BEGIN"].str[:4], errors="coerce")
    end = pd.to_numeric(df["END"].str[:4], errors="coerce")
    df = df[(begin <= g["first_year_max"]) & (end >= g["last_year_min"])]
    lat = pd.to_numeric(df["LAT"], errors="coerce")
    lon = pd.to_numeric(df["LON"], errors="coerce")
    df = df[lat.notna() & lon.notna()]
    regions = region_labels(lat[df.index].to_numpy(), lon[df.index].to_numpy())
    evidence = {
        "n_selected": int(len(df)),
        "by_country": dict(Counter(df["CTRY"])),
        "by_region": dict(Counter(r or "outside_domain" for r in regions)),
        "note": "ISD is hourly station data; per-value QC flags are in the full ISD files (not fetched in Phase 0).",
    }
    status = "ok" if len(df) else "fail"
    return ProbeResult("isd", status, f"{len(df)} active ISD stations in {', '.join(g['countries'])}", evidence)
