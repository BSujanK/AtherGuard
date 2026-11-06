"""Expanded held-out verification report (spec W1): v3 against rain, static-map, LHASA and rainfall-threshold benchmarks on
the June-December panels of 2018-2025 and on the reported events.

    python -m aetherguard.verify heldout    # reports/phase7_heldout_expanded.{json,md}

The panels are the training-style season panels of `verify.seasons`, loaded and turned into v3 levels exactly as the W0
baseline report does (`report.extract`; the section 11 rules). Days throughout are IMD days: day D runs from 03 UTC of the
previous day to 03 UTC of D (08:30 IST to 08:30 IST). Sets, each a pooling of seasons over days:

* `S2018`: the 2018 panel and the in-domain `season_2018` catalog events of June-September;
* `S1925`: the 2019-2025 panels and the admitted reported events (`ledger.load_reported`) plus the in-domain `test_sparse`
  catalog events of those years;
* `POOLED`: both; `L1820`: 2018-2020, the years LHASA covers, where `lhasa_v2` is compared on the same days and events.

Models (`MODELS`): `v3`; `rain_3d`, `susceptibility`, `lhasa_v2` (day shifts -1 / 0 / +1; 0 is primary) and `ed_threshold`
are burden-matched, season by season, to the shares v3 realised in that season, each ranking cell-days by its own score
(`baselines.burden_matched_cuts`); `rain_3d_devcuts` is the W0 baseline, cuts fitted on the development seasons.

`ed_threshold` scores a cell-day by the rain event ending on it (`baselines.rain_events`: consecutive IMD days of at least
1 mm of IMERG Late; E its total in mm, D its length in days) over the event-duration threshold E = alpha * D^gamma. The
coefficients are Brunetti et al. (2021, HESS 25, 3267-3279, "Satellite rainfall products outperform ground observations for
landslide prediction in India"), Table 1, IMERG Early run, 5% non-exceedance: E = 5.3 * D^0.74 with D in hours and E in mm.
D is converted to days (alpha = 5.3 * 24^0.74); after burden matching only the exponent shapes the ranking. The paper's hourly
events are not the daily events used here, so `ed_threshold_refit` is the same power law fitted on the development
positives' (D, E) at the 5% non-exceedance with the same frequentist method, labelled "refitted".

Ground truth after 2018 is very incomplete, so precision there is relative (between models), not absolute. Events are
de-duplicated on (cell, day) only, so the same slide in two sources, or in neighbouring cells, is several records;
`distinct_events` merges records within 10 km and a day into independent slides, and the 150-event gate is read on those
slides, not on the records. Events dated outside the panel days are counted, not scored; events in cells outside the panel
(`events_off_panel_cells`) can be matched only tolerantly, never cell-exact.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components

from ..alerts import levels as lv
from ..config import data_root
from ..features import imerg_features as F
from ..hazard import model as hm
from ..hazard.jsonio import dump_json
from ..ingest import imerg as imerg_mod
from ..live import backtest as bt
from ..live import burden
from ..live import hardening as H
from ..live import hardening_dev as D
from ..live import precision_study as ps
from ..live import run as live_run
from ..live.backtest import BOOTSTRAP
from ..live.sources import project_path
from . import ledger, seasons
from .baselines import (
    burden_matched_levels,
    ed_threshold_levels,
    fit_ed_threshold,
    rain_baseline,
    rain_events,
    realised_shares,
)
from .matching import Tolerance, rows_within
from .report import (
    LEVEL_NAMES,
    SHARE_HEADER,
    TABLE_HEADER_SLIDES,
    TOLERANCES,
    Part,
    RainFit,
    _pct,
    _rows,
    extract,
    fit_rain,
    load_development,
    model_table,
    susceptibility_levels,
)

REPORT_STEM = "phase7_heldout_expanded"
GATE_EVENTS = 150
HELD_OUT_YEARS = tuple(range(2019, 2026))
SEASON_YEARS = bt.SEASON_YEARS
LHASA_YEARS = (2018, 2019, 2020)
LHASA_SHIFTS = {"lhasa_v2_m1": -1, "lhasa_v2": 0, "lhasa_v2_p1": 1}
SOURCES = (
    "Event locations geocoded with GeoNames (CC BY 4.0) and © OpenStreetMap contributors (ODbL) via Nominatim",
    "LHASA v2: NASA GES DISC, Stanley et al. 2021",
    "Rainfall threshold: Brunetti et al. 2021 (HESS)",
    "IMERG: NASA GES DISC",
)
DEV_CUTS = "rain_3d_devcuts"
ED_LOOKBACK_DAYS = 60            # rain read before the first day, so a run that began in May is measured from its start
BRUNETTI_ALPHA_HOURS, BRUNETTI_GAMMA = 5.3, 0.74
SETS = {
    "S2018": (2018,),
    "S1925": HELD_OUT_YEARS,
    "POOLED": SEASON_YEARS,
    "L1820": LHASA_YEARS,
}
SET_NOTES = {
    "S2018": "the 2018 panel; the in-domain season_2018 catalog events of June-September",
    "S1925": "the 2019-2025 panels; admitted reported events and in-domain test_sparse catalog events",
    "POOLED": "S2018 and S1925 together",
    "L1820": "2018-2020, the years LHASA covers: every model, LHASA included, on the same days and events",
}
MODELS = {
    "v3": "v3 (frozen model, section 11 rules)",
    "rain_3d": "3-day rain, burden-matched to v3 in each season",
    "rain_3d_devcuts": "3-day rain cuts fitted on the development seasons (the W0 baseline)",
    "susceptibility": "static map (season-mean v3 risk), hindsight, at v3's shares",
    "lhasa_v2_m1": "LHASA v2 nowcast, day shift -1 (panel day D reads LHASA day D-1), burden-matched",
    "lhasa_v2": "LHASA v2 nowcast, same day (primary), burden-matched",
    "lhasa_v2_p1": "LHASA v2 nowcast, day shift +1 (panel day D reads LHASA day D+1), burden-matched",
    "ed_threshold": "rain event over the Brunetti et al. 2021 IMERG event-duration threshold, burden-matched",
    "ed_threshold_refit": "the same threshold refitted on the development positives, burden-matched",
}


def published_ed_threshold() -> tuple[float, float]:
    """(alpha, gamma) of Brunetti et al. (2021) Table 1, IMERG Early run 5% threshold, with D converted from hours to days."""
    return BRUNETTI_ALPHA_HOURS * 24.0**BRUNETTI_GAMMA, BRUNETTI_GAMMA


# ------------------------------------------------------------------------------------------------------ guards

def check_cell_order(cell_ids: np.ndarray, reference: np.ndarray, label: str) -> None:
    """Raise when `cell_ids` is not exactly the cells of `reference` in the same order (levels are compared by row)."""
    cell_ids, reference = np.asarray(cell_ids), np.asarray(reference)
    if cell_ids.shape != reference.shape or not np.array_equal(cell_ids, reference):
        raise ValueError(f"{label}: the cells or their order differ from the 2018 operational panel's "
                         f"({len(cell_ids)} against {len(reference)} cells)")


def days_below_half(scored: np.ndarray) -> int:
    """Days (columns of `scored`, cells x days) on which fewer than half of the cells have a score."""
    return int((np.asarray(scored, dtype=bool).mean(axis=0) < 0.5).sum())


def gate_line(records: int, slides: int, gate: int = GATE_EVENTS) -> str:
    """The gate is read on `slides`, the independent slides behind the `records` (see `event_clusters`)."""
    verdict = f"MET, {slides - gate} over" if slides >= gate else f"NOT MET, {gate - slides} short"
    return f"Held-out events: {records} records of {slides} independent slides against the {gate}-event gate: {verdict}."


# ------------------------------------------------------------------------------------------------------ events

def held_out_events(
    catalog_2018: pd.DataFrame, reported: pd.DataFrame, positives: pd.DataFrame, in_domain_cells: np.ndarray
) -> pd.DataFrame:
    """The held-out events as (cell_id, date, source): the 2018 catalog events as given, the reported events of 2019-2025,
    and the `test_sparse` catalog positives (`positive_cell_days`) of 2019-2025 in `in_domain_cells`."""
    sparse = positives[(positives["split"] == "test_sparse") & positives["cell_id"].isin(in_domain_cells)]
    sparse = sparse.rename(columns={"event_date": "date"})
    parts = {"catalog_2018": catalog_2018, "reported": reported, "catalog_sparse": sparse}
    frames = []
    for source, frame in parts.items():
        frame = frame[["cell_id", "date"]]
        if source != "catalog_2018":
            frame = frame[frame["date"].dt.year.isin(HELD_OUT_YEARS)]
        if len(frame):
            frames.append(frame.assign(source=source))
    if not frames:
        return pd.DataFrame({"cell_id": np.zeros(0, dtype=np.int64), "date": pd.to_datetime([]), "source": []})
    return pd.concat(frames, ignore_index=True)


def event_clusters(events: pd.DataFrame, tolerance: Tolerance = TOLERANCES["tolerant"]) -> np.ndarray:
    """A label per row of `events`: rows within `tolerance` of each other (single linkage) share one, as records of one slide.

    The same cell and day in two sources, or neighbouring cells a day apart, are one slide.
    """
    keys = pd.DataFrame({"cell_id": events["cell_id"].to_numpy(dtype=np.int64),
                         "ordinal": pd.to_datetime(events["date"]).map(lambda t: t.toordinal()).to_numpy(dtype=np.int64)})
    unique = keys.drop_duplicates().reset_index(drop=True)
    if unique.empty:
        return np.zeros(0, dtype=np.int64)
    near = rows_within(unique["cell_id"].to_numpy(), unique["cell_id"].to_numpy(), tolerance.km)
    first, second = [], []
    for i, rows in enumerate(near):
        close = rows[np.abs(unique["ordinal"].to_numpy()[rows] - unique["ordinal"].iloc[i]) <= tolerance.days]
        first.extend([i] * len(close))
        second.extend(close.tolist())
    graph = csr_matrix((np.ones(len(first)), (first, second)), shape=(len(unique), len(unique)))
    unique["label"] = connected_components(graph, directed=False)[1]
    return keys.merge(unique, on=["cell_id", "ordinal"], how="left")["label"].to_numpy()


def distinct_events(events: pd.DataFrame, tolerance: Tolerance = TOLERANCES["tolerant"]) -> int:
    """Independent slides among `events`: the clusters of `event_clusters`."""
    return len(np.unique(event_clusters(events, tolerance)))


def events_on_days(events: pd.DataFrame, days: list[date]) -> tuple[pd.DataFrame, int]:
    """The events dated on one of `days` and how many (distinct cell, day) events are not.

    Pooled seasons leave gaps between their days, which `matching.match` would read as days on which the system stayed
    silent, so an event in a gap must not reach it.
    """
    on_panel = pd.to_datetime(events["date"]).dt.date.isin(set(days)).to_numpy()
    outside = int(events[~on_panel][["cell_id", "date"]].drop_duplicates().shape[0])
    return events[on_panel].reset_index(drop=True), outside


# -------------------------------------------------------------------------------------------------------- LHASA

def align_lhasa(path: Path, cell_ids: np.ndarray, days: list[date], shift: int) -> np.ndarray:
    """LHASA probability (float64, cells x days) on the panel's cells and days: panel day D reads LHASA day D + `shift`.

    Cells are matched by id; NaN where the file has no granule for the shifted day. A panel cell the file lacks is an error.
    """
    with np.load(path, allow_pickle=False) as data:
        file_cells, file_days, prob = data["cell_id"], data["days"], data["prob"]
    rows = pd.Index(file_cells).get_indexer(np.asarray(cell_ids, dtype=np.int64))
    if (rows < 0).any():
        raise ValueError(f"{int((rows < 0).sum())} of the {len(rows)} panel cells are not cells of {Path(path).name}")
    column_of = {date.fromisoformat(str(d)): k for k, d in enumerate(file_days)}
    columns = np.array([column_of.get(d + timedelta(days=shift), -1) for d in days], dtype=np.int64)
    out = np.full((len(rows), len(days)), np.nan)
    known = columns >= 0
    out[:, known] = prob[np.ix_(rows, columns[known])]
    return out


# ----------------------------------------------------------------------------------------------- rain events

def ed_event_series(store, cell_ids: np.ndarray, first_day: date, n_days: int, lookback: int = ED_LOOKBACK_DAYS
                    ) -> tuple[np.ndarray, np.ndarray]:
    """Total (mm) and length (days) of the rain event ending on each of `n_days` days from `first_day` (cells x days).

    The IMD-day series of the cell's IMERG pixel is built as the model's features are (`imerg_features.imd_day_series`) from
    `lookback` days before `first_day`; `baselines.rain_events` reads the events. NaN for a cell outside the IMERG grid.
    """
    flat = F.cell_pixels(np.asarray(cell_ids, dtype=np.int64))
    event, duration = np.full((len(flat), n_days), np.nan), np.full((len(flat), n_days), np.nan)
    usable = np.flatnonzero(flat >= 0)
    if len(usable):
        pixels, inverse = np.unique(flat[usable], return_inverse=True)
        utc = store.gather(pixels // imerg_mod.COLS, pixels % imerg_mod.COLS, first_day - timedelta(days=lookback + 1),
                           lookback + 1 + n_days)
        total, length = rain_events(F.imd_day_series(utc))
        event[usable], duration[usable] = total[inverse, -n_days:], length[inverse, -n_days:]
    return event, duration


def ed_event_totals(store, cell_ids: np.ndarray, dates, lookback: int = ED_LOOKBACK_DAYS) -> tuple[np.ndarray, np.ndarray]:
    """Total and length of the rain event ending on each event's own day, per event (arrays of `len(cell_ids)`)."""
    cell_ids = np.asarray(cell_ids, dtype=np.int64)
    dates = pd.DatetimeIndex(pd.to_datetime(dates))
    event, duration = np.full(len(cell_ids), np.nan), np.full(len(cell_ids), np.nan)
    for day in dates.unique():
        chosen = np.flatnonzero(dates == day)
        total, length = ed_event_series(store, cell_ids[chosen], day.date(), 1, lookback)
        event[chosen], duration[chosen] = total[:, 0], length[:, 0]
    return event, duration


