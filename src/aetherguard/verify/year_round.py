"""Year-round alerts: why the levels outside June-September mean less, and a per-season treatment (phase 8, development).

    python -m aetherguard.verify.year_round panels      # per development year: today's chain decomposed, every candidate
    python -m aetherguard.verify.year_round summarise   # diagnosis, live days, slide counts, the declared selection
    python -m aetherguard.verify.year_round report      # reports/phase8_year_round.{json,md}
    python -m aetherguard.verify.year_round preflight   # the held-out look's inputs checked, no outcome read
    python -m aetherguard.verify.year_round heldout     # THE look (the lead's, once; refuses a second)

Why. The model and the alert levels were validated on June-September only; outside those months every lead carries
`outside_validated_season` (reports/phase8_season_validity.md). The thresholds are absolute risks, the same in every
month, and the post-model rules (rain cap, `uncertain_high`, hysteresis) were chosen on monsoon panels. Whether a level
means the same thing in January as in July was never measured. This module measures it on the out-of-fold v4 panels of
the development years on every scored cell (`live.oof_v4_full`, January-May and June-December) and the development
positives of every month, and chooses a per-season treatment by a rule declared in the spec
(docs/superpowers/specs/2026-11-17-aetherguard-year-round.md) before the selection was run.

Treatments (out of season only: a June-September published level is never changed, by construction):
* a per-season risk scale `m` (October-December and January-May each have their own): the three thresholds of both
  regions are multiplied by `m`, which is the same as dividing the risk by `m`, a per-season recalibration;
* `uncertain_high` off out of season: the raw level is the point level (no raise to Watch from the upper bound).
Every candidate goes through today's chain otherwise (rain cap and hold release of `post_rules_v3.json`, hysteresis of
`alert_config_v3.json`, both as the live run reads them), so the hysteresis steps down against the season's thresholds.

Nothing here reads a held-out event except `heldout`, and `summarise`, which counts held-out events by season (dates and
cells only, no model output) to state how much a held-out look could decide.
"""
from __future__ import annotations

import argparse
import json
import math
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
from . import operating_options as O
from .matching import match

RESULTS = "year_round"                                  # under data/processed/alerts/
REPORT_STEM = "phase8_year_round"
SPEC = "docs/superpowers/specs/2026-11-17-aetherguard-year-round.md"
LEVELS = (lv.WATCH, lv.WARNING, lv.EMERGENCY)
LEVEL_NAMES = O.LEVEL_NAMES
REGIONS = O.REGIONS
SEASONS = FL.SEASON_NAMES                               # monsoon, post_monsoon, rest
OUT_SEASONS = ("post_monsoon", "rest")
WINDOWS = ("jan_may", "jun_dec")
SCALES = (1.0, 1.25, 1.5, 2.0, 3.0)                     # the declared grid of the per-season risk scale
UNCERTAIN = (True, False)                               # uncertain_high out of season: on (today) or off
TODAY = (1.0, True)
STAGES = ("point", "raw", "capped", "published", "uncertain_capped")
ELEVATION_EDGES = (1000.0, 2000.0, 3000.0, 4000.0)      # metres; bands <1000, 1000-2000, ..., >=4000
# the declared selection rule (spec section 4): a candidate may lose at most this many independent slides against today
# in its season, at every level and tolerance: max(LOSS_MIN, floor(LOSS_SHARE x the season's slides))
LOSS_MIN, LOSS_SHARE = 1, 0.03
# the declared held-out look (spec section 6)
BURDEN_KEEP = 0.5                    # the held-out burden reduction must reach this share of the development (LOYO) one
BURDEN_MIN_DEV = 0.10                # ... at every region and level whose development reduction is at least this
LOOK_SEASON = "post_monsoon"         # the only out-of-season months with held-out panels (alerts/v4_seasons)


def results_dir() -> Path:
    return data_root() / "processed" / "alerts" / RESULTS


def key(scale: float, uncertain: bool) -> str:
    return f"m{scale:.2f}_u{'on' if uncertain else 'off'}"


def parse_key(name: str) -> tuple[float, bool]:
    scale, unc = name[1:].split("_u")
    return float(scale), unc == "on"


CANDIDATES = [key(m, u) for m in SCALES for u in UNCERTAIN]
TODAY_KEY = key(*TODAY)


# ------------------------------------------------------------------------------------------- pure building blocks

def season_thresholds(card: dict[str, lv.Thresholds], scales: dict[str, float]) -> dict[tuple[str, str], tuple]:
    """(watch, warning, emergency) of every (region, season): the card's, times the season's scale (1 if absent)."""
    out = {}
    for r in REGIONS:
        base = np.asarray(card[r].as_array(), dtype=np.float64)
        for s in SEASONS:
            out[(r, s)] = tuple(float(v) for v in base * float(scales.get(s, 1.0)))
    return out


def candidate_scales(name: str) -> tuple[dict[str, float], bool]:
    """({season: scale} of the out-of-season months, uncertain_high out of season) of a grid candidate (the same scale
    in both out-of-season seasons; `summarise` combines the per-season choices)."""
    scale, unc = parse_key(name)
    return {s: scale for s in OUT_SEASONS}, unc


def panel_season(y: O.Year) -> np.ndarray:
    """Season index of every panel day; the warm-up days take the season of the first evaluation day (as
    `operating_options.full_row_thresholds` does)."""
    first = y.season[0] if len(y.season) else 0
    return np.concatenate([np.full(y.first, first), y.season]).astype(int)


def treatment_levels(y: O.Year, card: dict, config, rules, scales: dict[str, float], uncertain_out: bool
                     ) -> dict[str, np.ndarray]:
    """Levels of the evaluation days under a treatment: point (risk against the season's thresholds), raw (with
    `uncertain_high`, unless switched off out of season), capped (the rain cap of `rules`) and published (the hold release
    and the hysteresis on top). June-September is today's chain whatever the treatment."""
    panel = y.panel
    rows = O.full_row_thresholds(y, season_thresholds(card, scales))
    point = lv.level_from_risk(panel["risk"], rows)
    raw = lv.raw_level(panel["risk"], panel["new_hi"], rows)[0]
    if not uncertain_out:
        out_days = panel_season(y) != SEASONS.index("monsoon")
        raw = np.where(out_days[None, :], point, raw).astype(np.int8)
    ok = D.rain_ok(panel, rules.rain)
    capped = np.where(ok, raw, rules.cap_array()[raw]).astype(np.int8)
    season = D.Season(y.year, panel, y.first, y.events, {r: card[r] for r in REGIONS})
    published = D.levels_from_raw(season, raw, config, rules, row_thresholds=rows)
    f = y.first
    return {"point": point[:, f:], "raw": raw[:, f:], "capped": capped[:, f:], "published": published[:, f:],
            "rain_ok": ok[:, f:]}


def stratum_counts(levels: np.ndarray, scored: np.ndarray, region: np.ndarray, season: np.ndarray) -> dict:
    """{"region|season": [scored cell-days, cell-days at Watch+, Warning+, Emergency]}."""
    out = {}
    for r in REGIONS:
        for si, s in enumerate(SEASONS):
            cols = season == si
            if not cols.any():
                continue
            block = np.ix_(region == r, cols)
            sc = scored[block]
            lev = levels[block]
            out[f"{r}|{s}"] = [int(sc.sum())] + [int(((lev >= k) & sc).sum()) for k in LEVELS]
    return out


