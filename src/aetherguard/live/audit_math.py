"""Mathematical integrity checks of published live tables (spec section 13, `live.audit`).

Every identity asserted here follows from the definition of the quantity, which is cited at the check. Features are
stored as float32 rounded from float64 values; rounding is monotone, so an inequality between two stored values that
holds in float64 holds in float32, and an identity that involves a sum or a ratio holds within `tol` (1e-4 mm +
1e-5 relative). A table without the columns a check needs is skipped (`found.checked` stays False).

    probability   risk, risk_lo, risk_hi in [0, 1] and finite exactly where the row is scored; level 0..3 with its name;
                  level_min <= level <= level_max.
    dates         date == run date + lead, `lead` == the file's lead, no duplicate cell, one cell set and one position
                  (lat, lon, region) per cell in every table of the run.
    rain_math     the identities of the `irain` / `iapi` / `inbr` features (`features.imerg_features`).
    rain_chain    the features of lead k against the forecast days and the features of lead 0 of the same run.
    shap          the listed contributions of a row (`HazardModel.contributions`) and `reasons_json` against the row.
"""
from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd

from ..alerts import levels as lv
from ..features import imerg_features as F
from ..features.compute import HEAVY_DAY_MM, MIN_SHARE_ACC3_MM, WET_MM
from ..hazard.model import TOP_CONTRIBUTIONS

ATOL = 1e-4                  # mm; float32 rounding of a sum of daily values
RTOL = 1e-5
BOUNDARY = 1e-4              # mm around a day threshold (1 mm wet day, 10 mm heavy day, 1 mm share floor)
WINDOWS = F.ACC_WINDOWS
DAYS_SINCE_NONE = F.LOOKBACK
CHAIN_ATOL = 1e-3            # mm; a chain sums up to 3 + 90 stored values


def tol(value, atol: float = ATOL, rtol: float = RTOL):
    return atol + rtol * np.abs(value)


def flag(found, check: str, table: pd.DataFrame, problems: dict[str, np.ndarray]) -> None:
    """Count the rows with any of `problems` ({text: mask}); the example text is that of the first problem of the row."""
    bad = np.zeros(len(table), dtype=bool)
    why = [""] * len(table)
    for text, mask in problems.items():
        mask = np.asarray(mask, dtype=bool)
        for i in np.flatnonzero(mask & ~bad):
            why[i] = text
        bad |= mask
    found.add(check, bad, table, why)


def _column(table: pd.DataFrame, name: str) -> np.ndarray | None:
    return table[name].to_numpy(dtype=np.float64) if name in table.columns else None


def _both(a, b):
    return np.isfinite(a) & np.isfinite(b)


def _above(x, y, extra: float = 0.0):
    """x exceeds y by more than the rounding tolerance (False where either is missing)."""
    with np.errstate(invalid="ignore"):
        return _both(x, y) & (x > y + extra + tol(y))


# ------------------------------------------------------------------------------------------------ probability

def check_probability(table: pd.DataFrame, found) -> None:
    if not {"risk", "risk_lo", "risk_hi", "level"} <= set(table.columns):
        return
    risk, lo, hi = (table[c].to_numpy(dtype=np.float64) for c in ("risk", "risk_lo", "risk_hi"))
    level = table["level"].to_numpy(dtype=np.int64)
    with np.errstate(invalid="ignore"):
        outside = np.zeros(len(table), dtype=bool)
        for values in (risk, lo, hi):
            outside |= (values < 0) | (values > 1)
    infinite = np.isinf(risk) | np.isinf(lo) | np.isinf(hi)
    names = np.array(lv.LEVEL_NAMES, dtype=object)
    in_range = (level >= 0) & (level <= lv.EMERGENCY)
    problems = {"a probability is infinite": infinite,
                "risk, risk_lo and risk_hi are not missing together": (np.isnan(risk) != np.isnan(lo)) | (np.isnan(risk) != np.isnan(hi)),
                "a probability outside [0, 1]": outside,
                "level outside 0..3": ~in_range,
                "level_name is not the name of the level": in_range & (table["level_name"].to_numpy(dtype=object)
                                                                       != names[np.where(in_range, level, 0)])
                if "level_name" in table.columns else np.zeros(len(table), dtype=bool)}
    if "raw_level" in table.columns:
        raw = table["raw_level"].to_numpy(dtype=np.int64)
        problems["raw_level outside 0..3"] = (raw < 0) | (raw > lv.EMERGENCY)
    if {"level_min", "level_max"} <= set(table.columns):
        low, high = (table[c].to_numpy(dtype=np.int64) for c in ("level_min", "level_max"))
        problems["level outside [level_min, level_max]"] = ~((low <= level) & (level <= high))
    flag(found, "probability", table, problems)


