"""Choosing the post-model rules on the DEVELOPMENT panels only (`hardening score-dev`, out of fold, 2007-2017).

Every number here comes from the out-of-fold panels of the development seasons and the development positives; nothing
reads 2018, the 2023 window, Wayanad 2024 or a live day. The alert levels are those of Task 6b: the card's thresholds per
region, `uncertain_high` at the 90th percentile and the hysteresis of `alert_config_v3.json` (exit factor 0.8, 2 days).

1. Interval. The levels with the old upper bound (90th percentile of the calibrated members) against the re-centred one
   (`HazardModel.score`); the re-centring is a correction, so it is the baseline of the steps below.
2. Ensemble agreement. At A in {0.1, 0.25, 0.5}: the development events whose point reaches Warning or above, split by
   whether at least A of the members reach the point's level, and the alert cell-days of the same split; the precision
   proxy is events per alerted cell-day. Pre-declared: A = 0.25, unless the disagreeing alerts are at least as precise as
   the agreeing ones, in which case the rule is kept as a flag only (`agreement_min` None).
3. Rain trigger. Minima are the 1st, 2nd and 5th percentiles of the 1-, 3- and 7-day IMERG rain of the in-domain
   development positives; forms: 3-day alone, 7-day alone, 3- OR 7-day, 1- OR 3- OR 7-day (a 0 mm minimum admits every
   cell-day, so a form with one is vacuous and skipped). Each (form, percentile) is applied at one level at a time (cap
   Watch -> Normal, Warning -> Watch, Emergency -> Watch, before the hysteresis, holds released after a hold window
   without rain). PRE-DECLARED ADOPTION, per level: adopted when it loses at most 1% (relative) of the development events
   detected at that level and lowers the share of cell-days at that level or above. The rule chosen is the candidate
   adoptable at the most levels; ties go to the lower Warning-or-above share with every adoptable level gated, then the
   lower Watch-or-above share, the lower percentile and the simpler form.
   Hold window, per level (as the adoption rule is): with the chosen rule, the shortest window in {1, 2, 3} days
   (ending on the day) for holds at that level whose release meets the adoption rule at that level, the other levels
   keeping 3 days; then the combination must meet the rule at every gated level (the rule itself is chosen with 3 days).
   Added after the continuous re-run of the live days showed a 3-day (then a common 2-day) window letting a 7-day total
   from up to 9 days back justify a hold; chosen on development data only.
   The cost of capping post-rain dry cells: the development positives that occurred 7 days or more after the last
   10 mm day with a 7-day rain under the 7-day minimum.
5. Blind-hold limit (safety rule). How fast the point level of a cell decays after a day at that level: the share of
   universe cell-days at Watch / Warning / Emergency or above whose point is still there k = 1, 2, 3 days later.
   PRE-DECLARED: H = the largest k with a retention of at least 0.5 at every level, and at least 1 (the default).
6. Terrain diagnostic. On the dry (3-day rain under 1 mm) and wet Watch, Warning and Emergency cell-days of the levels of
   step 1: how much of the point model's log-odds comes from stat_aspect_sin / stat_aspect_cos / stat_twi_proxy.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from ..alerts import levels as lv
from ..alerts.config import load_config_file as load_alert_config
from ..config import PROJECT_ROOT
from ..hazard import data as hd
from ..hazard import model as hm
from ..hazard.jsonio import dump_json
from ..hazard.train import extra_groups_used
from . import backtest as bt
from . import burden
from . import hardening as H
from . import postrules as pr
from . import run as live_run

ANALYSIS_FILE = "dev_analysis.json"
QUANTILES = (1.0, 2.0, 5.0)
FORMS = {"acc_3": (3,), "acc_7": (7,), "acc_3_or_acc_7": (3, 7), "acc_1_or_acc_3_or_acc_7": (1, 3, 7)}
AGREEMENT_MINIMA = (0.1, 0.25, 0.5)
DEFAULT_AGREEMENT = 0.25
MAX_RELATIVE_LOSS = 0.01
HOLD_WINDOW_DAYS = 3          # D-2..D: the window the rain-rule candidates are compared at
HOLD_WINDOWS = (1, 2, 3)      # the windows the chosen rule's hold release is compared at
POST_RAIN_DAYS = 7            # "post-rain": the last 10 mm day is at least this many days back
RETENTION_DAYS = (1, 2, 3)
RETENTION_MIN = 0.5
DEFAULT_BLIND_HOLD_DAYS = 1
LEVELS = (lv.WATCH, lv.WARNING, lv.EMERGENCY)
PROJECT_HAZARD_CONFIG = PROJECT_ROOT / "configs" / "hazard_v3.yaml"


@dataclass
class Season:
    year: int
    panel: H.Panel
    first: int                               # column of 1 June
    events: pd.DataFrame                     # development events of the season in the panel's cells
    thresholds: dict[str, lv.Thresholds]

    @property
    def region(self) -> np.ndarray:
        return self.panel.cells["region"].to_numpy()


def load_seasons(directory: Path, years, card: dict, events: pd.DataFrame, say=None) -> list[Season]:
    seasons = []
    for year in years:
        panel = H.load_panel(H.season_path(directory, year))
        first = panel.days.index(date(year, *burden.SEASON_START))
        ids = panel.cells["cell_id"]
        in_year = events[(events["date"].dt.year == year) & events["cell_id"].isin(ids)].reset_index(drop=True)
        seasons.append(Season(year, panel, first, in_year, lv.card_region_thresholds(card, panel.cells["region"])))
        if say:
            say(f"  loaded {year}: {len(panel.cells)} cells, {len(in_year)} events")
    return seasons


# ------------------------------------------------------------------------------------------------ levels

def window_any(ok: np.ndarray, window: int) -> np.ndarray:
    """Per (cell, day): `ok` on at least one of the `window` days ending on that day (days before the panel do not count)."""
    out = np.zeros(ok.shape, dtype=bool)
    for back in range(window):
        out[:, back:] |= ok[:, :ok.shape[1] - back]
    return out


def rain_ok(panel: H.Panel, rule: pr.RainRule) -> np.ndarray:
    return rule.passes_arrays({w: panel[f"acc_{w}"] for w in rule.minimum_mm})


def season_levels(season: Season, upper: str, config, rules: pr.PostRules | None = None, release: bool = True,
                  ok: np.ndarray | None = None) -> np.ndarray:
    """Full alert levels (cells, days) of a season: point risk against the thresholds of the cell's region,
    `uncertain_high` against the panel field `upper` (`risk` for none), the rain cap of `rules` on the raw level, then the
    hysteresis with the hold release (`release`) of `rules`."""
    panel = season.panel
    risk, bound = panel["risk"], panel[upper]
    region = season.region
    raw = np.zeros(risk.shape, dtype=np.int8)
    for name, thr in season.thresholds.items():
        rows = region == name
        raw[rows] = lv.raw_level(risk[rows], bound[rows], thr)[0]
    return levels_from_raw(season, raw, config, rules, release, ok)


def levels_from_raw(season: Season, raw: np.ndarray, config, rules: pr.PostRules | None = None, release: bool = True,
                    ok: np.ndarray | None = None, row_thresholds: np.ndarray | None = None) -> np.ndarray:
    """The part of `season_levels` after the raw level (cells, days): the rain cap of `rules` on the raw level, then the
    hysteresis with the hold release of `rules`. The hysteresis steps down against the thresholds of the cell's region,
    or against `row_thresholds` (cells, days, 3) when the thresholds change from day to day."""
    panel = season.panel
    risk, region = panel["risk"], season.region
    gates = rules is not None and rules.gates
    if gates:
        ok = rain_ok(panel, rules.rain) if ok is None else ok
        cap = rules.cap_array()
        raw = np.where(ok, raw, cap[raw]).astype(np.int8)
        windows = {level: rules.window_of(level) for level in LEVELS}
        by_window = {w: ~window_any(ok, w) for w in set(windows.values())}
        released = np.zeros((*ok.shape, 4), dtype=bool)
        for level, w in windows.items():
            released[..., level] = by_window[w]
    out = np.zeros(raw.shape, dtype=np.int8)
    stamps = pd.DatetimeIndex(pd.to_datetime(panel.days)).to_numpy()
    for name, thr in season.thresholds.items():
        rows = np.flatnonzero(region == name)
        ids = np.repeat(panel.cells["cell_id"].to_numpy(dtype=np.int64)[rows], len(panel.days))
        dates = np.tile(stamps, len(rows))
        extra = (released[rows].reshape(-1, 4), cap) if gates and release else (None, None)
        blind_hold = None if rules is None else rules.blind_hold_days
        step_down = thr if row_thresholds is None else row_thresholds[rows].reshape(-1, 3)
        out[rows] = lv.apply_hysteresis(ids, dates, raw[rows].ravel(), risk[rows].ravel(), step_down, config.exit_factor,
                                        config.exit_days, None, *extra, blind_hold).reshape(len(rows), -1)
    return out


def point_levels(season: Season) -> np.ndarray:
    risk, region = season.panel["risk"], season.region
    out = np.zeros(risk.shape, dtype=np.int8)
    for name, thr in season.thresholds.items():
        rows = region == name
        out[rows] = lv.level_from_risk(risk[rows], thr)
    return out


def agreement(season: Season, point: np.ndarray) -> np.ndarray:
    """Share of members at or above the point's level (1 for a Normal point), per (cell, day)."""
    panel = season.panel
    counts = np.stack([np.full(point.shape, panel.n_members, dtype=np.int64),
                       *(panel[name].astype(np.int64) for name in H.COUNT_FIELDS)])
    return np.take_along_axis(counts, point[None].astype(np.int64), axis=0)[0] / panel.n_members


