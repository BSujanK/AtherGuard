"""Post-model rules of the live alert levels (spec section 11): the rain trigger and the ensemble-disagreement confidence.

    rules = load_rules(path)                                           # data/processed/alerts/post_rules_v3.json
    table = apply_post_rules(features, scores, engine_table, rules, thresholds, scored)   # before the hysteresis
    level = live_hysteresis(table, history, rain_history, thresholds, alert_config, rules)  # instead of run.live_hysteresis
    leads = apply_lead_rules(frame, scores, level, confidence, causes, rules, thresholds)  # forecast leads, no hysteresis

Rain trigger (physical consistency). A rain-triggered landslide alert needs recent rain: the rule passes when ANY of its
IMERG windows reaches its minimum (`irain_acc_<w>` >= minimum_mm[w]; the windows and minima are low quantiles of the
development positives, `hardening_dev`). A cell-day that fails it has its level capped at each level the rule is adopted
at (`gated_levels`): the level is replaced by `cap[level]` (Watch -> Normal, Warning or Emergency -> Watch) with reason
code `no_recent_rain`. A cell whose rain windows are all unknown is not capped (it has no score), and neither is a
blind-escalated cell (`blind`: heavy rain in an independent source, the engine's no-silent-Normal rule). Hysteresis may
hold a capped level only while the rule passed on at least one day of the hold window of that level (the
`hold_window_days` days ending on the day, or the level's own entry of `hold_windows`); otherwise the hold is released
to the capped level (`levels.apply_hysteresis`, `release`).

Blind-hold limit (safety rule). A cell whose model inputs are missing has no score and never qualifies for a step
down, so an outage would hold its level indefinitely. A level is held over at most `blind_hold_days` (H) consecutive
days without a score, then drops one level per further such day (`levels.apply_hysteresis`); such a held cell stays
Insufficient and carries `held_while_blind` (`mark_blind_holds`). The blind-escalation rule still raises it to Watch
when any source shows heavy rain.

Forecast leads. The rain cap uses the lead's own rain windows (observed days plus the GFS forecast), there is no
hysteresis and no blind rule, and `uncertain_high` tests the bound `lead_uncertain_bound` names: `widened` (`risk_hi`
times the forecast-skill widening factor), `unwidened` (the re-centred ensemble `risk_hi`) or `none` (`hardening_leads`
chose it on the forecast-skill pairs). A forecast day has no observation, so its confidence is never High: a scored lead
is Degraded with cause `forecast_day`, the D0 state as `observed_through_d_<state>` and `forecast_widened` (or
`forecast_uncertainty_uncalibrated` without widening factors); an unscored lead is Insufficient.

Scenario certainty (spec section 12, F1). A forecast lead is scored three times with the same model and the same rules: with no
rain after day D (`dry`), with the chosen forecast (`forecast`, the published level) and with its heavy-rain bound (`wet`). The
row is `firm` when the three published levels are the same (the level is set by rain already on the ground) and
`depends_on_forecast` otherwise; `level_min` / `level_max` are the lowest and highest of the three. A row without a score has no
certainty and `level_min == level_max == level`.

Ensemble disagreement. When the point reaches Warning or above but fewer than `agreement_min` of the ensemble members
reach the point's level (`ensemble_agreement` of `HazardModel.score`), confidence is capped at Degraded with cause
`ensemble_disagrees` ("most of the 20 ensemble models put this cell lower"). The level does not change.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from ..alerts import levels as lv
from ..hazard.jsonio import dump_json

VERSION = 1
CODE_NO_RECENT_RAIN = "no_recent_rain"
CAUSE_ENSEMBLE = "ensemble_disagrees"
CODE_HELD_WHILE_BLIND = "held_while_blind"
CAUSE_FORECAST_DAY = "forecast_day"
CAUSE_FORECAST_WIDENED = "forecast_widened"
CAUSE_FORECAST_MISSING = "forecast_input_missing"
CAUSE_UNCALIBRATED = "forecast_uncertainty_uncalibrated"
CERTAINTY_FIRM, CERTAINTY_DEPENDS = "firm", "depends_on_forecast"
CERTAINTY_CODES = {None: 0, CERTAINTY_FIRM: 1, CERTAINTY_DEPENDS: 2}
LEAD_BOUNDS = ("widened", "unwidened", "none")
DEGRADED, HIGH, INSUFFICIENT = "Degraded", "High", "Insufficient"
DEFAULT_CAP = (lv.NORMAL, lv.NORMAL, lv.WATCH, lv.WATCH)     # the level each level is capped at when the rain rule fails
TEXTS = {CAUSE_ENSEMBLE: "most of the {n_members} ensemble models put this cell lower",
         CODE_NO_RECENT_RAIN: "no recent rain: the IMERG rain of the last days is below the rain-trigger minimum, so the "
                              "level is capped",
         CODE_HELD_WHILE_BLIND: "held while the model inputs are missing: the level of the last scored day is kept for "
                                "at most {blind_hold_days} day(s), then lowered one level per further missing day"}
ENSEMBLE_COLUMNS = ("member_median_risk", "ensemble_agreement")


def rain_column(window: int) -> str:
    return f"irain_acc_{window}"


def reason_text(code: str, n_members: int = 20, blind_hold_days: int | None = 1) -> str | None:
    """The plain-language text of a post-rule code or cause (None for any other code)."""
    text = TEXTS.get(code)
    return None if text is None else text.format(n_members=n_members, blind_hold_days=blind_hold_days)


# --------------------------------------------------------------------------------------------------- rules

@dataclass(frozen=True)
class RainRule:
    """Passes when any window's IMERG rain reaches its minimum (mm); a window whose value is unknown does not count, and
    a row with every window unknown passes (nothing to test)."""
    minimum_mm: dict[int, float]

    def __post_init__(self) -> None:
        if not self.minimum_mm:
            raise ValueError("a rain rule needs at least one window")
        for window, minimum in self.minimum_mm.items():
            if int(window) < 1 or not np.isfinite(minimum) or minimum <= 0:
                raise ValueError(f"rain rule window {window}: the minimum must be finite and positive (a 0 mm minimum "
                                 f"admits every cell-day), got {minimum}")

    @property
    def columns(self) -> list[str]:
        return [rain_column(w) for w in sorted(self.minimum_mm)]

    def passes_arrays(self, rain: dict[int, np.ndarray]) -> np.ndarray:
        """The rule on arrays of any one shape: `rain` maps each of the rule's windows to its rain (mm)."""
        windows = sorted(self.minimum_mm)
        shape = np.shape(rain[windows[0]])
        hit, known = np.zeros(shape, dtype=bool), np.zeros(shape, dtype=bool)
        for w in windows:
            values = np.asarray(rain[w], dtype=np.float64)
            finite = np.isfinite(values)
            known |= finite
            with np.errstate(invalid="ignore"):
                hit |= finite & (values >= self.minimum_mm[w])
        return hit | ~known

    def passes(self, frame: pd.DataFrame) -> np.ndarray:
        missing = [c for c in self.columns if c not in frame.columns]
        if missing:
            raise ValueError(f"the rain rule needs columns {missing}")
        return self.passes_arrays({w: frame[rain_column(w)].to_numpy(dtype=np.float64) for w in self.minimum_mm})

    def describe(self) -> str:
        return " OR ".join(f"{rain_column(w)} >= {m:.3g} mm" for w, m in sorted(self.minimum_mm.items()))


