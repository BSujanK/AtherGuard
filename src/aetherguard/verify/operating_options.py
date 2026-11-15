"""How much detection to give up for how much less alerting: the operating-point options of v4, on development data.

    python -m aetherguard.verify.operating_options tradeoff --window jun_dec|jan_may     # Task 1
    python -m aetherguard.verify.operating_options schemes  --window jun_dec|jan_may     # Tasks 2 and 3
    python -m aetherguard.verify.operating_options report                                # Task 4 document
    python -m aetherguard.verify.operating_options heldout --option NAME                 # THE look; the lead's, once

Why. Today's levels are defined by how many development landslides they would have caught (about 90%, 75%, 50% of the
development positives at Watch, Warning and Emergency), not by how rare they are, so a large share of monsoon cell-days is
on alert. The choice of how much detection to give up for how much less alerting belongs to the user and needs the cost
ratio of a miss against a false alarm; this module puts that trade-off in numbers and builds the two tools that make a
lower burden usable (levels defined by frequency, and districts).

Data. Only the out-of-fold v4 panels of the development years (2007-2017) on every scored cell
(`live.oof_v4_full`: June-December and January-May) and the development positives of every month (train and validation
samples, in domain). Nothing here reads a held-out event except the `heldout` command, which is the one confirming look of
the option the user chooses, taken by the lead, and refuses to run twice.

Seasons: monsoon June-September, post-monsoon October-December, rest of the year January-May
(`alerts.frequency_levels.SEASONS`); regions: the model's two (Himalaya, Western Ghats).

1. `tradeoff` (point level: the risk against a threshold, no post-model rules, no hysteresis). For each level a ladder of
   frequency caps (`LADDERS`); in each region and season the threshold of a cap is the lowest risk at which at most that
   share of the scored cell-days reach it (`frequency_levels.cap_threshold`, exact, streamed over the years). At every
   step: alert cell-days, the detection of the development events cell-exact (own cell, event day) and tolerant (10 km,
   1 day) with 95% intervals that resample independent slides (events within the tolerance of each other are one slide),
   events caught per 1,000 alert cell-days, the chance floor of tolerant matching (the share of all scored cell-days of
   the stratum that have an alert within the tolerance: the detection an event placed at random would get), and the
   implied cost ratio of each step (alert cell-days saved per event lost against the step before it: the step is the
   better choice when one missed event is worth fewer false-alarm cell-days than that). Today's card thresholds are
   measured the same way beside it.
2. `schemes`: the named options (`OPTIONS`), each a cap per level and season, floored at today's thresholds. The
   thresholds are written to a NEW file per option (`frequency_levels.scheme_document`, card format per season), never
   into the frozen card. Then the whole chain the live run applies on top (raw level with `uncertain_high`, the rain cap
   and hold release of `post_rules_v3.json`, the hysteresis of `alert_config_v3.json`) on the development panels: the
   point share against the realised share (holds inflate it), detection cell-exact and tolerant.
   Districts (`serve.districts`): the district level under each candidate rule (`DISTRICT_RULES`); district-days at each
   level, the share of development events inside a district at the level on the event day, district-days per event, and
   the days per week a district would be at each level.
3. `report` renders `reports/phase8_operating_point_options.{json,md}` from the result files.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from ..alerts import frequency_levels as FL
from ..alerts import levels as lv
from ..alerts.config import load_config_file as load_alert_config
from ..config import PROJECT_ROOT, data_root
from ..hazard.jsonio import dump_json, jsonable
from ..live import backtest as bt
from ..live import burden
from ..live import hardening as H
from ..live import hardening_dev as D
from ..live import oof_v4_full as F
from ..live import post_rules_v4 as P
from ..live import postrules as pr
from ..live import run as live_run
from ..serve import districts as DI
from .matching import CELL_EXACT, Tolerance, match, rows_within

LEVELS = (lv.WATCH, lv.WARNING, lv.EMERGENCY)
LEVEL_NAMES = {1: "Watch+", 2: "Warning+", 3: "Emergency"}
TOLERANCES = {"tolerant": Tolerance(10.0, 1), "cell_exact": CELL_EXACT}
REGIONS = ("himalaya", "western_ghats")
WINDOW_SEASONS = {"jun_dec": ("monsoon", "post_monsoon"), "jan_may": ("rest",)}
# frequency caps (share of the scored cell-days of a region and season) per level; step k of each ladder is one row
LADDERS = {3: (0.08, 0.05, 0.03, 0.02, 0.01, 0.005, 0.002),
           2: (0.20, 0.15, 0.10, 0.06, 0.04, 0.02, 0.01),
           1: (0.45, 0.35, 0.25, 0.15, 0.10, 0.06, 0.03)}
BOOT = {"n": 2000, "seed": 20261115, "level": 0.95}
HIST_EDGES = np.linspace(-30.0, 0.5, 61001)          # log10 risk bins of the streamed exact quantiles
DISTRICT_RULES = {"any_cell": DI.DistrictRule(cells=1, share=None),
                  "3_cells_or_10pct": DI.DistrictRule(cells=3, share=0.10),
                  "5_cells_or_25pct": DI.DistrictRule(cells=5, share=0.25)}
RESULTS = "operating_options"                      # under data/processed/alerts/
REPORT_STEM = "phase8_operating_point_options"


def results_dir() -> Path:
    return data_root() / "processed" / "alerts" / RESULTS


# ------------------------------------------------------------------------------------------------ inputs

def development_events_all(years=burden.DEV_YEARS, directory: Path | None = None) -> pd.DataFrame:
    """In-domain positives of the train and validation samples dated in `years`, every month (cell_id, date, split)."""
    directory = Path(directory or bt.features_dir())
    parts = []
    for split in ("train", "validation"):
        table = pd.read_parquet(directory / f"{split}_samples_features.parquet",
                                columns=["cell_id", "date", "kind", "in_domain"])
        keep = (table["kind"] == "positive") & table["in_domain"].astype(bool) & table["date"].dt.year.isin(list(years))
        parts.append(table[keep][["cell_id", "date"]].assign(split=split))
    return pd.concat(parts, ignore_index=True).sort_values(["date", "cell_id"]).reset_index(drop=True)


LIGHT_FIELDS = ("risk", "new_hi", "acc_1", "acc_3", "acc_7")


def load_light(path: Path) -> H.Panel:
    """A panel with only the fields the levels need (the full panel holds about 3 times as much)."""
    with np.load(path, allow_pickle=False) as data:
        cells = pd.DataFrame({"cell_id": data["cell_id"], "region": data["region"].astype(object),
                              "in_universe": data["in_universe"]})
        days = [date.fromisoformat(str(d)) for d in data["days"]]
        return H.Panel(cells, days, int(data["n_members"]), {name: data[name] for name in LIGHT_FIELDS})


class Year:
    """One development year of one window: the light panel, the evaluation days (after the warm-up), the season of each
    evaluation day, and the de-duplicated events dated on those days in the panel's cells."""

    def __init__(self, year: int, window: str, events: pd.DataFrame, directory: Path | None = None):
        self.year, self.window = year, window
        self.panel = load_light(F.panel_path(directory or F.out_dir(), window, year))
        self.first = F.window_days(year, window)[1]
        self.days = self.panel.days[self.first:]
        self.season = FL.season_index(np.array([d.month for d in self.days]))
        self.region = self.panel.cells["region"].to_numpy(dtype=str)
        self.cell_ids = self.panel.cells["cell_id"].to_numpy(dtype=np.int64)
        e = events[events["date"].dt.year == year]
        e = e[e["cell_id"].isin(self.cell_ids)][["cell_id", "date"]].drop_duplicates()
        e = e[pd.to_datetime(e["date"]).dt.date.isin(set(self.days))]
        self.events = e.reset_index(drop=True)

    @property
    def risk(self) -> np.ndarray:
        return np.asarray(self.panel["risk"], dtype=np.float64)[:, self.first:]

    @property
    def scored(self) -> np.ndarray:
        return self.panel.scored[:, self.first:]

    def stratum_mask(self, region: str, season: str) -> tuple[np.ndarray, np.ndarray]:
        return self.region == region, self.season == FL.SEASON_NAMES.index(season)


