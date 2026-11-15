"""Spec section 12 (amendment v2): the shipped calibration, the warning levels at target frequencies, and the one test
on June-September 2025.

    python -m aetherguard.rainwarn v2-dev          development only (June-September 2023 + 2024)
    python -m aetherguard.rainwarn v2-test2025     the one look at 2025; refuses a second run

`v2-dev` fits candidate A (the section 4 predictors) and B (A plus the season-state predictor) on each monsoon season,
scores each on the other (cross-season log loss summed over leads 1-3 and the five thresholds), ships B only when its
sum is lower, fits the shipped candidate on both seasons, sets the level cutoffs of each lead so that red, orange or
above and yellow or above fire on the target shares of the 2023 + 2024 pixel-days, and writes
`data/processed/rainwarn/calibration_v2.json` and the development part of `reports/phase8_rain_warnings_v2.json`.
Resumable per lead (`v2_partial.json` in the out directory).

`v2-test2025` writes `test_2025_started.json` before it computes anything, scores the shipped calibration and levels on
every 2025 issue day with an ECMWF file, applies the pass rule of section 12.4 and adds the result to the v2 JSON; the
markdown is re-rendered from the JSON.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from ..config import PROJECT_ROOT, data_root
from . import engine as E
from . import prob as P
from . import study as S

TARGETS = {"red": 0.003, "orange": 0.015, "yellow": 0.06}
DEV_SEASONS = {"2023": ("2023-06-01", "2023-09-30"), "2024": ("2024-06-01", "2024-09-30")}
TEST_2025 = ("2025-06-01", "2025-09-30")
PASS_ROWS = ((1, "heavy"), (2, "heavy"), (3, "heavy"), (1, "very_heavy"), (2, "very_heavy"))
NONE_SHARE_MAX = {1: 0.40, 2: 0.50, 3: 0.50}
CAL_BAND = (0.67, 1.5)
MIN_DAYS = 90
PARTIAL, STARTED = "v2_partial.json", "test_2025_started.json"
CALIBRATION = "calibration_v2.json"
REPORT = "reports/phase8_rain_warnings_v2"


def _days(ctx: S.Context, first: str, last: str) -> list[date]:
    return S.ensemble_days(ctx.rain_dir, date.fromisoformat(first), date.fromisoformat(last))


def _write_json(path: Path, payload: dict) -> None:
    from .report import clean
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(clean(payload), indent=1, allow_nan=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def report_paths() -> tuple[Path, Path]:
    stem = PROJECT_ROOT / REPORT
    return stem.with_suffix(".json"), stem.with_suffix(".md")


def _entries_to_json(lead: int, entries: dict, cfg_fit) -> dict:
    return E.Calibration(fit=cfg_fit, radii=[], entries={lead: entries}).to_dict()["leads"][str(lead)]


def _entries_from_json(lead: int, data: dict) -> dict:
    return E.Calibration.from_dict({"fit": [], "radii": [], "leads": {str(lead): data}}).entries[lead]


def run_dev(cfg: dict, progress=print) -> int:
    ctx = S.make_context(cfg)
    out_dir = data_root() / cfg["out_dir"]
    partial_path = out_dir / PARTIAL
    partial = json.loads(partial_path.read_text(encoding="utf-8")) if partial_path.is_file() else {"leads": {}}
    ridge = float(cfg["ridge"])
    season_days = {k: _days(ctx, *v) for k, v in DEV_SEASONS.items()}
    all_days = sorted(season_days["2023"] + season_days["2024"])
    progress(f"v2 dev: {len(season_days['2023'])} + {len(season_days['2024'])} issue days")
    boot, rules = cfg["bootstrap"], cfg["statements"]
    for lead in E.LEADS:
        key = str(lead)
        if key in partial["leads"]:
            progress(f"lead {lead}: kept from {PARTIAL}")
            continue
        inputs = {d: S.day_inputs(ctx, lead, d, False, state=lead > 0) for d in all_days}
        candidates = {"A": False} if lead == 0 else {"A": False, "B": True}
        out = {"cross_season": {}, "pooled": {}, "folds": {}}
        for cand, state in candidates.items():
            totals = {}
            for fit_key, test_key in (("2023", "2024"), ("2024", "2023")):
                entries = S.fit_lead(ctx, lead, inputs, season_days[fit_key], ridge, state)
                for name in P.THRESHOLDS:
                    loss, n = E.log_loss_total(entries[name], S.rows_of(ctx, lead, inputs, season_days[test_key], name),
                                               lead, name)
                    t = totals.setdefault(name, [0.0, 0])
                    t[0] += loss
                    t[1] += n
                result = S.evaluate(ctx, lead, inputs, entries, season_days[test_key], with_imd=False)
                summary = S.summarise(result, lead, int(boot["n"]), int(boot["seed"]), rules, len(season_days[test_key]))
                out["folds"].setdefault(cand, {})[f"test_{test_key}"] = {
                    name: {k: summary["thresholds"][name]["domain"]["product"].get(k)
                           for k in ("bss", "bss_ci", "calibration_in_the_large", "rel_over_unc", "auc", "events")}
                    for name in P.THRESHOLDS}
                progress(f"lead {lead} {cand}: fitted {fit_key}, scored {test_key}")
            out["cross_season"][cand] = {name: {"log_loss_sum": v[0], "n": v[1]} for name, v in totals.items()}
            pooled = S.fit_lead(ctx, lead, inputs, all_days, ridge, state)
            out["pooled"][cand] = _entries_to_json(lead, pooled, cfg["shipped_fit"])
            progress(f"lead {lead} {cand}: pooled fit")
        partial["leads"][key] = out
        _write_json(partial_path, partial)
        del inputs
        progress(f"lead {lead}: done")
    sums = {c: sum(partial["leads"][str(l)]["cross_season"][c][n]["log_loss_sum"] for l in (1, 2, 3) for n in P.THRESHOLDS)
            for c in ("A", "B")}
    chosen = "B" if sums["B"] < sums["A"] else "A"
    progress(f"cross-season log loss sums A {sums['A']:.1f}, B {sums['B']:.1f}: ship {chosen}")
    entries = {lead: _entries_from_json(lead, partial["leads"][str(lead)]["pooled"]["A" if lead == 0 else chosen])
               for lead in E.LEADS}
    levels, insample = {}, {}
    for lead in E.LEADS:
        state = lead > 0 and chosen == "B"
        inputs = {d: S.day_inputs(ctx, lead, d, False, state=state) for d in all_days}
        cal = E.Calibration(fit=[], radii=ctx.radii, entries={lead: entries[lead]})
        stacks = {name: [] for name in P.THRESHOLDS}
        for day in all_days:
            item = inputs[day]
            if item.fields is None:
                continue
            target = day + timedelta(days=lead)
            truth = ctx.truth(target)
            if not np.isfinite(truth).any():
                continue
            for name in P.THRESHOLDS:
                stacks[name].append(cal.probability(item.fields, lead, name, ctx.clim.threshold_mm(name),
                                                    ctx.clim.prob(name, target)))
        levels[lead] = E.derive_levels({k: np.concatenate(v) for k, v in stacks.items()}, TARGETS)
        result = S.evaluate(ctx, lead, inputs, entries[lead], all_days, with_imd=False, level_cutoffs=levels[lead])
        insample[str(lead)] = {r: S.level_table(m) for r, m in result["levels"].items()}
        progress(f"lead {lead}: levels {levels[lead]}")
        del inputs, stacks
    shipped = E.Calibration(fit=cfg["shipped_fit"], radii=ctx.radii, entries=entries, levels=levels)
    cal_path = shipped.save(data_root() / cfg["out_dir"] / CALIBRATION)
    json_path, _ = report_paths()
    payload = json.loads(json_path.read_text(encoding="utf-8")) if json_path.is_file() else {}
    payload.update({"spec": "docs/superpowers/specs/2026-11-14-aetherguard-rain-warnings.md section 12",
                    "targets": TARGETS, "pass_rule": {"rows": [list(r) for r in PASS_ROWS], "cal_band": list(CAL_BAND),
                                                      "none_share_max": {str(k): v for k, v in NONE_SHARE_MAX.items()},
                                                      "min_issue_days": MIN_DAYS},
                    "dev": {"cross_season_log_loss": sums, "chosen": chosen,
                            "leads": partial["leads"], "levels": {str(k): v for k, v in levels.items()},
                            "insample_levels": insample},
                    "calibration": str(cal_path.relative_to(data_root())).replace("\\", "/"),
                    "calibration_sha256": hashlib.sha256(cal_path.read_bytes()).hexdigest()})
    payload["dev"]["leads"] = {l: {k: v for k, v in d.items() if k != "pooled"} for l, d in partial["leads"].items()}
    _write_json(json_path, payload)
    from . import report_v2
    report_v2.rerender()
    progress(f"wrote {cal_path} and {json_path}")
    return 0


def pass_verdict(test: dict) -> dict:
    """Spec section 12.4 on the 2025 summaries."""
    checks = []
    for lead in (1, 2, 3):
        c = test["leads"][str(lead)]["counts"]
        scored = c["issue_days"] - c["no_inputs"] - c["no_truth"]
        checks.append({"check": f"issue days D+{lead}", "value": scored, "rule": f">= {MIN_DAYS}", "ok": scored >= MIN_DAYS})
    for lead, name in PASS_ROWS:
        e = test["leads"][str(lead)]["thresholds"][name]["domain"]
        p, enough = e["product"], e["statements"].get("enough_events", False)
        lo = (p.get("bss_ci") or [None])[0]
        cal = p.get("calibration_in_the_large")
        checks.append({"check": f"D+{lead} {name} enough events", "value": [p.get("events"), p.get("event_days")],
                       "rule": "section 6", "ok": bool(enough)})
        checks.append({"check": f"D+{lead} {name} BSS lower bound", "value": lo, "rule": "> 0",
                       "ok": bool(enough) and lo is not None and lo > 0})
        checks.append({"check": f"D+{lead} {name} mean p / base rate", "value": cal, "rule": f"{CAL_BAND[0]}..{CAL_BAND[1]}",
                       "ok": bool(enough) and cal is not None and CAL_BAND[0] <= cal <= CAL_BAND[1]})
    for lead, limit in NONE_SHARE_MAX.items():
        share = test["leads"][str(lead)]["levels"]["domain"]["levels"]["none"]["share_of_heavy_events"]
        checks.append({"check": f"D+{lead} share of heavy events under none", "value": share, "rule": f"<= {limit}",
                       "ok": share is not None and share <= limit})
    return {"pass": all(c["ok"] for c in checks), "checks": checks}


def run_test2025(cfg: dict, progress=print) -> int:
    out_dir = data_root() / cfg["out_dir"]
    marker = out_dir / STARTED
    if marker.is_file():
        progress(f"refused: {marker} exists, the 2025 test was already started once")
        return 2
    cal_path = out_dir / CALIBRATION
    calibration = E.Calibration.load(cal_path)
    digest = hashlib.sha256(cal_path.read_bytes()).hexdigest()
    ctx = S.make_context(cfg)
    days = _days(ctx, *TEST_2025)
    _write_json(marker, {"started_utc": datetime.now(timezone.utc).isoformat(), "calibration_sha256": digest,
                         "issue_days": len(days)})
    progress(f"2025 test started: {len(days)} issue days with an ECMWF file")
    boot, rules = cfg["bootstrap"], cfg["statements"]
    test = {"issue_days": len(days), "first": days[0].isoformat() if days else None,
            "last": days[-1].isoformat() if days else None, "calibration_sha256": digest, "leads": {}}
    for lead in E.LEADS:
        state = bool(calibration.entries[lead]["heavy"].get("state", False))
        inputs = {d: S.day_inputs(ctx, lead, d, False, state=state) for d in days}
        result = S.evaluate(ctx, lead, inputs, calibration.entries[lead], days, with_imd=False,
                            level_cutoffs=calibration.levels[lead])
        test["leads"][str(lead)] = S.summarise(result, lead, int(boot["n"]), int(boot["seed"]), rules, len(days))
        progress(f"lead {lead}: scored")
        del inputs
    test["verdict"] = pass_verdict(test)
    json_path, _ = report_paths()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    payload["test_2025"] = test
    _write_json(json_path, payload)
    from . import report_v2
    report_v2.rerender()
    progress(f"2025 test: {'PASS' if test['verdict']['pass'] else 'FAIL'}")
    return 0