@dataclass(frozen=True)
class PostRules:
    """The post-model rules. `agreement_min` None: no ensemble-disagreement rule; `rain` None or no `gated_levels`: no
    rain trigger. `cap` is indexed by level (0-3); only the gated levels use it."""
    agreement_min: float | None
    rain: RainRule | None
    gated_levels: tuple[int, ...] = ()
    cap: tuple[int, ...] = DEFAULT_CAP
    hold_window_days: int = 3
    hold_windows: dict = field(default_factory=dict)      # level (1-3) -> its own hold window, overriding the default
    blind_hold_days: int | None = None
    lead_uncertain_bound: str = "widened"
    source: str = ""
    derivation: dict = field(default_factory=dict, compare=False)

    def __post_init__(self) -> None:
        if self.agreement_min is not None and not 0.0 < self.agreement_min <= 1.0:
            raise ValueError(f"agreement_min must be None or in (0, 1], got {self.agreement_min}")
        if any(level not in (lv.WATCH, lv.WARNING, lv.EMERGENCY) for level in self.gated_levels):
            raise ValueError(f"gated levels must be Watch, Warning or Emergency (1-3), got {self.gated_levels}")
        if self.gated_levels and self.rain is None:
            raise ValueError("gated levels need a rain rule")
        if len(self.cap) != 4 or any(not 0 <= c <= level for level, c in enumerate(self.cap)):
            raise ValueError(f"cap must map each level 0-3 to a level not above it, got {self.cap}")
        if any(self.cap[level] == level for level in self.gated_levels):
            raise ValueError("a gated level must be capped below itself")
        if self.hold_window_days < 1 or any(int(w) < 1 for w in self.hold_windows.values()):
            raise ValueError("hold windows must be at least 1 day")
        if any(level not in (lv.WATCH, lv.WARNING, lv.EMERGENCY) for level in self.hold_windows):
            raise ValueError(f"hold windows are given for Watch, Warning or Emergency (1-3), got {self.hold_windows}")
        if self.blind_hold_days is not None and self.blind_hold_days < 0:
            raise ValueError("blind_hold_days must be None or at least 0")
        if self.lead_uncertain_bound not in LEAD_BOUNDS:
            raise ValueError(f"lead_uncertain_bound must be one of {LEAD_BOUNDS}, got {self.lead_uncertain_bound!r}")

    @property
    def gates(self) -> bool:
        return bool(self.gated_levels)

    def window_of(self, level: int) -> int:
        """The hold window (days) of a held `level`."""
        return int(self.hold_windows.get(level, self.hold_window_days))

    def cap_array(self) -> np.ndarray:
        """The level each level 0-3 becomes when the rain rule fails (identity at the levels that are not gated)."""
        out = np.arange(4, dtype=np.int8)
        for level in self.gated_levels:
            out[level] = self.cap[level]
        return out

    def to_dict(self) -> dict:
        return {"agreement_min": self.agreement_min,
                "rain_minimum_mm": None if self.rain is None else {str(w): m for w, m in sorted(self.rain.minimum_mm.items())},
                "gated_levels": [lv.level_name(level) for level in self.gated_levels],
                "cap": {lv.level_name(level): lv.level_name(c) for level, c in enumerate(self.cap)},
                "hold_window_days": self.hold_window_days,
                "hold_window_days_by_level": {lv.level_name(level): int(w) for level, w in sorted(self.hold_windows.items())},
                "blind_hold_days": self.blind_hold_days,
                "lead_uncertain_bound": self.lead_uncertain_bound}

    @classmethod
    def from_dict(cls, values: dict, source: str = "", derivation: dict | None = None) -> "PostRules":
        minimum = values.get("rain_minimum_mm")
        rain = None if not minimum else RainRule({int(w): float(m) for w, m in minimum.items()})
        cap = values.get("cap")
        return cls(agreement_min=None if values.get("agreement_min") is None else float(values["agreement_min"]),
                   rain=rain, gated_levels=tuple(sorted(lv.parse_level(v) for v in values.get("gated_levels", []))),
                   cap=DEFAULT_CAP if cap is None else tuple(lv.parse_level(cap[name]) for name in lv.LEVEL_NAMES),
                   hold_window_days=int(values.get("hold_window_days", 3)),
                   hold_windows={lv.parse_level(k): int(w) for k, w in (values.get("hold_window_days_by_level") or {}).items()},
                   blind_hold_days=None if values.get("blind_hold_days") is None else int(values["blind_hold_days"]),
                   lead_uncertain_bound=str(values.get("lead_uncertain_bound", "widened")),
                   source=source, derivation=derivation or {})