def elevation_band(elev: np.ndarray) -> np.ndarray:
    return np.digitize(np.asarray(elev, dtype=np.float64), ELEVATION_EDGES)


def loss_allowed(slides: int) -> int:
    return max(LOSS_MIN, int(math.floor(LOSS_SHARE * slides)))


def slide_hits(event_level: np.ndarray, labels: np.ndarray, level: int) -> int:
    """Independent slides with at least one record at `level` or above."""
    if len(labels) == 0:
        return 0
    found = pd.Series(np.asarray(event_level) >= level).groupby(np.asarray(labels)).any()
    return int(found.sum())


def choose(burden_by: dict[str, np.ndarray], hits_by: dict[str, dict], today_hits: dict, slides: int) -> dict:
    """The declared selection for one season (spec section 4). `burden_by[candidate]` = published cell-days at
    (Watch+, Warning+, Emergency); `hits_by[candidate][(tolerance, level)]` = slides detected; `today_hits` the same for
    today. A candidate passes when it loses at most `loss_allowed(slides)` slides at every tolerance and level; of the
    passing ones the fewest Emergency, then Warning+, then Watch+ cell-days wins, then the smaller scale, then
    `uncertain_high` on (the smaller change)."""
    allowed = loss_allowed(slides)
    passing = []
    for name, counts in burden_by.items():
        loss = max(today_hits[k] - hits_by[name][k] for k in today_hits)
        if loss <= allowed:
            scale, unc = parse_key(name)
            passing.append(((int(counts[2]), int(counts[1]), int(counts[0]), scale, not unc), name, loss))
    passing.sort()
    if not passing:
        return {"chosen": TODAY_KEY, "allowed_loss": allowed, "max_loss": 0, "passing": []}
    return {"chosen": passing[0][1], "allowed_loss": allowed, "max_loss": int(passing[0][2]),
            "passing": [p[1] for p in passing]}


def upper_loss_share(slides: int, lost: int = 0, level: float = 0.95) -> float | None:
    """One-sided upper confidence bound of the share of slides a treatment loses when `lost` of `slides` were lost
    (exact binomial, Clopper-Pearson); only `lost == 0` is needed here: 1 - (1 - level) ** (1 / slides)."""
    if slides <= 0:
        return None
    if lost != 0:
        raise ValueError("only the no-loss bound is implemented")
    return float(1.0 - (1.0 - level) ** (1.0 / slides))


def veto_power(slides: int, loss_share: float) -> float:
    """Chance that a treatment losing `loss_share` of the slides loses at least one of `slides` (the veto fires)."""
    return float(1.0 - (1.0 - loss_share) ** slides) if slides > 0 else 0.0


# ---------------------------------------------------------------------------------------- step 1: development panels

def year_path(window: str, year: int) -> Path:
    return results_dir() / f"year_{window}_{year}.json"


def chain_inputs():
    cfg = live_run.load_run_config()
    config = load_alert_config(live_run.project_path(cfg["alert_config"]))
    rules = pr.load_rules(live_run.project_path(cfg["post_rules"]))
    return cfg, config, rules, O.card_thresholds()


def cell_elevation(cell_ids: np.ndarray) -> np.ndarray:
    table = pd.read_parquet(data_root() / "processed" / "terrain" / "cell_terrain.parquet", columns=["cell_id", "elev_mean"])
    return table.set_index("cell_id").reindex(np.asarray(cell_ids, dtype=np.int64))["elev_mean"].to_numpy()


def score_year(y: O.Year, card: dict, config, rules) -> dict:
    """One development year of one window: today's chain decomposed by stratum and elevation band, the events with their
    levels, and every candidate's published counts and event levels (cell-exact and tolerant)."""
    region, season, scored = y.region, y.season, y.scored
    risk = y.risk
    base = treatment_levels(y, card, config, rules, {}, True)
    band = elevation_band(cell_elevation(y.cell_ids))
    acc7 = np.asarray(y.panel["acc_7"])[:, y.first:]
    decomposition = {}
    for r in REGIONS:
        for si, s in enumerate(SEASONS):
            cols = season == si
            if not cols.any():
                continue
            for b in range(len(ELEVATION_EDGES) + 1):
                block = np.ix_((region == r) & (band == b), cols)
                sc = scored[block]
                entry = {"cell_days": int(sc.sum()), "rain_ok": int((base["rain_ok"][block] & sc).sum()),
                         "risk_sum": float(np.where(sc, risk[block], 0.0).sum())}
                for name in ("point", "raw", "capped", "published"):
                    entry[name] = [int(((base[name][block] >= k) & sc).sum()) for k in LEVELS]
                entry["uncertain_capped"] = [int(((base["capped"][block] >= k) & (base["point"][block] < k) & sc).sum())
                                             for k in LEVELS]
                pub = base["published"][block]
                entry["risk_sum_published"] = [float(np.where((pub >= k) & sc, risk[block], 0.0).sum()) for k in LEVELS]
                decomposition[f"{r}|{s}|{b}"] = entry
    months = np.array([d.month for d in y.days])
    monthly = {}
    for r in REGIONS:
        for month in np.unique(months):
            block = np.ix_(region == r, months == month)
            sc = scored[block]
            monthly[f"{r}|{int(month)}"] = {"cell_days": int(sc.sum()), "rain_ok": int((base["rain_ok"][block] & sc).sum()),
                                            "published": [int(((base["published"][block] >= k) & sc).sum())
                                                          for k in LEVELS]}
    candidates, events = {}, None
    for name in CANDIDATES:
        scales, unc = candidate_scales(name)
        levels = base if name == TODAY_KEY else treatment_levels(y, card, config, rules, scales, unc)
        entry = {"counts": stratum_counts(levels["published"], scored, region, season), "event_level": {}}
        for t, tol in O.TOLERANCES.items():
            m = match(levels["published"], y.cell_ids, y.days, y.events, tol)
            if events is None:
                events = m.events.reset_index(drop=True)
            elif len(m.events) != len(events):
                raise ValueError(f"{y.window} {y.year}: {name} matched {len(m.events)} events against {len(events)}")
            entry["event_level"][t] = [int(v) for v in m.event_level]
        candidates[name] = entry
    events = events if events is not None else pd.DataFrame({"cell_id": [], "date": []})
    ci = pd.Index(y.cell_ids).get_indexer(events["cell_id"].to_numpy(dtype=np.int64))
    di = pd.Index(pd.to_datetime(pd.Series(y.days))).get_indexer(pd.to_datetime(events["date"]))
    if (ci < 0).any() or (di < 0).any():
        raise ValueError(f"{y.window} {y.year}: an event is outside the panel's cells or days")
    event_rows = [{"cell_id": int(y.cell_ids[i]), "date": pd.Timestamp(events["date"].iloc[n]).date().isoformat(),
                   "region": str(region[i]), "season": SEASONS[int(season[j])], "band": int(band[i]),
                   "acc_7": float(acc7[i, j]), "risk": float(risk[i, j]),
                   **{name: int(base[name][i, j]) for name in ("point", "raw", "capped", "published")}}
                  for n, (i, j) in enumerate(zip(ci, di))]
    return {"year": y.year, "window": y.window, "first_day": y.days[0].isoformat(), "last_day": y.days[-1].isoformat(),
            "decomposition": decomposition, "monthly": monthly, "events": event_rows, "candidates": candidates}


