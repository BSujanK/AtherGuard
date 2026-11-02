"""Forecast-day skill and the interval-widening factors of the forecast leads (spec section 5.3).

    python -m aetherguard.live.forecast_skill [rain|hazard|all]

rain    GFS IMD-day totals (issue day D, lead k = IMD day D+k, the 00Z archive `data/processed/rain/gfs_imdday_<D>.npz`) against
        IMERG Late IMD-day totals over June-September 2021-2024, on the domain pixels and per region: bias, MAE, correlation,
        quantiles of forecast / observed per observed-rain bin, hit rate and false-alarm ratio at 50 and 100 mm. The IMERG
        IMD day is the training one (0.875 UTC(d-1) + 0.125 UTC(d)). No model is needed.
hazard  v3 risk from forecast-driven features (observed rain through D, GFS after D: `forecast_features.lead_features`) against
        v3 risk from observed features for the same target day, on a seeded sample of cells plus every labelled cell; Watch
        detection and level agreement, and the observed / forecast risk ratio. The 10th and 90th percentile of that ratio per
        lead are the factors that multiply `risk_lo` and `risk_hi` of the forecast leads (`live.run` reads them from the file
        named by `forecast_widening` in `configs/live_run.yaml`). Refuses unless the model directory holds `FROZEN.json`.
all     both; the freeze is checked before any work is done.

The ratio is taken over the informative cell-days only: those where at least one of the two risks reaches `floor_fraction` of
the Watch threshold. Dry-weather cell-days carry near-zero risk on both sides and would pull both percentiles to 1.

Labels are thin: three day-exact positive cell-days in 2021-2024, 24 cells of the 2023 inventory window (day unknown) and the
Wayanad 2024 case. They show whether a forecast reaches Watch where an event happened; they cannot estimate a detection rate. The
widening itself needs no labels, only the pairs of risks.

Writes `reports/phase6_forecast_skill.{md,json}` (each command updates its own section and keeps the other) and, for `hazard`,
the widening file. Missing data is NaN and counted, never zero.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from ..alerts import levels as lv
from ..alerts.config import alerts_settings
from ..config import PROJECT_ROOT, data_root, load_config
from ..features import imerg_features as F
from ..hazard import model as hm
from ..hazard.freeze import FROZEN_NAME, FrozenMismatchError, default_external_files, verify_freeze
from ..hazard.jsonio import jsonable
from ..ingest import gfs, imerg
from ..integrity.neighbours import haversine_km
from ..manifest import sha256_file
from . import forecast_features as FF
from . import run as live_run
from .sources import project_path, write_json_atomic

REPORT_STEM = "phase6_forecast_skill"
LEADS = (1, 2, 3)
RAIN_BIN_EDGES_MM = (1.0, 10.0, 25.0, 50.0, 100.0)
RAIN_BIN_LABELS = ("<1", "1-10", "10-25", "25-50", "50-100", ">=100")
EVENT_THRESHOLDS_MM = (50.0, 100.0)
RATIO_QUANTILES = (0.10, 0.25, 0.50, 0.75, 0.90)
MEASURABLE_MM = 0.1                  # the forecast / observed ratio is taken where the observed rain is at least this
HIST_LOG10_RANGE = (-3.0, 3.0)
HIST_BINS = 1200                     # 0.005 decades, about 1.2 % per bin
REGIONS = ("himalaya", "western_ghats")
PIXEL_MIN_CELLS = 2                  # of the 4 cells of a 0.1 degree pixel that must be in a region for the pixel to be
WIDENING_QUANTILES = (10, 90)
MIN_RATIOS = 200                     # fewer informative cell-days than this at a lead and no factor is written
FLOOR_FRACTION = 0.1                 # of the Watch threshold
DEFAULT_SAMPLE_CELLS = 2500
DEFAULT_SEED = 20261015
RISK_RATIO_QUANTILES = (1, 5, 10, 25, 50, 75, 90, 95, 99)
HAZARD_COMMAND = ".venv/Scripts/python -m aetherguard.live.forecast_skill hazard"
WAYANAD_EVENT = date(2024, 7, 30)
LABEL_COUNT_KEYS = ("day_exact_cell_days", "window_cells", "case_cells")


class NotFrozen(RuntimeError):
    """The model directory has no freeze record: the hazard skill and the widening are not measured on a moving model."""


def _num(value) -> float | None:
    """A finite float, else None (strict JSON)."""
    value = float(value)
    return value if np.isfinite(value) else None


def write_json(path: Path, payload) -> None:
    write_json_atomic(path, payload)


# ============================================================================================================ rain skill

class RatioHistogram:
    """Quantiles of positive ratios from a log10-spaced histogram (about 1.2 % resolution), plus an exact count of zeros.

    A zero ratio (forecast of no rain) ranks below every positive one; ratios outside 1e-3..1e3 are clamped into the end bins.
    """

    def __init__(self) -> None:
        self.edges = np.linspace(*HIST_LOG10_RANGE, HIST_BINS + 1)
        self.counts = np.zeros(HIST_BINS, dtype=np.int64)
        self.zeros = 0

    @property
    def n(self) -> int:
        return int(self.zeros + self.counts.sum())

    def add(self, ratio) -> None:
        ratio = np.asarray(ratio, dtype=np.float64).ravel()
        self.zeros += int((ratio == 0).sum())
        positive = ratio[ratio > 0]
        index = np.clip(np.floor((np.log10(positive) - self.edges[0]) / (self.edges[1] - self.edges[0])).astype(np.int64),
                        0, HIST_BINS - 1)
        self.counts += np.bincount(index, minlength=HIST_BINS)

    def quantile(self, q: float) -> float:
        n = self.n
        if n == 0:
            return float("nan")
        target = q * n
        if target <= self.zeros:
            return 0.0
        cumulative = self.zeros + np.cumsum(self.counts)
        k = int(min(np.searchsorted(cumulative, target, side="left"), HIST_BINS - 1))
        before = cumulative[k] - self.counts[k]
        inside = (target - before) / self.counts[k] if self.counts[k] else 0.5
        return float(10.0 ** (self.edges[k] + inside * (self.edges[k + 1] - self.edges[k])))


class SkillAccumulator:
    """Streaming forecast-vs-observed rain metrics over pairs (observed, forecast) in mm.

    Everything is a sum or a count, so the result does not depend on how the pairs are chunked. A pair with a missing value is
    dropped and counted.
    """

    def __init__(self, bin_edges=RAIN_BIN_EDGES_MM, labels=RAIN_BIN_LABELS, thresholds=EVENT_THRESHOLDS_MM) -> None:
        self.bin_edges, self.labels, self.thresholds = tuple(bin_edges), tuple(labels), tuple(thresholds)
        nb = len(self.labels)
        self.n = 0
        self.dropped = 0
        self.sums = dict(o=0.0, f=0.0, abs=0.0, oo=0.0, ff=0.0, of=0.0)
        self.bin_n = np.zeros(nb, dtype=np.int64)
        self.bin_sums = np.zeros((nb, 3))                      # observed, forecast, absolute error
        self.hists = [RatioHistogram() for _ in range(nb)]
        self.events = {t: np.zeros(4, dtype=np.int64) for t in self.thresholds}     # hits, misses, false alarms, correct neg.

    def add(self, observed, forecast) -> None:
        observed = np.asarray(observed, dtype=np.float64).ravel()
        forecast = np.asarray(forecast, dtype=np.float64).ravel()
        if observed.shape != forecast.shape:
            raise ValueError("observed and forecast must have the same length")
        keep = np.isfinite(observed) & np.isfinite(forecast)
        self.dropped += int((~keep).sum())
        o, f = observed[keep], forecast[keep]
        self.n += o.size
        self.sums["o"] += o.sum()
        self.sums["f"] += f.sum()
        self.sums["abs"] += np.abs(f - o).sum()
        self.sums["oo"] += (o * o).sum()
        self.sums["ff"] += (f * f).sum()
        self.sums["of"] += (o * f).sum()
        which = np.digitize(o, self.bin_edges)
        for k in range(len(self.labels)):
            in_bin = which == k
            if not in_bin.any():
                continue
            self.bin_n[k] += int(in_bin.sum())
            self.bin_sums[k] += (o[in_bin].sum(), f[in_bin].sum(), np.abs(f[in_bin] - o[in_bin]).sum())
            measurable = in_bin & (o >= MEASURABLE_MM)
            self.hists[k].add(f[measurable] / o[measurable])
        for t, tally in self.events.items():
            hit_obs, hit_fc = o >= t, f >= t
            tally += (int((hit_obs & hit_fc).sum()), int((hit_obs & ~hit_fc).sum()),
                      int((~hit_obs & hit_fc).sum()), int((~hit_obs & ~hit_fc).sum()))

    def _correlation(self) -> float | None:
        n, s = self.n, self.sums
        if n < 2:
            return None
        mo, mf = s["o"] / n, s["f"] / n
        var_o, var_f = s["oo"] / n - mo * mo, s["ff"] / n - mf * mf
        if var_o <= 1e-12 * max(1.0, mo * mo) or var_f <= 1e-12 * max(1.0, mf * mf):
            return None
        return _num((s["of"] / n - mo * mf) / np.sqrt(var_o * var_f))

    def _bin_summary(self, k: int) -> dict:
        lo = 0.0 if k == 0 else self.bin_edges[k - 1]
        hi = self.bin_edges[k] if k < len(self.bin_edges) else None
        n, hist = int(self.bin_n[k]), self.hists[k]
        o, f, a = self.bin_sums[k]
        quantiles = {f"p{round(q * 100)}": (_num(hist.quantile(q)) if hist.n else None) for q in RATIO_QUANTILES}
        return {"label": self.labels[k], "lo_mm": lo, "hi_mm": hi, "n": n,
                "mean_obs_mm": _num(o / n) if n else None, "mean_fcst_mm": _num(f / n) if n else None,
                "bias_mm": _num((f - o) / n) if n else None, "mae_mm": _num(a / n) if n else None,
                "ratio_n": hist.n, "zero_forecast_share": _num(hist.zeros / hist.n) if hist.n else None,
                "ratio_quantiles": quantiles}

    def _event_summary(self, tally) -> dict:
        hits, misses, false_alarms, negatives = (int(x) for x in tally)
        return {"hits": hits, "misses": misses, "false_alarms": false_alarms, "correct_negatives": negatives,
                "hit_rate": hits / (hits + misses) if hits + misses else None,
                "false_alarm_ratio": false_alarms / (hits + false_alarms) if hits + false_alarms else None}

    def summary(self) -> dict:
        n, s = self.n, self.sums
        return {"n": n, "n_dropped_missing": self.dropped,
                "mean_obs_mm": _num(s["o"] / n) if n else None, "mean_fcst_mm": _num(s["f"] / n) if n else None,
                "bias_mm": _num((s["f"] - s["o"]) / n) if n else None, "mae_mm": _num(s["abs"] / n) if n else None,
                "correlation": self._correlation(),
                "bins": [self._bin_summary(k) for k in range(len(self.labels))],
                "events": {f"{t:g}": self._event_summary(tally) for t, tally in self.events.items()}}


def pixel_region_labels(cell_ids, regions, min_cells: int = PIXEL_MIN_CELLS) -> np.ndarray:
    """Region name of each flat IMERG pixel (row * COLS + col), '' for none.

    A pixel is the 0.1 degree square holding four 0.05 degree cells. It takes the region that holds the most of its cells,
    provided that is at least `min_cells` of them and no other region ties it (cells of `out_of_scope` count for no region).
    """
    flat = F.cell_pixels(np.asarray(cell_ids, dtype=np.int64))
    regions = np.asarray(regions, dtype=object)
    labels = np.full(imerg.ROWS * imerg.COLS, "", dtype=object)
    counts: dict[str, np.ndarray] = {}
    for name in sorted({str(r) for r in regions} - {"out_of_scope", ""}):
        counts[name] = np.bincount(flat[(regions == name) & (flat >= 0)], minlength=labels.size)
    if not counts:
        return labels
    names = list(counts)
    stack = np.stack([counts[n] for n in names])
    top = stack.max(axis=0)
    unique_top = (stack == top).sum(axis=0) == 1
    winner = np.array(names, dtype=object)[stack.argmax(axis=0)]
    chosen = (top >= min_cells) & unique_top
    labels[chosen] = winner[chosen]
    return labels


def gfs_day_path(rain_dir: Path, day: date) -> Path:
    return Path(rain_dir) / f"gfs_imdday_{day.isoformat()}.npz"


def load_gfs_day(rain_dir: Path, day: date):
    """(IMD-day totals (3, rows, cols) float32 for leads 1..3, validity (3,) bool) of the GFS issue day, None without a file."""
    path = gfs_day_path(rain_dir, day)
    if not path.is_file():
        return None
    with np.load(path, allow_pickle=False) as data:
        days, valid = data["days"].astype(np.float32), data["day_valid"].astype(bool)
    if days.shape != (len(LEADS), imerg.ROWS, imerg.COLS) or valid.shape != (len(LEADS),):
        raise ValueError(f"{path.name}: expected days {(len(LEADS), imerg.ROWS, imerg.COLS)}, found {days.shape}")
    return days, valid


def rain_skill(store, rain_dir: Path, issue_days: list[date], groups: dict[str, np.ndarray]) -> dict:
    """Skill of the GFS IMD-day totals against the IMD days of `store` (IMERG Late) for leads 1..3.

    `groups` maps a name to the flat pixel ids it covers. Issue days without an archive file are counted; a lead the file
    flags invalid, and every pixel the observed store lacks, is skipped (never read as zero).
    """
    accumulators = {k: {name: SkillAccumulator() for name in groups} for k in LEADS}
    days_used = {k: 0 for k in LEADS}
    missing_files = 0
    all_pixels = np.arange(imerg.ROWS * imerg.COLS)
    rows, cols = all_pixels // imerg.COLS, all_pixels % imerg.COLS
    by_year: dict[int, list[date]] = {}
    for day in sorted(issue_days):
        by_year.setdefault(day.year, []).append(day)
    for days in by_year.values():
        first, last = days[0], days[-1] + timedelta(days=max(LEADS))
        utc = store.gather(rows, cols, first, (last - first).days + 1)
        imd = F.imd_day_series(utc)                                    # column j: IMD day first + j + 1
        del utc
        for day in days:
            loaded = load_gfs_day(rain_dir, day)
            if loaded is None:
                missing_files += 1
                continue
            forecast, valid = loaded
            for k in LEADS:
                if not valid[k - 1]:
                    continue
                days_used[k] += 1
                observed = imd[:, (day + timedelta(days=k) - first).days - 1]
                predicted = forecast[k - 1].ravel()
                for name, pixels in groups.items():
                    accumulators[k][name].add(observed[pixels], predicted[pixels])
        del imd
    return {"issue_days": len(issue_days), "gfs_files_missing": missing_files,
            "leads": {str(k): {"days_used": days_used[k], **{name: acc.summary() for name, acc in accumulators[k].items()}}
                      for k in LEADS}}


# ========================================================================================================== hazard skill

def widening_factors(ratios: dict[int, np.ndarray], *, min_n: int = MIN_RATIOS,
                     quantiles: tuple[int, int] = WIDENING_QUANTILES) -> dict:
    """Multipliers of `risk_lo` and `risk_hi` per forecast lead from the observed / forecast risk ratio.

    lo and hi are the 10th and 90th percentile of the finite positive ratios, clamped so that lo <= 1 <= hi (the interval is
    only ever widened); the unclamped percentiles stay on record. ValueError when a lead has fewer than `min_n` ratios.
    """
    lo_q, hi_q = quantiles
    leads = {}
    for k in LEADS:
        values = np.asarray(ratios.get(k, np.empty(0)), dtype=np.float64)
        values = values[np.isfinite(values) & (values > 0)]
        if values.size < min_n:
            raise ValueError(f"lead {k}: {values.size} usable risk ratios, fewer than the {min_n} needed for a widening factor")
        raw_lo, raw_hi = (float(x) for x in np.percentile(values, [lo_q, hi_q]))
        leads[str(k)] = {"lo": min(raw_lo, 1.0), "hi": max(raw_hi, 1.0), "raw_lo": raw_lo, "raw_hi": raw_hi,
                         "n": int(values.size)}
    return {"leads": leads, "quantiles": [lo_q, hi_q]}


def _risk(model: hm.HazardModel, cells: pd.DataFrame, features: pd.DataFrame) -> np.ndarray:
    frame = pd.concat([cells, features], axis=1)
    scorable = np.isfinite(frame[live_run.CORE_COLUMN].to_numpy(dtype=np.float64))
    out = np.full(len(frame), np.nan)
    if scorable.any():
        out[scorable] = model.score(frame[scorable])["risk"].to_numpy()
    return out


def risk_pair(model: hm.HazardModel, cells: pd.DataFrame, day: date, lead: int, store, forecast: np.ndarray,
              clim) -> pd.DataFrame:
    """Calibrated risk of each cell for IMD day D + `lead` from observed features (the training row of that day) and from
    forecast-driven features (observed through D, `forecast` after it): columns cell_id, obs_risk, fcst_risk (NaN where the
    cell has no rain input)."""
    target = day + timedelta(days=lead)
    observed = FF.lead_features(cells, target, 0, store, None, clim)
    predicted = FF.lead_features(cells, day, lead, store, forecast, clim)
    return pd.DataFrame({"cell_id": cells["cell_id"].to_numpy(), "obs_risk": _risk(model, cells, observed),
                         "fcst_risk": _risk(model, cells, predicted)})


def level_agreement(observed_level, forecast_level) -> dict:
    """4x4 count matrix (rows observed level 0-3, columns forecast level), exact and within-one agreement, and the Watch+
    split with the observed side as the reference."""
    obs, fc = np.asarray(observed_level, dtype=np.int64), np.asarray(forecast_level, dtype=np.int64)
    n = int(obs.size)
    confusion = np.zeros((4, 4), dtype=np.int64)
    np.add.at(confusion, (obs, fc), 1)
    both = int(((obs >= 1) & (fc >= 1)).sum())
    observed_only, forecast_only = int(((obs >= 1) & (fc < 1)).sum()), int(((obs < 1) & (fc >= 1)).sum())
    return {"n": n, "confusion": confusion.tolist(),
            "exact": float((obs == fc).mean()) if n else None, "within_one": float((np.abs(obs - fc) <= 1).mean()) if n else None,
            "watch": {"both": both, "observed_only": observed_only, "forecast_only": forecast_only,
                      "neither": int(((obs < 1) & (fc < 1)).sum()),
                      "recall_of_observed": both / (both + observed_only) if both + observed_only else None,
                      "precision_of_forecast": both / (both + forecast_only) if both + forecast_only else None}}


def candidate_cells(cells: pd.DataFrame, label_cells, n_sample: int, seed: int) -> pd.DataFrame:
    """Every labelled cell plus a seeded random sample of `n_sample` of the others, in cell-id order."""
    labelled = cells["cell_id"].isin(set(int(c) for c in label_cells))
    rest = cells[~labelled]
    picked = rest.sample(n=min(n_sample, len(rest)), random_state=seed) if len(rest) else rest
    return pd.concat([cells[labelled], picked]).sort_values("cell_id").reset_index(drop=True)


@dataclass
class Labels:
    """The landslide labels that fall in the GFS archive years: day-exact positive cell-days, inventory-window cells (the
    event day inside the window is unknown) and the cells of the Wayanad 2024 case around its event day."""
    day_exact: pd.DataFrame = field(default_factory=lambda: pd.DataFrame({"cell_id": [], "event_date": []}))
    windows: pd.DataFrame = field(default_factory=lambda: pd.DataFrame({"cell_id": [], "window_start": [], "window_end": []}))
    case: pd.DataFrame = field(default_factory=lambda: pd.DataFrame({"cell_id": [], "event_date": [], "name": []}))

    def counts(self) -> dict:
        return dict(zip(LABEL_COUNT_KEYS, (len(self.day_exact), len(self.windows), len(self.case))))

    def cell_ids(self) -> list[int]:
        return sorted({int(c) for frame in (self.day_exact, self.windows, self.case) for c in frame["cell_id"]})

    def restrict_to(self, cell_ids) -> "Labels":
        keep = set(int(c) for c in cell_ids)
        return Labels(*(frame[frame["cell_id"].isin(keep)].reset_index(drop=True)
                        for frame in (self.day_exact, self.windows, self.case)))


def select_labels(positives: pd.DataFrame, windows: pd.DataFrame, first: date, last: date,
                  case: pd.DataFrame | None = None) -> Labels:
    """The labels inside first..last (inclusive); `positives` has cell_id, event_date, `windows` cell_id, window_start,
    window_end (a window counts when it overlaps the range)."""
    lo, hi = pd.Timestamp(first), pd.Timestamp(last)
    exact = positives[(positives["event_date"] >= lo) & (positives["event_date"] <= hi)][["cell_id", "event_date"]]
    inside = windows[(windows["window_end"] >= lo) & (windows["window_start"] <= hi)][["cell_id", "window_start", "window_end"]]
    out = Labels(exact.reset_index(drop=True), inside.reset_index(drop=True))
    if case is not None:
        out.case = case[(case["event_date"] >= lo) & (case["event_date"] <= hi)].reset_index(drop=True)
    return out


def load_labels(cells: pd.DataFrame, first: date, last: date) -> Labels:
    """The project's labels in first..last: `splits/positive_cell_days`, `splits/window_positives` and the scored cells within
    the case radius of the Wayanad 2024 focus point (event day 2024-07-30)."""
    from ..cases import openmeteo as om
    from ..cases.score import WAYANAD_RADIUS_KM
    splits = data_root() / "processed" / "splits"
    positives = pd.read_parquet(splits / "positive_cell_days.parquet", columns=["cell_id", "event_date"])
    windows = pd.read_parquet(splits / "window_positives.parquet", columns=["cell_id", "window_start", "window_end"])
    near = haversine_km(om.WAYANAD["lat"], om.WAYANAD["lon"], cells["lat"].to_numpy(), cells["lon"].to_numpy()) <= WAYANAD_RADIUS_KM
    case = pd.DataFrame({"cell_id": cells.loc[near, "cell_id"].to_numpy(), "event_date": pd.Timestamp(WAYANAD_EVENT),
                         "name": "wayanad_2024"})
    return select_labels(positives, windows, first, last, case)


def require_frozen(model_dir: Path) -> Path:
    path = Path(model_dir) / FROZEN_NAME
    if not path.is_file():
        raise NotFrozen(f"v3 model not frozen yet: {path} not found (the hazard skill is measured on the frozen model only)")
    return path


def _label_rows(pair: pd.DataFrame, label_cells: set[int], day: date, lead: int) -> pd.DataFrame:
    rows = pair[pair["cell_id"].isin(label_cells)].copy()
    rows.insert(1, "target", pd.Timestamp(day + timedelta(days=lead)))
    rows.insert(1, "lead", lead)
    return rows


def _level_columns(rows: pd.DataFrame, thresholds: lv.Thresholds) -> pd.DataFrame:
    rows = rows.copy()
    rows["obs_level"] = lv.level_from_risk(rows["obs_risk"], thresholds)
    rows["fcst_level"] = lv.level_from_risk(rows["fcst_risk"], thresholds)
    return rows


def detection(rows: pd.DataFrame, labels: Labels, thresholds: lv.Thresholds) -> dict:
    """Watch detection of the labels, from the risk pairs of the labelled cells (`rows`: cell_id, lead, target, obs_risk, fcst_risk).

    day_exact: per event and lead the risks and levels on the event day. windows: per cell and lead the Watch+ days inside the
    window. case: per lead the maximum over the case cells on the event day. A lead with no pair (no archive file, a flagged lead,
    no rain input) is listed with `available` false, never as a miss.
    """
    rows = _level_columns(rows, thresholds) if len(rows) else rows.assign(obs_level=[], fcst_level=[])
    out: dict = {"day_exact": [], "windows": [], "case": []}
    for event in labels.day_exact.itertuples():
        for k in LEADS:
            hit = rows[(rows["cell_id"] == event.cell_id) & (rows["lead"] == k) & (rows["target"] == event.event_date)]
            hit = hit.dropna(subset=["obs_risk", "fcst_risk"])
            entry = {"cell_id": int(event.cell_id), "event_date": event.event_date.date().isoformat(), "lead": k,
                     "available": bool(len(hit))}
            if len(hit):
                r = hit.iloc[0]
                entry.update(obs_risk=_num(r["obs_risk"]), fcst_risk=_num(r["fcst_risk"]),
                             obs_watch=bool(r["obs_level"] >= 1), fcst_watch=bool(r["fcst_level"] >= 1))
            out["day_exact"].append(entry)
    for window in labels.windows.itertuples():
        for k in LEADS:
            hit = rows[(rows["cell_id"] == window.cell_id) & (rows["lead"] == k) & (rows["target"] >= window.window_start)
                       & (rows["target"] <= window.window_end)].dropna(subset=["obs_risk", "fcst_risk"])
            entry = {"cell_id": int(window.cell_id), "lead": k, "available": bool(len(hit)), "n_days": int(len(hit))}
            if len(hit):
                entry.update(obs_watch_days=int((hit["obs_level"] >= 1).sum()), fcst_watch_days=int((hit["fcst_level"] >= 1).sum()),
                             obs_max_risk=_num(hit["obs_risk"].max()), fcst_max_risk=_num(hit["fcst_risk"].max()))
            out["windows"].append(entry)
    for name, group in labels.case.groupby("name") if len(labels.case) else []:
        for event_date, part in group.groupby("event_date"):
            for k in LEADS:
                hit = rows[rows["cell_id"].isin(part["cell_id"]) & (rows["lead"] == k) & (rows["target"] == event_date)]
                hit = hit.dropna(subset=["obs_risk", "fcst_risk"])
                entry = {"name": name, "event_date": event_date.date().isoformat(), "lead": k, "cells": int(len(part)),
                         "available": bool(len(hit)), "n_cells_scored": int(len(hit))}
                if len(hit):
                    entry.update(obs_max_risk=_num(hit["obs_risk"].max()), fcst_max_risk=_num(hit["fcst_risk"].max()),
                                 obs_watch_cells=int((hit["obs_level"] >= 1).sum()),
                                 fcst_watch_cells=int((hit["fcst_level"] >= 1).sum()))
                out["case"].append(entry)
    out["summary"] = {str(k): {
        "day_exact": _tally(out["day_exact"], k, "obs_watch", "fcst_watch"),
        "windows": _tally(out["windows"], k, None, None, window=True),
        "case": _tally(out["case"], k, None, None, case=True)} for k in LEADS}
    return out


def _tally(entries: list[dict], lead: int, obs_key, fcst_key, window: bool = False, case: bool = False) -> dict:
    of_lead = [e for e in entries if e["lead"] == lead]
    available = [e for e in of_lead if e["available"]]
    if window:
        observed = sum(e["obs_watch_days"] > 0 for e in available)
        forecast = sum(e["fcst_watch_days"] > 0 for e in available)
    elif case:
        observed = sum(e["obs_watch_cells"] > 0 for e in available)
        forecast = sum(e["fcst_watch_cells"] > 0 for e in available)
    else:
        observed, forecast = sum(e[obs_key] for e in available), sum(e[fcst_key] for e in available)
    return {"n": len(of_lead), "available": len(available), "observed_watch": int(observed), "forecast_watch": int(forecast)}


def hazard_skill(model: hm.HazardModel, thresholds: lv.Thresholds, cells: pd.DataFrame, clim, store, rain_dir: Path,
                 issue_days: list[date], labels: Labels, *, n_sample: int = DEFAULT_SAMPLE_CELLS, seed: int = DEFAULT_SEED,
                 floor_fraction: float = FLOOR_FRACTION, min_ratios: int = MIN_RATIOS, progress=None) -> dict:
    """Run the forecast-feature risk against the observed-feature risk for every issue day and lead.

    Returns {"widening": the widening payload (lo / hi per lead), "report": the hazard section of the skill report}.
    `cells` are the scored cells (`cell_id`, `region`, `stat_*`, `lat`, `lon`).
    """
    scored = set(int(c) for c in cells["cell_id"])
    not_scored = {key: n - m for key, n, m in zip(LABEL_COUNT_KEYS, labels.counts().values(),
                                                  labels.restrict_to(scored).counts().values())}
    labels = labels.restrict_to(scored)
    label_cells = set(labels.cell_ids())
    sample = candidate_cells(cells, label_cells, n_sample, seed)
    floor = floor_fraction * thresholds.watch
    region_names = sorted({str(r) for r in sample["region"]})
    region_code = sample["region"].map({r: i for i, r in enumerate(region_names)}).to_numpy()
    kept = {k: {"ratio": [], "region": [], "obs_level": [], "fcst_level": []} for k in LEADS}
    n_unscorable = {k: 0 for k in LEADS}
    days_used = {k: 0 for k in LEADS}
    label_rows: list[pd.DataFrame] = []
    missing_files = 0
    for i, day in enumerate(sorted(issue_days)):
        loaded = load_gfs_day(rain_dir, day)
        if loaded is None:
            missing_files += 1
            continue
        forecast, valid = loaded
        for k in LEADS:
            if not valid[k - 1]:
                continue
            days_used[k] += 1
            pair = risk_pair(model, sample, day, k, store, forecast, clim)
            both = pair["obs_risk"].notna() & pair["fcst_risk"].notna()
            n_unscorable[k] += int((~both).sum())
            obs, fc = pair.loc[both, "obs_risk"].to_numpy(), pair.loc[both, "fcst_risk"].to_numpy()
            informative = (np.maximum(obs, fc) >= floor) & (obs > 0) & (fc > 0)
            kept[k]["ratio"].append((obs / np.where(fc > 0, fc, np.nan))[informative].astype(np.float32))
            kept[k]["region"].append(region_code[both.to_numpy()][informative])
            kept[k]["obs_level"].append(lv.level_from_risk(obs, thresholds))
            kept[k]["fcst_level"].append(lv.level_from_risk(fc, thresholds))
            if label_cells:
                label_rows.append(_label_rows(pair, label_cells, day, k))
        if progress is not None:
            progress(i + 1, len(issue_days))
    leads_report = {}
    ratios = {}
    for k in LEADS:
        ratio = np.concatenate(kept[k]["ratio"]) if kept[k]["ratio"] else np.empty(0, dtype=np.float32)
        region = np.concatenate(kept[k]["region"]) if kept[k]["region"] else np.empty(0, dtype=region_code.dtype)
        obs_level = np.concatenate(kept[k]["obs_level"]) if kept[k]["obs_level"] else np.empty(0, dtype=np.int8)
        fcst_level = np.concatenate(kept[k]["fcst_level"]) if kept[k]["fcst_level"] else np.empty(0, dtype=np.int8)
        ratios[k] = ratio
        quantile = lambda values: {f"p{q:02d}": _num(np.percentile(values, q)) if values.size else None
                                   for q in RISK_RATIO_QUANTILES}
        leads_report[str(k)] = {
            "days_used": days_used[k], "n_pairs": int(obs_level.size), "n_unscorable": n_unscorable[k],
            "n_ratios": int(ratio.size), "ratio_quantiles": quantile(ratio),
            "by_region": {name: {"n": int((region == i).sum()),
                                 **{key: v for key, v in quantile(ratio[region == i]).items() if key in ("p10", "p50", "p90")}}
                          for i, name in enumerate(region_names)},
            "agreement": level_agreement(obs_level, fcst_level)}
    widening = widening_factors(ratios, min_n=min_ratios)
    pairs = pd.concat(label_rows, ignore_index=True) if label_rows else pd.DataFrame(
        {"cell_id": [], "lead": [], "target": pd.to_datetime([]), "obs_risk": [], "fcst_risk": []})
    report = {"issue_days": len(issue_days), "gfs_files_missing": missing_files,
              "sample": {"cells": int(len(sample)), "label_cells": len(label_cells), "seed": seed},
              "floor": {"fraction_of_watch": floor_fraction, "risk": floor, "min_ratios": min_ratios},
              "thresholds": {"watch": thresholds.watch, "warning": thresholds.warning, "emergency": thresholds.emergency,
                             "source": thresholds.source},
              "ratio": "observed risk / forecast risk over informative cell-days (either risk >= the floor)",
              "leads": leads_report, "labels": labels.counts(), "labels_not_scored": not_scored,
              "detection": detection(pairs, labels, thresholds), "widening": widening}
    return {"widening": widening, "report": report}


# ============================================================================================================= the report

def _f(value, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def _g(value) -> str:
    return "n/a" if value is None else f"{value:.3g}"


def _rain_md(rain: dict) -> list[str]:
    groups = [g for g in rain["leads"]["1"] if g not in ("days_used",)]
    lines = ["## Rain skill: GFS against IMERG Late", "",
             f"{rain['period']}. {rain['issue_days']} issue days (00Z cycle), {rain['gfs_files_missing']} without an archive file. "
             "Lead k is IMD day D+k; the observed IMD day is 0.875 UTC(d-1) + 0.125 UTC(d) of IMERG Late. Statistics pool every "
             "pixel-day of the group; pairs with a missing value are dropped and counted. `domain` is every pixel of the 0.1 degree "
             "domain grid (sea included); `himalaya` and `western_ghats` are the pixels with at least "
             f"{PIXEL_MIN_CELLS} of their 4 cells in that region of `cell_regions`.", ""]
    lines += ["### Headline", "", "| group | lead | days | n | bias (mm) | MAE (mm) | correlation | hit rate >=50 | FAR >=50 | hit rate >=100 | FAR >=100 |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
    for name in groups:
        for k in LEADS:
            lead = rain["leads"][str(k)]
            s = lead[name]
            e50, e100 = s["events"]["50"], s["events"]["100"]
            lines.append(f"| {name} | {k} | {lead['days_used']} | {s['n']} | {_f(s['bias_mm'])} | {_f(s['mae_mm'])} | {_f(s['correlation'])} | "
                         f"{_f(e50['hit_rate'])} | {_f(e50['false_alarm_ratio'])} | {_f(e100['hit_rate'])} | {_f(e100['false_alarm_ratio'])} |")
    lines += ["", "Event counts (pixel-days): hits / misses / false alarms.", "", "| group | lead | >=50 mm | >=100 mm |", "|---|---|---|---|"]
    for name in groups:
        for k in LEADS:
            e = rain["leads"][str(k)][name]["events"]
            lines.append(f"| {name} | {k} | {e['50']['hits']} / {e['50']['misses']} / {e['50']['false_alarms']} | "
                         f"{e['100']['hits']} / {e['100']['misses']} / {e['100']['false_alarms']} |")
    for name in groups:
        lines += ["", f"### Forecast / observed by observed-rain bin: {name}", "",
                  "The ratio is taken where the observed rain is at least 0.1 mm; a forecast of no rain counts as 0.", "",
                  "| lead | bin (mm) | n | mean obs | mean fcst | bias | MAE | ratio n | p10 | p25 | p50 | p75 | p90 |",
                  "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for k in LEADS:
            for b in rain["leads"][str(k)][name]["bins"]:
                q = b["ratio_quantiles"]
                lines.append(f"| {k} | {b['label']} | {b['n']} | {_f(b['mean_obs_mm'], 2)} | {_f(b['mean_fcst_mm'], 2)} | {_f(b['bias_mm'], 2)} | "
                             f"{_f(b['mae_mm'], 2)} | {b['ratio_n']} | " + " | ".join(_f(q[p], 2) for p in ("p10", "p25", "p50", "p75", "p90")) + " |")
    return lines


def _hazard_pending_md(hazard: dict) -> list[str]:
    return ["## Hazard skill and interval widening", "",
            "pending: runs after the v3 freeze. The v3 model is still being changed; the hazard skill is measured on the frozen "
            "model only. Command:", "", f"    {hazard['command']}", "",
            "It writes this section and the widening file the daily runner reads "
            f"(`{hazard.get('widening_file', 'forecast_widening')}`); until then the forecast leads are published at most Degraded with "
            "no invented factor."]


def _hazard_md(hazard: dict) -> list[str]:
    th, fl = hazard["thresholds"], hazard["floor"]
    lines = ["## Hazard skill and interval widening", "",
             f"v3 model `{hazard.get('model_dir', 'n/a')}` ({hazard.get('freeze', 'frozen')}). Thresholds from the model card "
             f"({th['source']}): Watch {th['watch']:.3g}, Warning {th['warning']:.3g}, Emergency {th['emergency']:.3g}. "
             f"{hazard['issue_days']} issue days ({hazard['gfs_files_missing']} without a GFS file); {hazard['sample']['cells']} cells "
             f"(a seeded sample of the scored cells plus {hazard['sample']['label_cells']} labelled cells, seed {hazard['sample']['seed']}). "
             "The forecast side uses observed IMERG rain through D and GFS after D; the observed side is the training feature row of the "
             "target day. Observed rain of D is the full Late series here (the live D comes from Early plus GFS 0-3 h, measured by the "
             "operational backtest).", "",
             "### Widening factors", "",
             f"Ratio = {hazard['ratio']}. The factors multiply `risk_lo` (lo) and `risk_hi` (hi); lo is clamped to at most 1 and hi to at least 1. "
             f"Informative = at least one risk of the two >= {fl['fraction_of_watch']:g} x Watch ({fl['risk']:.3g}); at least {fl['min_ratios']} needed per lead.", "",
             "| lead | informative cell-days | lo | hi | raw p10 | raw p90 | pairs scored | not scorable |", "|---|---|---|---|---|---|---|---|"]
    for k in LEADS:
        w, r = hazard["widening"]["leads"][str(k)], hazard["leads"][str(k)]
        lines.append(f"| {k} | {w['n']} | {_f(w['lo'])} | {_f(w['hi'])} | {_f(w['raw_lo'])} | {_f(w['raw_hi'])} | {r['n_pairs']} | {r['n_unscorable']} |")
    lines += ["", "### Observed / forecast risk ratio (informative cell-days)", "",
              "| lead | " + " | ".join(f"p{q}" for q in RISK_RATIO_QUANTILES) + " |", "|---|" + "---|" * len(RISK_RATIO_QUANTILES)]
    for k in LEADS:
        q = hazard["leads"][str(k)]["ratio_quantiles"]
        lines.append(f"| {k} | " + " | ".join(_g(q[f"p{x:02d}"]) for x in RISK_RATIO_QUANTILES) + " |")
    lines += ["", "### Level agreement (all scored pairs)", "",
              "Level from the point risk against the card thresholds; the observed-feature level is the reference.", "",
              "| lead | pairs | same level | within one | Watch+ both | observed only | forecast only | recall of observed Watch+ | precision of forecast Watch+ |",
              "|---|---|---|---|---|---|---|---|---|"]
    for k in LEADS:
        a = hazard["leads"][str(k)]["agreement"]
        w = a["watch"]
        lines.append(f"| {k} | {a['n']} | {_f(a['exact'])} | {_f(a['within_one'])} | {w['both']} | {w['observed_only']} | {w['forecast_only']} | "
                     f"{_f(w['recall_of_observed'])} | {_f(w['precision_of_forecast'])} |")
    labels, gone = hazard["labels"], hazard["labels_not_scored"]
    lines += ["", "### Labels", "",
              f"{labels['day_exact_cell_days']} day-exact positive cell-days, {labels['window_cells']} cells of the 2023 inventory window "
              f"(event day unknown inside 2023-06-16..2023-07-31) and {labels['case_cells']} cells of the Wayanad 2024 case (event day 2024-07-30) "
              f"fall in the archive years ({gone['day_exact_cell_days']}, {gone['window_cells']} and {gone['case_cells']} more are in cells that are not scored). "
              "This is far too thin to estimate a detection rate; the counts below say only whether the forecast side reaches Watch where an event "
              "happened, against the observed side.", "",
              "| lead | day-exact events with data | observed Watch+ | forecast Watch+ | window cells with data | observed Watch+ | forecast Watch+ | Wayanad with data | observed Watch+ | forecast Watch+ |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for k in LEADS:
        s = hazard["detection"]["summary"][str(k)]
        d, w, c = s["day_exact"], s["windows"], s["case"]
        lines.append(f"| {k} | {d['available']}/{d['n']} | {d['observed_watch']} | {d['forecast_watch']} | {w['available']}/{w['n']} | "
                     f"{w['observed_watch']} | {w['forecast_watch']} | {c['available']}/{c['n']} | {c['observed_watch']} | {c['forecast_watch']} |")
    lines += ["", "Day-exact events:", "", "| cell | event day | lead | observed risk | forecast risk | observed Watch+ | forecast Watch+ |", "|---|---|---|---|---|---|---|"]
    for e in hazard["detection"]["day_exact"]:
        lines.append(f"| {e['cell_id']} | {e['event_date']} | {e['lead']} | " + (
            f"{_g(e['obs_risk'])} | {_g(e['fcst_risk'])} | {e['obs_watch']} | {e['fcst_watch']} |" if e["available"] else "no data | no data | n/a | n/a |"))
    lines += ["", "Wayanad 2024 (maximum over the case cells on the event day):", "",
              "| lead | cells scored | observed max risk | forecast max risk | observed Watch+ cells | forecast Watch+ cells |", "|---|---|---|---|---|---|"]
    for e in hazard["detection"]["case"]:
        lines.append(f"| {e['lead']} | {e['n_cells_scored']}/{e['cells']} | " + (
            f"{_g(e['obs_max_risk'])} | {_g(e['fcst_max_risk'])} | {e['obs_watch_cells']} | {e['fcst_watch_cells']} |" if e["available"] else "no data | no data | n/a | n/a |"))
    return lines


def render_markdown(payload: dict) -> str:
    lines = ["# Forecast-day skill (GFS) and interval widening", "",
             "Spec section 5.3. Forecast days D+1..D+3 of the daily run use observed IMERG rain through D and the GFS 00Z IMD-day totals "
             "after D. This report measures how far GFS rain is from IMERG Late and how far the resulting v3 risk is from the risk "
             "of the observed rain; the second gap sets the widening of the forecast-day intervals.", ""]
    lines += _rain_md(payload["rain"]) if payload.get("rain") else ["## Rain skill: GFS against IMERG Late", "", "pending: not run yet."]
    lines += [""]
    hazard = payload["hazard"]
    lines += _hazard_pending_md(hazard) if hazard.get("status") == "pending" else _hazard_md(hazard)
    return "\n".join(lines) + "\n"


def write_report(reports_dir: Path, rain: dict | None = None, hazard: dict | None = None,
                 widening_file: str | None = None) -> dict:
    """Update `phase6_forecast_skill.{json,md}` in `reports_dir`: the sections passed replace theirs, the others are kept."""
    reports_dir = Path(reports_dir)
    json_path = reports_dir / f"{REPORT_STEM}.json"
    payload = json.loads(json_path.read_text(encoding="utf-8")) if json_path.is_file() else {}
    if rain is not None:
        payload["rain"] = rain
    if hazard is not None:
        payload["hazard"] = hazard
    elif "hazard" not in payload:
        payload["hazard"] = {"status": "pending", "command": HAZARD_COMMAND, "widening_file": widening_file}
    payload.setdefault("rain", None)
    payload["updated_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = jsonable(payload)
    write_json(json_path, payload)
    (reports_dir / f"{REPORT_STEM}.md").write_text(render_markdown(payload), encoding="utf-8")
    return payload


# ================================================================================================================= the CLI

def default_widening_path(cfg: dict) -> Path:
    return project_path(cfg["forecast_widening"])


def issue_days_of_archive() -> list[date]:
    archive = load_config("live")["gfs"]["archive"]
    return gfs.archive_days(date.fromisoformat(archive["start"]), date.fromisoformat(archive["end"]), archive)


def _region_groups(cfg: dict) -> dict[str, np.ndarray]:
    table = pd.read_parquet(project_path(cfg["region_table"]), columns=["cell_id", "region"])
    labels = pixel_region_labels(table["cell_id"].to_numpy(), table["region"].to_numpy())
    groups = {"domain": np.arange(labels.size)}
    groups.update({name: np.flatnonzero(labels == name) for name in REGIONS})
    return groups


def run_rain(cfg: dict, rain_dir: Path, reports_dir: Path, widening_file: str) -> int:
    days = issue_days_of_archive()
    store = imerg.ImergStore(rain_dir, "late")
    print(f"[forecast_skill] rain skill: {len(days)} issue days {days[0]}..{days[-1]}", flush=True)
    groups = _region_groups(cfg)
    rain = rain_skill(store, rain_dir, days, groups)
    rain["period"] = f"June-September {days[0].year}-{days[-1].year}"
    rain["pixels"] = {name: int(len(pixels)) for name, pixels in groups.items()}
    rain["observed"] = "IMERG V07 Late daily (UTC days), IMD day = 0.875 UTC(d-1) + 0.125 UTC(d)"
    rain["forecast"] = "GFS 0.25 deg APCP, 00Z cycle, IMD-day totals on the IMERG grid (data/processed/rain/gfs_imdday_<D>.npz)"
    write_report(reports_dir, rain=rain, widening_file=widening_file)
    print(f"[forecast_skill] wrote {reports_dir / (REPORT_STEM + '.md')}", flush=True)
    return 0


def run_hazard(cfg: dict, model_dir: Path, hazard_config: Path, rain_dir: Path, reports_dir: Path, widening_path: Path,
               n_sample: int, seed: int) -> int:
    try:
        verify_freeze(model_dir, default_external_files(hazard_config))
    except FrozenMismatchError as exc:
        print(f"[forecast_skill] v3 model does not match its freeze record: {exc}", file=sys.stderr)
        return 1
    model = hm.HazardModel.load(model_dir)
    thresholds = lv.thresholds_from_card(model.card, alerts_settings()["v1_card_fallback"])
    cells = live_run.load_cells(cfg)
    store = imerg.ImergStore(rain_dir, "late")
    clim = live_run.load_climatology(cfg, store, F.cell_pixels(cells["cell_id"].to_numpy()))
    days = issue_days_of_archive()
    labels = load_labels(cells, days[0], days[-1] + timedelta(days=max(LEADS)))
    print(f"[forecast_skill] hazard skill: {len(days)} issue days, labels {labels.counts()}", flush=True)

    def progress(done: int, total: int) -> None:
        if done % 20 == 0 or done == total:
            print(f"[forecast_skill] issue day {done}/{total}", flush=True)

    result = hazard_skill(model, thresholds, cells, clim, store, rain_dir, days, labels, n_sample=n_sample, seed=seed,
                          progress=progress)
    freeze_sha = sha256_file(model_dir / FROZEN_NAME)
    hazard = {**result["report"], "model_dir": hm.display_path(model_dir), "freeze": f"FROZEN.json sha256 {freeze_sha}"}
    widening = {**result["widening"], "model_dir": hm.display_path(model_dir), "freeze_sha256": freeze_sha,
                "ratio": "observed risk / forecast risk", "sample_cells": hazard["sample"]["cells"], "seed": seed,
                "floor_fraction_of_watch": hazard["floor"]["fraction_of_watch"], "issue_days": hazard["issue_days"],
                "labels": hazard["labels"], "report": f"reports/{REPORT_STEM}.md",
                "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    write_json(widening_path, widening)
    write_report(reports_dir, hazard=hazard)
    print(f"[forecast_skill] wrote {widening_path} and {reports_dir / (REPORT_STEM + '.md')}", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", nargs="?", choices=("rain", "hazard", "all"), default="all")
    parser.add_argument("--config", type=Path, default=None, help="live-run configuration (default configs/live_run.yaml)")
    parser.add_argument("--model-dir", type=Path, default=None, help="v3 model directory (default: the one hazard_v3.yaml names)")
    parser.add_argument("--rain-dir", type=Path, default=None, help="IMERG store and GFS archive directory (default: imerg.processed_dir)")
    parser.add_argument("--reports-dir", type=Path, default=PROJECT_ROOT / "reports")
    parser.add_argument("--widening-out", type=Path, default=None, help="widening file (default: forecast_widening of the live-run configuration)")
    parser.add_argument("--cells", type=int, default=DEFAULT_SAMPLE_CELLS, help="random cells besides the labelled ones (hazard)")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args(argv)
    cfg = live_run.load_run_config(args.config)
    hazard_config = project_path(cfg["model_config"])
    model_dir = args.model_dir or hm.configured_model_dir(hm.hazard_config(hazard_config))
    rain_dir = project_path(args.rain_dir or cfg["imerg"]["processed_dir"])
    widening_path = args.widening_out or default_widening_path(cfg)
    if args.command in ("hazard", "all"):
        try:
            require_frozen(model_dir)
        except NotFrozen as exc:
            print(f"[forecast_skill] {exc}", file=sys.stderr)
            return 1
    status = 0
    if args.command in ("rain", "all"):
        status |= run_rain(cfg, rain_dir, args.reports_dir, cfg["forecast_widening"])
    if args.command in ("hazard", "all"):
        status |= run_hazard(cfg, model_dir, hazard_config, rain_dir, args.reports_dir, widening_path, args.cells, args.seed)
    return status


if __name__ == "__main__":
    sys.exit(main())
