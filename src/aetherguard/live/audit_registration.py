"""Which rain product is registered right? A gauge-referenced study of the shift test of `audit_geo.rain_georef`.

    python -m aetherguard.live.audit_registration [--out DIR]

The audit test compares IMERG with the IMD real-time grid and asks whether a shifted grid correlates better. On the published
days a one-cell shift towards the west of the IMD grid does (reports/live/audit/summary.json). That is a statement about two
products, not about which one is displaced, so this study puts the GHCN-Daily gauges of the India / Nepal domain (point truth,
their readings are independent of the grids' registration) next to each product: for every product and every shift, the
correlation of the gauge rain with the product sampled at the station's pixel moved by the shift (pixels of the product's own
grid: IMD 0.25 degree, IMERG 0.1 degree, CHIRPS 0.05 degree). A product is registered correctly when its zero shift is among the
best. Also reported: the IMD final grid against IMERG Late over the same days, the pair the audit compares (IMD real-time is the
same product family as IMD final).

Period: 100 IMD days from 2024-06-10 (monsoon: rain at most stations), all selected stations inside the IMERG domain.
The IMD final grid is also read at the stations with each way of picking a grid column and row (`lookup_index`), over the monsoon
of each year of `LOOKUP_YEARS`, to say which way registers the grid with the gauges. Writes
`<out>/rain_registration_study.json`.
"""
from __future__ import annotations

import argparse
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from ..hazard.jsonio import dump_json
from .audit import DEFAULT_OUT

FIRST_DAY = date(2024, 6, 10)
DAYS = 100
LOOKUP_YEARS = (2015, 2018, 2023, 2024)
LOOKUP_OPTIONS = ("round", "round-1", "floor", "ceil")      # grid index from (coordinate - origin) / step
SHIFTS = tuple((dr, dc) for dr in (-1, 0, 1) for dc in (-1, 0, 1))
IMERG_COLUMN_SHIFTS = tuple((0, dc) for dc in range(-4, 3))     # 0.1 degree columns: reaches the 0.2-0.25 degree IMD offset


def shift_correlations(reference: np.ndarray, sample: Callable[[int, int], np.ndarray], shifts=SHIFTS,
                       transform: Callable[[np.ndarray], np.ndarray] = np.sqrt) -> dict[str, float]:
    """Pearson correlation of `reference` ((days, points)) with `sample(dr, dc)` (same shape) for each shift, after
    `transform` (square root: rain is heavy-tailed) over the entries where both are known and the reference is >= 0."""
    out = {}
    for dr, dc in shifts:
        other = sample(dr, dc)
        ok = np.isfinite(reference) & np.isfinite(other) & (reference >= 0) & (other >= 0)
        a, b = transform(reference[ok].astype(np.float64)), transform(other[ok].astype(np.float64))
        out[f"{dr},{dc}"] = float(np.corrcoef(a, b)[0, 1]) if ok.sum() > 2 and a.std() > 0 and b.std() > 0 else float("nan")
    return out


def lookup_index(position: np.ndarray, option: str) -> np.ndarray:
    """Grid index for `position` = (coordinate - origin) / step: the nearest point ("round", the project's lookup), the one
    before it ("round-1"), the point below ("floor", a label that names a cell's lower edge) or above ("ceil")."""
    position = np.round(np.asarray(position, dtype=np.float64), 6)
    nearest = np.floor(position + 0.5)
    return {"round": nearest, "round-1": nearest - 1, "floor": np.floor(position), "ceil": np.ceil(position)}[option].astype(np.int64)


def best_shift(table: dict[str, float]) -> str:
    return max(table, key=lambda k: table[k] if np.isfinite(table[k]) else -np.inf)


def imd_lookup_options(meta, rain_dir: Path) -> dict:
    """{"year": {"lon=<option>,lat=<option>": correlation}} of the gauges with the IMD final grid read by each lookup."""
    from ..integrity.stations import load_station_set
    from ..ingest import imd as imd_mod
    out: dict[str, dict[str, float]] = {}
    x_lon = (meta["lon"].to_numpy() - imd_mod.LON_MIN) / imd_mod.STEP
    x_lat = (meta["lat"].to_numpy() - imd_mod.LAT_MIN) / imd_mod.STEP
    for year in LOOKUP_YEARS:
        first = date(year, 6, 10)
        stations = load_station_set(start=first.isoformat(), end=(first + timedelta(days=DAYS - 1)).isoformat())
        observed = stations.values.reindex(stations.values.index)[meta["id"]].to_numpy(dtype=np.float64)
        grid = np.array(np.load(Path(rain_dir) / f"imd_{year}.npy", mmap_mode="r")[(first - date(year, 1, 1)).days:][:DAYS])
        grid[grid < 0] = np.nan
        table = {}
        for lon_option in LOOKUP_OPTIONS:
            for lat_option in ("round", "floor"):
                rows = np.clip(lookup_index(x_lat, lat_option), 0, imd_mod.N_LAT - 1)
                cols = np.clip(lookup_index(x_lon, lon_option), 0, imd_mod.N_LON - 1)
                table[f"lon={lon_option},lat={lat_option}"] = shift_correlations(observed, lambda dr, dc: grid[:, rows, cols],
                                                                                  shifts=((0, 0),))["0,0"]
        out[str(year)] = table
    return out


