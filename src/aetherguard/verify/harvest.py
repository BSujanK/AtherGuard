"""Live-period candidate harvester (spec W1b, task 4): landslide reports in a keyless open news index, turned into a REVIEW
QUEUE of candidate events. Nothing is admitted here.

    python -m aetherguard.verify harvest --start 2026-10-09 --end 2026-11-13 --out <queue dir>

Why. The live verification ledger (`verify.ledger`) needs reported events from October 2026 on, and none had been entered
after five weeks of alerts. This command finds candidates; a person (or the lead) confirms each row against its articles and
copies the confirmed ones into `data/raw/manual/reported_events/raw/<year>.csv` (the `inventory.RAW_COLUMNS` the queue
already carries), where `python -m aetherguard.verify inventory` geocodes, deduplicates and QA-checks them as every other
reported row. The queue never writes there itself.

Source. The GDELT DOC 2.0 API (https://api.gdeltproject.org/api/v2/doc/doc, no key, no account), article list mode, one
query per day and source country (`COUNTRIES`: India, Nepal), at most one request per `MIN_INTERVAL_S` (GDELT asks for no
more than one every 5 seconds) with a generic User-Agent. Every response is saved under `<out>/gdelt/` and read from there
on a rerun. GDELT supplies the title, URL, outlet domain, language and the time it saw the article, not the article text.
Titles and URLs are facts about the articles; the articles stay with their publishers.

Candidates. An article is a candidate when its title names a landslide (`LANDSLIDE_WORDS`, English, Hindi and Nepali). Its
place is read from the title: the capitalised word runs of one to three words (`place_phrases`) are geocoded with the W1
GeoNames geocoder (`geocode.geocode`, India only, no Nepal gazetteer), in the state the title names when it names one, else in
every domain state, where only an answer in exactly one state is kept (a name found in two states is ambiguous). The first
phrase that places decides. The date is the day GDELT saw the article (IST), so every row is `report`-dated: the reviewer
must read the event day in the article.

Grouping. Located candidates within `GROUP_KM` and `GROUP_DAYS` of each other (single linkage) are one candidate event;
unlocated candidates are grouped by the same folded title. A group's `independent_reports` counts outlets whose titles
differ (syndicated copies of one agency story on several sites count once): `corroborated` = at least two. In-domain means
inside a region box and in a scored cell (`live.backtest.universe_cell_ids`); the queue lists the rest too, flagged.

BIPAD. `--bipad` adds the locally fetched BIPAD Nepal register (`verify.open_sources`) incidents of the range, one row per
admitted incident of `data/raw/manual/bipad_nepal/qa/inventory_admitted.csv`: government register rows with a ward-bounded
point and the incident day, one source each.
"""
from __future__ import annotations

import csv
import json
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from .. import grid
from . import geocode as gc
from .inventory import RAW_COLUMNS

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
USER_AGENT = "AetherGuard-research/1.0 (landslide verification research prototype)"
MIN_INTERVAL_S = 6.0
ATTEMPTS, BACKOFF_S = 5, 30.0                          # a 429 waits 30, 60, 120, 240 s before giving up
TIMEOUT_S = 90
MAX_RECORDS = 250
COUNTRIES = {"IN": "India", "NP": "Nepal"}
QUERY = '(landslide OR landslides OR landslip OR mudslide OR "land slide")'
LANDSLIDE_WORDS = re.compile(r"landslides?|landslips?|mudslides?|land ?slides?|भूस्खलन|"
                             r"पहिरो", re.IGNORECASE)
GROUP_KM, GROUP_DAYS = 10.0, 2
IST = timezone(timedelta(hours=5, minutes=30))
QUEUE_COLUMNS = (*RAW_COLUMNS, "candidate_id", "latitude", "longitude", "accuracy_km", "region", "in_scored_cell",
                 "reports", "independent_reports", "corroborated", "source_urls", "outlets", "titles", "origin", "status")
