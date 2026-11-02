"""Fault injection into REAL clean rain-gauge series, with per-day truth labels.

Six fault types (daily resolution); missing values are `gap`, never injected. Every injector has
the signature ``injector(series, start, length, rng, params) -> faulty values`` (float32, shape
``(length,)``): `series` is the station's TRUE series (NaN = missing), the window is
``series[start:start + length]``, NaN days inside the window stay NaN, and all draws come from
the numpy Generator `rng`. Parameter ranges (documented per type below; `params` may override the
keys of DEFAULT_PARAMS and must hold the station-specific keys of `station_params`):

==============  =========  ====================================================================
type            length     effect
==============  =========  ====================================================================
stuck_value     5-30 d     one positive value, drawn from U(p50, p90) of the station's wet days
                           (>= 1 mm), repeated every day
zero_fault      3-30 d     the gauge reads 0
spike           1 d        a local wet value x U(10, 50) (capped at 1500 mm), or, with
                           probability 0.5, an absolute U(500, 1500) mm value
scale_drift     30-90 d    multiplicative bias moving linearly from 1 to 0.3 or to 2.5
offset_noise    10-60 d    U(0.2, 1.0) mm added on dry (== 0) days
duplicate_block 7-31 d     a copy of an earlier block of the same station that holds at least
                           3 positive days (a dry block repeated is indistinguishable from dry
                           weather, so it is not a meaningful fault; see checks.py)
==============  =========  ====================================================================

Values are rounded to 0.1 mm like the real gauge data.
"""
from __future__ import annotations

import zlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from .common import to_jsonable
from .stations import StationSet

FAULT_TYPES = ("stuck_value", "zero_fault", "spike", "scale_drift", "offset_noise", "duplicate_block")
WET_MM = 1.0
MIN_VALID_DAYS_PER_YEAR = 200  # base rule (ruling); 300 is run as a sensitivity in the report
MIN_WET_DAYS_FOR_PARAMS = 20

DEFAULT_PARAMS = {
    "spike_mult_range": (10.0, 50.0),
    "spike_abs_range": (500.0, 1500.0),
    "spike_abs_prob": 0.5,
    "spike_local_days": 15,
    "max_mm": 1500.0,
    "drift_targets": (0.3, 2.5),
    "offset_range": (0.2, 1.0),
    "min_source_positive": 3,
    "max_source_tries": 200,
}
_STATION_KEYS = ("wet_p50", "wet_p90")


class InjectionImpossible(ValueError):
    """The injector cannot build a fault at this position (e.g. no earlier block to copy)."""


def _param(params: Mapping, key: str):
    if key in params:
        return params[key]
    if key in DEFAULT_PARAMS:
        return DEFAULT_PARAMS[key]
    raise KeyError(f"injection parameter {key!r} is required (see station_params)")


def station_params(series) -> dict:
    """Station-specific parameters: the 50th and 90th percentile of its wet-day (>= 1 mm) values."""
    data = np.asarray(series, dtype=np.float32)
    wet = data[np.isfinite(data) & (data >= WET_MM)]
    if len(wet) < MIN_WET_DAYS_FOR_PARAMS:
        raise ValueError(f"only {len(wet)} wet days: too few to calibrate a station's fault magnitudes")
    p50, p90 = np.percentile(wet, [50, 90])
    return {"wet_p50": float(p50), "wet_p90": float(p90)}


def _round(values) -> np.ndarray:
    return np.round(np.asarray(values, dtype=np.float32), 1)


def _keep_nan(out: np.ndarray, window: np.ndarray) -> np.ndarray:
    out = np.asarray(out, dtype=np.float32).copy()
    out[np.isnan(window)] = np.nan
    return out


def _window(series, start: int, length: int) -> np.ndarray:
    data = np.asarray(series, dtype=np.float32)
    if start < 0 or length < 1 or start + length > len(data):
        raise ValueError(f"window [{start}, {start + length}) is outside the series of {len(data)} days")
    return data[start:start + length]


def inject_stuck_value(series, start, length, rng, params):
    window = _window(series, start, length)
    value = max(float(_round(rng.uniform(_param(params, "wet_p50"), _param(params, "wet_p90")))), 0.1)
    return _keep_nan(np.full(length, value), window)


def inject_zero_fault(series, start, length, rng, params):
    window = _window(series, start, length)
    return _keep_nan(np.zeros(length), window)


