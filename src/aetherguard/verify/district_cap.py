"""A district level whose frequency a district officer can act on (spec 2026-11-17-aetherguard-district-cap).

    python -m aetherguard.verify.district_cap counts --window jun_dec|jan_may   # cell levels -> district counts (heavy)
    python -m aetherguard.verify.district_cap fit                              # the curve, the choice, the rule file
    python -m aetherguard.verify.district_cap report                           # reports/phase8_district_cap.{json,md}
    python -m aetherguard.verify.district_cap heldout                          # THE look; the lead's, once

Why. A district takes today's published cell levels (option A; `operating_options.chain_levels` with the card's
thresholds). With "any cell" (R0) it is alerted on most days, because a district holds a median of 49 cells. Here the
district is at level L when the share f_L of its scored cells at L or above reaches s_L. The shares are set by a frequency
cap on district-days: one share per region, season and level (family F1), or one per district, season and level (F2).

Protocol (spec sections 2-5). Development only (2007-2017 out-of-fold panels on every scored cell). The shares of the curve
are fitted leave-one-year-out, so every year is scored with shares that never saw it. The choice rule, the cost ratios,
the chance floor and the held-out criterion are those declared in the spec before this module first ran. `heldout` is the
one confirming look, which refuses to run twice. The rule is not wired anywhere.
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
from ..alerts.config import load_config_file as load_alert_config
from ..config import PROJECT_ROOT, data_root
from ..hazard.jsonio import dump_json, jsonable
from ..live import backtest as bt
from ..live import burden
from ..live import hardening as H
from ..live import post_rules_v4 as P
from ..live import postrules as pr
from ..live import run as live_run
from ..serve import districts as DI
from . import operating_options as oo

LEVELS = (1, 2, 3)
LEVEL_NAMES = oo.LEVEL_NAMES
LADDERS = {1: (0.50, 0.40, 0.30, 0.20, 0.15, 0.10, 0.05),
           2: (0.25, 0.18, 0.12, 0.08, 0.06, 0.04, 0.02),
           3: (0.10, 0.06, 0.04, 0.03, 0.02, 0.01, 0.005)}
MIN_SHARE = 1e-9                    # "any cell": a positive share, so at least one cell is always needed
KEEP = 0.90                         # spec section 4: keep this share of R0's within-1-day coverage
FAMILIES = ("F1_stratum", "F2_district")
READINGS = ("same_day", "within_1_day")
BURDEN_FACTOR = 1.5
MARGIN_SD = 2.0
HELDOUT_SLIDES = 87
RESULTS = "district_cap"            # under data/processed/alerts/
REPORT_STEM = "phase8_district_cap"
HELDOUT_FILE = "heldout.json"


def results_dir() -> Path:
    return data_root() / "processed" / "alerts" / RESULTS


# ------------------------------------------------------------------------------------- pure building blocks

def district_counts(levels: np.ndarray, scored: np.ndarray, index: np.ndarray, n_districts: int
                    ) -> tuple[np.ndarray, np.ndarray]:
    """(count (districts, days, 3): scored cells at each level or above, n (districts, days): scored cells) from cell
    levels (cells, days); `index` is each cell's district (-1: none, left out)."""
    levels, scored, index = np.asarray(levels), np.asarray(scored, dtype=bool), np.asarray(index, dtype=np.int64)
    keep = index >= 0
    count = np.zeros((n_districts, levels.shape[1], len(LEVELS)), dtype=np.int32)
    n = np.zeros((n_districts, levels.shape[1]), dtype=np.int32)
    if keep.any():
        np.add.at(n, index[keep], scored[keep].astype(np.int32))
        for k, level in enumerate(LEVELS):
            np.add.at(count[:, :, k], index[keep], ((levels[keep] >= level) & scored[keep]).astype(np.int32))
    return count, n


def shares(count: np.ndarray, n: np.ndarray) -> np.ndarray:
    """f (districts, days, 3): the share of scored cells at each level or above; NaN where no cell is scored."""
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(n[..., None] > 0, count / np.maximum(n, 1)[..., None], np.nan)