# ------------------------------------------------------------------------------------------------------ dates

def check_dates(table: pd.DataFrame, day, lead: int, found) -> None:
    """`date` is the target day (run date + lead), `lead` the file's lead, and a cell appears once."""
    problems: dict[str, np.ndarray] = {}
    if "date" in table.columns:
        expected = pd.Timestamp(day) + pd.Timedelta(days=lead)
        problems[f"date is not the run date + {lead} days"] = pd.to_datetime(table["date"]).to_numpy() != expected.to_datetime64()
    if "lead" in table.columns:
        problems[f"lead column is not {lead}"] = table["lead"].to_numpy() != lead
    problems["cell_id appears more than once"] = table["cell_id"].duplicated(keep=False).to_numpy()
    flag(found, "dates", table, problems)


def check_cell_sets(frames: dict[str, pd.DataFrame], founds: dict) -> None:
    """The tables of one run hold the same cells at the same position. The reference is `alerts` (else the first table)."""
    reference_name = "alerts" if "alerts" in frames else next(iter(frames))
    reference = frames[reference_name].drop_duplicates("cell_id").set_index("cell_id")
    for name, table in frames.items():
        if name == reference_name:
            continue
        known = table["cell_id"].isin(reference.index).to_numpy()
        problems = {f"cell not in {reference_name}": ~known}
        joined = reference.reindex(table["cell_id"].to_numpy())
        for column in ("lat", "lon", "region"):
            if column in table.columns and column in reference.columns:
                problems[f"{column} differs from {reference_name}"] = known & (table[column].to_numpy() != joined[column].to_numpy())
        flag(founds[name], "dates", table, problems)
        missing = int((~reference.index.isin(table["cell_id"])).sum())
        founds[name].add_count("dates", missing, f"{missing} cells of {reference_name} are not in this table")


# ---------------------------------------------------------------------------------------------------- rain_math