def panels(say=print, years=burden.DEV_YEARS) -> list[Path]:
    """Step 1, resumable: one result file per development year and window; an existing file is kept."""
    burden._assert_development(years)
    _, config, rules, card = chain_inputs()
    events = O.development_events_all(years)
    results_dir().mkdir(parents=True, exist_ok=True)
    written = []
    for window in WINDOWS:
        for year in years:
            path = year_path(window, year)
            if path.is_file():
                say(f"{path.name} exists")
                written.append(path)
                continue
            started = time.perf_counter()
            result = score_year(O.Year(year, window, events), card, config, rules)
            result["seconds"] = time.perf_counter() - started
            part = path.with_name(path.name + ".part")            # a stopped job never leaves a half file behind
            dump_json(part, result)
            part.replace(path)
            say(f"{path.name}: {len(result['events'])} events, {result['seconds']:.0f}s")
            written.append(path)
    return written


# --------------------------------------------------------------------------------------- step 2: summarise and select

def load_years(years=burden.DEV_YEARS) -> list[dict]:
    out = []
    for window in WINDOWS:
        for year in years:
            path = year_path(window, year)
            if not path.is_file():
                raise FileNotFoundError(f"{path} is missing: run `panels` first")
            out.append(json.loads(path.read_text(encoding="utf-8")))
    return out


def event_table(parts: list[dict]) -> pd.DataFrame:
    """Every development event of every part with today's levels and each candidate's levels, one row per event."""
    frames = []
    for part in parts:
        e = pd.DataFrame(part["events"])
        if e.empty:
            continue
        e["year"] = part["year"]
        for name, entry in part["candidates"].items():
            for t, values in entry["event_level"].items():
                e[f"{name}|{t}"] = values
        frames.append(e)
    table = pd.concat(frames, ignore_index=True)
    table["date"] = pd.to_datetime(table["date"])
    from .heldout import event_clusters
    table["slide"] = event_clusters(table[["cell_id", "date"]])
    return table


def _share(n, d):
    return None if not d else n / d


def diagnosis(parts: list[dict], events: pd.DataFrame, rain_minimum_mm: float | None = None) -> dict:
    """Today's chain by region and season (and Himalayan elevation band): shares at each stage, `uncertain_high` added
    after the rain cap, hold inflation, rain-ok share, events, hits, precision and the tail calibration (expected events
    = summed risk over the alert cell-days, against the cell-exact hits)."""
    acc: dict = {}
    for part in parts:
        for k, entry in part["decomposition"].items():
            r, s, b = k.split("|")
            for target in ((r, s), (r, s, int(b))):
                a = acc.setdefault(target, {"cell_days": 0, "rain_ok": 0, "risk_sum": 0.0,
                                            **{n: np.zeros(3, np.int64) for n in STAGES},
                                            "risk_sum_published": np.zeros(3)})
                a["cell_days"] += entry["cell_days"]
                a["rain_ok"] += entry["rain_ok"]
                a["risk_sum"] += entry["risk_sum"]
                for n in STAGES:
                    a[n] += np.asarray(entry[n])
                a["risk_sum_published"] += np.asarray(entry["risk_sum_published"])
    out = {"strata": {}, "elevation": {}}
    for target, a in acc.items():
        r, s = target[0], target[1]
        sel = (events["region"] == r) & (events["season"] == s)
        if len(target) == 3:
            sel &= events["band"] == target[2]
        ev = events[sel]
        n = a["cell_days"]
        row = {"cell_days": n, "events": int(len(ev)), "slides": int(ev["slide"].nunique()),
               "rain_ok_share": _share(a["rain_ok"], n), "expected_over_observed_all": _share(a["risk_sum"], len(ev))}
        for i, k in enumerate(LEVELS):
            name = LEVEL_NAMES[k]
            hits = int((ev["published"] >= k).sum())
            row[name] = {"point_share": _share(a["point"][i], n), "raw_share": _share(a["raw"][i], n),
                         "capped_share": _share(a["capped"][i], n), "published_share": _share(a["published"][i], n),
                         "uncertain_added_share": _share(a["uncertain_capped"][i], n),
                         "hold_inflation": _share(a["published"][i], a["capped"][i]),
                         "alert_cell_days": int(a["published"][i]), "hits_exact": hits,
                         "hits_per_100k": _share(1e5 * hits, a["published"][i]),
                         "expected_over_observed": _share(a["risk_sum_published"][i], hits)}
        if len(target) == 2:
            out["strata"][f"{r}|{s}"] = row
        else:
            out["elevation"][f"{r}|{s}|{target[2]}"] = row
    rain = {}
    for (r, s), ev in events.groupby(["region", "season"]):
        rain[f"{r}|{s}"] = {"events": int(len(ev)), "acc_7_p05": float(np.quantile(ev["acc_7"], 0.05)),
                            "acc_7_median": float(ev["acc_7"].median()),
                            "share_below_minimum": None if rain_minimum_mm is None
                            else float((ev["acc_7"] < rain_minimum_mm).mean())}
    out["rain_at_events"] = rain
    out["rain_minimum_mm"] = rain_minimum_mm
    monthly: dict = {}
    for part in parts:
        for k, entry in part.get("monthly", {}).items():
            n = entry["cell_days"]
            monthly.setdefault(k, []).append({"year": part["year"], "rain_ok_share": _share(entry["rain_ok"], n),
                                              **{LEVEL_NAMES[lvl]: _share(entry["published"][i], n)
                                                 for i, lvl in enumerate(LEVELS)}})
    out["monthly_by_year"] = monthly
    return out


def season_burden(parts: list[dict], season: str, candidate: str, years=None, region: str | None = None) -> np.ndarray:
    """[scored cell-days, Watch+, Warning+, Emergency] published cell-days of `candidate` in `season` (both regions, or
    one), over the parts of `years` (all when None)."""
    total = np.zeros(4, dtype=np.int64)
    for part in parts:
        if years is not None and part["year"] not in years:
            continue
        for r in ([region] if region else REGIONS):
            total += np.asarray(part["candidates"][candidate]["counts"].get(f"{r}|{season}", [0, 0, 0, 0]), np.int64)
    return total


def season_hits(events: pd.DataFrame, season: str, candidate: str, years=None) -> dict[tuple[str, int], int]:
    """{(tolerance, level): independent slides detected} of the events of `season` (and `years`)."""
    ev = events[events["season"] == season]
    if years is not None:
        ev = ev[ev["year"].isin(list(years))]
    return {(t, k): slide_hits(ev[f"{candidate}|{t}"].to_numpy(), ev["slide"].to_numpy(), k)
            for t in O.TOLERANCES for k in LEVELS}


