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
consistency  E1 of the spec (section 4): every June-September issue day of `--years` with a GFS 3-hour archive day and an
         Early live window of D, a seeded random sample of 2,536 candidate cells (no event location used), each lead and
         candidate (c incumbent, a, b, and the diagnostics a_oracle, a_raw) against the published v4 level of the target
         day from observed features (and the incumbent against the v3 one): agreement, within one, Warning+ / Emergency
         recall and precision, burden by level, calibration of lead risk against the later lead-0 risk, and day-bootstrap
         standard errors of the differences from the incumbent. Writes `<out-dir>/phase8_leads_v4_e1.json`.
replays  E2 of the spec: the replayed sets c, a, b (tools/leads_v4_replays.sh) compared lead by lead with the same set's
         replayed lead 0 of the target day, plus the audit totals. Writes `<out-dir>/phase8_leads_v4_e2.json`.
report   `reports/phase8_leads_v4.{json,md}` rendered from the three result files above (numbers never typed by hand).
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
import pandas as pd

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


# ---------------------------------------------------------------------------------------------- E1: archive consistency

E1_SEED = 20261115
E1_CELLS = 2536
E1_CANDIDATES = ("c", "a", "b", "a_oracle", "a_raw")
LEVELS = 4


def level_metrics(confusion: np.ndarray) -> dict:
    """Agreement, within one, recall / precision of Warning+ and Emergency and the burden by level of both sides from a
    (reference level x forecast level) count matrix."""
    c = np.asarray(confusion, dtype=np.float64)
    n = c.sum()
    if not n:
        return {"pairs": 0}
    i, j = np.indices(c.shape)
    out = {"pairs": int(n), "agreement": float(c[i == j].sum() / n), "within_one": float(c[np.abs(i - j) <= 1].sum() / n)}
    for name, level in (("warning_plus", 2), ("emergency", 3)):
        ref, fc_ = c[level:, :].sum(), c[:, level:].sum()
        both = c[level:, level:].sum()
        out[f"{name}_recall"] = float(both / ref) if ref else None
        out[f"{name}_precision"] = float(both / fc_) if fc_ else None
    out["burden_reference"] = {name: float(c[k, :].sum() / n) for k, name in enumerate(("normal", "watch", "warning", "emergency"))}
    out["burden_forecast"] = {name: float(c[:, k].sum() / n) for k, name in enumerate(("normal", "watch", "warning", "emergency"))}
    return out


def calibration(forecast_risk: np.ndarray, reference_risk: np.ndarray, bins: int = 10) -> list[dict]:
    """Mean lead risk and mean later lead-0 risk by decile of the lead risk."""
    ok = np.isfinite(forecast_risk) & np.isfinite(reference_risk)
    f, r = forecast_risk[ok], reference_risk[ok]
    if not f.size:
        return []
    edges = np.quantile(f, np.linspace(0, 1, bins + 1))
    which = np.clip(np.searchsorted(edges, f, side="right") - 1, 0, bins - 1)
    return [{"decile": k + 1, "n": int((which == k).sum()), "mean_lead_risk": float(f[which == k].mean()),
             "mean_lead0_risk": float(r[which == k].mean())} for k in range(bins) if (which == k).any()]


def bootstrap_delta(per_day: dict, candidate: str, baseline: str, metric, n_boot: int = 1000, seed: int = E1_SEED):
    """SE of metric(candidate) - metric(baseline) with issue days resampled (the same days for both)."""
    a, b = np.stack(per_day[candidate]), np.stack(per_day[baseline])
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, len(a), size=(n_boot, len(a)))
    deltas = [metric(a[d].sum(axis=0)) - metric(b[d].sum(axis=0)) for d in draws]
    deltas = [x for x in deltas if x is not None and np.isfinite(x)]
    return float(np.std(deltas, ddof=1)) if len(deltas) > 1 else None


class Identity:
    def apply(self, source, offset, field):
        return np.asarray(field, dtype=np.float32)