# ----------------------------------------------------------------------------------------------- the models

@dataclass
class SeasonResult:
    """One season's levels per model (cells x days from 1 June) and the shares behind them."""

    year: int
    days: list[date]
    scored: np.ndarray
    levels: dict[str, np.ndarray]
    shares: dict[str, dict]


def season_models(
    part: Part,
    event_rain: np.ndarray,
    duration: np.ndarray,
    lhasa: dict[int, np.ndarray] | None,
    rain_fit: RainFit,
    ed_fits: dict[str, tuple[float, float]],
) -> tuple[dict[str, np.ndarray], dict[str, dict]]:
    """Levels and shares of every model on one season; the benchmarks are burden-matched to v3's realised shares in it.

    `lhasa` maps a day shift to the LHASA probability aligned to the season (None for a season without LHASA); `ed_fits`
    names each threshold's (alpha, gamma) in days.
    """
    scored = part.scored
    v3_shares = realised_shares(part.v3, scored)
    levels = {
        "v3": part.v3,
        "rain_3d": burden_matched_levels(part.acc_3, scored, v3_shares),
        "rain_3d_devcuts": rain_baseline(part.acc_3, scored, rain_fit.acc_3, rain_fit.scored, rain_fit.shares),
        "susceptibility": susceptibility_levels(part.static_score, len(part.days), scored, v3_shares),
    }
    for name, shift in LHASA_SHIFTS.items():
        if lhasa is not None:
            levels[name] = burden_matched_levels(lhasa[shift], scored, v3_shares)
    for name, (alpha, gamma) in ed_fits.items():
        levels[name] = ed_threshold_levels(event_rain, duration, alpha, gamma, v3_shares, scored)
    shares = {name: {"target": None if name == "v3" else list(rain_fit.shares if name == "rain_3d_devcuts" else v3_shares),
                     "realised": list(realised_shares(array, scored))} for name, array in levels.items()}
    return levels, shares


