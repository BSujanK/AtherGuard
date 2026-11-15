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

    def __init__(self, year: int, window: str, events: pd.DataFrame, directory: Path | None = None,
                 panel: H.Panel | None = None, first: int | None = None):
        self.year, self.window = year, window
        self.panel = panel if panel is not None else load_light(F.panel_path(directory or F.out_dir(), window, year))
        self.first = F.window_days(year, window)[1] if first is None else first
        self.days = self.panel.days[self.first:]
        self.season = FL.season_index(np.array([d.month for d in self.days]))
        self.region = self.panel.cells["region"].to_numpy(dtype=str)
        self.cell_ids = self.panel.cells["cell_id"].to_numpy(dtype=np.int64)
        e = events[events["date"].dt.year == year]
        e = e[e["cell_id"].isin(self.cell_ids)][["cell_id", "date"]].drop_duplicates()
        e = e[pd.to_datetime(e["date"]).dt.date.isin(set(self.days))]
        self.events = e.reset_index(drop=True)

    @classmethod
    def from_panel(cls, year: int, panel: H.Panel, first: int) -> "Year":
        """A year of another panel (the held-out seasons), without events."""
        none = pd.DataFrame({"cell_id": np.zeros(0, dtype=np.int64), "date": pd.to_datetime([])})
        return cls(year, "jun_dec", none, panel=panel, first=first)

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
    `burden_factor`. Detection: at every declared key ("tolerance|level", holding the development `share` and the
    allowed shortfall `margin_slides`), the held-out independent slides detected are at least share x slides - margin."""
    conditions = []
    for key, expected in declared["burden"].items():
        got = look["burden"][key]
        limit = expected * declared["burden_factor"]
        conditions.append({"condition": f"burden {key}", "development": expected, "heldout": got, "limit": limit,
                           "passed": bool(got <= limit)})
    for key, entry in declared["detection"].items():
        got = look["detection"][key]
        need = entry["share"] * got["of"] - entry["margin_slides"]
        conditions.append({"condition": f"detection {key}", "development_share": entry["share"], "heldout_hits": got["hits"],
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


# ------------------------------------------------------------------------------------- the one held-out look

HELDOUT_SLIDES = 87               # independent slides of the W1 assembly, 2018-2025 (reports/phase7_heldout_expanded)
BURDEN_FACTOR = 1.5               # the held-out published share may exceed the development one by at most this factor
MARGIN_SD = 2.0                   # detection may fall short of development by at most this many binomial SDs at 87 slides


def declared_criterion(name: str, schemes_by_window: dict) -> dict:
    """The pre-declared confirmation of option `name` (spec section 5), from the development results only: the
    published share per region, season (monsoon, post-monsoon) and level, and the pooled June-December detection per
    tolerance and level with its allowed shortfall."""
    measured = schemes_by_window["jun_dec"]["results"][name]
    burden_keys, detection = {}, {}
    for key, entry in measured.items():
        for level in LEVELS:
            burden_keys[f"{key}|{level}"] = entry[LEVEL_NAMES[level]]["published_share"]
    for t in TOLERANCES:
        for level in LEVELS:
            hits = sum(e[LEVEL_NAMES[level]][t]["hits"] for e in measured.values())
            events = sum(e["events"] for e in measured.values())
            share = hits / events
            margin = MARGIN_SD * float(np.sqrt(HELDOUT_SLIDES * share * (1.0 - share)))
            detection[f"{t}|{level}"] = {"share": share, "margin_slides": margin}
    return {"option": name, "burden": burden_keys, "burden_factor": BURDEN_FACTOR, "detection": detection,
            "slides": HELDOUT_SLIDES,
            "rule": f"confirmed when every held-out published share (region x season x level, June-December 2018-2025) "
                    f"is at most {BURDEN_FACTOR} x its development value, and at every tolerance and level the "
                    f"independent slides detected are at least the development detection share x the slides less "
                    f"{MARGIN_SD} binomial standard deviations"}


def heldout_path(name: str) -> Path:
    return results_dir() / f"heldout_{name}.json"


def document_thresholds(document: dict) -> dict[tuple[str, str], tuple[float, float, float]]:
    out = {}
    for season, block in document["seasons"].items():
        for r in REGIONS:
            card = {"alert_levels": block["alert_levels"]}
            out[(r, season)] = tuple(float(v) for v in lv.card_region_thresholds(card, [r])[r].as_array())
    return out


def heldout_look(name: str, say=print) -> dict:
    """THE look for option `name` (the lead's, once, after the user's choice): its levels on the v4 held-out season
    panels, the realised published shares and the independent-slide detection, decided by the declared criterion of
    the committed report. Refuses when any held-out result of this study exists."""
    from . import heldout
    from .scores import grouped_pod
    existing = sorted(results_dir().glob("heldout_*.json"))
    if existing:
        raise FileExistsError(f"{existing[0].name} exists: this study's one held-out look has been taken")
    report = json.loads((PROJECT_ROOT / "reports" / f"{REPORT_STEM}.json").read_text(encoding="utf-8"))
    declared = report["options"][name]["heldout_criterion"]
    document = json.loads(document_path(name).read_text(encoding="utf-8"))
    thresholds = {k: v for k, v in document_thresholds(document).items() if k[1] in WINDOW_SEASONS["jun_dec"]}
    cfg = live_run.load_run_config()
    config = load_alert_config(live_run.project_path(cfg["alert_config"]))
    rules = pr.load_rules(live_run.project_path(cfg["post_rules"]))
    card = card_thresholds()
    reference = H.load_panel(H.alerts_dir(H.HELDOUT_DIR) / H.HELDOUT_FILE).cells["cell_id"].to_numpy()
    days, scored, published = [], [], []
    burden_counts: dict = {}
    for year in bt.SEASON_YEARS:
        say(f"held-out season {year}")
        panel = load_light(H.alerts_dir(P.V4_SEASONS) / f"season_{year}_v4.npz")
        heldout.check_cell_order(panel.cells["cell_id"].to_numpy(), reference, f"v4 season {year}")
        y = Year.from_panel(year, panel, panel.days.index(date(year, 6, 1)))
        _, _, levels = chain_levels(y, thresholds, card, config, rules)
        for (r, s) in thresholds:
            block = np.ix_(*y.stratum_mask(r, s))
            sc = y.scored[block]
            counts = burden_counts.setdefault((r, s), np.zeros(len(LEVELS) + 1, np.int64))
            counts[0] += int(sc.sum())
            for level in LEVELS:
                counts[level] += int(((levels[block] >= level) & sc).sum())
        days += y.days
        scored.append(y.scored)
        published.append(levels)
        del panel, y
    levels = np.concatenate(published, axis=1)
    events = heldout.load_event_table(cfg)
    events = events[pd.to_datetime(events["date"]).dt.year.isin(bt.SEASON_YEARS)]
    kept, outside = heldout.events_on_days(events, days)
    look = {"burden": {f"{r}|{s}|{level}": counts[level] / counts[0] for (r, s), counts in burden_counts.items()
                       for level in LEVELS}, "detection": {}}
    for t, tol in TOLERANCES.items():
        m = match(levels, reference, days, kept, tol)
        labels = heldout.event_clusters(m.events)
        for level in LEVELS:
            g = grouped_pod(m.event_level, labels, level, BOOT)
            look["detection"][f"{t}|{level}"] = {"hits": g["group_hits"], "of": g["groups"], "ci": g["group_pod_ci"]}
    result = {"option": name, "declared": declared, "look": look, "events_outside_panel_days": int(outside),
              "decision": decide(declared, look)}
    text = json.dumps(jsonable(result), indent=2, allow_nan=False)
    with open(heldout_path(name), "x", encoding="utf-8") as handle:
        handle.write(text + "\n")
    say(f"{name}: {'CONFIRMED' if result['decision']['confirmed'] else 'NOT confirmed'} {result['decision']['failed']}")
    return result


# ------------------------------------------------------------------------------------------- Task 4: report

OPTION_TEXT = {
    "A_detection_first": "Keep today's levels (detection first): the model card's thresholds, which caught about 90%, 75% "
                         "and 50% of the development positives at Watch, Warning and Emergency.",
    "B_balanced": "Balanced: in every region and season, Watch+ on at most 20%, Warning+ on at most 6% and Emergency on "
                  "at most 2% of the cell-days (point level), never below today's thresholds.",
    "C_rare_emergency": "Rare Emergency: Watch+ on at most 10%, Warning+ on at most 3% and Emergency on at most 1% of "
                        "the cell-days (point level), never below today's thresholds.",
}
DISTRICT_KEEP = 0.90              # a coarser district rule must keep this share of the events "any cell" covers


def _read(name: str) -> dict | None:
    path = results_dir() / name
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def choose_district_rule(measured: dict) -> dict:
    """Pre-declared (spec section 4): the rule with the fewest Warning+ district-days among those that keep at least
    DISTRICT_KEEP of the events the any-cell rule puts inside an alerted district, at every level, pooled over the
    strata given; ties and no candidate go to `any_cell`."""
    totals = {}
    for rule in DISTRICT_RULES:
        totals[rule] = {L: {"days": sum(e[LEVEL_NAMES[L]]["districts"][rule]["district_days"] for e in measured.values()),
                            "events": sum(e[LEVEL_NAMES[L]]["districts"][rule]["events_in_alerted_district"]
                                          for e in measured.values())} for L in LEVELS}
    base = totals["any_cell"]
    keeping = [r for r in DISTRICT_RULES
               if all(totals[r][L]["events"] >= DISTRICT_KEEP * base[L]["events"] for L in LEVELS)]
    chosen = min(keeping, key=lambda r: (totals[r][lv.WARNING]["days"], r != "any_cell")) if keeping else "any_cell"
    return {"chosen": chosen, "totals": {r: {LEVEL_NAMES[L]: v for L, v in t.items()} for r, t in totals.items()},
            "keep": DISTRICT_KEEP}


def option_steps(options: dict) -> dict:
    """Between consecutive options (A -> B -> C), per stratum and level: the published alert cell-days saved, the
    events lost (tolerant and cell-exact) and the implied cost ratio (cell-days saved per event lost; None when no event
    is lost)."""
    names = list(options)
    out = {}
    for before, after in zip(names, names[1:]):
        step = {}
        for key, e in options[before]["measured"].items():
            f = options[after]["measured"][key]
            rows = {}
            for L in LEVELS:
                x, z = e[LEVEL_NAMES[L]], f[LEVEL_NAMES[L]]
                saved = x["published_cell_days"] - z["published_cell_days"]
                row = {"saved_cell_days": int(saved),
                       "saved_share": saved / x["published_cell_days"] if x["published_cell_days"] else None}
                for t in TOLERANCES:
                    lost = x[t]["hits"] - z[t]["hits"]
                    row[t] = {"lost": int(lost), "cost_ratio": float(saved / lost) if lost > 0 else None}
                rows[LEVEL_NAMES[L]] = row
            step[key] = rows
        out[f"{before}->{after}"] = step
    return out


def build_report() -> dict:
    tradeoff_ = {w: _read(f"tradeoff_{w}.json") for w in WINDOW_SEASONS}
    schemes_ = {w: _read(f"schemes_{w}.json") for w in WINDOW_SEASONS}
    if schemes_["jun_dec"] is None or tradeoff_["jun_dec"] is None:
        raise FileNotFoundError("run `tradeoff --window jun_dec` and `schemes --window jun_dec` first")
    options = {}
    for name in OPTIONS:
        measured = {k: v for w in WINDOW_SEASONS if schemes_[w] for k, v in schemes_[w]["results"][name].items()}
        rule = choose_district_rule(measured)
        options[name] = {"text": OPTION_TEXT[name], "caps": OPTIONS[name],
                         "thresholds": {k: v for w in WINDOW_SEASONS if schemes_[w]
                                        for k, v in schemes_[w]["thresholds"][name].items()},
                         "levels_file": f"data/processed/alerts/{RESULTS}/levels_{name}.json",
                         "measured": measured, "district_rule": rule,
                         "heldout_criterion": declared_criterion(name, schemes_),
                         "heldout_command": f"python -m aetherguard.verify.operating_options heldout --option {name}"}
    return {"created_utc": pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ"),
            "windows_present": [w for w in WINDOW_SEASONS if schemes_[w] and tradeoff_[w]],
            "panels": f"data/processed/alerts/{F.OUT_DIR}", "years": "2007-2017 (development, out of fold)",
            "events": {w: (tradeoff_[w] or {}).get("events") for w in WINDOW_SEASONS},
            "slides": {w: (tradeoff_[w] or {}).get("slides") for w in WINDOW_SEASONS},
            "tradeoff": {w: t for w, t in tradeoff_.items() if t},
            "schemes_meta": {w: {k: v for k, v in s.items() if k != "results"} for w, s in schemes_.items() if s},
            "options": options, "option_steps": option_steps(options),
            "district_rules": {k: v.to_dict() for k, v in DISTRICT_RULES.items()},
            "boot": BOOT, "caveats": CAVEATS_OPTIONS}


CAVEATS_OPTIONS = [
    "Development data only (2007-2017, out of fold, every scored cell). No held-out number is in this report; each "
    "option's realised detection and burden on 2018-2025 is confirmed by one look, after the choice.",
    "The catalogues miss most landslides and record them where people and roads are, so an alert far from a recorded "
    "event is not necessarily a false alarm, and detection counts what was recorded.",
    "Tolerant matching (10 km, 1 day) has a high chance floor at high burden: the floor column is the detection an "
    "event placed at random would get. Read tolerant detection against it; the cell-exact rows do not reward scattered "
    "alerts.",
    "The calibrated risk takes few distinct values in its upper tail (the monotone calibrator is a step function), so a "
    "threshold can only sit between two steps; a cap is met as 'at most', and the realised share is often well below it.",
    "The caps are met on the point level. The published level also raises to Watch where the ensemble's upper bound "
    "reaches it (uncertain_high) and holds levels (hysteresis, rain-capped hold release), which raises the realised "
    "share; the published columns measure it on the same panels.",
    "The live run outside June-September has published far more alerts than these panels show "
    "(reports/phase8_season_validity.md); thresholds set on development data do not remove that difference.",
    "January-May panels start on 1 January without a warm-up (no hysteresis state carried over New Year).",
    "District numbers use geoBoundaries district polygons (India ADM2, Nepal ADM2 = the 75 districts of 2006, Bhutan "
    "ADM1 = the 20 dzongkhags); a few cells at coasts and borders take the nearest district of their country within 5 km.",
    "A cost ratio counts every alert cell-day as a false alarm and every catalogue event as the only landslide; the "
    "catalogues hold a small fraction of the slides that happened, so the real number of misses behind each lost event "
    "is larger than one.",
    "The blind-escalation rule of the live run (raise to Watch when the rain sources disagree and confidence is not High) "
    "needs the live IMD comparison and is not in the development chain.",
]


def _p(x, digits: int = 1) -> str:
    return "" if x is None else f"{100.0 * x:.{digits}f}%"


def _n(x) -> str:
    return "" if x is None else f"{x:,.0f}"


def _ci(ci) -> str:
    return "" if not ci or ci[0] is None else f"[{100.0 * ci[0]:.0f}, {100.0 * ci[1]:.0f}]"


def _det(entry: dict, events: int) -> str:
    return f"{entry['hits']} / {events} ({_p(entry['detection'], 0)} {_ci(entry['ci'])})"


def _ratio(x) -> str:
    return "any" if x is None else f"{x:,.0f}"


STRATUM_TEXT = {"himalaya": "Himalaya", "western_ghats": "Western Ghats", "monsoon": "monsoon (Jun-Sep)",
                "post_monsoon": "post-monsoon (Oct-Dec)", "rest": "rest of year (Jan-May)"}


def _stratum(key: str) -> str:
    r, s = key.split("|")
    return f"{STRATUM_TEXT[r]}, {STRATUM_TEXT[s]}"


def recommendation(result: dict) -> list[str]:
    """The recommendation, with its numbers read from the result."""
    opts, steps = result["options"], result["option_steps"]
    key = "himalaya|monsoon"
    a, b, c = (opts[n]["measured"][key] for n in ("A_detection_first", "B_balanced", "C_rare_emergency"))
    ab, bc = steps["A_detection_first->B_balanced"][key], steps["B_balanced->C_rare_emergency"][key]
    em, wa = "Emergency", "Warning+"
    floor_b = next(x for x in result["tradeoff"]["jun_dec"]["strata"][key]["Emergency"] if x["cap"] == 0.02)
    rule_b = opts["B_balanced"]["district_rule"]["chosen"]
    db = b[em]["districts"][rule_b]["days_per_week"]
    da = a[em]["districts"][opts["A_detection_first"]["district_rule"]["chosen"]]["days_per_week"]
    return [
        "## Recommendation",
        "",
        "Take **B_balanced** to its one confirming held-out look, and keep A (today) live until that look has passed and "
        "the wiring has been reviewed.",
        "",
        f"- Most alerts are raised in the Himalayan monsoon. There B cuts the published Emergency cell-days by "
        f"{_p(ab[em]['saved_share'], 0)} (share {_p(a[em]['published_share'], 2)} -> {_p(b[em]['published_share'], 2)}) and "
        f"Warning+ by {_p(ab[wa]['saved_share'], 0)} ({_p(a[wa]['published_share'], 1)} -> {_p(b[wa]['published_share'], 1)}). "
        f"Emergency still catches {_p(b[em]['tolerant']['detection'], 0)} of the development events within 10 km and a day "
        f"({_p(b[em]['cell_exact']['detection'], 0)} on the exact cell), against {_p(a[em]['tolerant']['detection'], 0)} "
        f"({_p(a[em]['cell_exact']['detection'], 0)}) today. At B's 2% point cap the tolerant chance floor is "
        f"{_p(floor_b['chance_floor_tolerant'], 0)}, so this detection is far above what scattered alerts would get.",
        f"- The price: A -> B is worth it when one missed Emergency event is worth fewer than "
        f"{_ratio(ab[em]['tolerant']['cost_ratio'])} false-alarm Emergency cell-days (tolerant; "
        f"{_ratio(ab[em]['cell_exact']['cost_ratio'])} on the exact cell). Going on to C is worth it only below "
        f"{_ratio(bc[em]['tolerant']['cost_ratio'])} ({_ratio(bc[em]['cell_exact']['cost_ratio'])}). C leaves Emergency "
        f"catching {_p(c[em]['tolerant']['detection'], 0)} tolerant and {_p(c[em]['cell_exact']['detection'], 0)} exact. "
        "That is about one landslide in three on its own cell, too few for a level whose name promises the most danger. "
        "The ratio is the user's to set (roadmap section 5). If a missed landslide is worth more than the A -> B ratio, "
        "keep A.",
        f"- At the district level the burden stays high under every option. Under B the median Himalayan district would be "
        f"at Emergency {db['median']:.1f} days a week in the monsoon, and the busiest tenth {db['p90']:.1f} days (today: "
        f"{da['median']:.1f} and {da['p90']:.1f}). A district holds many cells, so one cell at a level is enough on most "
        "days. Before districts are used for messages, a district-level frequency cap is needed (a share-of-cells rule "
        "chosen the way the cell caps were). That is the next piece of work, and it does not depend on this choice.",
        "- Outside the monsoon the caps change little: on development data today's levels already fire below them. The "
        "high live burden outside June-September (phase8_season_validity) is not explained by the thresholds. It needs "
        "its own study and stays flagged outside the validated season.",
        "- Any option changes published levels, so wiring it is a model change: it needs the look, a reviewed wiring "
        "step and the user's yes.",
    ]


def markdown_report(result: dict) -> str:
    out = []
    opts = result["options"]
    a = opts["A_detection_first"]["measured"]
    out.append("# Operating point options: how much detection for how much less alerting (phase 8, development only)")
    out.append("")
    out.append("This document puts one decision in front of the user: how often AetherGuard may raise each alert level. "
               "Nothing here changes the live run, and no held-out number is in it. Every number comes from "
               f"`data/processed/alerts/{RESULTS}/` (development years 2007-2017, out of fold, every one of the 36,792 "
               "scored cells).")
    out.append("")
    if "jan_may" not in result["windows_present"]:
        out.append("**Incomplete:** the January-May panels are not all scored yet, so the rest-of-year rows are missing.")
        out.append("")
    out.append("## The three options at a glance (published levels, the whole live chain)")
    out.append("")
    out.append("Share of cell-days at each level or above, and how many development events (landslide cell-days in the "
               "catalogues) the level caught: cell-exact = an alert on the event's own cell and day; tolerant = an alert "
               "within 10 km and 1 day.")
    for key in a:
        out.append("")
        out.append(f"**{_stratum(key)}** ({a[key]['events']} development events)")
        out.append("")
        out.append("| option | Watch+ share | Warning+ share | Emergency share | Warning+ caught (exact / tolerant) | "
                   "Emergency caught (exact / tolerant) |")
        out.append("|---|---|---|---|---|---|")
        for name, o in opts.items():
            e = o["measured"][key]
            w, x = e["Warning+"], e["Emergency"]
            out.append(f"| {name} | {_p(e['Watch+']['published_share'])} | {_p(w['published_share'])} | "
                       f"{_p(x['published_share'], 2)} | {_p(w['cell_exact']['detection'], 0)} / "
                       f"{_p(w['tolerant']['detection'], 0)} | {_p(x['cell_exact']['detection'], 0)} / "
                       f"{_p(x['tolerant']['detection'], 0)} |")
    out.append("")
    out.append("## The price of each step, as a cost ratio")
    out.append("")
    out.append("Moving from one option to the next saves published alert cell-days and loses some development events. "
               "The cost ratio is cell-days saved per event lost: the step is worth taking when one missed landslide is "
               "worth FEWER false-alarm cell-days than this number ('any': no event is lost).")
    out.append("")
    out.append("| step | region and season | level | alert cell-days saved | events lost (exact / tolerant) | "
               "cost ratio (exact / tolerant) |")
    out.append("|---|---|---|---|---|---|")
    for step, strata in result["option_steps"].items():
        for key, rows in strata.items():
            for level_name, row in rows.items():
                out.append(f"| {step} | {_stratum(key)} | {level_name} | {_n(row['saved_cell_days'])} "
                           f"({_p(row['saved_share'], 0)}) | {row['cell_exact']['lost']} / {row['tolerant']['lost']} | "
                           f"{_ratio(row['cell_exact']['cost_ratio'])} / {_ratio(row['tolerant']['cost_ratio'])} |")
    out.append("")
    out += recommendation(result)
    out.append("")
    out.append("## What a district officer would receive")
    out.append("")
    out.append("A district is at a level on a day under the district rule chosen for the option (section 4 of the "
               "spec: the rule with the fewest Warning+ district-days that keeps at least "
               f"{DISTRICT_KEEP:.0%} of the events the any-cell rule covers). Days per week at each level or above, for "
               "the median district and the busiest tenth of districts (90th percentile):")
    out.append("")
    out.append("| option | district rule | region and season | Watch+ days/week (median, p90) | Warning+ | Emergency |")
    out.append("|---|---|---|---|---|---|")
    for name, o in opts.items():
        rule = o["district_rule"]["chosen"]
        for key, e in o["measured"].items():
            cells = []
            for L in LEVELS:
                d = e[LEVEL_NAMES[L]]["districts"][rule]["days_per_week"]
                cells.append(f"{d['median']:.1f}, {d['p90']:.1f}")
            out.append(f"| {name} | {DISTRICT_RULES[rule].name} | {_stratum(key)} | " + " | ".join(cells) + " |")
    out.append("")
    out.append("## The options in full")
    for name, o in opts.items():
        out.append("")
        out.append(f"### {name}")
        out.append("")
        out.append(o["text"])
        out.append("")
        out.append(f"Thresholds (calibrated risk, Watch / Warning / Emergency) are in `{o['levels_file']}`, in the "
                   "card format (`alert_levels`, `risk_by_region`) once per season.")
        out.append("")
        out.append("| region and season | level | threshold | point share | with uncertain_high | published share | "
                   "hold inflation | caught cell-exact | caught tolerant | cell-days per event caught (tolerant) |")
        out.append("|---|---|---|---|---|---|---|---|---|---|")
        for key, e in o["measured"].items():
            thr = o["thresholds"][key]
            for L in LEVELS:
                x = e[LEVEL_NAMES[L]]
                infl = "" if x["hold_inflation"] is None else f"x{x['hold_inflation']:.2f}"
                out.append(f"| {_stratum(key)} | {LEVEL_NAMES[L]} | {thr[L - 1]:.3g} | {_p(x['point_share'], 2)} | "
                           f"{_p(x['raw_share'], 2)} | {_p(x['published_share'], 2)} | {infl} | "
                           f"{_det(x['cell_exact'], e['events'])} | {_det(x['tolerant'], e['events'])} | "
                           f"{_n(x['tolerant']['cell_days_per_event'])} |")
        out.append("")
        out.append("Districts (each candidate rule): district-days at the level or above, events inside a district at "
                   "the level on the event day (and within 1 day), district-days per event:")
        out.append("")
        out.append("| region and season | level | rule | district-days | events in alerted district | within 1 day | "
                   "district-days per event | cell-days per event (tolerant, beside) |")
        out.append("|---|---|---|---|---|---|---|---|")
        for key, e in o["measured"].items():
            for L in LEVELS:
                x = e[LEVEL_NAMES[L]]
                for rule, d in x["districts"].items():
                    out.append(f"| {_stratum(key)} | {LEVEL_NAMES[L]} | {DISTRICT_RULES[rule].name} | "
                               f"{_n(d['district_days'])} | {d['events_in_alerted_district']} / {e['events']} | "
                               f"{d['events_in_alerted_district_within_1_day']} | {_n(d['district_days_per_event'])} | "
                               f"{_n(x['tolerant']['cell_days_per_event'])} |")
        out.append("")
        out.append(f"Chosen district rule: **{DISTRICT_RULES[o['district_rule']['chosen']].name}**.")
    out.append("")
    out.append("## The trade-off curve (point level, no rules, no hysteresis)")
    out.append("")
    out.append("Each row caps the level at a share of the cell-days of the region and season. Cost ratio: the alert "
               "cell-days the step saves per event it loses against the row above; the step is the better choice when one "
               "missed event is worth FEWER false-alarm cell-days than that ('any': the step loses no event). Chance "
               "floor: the share of all cell-days with an alert within 10 km and 1 day, i.e. the tolerant detection of an "
               "event placed at random.")
    for w, t in result["tradeoff"].items():
        for key, e in t["strata"].items():
            out.append("")
            out.append(f"### {_stratum(key)}: {e['events']} events ({e['slides']} independent slides), "
                       f"{_n(e['cell_days'])} cell-days")
            out.append("")
            out.append("| level | cap | realised share | alert cell-days | caught cell-exact [95% CI] | caught tolerant "
                       "[95% CI] | chance floor | events per 1,000 alert cell-days (exact / tolerant) | cost ratio "
                       "(exact / tolerant) |")
            out.append("|---|---|---|---|---|---|---|---|---|")
            for x in e["card"]:
                out.append(f"| {x['level']} today | card | {_p(x['share'], 2)} | {_n(x['alert_cell_days'])} | "
                           f"{_det(x['cell_exact'], e['events'])} | {_det(x['tolerant'], e['events'])} | "
                           f"{_p(x['chance_floor_tolerant'])} | {x['cell_exact']['per_1000_alert_cell_days'] or 0:.2f} / "
                           f"{x['tolerant']['per_1000_alert_cell_days'] or 0:.2f} | |")
            for level_name in ("Watch+", "Warning+", "Emergency"):
                for x in e[level_name]:
                    out.append(f"| {level_name} | {_p(x['cap'])} | {_p(x['share'], 2)} | {_n(x['alert_cell_days'])} | "
                               f"{_det(x['cell_exact'], e['events'])} | {_det(x['tolerant'], e['events'])} | "
                               f"{_p(x['chance_floor_tolerant'])} | {x['cell_exact']['per_1000_alert_cell_days'] or 0:.2f}"
                               f" / {x['tolerant']['per_1000_alert_cell_days'] or 0:.2f} | "
                               f"{_ratio(x['cell_exact']['cost_ratio'])} / {_ratio(x['tolerant']['cost_ratio'])} |")
    out.append("")
    out.append("## The one held-out look per option (pre-declared; the lead's, after the user chooses)")
    out.append("")
    for name, o in opts.items():
        c = o["heldout_criterion"]
        out.append(f"- **{name}**: `{o['heldout_command']}`. {c['rule']}. Development values it is held to: "
                   + "; ".join(f"{k} {_p(v['share'], 0)} (allowed shortfall {v['margin_slides']:.1f} slides)"
                               for k, v in c["detection"].items()) + ".")
    out.append("")
    out.append("## Caveats")
    out.append("")
    out += [f"- {c}" for c in result["caveats"]]
    out.append("")
    return "\n".join(out)


def write_report(say=print) -> dict:
    result = build_report()
    reports = PROJECT_ROOT / "reports"
    dump_json(reports / f"{REPORT_STEM}.json", jsonable(result))
    (reports / f"{REPORT_STEM}.md").write_text(markdown_report(result), encoding="utf-8")
    say(f"wrote reports/{REPORT_STEM}.{{json,md}}")
    return result


# ------------------------------------------------------------------------------------------- CLI

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m aetherguard.verify.operating_options", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    cmd = sub.add_parser("tradeoff", help="Task 1 on one window")
    cmd.add_argument("--window", choices=sorted(WINDOW_SEASONS), required=True)
    cmd = sub.add_parser("schemes", help="Tasks 2 and 3 on one window")
    cmd.add_argument("--window", choices=sorted(WINDOW_SEASONS), required=True)
    sub.add_parser("report", help="Task 4: reports/phase8_operating_point_options.{json,md}")
    cmd = sub.add_parser("heldout", help="THE one held-out look of the chosen option (the lead's)")
    cmd.add_argument("--option", choices=sorted(OPTIONS), required=True)
    args = parser.parse_args(argv)
    say = lambda m: print(m, flush=True)  # noqa: E731
    if args.command == "tradeoff":
        tradeoff(args.window, say)
    elif args.command == "schemes":
        schemes(args.window, say)
    elif args.command == "report":
        write_report(say)
    elif args.command == "heldout":
        heldout_look(args.option, say)
    return 0


if __name__ == "__main__":
    sys.exit(main())
