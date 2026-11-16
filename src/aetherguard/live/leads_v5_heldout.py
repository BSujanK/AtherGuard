"""W7b: the ONE held-out look of the forecast leads on v4-static (docs/superpowers/specs/2026-11-17-aetherguard-leads-v5.md).

    python -m aetherguard.live.leads_v5_heldout score     [--years 2025,2021,2022,2023,2024]   heavy, resumable per year
    python -m aetherguard.live.leads_v5_heldout preflight                                    no outcome is computed
    python -m aetherguard.live.leads_v5_heldout heldout                                      the one look

The same per-lead target-day panels, burden matching and detection as `leads_v4_heldout`, with candidate (s): v4-static
(no rain-intensity input) at every forecast lead. June-September 2025 is the fresh, deciding season; 2021-2024 were looked
at by the v4-leads look and are scored beside it only, labelled as such. Files under
`data/processed/lead_intensity/heldout_v5/`, separate from the v4 look's, with their own result and started marker.
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import data_root
from ..hazard import model as hm
from ..hazard.jsonio import dump_json
from ..manifest import sha256_file
from . import leads_v4_heldout as lh
from . import leads_v4_study as study

UTC = timezone.utc
CANDIDATE = "s"
DECIDING_YEARS = (2025,)
BESIDE_YEARS = (2021, 2022, 2023, 2024)
ALL_YEARS = (*DECIDING_YEARS, *BESIDE_YEARS)
PREFLIGHT, RESULT = "preflight.json", "heldout_result.json"
MODEL_FILES = ("model.txt", "card.json", "calibrator.json", "calibrator_regions.json")


def out_dir() -> Path:
    return data_root() / "processed" / "lead_intensity" / "heldout_v5"


def model_dir() -> Path:
    return data_root() / "processed" / "hazard" / "v4_static" / "models" / "v4_static"


def year_path(year: int) -> Path:
    return out_dir() / f"leads_{year}.npz"


def load_year(year: int) -> dict:
    with np.load(year_path(year), allow_pickle=False) as data:
        return {k: data[k] for k in data.files}


def model_digests() -> dict:
    return {name: sha256_file(model_dir() / name) for name in MODEL_FILES if (model_dir() / name).is_file()}


def panel_digests(years=ALL_YEARS) -> dict:
    return {str(y): sha256_file(year_path(y)) for y in years}


# ------------------------------------------------------------------------------------------------ scoring

class V5Setup(lh.LookSetup):
    """The v4 look's set-up (reference cells, incumbent, forecast rain) plus the candidate v4-static."""

    def __init__(self) -> None:
        from ..features import static_w5
        from . import run as live_run
        super().__init__()
        self.candidate = hm.HazardModel.load(model_dir())
        if live_run.uses_intensity(self.candidate):
            raise ValueError("the v5 candidate must read no rain-intensity input")
        names = [c for c in self.candidate.columns if c in static_w5.STATIC_COLUMNS]
        self.candidate_static = static_w5.join_static(self.sample[["cell_id"]], static_w5.static_table())[names].reset_index(drop=True)
        self.thresholds["s"] = live_run.card_thresholds(self.candidate, self.sample["region"])


def lead_scores_of_day(setup: V5Setup, issue_day: date, lead: int) -> dict | None:
    """{incumbent level, risk, raw; candidate risk, raw; scored} of one issue day and lead for every reference cell, or None
    when the lead's forecast rain is missing."""
    from . import forecast_choice as fc
    from . import forecast_features as FF
    products = fc.load_product_days(setup.rain_dir, issue_day)
    field = fc.resolve_lead(products, setup.choice, setup.maps, lead)
    if field is None or not np.isfinite(field.days).all():
        return None
    base = setup.sample
    rain = FF.lead_features(base, issue_day, lead, setup.store, field.days, setup.clim)
    incumbent_frame = pd.concat([base, rain], axis=1)
    candidate_frame = pd.concat([base, rain, setup.candidate_static], axis=1)
    out = {"source": field.label}
    for name, model, frame, key in (("incumbent", setup.v3, incumbent_frame, "v3"), ("s", setup.candidate, candidate_frame, "s")):
        risk, level, ok = setup.published(model, frame, setup.thresholds[key])
        raw = np.full(len(base), np.nan)
        if ok.any():
            raw[ok] = model.raw_score(frame[ok])
        out[f"{name}_risk"], out[f"{name}_raw"], out[f"{name}_ok"] = risk, raw, ok
        if name == "incumbent":
            out["incumbent_level"] = level.astype(np.int8)
    out["scored"] = out.pop("incumbent_ok") & out.pop("s_ok")
    return out