def pool_seasons(results: list[SeasonResult], years) -> tuple[dict[str, np.ndarray], np.ndarray, list[date]]:
    """Levels per model, scored and days of the seasons of `years` joined over days, for the models all of them have."""
    by_year = {r.year: r for r in results}
    missing = [y for y in years if y not in by_year]
    if missing:
        raise ValueError(f"no season result for {missing}")
    chosen = [by_year[y] for y in years]
    names = [m for m in chosen[0].levels if all(m in r.levels for r in chosen)]
    levels = {m: np.concatenate([r.levels[m] for r in chosen], axis=1) for m in names}
    return (levels, np.concatenate([r.scored for r in chosen], axis=1), [d for r in chosen for d in r.days])


def pooled_shares(results: list[SeasonResult], years, levels: dict[str, np.ndarray], scored: np.ndarray) -> dict[str, dict]:
    """Per model the realised shares of the pooled `levels` and the target: the seasons' targets weighted by scored cell-days."""
    chosen = [r for r in results if r.year in years]
    weights = np.array([r.scored.sum() for r in chosen], dtype=np.float64)
    out = {}
    for name, array in levels.items():
        targets = [r.shares[name]["target"] for r in chosen]
        target = None if targets[0] is None else (np.array(targets).T @ weights / weights.sum()).tolist()
        out[name] = {"target": target, "realised": list(realised_shares(array, scored))}
    return out


