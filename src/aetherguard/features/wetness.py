"""`iwet`: antecedent wetness from a soil-water bucket driven by the IMERG Late daily store (W4,
docs/superpowers/specs/2026-11-13-aetherguard-w4-wetness.md section 2).

Why a bucket and not a satellite soil-moisture product: the source probe (reports/phase8_wetness_sources_probe.md) found no
external product that covers 2007-2025, is available to the 11:00 IST run with a short lag, and is the same quantity in training
and live. A bucket driven by the rain the model already reads needs no new source and is identical in training and live by
construction; it adds what accumulations cannot express directly: a soil that fills up, stops taking water when full, and dries
at a rate set by the season and the latitude.

The bucket (Manabe 1969), per 0.1-degree IMERG pixel and IMD day t (state W at the end of the day, mm):
    ET_t = PET_t * min(1, W_{t-1} / (BETA_SHARE * CAPACITY_MM))
    W_t  = min(CAPACITY_MM, max(0, W_{t-1} - ET_t + P_t))
with P the IMD-day IMERG Late rain of `imerg_features.imd_day_series` (0.875 * UTC(t-1) + 0.125 * UTC(t)) and PET a
climatological loss computed exactly from latitude and day of year, PET = PET_SHARE_OF_RA * Ra / 2.45 (Ra the extraterrestrial
radiation of FAO-56 eq. 21, MJ m-2 day-1; 2.45 MJ kg-1 the latent heat of vaporisation). No parameter is fitted: capacity 150 mm
and beta 0.75 are Manabe's, the PET share of Ra (0.25) gives 3.5-4.5 mm/day in the monsoon and 1.5-3 mm/day in winter over
India, the range of the published reference evapotranspiration.

Lag (binding, `LAG_DAYS` = 2). The features of row date D are the state at the end of IMD day E = D - 2, i.e. after the rain up
to 03:00 UTC of D-2. IMD day D-2 needs UTC days D-3 and D-2, which the live run reads from the Late store at 05:30 UTC of D
(every live run of 2026-11-02..13 took UTC D-2 from Late, `run.json` `imd_day_inputs`), so training and live read the same Late
files and nothing from the Early run or the GFS tail. The rain of IMD days D-1 and D, the trigger, stays in `irain`/`iint`.

Spin-up. Each value is a run of the bucket from empty (W = 0) over the `SPINUP_DAYS` (120) IMD days ending at E. A row's value
therefore never depends on which other rows share its computation, and a single-day live run reproduces it exactly. 120 days is
what the store's history allows for the first development rows (2007-01-31: E - 119 = 2006-10-02, store from 2006-10-01); an
empty start is forgotten at about exp(-120 / 32) in dry weather and immediately once the bucket fills.

Features (float32, all three constrained non-decreasing in the model: wetter ground never lowers the hazard):
* `iwet_sat_l2`: W_E / CAPACITY_MM, the saturation of the root-zone bucket (0..1);
* `iwet_sat_anom_l2`: `iwet_sat_l2` minus the mean of `iwet_sat_l2` for the same pixel and calendar month of D over the TRAIN
  range 2007-01-01..2015-12-31 (the split bounds, as the `irain` climatology): unusually wet for the place and season;
* `iwet_satdays30_l2`: the number of the 30 IMD days ending at E on which the bucket ended at least `SAT_SHARE` (95%) full:
  how long the ground has been near saturation.

NaN rule. An IMD day whose rain is NaN adds no rain (the loss carries on); when any of the last `STRICT_DAYS` (30) IMD days of the
window is NaN the three features are NaN (nothing is filled where it matters). A cell outside the IMERG domain grid is NaN; an
anomaly is NaN where the climatology has no value.

Frozen tables (`build_tables`): group `iwet`, next to the other IMERG groups (`<name>_iwet.parquet` for every sample file of the
frozen feature store, rows and order of `<name>_features.parquet`; `season_<year>_iwet.parquet` for the cells x days of the
held-out season panel `season_<year>_training.npz`, cell-major), with `iwet_columns.json`, `iwet_manifest.json`,
`iwet_report.json` and the climatology `iwet_clim.npz`. No existing group or manifest is touched.

Live (`live_features`): the three features of one IMD day for the live cells, from the same store, climatology and code. Wiring
it into `live/run.py` is a separate, reviewed step.

CLI: python -m aetherguard.features.wetness tables [--out-dir DIR] [--panels-dir DIR] [--years 2018-2025] [--force]
"""
from __future__ import annotations