def score_year(setup: V5Setup, year: int, say=print) -> Path:
    path = year_path(year)
    if path.is_file():
        say(f"{path.name} exists: skipped")
        return path
    days = study.season_days(year)
    n, m = len(setup.reference), len(days)
    arrays = {f"L{lead}_{name}": np.full((n, m), np.nan, dtype=np.float64)
              for lead in lh.LEADS for name in ("incumbent_risk", "incumbent_raw", "s_risk", "s_raw")}
    arrays.update({f"L{lead}_incumbent_level": np.zeros((n, m), dtype=np.int8) for lead in lh.LEADS})
    arrays.update({f"L{lead}_scored": np.zeros((n, m), dtype=bool) for lead in lh.LEADS})
    sources = {str(lead): {} for lead in lh.LEADS}
    for j, day in enumerate(days):
        for lead in lh.LEADS:
            got = lead_scores_of_day(setup, day, lead)
            if got is None:
                continue
            for name in ("incumbent_level", "incumbent_risk", "incumbent_raw", "s_risk", "s_raw", "scored"):
                arrays[f"L{lead}_{name}"][:, j] = got[name]
            sources[str(lead)][got["source"]] = sources[str(lead)].get(got["source"], 0) + 1
        say(f"{year} {day}: done")
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part.npz")
    np.savez_compressed(part, cell_ids=setup.reference, issue_days=np.array([d.toordinal() for d in days]),
                        sources=np.array(json.dumps(sources)), model_sha256=np.array(json.dumps(model_digests())), **arrays)
    part.replace(path)
    return path


# ---------------------------------------------------------------------------------------------- the look

def pools(events: pd.DataFrame, years) -> dict:
    return {str(lead): lh.lead_pool(lead, CANDIDATE, events, years, loader=load_year) for lead in lh.LEADS}


def event_counts(pool) -> dict:
    from ..verify import heldout as vh
    return {"events_on_days": int(len(pool.events.drop_duplicates(["cell_id", "date"]))),
            "events_outside_days": int(pool.events_outside),
            "independent_slides_on_days": int(vh.distinct_events(pool.events)) if len(pool.events) else 0}


