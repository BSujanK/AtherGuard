"""Nominatim second-pass geocoder: acceptance of results, accuracy classes, spread rule, query order and the cache.

Everything is synthetic (an injected `fetch`, a hand-made places frame, a tmp_path cache); nothing touches the network.
"""
import hashlib
import json

import numpy as np
import pandas as pd
import pytest

from aetherguard.manifest import Manifest
from aetherguard.verify import geocode_osm as osm

KM_PER_DEG = 6371.0088 * np.pi / 180
UA = "AetherGuard-research/1.0 (+https://github.com/BSujanK/AtherGuard)"


def places(*rows):
    """(name, state, district, lat, lon) -> a places frame (populated places)."""
    return pd.DataFrame([{"geonameid": i + 1, "name": name, "asciiname": name, "alternatenames": "", "feature_class": "P",
                          "feature_code": "PPL", "lat": lat, "lon": lon, "population": 0, "district": district, "state": state}
                         for i, (name, state, district, lat, lon) in enumerate(rows)])


# Wayanad and Idukki are the real districts of Kerala here; Mangan is not in the table (a district GeoNames lacks).
PLACES = places(("Anchor1", "Kerala", "Wayanad", 11.6, 76.1), ("Anchor2", "Kerala", "Idukki", 9.9, 77.0),
                ("Anchor3", "Sikkim", "North Sikkim", 27.5, 88.5))


def hit(addresstype="village", lat=11.52, lon=76.18, state="Kerala", state_district="Wayanad", county=None, city_district=None,
        type_="administrative", category="boundary", name="Puthumala"):
    address = {"state": state, "country_code": "in"}
    for key, value in (("state_district", state_district), ("county", county), ("city_district", city_district)):
        if value is not None:
            address[key] = value
    return {"lat": str(lat), "lon": str(lon), "category": category, "type": type_, "addresstype": addresstype, "name": name,
            "display_name": f"{name}, {state}, India", "address": address}


class Fetch:
    """A fake `fetch(query)` returning `responses[query]` (or `default`) and recording every query."""

    def __init__(self, default=(), **by_query):
        self.default, self.by_query, self.queries = list(default), by_query, []

    def __call__(self, query):
        self.queries.append(query)
        return self.by_query.get(query, self.default)


def run(results, district="Wayanad", state="Kerala", place="Puthumala", tmp=None, **kwargs):
    fetch = Fetch(results)
    out = osm.osm_geocode(place, district, state, fetch=fetch, cache=tmp, places=PLACES, **kwargs)
    return out, fetch


# --- acceptance ----------------------------------------------------------------------------------

def test_a_village_in_the_named_state_and_district_is_accepted_at_five_km(tmp_path):
    out, _ = run([hit()], tmp=tmp_path)
    assert out == (11.52, 76.18, 5.0)


def test_a_result_in_another_state_is_rejected(tmp_path):
    out, _ = run([hit(state="Karnataka")], tmp=tmp_path)
    assert out is None


def test_a_result_in_another_district_is_rejected(tmp_path):
    out, _ = run([hit(state_district="Idukki")], tmp=tmp_path)
    assert out is None


def test_a_district_spelled_nearly_the_same_is_accepted(tmp_path):
    out, _ = run([hit(state_district="Wayanad district")], tmp=tmp_path)
    assert out == (11.52, 76.18, 5.0)


def test_the_county_is_used_when_there_is_no_state_district(tmp_path):
    out, _ = run([hit(state_district=None, county="Wayanad")], tmp=tmp_path)
    assert out == (11.52, 76.18, 5.0)


def test_the_city_district_is_used_when_there_is_neither(tmp_path):
    out, _ = run([hit(state_district=None, city_district="Wayanad")], tmp=tmp_path)
    assert out == (11.52, 76.18, 5.0)


def test_a_state_district_that_disagrees_is_not_overridden_by_a_matching_county(tmp_path):
    out, _ = run([hit(state_district="Idukki", county="Wayanad")], tmp=tmp_path)
    assert out is None


def test_a_result_with_no_district_in_its_address_is_rejected_when_a_district_is_named(tmp_path):
    out, _ = run([hit(state_district=None)], tmp=tmp_path)
    assert out is None