# ------------------------------------------------------------------------------------- pure building blocks

def _bins(values: np.ndarray) -> np.ndarray:
    return np.digitize(np.log10(np.maximum(values, 1e-300)), HIST_EDGES)


def streamed_cap_thresholds_multi(load, shares_by_key: dict) -> dict:
    """{key: [cap threshold of each share]} over every value `load()` yields for the key (a fresh pass per call; `load()`
    yields {key: values}). Exactly `frequency_levels.cap_threshold` of the pooled values, in two passes: a histogram of
    log10 risk finds the bin of each cut, the second pass keeps only the values of those bins."""
    n = {k: 0 for k in shares_by_key}
    hist = {k: np.zeros(len(HIST_EDGES) + 1, dtype=np.int64) for k in shares_by_key}
    for part in load():
        for key, values in part.items():
            values = np.asarray(values, dtype=np.float64).ravel()
            values = values[np.isfinite(values)]
            n[key] += len(values)
            hist[key] += np.bincount(_bins(values), minlength=len(HIST_EDGES) + 1)
    wanted: dict = {}
    for key, shares in shares_by_key.items():
        above = np.cumsum(hist[key][::-1])[::-1]               # values in this bin or higher
        for share in shares:
            allowed = int(np.floor(share * n[key] + 1e-9))
            if allowed >= n[key]:
                continue
            rank = allowed + 1                                  # the rank (from the top) of the value that must not fire
            b = int(np.flatnonzero(above >= rank)[-1])
            higher = int(above[b + 1]) if b + 1 < len(above) else 0
            wanted.setdefault(key, {}).setdefault(b, []).append((share, rank - higher))
    kept = {key: {b: [] for b in bins} for key, bins in wanted.items()}
    if kept:
        for part in load():
            for key, values in part.items():
                if key not in kept:
                    continue
                values = np.asarray(values, dtype=np.float64).ravel()
                values = values[np.isfinite(values)]
                b = _bins(values)
                for target in kept[key]:
                    kept[key][target].append(values[b == target])
    out = {}
    for key, shares in shares_by_key.items():
        found = {}
        for b, entries in wanted.get(key, {}).items():
            inside = np.sort(np.concatenate(kept[key][b]))[::-1]
            for share, rank in entries:
                found[share] = float(np.nextafter(inside[rank - 1], np.inf))
        out[key] = [found.get(share, -np.inf) for share in shares]
    return out


