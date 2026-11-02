"""Consistency audit of the published rows of live runs (spec section 11).

    python -m aetherguard.live.audit --date YYYY-MM-DD|all [--config configs/live_run.yaml] [--rules PATH] [--out DIR]

Every row of `alerts.parquet` (lead 0) and of `risk_D1..3.parquet` (the forecast leads) of a day is checked for:

  interval    risk_lo <= risk <= risk_hi (a row with a risk has both bounds);
  level       the level is the level of the point risk against the run's thresholds of the cell's region, unless a
              documented code explains the difference: `uncertain_high` and the blind escalation (`*_heavy_rain`) raise a
              raw level below Watch to Watch, `no_recent_rain` caps it, `hysteresis_hold` keeps a published level above
              the raw level (lead 0 only; a forecast lead has no hysteresis); every such change carries its code, the tier
              code names the point's level and no code is present without its change;
  rain_rule   with post-model rules that gate a level: a cell-day failing the rain rule (and not blind-escalated) is not
              at a gated level on its own raw level, and a hold at a gated level needs rain within the hold window;
  blind_hold  with a blind-hold limit H: a cell without a score is held above its raw level for at most H consecutive
              days without a score, then at most one level lower per further such day, and carries `held_while_blind`;
  confidence  Degraded and Insufficient carry at least one cause, High none;
  forecast_confidence  a forecast-lead row is never High (High states that the rain sources of the day agree, and a
              future day has no observation);
  certainty   a forecast-lead row with a score is `firm` or `depends_on_forecast` and has none without one; `level_min <=
              level <= level_max`; `firm` means `level_min == level == level_max`, `depends_on_forecast` means
              `level_min < level_max` (section 12: the level under no further rain, the forecast and the heavy-rain bound);
  per_100k    risk_per_100k == 1e5 x risk;
  lead0_table risk_D0.parquet repeats the levels, risks and confidence of alerts.parquet.

Integrity checks (spec section 13; every table of the run, features included):
  probability, dates, rain_math, rain_chain, shap   `live.audit_math`
  grid, land, georef, places                        `live.audit_geo`
  reproducible (and the full-vector part of shap)   `live.audit_rescore`, only with `--rescore`: it scores every stored
                                                    feature table again with the frozen model
  `--api URL` runs `live.audit_parity` instead: what the dashboard API serves against the published tables.
Modelling-plausibility findings (alerts on low-slope or low-elevation cells, cells in other countries, distant places)
are NOTES: `note_counts` per table, never violations.

The forecast leads pass the same checks (the rain rule on their own `features_D<k>.parquet` when it was written). Writes
`<out>/<date>.json` per day (and `<out>/summary.json` for `all`, with the pooled rain-registration test of `audit_geo.rain_georef`);
exits 0 when clean, 2 on any violation, 1 on an error.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from ..alerts import levels as lv
from ..alerts.engine import TIER_CODES
from ..config import PROJECT_ROOT
from ..hazard.jsonio import dump_json
from . import audit_geo, audit_math, audit_rescore
from . import postrules as pr
from .sources import project_path

CHECKS = ("interval", "level", "rain_rule", "blind_hold", "confidence", "forecast_confidence", "certainty", "per_100k",
          "lead0_table", "probability", "dates", "rain_math", "rain_chain", "reproducible", "shap", "grid", "land",
          "georef", "places")
CONFIDENCE = ("High", "Degraded", "Insufficient")
HOLD = "hysteresis_hold"
BLIND_SUFFIX = "_heavy_rain"
EXAMPLES = 5
EXIT_VIOLATIONS = 2
DEFAULT_OUT = PROJECT_ROOT / "reports" / "live" / "audit"
LEAD0_COLUMNS = ["risk", "risk_lo", "risk_hi", "risk_per_100k", "level", "confidence", "confidence_causes"]


def _codes(text) -> list[str]:
    return text.split(";") if isinstance(text, str) and text else []


def run_thresholds(summary: dict) -> lv.Thresholds | lv.RegionThresholds:
    """The thresholds a run compared its risk with, as its run.json records them."""
    model = summary["model"]

    def make(entry: dict, source: str) -> lv.Thresholds:
        return lv.Thresholds(float(entry["watch"]), float(entry["warning"]), float(entry["emergency"]), source)
    pooled = make(model["thresholds"], "run.json model.thresholds")
    by_region = model.get("thresholds_by_region")
    if not by_region:
        return pooled
    return lv.RegionThresholds({r: make(t, f"run.json thresholds_by_region[{r}]") for r, t in by_region.items()}, pooled)


def lead_codes(table: pd.DataFrame) -> list[list[str]]:
    """The reason codes of each row of a lead table: `reason_codes`, else the codes of `reasons_json`, else none."""
    if "reason_codes" in table.columns:
        return [_codes(t) for t in table["reason_codes"]]
    if "reasons_json" in table.columns:
        return [json.loads(t).get("codes", []) for t in table["reasons_json"]]
    return [[] for _ in range(len(table))]


class Findings:
    """Violation counts and the first examples per check of one table, plus the NOTE counts (modelling-plausibility
    findings that are reported, never counted as violations)."""

    def __init__(self, rows: int) -> None:
        self.rows = rows
        self.counts = {name: 0 for name in CHECKS}
        self.checked = {name: False for name in CHECKS}
        self.notes: list[str] = []
        self.note_counts: dict[str, int] = {}
        self.examples: dict[str, list[dict]] = {name: [] for name in CHECKS}

    def add(self, check: str, mask: np.ndarray, table: pd.DataFrame, why: str | list[str]) -> None:
        self.checked[check] = True
        mask = np.asarray(mask, dtype=bool)
        self.counts[check] += int(mask.sum())
        whys = [why] * len(table) if isinstance(why, str) else why
        for i in np.flatnonzero(mask)[:EXAMPLES - len(self.examples[check])]:
            row = table.iloc[i]
            example = {"cell_id": int(row["cell_id"])}
            if "level" in row.index:
                example["level"] = int(row["level"])
            if "risk" in row.index:
                example["risk"] = None if not np.isfinite(row["risk"]) else float(row["risk"])
            self.examples[check].append({**example, "why": whys[i]})

    def add_count(self, check: str, count: int, why: str) -> None:
        """`count` violations of a statement about the table as a whole (no row to point at)."""
        self.checked[check] = True
        self.counts[check] += int(count)
        if count and len(self.examples[check]) < EXAMPLES:
            self.examples[check].append({"why": why})

    def note_count(self, name: str, count: int) -> None:
        self.note_counts[name] = self.note_counts.get(name, 0) + int(count)

    def to_dict(self) -> dict:
        return {"rows": self.rows, "violations": self.counts, "checked": self.checked, "notes": self.notes,
                "note_counts": {k: v for k, v in sorted(self.note_counts.items()) if v},
                "examples": {k: v for k, v in self.examples.items() if v}}


# --------------------------------------------------------------------------------------------- the checks

def check_interval(table: pd.DataFrame, found: Findings) -> None:
    risk, lo, hi = (table[c].to_numpy(dtype=np.float64) for c in ("risk", "risk_lo", "risk_hi"))
    known = np.isfinite(risk)
    with np.errstate(invalid="ignore"):
        bad = known & ~((lo <= risk) & (risk <= hi))
    found.add("interval", bad, table, "risk outside [risk_lo, risk_hi] (or a bound missing)")


def check_per_100k(table: pd.DataFrame, found: Findings) -> None:
    risk, per = table["risk"].to_numpy(dtype=np.float64), table["risk_per_100k"].to_numpy(dtype=np.float64)
    same = np.isclose(per, 1e5 * risk, rtol=1e-12, atol=0.0) | (np.isnan(per) & np.isnan(risk))
    found.add("per_100k", ~same, table, "risk_per_100k is not 1e5 x risk")


def check_confidence(table: pd.DataFrame, found: Findings) -> None:
    state = table["confidence"].to_numpy(dtype=object)
    has_cause = np.array([bool(_codes(c)) for c in table["confidence_causes"]])
    unknown = ~np.isin(state, CONFIDENCE)
    bad = unknown | ((state == "High") & has_cause) | (np.isin(state, CONFIDENCE[1:]) & ~has_cause)
    why = ["unknown confidence state" if u else "High with a cause" if s == "High" else f"{s} without a cause"
           for u, s in zip(unknown, state)]
    found.add("confidence", bad, table, why)


def check_certainty(table: pd.DataFrame, found: Findings) -> None:
    """The scenario-certainty fields of a forecast lead (module doc); a table written before section 12 has none."""
    if "certainty" not in table.columns:
        found.notes.append("no certainty fields in this table (written before section 12)")
        return
    kind = table["certainty"].to_numpy(dtype=object)
    level, low, high = (table[c].to_numpy(dtype=np.int64) for c in ("level", "level_min", "level_max"))
    scored = np.isfinite(table["risk"].to_numpy(dtype=np.float64))
    firm, depends = kind == pr.CERTAINTY_FIRM, kind == pr.CERTAINTY_DEPENDS
    problems = {"a certainty other than firm / depends_on_forecast": ~(firm | depends | pd.isna(kind)),
                "a scored row without certainty": scored & pd.isna(kind),
                "certainty on a row without a score": ~scored & ~pd.isna(kind),
                "level outside [level_min, level_max]": ~((low <= level) & (level <= high)),
                "firm with a level range": firm & ~((low == level) & (level == high)),
                "depends_on_forecast without a level range": depends & (low >= high)}
    bad = np.zeros(len(table), dtype=bool)
    why = [""] * len(table)
    for text, mask in problems.items():
        for i in np.flatnonzero(mask & ~bad):
            why[i] = text
        bad |= mask
    found.add("certainty", bad, table, why)


def expected_raw(point: np.ndarray, uncertain: np.ndarray, blind: np.ndarray, capped: np.ndarray, cap: np.ndarray
                 ) -> tuple[np.ndarray, np.ndarray]:
    """(the raw level the codes explain, the level before the rain cap)."""
    pre = np.where(uncertain | blind, np.maximum(point, lv.WATCH), point).astype(np.int8)
    return np.where(capped, cap[pre], pre).astype(np.int8), pre


def check_levels(table: pd.DataFrame, codes: list[list[str]], thresholds, rules: pr.PostRules, lead: int,
                 found: Findings) -> np.ndarray:
    """The level check (module doc); returns the pre-cap raw level for the rain-rule check."""
    region = table["region"].to_numpy(dtype=object)
    point = pr.point_levels(table["risk"].to_numpy(dtype=np.float64), thresholds, region)
    uncertain = table["uncertain_high"].to_numpy(dtype=bool)
    blind_code = np.array([any(c.endswith(BLIND_SUFFIX) for c in cs) for cs in codes])
    blind = table["blind"].to_numpy(dtype=bool) if "blind" in table.columns else np.zeros(len(table), dtype=bool)
    capped = np.array([pr.CODE_NO_RECENT_RAIN in cs for cs in codes])
    held_code = np.array([HOLD in cs for cs in codes])
    cap = rules.cap_array() if rules.gates else np.asarray(pr.DEFAULT_CAP, dtype=np.int8)
    raw, pre = expected_raw(point, uncertain, blind_code, capped, cap)
    level = table["level"].to_numpy(dtype=np.int8)
    published_raw = table["raw_level"].to_numpy(dtype=np.int8) if "raw_level" in table.columns else level
    has_codes = "reason_codes" in table.columns or "reasons_json" in table.columns
    why = [""] * len(table)
    bad = np.zeros(len(table), dtype=bool)
    for i in range(len(table)):
        problems = []
        if has_codes:
            tiers = [c for c in codes[i] if c in TIER_CODES[1:]]
            if tiers != ([TIER_CODES[point[i]]] if point[i] else []):
                problems.append(f"tier code {tiers} for a point at {lv.level_name(point[i])}")
            if ("uncertain_high" in codes[i]) != bool(uncertain[i]):
                problems.append("uncertain_high flag and code disagree")
        if uncertain[i] and point[i] != lv.NORMAL:
            problems.append("uncertain_high on a point at or above Watch")
        if blind_code[i] != blind[i] and "blind" in table.columns:
            problems.append("blind flag and blind-escalation code disagree")
        if capped[i] and cap[pre[i]] == pre[i]:
            problems.append("no_recent_rain without a cap")
        if published_raw[i] != raw[i]:
            problems.append(f"raw level {lv.level_name(published_raw[i])} where the point and the codes give "
                            f"{lv.level_name(raw[i])}")
        if lead == 0:
            if level[i] < published_raw[i]:
                problems.append("published level below the raw level")
            if (level[i] > published_raw[i]) != held_code[i]:
                problems.append("hysteresis hold without its code" if level[i] > published_raw[i]
                                else "hysteresis_hold code without a hold")
        elif level[i] != published_raw[i] or held_code[i]:
            problems.append("a forecast lead is not its raw level")
        if problems:
            bad[i], why[i] = True, "; ".join(problems)
    found.add("level", bad, table, why)
    return pre


def check_rain(table: pd.DataFrame, rain_ok: np.ndarray, window_ok: np.ndarray, pre: np.ndarray, rules: pr.PostRules,
               lead: int, found: Findings, yesterday: np.ndarray | None = None) -> None:
    """A failing, not blind-escalated cell-day is not at a gated level on its own raw level; a hold at a gated level
    needs rain in the hold window, unless it is the release of a higher level (the published level of the day before,
    `yesterday`, NaN when unknown) to its cap."""
    gated = np.isin(pre, rules.gated_levels)
    blind = table["blind"].to_numpy(dtype=bool) if "blind" in table.columns else np.zeros(len(table), dtype=bool)
    raw = table["raw_level"].to_numpy(dtype=np.int8) if "raw_level" in table.columns else table["level"].to_numpy()
    level = table["level"].to_numpy(dtype=np.int8)
    uncapped = ~rain_ok & ~blind & gated & (raw == pre)
    cap = rules.cap_array()
    before = np.full(len(table), np.nan) if yesterday is None else np.asarray(yesterday, dtype=np.float64)
    known = np.isfinite(before)
    released = known & (before > level) & (cap[np.where(known, before, 0).astype(int)] == level)
    held = (lead == 0) & (level > raw) & ~window_ok & np.isin(level, rules.gated_levels) & ~blind & ~released
    why = ["raw level at a gated level without recent rain" if u else "held at a gated level without rain in the hold "
           "window" for u in uncapped]
    found.add("rain_rule", uncapped | held, table, why)


def previous_alerts(live_dir: Path, day: date, days: int) -> list[pd.DataFrame]:
    """(cell_id, risk, level) of the published alert tables of the consecutive days before `day`, newest first."""
    out = []
    for k in range(1, days + 1):
        path = Path(live_dir) / (day - timedelta(days=k)).isoformat() / "alerts.parquet"
        if not path.is_file():
            break
        names = pq.read_schema(path).names
        frame = pd.read_parquet(path, columns=["cell_id", "risk", "level" if "level" in names else "raw_level"])
        out.append(frame.rename(columns={"raw_level": "level"}).set_index("cell_id"))
    return out


def check_blind_hold(table: pd.DataFrame, codes: list[list[str]], previous: list[pd.DataFrame], rules: pr.PostRules,
                     found: Findings) -> None:
    """Cells without a score held above their raw level: at most `blind_hold_days` such days at the held level, then one
    level lower per further day (the level of the last scored day of the published history is the start; with no
    scored day in the history the start is Emergency), and the code `held_while_blind`."""
    limit = rules.blind_hold_days
    if limit is None:
        found.notes.append("no blind-hold limit: holds over days without a score are not checked")
        return
    risk, level, raw = (table[c].to_numpy() for c in ("risk", "level", "raw_level"))
    held = ~np.isfinite(risk.astype(np.float64)) & (level > raw)
    bad = np.zeros(len(table), dtype=bool)
    why = [""] * len(table)
    for i in np.flatnonzero(held):
        cell, missing, start = int(table["cell_id"].iat[i]), 1, None
        for frame in previous:
            if cell not in frame.index:
                break
            if np.isfinite(frame.at[cell, "risk"]):
                start = int(frame.at[cell, "level"])
                break
            missing += 1
        allowed = max(int(raw[i]), (lv.EMERGENCY if start is None else start) - max(0, missing - limit))
        problems = []
        if level[i] > allowed:
            problems.append(f"held at {lv.level_name(level[i])} on day {missing} without a score (limit {limit} "
                            f"days, at most {lv.level_name(allowed)})")
        if pr.CODE_HELD_WHILE_BLIND not in codes[i]:
            problems.append("held while blind without the code held_while_blind")
        if problems:
            bad[i], why[i] = True, "; ".join(problems)
    found.add("blind_hold", bad, table, why)


def check_lead0_table(alerts: pd.DataFrame, d0: pd.DataFrame, found: Findings) -> None:
    merged = alerts[["cell_id", *LEAD0_COLUMNS]].merge(d0[["cell_id", *LEAD0_COLUMNS]], on="cell_id", how="outer",
                                                       suffixes=("", "_d0"), indicator=True)
    bad = (merged["_merge"] != "both").to_numpy().copy()
    for column in LEAD0_COLUMNS:
        a, b = merged[column], merged[f"{column}_d0"]
        if pd.api.types.is_float_dtype(a):
            differ = ~(np.isclose(a.to_numpy(dtype=np.float64), b.to_numpy(dtype=np.float64), rtol=0, atol=0)
                       | (a.isna() & b.isna()).to_numpy())
        else:
            differ = (a.astype(str) != b.astype(str)).to_numpy()
        bad |= differ
    found.add("lead0_table", bad, merged.assign(level=merged["level"].fillna(-1)), "risk_D0 differs from alerts.parquet")


# ---------------------------------------------------------------------------------------------- one table

def audit_table(table: pd.DataFrame, lead: int, thresholds, rules: pr.PostRules, features: pd.DataFrame | None,
                rain_history: pd.DataFrame | None, previous: list[pd.DataFrame] | None = None) -> Findings:
    """Every check of one published table (lead 0: alerts.parquet with the previous days' tables `previous`, newest
    first; k: risk_D<k>.parquet)."""
    table = table.reset_index(drop=True)
    found = Findings(len(table))
    check_interval(table, found)
    check_per_100k(table, found)
    check_confidence(table, found)
    codes = lead_codes(table)
    pre = check_levels(table, codes, thresholds, rules, lead, found)
    if lead == 0:
        check_blind_hold(table, codes, previous or [], rules, found)
    else:
        found.add("forecast_confidence", (table["confidence"] == "High").to_numpy(), table,
                  "a forecast row claims High confidence (source agreement) for a day without observations")
        check_certainty(table, found)
    if not rules.gates:
        found.notes.append("no post-model rule gates a level: the rain rule is not checked")
        return found
    if features is None:
        found.notes.append(f"features of lead {lead} not stored: the rain rule is not checked")
        return found
    rain = features[["cell_id", *rules.rain.columns]].drop_duplicates("cell_id")
    joined = table[["cell_id"]].merge(rain, on="cell_id", how="left")
    ok = rules.rain.passes(joined)
    window_ok = np.ones(len(table), dtype=bool)
    if lead == 0:
        today = table[["cell_id", "date"]].assign(rain_ok=ok)
        history = pd.concat([rain_history, today], ignore_index=True) if rain_history is not None else today
        release = pr.release_matrix(table["cell_id"].to_numpy(), table["date"], history, rules)
        window_ok = ~release[np.arange(len(table)), table["level"].to_numpy(dtype=np.int64)]
    yesterday = None
    if lead == 0 and previous:
        yesterday = previous[0]["level"].reindex(table["cell_id"].to_numpy()).to_numpy(dtype=np.float64)
    check_rain(table, ok, window_ok, pre, rules, lead, found, yesterday)
    return found


@dataclass
class AuditContext:
    """What the integrity checks read besides the day's own tables. A check whose input is None is skipped with a note."""
    basemap: Path | None = None            # serve.basemap india_basemap.npz (land, georef, places)
    places: Path | None = None             # serve.places cell_places.parquet
    model_columns: tuple | None = None     # the model's inputs (shap)
    rescore: bool = False                  # score the stored features again (reproducible)
    model: object | None = None            # the HazardModel to rescore with (None: `model_loader`)
    imd_lon_offset_columns: int = 0        # columns the live IMD sampling is moved east (`imd_lon_offset_columns`)
    alert_config: object | None = None     # the run's AlertConfig (`uncertain_percentile` of the uncertain_high test)
    model_loader: object | None = None     # () -> HazardModel

    def load_model(self):
        if self.model is None and self.model_loader is not None:
            self.model = self.model_loader()
        return self.model