def test_without_a_district_any_district_of_the_state_is_accepted(tmp_path):
    out, _ = run([hit(state_district="Idukki")], district=None, tmp=tmp_path)
    assert out == (11.52, 76.18, 5.0)


def test_a_district_the_places_table_lacks_matches_by_its_own_name(tmp_path):
    result = hit(state="Sikkim", state_district="Mangan", lat=27.6, lon=88.5, name="Pakshep")
    out, _ = run([result], district="Mangan district", state="Sikkim", place="Pakshep village", tmp=tmp_path)
    assert out == (27.6, 88.5, 5.0)


def test_a_misspelt_state_district_of_the_report_can_still_be_a_district_of_the_table(tmp_path):
    out, _ = run([hit()], district="Wayanadu", tmp=tmp_path)
    assert out == (11.52, 76.18, 5.0)


def test_the_state_is_written_in_any_alias_form(tmp_path):
    result = hit(state="Jammu and Kashmir", state_district="Ramban")
    frame = places(("Ramban", "Jammu and Kashmir", "Ramban", 33.2, 75.2))
    out = osm.osm_geocode("Banihal", "Ramban", "J&K", fetch=Fetch([result]), cache=tmp_path, places=frame)
    assert out == (11.52, 76.18, 5.0)


def test_a_state_outside_the_study_domain_is_none_and_nothing_is_fetched(tmp_path):
    out, fetch = run([hit(state="Punjab")], state="Punjab", tmp=tmp_path)
    assert out is None and fetch.queries == []


# --- accuracy classes ----------------------------------------------------------------------------

@pytest.mark.parametrize("addresstype", ["village", "hamlet", "isolated_dwelling", "neighbourhood", "quarter", "suburb", "locality",
                                         "peak", "mountain_pass", "ridge", "valley", "bridge", "tunnel", "station", "halt"])
def test_point_features_are_good_to_five_km(addresstype, tmp_path):
    out, _ = run([hit(addresstype=addresstype)], tmp=tmp_path)
    assert out == (11.52, 76.18, 5.0)


@pytest.mark.parametrize("addresstype", ["town", "road", "highway", "track", "river", "stream"])
def test_towns_roads_and_waterways_are_good_to_ten_km(addresstype, tmp_path):
    out, _ = run([hit(addresstype=addresstype)], tmp=tmp_path)
    assert out == (11.52, 76.18, 10.0)


@pytest.mark.parametrize("addresstype", ["city", "municipality", "county", "state_district", "district", "state", "region", "shop"])
def test_areas_and_unknown_kinds_are_rejected(addresstype, tmp_path):
    out, _ = run([hit(addresstype=addresstype)], tmp=tmp_path)
    assert out is None


def test_the_osm_type_decides_when_the_address_type_is_not_a_known_kind(tmp_path):
    out, _ = run([hit(addresstype="man_made", type_="bridge", category="man_made")], tmp=tmp_path)
    assert out == (11.52, 76.18, 5.0)


def test_a_highway_by_category_is_a_road(tmp_path):
    out, _ = run([hit(addresstype="road", type_="tertiary", category="highway")], tmp=tmp_path)
    assert out == (11.52, 76.18, 10.0)


def test_an_area_address_type_is_not_rescued_by_a_point_type(tmp_path):
    out, _ = run([hit(addresstype="city", type_="village")], tmp=tmp_path)
    assert out is None


def test_a_rejected_result_does_not_hide_an_accepted_one(tmp_path):
    out, _ = run([hit(addresstype="county", lat=11.0), hit(addresstype="village", lat=11.52)], tmp=tmp_path)
    assert out == (11.52, 76.18, 5.0)


# --- several results -----------------------------------------------------------------------------

def test_two_accepted_results_30_km_apart_are_none(tmp_path):
    out, _ = run([hit(lat=11.5), hit(lat=11.5 + 30 / KM_PER_DEG)], tmp=tmp_path)
    assert out is None


def test_two_accepted_results_close_together_give_their_centroid_and_spread(tmp_path):
    out, _ = run([hit(lat=11.50), hit(lat=11.50 + 6 / KM_PER_DEG)], tmp=tmp_path)
    lat, lon, accuracy = out
    assert lat == pytest.approx(11.50 + 3 / KM_PER_DEG) and lon == pytest.approx(76.18)
    assert accuracy == pytest.approx(5.0)


