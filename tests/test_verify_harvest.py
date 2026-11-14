"""Live candidate harvester (W1b task 4): recorded GDELT-shaped responses and a tiny places table; no network."""
import csv
import json
from datetime import date

import pandas as pd
import pytest

from aetherguard.verify import harvest as hv

PLACES = pd.DataFrame({
    "geonameid": [1, 2, 3, 4],
    "name": ["Kotdwar", "Mandi", "Mandi", "Munnar"],
    "asciiname": ["Kotdwar", "Mandi", "Mandi", "Munnar"],
    "alternatenames": ["", "", "", ""],
    "feature_class": ["P", "P", "P", "P"], "feature_code": ["PPL"] * 4,
    "lat": [29.75, 31.71, 18.50, 10.09], "lon": [78.52, 76.93, 73.80, 77.06], "population": [0] * 4,
    "district": ["Garhwal", "Mandi", "Pune", "Idukki"],
    "state": ["Uttarakhand", "Himachal Pradesh", "Maharashtra", "Kerala"],
})


def article(title, url, domain="a.example", seendate="20261020T050000Z", country="IN"):
    return {"url": url, "title": title, "domain": domain, "language": "English", "seendate": seendate,
            "sourcecountry": country}


RECORDED = {
    ("IN", "2026-10-20"): {"articles": [
        article("Landslide near Kotdwar blocks highway after heavy rain", "https://a.example/1"),
        article("Landslide near Kotdwar blocks highway after heavy rain", "https://b.example/1", "b.example"),  # syndicated
        article("Kotdwar landslide: two houses buried, rescue on", "https://c.example/9", "c.example",
                "20261021T010000Z"),
        article("Dam in China rising 7 feet daily", "https://a.example/2"),                        # no landslide word
        article("Landslide in Mandi", "https://a.example/3"),                                    # Mandi: two states
        article("Landslide in Mandi, Himachal Pradesh", "https://d.example/3", "d.example"),     # the state decides
    ]},
}


def recorded_fetch(params):
    country = params["query"].rsplit(":", 1)[1]
    day = f"{params['startdatetime'][:4]}-{params['startdatetime'][4:6]}-{params['startdatetime'][6:8]}"
    return RECORDED.get((country, day), {"articles": []})


def test_titles_name_landslides_in_english_hindi_and_nepali():
    assert hv.is_landslide_title("Massive LANDSLIDE in Kullu") and hv.is_landslide_title("Landslips hit Idukki")
    assert hv.is_landslide_title("उत्तराखंड में भूस्खलन")
    assert hv.is_landslide_title("सिन्धुपाल्चोकमा पहिरो")
    assert not hv.is_landslide_title("Floods in Assam")


def test_place_phrases_are_capitalised_runs_without_stop_words():
    assert hv.place_phrases("Landslide near Kotdwar Bus Stand on Monday") == [
        "Kotdwar Bus Stand", "Kotdwar Bus", "Bus Stand", "Kotdwar", "Bus", "Stand"]


def test_a_name_in_two_states_is_placed_only_when_the_title_names_the_state():
    assert hv.locate_title("Landslide in Mandi", PLACES) is None
    found = hv.locate_title("Landslide in Mandi, Himachal Pradesh", PLACES)
    assert (found["place"], found["state"]) == ("Mandi", "Himachal Pradesh")


def test_the_seen_day_is_the_ist_day():
    assert hv.seen_day("20261020T200000Z") == date(2026, 10, 21)


