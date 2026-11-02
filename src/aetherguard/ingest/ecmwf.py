"""ECMWF IFS open-data precipitation forecasts -> IMD-day totals for D+1..D+3 on the 0.1-degree IMERG grid (spec section 12, F2).

Two products, both total precipitation `tp` (metres, accumulated from the start of the forecast; the cumulative message is used
directly, like the GFS `0-H` message):

* `hres`  the deterministic run: stream `oper` for the 00Z and 12Z cycles, `scda` for the 06Z and 18Z cycles;
* `ens`   stream `enfo`, the 51-member ensemble (control + 50 perturbed members; the live files of 2026 carry the 50 perturbed
          members only, so at least `MIN_ENSEMBLE_MEMBERS` members are required, not the control). Per pixel the ensemble mean and the 10th / 50th / 90th
          percentile of the member IMD-day totals are kept; the members themselves are not stored.

Day basis and cut-off are those of `ingest.gfs` (IMD day X = (03:00 UTC X-1, 03:00 UTC X]; a cycle may not start after 03:00 UTC
of the issue day). ECMWF publishes the 00Z run about 7.5-8 h after its time, so the 00Z cycle of the run day D is not out when the
daily run starts at 05:30 UTC (measured, reports/phase6_ecmwf_publication.md); the cycles tried are, newest first, 00Z of D, 18Z of
D-1 and 12Z of D-1 (`ecmwf.cycles` in configs/live.yaml), each only when its last needed step is published. The archive
evaluation uses `ecmwf.archive.cycle` (the 12Z run of D-1, complete on both public copies; the live run finds the 18Z run too from
02:15 UTC on). HRES and the ensemble pick their cycle independently; the day file records both.

Access paths (configs/live.yaml, section `ecmwf`), all anonymous HTTPS:
* live: `https://data.ecmwf.int/forecasts/` (the last few days);
* archive: the public buckets `ecmwf-open-data` (Google Cloud, tolerant of many parallel requests but with gaps in 2023-06/07 and
  in the 2024 `scda` runs) and `ecmwf-forecasts` (AWS, complete from 2023 but answers bursts with HTTP 503 `SlowDown`); the first
  copy whose index can be read is used. Every file has a `.index` (JSON lines) with the byte range of each message, so one record
  is fetched with an HTTP Range request and the global file is never downloaded. The AWS copy is the original: its
  `Last-Modified` is the publication time (`publication_latency_h`); the Google copy is made later. Layout: 0.4 degree under
  `<ymd>/<hh>z/0p4-beta/` until 2024-02-27, 0.25 degree under `<ymd>/<hh>z/ifs/0p25/` from 2024-02-28 (`ifs_layout_from`).

Licence: CC BY 4.0 (https://www.ecmwf.int/en/forecasts/datasets/open-data); wherever a forecast is shown it is attributed
(`ATTRIBUTION`).
"""
from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, time as clock, timedelta, timezone
from pathlib import Path

import numpy as np
import requests

from ..config import data_root
from ..http import DownloadError
from ..manifest import Manifest
from ..urlredact import redact_url
from . import gfs

UTC = timezone.utc
SOURCE_LIVE = "ECMWF IFS open data tp via data.ecmwf.int (.index byte range)"
SOURCE_ARCHIVE = "ECMWF IFS open data tp via the public bucket ecmwf-forecasts (.index byte range)"
LICENCE = "CC BY 4.0 (ECMWF open data, https://www.ecmwf.int/en/forecasts/datasets/open-data)"
ATTRIBUTION = "ECMWF IFS open data (CC BY 4.0)"
MANIFEST_PATH = gfs.MANIFEST_PATH
STREAM_TYPES = {"oper": "fc", "scda": "fc", "enfo": "ef"}
KINDS = ("hres", "ens")
HRES_STREAMS = {0: "oper", 12: "oper", 6: "scda", 18: "scda"}   # the 06Z / 18Z runs of the deterministic model are `scda`
ENSEMBLE_MEMBERS = 51
MIN_ENSEMBLE_MEMBERS = 40         # fewer complete members than this and the ensemble day is not published
PERCENTILES = (10, 50, 90)
STORED_DTYPE = np.float16           # rain totals are kept to 3 significant digits: the archive stays under 2 MB per issue day
M_TO_MM = 1000.0
LEAD_DAYS = gfs.LEAD_DAYS
_HEADERS = {"User-Agent": "AetherGuard/0.1 (research prototype)", "Accept-Encoding": "identity"}
_LOCAL = threading.local()


