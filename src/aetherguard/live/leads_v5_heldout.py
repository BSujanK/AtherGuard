"""W7b: the ONE held-out look of the forecast leads on v4-static (docs/superpowers/specs/2026-11-17-aetherguard-leads-v5.md).

    python -m aetherguard.live.leads_v5_heldout score     [--years 2025,2021,2022,2023,2024]   heavy, resumable per year
    python -m aetherguard.live.leads_v5_heldout gate      [--years 2022,2023,2024]           heavy, resumable per day
    python -m aetherguard.live.leads_v5_heldout preflight                                    no outcome is computed
    python -m aetherguard.live.leads_v5_heldout heldout                                      the one look

The same per-lead target-day panels, burden matching and detection as `leads_v4_heldout`, with candidate (s): v4-static
(no rain-intensity input) at every forecast lead. June-September 2025 is the fresh, deciding season; 2021-2024 were looked
at by the v4-leads look and are scored beside it only, labelled as such. Amendment 2 decides: adoption = the development gate (`gate`: E1 of the incumbent and the candidate, no event read)
passed AND the pooled 2025 no-harm veto not triggered. Files under
`data/processed/lead_intensity/heldout_v5/`, separate from the v4 look's, with their own result and started marker.
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import PROJECT_ROOT, data_root
from ..hazard import model as hm
from ..hazard.jsonio import dump_json
from ..manifest import sha256_file
from . import lead_intensity as li
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


# ---------------------------------------------------------------------------------- amendment 2: gate, veto, adoption

T_ALL, T_CE = 13, 4                       # tools/leads_v5_veto.py (reports/phase8_leads_v5_veto.json)
BURDEN_TOLERANCE = 0.20
BURDEN_LEVELS = ("watch", "warning", "emergency")
E1_CANDIDATES = ("c", "s")


def e1_path() -> Path:
    return PROJECT_ROOT / "reports" / "phase8_leads_v5_e1.json"


def e1_cache() -> Path:
    return data_root() / "processed" / "lead_intensity" / "e1_cache_v5"


def veto(by_lead: dict) -> dict:
    """Amendment 2 (b): incumbent minus candidate independent-slide detections pooled over the 12 deciding rows (NET_ALL) and
    over the three cell-exact Emergency rows (NET_CE); triggered at NET_ALL >= T_ALL or NET_CE >= T_CE."""
    net_all = net_ce = 0
    rows = []
    for lead, scores in by_lead.items():
        for tolerance in lh.TOLERANCE_NAMES:
            for level in lh.DECIDING_LEVELS:
                inc = int(scores[tolerance]["v3"][level]["group_hits"])
                cand = int(scores[tolerance]["candidate"][level]["group_hits"])
                net_all += inc - cand
                if tolerance == "cell_exact" and level == lh.lv.EMERGENCY:
                    net_ce += inc - cand
                rows.append({"lead": int(lead), "tolerance": tolerance, "level": lh.lv.level_name(level),
                             "incumbent": inc, "candidate": cand, "net_loss": inc - cand})
    return {"net_all": net_all, "net_ce": net_ce, "t_all": T_ALL, "t_ce": T_CE,
            "triggered": net_all >= T_ALL or net_ce >= T_CE, "rows": rows}


def gate_verdict(e1: dict) -> dict:
    """Amendment 2 (a): at every lead, the candidate's Watch / Warning / Emergency shares within 20% of the reference's and
    its Warning+ recall of the reference not lower than the incumbent's."""
    failures = []
    for lead in ("1", "2", "3"):
        s, c = e1["results"][lead]["s"]["vs_v4_reference"], e1["results"][lead]["c"]["vs_v4_reference"]
        for level in BURDEN_LEVELS:
            f, r = s["burden_forecast"][level], s["burden_reference"][level]
            if not r or abs(f / r - 1) > BURDEN_TOLERANCE + 1e-12:
                failures.append(f"lead {lead} {level} share {f:.4f} against reference {r:.4f}")
        if s["warning_plus_recall"] < c["warning_plus_recall"]:
            failures.append(f"lead {lead} Warning+ recall {s['warning_plus_recall']:.4f} below the incumbent's "
                            f"{c['warning_plus_recall']:.4f}")
    return {"passed": not failures, "failures": failures,
            "rule": "every lead: burden within 20% of the reference at Watch, Warning, Emergency; Warning+ recall >= incumbent's"}


