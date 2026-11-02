"""Place-name geocoder: where a news report says a landslide happened, as coordinates.

`geocode(place, district, state, places)` turns the place text of a reported event into (lat, lon, accuracy_km) from the
GeoNames India dump (`load_places()`; every feature, not only the populated places >= 500 people of `serve.places`, because
hamlets, bridges and road points are what reports name). It returns None when the place cannot be placed, never a guess.

Names. The query and every candidate name (`name`, `asciiname`, each of the comma-separated `alternatenames`) are ASCII-folded
(accents dropped, lower case, apostrophes removed, any other punctuation a single space) and must then be equal. There is no
fuzzy matching: "Mundakkai" and "Mundakai" are different places here.

Messy place text ("Kavalappara, near Pothukal (Muthappan Hill)", "Pakshep village"). The queries are, in order: the whole
text, then each comma / semicolon / bracket segment left to right, each as written and without a trailing generic word
(village, hamlet, town, area). A query that starts with "near" or "nr" is never used, so "near Gangtok" never places an event in
Gangtok. The whole text and the first non-empty segment name the place and are good to 5 km; a match on a later segment (a locality
the place lies in or beside) is good to 15 km only. Segment queries shorter than 3 characters are ignored. The first query
with candidates in the state (and district) decides, even when it is ambiguous.

State. Required. Written variants (J&K, Uttaranchal) are mapped to the GeoNames admin1 name by `STATE_ALIASES`; a state that
is not in the table (a state outside the study domain, or a typo) returns None. Only places of that state are candidates.

District. Optional. When given it is applied to all candidates of the state, of every feature class, before the class is
chosen, so a same-name populated place in another district cannot hide the right one. A candidate matches when its district
equals the given one ASCII-folded (without a trailing "district", and also without a bracketed part), is listed in
`DISTRICT_ALIASES` ("Kullu" is "Kulu" in GeoNames), or is spelled alike: the directional / qualifier words (east, west,
north, south, upper, lower, central, new, old) must be the same set ("East Khasi Hills" is not "West Khasi Hills") and the
rest may differ by 2 edits when it is 6 or more characters ("Waynad"), 1 edit at 3-5, none below. When no candidate of a
query matches, that query has no result; if no query has one the answer is None: a district that disagrees with every
candidate is evidence against them, not noise.

Feature classes. Populated places (class P) are tried first; only when none of that name remains do the other named
features follow, class by class: S spots (bridge, temple), T terrain (pass, hill), H water, L areas, R roads.
Administrative divisions (class A) are never matched.

Result. One candidate: its coordinates with the query's accuracy (5 or 15 km). Several candidates in one district: their
centroid with accuracy equal to the distance to the farthest one (never below the query's accuracy), but None when that
spread exceeds 10 km. Candidates in different districts (or one with no district recorded beside one with): None, the
report is ambiguous.

CLI-free; the table is built on first use from https://download.geonames.org/export/dump/IN.zip (CC BY 4.0) and cached as
`<data>/raw/geonames/geonames_in_all.parquet`; both files are recorded in the data manifest. Attribution: GeoNames (CC BY 4.0).
"""
from __future__ import annotations

import io
import re
import unicodedata
import zipfile
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import PROJECT_ROOT, data_root
from ..http import download
from ..manifest import Manifest
from ..serve.places import (ADMIN1_FILE, ADMIN2_FILE, CITY_COLUMNS, GEONAMES_BASE, GEONAMES_LICENCE, _write_atomic,
                            read_admin_names)

IN_ZIP, IN_MEMBER = "IN.zip", "IN.txt"
TABLE_NAME = "geonames_in_all.parquet"
PLACE_COLUMNS = ["geonameid", "name", "asciiname", "alternatenames", "feature_class", "feature_code", "lat", "lon",
                 "population", "district", "state"]