def select_season(parts: list[dict], events: pd.DataFrame, season: str, years) -> dict:
    burden_by = {c: season_burden(parts, season, c, years)[1:] for c in CANDIDATES}
    hits_by = {c: season_hits(events, season, c, years) for c in CANDIDATES}
    ev = events[(events["season"] == season) & events["year"].isin(list(years))]
    return choose(burden_by, hits_by, hits_by[TODAY_KEY], int(ev["slide"].nunique()))


def loyo(parts: list[dict], events: pd.DataFrame, season: str, years=burden.DEV_YEARS) -> dict:
    """Leave one development year out: the rule chooses on the other years and the choice is applied to the year left
    out; the burden and the detection summed over the left-out years estimate the rule's effect on unseen years."""
    chosen, burden_sum, base_sum = {}, np.zeros(4, np.int64), np.zeros(4, np.int64)
    hits = {k: 0 for k in season_hits(events, season, TODAY_KEY, [])}
    base = dict(hits)
    for year in years:
        rest = [y for y in years if y != year]
        name = select_season(parts, events, season, rest)["chosen"]
        chosen[year] = name
        burden_sum += season_burden(parts, season, name, [year])
        base_sum += season_burden(parts, season, TODAY_KEY, [year])
        for k, v in season_hits(events, season, name, [year]).items():
            hits[k] += v
        for k, v in season_hits(events, season, TODAY_KEY, [year]).items():
            base[k] += v
    return {"chosen_by_year": chosen, "published": burden_sum.tolist(), "today_published": base_sum.tolist(),
            "reduction": [None if not b else 1.0 - a / b for a, b in zip(burden_sum[1:], base_sum[1:])],
            "hits": {f"{t}|{k}": v for (t, k), v in hits.items()},
            "today_hits": {f"{t}|{k}": v for (t, k), v in base.items()},
            "lost": {f"{t}|{k}": base[(t, k)] - hits[(t, k)] for (t, k) in base}}


def candidate_table(parts: list[dict], events: pd.DataFrame, season: str) -> list[dict]:
    rows = []
    for c in CANDIDATES:
        hits = season_hits(events, season, c)
        row = {"candidate": c, "hits": {f"{t}|{k}": v for (t, k), v in hits.items()}, "regions": {}}
        for r in REGIONS:
            b = season_burden(parts, season, c, region=r)
            row["regions"][r] = {"cell_days": int(b[0]), **{LEVEL_NAMES[k]: _share(int(b[i + 1]), int(b[0]))
                                                          for i, k in enumerate(LEVELS)}}
        row["published"] = season_burden(parts, season, c).tolist()
        rows.append(row)
    return rows


def treatment_document(choices: dict[str, str], card: dict) -> dict:
    """The selected per-season treatment as thresholds per season and region (a NEW file, never the frozen card)."""
    scales = {s: parse_key(choices[s])[0] for s in OUT_SEASONS}
    thresholds = season_thresholds(card, scales)
    return {"version": 1, "spec": SPEC, "note": "development selection; NOT wired into the live run (a model change)",
            "seasons": {s: {"months": list(FL.SEASONS[s]), "scale": 1.0 if s == "monsoon" else scales[s],
                            "uncertain_high": True if s == "monsoon" else parse_key(choices[s])[1],
                            "thresholds": {r: list(thresholds[(r, s)]) for r in REGIONS}} for s in SEASONS}}


def document_path() -> Path:
    return results_dir() / "levels_year_round.json"


def document_treatment(document: dict) -> tuple[dict[str, float], dict[str, bool]]:
    seasons = document["seasons"]
    return ({s: float(seasons[s]["scale"]) for s in OUT_SEASONS},
            {s: bool(seasons[s]["uncertain_high"]) for s in OUT_SEASONS})


def live_days(live_dir: Path) -> list[dict]:
    """Published live days (read only): lead 0 shares by region, the model, `uncertain_high`, and the Emergency cells
    held by the hysteresis (reason `hysteresis_hold` with a raw level below Emergency)."""
    out = []
    for folder in sorted(Path(live_dir).iterdir()):
        if not (folder / "alerts.parquet").is_file() or not (folder / "run.json").is_file():
            continue
        run = json.loads((folder / "run.json").read_text(encoding="utf-8"))
        model = run.get("model")
        model = model.get("dir", model.get("name")) if isinstance(model, dict) else model
        a = pd.read_parquet(folder / "alerts.parquet",
                            columns=["region", "raw_level", "level", "uncertain_high", "reason_codes"])
        for r, g in a.groupby("region"):
            held = g["reason_codes"].fillna("").str.contains("hysteresis_hold") & (g["raw_level"] < lv.EMERGENCY)
            row = {"day": folder.name, "month": int(folder.name[5:7]), "region": str(r), "cells": int(len(g)),
                   "model": Path(str(model)).name, "uncertain_high_share": float(g["uncertain_high"].mean()),
                   "emergency_held": int(((g["level"] >= lv.EMERGENCY) & held).sum())}
            for k in LEVELS:
                row[f"{LEVEL_NAMES[k]}_published"] = float((g["level"] >= k).mean())
                row[f"{LEVEL_NAMES[k]}_raw"] = float((g["raw_level"] >= k).mean())
            out.append(row)
    return out


def live_replays() -> dict | None:
    """Lead-0 level counts of v4 and of v3 on the same replayed live days (reports/phase8_live_replays.json)."""
    path = PROJECT_ROOT / "reports" / "phase8_live_replays.json"
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return {day: {"v4": data["per_day"][day]["after"]["levels"], "v3": data["per_day"][day]["after_v3lead0"]["levels"]}
            for day in data["days"] if {"after", "after_v3lead0"} <= set(data["per_day"][day])}


def slide_counts(cfg: dict, cells: pd.DataFrame) -> dict:
    """Independent slides by set, region and season: development (2007-2017), the W1 held-out events (2018-2025, the
    deciding licence-clean set), and assembly v2 beside (all sources, and without the unlicensed BIPAD register). Only
    dates and cells are read."""
    from . import heldout
    sets = {"development": O.development_events_all()}
    w1 = heldout.load_event_table(cfg)
    sets["heldout_w1"] = w1[pd.to_datetime(w1["date"]).dt.year.isin(bt.SEASON_YEARS)]
    v2 = heldout.assembly_events(data_root() / "processed" / "heldout_v2")
    sets["heldout_v2_all_unlicensed_included"] = v2
    sets["heldout_v2_licence_clean"] = v2[~v2["source"].astype(str).str.contains("bipad", case=False)]
    out = {}
    for name, ev in sets.items():
        ev = ev[["cell_id", "date"]].merge(cells[["cell_id", "region"]], on="cell_id", how="inner")
        ev["season"] = [FL.season_of_month(d.month) for d in pd.to_datetime(ev["date"])]
        out[name] = {}
        for r in REGIONS:
            for s in SEASONS:
                g = ev[(ev["region"] == r) & (ev["season"] == s)][["cell_id", "date"]].drop_duplicates()
                out[name][f"{r}|{s}"] = {"records": int(len(g)), "slides": heldout.distinct_events(g) if len(g) else 0}
    return out


def rain_minimum(rules) -> float | None:
    """The 7-day minimum of the rain cap (the only window `post_rules_v3.json` uses), None for another form."""
    minimum = getattr(rules.rain, "minimum_mm", None) or {}
    return float(minimum[7]) if set(minimum) == {7} else None