class EcmwfFetchError(RuntimeError):
    """Nothing usable could be fetched for a stream."""


# ------------------------------------------------------------------------------------------------- locations

def archive_prefix(cycle: datetime, archive_cfg: dict) -> str:
    """Bucket folder of a cycle: `<ymd>/<hh>z/ifs/0p25` from `ifs_layout_from`, `<ymd>/<hh>z/0p4-beta` before."""
    switch = date.fromisoformat(archive_cfg["ifs_layout_from"])
    tail = "ifs/0p25" if cycle.date() >= switch else "0p4-beta"
    return f"{cycle:%Y%m%d}/{cycle:%H}z/{tail}"


def file_name(cycle: datetime, step: int, stream: str, suffix: str = "grib2") -> str:
    return f"{cycle:%Y%m%d%H}0000-{step}h-{stream}-{STREAM_TYPES[stream]}.{suffix}"


def archive_url_at(base: str, cycle: datetime, step: int, stream: str, cfg: dict, suffix: str = "grib2") -> str:
    archive = cfg["ecmwf"]["archive"]
    return f"{base}/{archive_prefix(cycle, archive)}/{stream}/{file_name(cycle, step, stream, suffix)}"


def archive_urls(cycle: datetime, step: int, stream: str, cfg: dict, suffix: str = "grib2") -> list[str]:
    """The archive copies of one file, best first: every base URL of `ecmwf.archive.base_urls` (same layout and same bytes)."""
    return [archive_url_at(base, cycle, step, stream, cfg, suffix) for base in cfg["ecmwf"]["archive"]["base_urls"]]


def live_urls(cycle: datetime, step: int, stream: str, cfg: dict, suffix: str = "grib2") -> list[str]:
    return [f"{cfg['ecmwf']['live']['base_url']}/{cycle:%Y%m%d}/{cycle:%H}z/ifs/0p25/{stream}/"
            f"{file_name(cycle, step, stream, suffix)}"]


# ---------------------------------------------------------------------------------------------- time rules

def archive_cycle(issue_day: date, cfg: dict) -> datetime:
    """The cycle the archive evaluation uses for `issue_day` (`ecmwf.archive.cycle`: day offset and hour)."""
    spec = cfg["ecmwf"]["archive"]["cycle"]
    return datetime.combine(issue_day + timedelta(days=int(spec["day_offset"])), clock(int(spec["hour"])), tzinfo=UTC)


def cycle_candidates(issue_day: date, cfg: dict, now_utc: datetime) -> list[datetime]:
    """Cycles the live run may use, newest first: those of `ecmwf.cycles`, not after 03:00 UTC of `issue_day` and not in the
    future."""
    now = gfs._require_utc(now_utc)
    limit = datetime.combine(issue_day, clock(gfs.IMD_DAY_END_UTC_HOUR), tzinfo=UTC)
    cycles = [datetime.combine(issue_day + timedelta(days=int(c["day_offset"])), clock(int(c["hour"])), tzinfo=UTC)
              for c in cfg["ecmwf"]["cycles"]]
    return sorted((c for c in cycles if c <= min(limit, now)), reverse=True)


def stream_name(kind: str, cycle: datetime) -> str:
    """Bucket stream of the product `kind` (`hres` | `ens`) for `cycle`."""
    if kind == "ens":
        return "enfo"
    if kind == "hres":
        return HRES_STREAMS[cycle.hour]
    raise ValueError(f"kind must be hres or ens, got {kind!r}")