def streamed_cap_thresholds(load, shares) -> list[float]:
    return streamed_cap_thresholds_multi(lambda: ({"x": v} for v in load()), {"x": tuple(shares)})["x"]


def ladder_levels(risk: np.ndarray, thresholds: np.ndarray) -> np.ndarray:
    """How many of the ascending `thresholds` each risk reaches (0 for NaN)."""
    risk = np.asarray(risk, dtype=np.float64)
    out = np.searchsorted(np.asarray(thresholds, dtype=np.float64), risk, side="right").astype(np.int8)
    out[~np.isfinite(risk)] = 0
    return out


def neighbour_index(cell_ids: np.ndarray, km: float) -> np.ndarray:
    """(cells, M) row indices of the cells within `km` of each cell (itself included), padded with its own row."""
    near = rows_within(np.asarray(cell_ids, dtype=np.int64), np.asarray(cell_ids, dtype=np.int64), km)
    width = max(len(r) for r in near)
    out = np.repeat(np.arange(len(near))[:, None], width, axis=1)
    for i, rows in enumerate(near):
        out[i, :len(rows)] = rows
    return out


def within_tolerance_max(levels: np.ndarray, nbr: np.ndarray, days: int, chunk: int = 4000) -> np.ndarray:
    """Per cell-day the highest level of any cell within the neighbourhood `nbr` and `days` days either side."""
    levels = np.asarray(levels)
    space = np.empty_like(levels)
    for start in range(0, len(levels), chunk):
        space[start:start + chunk] = levels[nbr[start:start + chunk]].max(axis=1)
    out = space.copy()
    for shift in range(1, days + 1):
        out[:, shift:] = np.maximum(out[:, shift:], space[:, :-shift])
        out[:, :-shift] = np.maximum(out[:, :-shift], space[:, shift:])
    return out


def cost_ratios(rows: list[dict]) -> list[float | None]:
    """Per step after the first: alert cell-days saved per event lost against the step before; None when the step loses
    no event (better at any cost ratio) and for the first step."""
    out: list[float | None] = [None]
    for before, after in zip(rows, rows[1:]):
        lost, saved = before["hits"] - after["hits"], before["alerts"] - after["alerts"]
        out.append(float(saved / lost) if lost > 0 else None)
    return out


def cluster_bootstrap(hits: np.ndarray, clusters: np.ndarray, boot: dict = BOOT) -> dict:
    """Detection share of each column of `hits` (events x steps) and its percentile interval when the slides
    (`clusters`, a label per event) are resampled."""
    hits = np.asarray(hits, dtype=bool)
    if hits.ndim == 1:
        hits = hits[:, None]
    if len(hits) == 0:
        return {"share": [None] * hits.shape[1], "ci": [[None, None]] * hits.shape[1]}
    labels, inverse = np.unique(np.asarray(clusters), return_inverse=True)
    sums = np.zeros((len(labels), hits.shape[1]))
    np.add.at(sums, inverse, hits)
    sizes = np.bincount(inverse, minlength=len(labels)).astype(np.float64)
    rng = np.random.default_rng(boot["seed"])
    draws = rng.integers(0, len(labels), (boot["n"], len(labels)))
    weights = np.zeros((boot["n"], len(labels)))
    for r in range(boot["n"]):
        weights[r] = np.bincount(draws[r], minlength=len(labels))
    reps = (weights @ sums) / (weights @ sizes)[:, None]
    alpha = (1.0 - boot["level"]) / 2.0
    lo, hi = np.quantile(reps, [alpha, 1.0 - alpha], axis=0)
    return {"share": [float(x) for x in hits.mean(axis=0)], "ci": [[float(a), float(b)] for a, b in zip(lo, hi)]}


