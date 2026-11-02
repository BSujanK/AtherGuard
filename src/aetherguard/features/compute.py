"""Feature computation for (cell, date) rows (docs/phase1-design.md D5/D6, docs/phase3-design.md feature groups).

Day basis (binding). The sample date D is an IMD day. A window of N days ends on IMD day D. IMD values are native
IMD days. CHIRPS (UTC days) is aligned to the IMD day with `ingest.align` weights, aligned(d) = 0.875 UTC(d-1) +
0.125 UTC(d), and then summed over D-N+1..D, so the 30-day window needs UTC days D-30..D. POWER wetness (UTC days)
is read from UTC day D-1 and earlier only (UTC day D extends past the end of IMD day D).

NaN rule. A window feature is NaN when ANY day in its window is missing (store gap, upstream missing day, cell without
a pixel / outside IMD coverage); a zero is a value, never a stand-in for missing. Nothing is filled or interpolated.

Rain source. `rain_source` per row = 'imd' when the IMD value of day D is valid, else 'chirps_aligned' when the aligned
CHIRPS value of day D is valid, else 'none'; the whole `rain_*` group of that row comes from that single source.

Climatology. clim_N(source pixel, calendar month) = mean over the TRAIN range (2007-2015, from the split bounds) of the
N-day trailing sum of the same source pixel on days of that month, computed once per pixel and cached; no value dated
after the train range enters it.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..grid import cell_center
from ..ingest.align import IMD_SHARE_OF_CURRENT_UTC_DAY, IMD_SHARE_OF_PREVIOUS_UTC_DAY
from . import sources
from .sources import DailyStore, day_numbers

LOOKBACK = 30
ACC_WINDOWS = (1, 3, 5, 7, 14, 30)
SRC_WINDOWS = (1, 3, 7)
CLIM_WINDOWS = (3, 7, 30)
WET_DAYS_BACK = 8           # UTC days D-8 .. D-1
STAT_COLUMNS = ["elev_mean", "elev_std", "relief", "slope_mean", "slope_p90", "slope_max", "curvature_mean",
                "aspect_sin", "aspect_cos", "twi_proxy"]
SOURCES = ("imd", "chirps_aligned", "none")
WET_MM = 1.0
HEAVY_DAY_MM = 10.0
ANOMALY_FLOOR_MM = 1.0
MIN_SHARE_ACC3_MM = 1.0


def feature_names() -> dict[str, list[str]]:
    """Feature column names per group, in output order."""
    rain = [f"rain_acc_{n}" for n in ACC_WINDOWS] + ["rain_max1d_7", "rain_max1d_30", "rain_wetdays_30",
                                                      "rain_days_since_10mm", "rain_share1_3"] + [
        f"rain_acc{n}_vs_clim" for n in CLIM_WINDOWS]
    src = ([f"src_imd_acc_{n}" for n in SRC_WINDOWS] + [f"src_chi_acc_{n}" for n in SRC_WINDOWS]
           + [f"src_dis_diff_{n}" for n in SRC_WINDOWS] + [f"src_dis_ratio_{n}" for n in SRC_WINDOWS]
           + ["src_dis_both"])
    wet = ["wet_top", "wet_root", "wet_top_chg3", "wet_top_chg7", "wet_root_chg3", "wet_root_chg7"]
    stat = [f"stat_{c}" for c in STAT_COLUMNS]
    return {"rain": rain, "src": src, "wet": wet, "stat": stat}


# ------------------------------------------------------------------------------------------ pure numerics

def aligned_chirps(utc: np.ndarray) -> np.ndarray:
    """(n, 31) UTC days D-30..D -> (n, 30) IMD-day totals D-29..D, 0.875 * UTC(d-1) + 0.125 * UTC(d); NaN-propagating."""
    utc = np.asarray(utc, dtype=np.float64)
    return IMD_SHARE_OF_PREVIOUS_UTC_DAY * utc[:, :-1] + IMD_SHARE_OF_CURRENT_UTC_DAY * utc[:, 1:]


def trailing_window_sums(daily: np.ndarray, window: int) -> np.ndarray:
    """(P, T) trailing `window`-day sums ending at each column; NaN while the window starts before the first column
    and whenever any day in it is NaN (the rule of `ingest.align.trailing_sums` with max_missing = 0)."""
    daily = np.asarray(daily, dtype=np.float64)
    missing = np.isnan(daily)
    zero = np.zeros((daily.shape[0], 1))
    total = np.concatenate([zero, np.cumsum(np.where(missing, 0.0, daily), axis=1)], axis=1)
    gaps = np.concatenate([zero, np.cumsum(missing, axis=1)], axis=1)
    out = np.full(daily.shape, np.nan)
    if daily.shape[1] >= window:
        sums = total[:, window:] - total[:, :-window]
        out[:, window - 1:] = np.where(gaps[:, window:] - gaps[:, :-window] == 0, sums, np.nan)
    return out


def select_primary(imd: np.ndarray, chi_aligned: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Primary daily matrix and `rain_source` per row from the IMD and aligned-CHIRPS (n, 30) matrices."""
    use_imd = np.isfinite(imd[:, -1])
    use_chi = ~use_imd & np.isfinite(chi_aligned[:, -1])
    primary = np.where(use_imd[:, None], imd, np.where(use_chi[:, None], chi_aligned, np.nan))
    source = np.where(use_imd, "imd", np.where(use_chi, "chirps_aligned", "none"))
    return primary.astype(np.float64), source


