"""Rain bias correction of the forecast days (spec section 12, F3): quantile mapping of a forecast onto IMERG Late.

    python -m aetherguard.live.forecast_map fit [--sources gfs ecmwf_hres ecmwf_ens_mean] [--out PATH]

One monotone curve per source, lead (IMD day D+1..D+3) and region (`himalaya`, `western_ghats`, `rest` = every other pixel of
the domain). It is fitted on pairs (forecast, IMERG Late IMD-day total) of every pixel of the region over the fit seasons of the
source: GFS June-September 2021-2023, ECMWF June-September 2023 (`FIT_SEASONS`); the season 2024 is never used.

The curve is the frequency-matched quantile mapping of `early_map.EarlyLateMap` (its piecewise-linear, tail-scaling form is reused
as it is):
  * observed rain below `DRY_MM` is dry; the forecast dry threshold is the forecast quantile that leaves the same share of
    pixel-days dry (a forecast that drizzles more often than IMERG sees rain maps its smallest values to 0);
  * above it the quantiles of the wet forecast values are matched to the quantiles of the wet observed values.
Fields are mapped pixel by pixel with the curve of the pixel's region; NaN stays NaN.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from ..features import imerg_features as F
from ..hazard.jsonio import dump_json
from ..ingest import imerg as imerg_mod
from . import forecast_choice as fc
from .early_map import DRY_MM, MIN_WET_VALUES, EarlyLateMap

VERSION = 1
REGIONS = ("himalaya", "western_ghats")
REST = "rest"
QUANTILES = tuple(float(round(q, 4)) for q in np.arange(0.005, 0.99, 0.005)) + (0.992, 0.995, 0.997, 0.998, 0.999, 0.9995, 0.9998)
FIT_SEASONS = {"gfs": (2021, 2022, 2023), "ecmwf_hres": (2023,), "ecmwf_ens_mean": (2023,)}
SEASON_MONTHS = (6, 7, 8, 9)
MAP_NAME = "forecast_maps.json"
MIN_FORECAST_MM = 1e-3


def region_labels(cell_ids, regions) -> np.ndarray:
    """Region of each flat IMERG pixel: `himalaya`, `western_ghats` or `rest`."""
    from .forecast_skill import pixel_region_labels
    labels = pixel_region_labels(cell_ids, regions)
    labels[~np.isin(labels, REGIONS)] = REST
    return labels


def fit_curve(forecast, observed, quantiles=QUANTILES, dry_mm: float = DRY_MM) -> EarlyLateMap:
    """The frequency-matched quantile mapping from paired forecast and observed arrays (any shape; NaN pairs ignored).

    Raises ValueError with fewer than `MIN_WET_VALUES` wet values on either side.
    """
    forecast, observed = np.asarray(forecast, dtype=np.float64).ravel(), np.asarray(observed, dtype=np.float64).ravel()
    if forecast.shape != observed.shape:
        raise ValueError("forecast and observed must have the same shape")
    paired = np.isfinite(forecast) & np.isfinite(observed)
    forecast, observed = forecast[paired], observed[paired]
    wet_obs = observed[observed >= dry_mm]
    wet_share = wet_obs.size / max(observed.size, 1)
    if wet_obs.size < MIN_WET_VALUES:
        raise ValueError(f"need at least {MIN_WET_VALUES} wet observed values, got {wet_obs.size}")
    threshold = max(float(np.quantile(forecast, 1.0 - wet_share)), MIN_FORECAST_MM)
    wet_fc = forecast[forecast >= threshold]
    if wet_fc.size < MIN_WET_VALUES:
        raise ValueError(f"need at least {MIN_WET_VALUES} wet forecast values, got {wet_fc.size}")
    probabilities = np.asarray(quantiles, dtype=np.float64)
    qf, qo = np.quantile(wet_fc, probabilities), np.quantile(wet_obs, probabilities)
    qo = np.maximum.accumulate(qo)
    keep = np.concatenate([[True], np.diff(qf) > 0])
    if keep.sum() < 2:
        raise ValueError("the forecast quantiles collapse to a single value; the data cannot define a mapping")
    info = {"pairs": int(forecast.size), "observed_wet_share": wet_share, "forecast_dry_below_mm": threshold,
            "wet_forecast": int(wet_fc.size), "wet_observed": int(wet_obs.size)}
    return EarlyLateMap(qf[keep], qo[keep], threshold, info)


class ForecastMaps:
    """The curves of every (source, lead, region) and the region of each pixel."""

    def __init__(self, curves: dict[tuple[str, int, str], EarlyLateMap], pixel_region: np.ndarray, info: dict | None = None):
        self.curves, self.pixel_region, self.info = curves, np.asarray(pixel_region, dtype=object), info or {}

    def sources(self) -> list[str]:
        return sorted({source for source, _, _ in self.curves})

    def apply(self, source: str, lead: int, field: np.ndarray) -> np.ndarray:
        """`field` (rows, cols) of `source` for IMD day D+`lead` on the IMERG Late scale, float32."""
        field = np.asarray(field, dtype=np.float32)
        flat = field.ravel()
        if flat.size != self.pixel_region.size:
            raise ValueError(f"the field has {flat.size} pixels, the mapping {self.pixel_region.size}")
        out = np.full(flat.shape, np.nan, dtype=np.float32)
        for region in (*REGIONS, REST):
            curve = self.curves.get((source, lead, region))
            if curve is None:
                raise KeyError(f"no mapping for {source}, lead {lead}, region {region}")
            pixels = self.pixel_region == region
            out[pixels] = curve.apply(flat[pixels])
        return out.reshape(field.shape)

    def to_dict(self) -> dict:
        curves: dict = {}
        for (source, lead, region), curve in sorted(self.curves.items()):
            curves.setdefault(source, {}).setdefault(str(lead), {})[region] = curve.to_dict()
        return {"version": VERSION, "info": self.info, "curves": curves}

    def save(self, path: Path) -> None:
        dump_json(Path(path), self.to_dict())

    @classmethod
    def from_dict(cls, payload: dict, pixel_region: np.ndarray) -> "ForecastMaps":
        if payload.get("version") != VERSION:
            raise ValueError(f"unsupported forecast mapping version {payload.get('version')!r}")
        curves = {(source, int(lead), region): EarlyLateMap.from_dict(curve)
                  for source, by_lead in payload["curves"].items() for lead, by_region in by_lead.items()
                  for region, curve in by_region.items()}
        return cls(curves, pixel_region, payload.get("info"))

    @classmethod
    def load(cls, path: Path, pixel_region: np.ndarray) -> "ForecastMaps":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")), pixel_region)


# ---------------------------------------------------------------------------------------------------- the fit

def season_days(year: int) -> list[date]:
    start, end = date(year, 6, 1), date(year, 9, 30)
    return [start + timedelta(days=n) for n in range((end - start).days + 1)]


def collect_pairs(store, rain_dir: Path, source: str, years, pixel_region: np.ndarray) -> dict[int, dict[str, list]]:
    """{lead: {region: [(forecast, observed) arrays per issue day batch]}} for the issue days of `years`."""
    rows, cols = np.divmod(np.arange(imerg_mod.ROWS * imerg_mod.COLS), imerg_mod.COLS)
    pairs = {k: {r: [] for r in (*REGIONS, REST)} for k in fc.LEADS}
    for year in years:
        days = season_days(year)
        first, last = days[0], days[-1] + timedelta(days=max(fc.LEADS))
        imd = F.imd_day_series(store.gather(rows, cols, first, (last - first).days + 1))   # column j: IMD day first + j + 1
        for day in days:
            product = fc.load_product_days(rain_dir, day).get(source)
            if product is None:
                continue
            for k in fc.LEADS:
                if not product.valid[k - 1]:
                    continue
                observed = imd[:, (day + timedelta(days=k) - first).days - 1]
                predicted = product.days[k - 1].ravel()
                for region in (*REGIONS, REST):
                    pixels = pixel_region == region
                    pairs[k][region].append((predicted[pixels], observed[pixels]))
    return pairs


def fit_source(store, rain_dir: Path, source: str, pixel_region: np.ndarray, years=None) -> tuple[dict, dict]:
    """({(source, lead, region): curve}, info) of one source on its fit seasons."""
    years = tuple(years if years is not None else FIT_SEASONS[source])
    pairs = collect_pairs(store, rain_dir, source, years, pixel_region)
    curves, info = {}, {"fit_seasons": list(years), "leads": {}}
    for k in fc.LEADS:
        info["leads"][str(k)] = {}
        for region in (*REGIONS, REST):
            parts = pairs[k][region]
            if not parts:
                raise ValueError(f"no archive day of {source} in {years} for lead {k}")
            f = np.concatenate([p[0] for p in parts])
            o = np.concatenate([p[1] for p in parts])
            curve = fit_curve(f, o)
            curves[(source, k, region)] = curve
            info["leads"][str(k)][region] = curve.info
    return curves, info


def pixel_regions_of(cfg: dict) -> np.ndarray:
    from .sources import project_path
    table = pd.read_parquet(project_path(cfg["region_table"]), columns=["cell_id", "region"])
    return region_labels(table["cell_id"].to_numpy(), table["region"].to_numpy())


def main(argv=None) -> int:
    from . import run as live_run
    from .sources import project_path
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    fit = sub.add_parser("fit", help="fit the curves and write the mapping file")
    fit.add_argument("--sources", nargs="+", default=list(fc.SOURCES), choices=fc.SOURCES)
    fit.add_argument("--config", type=Path, default=None, help="configs/live_run.yaml")
    fit.add_argument("--out", type=Path, default=None, help=f"mapping file (default <imerg.processed_dir>/{MAP_NAME})")
    args = parser.parse_args(argv)
    cfg = live_run.load_run_config(args.config)
    rain_dir = project_path(cfg["imerg"]["processed_dir"])
    out = args.out or rain_dir / MAP_NAME
    pixel_region = pixel_regions_of(cfg)
    store = imerg_mod.ImergStore(rain_dir, "late")
    curves, info = {}, {}
    for source in args.sources:
        print(f"[forecast_map] fitting {source} on {FIT_SEASONS[source]}", flush=True)
        try:
            fitted, source_info = fit_source(store, rain_dir, source, pixel_region)
        except ValueError as exc:
            print(f"[forecast_map] {source}: {exc}", file=sys.stderr)
            return 1
        curves.update(fitted)
        info[source] = source_info
    ForecastMaps(curves, pixel_region, info).save(out)
    print(f"[forecast_map] wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