def share_threshold(values: np.ndarray, cap: float) -> float:
    """The lowest share at which at most `cap` of the (finite) district-days reach it, never below MIN_SHARE."""
    return max(FL.cap_threshold(values, cap), MIN_SHARE)


def loyo_thresholds(by_year: dict[int, np.ndarray], cap: float) -> dict[int, float]:
    """Per year the `share_threshold` of the values of every OTHER year."""
    out = {}
    for year in by_year:
        others = [v.ravel() for y, v in by_year.items() if y != year]
        out[year] = share_threshold(np.concatenate(others) if others else np.zeros(0), cap)
    return out


def district_level(f: np.ndarray, s: np.ndarray) -> np.ndarray:
    """(districts, days) level: the highest L with f_L >= s_L (NaN never reaches)."""
    reached = np.asarray(f) >= np.asarray(s)
    return np.where(reached[..., 2], 3, np.where(reached[..., 1], 2, np.where(reached[..., 0], 1, 0))).astype(np.int8)


def coverage(alerted: np.ndarray, district: np.ndarray, day: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(same_day, within_1_day) per event: its district (-1: none) alerted on its day, or on a day either side."""
    alerted = np.asarray(alerted, dtype=bool)
    district, day = np.asarray(district, dtype=np.int64), np.asarray(day, dtype=np.int64)
    ok = district >= 0
    d = np.maximum(district, 0)
    same = ok & alerted[d, day]
    near = same.copy()
    for shift in (-1, 1):
        t = day + shift
        inside = (t >= 0) & (t < alerted.shape[1])
        near |= ok & inside & alerted[d, np.clip(t, 0, alerted.shape[1] - 1)]
    return same, near


def within_1_day(alerted: np.ndarray) -> np.ndarray:
    out = alerted.copy()
    out[:, 1:] |= alerted[:, :-1]
    out[:, :-1] |= alerted[:, 1:]
    return out


def decide(declared: dict, look: dict) -> dict:
    """The criterion of spec section 5, literally (keys "region|season|level" and "reading|level")."""
    conditions = []
    for key, expected in declared["burden"].items():
        got, limit = look["burden"][key], expected * declared["burden_factor"]
        conditions.append({"condition": f"burden {key}", "development": expected, "heldout": got, "limit": limit,
                           "passed": bool(got <= limit)})
    for key, entry in declared["loss"].items():
        got, base = look["coverage"][key], look["base_coverage"][key]
        lost = base["hits"] - got["hits"]
        allowed = entry["share"] * got["of"] + entry["margin_slides"]
        conditions.append({"condition": f"coverage lost against R0 {key}", "development_loss_share": entry["share"],
                           "heldout_lost": lost, "allowed": allowed, "passed": bool(lost <= allowed)})
    return {"confirmed": all(c["passed"] for c in conditions), "conditions": conditions,
            "failed": [c["condition"] for c in conditions if not c["passed"]]}


# --------------------------------------------------------------------------------- stage 1: district counts

def counts_path(window: str, year: int) -> Path:
    return results_dir() / f"counts_{window}_{year}.npz"


def a_thresholds(window: str, card: dict) -> dict:
    return {(r, s): tuple(float(v) for v in card[r].as_array()) for r in oo.REGIONS for s in oo.WINDOW_SEASONS[window]}


def chain_inputs():
    cfg = live_run.load_run_config()
    return (load_alert_config(live_run.project_path(cfg["alert_config"])),
            pr.load_rules(live_run.project_path(cfg["post_rules"])), oo.card_thresholds())


def counts(window: str, say=print, years=burden.DEV_YEARS) -> None:
    """Today's published cell levels of every development year of `window`, summed per district (resumable per year)."""
    config, rules, card = chain_inputs()
    events = oo.development_events_all(years)
    thresholds = a_thresholds(window, card)
    results_dir().mkdir(parents=True, exist_ok=True)
    for y in oo.years_of(window, events, years):
        path = counts_path(window, y.year)
        if path.is_file():
            say(f"{window} {y.year}: exists")
            continue
        started = time.perf_counter()
        index, info = oo.district_index(y.cell_ids, y.region)
        _, _, published = oo.chain_levels(y, thresholds, card, config, rules)
        count, n = district_counts(published, y.scored, index, len(info))
        rows = pd.Index(y.cell_ids).get_indexer(y.events["cell_id"].to_numpy(dtype=np.int64))
        cols = pd.Index(pd.to_datetime(y.days)).get_indexer(pd.to_datetime(y.events["date"]))
        part = path.with_name(path.name + ".part.npz")
        np.savez_compressed(part, count=count.astype(np.int16), n=n.astype(np.int16), season=y.season,
                            days=np.array([d.isoformat() for d in y.days]), event_district=index[rows],
                            event_day=cols, event_cell=y.events["cell_id"].to_numpy(dtype=np.int64),
                            event_date=np.array([str(pd.Timestamp(d).date()) for d in y.events["date"]]))
        part.replace(path)
        info_path = results_dir() / "districts.json"
        if not info_path.is_file():
            dump_json(info_path, {"districts": info.to_dict(orient="list"), "attribution": DI.ATTRIBUTION})
        say(f"{window} {y.year}: {len(info)} districts, {len(y.events)} events, {time.perf_counter() - started:.0f}s")
        del published, y


# ------------------------------------------------------------------------------------------ stage 2: fit

class Data:
    """Every cached year: f (districts, days, 3), the season of each day, the events (district, day, slide label)."""

    def __init__(self, windows=tuple(oo.WINDOW_SEASONS), years=burden.DEV_YEARS):
        info = json.loads((results_dir() / "districts.json").read_text(encoding="utf-8"))["districts"]
        self.region = np.asarray(info["region"], dtype=str)
        self.n_districts = len(self.region)
        self.parts = []                     # (window, year, f, season, events frame)
        frames = []
        for window in windows:
            for year in years:
                path = counts_path(window, year)
                if not path.is_file():
                    continue
                with np.load(path, allow_pickle=False) as z:
                    f = shares(z["count"].astype(np.int32), z["n"].astype(np.int32)).astype(np.float32)
                    ev = pd.DataFrame({"district": z["event_district"], "day": z["event_day"], "cell_id": z["event_cell"],
                                       "date": pd.to_datetime(z["event_date"])})
                    season = z["season"].astype(int)
                ev["season"] = [FL.season_of_month(d.month) for d in ev["date"]]
                ev["region"] = np.where(ev["district"] >= 0, self.region[np.maximum(ev["district"], 0)], "none")
                ev["part"] = len(self.parts)
                self.parts.append((window, year, f, season, ev))
                frames.append(ev)
        if not self.parts:
            raise FileNotFoundError("no district counts: run `counts` first")
        self.events = pd.concat(frames, ignore_index=True)
        self.labels = oo.slide_labels(self.events[["cell_id", "date"]])
        self.windows = sorted({p[0] for p in self.parts})

    def strata(self) -> list[tuple[str, str]]:
        seasons = [s for w in self.windows for s in oo.WINDOW_SEASONS[w]]
        return [(r, s) for r in oo.REGIONS for s in seasons]


def _values(f, season, rows, s_index, level):
    return f[np.ix_(rows, season == s_index)][..., level - 1]


def fit_thresholds(data: Data, family: str, level: int, cap: float, exclude_year: int | None) -> np.ndarray:
    """(districts, 3 seasons) shares of `family` for one level and cap, fitted on every year but `exclude_year`."""
    out = np.full((data.n_districts, len(FL.SEASON_NAMES)), np.nan)
    for s_index, season in enumerate(FL.SEASON_NAMES):
        parts = [p for p in data.parts if p[1] != exclude_year and season in oo.WINDOW_SEASONS[p[0]]]
        if not parts:
            continue
        if family == "R0":
            out[:, s_index] = MIN_SHARE
        elif family == "F1_stratum":
            for r in oo.REGIONS:
                rows = data.region == r
                values = np.concatenate([_values(f, se, rows, s_index, level).ravel() for _, _, f, se, _ in parts])
                out[rows, s_index] = share_threshold(values, cap)
        else:
            stacked = [f[:, se == s_index, level - 1] for _, _, f, se, _ in parts]
            pooled = np.concatenate(stacked, axis=1)
            for d in range(data.n_districts):
                out[d, s_index] = share_threshold(pooled[d], cap)
    return out


def evaluate(data: Data, s_by_year: dict, level: int | None) -> dict:
    """Per stratum and level (the one `level`, or all three combined by `district_level` when None): district-day share,
    the within-1-day share (the chance floor), days per week per district, and the coverage of every event.

    `s_by_year[(window, year)]` is (districts, 3 seasons, 3 levels) shares."""
    levels = LEVELS if level is None else (level,)
    acc = {(k, L): {"alerted": 0, "near": 0, "days": 0, "per_district": np.zeros((data.n_districts, 2))}
           for k in data.strata() for L in levels}
    hits = {L: {r: np.zeros(len(data.events), dtype=bool) for r in READINGS} for L in levels}
    for window, year, f, season, ev in data.parts:
        s = s_by_year[(window, year)][:, season, :]                     # (districts, days, 3)
        if level is None:
            lev = district_level(f, s)
            alerted_by = {L: lev >= L for L in LEVELS}
        else:
            alerted_by = {level: f[..., level - 1] >= s[..., level - 1]}
        valid = np.isfinite(f[..., 0])
        for L, alerted in alerted_by.items():
            alerted = alerted & valid
            near = within_1_day(alerted) & valid
            for (r, sname) in data.strata():
                rows, cols = data.region == r, season == FL.SEASON_NAMES.index(sname)
                if not cols.any():
                    continue
                a = acc[((r, sname), L)]
                block = np.ix_(rows, cols)
                a["alerted"] += int(alerted[block].sum())
                a["near"] += int(near[block].sum())
                a["days"] += int(valid[block].sum())
                a["per_district"][rows, 0] += alerted[block].sum(axis=1)
                a["per_district"][rows, 1] += valid[block].sum(axis=1)
            if len(ev):
                same, nr = coverage(alerted, ev["district"].to_numpy(), ev["day"].to_numpy())
                idx = np.flatnonzero(data.events["part"].to_numpy() == ev["part"].iloc[0])
                hits[L]["same_day"][idx] = same
                hits[L]["within_1_day"][idx] = nr
    out = {}
    for (k, L), a in acc.items():
        r, sname = k
        rows = data.region == r
        pd_ = a["per_district"][rows]
        per_week = np.where(pd_[:, 1] > 0, pd_[:, 0] / np.maximum(pd_[:, 1], 1) * 7.0, np.nan)
        inside = ((data.events["region"] == r) & (data.events["season"] == sname)).to_numpy()
        entry = {"district_days": a["alerted"], "share": a["alerted"] / a["days"] if a["days"] else None,
                 "chance_floor_within_1_day": a["near"] / a["days"] if a["days"] else None,
                 "days_per_week": {"median": float(np.nanmedian(per_week)), "p90": float(np.nanquantile(per_week, 0.9)),
                                   "max": float(np.nanmax(per_week))},
                 "events": int(inside.sum())}
        for reading in READINGS:
            hit = hits[L][reading][inside]
            boot = oo.cluster_bootstrap(hit, data.labels[inside])
            entry[reading] = {"hits": int(hit.sum()), "coverage": boot["share"][0], "ci": boot["ci"][0],
                              "district_days_per_event": a["alerted"] / hit.sum() if hit.sum() else None}
        out.setdefault(f"{r}|{sname}", {})[LEVEL_NAMES[L]] = entry
    out["_hits"] = {LEVEL_NAMES[L]: {r: hits[L][r] for r in READINGS} for L in levels}
    return out


def s_loyo(data: Data, family: str, caps: dict[int, float]) -> dict:
    """{(window, year): (districts, 3 seasons, 3 levels)} leave-one-year-out shares for per-level caps `caps`
    (a level without a cap is R0)."""
    out = {}
    years = sorted({p[1] for p in data.parts})
    fitted = {}
    for year in years:
        s = np.full((data.n_districts, len(FL.SEASON_NAMES), len(LEVELS)), MIN_SHARE)
        for L, cap in caps.items():
            if cap is not None:
                s[:, :, L - 1] = np.nan_to_num(fit_thresholds(data, family, L, cap, year), nan=MIN_SHARE)
        fitted[year] = s
    for window, year, *_ in data.parts:
        out[(window, year)] = fitted[year]
    return out


def jun_dec_mask(data: Data) -> np.ndarray:
    return (data.events["season"].isin(oo.WINDOW_SEASONS["jun_dec"]) & (data.events["district"] >= 0)).to_numpy()


def pooled_jun_dec(result: dict, level_name: str, reading: str, hits_key: str = "hits") -> tuple[int, int]:
    keys = [k for k in result if not k.startswith("_") and k.split("|")[1] in oo.WINDOW_SEASONS["jun_dec"]]
    return (sum(result[k][level_name][reading][hits_key] for k in keys), sum(result[k][level_name]["events"] for k in keys))


def fit(say=print) -> dict:
    """The curve of both families (leave-one-year-out), the choice of spec section 4, the final rule and its numbers."""
    started = time.perf_counter()
    data = Data()
    say(f"{len(data.parts)} panel-years, {data.n_districts} districts, {len(data.events)} events")
    r0 = evaluate(data, s_loyo(data, "R0", {}), None)
    curve = {}
    for family in FAMILIES:
        curve[family] = {}
        for L in LEVELS:
            steps = []
            for cap in LADDERS[L]:
                say(f"{family} {LEVEL_NAMES[L]} cap {cap:.3f}")
                steps.append({"cap": cap, "result": evaluate(data, s_loyo(data, family, {L: cap}), L)})
            curve[family][LEVEL_NAMES[L]] = steps
    choice = {}
    for family in FAMILIES:
        caps = {}
        for L in LEVELS:
            name = LEVEL_NAMES[L]
            base_hits, events = pooled_jun_dec(r0, name, "within_1_day")
            keeping = [x["cap"] for x in curve[family][name]
                       if pooled_jun_dec(x["result"], name, "within_1_day")[0] >= KEEP * base_hits]
            caps[L] = min(keeping) if keeping else None
        combined = evaluate(data, s_loyo(data, family, caps), None)
        p90 = combined["himalaya|monsoon"]["Emergency"]["days_per_week"]["p90"]
        choice[family] = {"caps": {LEVEL_NAMES[L]: c for L, c in caps.items()}, "combined": combined,
                          "himalaya_monsoon_emergency_p90_days_per_week": p90}
    chosen = min(FAMILIES, key=lambda f: (choice[f]["himalaya_monsoon_emergency_p90_days_per_week"], f != "F1_stratum"))
    caps = {L: choice[chosen]["caps"][LEVEL_NAMES[L]] for L in LEVELS}
    final = np.full((data.n_districts, len(FL.SEASON_NAMES), len(LEVELS)), MIN_SHARE)
    for L, cap in caps.items():
        if cap is not None:
            final[:, :, L - 1] = np.nan_to_num(fit_thresholds(data, chosen, L, cap, None), nan=MIN_SHARE)
    rule = {"family": chosen, "caps": {LEVEL_NAMES[L]: c for L, c in caps.items()}, "shares": final.tolist(),
            "seasons": list(FL.SEASON_NAMES), "levels": [LEVEL_NAMES[L] for L in LEVELS],
            "districts": json.loads((results_dir() / "districts.json").read_text(encoding="utf-8"))["districts"],
            "fitted_on": "2007-2017 development, every year", "attribution": DI.ATTRIBUTION,
            "status": "a candidate district rule; the live run does not read it"}
    dump_json(results_dir() / "rule.json", jsonable(rule))
    result = {"windows": data.windows, "events": int(len(data.events)),
              "events_without_district": int((data.events["district"] < 0).sum()),
              "slides": int(len(np.unique(data.labels))), "districts": data.n_districts,
              "ladders": {LEVEL_NAMES[k]: v for k, v in LADDERS.items()}, "keep": KEEP,
              "r0": _strip(r0), "curve": {f: {n: [{"cap": x["cap"], "result": _strip(x["result"])} for x in steps]
                                             for n, steps in c.items()} for f, c in curve.items()},
              "choice": {f: {**{k: v for k, v in c.items() if k != "combined"}, "combined": _strip(c["combined"])}
                         for f, c in choice.items()},
              "chosen": chosen, "rule_file": f"data/processed/alerts/{RESULTS}/rule.json",
              "loss": loss_shares(r0, choice[chosen]["combined"], jun_dec_mask(data)),
              "seconds": time.perf_counter() - started}
    for family in FAMILIES:
        for name, steps in result["curve"][family].items():
            add_cost_ratios(steps, name)
    dump_json(results_dir() / "fit.json", jsonable(result))
    say(f"chosen {chosen} {result['choice'][chosen]['caps']}; wrote {results_dir() / 'fit.json'}")
    return result


def _strip(result: dict) -> dict:
    return {k: v for k, v in result.items() if not k.startswith("_")}


def loss_shares(r0: dict, rule: dict, jun_dec: np.ndarray) -> dict:
    """Per reading and level: the share of the June-December development events (in a district; `jun_dec` marks them)
    that R0 covers and the rule does not."""
    out = {}
    for reading in READINGS:
        for L in LEVELS:
            base = r0["_hits"][LEVEL_NAMES[L]][reading][jun_dec]
            mine = rule["_hits"][LEVEL_NAMES[L]][reading][jun_dec]
            out[f"{reading}|{L}"] = float((base & ~mine).sum() / len(base)) if len(base) else 0.0
    return out


def add_cost_ratios(steps: list[dict], level_name: str) -> None:
    """District-days saved per covered event lost against the step before, per stratum and reading (None: none lost)."""
    for before, after in zip(steps, steps[1:]):
        for key, entry in after["result"].items():
            prev = before["result"][key][level_name]
            cur = entry[level_name]
            saved = prev["district_days"] - cur["district_days"]
            for reading in READINGS:
                lost = prev[reading]["hits"] - cur[reading]["hits"]
                cur[reading]["cost_ratio"] = float(saved / lost) if lost > 0 else None


# ------------------------------------------------------------------------------------------ the criterion

def declared_criterion(result: dict) -> dict:
    chosen = result["choice"][result["chosen"]]["combined"]
    burden_keys = {f"{k}|{L}": chosen[k][LEVEL_NAMES[L]]["share"] for k in chosen
                   if k.split("|")[1] in oo.WINDOW_SEASONS["jun_dec"] for L in LEVELS}
    events = sum(chosen[k]["Watch+"]["events"] for k in chosen if k.split("|")[1] in oo.WINDOW_SEASONS["jun_dec"])
    loss = {}
    for key, q in result["loss"].items():
        loss[key] = {"share": q, "margin_slides": MARGIN_SD * float(np.sqrt(HELDOUT_SLIDES * q * (1.0 - q)))}
    return {"rule": result["chosen"], "rule_file": result["rule_file"], "burden": burden_keys,
            "burden_factor": BURDEN_FACTOR, "loss": loss, "slides": HELDOUT_SLIDES, "development_events": events,
            "text": f"confirmed when every held-out share of district-days at a level (region x season x level, "
                    f"June-December 2018-2025) is at most {BURDEN_FACTOR} x its development value, and at every level "
                    f"and reading the independent slides the rule leaves uncovered compared with R0 on the same days are "
                    f"at most q x 87 + {MARGIN_SD} x sqrt(87 q (1 - q))"}


# ------------------------------------------------------------------------------------------------- CLI

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m aetherguard.verify.district_cap", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    cmd = sub.add_parser("counts", help="today's cell levels summed per district (resumable per year)")
    cmd.add_argument("--window", choices=sorted(oo.WINDOW_SEASONS), required=True)
    sub.add_parser("fit", help="the curve, the choice and the rule file")
    args = parser.parse_args(argv)
    say = lambda m: print(m, flush=True)  # noqa: E731
    if args.command == "counts":
        counts(args.window, say)
    elif args.command == "fit":
        fit(say)
    return 0


if __name__ == "__main__":
    sys.exit(main())
