"""Local store of decoded SYNOP reports: the NWS ring (live) and the OGIMET archive (validation and replays only).

    python -m aetherguard.ingest.synop_store collect                         # run at least once a day
    python -m aetherguard.ingest.synop_store backfill-ogimet --start 2026-07-01 --end 2026-11-15 [--blocks 42 43 44]
    python -m aetherguard.ingest.synop_store status

Why a store: the US National Weather Service republishes the GTS SYNOP bulletins as a ring of 5-minute files
(`RING_URL`, about 25 hours kept, about 10 MB a day), so a report is only there for a day. `collect` keeps every ring
file it has not seen yet under `data/raw/synop/nws/<YYYYMMDD>/` (manifest-tracked) and appends its decoded reports for
blocks 42-44 (India, Nepal, Bhutan) to `data/processed/synop/reports.parquet` with the ring file's time as the arrival
time, which is what a backtest checks against the cut-off. It is idempotent (a file already stored is skipped) and
logs to `logs/synop_collect.log`.

`backfill-ogimet` fills past days from OGIMET's archive (`getsynop`, at most one request per block and 30 days, 30 s
apart; OGIMET asks not to be abused and allows informational use only, not mission-critical use): these reports have no
arrival time (NaT). They serve the validation and the scratch replays; live use of OGIMET is a decision for the user.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd
import requests

from ..config import PROJECT_ROOT, data_root
from ..manifest import Manifest
from . import synop as S

log = logging.getLogger(__name__)
UTC = timezone.utc
RING_URL = "https://tgftp.nws.noaa.gov/SL.us008001/DF.an/DC.sflnd/DS.synop/"
OGIMET_URL = "https://www.ogimet.com/cgi-bin/getsynop"
NWS_LICENCE = "US National Weather Service, public domain; coded reports subject to WMO Resolution 40"
OGIMET_LICENCE = ("OGIMET (G. Ballester Valor): informational use only, not for mission-critical use, link to "
                  "https://www.ogimet.com required; coded reports copyright of each national service (WMO Resolution 40)")
BLOCKS = ("42", "43", "44")
HEADERS = {"User-Agent": "AetherGuard/0.1 (research prototype)"}
STORE_COLUMNS = ["station", "time", "ir", "nil", "bulletin", "accumulations", "arrival", "source"]
OGIMET_CHUNK_DAYS = 30
OGIMET_PAUSE_S = 30.0
MONTHS = {m: i for i, m in enumerate(("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov",
                                      "Dec"), start=1)}


def raw_root(root: Path | None = None) -> Path:
    return (Path(root) if root is not None else data_root()) / "raw" / "synop"


def store_path(root: Path | None = None) -> Path:
    return (Path(root) if root is not None else data_root()) / "processed" / "synop" / "reports.parquet"


def parse_listing(text: str, now: datetime) -> list[tuple[str, int, datetime]]:
    """(name, size, file time UTC) of the ring's `ls-l` (`-rw... size Mon DD HH:MM sn.NNNN.txt`); the year, which
    `ls` omits, is the one that puts the time no later than one day after `now`."""
    out = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 9 or not re.fullmatch(r"sn\.\d{4}\.txt", parts[8]) or parts[5] not in MONTHS:
            continue
        hour, minute = (int(x) for x in parts[7].split(":"))
        stamp = datetime(now.year, MONTHS[parts[5]], int(parts[6]), hour, minute, tzinfo=UTC)
        if stamp > now + timedelta(days=1):
            stamp = stamp.replace(year=now.year - 1)
        out.append((parts[8], int(parts[4]), stamp))
    return out


def _http_get(url: str, params: dict | None = None, timeout: float = 120.0) -> bytes:
    response = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    return response.content


def reports_frame(reports: list[S.Report], arrival: datetime | None, source: str) -> pd.DataFrame:
    rows = [{"station": r.station, "time": r.time, "ir": r.ir, "nil": r.nil, "bulletin": r.bulletin,
             "accumulations": json.dumps([[a.amount_mm, a.period_h, a.group, a.trace] for a in r.accumulations]),
             "arrival": arrival, "source": source} for r in reports]
    frame = pd.DataFrame(rows, columns=STORE_COLUMNS)
    frame["time"] = pd.to_datetime(frame["time"], utc=True)
    frame["arrival"] = pd.to_datetime(frame["arrival"], utc=True)
    return frame


def append_store(frame: pd.DataFrame, path: Path) -> int:
    """Append `frame` to the store, dropping exact repeats of a report (keeping its earliest arrival); returns rows
    added. Written through a temporary file, so an interrupted write leaves the old store."""
    path.parent.mkdir(parents=True, exist_ok=True)
    old = pd.read_parquet(path) if path.is_file() else frame.iloc[0:0]
    merged = pd.concat([old, frame], ignore_index=True)
    key = ["station", "time", "ir", "nil", "bulletin", "accumulations", "source"]
    merged = merged.sort_values("arrival", na_position="last").drop_duplicates(key, keep="first")
    merged = merged.sort_values(["time", "station"]).reset_index(drop=True)
    part = path.with_name(path.name + ".part")
    merged.to_parquet(part, index=False)
    part.replace(path)
    return int(len(merged) - len(old))


def load_store(path: Path | None = None) -> pd.DataFrame:
    path = Path(path) if path is not None else store_path()
    if not path.is_file():
        return pd.DataFrame(columns=STORE_COLUMNS)
    return pd.read_parquet(path)


def to_reports(frame: pd.DataFrame) -> list[S.Report]:
    out = []
    for row in frame.itertuples(index=False):
        accs = tuple(S.Accumulation(a, p, g, bool(t)) for a, p, g, t in json.loads(row.accumulations))
        out.append(S.Report(row.station, pd.Timestamp(row.time).to_pydatetime(), row.ir, accs, row.bulletin,
                            bool(row.nil)))
    return out


def usable_at(frame: pd.DataFrame, cutoff: datetime | None, latency_h: float) -> pd.DataFrame:
    """Rows a run with data cut-off `cutoff` may read: arrived at or before it; a row without an arrival time
    (OGIMET backfill) counts as arriving `latency_h` after its observation time. `cutoff` None: every row."""
    if cutoff is None or frame.empty:
        return frame
    arrival = frame["arrival"].where(frame["arrival"].notna(), frame["time"] + pd.Timedelta(hours=latency_h))
    return frame[arrival <= pd.Timestamp(cutoff)]


def station_day_totals(reports: list[S.Report], wmo_by_station: dict[str, str], days: pd.DatetimeIndex
                       ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(values, how): date x station (GHCN id) frames of IMD-day totals (NaN = none) and how each was made or why
    it is missing."""
    versions = S.latest_versions(reports)
    stations = list(wmo_by_station)
    values = pd.DataFrame(np.nan, index=days, columns=stations, dtype=np.float32)
    how = pd.DataFrame("", index=days, columns=stations, dtype=object)
    for day in days:
        for sid in stations:
            value, why = S.imd_day_total(versions, wmo_by_station[sid], day.date())
            how.at[day, sid] = why
            if value is not None:
                values.at[day, sid] = value
    return values, how