STOP = {"landslide", "landslides", "landslip", "heavy", "rain", "rains", "rainfall", "monsoon", "imd", "ndrf", "sdrf", "the",
        "a", "an", "in", "at", "of", "on", "after", "amid", "near", "due", "to", "and", "or", "for", "with", "as", "by",
        "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "january", "february", "march", "april",
        "may", "june", "july", "august", "september", "october", "november", "december", "india", "nepal", "pm", "cm", "govt",
        "highway", "road", "national", "state", "district", "village", "town", "city", "live", "updates", "news", "video",
        "watch", "photos", "breaking", "people", "killed", "dead", "dies", "die", "missing", "trapped", "rescued", "houses",
        "kills", "hits", "hit", "blocked", "blocks", "traffic", "alert", "orange", "red", "yellow", "toll", "rises", "says",
        "nh", "two", "three", "four", "five", "one", "several", "many"}
_last = float("-inf")


# --- fetching ---------------------------------------------------------------------------------------------------

def gdelt_fetch(params: dict, sleep=time.sleep) -> dict:
    """One GDELT DOC API call, politely spaced; three attempts. GDELT answers some failures with a plain-text message."""
    global _last
    error = None
    for attempt in range(ATTEMPTS):
        wait = _last + MIN_INTERVAL_S - time.monotonic()
        if wait > 0:
            sleep(wait)
        _last = time.monotonic()
        try:
            response = requests.get(GDELT_URL, params=params, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT_S)
            response.raise_for_status()
            text = response.text.strip()
            if not text:
                return {"articles": []}
            if not text.startswith("{"):                # a plain-text notice (rate limit, bad query): never cached
                raise ValueError(f"not JSON: {text[:120]!r}")
            return json.loads(text)
        except (requests.RequestException, ValueError) as exc:
            error = exc
            sleep(BACKOFF_S * 2 ** attempt)
    raise RuntimeError(f"GDELT: {error}")


def day_params(day: date, country: str) -> dict:
    start = datetime(day.year, day.month, day.day)
    return {"query": f"{QUERY} sourcecountry:{country}", "mode": "artlist", "format": "json", "maxrecords": MAX_RECORDS,
            "sort": "datedesc", "startdatetime": start.strftime("%Y%m%d%H%M%S"),
            "enddatetime": (start + timedelta(days=1) - timedelta(seconds=1)).strftime("%Y%m%d%H%M%S")}


def fetch_range(start: date, end: date, cache: Path, fetch=gdelt_fetch, say=print) -> list[dict]:
    """Every article of the range (UTC days `start`..`end`) and countries, each tagged with its query country; responses are
    cached as `<cache>/<country>_<YYYY-MM-DD>.json` and a cached day is never fetched again, except today's."""
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).date()
    articles = []
    day = start
    while day <= end:
        for country in COUNTRIES:
            path = cache / f"{country}_{day.isoformat()}.json"
            if path.is_file() and day < today:
                page = json.loads(path.read_text(encoding="utf-8"))
            else:
                page = fetch(day_params(day, country))
                path.write_text(json.dumps(page, ensure_ascii=False), encoding="utf-8")
            rows = page.get("articles", []) or []
            if len(rows) >= MAX_RECORDS:
                say(f"gdelt: {country} {day}: {len(rows)} articles, the cap; some may be missing")
            articles.extend({**a, "query_country": country} for a in rows)
        day += timedelta(days=1)
    return articles


# --- reading titles ---------------------------------------------------------------------------------------------

def is_landslide_title(title: str) -> bool:
    return bool(LANDSLIDE_WORDS.search(title or ""))


def place_phrases(title: str) -> list[str]:
    """Capitalised word runs of the title (one to three words, longest first within a run), stop words dropped."""
    words = re.findall(r"[A-Za-z][A-Za-z'\-]*", title or "")
    runs, current = [], []
    for word in words:
        if word[0].isupper() and word.lower().strip("'") not in STOP:
            current.append(word)
        else:
            if current:
                runs.append(current)
            current = []
    if current:
        runs.append(current)
    out = []
    for run in runs:
        for size in (3, 2, 1):
            for i in range(0, len(run) - size + 1):
                phrase = " ".join(run[i:i + size])
                if len(phrase) >= 3 and phrase not in out:
                    out.append(phrase)
    return out


def states_named(title: str) -> list[str]:
    folded = f" {gc.fold(title)} "
    return sorted({state for key, state in gc.STATE_ALIASES.items() if f" {key} " in folded})