import argparse
import json
import stat
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

import numpy as np
import pandas as pd

from ..ingest import imerg as imerg_mod
from ..manifest import sha256_file
from . import imerg_build as B
from . import imerg_features as F
from . import imerg_intensity as ii
from .build import MANIFEST_NAME as FEATURES_MANIFEST
from .build import load_configs

GROUP = "iwet"
LAG_DAYS = 2
SPINUP_DAYS = 120
CAPACITY_MM = 150.0
BETA_SHARE = 0.75
PET_SHARE_OF_RA = 0.25
LATENT_HEAT_MJ_PER_KG = 2.45
SOLAR_CONSTANT = 0.0820                 # MJ m-2 min-1 (FAO-56)
SAT_SHARE = 0.95
SATDAYS_WINDOW = 30
STRICT_DAYS = 30
BLOCK_DAYS = 64                         # distinct row dates that share one store gather
CLIM_NAME = "iwet_clim.npz"
REPORT_NAME = "iwet_report.json"
HELDOUT_YEARS = ii.HELDOUT_YEARS
EPOCH = date(1970, 1, 1)


class WetnessIntegrityError(RuntimeError):
    """The frozen iwet directory is damaged, stale or incompatible with the current inputs / configuration."""


def feature_names() -> list[str]:
    return ["iwet_sat_l2", "iwet_sat_anom_l2", "iwet_satdays30_l2"]


def build_config(years=HELDOUT_YEARS) -> dict:
    """Everything that changes a feature value (block sizes do not)."""
    train = load_configs()["splits"]["day_splits"]["train"]
    return {"features": feature_names(), "run": "late", "lag_days": LAG_DAYS, "spinup_days": SPINUP_DAYS,
            "capacity_mm": CAPACITY_MM, "beta_share": BETA_SHARE, "pet_share_of_ra": PET_SHARE_OF_RA,
            "sat_share": SAT_SHARE, "satdays_window": SATDAYS_WINDOW, "strict_days": STRICT_DAYS,
            "climatology": {"first_day": str(train["start"]), "last_day": str(train["end"])},
            "heldout_years": [int(y) for y in years]}


# ------------------------------------------------------------------------------------------- pure numerics

def extraterrestrial_radiation(lat_deg, doy) -> np.ndarray:
    """Ra (MJ m-2 day-1), FAO-56 eq. 21, broadcasting latitude (degrees) against day of year."""
    phi = np.radians(np.asarray(lat_deg, dtype=np.float64))
    j = np.asarray(doy, dtype=np.float64)
    dr = 1.0 + 0.033 * np.cos(2 * np.pi * j / 365.0)
    delta = 0.409 * np.sin(2 * np.pi * j / 365.0 - 1.39)
    ws = np.arccos(np.clip(-np.tan(phi) * np.tan(delta), -1.0, 1.0))
    return (24 * 60 / np.pi) * SOLAR_CONSTANT * dr * (ws * np.sin(phi) * np.sin(delta) + np.cos(phi) * np.cos(delta) * np.sin(ws))


def pet_mm(lat_deg, doy) -> np.ndarray:
    """The climatological evaporative loss (mm/day) of the bucket."""
    return PET_SHARE_OF_RA * extraterrestrial_radiation(lat_deg, doy) / LATENT_HEAT_MJ_PER_KG


def bucket(rain: np.ndarray, pet: np.ndarray, capacity: float = CAPACITY_MM, beta: float = BETA_SHARE) -> np.ndarray:
    """(n, K) end-of-day water W of buckets started empty before column 0; NaN rain adds nothing."""
    rain, pet = np.asarray(rain, dtype=np.float64), np.asarray(pet, dtype=np.float64)
    if rain.shape != pet.shape or rain.ndim != 2:
        raise ValueError(f"rain {rain.shape} and pet {pet.shape} must be one (n, K) shape")
    water = np.zeros(rain.shape[0])
    out = np.empty_like(rain)
    wet = np.nan_to_num(rain, nan=0.0)
    for t in range(rain.shape[1]):
        loss = pet[:, t] * np.minimum(1.0, water / (beta * capacity))
        water = np.minimum(capacity, np.maximum(0.0, water - loss + wet[:, t]))
        out[:, t] = water
    return out