NO_RULES = PostRules(agreement_min=None, rain=None, source="none")


def save_rules(path: Path, rules: PostRules, derivation: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    dump_json(path, {"version": VERSION, "parameters": rules.to_dict(), "derivation": derivation})


def load_rules(path: Path | str) -> PostRules:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"{path} not found; derive it first (python -m aetherguard.live.hardening analyze-dev)")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("version") != VERSION:
        raise ValueError(f"{path} has version {payload.get('version')!r}, expected {VERSION}")
    return PostRules.from_dict(payload["parameters"], source=str(path), derivation=payload.get("derivation"))


# ------------------------------------------------------------------------------------------- rule pieces

def rain_ok(frame: pd.DataFrame, rules: PostRules) -> np.ndarray:
    """Per row: the rain rule passes (every row passes when there is no rain rule)."""
    return np.ones(len(frame), dtype=bool) if rules.rain is None else rules.rain.passes(frame)


def capped_levels(level, ok, exempt, rules: PostRules) -> tuple[np.ndarray, np.ndarray]:
    """(level after the rain cap, mask of the rows it lowered): rows failing the rule and not `exempt` get `cap[level]`
    at the gated levels."""
    level = np.asarray(level, dtype=np.int8)
    fail = ~np.asarray(ok, dtype=bool) & ~np.asarray(exempt, dtype=bool)
    out = np.where(fail, rules.cap_array()[level], level).astype(np.int8)
    return out, out < level