def summarise(say=print) -> dict:
    """Step 2: the diagnosis, the candidates, the declared selection with its leave-one-year-out estimate, the live
    days, the slide counts and the power of a held-out look; writes summary.json and the treatment document."""
    cfg, _, rules, card = chain_inputs()
    parts = load_years()
    events = event_table(parts)
    say(f"{len(events)} development events, {events['slide'].nunique()} slides")
    cells = O.load_light(F.panel_path(F.out_dir(), "jun_dec", burden.DEV_YEARS[0])).cells
    selection = {s: select_season(parts, events, s, burden.DEV_YEARS) for s in OUT_SEASONS}
    choices = {s: selection[s]["chosen"] for s in OUT_SEASONS}
    document = treatment_document(choices, card)
    dump_json(document_path(), document)
    counts = slide_counts(cfg, cells)
    loyo_by = {s: loyo(parts, events, s) for s in OUT_SEASONS}
    power = {}
    for s in OUT_SEASONS:
        w1 = sum(counts["heldout_w1"][f"{r}|{s}"]["slides"] for r in REGIONS)
        v2 = sum(counts["heldout_v2_all_unlicensed_included"][f"{r}|{s}"]["slides"] for r in REGIONS)
        dev_slides = int(events[events["season"] == s]["slide"].nunique())
        lost = max(loyo_by[s]["lost"].values())
        q = lost / dev_slides if dev_slides else 0.0
        power[s] = {"heldout_w1_slides": w1, "heldout_v2_all_slides": v2, "development_slides": dev_slides,
                    "development_loyo_max_lost": int(lost), "development_loyo_loss_share": q,
                    "w1_upper_loss_share_if_none_lost": upper_loss_share(w1),
                    "v2_all_upper_loss_share_if_none_lost": upper_loss_share(v2),
                    "w1_chance_veto_fires_at_dev_loss": veto_power(w1, q),
                    "w1_chance_veto_fires_at_10pct_loss": veto_power(w1, 0.10),
                    "has_heldout_panels": s == LOOK_SEASON}
    result = {"created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "spec": SPEC,
              "years": list(burden.DEV_YEARS),
              "candidates_grid": {"scales": list(SCALES), "uncertain_high_out_of_season": list(UNCERTAIN)},
              "rule": {"loss_min": LOSS_MIN, "loss_share": LOSS_SHARE},
              "card_thresholds": {r: card[r].to_dict() for r in REGIONS},
              "diagnosis": diagnosis(parts, events, rain_minimum(rules)),
              "candidates": {s: candidate_table(parts, events, s) for s in OUT_SEASONS},
              "selection": selection, "loyo": loyo_by, "treatment": document,
              "live_days": live_days(live_run.project_path(cfg["live_dir"])), "live_replays": live_replays(),
              "slide_counts": counts, "power": power}
    dump_json(results_dir() / "summary.json", result)
    say(f"chosen: {choices}")
    return result


# ------------------------------------------------------------------------------------- step 3: report and criterion

def declared_criterion(summary: dict) -> dict:
    """The held-out criterion (spec section 6), filled with the development numbers of the selected treatment."""
    from ..manifest import sha256_file
    rows = {row["candidate"]: row for row in summary["candidates"][LOOK_SEASON]}
    chosen = summary["selection"][LOOK_SEASON]["chosen"]
    burden_rows = {}
    for r in REGIONS:
        for k in LEVELS:
            name = LEVEL_NAMES[k]
            today, treat = rows[TODAY_KEY]["regions"][r][name], rows[chosen]["regions"][r][name]
            reduction = None if not today else 1.0 - treat / today
            if reduction is not None and reduction >= BURDEN_MIN_DEV:
                burden_rows[f"{r}|{name}"] = {"today_development_share": today, "treatment_development_share": treat,
                                              "development_reduction": reduction,
                                              "required_heldout_reduction": BURDEN_KEEP * reduction}
    w1 = summary["power"][LOOK_SEASON]["heldout_w1_slides"]
    return {"season": LOOK_SEASON, "treatment": chosen, "treatment_document": str(document_path().name),
            "treatment_document_sha256": sha256_file(document_path()),
            "burden": burden_rows, "burden_keep": BURDEN_KEEP, "burden_min_development_reduction": BURDEN_MIN_DEV,
            "monsoon_identical": True,
            "detection_veto": {"set": "heldout_w1", "slides": w1, "rule": "every W1 slide of the season that today's "
                               "levels detect at a level and tolerance is detected by the treatment at that level and "
                               "tolerance (no slide lost)", "decides_detection": False},
            "beside": ["heldout_v2_all_unlicensed_included", "heldout_v2_licence_clean"],
            "adopt_if": "every burden row passes, June-September is identical, and the veto does not fire"}


def _p(x, digits: int = 2) -> str:
    return "-" if x is None else f"{100 * x:.{digits}f}%"


def _f(x, digits: int = 1) -> str:
    return "-" if x is None else f"{x:,.{digits}f}"


SEASON_TEXT = {"monsoon": "monsoon (Jun-Sep)", "post_monsoon": "post-monsoon (Oct-Dec)", "rest": "rest of year (Jan-May)"}
REGION_TEXT = {"himalaya": "Himalaya", "western_ghats": "Western Ghats"}
BAND_TEXT = ["below 1,000 m", "1,000-2,000 m", "2,000-3,000 m", "3,000-4,000 m", "4,000 m and above"]