def measure_set(name: str, results: list[SeasonResult], events: pd.DataFrame, cell_ids: np.ndarray, say) -> dict:
    levels, scored, days = pool_seasons(results, SETS[name])
    kept, outside = events_on_days(events[pd.to_datetime(events["date"]).dt.year.isin(SETS[name])], days)
    say(f"{name}: scoring {len(cell_ids)} cells x {len(days)} days, {len(kept)} events, models {list(levels)}")
    return {
        "years": list(SETS[name]),
        "note": SET_NOTES[name],
        "cells": int(len(cell_ids)),
        "days": len(days),
        "events": int(len(kept[["cell_id", "date"]].drop_duplicates())),
        "distinct_events": distinct_events(kept),
        "events_outside_panel_days": outside,
        "events_off_panel_cells": int((~kept[["cell_id", "date"]].drop_duplicates()["cell_id"].isin(cell_ids)).sum()),
        "events_by_source": {k: int(v) for k, v in kept.drop_duplicates(["cell_id", "date"]).groupby("source").size().items()},
        "shares": pooled_shares(results, SETS[name], levels, scored),
        "models": model_table(levels, scored, cell_ids, days, kept, TOLERANCES, None, BOOTSTRAP, event_clusters),
    }


# ------------------------------------------------------------------------------------------------------ loading