# ----------------------------------------------------------------------------------------------- metrics

def season_outcome(season: Season, levels: np.ndarray) -> dict:
    """Cell-day counts at each level or above on the universe cells (June-September), the dry ones among them, and the
    own-cell level and lead of every event."""
    panel, first = season.panel, season.first
    lev, scored = levels[:, first:], panel.scored[:, first:]
    universe = panel.cells["in_universe"].to_numpy(dtype=bool)
    lev_u, sc_u = lev[universe], scored[universe]
    dry_u = (panel["acc_3"][:, first:][universe] < H.DRY_ACC3_MM) & sc_u
    table = bt.event_outcomes(lev, scored, panel.cells["cell_id"].to_numpy(dtype=np.int64), panel.days[first:],
                              season.events)
    own = table["own_level"].fillna(0).to_numpy(dtype=int) if len(table) else np.zeros(0, dtype=int)
    leads = table["own_lead_days"].to_numpy(dtype=float) if len(table) else np.zeros(0)
    return {"cell_days": int(sc_u.sum()),
            "at_least": {int(L): int(((lev_u >= L) & sc_u).sum()) for L in LEVELS},
            "dry_at": {int(L): int(((lev_u == L) & dry_u).sum()) for L in LEVELS},
            "own_level": own, "leads": leads}