def context_from_config(cfg: dict, rescore: bool = False, model=None, alert_config=None) -> AuditContext:
    """The context of a run configuration (`basemap_file`, `places_table`, `model_config`); `model` is the model the run
    scored with, when the caller has it (its inputs, and the model to rescore with); likewise `alert_config`."""
    from ..hazard import model as hm
    from . import run as live_run
    columns = tuple(model.columns) if model is not None else None
    if columns is None:
        model_dir = hm.configured_model_dir(hm.hazard_config(project_path(cfg["model_config"])))
        try:
            columns = tuple(json.loads((model_dir / hm.CARD_FILE).read_text(encoding="utf-8"))["columns"])
        except (OSError, ValueError, KeyError):
            columns = None
    places = cfg.get("places_table")
    basemap = cfg.get("basemap_file")
    if alert_config is None and rescore:
        alert_config = live_run.load_alert_config(project_path(cfg["alert_config"]))
    return AuditContext(basemap=project_path(basemap) if basemap else None, places=project_path(places) if places else None,
                        model_columns=columns, rescore=rescore, model=model, alert_config=alert_config,
                        imd_lon_offset_columns=int(cfg.get("imd_lon_offset_columns", 0)),
                        model_loader=lambda: live_run.load_live_model(cfg))


def _read(run_dir: Path, name: str) -> pd.DataFrame | None:
    path = run_dir / name
    return pd.read_parquet(path) if path.is_file() else None