def _window(daily: np.ndarray, n: int) -> np.ndarray:
    return daily[:, -n:]


def rain_block(daily: np.ndarray) -> dict[str, np.ndarray]:
    """Accumulation features of a (n, 30) daily matrix whose last column is day D (NaN rule: any NaN -> NaN)."""
    daily = np.asarray(daily, dtype=np.float64)
    out = {f"acc_{n}": _window(daily, n).sum(axis=1) for n in ACC_WINDOWS}
    out["max1d_7"] = _window(daily, 7).max(axis=1)
    out["max1d_30"] = daily.max(axis=1)
    incomplete = np.isnan(out["acc_30"])
    out["wetdays_30"] = np.where(incomplete, np.nan, (daily >= WET_MM).sum(axis=1))
    heavy = (daily >= HEAVY_DAY_MM)[:, ::-1]
    days_since = np.where(heavy.any(axis=1), heavy.argmax(axis=1), LOOKBACK).astype(np.float64)
    out["days_since_10mm"] = np.where(incomplete, np.nan, days_since)
    acc3 = out["acc_3"]
    out["share1_3"] = np.where(acc3 >= MIN_SHARE_ACC3_MM, out["acc_1"] / np.where(acc3 >= MIN_SHARE_ACC3_MM, acc3, 1.0),
                               np.nan)
    return out


def source_block(imd: np.ndarray, chi: np.ndarray) -> dict[str, np.ndarray]:
    """Per-source accumulations and their disagreement; NaN unless both sources are valid in the window."""
    out = {}
    for n in SRC_WINDOWS:
        i, c = _window(imd, n).sum(axis=1), _window(chi, n).sum(axis=1)
        out[f"imd_acc_{n}"], out[f"chi_acc_{n}"] = i, c
        out[f"dis_diff_{n}"] = i - c
        out[f"dis_ratio_{n}"] = (i + 1.0) / (c + 1.0)
    out["dis_both"] = (np.isfinite(imd[:, -1]) & np.isfinite(chi[:, -1])).astype(np.float64)
    return out


def wetness_block(top: np.ndarray, root: np.ndarray) -> dict[str, np.ndarray]:
    """Wetness at UTC day D-1 and its 3- and 7-day changes (D-1 minus D-4, D-1 minus D-8) from (n, 8) D-8..D-1."""
    out = {}
    for name, values in (("top", top), ("root", root)):
        values = np.asarray(values, dtype=np.float64)
        out[name] = values[:, -1]
        out[f"{name}_chg3"] = values[:, -1] - values[:, -4]
        out[f"{name}_chg7"] = values[:, -1] - values[:, 0]
    return out


