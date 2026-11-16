"""Alert levels defined by how often they may fire: a frequency cap per level, region and season.

The model card's levels are defined by detection: Watch, Warning and Emergency sit at the risks that caught about 90%,
75% and 50% of the development positives, however often that makes them fire. A frequency-capped scheme instead declares,
per level, the largest share of cell-days the level may be raised on, in each region and each season, and sets the
threshold from the development risk distribution of that region and season:

* `cap_threshold`: the lowest risk threshold at which at most the declared share of the (finite) development risks reach
  it. Ties at the cut are left out, so the share is never exceeded on the data it was set on.
* `frequency_thresholds`: per (region, season) the three thresholds, never below a floor (the card's thresholds, so a cap
  only ever removes alerts: in a season where a level already fires less often than its cap, nothing changes), and
  non-decreasing from Watch to Emergency.

The seasons are those of `phase8_season_validity`: the monsoon (June-September), the post-monsoon (October-December) and
the rest of the year (January-May).

`scheme_document` writes the scheme in the format the live run reads from a model card (`alert_levels.<level>.risk` and
`risk_by_region`), once per season, so `season_card(document, month)` is a card that `levels.card_region_thresholds`
reads, and `row_thresholds` gives the per-cell-day thresholds `levels.raw_level` and the hysteresis take. A document is
always written to its own file, never into a frozen card.
"""
from __future__ import annotations

import numpy as np

from . import levels as lv

SEASONS = {"monsoon": (6, 7, 8, 9), "post_monsoon": (10, 11, 12), "rest": (1, 2, 3, 4, 5)}
SEASON_NAMES = tuple(SEASONS)
_SEASON_OF_MONTH = {m: s for s, months in SEASONS.items() for m in months}
SCHEMA = "aetherguard.frequency_levels/1"


def season_of_month(month: int) -> str:
    return _SEASON_OF_MONTH[int(month)]


def season_index(months) -> np.ndarray:
    """The position in `SEASON_NAMES` of the season of each month."""
    lookup = np.array([0] + [SEASON_NAMES.index(_SEASON_OF_MONTH[m]) for m in range(1, 13)])
    return lookup[np.asarray(months, dtype=np.int64)]


def cap_threshold(risk, share: float) -> float:
    """The lowest threshold t with at most `share` of the finite values of `risk` at or above t; -inf when every value
    may fire (or there is none)."""
    values = np.asarray(risk, dtype=np.float64)
    values = values[np.isfinite(values)]
    allowed = int(np.floor(share * len(values) + 1e-9))
    if allowed >= len(values):
        return -np.inf
    # the (allowed + 1)-th largest value must stay below t, so t is the next float above it
    cut = np.partition(values, len(values) - allowed - 1)[len(values) - allowed - 1]
    return float(np.nextafter(cut, np.inf))


def _check_caps(caps: dict) -> None:
    for season, shares in caps.items():
        if season not in SEASONS:
            raise ValueError(f"unknown season {season!r}; seasons are {SEASON_NAMES}")
        shares = [float(s) for s in shares]
        if len(shares) != 3 or not all(0.0 <= s <= 1.0 for s in shares) or shares != sorted(shares, reverse=True):
            raise ValueError(f"caps of {season} must be three shares in [0, 1], not rising from Watch to Emergency: {shares}")


def frequency_thresholds(samples: dict[tuple[str, str], np.ndarray], caps: dict[str, tuple[float, float, float]],
                         floor: dict[str, lv.Thresholds] | None) -> dict[tuple[str, str], tuple[float, float, float]]:
    """(watch, warning, emergency) thresholds of every (region, season) of `samples` (its development risks).

    `caps[season]` holds the largest shares of cell-days at Watch or above, Warning or above and Emergency. A threshold
    is the `cap_threshold` of its share, raised to the region's `floor` where one is given, then made non-decreasing
    across the levels."""
    _check_caps(caps)
    out = {}
    for (region, season), risk in samples.items():
        values = [cap_threshold(risk, share) for share in caps[season]]
        if floor is not None and region in floor:
            values = np.maximum(values, floor[region].as_array())
        out[(region, season)] = tuple(float(v) for v in np.maximum.accumulate(np.asarray(values, dtype=np.float64)))
    return out


def scheme_document(name: str, thresholds: dict[tuple[str, str], tuple[float, float, float]],
                    pooled: dict[str, tuple[float, float, float]], caps: dict[str, tuple[float, float, float]],
                    floor: str | None, provenance: dict, shares: dict | None = None) -> dict:
    """The scheme as a document: per season the months and an `alert_levels` block in the card's format (the pooled
    threshold as `risk`, the region thresholds as `risk_by_region`, the declared `cap_share`, and the realised development
    share per region where `shares[(region, season)]` gives it)."""
    _check_caps(caps)
    seasons = {}
    for season, months in SEASONS.items():
        regions = sorted(r for r, s in thresholds if s == season)
        if not regions:
            continue
        levels = {}
        for k, level in enumerate(lv.THRESHOLD_NAMES):
            entry = {"risk": float(pooled[season][k]),
                     "risk_by_region": {r: float(thresholds[(r, season)][k]) for r in regions},
                     "cap_share": float(caps[season][k])}
            if shares is not None:
                entry["dev_share_by_region"] = {r: float(shares[(r, season)][k]) for r in regions if (r, season) in shares}
            levels[level] = entry
        seasons[season] = {"months": list(months), "alert_levels": levels}
    return {"schema": SCHEMA, "name": name, "floor": floor, "seasons": seasons, "provenance": provenance,
            "status": "a candidate level scheme; the live run does not read it"}


def season_card(document: dict, month: int) -> dict:
    """The card-shaped block of the season of `month`: what `levels.card_region_thresholds` reads."""
    return {"alert_levels": document["seasons"][season_of_month(month)]["alert_levels"]}


def row_thresholds(document: dict, regions, months) -> np.ndarray:
    """(cells, days, 3) thresholds: those of each cell's region (`regions`, one per cell) in the season of each day's
    month (`months`, one per day)."""
    regions, months = np.asarray(regions).astype(str), np.asarray(months, dtype=np.int64)
    out = np.full((len(regions), len(months), 3), np.nan)
    for season in document["seasons"]:
        days = np.isin(months, SEASONS[season])
        if not days.any():
            continue
        card = {"alert_levels": document["seasons"][season]["alert_levels"]}
        for region, thr in lv.card_region_thresholds(card, np.unique(regions)).items():
            out[np.ix_(regions == region, days)] = thr.as_array()
    if np.isnan(out).any():
        raise ValueError("the document has no thresholds for some of the months asked for")
    return out