class E1Setup:
    def __init__(self, n_cells: int = E1_CELLS, seed: int = E1_SEED) -> None:
        from ..alerts.config import load_config_file as load_alert_config
        from ..features import imerg_features as F
        from ..features import static_w5
        from ..ingest import imerg
        from . import forecast_choice as fc
        from . import postrules as pr
        from . import run as live_run
        from .sources import project_path
        self.cfg = cfg = live_run.load_run_config()
        self.v3 = live_run.load_live_model(cfg)
        self.v4 = live_run.load_live_model({**cfg, "model_config": cfg[live_run.LEAD0_KEY]})
        cells, _ = live_run.load_candidate_cells(cfg)
        rng = np.random.default_rng(seed)
        self.sample = cells.iloc[np.sort(rng.choice(len(cells), size=min(n_cells, len(cells)), replace=False))].reset_index(drop=True)
        self.static = static_w5.join_static(self.sample[["cell_id"]], static_w5.static_table())[
            [c for c in self.v4.columns if c in static_w5.STATIC_COLUMNS]].reset_index(drop=True)
        self.rain_dir = project_path(cfg["imerg"]["processed_dir"])
        self.store = imerg.ImergStore(self.rain_dir, "late")
        self.clim = live_run.load_climatology(cfg, self.store, F.cell_pixels(self.sample["cell_id"].to_numpy()))
        self.alert_config = load_alert_config(project_path(cfg["alert_config"]))
        self.rules = pr.load_rules(project_path(cfg["post_rules"]))
        self.choice = fc.load_choice(project_path(cfg["forecast_selection"]))
        regions = fm.pixel_regions_of(cfg)
        self.maps = fm.ForecastMaps.load(project_path(self.choice.maps_file), regions)
        self.intensity_maps = fm.ForecastMaps.load(data_root() / "processed" / "lead_intensity" / "intensity_maps.json", regions)
        self.thresholds = {"v3": live_run.card_thresholds(self.v3, self.sample["region"]),
                           "v4": live_run.card_thresholds(self.v4, self.sample["region"])}

    def published(self, model, frame, thresholds):
        from . import postrules as pr
        from . import run as live_run
        scorable = live_run.scorable_mask(frame, model.columns)
        scores, level, _ = live_run.lead_scores(model, frame, scorable, thresholds, self.alert_config, self.rules, None)
        ok = pr.rain_ok(frame, self.rules) | ~scorable
        level = pr.capped_levels(level, ok, np.zeros(len(frame), dtype=bool), self.rules)[0]
        return scores["risk"].to_numpy(dtype=np.float64), np.asarray(level), scorable

    def sources(self, issue_day: date, stored, maps) -> li.LeadSources:
        early_root = study_root() if ii.load_day(study_root(), li.EARLY, issue_day) is not None else ii.default_root()
        cache: dict = {}

        def forecast(target):
            if target not in cache:
                cache[target] = li.day_maps_on_grid(stored, target)
            return cache[target]
        return li.LeadSources(ii.default_root(), early_root, forecast, maps)


def e1_day(setup: E1Setup, issue_day: date, lead: int, stored) -> dict | None:
    """{candidate: (reference level, forecast level, reference risk, forecast risk, both scored)} of one issue day and lead,
    plus the v3 reference for the incumbent; None when a candidate's inputs are missing."""
    from . import forecast_choice as fc
    from . import forecast_features as FF
    from . import run as live_run
    products = fc.load_product_days(setup.rain_dir, issue_day)
    field = fc.resolve_lead(products, setup.choice, setup.maps, lead)
    if field is None or not np.isfinite(field.days).all():
        return None
    cell_ids = setup.sample["cell_id"].to_numpy()
    target = issue_day + timedelta(days=lead)
    iint, _ = li.lead_frame(issue_day, lead, cell_ids, setup.sources(issue_day, stored, setup.intensity_maps))
    raw, _ = li.lead_frame(issue_day, lead, cell_ids, setup.sources(issue_day, stored, Identity()))
    observed_iint = ii.cell_features(target, cell_ids, ii.default_root(), li.LATE, 1)
    if iint is None or raw is None or not np.isfinite(observed_iint.to_numpy()).all():
        return None
    base = setup.sample
    forecast_rain = FF.lead_features(base, issue_day, lead, setup.store, field.days, setup.clim)
    observed_rain = FF.lead_features(base, target, 0, setup.store, None, setup.clim)
    frames = {"c": pd.concat([base, forecast_rain], axis=1),
              "a": pd.concat([base, forecast_rain, iint, setup.static], axis=1),
              "a_oracle": pd.concat([base, forecast_rain, observed_iint, setup.static], axis=1),
              "a_raw": pd.concat([base, forecast_rain, raw, setup.static], axis=1)}
    models = {"c": setup.v3, "a": setup.v4, "a_oracle": setup.v4, "a_raw": setup.v4, "b": setup.v4}
    frames["b"] = frames["a"]
    if field.scenarios is not None:
        scenes = {name: pd.concat([base, FF.lead_features(base, issue_day, lead, setup.store, rain, setup.clim), iint, setup.static],
                                  axis=1) for name, rain in field.scenarios.items()}
        models["b"] = live_run.ExpectedModel(setup.v4, {n: (live_run.EXPECTED_WEIGHTS[n], f) for n, f in scenes.items()})
    ref = {"v4": setup.published(setup.v4, pd.concat([base, observed_rain, observed_iint, setup.static], axis=1),
                                 setup.thresholds["v4"]),
           "v3": setup.published(setup.v3, pd.concat([base, observed_rain], axis=1), setup.thresholds["v3"])}
    out = {"source": field.label, "expected": field.scenarios is not None}
    for name, model in models.items():
        risk, level, ok = setup.published(model, frames[name], setup.thresholds["v3" if name == "c" else "v4"])
        out[name] = (risk, level, ok)
    out["ref"] = ref
    return out


