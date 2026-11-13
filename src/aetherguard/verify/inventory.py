"""Reported-event inventory: the landslides news and official sources reported in 2019-2025, as a scored test set.

    python -m aetherguard.verify inventory    # data/raw/manual/reported_events/<year>.csv + inventory_report.json

Input is `raw/<year>.csv` in the reported-events folder, one row per report, with the header

    event_date,date_basis,place,district,state,source_url,outlet,description

`date_basis` is "stated" when the source gives the day of the slide and "report" when only the day of the article is known.
Every row is geocoded with `geocode_osm.geocode_any` (GeoNames, then the Nominatim answers cached on disk) and is admitted to
the test set only when all of these hold; a row that fails keeps its reason in `inventory_report.json` and is written nowhere
else:

* `date_basis` is "stated" (else `report_dated`; such a row is not geocoded);
* the place is found (else `ungeocodable`);
* the point lies inside a region box of `configs/domain.yaml` (else `outside_domain`; `ledger.load_reported` would raise);
* its accuracy is at most `MAX_ACCURACY_KM` = 10 km (else `accuracy_over_10km`);
* it is not a duplicate (else `duplicate`): two rows are one event when they fall in the same cell on the same day, or within
  one day of each other in the same cell or within `SAME_PLACE_KM` = 5 km. Of a group the row with the smallest accuracy is
  kept, the earliest listed (by year file, then line) among equals; it keeps its place and source but takes the earliest stated
  date of the group (reports of one slide often lag it by a day), and `merged_events` in the report lists each such group.

A geocoder answer with a non-finite coordinate or accuracy counts as not found (`ungeocodable`).

QA corrections. The optional `qa/corrections.csv` of the reported-events folder (`CORRECTION_COLUMNS`) overrides the geocoder
for single events after the spot-check against the sources. A row names the raw row by `date`, `place` and `state` exactly as
written there and either gives the true point (`action` = correct, with latitude, longitude and accuracy_km; the surviving row's
`geocode_source` becomes "qa_correction" and it still goes through the domain, accuracy and duplicate checks) or throws the
event out (`action` = exclude, those three empty; reason `qa_excluded`, with the given `reason` as `qa_reason` in the report).
`reason` and `source_url` (where the correction comes from) are required. A key matching no raw row, or only a report-dated
one, is an error; so is a malformed line. The report lists every correction with what the geocoder had answered.

A correction applies to the whole duplicate group of its keyed row, not to that raw row alone: the groups are formed on the
uncorrected geocoded points (the rule above), then an exclude rejects every member (a twin reads `qa_reason` "<reason> (same
event as <keyed place> on <keyed date>)") and a correct moves the group's surviving row, whose twins stay `duplicate`s of it
whatever the corrected point. An exclude wins over a correct in the same group; two corrects in one group are an error. A
keyed row that is not a candidate (ungeocodable, over 10 km, outside the boxes) is a group of its own.

QA coverage. `qa/qa_results.csv` (columns `date`, `place`, `state`, ...) holds the spot-check of the admitted events, one row
each, by the admitted date, place and state. `unchecked` in the report lists every admitted event that has no row there (all
of them when the file does not exist) and the command prints their number.

Located sources (W1b). A raw file may carry the further columns `LOCATED_COLUMNS` (`verify.open_sources` writes them for
inventories that come with coordinates). In a file whose header has `latitude`, every row is located by its own `latitude`,
`longitude` and `accuracy_km` (`geocode_source` "source_point") and never by its place text, so no name is sent to a geocoder;
a row with an empty coordinate is `ungeocodable`. `trigger` (optional) is classed with `events.policy.normalize_trigger`;
only "rain" and "unknown" are admitted, anything else (earthquake, construction or mining, snow, other) and any text naming
a glacial lake outburst is rejected as `non_rain_trigger`. `date_basis` may also be "window": the slide happened on some
day from `event_date` to `window_end` (an imagery-mapped inventory); such a row is admitted only when the window is at most
`MAX_WINDOW_DAYS` days long (else `window_over_7d`), never merges with a day-dated row, and goes only to
`qa/inventory_admitted.csv` (the ledger format has no window). `how_found` ("reported" or "imagery") and `record_id` are
carried through. `build_inventory(max_accuracy_km=...)` sets the accuracy limit (10 km by default, as W1 admitted; W1b
admits its sources at 5 km, reason `accuracy_over_limit` then).

Admitted rows go to `<year>.csv` in the ledger format (`ledger.COLUMNS`, `location_text` = "place, district, state") and, with
the extra columns `EXTRA_COLUMNS`, to `qa/inventory_admitted.csv` for the spot-check against the source URLs. That file is in a
subfolder because `ledger.load_reported` reads every top-level `*.csv` and would count each event twice. An event's year is the
year of its (merged) date; the report's per-year counts are by the raw file a row came from.
`inventory_report.json` counts, per year and in total, the raw, stated and geocoded rows (by source and by region), the admitted
rows and the rejections by reason, lists every rejected row with its reason, and says how many Nominatim queries were not in
the cache and had to be fetched (`osm_fetched`; 0 on a rerun).
"""
from __future__ import annotations

