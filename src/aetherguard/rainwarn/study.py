"""The verification study of the heavy-rain warnings (spec sections 5 and 6).

    python -m aetherguard.rainwarn study [--resume]

Per lead (0..3) it builds a panel of the issue days that have an ECMWF day file, fits the calibration of each split on its
fitting days only, scores each test set against IMERG Late (and, for 2023 and 2024, the IMD grid as a second opinion),
tallies the warning levels, and keeps everything in per-day tallies so that the day-resampled intervals are cheap. The
fit of June-September 2023 + 2024 is the shipped calibration (`data/processed/rainwarn/calibration_shipped.json`).

Resumable: after each lead the partial result is written to `<out_dir>/study_partial.json` (and the shipped entries of
that lead); `--resume` skips the leads already there. The report JSON and markdown are written at the end.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import PROJECT_ROOT, data_root
from ..features import imerg_features as F
from ..ingest import ecmwf, imerg
from ..live.forecast_skill import load_gfs_day
from . import climatology as C
from . import engine as E
from . import prob as P
from . import verify as V

KINDS_ENS = ("calibrated", "raw", "climatology", "gfs", "ens_mean", "hres")
KINDS_OBS = ("calibrated", "climatology", "observed")
BASELINES = {0: ("observed",), 1: ("gfs", "ens_mean", "hres"), 2: ("gfs", "ens_mean", "hres"), 3: ("gfs", "ens_mean", "hres")}
REGIONS = ("domain", "himalaya", "western_ghats")
LEVEL_CODES = (0, 1, 2, 3, P.LEVEL_UNAVAILABLE)
OBS_CATEGORIES = ("below_heavy", "heavy", "very_heavy", "extremely_heavy")
IMD_ROOT_LAT, IMD_ROOT_LON, IMD_STEP = 6.5, 66.5, 0.25
PARTIAL = "study_partial.json"


def _ranges(spec) -> list[tuple[date, date]]:
    items = spec if isinstance(spec, list) else [spec]
    return [(date.fromisoformat(r["first"]), date.fromisoformat(r["last"])) for r in items]


def _inside(day: date, ranges) -> bool:
    return any(a <= day <= b for a, b in ranges)


def ensemble_days(rain_dir: Path, first: date, last: date) -> list[date]:
    days, day = [], first
    while day <= last:
        if (rain_dir / ecmwf.day_file_name(day)).is_file():
            days.append(day)
        day += timedelta(days=1)
    return days


def obs_category(values: np.ndarray) -> np.ndarray:
    cat = np.zeros(values.shape, dtype=np.int8)
    for k, name in enumerate(("heavy", "very_heavy", "extremely_heavy"), start=1):
        cat[values > P.FIXED_MM[name]] = k
    return cat


@dataclass
class Context:
    cfg: dict
    domain: C.Domain
    clim: C.Climatology
    rain_dir: Path
    live_dir: Path
    radii: list[int]
    late: object
    early: object
    _truth: dict = field(default_factory=dict)
    _early: dict = field(default_factory=dict)
    _imd: dict = field(default_factory=dict)

    @property
    def n(self) -> int:
        return len(self.domain.pixels)

    def truth(self, day: date) -> np.ndarray:
        """IMERG Late IMD-day total of `day` at the domain pixels (NaN where missing)."""
        if day.year not in self._truth:
            self._truth[day.year] = C.imd_days(self.late, self.domain.rows, self.domain.cols, date(day.year, 1, 1),
                                               date(day.year, 12, 31))
        return self._truth[day.year][:, (day - date(day.year, 1, 1)).days].astype(np.float64)

    def early_utc(self, day: date) -> np.ndarray:
        """IMERG Early UTC-day total of `day` at the domain pixels."""
        if day.year not in self._early:
            self._early[day.year] = self.early.gather(self.domain.rows, self.domain.cols, date(day.year, 1, 1),
                                                      (date(day.year, 12, 31) - date(day.year, 1, 1)).days + 1)
        return self._early[day.year][:, (day - date(day.year, 1, 1)).days].astype(np.float64)

    def imd(self, day: date) -> np.ndarray | None:
        """IMD gridded IMD-day total at the IMD cell nearest each domain pixel; None without that year."""
        if day.year not in self._imd:
            path = self.rain_dir / f"imd_{day.year}.npy"
            self._imd[day.year] = np.load(path, mmap_mode="r") if path.is_file() else None
        stack = self._imd[day.year]
        if stack is None:
            return None
        lat = imerg.LAT_FIRST + imerg.STEP * self.domain.rows
        lon = imerg.LON_FIRST + imerg.STEP * self.domain.cols
        ii = np.round((lat - IMD_ROOT_LAT) / IMD_STEP).astype(np.int64)
        jj = np.round((lon - IMD_ROOT_LON) / IMD_STEP).astype(np.int64)
        ok = (ii >= 0) & (ii < stack.shape[1]) & (jj >= 0) & (jj < stack.shape[2])
        out = np.full(self.n, np.nan)
        layer = np.asarray(stack[day.timetuple().tm_yday - 1], dtype=np.float64)
        out[ok] = layer[ii[ok], jj[ok]]
        out[out < 0] = np.nan
        return out

    def live_obs0(self, day: date) -> np.ndarray | None:
        """`irain_acc_1` of the live run of `day` averaged per domain pixel (the live lead-0 input)."""
        path = self.live_dir / day.isoformat() / "features_D0.parquet"
        if not path.is_file():
            return None
        return pixel_values(self.domain, pd.read_parquet(path, columns=["cell_id", "irain_acc_1"]), "irain_acc_1")


def pixel_values(domain: C.Domain, frame: pd.DataFrame, column: str) -> np.ndarray:
    """Mean of `column` over the cells of each domain pixel, NaN for a pixel without a cell in `frame`."""
    flat = F.cell_pixels(frame["cell_id"].to_numpy())
    where = np.searchsorted(domain.pixels, flat)
    where = np.clip(where, 0, len(domain.pixels) - 1)
    keep = (flat >= 0) & (domain.pixels[where] == flat) & np.isfinite(frame[column].to_numpy())
    total = np.bincount(where[keep], weights=frame[column].to_numpy()[keep], minlength=len(domain.pixels))
    count = np.bincount(where[keep], minlength=len(domain.pixels))
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(count > 0, total / np.maximum(count, 1), np.nan)


@dataclass
class DayInputs:
    fields: dict[str, np.ndarray] | None
    det: dict[str, np.ndarray]
    reason: str | None = None

    def __post_init__(self) -> None:          # float32 halves the panel (229 days x 19 fields x 11,354 pixels)
        if self.fields is not None:
            self.fields = {k: np.asarray(v, dtype=np.float32) for k, v in self.fields.items()}
        self.det = {k: np.asarray(v, dtype=np.float32) for k, v in self.det.items()}


def state_of(ctx: Context, day: date) -> np.ndarray:
    """Season-state predictor of issue day `day` at the domain pixels (spec section 12.2), from IMERG Late."""
    window = E.state_days(day)
    observed = np.column_stack([ctx.truth(d) for d in window])
    clim = np.column_stack([ctx.clim.prob("heavy", d) for d in window])
    return E.season_state(observed, clim, ctx.domain.regions)


def day_inputs(ctx: Context, lead: int, day: date, live_lead0: bool, state: bool = False) -> DayInputs:
    item = _day_inputs(ctx, lead, day, live_lead0)
    if state and item.fields is not None:
        item.fields[E.STATE] = state_of(ctx, day).astype(np.float32)
    return item


def _day_inputs(ctx: Context, lead: int, day: date, live_lead0: bool) -> DayInputs:
    pixels = ctx.domain.pixels
    if lead == 0:
        obs0 = ctx.live_obs0(day) if live_lead0 else ctx.early_utc(day - timedelta(days=1))
        if obs0 is None or not np.isfinite(obs0).any():
            return DayInputs(None, {}, "no lead-0 observation")
        return DayInputs(E.observed_fields(obs0, ctx.radii, pixels), {"observed": obs0})
    forecast = ecmwf.load_day(ctx.rain_dir / ecmwf.day_file_name(day))
    grids = E.ensemble_grids(forecast, lead)
    if grids is None:
        return DayInputs(None, {}, "no valid ensemble")
    fields = E.forecast_fields(grids, ctx.radii, pixels)
    det = {"ens_mean": fields["ens_mean"]}
    if forecast.hres is not None and bool(forecast.hres_valid[lead - 1]):
        det["hres"] = np.asarray(forecast.hres[lead - 1], dtype=np.float64).ravel()[pixels]
    gfs_day = load_gfs_day(ctx.rain_dir, day)
    if gfs_day is not None and bool(gfs_day[1][lead - 1]):
        det["gfs"] = np.asarray(gfs_day[0][lead - 1], dtype=np.float64).ravel()[pixels]
    return DayInputs(fields, det)


def thresholds_of(ctx: Context) -> dict[str, object]:
    return {name: ctx.clim.threshold_mm(name) for name in P.THRESHOLDS}


def rows_of(ctx: Context, lead: int, inputs: dict[date, DayInputs], days: list[date], name: str) -> list:
    """(fields, threshold, clim, observed) of every day with inputs, as `engine.fit_threshold` takes them."""
    limit = ctx.clim.threshold_mm(name)
    rows = []
    for day in days:
        item = inputs.get(day)
        if item is None or item.fields is None:
            continue
        target = day + timedelta(days=lead)
        rows.append((item.fields, limit, ctx.clim.prob(name, target), ctx.truth(target)))
    return rows


def fit_lead(ctx: Context, lead: int, inputs: dict[date, DayInputs], fit_days: list[date], ridge: float,
             state: bool = False) -> dict:
    return {name: E.fit_threshold(rows_of(ctx, lead, inputs, fit_days, name), lead, name, ctx.radii, ridge, state)
            for name in P.THRESHOLDS}


def _new_tallies(kinds, n_days) -> dict:
    return {name: {region: {kind: V.Tally(n_days) for kind in kinds} for region in REGIONS} for name in P.THRESHOLDS}


def evaluate(ctx: Context, lead: int, inputs: dict[date, DayInputs], entries: dict, test_days: list[date],
             with_imd: bool, level_cutoffs: dict | None = None) -> dict:
    """Tallies of every kind, the IMD second opinion and the level table of one lead on one test set."""
    kinds = KINDS_OBS if lead == 0 else KINDS_ENS
    n_days = len(test_days)
    tallies = _new_tallies(kinds, n_days)
    imd_tallies = {name: {region: V.Tally(n_days) for region in REGIONS} for name in P.FIXED_MM} if with_imd else None
    levels = {region: np.zeros((len(LEVEL_CODES), len(OBS_CATEGORIES)), dtype=np.int64) for region in REGIONS}
    groups = {"domain": np.ones(ctx.n, dtype=bool), "himalaya": ctx.domain.regions == "himalaya",
              "western_ghats": ctx.domain.regions == "western_ghats"}
    limits = thresholds_of(ctx)
    calibration = E.Calibration(fit=[], radii=ctx.radii, entries={lead: entries},
                                levels=None if level_cutoffs is None else {lead: level_cutoffs})
    counts = {"issue_days": n_days, "no_inputs": 0, "no_truth": 0, "pairs_dropped": 0}
    for i, day in enumerate(test_days):
        item = inputs.get(day)
        if item is None or item.fields is None:
            counts["no_inputs"] += 1
            continue
        target = day + timedelta(days=lead)
        truth = ctx.truth(target)
        if not np.isfinite(truth).any():
            counts["no_truth"] += 1
            continue
        imd_truth = ctx.imd(target) if with_imd else None
        probs = {}
        for name in P.THRESHOLDS:
            t = limits[name]
            clim = ctx.clim.prob(name, target)
            forecast = {"calibrated": calibration.probability(item.fields, lead, name, t, clim),
                        "climatology": np.clip(clim, P.CLIM_FLOOR, 1.0)}
            if lead == 0:
                forecast["observed"] = (item.det["observed"] > t).astype(np.float64)
            else:
                forecast["raw"] = P.quantile_exceedance(item.fields["ens_p10"], item.fields["ens_p50"],
                                                        item.fields["ens_p90"], t)
                for kind in ("gfs", "ens_mean", "hres"):
                    if kind in item.det:
                        forecast[kind] = np.where(np.isfinite(item.det[kind]), (item.det[kind] > t).astype(float),
                                                  np.nan)
            probs[name] = forecast["calibrated"]
            event = truth > t
            base_ok = np.isfinite(truth) & np.isfinite(forecast["calibrated"])
            if name == "heavy":
                counts["pairs_dropped"] += int(np.sum(~base_ok))
            for region, member in groups.items():
                for kind, p in forecast.items():
                    ok = member & base_ok & np.isfinite(p)
                    tallies[name][region][kind].add(i, p[ok], event[ok])
                if imd_tallies is not None and name in P.FIXED_MM and imd_truth is not None:
                    ok = member & np.isfinite(imd_truth) & np.isfinite(forecast["calibrated"])
                    imd_tallies[name][region].add(i, forecast["calibrated"][ok], imd_truth[ok] > t)
        level = calibration.warning_levels(lead, probs)
        category = obs_category(np.nan_to_num(truth, nan=-1.0))
        finite = np.isfinite(truth)
        for region, member in groups.items():
            for li, code in enumerate(LEVEL_CODES):
                sel = member & finite & (level == code)
                levels[region][li] += np.bincount(category[sel], minlength=len(OBS_CATEGORIES))
    return {"tallies": tallies, "imd": imd_tallies, "levels": levels, "counts": counts}


def level_table(matrix: np.ndarray) -> dict:
    total = int(matrix.sum())
    names = [P.LEVEL_NAMES[c] for c in LEVEL_CODES]
    events = matrix[:, 1:].sum(axis=0)
    out = {"pixel_days": total, "levels": {}}
    for li, name in enumerate(names):
        row = matrix[li]
        n = int(row.sum())
        out["levels"][name] = {
            "n": n, "share": n / total if total else None,
            "observed": {cat: int(row[k]) for k, cat in enumerate(OBS_CATEGORIES)},
            "freq_heavy_or_more": float(row[1:].sum() / n) if n else None,
            "freq_very_heavy_or_more": float(row[2:].sum() / n) if n else None,
            "freq_extremely_heavy": float(row[3] / n) if n else None,
            "share_of_heavy_events": float(row[1:].sum() / events.sum()) if events.sum() else None,
            "share_of_very_heavy_events": float(row[2:].sum() / events[1:].sum()) if events[1:].sum() else None}
    return out


def det_scores(t: V.Tally) -> dict:
    s = V.point(t)
    if s["n"] == 0:
        return s
    yes, hits = float(t.rel_n[:, -1].sum()), float(t.rel_o[:, -1].sum())
    s["hit_rate"] = hits / s["events"] if s["events"] else None
    s["false_alarm_ratio"] = (yes - hits) / yes if yes else None
    s["forecast_yes"] = int(yes)
    s.pop("reliability", None)
    return s


def summarise(result: dict, lead: int, n_boot: int, seed: int, rules: dict, n_days: int) -> dict:
    w = V.bootstrap_weights(n_days, n_boot, seed)
    out = {"counts": result["counts"], "thresholds": {}, "levels": {r: level_table(m) for r, m in result["levels"].items()}}
    for name in P.THRESHOLDS:
        by_region = {}
        for region in REGIONS:
            tallies = result["tallies"][name][region]
            baselines = {k: tallies[k] for k in BASELINES[lead] if k in tallies and tallies[k].n.sum() > 0}
            product = V.compare(tallies["calibrated"], tallies["climatology"], baselines, w)
            entry = {"product": product, "statements": V.statements(product, rules),
                     "climatology": {k: v for k, v in V.point(tallies["climatology"]).items() if k != "reliability"},
                     "baselines": {k: det_scores(t) for k, t in baselines.items()}}
            if "raw" in tallies:
                raw = V.compare(tallies["raw"], tallies["climatology"], {}, w)
                entry["raw"] = {k: raw.get(k) for k in ("bs", "bss", "bss_ci", "auc", "auc_ci", "calibration_in_the_large",
                                                        "rel_over_unc", "reliability")}
            if result["imd"] is not None and name in P.FIXED_MM:
                imd = V.compare(result["imd"][name][region], None, {}, w, sample_reference=True)
                entry["imd"] = {k: imd.get(k) for k in ("n", "events", "event_days", "base_rate", "mean_prob", "bs",
                                                        "bss", "bss_ci", "auc", "auc_ci", "calibration_in_the_large")}
            by_region[region] = entry
        out["thresholds"][name] = by_region
    return out


def _fit_record(entries: dict) -> dict:
    return {name: {"radius": e["radius"], "n": e["n"], "n_events": e["n_events"],
                   "log_loss_by_radius": e["log_loss_by_radius"], "coef": e["model"].coef.tolist()}
            for name, e in entries.items()}


def make_context(cfg: dict) -> Context:
    root = data_root()
    rain_dir = root / cfg["rain_dir"]
    clim = C.Climatology.load(root / cfg["out_dir"] / cfg["climatology"]["file"])
    domain = C.Domain(pixels=clim.pixels, regions=clim.regions)
    return Context(cfg=cfg, domain=domain, clim=clim, rain_dir=rain_dir, live_dir=root / cfg["live_dir"],
                   radii=[int(r) for r in cfg["radii"]], late=imerg.ImergStore(rain_dir, "late"),
                   early=imerg.ImergStore(rain_dir, "early"))


def run_study(cfg: dict, *, resume: bool = False, progress=print) -> int:
    from . import report as R
    ctx = make_context(cfg)
    out_dir = data_root() / cfg["out_dir"]
    partial_path = out_dir / PARTIAL
    partial = json.loads(partial_path.read_text(encoding="utf-8")) if resume and partial_path.is_file() else {"leads": {}}
    shipped_ranges = _ranges(cfg["shipped_fit"])
    sets = {name: {"test": _ranges(s["test"]), "fit": _ranges(s["fit"]), "role": s["role"],
                   "live_lead0": bool(s.get("live_lead0", False))} for name, s in cfg["sets"].items()}
    all_ranges = [r for s in sets.values() for r in s["test"] + s["fit"]]
    days = sorted({d for a, b in all_ranges for d in ensemble_days(ctx.rain_dir, a, b)})
    live_days = {d for s in sets.values() if s["live_lead0"] for d in days if _inside(d, s["test"])}
    progress(f"{len(days)} issue days with an ECMWF file; domain {ctx.n} pixels")
    boot, rules, ridge = cfg["bootstrap"], cfg["statements"], float(cfg["ridge"])
    shipped_entries: dict[int, dict] = {}
    for lead in E.LEADS:
        key = str(lead)
        if key in partial["leads"]:
            progress(f"lead {lead}: kept from {partial_path.name}")
            shipped_entries[lead] = E.Calibration.from_dict(partial["shipped"][key]).entries[lead]
            continue
        inputs = {d: day_inputs(ctx, lead, d, d in live_days) for d in days}
        progress(f"lead {lead}: inputs of {len(inputs)} days")
        fits: dict[tuple, dict] = {}

        def fitted(ranges):
            k = tuple(ranges)
            if k not in fits:
                fit_days = [d for d in days if _inside(d, ranges) and d not in live_days]
                fits[k] = fit_lead(ctx, lead, inputs, fit_days, ridge)
                progress(f"lead {lead}: fitted on {len(fit_days)} days")
            return fits[k]
        lead_out = {"sets": {}, "fits": {}}
        for set_name, s in sets.items():
            entries = fitted(s["fit"])
            test_days = [d for d in days if _inside(d, s["test"])]
            result = evaluate(ctx, lead, inputs, entries, test_days, with_imd=not s["live_lead0"])
            lead_out["sets"][set_name] = summarise(result, lead, int(boot["n"]), int(boot["seed"]), rules, len(test_days))
            lead_out["sets"][set_name]["test_days"] = [test_days[0].isoformat(), test_days[-1].isoformat(), len(test_days)]
            lead_out["fits"][set_name] = _fit_record(entries)
            progress(f"lead {lead}: {set_name} scored")
        entries = fitted(shipped_ranges)
        fit_days = [d for d in days if _inside(d, shipped_ranges) and d not in live_days]
        insample = evaluate(ctx, lead, inputs, entries, fit_days, with_imd=False)
        lead_out["shipped_levels_in_sample"] = {r: level_table(m) for r, m in insample["levels"].items()}
        lead_out["shipped_fit"] = _fit_record(entries)
        shipped_entries[lead] = entries
        partial["leads"][key] = lead_out
        partial.setdefault("shipped", {})[key] = E.Calibration(fit=cfg["shipped_fit"], radii=ctx.radii,
                                                               entries={lead: entries}).to_dict()
        out_dir.mkdir(parents=True, exist_ok=True)
        tmp = partial_path.with_name(partial_path.name + ".tmp")
        tmp.write_text(json.dumps(partial) + "\n", encoding="utf-8")
        tmp.replace(partial_path)
        del inputs
        progress(f"lead {lead}: done")
    shipped = E.Calibration(fit=cfg["shipped_fit"], radii=ctx.radii, entries=shipped_entries)
    shipped_path = shipped.save(out_dir / "calibration_shipped.json")
    payload = {"spec": "docs/superpowers/specs/2026-11-14-aetherguard-rain-warnings.md",
               "observed": "IMERG V07 Late, IMD day = 0.875 UTC(d-1) + 0.125 UTC(d)",
               "second_opinion": "IMD gridded 0.25 degree (imd_<YYYY>.npy), nearest IMD cell, sample-climatology reference",
               "forecast": "ECMWF IFS ensemble (open data, CC BY 4.0) mean / p10 / p50 / p90 of the IMD-day total",
               "domain_pixels": ctx.n, "regions": {r: int(np.sum(ctx.domain.regions == r)) for r in REGIONS[1:]},
               "issue_days": len(days), "climatology": {"years": list(ctx.clim.years), "window_days": ctx.clim.window_days,
                                                        "percentile_floor_mm": cfg["climatology"]["percentile_floor_mm"]},
               "thresholds_mm": P.FIXED_MM, "level_rules": [[c, list(map(list, r))] for c, r in P.LEVEL_RULES],
               "bootstrap": boot, "statement_rules": rules, "radii": ctx.radii,
               "sets": {n: {"role": s["role"], "test": cfg["sets"][n]["test"], "fit": cfg["sets"][n]["fit"]}
                        for n, s in sets.items()},
               "shipped_calibration": str(shipped_path.relative_to(data_root())).replace("\\", "/"),
               "leads": partial["leads"]}
    R.write(cfg, payload)
    progress(f"wrote {cfg['report']}.json and .md")
    return 0


def report_paths(cfg: dict) -> tuple[Path, Path]:
    stem = PROJECT_ROOT / cfg["report"]
    return stem.with_suffix(".json"), stem.with_suffix(".md")