def run_consistency(years, out_dir: Path, progress=print) -> int:
    setup = E1Setup()
    store = li.default_store()
    per_day: dict = {}
    pairs: dict = {}
    days_used: dict = {}
    sources: dict = {}
    for year in years:
        for day in season_days(year):
            stored = li.load_store_day(store, day)
            if stored is None:
                continue
            for lead in (1, 2, 3):
                got = e1_day(setup, day, lead, stored)
                if got is None:
                    continue
                days_used.setdefault(lead, []).append(day.isoformat())
                sources.setdefault(lead, {}).setdefault(got["source"], 0)
                sources[lead][got["source"]] += 1
                for name in E1_CANDIDATES:
                    risk, level, ok = got[name]
                    for ref_name in (("v4", "v3") if name == "c" else ("v4",)):
                        ref_risk, ref_level, ref_ok = got["ref"][ref_name]
                        both = ok & ref_ok
                        confusion = np.zeros((LEVELS, LEVELS), dtype=np.int64)
                        np.add.at(confusion, (ref_level[both].astype(int), level[both].astype(int)), 1)
                        key = (lead, name, ref_name)
                        per_day.setdefault(key, []).append(confusion)
                        pairs.setdefault(key, []).append((risk[both].astype(np.float32), ref_risk[both].astype(np.float32)))
            progress(f"{day}: leads done")
    results: dict = {}
    for (lead, name, ref_name), rows in sorted(per_day.items()):
        total = np.sum(rows, axis=0)
        f = np.concatenate([p[0] for p in pairs[(lead, name, ref_name)]])
        r = np.concatenate([p[1] for p in pairs[(lead, name, ref_name)]])
        entry = {**level_metrics(total), "days": len(rows), "calibration": calibration(f.astype(np.float64), r.astype(np.float64))}
        if ref_name == "v4" and name != "c":
            index = {"agreement": lambda m: level_metrics(m)["agreement"],
                     "warning_plus_recall": lambda m: level_metrics(m)["warning_plus_recall"]}
            per = {k: per_day[(lead, k, "v4")] for k in (name, "c")}
            entry["delta_vs_incumbent_se"] = {k: bootstrap_delta(per, name, "c", fn) for k, fn in index.items()}
        results.setdefault(str(lead), {}).setdefault(name, {})[f"vs_{ref_name}_reference"] = entry
    payload = {"generated_utc": datetime.now(UTC).isoformat(timespec="seconds"), "years": list(years),
               "months": list(SEASON), "cells": len(setup.sample), "seed": E1_SEED,
               "candidates": {"c": "v3 on the selected forecast rain (incumbent)", "a": "v4, forecast intensity mapped",
                              "b": "a with the expected risk over the ensemble percentiles (= a where the lead's rain is GFS)",
                              "a_oracle": "v4 with the observed Late intensity of the window (diagnostic ceiling)",
                              "a_raw": "v4 with unmapped forecast intensity (diagnostic)"},
               "reference": "published level of the target day from observed features (lead 0 as the live run scores it): "
                            "v4 with Late lag-1 intensity and static inputs; v3 for the incumbent's own consistency",
               "issue_days": {str(k): len(v) for k, v in days_used.items()}, "forecast_sources": sources,
               "results": results}
    out_dir.mkdir(parents=True, exist_ok=True)
    dump_json(out_dir / "phase8_leads_v4_e1.json", payload)
    print(f"wrote {out_dir / 'phase8_leads_v4_e1.json'}")
    return 0


# ---------------------------------------------------------------------------------------------- E2: live replays

E2_SETS = ("c", "a", "b")


