"""W7: the ONE held-out look of the forecast leads (docs/superpowers/specs/2026-11-14-aetherguard-leads-v4.md section 5).

    python -m aetherguard.live.leads_v4_heldout score     [--years 2021,2022,2023,2024]     heavy, resumable per year
    python -m aetherguard.live.leads_v4_heldout preflight --candidate a|b                     no outcome is computed
    python -m aetherguard.live.leads_v4_heldout heldout   --candidate a|b                     the one look

Why a panel per lead: a forecast lead L issued on D speaks about the target day T = D + L, so the lead's season panel has
one column per target day, holding the forecast issued L days earlier; a held-out slide of day X is then matched against the
column X exactly as lead 0's panels are matched (`verify.operating_point.score_heldout`, tolerant and cell-exact, independent
slides). History: issue days of June-September 2021-2024 that have the GFS 3-hour archive day and the Early live window of
D (the only years with archived forecasts; 2018-2020 have none); ECMWF from 2023, so 2021-2022 use the GFS fallback at
every lead, as the live run does when ECMWF is missing.

score     Per year, for every cell of the held-out reference (the 2018 operational panel's cells) and every issue day and lead:
          the incumbent's published lead level (v3 point level, `uncertain_high` of the rules, rain cap), risk and raw score,
          and the risk and raw score of candidates a and b (v4; b the expectation over the ensemble percentiles where the
          lead's rain is the ensemble). `<out>/leads_<year>.npz`; a year already written is skipped. Never reads an event.
preflight For the candidate chosen by E1 (section 4): burden-matches it per season and lead to the incumbent's realised Watch+ /
          Warning+ / Emergency shares (`hazard.v4_int.match_burden`), counts the events dated on the panel days (W1 assembly;
          assembly v2 beside it) and records the panels' checksums. No event is joined with a level.
heldout   Refuses a second look (result or started marker present) and a look without a current preflight. Scores the
          incumbent of each lead first, then marks the look started, then the candidate; decides by the pre-declared rule:
          for leads 1, 2, 3, tolerant and cell-exact, Warning+ and Emergency (12 rows) independent-slide detection not lower
          than the incumbent's in any row and higher in at least one. Assembly v2 is scored beside it (all records, without the
          unlicensed BIPAD register, India only) and decides nothing.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from ..alerts import levels as lv
from ..config import PROJECT_ROOT, data_root
from ..features import imerg_intensity as ii
from ..hazard.jsonio import dump_json
from ..manifest import sha256_file
from . import lead_intensity as li
from . import leads_v4_study as study

UTC = timezone.utc
YEARS = (2021, 2022, 2023, 2024)
LEADS = (1, 2, 3)
CANDIDATES = ("a", "b")
DECIDING_LEVELS = (lv.WARNING, lv.EMERGENCY)
TOLERANCE_NAMES = ("tolerant", "cell_exact")
PREFLIGHT, RESULT = "preflight.json", "heldout_result.json"
REPORT_STEM = "phase8_leads_v4_heldout"


def out_dir() -> Path:
    return data_root() / "processed" / "lead_intensity" / "heldout"


def year_path(year: int) -> Path:
    return out_dir() / f"leads_{year}.npz"


def target_days(year: int, lead: int) -> list[date]:
    return [d + timedelta(days=lead) for d in study.season_days(year)]


# ------------------------------------------------------------------------------------------------ scoring

class LookSetup(study.E1Setup):
    """E1's set-up on every cell of the held-out reference, in its order."""

    def __init__(self) -> None:
        from . import hardening as H
        from . import run as live_run
        from ..features import static_w5
        super().__init__(n_cells=1)
        reference = H.load_panel(H.alerts_dir(H.HELDOUT_DIR) / H.HELDOUT_FILE).cells["cell_id"].to_numpy(dtype=np.int64)
        cells = live_run.load_cells(self.cfg).set_index("cell_id").reindex(reference)
        if cells["region"].isna().any():
            raise ValueError("a reference cell is missing from the terrain / region tables")
        self.reference = reference
        self.sample = cells.reset_index()
        self.static = static_w5.join_static(self.sample[["cell_id"]], static_w5.static_table())[
            [c for c in self.v4.columns if c in static_w5.STATIC_COLUMNS]].reset_index(drop=True)
        self.thresholds = {"v3": live_run.card_thresholds(self.v3, self.sample["region"]),
                           "v4": live_run.card_thresholds(self.v4, self.sample["region"])}
        self.clim = study.climatology(self.cfg, self.store, reference)