def load_panel_season(year: int, reference_cells: np.ndarray, model) -> D.Season:
    """The training-style panel of `year` from 1 June, without events; its cells must be the 2018 operational panel's."""
    panel = H.load_panel(seasons.season_path(None, year))
    check_cell_order(panel.cells["cell_id"].to_numpy(), reference_cells, f"season {year}")
    return D.Season(year, panel, panel.days.index(date(year, *seasons.SEASON_START)),
                    pd.DataFrame({"cell_id": np.zeros(0, dtype=np.int64), "date": pd.to_datetime([])}),
                    lv.card_region_thresholds(model.card, panel.cells["region"]))


def load_season(year: int, reference_cells: np.ndarray, model, config, base_rules) -> Part:
    """The training-style panel of `year` as v3 levels and baseline inputs; its cells must be the 2018 operational panel's."""
    return extract(load_panel_season(year, reference_cells, model), config, base_rules)


def lhasa_path(year: int) -> Path:
    return data_root() / "processed" / "benchmarks" / f"lhasa_{year}.npz"


def late_store(cfg: dict) -> imerg_mod.ImergStore:
    return imerg_mod.ImergStore(project_path(cfg["imerg"]["processed_dir"]), "late")


def refit_threshold(store, say) -> dict:
    """The event-duration threshold refitted on the development positives (June-September of 2007-2017)."""
    events = burden.development_events()
    total, length = ed_event_totals(store, events["cell_id"].to_numpy(), events["date"])
    alpha, gamma = fit_ed_threshold(length, total)
    used = int(((length > 0) & (total > 0)).sum())
    say(f"refitted threshold: E = {alpha:.2f} * D^{gamma:.3f} on {used} of {len(events)} development positives")
    return {"alpha": alpha, "gamma": gamma, "events_used": used, "events": int(len(events))}


