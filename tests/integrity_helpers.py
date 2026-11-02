"""Hand-made GHCN-Daily files and station sets for the integrity tests."""
from __future__ import annotations

import calendar

import numpy as np
import pandas as pd

from aetherguard.integrity.stations import StationSet

DLY_LINE_LENGTH = 269


def dly_line(station, year, month, element="PRCP", days=None):
    """A 269-character .dly line; `days` maps day -> (raw tenths of mm, qflag)."""
    days = days or {}
    body = ""
    for d in range(1, 32):
        raw, q = days.get(d, (-9999, " "))
        body += f"{raw:5d}" + " " + q + "S"
    return f"{station}{year:04d}{month:02d}{element}{body}"


def station_line(sid, lat, lon, elev, name):
    return f"{sid:<11} {lat:8.4f} {lon:9.4f} {elev:6.1f} {'':<2} {name:<30}"


def inventory_line(sid, lat, lon, element="PRCP", first=1950, last=2024):
    return f"{sid:<11} {lat:8.4f} {lon:9.4f} {element:<4} {first:4d} {last:4d}"


def write_raw_tree(root, stations, dly_text):
    """Write ghcnd-stations.txt, ghcnd-inventory.txt and dly/<id>.dly under `root`.

    `stations` is a list of (id, lat, lon, elev, name); `dly_text` maps id -> full file text."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "dly").mkdir(exist_ok=True)
    (root / "ghcnd-stations.txt").write_text(
        "\n".join(station_line(*s) for s in stations) + "\n", encoding="ascii")
    (root / "ghcnd-inventory.txt").write_text(
        "\n".join(inventory_line(s[0], s[1], s[2]) for s in stations) + "\n", encoding="ascii")
    for sid, text in dly_text.items():
        (root / "dly" / f"{sid}.dly").write_text(text, encoding="ascii")
    return root


def month_lines(station, year, values_by_month):
    """One .dly line per (month -> list of mm values) so a whole year can be written."""
    lines = []
    for month, vals in values_by_month.items():
        days = {d + 1: (round(v * 10), " ") for d, v in enumerate(vals) if v is not None}
        lines.append(dly_line(station, year, month, days=days))
    return "\n".join(lines) + "\n"


def synthetic_set(values: dict, *, start="2000-01-01", meta_rows=None, flags=None) -> StationSet:
    """A StationSet from {station: array}; station ids sorted; lat/lon/elevation taken from
    `meta_rows` ({id: (lat, lon, elev)}) or spread on a small grid."""
    ids = sorted(values)
    n = len(next(iter(values.values())))
    index = pd.date_range(start, periods=n, freq="D").as_unit("ns")
    frame = pd.DataFrame({sid: np.asarray(values[sid], dtype=np.float32) for sid in ids}, index=index)
    flag_frame = pd.DataFrame({sid: np.full(n, "", dtype=object) for sid in ids}, index=index)
    for sid, updates in (flags or {}).items():
        for i, flag in updates.items():
            flag_frame.iloc[i, flag_frame.columns.get_loc(sid)] = flag
    rows = []
    for k, sid in enumerate(ids):
        lat, lon, elev = (meta_rows or {}).get(sid, (20.0 + 0.1 * k, 75.0, 100.0 * k))
        rows.append({"id": sid, "name": f"S{k}", "lat": lat, "lon": lon, "elevation_m": elev,
                     "country": sid[:2], "region": "western_ghats", "upland": elev >= 500})
    return StationSet(values=frame, flags=flag_frame, meta=pd.DataFrame(rows))


def days_in_year(year):
    return 366 if calendar.isleap(year) else 365


def synthetic_raw_years(tmp_path, n_stations=10, years=range(2007, 2013), seed=0, lat0=11.5, dlat=0.05, lon=76.25):
    """A .dly tree of full years of random rain for stations ~5 km apart around (lat0, lon)."""
    rng = np.random.default_rng(seed)
    stations, texts = [], {}
    for k in range(n_stations):
        sid = f"IN{k:09d}"
        stations.append((sid, lat0 + dlat * k, lon, 100.0 + 120.0 * k, f"STATION {k}"))
        text = ""
        for year in years:
            months = {}
            for month, days in enumerate([31, 29 if calendar.isleap(year) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31], 1):
                wet = rng.random(days) < 0.45
                months[month] = list(np.where(wet, np.round(rng.gamma(0.8, 9.0, days) + 1.0, 1), 0.0))
            text += month_lines(sid, year, months)
        texts[sid] = text
    return write_raw_tree(tmp_path / "ghcnd", stations, texts)


def write_toy_rain_store(root, years=range(2007, 2013), seed=1):
    """Toy IMD / CHIRPS / POWER stores around (11.5 N, 76.25 E): IMD points (18..23, 36..43) covered, CHIRPS window
    rows 760..779 x cols 5120..5139 (all days of `years`), POWER 4 x 4 MERRA-2 points."""
    import json
    rng = np.random.default_rng(seed)
    root.mkdir(parents=True, exist_ok=True)
    mask = np.zeros((129, 135), dtype=bool)
    mask[18:24, 36:44] = True
    np.save(root / "imd_coverage_mask.npy", mask)
    imd_years, chirps_days, all_dates = {}, {}, []
    for year in years:
        n = days_in_year(year)
        data = np.full((n, 129, 135), np.nan, dtype=np.float32)
        data[:, 18:24, 36:44] = rng.gamma(0.6, 9.0, (n, 6, 8)).astype(np.float32)
        np.save(root / f"imd_{year}.npy", data)
        imd_years[str(year)] = {"file": f"imd_{year}.npy"}
        stamps = [str(d.date()) for d in pd.date_range(f"{year}-01-01", periods=n)]
        np.save(root / f"chirps_{year}.npy", rng.gamma(0.6, 9.0, (n, 20, 20)).astype(np.float16))
        (root / f"chirps_{year}_dates.json").write_text(json.dumps(stamps), encoding="utf-8")
        chirps_days[str(year)] = n
        all_dates += stamps
    (root / "imd_index.json").write_text(json.dumps({"years": imd_years, "covered_cells": int(mask.sum()),
                                                     "coverage_mask": "imd_coverage_mask.npy"}), encoding="utf-8")
    (root / "chirps_index.json").write_text(json.dumps({"missing_dates": [], "days_per_year": chirps_days,
                                                        "rows": 20, "cols": 20, "row_off": 760, "col_off": 5120}),
                                            encoding="utf-8")
    nd = len(all_dates)
    np.savez_compressed(root / "power_wetness.npz",
                        GWETTOP=rng.random((nd, 4, 4)).astype(np.float32),
                        GWETROOT=rng.random((nd, 4, 4)).astype(np.float32),
                        lat=np.array([11.0, 11.5, 12.0, 12.5]), lon=np.array([75.625, 76.25, 76.875, 77.5]),
                        dates=np.array(all_dates, dtype="U10"))



def synthetic_rain(n, seed, wet=0.45, scale=9.0):
    rng = np.random.default_rng(seed)
    return np.where(rng.random(n) < wet, np.round(rng.gamma(0.8, scale, n) + 1.0, 1), 0.0).astype(np.float32)


def make_engine_world(n_stations=8, years=5, seed=0):
    """A small end-to-end world: stations, splits, fault table, grid references, wide neighbours and features."""
    from aetherguard.integrity import evaluate, features, inject, neighbours
    from aetherguard.integrity.grids import SOURCES, GridRefs
    n = 365 * years + 1
    data = {f"IN{k:09d}": synthetic_rain(n, seed + k) for k in range(n_stations)}
    for k in (0, 7):
        data[f"IN{k:09d}"][700:712] = np.nan                    # a gap run in two stations
    sset = synthetic_set(data, start="2007-01-01")
    ids = list(sset.meta["id"])
    splits = {"train": ids[:5], "val": ids[5:7], "test": ids[7:]}
    table = inject.build_fault_dataset(sset, splits, seed=3, density=0.15, min_valid_days=150)
    obs = evaluate.to_matrices(table).value_obs[ids]
    rng = np.random.default_rng(seed + 99)
    true = sset.values.to_numpy()
    frames = {}
    for name in SOURCES:
        arr = np.maximum(true * rng.uniform(0.7, 1.3, true.shape) + rng.normal(0, 1.0, true.shape), 0).astype(np.float32)
        if name == "chirps_aligned":
            arr[rng.random(arr.shape) < 0.3] = np.nan
        if name.startswith("gw_"):
            arr = rng.random(arr.shape).astype(np.float32)
        frames[name] = pd.DataFrame(arr, index=sset.values.index, columns=ids)
    refs = GridRefs(frames)
    wide = neighbours.neighbour_table(sset.meta, 10, 300)
    feats = features.build_features(obs, obs.index, sset.meta, refs, wide)
    return {"sset": sset, "ids": ids, "splits": splits, "table": table, "obs": obs, "refs": refs, "wide": wide,
            "feats": feats}