def combine(outcomes: list[dict]) -> dict:
    n = sum(o["cell_days"] for o in outcomes)
    own = np.concatenate([o["own_level"] for o in outcomes])
    leads = np.concatenate([o["leads"] for o in outcomes])
    boot = bt.BOOTSTRAP
    out = {"cell_days": n, "n_events": int(len(own)),
           "share_at_least": {lv.level_name(L): sum(o["at_least"][L] for o in outcomes) / n for L in LEVELS},
           "dry_cell_days_at": {lv.level_name(L): sum(o["dry_at"][L] for o in outcomes) for L in LEVELS},
           "detected_at_least": {lv.level_name(L): bt.share_ci(own >= L, boot["n"], boot["seed"], boot["level"])
                                 for L in LEVELS},
           "median_lead_days": float(np.nanmedian(leads)) if np.isfinite(leads).any() else None}
    out["own_levels"] = own.tolist()
    return out


def evaluate(seasons: list[Season], upper: str, config, rules: pr.PostRules | None = None, release: bool = True,
             label: str = "") -> dict:
    result = combine([season_outcome(s, season_levels(s, upper, config, rules, release)) for s in seasons])
    return {"label": label, "upper": upper, "rules": None if rules is None else rules.to_dict(), "release": release,
            **result}


def compact(result: dict) -> dict:
    return {k: v for k, v in result.items() if k != "own_levels"}


# -------------------------------------------------------------------------------------- step 2: agreement