def locate_title(title: str, places: pd.DataFrame, states=None) -> dict | None:
    """(place, state, lat, lon, accuracy_km) of the first title phrase the geocoder places unambiguously, or None."""
    named = states_named(title)
    scope = named or sorted(set(states or gc.STATE_ALIASES.values()))
    for phrase in place_phrases(title):
        if gc.canonical_state(phrase):
            continue                                            # a state name is not a place
        hits = {}
        for state in scope:
            found = gc.geocode(phrase, None, state, places)
            if found is not None:
                hits[state] = found
        if len(hits) == 1:
            (state, (lat, lon, accuracy)), = hits.items()
            return {"place": phrase, "state": state, "lat": float(lat), "lon": float(lon), "accuracy_km": float(accuracy)}
    return None


def seen_day(seendate: str) -> date:
    """The IST day of a GDELT `seendate` (YYYYMMDDTHHMMSSZ, UTC)."""
    return datetime.strptime(seendate, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).astimezone(IST).date()


def _title_key(title: str) -> str:
    return " ".join(gc.fold(title).split()[:8])


# --- grouping ---------------------------------------------------------------------------------------------------

def candidates(articles: list[dict], places: pd.DataFrame, universe: set[int] | None = None) -> list[dict]:
    """One row per landslide-titled article (deduplicated by URL), located when its title allows."""
    seen, out = set(), []
    for article in articles:
        url, title = article.get("url", ""), article.get("title", "")
        if not url or url in seen or not is_landslide_title(title):
            continue
        seen.add(url)
        located = locate_title(title, places) if article.get("query_country") == "IN" else None
        row = {"url": url, "title": title.strip(), "domain": article.get("domain", ""), "language": article.get("language", ""),
               "day": seen_day(article["seendate"]), "country": article.get("query_country", ""), "located": located}
        if located:
            row["region"] = grid.region_of(located["lat"], located["lon"]) or ""
            cell = int(grid.latlon_to_cell(located["lat"], located["lon"]))
            row["in_scored_cell"] = bool(universe is None or cell in universe) and bool(row["region"])
        else:
            row["region"], row["in_scored_cell"] = "", False
        out.append(row)
    return out


def group(rows: list[dict]) -> list[list[dict]]:
    """Located rows within GROUP_KM and GROUP_DAYS (single linkage); unlocated rows by folded title and day."""
    located = [r for r in rows if r["located"]]
    parent = list(range(len(located)))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i, a in enumerate(located):
        for j in range(i + 1, len(located)):
            b = located[j]
            if abs((a["day"] - b["day"]).days) <= GROUP_DAYS and float(gc._haversine_km(
                    a["located"]["lat"], a["located"]["lon"], b["located"]["lat"], b["located"]["lon"])) <= GROUP_KM:
                parent[root(j)] = root(i)
    groups: dict = {}
    for i, r in enumerate(located):
        groups.setdefault(("L", root(i)), []).append(r)
    for r in rows:
        if not r["located"]:
            groups.setdefault(("U", _title_key(r["title"]), r["day"]), []).append(r)
    return sorted(groups.values(), key=lambda g: (min(r["day"] for r in g), g[0]["title"]))


def independent_reports(members: list[dict]) -> int:
    """Outlets whose titles differ: a syndicated story repeated on several sites counts once."""
    by_title = {}
    for r in members:
        by_title.setdefault(_title_key(r["title"]), set()).add(r["domain"])
    domains_seen, count = set(), 0
    for key, domains in by_title.items():
        fresh = domains - domains_seen
        if fresh:
            count += 1
            domains_seen |= domains
    return count


def queue_rows(groups: list[list[dict]]) -> list[dict]:
    out = []
    for k, members in enumerate(groups, 1):
        first = min(members, key=lambda r: (r["day"], r["url"]))
        loc = next((r["located"] for r in members if r["located"]), None)
        independent = independent_reports(members)
        out.append({
            "event_date": first["day"].isoformat(), "date_basis": "report",
            "place": loc["place"] if loc else "", "district": "", "state": loc["state"] if loc else "",
            "source_url": first["url"], "outlet": first["domain"],
            "description": f"GDELT title: {first['title']}",
            "candidate_id": f"gdelt-{k:04d}",
            "latitude": "" if not loc else f"{loc['lat']:.5f}", "longitude": "" if not loc else f"{loc['lon']:.5f}",
            "accuracy_km": "" if not loc else f"{loc['accuracy_km']:.1f}",
            "region": first["region"], "in_scored_cell": any(r["in_scored_cell"] for r in members),
            "reports": len(members), "independent_reports": independent, "corroborated": independent >= 2,
            "source_urls": " | ".join(r["url"] for r in members), "outlets": " | ".join(sorted({r["domain"] for r in members})),
            "titles": " | ".join(sorted({r["title"] for r in members})), "origin": f"gdelt_{first['country']}",
            "status": "needs review: read the event day and place in the articles",
        })
    return out


