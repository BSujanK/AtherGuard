"""Hand-made label-store DataFrames for the splits tests."""
from __future__ import annotations

import pandas as pd

from aetherguard.grid import ID_STRIDE

COLUMNS = ["uid", "source", "event_id", "event_date", "event_date_raw", "latitude", "longitude",
           "cell_id", "accuracy_km", "trigger_raw", "trigger_class", "country_code", "region",
           "drop_reason", "not_positive_reason", "is_positive", "is_day_exact_positive",
           "date_basis", "date_window_start", "date_window_end"]

HIMALAYA = (2349, 5370)  # (lat_index, lon_index) of a real Himalaya cell
GHATS = (1970, 5150)


def cell(lat_index: int, lon_index: int) -> int:
    return lat_index * ID_STRIDE + lon_index


def event(n, date, cell_id=None, *, region="himalaya", country="IN", source="hma", accuracy=1.0,
          positive=True, window=None):
    """One label-store row. `window=(start, end)` makes it an inventory-window record."""
    if cell_id is None:
        cell_id = cell(*(HIMALAYA if region == "himalaya" else GHATS))
    is_window = window is not None
    return {
        "uid": f"{source}:{n}", "source": source, "event_id": n, "event_date": pd.Timestamp(date),
        "event_date_raw": str(date), "latitude": 30.0, "longitude": 79.0, "cell_id": cell_id,
        "accuracy_km": accuracy, "trigger_raw": "rain", "trigger_class": "rain",
        "country_code": country, "region": region, "drop_reason": None,
        "not_positive_reason": None if positive else "accuracy",
        "is_positive": positive, "is_day_exact_positive": positive and not is_window,
        "date_basis": "inventory_window" if is_window else "event_day",
        "date_window_start": pd.Timestamp(window[0]) if is_window else pd.NaT,
        "date_window_end": pd.Timestamp(window[1]) if is_window else pd.NaT,
    }


def events_frame(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=COLUMNS)
    for column in ("event_date", "date_window_start", "date_window_end"):
        df[column] = pd.to_datetime(df[column]).astype("datetime64[ns]")
    df["cell_id"] = df["cell_id"].astype("Int64")
    df["event_id"] = df["event_id"].astype("Int64")
    df["drop_reason"] = df["drop_reason"].astype("string")
    df["not_positive_reason"] = df["not_positive_reason"].astype("string")
    return df


def sample_events() -> pd.DataFrame:
    """Covers every split boundary, both regions, both case studies and an inventory window."""
    h, g = cell(*HIMALAYA), cell(*GHATS)
    far = cell(2100, 4000)
    rows = [event(i, "2010-07-01", h) for i in range(1, 39)]  # 38 events in one cell-day
    n = 100
    for date in ("2015-12-31", "2016-01-01", "2017-12-31", "2018-01-01", "2018-12-31",
                 "2019-01-01", "2024-12-31"):
        n += 1
        rows.append(event(n, date, far))
    rows += [
        event(201, "2018-08-15", g, region="western_ghats"),                     # kerala_2018
        event(202, "2018-08-01", g, region="western_ghats", source="glc"),       # kerala_2018 start boundary
        event(203, "2018-08-31", g, region="western_ghats"),                     # kerala_2018 end boundary
        event(204, "2018-09-01", g, region="western_ghats"),                     # just after
        event(205, "2018-08-15", h),                     # right dates, wrong region
        event(206, "2024-07-24", g, region="western_ghats"),                     # day before wayanad_2024
        event(207, "2024-08-06", g, region="western_ghats"),                     # day after wayanad_2024
        event(208, "2012-06-01", h, country="NP"),
        event(209, "2012-06-01", h, country="NP", source="glc"),
        event(210, "2012-06-01", h, country="IN", source="coolr_reports"),
        event(301, "2023-07-01", h, source="coolr_events", window=("2023-06-16", "2023-07-31")),
        event(302, "2023-07-01", h, source="coolr_events", window=("2023-06-16", "2023-07-31")),
        event(303, "2023-07-01", far, source="coolr_events", window=("2023-06-16", "2023-07-31")),
        event(401, "2011-01-01", h, positive=False, accuracy=40.0),
    ]
    return events_frame(rows)


def write_events(df: pd.DataFrame, path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