def run_replays(replay_dir: Path, out_dir: Path) -> int:
    """E2 of the spec: each set's forecast lead L issued on D against the same set's lead 0 of D + L (both replayed)."""
    results: dict = {}
    audits: dict = {}
    for name in E2_SETS:
        live = replay_dir / name / "live"
        summary_path = replay_dir / name / "replay_summary.json"
        if not summary_path.is_file():
            continue
        done = json.loads(summary_path.read_text(encoding="utf-8"))
        audits[name] = {"days": len(done), "violations": int(sum(v["audit"] for v in done.values())),
                        "by_check": {}, "lead_intensity_used": sum(bool((v.get("lead_intensity") or {}).get("used"))
                                                                   for v in done.values()),
                        "expected_risk_leads": sum(sum(v.get("expected_risk", {}).values()) for v in done.values())}
        for v in done.values():
            for check, count in v.get("audit_violations", {}).items():
                audits[name]["by_check"][check] = audits[name]["by_check"].get(check, 0) + count
        days = sorted(date.fromisoformat(d) for d in done)
        for lead in (1, 2, 3):
            confusion = np.zeros((LEVELS, LEVELS), dtype=np.int64)
            used = []
            for day in days:
                target = day + timedelta(days=lead)
                lead_path, ref_path = live / day.isoformat() / f"risk_D{lead}.parquet", live / target.isoformat() / "alerts.parquet"
                if target.isoformat() not in done or not lead_path.is_file() or not ref_path.is_file():
                    continue
                fc_ = pd.read_parquet(lead_path, columns=["cell_id", "level", "risk"])
                ref = pd.read_parquet(ref_path, columns=["cell_id", "level", "risk"])
                both = fc_.merge(ref, on="cell_id", suffixes=("_lead", "_ref"))
                both = both[np.isfinite(both["risk_lead"]) & np.isfinite(both["risk_ref"])]
                np.add.at(confusion, (both["level_ref"].to_numpy(dtype=int), both["level_lead"].to_numpy(dtype=int)), 1)
                used.append(day.isoformat())
            results.setdefault(str(lead), {})[name] = {**level_metrics(confusion), "issue_days": len(used)}
    payload = {"generated_utc": datetime.now(UTC).isoformat(timespec="seconds"), "replay_dir": str(replay_dir),
               "reference": "the same set's published lead 0 of the target day (replayed, backtest mode)",
               "audit": audits, "results": results,
               "caveat": "October-November 2026: outside the validated season (June-September)"}
    out_dir.mkdir(parents=True, exist_ok=True)
    dump_json(out_dir / "phase8_leads_v4_e2.json", payload)
    print(f"wrote {out_dir / 'phase8_leads_v4_e2.json'}")
    return 0


# ---------------------------------------------------------------------------------------------- the report

REPORT_STEM = "phase8_leads_v4"
PARTS = {"measure": "phase8_leads_v4_measure.json", "e1": "phase8_leads_v4_e1.json", "e2": "phase8_leads_v4_e2.json"}


def _f(value, digits: int = 2) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def _pct(value) -> str:
    return "-" if value is None else f"{100 * value:.1f}%"