def district_week(levels: np.ndarray) -> dict:
    """Over districts (rows of `levels`, districts x days): days per week at each level or above."""
    levels = np.asarray(levels)
    days = levels.shape[1]
    out = {}
    for level in LEVELS:
        per_week = (levels >= level).sum(axis=1) / days * 7.0 if days else np.zeros(len(levels))
        out[LEVEL_NAMES[level]] = {"mean_per_week": float(per_week.mean()), "median_per_week": float(np.median(per_week)),
                                   "p90_per_week": float(np.quantile(per_week, 0.9)), "max_per_week": float(per_week.max())}
    return out


def refuse_second_look(path: Path) -> None:
    if Path(path).exists():
        raise FileExistsError(f"{Path(path).name} exists: the held-out look has been taken and is not repeated")


def decide(declared: dict, look: dict) -> dict:
    """The pre-declared confirmation of an option (spec section 5), literally.

    Burden: every declared realised share (key "region|season|level") may be exceeded by at most the factor
    `burden_factor`. Detection: at every declared key ("tolerance|level"), the held-out independent slides detected are at
    least the development detection share times the slides, less `detection_margin_slides`."""
    conditions = []
    for key, expected in declared["burden"].items():
        got = look["burden"][key]
        limit = expected * declared["burden_factor"]
        conditions.append({"condition": f"burden {key}", "development": expected, "heldout": got, "limit": limit,
                           "passed": bool(got <= limit)})
    for key, share in declared["detection"].items():
        got = look["detection"][key]
        need = share * got["of"] - declared["detection_margin_slides"]
        conditions.append({"condition": f"detection {key}", "development_share": share, "heldout_hits": got["hits"],
                           "slides": got["of"], "need": need, "passed": bool(got["hits"] >= need)})
    return {"confirmed": all(c["passed"] for c in conditions), "conditions": conditions,
            "failed": [c["condition"] for c in conditions if not c["passed"]]}


# --------------------------------------------------------------------------------------- the study: inputs

def card_thresholds() -> dict[str, lv.Thresholds]:
    cfg = live_run.load_run_config()
    model = live_run.load_live_model(P.v4_cfg(cfg))
    return lv.card_region_thresholds(model.card, REGIONS)


def years_of(window: str, events: pd.DataFrame, years=burden.DEV_YEARS):
    for year in years:
        yield Year(year, window, events)


def stratum_risks(window: str, events: pd.DataFrame, years=burden.DEV_YEARS):
    """`load` for the streamed thresholds: per year {(region, season): its scored risks}."""
    def load():
        for y in years_of(window, events, years):
            risk = y.risk
            yield {(r, s): risk[np.ix_(*y.stratum_mask(r, s))] for r in REGIONS for s in WINDOW_SEASONS[window]}
    return load


def slide_labels(events: pd.DataFrame) -> np.ndarray:
    from .heldout import event_clusters
    return event_clusters(events) if len(events) else np.zeros(0, dtype=np.int64)


# ------------------------------------------------------------------------------------------- Task 1

