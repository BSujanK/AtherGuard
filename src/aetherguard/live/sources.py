"""Live data sources of the daily run: fetch, freshness and backtest cut-off.

`fetch_all(day, cfg)` asks every source for what the run for IST date `day` needs and returns one `SourceStatus` per
source (`imerg_late`, `imerg_early`, `gfs`, `imd_rt`, `ghcn`). A source never raises out of `fetch_all`: any failure
becomes a failed status carrying the exception class and a redacted message, so the run still publishes and the
bulletin can name what is missing. Payloads stay on disk or in the source object and are read back with the source's
`load`, only for sources whose status is usable.

Day basis (binding). The run date is the IST calendar date. IMD day D = 08:30 IST D-1 to 08:30 IST D = 03:00 UTC D-1 to
03:00 UTC D. IMERG days are UTC days; the training rule is IMD(d) = 0.875 UTC(d-1) + 0.125 UTC(d).

Rain at run time (spec section 10; the run is at 11:00 IST = 05:30 UTC D). The newest Late UTC day is D-2 (Late is
published about 14.5 h after a UTC day ends) and the Early run publishes UTC D-1 about 4.5 h after it ends, so the live
UTC-day series is assembled by `LiveRainView`:
  UTC d <= D-2   Late run (Early mapped to the Late scale where Late is missing, D-3 and D-2 only)
  UTC D-1        Early run, as it is (`early_map.mode: identity`, product `early`) or through the fitted Early->Late
                 quantile mapping (`fitted`, product `early_mapped`)
  UTC D          the 00-03 UTC hours of IMD day D, g, from the first GFS source available: the 00Z cycle 0-3 h
                 accumulation (`gfs_00z_0_3h`), else the 18Z cycle of D-1 f006->f009 (`gfs_18z_6_9h`), else its 12Z
                 cycle f012->f015 (`gfs_12z_12_15h`), else persistence UTC D := UTC D-1 (`persist_d1`, flagged: the run
                 caps confidence at Degraded). g is supplied as the pseudo UTC value 8 g, so that the unchanged training
                 rule gives 0.125 x (8 g) = g and `imerg_features.build_imerg_features` can be fed this series as it is.
Hence IMD day D = 0.875 Early(D-1) + g and IMD day D-1 = 0.875 Late(D-2) + 0.125 Early(D-1). The product behind each
UTC day is available as `LiveRainView.product` and `imd_day_inputs`.

Backtest. With `backtest=True` an input is usable only if it was issued at or before the data cut-off (09:30 IST of
`day`, `schedule.data_cutoff`). The multi-day sources (IMERG, IMD real-time, GHCN) judge each day by its estimated issue
time (end of the day plus the configured latency), so a day that did not exist yet that morning is not read even if
the store holds it now. After a source answers, `fetch_all` also rejects any status whose `issued` is after the cut-off
(or unknown), whatever the source did itself.

Credentials: Earthdata comes from the user's netrc through `aetherguard.http` / `requests`; nothing here reads or
prints a credential value, and error text goes through `urlredact`.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, datetime, time as clock, timedelta, timezone
from pathlib import Path
from typing import Callable, Protocol
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests

from ..config import PROJECT_ROOT, data_root, load_config
from ..hazard.jsonio import jsonable
from ..http import DownloadError, fetch_json
from ..urlredact import redact_text
from .early_map import EarlyLateMap, IdentityMap

UTC = timezone.utc
SOURCE_NAMES = ("imerg_late", "imerg_early", "gfs", "imd_rt", "ghcn")
OPTIONAL_SOURCE_NAMES = ("ecmwf",)       # fetched when configured; never a failed run, never in `failed_sources`
IMD_RT_URL = "https://imdpune.gov.in/cmpg/Realtimedata/Rainfall/rain.php"
IMD_GRID = (129, 135)
IMD_FILE_BYTES = IMD_GRID[0] * IMD_GRID[1] * 4
IMD_MISSING = -999.0
NCEI_ACCESS = "https://www.ncei.noaa.gov/access/services/data/v1"
HEADERS = {"User-Agent": "AetherGuard/0.1 (research prototype)"}


# ------------------------------------------------------------------------------------------------ time rules

def local_tz(cfg: dict) -> ZoneInfo:
    return ZoneInfo(cfg["schedule"]["timezone"])


def resolve_day(text: str, cfg: dict, now: datetime | None = None) -> date:
    """`today` is the IST calendar date of `now`; anything else must be YYYY-MM-DD."""
    if text == "today":
        return (now or datetime.now(UTC)).astimezone(local_tz(cfg)).date()
    return date.fromisoformat(text)


def cutoff_utc(day: date, cfg: dict) -> datetime:
    """The backtest data cut-off of `day` (local `schedule.data_cutoff`) in UTC."""
    return datetime.combine(day, clock.fromisoformat(cfg["schedule"]["data_cutoff"]), tzinfo=local_tz(cfg)).astimezone(UTC)


def utc_day_end(day: date) -> datetime:
    """The instant a UTC day ends (00:00 UTC of the next day)."""
    return datetime.combine(day + timedelta(days=1), clock(0), tzinfo=UTC)


def imd_day_end(day: date) -> datetime:
    """The instant IMD day `day` ends: 08:30 IST = 03:00 UTC of `day`."""
    return datetime.combine(day, clock(3), tzinfo=UTC)


def imd_due_day(day: date, at: datetime, latency_h: float) -> date:
    """The newest IMD day (at most `day`) whose file is due by the instant `at` under a declared publication latency of
    `latency_h` hours after the day ends: the day the second opinion can be expected for. At the 11:00 IST run with the
    24 h latency of the real-time grid this is D-1."""
    due = day
    while imd_day_end(due) + timedelta(hours=latency_h) > at:
        due -= timedelta(days=1)
    return due


def project_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def hours_between(start: datetime, end: datetime) -> float:
    return (end - start).total_seconds() / 3600.0


# --------------------------------------------------------------------------------------------- status and context

@dataclass(frozen=True)
class SourceStatus:
    """What a source delivered for one run.

    `ok` is true only when the source delivered everything the run asked of it. `valid_through` is the end of the
    last interval its data covers and `issued` when that data was published (None when nothing usable arrived);
    `latency_h` is `issued - valid_through` in hours for the observed products (IMERG, IMD, gauges) and `issued -` the
    cycle time for GFS, as measured in reports/phase6_live_sources_probe.md. A status with `ok` false but a `valid_through` carries partial
    data that the run still uses (for example GFS with a gap in one lead day).
    """
    name: str
    ok: bool
    valid_through: datetime | None = None
    issued: datetime | None = None
    latency_h: float | None = None
    error: str | None = None

    @property
    def usable(self) -> bool:
        return self.ok or self.valid_through is not None

    def to_dict(self) -> dict:
        return {"name": self.name, "ok": self.ok,
                "valid_through": None if self.valid_through is None else self.valid_through.isoformat(),
                "issued": None if self.issued is None else self.issued.isoformat(),
                "latency_h": None if self.latency_h is None else round(self.latency_h, 2), "error": self.error}


def failed(name: str, error: str, issued: datetime | None = None) -> SourceStatus:
    return SourceStatus(name=name, ok=False, issued=issued, error=error)


def describe_error(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {redact_text(str(exc))[:300]}".rstrip(": ")


@dataclass(frozen=True)
class FetchContext:
    day: date                  # IST run date = IMD day D
    cfg: dict
    raw_dir: Path              # <live_dir>/<day>/raw
    now: datetime              # UTC
    cutoff: datetime | None    # UTC data cut-off; None outside backtest mode

    @property
    def horizon(self) -> datetime:
        """Inputs issued after this instant cannot exist (or may not be used)."""
        return self.cutoff if self.cutoff is not None else self.now


class Source(Protocol):
    name: str

    def fetch(self, ctx: FetchContext) -> SourceStatus: ...


class DisabledSource:
    def __init__(self, name: str, reason: str) -> None:
        self.name, self.reason = name, reason

    def fetch(self, ctx: FetchContext) -> SourceStatus:
        return failed(self.name, self.reason)

    def load(self, ctx: FetchContext):
        return None


# ------------------------------------------------------------------------------------------------------ IMERG

class ImergSource:
    """One IMERG run (`late` or `early`) kept current in its `ImergStore` and read through `usable`.

    `store` needs `has_date`, `gather` and `update(days)` (the `ImergStore` interface). Late supplies UTC days up to
    D-2 (the newest it has published at run time), Early the day D-1 (and D-3, D-2 where Late is missing); the Early
    run is only usable with its Early->Late `mapping`.
    """

    def __init__(self, run: str, store, *, latency_h: float, window_days: int, mapping=None) -> None:
        if run not in ("late", "early"):
            raise ValueError(f"run must be late or early, got {run!r}")
        self.run, self.store, self.latency_h, self.window_days = run, store, float(latency_h), int(window_days)
        self.mapping = mapping
        self.name = f"imerg_{run}"

    def issue_time(self, utc_day: date) -> datetime:
        return utc_day_end(utc_day) + timedelta(hours=self.latency_h)

    def wanted_days(self, day: date) -> list[date]:
        """UTC days this run is asked for: the Late look-back up to D-2, or D-3..D-1 for Early."""
        if self.run == "late":
            return [day - timedelta(days=k) for k in range(self.window_days, 1, -1)]
        return [day - timedelta(days=k) for k in (3, 2, 1)]

    def required_day(self, day: date) -> date:
        return day - timedelta(days=2 if self.run == "late" else 1)

    def usable(self, utc_day: date, ctx: FetchContext) -> bool:
        if self.run == "early" and self.mapping is None:
            return False
        return self.store.has_date(utc_day) and (ctx.cutoff is None or self.issue_time(utc_day) <= ctx.cutoff)

    def fetch(self, ctx: FetchContext) -> SourceStatus:
        if self.run == "early" and self.mapping is None:
            return failed(self.name, "Early->Late mapping missing (python -m aetherguard.live.early_map fit)")
        wanted = self.wanted_days(ctx.day)
        todo = [u for u in wanted if not self.store.has_date(u) and self.issue_time(u) <= ctx.horizon]
        update_error = None
        if todo:
            try:
                self.store.update(todo)
            except Exception as exc:    # the days already in the store stay usable
                update_error = describe_error(exc)
        have = [u for u in wanted if self.usable(u, ctx)]
        required = self.required_day(ctx.day)
        ok = self.usable(required, ctx)
        if not have:
            return failed(self.name, update_error or f"no {self.run} granule for UTC days {wanted[0]}..{wanted[-1]}")
        newest = max(have)
        valid_through = utc_day_end(newest)
        issued = min(self.issue_time(newest), ctx.now)
        error = None
        if not ok:
            error = (f"no {self.run} granule usable for UTC day {required} yet (published about "
                     f"{self.latency_h:g} h after the day ends); newest usable day {newest}")
            if update_error:
                error += f"; update failed: {update_error}"
        return SourceStatus(self.name, ok, valid_through, issued, hours_between(valid_through, issued), error)


FIRST_HOURS_SCALE = 8.0     # pseudo UTC value of day D: 0.125 x (8 g) = g, the 00-03 UTC GFS accumulation


class LiveRainView:
    """The live IMERG UTC-day series: the `gather` interface of `ImergStore`, assembled as described in the module doc.

    `first_hours` is the (rows, cols) GFS accumulation (mm) over 00-03 UTC of IMD day D on the IMERG grid and
    `first_hours_product` which cycle it came from; without it the tail is persisted from UTC D-1 (`persist_d1`) when
    that day exists. A run passed as None supplies nothing. Days a source does not consider usable (issued after the
    backtest cut-off) are NaN. Nothing after UTC day D is ever supplied.
    """

    def __init__(self, day: date, late: ImergSource | None, early: ImergSource | None, ctx: FetchContext,
                 first_hours: np.ndarray | None = None, first_hours_product: str = "gfs_00z_0_3h") -> None:
        self.day, self.late, self.early, self.ctx = day, late, early, ctx
        self.first_hours, self.first_hours_product = first_hours, first_hours_product

    def _early_label(self) -> str | None:
        return None if self.early is None or self.early.mapping is None else self.early.mapping.label

    def product(self, utc_day: date) -> str:
        """`late`, `early` / `early_mapped`, a GFS tail product, `persist_d1` or `missing`: what supplies UTC day `utc_day`."""
        if utc_day == self.day:
            if self.first_hours is not None:
                return self.first_hours_product
            return PERSIST if self.product(utc_day - timedelta(days=1)) != "missing" else "missing"
        if utc_day > self.day:
            return "missing"
        if utc_day <= self.day - timedelta(days=2) and self.late is not None and self.late.usable(utc_day, self.ctx):
            return "late"
        if (utc_day >= self.day - timedelta(days=3) and self.early is not None
                and self.early.usable(utc_day, self.ctx)):
            return self._early_label()
        return "missing"

    def has_date(self, utc_day: date) -> bool:
        return self.product(utc_day) != "missing"

    def gather(self, rows, cols, first_day: date, length: int) -> np.ndarray:
        rows, cols = np.asarray(rows, dtype=np.int64).ravel(), np.asarray(cols, dtype=np.int64).ravel()
        out = np.full((rows.size, length), np.nan, dtype=np.float32)
        days = [first_day + timedelta(days=k) for k in range(length)]
        products = [self.product(d) for d in days]
        for source, name in ((self.late, "late"), (self.early, self._early_label())):
            keep = np.array([p == name for p in products])
            if source is not None and name is not None and keep.any():
                values = source.store.gather(rows, cols, first_day, length)[:, keep]
                out[:, keep] = values if name == "late" else self.early.mapping.apply(values)
        if self.day in days:
            column = days.index(self.day)
            if products[column] == PERSIST:
                out[:, column] = self.gather(rows, cols, self.day - timedelta(days=1), 1)[:, 0]
            elif self.first_hours is not None:
                out[:, column] = FIRST_HOURS_SCALE * self.first_hours[rows, cols]
        return out

    def imd_day_inputs(self) -> dict:
        """The product behind each of the last two IMD days: the UTC day weighted 0.875 and the one weighted 0.125."""
        out = {}
        for label, lag in (("D", 0), ("D-1", 1)):
            previous = self.product(self.day - timedelta(days=lag + 1))
            current = self.product(self.day - timedelta(days=lag))
            out[label] = {"utc_day_0.875": previous, "utc_day_0.125": current,
                          "product": "missing" if "missing" in (previous, current)
                          else "+".join(dict.fromkeys((previous, current)))}
        return out

    def coverage_gaps(self) -> list[date]:
        """UTC days D-1 and D (the days that are not plain Late data) that nothing supplies."""
        return [d for d in (self.day - timedelta(days=1), self.day) if self.product(d) == "missing"]


# --------------------------------------------------------------------------------------------------------- GFS

@dataclass(frozen=True)
class ForecastDays:
    """GFS IMD-day totals (mm) for D+1..D+3 on the IMERG domain grid; NaN days are in `day_valid` false."""
    days: np.ndarray            # (3, rows, cols) float32
    day_valid: np.ndarray       # (3,) bool
    cycle: datetime
    missing_hours: list[int]

    def lead_array(self, lead: int) -> np.ndarray:
        return self.days[lead - 1]


@dataclass(frozen=True)
class GfsData:
    forecast: ForecastDays | None
    first_hours: np.ndarray | None      # (rows, cols) mm over 00-03 UTC of IMD day D, None when only persistence is left
    first_hours_product: str            # which GFS cycle supplied it, or `persist_d1`


PERSIST = "persist_d1"
# The 00-03 UTC hours of IMD day D, first available source wins: (product, cycle day offset, cycle hour, (start, end)
# forecast hour of the accumulation). Hours 0-3 of the 00Z cycle, 6-9 of the 18Z cycle of D-1 and 12-15 of its 12Z
# cycle are the same 00-03 UTC window.
TAIL_CANDIDATES = (("gfs_00z_0_3h", 0, 0, (0, 3)), ("gfs_18z_6_9h", -1, 18, (6, 9)), ("gfs_12z_12_15h", -1, 12, (12, 15)))


def hour_file_path(root: Path, cycle: datetime, hour: int) -> Path:
    return root / "raw" / "gfs" / "tail" / f"{cycle:%Y%m%d%H}" / f"f{hour:03d}.grib2"


def fetch_hour_file(cycle: datetime, hour: int, cfg: dict, dest: Path, root: Path, backtest: bool) -> None:
    """The cumulative APCP record of forecast `hour` of `cycle`: NOMADS for a live run (the AWS archive when NOMADS no
    longer holds the cycle), the AWS archive for a backtest run (2021 onwards)."""
    from ..ingest import gfs
    from ..manifest import Manifest
    manifest = Manifest(gfs.MANIFEST_PATH, root)
    if not backtest:
        try:
            gfs.fetch_nomads_hour(cycle, hour, cfg, dest, manifest)
            return
        except gfs.DownloadError:
            pass
    gfs.fetch_archive_hour(cycle, hour, cfg, dest, manifest)


def read_accumulation(end_path: Path, end_hour: int, start_path: Path | None, start_hour: int, bbox: dict) -> np.ndarray:
    """Rain (mm) between forecast hours `start_hour` and `end_hour` on the IMERG grid, float32 (rows, cols): the
    difference of the two cumulative 0-H fields (just the end field when `start_path` is None); never negative."""
    from ..ingest import gfs

    def cumulative(path: Path, hour: int):
        lats, lons, values, start, end = gfs.decode_apcp(path.read_bytes())
        if (start, end) != (0, hour):
            raise gfs.GribDecodeError(f"{path.name}: the message covers hours {start}-{end}, expected 0-{hour}")
        return gfs.crop_to_bbox(lats, lons, values, bbox)
    lats, lons, field = cumulative(end_path, end_hour)
    if start_path is not None:
        field = field - cumulative(start_path, start_hour)[2]
    return np.maximum(gfs.regrid_to_imerg(field, lats, lons), 0.0)


class GfsSource:
    """The latest complete GFS cycle (never later than 03:00 UTC of the run day) as IMD-day totals for D+1..D+3, and
    the rain over 00-03 UTC of IMD day D from the first of `TAIL_CANDIDATES` that was issued before the cut-off / now
    and can be fetched; if none can, the tail is left to persistence (`persist_d1`, applied by `LiveRainView`).

    Live runs fetch from NOMADS (`ingest.gfs.fetch_live`); backtest runs read the archive day file
    (`gfs_imdday_<day>.npz`), fetching it from the AWS archive when it is not there (2021 onwards). A NOMADS answer of
    403 means the cycle is not published yet, and the previous cycle is used for the forecast days.
    """

    name = "gfs"

    def __init__(self, live_cfg: dict, *, latency_h: float, first_hours_latency_h: float, root: Path | None = None,
                 fetch_live: Callable | None = None, fetch_archive: Callable | None = None,
                 fetch_hour: Callable | None = None) -> None:
        self.live_cfg, self.latency_h, self.first_hours_latency_h = live_cfg, float(latency_h), float(first_hours_latency_h)
        self.root = root
        self._fetch_live, self._fetch_archive = fetch_live, fetch_archive
        self._fetch_hour = fetch_hour or fetch_hour_file
        self.first_hours: np.ndarray | None = None
        self.first_hours_product = PERSIST
        self._tail_issued: datetime | None = None
        self._tail_cycle: datetime | None = None

    def _root(self) -> Path:
        return Path(self.root) if self.root is not None else data_root()

    def day_file(self, day: date) -> Path:
        from ..ingest import gfs
        return gfs.day_file_path(self._root(), day)

    def _fetch_forecast(self, ctx: FetchContext) -> str | None:
        from ..ingest import gfs
        try:
            if ctx.cutoff is None:
                (self._fetch_live or gfs.fetch_live)(ctx.day, self.live_cfg, now_utc=ctx.now, root=self._root())
            elif not self.day_file(ctx.day).is_file():
                (self._fetch_archive or gfs.fetch_archive)([ctx.day], self.live_cfg, root=self._root())
        except Exception as exc:
            return describe_error(exc)
        return None

    def _load_tail(self, ctx: FetchContext) -> list[str]:
        """Find the 00-03 UTC accumulation; returns what went wrong with the candidates tried before the one used."""
        self.first_hours, self.first_hours_product, self._tail_issued, self._tail_cycle = None, PERSIST, None, None
        problems = []
        for product, offset, hour, (start, end) in TAIL_CANDIDATES:
            cycle = datetime.combine(ctx.day + timedelta(days=offset), clock(hour), tzinfo=UTC)
            issued = cycle + timedelta(hours=self.first_hours_latency_h)
            if issued > ctx.horizon:
                problems.append(f"GFS {cycle:%Y-%m-%d %HZ} cycle not published yet ({issued:%H:%M} UTC)")
                continue
            try:
                paths = {h: hour_file_path(self._root(), cycle, h) for h in (start, end) if h > 0}
                for h, path in paths.items():
                    if not path.is_file():
                        self._fetch_hour(cycle, h, self.live_cfg, path, self._root(), ctx.cutoff is not None)
                self.first_hours = read_accumulation(paths[end], end, paths.get(start), start, self.live_cfg["domain_bbox"])
            except Exception as exc:
                problems.append(f"GFS {cycle:%Y-%m-%d %HZ} cycle hours {start}-{end}: {describe_error(exc)}")
                continue
            self.first_hours_product, self._tail_issued, self._tail_cycle = product, issued, cycle
            break
        return problems

    def fetch(self, ctx: FetchContext) -> SourceStatus:
        forecast_error = self._fetch_forecast(ctx)
        forecast = self._read(self.day_file(ctx.day))
        if forecast is not None and not forecast.day_valid.any():
            forecast_error = forecast_error or (f"GFS cycle {forecast.cycle:%Y-%m-%d %HZ} has no valid forecast day "
                                                f"(missing hours {forecast.missing_hours})")
            forecast = None
        tail_problems = self._load_tail(ctx)
        problems = []
        if forecast is None:
            problems.append(forecast_error or f"no GFS forecast file {self.day_file(ctx.day).name}")
        elif not forecast.day_valid.all():
            lost = [f"D+{lead}" for lead, ok in zip((1, 2, 3), forecast.day_valid) if not ok]
            problems.append(f"forecast days {', '.join(lost)} are missing (forecast hours {forecast.missing_hours} "
                            "not available)")
        elif forecast_error:
            problems.append(f"newest cycle not fetched ({forecast_error}); using the {forecast.cycle:%Y-%m-%d %HZ} cycle")
        persisted = self.first_hours is None
        if persisted:
            problems.append("00-03 UTC rain of IMD day D persisted from UTC D-1 (" + "; ".join(tail_problems) + ")")
        elif self.first_hours_product != TAIL_CANDIDATES[0][0]:
            problems.append(f"00-03 UTC rain of IMD day D from {self.first_hours_product} ({'; '.join(tail_problems)})")
        if forecast is None and persisted:
            return failed(self.name, "; ".join(problems))
        issued = max(([forecast.cycle + timedelta(hours=self.latency_h)] if forecast is not None else [])
                     + ([self._tail_issued] if self._tail_issued is not None else []))
        issued = issued if ctx.cutoff is not None else min(issued, ctx.now)
        last_lead = max([lead for lead, ok in zip((1, 2, 3), forecast.day_valid) if ok], default=0) if forecast else 0
        valid_through = imd_day_end(ctx.day + timedelta(days=last_lead))
        ok = forecast is not None and bool(forecast.day_valid.all()) and not persisted
        # GFS latency is issued minus the cycle time (probe definition); valid_through is the end of the forecast
        cycle = forecast.cycle if forecast is not None else self._tail_cycle
        return SourceStatus(self.name, ok, valid_through, issued, hours_between(cycle, issued), "; ".join(problems) or None)

    @staticmethod
    def _read(path: Path) -> ForecastDays | None:
        if not path.is_file():
            return None
        with np.load(path, allow_pickle=False) as data:
            return ForecastDays(days=np.asarray(data["days"], dtype=np.float32),
                                day_valid=np.asarray(data["day_valid"], dtype=bool),
                                cycle=datetime.fromisoformat(str(data["cycle"])).astimezone(UTC),
                                missing_hours=[int(h) for h in data["missing_hours"]])

    def load(self, ctx: FetchContext) -> GfsData:
        forecast = self._read(self.day_file(ctx.day))
        if forecast is not None and not forecast.day_valid.any():
            forecast = None
        return GfsData(forecast=forecast, first_hours=self.first_hours, first_hours_product=self.first_hours_product)


# ------------------------------------------------------------------------------------------------------- ECMWF

class EcmwfSource:
    """ECMWF IFS open-data rain (HRES and the 51-member ensemble) as IMD-day totals for D+1..D+3 (`ingest.ecmwf`).

    A live run fetches the newest published cycle of each product (the 18Z or 12Z run of D-1 at 11:00 IST, the 00Z run of D
    from about 13:30 IST); a backtest run reads the archive day file (the 18Z run of D-1), fetching it from the public archive
    when it is not there. The source is optional: the daily run falls back to GFS for any lead ECMWF cannot supply, so its
    failure is a status, not a failed run.
    """

    name = "ecmwf"

    def __init__(self, live_cfg: dict, *, latency_h: float, root: Path | None = None, fetch_live: Callable | None = None,
                 fetch_archive: Callable | None = None) -> None:
        self.live_cfg, self.latency_h, self.root = live_cfg, float(latency_h), root
        self._fetch_live, self._fetch_archive = fetch_live, fetch_archive

    def _root(self) -> Path:
        return Path(self.root) if self.root is not None else data_root()

    def day_file(self, day: date) -> Path:
        from ..ingest import ecmwf
        return ecmwf.day_file_path(self._root(), day)

    def fetch(self, ctx: FetchContext) -> SourceStatus:
        from ..ingest import ecmwf
        error = None
        try:
            if ctx.cutoff is None:
                (self._fetch_live or ecmwf.fetch_live)(ctx.day, self.live_cfg, now_utc=ctx.now, root=self._root())
            elif not self.day_file(ctx.day).is_file():
                (self._fetch_archive or ecmwf.fetch_archive)([ctx.day], self.live_cfg, root=self._root())
        except Exception as exc:
            error = describe_error(exc)
        forecast = ecmwf.load_day(self.day_file(ctx.day))
        if forecast is None or not (forecast.hres_valid.any() or forecast.ens_valid.any()):
            return failed(self.name, error or f"no ECMWF forecast file {self.day_file(ctx.day).name}")
        problems = [] if error is None else [f"newest cycle not fetched ({error})"]
        for label, valid in (("HRES", forecast.hres_valid), ("ensemble", forecast.ens_valid)):
            if not valid.all():
                lost = ", ".join(f"D+{k}" for k, ok in zip((1, 2, 3), valid) if not ok)
                problems.append(f"{label} {'has no data' if not valid.any() else 'is missing ' + lost}")
        cycles = [c for c in (forecast.hres_cycle, forecast.ens_cycle) if c is not None]
        issued = max(cycles) + timedelta(hours=self.latency_h)
        issued = issued if ctx.cutoff is not None else min(issued, ctx.now)
        last_lead = max(k for valid in (forecast.hres_valid, forecast.ens_valid) for k, ok in zip((1, 2, 3), valid) if ok)
        ok = bool(forecast.hres_valid.all() and forecast.ens_valid.all())
        return SourceStatus(self.name, ok, imd_day_end(ctx.day + timedelta(days=last_lead)), issued,
                            hours_between(max(cycles), issued), "; ".join(problems) or None)

    def load(self, ctx: FetchContext):
        from ..ingest import ecmwf
        return ecmwf.load_day(self.day_file(ctx.day))


# --------------------------------------------------------------------------------------------- IMD real-time

def parse_imd_grid(data: bytes) -> np.ndarray:
    """One IMD real-time file (little-endian float32, 129 x 135, -999 = missing) as float32 with NaN for missing."""
    if len(data) != IMD_FILE_BYTES:
        raise ValueError(f"IMD file has {len(data)} bytes, expected {IMD_FILE_BYTES}")
    grid = np.frombuffer(data, dtype="<f4").reshape(IMD_GRID).astype(np.float32)
    grid[(grid == IMD_MISSING) | ~np.isfinite(grid) | (grid < 0)] = np.nan
    return grid


def post_imd_day(day: date, timeout: float) -> bytes | None:
    """The real-time rainfall file of IMD day `day`, or None when it is not published yet (empty answer)."""
    response = requests.post(IMD_RT_URL, data={"rain": f"{day:%d%m%Y}"}, headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    return response.content or None


class ImdRealtimeSource:
    """IMD real-time gridded rain (0.25 degree, India) for IMD days D-n+1..D: the alert engine's second opinion.

    The server is slow and flaky, so each request has a timeout, a failed transport stops further requests of the
    run, and every file received is cached under `raw/imd_rt/` (days are looked up in the raw folders of the
    neighbouring runs first, so a daily run asks for one new file).

    The file of day d is published about `latency_h` hours after d ends, so at the 11:00 IST run day D is normally not
    there yet. The source is on time (`ok`) when it delivered the newest day due by the run under that declared latency
    (`imd_due_day`, D-1 at 11:00 IST); day D is requested too and used when it is already there. Later than that it is
    reported late, with the day that was due.
    """

    name = "imd_rt"

    def __init__(self, *, days: int, timeout_s: float, attempts: int, latency_h: float,
                 post: Callable[[date, float], bytes | None] | None = None) -> None:
        self.n_days, self.timeout_s, self.attempts, self.latency_h = int(days), float(timeout_s), int(attempts), float(latency_h)
        self._post = post or post_imd_day
        self.grids: dict[date, np.ndarray] = {}

    def issue_time(self, day: date) -> datetime:
        return imd_day_end(day) + timedelta(hours=self.latency_h)

    def _cached(self, day: date, ctx: FetchContext) -> Path | None:
        live_dir = ctx.raw_dir.parent.parent
        candidates = [ctx.raw_dir / "imd_rt" / f"{day}.grd"] + [
            live_dir / (day + timedelta(days=k)).isoformat() / "raw" / "imd_rt" / f"{day}.grd" for k in (0, 1)]
        return next((p for p in candidates if p.is_file() and p.stat().st_size == IMD_FILE_BYTES), None)

    def _get(self, day: date, ctx: FetchContext) -> np.ndarray | None:
        cached = self._cached(day, ctx)
        if cached is not None:
            return parse_imd_grid(cached.read_bytes())
        data = None
        for attempt in range(self.attempts):
            try:
                data = self._post(day, self.timeout_s)
                break
            except requests.RequestException:
                if attempt == self.attempts - 1:
                    raise
        if data is None:
            return None
        grid = parse_imd_grid(data)
        dest = ctx.raw_dir / "imd_rt" / f"{day}.grd"
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".part")
        part.write_bytes(data)
        os.replace(part, dest)
        return grid

    def fetch(self, ctx: FetchContext) -> SourceStatus:
        self.grids = {}
        days = [ctx.day - timedelta(days=k) for k in range(self.n_days - 1, -1, -1)]
        problem = None
        for day in days:
            if ctx.cutoff is not None and self.issue_time(day) > ctx.cutoff:
                continue
            try:
                grid = self._get(day, ctx)
            except (requests.RequestException, ValueError, OSError) as exc:
                problem = describe_error(exc)
                break
            if grid is not None:
                self.grids[day] = grid
        if not self.grids:
            return failed(self.name, problem or f"IMD real-time has no file for IMD days {days[0]}..{days[-1]} "
                                                "(not published yet)")
        newest = max(self.grids)
        valid_through = imd_day_end(newest)
        issued = min(self.issue_time(newest), ctx.now)
        due = imd_due_day(ctx.day, ctx.horizon, self.latency_h)
        ok = newest >= due            # inside its declared latency a missing day D is not a delay
        error = None if ok else (problem or f"IMD real-time later than its declared latency of {self.latency_h:g} h: no "
                                            f"file for IMD day {due} (due {self.issue_time(due).isoformat()}); newest {newest}")
        return SourceStatus(self.name, ok, valid_through, issued, hours_between(valid_through, issued), error)

    def load(self, ctx: FetchContext) -> dict[date, np.ndarray]:
        return dict(self.grids)


# ------------------------------------------------------------------------------------------------------- GHCN

@dataclass(frozen=True)
class GhcnData:
    values: pd.DataFrame        # date x station, mm/day, NaN = no value; daily index ending on D
    meta: pd.DataFrame          # station metadata (id, lat, lon, ...), one row per column of `values`


def ghcn_rows_to_frame(rows: list[dict], index: pd.DatetimeIndex, stations: list[str]) -> pd.DataFrame:
    """NCEI access-service JSON rows (DATE, STATION, PRCP in mm) as a date x station frame; rows without PRCP skipped."""
    data = {}
    for row in rows:
        text = str(row.get("PRCP", "")).strip()
        if text:
            data[(pd.Timestamp(row["DATE"]), row["STATION"])] = float(text)
    frame = pd.DataFrame(np.nan, index=index, columns=stations, dtype=np.float32)
    for (stamp, station), value in data.items():
        if stamp in frame.index and station in frame.columns:
            frame.at[stamp, station] = value
    return frame


class GhcnSource:
    """GHCN-Daily recent precipitation of the project's gauge stations (NCEI access-data-service), last N days.

    Values arrive 5 to 13 days late (probe), so the newest days are mostly empty; they are NaN, never zero.
    """

    name = "ghcn"

    def __init__(self, *, look_back_days: int, timeout_s: float, per_request: int, latency_h: float,
                 expected_lag_days: int, stations: Callable[[], pd.DataFrame] | None = None,
                 fetch: Callable[..., list] | None = None) -> None:
        self.look_back, self.timeout_s, self.per_request = int(look_back_days), float(timeout_s), int(per_request)
        self.latency_h, self.expected_lag_days = float(latency_h), int(expected_lag_days)
        self._stations = stations
        self._fetch = fetch or (lambda params: fetch_json(NCEI_ACCESS, params=params, retries=2, timeout=self.timeout_s))
        self.data: GhcnData | None = None

    def _meta(self) -> pd.DataFrame:
        if self._stations is not None:
            return self._stations()
        from ..integrity.stations import select_station_meta
        return select_station_meta()

    def fetch(self, ctx: FetchContext) -> SourceStatus:
        self.data = None
        meta = self._meta().reset_index(drop=True)
        ids = list(meta["id"])
        index = pd.date_range(pd.Timestamp(ctx.day) - pd.Timedelta(days=self.look_back - 1), pd.Timestamp(ctx.day), freq="D")
        rows, failures, last_error = [], 0, ""
        for lo in range(0, len(ids), self.per_request):
            params = {"dataset": "daily-summaries", "stations": ",".join(ids[lo:lo + self.per_request]),
                      "dataTypes": "PRCP", "startDate": index[0].date().isoformat(), "endDate": index[-1].date().isoformat(),
                      "format": "json", "includeAttributes": "true", "units": "metric"}
            try:
                rows.extend(self._fetch(params))
            except Exception as exc:
                failures += 1
                last_error = describe_error(exc)
        if ctx.cutoff is not None:
            rows = [r for r in rows if utc_day_end(date.fromisoformat(r["DATE"][:10])) + timedelta(hours=self.latency_h)
                    <= ctx.cutoff]
        values = ghcn_rows_to_frame(rows, index, ids)
        observed = values.dropna(how="all")
        if observed.empty:
            return failed(self.name, last_error if failures else "GHCN-Daily returned no PRCP value in the window")
        raw = ctx.raw_dir / "ghcn_prcp.csv"
        raw.parent.mkdir(parents=True, exist_ok=True)
        values.rename_axis("date").reset_index().to_csv(raw, index=False)
        self.data = GhcnData(values=values, meta=meta)
        newest = observed.index.max().date()
        valid_through = utc_day_end(newest)
        issued = min(valid_through + timedelta(hours=self.latency_h), ctx.now)
        error = None
        if failures:
            error = f"{failures} of {-(-len(ids) // self.per_request)} requests failed ({last_error}); partial gauge data"
        ok = not failures
        return SourceStatus(self.name, ok, valid_through, issued, hours_between(valid_through, issued), error)

    def load(self, ctx: FetchContext) -> GhcnData | None:
        return self.data


# ----------------------------------------------------------------------------------------------------- assembly

def early_mapping(cfg: dict):
    """The Early-run treatment of `early_map.mode`: `identity` (as it is) or `fitted` (the quantile mapping in
    `early_map.file`; None when the file is missing, which makes the Early run unusable)."""
    mode = cfg["early_map"]["mode"]
    if mode == "identity":
        return IdentityMap()
    if mode == "fitted":
        path = project_path(cfg["early_map"]["file"])
        return EarlyLateMap.load(path) if path.is_file() else None
    raise ValueError(f"early_map.mode must be identity or fitted, got {mode!r}")


def default_sources(cfg: dict) -> dict[str, Source]:
    """The real sources configured by `cfg` (configs/live_run.yaml); disabled ones fail with their reason."""
    from ..ingest.imerg import ImergStore
    live = load_config("live")
    imerg = cfg["imerg"]
    processed = project_path(imerg["processed_dir"])
    latency = imerg["latency_h"]
    early_map = early_mapping(cfg)
    sources: dict[str, Source] = {
        "imerg_late": ImergSource("late", ImergStore(processed, "late"), latency_h=latency["late"],
                                  window_days=imerg["late_window_days"]),
        "imerg_early": ImergSource("early", ImergStore(processed, "early"), latency_h=latency["early"],
                                   window_days=imerg["late_window_days"],
                                   mapping=early_map)}
    off = "disabled in configs/live_run.yaml"
    sources["gfs"] = (GfsSource(live, latency_h=cfg["gfs"]["latency_h"],
                                first_hours_latency_h=cfg["gfs"]["first_hours_latency_h"]) if cfg["gfs"]["enabled"]
                      else DisabledSource("gfs", off))
    if cfg.get("ecmwf", {}).get("enabled"):
        sources["ecmwf"] = EcmwfSource(live, latency_h=cfg["ecmwf"]["latency_h"])
    imd = cfg["imd_rt"]
    sources["imd_rt"] = (ImdRealtimeSource(days=imd["days"], timeout_s=imd["timeout_s"], attempts=imd["attempts"],
                                           latency_h=imd["latency_h"]) if imd["enabled"] else DisabledSource("imd_rt", off))
    ghcn = cfg["ghcn"]
    sources["ghcn"] = (GhcnSource(look_back_days=ghcn["look_back_days"], timeout_s=ghcn["request_timeout_s"],
                                  per_request=ghcn["stations_per_request"], latency_h=ghcn["latency_h"],
                                  expected_lag_days=ghcn["expected_lag_days"]) if ghcn["enabled"]
                      else DisabledSource("ghcn", off))
    return sources


def fetch_one(source: Source, name: str, ctx: FetchContext) -> SourceStatus:
    try:
        status = source.fetch(ctx)
    except Exception as exc:
        return failed(name, describe_error(exc))
    if not isinstance(status, SourceStatus) or status.name != name:
        return failed(name, f"source returned an unusable status ({type(status).__name__})")
    if ctx.cutoff is not None and status.usable:
        if status.issued is None:
            return failed(name, "issue time unknown: cannot show the input existed at the backtest cut-off")
        if status.issued > ctx.cutoff:
            return failed(name, f"input issued {status.issued:%Y-%m-%d %H:%M} UTC, after the backtest cut-off "
                                f"{ctx.cutoff:%Y-%m-%d %H:%M} UTC", issued=status.issued)
    return status


def make_context(day: date, cfg: dict, now: datetime | None, backtest: bool, raw_dir: Path | None = None) -> FetchContext:
    return FetchContext(day=day, cfg=cfg, raw_dir=Path(raw_dir) if raw_dir is not None
                        else project_path(cfg["live_dir"]) / day.isoformat() / "raw",
                        now=(now or datetime.now(UTC)).astimezone(UTC), cutoff=cutoff_utc(day, cfg) if backtest else None)


def fetch_all(day: date, cfg: dict, *, sources: dict[str, Source] | None = None, now: datetime | None = None,
              backtest: bool = False, raw_dir: Path | None = None) -> dict[str, SourceStatus]:
    """Status of every source for the run of IST date `day`; never raises for a source failure.

    `sources` maps a source name to an object with `fetch(ctx)` (default: the real sources of `cfg`); `now` is the
    UTC time of the run; `backtest` enforces the data cut-off.
    """
    ctx = make_context(day, cfg, now, backtest, raw_dir)
    sources = sources if sources is not None else default_sources(cfg)
    statuses = {}
    for name in SOURCE_NAMES:
        source = sources.get(name)
        statuses[name] = (failed(name, "source not configured") if source is None else fetch_one(source, name, ctx))
    for name in OPTIONAL_SOURCE_NAMES:
        if sources.get(name) is not None:
            statuses[name] = fetch_one(sources[name], name, ctx)
    return statuses


# ------------------------------------------------------------------------------------------------------ freshness

def expected_valid_through(name: str, day: date, cfg: dict) -> datetime:
    """Where a source's data should end on the run morning of `day` for the source to count as on time. For the IMD
    real-time grid that is the newest IMD day due by the scheduled run time under its declared latency (`imd_due_day`):
    a day still inside its latency is not late."""
    return {"imerg_late": lambda: utc_day_end(day - timedelta(days=2)),
            "imerg_early": lambda: utc_day_end(day - timedelta(days=1)),
            "gfs": lambda: imd_day_end(day + timedelta(days=3)),
            "ecmwf": lambda: imd_day_end(day + timedelta(days=3)),
            "imd_rt": lambda: imd_day_end(imd_due_day(day, cutoff_utc(day, cfg), float(cfg["imd_rt"]["latency_h"]))),
            "ghcn": lambda: utc_day_end(day - timedelta(days=int(cfg["ghcn"]["expected_lag_days"])))}[name]()


def source_state(status: SourceStatus, day: date, cfg: dict) -> str:
    """`ok`, `late` (usable but ending before the expected time, or partial) or `failed` (nothing usable)."""
    if not status.usable:
        return "failed"
    if not status.ok or status.valid_through < expected_valid_through(status.name, day, cfg):
        return "late"
    return "ok"


def freshness_record(day: date, cfg: dict, statuses: dict[str, SourceStatus], now: datetime, backtest: bool,
                     imd_day_inputs: dict | None = None) -> dict:
    """The content of freshness.json (read by serve.dash_api `/api/sources/status`)."""
    cutoff = cutoff_utc(day, cfg) if backtest else None
    return {"available": True, "date": day.isoformat(), "generated_utc": now.astimezone(UTC).isoformat(timespec="seconds"),
            "backtest": backtest, "data_cutoff_utc": None if cutoff is None else cutoff.isoformat(),
            "imd_day_inputs": imd_day_inputs,
            "sources": {name: {**status.to_dict(), "state": source_state(status, day, cfg),
                               "expected_valid_through": expected_valid_through(name, day, cfg).isoformat()}
                        for name, status in statuses.items()}}


def write_json_atomic(path: Path, payload) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    part.write_text(json.dumps(jsonable(payload), indent=2, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(part, path)
