"""W7 study: can the forecast leads be scored by v4, and how do candidate lead models compare (development and archive data).

    python -m aetherguard.live.leads_v4_study measure [--out-dir DIR]
    python -m aetherguard.live.leads_v4_study fit     [--out FILE]

measure  Task 1 of docs/superpowers/specs/2026-11-14-aetherguard-leads-v4.md. Pairs the day maps a forecast lead would read
         (`lead_intensity`: 3-hourly GFS for the days after D, the truncated IMERG Early day for D) with the complete IMERG Late
         day maps of the same IMD day, on every day both exist:
           * GFS archive (00Z cycle of D, forecast days D+1 and D+2) against Late, June-September of the archive years held;
           * GFS live raw files (00Z cycles kept by the daily run since 2026-10-14) against Late;
           * the Early live window (first 44 half-hours) of day D against Late, 2024 (June-September) and the development years
             fetched for the fit.
         Per (source, day offset, field, region): pairs, means, the ratio of means, the frequency-matched quantiles (p50, p90,
         p99 of each side's own values) and their ratio, Pearson correlation, and the mean forecast where Late is at least
         10 mm (max3h). Pixels are those of the two scored regions. Writes `<out-dir>/phase8_leads_v4_measure.json` and the
         pairs of the fit seasons (`<out-dir>/lead_intensity_pairs.npz`, scratch; never committed).
fit      Quantile maps (`lead_intensity.fit_maps`) from the pairs of the fit seasons only: GFS on June-September 2021 (the first
         archive season; GFS has no archive in the development years), Early on June-September of the development years
         fetched (2016, 2017). The other seasons are never used by the fit.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from ..config import PROJECT_ROOT, data_root, load_config_file
from ..features import imerg_intensity as ii
from ..hazard.jsonio import dump_json
from . import forecast_map as fm
from . import lead_intensity as li

UTC = timezone.utc
SEASON = (6, 7, 8, 9)
GFS_YEARS = (2021, 2022, 2023, 2024)
GFS_FIT_YEARS = (2021,)
EARLY_YEARS = (2016, 2017, 2024)
EARLY_FIT_YEARS = (2016, 2017)
LIVE_FIRST, LIVE_LAST = date(2026, 10, 14), date(2026, 11, 14)
QUANTILES = (50, 90, 99)
HEAVY_MM = 10.0
REST_STRIDE = 10                      # every 10th pixel outside the regions enters the fit (the `rest` curve only)


def study_root() -> Path:
    return data_root() / "processed" / "lead_intensity" / "imerg_hh"


def late_day(day: date) -> dict | None:
    """Late day maps from the study root (days fetched for this study) or the frozen intensity store."""
    return ii.load_day(study_root(), li.LATE, day) or ii.load_day(ii.default_root(), li.LATE, day)


def early_day(day: date) -> dict | None:
    return ii.load_day(study_root(), li.EARLY, day) or ii.load_day(ii.default_root(), li.EARLY, day)


def season_days(year: int) -> list[date]:
    first, last = date(year, SEASON[0], 1), date(year, SEASON[-1], 30)
    return [first + timedelta(days=n) for n in range((last - first).days + 1)]


class Pairs:
    """(forecast, observed, region) values per (source, offset, field), on the region pixels (and a stride of the rest)."""

    def __init__(self, pixel_region: np.ndarray) -> None:
        self.region = np.asarray(pixel_region, dtype=object)
        regional = np.isin(self.region, fm.REGIONS)
        rest = np.flatnonzero(~regional)[::REST_STRIDE]
        self.pixels = np.sort(np.concatenate([np.flatnonzero(regional), rest]))
        self.labels = self.region[self.pixels]
        self.data: dict[tuple, list] = {}
        self.days: dict[tuple, list[str]] = {}

    def add(self, key: tuple, day: date, forecast: dict, observed: dict) -> None:
        source, offset, year = key
        for field in ii.FIELDS:
            f, o = forecast[field].ravel()[self.pixels], observed[field].ravel()[self.pixels]
            self.data.setdefault((source, offset, year, field), []).append((f.astype(np.float32), o.astype(np.float32)))
        self.days.setdefault(key, []).append(day.isoformat())

    def arrays(self, source: str, offset: int, years, field: str):
        parts = [p for y in years for p in self.data.get((source, offset, y, field), [])]
        if not parts:
            return None
        f = np.concatenate([p[0] for p in parts])
        o = np.concatenate([p[1] for p in parts])
        return f, o, np.tile(self.labels, len(parts))


def _stats(f: np.ndarray, o: np.ndarray, field: str) -> dict:
    ok = np.isfinite(f) & np.isfinite(o)
    f, o = f[ok].astype(np.float64), o[ok].astype(np.float64)
    if not f.size:
        return {"pairs": 0}
    out = {"pairs": int(f.size), "mean_late": float(o.mean()), "mean_forecast": float(f.mean()),
           "ratio_of_means": float(f.mean() / o.mean()) if o.mean() > 0 else None,
           "correlation": float(np.corrcoef(f, o)[0, 1]) if f.std() > 0 and o.std() > 0 else None}
    for q in QUANTILES:
        qo, qf = float(np.percentile(o, q)), float(np.percentile(f, q))
        out[f"p{q}_late"], out[f"p{q}_forecast"] = qo, qf
        out[f"p{q}_ratio"] = qf / qo if qo > 0 else None
    if field != "wet_hours":
        heavy = o >= HEAVY_MM
        out["late_at_least_10mm"] = {"pairs": int(heavy.sum()), "mean_late": float(o[heavy].mean()) if heavy.any() else None,
                                     "mean_forecast": float(f[heavy].mean()) if heavy.any() else None}
    return out


def collect(cfg: dict, pixel_region: np.ndarray, progress=print) -> Pairs:
    pairs = Pairs(pixel_region)
    store = li.default_store()
    for year in GFS_YEARS:
        for day in season_days(year):
            stored = li.load_store_day(store, day)
            if stored is None:
                continue
            for offset in (1, 2):
                target = day + timedelta(days=offset)
                forecast, observed = li.day_maps_on_grid(stored, target), late_day(target)
                if forecast is not None and observed is not None:
                    pairs.add(("gfs3h_archive", offset, year), target, forecast, observed)
        progress(f"gfs archive {year}: {len(pairs.days.get(('gfs3h_archive', 1, year), []))} issue days")
    for n in range((LIVE_LAST - LIVE_FIRST).days + 1):
        day = LIVE_FIRST + timedelta(days=n)
        cycle = datetime(day.year, day.month, day.day, 0, tzinfo=UTC)
        stored = li.live_raw_day(data_root(), day, cycle, cfg["domain_bbox"])
        for offset in (1, 2):
            target = day + timedelta(days=offset)
            forecast, observed = li.day_maps_on_grid(stored, target), late_day(target)
            if forecast is not None and observed is not None:
                pairs.add(("gfs3h_live", offset, 2026), target, forecast, observed)
    progress(f"gfs live 2026: {len(pairs.days.get(('gfs3h_live', 1, 2026), []))} issue days")
    early_days = [(y, d) for y in EARLY_YEARS for d in season_days(y)]
    early_days += [(2026, LIVE_FIRST + timedelta(days=n)) for n in range((LIVE_LAST - LIVE_FIRST).days + 1)]
    for year, day in early_days:
        forecast, observed = early_day(day), late_day(day)
        if forecast is not None and observed is not None:
            pairs.add(("early_live", 0, year), day, forecast, observed)
    progress("early: " + ", ".join(f"{y} {len(pairs.days.get(('early_live', 0, y), []))}" for y in (*EARLY_YEARS, 2026)))
    return pairs


def summarize(pairs: Pairs) -> dict:
    out: dict = {}
    for (source, offset, year), days in sorted(pairs.days.items()):
        entry = out.setdefault(source, {}).setdefault(str(offset), {}).setdefault(str(year), {"days": len(days),
                                                                                                "first": min(days),
                                                                                                "last": max(days)})
        for field in ii.FIELDS:
            f, o, regions = pairs.arrays(source, offset, (year,), field)
            entry[field] = {region: _stats(f[regions == region], o[regions == region], field) for region in fm.REGIONS}
    return out


def inventory() -> dict:
    """What history exists to build and test forecast-lead intensity (counted on disk)."""
    root = data_root()
    raw = root / "raw" / "gfs"
    archive = sorted(p for p in (raw / "archive").iterdir() if p.is_dir()) if (raw / "archive").is_dir() else []
    live = sorted(p for p in (raw / "live").iterdir() if p.is_dir()) if (raw / "live").is_dir() else []
    rain = root / "processed" / "rain"
    ecmwf_days = sorted(p.stem.rsplit("_", 1)[-1] for p in rain.glob("ecmwf_imdday_*.npz"))
    keys = []
    if ecmwf_days:
        with np.load(rain / f"ecmwf_imdday_{ecmwf_days[-1]}.npz", allow_pickle=False) as data:
            keys = sorted(data.files)
    hh = {}
    for store_root, label in ((ii.default_root(), "intensity_store"), (study_root(), "study_store")):
        for run_dir in sorted(p for p in Path(store_root).iterdir() if p.is_dir()) if Path(store_root).is_dir() else []:
            for year_dir in sorted(p for p in run_dir.iterdir() if p.is_dir()):
                files = sorted(year_dir.glob("*.npz"))
                if files:
                    hh.setdefault(label, {}).setdefault(run_dir.name, {})[year_dir.name] = {
                        "days": len(files), "first": files[0].stem, "last": files[-1].stem}
    store = li.default_store()
    gfs3h = {y.name: len(list(y.glob("*.npz"))) for y in sorted(store.iterdir()) if y.is_dir()} if store.is_dir() else {}
    return {
        "gfs_archive": {"cycles": len(archive), "first": archive[0].name if archive else None,
                        "last": archive[-1].name if archive else None,
                        "hours_kept": sorted({p.name for c in archive[:5] for p in c.glob("*.grib2")}),
                        "note": "the archive fetch keeps only the IMD-day boundary hours: no sub-daily rain"},
        "gfs_live_raw": {"cycles": len(live), "first": live[0].name if live else None, "last": live[-1].name if live else None,
                         "hours_kept_newest": len(list(live[-1].glob("*.grib2"))) if live else 0,
                         "note": "3-hourly cumulative APCP f003..f096 per cycle (NOMADS grib filter, domain crop)"},
        "ecmwf_day_files": {"days": len(ecmwf_days), "by_year": {y: sum(d.startswith(y) for d in ecmwf_days)
                                                                  for y in sorted({d[:4] for d in ecmwf_days})},
                            "keys": keys, "members_kept": any(k.startswith("ens_member") for k in keys),
                            "note": "IMD-day totals only: HRES and the ensemble mean / p10 / p50 / p90; members and sub-daily steps not kept"},
        "imerg_halfhourly": hh,
        "gfs3h_store": {"by_year": gfs3h, "note": "this study's 3-hourly archive fetch (00Z, hours 3..51)"},
        "live_days": sorted(p.name for p in (root / "live").iterdir() if p.is_dir() and p.name[:2] == "20"),
    }


def run_measure(out_dir: Path) -> int:
    cfg = load_config_file(PROJECT_ROOT / "configs" / "live.yaml")
    run_cfg = load_config_file(PROJECT_ROOT / "configs" / "live_run.yaml")
    pixel_region = fm.pixel_regions_of(run_cfg)
    pairs = collect(cfg, pixel_region)
    payload = {"generated_utc": datetime.now(UTC).isoformat(timespec="seconds"), "inventory": inventory(),
               "regions": list(fm.REGIONS), "heavy_mm": HEAVY_MM, "quantiles": list(QUANTILES),
               "definitions": {
                   "forecast_maps": "GFS 3-hour blocks regridded bilinearly to 0.1 degree, then max3h, max6h (two consecutive blocks), "
                                    "wet_hours (3 h per block of at least 0.3 mm); max1h is the 3-hour maximum (no sub-3-hour step)",
                   "late_maps": "complete IMERG Late half-hourly days reduced by imerg_hh.reduce_day (rolling 1/3/6 h windows)",
                   "early_maps": "the first 44 IMERG Early half-hours of the day (what the 11:00 IST run has)",
                   "quantiles": "each side's own percentile over the pairs (frequency matched, not paired)"},
               "results": summarize(pairs)}
    out_dir.mkdir(parents=True, exist_ok=True)
    dump_json(out_dir / "phase8_leads_v4_measure.json", payload)
    fit_pairs = {}
    for source, offset, years in (("gfs3h_archive", 1, GFS_FIT_YEARS), ("gfs3h_archive", 2, GFS_FIT_YEARS),
                                  ("early_live", 0, EARLY_FIT_YEARS)):
        for field in ii.FIELDS:
            got = pairs.arrays(source, offset, years, field)
            if got is not None:
                fit_pairs[f"{source}|{offset}|{field}"] = got
    np.savez_compressed(out_dir / "lead_intensity_pairs.npz",
                        **{f"{k}|{part}": v[i] for k, v in fit_pairs.items() for i, part in enumerate(("f", "o", "r"))})
    print(f"wrote {out_dir / 'phase8_leads_v4_measure.json'}")
    return 0


def run_fit(pairs_path: Path, out: Path) -> int:
    run_cfg = load_config_file(PROJECT_ROOT / "configs" / "live_run.yaml")
    with np.load(pairs_path, allow_pickle=True) as data:
        keys = sorted({k.rsplit("|", 1)[0] for k in data.files})
        pairs = {}
        for key in keys:
            source, offset, field = key.split("|")
            kind = li.GFS if source.startswith("gfs3h") else li.EARLY
            pairs[(kind, int(offset), field)] = (data[f"{key}|f"], data[f"{key}|o"], data[f"{key}|r"])
    info = {"fit": {"gfs3h": {"years": list(GFS_FIT_YEARS), "months": list(SEASON)},
                    "early_live": {"years": list(EARLY_FIT_YEARS), "months": list(SEASON)}},
            "pairs": {f"{k[0]}:{k[2]}@{k[1]}": int(len(v[0])) for k, v in pairs.items()},
            "note": "frequency-matched quantile curves (forecast_map.fit_curve) per field, day offset and region"}
    maps = li.fit_maps(pairs, fm.pixel_regions_of(run_cfg), info)
    maps.save(out)
    print(f"wrote {out}: {len(maps.curves)} curves")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m aetherguard.live.leads_v4_study", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    measure = sub.add_parser("measure")
    measure.add_argument("--out-dir", type=Path, default=PROJECT_ROOT / "reports")
    fit = sub.add_parser("fit")
    fit.add_argument("--pairs", type=Path, required=True)
    fit.add_argument("--out", type=Path, default=data_root() / "processed" / "lead_intensity" / "intensity_maps.json")
    args = parser.parse_args(argv)
    if args.command == "measure":
        return run_measure(args.out_dir)
    return run_fit(args.pairs, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