# ------------------------------------------------------------------------------------------------------ commands

def collect(root: Path | None = None, manifest: Manifest | None = None, *, fetch: Callable[[str], bytes] | None = None,
            now: datetime | None = None, blocks=BLOCKS) -> dict:
    """Store the ring files not stored yet and append their decoded reports; returns counts."""
    fetch = fetch or (lambda url: _http_get(url))
    now = (now or datetime.now(UTC)).astimezone(UTC)
    raw = raw_root(root) / "nws"
    listing = parse_listing(fetch(RING_URL + "ls-l").decode("latin-1"), now)
    new_files, frames, failures = 0, [], 0
    for name, size, stamp in listing:
        path = raw / stamp.strftime("%Y%m%d") / f"{stamp:%H%M}_{name}"
        if path.is_file():
            continue
        try:
            content = fetch(RING_URL + name)
        except Exception as exc:          # one unreadable file does not stop the collection
            failures += 1
            log.warning("ring file %s not read: %s", name, type(exc).__name__)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        part = path.with_name(path.name + ".part")
        part.write_bytes(content)
        part.replace(path)
        if manifest is not None:
            manifest.add(path, "NWS SYNOP ring (tgftp DS.synop)", RING_URL + name, NWS_LICENCE)
        frames.append(reports_frame(S.parse_bulletins(content.decode("latin-1"), stamp, tuple(blocks)), stamp, "nws"))
        new_files += 1
    added = append_store(pd.concat(frames, ignore_index=True), store_path(root)) if frames else 0
    result = {"ring_files": len(listing), "new_files": new_files, "failed_files": failures, "reports_added": added,
              "ring_oldest": min((s for _, _, s in listing), default=None),
              "ring_newest": max((s for _, _, s in listing), default=None)}
    log.info("collect: %s", result)
    return result