def check_rain_math(table: pd.DataFrame, found) -> None:
    """The identities of the IMERG rain features, from `imerg_features.accumulation_block`, `api_at` and
    `neighbourhood_stats` (day D is the last of the IMD-day series; a window with a missing day is NaN):

    * acc_n is the sum of the last n days: >= 0, and non-decreasing in n; a window with a missing day makes every longer
      window NaN;
    * max1d_w is the largest day of the last w days: acc_1 <= max1d_7 <= max1d_30, max1d_w <= acc_w <= w x max1d_w;
    * wetdays_30 counts days >= WET_MM among the last 30: an integer 0..30, 0 exactly when max1d_30 < WET_MM, and
      acc_30 >= WET_MM x wetdays_30;
    * share1_3 = acc_1 / acc_3 when acc_3 >= MIN_SHARE_ACC3_MM, else missing;
    * days_since_10mm is the age of the newest day >= HEAVY_DAY_MM (0 = D, 90 = none in the window), so it is <= 6
      exactly when max1d_7 >= HEAVY_DAY_MM and <= 29 exactly when max1d_30 >= HEAVY_DAY_MM, 0 exactly when acc_1 >= it;
    * accNn_vs_clim = acc_n / max(climatology, 1 mm) >= 0;
    * iapi_k = sum of k^j x rain(D - j), j = 0..120: >= 0, non-decreasing in k, >= k^(n-1) x acc_n, finite exactly when
      the rain of D is;
    * inbr_max/mean_acc_n are the max and mean of the n-day totals over the 3x3 pixels around the cell's own, which is
      one of them: mean <= max, own total <= max, own total / 9 <= mean, all >= 0.
    """
    acc = {n: _column(table, f"irain_acc_{n}") for n in WINDOWS}
    have = {n: a for n, a in acc.items() if a is not None}
    problems: dict[str, np.ndarray] = {}
    with np.errstate(invalid="ignore"):
        for n, a in have.items():
            problems[f"irain_acc_{n} is negative"] = np.isfinite(a) & (a < -ATOL)
        for n, m in zip(WINDOWS[:-1], WINDOWS[1:]):
            if n in have and m in have:
                problems[f"irain_acc_{m} is below irain_acc_{n}"] = _above(have[n], have[m])
                problems[f"irain_acc_{m} is known but irain_acc_{n} is missing"] = np.isnan(have[n]) & np.isfinite(have[m])
        max7, max30 = _column(table, "irain_max1d_7"), _column(table, "irain_max1d_30")
        for name, value in (("irain_max1d_7", max7), ("irain_max1d_30", max30)):
            if value is not None:
                problems[f"{name} is negative"] = np.isfinite(value) & (value < -ATOL)
        if max7 is not None:
            if 1 in have:
                problems["irain_acc_1 is above irain_max1d_7"] = _above(have[1], max7)
            if 7 in have:
                problems["irain_max1d_7 is above irain_acc_7"] = _above(max7, have[7])
                problems["irain_acc_7 is above 7 x irain_max1d_7"] = _above(have[7], 7 * max7)
            if 3 in have:
                problems["irain_acc_3 is above 3 x irain_max1d_7"] = _above(have[3], 3 * max7)
        if max7 is not None and max30 is not None:
            problems["irain_max1d_7 is above irain_max1d_30"] = _above(max7, max30)
        if max30 is not None and 30 in have:
            problems["irain_max1d_30 is above irain_acc_30"] = _above(max30, have[30])
            problems["irain_acc_30 is above 30 x irain_max1d_30"] = _above(have[30], 30 * max30)
        wet = _column(table, "irain_wetdays_30")
        if wet is not None:
            known = np.isfinite(wet)
            problems["irain_wetdays_30 is not an integer in 0..30"] = known & ((wet < 0) | (wet > 30) | (wet != np.round(wet)))
            if 30 in have:
                problems["irain_wetdays_30 and irain_acc_30 are not missing together"] = known != np.isfinite(have[30])
                problems["irain_acc_30 is below WET_MM x irain_wetdays_30"] = _both(wet, have[30]) & (have[30] < WET_MM * wet - tol(have[30]))
            if max30 is not None:
                problems["a wet day (>= 1 mm) exists but irain_wetdays_30 is 0"] = _both(wet, max30) & (max30 >= WET_MM + BOUNDARY) & (wet < 1)
                problems["irain_wetdays_30 > 0 without a day >= 1 mm"] = _both(wet, max30) & (max30 < WET_MM - BOUNDARY) & (wet > 0)
        share = _column(table, "irain_share1_3")
        if share is not None and 1 in have and 3 in have:
            enough = np.isfinite(have[3]) & (have[3] >= MIN_SHARE_ACC3_MM + BOUNDARY)
            small = np.isfinite(have[3]) & (have[3] < MIN_SHARE_ACC3_MM - BOUNDARY)
            with np.errstate(divide="ignore"):
                ratio = have[1] / have[3]
            problems["irain_share1_3 missing though irain_acc_3 >= 1 mm"] = enough & ~np.isfinite(share)
            problems["irain_share1_3 is not irain_acc_1 / irain_acc_3"] = enough & np.isfinite(share) & (np.abs(share - ratio) > 1e-5 + 1e-5 * np.abs(ratio))
            problems["irain_share1_3 outside [0, 1]"] = np.isfinite(share) & ((share < -1e-6) | (share > 1 + 1e-5))
            problems["irain_share1_3 present though irain_acc_3 < 1 mm"] = small & np.isfinite(share)
        for n in (3, 7, 30):
            anomaly = _column(table, f"irain_acc{n}_vs_clim")
            if anomaly is not None:
                problems[f"irain_acc{n}_vs_clim is negative"] = np.isfinite(anomaly) & (anomaly < -1e-6)
                if n in have:
                    problems[f"irain_acc{n}_vs_clim present though irain_acc_{n} is missing"] = np.isnan(have[n]) & np.isfinite(anomaly)
        days = _column(table, "irain_days_since_10mm")
        if days is not None:
            known = np.isfinite(days)
            problems["irain_days_since_10mm is not an integer in 0..90"] = known & ((days < 0) | (days > DAYS_SINCE_NONE) | (days != np.round(days)))
            if 90 in have:
                problems["irain_days_since_10mm and irain_acc_90 are not missing together"] = known != np.isfinite(have[90])
            heavy = HEAVY_DAY_MM
            if 1 in have:
                problems["irain_acc_1 >= 10 mm but irain_days_since_10mm is not 0"] = _both(days, have[1]) & (have[1] >= heavy + BOUNDARY) & (days != 0)
                problems["irain_days_since_10mm is 0 but irain_acc_1 < 10 mm"] = _both(days, have[1]) & (have[1] < heavy - BOUNDARY) & (days == 0)
            for value, limit, name in ((max7, 6, "irain_max1d_7"), (max30, 29, "irain_max1d_30")):
                if value is not None:
                    problems[f"{name} >= 10 mm but irain_days_since_10mm > {limit}"] = _both(days, value) & (value >= heavy + BOUNDARY) & (days > limit)
                    problems[f"{name} < 10 mm but irain_days_since_10mm <= {limit}"] = _both(days, value) & (value < heavy - BOUNDARY) & (days <= limit)
        api = {k: _column(table, f"iapi_{round(k * 100)}") for k in F.API_DECAYS}
        for k, value in api.items():
            if value is None:
                continue
            name = f"iapi_{round(k * 100)}"
            problems[f"{name} is negative"] = np.isfinite(value) & (value < -ATOL)
            if 1 in have:
                problems[f"{name} and irain_acc_1 are not missing together"] = np.isfinite(value) != np.isfinite(have[1])
            for n, a in have.items():
                problems[f"{name} is below {k}^{n - 1} x irain_acc_{n}"] = _both(value, a) & (value < k ** (n - 1) * a - tol(a))
        decays = list(F.API_DECAYS)
        for k, j in zip(decays[:-1], decays[1:]):
            if api[k] is not None and api[j] is not None:
                problems[f"iapi_{round(k * 100)} is above iapi_{round(j * 100)}"] = _above(api[k], api[j])
        for n in F.NBR_WINDOWS:
            top, mean = _column(table, f"inbr_max_acc_{n}"), _column(table, f"inbr_mean_acc_{n}")
            own = have.get(n)
            for name, value in ((f"inbr_max_acc_{n}", top), (f"inbr_mean_acc_{n}", mean)):
                if value is not None:
                    problems[f"{name} is negative"] = np.isfinite(value) & (value < -ATOL)
            if top is not None and mean is not None:
                problems[f"inbr_mean_acc_{n} is above inbr_max_acc_{n}"] = _above(mean, top)
            if top is not None and own is not None:
                problems[f"inbr_max_acc_{n} is below the cell's own irain_acc_{n}"] = _both(top, own) & (top < own - tol(own))
                problems[f"inbr_max_acc_{n} missing though the cell's own total is known"] = np.isfinite(own) & ~np.isfinite(top)
            if mean is not None and own is not None:
                problems[f"inbr_mean_acc_{n} is below irain_acc_{n} / 9"] = _both(mean, own) & (mean < own / 9 - tol(own))
    if problems:
        flag(found, "rain_math", table, problems)