# --------------------------------------------------------------------------------------------- index and stats

def parse_index(text: str) -> list[dict]:
    """The JSON-lines `.index` of an ECMWF open-data file as a list of records (blank lines skipped)."""
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def tp_ranges(records: list[dict], stream: str) -> dict[int, tuple[int, int]]:
    """{member: (first byte, last byte)} of the `tp` messages. HRES (`oper`, `scda`) is member 0; the ensemble has the control
    `cf` as 0 and the perturbed members `pf` as their `number` (1..50)."""
    ranges: dict[int, tuple[int, int]] = {}
    for record in records:
        if record.get("param") != "tp":
            continue
        if stream != "enfo":
            member = 0
        elif record.get("type") == "cf":
            member = 0
        elif record.get("type") == "pf":
            member = int(record["number"])
        else:
            continue
        start = int(record["_offset"])
        ranges[member] = (start, start + int(record["_length"]) - 1)
    return ranges


def ensemble_stats(members: np.ndarray) -> dict[str, np.ndarray]:
    """Per-pixel mean and p10 / p50 / p90 of (n_members, ...) member totals; a pixel NaN in any member is NaN."""
    members = np.asarray(members, dtype=np.float32)
    p10, p50, p90 = np.percentile(members, PERCENTILES, axis=0)
    return {"mean": members.mean(axis=0, dtype=np.float64).astype(np.float32), "p10": p10.astype(np.float32),
            "p50": p50.astype(np.float32), "p90": p90.astype(np.float32)}


# ---------------------------------------------------------------------------------------------- transport

class Http:
    """Anonymous HTTPS with a keep-alive session per thread; every call retries transport errors, HTTP 429 and 5xx."""

    def __init__(self, retries: int = 6, backoff: float = 2.0, timeout: float = 60.0, requests_per_s: float = 0.0) -> None:
        self.retries, self.backoff, self.timeout = retries, backoff, timeout
        self._interval = 1.0 / requests_per_s if requests_per_s > 0 else 0.0
        self._pace = threading.Lock()
        self._next_slot = 0.0
        self.throttled = 0              # HTTP 429 / 5xx answers seen (each is retried after a backoff)

    def _wait_for_slot(self) -> None:
        """Spaces the requests of all threads at least `1 / requests_per_s` seconds apart (the bucket answers HTTP 503
        `SlowDown` to bursts)."""
        if not self._interval:
            return
        with self._pace:
            now = time.monotonic()
            slot = max(now, self._next_slot)
            self._next_slot = slot + self._interval
        if slot > now:
            time.sleep(slot - now)

    def _session(self) -> requests.Session:
        session = getattr(_LOCAL, "session", None)
        if session is None:
            session = _LOCAL.session = requests.Session()
            session.headers.update(_HEADERS)
        return session

    def _request(self, method: str, url: str, headers: dict | None = None) -> requests.Response:
        error: DownloadError | None = None
        for attempt in range(self.retries):
            self._wait_for_slot()
            try:
                response = self._session().request(method, url, headers=headers, timeout=self.timeout)
                code = response.status_code
                if code in (403, 404):
                    raise gfs.NotPublishedError(f"HTTP {code} from {redact_url(url)}", status=code)
                if code == 429 or code >= 500:
                    self.throttled += 1
                    raise DownloadError(f"HTTP {code} from {redact_url(url)}", retriable=True, status=code)
                if code >= 400:
                    raise DownloadError(f"HTTP {code} from {redact_url(url)}", status=code)
                return response
            except requests.RequestException as exc:
                error = DownloadError(f"{type(exc).__name__}: {exc}", retriable=True)
            except DownloadError as exc:
                error = exc
            if not error.retriable:
                raise error
            if attempt < self.retries - 1:
                time.sleep(self.backoff * 2 ** attempt)
        raise error

    def head(self, url: str) -> dict | None:
        """Response headers of `url`, None when it does not exist (yet)."""
        try:
            return dict(self._request("HEAD", url).headers)
        except gfs.NotPublishedError:
            return None

    def text(self, url: str) -> str:
        return self._request("GET", url).text

    def byte_range(self, url: str, first: int, last: int) -> bytes:
        response = self._request("GET", url, headers={"Range": f"bytes={first}-{last}"})
        if response.status_code != 206:
            raise DownloadError(f"range request to {redact_url(url)} answered HTTP {response.status_code}")
        if len(response.content) != last - first + 1:
            raise DownloadError(f"truncated range from {redact_url(url)}: got {len(response.content)} of "
                                f"{last - first + 1} bytes", retriable=True)
        return response.content