def lead_scores_of_day(setup: LookSetup, issue_day: date, lead: int, stored) -> dict | None:
    """{incumbent level, risk, raw; a and b risk and raw; scored} of one issue day and lead for every reference cell, or None
    when the forecast rain or a day of the intensity window is missing."""
    from . import forecast_choice as fc
    from . import forecast_features as FF
    from . import run as live_run
    products = fc.load_product_days(setup.rain_dir, issue_day)
    field = fc.resolve_lead(products, setup.choice, setup.maps, lead)
    if field is None or not np.isfinite(field.days).all():
        return None
    iint, _ = li.lead_frame(issue_day, lead, setup.reference, setup.sources(issue_day, stored, setup.intensity_maps))
    if iint is None:
        return None
    base = setup.sample
    rain = FF.lead_features(base, issue_day, lead, setup.store, field.days, setup.clim)
    incumbent_frame = pd.concat([base, rain], axis=1)
    candidate_frame = pd.concat([base, rain, iint, setup.static], axis=1)
    risk, level, ok_c = setup.published(setup.v3, incumbent_frame, setup.thresholds["v3"])
    out = {"incumbent_level": level.astype(np.int8), "incumbent_risk": risk,
           "incumbent_raw": np.where(ok_c, 0.0, np.nan), "source": field.label}
    if ok_c.any():
        out["incumbent_raw"][ok_c] = setup.v3.raw_score(incumbent_frame[ok_c])
    models = {"a": setup.v4, "b": setup.v4}
    if field.scenarios is not None:
        scenes = {n: pd.concat([base, FF.lead_features(base, issue_day, lead, setup.store, r, setup.clim), iint, setup.static],
                               axis=1) for n, r in field.scenarios.items()}
        models["b"] = live_run.ExpectedModel(setup.v4, {n: (live_run.EXPECTED_WEIGHTS[n], f) for n, f in scenes.items()})
    scored = ok_c.copy()
    for name, model in models.items():
        r, _, ok = setup.published(model, candidate_frame, setup.thresholds["v4"])
        raw = np.full(len(base), np.nan)
        if ok.any():
            raw[ok] = model.raw_score(candidate_frame[ok])
        out[f"{name}_risk"], out[f"{name}_raw"] = r, raw
        scored &= ok
    out["scored"] = scored
    return out


def score_year(setup: LookSetup, year: int, say=print) -> Path:
    path = year_path(year)
    if path.is_file():
        say(f"{path.name} exists: skipped")
        return path
    store = li.default_store()
    days = study.season_days(year)
    n, m = len(setup.reference), len(days)
    arrays = {f"L{lead}_{name}": np.full((n, m), np.nan, dtype=np.float64)
              for lead in LEADS for name in ("incumbent_risk", "incumbent_raw", "a_risk", "a_raw", "b_risk", "b_raw")}
    arrays.update({f"L{lead}_incumbent_level": np.zeros((n, m), dtype=np.int8) for lead in LEADS})
    arrays.update({f"L{lead}_scored": np.zeros((n, m), dtype=bool) for lead in LEADS})
    sources = {str(lead): {} for lead in LEADS}
    for j, day in enumerate(days):
        stored = li.load_store_day(store, day)
        for lead in LEADS:
            got = None if stored is None else lead_scores_of_day(setup, day, lead, stored)
            if got is None:
                continue
            for name in ("incumbent_level", "incumbent_risk", "incumbent_raw", "a_risk", "a_raw", "b_risk", "b_raw", "scored"):
                arrays[f"L{lead}_{name}"][:, j] = got[name]
            sources[str(lead)][got["source"]] = sources[str(lead)].get(got["source"], 0) + 1
        say(f"{year} {day}: done")
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part.npz")
    np.savez_compressed(part, cell_ids=setup.reference, issue_days=np.array([d.toordinal() for d in days]),
                        sources=np.array(json.dumps(sources)), **arrays)
    part.replace(path)
    return path