def inject_spike(series, start, length, rng, params):
    """Every day of the window becomes an independent spike (the standard episode is 1 day)."""
    window = _window(series, start, length)
    data = np.asarray(series, dtype=np.float32)
    half = int(_param(params, "spike_local_days"))
    around = np.concatenate([data[max(0, start - half):start], data[start + length:start + length + half]])
    wet = around[np.isfinite(around) & (around >= WET_MM)]
    local = float(np.median(wet)) if len(wet) else float(_param(params, "wet_p50"))
    mult_lo, mult_hi = _param(params, "spike_mult_range")
    abs_lo, abs_hi = _param(params, "spike_abs_range")
    cap = float(_param(params, "max_mm"))
    use_abs = rng.random(length) < _param(params, "spike_abs_prob")
    mult = np.minimum(local * rng.uniform(mult_lo, mult_hi, length), cap)
    absolute = rng.uniform(abs_lo, abs_hi, length)
    return _keep_nan(_round(np.where(use_abs, absolute, mult)), window)


def inject_scale_drift(series, start, length, rng, params):
    window = _window(series, start, length)
    target = float(rng.choice(np.asarray(_param(params, "drift_targets"), dtype=float)))
    factor = np.linspace(1.0, target, length) if length > 1 else np.array([target])
    return _keep_nan(_round(window * factor.astype(np.float32)), window)


def inject_offset_noise(series, start, length, rng, params):
    window = _window(series, start, length)
    lo, hi = _param(params, "offset_range")
    noise = _round(rng.uniform(lo, hi, length))
    return _keep_nan(np.where(window == 0, noise, window), window)


def inject_duplicate_block(series, start, length, rng, params):
    """Copy an earlier block of `series` (true data, fully observed, >= 3 positive days)."""
    window = _window(series, start, length)
    data = np.asarray(series, dtype=np.float32)
    last_source = start - length  # the source must end before the window starts
    if last_source < 0:
        raise InjectionImpossible("no earlier block of this length exists")
    need = int(_param(params, "min_source_positive"))
    for _ in range(int(_param(params, "max_source_tries"))):
        source = int(rng.integers(0, last_source + 1))
        block = data[source:source + length]
        if np.isfinite(block).all() and (block > 0).sum() >= need:
            return _keep_nan(block, window)
    raise InjectionImpossible("no earlier fully observed block with enough rainy days was found")


@dataclass(frozen=True)
class FaultSpec:
    name: str
    min_len: int
    max_len: int
    min_changed: int  # an episode must alter at least this many days, else it is re-placed
    injector: Callable


DEFAULT_SPECS = {
    "stuck_value": FaultSpec("stuck_value", 5, 30, 3, inject_stuck_value),
    "zero_fault": FaultSpec("zero_fault", 3, 30, 3, inject_zero_fault),
    "spike": FaultSpec("spike", 1, 1, 1, inject_spike),
    "scale_drift": FaultSpec("scale_drift", 30, 90, 3, inject_scale_drift),
    "offset_noise": FaultSpec("offset_noise", 10, 60, 3, inject_offset_noise),
    "duplicate_block": FaultSpec("duplicate_block", 7, 31, 3, inject_duplicate_block),
}


def station_rng(seed: int, station_id: str) -> np.random.Generator:
    """Generator for one station: seeded by (seed, crc32(station id)), independent of station order."""
    return np.random.default_rng(np.random.SeedSequence([int(seed), zlib.crc32(station_id.encode("ascii"))]))


def clean_real_mask(station_set: StationSet, min_valid_days: int = MIN_VALID_DAYS_PER_YEAR) -> pd.DataFrame:
    """A day is clean real when it has a value, no NOAA flag, and its station-year has at least
    `min_valid_days` valid days."""
    valid = station_set.values.notna()
    year_valid = valid.groupby(valid.index.year).transform("sum")
    return valid & station_set.flags.eq("") & (year_valid >= min_valid_days)


def _identical_positive_streaks(series) -> np.ndarray:
    """Lengths (days) of every maximal streak of >= 2 identical positive values."""
    data = np.asarray(series, dtype=np.float32)
    same = np.zeros(len(data), dtype=bool)
    with np.errstate(invalid="ignore"):
        same[1:] = (data[1:] == data[:-1]) & (data[1:] > 0) & np.isfinite(data[1:])
    edges = np.diff(np.concatenate(([0], same.astype(np.int8), [0])))
    return np.flatnonzero(edges == -1) - np.flatnonzero(edges == 1) + 1


def _flag_runs(full: pd.DataFrame) -> list[tuple[str, int]]:
    flag = full["flag"].to_numpy(dtype=object)
    runs: list[tuple[str, int]] = []
    i = 0
    while i < len(flag):
        if flag[i] == "":
            i += 1
            continue
        j = i
        while j + 1 < len(flag) and flag[j + 1] == flag[i]:
            j += 1
        runs.append((str(flag[i]), j - i + 1))
        i = j + 1
    return runs