def _imd_grid_of(run_dir: Path, day: date) -> np.ndarray | None:
    """The IMD real-time grid of IMD day `day` kept under the published days' folders, None when there is none."""
    from .sources import parse_imd_grid
    path = audit_geo.imd_grid_files(Path(run_dir).parent).get(day)
    return parse_imd_grid(path.read_bytes()) if path is not None else None


def _optional(path: Path | None, label: str, found_list: list[Findings], reader):
    """The content of an optional input file, or None with a note on every table that would have used it."""
    if path is None or not Path(path).is_file():
        for found in found_list:
            found.notes.append(f"{label} not available ({'not configured' if path is None else Path(path).name + ' not found'}): "
                               "its checks are not run")
        return None
    return reader(Path(path))


def integrity_checks(run_dir: Path, day: date, risk_tables: dict[str, pd.DataFrame], founds: dict[str, Findings],
                     features: dict[int, pd.DataFrame], context: AuditContext) -> dict[str, Findings]:
    """The integrity checks (module doc) over the risk tables `risk_tables` ({name: table}, `alerts` first) and the
    features tables `features` ({lead: table}); returns the Findings of the features tables."""
    lead_of = {"alerts": 0, **{f"risk_D{k}": k for k in range(4)}}
    feature_founds = {f"features_D{k}": Findings(len(t)) for k, t in features.items()}
    base = _optional(context.basemap, "base map", [*founds.values(), *feature_founds.values()], audit_geo.load_basemap)
    places = _optional(context.places, "place table", list(founds.values()), pd.read_parquet)
    terrain = features.get(0)
    day_grid = _imd_grid_of(run_dir, day)
    for name, table in risk_tables.items():
        found, lead = founds[name], lead_of[name]
        audit_math.check_probability(table, found)
        audit_math.check_dates(table, day, lead, found)
        audit_geo.check_grid(table, found)
        if name == "alerts":      # the cell set is the same in every table (check `dates`): land and places once
            if base is not None:
                audit_geo.check_land(table, base, found)
            if places is not None:
                audit_geo.check_places(table, places, base, found)
        if name != "risk_D0":
            audit_math.check_shap(table, features.get(lead), context.model_columns or (), found)
        if terrain is not None and name != "risk_D0":
            audit_geo.terrain_notes(table, terrain, found)
    for lead, table in features.items():
        found = feature_founds[f"features_D{lead}"]
        audit_math.check_dates(table, day, lead, found)
        audit_geo.check_grid(table, found)
        audit_math.check_rain_math(table, found)
        if lead == 0 and base is not None:
            audit_geo.check_georef_terrain(table, base, found)
        if lead == 0 and day_grid is not None:
            audit_geo.check_imd_sampling(table, day_grid, context.imd_lon_offset_columns, found)
    audit_math.check_cell_sets({**risk_tables, **{n: features[int(n[-1])] for n in feature_founds}},
                               {**founds, **feature_founds})
    audit_math.check_rain_chain(features, {k: feature_founds[f"features_D{k}"] for k in features})
    return feature_founds