# --------------------------------------------------------------------------------------------------- rain_chain

def _aligned(table: pd.DataFrame, reference: pd.DataFrame) -> pd.DataFrame:
    return reference.drop_duplicates("cell_id").set_index("cell_id").reindex(table["cell_id"].to_numpy())


def check_rain_chain(tables: dict[int, pd.DataFrame], founds: dict) -> None:
    """The features of lead k (IMD day D + k) against the forecast days d_1..d_k (`gfs_rain_d*`, the IMD-day rain the
    series is extended with, `forecast_features.imd_series_with_forecast`) and the features of lead 0 of the same run
    (the series up to D). The day-D value shared by both is the same stored series, so, with x(D) = irain_acc_1 of lead 0:

    * irain_acc_1 of lead k == d_k, and acc_n of lead k == the sum of its last n forecast days when n <= k;
    * for n > k: acc_n(k) = d_1 + .. + d_k + acc_(n-k)(0); acc_(n-k) is not a stored window unless n-k is one, so it lies
      between the stored windows around n-k (acc is non-decreasing in the window);
    * max1d_w(k) is the maximum over d_1..d_k and a part of lead 0's w-day window that contains day D: it is >= the larger
      of max(d_1..d_k) and x(D) (k <= 6) and <= the larger of max(d_1..d_k) and max1d_w(0);
    * wetdays_30(k) is between #(d_i >= 1 mm) and #(d_i >= 1 mm) + wetdays_30(0);
    * days_since_10mm(k) = k - i for the newest forecast day i with d_i >= 10 mm, else min(90, days_since_10mm(0) + k);
    * iapi_c(k) <= c x iapi_c(k-1) + d_k (the recursion; the spin-up term -c^121 x rain(D+k-121) is never positive).
    """
    base = tables.get(0)
    if base is None:
        return
    for k in (1, 2, 3):
        table = tables.get(k)
        columns = [f"gfs_rain_d{i}" for i in range(1, k + 1)]
        if table is None or not all(c in table.columns for c in columns):
            continue
        ref = _aligned(table, base)
        d = [table[c].to_numpy(dtype=np.float64) for c in columns]

        def known(name: str) -> bool:
            return name in table.columns and name in ref.columns
        problems: dict[str, np.ndarray] = {}
        total = np.sum(d, axis=0)
        offset = CHAIN_ATOL
        with np.errstate(invalid="ignore"):
            for n in WINDOWS:
                name = f"irain_acc_{n}"
                if not known(name):
                    continue
                a = table[name].to_numpy(dtype=np.float64)
                if n <= k:
                    expected = np.sum(d[k - n:], axis=0)
                    problems[f"{name} is not the sum of the last {n} forecast days"] = _both(a, expected) & (np.abs(a - expected) > offset + RTOL * np.abs(expected))
                    continue
                gap = n - k
                lo = max(w for w in WINDOWS if w <= gap)
                hi = min(w for w in WINDOWS if w >= gap)
                low, high = (ref[f"irain_acc_{w}"].to_numpy(dtype=np.float64) for w in (lo, hi))
                what = f"irain_acc_{gap}(0)" if lo == hi else f"irain_acc_{lo}(0)..irain_acc_{hi}(0)"
                problems[f"{name} is not the forecast days + {what}"] = (
                    _both(a, total + low) & (a < total + low - offset - RTOL * np.abs(a))) | (
                    _both(a, total + high) & (a > total + high + offset + RTOL * np.abs(a)))
            if known("irain_max1d_7") and known("irain_acc_1"):
                largest = np.max(d, axis=0)
                for name in ("irain_max1d_7", "irain_max1d_30"):
                    if not known(name):
                        continue
                    value = table[name].to_numpy(dtype=np.float64)
                    reference = ref[name].to_numpy(dtype=np.float64)
                    today = ref["irain_acc_1"].to_numpy(dtype=np.float64)
                    problems[f"{name} is below the forecast days or the rain of day D"] = _both(value, largest) & _both(value, today) & (
                        value < np.maximum(largest, today) - offset)
                    problems[f"{name} is above the forecast days and lead 0's {name}"] = _both(value, largest) & _both(value, reference) & (
                        value > np.maximum(largest, reference) + offset)
            if "irain_wetdays_30" in table.columns:
                wet = table["irain_wetdays_30"].to_numpy(dtype=np.float64)
                forecast_wet = np.sum([x >= WET_MM for x in d], axis=0).astype(np.float64)
                problems["irain_wetdays_30 is below the wet forecast days"] = _both(wet, total) & (wet < forecast_wet)
                observed = ref["irain_wetdays_30"].to_numpy(dtype=np.float64)
                problems["irain_wetdays_30 exceeds the wet forecast days + lead 0's"] = _both(wet, observed) & _both(wet, total) & (wet > forecast_wet + observed)
            if "irain_days_since_10mm" in table.columns:
                days = table["irain_days_since_10mm"].to_numpy(dtype=np.float64)
                newest = np.zeros(len(table))
                for i, x in enumerate(d, start=1):
                    newest = np.where(np.nan_to_num(x, nan=-1.0) >= HEAVY_DAY_MM, i, newest)
                observed = ref["irain_days_since_10mm"].to_numpy(dtype=np.float64)
                expected = np.where(newest > 0, k - newest, np.minimum(DAYS_SINCE_NONE, observed + k))
                missing = np.isnan(np.sum(d, axis=0))
                problems["irain_days_since_10mm is not the age of the newest 10 mm day of the forecast and lead 0"] = (
                    ~missing & _both(days, expected) & (days != expected))
            previous = tables.get(k - 1)
            if previous is not None:
                before = _aligned(table, previous)
                for decay in F.API_DECAYS:
                    name = f"iapi_{round(decay * 100)}"
                    if name in table.columns and name in before.columns:
                        value = table[name].to_numpy(dtype=np.float64)
                        bound = decay * before[name].to_numpy(dtype=np.float64) + d[-1]
                        problems[f"{name} is above {decay} x the previous lead's + the forecast day"] = _above(value, bound)
        flag(founds[k], "rain_chain", table, problems)