def disagrees(point_level, agreement, rules: PostRules) -> np.ndarray:
    """The point reaches Warning or above while fewer than `agreement_min` of the members reach its level (an unknown
    agreement never triggers)."""
    point_level = np.asarray(point_level)
    agreement = np.asarray(agreement, dtype=np.float64)
    if rules.agreement_min is None:
        return np.zeros(point_level.shape, dtype=bool)
    with np.errstate(invalid="ignore"):
        return (point_level >= lv.WARNING) & np.isfinite(agreement) & (agreement < rules.agreement_min)


def point_levels(risk, thresholds, region) -> np.ndarray:
    """The level the point risk reaches (Normal for an unknown risk)."""
    risk = np.asarray(risk, dtype=np.float64)
    region = np.asarray(region, dtype=object) if isinstance(thresholds, lv.RegionThresholds) else None
    return lv.level_from_risk(risk, thresholds, region)


def release_matrix(cell_id, day, rain: pd.DataFrame, rules: "PostRules") -> np.ndarray:
    """(rows, 4): the hold release of each row for a held level 0-3 (column 0 is never used), each level with its own
    hold window."""
    windows = {level: rules.window_of(level) for level in (lv.WATCH, lv.WARNING, lv.EMERGENCY)}
    by_window = {w: hold_release(cell_id, day, rain, w) for w in set(windows.values())}
    out = np.zeros((len(np.asarray(cell_id)), 4), dtype=bool)
    for level, w in windows.items():
        out[:, level] = by_window[w]
    return out


def hold_release(cell_id, day, rain: pd.DataFrame, window_days: int) -> np.ndarray:
    """Per row (cell, day): True when the rain rule passed on none of the cell's days day-window+1..day in `rain`
    (cell_id, date, rain_ok); a day `rain` does not hold counts as not passed."""
    keys = pd.MultiIndex.from_arrays([np.asarray(rain["cell_id"], dtype=np.int64),
                                      pd.DatetimeIndex(rain["date"]).normalize()])
    passed = pd.Series(np.asarray(rain["rain_ok"], dtype=bool), index=keys)
    passed = passed[~passed.index.duplicated(keep="last")]
    cells = np.asarray(cell_id, dtype=np.int64)
    days = pd.DatetimeIndex(day).normalize()
    any_pass = np.zeros(len(cells), dtype=bool)
    for back in range(window_days):
        probe = pd.MultiIndex.from_arrays([cells, days - pd.Timedelta(days=back)])
        any_pass |= passed.reindex(probe).fillna(False).to_numpy(dtype=bool)
    return ~any_pass


