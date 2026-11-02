"""Live verification ledger: the alerts the daily run published, scored against landslides people reported.

    python -m aetherguard.verify ledger    # reports/live_verification.{json,md}

Reported events are CSV files in `data/raw/manual/reported_events/` (git-ignored with the rest of data/, so the folder is
created locally and its files are not committed). Every `*.csv` in the folder is read; each needs this header:

    date,latitude,longitude,location_text,source_url,accuracy_km

* `date`: YYYY-MM-DD, the IST calendar date of the landslide;
* `latitude`, `longitude`: decimal degrees, inside a region box of `configs/domain.yaml`;
* `location_text`: the place as the source names it;
* `source_url`: where the report was published (required, so every event can be checked);
* `accuracy_km`: how well the source locates the event; may be left empty, otherwise a number >= 0.

A row that breaks these rules stops the ledger with an error naming the file and line. An empty folder is a valid answer: the
ledger then reports no events (NaN detection) and still counts the alert cell-days.

The ledger reads every published day of `data/live` (a day with a `run.json` whose status is `complete`) and scores, for each
lead 0 to 3 and each alert level, with the same matching and bootstrap as the baseline report (`Tolerance(km=10, days=1)`
by default). Lead 0 is the day's `alerts.parquet`; lead k is `risk_D{k}.parquet`, placed on the date it forecasts. A day
without a published run counts as no alert and is not scored. Forecast days after `today` are left out, since nothing can have
been reported for them yet. Reports keep arriving for a while, so days within 14 days of `today` (from `provisional_from`
on) are listed as provisional, and their precision and detection can still change.
"""
from __future__ import annotations

import csv
import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .. import grid
from ..config import PROJECT_ROOT
from ..hazard import model as hm
from ..hazard.jsonio import dump_json
from ..live import run as live_run
from ..live.backtest import BOOTSTRAP
from .matching import Tolerance, match
from .report import LEVEL_NAMES, LEVELS, _interval, _pct
from .scores import bootstrap_scores

IST = timezone(timedelta(hours=5, minutes=30), "IST")  # Asia/Kolkata has no daylight saving, so a fixed offset is exact
REPORT_STEM = "live_verification"
REPORTED_DIR = PROJECT_ROOT / "data" / "raw" / "manual" / "reported_events"
COLUMNS = ("date", "latitude", "longitude", "location_text", "source_url", "accuracy_km")
LEADS = (0, 1, 2, 3)
PROVISIONAL_DAYS = 14


# --------------------------------------------------------------------------------------------- reported events

def _parse_row(row: dict[str, str]) -> tuple[date, float, float, float]:
    """The validated (date, latitude, longitude, accuracy_km) of one CSV row; ValueError says what is wrong."""
    try:
        day = datetime.strptime(row["date"].strip(), "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(f"date {row['date']!r} is not YYYY-MM-DD") from None
    coordinates = []
    for name in ("latitude", "longitude"):
        try:
            value = float(row[name])
        except ValueError:
            raise ValueError(f"{name} {row[name]!r} is not a number") from None
        if not np.isfinite(value):
            raise ValueError(f"{name} {row[name]!r} is not finite")
        coordinates.append(value)
    if not grid.region_of(*coordinates):
        raise ValueError(f"({coordinates[0]}, {coordinates[1]}) is outside the domain regions")
    if not row["source_url"].strip():
        raise ValueError("source_url is empty")
    accuracy = row["accuracy_km"].strip()
    try:
        accuracy_km = float(accuracy) if accuracy else np.nan
    except ValueError:
        raise ValueError(f"accuracy_km {accuracy!r} is not a number") from None
    if accuracy_km < 0 or np.isinf(accuracy_km):
        raise ValueError(f"accuracy_km {accuracy!r} must be a number >= 0")
    return day, coordinates[0], coordinates[1], accuracy_km


def _read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle)
        header = next(reader, None) or []
        missing = [c for c in COLUMNS if c not in header]
        if missing:
            raise ValueError(f"{path.name}: missing column(s) {missing}; the header is {','.join(COLUMNS)}")
        records = []
        while True:
            line = reader.line_num + 1
            raw = next(reader, None)
            if raw is None:
                return records
            if not any(cell.strip() for cell in raw):
                continue
            row = {name: (raw[i] if i < len(raw) else "") for i, name in enumerate(header)}
            try:
                day, lat, lon, accuracy_km = _parse_row(row)
            except ValueError as exc:
                raise ValueError(f"{path.name} line {line}: {exc}") from None
            records.append({"date": day, "latitude": lat, "longitude": lon, "location_text": row["location_text"].strip(),
                            "source_url": row["source_url"].strip(), "accuracy_km": accuracy_km})