def rescore_checks(risk_tables: dict[str, pd.DataFrame], founds: dict[str, Findings], features: dict[int, pd.DataFrame],
                   context: AuditContext, thresholds, rules: pr.PostRules) -> dict:
    """`reproducible` and the full-vector `shap` check with the context's model; returns {"ran", "seconds", "factors", ...}."""
    start = time.monotonic()
    model = context.load_model()
    if model is None:
        for found in founds.values():
            found.notes.append("no model to rescore with: reproducible is not checked")
        return {"ran": False}
    info = {"ran": True, "factors": {}, "rows_scored": {}}
    alerts = risk_tables["alerts"]
    scored_on_d = pd.Series(np.isfinite(alerts["risk"].to_numpy(dtype=np.float64)), index=alerts["cell_id"].to_numpy())
    for name in ("alerts", "risk_D1", "risk_D2", "risk_D3"):
        lead = 0 if name == "alerts" else int(name[-1])
        if name not in risk_tables or lead not in features:
            continue
        table = risk_tables[name]
        on_day_d = None if lead == 0 else scored_on_d.reindex(table["cell_id"].to_numpy()).fillna(False).to_numpy(dtype=bool)
        done = audit_rescore.check_reproducible(model, table, features[lead], lead, on_day_d, founds[name])
        audit_rescore.check_contributions(model, table, features[lead], done["scorable"], founds[name])
        if context.alert_config is not None and "uncertain_high" in table.columns:
            audit_rescore.check_uncertain(model, table, done["features"], done["raw"], done["scorable"], lead, thresholds,
                                          context.alert_config, rules, done["factors"], founds[name])
        info["rows_scored"][name] = done["rows_scored"]
        if done["factors"] is not None:
            info["factors"][name] = list(done["factors"])
    info["seconds"] = round(time.monotonic() - start, 1)
    return info


