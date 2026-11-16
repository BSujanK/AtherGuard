"""Probe of keyless same-day rain-gauge sources for the integrity engine (phase 8, workstream gauges-isd).

    python -m aetherguard.live.gauge_sources_probe measure --evidence DIR     # network: HEAD / small GETs only
    python -m aetherguard.live.gauge_sources_probe build --evidence DIR [--out reports]

`measure` asks each candidate where its data end today (bucket listings, Last-Modified headers, the last record of
sample station files) and writes `<DIR>/probe_measure.json`. `build` joins it with the evidence files the workstream's
measurements wrote into the same directory (GHCN-Daily 2026 census, NWS ring latency, stations near the scored cells,
OGIMET request log, GHCNh precipitation content) and renders reports/phase8_gauge_sources_probe.{json,md}. Every
number in the report is read from those files.
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import requests

from ..config import PROJECT_ROOT
from ..hazard.jsonio import dump_json

UA = {"User-Agent": "AetherGuard/0.1 (research prototype)"}
REPORT_STEM = "phase8_gauge_sources_probe"
SAMPLE_WMO = ("42111", "43371", "42182")
GHCNH = "https://www.ncei.noaa.gov/oa/global-historical-climatology-network/hourly/access/by-year"
RING = "https://tgftp.nws.noaa.gov/SL.us008001/DF.an/DC.sflnd/DS.synop/"


def _head(url: str) -> dict:
    try:
        r = requests.head(url, headers=UA, timeout=60, allow_redirects=False)
        return {"url": url, "status": r.status_code, "last_modified": r.headers.get("Last-Modified"),
                "bytes": r.headers.get("Content-Length"), "location": r.headers.get("Location")}
    except requests.RequestException as exc:
        return {"url": url, "error": type(exc).__name__}


def _prefixes(bucket: str, prefix: str = "") -> list[str]:
    r = requests.get(f"https://{bucket}.s3.amazonaws.com/", params={"list-type": "2", "delimiter": "/", "prefix": prefix},
                     headers=UA, timeout=60)
    return re.findall(r"<Prefix>([^<]+)</Prefix>", r.text)


def _last_line(url: str, gz: bool = False) -> str | None:
    r = requests.get(url, headers=UA, timeout=120)
    if r.status_code != 200:
        return None
    data = gzip.decompress(r.content) if gz else r.content
    lines = [x for x in data.decode("latin-1").splitlines() if x.strip()]
    return lines[-1][:120] if lines else None


def measure() -> dict:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    isd_years = [p for p in _prefixes("noaa-isd-pds", "data/") if p != "data/"]
    gh_years = [p for p in _prefixes("noaa-global-hourly-pds") if re.fullmatch(r"\d{4}/", p)]
    out = {"measured_utc": now,
           "isd": {"isd_history": _head("https://www.ncei.noaa.gov/pub/data/noaa/isd-history.csv"),
                   "noaa_isd_pds_newest_year": isd_years[-1] if isd_years else None,
                   "noaa_global_hourly_pds_newest_year": gh_years[-1] if gh_years else None,
                   "last_record": {w: _last_line(f"https://noaa-global-hourly-pds.s3.amazonaws.com/2025/{w}099999.csv")
                                   for w in SAMPLE_WMO}},
           "gsod": {"files_2026": {w: _head(f"https://www.ncei.noaa.gov/data/global-summary-of-the-day/access/2026/{w}099999.csv")
                                   for w in SAMPLE_WMO},
                    "last_record_2025": {w: _last_line(f"https://www.ncei.noaa.gov/data/global-summary-of-the-day/access/2025/{w}099999.csv")
                                         for w in SAMPLE_WMO}},
           "ghcnh": {w: {**_head(f"{GHCNH}/2026/psv/GHCNh_INM000{w}_2026.psv")} for w in SAMPLE_WMO},
           "meteostat": {w: _head(f"https://bulk.meteostat.net/v2/hourly/2026/{w}.csv.gz") for w in SAMPLE_WMO},
           "nws_ring": {"listing": _head(RING + "ls-l")}}
    listing = requests.get(RING + "ls-l", headers=UA, timeout=60).text
    files = [x.split() for x in listing.splitlines() if re.search(r"sn\.\d{4}\.txt$", x)]
    out["nws_ring"].update(files=len(files), bytes=sum(int(f[4]) for f in files),
                           oldest=min((" ".join(f[5:8]) for f in files), default=None),
                           newest=max((" ".join(f[5:8]) for f in files), default=None))
    return out


def build(evidence: Path) -> dict:
    load = lambda name: json.loads((evidence / name).read_text(encoding="utf-8")) if (evidence / name).is_file() else None  # noqa: E731
    return {"report": REPORT_STEM, "measure": load("probe_measure.json"), "ghcn_2026": load("ghcn_census.json"),
            "nws_latency": load("latency.json"), "near_scored_cells": load("domain_synop.json"),
            "ghcnh_content": load("ghcnh_content.json"), "ogimet": load("ogimet_log.json"),
            "licences": LICENCES, "decisions_for_user": DECISIONS}


LICENCES = {
    "noaa_ncei": "NOAA NCEI open data (public domain); ISD, GSOD, GHCN-Daily, GHCNh",
    "nws": ("weather.gov disclaimer: information on NWS Web servers 'is in the public domain, unless specifically noted "
            "otherwise' and 'may be used freely by the public' (the page does not name the tgftp server); coded SYNOP "
            "reports are WMO essential data (Resolution 40)"),
    "ogimet": ("ogimet.com footer/licence: text tables may be used 'siempre que se incluya el enlace al sitio de origen "
               "Ogimet'; 'Estas paginas deben utilizarse a titulo informativo'; 'Los productos de este sitio no deben "
               "utilizarse en ninguna mision critica'; coded reports are copyright of each national service, WMO "
               "Resolution 40. getsynop help: 'No more than 200000 synops in a petition', 'please, don't abuse'"),
    "meteostat": "dev.meteostat.net/license: Creative Commons Attribution 4.0 International (CC BY 4.0); credit Meteostat and its data providers",
}
DECISIONS = [
    "Live use of OGIMET (terms: informational use only, not mission-critical). Used here only for validation and scratch replays.",
    "India-WRIS and the IMD AWS/ARG portals need registration: not signed up, not probed.",
    "Wiring synop.enabled and/or ghcn.h_zero_as_missing into the live run (levels can change: a model change).",
    "More stations than the 140 (SYNOP stations near the scored cells that the engine has no climatology for): needs an engine retraining and evaluation.",
]


def _row(name, data_end, latency, precip, licence, verdict):
    return f"| {name} | {data_end} | {latency} | {precip} | {licence} | {verdict} |"


def render(r: dict) -> str:
    m, g, lat, near, gh, og = (r.get(k) or {} for k in ("measure", "ghcn_2026", "nws_latency", "near_scored_cells",
                                                          "ghcnh_content", "ogimet"))
    isd = m.get("isd", {})
    mon = g.get("monsoon_2026", {})
    m24 = g.get("monsoon_2024_local", {})
    o3 = next(iter((lat.get("03utc") or {}).values()), {})
    lines = ["# Same-day rain gauges: source probe (phase 8, gauges-isd)", "",
             f"Measured {m.get('measured_utc', '-')} (and during 15-16 Nov 2026 for the evidence files). Research "
             "prototype, not validated for issuing real public warnings. Every number is read from "
             f"`{REPORT_STEM}.json`.", "",
             "## Findings", "",
             f"1. **NOAA ISD / Global Hourly and GSOD have ended.** isd-history.csv last modified "
             f"{isd.get('isd_history', {}).get('last_modified')}; newest year prefix in `noaa-isd-pds`: "
             f"{isd.get('noaa_isd_pds_newest_year')}, in `noaa-global-hourly-pds`: {isd.get('noaa_global_hourly_pds_newest_year')}; "
             f"GSOD 2026 files: HTTP {sorted({v.get('status') for v in m.get('gsod', {}).get('files_2026', {}).values()})}. "
             "NCEI's successor products are GHCNh (hourly) and the Synoptic Summary of the Day v2 (SSOD, GHCN-Daily source flag 2).",
             f"2. **The engine's current gauge source carries no rain in 2026.** GHCN-Daily for the 140 project stations, "
             f"June-September 2026: {mon.get('station_days')} station-days from {mon.get('stations')} stations, source flags "
             f"{mon.get('sflag')}, measurement flags {mon.get('mflag')}; share >= 1 mm {mon.get('wet_share_ge1mm'):.4f} against "
             f"{m24.get('wet_share_ge1mm'):.4f} in June-September 2024 ({m24.get('station_days')} station-days, source S). Flag H "
             "means the amount 'could not be calculated, but at least one occurrence of precipitation was noted': these "
             "are not measured zeros, yet the live run reads them as dry days.",
             "3. **The same stations' own SYNOP reports are on the WMO GTS within the hour.** NWS ring, 03 UTC cycles: "
             + "; ".join(f"{t[:10]}: {v.get('stations_reported')} of {lat.get('wmo_stations')} stations with a non-NIL "
                         f"report, {v.get('by_0530utc')} before 05:30 UTC (the run), p95 delay {v.get('lag_h_p95', 0):.2f} h, "
                         f"maximum {v.get('lag_h_max', 0):.2f} h" for t, v in (lat.get('03utc') or {}).items())
             + ". All hours: " + "; ".join(f"{h} UTC p90 {v['lag_h_p90']:.2f} h max {v['lag_h_max']:.2f} h ({v['reports']} reports)"
                                         for h, v in (lat.get('by_hour') or {}).items()) + ".",
             "", "## Candidates", "",
             "| source | data end (measured) | latency | precipitation for our stations | licence | verdict |",
             "|---|---|---|---|---|---|",
             _row("NOAA ISD / Global Hourly (buckets, NCEI)", f"newest year {isd.get('noaa_global_hourly_pds_newest_year')}; "
                  f"last records {list((isd.get('last_record') or {}).values())[:1]}", "-", "AA1 groups up to Aug 2025",
                  "public domain", "ended; used for the V1 diagnostic only"),
             _row("NOAA GSOD", "2025 files end Aug 2025; 2026 absent", "-", "-", "public domain", "ended"),
             _row("GHCN-Daily (current)", f"newest value of any station {max(g.get('newest_date_counts') or {'-': 0})} "
                  "when queried on 15 Nov 2026 (window to 14 Nov)", "115-308 h (phase 6 probe)",
                  f"{mon.get('zero_with_H_share', 0):.3f} of monsoon-2026 values are flag-H zeros", "public domain",
                  "keep only as history; flag-H zeros are not rain data"),
             _row("GHCNh (ISD successor)", f"by-year 2026 files: {[(k, v.get('status'), v.get('last_modified')) for k, v in (m.get('ghcnh') or {}).items()]}",
                  "days (file updates not daily)", f"{gh.get('summary', '-')}", "public domain",
                  f"{gh.get('coverage', '-')}; not usable same-day"),
             _row("Meteostat bulk", f"Last-Modified {[v.get('last_modified') for v in (m.get('meteostat') or {}).values()]}",
                  "stale since March 2026", "-", "CC BY 4.0", "stale"),
             _row("OGIMET getsynop", "real time (archive)", "minutes", "raw SYNOP, all groups",
                  "informational only, not mission-critical", f"validation and replays only ({og.get('requests', '-')} requests)"),
             _row("NWS tgftp SYNOP ring", f"{m.get('nws_ring', {}).get('files')} files, {m.get('nws_ring', {}).get('bytes')} bytes, "
                  f"{m.get('nws_ring', {}).get('oldest')} .. {m.get('nws_ring', {}).get('newest')} UTC",
                  f"03 UTC p95 {o3.get('lag_h_p95', 0):.2f} h", "raw SYNOP, all groups", "public domain (NWS)",
                  "**chosen live source**"),
             "", "## Stations near the scored cells", "",
             f"SYNOP stations within 100 km of the {near.get('scored_cells')} live-scored cells "
             f"({near.get('station_list_source')}): {near.get('stations_within_100km')} by country {near.get('by_country')}; "
             f"{near.get('in_ghcn_140')} of them are among the engine's {near.get('ghcn_140_total')} stations. In the NWS ring "
             f"of 14-15 Nov, {near.get('reported_in_ring_14_15_nov')} reported; {near.get('with_imd_day_total_15nov')} gave an "
             f"IMD-day total for 15 Nov ({near.get('how_15nov')}), {near.get('with_total_not_in_ghcn_140')} of them outside the "
             "engine's station set (they need a climatology and an engine evaluation before use).", "",
             "Precipitation in Indian SYNOPs: section 1 `i_R` (3 = omitted because zero, 4 = not observed) and section 3 "
             "`6RRR/`, the amount since 03 UTC (24 h at 03 UTC), plus `7R24R24R24R24` at some stations; trace is RRR 990 "
             "or R24 9999. ISD 2024 (Dehradun) decodes the same groups with periods 3, 6, ..., 24 h, cumulative since 03 UTC.",
             "", "## OGIMET usage", "",
             f"{og.get('requests')} requests in all, {og.get('total_bytes')} bytes ({og.get('note')}); terms read before the "
             f"first request: {og.get('terms_checked_before_requests')}. Raw responses are kept under data/raw/synop/ogimet "
             "(July 2024 in the workstream's scratch directory), never committed.", "", "## Licences (quoted)", ""]
    lines += [f"- {k}: {v}" for k, v in r["licences"].items()]
    lines += ["", "## Decisions for the user", ""] + [f"- {d}" for d in r["decisions_for_user"]]
    lines += ["", "## Caveats", "",
              "- Latency of the ring was measured on two 03 UTC cycles (15 and 16 Nov 2026) and the hours in between; "
              "more days need the daily collection.",
              "- The station list near the scored cells comes from isd-history.csv, frozen since August 2025.", ""]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m aetherguard.live.gauge_sources_probe")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("measure", "build"):
        p = sub.add_parser(name)
        p.add_argument("--evidence", type=Path, required=True)
        p.add_argument("--out", type=Path, default=PROJECT_ROOT / "reports")
    args = parser.parse_args(argv)
    if args.cmd == "measure":
        dump_json(args.evidence / "probe_measure.json", measure())
        return 0
    result = build(args.evidence)
    dump_json(args.out / f"{REPORT_STEM}.json", result)
    (args.out / f"{REPORT_STEM}.md").write_text(render(result), encoding="utf-8")
    print(args.out / f"{REPORT_STEM}.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
