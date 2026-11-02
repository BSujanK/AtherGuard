"""Place-name geocoder: where a news report says a landslide happened, as coordinates.

`geocode(place, district, state, places)` turns the place text of a reported event into (lat, lon, accuracy_km) from the
GeoNames India dump (`load_places()`; every feature, not only the populated places >= 500 people of `serve.places`, because
hamlets, bridges and road points are what reports name). It returns None when the place cannot be placed, never a guess.

Names. The query and every candidate name (`name`, `asciiname`, each of the comma-separated `alternatenames`) are ASCII-folded
(accents dropped, lower case, apostrophes removed, any other punctuation a single space) and must then be equal. There is no
fuzzy matching: "Mundakkai" and "Mundakai" are different places here.

Messy place text ("Kavalappara, near Pothukal (Muthappan Hill)", "Pakshep village"). The whole text is tried first, then each
comma / semicolon / bracket segment left to right, each as written, without a leading "near" and without a trailing generic
word (village, hamlet, town, area). The first query with a match in the state decides, even when that match is ambiguous: an
ambiguous first segment is not replaced by a later, more distant one.

State. Required. Written variants (J&K, Uttaranchal) are mapped to the GeoNames admin1 name by `STATE_ALIASES`; a state that
is not in the table (a state outside the study domain, or a typo) returns None. Only places of that state are candidates.

Feature classes. Populated places (class P) are tried first; only when none of that name exists in the state do the other
named features follow, class by class: S spots (bridge, temple), T terrain (pass, hill), H water, L areas, R roads.
Administrative divisions (class A) are never matched.

District. Optional evidence, compared ASCII-folded and without a trailing "district". When it matches some of the candidates
only those are kept; when it matches none of them (reports spell districts differently from GeoNames) it is ignored and the
state-only rules apply, so a district spelling difference alone never rejects a place.

Result. One candidate: its coordinates with accuracy 5 km. Several candidates in one district: their centroid with accuracy
equal to the distance to the farthest one (never below 5 km, the accuracy of a single match). Candidates in different districts
(or one with no district recorded beside one with): None, the report is ambiguous.

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

SINGLE_MATCH_KM = 5.0
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


def candidate_queries(place: str) -> list[str]:
    """The folded names to look up for the place text of a report, most specific first (see the module docstring)."""
    queries: list[str] = []

    def add(key: str) -> None:
        if key and key not in queries:
            queries.append(key)

    def variants(key: str) -> None:
        key = re.sub(r"^(near|nr) ", "", key)
        add(key)
        for word in GENERIC_WORDS:
            if key.endswith(" " + word):
                add(key[: -len(word) - 1])

    variants(fold(place))
    for segment in re.split(r"[,;()\[\]]", str(place)):
        variants(fold(segment))
    return queries


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


def _resolve(index: _Index, rows: np.ndarray, district_key: str) -> tuple[float, float, float] | None:
    if district_key:
        in_district = rows[index.district[rows] == district_key]
        if len(in_district):
            rows = in_district
    if len(set(index.district[rows])) > 1:
        return None
    lat, lon = index.lat[rows], index.lon[rows]
    if len(rows) == 1:
        return float(lat[0]), float(lon[0]), SINGLE_MATCH_KM
    centre_lat, centre_lon = float(lat.mean()), float(lon.mean())
    farthest = float(_haversine_km(lat, lon, centre_lat, centre_lon).max())
    return centre_lat, centre_lon, max(farthest, SINGLE_MATCH_KM)


def geocode(place: str, district: str | None, state: str, places: pd.DataFrame) -> tuple[float, float, float] | None:
    """(lat, lon, accuracy_km) of the place a report names, or None when it is unknown, in another state or ambiguous.

    Matching, state, feature classes, the optional district and the accuracy follow the module docstring; `places` is the
    table of `load_places()`."""
    canonical = canonical_state(state)
    if canonical is None:
        return None
    index = _index(places)
    state_key, district_key = fold(canonical), _district_key(district)
    for query in candidate_queries(place):
        rows = index.by_name.get(query)
        if rows is None:
            continue
        rows = rows[index.state[rows] == state_key]
        for feature_class in FEATURE_ORDER:
            tier = rows[index.feature_class[rows] == feature_class]
            if len(tier):
                return _resolve(index, tier, district_key)
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