def load_event_table(cfg: dict) -> pd.DataFrame:
    catalog = bt.load_set("season_2018", cfg=cfg).events
    positives = pd.read_parquet(data_root() / "processed" / "splits" / "positive_cell_days.parquet",
                                columns=["cell_id", "event_date", "split"])
    return held_out_events(catalog, ledger.load_reported(ledger.REPORTED_DIR), positives, bt.universe_cell_ids())


def season_summary(part: Part, result: SeasonResult, events: pd.DataFrame, lhasa: bool) -> dict:
    kept, _ = events_on_days(events, part.days)
    return {
        "cells": int(len(part.cell_ids)), "days": len(part.days), "scored_cell_days": int(part.scored.sum()),
        "scored_share_mean": float(part.scored.mean()), "days_below_half": days_below_half(part.scored),
        "v3_realised_shares": result.shares["v3"]["realised"], "events": int(len(kept[["cell_id", "date"]].drop_duplicates())),
        "lhasa": lhasa,
    }


def run(cfg: dict, say=print) -> dict:
    started = time.perf_counter()
    model, config, base_rules = ps.load_inputs(cfg)
    say("loading the development panels")
    development = load_development(model, config, base_rules, say)
    rain_fit = fit_rain(development, development[0].in_universe)
    del development
    store = late_store(cfg)
    refit = refit_threshold(store, say)
    published = published_ed_threshold()
    ed_fits = {"ed_threshold": published, "ed_threshold_refit": (refit["alpha"], refit["gamma"])}
    reference = H.load_panel(H.alerts_dir(H.HELDOUT_DIR) / H.HELDOUT_FILE).cells["cell_id"].to_numpy()
    events = load_event_table(cfg)
    results, per_season = [], {}
    for year in SEASON_YEARS:
        say(f"season {year}: loading the panel and scoring the models")
        part = load_season(year, reference, model, config, base_rules)
        event_rain, duration = ed_event_series(store, part.cell_ids, part.days[0], len(part.days))
        lhasa = None
        if year in LHASA_YEARS:
            lhasa = {shift: align_lhasa(lhasa_path(year), part.cell_ids, part.days, shift) for shift in LHASA_SHIFTS.values()}
        levels, shares = season_models(part, event_rain, duration, lhasa, rain_fit, ed_fits)
        results.append(SeasonResult(year, part.days, part.scored, levels, shares))
        per_season[str(year)] = season_summary(part, results[-1], events, lhasa is not None)
        del part, event_rain, duration, lhasa
    store.close()
    sets = {name: measure_set(name, results, events, reference, say) for name in SETS}
    held_out, slides = sets["POOLED"]["events"], sets["POOLED"]["distinct_events"]
    return {
        "protocol": {
            "alert_levels": LEVEL_NAMES,
            "tolerances": {n: {"km": t.km, "days": t.days} for n, t in TOLERANCES.items()},
            "models": MODELS,
            "sets": SET_NOTES,
            "sources": list(SOURCES),
            "ed_threshold": {
                "published": {"source": "Brunetti et al. 2021, HESS 25, 3267-3279, Table 1, IMERG Early run, 5% non-exceedance",
                              "alpha_hours": BRUNETTI_ALPHA_HOURS, "gamma": BRUNETTI_GAMMA, "alpha_days": published[0]},
                "refitted": refit,
            },
            "bootstrap": BOOTSTRAP,
        },
        "seasons": per_season,
        "sets": sets,
        "gate": {"gate": GATE_EVENTS, "events": held_out, "distinct_events": slides, "met": slides >= GATE_EVENTS,
                 "line": gate_line(held_out, slides)},
        "seconds": time.perf_counter() - started,
    }