def test_the_spread_widens_the_accuracy_past_five_km(tmp_path):
    out, _ = run([hit(lat=11.50), hit(lat=11.50 + 16 / KM_PER_DEG)], tmp=tmp_path)
    assert out[2] == pytest.approx(8.0)


def test_a_village_and_a_road_together_are_good_to_the_coarser_ten_km(tmp_path):
    out, _ = run([hit(addresstype="village"), hit(addresstype="road")], tmp=tmp_path)
    assert out[2] == 10.0


# --- queries and the cache ------------------------------------------------------------------------

def test_the_first_query_names_place_district_and_state(tmp_path):
    _, fetch = run([hit()], tmp=tmp_path)
    assert fetch.queries == ["Puthumala, Wayanad, Kerala, India"]


def test_when_the_first_query_has_nothing_acceptable_the_second_leaves_out_the_district(tmp_path):
    fetch = Fetch(**{"Puthumala, Wayanad, Kerala, India": [hit(state="Karnataka")], "Puthumala, Kerala, India": [hit()]})
    out = osm.osm_geocode("Puthumala", "Wayanad", "Kerala", fetch=fetch, cache=tmp_path, places=PLACES)
    assert out == (11.52, 76.18, 5.0)
    assert fetch.queries == ["Puthumala, Wayanad, Kerala, India", "Puthumala, Kerala, India"]


def test_the_second_query_still_applies_the_district(tmp_path):
    fetch = Fetch(**{"Puthumala, Kerala, India": [hit(state_district="Idukki")]})
    assert osm.osm_geocode("Puthumala", "Wayanad", "Kerala", fetch=fetch, cache=tmp_path, places=PLACES) is None


def test_an_ambiguous_first_query_does_not_fall_through_to_the_second(tmp_path):
    fetch = Fetch(**{"Puthumala, Wayanad, Kerala, India": [hit(lat=11.5), hit(lat=11.5 + 30 / KM_PER_DEG)],
                     "Puthumala, Kerala, India": [hit()]})
    assert osm.osm_geocode("Puthumala", "Wayanad", "Kerala", fetch=fetch, cache=tmp_path, places=PLACES) is None
    assert fetch.queries == ["Puthumala, Wayanad, Kerala, India"]


def test_without_a_district_there_is_one_query(tmp_path):
    _, fetch = run([], district=None, tmp=tmp_path)
    assert fetch.queries == ["Puthumala, Kerala, India"]


def test_a_second_call_reads_the_cache_and_does_not_fetch(tmp_path):
    first, fetch = run([hit()], tmp=tmp_path)
    again = Fetch()
    assert osm.osm_geocode("Puthumala", "Wayanad", "Kerala", fetch=again, cache=tmp_path, places=PLACES) == first
    assert first == (11.52, 76.18, 5.0) and len(fetch.queries) == 1 and again.queries == []


def test_every_response_is_cached_under_the_sha1_of_its_query_even_an_empty_one(tmp_path):
    run([], tmp=tmp_path)
    for query in ("Puthumala, Wayanad, Kerala, India", "Puthumala, Kerala, India"):
        path = tmp_path / (hashlib.sha1(query.encode("utf-8")).hexdigest() + ".json")
        assert json.loads(path.read_text(encoding="utf-8"))["response"] == []
    again = Fetch()
    assert osm.osm_geocode("Puthumala", "Wayanad", "Kerala", fetch=again, cache=tmp_path, places=PLACES) is None
    assert again.queries == []


def test_a_failed_fetch_raises_and_leaves_nothing_cached(tmp_path):
    def broken(query):
        raise OSError("network down")

    with pytest.raises(OSError):
        osm.osm_geocode("Puthumala", "Wayanad", "Kerala", fetch=broken, cache=tmp_path, places=PLACES)
    assert list(tmp_path.iterdir()) == []


def test_an_unreadable_cache_file_is_an_error_not_a_miss(tmp_path):
    path = tmp_path / (hashlib.sha1(b"Puthumala, Kerala, India").hexdigest() + ".json")
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(osm.GeocodeError, match=path.name):
        osm.osm_geocode("Puthumala", None, "Kerala", fetch=Fetch(), cache=tmp_path, places=PLACES)


