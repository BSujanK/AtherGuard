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
  kept, the earliest listed (by year file, then line) among equals.

Admitted rows go to `<year>.csv` in the ledger format (`ledger.COLUMNS`, `location_text` = "place, district, state") and, with
the extra columns `EXTRA_COLUMNS`, to `inventory_admitted.csv` for the spot-check against the source URLs.
`inventory_report.json` counts, per year and in total, the raw, stated and geocoded rows (by source and by region), the admitted
rows and the rejections by reason, lists every rejected row with its reason, and says how many Nominatim queries were not in
the cache and had to be fetched (`osm_fetched`; 0 on a rerun).
"""
from __future__ import annotations

import csv
import json
import re
from collections import Counter
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import pandas as pd

from .. import grid
from ..hazard.jsonio import dump_json
from . import geocode as gc
from . import ledger
from .geocode_osm import geocode_any, nominatim_fetch

RAW_COLUMNS = ("event_date", "date_basis", "place", "district", "state", "source_url", "outlet", "description")
EXTRA_COLUMNS = ("year", "place", "district", "state", "outlet", "geocode_source", "description")
REPORT_NAME, COMBINED_NAME = "inventory_report.json", "inventory_admitted.csv"
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
    if fields["date_basis"] not in ("stated", "report"):
        raise ValueError(f"date_basis {fields['date_basis']!r} is neither 'stated' nor 'report'")
    for name in ("place", "state", "source_url"):
        if not fields[name]:
            raise ValueError(f"{name} is empty")
    return {"day": day, "year": year}


# --- deciding -----------------------------------------------------------------------------------------------------

def _duplicate(a: dict, b: dict) -> bool:
    """Whether two located rows are one event: same cell on the same day, or within a day in one cell or within 5 km."""
    if abs((a["day"] - b["day"]).days) > 1:
        return False
    return a["cell_id"] == b["cell_id"] or float(gc._haversine_km(a["lat"], a["lon"], b["lat"], b["lon"])) <= SAME_PLACE_KM


def _locate(record: dict, geocoder: Geocoder) -> None:
    """Geocode a stated row and set its `reason` (None = still a candidate) and, when found, its point and region."""
    record.update(reason=None, lat=None, lon=None, accuracy_km=None, geocode_source=None, region=None, cell_id=None)
    if record["date_basis"] != "stated":
        record["reason"] = "report_dated"
        return
    found = geocoder(record["place"], record["district"], record["state"])
    if found is None:
        record["reason"] = "ungeocodable"
        return
    lat, lon, accuracy, source = found
    record.update(lat=round(float(lat), DECIMALS), lon=round(float(lon), DECIMALS), accuracy_km=float(accuracy),
                  geocode_source=source)
    record["region"] = grid.region_of(record["lat"], record["lon"]) or OUTSIDE
    if record["region"] == OUTSIDE:
        record["reason"] = OUTSIDE
        return
    record["cell_id"] = int(grid.latlon_to_cell(record["lat"], record["lon"]))
    if record["accuracy_km"] > MAX_ACCURACY_KM:
        record["reason"] = "accuracy_over_10km"


def _drop_duplicates(records: list[dict]) -> None:
    """Mark as `duplicate` every candidate beaten by a kept one (smaller accuracy, then earlier listed)."""
    kept = []
    for record in sorted((r for r in records if r["reason"] is None), key=lambda r: (r["accuracy_km"], r["order"])):
        twin = next((k for k in kept if _duplicate(record, k)), None)
        if twin is None:
            kept.append(record)
        else:
            record["reason"] = "duplicate"
            record["duplicate_of"] = f"{twin['place']} on {twin['day'].isoformat()} ({twin['outlet']}, {twin['source_url']})"


# --- writing ------------------------------------------------------------------------------------------------------

def _location_text(record: dict) -> str:
    return ", ".join(part for part in (record["place"], record["district"], record["state"]) if part)


def _admitted_frame(records: list[dict]) -> pd.DataFrame:
    admitted = sorted((r for r in records if r["reason"] is None), key=lambda r: (r["day"], r["order"]))
    rows = [{"date": r["day"].isoformat(), "latitude": r["lat"], "longitude": r["lon"], "location_text": _location_text(r),
             "source_url": r["source_url"], "accuracy_km": r["accuracy_km"], "year": r["year"], "place": r["place"],
             "district": r["district"], "state": r["state"], "outlet": r["outlet"], "geocode_source": r["geocode_source"],
             "description": r["description"]} for r in admitted]
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


def _rejected_entry(record: dict) -> dict:
    entry = {"year": record["year"], "event_date": record["event_date"], "place": record["place"],
             "district": record["district"], "state": record["state"], "source_url": record["source_url"],
             "outlet": record["outlet"], "reason": record["reason"], "latitude": record["lat"], "longitude": record["lon"],
             "accuracy_km": record["accuracy_km"], "geocode_source": record["geocode_source"]}
    if "duplicate_of" in record:
        entry["duplicate_of"] = record["duplicate_of"]
    return entry


# --- the build ----------------------------------------------------------------------------------------------------

def build_inventory(raw_dir: Path, places: pd.DataFrame | None, out_dir: Path | None = None, geocoder: Geocoder | None = None,
                    fetch: Callable[[str], list[dict]] | None = None, cache: Path | None = None) -> pd.DataFrame:
    """Geocode the rows of `<raw_dir>/<year>.csv`, admit those the module docstring allows and write the files into `out_dir`
    (default the parent of `raw_dir`): `<year>.csv` per raw year, `inventory_admitted.csv` and `inventory_report.json`.

    Returns the admitted rows (ledger columns, then EXTRA_COLUMNS), by date. `places` is the table of `geocode.load_places()`;
    `fetch` and `cache` go to `geocode_any` (defaults: the throttled Nominatim call and its on-disk cache). `geocoder(place,
    district, state) -> (lat, lon, accuracy_km, source) | None` replaces `geocode_any` (for tests)."""
    raw_dir = Path(raw_dir)
    out_dir = Path(out_dir) if out_dir is not None else raw_dir.parent
    fetched = []

    def counted(query: str) -> list[dict]:
        fetched.append(query)
        return (fetch or nominatim_fetch)(query)

    geocoder = geocoder or (lambda place, district, state: geocode_any(place, district, state, places, fetch=counted, cache=cache))
    records = _read_raw(raw_dir)
    for record in records:
        _locate(record, geocoder)
    _drop_duplicates(records)

    admitted = _admitted_frame(records)
    out_dir.mkdir(parents=True, exist_ok=True)
    years = sorted({r["year"] for r in records})
    for year in years:
        _write_csv(out_dir / f"{year}.csv", admitted[admitted["year"] == year], ledger.COLUMNS)
    _write_csv(out_dir / COMBINED_NAME, admitted, [*ledger.COLUMNS, *EXTRA_COLUMNS])
    dump_json(out_dir / REPORT_NAME, {
        "max_accuracy_km": MAX_ACCURACY_KM,
        "same_place_km": SAME_PLACE_KM,
        "osm_fetched": len(fetched),
        "totals": _summary(records),
        "years": {str(y): _summary([r for r in records if r["year"] == y]) for y in years},
        "rejected": [_rejected_entry(r) for r in records if r["reason"]],
    })
    return admitted


def write_inventory(directory: Path, places: pd.DataFrame, say=print) -> pd.DataFrame:
    """`build_inventory` of `<directory>/raw` into `directory`, saying one line per year and the number of Nominatim fetches."""
    admitted = build_inventory(Path(directory) / "raw", places, out_dir=directory)
    report = json.loads((Path(directory) / REPORT_NAME).read_text(encoding="utf-8"))
    for year, entry in report["years"].items():
        say(f"{year}: {entry['raw']} raw, {entry['stated']} stated, {entry['geocoded']} geocoded, {entry['admitted']} admitted")
    say(f"{len(admitted)} admitted of {report['totals']['raw']}; {report['osm_fetched']} Nominatim query(ies) fetched; "
        f"wrote {Path(directory) / REPORT_NAME}")
    return admitted