# ----------------------------------------------------------------------------------------- reason records

def _split(text: str) -> list[str]:
    return text.split(";") if text else []


def _join(parts) -> str:
    return ";".join(dict.fromkeys(p for p in parts if p))


def _clean(value) -> float | None:
    return None if value is None or not np.isfinite(value) else float(value)


def annotate(detail: dict, median, agreement, ok: bool, exempt: bool, capped: bool) -> dict:
    """The `ensemble` and `rain_rule` entries of a row's `reasons_json`."""
    detail["ensemble"] = {"median_risk": _clean(median), "agreement": _clean(agreement)}
    detail["rain_rule"] = {"passed": bool(ok), "exempt": bool(exempt), "capped": bool(capped)}
    return detail


# --------------------------------------------------------------------------------------------------- lead 0

def apply_post_rules(features: pd.DataFrame, scores: pd.DataFrame, alerts: pd.DataFrame, rules: PostRules,
                     thresholds: lv.Thresholds | lv.RegionThresholds, scored=None) -> pd.DataFrame:
    """The engine table of one day (`run_alerts(..., hysteresis=False)`, possibly after `cap_to_degraded`) with the
    post-model rules applied, before the hysteresis.

    `features` (the alert input, with the `irain_acc_*` windows of the rule) and `scores` (the model's scores, with
    `member_median_risk` / `ensemble_agreement` when the model gives them) share the table's index; `scored` marks the
    rows that have a real score (default: all). Adds the columns `member_median_risk`, `ensemble_agreement` (NaN where
    not scored) and `rain_ok`; caps the raw level (and the level, which equals it before the hysteresis) of the rows
    failing the rain rule at the gated levels with code `no_recent_rain`; lowers `High` to `Degraded` with cause
    `ensemble_disagrees` where the ensemble disagrees; keeps `reasons_json` consistent and adds its `ensemble` and
    `rain_rule` entries.
    """
    if not (features.index.equals(alerts.index) and scores.index.equals(alerts.index)):
        raise ValueError("features, scores and the alert table must have the same rows (index)")
    if not np.array_equal(alerts["level"].to_numpy(), alerts["raw_level"].to_numpy()):
        raise ValueError("apply_post_rules takes the engine table before the hysteresis (level == raw_level)")
    n = len(alerts)
    scored = np.ones(n, dtype=bool) if scored is None else np.asarray(scored, dtype=bool)
    out = alerts.copy()
    for column in ENSEMBLE_COLUMNS:
        values = scores[column].to_numpy(dtype=np.float64) if column in scores.columns else np.full(n, np.nan)
        out[column] = np.where(scored, values, np.nan)
    ok = rain_ok(features, rules)
    out["rain_ok"] = ok
    exempt = out["blind"].to_numpy(dtype=bool)
    raw = out["raw_level"].to_numpy()
    new_raw, capped = capped_levels(raw, ok, exempt, rules)
    out["raw_level"] = new_raw
    out["level"] = new_raw
    out["level_name"] = np.array(lv.LEVEL_NAMES, dtype=object)[new_raw]
    risk = np.where(scored, out["risk"].to_numpy(dtype=np.float64), np.nan)
    region = out["region"].to_numpy() if "region" in out.columns else np.full(n, None, dtype=object)
    disagree = disagrees(point_levels(risk, thresholds, region), out["ensemble_agreement"].to_numpy(), rules) & scored
    confidence = out["confidence"].to_numpy(dtype=object).copy()
    confidence[disagree & (confidence == HIGH)] = DEGRADED
    out["confidence"] = confidence
    codes, causes, reasons = out["reason_codes"].tolist(), out["confidence_causes"].tolist(), out["reasons_json"].tolist()
    median, agreement = out["member_median_risk"].to_numpy(), out["ensemble_agreement"].to_numpy()
    for i in range(n):
        if capped[i]:
            codes[i] = _join([*_split(codes[i]), CODE_NO_RECENT_RAIN])
        if disagree[i]:
            causes[i] = _join([*_split(causes[i]), CAUSE_ENSEMBLE])
        detail = json.loads(reasons[i])
        detail["level"], detail["raw_level"] = lv.level_name(new_raw[i]), lv.level_name(new_raw[i])
        detail["codes"] = _split(codes[i])
        detail["confidence"] = {"state": confidence[i], "causes": _split(causes[i])}
        reasons[i] = json.dumps(annotate(detail, median[i], agreement[i], ok[i], exempt[i], capped[i]), allow_nan=False)
    out["reason_codes"], out["confidence_causes"], out["reasons_json"] = codes, causes, reasons
    return out