NAMED_PLACE_KM = 5.0                                   # accuracy of a match on the whole text or its first segment
LOCALITY_KM = 15.0                                     # accuracy of a match on a later segment
MAX_SPREAD_KM = 10.0                                   # several matches further apart than this are not one place
MIN_SEGMENT_CHARS = 3
QUALIFIERS = frozenset({"east", "west", "north", "south", "upper", "lower", "central", "new", "old"})
FEATURE_ORDER = ("P", "S", "T", "H", "L", "R")         # populated places first, then the other named features
GENERIC_WORDS = ("village", "hamlet", "town", "area")  # dropped from the end of a place text
STATE_ALIASES = {                                      # folded spelling -> GeoNames admin1 name
    "jammu and kashmir": "Jammu and Kashmir", "jammu kashmir": "Jammu and Kashmir", "j k": "Jammu and Kashmir",
    "jk": "Jammu and Kashmir", "ladakh": "Ladakh", "leh ladakh": "Ladakh", "himachal pradesh": "Himachal Pradesh",
    "himachal": "Himachal Pradesh", "uttarakhand": "Uttarakhand", "uttaranchal": "Uttarakhand", "sikkim": "Sikkim",
    "west bengal": "West Bengal", "arunachal pradesh": "Arunachal Pradesh", "arunachal": "Arunachal Pradesh",
    "assam": "Assam", "meghalaya": "Meghalaya", "nagaland": "Nagaland", "manipur": "Manipur", "mizoram": "Mizoram",
    "tripura": "Tripura", "kerala": "Kerala", "karnataka": "Karnataka", "goa": "Goa", "maharashtra": "Maharashtra",
    "tamil nadu": "Tamil Nadu", "tamilnadu": "Tamil Nadu",
}
DISTRICT_ALIASES = {                                   # folded district in a report -> folded GeoNames district names
    "kullu": {"kulu"}, "mumbai": {"mumbai", "mumbai suburban", "mumbai city"}, "gurugram": {"gurgaon"},
    "shivamogga": {"shimoga"}, "tehri": {"tehri garhwal"}, "pauri garhwal": {"garhwal"},
}
IN_SOURCE_LABEL = "GeoNames India dump (all features)"
TABLE_SOURCE_LABEL = "GeoNames India places: every feature with district and state names"
EARTH_RADIUS_KM = 6371.0088


class GeocodeError(RuntimeError):
    """The place table cannot be built or read; the message names what is wrong."""


# --- folding ----------------------------------------------------------------------------------------------------

def fold(text) -> str:
    """ASCII-folded, lower-case, punctuation-free form of `text` used to compare names ('' for None / non-Latin text)."""
    if text is None or (isinstance(text, float) and np.isnan(text)):
        return ""
    ascii_text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", " ", re.sub(r"['`]", "", ascii_text)).strip()


def canonical_state(state: str | None) -> str | None:
    """The GeoNames admin1 name of a state as a report writes it, None when it is not a state of the study domain."""
    return STATE_ALIASES.get(fold(state))


def _district_key(district: str | None) -> str:
    return re.sub(r" district$", "", fold(district))


def _given_districts(district: str | None) -> list[str]:
    """The folded spellings of a district as a report gives it: as written, and without a bracketed part."""
    keys = [_district_key(district), _district_key(re.sub(r"\(.*?\)", " ", district or ""))]
    return [key for i, key in enumerate(keys) if key and key not in keys[:i]]


def _edit_distance_within(a: str, b: str, limit: int) -> bool:
    if abs(len(a) - len(b)) > limit:
        return False
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1] <= limit


def _split_qualifiers(key: str) -> tuple[frozenset[str], str]:
    words = key.split()
    return frozenset(w for w in words if w in QUALIFIERS), " ".join(w for w in words if w not in QUALIFIERS)


def _allowed_edits(shorter_length: int) -> int:
    return 2 if shorter_length >= 6 else 1 if shorter_length >= 3 else 0


def _same_district(key: str, candidate: str) -> bool:
    """Equal, listed in DISTRICT_ALIASES, or alike in spelling: the same directional / qualifier words ("East Khasi Hills"
    is not "West Khasi Hills") and the rest within 2 edits (6 or more characters), 1 edit (3-5) or equal (fewer)."""
    if key == candidate or candidate in DISTRICT_ALIASES.get(key, ()):
        return True
    qualifiers, rest = _split_qualifiers(key)
    candidate_qualifiers, candidate_rest = _split_qualifiers(candidate)
    return qualifiers == candidate_qualifiers and _edit_distance_within(
        rest, candidate_rest, _allowed_edits(min(len(rest), len(candidate_rest))))


def _district_matches(given: list[str], candidate: str) -> bool:
    return bool(candidate) and any(_same_district(key, candidate) for key in given)