def agreement_split(seasons: list[Season], minima=AGREEMENT_MINIMA, universe_cells: int | None = None) -> dict:
    """At each minimum A: development events whose point reaches Warning or above on the event day (own cell), and the
    universe cell-days at Warning or above, split into agreeing (agreement >= A) and disagreeing; the precision proxy is
    events per 1,000 alerted cell-days, the sampled cell-days scaled to all `universe_cells`."""
    event_values, alert_values, sampled = [], [], 0
    for s in seasons:
        point = point_levels(s)
        share = agreement(s, point)
        first, panel = s.first, s.panel
        universe = panel.cells["in_universe"].to_numpy(dtype=bool)
        sampled = int(universe.sum())
        alerted = (point[:, first:] >= lv.WARNING) & panel.scored[:, first:]
        alert_values.append(share[:, first:][universe][alerted[universe]])
        row_of = {int(c): i for i, c in enumerate(panel.cells["cell_id"])}
        col_of = {pd.Timestamp(d): j for j, d in enumerate(panel.days)}
        for event in s.events.itertuples():
            i, j = row_of[int(event.cell_id)], col_of.get(pd.Timestamp(event.date))
            if j is not None and point[i, j] >= lv.WARNING:
                event_values.append(share[i, j])
    events, alerts = np.asarray(event_values), np.concatenate(alert_values)
    n_events = sum(len(s.events) for s in seasons)
    scale = (universe_cells / sampled) if universe_cells and sampled else 1.0
    out = {"events_total": int(n_events), "events_point_warning_plus": int(len(events)),
           "alert_cell_days_point_warning_plus": int(len(alerts)), "universe_cells": universe_cells,
           "sampled_universe_cells": sampled, "by_minimum": {}}
    for a in minima:
        groups = {}
        for name, e_mask, c_mask in (("agreeing", events >= a, alerts >= a), ("disagreeing", events < a, alerts < a)):
            n_e, n_c = int(e_mask.sum()), int(c_mask.sum())
            groups[name] = {"events": n_e, "events_share_of_all": n_e / n_events if n_events else None,
                            "alert_cell_days": n_c, "alert_cell_day_share": n_c / len(alerts) if len(alerts) else None,
                            "events_per_1000_alerted_cell_days": 1000 * n_e / (n_c * scale) if n_c else None}
        groups["disagreeing_as_precise"] = bool(
            groups["disagreeing"]["events_per_1000_alerted_cell_days"] is not None
            and groups["agreeing"]["events_per_1000_alerted_cell_days"] is not None
            and groups["disagreeing"]["events_per_1000_alerted_cell_days"]
            >= groups["agreeing"]["events_per_1000_alerted_cell_days"])
        out["by_minimum"][f"{a:g}"] = groups
    return out


def choose_agreement(split: dict) -> dict:
    default = split["by_minimum"][f"{DEFAULT_AGREEMENT:g}"]
    as_precise = default["disagreeing_as_precise"]
    return {"agreement_min": None if as_precise else DEFAULT_AGREEMENT, "flag_only": as_precise,
            "rule": "A = 0.25 (pre-declared) unless the disagreeing Warning+ alerts are at least as precise (events per "
                    "alerted cell-day) as the agreeing ones; then the disagreement is reported as a flag only"}


# ----------------------------------------------------------------------------------- step 3: rain trigger

def positive_quantiles(directory: Path | None = None, hazard_cfg: dict | None = None) -> dict:
    """The 1st, 2nd and 5th percentiles of the 1-, 3- and 7-day IMERG rain of the in-domain development positives
    (train + validation samples, every month)."""
    cfg = hazard_cfg or hm.hazard_config(PROJECT_HAZARD_CONFIG)
    dev = hd.load_development(directory, cfg["extra_groups"], extra_groups_used(cfg), cfg["meta_columns"])
    samples = dev.samples
    positives = samples[(samples["kind"] == "positive") & samples["in_domain"].astype(bool)]
    out = {"n_positives": int(len(positives)), "quantiles": {}, "dry_shares": {},
           "acc_7": positives["irain_acc_7"].to_numpy(dtype=np.float64).tolist(),
           "days_since_10mm": positives["irain_days_since_10mm"].to_numpy(dtype=np.float64).tolist()}
    for w in H.RAIN_WINDOWS:
        values = positives[f"irain_acc_{w}"].dropna().to_numpy(dtype=np.float64)
        out["quantiles"][str(w)] = {f"{q:g}": float(np.percentile(values, q)) for q in QUANTILES}
        out["dry_shares"][str(w)] = {"below_1mm": float((values < 1).mean()), "below_5mm": float((values < 5).mean()),
                                     "n": int(len(values))}
    return out