def audit_day(run_dir: Path, rules: pr.PostRules, summary: dict | None = None, context: AuditContext | None = None) -> dict:
    """The audit of one published day (`<live_dir>/<D>/`): its run.json, or `summary` (the run's summary before run.json
    is written). `context` names the optional inputs of the integrity checks (none: they run on the day's tables only)."""
    run_dir = Path(run_dir)
    context = context or AuditContext()
    summary_path = run_dir / "run.json"
    if summary is None:
        if not summary_path.is_file():
            raise FileNotFoundError(f"{summary_path} not found: the day is not published")
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    day = date.fromisoformat(summary["date"])
    thresholds = run_thresholds(summary)
    tables = {}
    alerts = pd.read_parquet(run_dir / "alerts.parquet")
    risk_tables = {"alerts": alerts}
    features = {k: t for k in range(4) if (t := _read(run_dir, f"features_D{k}.parquet")) is not None}
    longest = max([rules.hold_window_days, *rules.hold_windows.values()])
    history = pr.previous_rain_ok(run_dir.parent, day, longest - 1, rules) if rules.gates and longest > 1 else None
    previous = previous_alerts(run_dir.parent, day, 30)
    tables["alerts"] = audit_table(alerts, 0, thresholds, rules, features.get(0), history, previous)
    d0 = _read(run_dir, "risk_D0.parquet")
    if d0 is not None:
        found = Findings(len(alerts))
        check_lead0_table(alerts, d0, found)
        tables["risk_D0"] = found
        risk_tables["risk_D0"] = d0
    for lead in (1, 2, 3):
        table = _read(run_dir, f"risk_D{lead}.parquet")
        if table is None:
            continue
        tables[f"risk_D{lead}"] = audit_table(table, lead, thresholds, rules, features.get(lead), None)
        risk_tables[f"risk_D{lead}"] = table
    feature_tables = integrity_checks(run_dir, day, risk_tables, tables, features, context)
    extra = {"rescore": rescore_checks(risk_tables, tables, features, context, thresholds, rules)} if context.rescore else {}
    everyone = {**tables, **feature_tables}
    totals = {name: sum(t.counts[name] for t in everyone.values()) for name in CHECKS}
    notes = {f"{name}.{key}": count for name, found in everyone.items() for key, count in found.note_counts.items() if count}
    return {"date": day.isoformat(), "rules": rules.to_dict(), "rules_source": rules.source,
            "tables": {name: t.to_dict() for name, t in tables.items()},
            "feature_tables": {name: t.to_dict() for name, t in feature_tables.items()}, "violations": totals,
            "total_violations": int(sum(totals.values())), "rows": int(sum(t.rows for t in tables.values())),
            "note_counts": dict(sorted(notes.items())), **extra}


