"""Second-pass place geocoder: OpenStreetMap's Nominatim for the reported places GeoNames cannot place.

`geocode_any(place, district, state, places)` tries `geocode.geocode` (GeoNames) first and asks Nominatim only when that returns
None; the fourth element of its answer names the source, "geonames" or "osm". `osm_geocode` is the Nominatim half on its own.
Both return None rather than a guess.

Queries, in order: the place text as written, then each segment of it (the segment logic of `geocode.candidate_queries`: comma /
semicolon / bracket segments left to right, each also without a trailing village / hamlet / town / area, in its folded spelling;
a segment starting with "near" or "nr" or shorter than 3 characters is never queried, "NH-29" is kept as "nh 29"). Each is asked
as "<text>, <district>, <state>, India" and then, when a district is named, as "<text>, <state>, India". The first query with
acceptable results decides, even when they are ambiguous (None): a later query is never tried past it. The state is the
GeoNames admin1 name of `geocode.canonical_state`; a state outside the study domain returns None without a request. Parameters:
countrycodes=in, format=jsonv2, addressdetails=1, limit=10.

Acceptance. A result is discarded unless its `address.state` is the named state (same alias table as GeoNames) and, when a
district is named, the first of its `address.state_district`, `address.county`, `address.city_district` that is present denotes
that district (`geocode.district_matches` against the state's districts in the places table; a named district the table
lacks, such as a district created after the GeoNames dump, matches a result of the same name). Accuracy follows the kind of the
result (`addresstype`, then `type`): villages, hamlets, neighbourhoods, localities, peaks, passes, ridges, valleys, bridges,
tunnels and railway stations are good to 5 km; towns, roads (also `category` highway), tracks, rivers and streams to 10 km;
cities, municipalities, counties, districts, states, regions and any other kind are rejected. Several accepted results are one
place when within 10 km of their centroid (`geocode.merge_points`: accuracy max(coarsest kind, spread)), otherwise None. A match
on the whole text or its first segment keeps the accuracy of its kind; a match on a later segment is good to 15 km only
(`geocode.LOCALITY_KM`).

Usage policy (https://operations.osmfoundation.org/policies/nominatim/): an identifying User-Agent, at most one request per
second, every response cached on disk and a cached query never fetched again. This module is for the one-off set of reported
places, not for bulk or systematic querying. Responses are cached as JSON under `<data>/raw/geocode_cache/nominatim/`, one file
per query named by the SHA-1 of the query text; `record_cache` lists them in the data manifest (licence ODbL).

Geocoding © OpenStreetMap contributors (ODbL), via Nominatim. https://www.openstreetmap.org/copyright
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlencode

import numpy as np
import pandas as pd
import requests

from ..config import data_root
from ..manifest import Manifest
from ..serve.places import _write_atomic
from . import geocode as gc
from .geocode import GeocodeError

SEARCH_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "AetherGuard-research/1.0 (+https://github.com/BSujanK/AtherGuard)"
SEARCH_PARAMS = {"countrycodes": "in", "format": "jsonv2", "addressdetails": 1, "limit": 10}
MIN_INTERVAL_S = 1.1                                   # the policy allows one request per second; a margin on top
ATTEMPTS, BACKOFF_S, TIMEOUT_S = 3, 5.0, 60
OSM_LICENCE = "ODbL 1.0 (https://opendatacommons.org/licenses/odbl/1-0/); geocoding (c) OpenStreetMap contributors, via Nominatim"

POINT_KM, WIDE_KM = 5.0, 10.0
POINT_KINDS = frozenset({"village", "hamlet", "isolated_dwelling", "neighbourhood", "quarter", "suburb", "locality", "peak",
                         "mountain_pass", "ridge", "valley", "bridge", "tunnel", "station", "halt"})
WIDE_KINDS = frozenset({"town", "road", "highway", "track", "river", "stream"})
AREA_KINDS = frozenset({"city", "municipality", "county", "state_district", "district", "state", "region"})
DISTRICT_FIELDS = ("state_district", "county", "city_district")   # the address keys that can name a district, in this order

_last_request = float("-inf")


# --- the HTTP side ----------------------------------------------------------------------------------------------

def _throttle(clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep) -> None:
    """Block until `MIN_INTERVAL_S` has passed since the previous request of this process, then count this one."""
    global _last_request
    wait = _last_request + MIN_INTERVAL_S - clock()
    if wait > 0:
        sleep(wait)
    _last_request = clock()


def nominatim_fetch(query: str, sleep: Callable[[float], None] = time.sleep) -> list[dict]:
    """The Nominatim search results for a free-text query (throttled, retried on a network error, HTTP 429 or 5xx)."""
    problem = ""
    for attempt in range(ATTEMPTS):
        _throttle()
        try:
            response = requests.get(SEARCH_URL, params={"q": query, **SEARCH_PARAMS}, headers={"User-Agent": USER_AGENT},
                                    timeout=TIMEOUT_S)
        except requests.RequestException as error:
            problem = f"{type(error).__name__}: {error}"
        else:
            code = response.status_code
            if code == 200:
                try:
                    body = response.json()
                except ValueError as error:
                    raise GeocodeError(f"Nominatim sent invalid JSON for {query!r}: {error}") from None
                if not isinstance(body, list):
                    raise GeocodeError(f"Nominatim sent {type(body).__name__}, not a list, for {query!r}")
                return body
            if code != 429 and code < 500:
                raise GeocodeError(f"Nominatim answered HTTP {code} for {query!r}")
            problem = f"HTTP {code}"
        if attempt < ATTEMPTS - 1:
            sleep(BACKOFF_S * 2 ** attempt)
    raise GeocodeError(f"Nominatim failed for {query!r} after {ATTEMPTS} attempts: {problem}")


def _search(query: str, fetch: Callable[[str], list[dict]], cache_dir: Path) -> list[dict]:
    """The results for `query` from the cache, else from `fetch` (cached before they are returned)."""
    path = cache_dir / (hashlib.sha1(query.encode("utf-8")).hexdigest() + ".json")
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))["response"]
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise GeocodeError(f"{path.name} cannot be read: {error}") from None
    response = fetch(query)
    cache_dir.mkdir(parents=True, exist_ok=True)
    _write_atomic(path, lambda partial: partial.write_text(json.dumps({"query": query, "response": response}, ensure_ascii=False),
                                                           encoding="utf-8"))
    return response


def record_cache(manifest: Manifest, cache: Path | None = None) -> int:
    """Record every cached response not yet current in the data manifest with the ODbL licence; returns how many were added."""
    cache_dir = Path(cache) if cache is not None else data_root() / "raw" / "geocode_cache" / "nominatim"
    added = 0
    for path in sorted(cache_dir.glob("*.json")):
        if not manifest.is_current(path):
            query = json.loads(path.read_text(encoding="utf-8"))["query"]
            manifest.add(path, "OpenStreetMap Nominatim search response", f"{SEARCH_URL}?{urlencode({'q': query, **SEARCH_PARAMS})}",
                         OSM_LICENCE)
            added += 1
    return added


# --- accepting a result -----------------------------------------------------------------------------------------

def _accuracy_km(result: dict) -> float | None:
    """The accuracy of a result by its kind, None for a kind that is not a point-like place."""
    if result.get("addresstype") in AREA_KINDS:
        return None
    for kind in (result.get("addresstype"), result.get("type")):
        if kind in POINT_KINDS:
            return POINT_KM
        if kind in WIDE_KINDS:
            return WIDE_KM
    return WIDE_KM if result.get("category") == "highway" else None


def _in_district(address: dict, wanted: set[str], scope: list[str]) -> bool:
    """Whether the first district-naming field of the address denotes one of the `wanted` districts."""
    for field in DISTRICT_FIELDS:
        if address.get(field):
            return bool(wanted & gc.district_matches(address[field], scope))
    return False


def _squash(text) -> str:
    return re.sub(r"\s+", " ", str(text)).strip()


def _point(result: dict) -> tuple[float, float]:
    try:
        return float(result["lat"]), float(result["lon"])
    except (KeyError, TypeError, ValueError):
        raise GeocodeError(f"a Nominatim result has no usable lat / lon: {str(result)[:200]}") from None


def _accepted(results: list[dict], state: str, wanted: set[str] | None, scope: list[str]) -> list[tuple[float, float, float]]:
    """(lat, lon, accuracy_km) of each result in `state` (and in a `wanted` district) that is a point-like place."""
    found = []
    for result in results:
        address = result.get("address") or {}
        accuracy = _accuracy_km(result)
        if accuracy is None or gc.canonical_state(address.get("state")) != state:
            continue
        if wanted is not None and not _in_district(address, wanted, scope):
            continue
        found.append((*_point(result), accuracy))
    return found


def _texts(place: str) -> list[tuple[str, float]]:
    """(text to ask Nominatim about, accuracy_km of a match on it): the place as written, then its segments (see the docstring)."""
    texts = {}
    if not gc.fold(place).startswith(("near ", "nr ")):
        texts[place] = gc.NAMED_PLACE_KM
    for key, accuracy in gc.candidate_queries(place):
        if key != gc.fold(place):
            texts.setdefault(key, accuracy)
    return list(texts.items())


# --- geocoding --------------------------------------------------------------------------------------------------

def osm_geocode(place: str, district: str | None, state: str, fetch: Callable[[str], list[dict]] | None = None,
                cache: Path | None = None, places: pd.DataFrame | None = None) -> tuple[float, float, float] | None:
    """(lat, lon, accuracy_km) of the place a report names according to Nominatim, or None when it is not found, lies in
    another state or district, is not a point-like place, or its results are spread over more than 10 km.

    `fetch(query) -> list of Nominatim results` defaults to the throttled HTTP call; `cache` is the cache directory (default
    `<data>/raw/geocode_cache/nominatim`); `places` is the table of `geocode.load_places()` giving the districts of the
    state (loaded only when a district is named and `places` is not passed). The module docstring has the rules."""
    canonical = gc.canonical_state(state)
    place = _squash(place)
    if canonical is None or not place:
        return None
    fetch = fetch or nominatim_fetch
    cache_dir = Path(cache) if cache is not None else data_root() / "raw" / "geocode_cache" / "nominatim"
    wanted, scope = None, []
    given = ""
    if gc._district_key(district):
        scope = list(gc.known_districts(places if places is not None else gc.load_places(), canonical))
        wanted = gc.district_matches(district, scope)
        if not wanted:                                 # a district the places table lacks: it can only match by its own name
            scope.append(gc._district_key(district))
            wanted = {scope[-1]}
        given = _squash(district)
    for text, query_km in _texts(place):
        for query in ([f"{text}, {given}, {canonical}, India"] if given else []) + [f"{text}, {canonical}, India"]:
            found = _accepted(_search(query, fetch, cache_dir), canonical, wanted, scope)
            if found:
                lat, lon, accuracy = np.array(found).T
                return gc.merge_points(lat, lon, max(float(accuracy.max()), query_km))
    return None


def geocode_any(place: str, district: str | None, state: str, places: pd.DataFrame,
                fetch: Callable[[str], list[dict]] | None = None,
                cache: Path | None = None) -> tuple[float, float, float, str] | None:
    """(lat, lon, accuracy_km, source) from GeoNames, else from Nominatim ("geonames" | "osm"), None when neither places it."""
    found = gc.geocode(place, district, state, places)
    if found is not None:
        return (*found, "geonames")
    found = osm_geocode(place, district, state, fetch=fetch, cache=cache, places=places)
    return None if found is None else (*found, "osm")