# -------------------------------------------------------------------------------------------------------- shap

def _listed(text):
    try:
        value = json.loads(text) if isinstance(text, str) else None
    except ValueError:
        return None
    return value if isinstance(value, list) else None


def _missing(x) -> bool:
    return x is None or (isinstance(x, float) and x != x) or (isinstance(x, float) and math.isinf(x))


def _same(a, b, rel: float) -> bool:
    if a == b:
        return True
    if _missing(a) or _missing(b):
        return _missing(a) and _missing(b)
    return abs(a - b) <= rel * max(abs(a), abs(b)) + 1e-12


def check_shap(table: pd.DataFrame, features: pd.DataFrame | None, model_columns, found) -> None:
    """The contributions of a row (`HazardModel.contributions`: the `top` largest |log-odds contribution| of the model's
    inputs, in descending |contribution|, with the input's value; value null when it is missing) and `reasons_json`.
    Every scored row lists min(5, #inputs) of them, an unscored row none; each `value` is the row's value of that input
    in the lead's features table (1e-4 relative); `reasons_json` repeats the risk (point, lo, hi, per_100k), the level
    name, the contributions, the codes and the confidence of the row."""
    if "shap_json" not in table.columns:
        return
    columns = list(model_columns)
    expected = min(TOP_CONTRIBUTIONS, len(columns)) if columns else None
    position = (pd.Index(features["cell_id"]).get_indexer(table["cell_id"]).tolist() if features is not None else None)
    values: dict[str, list] = {}
    risk = {c: table[c].to_numpy(dtype=np.float64).tolist() for c in ("risk", "risk_lo", "risk_hi", "risk_per_100k") if c in table.columns}
    scored = [x == x and not math.isinf(x) for x in risk["risk"]] if "risk" in risk else [True] * len(table)

    def strings(name):
        return table[name].tolist() if name in table.columns else None
    reasons, codes, causes = strings("reasons_json"), strings("reason_codes"), strings("confidence_causes")
    level_name, confidence = strings("level_name"), strings("confidence")
    shap_json = table["shap_json"].tolist()
    problems: list[list[str]] = [[] for _ in range(len(table))]
    for i, text in enumerate(shap_json):
        listed = _listed(text)
        mine = problems[i]
        if listed is None:
            mine.append("shap_json is not a JSON list")
            continue
        if not scored[i]:
            if listed:
                mine.append("contributions on a row without a score")
        elif not listed or (expected is not None and len(listed) != expected):
            mine.append(f"{len(listed)} contributions where {expected} are listed")
        items = [c for c in listed if isinstance(c, dict)]
        size = [abs(c["contribution"]) if isinstance(c.get("contribution"), (int, float)) else math.nan for c in items]
        if len(items) != len(listed) or any(x != x or math.isinf(x) for x in size):
            mine.append("a contribution is not a number")
        elif any(a < b for a, b in zip(size, size[1:])):
            mine.append("contributions not sorted by |contribution|")
        names = [c.get("feature") for c in items]
        if len(set(names)) != len(names):
            mine.append("a feature is listed twice")
        if columns and any(n not in columns for n in names):
            mine.append("a listed feature is not a model input")
        if features is not None and position[i] >= 0:
            for item in items:
                name = item.get("feature")
                if name in features.columns:
                    if name not in values:
                        values[name] = features[name].to_numpy(dtype=np.float64).tolist()
                    stored = values[name][position[i]]
                    if not _same(item.get("value"), None if stored != stored else stored, 1e-4):
                        mine.append(f"value of {name} differs from the features table")
                        break
        if reasons is not None:
            detail = _listed_dict(reasons[i])
            if detail is None:
                mine.append("reasons_json is not a JSON object")
                continue
            reported = detail.get("risk") or {}
            for key, column in (("point", "risk"), ("lo", "risk_lo"), ("hi", "risk_hi"), ("per_100k", "risk_per_100k")):
                if column in risk and not _same(reported.get(key), risk[column][i], 1e-12):
                    mine.append(f"reasons_json risk.{key} differs from {column}")
            if level_name is not None and detail.get("level") != level_name[i]:
                mine.append("reasons_json level differs from level_name")
            if "shap" in detail and detail["shap"] != listed:
                mine.append("reasons_json shap differs from shap_json")
            if codes is not None and detail.get("codes") != (codes[i].split(";") if isinstance(codes[i], str) and codes[i] else []):
                mine.append("reasons_json codes differ from reason_codes")
            state = detail.get("confidence") or {}
            if confidence is not None and state.get("state") != confidence[i]:
                mine.append("reasons_json confidence differs from confidence")
            if causes is not None and state.get("causes") != (causes[i].split(";") if isinstance(causes[i], str) and causes[i] else []):
                mine.append("reasons_json confidence causes differ from confidence_causes")
    found.add("shap", np.array([bool(p) for p in problems]), table, ["; ".join(p) for p in problems])


def _listed_dict(text):
    try:
        value = json.loads(text) if isinstance(text, str) else None
    except ValueError:
        return None
    return value if isinstance(value, dict) else None