# ------------------------------------------------------------------------------------------------------- output

def lhasa_shift_gap(result: dict) -> list[float] | None:
    """The largest burden shortfall, in percentage points per level (Watch+, Warning+, Emergency), of a shifted LHASA row
    against v3 over the sets that hold one; None when no set does."""
    gaps = []
    for entry in result["sets"].values():
        shares = entry["shares"]
        for name, shift in LHASA_SHIFTS.items():
            if shift != 0 and name in shares:
                gaps.append([100.0 * (v - w) for v, w in zip(shares["v3"]["realised"], shares[name]["realised"])])
    return None if not gaps else [max(level) for level in zip(*gaps)]


def _share_rows(entry: dict) -> list[str]:
    """The share table rows; the target of the development-cuts baseline is not a matched one and says so."""
    rows = []
    for model in entry["models"]:
        s = entry["shares"][model]
        target = "n/a" if s["target"] is None else " / ".join(_pct(v, 2) for v in s["target"])
        if model == DEV_CUTS:
            target = f"development shares (not matched): {target}"
        rows.append(f"| {model} | {target} | {' / '.join(_pct(v, 2) for v in s['realised'])} |")
    return rows


def _set_section(name: str, entry: dict) -> list[str]:
    sources = ", ".join(f"{k} {v}" for k, v in entry["events_by_source"].items())
    outside = entry["events_outside_panel_days"]
    outside_text = f"{outside} further event is" if outside == 1 else f"{outside} further events are"
    off = entry["events_off_panel_cells"]
    verb = "lies" if off == 1 else "lie"
    off_panel = [f"{off} of the {entry['events']} events {verb} outside the panel cells and can be detected only tolerantly (by a "
                 "panel cell within 10 km), never cell-exact.", ""] if off else []
    return [
        f"## {name} ({entry['cells']:,} cells, {entry['days']} days, {entry['events']} events)",
        "",
        f"{entry['note']}. Events by source: {sources}. {entry['distinct_events']} independent slides when events within "
        f"10 km and a day are merged (`POD (independent slides)` counts a slide as detected when any of its records is); "
        f"{outside_text} dated outside the panel days and not scored.",
        "",
        *off_panel,
        TABLE_HEADER_SLIDES,
        *_rows(entry, entry["models"], independent=True),
        "",
        "Alert shares, target against realised (pooled over the set's seasons):",
        "",
        SHARE_HEADER,
        *_share_rows(entry),
        "",
    ]