def candidate_queries(place: str) -> list[tuple[str, float]]:
    """(folded name, accuracy_km) to look up for the place text of a report, most specific first (see the module docstring)."""
    queries: dict[str, float] = {}

    def add(key: str, accuracy: float, segment: bool) -> None:
        if key and not key.startswith(("near ", "nr ")) and not (segment and len(key) < MIN_SEGMENT_CHARS):
            queries.setdefault(key, accuracy)

    def variants(key: str, accuracy: float, segment: bool) -> None:
        add(key, accuracy, segment)
        for word in GENERIC_WORDS:
            if key.endswith(" " + word):
                add(key[: -len(word) - 1], accuracy, segment)

    variants(fold(place), NAMED_PLACE_KM, False)
    segments = [key for key in (fold(segment) for segment in re.split(r"[,;()\[\]]", str(place))) if key]
    for i, key in enumerate(segments):
        variants(key, NAMED_PLACE_KM if i == 0 else LOCALITY_KM, True)
    return list(queries.items())


# --- the place index ---------------------------------------------------------------------------------------------

@dataclass
class _Index:
    frame: pd.DataFrame                 # kept so the identity check below cannot be fooled by a reused id()
    by_name: dict[str, np.ndarray]      # folded name / asciiname / alternate name -> row positions
    state: np.ndarray
    district: np.ndarray
    feature_class: np.ndarray
    lat: np.ndarray
    lon: np.ndarray


_cache: _Index | None = None


def _build_index(places: pd.DataFrame) -> _Index:
    missing = [c for c in PLACE_COLUMNS if c not in places.columns]
    if missing:
        raise GeocodeError(f"the places table lacks the columns {missing}")
    rows: dict[str, list[int]] = defaultdict(list)
    for position, (name, ascii_name, alternates) in enumerate(zip(places["name"], places["asciiname"], places["alternatenames"])):
        keys = {fold(name), fold(ascii_name)}
        if isinstance(alternates, str) and alternates:
            keys.update(fold(alternate) for alternate in alternates.split(","))
        for key in keys:
            if key:
                rows[key].append(position)
    return _Index(
        frame=places,
        by_name={key: np.asarray(positions, dtype=np.int64) for key, positions in rows.items()},
        state=np.array([fold(s) for s in places["state"]], dtype=object),
        district=np.array([_district_key(d) for d in places["district"]], dtype=object),
        feature_class=places["feature_class"].to_numpy(dtype=object),
        lat=places["lat"].to_numpy(dtype=np.float64), lon=places["lon"].to_numpy(dtype=np.float64))


def _index(places: pd.DataFrame) -> _Index:
    """The index of `places`, built once per frame (the last one used is kept; do not edit a frame between calls)."""
    global _cache
    if _cache is None or _cache.frame is not places:
        _cache = _build_index(places)
    return _cache


# --- geocoding --------------------------------------------------------------------------------------------------

def _haversine_km(lat, lon, lat0: float, lon0: float) -> np.ndarray:
    p, p0 = np.radians(lat), np.radians(lat0)
    a = np.sin((p - p0) / 2) ** 2 + np.cos(p) * np.cos(p0) * np.sin(np.radians(lon - lon0) / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a))


def _resolve(index: _Index, rows: np.ndarray, accuracy_km: float) -> tuple[float, float, float] | None:
    if len(set(index.district[rows])) > 1:
        return None
    lat, lon = index.lat[rows], index.lon[rows]
    if len(rows) == 1:
        return float(lat[0]), float(lon[0]), accuracy_km
    centre_lat, centre_lon = float(lat.mean()), float(lon.mean())
    spread = float(_haversine_km(lat, lon, centre_lat, centre_lon).max())
    if spread > MAX_SPREAD_KM:
        return None
    return centre_lat, centre_lon, max(spread, accuracy_km)


def geocode(place: str, district: str | None, state: str, places: pd.DataFrame) -> tuple[float, float, float] | None:
    """(lat, lon, accuracy_km) of the place a report names, or None when it is unknown, in another state or district,
    ambiguous, or its candidates are spread over more than 10 km.

    Matching, state, district, feature classes and the accuracy follow the module docstring; `places` is the table of
    `load_places()`."""
    canonical = canonical_state(state)
    if canonical is None:
        return None
    index = _index(places)
    state_key, given = fold(canonical), _given_districts(district)
    for query, accuracy_km in candidate_queries(place):
        rows = index.by_name.get(query)
        if rows is None:
            continue
        rows = rows[index.state[rows] == state_key]
        if given and len(rows):
            matching = {d: _district_matches(given, d) for d in set(index.district[rows])}
            rows = rows[[matching[d] for d in index.district[rows]]]
        for feature_class in FEATURE_ORDER:
            tier = rows[index.feature_class[rows] == feature_class]
            if len(tier):
                return _resolve(index, tier, accuracy_km)
    return None