def candidate_rules(quantiles: dict) -> list[dict]:
    """Every (form, percentile) with its minima; a form whose minimum is 0 mm at that percentile is marked vacuous."""
    out = []
    for form, windows in FORMS.items():
        for q in QUANTILES:
            minima = {w: quantiles["quantiles"][str(w)][f"{q:g}"] for w in windows}
            vacuous = [w for w, m in minima.items() if m <= 0]
            out.append({"form": form, "percentile": q, "minimum_mm": minima, "vacuous_windows": vacuous})
    return out


def adoption(baseline: dict, gated: dict, level: int) -> dict:
    name = lv.level_name(level)
    before, after = baseline["detected_at_least"][name]["hits"], gated["detected_at_least"][name]["hits"]
    loss = (before - after) / before if before else 0.0
    share_before, share_after = baseline["share_at_least"][name], gated["share_at_least"][name]
    return {"level": name, "events_before": before, "events_after": after, "events_lost": before - after,
            "relative_loss": loss, "share_before": share_before, "share_after": share_after,
            "adopt": bool(loss <= MAX_RELATIVE_LOSS + 1e-12 and share_after < share_before)}


def rain_study(seasons: list[Season], config, quantiles: dict, baseline: dict, say=None) -> dict:
    rows, combined = [], []
    for candidate in candidate_rules(quantiles):
        if candidate["vacuous_windows"]:
            rows.append({**candidate, "per_level": None, "adoptable_levels": []})
            continue
        rule = pr.RainRule(candidate["minimum_mm"])
        per_level = []
        for level in LEVELS:
            rules = pr.PostRules(None, rule, (level,), hold_window_days=HOLD_WINDOW_DAYS)
            per_level.append(adoption(baseline, evaluate(seasons, "new_hi", config, rules), level))
        adoptable = [p["level"] for p in per_level if p["adopt"]]
        entry = {**candidate, "per_level": per_level, "adoptable_levels": adoptable}
        if adoptable:
            rules = pr.PostRules(None, rule, tuple(lv.parse_level(n) for n in adoptable), hold_window_days=HOLD_WINDOW_DAYS)
            together = evaluate(seasons, "new_hi", config, rules, label=f"{candidate['form']} p{candidate['percentile']:g}")
            entry["combined"] = compact(together)
            entry["combined_adoption"] = [adoption(baseline, together, lv.parse_level(n)) for n in adoptable]
            combined.append(entry)
        rows.append(entry)
        if say:
            say(f"  {candidate['form']} p{candidate['percentile']:g}: adoptable {adoptable}")
    return {"candidates": rows, "chosen": choose_rule(rows)}


def choose_rule(rows: list[dict]) -> dict | None:
    """The pre-declared choice (module doc, step 3) among the candidates adoptable at one level or more whose combined
    gating still meets the adoption rule at every adopted level."""
    order = list(FORMS)
    eligible = [r for r in rows if r["adoptable_levels"] and all(a["adopt"] for a in r["combined_adoption"])]
    if not eligible:
        return None
    best = min(eligible, key=lambda r: (-len(r["adoptable_levels"]), r["combined"]["share_at_least"]["Warning"],
                                        r["combined"]["share_at_least"]["Watch"], r["percentile"], order.index(r["form"])))
    return {"form": best["form"], "percentile": best["percentile"], "minimum_mm": best["minimum_mm"],
            "gated_levels": best["adoptable_levels"]}


def hold_window_study(seasons: list[Season], config, rules: pr.PostRules, baseline: dict) -> dict:
    """Per gated level, the chosen rule with that level's hold window shortened to 1, 2 or 3 days (the others at 3):
    the adoption at that level; the shortest window meeting it is the level's window. The combination is then evaluated
    and must meet the adoption rule at every gated level (else every level keeps 3 days)."""
    per_level, chosen = {}, {}
    for level in rules.gated_levels:
        rows = {}
        for window in HOLD_WINDOWS:
            result = evaluate(seasons, "new_hi", config, replace(rules, hold_windows={level: window}))
            rows[str(window)] = {"share_at_least": result["share_at_least"],
                                 "adoption": adoption(baseline, result, level)}
        ok = [w for w in HOLD_WINDOWS if rows[str(w)]["adoption"]["adopt"]]
        chosen[level] = min(ok) if ok else rules.hold_window_days
        per_level[lv.level_name(level)] = {"windows": rows, "chosen": chosen[level]}
    combined = evaluate(seasons, "new_hi", config, replace(rules, hold_windows=chosen), label="per-level hold windows")
    checks = [adoption(baseline, combined, level) for level in rules.gated_levels]
    keep = all(c["adopt"] for c in checks)
    return {"per_level": per_level, "combined": compact(combined), "combined_adoption": checks,
            "chosen": {lv.level_name(level): int(w) for level, w in chosen.items()} if keep else None,
            "rule": "per level, the shortest hold window meeting the adoption rule at that level; the combination must "
                    "meet it at every gated level"}