def test_the_default_cache_lives_under_the_data_root(isolated_data_root):
    osm.osm_geocode("Puthumala", None, "Kerala", fetch=Fetch(), places=PLACES)
    cached = list((isolated_data_root / "raw" / "geocode_cache" / "nominatim").glob("*.json"))
    assert len(cached) == 1


def test_cached_responses_are_recorded_in_the_manifest_with_the_odbl_licence_once(tmp_path):
    cache = tmp_path / "cache"
    run([hit()], tmp=cache)
    manifest = Manifest(tmp_path / "manifest.jsonl", tmp_path)
    assert osm.record_cache(manifest, cache) == 1
    assert osm.record_cache(manifest, cache) == 0
    (entry,) = manifest.entries().values()
    assert "ODbL" in entry.licence and "q=Puthumala" in entry.url and entry.path.startswith("cache/")


# --- geocode_any ---------------------------------------------------------------------------------

def test_geocode_any_uses_geonames_when_it_resolves_and_does_not_fetch(tmp_path):
    frame = places(("Puthumala", "Kerala", "Wayanad", 11.52, 76.18))
    fetch = Fetch([hit(lat=1.0)])
    out = osm.geocode_any("Puthumala", "Wayanad", "Kerala", frame, fetch=fetch, cache=tmp_path)
    assert out == (11.52, 76.18, 5.0, "geonames") and fetch.queries == []


def test_geocode_any_falls_back_to_nominatim(tmp_path):
    fetch = Fetch([hit()])
    out = osm.geocode_any("Puthumala", "Wayanad", "Kerala", PLACES, fetch=fetch, cache=tmp_path)
    assert out == (11.52, 76.18, 5.0, "osm")


def test_geocode_any_is_none_when_neither_source_places_it(tmp_path):
    assert osm.geocode_any("Puthumala", "Wayanad", "Kerala", PLACES, fetch=Fetch(), cache=tmp_path) is None


# --- the default fetch ---------------------------------------------------------------------------

def test_requests_are_spaced_at_least_a_second_apart(monkeypatch):
    clock = {"now": 100.0}
    slept = []

    def sleep(seconds):
        slept.append(seconds)
        clock["now"] += seconds

    monkeypatch.setattr(osm, "_last_request", 0.0)
    osm._throttle(clock=lambda: clock["now"], sleep=sleep)
    clock["now"] += 0.4
    osm._throttle(clock=lambda: clock["now"], sleep=sleep)
    assert slept == [pytest.approx(osm.MIN_INTERVAL_S - 0.4)] and osm.MIN_INTERVAL_S >= 1.0


class _Response:
    def __init__(self, status, body=None):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


def test_the_default_fetch_sends_the_documented_parameters_and_user_agent(monkeypatch):
    seen = {}

    def get(url, params, headers, timeout):
        seen.update(url=url, params=params, headers=headers)
        return _Response(200, [hit()])

    monkeypatch.setattr(osm.requests, "get", get)
    monkeypatch.setattr(osm, "_throttle", lambda: None)
    assert osm.nominatim_fetch("Puthumala, Kerala, India") == [hit()]
    assert seen["url"] == "https://nominatim.openstreetmap.org/search"
    assert seen["params"] == {"q": "Puthumala, Kerala, India", "countrycodes": "in", "format": "jsonv2", "addressdetails": 1,
                              "limit": 10}
    assert seen["headers"]["User-Agent"] == UA


def test_the_default_fetch_retries_a_throttled_response_then_gives_up(monkeypatch):
    calls = []
    monkeypatch.setattr(osm.requests, "get", lambda *a, **k: calls.append(1) or _Response(429))
    monkeypatch.setattr(osm, "_throttle", lambda: None)
    with pytest.raises(osm.GeocodeError, match="429"):
        osm.nominatim_fetch("Puthumala, Kerala, India", sleep=lambda seconds: None)
    assert len(calls) == osm.ATTEMPTS


def test_the_default_fetch_does_not_retry_a_client_error(monkeypatch):
    calls = []
    monkeypatch.setattr(osm.requests, "get", lambda *a, **k: calls.append(1) or _Response(403))
    monkeypatch.setattr(osm, "_throttle", lambda: None)
    with pytest.raises(osm.GeocodeError, match="403"):
        osm.nominatim_fetch("Puthumala, Kerala, India")
    assert len(calls) == 1