def bipad_rows(start: date, end: date, admitted_csv: Path, universe: set[int] | None = None) -> list[dict]:
    """The BIPAD register incidents of the range (already admitted by its inventory at 5 km) as queue rows."""
    if not Path(admitted_csv).is_file():
        return []
    frame = pd.read_csv(admitted_csv, dtype=str, keep_default_na=False)
    days = pd.to_datetime(frame["date"]).dt.date
    frame = frame[(days >= start) & (days <= end)]
    out = []
    for k, r in enumerate(frame.to_dict("records"), 1):
        lat, lon = float(r["latitude"]), float(r["longitude"])
        cell = int(grid.latlon_to_cell(lat, lon))
        out.append({**{c: r.get(c, "") for c in RAW_COLUMNS}, "event_date": r["date"], "date_basis": "stated",
                    "candidate_id": f"bipad-{k:04d}", "latitude": r["latitude"], "longitude": r["longitude"],
                    "accuracy_km": r["accuracy_km"], "region": grid.region_of(lat, lon) or "",
                    "in_scored_cell": universe is None or cell in universe, "reports": 1, "independent_reports": 1,
                    "corroborated": False, "source_urls": r["source_url"], "outlets": r["outlet"], "titles": "",
                    "origin": "bipad_register", "status": "register row: confirm with a second report before admission"})
    return out


def write_queue(path: Path, rows: list[dict]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=QUEUE_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return path


def summary(rows: list[dict]) -> dict:
    gd = [r for r in rows if r["origin"].startswith("gdelt")]
    located = [r for r in gd if r["latitude"]]
    inside = [r for r in located if r["in_scored_cell"]]
    return {"gdelt_candidates": len(gd), "gdelt_located": len(located), "gdelt_in_scored_cells": len(inside),
            "gdelt_in_scored_cells_corroborated": sum(r["corroborated"] for r in inside),
            "gdelt_unlocated_corroborated": sum(r["corroborated"] for r in gd if not r["latitude"]),
            "bipad_register_rows": sum(r["origin"] == "bipad_register" for r in rows),
            "bipad_register_in_scored_cells": sum(r["origin"] == "bipad_register" and r["in_scored_cell"] for r in rows)}


def harvest(start: date, end: date, out: Path, places: pd.DataFrame, fetch=gdelt_fetch, universe: set[int] | None = None,
            bipad_csv: Path | None = None, say=print) -> dict:
    """Fetch (or read cached), extract, group and write `<out>/review_queue_<start>_<end>.csv` and its summary JSON."""
    out = Path(out)
    articles = fetch_range(start, end, out / "gdelt", fetch, say)
    rows = queue_rows(group(candidates(articles, places, universe)))
    if bipad_csv is not None:
        rows += bipad_rows(start, end, bipad_csv, universe)
    stem = f"review_queue_{start.isoformat()}_{end.isoformat()}"
    write_queue(out / f"{stem}.csv", rows)
    result = {"start": start.isoformat(), "end": end.isoformat(), "articles": len(articles), **summary(rows),
              "queue": (out / f"{stem}.csv").as_posix()}
    (out / f"{stem}.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    say(f"harvest {start}..{end}: {len(articles)} articles, {result['gdelt_candidates']} GDELT candidates, "
        f"{result['gdelt_in_scored_cells']} located in scored cells ({result['gdelt_in_scored_cells_corroborated']} "
        f"corroborated), {result['bipad_register_rows']} BIPAD register rows; wrote {out / stem}.csv")
    return result


def universe_set() -> set[int]:
    from ..live import backtest as bt
    return set(np.asarray(bt.universe_cell_ids(), dtype=np.int64).tolist())