def published_days(live_dir: Path) -> list[date]:
    days = []
    for folder in sorted(Path(live_dir).iterdir()):
        try:
            day = date.fromisoformat(folder.name)
        except ValueError:
            continue
        if (folder / "run.json").is_file():
            days.append(day)
    return days


MIN_RAIN_DAYS = 5      # the pooled rain-registration test is decided on at least this many days with both products


def pooled_rain_georef(live_dir: Path, days, lon_offset_columns: int = 0) -> dict:
    """`audit_geo.rain_georef` over the features and the IMD real-time grids of `days`; undecided on fewer than
    MIN_RAIN_DAYS days with both products."""
    from .sources import parse_imd_grid
    grids = {d: parse_imd_grid(p.read_bytes()) for d, p in audit_geo.imd_grid_files(live_dir).items()}
    daily = {}
    for d in days:
        path = Path(live_dir) / d.isoformat() / "features_D0.parquet"
        if path.is_file() and "irain_acc_1" in pq.read_schema(path).names:
            daily[d] = pd.read_parquet(path, columns=["cell_id", "irain_acc_1"])
    result = audit_geo.rain_georef(daily, grids, lon_offset_columns=lon_offset_columns)
    if result["days"] < MIN_RAIN_DAYS:
        result["decided"], result["violations"] = False, []
    return result


