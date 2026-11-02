"""Tolerance matching of landslide events and alert cell-days.

An event is reported with a location and a date that are only good to a few kilometres and a day, so an alert is credited
with an event when it lies within a tolerance of it: `Tolerance(km=10, days=1)` by default, `CELL_EXACT` for the strict
same-cell, same-day reading. The distance is the great-circle (haversine) distance between 0.05-degree cell centres, not a
count of cells, because a cell is narrower in kilometres towards the poles.

Two views of the same rule:

* per event: the highest published level of any panel cell-day within tolerance (`Match.event_level`), -1 when the panel
  has no cell-day within tolerance, so the event could not have been alerted and is not a miss;
* per cell-day: whether some event lies within tolerance of it (`Match.alert_verified`), which is what makes an alert a
  hit rather than a false alarm.

Events are de-duplicated on (cell, date) first, since one slide appears in several catalogue records. An event whose date
lies outside the panel days widened by the day tolerance is counted in `Match.outside_window` and takes no further part.
The panel need not contain the event's own cell: events are matched to panel cells by distance.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from ..grid import cell_center

EARTH_RADIUS_KM = 6371.0088
KM_PER_DEG = 111.0  # deliberately a little under the true 111.2 so the candidate window never clips a cell in range


@dataclass(frozen=True)
class Tolerance:
    km: float = 10.0
    days: int = 1

    def __post_init__(self) -> None:
        if not self.km >= 0:
            raise ValueError(f"km must be >= 0, got {self.km}")
        if not self.days >= 0:
            raise ValueError(f"days must be >= 0, got {self.days}")


CELL_EXACT = Tolerance(0.0, 0)


@dataclass
class Match:
    event_level: np.ndarray  # int8 per event: highest level within tolerance, -1 when no panel cell-day is within it
    alert_verified: np.ndarray  # bool, cells x days: an event lies within tolerance of the cell-day
    events: pd.DataFrame  # the de-duplicated events inside the window, columns cell_id and date
    outside_window: int  # de-duplicated events dated outside the panel days widened by the day tolerance


def _haversine_km(lat1: float, lon1: float, lat2: np.ndarray, lon2: np.ndarray) -> np.ndarray:
    p1, p2 = np.radians(lat1), np.radians(lat2)
    a = np.sin((p2 - p1) / 2.0) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(np.radians(lon2 - lon1) / 2.0) ** 2
    return 2.0 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def rows_within(event_cells: np.ndarray, panel_cells: np.ndarray, km: float) -> list[np.ndarray]:
    """Per event cell, the ascending panel row indices whose cell centres lie within `km` of the event cell's centre.

    Candidates come from a latitude/longitude window of `km / 111` degrees (longitude widened by 1 / cos(lat) at the
    window's poleward edge, wrapping at the antimeridian) and are then filtered by exact haversine distance. The event's
    own cell is always included when it is a panel cell.
    """
    event_cells = np.asarray(event_cells, dtype=np.int64)
    panel_lat, panel_lon = cell_center(np.asarray(panel_cells, dtype=np.int64))
    order = np.argsort(panel_lat, kind="stable")
    sorted_lat = panel_lat[order]
    dlat = km / KM_PER_DEG
    found: dict[int, np.ndarray] = {}
    out: list[np.ndarray] = []
    for cell in event_cells.tolist():
        if cell not in found:
            lat, lon = cell_center(cell)
            lo = np.searchsorted(sorted_lat, lat - dlat, side="left")
            hi = np.searchsorted(sorted_lat, lat + dlat, side="right")
            rows = order[lo:hi]
            cos_edge = np.cos(np.radians(min(abs(lat) + dlat, 90.0)))
            if cos_edge > 1e-9:
                dlon = (panel_lon[rows] - lon + 180.0) % 360.0 - 180.0
                rows = rows[np.abs(dlon) <= dlat / cos_edge]
            dist = _haversine_km(lat, lon, panel_lat[rows], panel_lon[rows])
            found[cell] = np.sort(rows[dist <= km])
        out.append(found[cell])
    return out


def _dedupe(events: pd.DataFrame) -> pd.DataFrame:
    missing = {"cell_id", "date"} - set(events.columns)
    if missing:
        raise ValueError(f"events lack column(s): {sorted(missing)}")
    frame = pd.DataFrame(
        {
            "cell_id": events["cell_id"].to_numpy(dtype=np.int64),
            "date": [d.date() for d in pd.to_datetime(events["date"])],
        }
    )
    return frame.drop_duplicates().reset_index(drop=True)


def match(levels: np.ndarray, cell_ids: np.ndarray, days: list[date], events: pd.DataFrame, tol: Tolerance) -> Match:
    """Match events to the published levels of a panel (`levels`: cells x days) under `tol`; see the module docstring."""
    levels = np.asarray(levels)
    cell_ids = np.asarray(cell_ids, dtype=np.int64)
    if levels.shape != (len(cell_ids), len(days)):
        raise ValueError(f"levels shape {levels.shape} does not match {len(cell_ids)} cells x {len(days)} days")
    unique = _dedupe(events)
    day_ordinals = np.array([d.toordinal() for d in days], dtype=np.int64)
    event_ordinals = np.array([d.toordinal() for d in unique["date"]], dtype=np.int64)
    if len(days):
        inside = (event_ordinals >= day_ordinals.min() - tol.days) & (event_ordinals <= day_ordinals.max() + tol.days)
    else:
        inside = np.zeros(len(unique), dtype=bool)
    kept = unique[inside].reset_index(drop=True)
    kept_ordinals = event_ordinals[inside]

    event_level = np.full(len(kept), -1, dtype=np.int8)
    alert_verified = np.zeros(levels.shape, dtype=bool)
    near_rows = rows_within(kept["cell_id"].to_numpy(), cell_ids, tol.km)
    for i, (rows, ordinal) in enumerate(zip(near_rows, kept_ordinals)):
        cols = np.flatnonzero(np.abs(day_ordinals - ordinal) <= tol.days)
        if len(rows) == 0 or len(cols) == 0:
            continue
        block = np.ix_(rows, cols)
        event_level[i] = levels[block].max()
        alert_verified[block] = True
    return Match(event_level, alert_verified, kept, int((~inside).sum()))
