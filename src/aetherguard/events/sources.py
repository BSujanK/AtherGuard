"""Readers that map each landslide source file onto one common raw schema.

Every reader returns one row per record in the file, in file order, and never drops anything:
unparseable dates become NaT and unparseable coordinates NaN, so the store can count and label them.
`DataFrame.attrs` carries `n_rows` (records returned) and `n_deleted` (records flagged deleted in the
file and therefore not returned, only ever non-zero for the DBF).

Files that cannot be read without guessing raise `CatalogFormatError` with the file path in the message.
No timezone conversion is done anywhere: a date string carrying a UTC offset is refused.
"""
from __future__ import annotations

import codecs
import csv
import io
import re
import struct
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pandas as pd

from ..audit.landslides import CatalogFormatError, _normalise, _parse_dates, parse_accuracy_km

# The COOLR events layer is a set of individually mapped landslides and has no accuracy field;
# 1 km is the documented assumption (Phase 1 design D2).
COOLR_EVENTS_ACCURACY_KM = 1.0

COMMON_COLUMNS = ["source", "row", "event_id", "event_date_raw", "event_date", "latitude", "longitude",
                  "accuracy_raw", "accuracy_km", "trigger_raw", "country_code"]
EVENTS_EXTRA_COLUMNS = ["sat_date_before", "sat_date_after", "date_window_start", "date_window_end"]

_CSV_REQUIRED = ("event_id", "event_date", "landslide_trigger", "country_code", "latitude", "longitude")
_KNOWN_WITHIN_RE = re.compile(r"known within (\d+(?:\.\d+)?)\s*km")
# A clock time followed by Z or +hh[:mm] / -hh[:mm]; a bare date such as 2015-07-15 never matches.
_UTC_OFFSET_RE = re.compile(r"\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?\s*(?:Z|[+-]\d{2}(?::?\d{2})?)\s*$", re.IGNORECASE)
_ISO_DAY_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _accuracy_km(value: str) -> float:
    """`parse_accuracy_km` plus the long-form wording some COOLR reports use ("Known within 5 km")."""
    text = str(value).strip().lower()
    if text == "known exactly":
        return 0.0
    match = _KNOWN_WITHIN_RE.fullmatch(text)
    if match:
        return float(match.group(1))
    return parse_accuracy_km(text)