def audit_days(live_dir: Path, days, rules: pr.PostRules, out: Path, context: AuditContext | None = None) -> dict:
    """Audit each day, write `<out>/<day>.json`; returns the summary over the days."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    per_day = {}
    for day in days:
        result = audit_day(Path(live_dir) / day.isoformat(), rules, context=context)
        dump_json(out / f"{day.isoformat()}.json", result)
        per_day[day.isoformat()] = {"rows": result["rows"], "violations": result["violations"],
                                    "total_violations": result["total_violations"], "note_counts": result["note_counts"],
                                    **({"rescore_seconds": result["rescore"].get("seconds")} if "rescore" in result else {})}
    totals = {name: sum(d["violations"][name] for d in per_day.values()) for name in CHECKS}
    georef = pooled_rain_georef(live_dir, days, context.imd_lon_offset_columns) if context is not None else None
    if georef is not None:
        totals["georef"] += len(georef["violations"])
    return {"created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "rules": rules.to_dict(),
            "rules_source": rules.source, "days": per_day, "violations": totals, "rain_georef": georef,
            "total_violations": int(sum(totals.values()))}


def configured_rules(cfg: dict, path: Path | None) -> pr.PostRules:
    """The rules named on the command line, else the run configuration's `post_rules`, else none."""
    if path is not None:
        return pr.load_rules(path)
    configured = cfg.get("post_rules")
    return pr.load_rules(project_path(configured)) if configured else pr.NO_RULES