def _measure_md(m: dict) -> list[str]:
    inv = m["inventory"]
    lines = ["## Part 1: what a forecast can supply (Task 1)", "",
             "### History on disk", "",
             f"- GFS archive folders: {inv['gfs_archive']['cycles']} cycles {inv['gfs_archive']['first']}..{inv['gfs_archive']['last']}, files kept "
             f"{', '.join(inv['gfs_archive']['hours_kept'])}: IMD-day boundary hours only, no sub-daily rain.",
             f"- GFS live raw files: {inv['gfs_live_raw']['cycles']} cycles {inv['gfs_live_raw']['first']}..{inv['gfs_live_raw']['last']}, "
             f"{inv['gfs_live_raw']['hours_kept_newest']} 3-hourly cumulative files each (f003..f096).",
             f"- ECMWF day files: {inv['ecmwf_day_files']['days']} issue days ({', '.join(f'{y}: {n}' for y, n in inv['ecmwf_day_files']['by_year'].items())}); "
             f"members kept: {'yes' if inv['ecmwf_day_files']['members_kept'] else 'no'}; stored keys {', '.join(inv['ecmwf_day_files']['keys'])}.",
             f"- This study's 3-hourly GFS archive (00Z, hours 3..51, public AWS copy, no account): "
             f"{', '.join(f'{y}: {n} days' for y, n in inv['gfs3h_store']['by_year'].items())}.",
             f"- Live days on disk: {len(inv['live_days'])} ({inv['live_days'][0]}..{inv['live_days'][-1]}).", "",
             "### Which of v4's six intensity inputs a forecast lead can form", "",
             "| lead | days read (lag 1) | source of each day | inputs formed |", "|---|---|---|---|",
             "| 1 | D-2, D-1, D | Late, Late, Early live window (44 half-hours) | all six, as observed |",
             "| 2 | D-1, D, D+1 | Late, Early, GFS 3-hour | max3h, max6h, wet hours from 3-hour blocks; max1h only as the 3-hour maximum mapped onto IMERG's 1-hour maximum |",
             "| 3 | D, D+1, D+2 | Early, GFS, GFS | as lead 2 |", "",
             "### Forecast and Early intensities against IMERG Late (same IMD day)", "",
             "Pixels of the two scored regions. `ratio` = mean forecast / mean Late; p90 / p99 are each side's own percentiles; "
             "`Late>=10` = mean of each side where Late's value is at least 10 mm (paired).", "",
             "| source | day offset | year | days | field | region | ratio | p90 fcst / Late | p99 fcst / Late | r | Late>=10: fcst / Late |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for source, by_offset in m["results"].items():
        for offset, by_year in by_offset.items():
            for year, entry in by_year.items():
                for field in ii.FIELDS:
                    for region in fm.REGIONS:
                        s = entry[field][region]
                        if not s.get("pairs"):
                            continue
                        heavy = s.get("late_at_least_10mm") or {}
                        heavy_text = (f"{_f(heavy.get('mean_forecast'), 1)} / {_f(heavy.get('mean_late'), 1)}"
                                      if heavy.get("pairs") else "-")
                        lines.append(f"| {source} | {offset} | {year} | {entry['days']} | {field} | {region} | "
                                     f"{_f(s['ratio_of_means'])} | {_f(s['p90_forecast'], 1)} / {_f(s['p90_late'], 1)} | "
                                     f"{_f(s['p99_forecast'], 1)} / {_f(s['p99_late'], 1)} | {_f(s['correlation'])} | {heavy_text} |")
    return lines + [""]


def _metrics_rows(entry: dict) -> str:
    b, r = entry.get("burden_forecast", {}), entry.get("burden_reference", {})
    return (f"{entry.get('pairs', 0)} | {_f(entry.get('agreement'), 3)} | {_f(entry.get('within_one'), 3)} | "
            f"{_f(entry.get('warning_plus_recall'), 3)} | {_f(entry.get('warning_plus_precision'), 3)} | "
            f"{_f(entry.get('emergency_recall'), 3)} | {_f(entry.get('emergency_precision'), 3)} | "
            f"{_pct(b.get('warning'))} / {_pct(r.get('warning'))} | {_pct(b.get('emergency'))} / {_pct(r.get('emergency'))}")


HEADER = ("| lead | candidate | reference | pairs | agreement | within one | Warning+ recall | Warning+ precision | "
          "Emergency recall | Emergency precision | Warning share lead / ref | Emergency share lead / ref |")


def _e1_md(e: dict) -> list[str]:
    lines = ["## Part 2a: E1 archive consistency (development and archive data, no event read)", "",
             f"Years {', '.join(map(str, e['years']))}, months {e['months']}, {e['cells']} cells (seed {e['seed']}), "
             f"issue days per lead {e['issue_days']}; forecast rain used per lead {e['forecast_sources']}. Reference: {e['reference']}.", "",
             HEADER, "|" + "---|" * 12]
    for lead, by in e["results"].items():
        for name, refs in by.items():
            for ref, entry in refs.items():
                lines.append(f"| {lead} | {name} | {ref.split('_')[1]} | {_metrics_rows(entry)} |")
    lines += ["", "Differences from the incumbent (v4 reference; standard errors resample issue days):", "",
              "| lead | candidate | agreement delta (SE) | Warning+ recall delta (SE) |", "|---|---|---|---|"]
    for lead, by in e["results"].items():
        base = by["c"]["vs_v4_reference"]
        for name, refs in by.items():
            entry = refs["vs_v4_reference"]
            se = entry.get("delta_vs_incumbent_se")
            if se is None:
                continue
            da = entry["agreement"] - base["agreement"]
            dw = (entry["warning_plus_recall"] - base["warning_plus_recall"]
                  if entry.get("warning_plus_recall") is not None and base.get("warning_plus_recall") is not None else None)
            lines.append(f"| {lead} | {name} | {_f(da, 4)} ({_f(se.get('agreement'), 4)}) | {_f(dw, 4)} ({_f(se.get('warning_plus_recall'), 4)}) |")
    lines += ["", "Calibration of lead risk against the later lead-0 risk (v4 reference), by decile of lead risk, lead 2:", "",
              "| candidate | decile | n | mean lead risk | mean lead-0 risk |", "|---|---|---|---|---|"]
    for name, refs in e["results"].get("2", {}).items():
        for row in refs["vs_v4_reference"].get("calibration", []):
            lines.append(f"| {name} | {row['decile']} | {row['n']} | {row['mean_lead_risk']:.3g} | {row['mean_lead0_risk']:.3g} |")
    return lines + [""]


def _e2_md(e: dict) -> list[str]:
    lines = ["## Part 2b: E2 live replays (archived live days, scratch live_dir)", "", f"Reference: {e['reference']}. {e['caveat']}.", "",
             "| set | days | audit violations | by check | leads with their own intensity (days) | leads scored as an expectation |",
             "|---|---|---|---|---|---|"]
    for name, a in e["audit"].items():
        lines.append(f"| {name} | {a['days']} | {a['violations']} | {a['by_check'] or '-'} | {a['lead_intensity_used']} | {a['expected_risk_leads']} |")
    lines += ["", HEADER.replace("| reference ", ""), "|" + "---|" * 11]
    for lead, by in e["results"].items():
        for name, entry in by.items():
            lines.append(f"| {lead} | {name} | {_metrics_rows(entry)} |")
    return lines + [""]


def run_report(reports_dir: Path) -> int:
    parts = {k: json.loads((reports_dir / f).read_text(encoding="utf-8")) for k, f in PARTS.items() if (reports_dir / f).is_file()}
    lines = ["# Forecast leads on v4 (W7): development and archive evidence", "",
             "Spec: docs/superpowers/specs/2026-11-14-aetherguard-leads-v4.md (written before any lead-skill number). Research "
             "prototype, not validated for issuing real public warnings. No held-out event was read for this report.", "",
             "Caveats: ground truth after 2018 is very incomplete; E1 and E2 measure consistency with the model's own later "
             "view of the day, not landslides; E2 days are post-monsoon (outside the validated season); ECMWF has no archive "
             "before 2023, so 2022 issue days use the GFS fallback at every lead (candidate b equals a there).", ""]
    if "measure" in parts:
        lines += _measure_md(parts["measure"])
    lines += _e1_md(parts["e1"]) if "e1" in parts else ["## Part 2a: E1 archive consistency", "", "Not computed yet.", ""]
    lines += _e2_md(parts["e2"]) if "e2" in parts else ["## Part 2b: E2 live replays", "", "Not computed yet.", ""]
    dump_json(reports_dir / f"{REPORT_STEM}.json", {"parts": {k: PARTS[k] for k in parts},
                                                    "generated_utc": datetime.now(UTC).isoformat(timespec="seconds")})
    (reports_dir / f"{REPORT_STEM}.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {reports_dir / (REPORT_STEM + '.md')}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m aetherguard.live.leads_v4_study", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    measure = sub.add_parser("measure")
    measure.add_argument("--out-dir", type=Path, default=PROJECT_ROOT / "reports")
    fit = sub.add_parser("fit")
    fit.add_argument("--pairs", type=Path, required=True)
    fit.add_argument("--out", type=Path, default=data_root() / "processed" / "lead_intensity" / "intensity_maps.json")
    consistency = sub.add_parser("consistency")
    consistency.add_argument("--years", type=lambda t: tuple(int(y) for y in t.split(",")), default=(2022, 2023, 2024))
    consistency.add_argument("--out-dir", type=Path, default=PROJECT_ROOT / "reports")
    replays = sub.add_parser("replays")
    replays.add_argument("--replay-dir", type=Path, required=True)
    replays.add_argument("--out-dir", type=Path, default=PROJECT_ROOT / "reports")
    report = sub.add_parser("report")
    report.add_argument("--reports-dir", type=Path, default=PROJECT_ROOT / "reports")
    args = parser.parse_args(argv)
    if args.command == "report":
        return run_report(args.reports_dir)
    if args.command == "replays":
        return run_replays(args.replay_dir, args.out_dir)
    if args.command == "consistency":
        return run_consistency(args.years, args.out_dir)
    if args.command == "measure":
        return run_measure(args.out_dir)
    return run_fit(args.pairs, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
