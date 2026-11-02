"""Builders for tiny synthetic label files (CSV, DBF, SHP) used by the events tests."""
from __future__ import annotations

import csv
import struct
from pathlib import Path

GLC_COLUMNS = ["event_id", "event_date", "location_accuracy", "landslide_trigger",
               "country_code", "latitude", "longitude"]
COOLR_EVENTS_COLUMNS = ["event_id", "event_date", "landslide_trigger", "country_code",
                        "latitude", "longitude", "sat_date_before", "sat_date_after"]

HMA_FIELDS = [("ev_id", "N", 10, 0), ("ev_date", "D", 8, 0), ("loc_accu", "C", 50, 0),
              ("ls_trig", "C", 50, 0), ("ctry_code", "C", 2, 0),
              ("latitude", "F", 19, 11), ("longitude", "F", 19, 11)]


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, restval="")
        writer.writeheader()
        writer.writerows(rows)
    return path


def write_dbf(path: Path, fields: list[tuple], records: list[dict], deleted=(),
              encoding: str = "utf-8", cpg: str | None = "UTF-8") -> Path:
    """Write a dBase III file. `fields` is (name, type, length, decimals); `deleted` are record positions."""
    header_len = 32 + 32 * len(fields) + 1
    record_len = 1 + sum(f[2] for f in fields)
    out = bytearray(struct.pack("<B3BIHH20x", 3, 26, 9, 30, len(records), header_len, record_len))
    for name, ftype, length, decimals in fields:
        out += struct.pack("<11sc4xBB14x", name.encode("ascii"), ftype.encode("ascii"), length, decimals)
    out += b"\x0d"
    for pos, record in enumerate(records):
        out += b"*" if pos in deleted else b" "
        for name, ftype, length, decimals in fields:
            value = record.get(name)
            if value is None:
                text = ""
            elif ftype in "NF" and not isinstance(value, str):
                text = f"{value:.{decimals}f}"
            else:
                text = str(value)
            raw = text.encode(encoding)
            out += raw.rjust(length) if ftype in "NF" else raw.ljust(length)
    out += b"\x1a"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(out))
    if cpg is not None:
        path.with_suffix(".cpg").write_text(cpg, encoding="ascii")
    return path


def write_shp_points(path: Path, points: list[tuple[float, float] | None]) -> Path:
    """Write a point shapefile; None entries become null shapes. Points are (lon, lat)."""
    body = bytearray()
    for number, point in enumerate(points, start=1):
        if point is None:
            body += struct.pack(">ii", number, 2) + struct.pack("<i", 0)
        else:
            body += struct.pack(">ii", number, 10) + struct.pack("<idd", 1, point[0], point[1])
    header = bytearray(100)
    struct.pack_into(">i", header, 0, 9994)
    struct.pack_into(">i", header, 24, (100 + len(body)) // 2)
    struct.pack_into("<ii", header, 28, 1000, 1)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(header) + bytes(body))
    return path


def write_raw_dir(root: Path, glc=(), reports=(), events=(), hma=(), hma_deleted=()) -> Path:
    """Write the four source files under `root` from lists of row dicts."""
    write_csv(root / "nasa_glc.csv", GLC_COLUMNS, list(glc))
    write_csv(root / "coolr_reports_points.csv", GLC_COLUMNS, list(reports))
    write_csv(root / "coolr_events_points.csv", COOLR_EVENTS_COLUMNS, list(events))
    write_dbf(root / "hma" / "HMA_LS_Cat_point_v02.0.dbf", HMA_FIELDS, list(hma), deleted=hma_deleted)
    return root