def calibrate_from_real_flags(station_set: StationSet, full: Mapping[str, pd.DataFrame]) -> dict:
    """Empirical stats of the REAL NOAA flags (whole history of the set's stations) and the
    injection ranges derived from them.

    `full` maps station id -> `stations.load_full_series` frame. Returns:
      flag_days   {flag: number of flagged values}
      runs        {flag: sorted lengths of consecutive same-flag runs}  (K and D are listed)
      identical_positive_streaks  {length: count} of streaks of identical positive values in the
                  real series (flagged or not), the natural background for the stuck rule
      used        the length range used for stuck_value and duplicate_block and why
    """
    flag_days: dict[str, int] = {}
    runs: dict[str, list[int]] = {}
    streaks: dict[int, int] = {}
    n_valid = 0
    for sid in station_set.meta["id"]:
        frame = full[sid]
        for flag, length in _flag_runs(frame):
            runs.setdefault(flag, []).append(length)
            flag_days[flag] = flag_days.get(flag, 0) + length
        for length in _identical_positive_streaks(frame["value"].to_numpy()):
            streaks[int(length)] = streaks.get(int(length), 0) + 1
        n_valid += int(frame["value"].notna().sum())
    runs = {flag: sorted(lengths) for flag, lengths in sorted(runs.items())}
    natural_max = max(streaks) if streaks else 1
    d_runs = runs.get("D", [])
    specs = DEFAULT_SPECS
    dup_hi = max([n for n in d_runs if n <= specs["duplicate_block"].max_len],
                 default=specs["duplicate_block"].max_len)
    stuck_lo = max(specs["stuck_value"].min_len, natural_max + 1)
    return {
        "n_valid_values": n_valid,
        "flag_days": dict(sorted(flag_days.items())),
        "runs": runs,
        "identical_positive_streaks": dict(sorted(streaks.items())),
        "used": {
            "duplicate_block": {
                "min_len": specs["duplicate_block"].min_len, "max_len": dup_hi,
                "basis": "real D runs are whole duplicated months (lengths "
                         f"{sorted(set(d_runs))}); a block of 7+ days tests the L1 threshold, the upper "
                         "end is the longest single-month run (two-month runs are two blocks)"},
            "stuck_value": {
                "min_len": stuck_lo, "max_len": specs["stuck_value"].max_len,
                "basis": "real K flags mark isolated days, not streaks; the longest natural streak of "
                         f"identical positive values in the real series is {natural_max} days, so "
                         "injected stuck episodes start above it"},
        },
    }


def specs_from_calibration(calibration: Mapping | None) -> dict[str, FaultSpec]:
    """DEFAULT_SPECS with the length ranges of `calibration["used"]` applied (None: defaults)."""
    specs = dict(DEFAULT_SPECS)
    if calibration is None:
        return specs
    for name, used in calibration["used"].items():
        specs[name] = replace(specs[name], min_len=int(used["min_len"]), max_len=int(used["max_len"]))
    return specs


def _stretch_ends(clean: np.ndarray) -> np.ndarray:
    """For each index, the last index of the run of clean days containing it (-1 when not clean)."""
    ends = np.full(len(clean), -1, dtype=np.int64)
    edges = np.diff(np.concatenate(([0], clean.astype(np.int8), [0])))
    for lo, hi in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)):
        ends[lo:hi] = hi - 1
    return ends


def _check_splits(station_set: StationSet, station_splits: Mapping[str, list]) -> dict[str, str]:
    owner: dict[str, str] = {}
    for split, ids in station_splits.items():
        for sid in ids:
            if sid in owner:
                raise ValueError(f"station {sid} is in both {owner[sid]} and {split}")
            owner[sid] = split
    missing = set(station_set.meta["id"]) - set(owner)
    extra = set(owner) - set(station_set.meta["id"])
    if missing or extra:
        raise ValueError(f"station splits do not match the station set (missing {sorted(missing)[:3]}, "
                         f"unknown {sorted(extra)[:3]})")
    return owner


def _inject_station(true: np.ndarray, clean: np.ndarray, rng, specs, density, min_gap_days):
    """Episodes for one station: list of (fault_type, start, length, faulty values)."""
    clean_idx = np.flatnonzero(clean)
    target_days = int(round(density * len(clean_idx)))
    if target_days == 0:
        return []
    try:
        params = station_params(true[clean])
    except ValueError:  # too few wet days to calibrate magnitudes: no episodes (see dataset_report)
        return []
    room = _stretch_ends(clean) - np.arange(len(true)) + 1  # days left in the clean stretch from each day
    blocked = np.zeros(len(true), dtype=bool)
    episodes, placed = [], 0
    tries_per_type = 30
    progress = True
    while placed < target_days and progress:
        progress = False
        for type_index in rng.permutation(len(FAULT_TYPES)):  # round-robin keeps the types balanced
            if placed >= target_days:
                break
            spec = specs[FAULT_TYPES[type_index]]
            for _ in range(tries_per_type):
                length = int(rng.integers(spec.min_len, spec.max_len + 1))
                fits = clean_idx[room[clean_idx] >= length]  # starts whose clean stretch is long enough
                if len(fits) == 0:
                    continue
                start = int(fits[rng.integers(len(fits))])
                if blocked[start:start + length].any():
                    continue
                try:
                    faulty = spec.injector(true, start, length, rng, params)
                except InjectionImpossible:
                    continue
                if int((faulty != true[start:start + length]).sum()) < spec.min_changed:
                    continue
                blocked[max(0, start - min_gap_days):start + length + min_gap_days] = True
                episodes.append((spec.name, start, length, faulty))
                placed += length
                progress = True
                break
    return episodes