def post_rain_cost(quantiles: dict, minimum_7: float | None) -> dict:
    """Development positives (in-domain, every month) 7 days or more after the last 10 mm day, and those of them whose
    7-day rain is under the rule's 7-day minimum (they are capped by it)."""
    acc7, since = np.asarray(quantiles["acc_7"]), np.asarray(quantiles["days_since_10mm"])
    post = np.isfinite(since) & (since >= POST_RAIN_DAYS)
    out = {"n_positives": int(len(acc7)), "post_rain": int(post.sum()), "minimum_7_mm": minimum_7,
           "unknown_days_since": int((~np.isfinite(since)).sum())}
    if minimum_7 is not None:
        capped = post & (acc7 < minimum_7)
        out.update(post_rain_below_minimum=int(capped.sum()), share_of_positives=float(capped.sum() / len(acc7)),
                   all_below_minimum=int((acc7 < minimum_7).sum()))
    return out


# --------------------------------------------------------------------------------- step 5: blind-hold limit

def retention(seasons: list[Season], days=RETENTION_DAYS) -> dict:
    """Per level L and lag k: of the universe cell-days whose point is at L or above, the share still at L or above k days
    later (both days scored, June-September)."""
    hits = {(L, k): 0 for L in LEVELS for k in days}
    base = {(L, k): 0 for L in LEVELS for k in days}
    for s in seasons:
        universe = s.panel.cells["in_universe"].to_numpy(dtype=bool)
        point = point_levels(s)[universe, s.first:]
        scored = s.panel.scored[universe, s.first:]
        for k in days:
            both = scored[:, :-k] & scored[:, k:]
            for L in LEVELS:
                start = (point[:, :-k] >= L) & both
                base[(L, k)] += int(start.sum())
                hits[(L, k)] += int((start & (point[:, k:] >= L)).sum())
    return {lv.level_name(L): {str(k): {"cell_days": base[(L, k)], "retained": hits[(L, k)],
                                        "share": hits[(L, k)] / base[(L, k)] if base[(L, k)] else None} for k in days}
            for L in LEVELS}


def choose_blind_hold(table: dict) -> dict:
    ok = [k for k in RETENTION_DAYS if all(table[lv.level_name(L)][str(k)]["share"] is not None
                                           and table[lv.level_name(L)][str(k)]["share"] >= RETENTION_MIN for L in LEVELS)]
    days = max([DEFAULT_BLIND_HOLD_DAYS, *ok])
    return {"blind_hold_days": days, "lags_meeting_retention": ok,
            "rule": f"H = the largest k in {list(RETENTION_DAYS)} whose retention is at least {RETENTION_MIN} at every "
                    f"level, and at least {DEFAULT_BLIND_HOLD_DAYS} (pre-declared)"}


# --------------------------------------------------------------------------------- step 6: terrain diagnostic

def terrain_rows(season: Season, levels: np.ndarray, model: hm.HazardModel) -> pd.DataFrame:
    """The universe cell-days (June-September) at Watch or above with their published level, dryness and the terrain
    contributions (NaN where the point model was not explained)."""
    panel, first = season.panel, season.first
    universe = panel.cells["in_universe"].to_numpy(dtype=bool)
    lev = levels[universe, first:]
    keep = (lev >= lv.WATCH) & panel.scored[universe, first:]
    take = lambda name: panel[name][universe, first:][keep]
    regions = np.repeat(season.region[universe][:, None], lev.shape[1], axis=1)[keep]
    frame = pd.DataFrame({"level": lev[keep], "region": regions, "acc_3": take("acc_3"), "risk": take("risk"),
                          "c_aspect_sin": take("c_aspect_sin"), "c_aspect_cos": take("c_aspect_cos"),
                          "c_twi": take("c_twi"), "c_positive": take("c_positive"), "margin": take("margin"),
                          "top3_terrain": take("top3_terrain")})
    return with_counterfactual(frame, model, season.thresholds)