def adoption(gate_passed: bool, veto_result: dict) -> bool:
    return bool(gate_passed) and not veto_result["triggered"]


class GateSetup(study.E1Setup):
    """E1's sample and models plus the candidate v4-static."""

    def __init__(self) -> None:
        from ..features import static_w5
        from . import run as live_run
        super().__init__()
        self.candidate = hm.HazardModel.load(model_dir())
        names = [c for c in self.candidate.columns if c in static_w5.STATIC_COLUMNS]
        self.candidate_static = static_w5.join_static(self.sample[["cell_id"]], static_w5.static_table())[names].reset_index(drop=True)
        self.thresholds["s"] = live_run.card_thresholds(self.candidate, self.sample["region"])


def gate_day(setup: GateSetup, issue_day: date, lead: int) -> dict | None:
    """{(candidate, "v4"): (confusion, lead risk, reference risk)} of one issue day and lead; None without forecast rain or a
    complete observed intensity window of the reference."""
    from ..features import imerg_intensity as ii
    from . import forecast_choice as fc
    from . import forecast_features as FF
    products = fc.load_product_days(setup.rain_dir, issue_day)
    field = fc.resolve_lead(products, setup.choice, setup.maps, lead)
    if field is None or not np.isfinite(field.days).all():
        return None
    base = setup.sample
    target = issue_day + timedelta(days=lead)
    observed_iint = ii.cell_features(target, base["cell_id"].to_numpy(), ii.default_root(), li.LATE, 1)
    if not np.isfinite(observed_iint.to_numpy()).all():
        return None
    rain = FF.lead_features(base, issue_day, lead, setup.store, field.days, setup.clim)
    observed = FF.lead_features(base, target, 0, setup.store, None, setup.clim)
    ref_risk, ref_level, ref_ok = setup.published(setup.v4, pd.concat([base, observed, observed_iint, setup.static], axis=1),
                                                  setup.thresholds["v4"])
    out = {"source": field.label}
    for name, model, frame, key in (("c", setup.v3, pd.concat([base, rain], axis=1), "v3"),
                                    ("s", setup.candidate, pd.concat([base, rain, setup.candidate_static], axis=1), "s")):
        risk, level, ok = setup.published(model, frame, setup.thresholds[key])
        both = ok & ref_ok
        confusion = np.zeros((study.LEVELS, study.LEVELS), dtype=np.int64)
        np.add.at(confusion, (ref_level[both].astype(int), level[both].astype(int)), 1)
        out[(name, "v4")] = (confusion, risk[both].astype(np.float32), ref_risk[both].astype(np.float32))
    return out


def gate_cached(holder: dict, issue_day: date, lead: int) -> dict | None:
    path = e1_cache() / f"{issue_day.isoformat()}_L{lead}.npz"
    if path.is_file():
        with np.load(path, allow_pickle=False) as data:
            return {"source": str(data["source"]),
                    **{(n, "v4"): (data[f"{n}|conf"], data[f"{n}|f"], data[f"{n}|r"]) for n in E1_CANDIDATES}}
    if "setup" not in holder:
        holder["setup"] = GateSetup()
    got = gate_day(holder["setup"], issue_day, lead)
    if got is None:
        return None
    arrays = {"source": np.array(got["source"])}
    for n in E1_CANDIDATES:
        arrays[f"{n}|conf"], arrays[f"{n}|f"], arrays[f"{n}|r"] = got[(n, "v4")]
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part.npz")
    np.savez_compressed(part, **arrays)
    part.replace(path)
    return got