def anomaly(acc: np.ndarray, clim: np.ndarray) -> np.ndarray:
    """acc / max(clim, 1 mm); NaN when either is NaN."""
    return np.asarray(acc, dtype=np.float64) / np.maximum(np.asarray(clim, dtype=np.float64), ANOMALY_FLOOR_MM)


# ------------------------------------------------------------------------------------------- climatology

def climatology(store: DailyStore, pix: np.ndarray, first_day: int, last_day: int, aligned: bool,
                windows: tuple[int, ...] = CLIM_WINDOWS, pixel_chunk: int = 4000) -> np.ndarray:
    """(P, 12, len(windows)) mean trailing sums per calendar month over first_day..last_day only.

    `aligned` converts a UTC-day store (CHIRPS) to IMD days before summing; the first day of the range is then NaN
    (no UTC day before it is allowed in). NaN where a month has no valid day.
    """
    pix = np.asarray(pix, dtype=np.int64)
    days = np.arange(first_day, last_day + 1)
    month = pd.DatetimeIndex(days.astype("datetime64[D]")).month.to_numpy()
    out = np.full((len(pix), 12, len(windows)), np.nan, dtype=np.float32)
    for start in range(0, len(pix), pixel_chunk):
        sel = slice(start, start + pixel_chunk)
        daily = store.series(pix[sel], first_day, last_day).astype(np.float64)
        if aligned:
            shifted = np.full_like(daily, np.nan)
            shifted[:, 1:] = (IMD_SHARE_OF_PREVIOUS_UTC_DAY * daily[:, :-1]
                              + IMD_SHARE_OF_CURRENT_UTC_DAY * daily[:, 1:])
            daily = shifted
        for w, window in enumerate(windows):
            sums = trailing_window_sums(daily, window)
            valid = np.isfinite(sums)
            filled = np.where(valid, sums, 0.0)
            for m in range(1, 13):
                days_in_month = month == m
                count = valid[:, days_in_month].sum(axis=1)
                total = filled[:, days_in_month].sum(axis=1)
                out[sel, m - 1, w] = np.where(count > 0, total / np.maximum(count, 1), np.nan)
    return out


@dataclass(frozen=True)
class ClimTable:
    pix: np.ndarray            # sorted unique pixel indices
    values: np.ndarray         # (len(pix), 12, len(CLIM_WINDOWS))

    def lookup(self, pix: np.ndarray, month: np.ndarray) -> np.ndarray:
        """(n, len(CLIM_WINDOWS)) float64, NaN for pixels not in the table."""
        out = np.full((len(pix), self.values.shape[2]), np.nan)
        if len(self.pix) == 0:
            return out
        pos = np.minimum(np.searchsorted(self.pix, pix), len(self.pix) - 1)
        found = (pix >= 0) & (self.pix[pos] == pix)
        out[found] = self.values[pos[found], month[found] - 1, :]
        return out


# ------------------------------------------------------------------------------------------------ context

@dataclass
class FeatureContext:
    imd: DailyStore
    chirps: DailyStore
    wet_top: DailyStore
    wet_root: DailyStore
    terrain: pd.DataFrame      # indexed by cell_id, STAT_COLUMNS
    clim_imd: ClimTable
    clim_chirps: ClimTable

    @classmethod
    def build(cls, cell_ids, imd_dir, chirps_dir, power_npz, terrain: pd.DataFrame, train_first_day: int,
              train_last_day: int, pixel_chunk: int = 4000) -> FeatureContext:
        cells = np.unique(np.asarray(cell_ids, dtype=np.int64))
        imd, chirps = sources.load_imd(imd_dir), sources.load_chirps(chirps_dir)
        wet_top, wet_root = sources.load_wetness(power_npz, cells)
        tables = []
        for store, aligned in ((imd, False), (chirps, True)):
            pix = np.unique(store.pixels(cells))
            pix = pix[pix >= 0]
            tables.append(ClimTable(pix, climatology(store, pix, train_first_day, train_last_day, aligned,
                                                     pixel_chunk=pixel_chunk)))
        return cls(imd, chirps, wet_top, wet_root, terrain.set_index("cell_id")[STAT_COLUMNS],
                   tables[0], tables[1])