def load_reported(directory: Path) -> pd.DataFrame:
    """Every `*.csv` of `directory` as one validated frame (columns of the module docstring plus `cell_id`)."""
    records = [r for path in sorted(Path(directory).glob("*.csv")) for r in _read_csv(path)]
    frame = pd.DataFrame(records, columns=list(COLUMNS))
    frame["date"] = pd.to_datetime(frame["date"]).astype("datetime64[ns]")
    for name in ("latitude", "longitude", "accuracy_km"):
        frame[name] = frame[name].astype(np.float64)
    cells = grid.latlon_to_cell(frame["latitude"].to_numpy(), frame["longitude"].to_numpy())
    frame["cell_id"] = np.asarray(cells, dtype=np.int64)
    return frame


# --------------------------------------------------------------------------------------------- published levels

def published_days(live_root: Path) -> list[date]:
    """The run dates under `live_root` whose `run.json` says the run completed, ascending."""
    live_root = Path(live_root)
    if not live_root.is_dir():
        return []
    days = []
    for folder in sorted(live_root.iterdir()):
        try:
            day = date.fromisoformat(folder.name)
        except ValueError:
            continue
        run_json = folder / "run.json"
        if day.isoformat() == folder.name and run_json.is_file() \
                and json.loads(run_json.read_text(encoding="utf-8")).get("status") == "complete":
            days.append(day)
    return days


def live_levels(live_root: Path, lead: int = 0) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[date]]:
    """(levels, scored, cell_ids, days) of the published lead-`lead` forecasts, cells x days.

    `days` is every calendar day from the first to the last forecast day; a day with no published run is a column of -1
    levels (never an alert, which `match` and the scores read as `level >= min_level`) and is not scored. Lead k of the run
    of day D sits on day D + k; a completed run without its `risk_D{k}.parquet` published no lead-k forecast and leaves that
    day as missing. `scored` marks the cells with a finite risk.
    """
    if lead not in LEADS:
        raise ValueError(f"lead must be one of {LEADS}, got {lead}")
    name = "alerts.parquet" if lead == 0 else f"risk_D{lead}.parquet"
    frames = {}
    for run in published_days(live_root):
        path = Path(live_root) / run.isoformat() / name
        if lead and not path.is_file():
            continue  # a run that could not fetch its forecast rain wrote no risk_D{k}: no forecast for that day
        frame = pd.read_parquet(path, columns=["cell_id", "date", "level", "risk"])
        forecast = pd.Timestamp(run + timedelta(days=lead))
        if not (frame["date"] == forecast).all():
            raise ValueError(f"{run.isoformat()}/{name} holds dates other than {forecast.date().isoformat()}")
        frames[run] = frame
    if not frames:
        return np.zeros((0, 0), dtype=np.int8), np.zeros((0, 0), dtype=bool), np.zeros(0, dtype=np.int64), []
    runs = list(frames)
    cell_ids = np.unique(np.concatenate([f["cell_id"].to_numpy() for f in frames.values()])).astype(np.int64)
    n_days = (runs[-1] - runs[0]).days + 1
    levels = np.full((len(cell_ids), n_days), -1, dtype=np.int8)
    scored = np.zeros(levels.shape, dtype=bool)
    for run, frame in frames.items():
        column = (run - runs[0]).days
        rows = np.searchsorted(cell_ids, frame["cell_id"].to_numpy())
        levels[rows, column] = frame["level"].to_numpy()
        scored[rows, column] = np.isfinite(frame["risk"].to_numpy())
    first = runs[0] + timedelta(days=lead)
    return levels, scored, cell_ids, [first + timedelta(days=i) for i in range(n_days)]


# --------------------------------------------------------------------------------------------------- the ledger

def _without_ground_truth(scores: dict) -> dict:
    """With no event in the lead's days nothing can verify an alert, so precision is unknown (NaN), not 0 of N.

    `verified_alert_cell_days` is unknown too: an event just outside the window can still verify an alert beside it.
    """
    if scores["events"]:
        return scores
    return {**scores, "precision": math.nan, "precision_ci": [math.nan, math.nan],
            "verified_alert_cell_days": math.nan, "events_per_1000_alert_cell_days": math.nan}