def previous_rain_ok(live_dir: Path, day: date, days: int, rules: PostRules) -> pd.DataFrame:
    """(cell_id, date, rain_ok) of the rain rule on the stored features (`features_D0.parquet`) of the consecutive days
    before `day` (the same days `run.previous_state` reads)."""
    frames = []
    columns = ["cell_id", "date"] + ([] if rules.rain is None else rules.rain.columns)
    days = max(days, 0)
    for k in range(1, days + 1):
        path = Path(live_dir) / (day - timedelta(days=k)).isoformat() / "features_D0.parquet"
        if not path.is_file():
            break
        frame = pd.read_parquet(path, columns=columns)
        frames.append(frame[["cell_id", "date"]].assign(rain_ok=rain_ok(frame, rules)))
    if not frames:
        return pd.DataFrame({"cell_id": pd.Series(dtype="int64"), "date": pd.Series(dtype="datetime64[ns]"),
                             "rain_ok": pd.Series(dtype=bool)})
    return pd.concat(frames, ignore_index=True)


def live_hysteresis(today: pd.DataFrame, history: pd.DataFrame, rain_history: pd.DataFrame,
                    thresholds: lv.Thresholds | lv.RegionThresholds, config, rules: PostRules) -> np.ndarray:
    """`run.live_hysteresis` with the hold release of the rain trigger: levels of `today` (a table after
    `apply_post_rules`, NaN risk where a cell has no score) after the hysteresis run over the previous days' live state
    (`history`: cell_id, date, raw_level, risk), where a hold is released on a day whose hold window has no rain
    (`rain_history`, `previous_rain_ok`, plus today's `rain_ok`), and a hold over days without a score is limited to
    `rules.blind_hold_days`."""
    both = pd.concat([history, today[["cell_id", "date", "raw_level", "risk"]]], ignore_index=True)
    region = (both["cell_id"].map(dict(zip(today["cell_id"], today["region"]))).to_numpy(dtype=object)
              if isinstance(thresholds, lv.RegionThresholds) else None)
    release = cap = None
    if rules.gates:
        rain = pd.concat([rain_history, today[["cell_id", "date", "rain_ok"]]], ignore_index=True)
        release = release_matrix(both["cell_id"].to_numpy(), both["date"], rain, rules)
        cap = rules.cap_array()
    levels = lv.apply_hysteresis(both["cell_id"].to_numpy(), both["date"], both["raw_level"].to_numpy(),
                                 both["risk"].to_numpy(), thresholds, config.exit_factor, config.exit_days, region,
                                 release, cap, rules.blind_hold_days)
    return levels[len(history):]


def mark_blind_holds(alerts: pd.DataFrame, unscorable) -> pd.DataFrame:
    """After `run.finalize_alerts`: the cells without a score whose published level is above their raw level get reason
    code `held_while_blind` (their confidence is Insufficient already)."""
    out = alerts.copy()
    held = np.asarray(unscorable, dtype=bool) & (out["level"].to_numpy() > out["raw_level"].to_numpy())
    codes, reasons = out["reason_codes"].tolist(), out["reasons_json"].tolist()
    for i in np.flatnonzero(held):
        codes[i] = _join([*_split(codes[i]), CODE_HELD_WHILE_BLIND])
        detail = json.loads(reasons[i])
        detail["codes"] = _split(codes[i])
        reasons[i] = json.dumps(detail, allow_nan=False)
    out["reason_codes"], out["reasons_json"] = codes, reasons
    return out


