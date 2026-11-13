"""W4 antecedent wetness: the development checks of the spec and the reports
(docs/superpowers/specs/2026-11-13-aetherguard-w4-wetness.md sections 4-6).

    python -m aetherguard.hazard.w4_wetness checks          # section 5: C1-C3 and the ablation (development rows only)
    python -m aetherguard.hazard.w4_wetness report          # reports/phase8_wetness.{md,json}: the development half
    python -m aetherguard.hazard.w4_wetness heldout-report  # reports/phase8_wetness_heldout.{md,json}, after the one look

Every model stage is `hazard.v4_int`'s, run by configuration (configs/hazard_w4_wet.yaml for stage 1, configs/hazard_v5.yaml for
v5 through `hazard.v4_combined`). This module adds only what the spec asks beside them:

* C1 where, not when: v3 plus `iwet_sat_clim` (= `iwet_sat_l2` - `iwet_sat_anom_l2`, the pixel's train-range mean saturation
  for the calendar month, a static map per month) alone. Flag if its pooled OOF FA@90 is at or below w4_wet's.
* C2 reporting bias by built-up share: the paired FA@90 difference w4_wet - C0 within terciles of the W5 `lc_built` share (cells
  joined on `cell_id`). Flag if the top tercile's difference is negative while both others are at or above 0.
* C3 missingness: the NaN share of each input among development positives and universe negatives. Flag above 1 point.
* Ablation (reported only): v3 plus each input alone, and v3 plus the three minus each.

All on the development rows with v3's folds, seeds and hyper-parameters; no 2018-2025 outcome is read. The results go to
data/processed/hazard/w4_wet/checks.json. A flag stops the work before the look; nothing is tuned to clear it.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import PROJECT_ROOT, data_root
from ..features import static_w5 as sw
from ..features import wetness as wt
from . import challengers as ch
from . import cv
from . import data as hd
from . import model as hm
from . import v31_challenger as vc
from . import v4_int as w3
from .jsonio import dump_json

STAGE1_CONFIG = PROJECT_ROOT / "configs" / "hazard_w4_wet.yaml"
V5_CONFIG = PROJECT_ROOT / "configs" / "hazard_v5.yaml"
CHECKS = "checks.json"
REPORT_STEM = "phase8_wetness"
PROBE = PROJECT_ROOT / "reports" / "phase8_wetness_sources_probe.json"
CLIM = "iwet_sat_clim"
NAN_GAP = 0.01
HEADLINE = ch.HEADLINE


def variants(inputs: list[str]) -> dict[str, list[str]]:
    """The ablation and C1 candidates: name -> the inputs added to v3 (each non-decreasing)."""
    out = {f"v3+{c}": [c] for c in inputs}
    out.update({f"v3+iwet-{c}": [x for x in inputs if x != c] for c in inputs})
    out[f"v3+{CLIM}"] = [CLIM]
    return out


def with_climatology(dev: hd.Development) -> hd.Development:
    """The development rows with `iwet_sat_clim` = sat - anomaly (NaN where either is)."""
    def add(frame: pd.DataFrame) -> pd.DataFrame:
        return frame.assign(**{CLIM: (frame["iwet_sat_l2"] - frame["iwet_sat_anom_l2"]).astype(np.float32)})
    return hd.Development(add(dev.samples), add(dev.universe), {**dev.column_map, CLIM: wt.GROUP}, dev.universe_sizes)


def c1_flag(fa: dict[str, float], challenger: str) -> dict:
    clim, wet = fa[f"v3+{CLIM}"], fa[challenger]
    return {"name": "C1 where, not when", "fa_at_90_clim_only": clim, "fa_at_90_w4_wet": wet, "flag": bool(clim <= wet),
            "rule": f"flag if FA@90 of v3 + {CLIM} alone is at or below w4_wet's"}


def c2_flag(by_tercile: dict[str, dict]) -> dict:
    d = {k: v["point_difference"] for k, v in by_tercile.items()}
    flag = d["top"] < 0 and d["low"] >= 0 and d["middle"] >= 0
    return {"name": "C2 reporting bias by built-up share", "differences": d, "flag": bool(flag),
            "rule": "flag if the top lc_built tercile's w4_wet - C0 difference is negative while both others are at or above 0"}


def c3_flag(nan_share: dict[str, dict]) -> dict:
    gaps = {c: abs(v["positives"] - v["universe_negatives"]) for c, v in nan_share.items()}
    return {"name": "C3 missingness", "nan_share": nan_share, "gaps": gaps, "flag": bool(max(gaps.values()) > NAN_GAP),
            "rule": f"flag if the NaN share of an input differs between positives and universe negatives by more than {NAN_GAP:.0%}"}


def terciles(frame: pd.DataFrame, built: pd.Series) -> np.ndarray:
    """'low' / 'middle' / 'top' per OOF row by its cell's `lc_built`, cut at the terciles of the rows' own values."""
    values = frame["cell_id"].map(built).to_numpy(dtype=np.float64)
    lo, hi = np.nanquantile(values, [1 / 3, 2 / 3])
    return np.where(np.isnan(values), "unknown", np.where(values <= lo, "low", np.where(values <= hi, "middle", "top")))


def run_checks(features_dir: Path | None = None, say=print) -> dict:
    started = time.perf_counter()
    study = w3.load_study(STAGE1_CONFIG)
    base, out = study["base"], w3.output_dir(study)
    record = w3.load_dev_results(study)
    lag = w3.current_lag(record)
    selected = w3.frozen_selection(study)
    inputs = list(study["candidates"][study["challenger"]]["add_increasing"])
    dev = with_climatology(w3.load_development(study, features_dir, lag))
    layout = cv.make_layout(dev, base["cv"]["folds"])
    frames = {n: ch.read_oof(out / w3.OOF_SUBDIR / f"oof_{n}.parquet") for n in (study["reference"], study["challenger"])}
    rows = ch.oof_frame(layout, cv.Oof.empty(layout))[ch.SAME_ROWS]
    for name, frame in frames.items():
        if not frame[ch.SAME_ROWS].equals(rows):
            raise ValueError(f"the stored OOF rows of {name} are not this layout's rows")
    runs = {}
    for name, added in variants(inputs).items():
        columns = [*selected["columns"], *added]
        constraints = vc.candidate_constraints(columns, {"increasing_extra": added}, base)
        result = cv.run_cv(dev, layout, columns, constraints, selected["hp"], selected["neg_mix"], base, name)
        frames[name] = ch.oof_frame(layout, result.oof)
        runs[name] = {"added": added, "n_trees": result.n_trees, "fa_at_90": result.pooled[HEADLINE], "seconds": result.seconds}
        say(f"{name}: FA@90 {result.pooled[HEADLINE]:.4f}, {result.n_trees} trees")
    boot, ops = base["bootstrap"], base["operating_points"]
    reference = study["reference"]
    paired = ch.paired_fa_differences(frames, [(n, reference) for n in frames if n != reference], boot["n"], boot["seed"],
                                      boot["level"], recalls=ops["recalls"], fa_shares=ops["fa_shares"])
    fa = {n: paired["metrics"][n][HEADLINE]["value"] for n in frames}
    built = sw.static_table().set_index("cell_id")["lc_built"]
    tiers = terciles(frames[reference], built)
    by_tercile = {}
    for tier in ("low", "middle", "top"):
        keep = tiers == tier
        sub = {n: frames[n][keep].reset_index(drop=True) for n in (reference, study["challenger"])}
        diff = ch.paired_fa_differences(sub, [(study["challenger"], reference)], boot["n"], boot["seed"], boot["level"])
        by_tercile[tier] = {**diff["differences"][f"{study['challenger']}-{reference}"],
                            "positives": int((sub[reference]["kind"] == ch.POSITIVE).sum()),
                            "universe_rows": int((sub[reference]["kind"] == ch.UNIVERSE).sum())}
    nan_share = {c: {"positives": float(layout.positives[c].isna().mean()),
                     "universe_negatives": float(layout.negatives[c].isna().mean())} for c in [*inputs, CLIM]}
    flags = [c1_flag(fa, study["challenger"]), c2_flag(by_tercile), c3_flag({c: nan_share[c] for c in inputs})]
    result = {"created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "lag_days": lag,
              "spec": "docs/superpowers/specs/2026-11-13-aetherguard-w4-wetness.md section 5",
              "development": {"positives": len(layout.positives), "universe_rows": len(layout.negatives),
                              "matched_rows": len(layout.matched)},
              "runs": runs, "fa_at_90": fa, "differences_to_c0": paired["differences"], "metrics": paired["metrics"],
              "by_built_tercile": by_tercile, "unknown_built_rows": int((tiers == "unknown").sum()),
              "nan_share": nan_share, "flags": flags, "passed": not any(f["flag"] for f in flags),
              "seconds": time.perf_counter() - started}
    dump_json(out / CHECKS, result)
    say(f"checks {'passed' if result['passed'] else 'FLAGGED: ' + ', '.join(f['name'] for f in flags if f['flag'])}; "
        f"wrote {hm.display_path(out / CHECKS)}")
    return result


# ------------------------------------------------------------------------------------------------ report

def _read(path: Path) -> dict | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def _ci(d: dict) -> str:
    return f"{d['point_difference']:+.4f} [{d['ci_lo']:+.4f}, {d['ci_hi']:+.4f}]"


def _fa(entry: dict) -> str:
    return f"{entry['value']:.4f} [{entry['lo']:.4f}, {entry['hi']:.4f}]"


def state(stage1: dict | None, checks: dict | None, v5: dict | None, seasons: int, preflight: dict | None,
          heldout: dict | None) -> tuple[str, str]:
    """(status, next step) of the workstream, from the stored results only."""
    if stage1 is None:
        return "stage 1 not run", "python -m aetherguard.hazard.v4_int dev --config configs/hazard_w4_wet.yaml"
    if not stage1["stage_one"]["passed"]:
        return "STOPPED: stage 1 failed its pre-declared guard (no v5, no look)", "none"
    if checks is None:
        return "checks not run", "python -m aetherguard.hazard.w4_wetness checks"
    if not checks["passed"]:
        return "STOPPED: a pre-declared check flagged before the look", "none"
    if v5 is None:
        return "stage 2 not run", "python -m aetherguard.hazard.v4_combined dev --config configs/hazard_v5.yaml"
    if not v5["stage_one"]["passed"]:
        return "STOPPED: stage 2 (v5) failed a pre-declared development guard (no look)", "none"
    if seasons < 8:
        return f"seasons scored: {seasons} of 8", "python -m aetherguard.hazard.v4_combined seasons --config configs/hazard_v5.yaml"
    if preflight is None or not preflight["passed"]:
        return "preflight not passed", "python -m aetherguard.hazard.v4_combined preflight --config configs/hazard_v5.yaml"
    if heldout is None:
        return "READY FOR HELD-OUT LOOK", "python -m aetherguard.hazard.v4_combined heldout --config configs/hazard_v5.yaml"
    return f"held-out look taken: v5 {'adopted' if heldout['decision']['adopt'] else 'not adopted'}", \
        "python -m aetherguard.hazard.w4_wetness heldout-report"


def collect() -> dict:
    s1, s5 = w3.load_study(STAGE1_CONFIG), w3.load_study(V5_CONFIG)
    out1, out5 = w3.output_dir(s1), w3.output_dir(s5)
    stage1, checks, v5 = _read(out1 / w3.DEV_RESULTS), _read(out1 / CHECKS), _read(out5 / w3.DEV_RESULTS)
    seasons = sum(1 for y in range(2018, 2026) if w3.season_file(s5, y).is_file())
    preflight, heldout = _read(out5 / w3.PREFLIGHT), _read(out5 / w3.HELDOUT)
    status, step = state(stage1, checks, v5, seasons, preflight, heldout)
    probe = _read(PROBE)
    tables = _read(data_root() / "processed" / "features" / "imerg" / wt.REPORT_NAME)
    return {"created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "spec": "docs/superpowers/specs/2026-11-13-aetherguard-w4-wetness.md", "status": status, "next": step,
            "probe": None if probe is None else {"choice": probe["choice"], "candidates": probe["candidates"]},
            "tables": tables, "stage1": stage1, "checks": checks, "v5": v5, "seasons_scored": seasons,
            "preflight": None if preflight is None else {"passed": preflight["passed"], "checks": len(preflight["checks"]),
                                                         "failed": [c["name"] for c in preflight["checks"] if not c["passed"]],
                                                         "peak_memory_mb": preflight.get("peak_memory_mb"),
                                                         "events_sha256": preflight.get("events_sha256")},
            "heldout_decision": None if heldout is None else heldout["decision"]}


def markdown(r: dict) -> str:
    lines = ["# Antecedent wetness inputs and the combined model v5 (phase 8, W4): development", "",
             f"**Status: {r['status']}.**" + (f" Next: `{r['next']}`." if r["next"] != "none" else ""), "",
             f"Criteria fixed before any model result: `{r['spec']}`. Development only (year-blocked CV 2007-2017, v3's folds "
             "and seeds); no 2018-2025 outcome was read for anything below.", ""]
    if r["probe"]:
        lines += ["## Source probe", "", f"Chosen: {r['probe']['choice']} (`reports/phase8_wetness_sources_probe.md`).", "",
                  "| candidate | verdict |", "|---|---|", *[f"| {c['candidate']} | {c['verdict']} |" for c in r["probe"]["candidates"]], ""]
    if r["tables"]:
        t = r["tables"]
        lines += ["## Inputs", "",
                  "`iwet_sat_l2` (bucket saturation at the end of IMD day D-2), `iwet_sat_anom_l2` (minus its 2007-2015 mean for the "
                  "pixel and month), `iwet_satdays30_l2` (days at 95% or more in the 30 ending at D-2), each non-decreasing. "
                  f"IMERG Late days missing in the history the tables read: {t['imerg_days_missing']['n_missing']}. NaN share per "
                  "file (largest over the three inputs):", "", "| file | rows | NaN share |", "|---|---|---|",
                  *[f"| {name} | {e['rows']:,} | {max(e['nan_share'].values()):.4%} |" for name, e in t["files"].items()], ""]
    s1 = r["stage1"]
    if s1:
        metrics, stage = s1["comparison"]["metrics"], s1["stage_one"]
        lines += ["## Stage 1: the wetness group alone on v3", "",
                  f"The reference C0 reproduces the frozen v3-live FA@90 to {s1['reproduction']['abs_difference']:.1e} with the same "
                  "tree count.", "", "| model | inputs | trees | pooled OOF FA@90 (95% CI) |", "|---|---|---|---|",
                  *[f"| {n} | {c['n_inputs']} | {c['n_trees']} | {_fa(metrics[n][HEADLINE])} |" for n, c in s1["candidates"].items()], "",
                  f"FA@90 is a false-alarm share, lower is better. w4_wet - C0 = {stage['difference']:+.4f}, 95% paired-bootstrap "
                  f"interval [{stage['ci'][0]:+.4f}, {stage['ci'][1]:+.4f}]. Guard: lower bound at or below 0. Stage 1 "
                  f"**{'passed' if stage['passed'] else 'failed'}** ({stage['verdict']}).", ""]
    c = r["checks"]
    if c:
        diffs = c["differences_to_c0"]
        lines += ["## Checks before the look (spec section 5) and the ablation", "",
                  "| check | numbers | rule | flag |", "|---|---|---|---|"]
        for f in c["flags"]:
            if f["name"].startswith("C1"):
                nums = f"v3 + {CLIM} alone {f['fa_at_90_clim_only']:.4f}; w4_wet {f['fa_at_90_w4_wet']:.4f}"
            elif f["name"].startswith("C2"):
                nums = "; ".join(f"{k} {v:+.4f}" for k, v in f["differences"].items())
            else:
                nums = "; ".join(f"{k} {v:.2%}" for k, v in f["gaps"].items())
            lines.append(f"| {f['name']} | {nums} | {f['rule']} | {'FLAG' if f['flag'] else 'no'} |")
        lines += ["", "Within the built-up terciles (w4_wet - C0, paired bootstrap; cells joined on `cell_id`):", "",
                  "| lc_built tercile | positives | universe rows | difference [95% CI] |", "|---|---|---|---|",
                  *[f"| {k} | {v['positives']} | {v['universe_rows']:,} | {_ci(v)} |" for k, v in c["by_built_tercile"].items()], "",
                  "Ablation (reported only, not used to choose inputs): v3 plus", "",
                  "| candidate | trees | pooled OOF FA@90 | difference to C0 [95% CI] |", "|---|---|---|---|",
                  *[f"| {n} | {run['n_trees']} | {c['fa_at_90'][n]:.4f} | {_ci(diffs[f'{n}-C0'])} |" for n, run in c["runs"].items()], ""]
    v5 = r["v5"]
    if v5:
        metrics, stage = v5["comparison"]["metrics"], v5["stage_one"]
        against = v5["comparison"].get("against_incumbent")
        lines += ["## Stage 2: v5 = v4 plus the wetness group", "",
                  f"C0 reproduces the frozen v3-live FA@90 to {v5['reproduction']['abs_difference']:.1e}.", "",
                  "| model | inputs | trees | pooled OOF FA@90 (95% CI) |", "|---|---|---|---|",
                  *[f"| {n} | {cand['n_inputs']} | {cand['n_trees']} | {_fa(metrics[n][HEADLINE])} |" for n, cand in v5["candidates"].items()],
                  *([f"| v4 (stored OOF) | 41 | | {_fa(against['metrics'][HEADLINE])} |"] if against else []), "",
                  f"v5 - C0 = {_ci(v5['comparison']['difference'])}"
                  + (f"; v5 - v4 = {_ci(against['difference'])}" if against else "")
                  + f". Guards: both lower bounds at or below 0. Stage 2 **{'passed' if stage['passed'] else 'failed'}**.", ""]
    lines += ["## Seasons and preflight", "", f"v5 season panels scored: {r['seasons_scored']} of 8 (no outcome read)."]
    if r["preflight"]:
        p = r["preflight"]
        lines.append(f"Preflight {'passed' if p['passed'] else 'FAILED'}: {p['checks'] - len(p['failed'])} of {p['checks']} checks"
                     + (f"; failed: {', '.join(p['failed'])}" if p["failed"] else "") + ". It computes no outcome.")
    lines += ["", "## Caveats", "",
              "- The held-out look is the only test that decides; development numbers are selection-free here but share the "
              "catalogue's reporting bias (C2 looks for it, it cannot remove it).",
              "- Ground truth after 2018 is very incomplete, so held-out detection counts compare models at equal burden and are "
              "not absolute; tolerant matching has a high chance floor at Watch+ and Warning+.",
              "- The bucket is a simple, unfitted water balance driven by satellite rain; it is not a measured soil moisture.",
              "- The live adapter exists and is tested; it is not wired into the live run (a separate, reviewed step).", ""]
    return "\n".join(lines)


def write_report(say=print) -> dict:
    result = collect()
    dump_json(PROJECT_ROOT / "reports" / f"{REPORT_STEM}.json", result)
    (PROJECT_ROOT / "reports" / f"{REPORT_STEM}.md").write_text(markdown(result), encoding="utf-8")
    say(f"status: {result['status']}; wrote reports/{REPORT_STEM}.{{json,md}}")
    return result


def heldout_markdown(result: dict, names: tuple[str, str]) -> str:
    incumbent, candidate = names
    decision, heldout = result["decision"], result["heldout"]
    lines = ["# Antecedent wetness: the held-out look of v5 (phase 8, W4)", "",
             f"**v5 is {'adopted' if decision['adopt'] else 'not adopted'}.** {decision['reason']}.", "",
             f"Criterion fixed before the look: `{result['spec']}` section 4. Development half: `reports/{REPORT_STEM}.md`.", ""]
    if heldout is None:
        return "\n".join([*lines, "No look was taken.", ""])
    scores = heldout["scores"]
    lines += [f"{scores['events']} events in {scores['slides']} independent slides. {candidate} against `{incumbent}` at equal "
              "burden, season by season (W3's burden matching).", "",
              f"| tolerance | level | {incumbent} | {candidate} | difference | not lower | higher |", "|---|---|---|---|---|---|---|",
              *[f"| {c['tolerance']} | {c['level']} | {c['v3']} | {c['candidate']} | {c['difference']:+d} | "
                f"{'yes' if c['not_lower'] else 'NO'} | {'yes' if c['higher'] else 'no'} |" for c in decision["conditions"]], "",
              "All levels:", "", *w3._slide_rows(scores, (incumbent, candidate)), "",
              "Beside it, not deciding, v3 with the section 11 rules:", "", *w3._slide_rows(heldout["scores_v3_rules"], ("v3 with rules", candidate)), "",
              "Ground truth after 2018 is very incomplete; detection counts compare models at equal burden. Adoption into the live "
              "run is a separate, reviewed step.", ""]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("stage", choices=["checks", "report", "heldout-report"])
    parser.add_argument("--features", type=Path, default=None)
    args = parser.parse_args(argv)

    def say(message: str) -> None:
        print(message, flush=True)
    if args.stage == "checks":
        record = run_checks(args.features, say)
        return 0 if record["passed"] else 1
    if args.stage == "report":
        write_report(say)
        return 0
    study = w3.load_study(V5_CONFIG)
    w3.write_report(study, render=lambda result: heldout_markdown(result, w3.pool_names(study)), say=say)
    return 0


if __name__ == "__main__":
    sys.exit(main())
