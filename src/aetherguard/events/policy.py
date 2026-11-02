"""Label policy as pure functions: trigger classes, label regions (D1) and the positive rule (D2)."""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from ..config import load_config
from ..grid import region_labels

# A trigger text containing any of these words is rain-class (design D2); "flooding" deliberately is not.
_RAIN_WORDS = ("rain", "downpour", "monsoon", "cyclone")
_CONSTRUCTION_MINING = frozenset({"construction", "mining", "quarry", "construction_mining"})
_SNOW = frozenset({"snowfall", "snowmelt", "snowfall_snowmelt", "freeze_thaw"})

HIMALAYA_COUNTRIES = frozenset({"IN", "NP", "BT"})
GHATS_COUNTRIES = frozenset({"IN"})
POSITIVE_REGIONS = frozenset({"himalaya", "western_ghats"})
MAX_ACCURACY_KM = 5.0


def normalize_trigger(raw) -> str:
    """Map a catalogue trigger string to a trigger class (case, underscores, spaces and hyphens ignored)."""
    if raw is None or pd.isna(raw):
        return "unknown"
    text = re.sub(r"[\s_\-]+", "_", str(raw).strip().lower()).strip("_")
    if text in ("", "unknown"):
        return "unknown"
    if any(word in text for word in _RAIN_WORDS):
        return "rain"
    if text == "earthquake":
        return "earthquake"
    if text in _CONSTRUCTION_MINING:
        return "construction_mining"
    if text in _SNOW:
        return "snow"
    return "other"


def assign_regions(country_code, lat, lon) -> np.ndarray:
    """Label region per record (D1): 'himalaya', 'western_ghats' or '' for out of scope.

    The boxes come from configs/domain.yaml through `grid.region_labels` (half-open, the Ghats box
    takes precedence where they overlap), refined by country: the Himalaya box only counts India,
    Nepal and Bhutan and the Ghats box only India.
    """
    country = np.asarray(country_code, dtype=object)
    box = region_labels(lat, lon)
    out = np.full(box.shape, "", dtype=object)
    out[(box == "himalaya") & np.isin(country, list(HIMALAYA_COUNTRIES))] = "himalaya"
    out[(box == "western_ghats") & np.isin(country, list(GHATS_COUNTRIES))] = "western_ghats"
    return out


def assign_region(country_code: str, lat: float, lon: float) -> str:
    return str(assign_regions([country_code], [lat], [lon])[0])


def positive_flags(trigger_class, accuracy_km, event_date, region) -> tuple[np.ndarray, np.ndarray]:
    """D2 positive rule, vectorised. Returns (is_positive, not_positive_reason), reason None when positive.

    Inputs must already be valid records (known date, coordinates and in-scope region); anything else
    raises, because such records are dropped from the store before this rule applies. The reason is the
    first failing test in the order trigger, accuracy, period.
    """
    trigger = np.asarray(trigger_class, dtype=object)
    accuracy = np.asarray(accuracy_km, dtype=float)
    dates = pd.to_datetime(pd.Series(np.asarray(event_date)))
    if dates.isna().any():
        raise ValueError("event_date must be known to classify a positive (missing dates are dropped first)")
    if not pd.Series(np.asarray(region, dtype=object)).isin(POSITIVE_REGIONS).all():
        raise ValueError(f"region must be one of {sorted(POSITIVE_REGIONS)} to classify a positive")
    period = load_config("domain")["period"]
    outside = ((dates < pd.Timestamp(period["start"])) | (dates > pd.Timestamp(period["end"]))).to_numpy()

    reasons = np.full(len(trigger), None, dtype=object)
    undecided = np.ones(len(trigger), dtype=bool)
    for failed, reason in (
        ((trigger != "rain") & (trigger != "unknown"), "non_rain_trigger"),
        (trigger == "unknown", "unknown_trigger"),
        (np.isnan(accuracy), "unknown_accuracy"),
        (accuracy > MAX_ACCURACY_KM, "poor_accuracy"),
        (outside, "outside_period"),
    ):
        hit = undecided & failed
        reasons[hit] = reason
        undecided &= ~hit
    return undecided, reasons


def is_positive(trigger_class: str, accuracy_km: float, event_date, region: str) -> tuple[bool, str | None]:
    flags, reasons = positive_flags([trigger_class], [accuracy_km], [event_date], [region])
    return bool(flags[0]), reasons[0]