import csv
import json
import math
import re
from collections import Counter
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from .. import grid
from ..events.policy import normalize_trigger
from ..hazard.jsonio import dump_json
from . import geocode as gc
from . import ledger
from .geocode import GeocodeError
from .geocode_osm import geocode_any, nominatim_fetch

RAW_COLUMNS = ("event_date", "date_basis", "place", "district", "state", "source_url", "outlet", "description")
LOCATED_COLUMNS = ("latitude", "longitude", "accuracy_km", "window_end", "how_found", "trigger", "record_id")
EXTRA_COLUMNS = ("year", "place", "district", "state", "outlet", "geocode_source", "description",
                 "date_basis", "window_end", "how_found", "trigger", "record_id")
MAX_WINDOW_DAYS = 7
ADMITTED_TRIGGERS = frozenset({"rain", "unknown"})
_GLOF_WORDS = ("glof", "glacial lake", "lake outburst", "outburst flood")
REPORT_NAME, QA_DIR, COMBINED_NAME, CORRECTIONS_NAME = "inventory_report.json", "qa", "inventory_admitted.csv", "corrections.csv"
QA_RESULTS_NAME = "qa_results.csv"
CORRECTION_COLUMNS = ("date", "place", "state", "action", "latitude", "longitude", "accuracy_km", "reason", "source_url")
MAX_ACCURACY_KM = 10.0
SAME_PLACE_KM = 5.0
OUTSIDE = "outside_domain"
DECIMALS = 5                                           # coordinates are written to about a metre

Geocoder = Callable[[str, str, str], "tuple[float, float, float, str] | None"]


# --- reading ----------------------------------------------------------------------------------------------------

def _read_raw(raw_dir: Path) -> list[dict]:
    """Every row of `<raw_dir>/<year>.csv`, validated, in listing order (year ascending, then line)."""
    paths = sorted(p for p in Path(raw_dir).glob("*.csv") if re.fullmatch(r"\d{4}", p.stem))
    if not paths:
        raise ValueError(f"{raw_dir} has no <year>.csv file")
    records = []
    for path in paths:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.reader(handle)
            header = next(reader, None) or []
            missing = [c for c in RAW_COLUMNS if c not in header]
            if missing:
                raise ValueError(f"{path.name}: missing column(s) {missing}; the header is {','.join(RAW_COLUMNS)}")
            while True:
                line = reader.line_num + 1
                raw = next(reader, None)
                if raw is None:
                    break
                if not any(cell.strip() for cell in raw):
                    continue
                fields = {name: (raw[i] if i < len(raw) else "").strip() for i, name in enumerate(header)}
                for name in LOCATED_COLUMNS:
                    fields.setdefault(name, "")
                fields["located"] = "latitude" in header
                try:
                    records.append({**fields, **_check(fields, int(path.stem))})
                except ValueError as error:
                    raise ValueError(f"{path.name} line {line}: {error}") from None
    for order, record in enumerate(records):
        record["order"] = order
    return records