# ------------------------------------------------------------------------------------------ forecast leads

def lead_bound(rules: PostRules, risk, risk_hi, widened_hi) -> np.ndarray:
    """The score `uncertain_high` tests on a forecast lead: the widened `risk_hi`, the re-centred one, or the point."""
    choice = {"widened": widened_hi, "unwidened": risk_hi, "none": risk}[rules.lead_uncertain_bound]
    return np.asarray(choice, dtype=np.float64)


def lead_confidence(base_state, scored, widened: bool) -> tuple[np.ndarray, list[str]]:
    """Confidence of a forecast lead from its own inputs (module doc): never High. `base_state` is the D0 confidence of
    each cell, `widened` whether the forecast-skill widening factors were applied."""
    scored = np.asarray(scored, dtype=bool)
    states, causes = [], []
    for state, ok in zip(base_state, scored):
        if not ok:
            states.append(INSUFFICIENT)
            causes.append(CAUSE_FORECAST_MISSING)
            continue
        states.append(DEGRADED)
        causes.append(_join([CAUSE_FORECAST_DAY, f"observed_through_d_{str(state).lower()}",
                             CAUSE_FORECAST_WIDENED if widened else CAUSE_UNCALIBRATED]))
    return np.array(states, dtype=object), causes


def scenario_certainty(level, dry, wet, scored) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(certainty, level_min, level_max) of forecast-lead rows from the published level and the levels under the `dry` and `wet`
    rain scenarios (module doc). `certainty` is `firm`, `depends_on_forecast` or None for a row that is not scored."""
    level = np.asarray(level, dtype=np.int8)
    scored = np.asarray(scored, dtype=bool)
    stack = np.stack([level, np.asarray(dry, dtype=np.int8), np.asarray(wet, dtype=np.int8)])
    low = np.where(scored, stack.min(axis=0), level).astype(np.int8)
    high = np.where(scored, stack.max(axis=0), level).astype(np.int8)
    certainty = np.where(~scored, None, np.where(low == high, CERTAINTY_FIRM, CERTAINTY_DEPENDS)).astype(object)
    return certainty, low, high


def apply_lead_rules(frame: pd.DataFrame, scores: pd.DataFrame, level, confidence, causes, rules: PostRules,
                     thresholds: lv.Thresholds | lv.RegionThresholds, scored) -> tuple[np.ndarray, np.ndarray, list, list]:
    """The post-model rules on one forecast lead (no hysteresis, no blind rule): the rain cap on the lead's own rain
    windows (observed days plus the GFS forecast, `frame`) and the ensemble-disagreement cause on its scores. Returns
    (level, confidence, causes, extra reason codes per row)."""
    scored = np.asarray(scored, dtype=bool)
    n = len(frame)
    ok = rain_ok(frame, rules) | ~scored
    new_level, capped = capped_levels(level, ok, np.zeros(n, dtype=bool), rules)
    agreement = (scores["ensemble_agreement"].to_numpy(dtype=np.float64) if "ensemble_agreement" in scores.columns
                 else np.full(n, np.nan))
    risk = np.where(scored, scores["risk"].to_numpy(dtype=np.float64), np.nan)
    disagree = disagrees(point_levels(risk, thresholds, frame["region"].to_numpy()), agreement, rules) & scored
    confidence = np.asarray(confidence, dtype=object).copy()
    confidence[disagree & (confidence == HIGH)] = DEGRADED
    causes = [_join([*_split(c), CAUSE_ENSEMBLE]) if d else c for c, d in zip(causes, disagree)]
    codes = [CODE_NO_RECENT_RAIN if c else "" for c in capped]
    return new_level, confidence, causes, codes