def _read_csv(path, required: tuple[str, ...]) -> pd.DataFrame:
    """Read a CSV as strings with normalised column names; refuse empty files and duplicate columns."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"label file not found: {path}")
    data = path.read_bytes()
    if not data.strip():
        raise CatalogFormatError(f"{path}: file is empty")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1").removeprefix("\xef\xbb\xbf")
    names = [_normalise(name) for name in next(csv.reader(io.StringIO(text)))]
    duplicated = sorted({name for name in names if names.count(name) > 1})
    if duplicated:
        raise CatalogFormatError(f"{path}: duplicate column name(s) after normalisation: {duplicated}")
    try:
        raw = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False, header=0, names=names)
    except pd.errors.ParserError as exc:
        raise CatalogFormatError(f"{path}: cannot parse CSV: {exc}") from exc
    missing = [c for c in required if c not in raw.columns]
    if missing:
        raise CatalogFormatError(f"{path}: missing required column(s) {missing}; found columns: {names}")
    return raw


def _reject_utc_offsets(path, dates: pd.Series) -> None:
    hits = dates[dates.str.strip().str.contains(_UTC_OFFSET_RE)]
    if len(hits):
        raise CatalogFormatError(
            f"{path}: {len(hits)} date value(s) carry a UTC offset (first: {hits.iloc[0].strip()!r}); "
            "no timezone conversion is done, so the file is refused")


def _common_frame(source: str, event_id, date_raw, event_date, latitude, longitude, accuracy_raw,
                  accuracy_km, trigger_raw, country_code) -> pd.DataFrame:
    n = len(date_raw)
    frame = pd.DataFrame({
        "source": pd.Series([source] * n, dtype="str"),
        "row": np.arange(n, dtype="int64"),
        "event_id": pd.to_numeric(pd.Series(event_id).astype("string").str.strip(), errors="coerce").astype("Int64"),
        "event_date_raw": pd.Series(date_raw, dtype="str").str.strip(),
        "event_date": event_date.astype("datetime64[ns]"),
        "latitude": pd.to_numeric(pd.Series(latitude), errors="coerce").astype("float64"),
        "longitude": pd.to_numeric(pd.Series(longitude), errors="coerce").astype("float64"),
        "accuracy_raw": pd.Series(accuracy_raw, dtype="str").str.strip(),
        "accuracy_km": pd.Series(accuracy_km, dtype="float64"),
        "trigger_raw": pd.Series(trigger_raw, dtype="str").str.strip(),
        "country_code": pd.Series(country_code, dtype="str").str.strip().str.upper(),
    })
    frame.attrs["n_rows"] = n
    frame.attrs["n_deleted"] = 0
    return frame[COMMON_COLUMNS]


def _csv_source(source: str, path, raw: pd.DataFrame, accuracy_raw, accuracy_km) -> pd.DataFrame:
    _reject_utc_offsets(path, raw["event_date"])
    return _common_frame(
        source, raw["event_id"], raw["event_date"], _parse_dates(raw["event_date"]),
        raw["latitude"].str.strip(), raw["longitude"].str.strip(), accuracy_raw, accuracy_km,
        raw["landslide_trigger"], raw["country_code"])


def _read_accuracy_csv(source: str, path) -> pd.DataFrame:
    raw = _read_csv(path, _CSV_REQUIRED + ("location_accuracy",))
    return _csv_source(source, path, raw, raw["location_accuracy"], raw["location_accuracy"].map(_accuracy_km))


def read_glc(path) -> pd.DataFrame:
    """Legacy NASA GLC export (`nasa_glc.csv`); dates are month-first numeric, inferred file-wide."""
    return _read_accuracy_csv("glc", path)


def read_coolr_reports(path) -> pd.DataFrame:
    """COOLR reports layer (`coolr_reports_points.csv`); ISO dates, blank when missing."""
    return _read_accuracy_csv("coolr_reports", path)


def _window_bound(text: str, pick) -> pd.Timestamp:
    """One bound of the inventory window from a comma-separated list of ISO days; NaT if blank or unparsable.

    With several dates the widest bound is taken (`pick` is min for the start, max for the end).
    A single malformed or impossible token makes the whole bound NaT; nothing is repaired.
    """
    if not text.strip():
        return pd.NaT
    days = []
    for token in (t.strip() for t in text.split(",")):
        if not _ISO_DAY_RE.fullmatch(token):
            return pd.NaT
        try:
            days.append(pd.Timestamp(token))
        except ValueError:
            return pd.NaT
    return pick(days)


def read_coolr_events(path) -> pd.DataFrame:
    """COOLR events layer (`coolr_events_points.csv`).

    No accuracy field, so a documented constant. The event date is the inventory headline date; the real
    landslide dates lie between the satellite images in `sat_date_before` and `sat_date_after`, which are
    kept raw and parsed into `date_window_start` / `date_window_end` (NaT when blank or unparsable).
    """
    raw = _read_csv(path, _CSV_REQUIRED + ("sat_date_before", "sat_date_after"))
    blank = pd.Series([""] * len(raw), index=raw.index)
    frame = _csv_source("coolr_events", path, raw, blank, pd.Series(COOLR_EVENTS_ACCURACY_KM, index=raw.index))
    frame["sat_date_before"] = raw["sat_date_before"].str.strip()
    frame["sat_date_after"] = raw["sat_date_after"].str.strip()
    frame["date_window_start"] = pd.Series(
        [_window_bound(t, min) for t in frame["sat_date_before"]], dtype=object).astype("datetime64[ns]")
    frame["date_window_end"] = pd.Series(
        [_window_bound(t, max) for t in frame["sat_date_after"]], dtype=object).astype("datetime64[ns]")
    return frame


_DBF_TYPES = {"C", "N", "F", "D"}


def read_dbf(path, columns: Sequence[str] | None = None) -> tuple[pd.DataFrame, int]:
    """Pure-Python dBase III/IV reader for field types C, N, F and D.

    Returns the non-deleted records (indexed by their 0-based position in the file, so a sibling
    .shp can be aligned) and the number of records flagged deleted. Text uses the encoding named in the
    sibling `.cpg`, else UTF-8. C and D values are returned as stripped strings ("" when blank); N and F as
    floats (NaN when blank), or nullable integers for N fields without decimals. Only `columns` are
    decoded and parsed when given (every field otherwise); any of those that cannot be decoded or parsed
    raises `CatalogFormatError` naming the field and record. The file size must equal the header's
    record count exactly, allowing one trailing 0x1A EOF byte.
    """
    path = Path(path)
    data = path.read_bytes()
    if len(data) < 33:
        raise CatalogFormatError(f"{path}: truncated dBase header")
    n_records, header_len, record_len = struct.unpack("<IHH", data[4:12])
    fields: list[tuple[str, str, int, int, int]] = []  # name, type, length, decimals, offset in record
    pos, offset = 32, 1
    while True:
        if pos >= len(data):
            raise CatalogFormatError(f"{path}: truncated dBase field descriptors")
        if data[pos] == 0x0D:
            break
        name = data[pos:pos + 11].split(b"\x00", 1)[0].decode("ascii", errors="replace")
        ftype = chr(data[pos + 11])
        if ftype not in _DBF_TYPES:
            raise CatalogFormatError(f"{path}: unsupported dBase field type {ftype!r} for field {name!r}")
        fields.append((name, ftype, data[pos + 16], data[pos + 17], offset))
        offset += data[pos + 16]
        pos += 32
    if offset != record_len:
        raise CatalogFormatError(f"{path}: field lengths add up to {offset}, header says record length {record_len}")
    expected = header_len + n_records * record_len
    if not (len(data) == expected or (len(data) == expected + 1 and data[-1] == 0x1A)):
        raise CatalogFormatError(
            f"{path}: dBase file size {len(data)} does not match its {n_records} records "
            f"(expected {expected} bytes, or {expected + 1} with the trailing EOF byte)")

    cpg = path.with_suffix(".cpg")
    encoding = cpg.read_text(encoding="ascii", errors="replace").strip() if cpg.is_file() else "utf-8"
    try:
        codecs.lookup(encoding)
    except LookupError as exc:
        raise CatalogFormatError(f"{cpg}: unknown text encoding {encoding!r}") from exc

    wanted = [f for f in fields if columns is None or f[0] in columns]
    values: dict[str, list] = {f[0]: [] for f in wanted}
    positions: list[int] = []
    n_deleted = 0
    for i in range(n_records):
        start = header_len + i * record_len
        record = data[start:start + record_len]
        if record[:1] == b"*":
            n_deleted += 1
            continue
        for name, ftype, length, _, field_offset in wanted:
            try:
                text = record[field_offset:field_offset + length].decode(encoding).strip(" \x00")
            except UnicodeDecodeError as exc:
                raise CatalogFormatError(
                    f"{path}: cannot decode field {name!r} of record {i} as {encoding}: {exc}") from exc
            if ftype in "NF":
                if not text or set(text) == {"*"}:  # blank or dBase overflow marker
                    values[name].append(float("nan"))
                    continue
                try:
                    values[name].append(float(text))
                except ValueError as exc:
                    raise CatalogFormatError(
                        f"{path}: field {name!r} of record {i}: cannot parse number {text!r}") from exc
            else:
                values[name].append(text)
        positions.append(i)

    out = {}
    for name, ftype, _, decimals, _ in wanted:
        if ftype in "NF":
            series = pd.Series(values[name], dtype="float64")
            integral = decimals == 0 and bool((series.dropna() % 1 == 0).all())
            out[name] = series.astype("Int64") if integral else series
        else:
            out[name] = pd.Series(values[name], dtype="str")
    table = pd.DataFrame(out)
    table.index = pd.Index(positions, dtype="int64")
    return table, n_deleted


_HMA_REQUIRED = ("ev_id", "ev_date", "loc_accu", "ls_trig", "ctry_code", "latitude", "longitude")


def read_hma(dbf_path) -> pd.DataFrame:
    """HMA landslide catalogue attribute table (`HMA_LS_Cat_point_v02.0.dbf`)."""
    dbf_path = Path(dbf_path)
    table, n_deleted = read_dbf(dbf_path, columns=_HMA_REQUIRED)
    missing = [c for c in _HMA_REQUIRED if c not in table.columns]
    if missing:
        raise CatalogFormatError(
            f"{dbf_path}: missing required field(s) {missing}; found fields: {list(table.columns)}")
    positions = table.index.to_numpy(dtype="int64")
    table = table.reset_index(drop=True)
    frame = _common_frame(
        "hma", table["ev_id"], table["ev_date"],
        pd.to_datetime(table["ev_date"], format="%Y%m%d", errors="coerce"),
        table["latitude"], table["longitude"], table["loc_accu"], table["loc_accu"].map(_accuracy_km),
        table["ls_trig"], table["ctry_code"])
    frame["row"] = positions  # position in the file, deleted records included
    frame.attrs["n_rows"] = len(table)
    frame.attrs["n_deleted"] = n_deleted
    return frame


def read_shp_points(shp_path) -> pd.DataFrame:
    """Coordinates of a point shapefile (type 1, WGS84 lon/lat) indexed by record position.

    Null shapes yield NaN. Anything other than a point layer is refused rather than guessed at.
    """
    shp_path = Path(shp_path)
    data = shp_path.read_bytes()
    if len(data) < 100 or struct.unpack(">i", data[:4])[0] != 9994:
        raise CatalogFormatError(f"{shp_path}: not a shapefile")
    shape_type = struct.unpack("<i", data[32:36])[0]
    if shape_type != 1:
        raise CatalogFormatError(
            f"{shp_path}: only point (type 1) shapefiles are supported, got type {shape_type}")
    file_len = struct.unpack(">i", data[24:28])[0] * 2
    if len(data) < file_len:
        raise CatalogFormatError(f"{shp_path}: truncated ({len(data)} of {file_len} bytes)")
    lons: list[float] = []
    lats: list[float] = []
    pos = 100
    while pos < file_len:
        _, words = struct.unpack(">ii", data[pos:pos + 8])
        content = data[pos + 8:pos + 8 + words * 2]
        record_type = struct.unpack("<i", content[:4])[0]
        if record_type == 0:
            lons.append(float("nan"))
            lats.append(float("nan"))
        elif record_type == 1:
            x, y = struct.unpack("<dd", content[4:20])
            lons.append(x)
            lats.append(y)
        else:
            raise CatalogFormatError(f"{shp_path}: record {len(lons)} has non-point shape type {record_type}")
        pos += 8 + words * 2
    return pd.DataFrame({"longitude": lons, "latitude": lats})