def markdown(result: dict) -> str:
    ed, gate = result["protocol"]["ed_threshold"], result["gate"]
    published, refit = ed["published"], ed["refitted"]
    gap = lhasa_shift_gap(result)
    shift_note = [] if gap is None else [
        f"- The LHASA shift rows (-1, +1) realise up to {gap[0]:.1f} points (Watch+; {gap[1]:.2f} at Warning+, {gap[2]:.2f} at "
        "Emergency) less burden than v3 and the other benchmarks (shift 0 matches): one boundary day per season has no "
        "granule for the shifted day."]
    season_rows = [
        f"| {year} | {_pct(s['scored_share_mean'])} | {s['days_below_half']} of {s['days']} | "
        f"{' / '.join(_pct(v, 2) for v in s['v3_realised_shares'])} | {s['events']} | {'yes' if s['lhasa'] else 'no'} |"
        for year, s in result["seasons"].items()]
    lines = [
        "# Held-out verification, expanded (phase 7, W1)",
        "",
        f"**{gate['line']}** Records are merged into slides when they lie within 10 km and a day of each other (the same slide "
        "in two sources, or in neighbouring cells).",
        "",
        "v3 against 3-day rain, a static map, the NASA LHASA v2 nowcast and a rainfall event-duration threshold, on the "
        "June-December panels of 2018-2025 (frozen model, training-style features). POD is the share of events whose highest "
        "level within tolerance reached the level; precision is the share of alert cell-days that an event lies within "
        "tolerance of. `tolerant` is 10 km and 1 day, `cell_exact` the same cell and day. Intervals are 95% percentile "
        "bootstraps (days resampled for precision, events for POD).",
        "",
        "## Reading this report",
        "",
        "- Days are IMD days: day D runs from 03 UTC of the previous day to 03 UTC of D (08:30 IST to 08:30 IST).",
        "- Tolerant POD has a high chance floor at Watch+ and Warning+: the 10 km / ±1 day window covers about 30-40 "
        "cell-days, so alerts placed at random at the same burden would also hit often. It is meaningful only as a comparison "
        "between models at matched burden; the cell-exact rows are the check that does not reward scattered alerts (v3 leads "
        "there too).",
        "- Ground truth after 2018 is very incomplete: the reported and catalog events are a small fraction of the slides "
        "that happened. Precision on S1925 and POOLED is therefore relative, for comparing models that raise the same "
        "burden, and is not an absolute false-alarm rate.",
        "- Every benchmark except `rain_3d_devcuts` is burden-matched, season by season, to the shares v3 realised in that "
        "season, ranking the cell-days by its own score; the realised shares are in the tables. `lhasa_v2` has no score on "
        "days its archive lacks, so it can fall short of the target.",
        "- `ed_threshold` applies Brunetti et al.'s hourly-event exponent to daily wet-day runs, so `ed_threshold_refit`, "
        "fitted on the same kind of daily events, is the fairer threshold benchmark.",
        *shift_note,
        "- `susceptibility` is computed from v3's risk over the season it is scored on (hindsight), an optimistic baseline.",
        "- S2018 events are the June-September catalog events while the 2018 panel runs to December: alerts in October-"
        "December cannot be verified there, which lowers S2018 precision for every model alike.",
        "- Every set holds the same panel cells, which are not all cells of India; an event is matched to the panel cells "
        "within tolerance.",
        "- `lhasa_v2` covers 2018-2020 only, so it appears in S2018 and in L1820, which holds every model on the same days "
        "and events. Shift 0 (panel day D with LHASA day D) is primary; whether LHASA day D uses rain through the whole of "
        "UTC day D is not established, hence the -1 and +1 rows.",
        "- `ed_threshold`: the rain event ending on the cell-day (consecutive IMD days with at least 1 mm of IMERG Late; E "
        "its total, D its length in days) over E = alpha * D^gamma. Published: "
        f"{published['source']}: E = {published['alpha_hours']} * D_hours^{published['gamma']}, that is alpha = "
        f"{published['alpha_days']:.1f} for D in days; only the exponent shapes a burden-matched ranking. "
        f"`ed_threshold_refit` is refitted: E = {refit['alpha']:.2f} * D^{refit['gamma']:.3f} at the 5% non-exceedance of "
        f"{refit['events_used']} of {refit['events']} development positives (the rest have no usable rain event ending on "
        "their day). A cell-day with no event never alerts.",
        "",
        "## Data sources",
        "",
        *[f"- {source}" for source in result["protocol"]["sources"]],
        "",
        "## Seasons",
        "",
        "| season | scored share of cell-days | days below half | v3 realised Watch+ / Warning+ / Emergency | events | LHASA |",
        "|---|---|---|---|---|---|",
        *season_rows,
        "",
    ]
    for name, entry in result["sets"].items():
        lines += _set_section(name, entry)
    return "\n".join(lines)


def write_heldout(out: Path, say=print) -> dict:
    result = run(live_run.load_run_config(), say)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    dump_json(out / f"{REPORT_STEM}.json", result)
    (out / f"{REPORT_STEM}.md").write_text(markdown(result), encoding="utf-8")
    say(f"wrote {hm.display_path(out / REPORT_STEM)}.{{json,md}}")
    return result