def ledger(live_root: Path, reported_dir: Path, today: date, tol: Tolerance = Tolerance()) -> dict:
    """Per lead and alert level, `bootstrap_scores` of the published levels against the reported events.

    Forecast days after `today` are dropped. Days from `provisional_from` (`today` minus 14 days) on are listed under
    `provisional_days` of each lead: reports for them may still arrive.
    """
    events = load_reported(reported_dir)
    provisional_from = today - timedelta(days=PROVISIONAL_DAYS)
    result = {
        "today": today.isoformat(),
        "provisional_from": provisional_from.isoformat(),
        "tolerance": {"km": tol.km, "days": tol.days},
        "reported_events": int(len(events[["cell_id", "date"]].drop_duplicates())),
        "leads": {},
    }
    for lead in LEADS:
        levels, scored, cell_ids, days = live_levels(live_root, lead)
        keep = [i for i, d in enumerate(days) if d <= today]
        levels, scored, days = levels[:, keep], scored[:, keep], [days[i] for i in keep]
        m = match(levels, cell_ids, days, events, tol)
        result["leads"][str(lead)] = {
            "first_day": days[0].isoformat() if days else None,
            "last_day": days[-1].isoformat() if days else None,
            "days": len(days),
            "published_days": int((levels >= 0).any(axis=0).sum()),
            "provisional_days": [d.isoformat() for d in days if d >= provisional_from],
            "events_outside_window": m.outside_window,
            "levels": {str(k): _without_ground_truth(bootstrap_scores(levels, scored, m, k, BOOTSTRAP)) for k in LEVELS},
        }
    return result


# ------------------------------------------------------------------------------------------------------- output

def markdown(result: dict) -> str:
    tol = result["tolerance"]
    lines = [
        "# Live verification ledger",
        "",
        f"As of {result['today']}. Published alerts against {result['reported_events']} reported landslide events "
        f"(`data/raw/manual/reported_events/`), matched within {tol['km']:g} km and {tol['days']} day(s). POD is the share of "
        "events whose highest level within tolerance reached the level; precision is the share of alert cell-days that an "
        "event lies within tolerance of. Intervals are 95% percentile bootstraps over days (precision) and events (POD).",
        "",
        f"Days from {result['provisional_from']} on are provisional: reports for them are still arriving, so their precision "
        "and detection can change. Forecast days after the date above are not scored.",
        "",
    ]
    if result["reported_events"] == 0:
        lines += ["No reported events yet, so detection and precision are n/a; alert cell-days are still counted.", ""]
    for lead, entry in result["leads"].items():
        ahead = "the day's own alerts" if lead == "0" else f"forecast {lead} day{'s' * (int(lead) > 1)} ahead"
        lines += [
            f"## Lead {lead} ({ahead})",
            "",
            f"{entry['days']} days from {entry['first_day'] or 'n/a'} to {entry['last_day'] or 'n/a'}, "
            f"{entry['published_days']} with a published run, {len(entry['provisional_days'])} provisional; "
            f"{entry['events_outside_window']} reported event(s) fall outside these days.",
            "",
            "| level | events | hits | POD [95% CI] | alert cell-days | verified | precision [95% CI] | alert share |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for level in LEVELS:
            s = entry["levels"][str(level)]
            precision = f"{_pct(s['precision'], 3)} {_interval(s['precision_ci'], 3)}" if s["events"] else "n/a"
            verified = f"{s['verified_alert_cell_days']:,}" if s["events"] else "n/a"
            lines.append(
                f"| {LEVEL_NAMES[level]} | {s['events']} | {s['hits']} | {_pct(s['pod'])} {_interval(s['pod_ci'])} | "
                f"{s['alert_cell_days']:,} | {verified} | "
                f"{precision} | {_pct(s['alert_share'], 2)} |")
        lines.append("")
    return "\n".join(lines)


def write_ledger(out: Path, today: date | None = None, say=print) -> dict:
    """Score `data/live` against the reported events and write `reports/live_verification.{json,md}` into `out`."""
    today = today or datetime.now(IST).date()
    REPORTED_DIR.mkdir(parents=True, exist_ok=True)
    result = ledger(live_run.live_root(live_run.load_run_config()), REPORTED_DIR, today)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    dump_json(out / f"{REPORT_STEM}.json", result)
    (out / f"{REPORT_STEM}.md").write_text(markdown(result), encoding="utf-8")
    say(f"{result['reported_events']} reported event(s); wrote {hm.display_path(out / REPORT_STEM)}.{{json,md}}")
    return result