def markdown(result: dict) -> str:
    s, d = result["summary"], result["summary"]["diagnosis"]
    crit = result["heldout_criterion"]
    lines = ["# Year-round alerts: what a level means outside June-September (phase 8, development)", "",
             "Development years 2007-2017 only, out of fold, every one of the 36,792 scored cells "
             "(`data/processed/alerts/year_round/summary.json`, from `python -m aetherguard.verify.year_round`). "
             "Nothing here is wired into the live run. A change of the out-of-season levels would be a model change.", ""]
    lines += ["## Answer", ""] + [f"- {x}" for x in result["findings"]] + [""]
    lines += ["## Today's chain by region and season", "",
              "Published share = cell-days at the level or above after the whole chain (`uncertain_high`, rain cap, hold "
              "release, hysteresis). Hits = development events on their own cell and day at the level or above. "
              "Precision = hits per 100,000 alert cell-days. E/O = the summed risk of the alert cell-days over the hits "
              "(1 would be a calibrated tail; the model's risk is a probability of a catalogued slide per cell-day).", "",
              "| region and season | events (slides) | level | published share | hits | hits per 100k alert cell-days | E/O |",
              "|---|---|---|---|---|---|---|"]
    for r in REGIONS:
        for season in SEASONS:
            row = d["strata"].get(f"{r}|{season}")
            if not row:
                continue
            for k in LEVELS:
                e = row[LEVEL_NAMES[k]]
                lines.append(f"| {REGION_TEXT[r]}, {SEASON_TEXT[season]} | {row['events']} ({row['slides']}) | "
                             f"{LEVEL_NAMES[k]} | {_p(e['published_share'])} | {e['hits_exact']} | "
                             f"{_f(e['hits_per_100k'], 2)} | {_f(e['expected_over_observed'], 2)} |")
    lines += ["", "Where the published share comes from (share of cell-days):", "",
              "| region and season | point Watch+ | `uncertain_high` adds (after the rain cap) | published Watch+ | "
              "point Emergency | published Emergency | hold inflation Warning+ / Emergency | 7-day rain at or above the "
              "rule's minimum | events under the rain minimum |", "|---|---|---|---|---|---|---|---|---|"]
    for r in REGIONS:
        for season in SEASONS:
            row = d["strata"].get(f"{r}|{season}")
            if not row:
                continue
            w, wa, em = (row[LEVEL_NAMES[k]] for k in LEVELS)
            rain = d["rain_at_events"].get(f"{r}|{season}", {})
            lines.append(f"| {REGION_TEXT[r]}, {SEASON_TEXT[season]} | {_p(w['point_share'])} | "
                         f"{_p(w['uncertain_added_share'])} | {_p(w['published_share'])} | {_p(em['point_share'])} | "
                         f"{_p(em['published_share'])} | {_f(wa['hold_inflation'], 2)} / {_f(em['hold_inflation'], 2)} | "
                         f"{_p(row['rain_ok_share'], 1)} | {_p(rain.get('share_below_minimum'), 1)} |")
    lines += ["", "Himalaya by elevation band (Watch+ published):", "",
              "| season | band | share of cell-days | events | Watch+ share | hits per 100k Watch+ cell-days |",
              "|---|---|---|---|---|---|"]
    for season in SEASONS:
        total = sum(d["elevation"][f"himalaya|{season}|{b}"]["cell_days"] for b in range(len(BAND_TEXT))
                    if f"himalaya|{season}|{b}" in d["elevation"])
        for b, text in enumerate(BAND_TEXT):
            row = d["elevation"].get(f"himalaya|{season}|{b}")
            if row:
                lines.append(f"| {SEASON_TEXT[season]} | {text} | {_p(row['cell_days'] / total, 1)} | {row['events']} | "
                             f"{_p(row['Watch+']['published_share'], 1)} | {_f(row['Watch+']['hits_per_100k'], 2)} |")
    lines += ["", "## The live days so far (lead 0, published)", "",
              "| month | model | region | days | Watch+ | Warning+ | Emergency | Emergency held by the hysteresis "
              "(cells, summed) |", "|---|---|---|---|---|---|---|---|"]
    for row in result["live_months"]:
        lines.append(f"| {row['month']} | `{row['model']}` | {REGION_TEXT[row['region']]} | {row['days']} | "
                     f"{_p(row['Watch+'])} | {_p(row['Warning+'])} | {_p(row['Emergency'])} | {row['emergency_held']} |")
    if s.get("live_replays"):
        lines += ["", "The same live days replayed with v4 and with v3 at lead 0 (`reports/phase8_live_replays.json`), "
                  "Emergency cells of 36,792:", "", "| day | v4 | v3 |", "|---|---|---|"]
        for day, entry in s["live_replays"].items():
            lines.append(f"| {day} | {entry['v4']['Emergency']} | {entry['v3']['Emergency']} |")
    lines += ["", "## Candidates (out of season only; June-September is today's chain in every candidate)", "",
              "`m` = the per-season risk scale (thresholds times m), `u` = `uncertain_high` out of season. Hits are "
              "independent slides (records within 10 km and a day merged), cell-exact / tolerant (10 km, 1 day).", ""]
    for season in OUT_SEASONS:
        lines += [f"### {SEASON_TEXT[season]}", "",
                  "| candidate | Himalaya Watch+ / Warning+ / Emergency | Western Ghats Watch+ / Warning+ / Emergency | "
                  "Watch+ hits | Warning+ hits | Emergency hits |", "|---|---|---|---|---|---|"]
        for row in s["candidates"][season]:
            reg = [" / ".join(_p(row["regions"][r][LEVEL_NAMES[k]]) for k in LEVELS) for r in REGIONS]
            hits = [f"{row['hits'][f'cell_exact|{k}']} / {row['hits'][f'tolerant|{k}']}" for k in LEVELS]
            mark = " (chosen)" if row["candidate"] == s["selection"][season]["chosen"] else ""
            lines.append(f"| `{row['candidate']}`{mark} | {reg[0]} | {reg[1]} | {' | '.join(hits)} |")
        sel, lo = s["selection"][season], s["loyo"][season]
        red = " / ".join(_p(x, 0) for x in lo["reduction"])
        lost = ", ".join(f"{k} {v}" for k, v in lo["lost"].items())
        lines += ["", f"Declared rule: at most {sel['allowed_loss']} slide(s) lost against today at every level and "
                  f"tolerance; then the fewest Emergency, Warning+, Watch+ cell-days. Chosen on all 11 years: "
                  f"`{sel['chosen']}` (largest loss {sel['max_loss']}). Leave one year out (the rule re-chosen without "
                  f"the year, then applied to it): published cell-days reduced {red} (Watch+ / Warning+ / Emergency); "
                  f"slides lost: {lost}.", ""]
    lines += ["## Ground truth outside the monsoon (independent slides)", "",
              "| set | " + " | ".join(f"{REGION_TEXT[r]} {SEASON_TEXT[x]}" for r in REGIONS for x in SEASONS) + " |",
              "|---|" + "---|" * (len(REGIONS) * len(SEASONS))]
    names = {"development": "development 2007-2017", "heldout_w1": "held-out W1 2018-2025 (deciding)",
             "heldout_v2_licence_clean": "held-out v2 without BIPAD",
             "heldout_v2_all_unlicensed_included": "held-out v2 with BIPAD (unlicensed, local only, not deciding)"}
    for name, text in names.items():
        lines.append(f"| {text} | " + " | ".join(str(s["slide_counts"][name][f"{r}|{x}"]["slides"])
                                                 for r in REGIONS for x in SEASONS) + " |")
    lines += ["", "What a held-out look could decide:", ""]
    for season in OUT_SEASONS:
        p = s["power"][season]
        lines.append(f"- {SEASON_TEXT[season]}: {p['heldout_w1_slides']} W1 slide(s). If none were lost, the loss could "
                     f"still be up to {_p(p['w1_upper_loss_share_if_none_lost'], 0)} of slides (one-sided 95%). A "
                     f"treatment losing 10% of slides would lose at least one of them with chance "
                     f"{_p(p['w1_chance_veto_fires_at_10pct_loss'], 0)}. With BIPAD ({p['heldout_v2_all_slides']} slides) "
                     f"the bound would be {_p(p['v2_all_upper_loss_share_if_none_lost'], 1)}. Held-out panels: "
                     f"{'yes (alerts/v4_seasons)' if p['has_heldout_panels'] else 'none (IMERG half-hourly files for January-May 2018-2025 are not on disk)'}.")
    lines += ["", "## The held-out look (declared before any held-out number; the lead's, once)", "",
              f"Command: `python -m aetherguard.verify.year_round heldout`. Season: {SEASON_TEXT[crit['season']]} "
              f"2018-2025 on `alerts/v4_seasons`. Treatment `{crit['treatment']}` "
              f"(`{crit['treatment_document']}`, sha256 `{crit['treatment_document_sha256'][:16]}...`).", "",
              "1. Burden (decides): in every region and level below, the held-out published share falls by at least "
              f"{crit['burden_keep']:.0%} of the development reduction, paired with today's levels on the same days:", "",
              "| region and level | development today | development treatment | development reduction | required held-out "
              "reduction |", "|---|---|---|---|---|"]
    for k, row in crit["burden"].items():
        r, name = k.split("|")
        lines.append(f"| {REGION_TEXT[r]} {name} | {_p(row['today_development_share'])} | "
                     f"{_p(row['treatment_development_share'])} | {_p(row['development_reduction'], 0)} | "
                     f"{_p(row['required_heldout_reduction'], 0)} |")
    lines += ["", "2. June-September published levels identical cell-day by cell-day (a check of the construction).",
              f"3. Detection veto, W1 ({crit['detection_veto']['slides']} slide(s)): {crit['detection_veto']['rule']}. "
              "It cannot show that detection is not worse (section above); it only stops adoption if a slide is lost.",
              "4. Beside, not deciding: the same paired detection on assembly v2 with and without BIPAD.", "",
              "Adopt only if 1-3 pass. Adoption still changes published levels (a model change): it needs a reviewed "
              "wiring step and the user's yes. January-May has no held-out panels and stays development-only.", ""]
    if result.get("heldout"):
        lines += heldout_lines(result["heldout"])
    lines += ["## Caveats", ""] + [f"- {x}" for x in CAVEATS] + [""]
    return "\n".join(lines)