def tradeoff(window: str, say=print, years=burden.DEV_YEARS) -> dict:
    """The point-level trade-off of `window` (module doc, step 1)."""
    started = time.perf_counter()
    events = development_events_all(years)
    card = card_thresholds()
    strata = [(r, s) for r in REGIONS for s in WINDOW_SEASONS[window]]
    say("thresholds of the ladders (two passes over the panels)")
    shares = sorted({x for ladder in LADDERS.values() for x in ladder}, reverse=True)
    caps = streamed_cap_thresholds_multi(stratum_risks(window, events, years), {k: tuple(shares) for k in strata})
    ladder_thr = {level: {k: np.array([caps[k][shares.index(x)] for x in LADDERS[level]]) for k in strata}
                  for level in LEVELS}
    nbr = None
    acc = {name: {k: {"alerts": np.zeros(len(LADDERS[1]) + 1, dtype=np.int64), "near": np.zeros(len(LADDERS[1]) + 1),
                      "cell_days": 0} for k in strata} for name in list(LEVELS) + ["card"]}
    hits = {name: {t: [] for t in TOLERANCES} for name in list(LEVELS) + ["card"]}
    ev_all = []
    for y in years_of(window, events, years):
        say(f"{window} {y.year}: {len(y.events)} events")
        if nbr is None:
            nbr = neighbour_index(y.cell_ids, TOLERANCES["tolerant"].km)
        risk, scored = y.risk, y.scored
        # step counts per ladder; the card is the ladder of its three thresholds
        arrays = {}
        for level in LEVELS:
            out = np.zeros(risk.shape, dtype=np.int8)
            for (r, s) in strata:
                rows, cols = y.stratum_mask(r, s)
                out[np.ix_(rows, cols)] = ladder_levels(risk[np.ix_(rows, cols)], ladder_thr[level][(r, s)])
            arrays[level] = out
        card_levels = np.zeros(risk.shape, dtype=np.int8)
        for r in REGIONS:
            card_levels[y.region == r] = lv.level_from_risk(risk[y.region == r], card[r])
        arrays["card"] = card_levels
        del risk
        for name, levels in arrays.items():
            near = within_tolerance_max(levels, nbr, TOLERANCES["tolerant"].days)
            for (r, s) in strata:
                block = np.ix_(*y.stratum_mask(r, s))
                lev, sc, nr = levels[block], scored[block], near[block]
                a = acc[name][(r, s)]
                a["cell_days"] += int(sc.sum())
                for k in range(1, len(a["alerts"])):
                    a["alerts"][k] += int(((lev >= k) & sc).sum())
                    a["near"][k] += float(((nr >= k) & sc).sum())
            del near
            for t, tol in TOLERANCES.items():
                m = match(levels, y.cell_ids, y.days, y.events, tol)
                if len(m.event_level) != len(y.events):
                    raise ValueError(f"{y.year}: {len(m.event_level)} matched events against {len(y.events)}")
                hits[name][t].append(m.event_level)
        e = y.events.copy()
        idx = pd.Index(y.cell_ids).get_indexer(e["cell_id"].to_numpy(dtype=np.int64))
        e["region"] = y.region[idx]
        e["season"] = [FL.season_of_month(d.month) for d in pd.to_datetime(e["date"])]
        ev_all.append(e)
        del arrays, card_levels
    ev = pd.concat(ev_all, ignore_index=True)
    labels = slide_labels(ev[["cell_id", "date"]])
    result = {"window": window, "years": list(years), "events": int(len(ev)), "slides": int(len(np.unique(labels))),
              "card_thresholds": {r: card[r].to_dict() for r in REGIONS}, "ladders": {LEVEL_NAMES[k]: v for k, v in LADDERS.items()},
              "strata": {}}
    for (r, s) in strata:
        inside = ((ev["region"] == r) & (ev["season"] == s)).to_numpy()
        entry = {"events": int(inside.sum()), "slides": int(len(np.unique(labels[inside]))) if inside.any() else 0,
                 "cell_days": int(acc["card"][(r, s)]["cell_days"])}
        for name in list(LEVELS) + ["card"]:
            a = acc[name][(r, s)]
            steps = range(1, len(LADDERS[1]) + 1) if name != "card" else LEVELS
            per_tol = {t: np.concatenate(hits[name][t])[inside] for t in TOLERANCES}
            rows = []
            for k in steps:
                row = {"step": int(k), "alert_cell_days": int(a["alerts"][k]),
                       "share": a["alerts"][k] / a["cell_days"] if a["cell_days"] else None,
                       "chance_floor_tolerant": a["near"][k] / a["cell_days"] if a["cell_days"] else None}
                if name != "card":
                    row["cap"] = LADDERS[name][k - 1]
                    row["threshold"] = float(ladder_thr[name][(r, s)][k - 1])
                else:
                    row["level"] = LEVEL_NAMES[k]
                    row["threshold"] = float(card[r].as_array()[k - 1])
                for t in TOLERANCES:
                    hit = per_tol[t] >= k
                    boot = cluster_bootstrap(hit, labels[inside])
                    row[t] = {"hits": int(hit.sum()), "detection": boot["share"][0], "ci": boot["ci"][0],
                              "per_1000_alert_cell_days": 1000.0 * hit.sum() / a["alerts"][k] if a["alerts"][k] else None}
                rows.append(row)
            if name != "card":
                for t in TOLERANCES:
                    ratios = cost_ratios([{"alerts": x["alert_cell_days"], "hits": x[t]["hits"]} for x in rows])
                    for x, ratio in zip(rows, ratios):
                        x[t]["cost_ratio"] = ratio
                entry[LEVEL_NAMES[name]] = rows
            else:
                entry["card"] = rows
        result["strata"][f"{r}|{s}"] = entry
    result["seconds"] = time.perf_counter() - started
    path = results_dir() / f"tradeoff_{window}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    dump_json(path, jsonable(result))
    say(f"wrote {path}")
    return result


# ------------------------------------------------------------------------------------------- Tasks 2 and 3

# The named options: caps per season (Watch+, Warning+, Emergency share of the scored cell-days of a region and season),
# floored at the card's thresholds. None: today's card thresholds (detection-first).
OPTIONS: dict[str, dict | None] = {
    "A_detection_first": None,
    "B_balanced": {s: (0.20, 0.06, 0.02) for s in FL.SEASON_NAMES},
    "C_rare_emergency": {s: (0.10, 0.03, 0.01) for s in FL.SEASON_NAMES},
}