def main(argv=None) -> int:
    from .run import live_root, load_run_config
    parser = argparse.ArgumentParser(prog="python -m aetherguard.live.audit", description=__doc__.splitlines()[0])
    parser.add_argument("--date", default=None, help="YYYY-MM-DD or all")
    parser.add_argument("--config", type=Path, default=None, help="configs/live_run.yaml")
    parser.add_argument("--rules", type=Path, default=None, help="post-model rules (default: the config's post_rules)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="where the JSON summaries are written")
    parser.add_argument("--rescore", action="store_true", help="score every stored feature table again (check `reproducible`)")
    parser.add_argument("--api", default=None, metavar="URL", help="compare the dashboard API at URL with the newest published "
                        "day (live.audit_parity) instead of auditing the tables")
    args = parser.parse_args(argv)
    if args.api is None and args.date is None:
        parser.error("--date is required (unless --api is given)")
    try:
        cfg = load_run_config(args.config)
        live_dir = live_root(cfg)
        if args.api:
            from . import audit_parity
            return audit_parity.main_api(args.api, cfg, live_dir, args.out)
        rules = configured_rules(cfg, args.rules)
        context = context_from_config(cfg, rescore=args.rescore)
        days = published_days(live_dir) if args.date == "all" else [date.fromisoformat(args.date)]
        summary = audit_days(live_dir, days, rules, args.out, context)
        if args.date == "all":
            dump_json(Path(args.out) / "summary.json", summary)
    except (ValueError, OSError, KeyError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    for day, entry in summary["days"].items():
        listed = ", ".join(f"{k} {v}" for k, v in entry["violations"].items() if v) or "none"
        print(f"{day}: {entry['rows']} rows, violations: {listed}")
    georef = summary.get("rain_georef")
    if georef is not None:
        for text in georef["violations"]:
            print(f"rain georef: {text}")
    return EXIT_VIOLATIONS if summary["total_violations"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