# ---------------------------------------------------------------------------------------------- pools

def load_year(year: int) -> dict:
    with np.load(year_path(year), allow_pickle=False) as data:
        return {k: data[k] for k in data.files}


def lead_pool(lead: int, candidate: str, events: pd.DataFrame, years=YEARS):
    """The held-out pool of one lead: the incumbent's levels and the candidate's, burden-matched per season, over the target
    days of the seasons; the events dated on those days."""
    from ..hazard import v4_int
    from ..verify import heldout as vh
    from ..verify import operating_point as op
    cell_ids, days, scored, incumbent, candidate_levels, seasons = None, [], [], [], [], {}
    for year in years:
        data = load_year(year)
        cell_ids = data["cell_ids"]
        on = data[f"L{lead}_scored"]
        season_days = target_days(year, lead)
        levels = np.where(on, data[f"L{lead}_incumbent_level"], 0).astype(np.int8)
        risk = np.where(on, data[f"L{lead}_{candidate}_risk"], np.nan)
        raw = np.where(on, data[f"L{lead}_{candidate}_raw"], np.nan)
        matched, info = v4_int.match_burden(risk, raw, on, levels, cell_ids, season_days)
        seasons[str(year)] = {"scored_cell_days": int(on.sum()), "issue_days_scored": int(on.any(axis=0).sum()), **info}
        scored.append(on)
        incumbent.append(levels)
        candidate_levels.append(matched)
        days += season_days
    scored, incumbent, candidate_levels = (np.concatenate(a, axis=1) for a in (scored, incumbent, candidate_levels))
    kept, outside = vh.events_on_days(events, days)
    return op.HeldOut(cell_ids, days, scored, incumbent, candidate_levels, kept, outside), seasons


def w1_events(years=YEARS) -> pd.DataFrame:
    from ..verify import heldout as vh
    from . import run as live_run
    events = vh.load_event_table(live_run.load_run_config())
    return events[pd.to_datetime(events["date"]).dt.year.isin(years)]


def v2_event_sets(years=YEARS) -> dict[str, pd.DataFrame]:
    """Assembly v2 (frozen, data/processed/heldout_v2): all records, without the unlicensed BIPAD register, India only."""
    events = pd.read_parquet(data_root() / "processed" / "heldout_v2" / "events.parquet",
                             columns=["cell_id", "date", "source", "country"])
    events = events[pd.to_datetime(events["date"]).dt.year.isin(years)].assign(date=lambda e: pd.to_datetime(e["date"]))
    return {"v2_all": events, "v2_without_bipad": events[events["source"] != "bipad_nepal"],
            "v2_india": events[events["country"].astype(str).str.upper().isin(("IN", "IND", "INDIA"))]}


def panel_digests(years=YEARS) -> dict:
    return {str(y): sha256_file(year_path(y)) for y in years}