CAVEATS = [
    "Detection counts what the catalogues recorded. They miss most landslides and report them where people live and "
    "when people look; out-of-season slides may be reported less often than monsoon slides, which would make the "
    "out-of-season precision and E/O look worse than they are. The catalogues cannot separate this from a model that "
    "over-predicts out of season.",
    "Out of the monsoon the development events are few (counts in the tables), so every out-of-season detection "
    "number has a wide interval; the leave-one-year-out estimate is the honest one for the selected rule.",
    "Tolerant matching (10 km, 1 day) has a high chance floor at Watch+.",
    "The development panels have no blind-escalation rule (it needs the live IMD comparison); January-May starts each "
    "year cold (no hysteresis carried over New Year).",
    "The live days so far are 2026-10-09 onwards, mostly scored by v3; one month of live weather cannot separate weather "
    "from a train/serve gap.",
]


def live_months(rows: list[dict]) -> list[dict]:
    frame = pd.DataFrame(rows)
    if frame.empty:
        return []
    out = []
    for (month, model, region), g in frame.groupby(["month", "model", "region"]):
        out.append({"month": int(month), "model": model, "region": region, "days": int(len(g)),
                    **{LEVEL_NAMES[k]: float(g[f"{LEVEL_NAMES[k]}_published"].mean()) for k in LEVELS},
                    "emergency_held": int(g["emergency_held"].sum())})
    return out


def findings(summary: dict) -> list[str]:
    """The answer, written from the numbers."""
    d = summary["diagnosis"]["strata"]
    out = []
    for r in REGIONS:
        mon = d[f"{r}|monsoon"]
        for season in OUT_SEASONS:
            row = d[f"{r}|{season}"]
            parts = []
            for k in (lv.WATCH, lv.EMERGENCY):
                a, b = row[LEVEL_NAMES[k]]["hits_per_100k"], mon[LEVEL_NAMES[k]]["hits_per_100k"]
                parts.append(f"{LEVEL_NAMES[k]} {_f(a, 2)} against {_f(b, 2)}")
            eo = (row["Watch+"]["expected_over_observed"], mon["Watch+"]["expected_over_observed"])
            out.append(f"{REGION_TEXT[r]}, {SEASON_TEXT[season]}: published Emergency {_p(row['Emergency']['published_share'])} "
                       f"(monsoon {_p(mon['Emergency']['published_share'])}), but hits per 100k alert cell-days "
                       f"{'; '.join(parts)} in the monsoon; E/O at Watch+ {_f(eo[0], 2)} against {_f(eo[1], 2)} "
                       f"({row['events']} events).")
    return out


def build_report(say=print) -> dict:
    summary = json.loads((results_dir() / "summary.json").read_text(encoding="utf-8"))
    result = {"created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "spec": SPEC, "summary": summary,
              "live_months": live_months(summary["live_days"]), "findings": findings(summary),
              "heldout_criterion": declared_criterion(summary)}
    path = heldout_path()
    if path.is_file():
        result["heldout"] = json.loads(path.read_text(encoding="utf-8"))
        result["heldout_criterion"] = result["heldout"]["declared"]
    reports = PROJECT_ROOT / "reports"
    dump_json(reports / f"{REPORT_STEM}.json", result)
    (reports / f"{REPORT_STEM}.md").write_text(markdown(result), encoding="utf-8")
    say(f"written reports/{REPORT_STEM}.json and .md")
    return result


# ------------------------------------------------------------------------------------------- step 4: the look

def heldout_path() -> Path:
    return results_dir() / "heldout.json"


def started_path() -> Path:
    return results_dir() / "heldout.started"


def committed_criterion() -> dict:
    report = json.loads((PROJECT_ROOT / "reports" / f"{REPORT_STEM}.json").read_text(encoding="utf-8"))
    return report["heldout_criterion"]


def heldout_years():
    """(year, light v4 held-out season panel) of 2018-2025, cells checked against the held-out reference order."""
    from . import heldout
    reference = H.load_panel(H.alerts_dir(H.HELDOUT_DIR) / H.HELDOUT_FILE).cells["cell_id"].to_numpy()
    for year in bt.SEASON_YEARS:
        panel = O.load_light(H.alerts_dir(P.V4_SEASONS) / f"season_{year}_v4.npz")
        heldout.check_cell_order(panel.cells["cell_id"].to_numpy(), reference, f"v4 season {year}")
        yield year, panel, reference


def preflight(say=print) -> dict:
    """Everything the look needs, checked without reading an event: the committed criterion names the treatment file
    by its hash, every held-out panel loads in the reference cell order, and no look was started."""
    from ..manifest import sha256_file
    for path in (heldout_path(), started_path()):
        if path.exists():
            raise FileExistsError(f"{path.name} exists: the look was taken or started")
    crit = committed_criterion()
    if sha256_file(document_path()) != crit["treatment_document_sha256"]:
        raise ValueError("the treatment document changed after the criterion was committed")
    panels = {}
    for year, panel, _ in heldout_years():
        path = H.alerts_dir(P.V4_SEASONS) / f"season_{year}_v4.npz"
        months = {d.month for d in panel.days}
        if not {10, 11, 12} <= months:
            raise ValueError(f"{path.name}: no October-December days")
        panels[str(year)] = {"sha256": sha256_file(path), "days": len(panel.days)}
        say(f"{path.name}: {len(panel.days)} days")
    out = {"created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "criterion": crit, "panels": panels,
           "passed": True}
    dump_json(results_dir() / "preflight.json", out)
    return out