def build_fault_dataset(station_set: StationSet, station_splits: Mapping[str, list], seed: int,
                        density: float = 0.08, min_gap_days: int = 5,
                        calibration: Mapping | None = None,
                        min_valid_days: int = MIN_VALID_DAYS_PER_YEAR) -> pd.DataFrame:
    """Long table (one row per station-day): station, date, value_true, value_obs, fault_type
    ('' = none), episode_id (-1 = none), split, clean_real, real_flag.

    Episodes are placed only on runs of clean real days, never overlap, and keep at least
    `min_gap_days` unaffected days between them; about `density` of each station's clean days lie
    inside an episode window, and the six types are dealt round-robin so they are about equally
    frequent. `value_true` is the real reading (NaN = missing, never 0); `value_obs` equals it except
    on the days an injector changed. `fault_type` is set ONLY on changed days, `episode_id` on every
    day of the window (an unchanged day inside a window, e.g. a dry day in a zero fault, is neither
    clean nor faulty). `min_valid_days` is the station-year threshold of `clean_real_mask`. `calibration` (from `calibrate_from_real_flags`) sets the length ranges;
    None uses DEFAULT_SPECS."""
    if not 0 < density < 1:
        raise ValueError("density must be in (0, 1)")
    owner = _check_splits(station_set, station_splits)
    specs = specs_from_calibration(calibration)
    clean_frame = clean_real_mask(station_set, min_valid_days)
    dates = station_set.values.index.to_numpy()
    pieces, next_id = [], 0
    for sid in station_set.meta["id"]:
        true = station_set.values[sid].to_numpy(np.float32)
        clean = clean_frame[sid].to_numpy()
        obs = true.copy()
        fault_type = np.full(len(true), "", dtype=object)
        episode_id = np.full(len(true), -1, dtype=np.int32)
        for name, start, length, faulty in _inject_station(true, clean, station_rng(seed, sid), specs,
                                                           density, min_gap_days):
            window = slice(start, start + length)
            changed = faulty != true[window]
            obs[window] = faulty
            fault_type[window][changed] = name
            episode_id[window] = next_id
            next_id += 1
        pieces.append(pd.DataFrame({
            "station": sid, "date": dates, "value_true": true, "value_obs": obs,
            "fault_type": fault_type, "episode_id": episode_id, "split": owner[sid],
            "clean_real": clean, "real_flag": station_set.flags[sid].to_numpy(dtype=object)}))
    table = pd.concat(pieces, ignore_index=True)
    return table.astype({"station": "category", "split": "category", "fault_type": "category"})


def dataset_report(table: pd.DataFrame, calibration: Mapping | None = None) -> dict:
    """Counts of episodes and faulty days per fault type per split (plus clean-day totals)."""
    faulty = table[table["fault_type"] != ""]
    splits = sorted(table["split"].unique())
    in_episode = table["episode_id"] >= 0
    out: dict = {"n_rows": int(len(table)), "n_episodes": int(table.loc[in_episode, "episode_id"].nunique()),
                 "splits": {}}
    for split in splits:
        rows = table["split"] == split
        by_type = {}
        for name in FAULT_TYPES:
            sel = faulty[(faulty["split"] == split) & (faulty["fault_type"] == name)]
            by_type[name] = {"episodes": int(sel["episode_id"].nunique()), "days": int(len(sel))}
        stations_with_clean = table.loc[rows & table["clean_real"], "station"].nunique()
        out["splits"][split] = {
            "n_stations": int(table.loc[rows, "station"].nunique()),
            "n_stations_with_clean_days": int(stations_with_clean),
            "n_stations_with_episodes": int(table.loc[rows & in_episode, "station"].nunique()),
            "clean_real_days": int((rows & table["clean_real"]).sum()),
            "clean_days_outside_episodes": int((rows & table["clean_real"] & ~in_episode).sum()),
            "episode_window_days": int((rows & in_episode).sum()),
            "by_type": by_type}
    if calibration is not None:
        out["calibration"] = to_jsonable(calibration)
    return out