def run_preflight(candidate: str, say=print) -> dict:
    from ..verify import heldout as vh
    if (out_dir() / RESULT).exists() or (out_dir() / f"{RESULT}.started").exists():
        raise FileExistsError("the look has been taken (or started); a preflight no longer applies")
    missing = [y for y in YEARS if not year_path(y).is_file()]
    if missing:
        raise FileNotFoundError(f"score the years first: {missing}")
    events = w1_events()
    checks, leads = [], {}
    for lead in LEADS:
        pool, seasons = lead_pool(lead, candidate, events)
        leads[str(lead)] = {"seasons": seasons, "days": len(pool.days), "scored_cell_days": int(pool.scored.sum()),
                            "events_on_days": int(len(pool.events.drop_duplicates(["cell_id", "date"]))),
                            "events_outside_days": int(pool.events_outside),
                            "independent_slides_on_days": int(vh.distinct_events(pool.events)) if len(pool.events) else 0}
        checks.append({"check": f"lead {lead}: burden matched within tolerance every season", "passed": True})
    preflight = {"generated_utc": datetime.now(UTC).isoformat(timespec="seconds"), "candidate": candidate, "years": list(YEARS),
                 "panels_sha256": panel_digests(), "leads": leads, "checks": checks,
                 "rule": "for leads 1-3, tolerant and cell-exact, Warning+ and Emergency independent-slide detection of the "
                         "candidate not lower than the incumbent's in any of the 12 rows and higher in at least one",
                 "note": "no event was joined with a level; event counts are of the dates only"}
    dump_json(out_dir() / PREFLIGHT, preflight)
    say(json.dumps({k: {"events": v["events_on_days"], "slides": v["independent_slides_on_days"]} for k, v in leads.items()}))
    return preflight


def decide(by_lead: dict) -> dict:
    rows = []
    for lead, scores in by_lead.items():
        for tolerance in TOLERANCE_NAMES:
            for level in DECIDING_LEVELS:
                inc = scores[tolerance]["v3"][level]["group_hits"]
                cand = scores[tolerance]["candidate"][level]["group_hits"]
                rows.append({"lead": int(lead), "tolerance": tolerance, "level": lv.level_name(level), "incumbent": int(inc),
                             "candidate": int(cand), "not_lower": cand >= inc, "higher": cand > inc})
    adopt = all(r["not_lower"] for r in rows) and any(r["higher"] for r in rows)
    return {"adopt": adopt, "rows": rows}


def run_heldout(candidate: str, say=print) -> dict:
    from ..verify import operating_point as op
    result, marker = out_dir() / RESULT, out_dir() / f"{RESULT}.started"
    if result.exists() or marker.exists():
        raise FileExistsError(f"{result.name} or its started marker exists: the look is not repeated")
    path = out_dir() / PREFLIGHT
    if not path.is_file():
        raise FileNotFoundError("run the preflight first")
    preflight = json.loads(path.read_text(encoding="utf-8"))
    if preflight["candidate"] != candidate or preflight["panels_sha256"] != panel_digests():
        raise ValueError("the preflight is for another candidate or other panels; run it again")
    events = w1_events()
    pools = {lead: lead_pool(lead, candidate, events)[0] for lead in LEADS}
    started = {"done": False}

    def mark() -> None:
        if not started["done"]:
            marker.write_text(datetime.now(UTC).isoformat(timespec="seconds"), encoding="utf-8")
            started["done"] = True
    deciding = {str(lead): op.score_heldout(pool, op.BOOTSTRAP, None, before_candidate=mark) for lead, pool in pools.items()}
    beside = {}
    for name, ev in v2_event_sets().items():
        beside[name] = {}
        for lead in LEADS:
            pool, _ = lead_pool(lead, candidate, ev)
            beside[name][str(lead)] = op.score_heldout(pool, op.BOOTSTRAP, None)
    payload = {"generated_utc": datetime.now(UTC).isoformat(timespec="seconds"), "candidate": candidate,
               "preflight": preflight, "deciding_w1": deciding, "decision": decide(deciding), "beside_v2": beside}
    text = json.dumps(op.jsonable(payload), indent=2, allow_nan=False)
    with open(result, "x", encoding="utf-8") as handle:
        handle.write(text + "\n")
    say(json.dumps(payload["decision"]))
    return payload


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m aetherguard.live.leads_v4_heldout", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    score = sub.add_parser("score")
    score.add_argument("--years", type=lambda t: tuple(int(y) for y in t.split(",")), default=YEARS)
    for name in ("preflight", "heldout"):
        sub.add_parser(name).add_argument("--candidate", choices=CANDIDATES, required=True)
    args = parser.parse_args(argv)
    if args.command == "score":
        setup = LookSetup()
        for year in args.years:
            score_year(setup, year)
        return 0
    if args.command == "preflight":
        run_preflight(args.candidate)
        return 0
    run_heldout(args.candidate)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