def _check(fields: dict[str, str], year: int) -> dict:
    """The parsed `day` and `year` of one raw row; ValueError says what is wrong."""
    try:
        day = datetime.strptime(fields["event_date"], "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(f"event_date {fields['event_date']!r} is not YYYY-MM-DD") from None
    if day.year != year:
        raise ValueError(f"event_date {fields['event_date']} is not in {year}")
    if fields["date_basis"] not in ("stated", "report", "window"):
        raise ValueError(f"date_basis {fields['date_basis']!r} is not 'stated', 'report' or 'window'")
    for name in ("place", "state", "source_url"):
        if not fields[name]:
            raise ValueError(f"{name} is empty")
    end = None
    if fields["date_basis"] == "window":
        try:
            end = datetime.strptime(fields["window_end"], "%Y-%m-%d").date()
        except ValueError:
            raise ValueError(f"window_end {fields['window_end']!r} is not YYYY-MM-DD") from None
        if end < day:
            raise ValueError(f"window_end {end} is before event_date {day}")
    elif fields["window_end"]:
        raise ValueError("window_end is given but date_basis is not 'window'")
    point = None
    if fields["located"] and any(fields[n] for n in ("latitude", "longitude", "accuracy_km")):
        try:
            point = tuple(float(fields[n]) for n in ("latitude", "longitude", "accuracy_km"))
        except ValueError:
            raise ValueError("latitude, longitude and accuracy_km must all be numbers or all be empty") from None
        if not all(math.isfinite(v) for v in point) or point[2] < 0:
            raise ValueError("latitude, longitude and accuracy_km must be finite and accuracy_km >= 0")
    return {"day": day, "year": year, "window_end_day": end, "point": point}


def trigger_class(text: str) -> str:
    """The trigger class of a raw `trigger` text (`events.policy.normalize_trigger`; a glacial lake outburst is 'glof')."""
    if any(word in text.lower() for word in _GLOF_WORDS):
        return "glof"
    return normalize_trigger(text)


def _correction(fields: dict[str, str]) -> dict:
    """The validated correction of one CSV row (key, action, point, reason, source); ValueError says what is wrong."""
    try:
        day = datetime.strptime(fields["date"], "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(f"date {fields['date']!r} is not YYYY-MM-DD") from None
    for name in ("place", "state", "reason", "source_url"):
        if not fields[name]:
            raise ValueError(f"{name} is empty")
    action = fields["action"]
    if action not in ("correct", "exclude"):
        raise ValueError(f"action {action!r} is neither 'correct' nor 'exclude'")
    entry = {"key": (day.isoformat(), fields["place"], fields["state"]), "action": action, "reason": fields["reason"],
             "source_url": fields["source_url"]}
    numbers = {name: fields[name] for name in ("latitude", "longitude", "accuracy_km")}
    if action == "exclude":
        if any(numbers.values()):
            raise ValueError("latitude, longitude and accuracy_km must be empty for an exclude")
        return entry
    for name, text in numbers.items():
        try:
            value = float(text)
        except ValueError:
            raise ValueError(f"{name} {text!r} is not a number") from None
        if not math.isfinite(value) or (name == "accuracy_km" and value < 0):
            raise ValueError(f"{name} {text!r} must be a finite number" + (" >= 0" if name == "accuracy_km" else ""))
        entry[name] = value
    return entry


def _read_corrections(path: Path | None) -> dict[tuple[str, str, str], dict]:
    """The corrections of `path` by (date, place, state); none when the file does not exist."""
    if path is None or not Path(path).is_file():
        return {}
    path = Path(path)
    corrections = {}
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle)
        header = next(reader, None) or []
        missing = [c for c in CORRECTION_COLUMNS if c not in header]
        if missing:
            raise ValueError(f"{path.name}: missing column(s) {missing}; the header is {','.join(CORRECTION_COLUMNS)}")
        while True:
            line = reader.line_num + 1
            raw = next(reader, None)
            if raw is None:
                return corrections
            if not any(cell.strip() for cell in raw):
                continue
            fields = {name: (raw[i] if i < len(raw) else "").strip() for i, name in enumerate(header)}
            try:
                entry = _correction(fields)
                if entry["key"] in corrections:
                    raise ValueError(f"{entry['key']} is corrected twice")
            except ValueError as error:
                raise ValueError(f"{path.name} line {line}: {error}") from None
            corrections[entry["key"]] = entry


def _check_corrections(corrections: dict, records: list[dict]) -> None:
    """Raise unless every correction names a stated raw row."""
    basis = {}
    for record in records:
        basis.setdefault((record["event_date"], record["place"], record["state"]), set()).add(record["date_basis"])
    for key in corrections:
        if key not in basis:
            raise ValueError(f"{CORRECTIONS_NAME}: no raw row matches {key}")
        if not basis[key] & {"stated", "window"}:
            raise ValueError(f"{CORRECTIONS_NAME}: the raw row {key} is report-dated and never enters the test set")


# --- deciding -----------------------------------------------------------------------------------------------------

def _duplicate(a: dict, b: dict) -> bool:
    """Whether two located rows are one event: same cell on the same day, or within a day in one cell or within 5 km. Two
    window rows are one event when their windows (widened by a day) overlap at that distance; a window row and a day row never
    are."""
    if (a["date_basis"] == "window") != (b["date_basis"] == "window"):
        return False
    if a["date_basis"] == "window":
        if a["day"] > b["window_end_day"] + timedelta(days=1) or b["day"] > a["window_end_day"] + timedelta(days=1):
            return False
    elif abs((a["day"] - b["day"]).days) > 1:
        return False
    return a["cell_id"] == b["cell_id"] or float(gc._haversine_km(a["lat"], a["lon"], b["lat"], b["lon"])) <= SAME_PLACE_KM


def _locate(record: dict, geocoder: Geocoder, max_accuracy_km: float = MAX_ACCURACY_KM) -> None:
    """Geocode a stated (or window) row and set its `reason` (None = still a candidate) and, when placed, its point and region.
    The point is the geocoder's, or the row's own in a located file: QA corrections come later (`_apply_corrections`)."""
    _reset(record)
    record["max_accuracy_km"] = max_accuracy_km
    record["found"] = None
    if record["date_basis"] == "report":
        record["reason"] = "report_dated"
        return
    if record["trigger"] and trigger_class(record["trigger"]) not in ADMITTED_TRIGGERS:
        record["reason"] = "non_rain_trigger"
        return
    if record["date_basis"] == "window" and (record["window_end_day"] - record["day"]).days + 1 > MAX_WINDOW_DAYS:
        record["reason"] = f"window_over_{MAX_WINDOW_DAYS}d"
        return
    if record["located"]:
        record["found"] = None if record["point"] is None else (*record["point"], "source_point")
    else:
        record["found"] = geocoder(record["place"], record["district"], record["state"])
    _place(record, record["found"])


def _reset(record: dict) -> None:
    record.update(reason=None, lat=None, lon=None, accuracy_km=None, geocode_source=None, region=None, cell_id=None)


def _place(record: dict, found: tuple[float, float, float, str] | None) -> None:
    """Set the point, region and `reason` of a stated row from the geocoder's (or a correction's) answer."""
    if found is None:
        record["reason"] = "ungeocodable"
        return
    lat, lon, accuracy, source = found
    if not all(math.isfinite(float(v)) for v in (lat, lon, accuracy)):
        record["reason"] = "ungeocodable"
        return
    record.update(lat=round(float(lat), DECIMALS), lon=round(float(lon), DECIMALS), accuracy_km=float(accuracy),
                  geocode_source=source)
    record["region"] = grid.region_of(record["lat"], record["lon"]) or OUTSIDE
    if record["region"] == OUTSIDE:
        record["reason"] = OUTSIDE
        return
    record["cell_id"] = int(grid.latlon_to_cell(record["lat"], record["lon"]))
    limit = record.get("max_accuracy_km", MAX_ACCURACY_KM)
    if record["accuracy_km"] > limit:
        record["reason"] = f"accuracy_over_{limit:g}km"


def _group(candidates: list[dict]) -> list[list[dict]]:
    """The candidates as duplicate groups, the row to keep first: smaller accuracy, then earlier listed. A row joins the first
    kept row it duplicates."""
    groups: list[list[dict]] = []
    for record in sorted(candidates, key=lambda r: (r["accuracy_km"], r["order"])):
        group = next((g for g in groups if _duplicate(record, g[0])), None)
        if group is None:
            groups.append([record])
        else:
            group.append(record)
    return groups


def _beaten_by(record: dict, kept: dict) -> None:
    record["reason"] = "duplicate"
    record["duplicate_of"] = f"{kept['place']} on {kept['day'].isoformat()} ({kept['outlet']}, {kept['source_url']})"


def _apply_corrections(records: list[dict], corrections: dict[tuple[str, str, str], dict]) -> None:
    """Apply the QA corrections to the duplicate group of each keyed row (see the module docstring).

    The groups are formed on the points the geocoder gave. An exclude rejects every member; a correct moves the group's
    surviving row to the given point and makes the other members its duplicates, so none of them is admitted on its own. Each
    correction learns what the geocoder had answered (`geocoded`), the raw `rows` it matched and the `group_rows` they stand for.
    """
    groups = {r["order"]: g for g in _group([r for r in records if r["reason"] is None]) for r in g}
    moved: dict[int, tuple[tuple[str, str, str], list[dict]]] = {}
    for key, entry in corrections.items():
        rows = [r for r in records if (r["event_date"], r["place"], r["state"]) == key and r["date_basis"] in ("stated", "window")]
        members = {m["order"]: m for r in rows for m in groups.get(r["order"], [r])}
        entry.update(rows=len(rows), group_rows=len(members), geocoded=None if rows[-1]["found"] is None else
                     dict(zip(("latitude", "longitude", "accuracy_km", "source"), rows[-1]["found"])))
        for row in rows:
            group = groups.get(row["order"], [row])
            if entry["action"] == "exclude":
                for member in group:
                    member["reason"] = "qa_excluded"
                    member["qa_reason"] = entry["reason"] if member is row else                         f"{entry['reason']} (same event as {row['place']} on {row['event_date']})"
            else:
                survivor = group[0]
                if survivor["order"] in moved and moved[survivor["order"]][0] != key:
                    raise ValueError(f"{CORRECTIONS_NAME}: {moved[survivor['order']][0]} and {key} correct the same duplicate group")
                moved[survivor["order"]] = (key, group)
    for key, group in moved.values():
        survivor, entry = group[0], corrections[key]
        if survivor["reason"] == "qa_excluded":
            continue
        _reset(survivor)
        _place(survivor, (entry["latitude"], entry["longitude"], entry["accuracy_km"], "qa_correction"))
        survivor["twins"] = group[1:]
        for twin in group[1:]:
            _beaten_by(twin, survivor)


def _drop_duplicates(records: list[dict]) -> None:
    """Mark as `duplicate` every candidate beaten by a kept one (smaller accuracy, then earlier listed). A kept row takes the
    earliest date of its group (the group is formed on the stated dates), counting the twins a QA correction already folded
    into any member; its `merged` entry records the group."""
    for group in _group([r for r in records if r["reason"] is None]):
        kept = group[0]
        for record in group[1:]:
            _beaten_by(record, kept)
        full = [m for r in group for m in (r, *r.get("twins", []))]
        if len(full) > 1:
            stated = kept["day"]
            kept["day"] = min(r["day"] for r in full)
            kept["merged"] = {
                "kept": {"place": kept["place"], "outlet": kept["outlet"], "source_url": kept["source_url"]},
                "stated_date": stated.isoformat(),
                "date": kept["day"].isoformat(),
                "dates": sorted({r["event_date"] for r in full}),
                "dropped": [{"place": r["place"], "event_date": r["event_date"], "outlet": r["outlet"],
                             "source_url": r["source_url"]} for r in full[1:]],
            }


# --- writing ------------------------------------------------------------------------------------------------------

def _location_text(record: dict) -> str:
    return ", ".join(part for part in (record["place"], record["district"], record["state"]) if part)


def _admitted_frame(records: list[dict]) -> pd.DataFrame:
    admitted = sorted((r for r in records if r["reason"] is None), key=lambda r: (r["day"], r["order"]))
    rows = [{"date": r["day"].isoformat(), "latitude": r["lat"], "longitude": r["lon"], "location_text": _location_text(r),
             "source_url": r["source_url"], "accuracy_km": r["accuracy_km"], "year": r["day"].year, "place": r["place"],
             "district": r["district"], "state": r["state"], "outlet": r["outlet"], "geocode_source": r["geocode_source"],
             "description": r["description"], "date_basis": r["date_basis"],
             "window_end": "" if r["window_end_day"] is None else r["window_end_day"].isoformat(),
             "how_found": r["how_found"], "trigger": r["trigger"], "record_id": r["record_id"]} for r in admitted]
    return pd.DataFrame(rows, columns=[*ledger.COLUMNS, *EXTRA_COLUMNS])


def _write_csv(path: Path, frame: pd.DataFrame, columns) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        writer.writerows(frame[list(columns)].itertuples(index=False, name=None))


def _summary(records: list[dict]) -> dict:
    stated = [r for r in records if r["date_basis"] == "stated"]
    located = [r for r in records if r["lat"] is not None]
    regions = [*grid.regions(), OUTSIDE]
    return {
        "raw": len(records),
        "stated": len(stated),
        "geocoded": len(located),
        "geocoded_by_source": dict(Counter(r["geocode_source"] for r in located)),
        "admitted": sum(r["reason"] is None for r in records),
        "rejected": dict(Counter(r["reason"] for r in records if r["reason"])),
        "by_region": {name: {"geocoded": sum(r["region"] == name for r in located),
                             "admitted": sum(r["region"] == name and r["reason"] is None for r in located)} for name in regions},
    }


def _read_qa_keys(path: Path) -> set[tuple[str, str, str]]:
    """The (date, place, state) of every row of the QA results at `path`; empty when the file does not exist."""
    if not Path(path).is_file():
        return set()
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        missing = [c for c in ("date", "place", "state") if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{Path(path).name}: missing column(s) {missing}")
        return {(row["date"].strip(), row["place"].strip(), row["state"].strip()) for row in reader}


def _unchecked(admitted: pd.DataFrame, qa_results: Path) -> list[dict]:
    """The admitted events (date, place, state, source_url) that have no row in the QA results at `qa_results`."""
    checked = _read_qa_keys(qa_results)
    return [{"date": r["date"], "place": r["place"], "state": r["state"], "source_url": r["source_url"]}
            for r in admitted.to_dict("records") if (r["date"], r["place"], r["state"]) not in checked]


def _rejected_entry(record: dict) -> dict:
    entry = {"year": record["year"], "event_date": record["event_date"], "place": record["place"],
             "district": record["district"], "state": record["state"], "source_url": record["source_url"],
             "outlet": record["outlet"], "reason": record["reason"], "latitude": record["lat"], "longitude": record["lon"],
             "accuracy_km": record["accuracy_km"], "geocode_source": record["geocode_source"]}
    for extra in ("trigger", "record_id"):
        if record.get(extra):
            entry[extra] = record[extra]
    for extra in ("duplicate_of", "qa_reason"):
        if extra in record:
            entry[extra] = record[extra]
    return entry


# --- the build ----------------------------------------------------------------------------------------------------

def build_inventory(raw_dir: Path, places: pd.DataFrame | None, out_dir: Path | None = None, geocoder: Geocoder | None = None,
                    fetch: Callable[[str], list[dict]] | None = None, cache: Path | None = None,
                    offline: bool = False, corrections: Path | None = None, qa_results: Path | None = None,
                    max_accuracy_km: float = MAX_ACCURACY_KM) -> pd.DataFrame:
    """Geocode the rows of `<raw_dir>/<year>.csv`, admit those the module docstring allows and write the files into `out_dir`
    (default the parent of `raw_dir`): `<year>.csv` per raw year, `qa/inventory_admitted.csv` and `inventory_report.json`.

    Returns the admitted rows (ledger columns, then EXTRA_COLUMNS), by date. `places` is the table of `geocode.load_places()`;
    `fetch` and `cache` go to `geocode_any` (defaults: the throttled Nominatim call and its on-disk cache). `geocoder(place,
    district, state) -> (lat, lon, accuracy_km, source) | None` replaces `geocode_any` (for tests). With `offline` a Nominatim
    query missing from the cache raises `GeocodeError` naming it instead of being fetched. `corrections` is the QA corrections file
    (default `<out_dir>/qa/corrections.csv`, used when it exists) and `qa_results` the spot-check results the admitted rows are
    held against (default `<out_dir>/qa/qa_results.csv`). `max_accuracy_km` is the accuracy limit of admission."""
    raw_dir = Path(raw_dir)
    out_dir = Path(out_dir) if out_dir is not None else raw_dir.parent
    fetched = []

    def counted(query: str) -> list[dict]:
        if offline:
            raise GeocodeError(f"offline: the Nominatim query {query!r} is not in the cache")
        fetched.append(query)
        return (fetch or nominatim_fetch)(query)

    geocoder = geocoder or (lambda place, district, state: geocode_any(place, district, state, places, fetch=counted, cache=cache))
    records = _read_raw(raw_dir)
    corrections = _read_corrections(corrections if corrections is not None else out_dir / QA_DIR / CORRECTIONS_NAME)
    _check_corrections(corrections, records)
    for record in records:
        _locate(record, geocoder, max_accuracy_km)
    _apply_corrections(records, corrections)
    _drop_duplicates(records)

    admitted = _admitted_frame(records)
    out_dir.mkdir(parents=True, exist_ok=True)
    years = sorted({r["year"] for r in records})
    for year in years:
        _write_csv(out_dir / f"{year}.csv", admitted[(admitted["year"] == year) & (admitted["date_basis"] != "window")],
                   ledger.COLUMNS)
    (out_dir / QA_DIR).mkdir(exist_ok=True)
    _write_csv(out_dir / QA_DIR / COMBINED_NAME, admitted, [*ledger.COLUMNS, *EXTRA_COLUMNS])
    unchecked = _unchecked(admitted, qa_results if qa_results is not None else out_dir / QA_DIR / QA_RESULTS_NAME)
    dump_json(out_dir / REPORT_NAME, {
        "max_accuracy_km": max_accuracy_km,
        "same_place_km": SAME_PLACE_KM,
        "osm_fetched": len(fetched),
        "totals": {**_summary(records), "unchecked": len(unchecked)},
        "years": {str(y): _summary([r for r in records if r["year"] == y]) for y in years},
        "rejected": [_rejected_entry(r) for r in records if r["reason"]],
        "merged_events": [r["merged"] for r in records if "merged" in r],
        "unchecked": unchecked,
        "corrections": [{"date": c["key"][0], "place": c["key"][1], "state": c["key"][2],
                         **{k: v for k, v in c.items() if k != "key"}} for c in corrections.values()],
    })
    return admitted


def write_inventory(directory: Path, places: pd.DataFrame, say=print, offline: bool = False,
                    max_accuracy_km: float = MAX_ACCURACY_KM) -> pd.DataFrame:
    """`build_inventory` of `<directory>/raw` into `directory`, saying one line per year and the number of Nominatim fetches."""
    admitted = build_inventory(Path(directory) / "raw", places, out_dir=directory, offline=offline,
                               max_accuracy_km=max_accuracy_km)
    report = json.loads((Path(directory) / REPORT_NAME).read_text(encoding="utf-8"))
    for year, entry in report["years"].items():
        say(f"{year}: {entry['raw']} raw, {entry['stated']} stated, {entry['geocoded']} geocoded, {entry['admitted']} admitted")
    say(f"{len(admitted)} admitted of {report['totals']['raw']}; {report['osm_fetched']} Nominatim query(ies) fetched; "
        f"wrote {Path(directory) / REPORT_NAME}")
    unchecked = report["totals"]["unchecked"]
    say(f"{unchecked} admitted row(s) have no result in {QA_DIR}/{QA_RESULTS_NAME}" if unchecked
        else f"every admitted row has a result in {QA_DIR}/{QA_RESULTS_NAME}")
    return admitted