def _regular_axis(first: float, last: float, count: int) -> np.ndarray:
    if count < 2:
        raise gfs.GribDecodeError("a grid axis needs at least two points")
    return np.linspace(first, last, count)


def _longitudes(first: float, increment: float, count: int) -> tuple[np.ndarray, np.ndarray]:
    """(ascending longitudes in 0..360, the column order that sorts the stored ones): ECMWF global grids start at 180 degrees
    and wrap through 0."""
    stored = (first + increment * np.arange(count)) % 360.0
    order = np.argsort(stored, kind="stable")
    return stored[order], order


def decode_tp(data: bytes, step: int, bbox: dict):
    """(lats, lons, field in mm) of one `tp` message cropped to the domain; the message must be the total from forecast hour 0
    to `step`.

    The axes of the regular latitude-longitude grid come from the message header (a global 0.25 degree field has a million
    points and eccodes needs 0.2 s to enumerate them; the header takes microseconds).
    """
    messages = gfs._split_grib(data)
    if len(messages) != 1:
        raise gfs.GribDecodeError(f"expected one GRIB message, found {len(messages)}")
    eccodes = gfs._eccodes()
    with gfs._ECCODES_LOCK:
        gid = eccodes.codes_new_from_message(messages[0])
        try:
            get = lambda key: eccodes.codes_get(gid, key)  # noqa: E731
            if get("shortName") != "tp":
                raise gfs.GribDecodeError(f"the message is {get('shortName')!r}, expected tp")
            if get("stepUnits") != 1:
                raise gfs.GribDecodeError("tp step is not in hours")
            if get("iScansNegatively") or get("jPointsAreConsecutive"):
                raise gfs.GribDecodeError("unsupported GRIB scanning mode")
            start, end = int(get("startStep")), int(get("endStep"))
            ni, nj = int(get("Ni")), int(get("Nj"))
            lats = _regular_axis(get("latitudeOfFirstGridPointInDegrees"), get("latitudeOfLastGridPointInDegrees"), nj)
            lons, order = _longitudes(get("longitudeOfFirstGridPointInDegrees"), get("iDirectionIncrementInDegrees"), ni)
            values = np.asarray(eccodes.codes_get_values(gid), dtype=np.float64)
            if values.size != ni * nj:
                raise gfs.GribDecodeError(f"{values.size} values for a {nj} x {ni} grid")
            if get("bitmapPresent"):
                values[values == get("missingValue")] = np.nan
        finally:
            eccodes.codes_release(gid)
    if (start, end) != (0, step):
        raise gfs.GribDecodeError(f"the tp message covers hours {start}-{end}, expected 0-{step}")
    grid = values.reshape(nj, ni)[:, order]
    if lats[0] > lats[-1]:
        lats, grid = lats[::-1], grid[::-1]
    if np.any(np.diff(lons) <= 0):
        raise gfs.GribDecodeError("longitudes repeat")
    lats, lons, grid = gfs.crop_to_bbox(lats, lons, np.ascontiguousarray(grid, dtype=np.float32), bbox)
    return lats, lons, grid * np.float32(M_TO_MM)