def with_counterfactual(frame: pd.DataFrame, model: hm.HazardModel, thresholds) -> pd.DataFrame:
    """Adds the point level the row would have without the aspect and TWI contributions (raw score from the log-odds
    minus those three, calibrated by the row's calibrator) and the point level it has."""
    terrain = frame[["c_aspect_sin", "c_aspect_cos", "c_twi"]].to_numpy(dtype=np.float64)
    explained = np.isfinite(frame["margin"].to_numpy(dtype=np.float64))
    without = np.full(len(frame), np.nan)
    if explained.any():
        raw = hm.expit(frame["margin"].to_numpy(dtype=np.float64)[explained] - terrain[explained].sum(axis=1))
        without[explained] = model.calibrate(raw, frame.loc[explained, ["region"]])[0]
    region = frame["region"].to_numpy(dtype=object)
    point = np.zeros(len(frame), dtype=np.int8)
    after = np.zeros(len(frame), dtype=np.int8)
    for name, thr in thresholds.items():
        rows = region == name
        point[rows] = lv.level_from_risk(frame["risk"].to_numpy()[rows], thr)
        after[rows] = lv.level_from_risk(without[rows], thr)
    return frame.assign(point_level=point, level_without_terrain=after, explained=explained)


def terrain_summary(frame: pd.DataFrame) -> dict:
    """Per published level and dry / wet: how much of the point model's log-odds the aspect and TWI inputs carry."""
    out = {}
    for level in LEVELS:
        for dry in (True, False):
            part = frame[(frame["level"] == level) & ((frame["acc_3"] < H.DRY_ACC3_MM) == dry)]
            key = f"{lv.level_name(level)}_{'dry' if dry else 'wet'}"
            explained = part[part["explained"]]
            entry = {"cell_days": int(len(part)), "explained": int(len(explained))}
            if len(explained):
                aspect = explained["c_aspect_sin"] + explained["c_aspect_cos"]
                terrain = aspect + explained["c_twi"]
                positive = (explained[["c_aspect_sin", "c_aspect_cos", "c_twi"]].clip(lower=0).sum(axis=1)
                            / explained["c_positive"].where(explained["c_positive"] > 0))
                at_point = explained["point_level"] >= lv.WATCH
                entry.update({
                    "median_logodds_aspect": float(aspect.median()), "median_logodds_twi": float(explained["c_twi"].median()),
                    "median_logodds_aspect_twi": float(terrain.median()),
                    "mean_share_of_positive_contribution": float(positive.mean()),
                    "share_top3_all_aspect_twi": float(explained["top3_terrain"].mean()),
                    "share_point_level_drops_without_aspect_twi": float(
                        (explained.loc[at_point, "level_without_terrain"] < explained.loc[at_point, "point_level"]).mean())
                    if at_point.any() else None,
                    "share_below_watch_without_aspect_twi": float(
                        (explained.loc[at_point, "level_without_terrain"] < lv.WATCH).mean()) if at_point.any() else None})
            out[key] = entry
    return out


# ------------------------------------------------------------------------------------------------------- run