def decide(declared: dict, look: dict) -> dict:
    conditions = []
    for k, row in declared["burden"].items():
        got = look["burden_reduction"][k]
        need = row["required_heldout_reduction"]
        conditions.append({"condition": f"burden {k}", "heldout_reduction": got, "required": need,
                           "passed": bool(got is not None and got >= need)})
    conditions.append({"condition": "June-September identical", "differing_cell_days": look["monsoon_differing"],
                       "passed": look["monsoon_differing"] == 0})
    lost = look["detection"]["heldout_w1"]["lost"]
    conditions.append({"condition": "detection veto (W1)", "lost": lost, "passed": max(lost.values(), default=0) == 0})
    return {"adopt": all(c["passed"] for c in conditions), "conditions": conditions,
            "failed": [c["condition"] for c in conditions if not c["passed"]]}


def paired_detection(levels_t: np.ndarray, levels_b: np.ndarray, cell_ids, days, events: pd.DataFrame) -> dict:
    """Slides of `events` in the look season detected by today's levels and by the treatment, per tolerance and level."""
    from . import heldout
    out = {"slides": 0, "today": {}, "treatment": {}, "lost": {}}
    for t, tol in O.TOLERANCES.items():
        mt = match(levels_t, cell_ids, days, events, tol)
        mb = match(levels_b, cell_ids, days, events, tol)
        e = mt.events
        inside = np.array([FL.season_of_month(pd.Timestamp(x).month) == LOOK_SEASON for x in e["date"]], dtype=bool)
        if not inside.any():
            for k in LEVELS:
                out["today"][f"{t}|{k}"] = out["treatment"][f"{t}|{k}"] = out["lost"][f"{t}|{k}"] = 0
            continue
        labels = heldout.event_clusters(e[inside])
        out["slides"] = int(len(np.unique(labels)))
        for k in LEVELS:
            b = slide_hits(mb.event_level[inside], labels, k)
            a = slide_hits(mt.event_level[inside], labels, k)
            out["today"][f"{t}|{k}"], out["treatment"][f"{t}|{k}"] = b, a
            out["lost"][f"{t}|{k}"] = b - a
    return out


def heldout_look(say=print) -> dict:
    """THE look (spec section 6): the treatment and today's levels on the held-out October-December days, the paired
    burden, the June-September identity check and the paired detection of the W1 slides (v2 beside). Refuses when a
    look was taken or started; writes the started marker first so a crash cannot lead to a second look."""
    from . import heldout
    for path in (heldout_path(), started_path()):
        if path.exists():
            raise FileExistsError(f"{path.name} exists: this study's one held-out look was taken or started")
    pre = results_dir() / "preflight.json"
    if not pre.is_file():
        raise FileNotFoundError("run `preflight` first")
    declared = committed_criterion()
    document = json.loads(document_path().read_text(encoding="utf-8"))
    from ..manifest import sha256_file
    if sha256_file(document_path()) != declared["treatment_document_sha256"]:
        raise ValueError("the treatment document changed after the criterion was committed")
    started_path().write_text(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) + "\n", encoding="utf-8")
    scales, uncertain = document_treatment(document)
    cfg, config, rules, card = chain_inputs()
    counts = {"today": {}, "treatment": {}}
    monsoon_differing = 0
    days, treat_all, base_all, cell_ids = [], [], [], None
    for year, panel, reference in heldout_years():
        say(f"held-out season {year}")
        y = O.Year.from_panel(year, panel, panel.days.index(date(year, 6, 1)))
        base = treatment_levels(y, card, config, rules, {}, True)["published"]
        treat = treatment_levels(y, card, config, rules, scales, uncertain[LOOK_SEASON])["published"]
        mon = y.season == SEASONS.index("monsoon")
        monsoon_differing += int((base[:, mon] != treat[:, mon]).sum())
        for name, levels in (("today", base), ("treatment", treat)):
            for k, v in stratum_counts(levels, y.scored, y.region, y.season).items():
                acc = counts[name].setdefault(k, np.zeros(4, np.int64))
                acc += np.asarray(v, np.int64)
        days += y.days
        treat_all.append(treat)
        base_all.append(base)
        cell_ids = y.cell_ids
        del panel, y
    treat_all, base_all = np.concatenate(treat_all, axis=1), np.concatenate(base_all, axis=1)
    reduction = {}
    for r in REGIONS:
        b, t = counts["today"][f"{r}|{LOOK_SEASON}"], counts["treatment"][f"{r}|{LOOK_SEASON}"]
        for i, k in enumerate(LEVELS):
            reduction[f"{r}|{LEVEL_NAMES[k]}"] = None if not b[i + 1] else float(1.0 - t[i + 1] / b[i + 1])
    sets = {"heldout_w1": heldout.load_event_table(cfg)}
    v2 = heldout.assembly_events(data_root() / "processed" / "heldout_v2")
    sets["heldout_v2_all_unlicensed_included"] = v2
    sets["heldout_v2_licence_clean"] = v2[~v2["source"].astype(str).str.contains("bipad", case=False)]
    detection = {}
    for name, ev in sets.items():
        ev = ev[pd.to_datetime(ev["date"]).dt.year.isin(bt.SEASON_YEARS)]
        kept, _ = heldout.events_on_days(ev, days)
        detection[name] = paired_detection(treat_all, base_all, cell_ids, days, kept)
    look = {"burden": {n: {k: (v / v[0]).tolist() if v[0] else None for k, v in c.items()} for n, c in counts.items()},
            "burden_reduction": reduction, "monsoon_differing": monsoon_differing, "detection": detection}
    result = {"created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "declared": declared, "look": look,
              "decision": decide(declared, look)}
    text = json.dumps(jsonable(result), indent=2, allow_nan=False)
    with open(heldout_path(), "x", encoding="utf-8") as handle:
        handle.write(text + "\n")
    say(f"adopt: {result['decision']['adopt']} failed: {result['decision']['failed']}")
    return result


def heldout_lines(look: dict) -> list[str]:
    dec = look["decision"]
    lines = ["## The held-out look: " + ("ADOPT by the declared rule" if dec["adopt"] else "NOT adopted"), "",
             "| condition | held-out | required | passed |", "|---|---|---|---|"]
    for c in dec["conditions"]:
        if "heldout_reduction" in c:
            lines.append(f"| {c['condition']} | {_p(c['heldout_reduction'], 0)} | {_p(c['required'], 0)} | {c['passed']} |")
        elif "lost" in c:
            lines.append(f"| {c['condition']} | lost {c['lost']} | none lost | {c['passed']} |")
        else:
            lines.append(f"| {c['condition']} | {c['differing_cell_days']} differing | 0 | {c['passed']} |")
    for name, det in look["look"]["detection"].items():
        lines.append("")
        lines.append(f"{name}: {det['slides']} slide(s); today {det['today']}, treatment {det['treatment']}.")
    return lines + [""]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m aetherguard.verify.year_round", description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=["panels", "summarise", "report", "preflight", "heldout"])
    args = parser.parse_args(argv)
    say = lambda m: print(m, flush=True)       # noqa: E731
    {"panels": panels, "summarise": summarise, "report": build_report, "preflight": preflight,
     "heldout": heldout_look}[args.command](say=say)
    return 0


if __name__ == "__main__":
    sys.exit(main())