def _chunk_features(cells: np.ndarray, days: np.ndarray, terrain_cells: np.ndarray, ctx: FeatureContext) -> tuple:
    n = len(cells)
    imd_pix, chi_pix = ctx.imd.pixels(cells), ctx.chirps.pixels(cells)
    imd = ctx.imd.gather(imd_pix, days - (LOOKBACK - 1), LOOKBACK).astype(np.float64)
    chi = aligned_chirps(ctx.chirps.gather(chi_pix, days - LOOKBACK, LOOKBACK + 1))
    primary, source = select_primary(imd, chi)
    months = pd.DatetimeIndex(days.astype("datetime64[D]")).month.to_numpy()
    clim = np.where((source == "imd")[:, None], ctx.clim_imd.lookup(imd_pix, months),
                    np.where((source == "chirps_aligned")[:, None], ctx.clim_chirps.lookup(chi_pix, months), np.nan))
    columns: dict[str, np.ndarray] = {}
    for name, values in rain_block(primary).items():
        columns[f"rain_{name}"] = values
    for w, window in enumerate(CLIM_WINDOWS):
        columns[f"rain_acc{window}_vs_clim"] = anomaly(columns[f"rain_acc_{window}"], clim[:, w])
    for name, values in source_block(imd, chi).items():
        columns[f"src_{name}"] = values
    wet_pix = ctx.wet_top.pixels(cells)
    wet = wetness_block(ctx.wet_top.gather(wet_pix, days - WET_DAYS_BACK, WET_DAYS_BACK),
                        ctx.wet_root.gather(wet_pix, days - WET_DAYS_BACK, WET_DAYS_BACK))
    for name, values in wet.items():
        columns[f"wet_{name}"] = values
    static = ctx.terrain.reindex(terrain_cells)
    for column in STAT_COLUMNS:
        columns[f"stat_{column}"] = static[column].to_numpy(dtype=np.float64)
    return columns, source


def compute_features(frame: pd.DataFrame, ctx: FeatureContext, chunk_rows: int = 100_000) -> pd.DataFrame:
    """The sample frame (all its columns, same rows and order) + lat, lon, month, rain_source + float32 features.

    Static terrain is joined at `terrain_cell_id` when the frame has it (nearest_land positives), else at `cell_id`;
    a null terrain cell gives NaN statics.
    """
    cells = frame["cell_id"].to_numpy(dtype=np.int64)
    days = day_numbers(frame["date"].to_numpy())
    if "terrain_cell_id" in frame.columns:
        terrain_cells = frame["terrain_cell_id"].astype("Float64").to_numpy(dtype=np.float64, na_value=np.nan)
        terrain_cells = np.where(np.isnan(terrain_cells), -1, terrain_cells).astype(np.int64)
    else:
        terrain_cells = cells
    names = [c for group in feature_names().values() for c in group]
    out = {c: np.empty(len(frame), dtype=np.float32) for c in names}
    source = np.empty(len(frame), dtype=object)
    for start in range(0, len(frame), chunk_rows):
        sel = slice(start, start + chunk_rows)
        columns, source[sel] = _chunk_features(cells[sel], days[sel], terrain_cells[sel], ctx)
        for name in names:
            out[name][sel] = columns[name]
    lat, lon = cell_center(cells)
    result = frame.copy()
    result["lat"], result["lon"] = lat.astype(np.float32), lon.astype(np.float32)
    result["month"] = pd.DatetimeIndex(days.astype("datetime64[D]")).month.to_numpy().astype(np.int8)
    result["rain_source"] = pd.Series(source, dtype="str").to_numpy()
    for name in names:
        result[name] = out[name]
    return result