def option_thresholds(window: str, events: pd.DataFrame, card: dict[str, lv.Thresholds], years=burden.DEV_YEARS
                      ) -> dict[str, dict[tuple[str, str], tuple[float, float, float]]]:
    """Per option the (watch, warning, emergency) threshold of every (region, season) of `window`: the cap thresholds
    of the pooled development risks, raised to the card's, non-decreasing across the levels."""
    strata = [(r, s) for r in REGIONS for s in WINDOW_SEASONS[window]]
    wanted = {k: tuple(sorted({x for caps in OPTIONS.values() if caps for x in caps[k[1]]}, reverse=True)) for k in strata}
    found = streamed_cap_thresholds_multi(stratum_risks(window, events, years), wanted)
    out = {}
    for name, caps in OPTIONS.items():
        out[name] = {}
        for (r, s) in strata:
            floor = card[r].as_array()
            if caps is None:
                values = floor
            else:
                values = np.maximum([found[(r, s)][wanted[(r, s)].index(x)] for x in caps[s]], floor)
            out[name][(r, s)] = tuple(float(v) for v in np.maximum.accumulate(np.asarray(values, dtype=np.float64)))
    return out


def full_row_thresholds(y: Year, thresholds: dict[tuple[str, str], tuple]) -> np.ndarray:
    """(cells, panel days, 3) thresholds; the warm-up days take the season of the first evaluation day."""
    n_days = len(y.panel.days)
    season = np.concatenate([np.full(y.first, y.season[0] if len(y.season) else 0), y.season]).astype(int)
    out = np.full((len(y.cell_ids), n_days, 3), np.nan)
    for (r, s), values in thresholds.items():
        cols = season == FL.SEASON_NAMES.index(s)
        out[np.ix_(y.region == r, cols)] = values
    if np.isnan(out).any():
        raise ValueError(f"{y.year}: some cell-days have no threshold")
    return out


