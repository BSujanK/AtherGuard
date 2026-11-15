"""FM-12 SYNOP decoding for rain gauges: raw bulletins -> precipitation reports -> IMD-day totals.

Why: GHCN-Daily, the engine's only gauge source, arrives days late, and since August 2025 its values for the project's
stations come from NOAA's Synoptic Summary of the Day v2 (source flag 2), which for India is almost entirely 0.0 with
measurement flag H ("could not be calculated, precipitation noted": reports/phase8_gauge_sources_probe.md). The
project's 140 GHCN stations are WMO synoptic stations whose GHCN values were, up to 2025, GSOD summaries of their own
SYNOP reports (source flag S). The SYNOP reports themselves reach the WMO GTS within about an hour, so decoding them
gives the same sensors' readings on the run day.

Only the groups that carry precipitation are decoded (spec docs/superpowers/specs/2026-11-14-aetherguard-same-day-gauges.md):
* section 0  `AAXX YYGGi_w` (day, hour) and the station's `IIiii`;
* section 1  `i_R i_x h VV` (precipitation indicator i_R) and `6RRRt_R`;
* section 3  `6RRRt_R` and the regional 24-hour group `7R24R24R24R24` (tenths of mm, 9999 = trace).
RRR (WMO code table 3590): 001-988 mm, 989 = 989 mm or more, 990 = trace, 991-999 = 0.1-0.9 mm, 000 = 0 mm.
t_R (code table 4019): 1 = 6 h, 2 = 12 h, 3 = 18 h, 4 = 24 h, 5 = 1 h, 6 = 2 h, 7 = 3 h, 8 = 9 h, 9 = 15 h; 0 and `/`
are regional ("period as in regional practice"): they are kept as `period_h = None` and resolved only by the explicit
`regional_periods` rule of the caller (never guessed here).
i_R: 0/1/2 groups present, 3 = groups omitted because the amount is zero, 4 = not observed / not available.
A trace is 0.0 mm (as in GHCN-Daily, flag T); a missing or unreadable group is None, never zero.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
HEADING = re.compile(r"^([A-Z]{4}\d{2}) ([A-Z]{4}) (\d{6})(?: ([A-Z]{3}))?\s*$")
PERIOD_TR = {"1": 6, "2": 12, "3": 18, "4": 24, "5": 1, "6": 2, "7": 3, "8": 9, "9": 15}
TRACE = "trace"


def rrr_mm(code: str) -> float | None:
    """RRR (code table 3590) in mm; trace = 0.0; None when unreadable."""
    if not re.fullmatch(r"\d{3}", code):
        return None
    value = int(code)
    if value <= 989:
        return float(value)
    if value == 990:
        return 0.0
    return round((value - 990) / 10.0, 1)


def r24_mm(code: str) -> float | None:
    """R24R24R24R24 (tenths of mm, 9999 = trace) in mm; None when unreadable."""
    if not re.fullmatch(r"\d{4}", code):
        return None
    value = int(code)
    return 0.0 if value == 9999 else value / 10.0


@dataclass(frozen=True)
class Accumulation:
    """One precipitation group: `amount_mm` over the `period_h` hours ending at the report time (None: regional `/`
    or `0` period, resolved by the caller), from `group` ('6' section 1, '6s3' section 3, '7s3' the 24-h group)."""
    amount_mm: float | None
    period_h: int | None
    group: str
    trace: bool = False


@dataclass(frozen=True)
class Report:
    station: str                     # WMO IIiii
    time: datetime                   # nominal observation time (UTC)
    ir: str                          # precipitation indicator i_R ('/' if unreadable)
    accumulations: tuple[Accumulation, ...] = field(default_factory=tuple)
    bulletin: str = ""               # heading TTAAii CCCC YYGGgg [BBB]
    nil: bool = False


def _accumulation_6(group: str, where: str) -> Accumulation:
    amount = rrr_mm(group[1:4])
    return Accumulation(amount, PERIOD_TR.get(group[4]), where, trace=group[1:4] == "990")


def parse_report(text: str, year: int, month: int, day: int, hour: int, bulletin: str = "") -> Report | None:
    """Decode one FM-12 land-station report (the text between the AAXX line and its '=') of nominal time
    year-month-day hour UTC. None when the text does not start with a station index."""
    tokens = text.replace("=", " ").split()
    if not tokens or not re.fullmatch(r"\d{5}", tokens[0]):
        return None
    station = tokens[0]
    time = datetime(year, month, day, hour, tzinfo=UTC)
    if len(tokens) > 1 and tokens[1].startswith("NIL"):
        return Report(station, time, "/", (), bulletin, nil=True)
    ir = tokens[1][0] if len(tokens) > 1 and tokens[1] else "/"
    accs: list[Accumulation] = []
    section = 1
    # section 1 groups start after IIiii iRixhVV Nddff (and the optional 00fff)
    position = 3
    if len(tokens) > position and tokens[2][3:5] == "99" and tokens[position].startswith("00"):
        position += 1
    for token in tokens[position:]:
        if token == "333":
            section = 3
            continue
        if token in ("222", "444", "555") or re.fullmatch(r"222\d\d", token):
            section = 0          # sections we do not read
            continue
        if len(token) != 5 or section == 0:
            continue
        if section == 1 and token[0] == "6":
            accs.append(_accumulation_6(token, "6"))
        elif section == 3 and token[0] == "6":
            accs.append(_accumulation_6(token, "6s3"))
        elif section == 3 and token[0] == "7":
            accs.append(Accumulation(r24_mm(token[1:]), 24, "7s3", trace=token[1:] == "9999"))
    return Report(station, time, ir, tuple(accs), bulletin)


def _month_of(day: int, reference: datetime) -> tuple[int, int]:
    """(year, month) of day-of-month `day` nearest before or at `reference` (bulletins carry only the day)."""
    year, month = reference.year, reference.month
    if day > reference.day + 1:
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return year, month


def parse_bulletins(text: str, reference: datetime, block_prefixes: tuple[str, ...] | None = None) -> list[Report]:
    """Every FM-12 report in a file of WMO bulletins (the NWS SYNOP ring files). `reference` (UTC, the file's time)
    supplies the year and month the bulletins omit. `block_prefixes` keeps only stations whose index starts with one
    of them (for example ("42", "43", "44"))."""
    out: list[Report] = []
    heading, aaxx = "", None
    buffer: list[str] = []

    def flush() -> None:
        if aaxx is None or not buffer:
            buffer.clear()
            return
        body = " ".join(buffer)
        buffer.clear()
        year, month, day, hour = aaxx
        report = parse_report(body, year, month, day, hour, heading)
        if report is not None and (block_prefixes is None or report.station.startswith(block_prefixes)):
            out.append(report)

    for raw in text.replace("\r", "").split("\n"):
        line = re.sub(r"#+\d*#+", "", raw.replace("\x01", "").replace("\x03", "")).strip()
        if not line:
            continue
        match = HEADING.match(line)
        if match:
            flush()
            heading, aaxx = line, None
            continue
        if line.startswith(("AAXX", "BBXX", "OOXX")):
            flush()
            parts = line.split()
            aaxx = None
            if parts[0] == "AAXX" and len(parts) > 1 and re.fullmatch(r"\d{5}", parts[1]):
                day, hour = int(parts[1][:2]), int(parts[1][2:4])
                if 1 <= day <= 31 and hour <= 23:
                    year, month = _month_of(day, reference)
                    try:
                        datetime(year, month, day)
                        aaxx = (year, month, day, hour)
                    except ValueError:
                        aaxx = None
            rest = " ".join(parts[2:])
            if aaxx is not None and rest:
                buffer.append(rest)
                if "=" in rest:
                    flush()
            continue
        if aaxx is None:
            continue
        pieces = line.split("=")
        for i, piece in enumerate(pieces):
            if piece.strip():
                buffer.append(piece.strip())
            if i < len(pieces) - 1:
                flush()
    flush()
    return out


def parse_ogimet_line(line: str) -> Report | None:
    """One line of OGIMET getsynop output: `IIiii,YYYY,MM,DD,HH,mm,AAXX YYGGi IIiii ...=`."""
    parts = line.strip().split(",", 6)
    if len(parts) < 7 or not parts[0].isdigit():
        return None
    year, month, day, hour = (int(p) for p in parts[1:5])
    body = parts[6]
    if body.startswith("AAXX"):
        body = body.split(None, 2)[2] if len(body.split(None, 2)) > 2 else ""
    return parse_report(body, year, month, day, hour, "ogimet")


def imd_day_window(day) -> tuple[datetime, datetime]:
    """IMD day `day` = 03:00 UTC of day-1 to 03:00 UTC of day."""
    end = datetime(day.year, day.month, day.day, 3, tzinfo=UTC)
    return end - timedelta(hours=24), end


# ------------------------------------------------------------------------------------------------ IMD-day totals

SINCE_03UTC_BLOCKS = ("42", "43")   # India: a group with a regional period ('/' or '0') holds the amount since 03 UTC
IMD_DAY_END_HOUR = 3


def resolve_period(report: Report, acc: Accumulation, since_03utc_blocks=SINCE_03UTC_BLOCKS) -> int | None:
    """Hours the group covers: its t_R period, or for a regional period at a station of `since_03utc_blocks` the hours
    since the latest 03 UTC (03 UTC itself: 24). None when the period cannot be known."""
    if acc.period_h is not None:
        return acc.period_h
    if report.station.startswith(tuple(since_03utc_blocks)):
        hours = (report.time.hour - IMD_DAY_END_HOUR) % 24
        return 24 if hours == 0 else hours
    return None


def _priority(report: Report) -> tuple[int, str]:
    """Corrections (BBB = CCx) outrank originals and retransmissions (RRx); a later letter outranks an earlier one."""
    parts = report.bulletin.split()
    bbb = parts[3] if len(parts) > 3 else ""
    return (1, bbb) if bbb.startswith("CC") else (0, "")


def latest_versions(reports) -> dict[tuple[str, datetime], list[Report]]:
    """(station, time) -> the reports of the highest priority version (several when retransmitted)."""
    best: dict[tuple[str, datetime], list[Report]] = {}
    for r in reports:
        if r.nil:
            continue
        key = (r.station, r.time)
        if key not in best or _priority(r) > _priority(best[key][0]):
            best[key] = [r]
        elif _priority(r) == _priority(best[key][0]):
            best[key].append(r)
    return best


def _amount_24h(report: Report, since_03utc_blocks) -> tuple[float | None, str]:
    amounts = {acc.amount_mm for acc in report.accumulations
               if acc.amount_mm is not None and resolve_period(report, acc, since_03utc_blocks) == 24}
    if len(amounts) == 1:
        return amounts.pop(), "24h_group"
    if len(amounts) > 1:
        return None, "conflicting_24h_groups"
    if report.ir == "3":
        return 0.0, "ir3_zero"
    return None, "no_24h_amount" if report.ir != "4" else "ir4_not_observed"


def _partition(intervals: dict[tuple[datetime, datetime], float], start: datetime, end: datetime) -> float | None:
    """Sum over a chain of non-overlapping intervals that covers [start, end] exactly, with the fewest pieces
    (None when no chain exists): accumulations never overlap, so nothing is counted twice."""
    best: dict[datetime, tuple[int, float]] = {start: (0, 0.0)}
    for point in sorted({s for s, _ in intervals} | {e for _, e in intervals} | {start, end}):
        if point not in best:
            continue
        pieces, total = best[point]
        for (s, e), amount in intervals.items():
            if s == point and e <= end and (e not in best or best[e][0] > pieces + 1):
                best[e] = (pieces + 1, total + amount)
    return best[end][1] if end in best else None


def imd_day_total(versions: dict[tuple[str, datetime], list[Report]], station: str, day,
                  since_03utc_blocks=SINCE_03UTC_BLOCKS) -> tuple[float | None, str]:
    """(mm, how) for `station` on IMD day `day`. `how` is 24h_group | ir3_zero | partition, or why the value is
    missing (conflict, ir4_not_observed, no_24h_amount, no_03utc_report). A missing report is never zero."""
    start, end = imd_day_window(day)
    candidates = versions.get((station, end), [])
    if candidates:
        results = {_amount_24h(r, since_03utc_blocks) for r in candidates}
        values = {v for v, _ in results if v is not None}
        if len(values) > 1:
            return None, "conflicting_versions"
        if values:
            value = values.pop()
            return value, next(how for v, how in results if v == value)
        reasons = sorted(how for _, how in results)
        if reasons != ["no_24h_amount"]:
            return None, reasons[0]
    intervals: dict[tuple[datetime, datetime], float] = {}
    for (sid, time), reports in versions.items():
        if sid != station or not (start < time <= end):
            continue
        for acc in reports[0].accumulations:
            hours = resolve_period(reports[0], acc, since_03utc_blocks)
            if acc.amount_mm is not None and hours is not None and time - timedelta(hours=hours) >= start:
                intervals[(time - timedelta(hours=hours), time)] = acc.amount_mm
    total = _partition(intervals, start, end)
    if total is not None:
        return total, "partition"
    return None, "no_24h_amount" if candidates else "no_03utc_report"