def backfill_ogimet(start: date, end: date, root: Path | None = None, manifest: Manifest | None = None, *,
                    blocks=BLOCKS, fetch: Callable[[dict], bytes] | None = None, pause_s: float = OGIMET_PAUSE_S) -> dict:
    """OGIMET reports of `start` 00 UTC .. `end` 23 UTC per block, in chunks of at most 30 days, one raw file per
    chunk (kept; a chunk already on disk is not requested again)."""
    fetch = fetch or (lambda params: _http_get(OGIMET_URL, params=params, timeout=300.0))
    raw = raw_root(root) / "ogimet"
    requested, frames = 0, []
    chunk_start = start
    while chunk_start <= end:
        chunk_end = min(end, chunk_start + timedelta(days=OGIMET_CHUNK_DAYS - 1))
        for block in blocks:
            path = raw / f"b{block}_{chunk_start:%Y%m%d}_{chunk_end:%Y%m%d}.txt"
            if not path.is_file() or path.stat().st_size == 0:
                if requested:
                    time.sleep(pause_s)
                params = {"block": block, "begin": f"{chunk_start:%Y%m%d}0000", "end": f"{chunk_end:%Y%m%d}2300"}
                content = fetch(params)
                requested += 1
                if not content.strip():
                    log.warning("OGIMET returned nothing for block %s %s..%s", block, chunk_start, chunk_end)
                    continue
                path.parent.mkdir(parents=True, exist_ok=True)
                part = path.with_name(path.name + ".part")
                part.write_bytes(content)
                part.replace(path)
                if manifest is not None:
                    manifest.add(path, "OGIMET getsynop archive", OGIMET_URL, OGIMET_LICENCE)
            lines = path.read_text(encoding="latin-1").splitlines()
            frames.append(reports_frame([r for r in map(S.parse_ogimet_line, lines) if r is not None], None, "ogimet"))
        chunk_start = chunk_end + timedelta(days=1)
    added = append_store(pd.concat(frames, ignore_index=True), store_path(root)) if frames else 0
    result = {"requests": requested, "reports_added": added}
    log.info("backfill-ogimet %s..%s %s: %s", start, end, blocks, result)
    return result


def status(root: Path | None = None) -> dict:
    frame = load_store(store_path(root))
    if frame.empty:
        return {"rows": 0}
    return {"rows": int(len(frame)), "by_source": frame["source"].value_counts().to_dict(),
            "first_time": str(frame["time"].min()), "last_time": str(frame["time"].max()),
            "last_arrival": str(frame["arrival"].max())}


def _setup_logging() -> None:
    logs = PROJECT_ROOT / "logs"
    logs.mkdir(exist_ok=True)
    handler = logging.FileHandler(logs / "synop_collect.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler, logging.StreamHandler()])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m aetherguard.ingest.synop_store")
    parser.add_argument("--manifest", type=Path, default=PROJECT_ROOT / "manifests" / "data_manifest.jsonl")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("collect")
    back = sub.add_parser("backfill-ogimet")
    back.add_argument("--start", type=date.fromisoformat, required=True)
    back.add_argument("--end", type=date.fromisoformat, required=True)
    back.add_argument("--blocks", nargs="+", default=list(BLOCKS))
    sub.add_parser("status")
    args = parser.parse_args(argv)
    _setup_logging()
    manifest = Manifest(args.manifest, data_root())
    if args.cmd == "collect":
        result = collect(manifest=manifest)
    elif args.cmd == "backfill-ogimet":
        result = backfill_ogimet(args.start, args.end, manifest=manifest, blocks=tuple(args.blocks))
    else:
        result = status()
    print(json.dumps(result, default=str, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