# ----------------------------------------------------------------------------------------------- one stream

@dataclass
class StreamResult:
    """What one product gives for an issue day: (3, 280, 260) fields, validity per lead day and the steps that failed."""
    cycle: datetime
    fields: dict[str, np.ndarray]
    day_valid: np.ndarray
    missing_steps: list[int]
    n_members: int
    urls: list[str]
    failures: dict[str, str]


def _nan_days() -> np.ndarray:
    return np.full((len(LEAD_DAYS), gfs.TARGET_LATS.size, gfs.TARGET_LONS.size), np.nan, dtype=np.float32)


def _fetch_member(http, url: str, ranges: dict[int, tuple[int, int]], member: int, step: int, bbox: dict):
    first, last = ranges[member]
    return decode_tp(http.byte_range(url, first, last), step, bbox)


def _first_index(http, candidates: list[str], stream: str) -> tuple[str, dict[int, tuple[int, int]]]:
    """(file URL, tp byte ranges) from the first copy of a file whose `.index` can be read."""
    error: DownloadError | None = None
    for url in candidates:
        try:
            return url, tp_ranges(parse_index(http.text(url.rsplit(".", 1)[0] + ".index")), stream)
        except DownloadError as exc:
            error = exc
    raise error


def fetch_stream(http, kind: str, cycle: datetime, issue_day: date, cfg: dict, urls_of, *, members_pool: int = 6
                 ) -> StreamResult:
    """IMD-day totals of the product `kind` (`hres` | `ens`) for the cycle: HRES one field set, the ensemble the mean / p10 / p50
    / p90 of its members.

    A step whose index or message cannot be fetched is listed in `missing_steps` and every lead day whose window uses it is
    invalid (NaN, never zero). For the ensemble only the members with every needed step count; fewer than
    `MIN_ENSEMBLE_MEMBERS` of them invalidate the ensemble day.
    """
    bbox = cfg["domain_bbox"]
    steps = gfs.required_hours(cycle, issue_day)
    stream = stream_name(kind, cycle)
    ensemble = kind == "ens"
    cumulative: dict[int, dict[int, np.ndarray]] = {}     # member -> step -> mm on the domain crop
    axes = None
    failures: dict[str, str] = {}
    urls: list[str] = []
    for step in steps:
        try:
            url, ranges = _first_index(http, urls_of(cycle, step, stream, cfg), stream)
            urls.append(url)
            wanted = sorted(ranges) if ensemble else [0]
            if (len(ranges) < MIN_ENSEMBLE_MEMBERS) if ensemble else (0 not in ranges):
                raise gfs.NotPublishedError(f"no complete tp record set in the index of {redact_url(url)}")
            with ThreadPoolExecutor(max_workers=members_pool if ensemble else 1) as pool:
                futures = {pool.submit(_fetch_member, http, url, ranges, m, step, bbox): m for m in wanted}
                for future in as_completed(futures):
                    member = futures[future]
                    try:
                        lats, lons, field = future.result()
                        if axes is None:
                            axes = (lats, lons)
                        elif not (np.array_equal(axes[0], lats) and np.array_equal(axes[1], lons)):
                            raise gfs.GribDecodeError("the grid differs between messages")
                    except (DownloadError, gfs.GribDecodeError) as exc:
                        if not ensemble:
                            raise
                        failures[f"member{member}@{step}"] = f"{type(exc).__name__}: {exc}"   # that member is left out
                        continue
                    cumulative.setdefault(member, {})[step] = field
        except (DownloadError, gfs.GribDecodeError) as exc:
            failures[str(step)] = f"{type(exc).__name__}: {exc}"
    missing = [s for s in steps if str(s) in failures]
    fields = {name: _nan_days() for name in (("mean", "p10", "p50", "p90") if ensemble else ("hres",))}
    valid = np.zeros(len(LEAD_DAYS), dtype=bool)
    counts: list[int] = []
    if cumulative:
        lats, lons = axes
        members = sorted(cumulative)
        per_member = np.stack([gfs.imd_days_on_grid(cumulative[m], lats, lons, cycle, issue_day) for m in members])
        need = MIN_ENSEMBLE_MEMBERS if ensemble else 1
        for k in range(len(LEAD_DAYS)):
            usable = [i for i in range(len(members)) if np.isfinite(per_member[i, k]).all()]
            if len(usable) < need:
                continue
            valid[k] = True
            counts.append(len(usable))
            if ensemble:
                for name, values in ensemble_stats(per_member[usable, k]).items():
                    fields[name][k] = values
            else:
                fields["hres"][k] = per_member[usable[0], k]
        if ensemble and not valid.any():
            failures.setdefault("members", f"fewer than {MIN_ENSEMBLE_MEMBERS} members have the steps of a lead day")
    return StreamResult(cycle, fields, valid, missing, min(counts, default=0), urls, failures)