def chain_levels(y: Year, thresholds: dict, card: dict, config, rules) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(point, raw, published levels) of the evaluation days: the point level is the risk against the thresholds, the raw
    level adds `uncertain_high` (Watch where the upper bound reaches it), the published level adds the rain cap and hold
    release of `rules` and the hysteresis of `config`."""
    panel = y.panel
    rows = full_row_thresholds(y, thresholds)
    season = D.Season(y.year, panel, y.first, y.events, {r: card[r] for r in REGIONS})
    raw = lv.raw_level(panel["risk"], panel["new_hi"], rows)[0]
    published = D.levels_from_raw(season, raw, config, rules, row_thresholds=rows)
    point = lv.level_from_risk(panel["risk"], rows)
    return point[:, y.first:], raw[:, y.first:], published[:, y.first:]


def district_index(cell_ids: np.ndarray, region: np.ndarray) -> tuple[np.ndarray, pd.DataFrame]:
    """(district index per cell, -1 for none; the districts with id, name, country, region and cell count). A district's
    region is the region of most of its cells."""
    table = pd.read_parquet(DI.out_dir() / "cell_districts.parquet")
    frame = pd.DataFrame({"cell_id": cell_ids, "region": region}).merge(table, on="cell_id", how="left")
    ids = frame["district_id"].astype(object)
    known = sorted({x for x in ids if isinstance(x, str)})
    index = pd.Index(known).get_indexer(ids.where(ids.notna(), "")).astype(np.int64)
    sub = frame[index >= 0].assign(index=index[index >= 0])
    info = sub.groupby("index").agg(district_id=("district_id", "first"), district=("district", "first"),
                                    country=("country", "first"), cells=("cell_id", "size"),
                                    region=("region", lambda x: x.value_counts().index[0])).reset_index(drop=True)
    return index, info


def schemes(window: str, say=print, years=burden.DEV_YEARS) -> dict:
    """Tasks 2 and 3 on `window` (module doc, step 2); writes schemes_<window>.json and the option documents."""
    started = time.perf_counter()
    cfg = live_run.load_run_config()
    config = load_alert_config(live_run.project_path(cfg["alert_config"]))
    rules = pr.load_rules(live_run.project_path(cfg["post_rules"]))
    events = development_events_all(years)
    card = card_thresholds()
    seasons = WINDOW_SEASONS[window]
    strata = [(r, s) for r in REGIONS for s in seasons]
    say("option thresholds (two passes over the panels)")
    thresholds = option_thresholds(window, events, card, years)
    names = list(OPTIONS)
    nl = len(LEVELS) + 1
    cell = {n: {k: {"cell_days": 0, "point": np.zeros(nl, np.int64), "raw": np.zeros(nl, np.int64),
                    "published": np.zeros(nl, np.int64)} for k in strata} for n in names}
    hits = {n: {t: [] for t in TOLERANCES} for n in names}
    point_hits = {n: [] for n in names}
    dist_hits = {n: {rule: {"same_day": [], "within_1_day": []} for rule in DISTRICT_RULES} for n in names}
    index = info = None
    dist_days = None
    season_days = np.zeros(len(FL.SEASON_NAMES), np.int64)
    ev_all = []
    for y in years_of(window, events, years):
        say(f"{window} {y.year}: {len(y.events)} events")
        if index is None:
            index, info = district_index(y.cell_ids, y.region)
            dist_days = {n: {rule: np.zeros((len(info), len(FL.SEASON_NAMES), nl), np.int64) for rule in DISTRICT_RULES}
                         for n in names}
        scored = y.scored
        for s_i in range(len(FL.SEASON_NAMES)):
            season_days[s_i] += int((y.season == s_i).sum())
        ev_rows = pd.Index(y.cell_ids).get_indexer(y.events["cell_id"].to_numpy(dtype=np.int64))
        ev_cols = pd.Index(pd.to_datetime(y.days)).get_indexer(pd.to_datetime(y.events["date"]))
        for name in names:
            point, raw, published = chain_levels(y, thresholds[name], card, config, rules)
            for (r, s) in strata:
                block = np.ix_(*y.stratum_mask(r, s))
                sc = scored[block]
                c = cell[name][(r, s)]
                c["cell_days"] += int(sc.sum())
                for level in LEVELS:
                    c["point"][level] += int(((point[block] >= level) & sc).sum())
                    c["raw"][level] += int(((raw[block] >= level) & sc).sum())
                    c["published"][level] += int(((published[block] >= level) & sc).sum())
            for t, tol in TOLERANCES.items():
                m = match(published, y.cell_ids, y.days, y.events, tol)
                if len(m.event_level) != len(y.events):
                    raise ValueError(f"{y.year}: {len(m.event_level)} matched events against {len(y.events)}")
                hits[name][t].append(m.event_level)
            point_hits[name].append(point[ev_rows, ev_cols])
            for rule_name, rule in DISTRICT_RULES.items():
                dl = DI.district_levels(published, scored, index, len(info), rule)
                for s_i in range(len(FL.SEASON_NAMES)):
                    cols = y.season == s_i
                    if cols.any():
                        for level in LEVELS:
                            dist_days[name][rule_name][:, s_i, level] += (dl[:, cols] >= level).sum(axis=1)
                d_ev = index[ev_rows]
                same = np.where(d_ev >= 0, dl[np.maximum(d_ev, 0), ev_cols], 0)
                near = same.copy()
                for shift in (-1, 1):
                    cols = np.clip(ev_cols + shift, 0, dl.shape[1] - 1)
                    near = np.maximum(near, np.where(d_ev >= 0, dl[np.maximum(d_ev, 0), cols], 0))
                dist_hits[name][rule_name]["same_day"].append(same)
                dist_hits[name][rule_name]["within_1_day"].append(near)
                del dl
            del point, raw, published
        e = y.events.copy()
        e["region"] = y.region[ev_rows]
        e["season"] = [FL.season_of_month(d.month) for d in pd.to_datetime(e["date"])]
        e["in_district"] = index[ev_rows] >= 0
        ev_all.append(e)
    ev = pd.concat(ev_all, ignore_index=True)
    labels = slide_labels(ev[["cell_id", "date"]])
    result = {"window": window, "years": list(years), "events": int(len(ev)),
              "events_without_district": int((~ev["in_district"]).sum()),
              "alert_config": cfg["alert_config"], "post_rules": cfg["post_rules"],
              "options": {n: OPTIONS[n] for n in names},
              "thresholds": {n: {f"{r}|{s}": v for (r, s), v in thresholds[n].items()} for n in names},
              "district_rules": {k: v.to_dict() for k, v in DISTRICT_RULES.items()},
              "districts": {"count": int(len(info)), "by_region": info["region"].value_counts().to_dict(),
                            "cells_median": float(info["cells"].median())},
              "season_days": {FL.SEASON_NAMES[i]: int(season_days[i]) for i in range(len(FL.SEASON_NAMES)) if season_days[i]},
              "results": {}}
    for name in names:
        per_tol = {t: np.concatenate(hits[name][t]) for t in TOLERANCES}
        point_all = np.concatenate(point_hits[name])
        out = {}
        for (r, s) in strata:
            inside = ((ev["region"] == r) & (ev["season"] == s)).to_numpy()
            c = cell[name][(r, s)]
            entry = {"events": int(inside.sum()), "cell_days": c["cell_days"]}
            region_rows = (info["region"] == r).to_numpy()
            s_i = FL.SEASON_NAMES.index(s)
            for level in LEVELS:
                row = {"point_share": c["point"][level] / c["cell_days"], "raw_share": c["raw"][level] / c["cell_days"],
                       "published_share": c["published"][level] / c["cell_days"],
                       "published_cell_days": int(c["published"][level]),
                       "point_cell_exact_hits": int((point_all[inside] >= level).sum())}
                row["hold_inflation"] = row["published_share"] / row["point_share"] if row["point_share"] else None
                for t in TOLERANCES:
                    hit = per_tol[t][inside] >= level
                    boot = cluster_bootstrap(hit, labels[inside])
                    row[t] = {"hits": int(hit.sum()), "detection": boot["share"][0], "ci": boot["ci"][0],
                              "cell_days_per_event": c["published"][level] / hit.sum() if hit.sum() else None}
                districts = {}
                for rule_name in DISTRICT_RULES:
                    days = dist_days[name][rule_name][region_rows, s_i, level]
                    hit_same = np.concatenate(dist_hits[name][rule_name]["same_day"])[inside] >= level
                    hit_near = np.concatenate(dist_hits[name][rule_name]["within_1_day"])[inside] >= level
                    per_week = days / season_days[s_i] * 7.0
                    districts[rule_name] = {
                        "district_days": int(days.sum()), "districts": int(region_rows.sum()),
                        "share_of_district_days": float(days.sum() / (region_rows.sum() * season_days[s_i])),
                        "events_in_alerted_district": int(hit_same.sum()),
                        "events_in_alerted_district_within_1_day": int(hit_near.sum()),
                        "detection_same_day": cluster_bootstrap(hit_same, labels[inside])["share"][0],
                        "detection_same_day_ci": cluster_bootstrap(hit_same, labels[inside])["ci"][0],
                        "district_days_per_event": float(days.sum() / hit_same.sum()) if hit_same.sum() else None,
                        "days_per_week": {"mean": float(per_week.mean()), "median": float(np.median(per_week)),
                                          "p90": float(np.quantile(per_week, 0.9)), "max": float(per_week.max())}}
                row["districts"] = districts
                entry[LEVEL_NAMES[level]] = row
            out[f"{r}|{s}"] = entry
        result["results"][name] = out
    result["seconds"] = time.perf_counter() - started
    directory = results_dir()
    directory.mkdir(parents=True, exist_ok=True)
    dump_json(directory / f"schemes_{window}.json", jsonable(result))
    for name in names:
        write_document(name, window, thresholds[name], result["results"][name])
    say(f"wrote {directory / f'schemes_{window}.json'}")
    return result


def document_path(name: str) -> Path:
    return results_dir() / f"levels_{name}.json"


def write_document(name: str, window: str, thresholds: dict, measured: dict) -> dict:
    """The option's level document (card format per season): the seasons of `window` replace those already written by
    the other window."""
    caps = OPTIONS[name] or {s: (1.0, 1.0, 1.0) for s in FL.SEASON_NAMES}
    shares = {(r, s): tuple(measured[f"{r}|{s}"][LEVEL_NAMES[L]]["point_share"] for L in LEVELS) for (r, s) in thresholds}
    pooled = {s: tuple(np.max([thresholds[(r, s2)] for (r, s2) in thresholds if s2 == s], axis=0))
              for s in WINDOW_SEASONS[window]}
    new = FL.scheme_document(name, thresholds, pooled, {s: caps[s] for s in WINDOW_SEASONS[window]},
                             floor="card (model_v4_live alert_levels risk_by_region)",
                             provenance={"panels": f"data/processed/alerts/{F.OUT_DIR}", "years": "2007-2017 out of fold",
                                         "pooled_risk": "the higher of the two regions' thresholds",
                                         "module": "aetherguard.verify.operating_options"},
                             shares=shares)
    path = document_path(name)
    if path.is_file():
        old = json.loads(path.read_text(encoding="utf-8"))
        for season, block in old["seasons"].items():
            if season not in new["seasons"]:
                new["seasons"][season] = block
    new["seasons"] = {s: new["seasons"][s] for s in FL.SEASON_NAMES if s in new["seasons"]}
    if OPTIONS[name] is None:
        new["status"] = "today's card thresholds, written in the same format for comparison; the live run reads the card"
    dump_json(path, jsonable(new))
    return new


# ------------------------------------------------------------------------------------------- CLI

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m aetherguard.verify.operating_options", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    cmd = sub.add_parser("tradeoff", help="Task 1 on one window")
    cmd.add_argument("--window", choices=sorted(WINDOW_SEASONS), required=True)
    cmd = sub.add_parser("schemes", help="Tasks 2 and 3 on one window")
    cmd.add_argument("--window", choices=sorted(WINDOW_SEASONS), required=True)
    args = parser.parse_args(argv)
    say = lambda m: print(m, flush=True)  # noqa: E731
    if args.command == "tradeoff":
        tradeoff(args.window, say)
    elif args.command == "schemes":
        schemes(args.window, say)
    return 0


if __name__ == "__main__":
    sys.exit(main())