def run_study(out: Path) -> dict:
    from ..features import imerg_features as F
    from ..features.sources import day_numbers, load_chirps
    from ..grid import latlon_to_cell
    from ..ingest import imd as imd_mod
    from ..ingest import imerg as imerg_mod
    from ..integrity.stations import load_station_set
    from .sources import project_path
    last = FIRST_DAY + timedelta(days=DAYS - 1)
    stations = load_station_set(start=FIRST_DAY.isoformat(), end=last.isoformat())
    meta = stations.meta
    meta = meta[(meta.lat >= 8.1) & (meta.lat <= 36) & (meta.lon >= 72.1) & (meta.lon <= 98)].reset_index(drop=True)
    observed = stations.values.reindex(stations.values.index)[meta["id"]].to_numpy(dtype=np.float64)
    cells = np.array([int(latlon_to_cell(a, b)) for a, b in zip(meta["lat"], meta["lon"])])
    flat = F.cell_pixels(cells)
    row, col = flat // imerg_mod.COLS, flat % imerg_mod.COLS
    rain = project_path("data/processed/rain")
    store = imerg_mod.ImergStore(rain, "late")
    imd = np.load(rain / f"imd_{FIRST_DAY.year}.npy", mmap_mode="r")
    start = (FIRST_DAY - date(FIRST_DAY.year, 1, 1)).days
    chirps = load_chirps(rain)
    first_number = int(day_numbers([FIRST_DAY])[0])
    i0 = np.floor(np.round((meta["lat"].to_numpy() - imd_mod.LAT_MIN) / imd_mod.STEP, 6) + 0.5).astype(int)
    j0 = np.floor(np.round((meta["lon"].to_numpy() - imd_mod.LON_MIN) / imd_mod.STEP, 6) + 0.5).astype(int)
    grid_imd = np.array(imd[start:start + DAYS])
    grid_imd[grid_imd < 0] = np.nan

    def imerg(dr, dc):
        utc = store.gather(np.clip(row + dr, 0, imerg_mod.ROWS - 1), np.clip(col + dc, 0, imerg_mod.COLS - 1),
                           FIRST_DAY - timedelta(days=1), DAYS + 1)
        return F.imd_day_series(utc).T

    def imd_final(dr, dc):
        return grid_imd[:, np.clip(i0 + dr, 0, imd_mod.N_LAT - 1), np.clip(j0 + dc, 0, imd_mod.N_LON - 1)]

    def chirps_aligned(dr, dc):
        utc = chirps.gather(chirps.pixels(cells + dr * 10000 + dc), first_number - 1, DAYS + 1)
        return (0.875 * utc[:, :-1] + 0.125 * utc[:, 1:]).T

    result = {"period": [FIRST_DAY.isoformat(), last.isoformat()], "stations": int(len(meta)),
              "shift_unit": "(rows north, columns east) of the product's own grid",
              "gauge_vs_product": {name: shift_correlations(observed, fn, shifts)
                                   for name, fn, shifts in (("imd_final", imd_final, SHIFTS), ("imerg_late", imerg, SHIFTS),
                                                            ("chirps", chirps_aligned, SHIFTS))},
              "gauge_vs_imerg_columns": shift_correlations(observed, imerg, IMERG_COLUMN_SHIFTS)}
    result["best_shift"] = {name: best_shift(t) for name, t in result["gauge_vs_product"].items()}
    result["imd_lookup_options"] = imd_lookup_options(meta, rain)
    dump_json(Path(out) / "rain_registration_study.json", result)
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m aetherguard.live.audit_registration", description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    result = run_study(args.out)
    for name, best in result["best_shift"].items():
        print(f"{name}: best shift {best}, zero shift {result['gauge_vs_product'][name]['0,0']:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
