"""Openly accessible landslide inventories (spec W1b): fetch them into `data/raw/manual/<source>/` and turn them into the raw
rows of the reported-event inventory (`verify.inventory`), so they pass the same checks, duplicate rule and QA as the news rows.

    python -m aetherguard.verify sources fetch bipad_nepal     # api/*.json + PROVENANCE.json
    python -m aetherguard.verify sources fetch gfld
    python -m aetherguard.verify sources normalise bipad_nepal # raw/<year>.csv for `inventory --dir <source dir>`

Why these two. The survey (`reports/phase8_ground_truth_survey.md`) found few openly licensed, day-dated, point-located
inventories inside the scored cells. The two that are:

* `bipad_nepal`: the incident register of Nepal's Disaster Risk Reduction portal (BIPAD, NDRRMA), public JSON API without a
  key. One row per reported incident (mostly Nepal Police reports), hazard "Landslide" (id 17), the incident day and a map
  point with its ward. The register states no licence; it is used locally only and never committed (a user decision is
  recorded in the survey). Nepal cells are scored cells of the model (Himalaya region, country NP), so these are in-domain.
  The location is bounded by the ward: `accuracy_km` is the distance from the point to the farthest corner of the ward's
  bounding box, which is the most the slide can be off if it lies in the stated ward (conservative: the point itself is often
  better). A point outside its ward's box is left unlocated (reason `point_outside_ward`), since then neither is trusted.
* `gfld`: the Global Fatal Landslide Database v2, 2004-2017 (Froude and Petley 2018, University of Sheffield), public ArcGIS
  feature service, Open Government Licence v2. Each fatal landslide has its day and a polygon of the area it is known to (the
  slide itself or its village); `Precision_` is the polygon area in square metres and `accuracy_km` is the radius of a circle
  of that area. Its years are development years only.

Both are found by people reporting slides (police, news), never mapped from imagery, so they share the road-and-settlement
bias of the W1 news rows; `how_found` = "reported" says so for the assembly.

HTTP etiquette: a generic User-Agent without personal details, at most one request per `MIN_INTERVAL_S`, every page saved
on disk and never fetched twice unless `force`.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import time
from collections.abc import Callable
from datetime import date, datetime, timezone
from pathlib import Path

import requests

from ..config import data_root
from .geocode import _haversine_km

USER_AGENT = "AetherGuard-research/1.0 (landslide verification research prototype)"
MIN_INTERVAL_S = 1.1
TIMEOUT_S = 90
RAW_HEADER = ("event_date", "date_basis", "place", "district", "state", "source_url", "outlet", "description",
              "latitude", "longitude", "accuracy_km", "window_end", "how_found", "trigger", "record_id")

BIPAD = "bipad_nepal"
BIPAD_API = "https://bipadportal.gov.np/api/v1"
BIPAD_LANDSLIDE = 17
BIPAD_PAGE = 500
BIPAD_FIRST_YEAR = 2011
BIPAD_LICENCE = ("No licence stated on the portal or in the API (checked 2026-11-13); public API without key or account; "
                 "Government of Nepal, NDRRMA. Used locally only, never redistributed or committed.")

GFLD = "gfld"
GFLD_LAYER = ("https://services2.arcgis.com/Dn40vzt2R38VJsSS/arcgis/rest/services/"
              "Fatal_landslide_points_2004_to_2017/FeatureServer/0")
GFLD_COUNTRIES = ("India", "Nepal", "Bhutan")
GFLD_LICENCE = ("'We have released the data as an asset for free public use. However, please acknowledge the following open "
                "source license and acknowledge the source of the data by citation. The dataset is covered by a University of "
                "Sheffield copyright and database rights reserved 2019. For the full license see "
                "http://www.nationalarchives.gov.uk/doc/open-government-licence/version/2/' (D. Petley, The Landslide Blog, "
                "2019-06-18). Cite Froude and Petley 2018, NHESS 18, 2161-2181.")

_last = float("-inf")


def source_dir(name: str) -> Path:
    return data_root() / "raw" / "manual" / name


def _get_json(url: str, params: dict | None = None, sleep: Callable[[float], None] = time.sleep) -> dict:
    """GET JSON politely: one request per MIN_INTERVAL_S, three attempts with back-off on network errors and 5xx/429."""
    global _last
    error = None
    for attempt in range(3):
        wait = _last + MIN_INTERVAL_S - time.monotonic()
        if wait > 0:
            sleep(wait)
        _last = time.monotonic()
        try:
            response = requests.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT_S)
            if response.status_code == 429 or response.status_code >= 500:
                raise requests.HTTPError(f"HTTP {response.status_code} from {url}")
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            error = exc
            sleep(5.0 * 2 ** attempt)
    raise RuntimeError(f"{url}: {error}")


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_provenance(directory: Path, info: dict) -> Path:
    """`PROVENANCE.json` of a source folder: what it is, where from, the licence line, when, and every file's hash."""
    directory = Path(directory)
    files = sorted(p for p in directory.rglob("*") if p.is_file() and p.name != "PROVENANCE.json")
    info = {**info, "files": {p.relative_to(directory).as_posix(): {"sha256": _sha256(p), "bytes": p.stat().st_size}
                              for p in files}}
    path = directory / "PROVENANCE.json"
    path.write_text(json.dumps(info, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


# --- BIPAD ----------------------------------------------------------------------------------------------------------

def _pages(url: str, params: dict, get) -> list[dict]:
    """Every result of a paged BIPAD list (limit/offset; the API's `count` is not usable)."""
    out, offset = [], 0
    while True:
        page = get(url, {**params, "limit": BIPAD_PAGE, "offset": offset, "format": "json"})
        rows = page.get("results", [])
        out.extend(rows)
        if len(rows) < BIPAD_PAGE:
            return out
        offset += BIPAD_PAGE


def fetch_bipad(directory: Path | None = None, last: date | None = None, get=_get_json, force: bool = False,
                say=print) -> Path:
    """Every landslide incident before the day after `last` (default today) into `<dir>/api/incidents.json`, and the ward,
    municipality and district tables (fetched once unless `force`).

    The API honours `incident_on__lt` but ignores `incident_on__gte` (checked 2026-11-13: a year query returned every earlier
    year as well), so the register is fetched whole, ordered by id, and years are split client-side."""
    directory = Path(directory or source_dir(BIPAD))
    api = directory / "api"
    api.mkdir(parents=True, exist_ok=True)
    last = last or date.today()
    for table in ("ward", "municipality", "district"):
        path = api / f"{table}.json"
        if force or not path.is_file():
            rows = _pages(f"{BIPAD_API}/{table}/", {}, get)
            path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
            say(f"bipad: {len(rows)} {table} rows")
    rows = _pages(f"{BIPAD_API}/incident/", {"hazard": BIPAD_LANDSLIDE, "ordering": "id",
                                             "incident_on__lt": date.fromordinal(last.toordinal() + 1).isoformat()}, get)
    (api / "incidents.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    say(f"bipad: {len(rows)} landslide incidents before {date.fromordinal(last.toordinal() + 1)}")
    write_provenance(directory, bipad_info(last))
    return directory


def bipad_info(last: date) -> dict:
    """The provenance entry of the BIPAD folder, register fetched through `last`."""
    return {
        "source": "BIPAD portal (Government of Nepal, NDRRMA), incident register, hazard Landslide (id 17)",
        "url": f"{BIPAD_API}/incident/?hazard={BIPAD_LANDSLIDE}",
        "licence": BIPAD_LICENCE,
        "how_found": "reported (Nepal Police and other agency reports entered in the register)",
        "date_precision": "day (incidentOn, Nepal time)",
        "location_precision": "map point with its ward; bounded by the ward's bounding box",
        "retrieved_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "through": last.isoformat(),
        "note": "the incident point is a per-ward point reused for most incidents of the ward (a 2026-11-13 check: 4,361 of "
                "6,672 incidents sit on a point used five or more times), so the location is the ward, not the slide",
    }


def _corner_km(lat: float, lon: float, bbox) -> float:
    """Distance from (lat, lon) to the farthest corner of `bbox` = [lon_min, lat_min, lon_max, lat_max]."""
    x0, y0, x1, y1 = bbox
    return max(float(_haversine_km(lat, lon, y, x)) for x in (x0, x1) for y in (y0, y1))


def _inside(lat: float, lon: float, bbox, margin: float = 1e-4) -> bool:
    x0, y0, x1, y1 = bbox
    return x0 - margin <= lon <= x1 + margin and y0 - margin <= lat <= y1 + margin


def bipad_rows(incident: dict, wards: dict, municipalities: dict, districts: dict) -> dict:
    """One raw inventory row (RAW_HEADER) of a BIPAD incident. The location is left empty (the row then reads
    `ungeocodable` downstream, with the reason in `description`) when the incident has no point or ward, or the point lies
    outside its ward."""
    day = incident["incidentOn"][:10]
    ward = wards.get((incident.get("wards") or [None])[0])
    municipality = municipalities.get(ward["municipality"]) if ward else None
    district = districts.get(municipality["district"]) if municipality else None
    title = (incident.get("title") or "").strip()
    place = title.removeprefix("Landslide at ").strip() or (incident.get("streetAddress") or "").strip() or f"incident {incident['id']}"
    point = (incident.get("point") or {}).get("coordinates")
    lat = lon = accuracy = ""
    note = f"BIPAD incident {incident['id']}; source {incident.get('source')}; verified {incident.get('verified')}; " \
           f"approved {incident.get('approved')}"
    if not incident.get("verified") or not incident.get("approved"):
        note += "; not verified or approved"
        point = None
    if point and ward:
        x, y = float(point[0]), float(point[1])
        if _inside(y, x, ward["bbox"]):
            lat, lon, accuracy = f"{y:.5f}", f"{x:.5f}", f"{_corner_km(y, x, ward['bbox']):.2f}"
        else:
            note += "; point_outside_ward"
    elif not point:
        note += "; no point"
    else:
        note += "; no ward"
    return {
        "event_date": day, "date_basis": "stated", "place": place,
        "district": district["title_en"] if district else "", "state": "Nepal",
        "source_url": f"{BIPAD_API}/incident/{incident['id']}/", "outlet": "BIPAD portal (NDRRMA)",
        "description": note, "latitude": lat, "longitude": lon, "accuracy_km": accuracy, "window_end": "",
        "how_found": "reported", "trigger": (incident.get("cause") or "").strip() or "unknown",
        "record_id": f"bipad:{incident['id']}",
    }


def normalise_bipad(directory: Path | None = None, say=print) -> dict[int, int]:
    """`<dir>/raw/<year>.csv` from the fetched incident files; returns rows per year."""
    directory = Path(directory or source_dir(BIPAD))
    api = directory / "api"
    by_id = lambda name: {row["id"]: row for row in json.loads((api / f"{name}.json").read_text(encoding="utf-8"))}
    wards, municipalities, districts = by_id("ward"), by_id("municipality"), by_id("district")
    seen, rows = set(), []
    for incident in json.loads((api / "incidents.json").read_text(encoding="utf-8")):
        if incident["id"] in seen or int(incident.get("hazard") or 0) != BIPAD_LANDSLIDE:
            continue
        seen.add(incident["id"])
        rows.append(bipad_rows(incident, wards, municipalities, districts))
    counts = {}
    for year in sorted({int(r["event_date"][:4]) for r in rows}):
        counts[year] = _write_raw(directory / "raw" / f"{year}.csv", [r for r in rows if r["event_date"].startswith(f"{year}-")])
    say(f"bipad: raw/<year>.csv for {len(counts)} years, {sum(counts.values())} rows")
    return counts


def _write_raw(path: Path, rows: list[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=RAW_HEADER)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


# --- GFLD -----------------------------------------------------------------------------------------------------------

def fetch_gfld(directory: Path | None = None, get=_get_json, say=print) -> Path:
    """The GFLD v2 points of India, Nepal and Bhutan (all attributes, WGS84) into `<dir>/api/points.json`."""
    directory = Path(directory or source_dir(GFLD))
    api = directory / "api"
    api.mkdir(parents=True, exist_ok=True)
    where = "Country IN (" + ",".join(f"'{c}'" for c in GFLD_COUNTRIES) + ")"
    features, offset = [], 0
    while True:
        page = get(f"{GFLD_LAYER}/query", {"where": where, "outFields": "*", "outSR": 4326, "returnGeometry": "true",
                                            "orderByFields": "FID", "resultOffset": offset, "resultRecordCount": 1000,
                                            "f": "json"})
        rows = page.get("features", [])
        features.extend(rows)
        if not page.get("exceededTransferLimit") and len(rows) < 1000:
            break
        offset += len(rows)
    (api / "points.json").write_text(json.dumps(features, ensure_ascii=False), encoding="utf-8")
    say(f"gfld: {len(features)} points in {', '.join(GFLD_COUNTRIES)}")
    write_provenance(directory, {
        "source": "Global Fatal Landslide Database v2, 2004-2017 (Froude and Petley 2018), University of Sheffield",
        "url": GFLD_LAYER,
        "licence": GFLD_LICENCE,
        "how_found": "reported (news and agency reports of fatal landslides, remapped by the authors)",
        "date_precision": "day (Day, Month, Year fields)",
        "location_precision": "polygon of the slide or its village; Precision_ = polygon area in m2",
        "retrieved_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    })
    return directory


GFLD_STATE = {"Nepal": "Nepal", "Bhutan": "Bhutan"}


def gfld_row(feature: dict) -> dict | None:
    """One raw inventory row of a GFLD point; None when the day is not known."""
    a = feature["attributes"]
    try:
        day = date(int(a["Year"]), int(a["Month"]), int(a["Day"]))
    except (TypeError, ValueError):
        return None
    area = a.get("Precision_")
    accuracy = math.sqrt(float(area) / math.pi) / 1000.0 if area not in (None, "") and float(area) > 0 else None
    lat, lon = a.get("Latitude"), a.get("Longitude")
    sources = [a.get(f"Source_{i}", "").strip() for i in range(1, 5)]
    url = next((s for s in sources if s.startswith("http")), "")
    place = (a.get("Location_M") or "").strip() or (a.get("Location_R") or "").strip() or f"GFLD {a['LandslideN']}"
    region = (a.get("Location_R") or "").strip()
    return {
        "event_date": day.isoformat(), "date_basis": "stated", "place": place, "district": "",
        "state": GFLD_STATE.get(a["Country"], a["Country"]),
        "source_url": url or f"{GFLD_LAYER}/query?where=FID%3D{a['FID']}&outFields=*&f=json",
        "outlet": "GFLD v2 (Froude and Petley)", "description": f"GFLD {a['LandslideN']}; {region}; fatalities {a.get('Fatalities')}",
        "latitude": "" if lat is None else f"{float(lat):.5f}", "longitude": "" if lon is None else f"{float(lon):.5f}",
        "accuracy_km": "" if accuracy is None else f"{accuracy:.2f}", "window_end": "", "how_found": "reported",
        "trigger": (a.get("Trigger_") or "").strip() or "unknown", "record_id": f"gfld:{a['LandslideN']}",
    }


def normalise_gfld(directory: Path | None = None, say=print) -> dict[int, int]:
    directory = Path(directory or source_dir(GFLD))
    features = json.loads((directory / "api" / "points.json").read_text(encoding="utf-8"))
    rows = [r for r in (gfld_row(f) for f in features) if r is not None]
    say(f"gfld: {len(features) - len(rows)} of {len(features)} points have no day and are left out")
    counts = {}
    for year in sorted({int(r["event_date"][:4]) for r in rows}):
        counts[year] = _write_raw(directory / "raw" / f"{year}.csv", [r for r in rows if r["event_date"].startswith(f"{year}-")])
    say(f"gfld: raw/<year>.csv for {len(counts)} years, {sum(counts.values())} rows")
    return counts


FETCHERS = {BIPAD: fetch_bipad, GFLD: fetch_gfld}
NORMALISERS = {BIPAD: normalise_bipad, GFLD: normalise_gfld}