# ---------------------------------------------------------------------------------------------- day files

def day_file_name(issue_day: date) -> str:
    return f"ecmwf_imdday_{issue_day.isoformat()}.npz"


def day_file_path(root: Path, issue_day: date) -> Path:
    return Path(root) / "processed" / "rain" / day_file_name(issue_day)


@dataclass(frozen=True)
class EcmwfForecast:
    """The stored IMD-day totals of one issue day (None fields: the stream is not valid for that day)."""
    hres: np.ndarray | None             # (3, rows, cols)
    ens_mean: np.ndarray | None
    ens_p10: np.ndarray | None
    ens_p50: np.ndarray | None
    ens_p90: np.ndarray | None
    hres_valid: np.ndarray              # (3,) bool
    ens_valid: np.ndarray
    hres_cycle: datetime | None
    ens_cycle: datetime | None
    n_members: int


def _iso(moment: datetime | None) -> str:
    return "" if moment is None else moment.isoformat()


def write_day_file(root: Path, manifest: Manifest, issue_day: date, hres: StreamResult | None, ens: StreamResult | None,
                   issued: datetime, source: str) -> Path:
    arrays = {"lead_days": np.array(LEAD_DAYS, dtype=np.int32), "lats": gfs.TARGET_LATS, "lons": gfs.TARGET_LONS,
              "issued_utc": np.array(issued.isoformat())}
    arrays["hres"] = (hres.fields["hres"] if hres else _nan_days()).astype(STORED_DTYPE)
    arrays["hres_valid"] = hres.day_valid if hres else np.zeros(len(LEAD_DAYS), dtype=bool)
    arrays["hres_cycle"] = np.array(_iso(hres.cycle if hres else None))
    for name in ("mean", "p10", "p50", "p90"):
        arrays[f"ens_{name}"] = (ens.fields[name] if ens else _nan_days()).astype(STORED_DTYPE)
    arrays["ens_valid"] = ens.day_valid if ens else np.zeros(len(LEAD_DAYS), dtype=bool)
    arrays["ens_cycle"] = np.array(_iso(ens.cycle if ens else None))
    arrays["n_members"] = np.array(ens.n_members if ens else 0, dtype=np.int32)
    urls = [u for r in (hres, ens) if r for u in r.urls]
    arrays["urls"] = np.array(urls)
    arrays["failures"] = np.array(json.dumps({"oper": hres.failures if hres else None,
                                              "enfo": ens.failures if ens else None}))
    path = day_file_path(root, issue_day)
    gfs._write_npz(path, **arrays)
    first = next((u for u in urls), "none")
    manifest.add(path, source, f"derived: ECMWF IFS tp, {len(urls)} files from {first} (+ same cycle, other steps)", LICENCE)
    return path