def test_harvest_writes_a_review_queue_with_grouped_corroborated_candidates(tmp_path):
    result = hv.harvest(date(2026, 10, 20), date(2026, 10, 20), tmp_path, PLACES, fetch=recorded_fetch, say=lambda m: None)
    with open(result["queue"], newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    kotdwar = [r for r in rows if r["place"] == "Kotdwar"]
    assert len(kotdwar) == 1                                    # three articles, two days, one candidate
    assert (kotdwar[0]["reports"], kotdwar[0]["independent_reports"], kotdwar[0]["corroborated"]) == ("3", "2", "True")
    assert kotdwar[0]["date_basis"] == "report" and kotdwar[0]["event_date"] == "2026-10-20"
    assert kotdwar[0]["region"] == "himalaya"
    mandi = [r for r in rows if r["place"] == "Mandi"]
    assert len(mandi) == 1 and mandi[0]["state"] == "Himachal Pradesh"
    assert any(r["place"] == "" and "Mandi" in r["titles"] for r in rows)       # the ambiguous one stays unlocated
    assert all("China" not in r["titles"] for r in rows)
    assert result["gdelt_candidates"] == len(rows)
    assert json.loads((tmp_path / "review_queue_2026-10-20_2026-10-20.json").read_text())["articles"] == 6


def test_a_cached_day_is_not_fetched_again(tmp_path):
    hv.harvest(date(2026, 10, 20), date(2026, 10, 20), tmp_path, PLACES, fetch=recorded_fetch, say=lambda m: None)
    again = hv.harvest(date(2026, 10, 20), date(2026, 10, 20), tmp_path, PLACES,
                       fetch=lambda p: pytest.fail("fetched"), say=lambda m: None)
    assert again["articles"] == 6


def test_cells_outside_the_scored_set_are_flagged(tmp_path):
    result = hv.harvest(date(2026, 10, 20), date(2026, 10, 20), tmp_path, PLACES, fetch=recorded_fetch, universe=set(),
                        say=lambda m: None)
    assert result["gdelt_in_scored_cells"] == 0 and result["gdelt_located"] >= 2


def test_bipad_register_rows_of_the_range_join_the_queue(tmp_path):
    admitted = tmp_path / "admitted.csv"
    pd.DataFrame({"date": ["2026-10-10", "2026-09-01"], "place": ["W", "X"], "district": ["", ""], "state": ["Nepal"] * 2,
                  "source_url": ["u1", "u2"], "outlet": ["BIPAD"] * 2, "description": ["d", "d"],
                  "latitude": ["27.7", "27.7"], "longitude": ["85.3", "85.3"], "accuracy_km": ["3", "3"]}).to_csv(admitted, index=False)
    rows = hv.bipad_rows(date(2026, 10, 9), date(2026, 11, 13), admitted)
    assert [(r["place"], r["event_date"], r["origin"]) for r in rows] == [("W", "2026-10-10", "bipad_register")]


def test_the_command_refuses_to_write_into_reported_events(monkeypatch):
    import runpy
    import sys
    from aetherguard.verify import ledger
    monkeypatch.setattr(sys, "argv", ["aetherguard.verify", "harvest", "--start", "2026-10-09", "--end", "2026-10-10",
                                      "--out", str(ledger.REPORTED_DIR / "queue")])
    with pytest.raises(SystemExit) as stop:
        runpy.run_module("aetherguard.verify", run_name="__main__")
    assert stop.value.code == 1


def test_a_rate_limit_notice_is_retried_and_never_returned_as_an_empty_day(monkeypatch):
    answers = iter([("Please limit requests to one every 5 seconds", 200), ('{"articles": [{"url": "u"}]}', 200)])

    class Response:
        def __init__(self, text, status):
            self.text, self.status_code = text, status

        def raise_for_status(self):
            pass
    monkeypatch.setattr(hv.requests, "get", lambda *a, **k: Response(*next(answers)))
    slept = []
    assert hv.gdelt_fetch({}, sleep=slept.append) == {"articles": [{"url": "u"}]}
    assert hv.BACKOFF_S in slept


def test_a_failed_fetch_stops_fetching_and_lists_the_days_not_fetched(tmp_path):
    calls = []

    def failing(params):
        calls.append(params)
        raise RuntimeError("GDELT: 429")
    result = hv.harvest(date(2026, 10, 20), date(2026, 10, 21), tmp_path, PLACES, fetch=failing, say=lambda m: None)
    assert len(calls) == 1
    assert result["days_not_fetched"] == ["IN 2026-10-20", "NP 2026-10-20", "IN 2026-10-21", "NP 2026-10-21"]
    assert not list((tmp_path / "gdelt").glob("*.json"))          # nothing cached for a failed day


def test_the_cache_name_carries_the_query_so_a_new_query_never_reads_old_answers(tmp_path, monkeypatch):
    hv.harvest(date(2026, 10, 20), date(2026, 10, 20), tmp_path, PLACES, fetch=recorded_fetch, say=lambda m: None)
    assert (tmp_path / "gdelt" / f"IN_2026-10-20_{hv.query_tag()}.json").is_file()
    monkeypatch.setattr(hv, "QUERY", "landslip")
    fetched = []
    hv.harvest(date(2026, 10, 20), date(2026, 10, 20), tmp_path, PLACES, fetch=lambda p: fetched.append(p) or {"articles": []},
               say=lambda m: None)
    assert len(fetched) == 2