def run_preflight(say=print) -> dict:
    if (out_dir() / RESULT).exists() or (out_dir() / f"{RESULT}.started").exists():
        raise FileExistsError("the look has been taken (or started); a preflight no longer applies")
    missing = [y for y in ALL_YEARS if not year_path(y).is_file()]
    if missing:
        raise FileNotFoundError(f"score the years first: {missing}")
    stored = {str(y): json.loads(str(load_year(y)["model_sha256"])) for y in ALL_YEARS}
    if any(v != model_digests() for v in stored.values()):
        raise ValueError("a panel was scored with other v4-static files than the ones on disk now")
    deciding = pools(lh.w1_events(DECIDING_YEARS), DECIDING_YEARS)
    leads = {lead: {"days": len(pool.days), "scored_cell_days": int(pool.scored.sum()), "seasons": seasons,
                    **event_counts(pool)} for lead, (pool, seasons) in deciding.items()}
    beside_counts = {"w1_2021_2024_already_looked_at": {
        lead: event_counts(pool) for lead, (pool, _) in pools(lh.w1_events(BESIDE_YEARS), BESIDE_YEARS).items()}}
    for name, events in lh.v2_event_sets(DECIDING_YEARS).items():
        beside_counts[f"{name}_2025"] = {lead: event_counts(pool) for lead, (pool, _) in pools(events, DECIDING_YEARS).items()}
    preflight = {"generated_utc": datetime.now(UTC).isoformat(timespec="seconds"), "candidate": CANDIDATE,
                 "deciding_years": list(DECIDING_YEARS), "beside_years": list(BESIDE_YEARS),
                 "panels_sha256": panel_digests(), "model_sha256": model_digests(), "leads": leads,
                 "beside_event_counts": beside_counts,
                 "checks": [{"check": f"lead {lead}: burden matched within tolerance every season", "passed": True}
                            for lead in leads] + [{"check": "every panel scored with the v4-static files on disk", "passed": True}],
                 "rule": "on June-September 2025, for leads 1-3, tolerant and cell-exact, Warning+ and Emergency independent-slide "
                         "detection of the candidate not lower than the incumbent's in any of the 12 rows and higher in at least one",
                 "note": "no event was joined with a level; event counts are of the dates only"}
    dump_json(out_dir() / PREFLIGHT, preflight)
    say(json.dumps({k: {"events": v["events_on_days"], "slides": v["independent_slides_on_days"]} for k, v in leads.items()}))
    return preflight


def run_heldout(say=print) -> dict:
    from ..verify import operating_point as op
    result, marker = out_dir() / RESULT, out_dir() / f"{RESULT}.started"
    if result.exists() or marker.exists():
        raise FileExistsError(f"{result.name} or its started marker exists: the look is not repeated")
    path = out_dir() / PREFLIGHT
    if not path.is_file():
        raise FileNotFoundError("run the preflight first")
    preflight = json.loads(path.read_text(encoding="utf-8"))
    if preflight["panels_sha256"] != panel_digests() or preflight["model_sha256"] != model_digests():
        raise ValueError("the panels or the model differ from the preflight's; run it again")
    started = {"done": False}

    def mark() -> None:
        if not started["done"]:
            marker.write_text(datetime.now(UTC).isoformat(timespec="seconds"), encoding="utf-8")
            started["done"] = True
    deciding = {lead: op.score_heldout(pool, op.BOOTSTRAP, None, before_candidate=mark)
                for lead, (pool, _) in pools(lh.w1_events(DECIDING_YEARS), DECIDING_YEARS).items()}
    beside = {"w1_2021_2024_already_looked_at": {lead: op.score_heldout(pool, op.BOOTSTRAP, None) for lead, (pool, _) in
                                                 pools(lh.w1_events(BESIDE_YEARS), BESIDE_YEARS).items()}}
    for name, events in lh.v2_event_sets(DECIDING_YEARS).items():
        beside[f"{name}_2025"] = {lead: op.score_heldout(pool, op.BOOTSTRAP, None)
                                  for lead, (pool, _) in pools(events, DECIDING_YEARS).items()}
    payload = {"generated_utc": datetime.now(UTC).isoformat(timespec="seconds"), "candidate": CANDIDATE,
               "preflight": preflight, "deciding_w1_2025": deciding, "decision": lh.decide(deciding), "beside": beside}
    text = json.dumps(op.jsonable(payload), indent=2, allow_nan=False)
    with open(result, "x", encoding="utf-8") as handle:
        handle.write(text + "\n")
    say(json.dumps(payload["decision"]))
    return payload


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m aetherguard.live.leads_v5_heldout", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    score = sub.add_parser("score")
    score.add_argument("--years", type=lambda t: tuple(int(y) for y in t.split(",")), default=ALL_YEARS)
    sub.add_parser("preflight")
    sub.add_parser("heldout")
    args = parser.parse_args(argv)
    if args.command == "score":
        setup = V5Setup()
        for year in args.years:
            score_year(setup, year)
        return 0
    if args.command == "preflight":
        run_preflight()
        return 0
    run_heldout()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