def run_gate(years=(2022, 2023, 2024), say=print) -> dict:
    holder: dict = {}
    per_day: dict = {}
    pairs: dict = {}
    sources: dict = {}
    for year in years:
        for day in study.season_days(year):
            for lead in lh.LEADS:
                got = gate_cached(holder, day, lead)
                if got is None:
                    continue
                sources.setdefault(str(lead), {}).setdefault(got["source"], 0)
                sources[str(lead)][got["source"]] += 1
                for n in E1_CANDIDATES:
                    confusion, f, r = got[(n, "v4")]
                    per_day.setdefault((lead, n), []).append(confusion)
                    pairs.setdefault((lead, n), []).append((f, r))
            say(f"{day}: done")
    results: dict = {}
    for (lead, n), rows in sorted(per_day.items()):
        f = np.concatenate([p[0] for p in pairs[(lead, n)]]).astype(np.float64)
        r = np.concatenate([p[1] for p in pairs[(lead, n)]]).astype(np.float64)
        results.setdefault(str(lead), {})[n] = {"vs_v4_reference": {**study.level_metrics(np.sum(rows, axis=0)), "days": len(rows),
                                                                    "calibration": study.calibration(f, r)}}
    payload = {"generated_utc": datetime.now(UTC).isoformat(timespec="seconds"), "years": list(years), "cells": study.E1_CELLS,
               "seed": study.E1_SEED, "candidates": {"c": "v3 on the selected forecast rain (incumbent)",
                                                     "s": "v4-static on the selected forecast rain"},
               "reference": "published v4 lead-0 level of the target day from observed features (Late lag-1 intensity, static)",
               "forecast_sources": sources, "results": results, "model_sha256": model_digests()}
    payload["gate"] = gate_verdict(payload)
    dump_json(e1_path(), payload)
    say(json.dumps(payload["gate"]))
    return payload


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
    if not e1_path().is_file():
        raise FileNotFoundError(f"{e1_path().name} not found: run the development gate first (amendment 2)")
    gate = json.loads(e1_path().read_text(encoding="utf-8"))
    if gate.get("model_sha256") != model_digests():
        raise ValueError("the gate was computed with other v4-static files than the ones on disk now")
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
                 "gate": gate["gate"], "gate_sha256": sha256_file(e1_path()),
                 "beside_event_counts": beside_counts,
                 "checks": [{"check": f"lead {lead}: burden matched within tolerance every season", "passed": True}
                            for lead in leads] + [{"check": "every panel scored with the v4-static files on disk", "passed": True}],
                 "rule": "amendment 2: adoption = development gate passed AND 2025 veto not triggered (NET_ALL >= "
                         f"{T_ALL} or NET_CE >= {T_CE} over the 12 W1 rows, incumbent minus candidate slides)",
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
    if not preflight["gate"]["passed"]:
        raise ValueError("the development gate failed (amendment 2): no look is taken and the incumbent stays")
    if not e1_path().is_file() or sha256_file(e1_path()) != preflight["gate_sha256"]:
        raise ValueError("the gate result differs from the preflight's; run it again")
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
               "preflight": preflight, "deciding_w1_2025": deciding, "veto": veto(deciding),
               "decision": {"adopt": adoption(preflight["gate"]["passed"], veto(deciding)), "gate_passed": preflight["gate"]["passed"],
                            "veto_triggered": veto(deciding)["triggered"]},
               "beside": beside}
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
    gate = sub.add_parser("gate")
    gate.add_argument("--years", type=lambda t: tuple(int(y) for y in t.split(",")), default=(2022, 2023, 2024))
    sub.add_parser("preflight")
    sub.add_parser("heldout")
    args = parser.parse_args(argv)
    if args.command == "score":
        setup = V5Setup()
        for year in args.years:
            score_year(setup, year)
        return 0
    if args.command == "gate":
        run_gate(args.years)
        return 0
    if args.command == "preflight":
        run_preflight()
        return 0
    run_heldout()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