def load_day(path: Path) -> EcmwfForecast | None:
    path = Path(path)
    if not path.is_file():
        return None
    with np.load(path, allow_pickle=False) as data:
        hres_valid, ens_valid = data["hres_valid"].astype(bool), data["ens_valid"].astype(bool)

        def cycle(name: str) -> datetime | None:
            text = str(data[name])
            return datetime.fromisoformat(text).astimezone(UTC) if text else None
        return EcmwfForecast(
            hres=data["hres"].astype(np.float32) if hres_valid.any() else None,
            ens_mean=data["ens_mean"].astype(np.float32) if ens_valid.any() else None,
            ens_p10=data["ens_p10"].astype(np.float32) if ens_valid.any() else None,
            ens_p50=data["ens_p50"].astype(np.float32) if ens_valid.any() else None,
            ens_p90=data["ens_p90"].astype(np.float32) if ens_valid.any() else None,
            hres_valid=hres_valid, ens_valid=ens_valid, hres_cycle=cycle("hres_cycle"), ens_cycle=cycle("ens_cycle"),
            n_members=int(data["n_members"]))


def _manifest(root: Path, manifest: Manifest | None) -> Manifest:
    return manifest if manifest is not None else Manifest(MANIFEST_PATH, root)


# ----------------------------------------------------------------------------------------------- live path

def newest_published(http, kind: str, issue_day: date, cfg: dict, now_utc: datetime) -> datetime:
    """Newest candidate cycle whose last needed step of the product `kind` is published on data.ecmwf.int."""
    tried = []
    for cycle in cycle_candidates(issue_day, cfg, now_utc):
        last = gfs.required_hours(cycle, issue_day)[-1]
        if http.head(live_urls(cycle, last, stream_name(kind, cycle), cfg)[0]) is not None:
            return cycle
        tried.append(f"{cycle:%Y-%m-%d %HZ}")
    raise gfs.NoCompleteCycleError(f"none of the cycles {', '.join(tried) or 'allowed'} has step data of {kind} published")


def fetch_live(issue_day: date, cfg: dict, *, now_utc: datetime | None = None, root: Path | None = None,
               manifest: Manifest | None = None, http=None) -> Path:
    """Write `processed/rain/ecmwf_imdday_<issue_day>.npz` from the newest published cycle of each stream (module doc).

    A stream that cannot be fetched is left out of the file (its days invalid); EcmwfFetchError when neither stream is usable.
    """
    root = Path(root) if root is not None else data_root()
    manifest = _manifest(root, manifest)
    http = http or Http()
    now = gfs._require_utc(now_utc if now_utc is not None else datetime.now(UTC))
    results: dict[str, StreamResult | None] = {}
    errors: dict[str, str] = {}
    for kind in KINDS:
        try:
            cycle = newest_published(http, kind, issue_day, cfg, now)
            results[kind] = fetch_stream(http, kind, cycle, issue_day, cfg, live_urls)
        except (DownloadError, gfs.GribDecodeError, gfs.NoCompleteCycleError) as exc:
            results[kind], errors[kind] = None, f"{type(exc).__name__}: {exc}"
    usable = [r for r in results.values() if r is not None and r.day_valid.any()]
    if not usable:
        raise EcmwfFetchError("no ECMWF stream could be fetched: " + "; ".join(
            f"{k}: {errors.get(k) or 'no valid lead day'}" for k in KINDS))
    return write_day_file(root, manifest, issue_day, results["hres"], results["ens"], now, SOURCE_LIVE)


# -------------------------------------------------------------------------------------------- archive path

def archive_days(windows: list[dict]) -> list[date]:
    """Every day of the configured `{start, end}` windows, in order."""
    days: list[date] = []
    for window in windows:
        start, end = date.fromisoformat(window["start"]), date.fromisoformat(window["end"])
        days += [start + timedelta(days=n) for n in range((end - start).days + 1)]
    return days


