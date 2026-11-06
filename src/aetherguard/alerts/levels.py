"""Alert levels: risk -> level mapping, the `uncertain_high` rule, the card threshold adapter and hysteresis.

Levels: 0 Normal < 1 Watch <= 2 Warning <= 3 Emergency, from the calibrated risk against the thresholds of the
hazard model card. Thresholds are never hardcoded: `thresholds_from_card` reads a card that names them
(`alert_levels` / `alert_thresholds` / `thresholds_oof` / `thresholds` with keys watch, warning, emergency, as float or
{"risk": float}, any letter case; the first block that names all three wins) and
otherwise falls back to the operating points of the v1 card named in `configs/alerts.yaml` (`v1_card_fallback`),
logging which source was used.

`uncertain_high`: when the point risk is below Watch but the upper interval bound `risk_hi` reaches Watch, the level
is raised to Watch (recall-first).

Thresholds by region: a card calibrated per region (v3) gives each region its own risk thresholds (`risk_by_region`).
`RegionThresholds` holds them with the pooled thresholds for any other region; `level_from_risk`, `uncertain_high_mask`,
`raw_level` and `apply_hysteresis` take either kind plus the region of every row (a cell has one region). Plain
`Thresholds` ignore the region.

Thresholds per row: where the thresholds also change with the day (region x month operating points), the thresholds
argument may instead be an array of the three thresholds (watch, warning, emergency) of every score, shape
`risk.shape + (3,)`. The region is then ignored. Hysteresis steps down against the thresholds of the row it decides on.

Hysteresis is a per-cell state machine over consecutive calendar days: the level steps UP to the raw level at once; it
steps DOWN one level only after `exit_days` consecutive days on which the raw level is below the current level AND the
risk is below `exit_factor` x the current level's threshold (the counter restarts after each step and whenever a day
does not qualify). A gap of more than one calendar day between two rows of a cell has no information, so the state
restarts at the raw level. The result does not depend on the row order of the input.

Hold release (spec section 11, the rain trigger): rows flagged `release` (no recent rain through the hold window) may
not hold a level the rain rule caps: where the machine would hold a state above the raw level, the state becomes
`cap[state]`, never below the raw level, and the step-down counter restarts. `release` may also be given per row and
held level (shape (rows, 4)), when the hold window depends on the level held.

Blind-hold limit (spec section 11): a row without a score (NaN risk: the model inputs are missing) never qualifies for a
step down, so an outage would hold a level indefinitely. With `blind_hold_days` H, a level is held over at most H
consecutive rows without a score; on each further such row the held state drops one level (never below the raw level,
which the blind-escalation rule may still raise).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

LEVEL_NAMES = ("Normal", "Watch", "Warning", "Emergency")
NORMAL, WATCH, WARNING, EMERGENCY = range(4)
THRESHOLD_NAMES = ("watch", "warning", "emergency")
NAMED_BLOCKS = ("alert_levels", "alert_thresholds", "thresholds_oof", "thresholds")
UNCERTAIN_HIGH = "uncertain_high"

log = logging.getLogger(__name__)


def level_name(level: int) -> str:
    return LEVEL_NAMES[int(level)]


def parse_level(value) -> int:
    """A level given as 0-3 or as a name (any letter case)."""
    if isinstance(value, (int, np.integer)):
        if 0 <= int(value) <= EMERGENCY:
            return int(value)
    else:
        text = str(value).strip()
        if text.isdigit() and int(text) <= EMERGENCY:
            return int(text)
        for level, name in enumerate(LEVEL_NAMES):
            if text.lower() == name.lower():
                return level
    raise ValueError(f"unknown alert level {value!r}; use 0-3 or one of {list(LEVEL_NAMES)}")


@dataclass(frozen=True)
class Thresholds:
    """Calibrated-risk thresholds of the three alert tiers and where they came from."""
    watch: float
    warning: float
    emergency: float
    source: str

    def __post_init__(self) -> None:
        values = self.as_array()
        if not np.isfinite(values).all() or values[0] <= 0:
            raise ValueError(f"alert thresholds must be finite and positive, got {values.tolist()}")
        if (np.diff(values) < 0).any():
            raise ValueError(f"alert thresholds must satisfy watch <= warning <= emergency, got {values.tolist()}")

    def as_array(self) -> np.ndarray:
        return np.array([self.watch, self.warning, self.emergency], dtype=np.float64)

    def to_dict(self) -> dict:
        return {"watch": self.watch, "warning": self.warning, "emergency": self.emergency, "source": self.source}


@dataclass(frozen=True)
class RegionThresholds:
    """Thresholds of each region with `pooled` for any region not named (or missing)."""
    by_region: dict
    pooled: Thresholds

    def of(self, region) -> Thresholds:
        return self.by_region.get(region, self.pooled)

    def matrix(self, region) -> np.ndarray:
        """(n, 3) thresholds, one row per entry of `region`."""
        region = np.asarray(region, dtype=object)
        out = np.tile(self.pooled.as_array(), (len(region), 1))
        for name, thresholds in self.by_region.items():
            out[region == name] = thresholds.as_array()
        return out

    def to_dict(self) -> dict:
        return {name: thresholds.to_dict() for name, thresholds in sorted(self.by_region.items())}


def _threshold_rows(thresholds: "Thresholds | RegionThresholds | np.ndarray", region, shape) -> np.ndarray:
    """(3,) for plain thresholds; (n, 3) for thresholds by region, which need one region per row (1-D rows); the array
    itself for thresholds given per row, which must hold three per score."""
    if isinstance(thresholds, np.ndarray):
        if thresholds.shape != (*shape, 3):
            raise ValueError(f"thresholds per row need three thresholds per score, shape {(*shape, 3)}, "
                             f"got {thresholds.shape}")
        return thresholds
    if not isinstance(thresholds, RegionThresholds):
        return thresholds.as_array()
    if region is None or len(shape) != 1 or np.shape(region) != tuple(shape):
        raise ValueError("thresholds by region need the region of every row (1-D scores, one region each)")
    return thresholds.matrix(region)


def _risk_value(entry, name: str) -> float:
    value = entry.get("risk") if isinstance(entry, dict) else entry
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"card threshold {name!r} has no numeric risk value: {entry!r}")
    return float(value)


def _named_thresholds(card: dict) -> tuple[str, dict] | None:
    for key in NAMED_BLOCKS:
        block = card.get(key)
        if isinstance(block, dict):
            lowered = {str(k).lower(): v for k, v in block.items()}
            if all(name in lowered for name in THRESHOLD_NAMES):
                return key, lowered
    return None


def _v1_operating_point(card: dict, spec: dict, name: str) -> float:
    points = card.get("operating_points_validation")
    if not isinstance(points, dict):
        raise ValueError("the model card names no Watch/Warning/Emergency thresholds and has no "
                         "`operating_points_validation` to fall back on")
    (kind, level), = spec.items()
    if kind not in ("recall", "fa_share"):
        raise ValueError(f"v1 fallback for {name!r} must name `recall` or `fa_share`, got {kind!r}")
    table = points.get(kind, {})
    entry = table.get(str(level))
    if entry is None or entry.get("risk") is None:
        raise ValueError(f"v1 card has no {kind}={level} operating point for {name!r}; "
                         f"available: {sorted(table)}")
    return float(entry["risk"])


def thresholds_from_card(card: dict, fallback: dict) -> Thresholds:
    """Watch / Warning / Emergency risk thresholds by name from `card`; the v1 operating points named in `fallback`
    (the `v1_card_fallback` block of configs/alerts.yaml) when the card does not name them."""
    named = _named_thresholds(card)
    if named is not None:
        key, block = named
        out = Thresholds(*(_risk_value(block[n], n) for n in THRESHOLD_NAMES), source=f"card.{key}")
    else:
        values = [_v1_operating_point(card, fallback[n], n) for n in THRESHOLD_NAMES]
        described = ", ".join(f"{n}: " + " ".join(f"{k}={v}" for k, v in fallback[n].items())
                              for n in THRESHOLD_NAMES)
        out = Thresholds(*values, source=f"v1_card_fallback ({described})")
    log.info("alert thresholds from %s: watch=%.3g warning=%.3g emergency=%.3g", out.source, out.watch, out.warning,
             out.emergency)
    return out


def card_region_thresholds(card: dict, regions) -> dict[str, Thresholds]:
    """Risk thresholds of each of `regions` as the card gives them for its calibrator (`risk_by_region` of each alert
    level), the pooled risk threshold where the card names none for that region."""
    levels = card.get("alert_levels")
    if not isinstance(levels, dict) or not all(name in levels for name in THRESHOLD_NAMES):
        raise ValueError("the card has no `alert_levels` block naming watch, warning and emergency")
    out = {}
    for region in sorted({str(r) for r in regions}):
        values = [float(levels[name].get("risk_by_region", {}).get(region, levels[name]["risk"]))
                  for name in THRESHOLD_NAMES]
        out[region] = Thresholds(*values, source=f"card.alert_levels risk_by_region[{region}]")
    return out


def level_from_risk(risk, thresholds: "Thresholds | RegionThresholds | np.ndarray", region=None) -> np.ndarray:
    """0-3: the number of thresholds the risk has reached (a NaN risk reaches none)."""
    risk = np.asarray(risk, dtype=np.float64)
    return (risk[..., None] >= _threshold_rows(thresholds, region, risk.shape)).sum(axis=-1).astype(np.int8)


def uncertain_high_mask(risk, risk_hi, thresholds: "Thresholds | RegionThresholds | np.ndarray", region=None
                        ) -> np.ndarray:
    """Point risk below Watch while the upper interval bound has reached it."""
    risk, risk_hi = np.asarray(risk, dtype=np.float64), np.asarray(risk_hi, dtype=np.float64)
    watch = _threshold_rows(thresholds, region, risk.shape)[..., 0]
    return (risk < watch) & (risk_hi >= watch)


def raw_level(risk, risk_hi, thresholds: "Thresholds | RegionThresholds | np.ndarray", region=None
              ) -> tuple[np.ndarray, np.ndarray]:
    """(level, uncertain_high mask): the level from the point risk, raised to Watch where `uncertain_high` holds."""
    uncertain = uncertain_high_mask(risk, risk_hi, thresholds, region)
    return np.where(uncertain, WATCH, level_from_risk(risk, thresholds, region)).astype(np.int8), uncertain


def apply_hysteresis(cell_id, date, raw, risk, thresholds: "Thresholds | RegionThresholds | np.ndarray",
                     exit_factor: float, exit_days: int, region=None, release=None, cap=None,
                     blind_hold_days: int | None = None) -> np.ndarray:
    """Level per row after hysteresis (see the module doc); output is aligned with the input rows. With thresholds by
    region the cell's step-down thresholds are those of its region (`region` per row, constant within a cell); with
    thresholds per row (an (n, 3) array) the step-down thresholds are those of the row being decided.
    `release` (bool per row, or per row and held level 0-3) and `cap` (the level each level 0-3 is capped at) give the
    hold release; both or neither.
    `blind_hold_days` limits a hold over rows without a score (None: no limit)."""
    cell_id, raw = np.asarray(cell_id), np.asarray(raw, dtype=np.int8)
    day = pd.DatetimeIndex(date).to_numpy("datetime64[D]").astype(np.int64)
    risk = np.asarray(risk, dtype=np.float64)
    n = len(raw)
    if not (len(cell_id) == len(day) == len(risk) == n):
        raise ValueError("cell_id, date, raw level and risk must have the same length")
    if exit_days < 1 or not 0 < exit_factor <= 1:
        raise ValueError("exit_days must be >= 1 and exit_factor in (0, 1]")
    if (release is None) != (cap is None):
        raise ValueError("`release` and `cap` go together")
    if release is not None:
        release = np.asarray(release, dtype=bool)
        cap = np.asarray(cap, dtype=np.int8)
        if release.shape == (n,):
            release = np.repeat(release[:, None], 4, axis=1)
        if release.shape != (n, 4):
            raise ValueError("release must have one flag per row, or one per row and held level (rows, 4)")
        if cap.shape != (4,) or (cap < NORMAL).any() or (cap > np.arange(4)).any():
            raise ValueError(f"cap must map each level 0-3 to a level not above it, got {cap.tolist()}")
    if blind_hold_days is not None and int(blind_hold_days) < 0:
        raise ValueError("blind_hold_days must be None or >= 0")
    order = np.lexsort((day, cell_id))
    cell_s, day_s = cell_id[order], day[order]
    if n and ((cell_s[1:] == cell_s[:-1]) & (day_s[1:] == day_s[:-1])).any():
        raise ValueError("duplicate (cell_id, date) rows; the alert sequence of a cell must have one row per day")
    new_run = np.ones(n, dtype=bool)
    if n:
        new_run[1:] = (cell_s[1:] != cell_s[:-1]) | ((day_s[1:] - day_s[:-1]) != 1)
    starts = np.flatnonzero(new_run)
    lengths = np.diff(np.append(starts, n))
    raw_s, risk_s = raw[order], risk[order]
    release_s = release[order] if release is not None else None
    rows = _threshold_rows(thresholds, region, (n,))
    cell_thresholds = rows[order[starts]] if rows.ndim == 2 else np.broadcast_to(rows, (len(starts), 3))
    exit_threshold = np.column_stack([np.full(len(starts), np.inf), cell_thresholds * exit_factor])   # (run, level)
    per_row = isinstance(thresholds, np.ndarray)
    exit_row = np.column_stack([np.full(n, np.inf), rows[order] * exit_factor]) if per_row else None   # (row, level)
    state = raw_s[starts].astype(np.int8)
    streak = np.zeros(len(starts), dtype=np.int32)
    out_s = np.empty(n, dtype=np.int8)
    out_s[starts] = state
    blind_s = ~np.isfinite(risk_s)
    blind_run = blind_s[starts].astype(np.int32)       # consecutive rows without a score, per run
    for k in range(1, int(lengths.max()) if n else 0):
        active = np.flatnonzero(lengths > k)
        idx = starts[active] + k
        r, x, s = raw_s[idx], risk_s[idx], state[active]
        up = r >= s
        limit = exit_row[idx, s] if per_row else exit_threshold[active, s]
        qualifies = ~up & (x < limit)
        streak_a = np.where(qualifies, streak[active] + 1, 0)
        down = streak_a >= exit_days
        new = np.where(up, r, np.where(down, s - 1, s)).astype(np.int8)
        reset = down
        if release_s is not None:
            released = release_s[idx, new] & (new > r) & (cap[new] < new)
            new = np.where(released, np.maximum(r, cap[new]), new).astype(np.int8)
            reset = reset | released
        if blind_hold_days is not None:
            blind_run[active] = np.where(blind_s[idx], blind_run[active] + 1, 0)
            decay = blind_s[idx] & (blind_run[active] > blind_hold_days) & (new > r)
            new = np.where(decay, np.maximum(r, new - 1), new).astype(np.int8)
            reset = reset | decay
        state[active] = new
        streak[active] = np.where(reset, 0, streak_a)
        out_s[idx] = state[active]
    out = np.empty(n, dtype=np.int8)
    out[order] = out_s
    return out
