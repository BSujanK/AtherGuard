import math

import pandas as pd
import pytest

from aetherguard.events import policy


@pytest.mark.parametrize("raw, expected", [
    ("rain", "rain"), ("Rain", "rain"), ("RAIN", "rain"), ("downpour", "rain"), ("Downpour", "rain"),
    ("continuous_rain", "rain"), ("Continuous Rain", "rain"), ("continuous-rain", "rain"),
    ("monsoon", "rain"), ("Heavy Rain", "rain"), ("heavy_rain", "rain"),
    ("tropical_cyclone", "rain"), ("Tropical Cyclone", "rain"), ("Cyclone", "rain"),
    ("", "unknown"), ("  ", "unknown"), ("unknown", "unknown"), ("Unknown", "unknown"),
    (None, "unknown"), (float("nan"), "unknown"),
    ("earthquake", "earthquake"), ("Earthquake", "earthquake"),
    ("construction", "construction_mining"), ("mining", "construction_mining"),
    ("quarry", "construction_mining"), ("Quarry ", "construction_mining"),
    ("snowfall_snowmelt", "snow"), ("snowfall", "snow"), ("snowmelt", "snow"), ("freeze_thaw", "snow"),
    ("flooding", "other"), ("volcano", "other"), ("no_apparent_trigger", "other"), ("other", "other"),
    ("Heavy Rainfall", "rain"), ("rainfall", "rain"), ("Monsoon rains", "rain"), ("heavy-rain storm", "rain"),
    ("Tropical Cyclone Amphan", "rain"), ("cyclone_winds", "rain"), ("DOWNPOUR_AND_FLOODING", "rain"),
    ("Flooding", "other"), ("Tropical Storm", "other"), ("dam_embankment_collapse", "other"),
])
def test_normalize_trigger(raw, expected):
    assert policy.normalize_trigger(raw) == expected


@pytest.mark.parametrize("country, lat, lon, expected", [
    ("IN", 30.0, 79.0, "himalaya"),         # Uttarakhand
    ("NP", 28.0, 84.0, "himalaya"),
    ("BT", 27.5, 90.0, "himalaya"),
    ("IN", 11.55, 76.13, "western_ghats"),  # Wayanad
    ("IN", 22.0, 72.0, "himalaya"),         # lower-left himalaya corner is inside (closed lower edges)
    ("IN", 36.0, 80.0, ""),                 # upper edge is open
    ("IN", 30.0, 98.0, ""),
    ("IN", 21.49, 76.0, "western_ghats"),
    ("IN", 21.5, 76.0, ""),                 # ghats upper edge is open and below the himalaya box
    ("IN", 8.0, 76.5, "western_ghats"),
    ("IN", 7.99, 76.5, ""),
    ("IN", 15.0, 72.5, "western_ghats"),
    ("IN", 15.0, 72.49, ""),
    ("IN", 15.0, 78.5, ""),
    ("NP", 15.0, 76.0, ""),                 # only India counts for the Ghats
    ("MM", 25.0, 95.0, ""),
    ("BD", 24.0, 91.0, ""),
    ("PK", 34.0, 73.0, ""),
    ("CN", 30.0, 90.0, ""),
    ("", 30.0, 79.0, ""),
    ("IN", float("nan"), 79.0, ""),
])
def test_assign_region(country, lat, lon, expected):
    assert policy.assign_region(country, lat, lon) == expected


def test_assign_regions_vectorised_matches_scalar():
    country = pd.Series(["IN", "NP", "MM", "IN"])
    lat = pd.Series([30.0, 28.0, 25.0, 11.55])
    lon = pd.Series([79.0, 84.0, 95.0, 76.13])
    assert policy.assign_regions(country, lat, lon).tolist() == ["himalaya", "himalaya", "", "western_ghats"]


def decide(trigger_class="rain", accuracy_km=5.0, date="2015-07-01", region="himalaya"):
    return policy.is_positive(trigger_class, accuracy_km, pd.Timestamp(date), region)


def test_accuracy_boundary_is_inclusive_at_five_km():
    assert decide(accuracy_km=5.0) == (True, None)
    assert decide(accuracy_km=5.0001) == (False, "poor_accuracy")
    assert decide(accuracy_km=0.0) == (True, None)


def test_period_boundaries_are_inclusive():
    assert decide(date="2007-01-01") == (True, None)
    assert decide(date="2024-12-31") == (True, None)
    assert decide(date="2006-12-31") == (False, "outside_period")
    assert decide(date="2025-01-01") == (False, "outside_period")


def test_non_rain_and_unknown_triggers_are_not_positive():
    assert decide(trigger_class="unknown") == (False, "unknown_trigger")
    for cls in ("earthquake", "construction_mining", "snow", "other"):
        assert decide(trigger_class=cls) == (False, "non_rain_trigger")


def test_unknown_accuracy_is_not_positive():
    assert decide(accuracy_km=math.nan) == (False, "unknown_accuracy")


def test_reason_is_the_first_failing_test_in_order():
    assert decide("earthquake", math.nan, "2001-01-01") == (False, "non_rain_trigger")
    assert decide("unknown", 50.0, "2001-01-01") == (False, "unknown_trigger")
    assert decide("rain", math.nan, "2001-01-01") == (False, "unknown_accuracy")
    assert decide("rain", 25.0, "2001-01-01") == (False, "poor_accuracy")


def test_both_regions_can_be_positive():
    assert decide(region="western_ghats") == (True, None)


def test_is_positive_rejects_records_that_should_have_been_dropped_first():
    with pytest.raises(ValueError, match="region"):
        decide(region="")
    with pytest.raises(ValueError, match="date"):
        policy.is_positive("rain", 1.0, pd.NaT, "himalaya")


def test_positive_flags_vectorised():
    flags, reasons = policy.positive_flags(
        pd.Series(["rain", "unknown", "rain", "rain", "rain", "snow"]),
        pd.Series([5.0, 1.0, 5.5, math.nan, 1.0, 1.0]),
        pd.Series(pd.to_datetime(["2007-01-01", "2010-01-01", "2010-01-01", "2010-01-01", "2025-01-01", "2010-01-01"])),
        pd.Series(["himalaya"] * 6),
    )
    assert flags.tolist() == [True, False, False, False, False, False]
    assert reasons.tolist() == [None, "unknown_trigger", "poor_accuracy", "unknown_accuracy",
                                "outside_period", "non_rain_trigger"]