def run(directory: Path, cfg: dict, write_rules: Path | None, say=print) -> dict:
    started = time.perf_counter()
    model = live_run.load_live_model(cfg)
    config = load_alert_config(live_run.project_path(cfg["alert_config"]))
    years = burden.DEV_YEARS
    events = burden.development_events(years)
    say("loading the development panels")
    seasons = load_seasons(directory, years, model.card, events, say)
    universe_cells = int(len(bt.universe_cell_ids()))

    say("step 1: interval")
    interval = {"old_bound": evaluate(seasons, "old_hi", config, label="old interval (calibrated members p10 / p90)"),
                "new_bound": evaluate(seasons, "new_hi", config, label="re-centred interval"),
                "no_uncertain_high": evaluate(seasons, "risk", config, label="no uncertain_high")}
    interval["outside_old_interval"] = outside_share(seasons)
    baseline = interval["new_bound"]

    say("step 2: ensemble agreement")
    split = agreement_split(seasons, universe_cells=universe_cells)
    agreement_choice = choose_agreement(split)

    say("step 3: rain trigger")
    quantiles = positive_quantiles()
    rain = rain_study(seasons, config, quantiles, baseline, say)
    chosen = rain["chosen"]
    minima = {int(w): m for w, m in chosen["minimum_mm"].items()} if chosen else {}
    post_rain = post_rain_cost(quantiles, minima.get(7))

    say("step 5: blind-hold limit")
    decay = retention(seasons)
    blind_choice = choose_blind_hold(decay)
    rules = pr.PostRules(agreement_choice["agreement_min"], pr.RainRule(minima) if chosen else None,
                         tuple(lv.parse_level(n) for n in chosen["gated_levels"]) if chosen else (),
                         hold_window_days=HOLD_WINDOW_DAYS, blind_hold_days=blind_choice["blind_hold_days"],
                         source="development out-of-fold panels")
    window = None
    if rules.gates:
        say("step 3b: hold window")
        window = hold_window_study(seasons, config, rules, baseline)
        if window["chosen"] is not None:
            rules = replace(rules, hold_windows={lv.parse_level(k): w for k, w in window["chosen"].items()})
    after = evaluate(seasons, "new_hi", config, rules, label="chosen post-model rules")
    after_no_release = (evaluate(seasons, "new_hi", config, rules, release=False,
                                 label="chosen rules, holds not released") if rules.gates else None)

    say("step 6: terrain diagnostic")
    frames = []
    for s in seasons:
        frames.append(terrain_rows(s, season_levels(s, "new_hi", config), model))
    terrain = terrain_summary(pd.concat(frames, ignore_index=True))

    analysis = {
        "protocol": {"period": "06-01 to 09-30 of 2007-2017 (train + validation years)", "panels": hm.display_path(directory),
                     "model": burden.BASES["oof"]["model"], "alert_config": cfg["alert_config"],
                     "universe_cells": universe_cells, "note": "chosen on development years only; test_2018, the 2023 "
                     "window, Wayanad 2024 and the live days are not read"},
        "events": {"in_season": int(len(events)), "in_panel_cells": int(sum(len(s.events) for s in seasons))},
        "interval": {k: compact(v) if isinstance(v, dict) and "own_levels" in v else v for k, v in interval.items()},
        "agreement": {"split": split, "choice": agreement_choice},
        "rain": {"positives": {k: v for k, v in quantiles.items() if k not in ("acc_7", "days_since_10mm")}, **rain,
                 "hold_window_days": rules.hold_window_days, "candidate_hold_window_days": HOLD_WINDOW_DAYS,
                 "hold_window": window, "max_relative_loss": MAX_RELATIVE_LOSS, "post_rain": post_rain},
        "blind_hold": {"retention": decay, "choice": blind_choice},
        "after": compact(after), "after_without_hold_release": None if after_no_release is None else compact(after_no_release),
        "rules": rules.to_dict(), "terrain": terrain, "seconds": time.perf_counter() - started}
    dump_json(Path(directory) / ANALYSIS_FILE, analysis)
    if write_rules:
        pr.save_rules(write_rules, rules, {"source": hm.display_path(Path(directory) / ANALYSIS_FILE),
                                          "agreement": agreement_choice, "rain_rule": chosen,
                                          "blind_hold": blind_choice,
                                          "hold_window": None if window is None else {k: window[k] for k in ("chosen", "rule")},
                                          "protocol": analysis["protocol"]})
        say(f"wrote {write_rules}")
    say(f"rules: {rules.to_dict()}")
    return analysis


def outside_share(seasons: list[Season]) -> dict:
    """How often the point lay outside the old interval (universe cell-days of the seasons) and the new one."""
    n = old_out = new_out = above = 0
    for s in seasons:
        panel, first = s.panel, s.first
        universe = panel.cells["in_universe"].to_numpy(dtype=bool)
        scored = panel.scored[universe, first:]
        risk = panel["risk"][universe, first:][scored]
        old_lo, old_hi = panel["old_lo"][universe, first:][scored], panel["old_hi"][universe, first:][scored]
        new_lo, new_hi = panel["new_lo"][universe, first:][scored], panel["new_hi"][universe, first:][scored]
        n += len(risk)
        old_out += int(((risk < old_lo) | (risk > old_hi)).sum())
        above += int((risk > old_hi).sum())
        new_out += int(((risk < new_lo) | (risk > new_hi)).sum())
    return {"cell_days": n, "outside_old": old_out, "outside_old_share": old_out / n, "above_old_hi": above,
            "outside_new": new_out}