def window_features(rain: np.ndarray, pet: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(saturation at the last column, saturated days among the last `SATDAYS_WINDOW` columns) of (n, K) windows, NaN where
    any of the last `STRICT_DAYS` rain values is NaN."""
    water = bucket(rain, pet)
    sat = water[:, -1] / CAPACITY_MM
    days = (water[:, -SATDAYS_WINDOW:] >= SAT_SHARE * CAPACITY_MM).sum(axis=1).astype(np.float64)
    gap = np.isnan(np.asarray(rain, dtype=np.float64)[:, -STRICT_DAYS:]).any(axis=1)
    return np.where(gap, np.nan, sat), np.where(gap, np.nan, days)


def pixel_latitude(flat: np.ndarray) -> np.ndarray:
    """Latitude (degrees) of the centre of flat IMERG pixels (row * COLS + col)."""
    return imerg_mod.LAT_FIRST + imerg_mod.STEP * (np.asarray(flat, dtype=np.int64) // imerg_mod.COLS)


def _to_date(day_number: int) -> date:
    return EPOCH + timedelta(days=int(day_number))


def _day_of_year(day_numbers: np.ndarray) -> np.ndarray:
    return pd.DatetimeIndex(np.asarray(day_numbers).astype("datetime64[D]")).dayofyear.to_numpy()


# ------------------------------------------------------------------------------------------- the engine

def _block_series(store, pixels: np.ndarray, block: np.ndarray, lag_days: int) -> tuple[np.ndarray, int]:
    """(IMD-day series of `pixels` from the first IMD day the earliest window of `block` needs to the last IMD day E of the
    block, the IMD day number of its column 0). Nothing after E is read."""
    ends = block - lag_days
    first_imd = int(ends.min()) - SPINUP_DAYS + 1
    n_imd = int(ends.max()) - first_imd + 1
    utc = store.gather(pixels // imerg_mod.COLS, pixels % imerg_mod.COLS, _to_date(first_imd - 1), n_imd + 1)
    return F.imd_day_series(utc), first_imd


def _day_state(imd: np.ndarray, first_imd: int, rows: np.ndarray, lat: np.ndarray, end: int) -> tuple[np.ndarray, np.ndarray]:
    """(saturation, saturated days) of the series rows `rows` (latitudes `lat`) for the window ending at IMD day `end`."""
    column = int(end) - first_imd
    span = np.arange(column - SPINUP_DAYS + 1, column + 1)
    doy = _day_of_year(first_imd + span)
    return window_features(imd[np.ix_(rows, span)], pet_mm(np.asarray(lat)[:, None], doy[None, :]))


def state_blocks(store, flat: np.ndarray, row_days: np.ndarray, lag_days: int = LAG_DAYS,
                 block_days: int = BLOCK_DAYS) -> Iterator[tuple[int, np.ndarray, np.ndarray, np.ndarray]]:
    """For each distinct row day D (day numbers) of rows with pixels `flat` (>= 0): (D, the unique pixels of its rows, their
    saturation, their saturated days), the bucket of each run over the `SPINUP_DAYS` IMD days ending at D - `lag_days`.

    Distinct days are taken in blocks of `block_days`; each block gathers its pixels' UTC days once, from the first UTC day the
    earliest window needs to the last IMD day E of the block (nothing after E is read)."""
    flat, row_days = np.asarray(flat, dtype=np.int64), np.asarray(row_days, dtype=np.int64)
    order = np.argsort(row_days, kind="stable")
    days, starts = np.unique(row_days[order], return_index=True)
    stops = np.append(starts[1:], len(order))
    for b in range(0, len(days), block_days):
        block = days[b:b + block_days]
        pixels = np.unique(flat[order[starts[b]:stops[b + len(block) - 1]]])
        imd, first_imd = _block_series(store, pixels, block, lag_days)
        lat = pixel_latitude(pixels)
        for k, day in enumerate(block, start=b):
            own = np.unique(flat[order[starts[k]:stops[k]]])
            pos = np.searchsorted(pixels, own)
            sat, satdays = _day_state(imd, first_imd, pos, lat[pos], int(day) - lag_days)
            yield int(day), own, sat, satdays


@dataclass
class Climatology:
    """Mean `iwet_sat_l2` per (pixel, calendar month of the row day) over the train range; NaN where unknown."""

    pix: np.ndarray            # sorted unique flat pixel ids
    mean: np.ndarray           # (len(pix), 12) float64

    def lookup(self, flat: np.ndarray, month: np.ndarray) -> np.ndarray:
        flat, month = np.asarray(flat, dtype=np.int64), np.asarray(month, dtype=np.int64)
        out = np.full(len(flat), np.nan)
        if not len(self.pix):
            return out
        pos = np.minimum(np.searchsorted(self.pix, flat), len(self.pix) - 1)
        found = (flat >= 0) & (self.pix[pos] == flat)
        out[found] = self.mean[pos[found], month[found] - 1]
        return out

    def save(self, path: Path) -> None:
        with open(path, "wb") as handle:
            np.savez(handle, pix=self.pix, mean=self.mean)

    @classmethod
    def load(cls, path: Path) -> "Climatology":
        with np.load(path, allow_pickle=False) as data:
            return cls(np.asarray(data["pix"], dtype=np.int64), np.asarray(data["mean"], dtype=np.float64))


def climatology(store, pixels, first_day: date, last_day: date, block_days: int = BLOCK_DAYS) -> Climatology:
    """Mean saturation (the `iwet_sat_l2` of every row day first_day..last_day) per pixel and calendar month of the row day.
    A NaN value is left out of its mean; a (pixel, month) without a value is NaN."""
    pix = np.unique(np.asarray(pixels, dtype=np.int64))
    pix = pix[pix >= 0]
    first, last = (first_day - EPOCH).days, (last_day - EPOCH).days
    days = np.arange(first, last + 1, dtype=np.int64)
    sums, counts = np.zeros((len(pix), 12)), np.zeros((len(pix), 12))
    lat, every = pixel_latitude(pix), np.arange(len(pix))
    for start in range(0, len(days), block_days):        # every pixel on every day: the same windows as `state_blocks`
        block = days[start:start + block_days]
        imd, first_imd = _block_series(store, pix, block, LAG_DAYS)
        for day in block:
            sat, _ = _day_state(imd, first_imd, every, lat, int(day) - LAG_DAYS)
            month = _to_date(day).month - 1
            ok = np.isfinite(sat)
            sums[ok, month] += sat[ok]
            counts[ok, month] += 1.0
    with np.errstate(invalid="ignore", divide="ignore"):
        return Climatology(pix, np.where(counts > 0, sums / np.maximum(counts, 1), np.nan))


def features_for_rows(cell_ids, dates, store, clim: Climatology, lag_days: int = LAG_DAYS) -> pd.DataFrame:
    """The three float32 features for rows (cell_id, date), in the rows' order (default index)."""
    cells = np.asarray(cell_ids, dtype=np.int64)
    row_days = (pd.to_datetime(pd.Series(dates)).to_numpy().astype("datetime64[D]").astype(np.int64))
    flat = F.cell_pixels(cells)
    sat = np.full(len(cells), np.nan)
    satdays = np.full(len(cells), np.nan)
    usable = flat >= 0
    if usable.any():
        index = np.flatnonzero(usable)
        order = index[np.argsort(row_days[index], kind="stable")]
        days, starts = np.unique(row_days[order], return_index=True)
        slices = dict(zip(days.tolist(), zip(starts, np.append(starts[1:], len(order)))))
        for day, own, s, n in state_blocks(store, flat[usable], row_days[usable], lag_days):
            lo, hi = slices[day]
            rows = order[lo:hi]
            pos = np.searchsorted(own, flat[rows])
            sat[rows], satdays[rows] = s[pos], n[pos]
    months = pd.DatetimeIndex(row_days.astype("datetime64[D]")).month.to_numpy()
    anomaly = sat - clim.lookup(flat, months)
    return pd.DataFrame({"iwet_sat_l2": sat.astype(np.float32), "iwet_sat_anom_l2": anomaly.astype(np.float32),
                         "iwet_satdays30_l2": satdays.astype(np.float32)})


def frame_features(frame: pd.DataFrame, store, clim: Climatology) -> pd.DataFrame:
    """`features_for_rows` of a (cell_id, date) frame, with the frame's index."""
    out = features_for_rows(frame["cell_id"].to_numpy(), frame["date"].to_numpy(), store, clim)
    out.index = frame.index
    return out


def live_features(day: date, cell_ids, store, clim: Climatology) -> pd.DataFrame:
    """The live adapter: the three features of IMD day `day` for each cell (rows in `cell_ids` order), from the Late store and
    the frozen climatology, exactly as training computed them. Reads UTC days up to `day` - LAG_DAYS only."""
    cells = np.asarray(cell_ids, dtype=np.int64)
    return features_for_rows(cells, np.full(len(cells), np.datetime64(day, "D")), store, clim)


def last_utc_day_read(day: date, lag_days: int = LAG_DAYS) -> date:
    """The newest UTC day a feature of row day `day` reads (IMD day E = day - lag needs UTC E - 1 and E)."""
    return day - timedelta(days=lag_days)


# ------------------------------------------------------------------------------------------- frozen tables

def _managed(out_dir: Path, stems: list[str], years) -> list[Path]:
    return [*(out_dir / B.table_name(s, GROUP) for s in stems), *(out_dir / season_name(y) for y in years),
            out_dir / B.columns_name(GROUP), out_dir / B.manifest_name(GROUP), out_dir / REPORT_NAME, out_dir / CLIM_NAME]


def season_name(year: int) -> str:
    return f"season_{year}_{GROUP}.parquet"


def _input_records(inputs: B.ImergInputs, through: date, panels_dir: Path, years) -> dict:
    return {"features_manifest": {"path": B._display_path(inputs.features_dir / FEATURES_MANIFEST),
                                  "sha256": sha256_file(inputs.features_dir / FEATURES_MANIFEST)},
            "imerg_index": {"path": B._display_path(inputs.index_path), "through": through.isoformat(),
                            "signature": B.index_signature(inputs.index_path, through),
                            "file_sha256_at_build": sha256_file(inputs.index_path)},
            "season_panels": {str(y): {"path": B._display_path(ii.panel_path(panels_dir, y)),
                                       "sha256": sha256_file(ii.panel_path(panels_dir, y))} for y in years}}


def build_tables(inputs: B.ImergInputs, out_dir, store, panels_dir, years=HELDOUT_YEARS, force: bool = False,
                 cfg: dict | None = None, clim_pixels=None, say=lambda message: None) -> tuple[dict, bool]:
    """Write the frozen iwet tables and climatology; returns (manifest, reused). With a manifest present and `force` False
    nothing is rewritten: files, inputs and configuration are verified (WetnessIntegrityError on any problem).

    `clim_pixels`: further flat pixels for the climatology; the pixels of every sample and season-panel cell are always
    included (the live cells are the panel cells, so a live cell never lacks one). A run over all 72,800 domain pixels takes
    about 30 minutes; the rows' pixels about a sixth of that."""
    out_dir, panels_dir = Path(out_dir), Path(panels_dir)
    cfg = cfg if cfg is not None else build_config(years)
    manifest_path = out_dir / B.manifest_name(GROUP)
    if not force and manifest_path.exists():
        result = verify_tables(out_dir, inputs, panels_dir, cfg)
        if not result["ok"]:
            raise WetnessIntegrityError(f"{out_dir} is frozen but not intact (pass force=True to rebuild): "
                                        + "; ".join(result["problems"]))
        return json.loads(manifest_path.read_text(encoding="utf-8")), True

    started = time.perf_counter()
    stems, _ = B._sample_stems(inputs)
    panels = {y: ii.read_panel(panels_dir, y) for y in years}
    jobs = [(B.base_name(stem), B.table_name(stem, GROUP),
             lambda stem=stem: pd.read_parquet(inputs.features_dir / B.base_name(stem), columns=["cell_id", "date"]))
            for stem in stems]
    jobs += [(f"season_{y}_training.npz", season_name(y), lambda y=y: ii.panel_frame(*panels[y])) for y in years]
    row_cells = [pd.read_parquet(inputs.features_dir / B.base_name(s), columns=["cell_id"])["cell_id"].to_numpy() for s in stems]
    row_cells += [cells for cells, _ in panels.values()]
    own = F.cell_pixels(np.concatenate(row_cells)) if row_cells else np.zeros(0, dtype=np.int64)
    extra = np.zeros(0, dtype=np.int64) if clim_pixels is None else np.asarray(clim_pixels, dtype=np.int64)
    pixels = np.union1d(own[own >= 0], extra[extra >= 0])
    train = cfg["climatology"]
    say(f"climatology over {len(pixels):,} pixels, {train['first_day']}..{train['last_day']}")
    clim = climatology(store, pixels, date.fromisoformat(train["first_day"]), date.fromisoformat(train["last_day"]))
    clim_seconds = round(time.perf_counter() - started, 1)

    out_dir.mkdir(parents=True, exist_ok=True)
    B._set_mode(_managed(out_dir, stems, years), stat.S_IWRITE | stat.S_IREAD)
    clim.save(out_dir / CLIM_NAME)
    rows: dict[str, int] = {}
    per_file: dict[str, dict] = {}
    through = date(1970, 1, 1)
    for source, name, make_frame in jobs:
        tick = time.perf_counter()
        frame = make_frame()
        features = frame_features(frame, store, clim)
        pd.concat([frame[["cell_id", "date"]].reset_index(drop=True), features.reset_index(drop=True)],
                  axis=1).to_parquet(out_dir / name, index=False)
        rows[name] = len(frame)
        if len(frame):
            through = max(through, last_utc_day_read(pd.Timestamp(frame["date"].max()).date()))
        outside = int((F.cell_pixels(frame["cell_id"].to_numpy(dtype=np.int64)) < 0).sum())
        per_file[source] = {"rows": len(frame), "rows_outside_grid": outside, "nan_share": B._nan_share(features),
                            "seconds": round(time.perf_counter() - tick, 1)}
        say(f"{name}: {len(frame):,} rows in {per_file[source]['seconds']} s")
    B._write_json(out_dir / B.columns_name(GROUP), {c: GROUP for c in feature_names()})
    gaps = B.coverage_gaps(inputs.index_path, imerg_mod.HISTORY_START, through)
    total = round(time.perf_counter() - started, 1)
    B._write_json(out_dir / REPORT_NAME, {
        "files": per_file, "climatology": {**train, "pixels": int(len(pixels)),
                                           "pixel_months_without_value": int(np.isnan(clim.mean).sum())},
        "imerg_days_missing": {"first_day": imerg_mod.HISTORY_START.isoformat(), "last_day": through.isoformat(),
                               "n_missing": len(gaps), "days": gaps},
        "seconds": {"climatology": clim_seconds, "total": total}})
    files = {n: {"sha256": sha256_file(out_dir / n), "size_bytes": (out_dir / n).stat().st_size, "n_rows": None}
             for n in (B.columns_name(GROUP), REPORT_NAME, CLIM_NAME)}
    for name, n_rows in rows.items():
        files[name] = {"sha256": sha256_file(out_dir / name), "size_bytes": (out_dir / name).stat().st_size, "n_rows": n_rows}
    B._write_json(manifest_path, {
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "frozen": True, "group": GROUP,
        "lag_days": LAG_DAYS, "config": cfg, "inputs": _input_records(inputs, through, panels_dir, years),
        "sample_files": [B.base_name(s) for s in stems], "season_files": [season_name(y) for y in years],
        "allow_missing": False, "required_days_missing": len(gaps), "files": files, "runtime_seconds": total})
    B._set_mode(_managed(out_dir, stems, years), stat.S_IREAD)
    return json.loads(manifest_path.read_text(encoding="utf-8")), False


def verify_tables(out_dir, inputs: B.ImergInputs | None = None, panels_dir=None, cfg: dict | None = None) -> dict:
    """Check the frozen files against the manifest; returns {"ok": bool, "problems": [str]}. Raises FileNotFoundError when
    there is no manifest. With `inputs`: unchanged feature-store manifest and IMERG index entries, sample keys equal to the
    base tables; with `panels_dir`: unchanged season panels and season keys equal to their cells x days; with `cfg`: the
    configuration it was built with."""
    out_dir = Path(out_dir)
    path = out_dir / B.manifest_name(GROUP)
    if not path.is_file():
        raise FileNotFoundError(f"{path} not found")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["files"], manifest["config"], manifest["inputs"], manifest["sample_files"], manifest["season_files"]
    except (ValueError, KeyError, TypeError) as exc:
        return {"ok": False, "problems": [f"{path.name} unreadable or incomplete: {exc!r}"]}
    problems: list[str] = []
    if manifest.get("frozen") is not True:
        problems.append(f"{path.name} says the features are not frozen")
    if cfg is not None and json.loads(json.dumps(cfg)) != manifest["config"]:
        problems.append("configuration changed after freezing")
    for name, entry in manifest["files"].items():
        file = out_dir / name
        if not file.is_file():
            problems.append(f"missing: {name}")
        elif sha256_file(file) != entry["sha256"]:
            problems.append(f"checksum mismatch: {name}")
    recorded = manifest["inputs"]
    if inputs is not None:
        if sha256_file(inputs.features_dir / FEATURES_MANIFEST) != recorded["features_manifest"]["sha256"]:
            problems.append(f"input changed after freezing: {FEATURES_MANIFEST}")
        through = date.fromisoformat(recorded["imerg_index"]["through"])
        if B.index_signature(inputs.index_path, through) != recorded["imerg_index"]["signature"]:
            problems.append(f"input changed after freezing: IMERG index entries up to {through}")
    if panels_dir is not None:
        for year, entry in recorded["season_panels"].items():
            panel = ii.panel_path(panels_dir, int(year))
            if not panel.is_file() or sha256_file(panel) != entry["sha256"]:
                problems.append(f"input changed after freezing: {panel.name}")
    if problems:
        return {"ok": False, "problems": problems}
    expected = feature_names()
    columns = json.loads((out_dir / B.columns_name(GROUP)).read_text(encoding="utf-8"))
    if columns != {c: GROUP for c in expected}:
        problems.append(f"{B.columns_name(GROUP)} does not map exactly the iwet columns to `{GROUP}`")
    tables = [(B.table_name(B.base_stem(base).removesuffix("_features"), GROUP), base) for base in manifest["sample_files"]]
    tables += [(name, None) for name in manifest["season_files"]]
    for name, base in tables:
        table = pd.read_parquet(out_dir / name)
        if list(table.columns) != ["cell_id", "date", *expected]:
            problems.append(f"{name}: columns are not cell_id, date and the iwet features")
            continue
        if any(table[c].dtype != np.float32 for c in expected):
            problems.append(f"{name}: feature columns not float32")
        keys = None
        if base is not None and inputs is not None:
            keys = pd.read_parquet(inputs.features_dir / base, columns=["cell_id", "date"])
        elif base is None and panels_dir is not None:
            keys = ii.panel_frame(*ii.read_panel(panels_dir, int(name.split("_")[1])))
        if keys is not None and not table[["cell_id", "date"]].equals(keys):
            problems.append(f"{name}: keys (cell_id, date) differ from their source in value or order")
    return {"ok": not problems, "problems": problems}


def load_climatology(out_dir=None) -> Climatology:
    """The frozen climatology, verified against the manifest."""
    out_dir = Path(out_dir or B.default_out_dir())
    manifest = json.loads((out_dir / B.manifest_name(GROUP)).read_text(encoding="utf-8"))
    if sha256_file(out_dir / CLIM_NAME) != manifest["files"][CLIM_NAME]["sha256"]:
        raise WetnessIntegrityError(f"{CLIM_NAME} does not match {B.manifest_name(GROUP)}")
    return Climatology.load(out_dir / CLIM_NAME)


# ----------------------------------------------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="W4 antecedent-wetness (bucket) features.")
    sub = parser.add_subparsers(dest="command", required=True)
    tables = sub.add_parser("tables", help="build and freeze the iwet feature tables and climatology")
    tables.add_argument("--out-dir", type=Path, help="default: <data>/processed/features/imerg")
    tables.add_argument("--panels-dir", type=Path, default=None, help="default: <data>/processed/alerts/heldout_seasons")
    tables.add_argument("--years", type=ii.parse_years, default=HELDOUT_YEARS)
    tables.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    inputs = B.default_inputs()
    out_dir = args.out_dir or B.default_out_dir()
    store = imerg_mod.ImergStore(inputs.index_path.parent, run="late")
    try:
        manifest, reused = build_tables(inputs, out_dir, store, args.panels_dir or ii.default_panels_dir(), args.years,
                                        force=args.force, say=lambda m: print(m, flush=True))
    except (WetnessIntegrityError, FileNotFoundError, B.ImergFeaturesIntegrityError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        store.close()
    print(f"iwet {'reused (verified intact)' if reused else 'built and frozen'} in {out_dir} ({manifest['runtime_seconds']} s); "
          f"{manifest['required_days_missing']} IMERG days missing")
    return 0


if __name__ == "__main__":
    sys.exit(main())