def _archive_day(day: date, cfg: dict, root: Path, manifest: Manifest, http) -> dict:
    if manifest.is_current(day_file_path(root, day)):
        return {"state": "skipped"}
    cycle = archive_cycle(day, cfg)
    pool = int(cfg["ecmwf"]["archive"]["members_pool"])
    hres = fetch_stream(http, "hres", cycle, day, cfg, archive_urls)
    ens = fetch_stream(http, "ens", cycle, day, cfg, archive_urls, members_pool=pool)
    if not (hres.day_valid.any() or ens.day_valid.any()):
        reasons = {**hres.failures, **{f"enfo_{k}": v for k, v in ens.failures.items()}}
        raise EcmwfFetchError(f"nothing could be fetched for the {cycle:%Y-%m-%d %HZ} cycle: {next(iter(reasons.values()), 'no data')}")
    write_day_file(root, manifest, day, hres, ens, datetime.now(UTC), SOURCE_ARCHIVE)
    return {"state": "written", "hres_valid": hres.day_valid.tolist(), "ens_valid": ens.day_valid.tolist()}


def fetch_archive(days: list[date], cfg: dict, *, workers: int = 1, root: Path | None = None,
                  manifest: Manifest | None = None, http=None, abort_after: int = 12) -> dict:
    """One `ecmwf_imdday_<day>.npz` per issue day from the archived cycle `ecmwf.archive.cycle`; idempotent and resumable.

    A manifest-current day is skipped. A day with a failure is left unwritten for the next run; after `abort_after`
    consecutive failed days the remaining days are not attempted. Returns {requested, written, skipped, failed: {day: reason},
    incomplete: {day: valid lead days}, seconds}.
    """
    root = Path(root) if root is not None else data_root()
    manifest = _manifest(root, manifest)
    http = http or Http()
    started = time.monotonic()
    state = {"consecutive": 0}
    lock = threading.Lock()
    stop = threading.Event()

    def work(day: date) -> dict:
        if stop.is_set():
            return {"state": "failed", "reason": "not attempted: stopped after repeated failures"}
        try:
            result = _archive_day(day, cfg, root, manifest, http)
        except (DownloadError, gfs.GribDecodeError, EcmwfFetchError, OSError) as exc:
            result = {"state": "failed", "reason": f"{type(exc).__name__}: {exc}"}
        with lock:
            state["consecutive"] = state["consecutive"] + 1 if result["state"] == "failed" else 0
            if state["consecutive"] >= abort_after:
                stop.set()
        return result

    summary = {"requested": len(days), "written": [], "skipped": [], "failed": {}, "incomplete": {}}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(work, day): day for day in days}
        for future in as_completed(futures):
            key, result = futures[future].isoformat(), future.result()
            if result["state"] == "failed":
                summary["failed"][key] = result["reason"]
            elif result["state"] == "skipped":
                summary["skipped"].append(key)
            else:
                summary["written"].append(key)
                if not (all(result["hres_valid"]) and all(result["ens_valid"])):
                    summary["incomplete"][key] = {"hres": result["hres_valid"], "ens": result["ens_valid"]}
    for name in ("written", "skipped"):
        summary[name].sort()
    summary["failed"] = dict(sorted(summary["failed"].items()))
    summary["incomplete"] = dict(sorted(summary["incomplete"].items()))
    summary["seconds"] = time.monotonic() - started
    return summary


# ------------------------------------------------------------------------------------ publication times

def publication_latency_h(http, cycle: datetime, kind: str, issue_day: date, cfg: dict) -> float | None:
    """Hours between the cycle time and the bucket's `Last-Modified` of the last step the IMD days need (None: not there)."""
    last = gfs.required_hours(cycle, issue_day)[-1]
    base = cfg["ecmwf"]["archive"]["publication_base_url"]
    headers = http.head(archive_url_at(base, cycle, last, stream_name(kind, cycle), cfg))
    if headers is None or "Last-Modified" not in headers:
        return None
    modified = datetime.strptime(headers["Last-Modified"], "%a, %d %b %Y %H:%M:%S GMT").replace(tzinfo=UTC)
    return (modified - cycle).total_seconds() / 3600.0
