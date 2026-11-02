"""Case-study inputs (Kerala 2018, Wayanad 2024): one tidy table per case from the frozen feature files, the integrity
and corrector tables, the nearest station observation (out-of-fold engine trust) and the ERA5 point series.

    python -m aetherguard.cases.series [--fetch/--no-fetch]

Outputs in data/processed/cases/: `<case>_inputs.parquet`, `wayanad_2024_focus_table.parquet`,
`era5_<point>_<model>_daily.parquet`, and reports/phase3e_case_inputs.md/.json (ERA5 numbers, D5 approximation error,
focus-point table, API usage). The frozen feature files are only read.
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import data_root
from ..grid import cell_center, latlon_to_cell
from ..integrity import hazard_features as hf
from ..integrity.common import display_path, dumps_strict, integrity_dir, reports_dir
from ..integrity.neighbours import haversine_km
from ..integrity.stations import StationSet, load_station_set
from . import openmeteo as om

CASES = {
    "kerala_2018": {"features": "case_kerala_2018_samples", "window": ("2018-08-01", "2018-08-20")},
    "wayanad_2024": {"features": "case_wayanad_2024_samples", "window": ("2024-07-15", "2024-08-05")},
}
FOCUS_DATES = ("2024-07-25", "2024-08-02")
FAR_KM = 300.0
KEY_COLUMNS = ["cell_id", "date", "region", "lat", "lon", "rain_source", "is_positive_cell_day"]
INPUT_COLUMNS = (["rain_acc_1", "rain_acc_3", "rain_acc_7"]
                 + [f"src_imd_acc_{n}" for n in (1, 3, 7)] + [f"src_chi_acc_{n}" for n in (1, 3, 7)]
                 + ["corr_q50_1", "corr_q90_1", "corr_q99_1", "corr_p_exceed99", "integ_trw_rain_1"]
                 + ["wet_top", "wet_root", "wet_top_chg3", "wet_top_chg7", "wet_root_chg3", "wet_root_chg7"])
NEAREST_COLUMNS = ["near_station", "near_dist_km", "near_value_mm", "near_trust", "near_flagged", "near_genuine"]
ERA5_COLUMNS = ["focus_point", "era5_utc_mm", "era5_imd_exact_mm", "era5_imd_d5_mm", "era5_land_utc_mm",
                "era5_land_imd_exact_mm", "era5_land_imd_d5_mm"]


def features_dir() -> Path:
    return data_root() / "processed" / "features"


def cases_dir() -> Path:
    path = data_root() / "processed" / "cases"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _read_aligned(directory: Path, name: str, base: pd.DataFrame) -> pd.DataFrame:
    table = pd.read_parquet(directory / name)
    if not table[["cell_id", "date"]].equals(base[["cell_id", "date"]]):
        raise ValueError(f"{name}: keys / row order differ from the features file")
    return table.drop(columns=["cell_id", "date"])


def load_case_frame(case: str, directory=None) -> pd.DataFrame:
    """The frozen features of a case joined (by identical keys and row order) with its integ_ and corr_ columns: the frame
    a hazard scorer takes."""
    spec = CASES[case]
    directory = Path(directory) if directory is not None else features_dir()
    base = pd.read_parquet(directory / f"{spec['features']}_features.parquet")
    integ = _read_aligned(directory / "integ", f"{spec['features']}_integ.parquet", base)
    corr = _read_aligned(directory / "corrector", f"{spec['features']}_corr.parquet", base)
    return pd.concat([base, integ, corr], axis=1)


def nearest_station(sd: hf.StationDays, lat, lon, dates, chunk_rows: int = 20_000) -> pd.DataFrame:
    """Per row the nearest station with an observed value on that day (within 300 km), with its out-of-fold trust.

    Columns: near_station (id or ''), near_dist_km, near_value_mm, near_trust (NaN when unobserved), near_flagged,
    near_genuine. All NaN / '' / False when no station qualifies."""
    lat, lon = np.asarray(lat, float), np.asarray(lon, float)
    day = sd.index.get_indexer(pd.DatetimeIndex(dates))
    if (day < 0).any():
        raise ValueError("some dates are outside the station-day index")
    observed = np.isfinite(sd.value)
    cells, inverse = np.unique(np.stack([lat, lon], axis=1), axis=0, return_inverse=True)
    inverse = np.asarray(inverse).ravel()
    dist = haversine_km(cells[:, [0]], cells[:, [1]], sd.lat[None, :], sd.lon[None, :])
    n = len(day)
    out = {"near_station": np.full(n, "", dtype=object), "near_dist_km": np.full(n, np.nan), "near_value_mm": np.full(n, np.nan),
           "near_trust": np.full(n, np.nan), "near_flagged": np.zeros(n, bool), "near_genuine": np.zeros(n, bool)}
    ids = np.asarray(sd.ids, dtype=object)
    for lo in range(0, n, chunk_rows):
        sel = slice(lo, lo + chunk_rows)
        t = day[sel]
        masked = np.where(observed[t], dist[inverse[sel]], np.inf)
        j = masked.argmin(axis=1)
        d = masked[np.arange(len(j)), j]
        ok = d <= FAR_KM
        rows = np.arange(lo, min(lo + chunk_rows, n))
        out["near_station"][rows[ok]] = ids[j[ok]]
        out["near_dist_km"][rows[ok]] = d[ok]
        out["near_value_mm"][rows[ok]] = sd.value[t[ok], j[ok]]
        out["near_trust"][rows[ok]] = sd.trust[t[ok], j[ok]]
        out["near_flagged"][rows[ok]] = sd.flagged[t[ok], j[ok]]
        out["near_genuine"][rows[ok]] = sd.genuine[t[ok], j[ok]]
    return pd.DataFrame(out)


def attach_era5(table: pd.DataFrame, focus: list[dict], daily: dict) -> pd.DataFrame:
    """Add the ERA5 columns: on the rows of a focus cell the point series of that cell (NaN elsewhere).

    `focus` lists {"name", "cell_id"}; `daily` is the {(point, model): daily table} of `openmeteo.fetch_series`."""
    out = table.copy()
    out["focus_point"] = ""
    for column in ERA5_COLUMNS[1:]:
        out[column] = np.nan
    mapping = {"era5": ("era5_utc_mm", "era5_imd_exact_mm", "era5_imd_d5_mm"),
               "era5_land": ("era5_land_utc_mm", "era5_land_imd_exact_mm", "era5_land_imd_d5_mm")}
    for point in focus:
        rows = out["cell_id"].to_numpy() == point["cell_id"]
        out.loc[rows, "focus_point"] = point["name"]
        for model, (c_utc, c_exact, c_d5) in mapping.items():
            table_ = daily.get((point["name"], model))
            if table_ is None:
                continue
            aligned = table_.reindex(pd.DatetimeIndex(out.loc[rows, "date"]))
            out.loc[rows, c_utc] = aligned["utc_day_mm"].to_numpy()
            out.loc[rows, c_exact] = aligned["imd_exact_mm"].to_numpy()
            out.loc[rows, c_d5] = aligned["imd_d5_mm"].to_numpy()
    return out


def case_inputs(case: str, sd: hf.StationDays, focus: list[dict], daily: dict, directory=None) -> pd.DataFrame:
    """The tidy per-cell-day input table of a case (see the module doc)."""
    frame = load_case_frame(case, directory)
    keys = [c for c in KEY_COLUMNS if c in frame.columns]
    table = frame[keys + INPUT_COLUMNS].copy()
    table = pd.concat([table, nearest_station(sd, frame["lat"], frame["lon"], frame["date"])], axis=1)
    return attach_era5(table, focus, daily)


def focus_cell(frame: pd.DataFrame, lat: float, lon: float) -> tuple[int, float]:
    """(cell id, distance km) of the case cell that contains the point, else the nearest case cell."""
    exact = int(latlon_to_cell(lat, lon))
    cells = frame["cell_id"].unique()
    if exact in cells:
        return exact, float(haversine_km(lat, lon, *cell_center(exact)))
    lats, lons = cell_center(cells)
    d = haversine_km(lat, lon, lats, lons)
    return int(cells[int(np.argmin(d))]), float(d.min())


def focus_table(inputs: pd.DataFrame, cell_id: int, daily: dict, point_name: str, chirps_utc: pd.Series | None,
                dates=FOCUS_DATES) -> pd.DataFrame:
    """Per-day Wayanad comparison at the focus cell: IMD vs CHIRPS (UTC and aligned) vs ERA5 (UTC, IMD-day exact and D5,
    ERA5-Land) vs the corrector vs the nearest station."""
    rows = inputs[inputs["cell_id"] == cell_id].set_index("date").sort_index().loc[dates[0]:dates[1]]
    out = pd.DataFrame(index=rows.index)
    out["imd_mm"] = rows["src_imd_acc_1"]
    out["chirps_aligned_mm"] = rows["src_chi_acc_1"]
    out["chirps_utc_mm"] = chirps_utc.reindex(rows.index) if chirps_utc is not None else np.nan
    for model, prefix in (("era5", "era5"), ("era5_land", "era5_land")):
        table = daily.get((point_name, model))
        for source, column in (("utc_day_mm", f"{prefix}_utc_mm"), ("imd_exact_mm", f"{prefix}_imd_exact_mm"),
                               ("imd_d5_mm", f"{prefix}_imd_d5_mm")):
            out[column] = table[source].reindex(rows.index) if table is not None else np.nan
    for column in ("corr_q50_1", "corr_q90_1", "corr_q99_1", "corr_p_exceed99", "integ_trw_rain_1") + tuple(NEAREST_COLUMNS):
        out[column] = rows[column]
    out.index.name = "date"
    return out


def _station_inputs(raw_dir=None):
    window = load_station_set(raw_dir, start=hf.ENGINE_PERIOD[0], end=hf.ENGINE_PERIOD[1])
    oof = pd.read_parquet(integrity_dir() / "engine_outputs_2007_oof.parquet")
    return window, hf.station_days(oof, window.values, window.meta)


def build_all(raw_dir=None, fetch=True, directory=None, station_data=None, fetch_fn=None, manifest=None,
              chirps_series=None) -> dict:
    """Fetch (or reuse) the ERA5 series, write both input tables, the focus table and the ERA5 summary."""
    started = time.perf_counter()
    kerala_frame = load_case_frame("kerala_2018", directory)
    points = [om.WAYANAD, *om.kerala_points(kerala_frame)]
    kwargs = {"manifest": manifest}
    if fetch_fn is not None:
        kwargs["fetch"] = fetch_fn
    series = om.fetch_series(points, **kwargs)
    daily = series["daily"]
    sd = (station_data or _station_inputs(raw_dir))[1]
    out_dir = cases_dir()
    results, summaries = {}, {}
    wayanad_frame = load_case_frame("wayanad_2024", directory)
    way_cell, way_distance = focus_cell(wayanad_frame, om.WAYANAD["lat"], om.WAYANAD["lon"])
    focus = {"kerala_2018": [{"name": p["name"], "cell_id": p["cell_id"]} for p in points[1:]],
             "wayanad_2024": [{"name": om.WAYANAD["name"], "cell_id": way_cell}]}
    for case in CASES:
        table = case_inputs(case, sd, focus[case], daily, directory)
        table.to_parquet(out_dir / f"{case}_inputs.parquet", index=False)
        results[case] = table
    chirps = chirps_series if chirps_series is not None else _chirps_utc_series(way_cell)
    focus_frame = focus_table(results["wayanad_2024"], way_cell, daily, om.WAYANAD["name"], chirps)
    focus_frame.to_parquet(out_dir / "wayanad_2024_focus_table.parquet")
    for (name, model), table in daily.items():
        summaries[f"{name}|{model}"] = om.approximation_error(table)
    usage = series["usage"]
    return {"points": points, "wayanad_focus_cell": {"cell_id": way_cell, "distance_to_point_km": way_distance},
            "daily": daily, "unavailable": {f"{k[0]}|{k[1]}": v for k, v in series["unavailable"].items()},
            "d5_error": summaries, "focus_table": focus_frame, "inputs": results,
            "usage": {"calls": usage.calls, "weight": usage.weight, "cached": usage.cached, "failures": usage.failures,
                      "free_tier_calls_per_day": om.FREE_CALLS_PER_DAY, "all_time": om.cache_summary()},
            "runtime_seconds": round(time.perf_counter() - started, 1)}


def _chirps_utc_series(cell_id: int) -> pd.Series:
    """CHIRPS UTC-day values at the focus cell over the focus window (raw, before alignment)."""
    from ..integrity.grids import default_rain_dir
    from ..ingest.chirps import ChirpsStore
    store = ChirpsStore(default_rain_dir())
    days = pd.date_range(*FOCUS_DATES)
    return pd.Series(store.cell_series(cell_id, days[0], days[-1]), index=days.as_unit("ns"))


# ----------------------------------------------------------------------------------------------- report

def _f(x, d=1):
    return "n/a" if x is None or (isinstance(x, float) and not np.isfinite(x)) else f"{x:.{d}f}"


def era5_day_rows(daily: dict, name: str, dates) -> list[dict]:
    rows = []
    for date in dates:
        row = {"date": date}
        for model in ("era5", "era5_land"):
            table = daily.get((name, model))
            if table is not None and pd.Timestamp(date) in table.index:
                r = table.loc[pd.Timestamp(date)]
                row[model] = {"utc_day_mm": float(r["utc_day_mm"]), "imd_exact_mm": float(r["imd_exact_mm"]),
                              "imd_d5_mm": float(r["imd_d5_mm"])}
        rows.append(row)
    return rows


def build_report(result: dict) -> dict:
    daily = result["daily"]
    way = om.WAYANAD["name"]
    report = {"era5_wayanad": era5_day_rows(daily, way, ["2024-07-29", "2024-07-30", "2024-07-31"]),
              "era5_kerala": {p["name"]: {"cell_id": p["cell_id"], "lat": p["lat"], "lon": p["lon"], "rain_acc_3_event": p["rain_acc_3"],
                                          "event_date": p["event_date"],
                                          "days": era5_day_rows(daily, p["name"], ["2018-08-14", "2018-08-15", "2018-08-16", "2018-08-17"])}
                              for p in result["points"][1:]},
              "d5_error": result["d5_error"], "unavailable": result["unavailable"], "usage": result["usage"],
              "wayanad_focus_cell": result["wayanad_focus_cell"],
              "focus_table": result["focus_table"].reset_index().assign(date=lambda t: t["date"].dt.strftime("%Y-%m-%d")).to_dict("records"),
              "points": result["points"], "runtime_seconds": result["runtime_seconds"],
              "notes": ["Open-Meteo hourly precipitation is stamped by the PRECEDING hour; UTC day D = stamps 01:00 D..00:00 D+1, "
                        "IMD day D = stamps 04:00 D-1..03:00 D (exact), D5 = 0.875 UTC(D-1) + 0.125 UTC(D).",
                        "ERA5 / ERA5-Land are reanalysis point values (about 0.25 / 0.1 degree cells), not gauge data.",
                        "Licence: Open-Meteo CC BY 4.0; ERA5 / ERA5-Land Copernicus (CC BY 4.0)."]}
    return report


def render_markdown(report: dict) -> str:
    lines = ["# Phase 3e preparation - case-study inputs", "",
             "Point series from the Open-Meteo ERA5 archive (timezone=GMT, hourly precipitation, preceding-hour stamps).", "",
             f"## Wayanad point ({om.WAYANAD['lat']} N, {om.WAYANAD['lon']} E): UTC day vs IMD day (mm)", "",
             "| date | ERA5 UTC day | ERA5 IMD day (exact) | ERA5 IMD day (D5 approx.) | ERA5-Land UTC | ERA5-Land IMD (exact) | ERA5-Land D5 |",
             "|---|---|---|---|---|---|---|"]
    for row in report["era5_wayanad"]:
        e, l = row.get("era5", {}), row.get("era5_land", {})
        lines.append(f"| {row['date']} | {_f(e.get('utc_day_mm'))} | {_f(e.get('imd_exact_mm'))} | {_f(e.get('imd_d5_mm'))} | "
                     f"{_f(l.get('utc_day_mm'))} | {_f(l.get('imd_exact_mm'))} | {_f(l.get('imd_d5_mm'))} |")
    lines += ["", "## Kerala 2018 points (three wettest positive cells on 15-16 Aug): ERA5 UTC vs IMD-day (mm)", "",
              "| point | lat, lon | event | date | UTC day | IMD day exact | D5 |", "|---|---|---|---|---|---|---|"]
    for name, p in report["era5_kerala"].items():
        for row in p["days"]:
            e = row.get("era5", {})
            lines.append(f"| {name} | {p['lat']:.3f}, {p['lon']:.3f} | {p['event_date']} | {row['date']} | {_f(e.get('utc_day_mm'))} | "
                         f"{_f(e.get('imd_exact_mm'))} | {_f(e.get('imd_d5_mm'))} |")
    lines += ["", "## D5 approximation error vs the exact IMD-day total (whole windows)", "",
              "| point | model | days | mean abs err mm | max abs err mm | bias mm | heavy days (>= 10 mm) | heavy mean rel. err | worst day |",
              "|---|---|---|---|---|---|---|---|---|"]
    for key, e in report["d5_error"].items():
        name, model = key.split("|")
        worst = e["worst_days"][0] if e.get("worst_days") else None
        lines.append(f"| {name} | {model} | {e['days']} | {_f(e.get('mean_abs_error_mm'), 2)} | {_f(e.get('max_abs_error_mm'), 1)} | "
                     f"{_f(e.get('mean_error_mm'), 2)} | {e.get('heavy_days', 0)} | {_f(e.get('heavy_mean_abs_relative_error'), 3)} | "
                     f"{worst['date'] + ': exact ' + _f(worst['exact_mm']) + ', D5 ' + _f(worst['d5_mm']) if worst else 'n/a'} |")
    if report["unavailable"]:
        lines += ["", "Unavailable: " + "; ".join(f"{k}: {v}" for k, v in report["unavailable"].items())]
    focus = report["focus_table"]
    way = report["wayanad_focus_cell"]
    lines += ["", f"## Wayanad focus cell {way['cell_id']} ({_f(way['distance_to_point_km'], 1)} km from the point): daily comparison (mm)", "",
              "| date | IMD | CHIRPS aligned | CHIRPS UTC | ERA5 UTC | ERA5 IMD exact | ERA5 D5 | ERA5-Land IMD exact | corr q50 | q90 | q99 | "
              "nearest station (km) | its mm | trust |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in focus:
        lines.append(f"| {r['date']} | {_f(r['imd_mm'])} | {_f(r['chirps_aligned_mm'])} | {_f(r['chirps_utc_mm'])} | {_f(r['era5_utc_mm'])} | "
                     f"{_f(r['era5_imd_exact_mm'])} | {_f(r['era5_imd_d5_mm'])} | {_f(r['era5_land_imd_exact_mm'])} | {_f(r['corr_q50_1'])} | "
                     f"{_f(r['corr_q90_1'])} | {_f(r['corr_q99_1'])} | {r['near_station'] or 'none'} ({_f(r['near_dist_km'], 0)}) | "
                     f"{_f(r['near_value_mm'])} | {_f(r['near_trust'], 2)} |")
    u = report["usage"]
    total = u["all_time"]
    lines += ["", f"API use: this run {u['calls']} calls (weight {_f(u['weight'], 2)}), {u['cached']} responses from the cache; "
              f"all time {total['cached_responses']} cached responses = {total['cached_responses']} calls, free-tier weight "
              f"{_f(total['total_weight'], 2)} of {u['free_tier_calls_per_day']} per day.", ""]
    lines += [f"- {n}" for n in report["notes"]] + [""]
    return "\n".join(lines)


def write_report(report: dict, out_dir=None) -> tuple[Path, Path]:
    out = Path(out_dir) if out_dir is not None else reports_dir()
    out.mkdir(parents=True, exist_ok=True)
    md, js = out / "phase3e_case_inputs.md", out / "phase3e_case_inputs.json"
    js.write_text(dumps_strict(report), encoding="utf-8", newline="\n")
    md.write_text(render_markdown(report), encoding="utf-8", newline="\n")
    return md, js


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw-dir", default=None)
    parser.add_argument("--reports-dir", default=None)
    args = parser.parse_args(argv)
    result = build_all(args.raw_dir)
    report = build_report(result)
    md, js = write_report(report, args.reports_dir)
    print(f"wrote {display_path(md)} and {display_path(js)}; API calls {result['usage']['calls']} "
          f"(weight {result['usage']['weight']:.2f}), cached {result['usage']['cached']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
