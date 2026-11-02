"""Tolerant reader for landslide catalog CSV exports (NASA GLC / COOLR, HMA catalog)."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from ..grid import region_labels, regions


class CatalogFormatError(ValueError):
    """Raised when a catalog file cannot be read without guessing."""


COLUMN_CANDIDATES = {
    "event_date": ["event_date", "date", "event_datetime", "start_date"],
    "latitude": ["latitude", "lat", "y"],
    "longitude": ["longitude", "lon", "lng", "long", "x"],
    "accuracy": ["location_accuracy", "location_accuracy_km", "loc_accuracy"],
    "trigger": ["landslide_trigger", "trigger"],
    "country": ["country_name", "country"],
}
REQUIRED = ("event_date", "latitude", "longitude")


def _normalise(name: str) -> str:
    return re.sub(r"[^0-9a-z]+", "_", str(name).strip().lower()).strip("_")


def parse_accuracy_km(value) -> float:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return float("nan")
    text = str(value).strip().lower()
    if text == "exact":
        return 0.0
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(?:km)?", text)
    return float(match.group(1)) if match else float("nan")


_ISO_RE = r"^\d{4}-\d{2}-\d{2}(?:[T ].*)?$"
_NUMERIC_DMY_RE = r"^(\d{1,2})[/.-](\d{1,2})[/.-]\d{2,4}(?:\s.*)?$"


def _parse_dates(series: pd.Series) -> pd.Series:
    """Parse a date column without guessing.

    Each non-blank string is classified into exactly one form:
    * ISO (YYYY-MM-DD, optional time): parsed as ISO 8601, never day-first, and
      independent of how any other row is written.
    * numeric day/month/year (D[/.-]M[/.-]YY or YYYY, optional time): the
      day/month ordering is inferred file-wide from these rows only. A value
      above 12 in the first position means day-first, in the second month-first;
      both raises "inconsistent", neither raises "ambiguous". Two-digit years
      follow pandas' (dateutil's) default, which resolves the century relative
      to the current year (today, 69 -> 2069 and 77 -> 1977); prefer 4-digit years.
      ISO timestamps carrying a UTC offset are converted to UTC before the time
      of day is dropped.
    * anything else: NaT, so the caller counts it as a dropped bad date.
    """
    text = series.astype("string").str.strip()
    is_iso = text.str.match(_ISO_RE).fillna(False).astype(bool)
    is_dmy = text.str.match(_NUMERIC_DMY_RE).fillna(False).astype(bool)
    out = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]")

    if is_iso.any():
        iso = pd.to_datetime(text[is_iso], format="ISO8601", errors="coerce", utc=True)
        out.loc[is_iso] = iso.dt.tz_localize(None).astype("datetime64[ns]")
    if is_dmy.any():
        parts = text[is_dmy].str.extract(_NUMERIC_DMY_RE)
        first_over_12 = bool((parts[0].astype(int) > 12).any())
        second_over_12 = bool((parts[1].astype(int) > 12).any())
        if first_over_12 and second_over_12:
            raise CatalogFormatError("inconsistent day/month ordering in numeric day/month/year dates")
        if not first_over_12 and not second_over_12:
            raise CatalogFormatError(
                "ambiguous numeric day/month/year dates (no value above 12 in either position); "
                "cannot tell day-first from month-first without guessing")
        dmy = pd.to_datetime(text[is_dmy], dayfirst=first_over_12, errors="coerce", format="mixed")
        out.loc[is_dmy] = dmy.astype("datetime64[ns]")
    return out.dt.normalize()


@dataclass
class CatalogReport:
    path: str
    total_rows: int = 0
    dropped_bad_date: int = 0
    dropped_bad_coordinates: int = 0
    kept_rows: int = 0
    columns_found: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)


def read_catalog_csv(path) -> tuple[pd.DataFrame, CatalogReport]:
    path = Path(path)
    try:
        raw = pd.read_csv(path, dtype=str, encoding="utf-8-sig", keep_default_na=False)
    except UnicodeDecodeError:
        raw = pd.read_csv(path, dtype=str, encoding="latin-1", keep_default_na=False)
    if raw.shape[1] == 1 and (";" in raw.columns[0] or "\t" in raw.columns[0]):
        raise CatalogFormatError("unsupported delimiter: expected a comma-separated file")

    lookup = {_normalise(c): c for c in raw.columns}
    cols = {}
    for canonical, candidates in COLUMN_CANDIDATES.items():
        cols[canonical] = next((lookup[c] for c in candidates if c in lookup), None)
    missing = [c for c in REQUIRED if cols[c] is None]
    if missing:
        raise CatalogFormatError(f"missing required column(s) {missing}; found columns: {list(raw.columns)}")

    report = CatalogReport(path=str(path), total_rows=len(raw),
                           columns_found={k: v for k, v in cols.items() if v is not None})
    dates = _parse_dates(raw[cols["event_date"]])
    lat = pd.to_numeric(raw[cols["latitude"]].str.strip(), errors="coerce")
    lon = pd.to_numeric(raw[cols["longitude"]].str.strip(), errors="coerce")
    bad_date = dates.isna()
    bad_coord = (lat.isna() | lon.isna() | (lat.abs() > 90) | (lon.abs() > 180)
                 | ((lat == 0) & (lon == 0)))  # (0, 0) is a placeholder for "no coordinates"
    report.dropped_bad_date = int(bad_date.sum())
    report.dropped_bad_coordinates = int((bad_coord & ~bad_date).sum())
    keep = ~bad_date & ~bad_coord
    report.kept_rows = int(keep.sum())

    def column(canonical, default=""):
        return raw.loc[keep, cols[canonical]].str.strip() if cols[canonical] else pd.Series(default, index=raw.index[keep])

    out = pd.DataFrame({
        "event_date": dates[keep],
        "latitude": lat[keep],
        "longitude": lon[keep],
        "accuracy_km": column("accuracy", "unknown").map(parse_accuracy_km),
        "trigger": column("trigger"),
        "country": column("country"),
    }).sort_values("event_date").reset_index(drop=True)
    out["region"] = region_labels(out["latitude"].to_numpy(), out["longitude"].to_numpy())
    return out, report


def summarize_catalog(df: pd.DataFrame, max_accuracy_km: float) -> dict[str, dict]:
    summary: dict[str, dict] = {}
    for name in [*regions().keys(), ""]:
        sub = df[df["region"] == name]
        located = sub[sub["accuracy_km"].le(max_accuracy_km)]  # NaN compares False
        summary[name or "outside_domain"] = {
            "n_total": int(len(sub)),
            "n_located": int(len(located)),
            "n_unknown_accuracy": int(sub["accuracy_km"].isna().sum()),
            "first_date": str(sub["event_date"].min().date()) if len(sub) else None,
            "last_date": str(sub["event_date"].max().date()) if len(sub) else None,
            "by_year": {int(y): int(c) for y, c in
                        located["event_date"].dt.year.value_counts().sort_index().items()},
            "top_triggers": located["trigger"].replace("", "unknown").value_counts().head(5).to_dict(),
        }
    return summary