# --- the table --------------------------------------------------------------------------------------------------

def read_in_dump(path: Path) -> pd.DataFrame:
    """The rows of IN.txt inside the GeoNames IN.zip (tab separated, UTF-8, no header), as strings."""
    try:
        with zipfile.ZipFile(path) as archive:
            raw = archive.read(IN_MEMBER)
    except (zipfile.BadZipFile, KeyError) as error:
        raise GeocodeError(f"{path.name} is not a GeoNames zip holding {IN_MEMBER}: {error}") from None
    return pd.read_csv(io.BytesIO(raw), sep="\t", header=None, names=CITY_COLUMNS, dtype=str, keep_default_na=False, quoting=3,
                       usecols=["geonameid", "name", "asciiname", "alternatenames", "latitude", "longitude", "feature_class",
                                "feature_code", "country_code", "admin1", "admin2", "population"])


def extract_table(dump: pd.DataFrame, admin1: dict[str, str], admin2: dict[str, str]) -> pd.DataFrame:
    """PLACE_COLUMNS rows of the India dump, admin codes mapped to names (None where GeoNames has no code or no name)."""
    lat = pd.to_numeric(dump["latitude"], errors="coerce")
    lon = pd.to_numeric(dump["longitude"], errors="coerce")
    keep = lat.notna() & lon.notna() & (dump["name"] != "")
    kept = dump[keep]
    state_key = kept["country_code"] + "." + kept["admin1"]
    district_key = state_key + "." + kept["admin2"]
    frame = pd.DataFrame({
        "geonameid": pd.to_numeric(kept["geonameid"]).astype("int64"),
        "name": kept["name"],
        "asciiname": kept["asciiname"].where(kept["asciiname"] != "", kept["name"]),
        "alternatenames": kept["alternatenames"],
        "feature_class": kept["feature_class"],
        "feature_code": kept["feature_code"],
        "lat": lat[keep].astype("float64"),
        "lon": lon[keep].astype("float64"),
        "population": pd.to_numeric(kept["population"], errors="coerce").fillna(0).astype("int64"),
        "district": district_key.map(admin2).where(kept["admin2"] != ""),
        "state": state_key.map(admin1).where(kept["admin1"] != ""),
    })
    frame = frame.sort_values("geonameid", kind="stable").reset_index(drop=True)
    return frame.astype({"district": object, "state": object}).where(frame.notna(), None)


def build_places_table(raw_dir: Path, manifest: Manifest, fetch: Callable = download) -> pd.DataFrame:
    """Fetch IN.zip and the admin name files (each only when not current in the manifest), write
    `<raw_dir>/geonames_in_all.parquet`, record it in the manifest and return the table."""
    wanted = {IN_ZIP: IN_SOURCE_LABEL, ADMIN1_FILE: "GeoNames admin1 codes (state / province names, ASCII)",
              ADMIN2_FILE: "GeoNames admin2 codes (district names)"}
    for file, label in wanted.items():
        if not manifest.is_current(raw_dir / file):
            fetch(GEONAMES_BASE + file, raw_dir / file, manifest, label, GEONAMES_LICENCE)
    table = extract_table(read_in_dump(raw_dir / IN_ZIP), read_admin_names(raw_dir / ADMIN1_FILE), read_admin_names(raw_dir / ADMIN2_FILE))
    path = raw_dir / TABLE_NAME
    _write_atomic(path, lambda partial: table.to_parquet(partial, index=False))
    manifest.add(path, TABLE_SOURCE_LABEL, f"derived: {GEONAMES_BASE}{IN_ZIP}, {ADMIN1_FILE}, {ADMIN2_FILE}", GEONAMES_LICENCE)
    return table


def load_places() -> pd.DataFrame:
    """The India places table (PLACE_COLUMNS), built from IN.zip and cached under `<data>/raw/geonames/` on first use."""
    raw_dir = data_root() / "raw" / "geonames"
    path = raw_dir / TABLE_NAME
    if not path.exists():
        return build_places_table(raw_dir, Manifest(PROJECT_ROOT / "manifests" / "data_manifest.jsonl", data_root()))
    try:
        table = pd.read_parquet(path)
    except (OSError, ValueError) as error:
        raise GeocodeError(f"{path.name} cannot be read: {error}") from None
    missing = [c for c in PLACE_COLUMNS if c not in table.columns]
    if missing:
        raise GeocodeError(f"{path.name} lacks the columns {missing}")
    return table[PLACE_COLUMNS]
