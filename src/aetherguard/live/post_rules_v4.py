"""The section 11 post-model rules re-derived for model v4, on development data only.

    python -m aetherguard.live.post_rules_v4 score-dev   [--years 2007-2017]   # v4 fold models, out-of-fold panels
    python -m aetherguard.live.post_rules_v4 analyze-dev [--force]             # the rules -> post_rules_v4.json
    python -m aetherguard.live.post_rules_v4 report                            # reports/phase8_post_rules_v4.{json,md}

Why. Since 2026-11-13 lead 0 is scored by v4 (`configs/live_run.yaml` `lead0_model_config`), but the post-model rules of the
run (`post_rules_v3.json`: the ensemble-agreement minimum, the rain trigger, the hold windows and the blind-hold limit) were
chosen on v3's development out-of-fold risk. v4 has a different risk distribution and its own card thresholds, so the rules
are chosen again for it with the method that chose v3's, and nothing else:

* `score-dev` is `hardening score-dev` with the v4 configuration: the year-blocked cross-validation models of v4 (the same
  folds, seeds, hyper-parameters, tree count and ensemble as `hazard.v4_combined dev` cross-validated it, refitted by
  `burden.fold_models` on v4's development rows, which must reproduce the out-of-fold recall at Watch the v4 card
  reports), scoring June-September of every development year (2007-2017) out of fold on the cells of the v3 study (every
  development-event cell plus the same seeded 5,000 universe cells). The features are those v4 was trained on: the
  training-style rain features of the backtest, the six rain-intensity inputs of the complete half-hourly Late days at
  the card's lag (`imerg_intensity.cell_features`), and the nine static inputs of each cell (`static_w5`). A season whose
  panel exists is kept.
* `analyze-dev` runs `hardening_dev.run` on those panels with the v4 card's thresholds and `alert_config_v3.json` (the
  pre-declared steps, candidates and adoption rules of section 11, unchanged) and writes the rules to a NEW file,
  `data/processed/alerts/post_rules_v4.json`. `lead_uncertain_bound` is a forecast-lead parameter chosen on v3's
  forecast-skill pairs; the forecast leads are still scored by v3, so it is copied from the v3 rules and says so.
* `report` evaluates v4 on its development panels with no rules, with the v3 rules (what the live run applies to v4 today)
  and with the v4 rules: alert-cell-day shares and development event detection at each level (own cell, event day), and
  the parameters side by side. v3 on its own panels with its own rules is shown for reference.

Nothing here reads 2018-2025, the held-out events or a live day, and nothing here changes what the live run reads: the
live configuration keeps `post_rules_v3.json` until the one held-out look of
`docs/superpowers/specs/2026-11-13-aetherguard-post-rules-v4.md` has been taken and passed.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from ..alerts import levels as lv
from ..alerts.config import load_config_file as load_alert_config
from ..config import PROJECT_ROOT, data_root
from ..features import imerg_intensity as ii
from ..features import static_w5 as sw
from ..hazard import model as hm
from ..hazard.jsonio import dump_json
from . import backtest as bt
from . import burden
from . import hardening as H
from . import postrules as pr
from . import run as live_run

V4_MODEL_CONFIG = "configs/hazard_model_v4_live.yaml"
V4_STUDY = "configs/hazard_v4.yaml"
PANEL_DIR = "accuracy_hardening_oof_v4"            # under data/processed/alerts/, next to v3's accuracy_hardening_oof
V3_PANEL_DIR = H.DEV_DIR
RULES_V3 = "data/processed/alerts/post_rules_v3.json"
RULES_V4 = "data/processed/alerts/post_rules_v4.json"
REPORT_STEM = "phase8_post_rules_v4"
MODEL_TEXT = ("the year-blocked cross-validation models of the v4 configuration (configs/hazard_v4.yaml, refitted with the "
              "folds, seeds and tree count of the model_v4_live card), each scoring the years it did not train on "
              "(out-of-fold, the setting the card's thresholds were set in)")
CAVEATS = [
    "Development data only (2007-2017, June-September, out of fold); no held-out number is in this report.",
    "Detection is cell-exact on the event cell and day (development positives), so it counts what the catalogues "
    "recorded; the catalogues miss most landslides, so alert cell-days far from a recorded event are not all false alarms.",
    "Alert shares are on the 5,000 seeded universe cells of the study, not on every scored cell.",
    "The rules are chosen in sample on these seasons by pre-declared rules; the burden change here is not evidence of a "
    "held-out gain, which only the one look of the spec decides.",
    "The ensemble-agreement rule changes confidence, not the level, so it does not move any number of the level tables.",
]


def alerts_dir(name: str) -> Path:
    return data_root() / "processed" / "alerts" / name


def v4_cfg(cfg: dict) -> dict:
    """The run configuration with `model_config` naming v4: what the derivation steps read the card and thresholds from."""
    return {**cfg, "model_config": V4_MODEL_CONFIG}


def day_features(day, cells: pd.DataFrame, stores: bt.Stores, root: Path, lag_days: int,
                 static: pd.DataFrame | None) -> pd.DataFrame:
    """v4's inputs of `cells` on IMD day `day` as training built them: the training-style rain features, the six intensity
    inputs of the complete Late days at `lag_days`, and the static inputs (one row per cell, default index)."""
    base = bt.training_style_features(day, cells, stores).reset_index(drop=True)
    intensity = ii.cell_features(day, cells["cell_id"].to_numpy(dtype=np.int64), root, ii.RUN, lag_days)
    parts = [base, intensity] + ([static.reset_index(drop=True)] if static is not None else [])
    return pd.concat(parts, axis=1)


def missing_intensity_days(years, root: Path, lag_days: int) -> list:
    days = [d for year in years for d in burden.season_days(year)[0]]
    return ii.missing_days(root, ii.window_days(days, lag_days), ii.RUN)


def score_dev(years, cfg: dict, directory: Path, say, root: Path | None = None) -> None:
    """The out-of-fold v4 panels of the development seasons (module doc); a season whose file exists is kept."""
    from ..hazard import v4_int
    burden._assert_development(years)
    model = live_run.load_live_model(v4_cfg(cfg))
    lag = int(model.card.get("intensity", {}).get("lag_days", 0))
    static_names = [c for c in model.columns if c in sw.STATIC_COLUMNS]
    root = Path(root or ii.default_root())
    missing = missing_intensity_days(years, root, lag)
    if missing:
        raise ValueError(f"{len(missing)} half-hourly Late day files are missing under {root} ({ii.format_ranges(missing)})")
    study = v4_int.load_study(PROJECT_ROOT / V4_STUDY)
    events = burden.development_events(years)
    cells, kept, counts = burden.development_cells(events, cfg)
    cells = burden.sample_cells(kept, cells, burden.OOF_SAMPLE["cells"], burden.OOF_SAMPLE["seed"])
    say(json.dumps(counts))
    dev = v4_int.load_development(study, None, lag)
    absent = [c for c in model.columns if c not in dev.samples.columns]
    if absent:
        raise ValueError(f"the v4 development rows lack the model inputs {absent}")
    models, check = burden.fold_models(model, study["base"], progress=say, dev=dev)
    directory.mkdir(parents=True, exist_ok=True)
    dump_json(directory / burden.OOF_CHECK_FILE, {**check, "cells": int(len(cells)), "sample": burden.OOF_SAMPLE,
                                                  "model_config": V4_MODEL_CONFIG, "lag_days": lag,
                                                  "static_inputs": static_names})
    say(json.dumps(check))
    if abs(check["oof_recall_at_watch"] - check["card_oof_recall_at_watch"]) > 1e-12:
        raise ValueError(f"the refitted v4 fold models do not reproduce the card's out-of-fold recall: {check}")
    static = sw.join_static(cells[["cell_id"]], sw.static_table())[static_names] if static_names else None
    stores = bt.build_stores(cells, cfg)
    for year in years:
        path = H.season_path(directory, year)
        if path.is_file():
            continue
        say(f"season {year}")
        started = time.perf_counter()
        days, _ = burden.season_days(year)
        panel = H.score_panel(days, cells, lambda day: models[day.year],
                              lambda day: day_features(day, cells, stores, root, lag, static), say)
        H.save_panel(path, panel)
        say(f"season {year} written in {time.perf_counter() - started:.0f}s")


def rules_from_analysis(analysis: dict, v3_rules: pr.PostRules) -> pr.PostRules:
    """The PostRules `hardening_dev.run` chose, with the forecast-lead bound of the v3 rules (module doc)."""
    chosen = pr.PostRules.from_dict(analysis["rules"], source="v4 development out-of-fold panels")
    from dataclasses import replace
    return replace(chosen, lead_uncertain_bound=v3_rules.lead_uncertain_bound)


def analyze_dev(cfg: dict, directory: Path, rules_path: Path, say, force: bool = False) -> dict:
    if rules_path.exists() and not force:
        raise FileExistsError(f"{rules_path} exists; pass --force to derive it again")
    from . import hardening_dev
    analysis = hardening_dev.run(directory, v4_cfg(cfg), None, say, MODEL_TEXT)
    v3_rules = pr.load_rules(live_run.project_path(RULES_V3))
    rules = rules_from_analysis(analysis, v3_rules)
    pr.save_rules(rules_path, rules, {
        "source": hm.display_path(Path(directory) / hardening_dev.ANALYSIS_FILE),
        "agreement": analysis["agreement"]["choice"], "rain_rule": analysis["rain"]["chosen"],
        "blind_hold": analysis["blind_hold"]["choice"],
        "hold_window": None if analysis["rain"]["hold_window"] is None else
        {k: analysis["rain"]["hold_window"][k] for k in ("chosen", "rule")},
        "protocol": analysis["protocol"],
        "lead_uncertain_bound": {"option": v3_rules.lead_uncertain_bound, "source": RULES_V3,
                                 "note": "a forecast-lead parameter, chosen on v3's forecast-skill pairs; the forecast "
                                         "leads are scored by v3, so it is the v3 rules' value, not re-derived"},
        "status": "development only; not read by the live run until the held-out look of "
                  "docs/superpowers/specs/2026-11-13-aetherguard-post-rules-v4.md has passed"})
    say(f"wrote {rules_path}")
    return analysis


# -------------------------------------------------------------------------------------------------- report

def evaluate_sets(seasons, config, sets: dict[str, pr.PostRules | None]) -> dict:
    from . import hardening_dev as hdv
    return {name: hdv.compact(hdv.evaluate(seasons, "new_hi", config, rules, label=name)) for name, rules in sets.items()}


def parameters(rules: pr.PostRules) -> dict:
    return rules.to_dict()


def build_report(cfg: dict, v4_dir: Path, v3_dir: Path, say=print) -> dict:
    """The development comparison (module doc). Reads the panels and both rule files; writes nothing."""
    from . import hardening_dev as hdv
    config = load_alert_config(live_run.project_path(cfg["alert_config"]))
    v3_rules = pr.load_rules(live_run.project_path(RULES_V3))
    v4_rules = pr.load_rules(live_run.project_path(RULES_V4))
    events = burden.development_events(burden.DEV_YEARS)
    v4_model = live_run.load_live_model(v4_cfg(cfg))
    v3_model = live_run.load_live_model(cfg)
    say("loading the v4 panels")
    v4_seasons = hdv.load_seasons(v4_dir, burden.DEV_YEARS, v4_model.card, events)
    v4 = evaluate_sets(v4_seasons, config, {"v4_no_rules": None, "v4_v3_rules": v3_rules, "v4_v4_rules": v4_rules})
    del v4_seasons
    say("loading the v3 panels")
    v3_seasons = hdv.load_seasons(v3_dir, burden.DEV_YEARS, v3_model.card, events)
    v3 = evaluate_sets(v3_seasons, config, {"v3_no_rules": None, "v3_v3_rules": v3_rules})
    del v3_seasons
    analysis = json.loads((Path(v4_dir) / hdv.ANALYSIS_FILE).read_text(encoding="utf-8"))
    check = json.loads((Path(v4_dir) / burden.OOF_CHECK_FILE).read_text(encoding="utf-8"))
    results = {**v4, **v3}
    deltas = {}
    for level in ("Watch", "Warning", "Emergency"):
        a, b = results["v4_v3_rules"], results["v4_v4_rules"]
        deltas[level] = {"share_v3_rules": a["share_at_least"][level], "share_v4_rules": b["share_at_least"][level],
                         "share_change": b["share_at_least"][level] - a["share_at_least"][level],
                         "hits_v3_rules": a["detected_at_least"][level]["hits"],
                         "hits_v4_rules": b["detected_at_least"][level]["hits"],
                         "hits_change": b["detected_at_least"][level]["hits"] - a["detected_at_least"][level]["hits"]}
    return {"created_utc": pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ"),
            "protocol": analysis["protocol"], "oof_check": check,
            "parameters": {"v3_rules": parameters(v3_rules), "v4_rules": parameters(v4_rules)},
            "derivation_v4": {"agreement": analysis["agreement"], "rain_chosen": analysis["rain"]["chosen"],
                              "rain_positives": analysis["rain"]["positives"], "hold_window": analysis["rain"]["hold_window"],
                              "blind_hold": analysis["blind_hold"], "post_rain": analysis["rain"]["post_rain"]},
            "alert_config": cfg["alert_config"], "events": analysis["events"], "results": results,
            "v4_rules_against_v3_rules": deltas, "caveats": CAVEATS}


def _pct(x) -> str:
    return "-" if x is None else f"{100 * x:.2f}%"


def markdown(result: dict) -> str:
    p3, p4 = result["parameters"]["v3_rules"], result["parameters"]["v4_rules"]
    lines = ["# Post-model rules for model v4 (phase 8, development only)", "",
             "The section 11 rule family (ensemble-agreement minimum, rain trigger, hold windows, blind-hold limit) chosen "
             "again, by the same pre-declared steps as v3's (`live.hardening_dev`), on v4's development out-of-fold risk. "
             "The live run still applies the v3 rules to v4; adopting the v4 rules needs the one held-out look of "
             "`docs/superpowers/specs/2026-11-13-aetherguard-post-rules-v4.md`.", "",
             f"Panels: `{result['protocol']['panels']}`; models: {result['protocol']['model']}. The refitted fold models give "
             f"an out-of-fold recall at Watch of {result['oof_check']['oof_recall_at_watch']:.6f} against the card's "
             f"{result['oof_check']['card_oof_recall_at_watch']:.6f} ({result['oof_check']['positives']} positives). "
             f"Hysteresis and `uncertain_high` from `{result['alert_config']}`. Events in the panel cells: "
             f"{result['events']['in_panel_cells']} (development positives of June-September 2007-2017).", "",
             "## Parameters", "", "| parameter | v3 rules (live today) | v4 rules (derived here) |", "|---|---|---|"]
    for key in ("agreement_min", "rain_minimum_mm", "gated_levels", "hold_window_days", "hold_window_days_by_level",
                "blind_hold_days", "lead_uncertain_bound"):
        lines.append(f"| `{key}` | {json.dumps(p3.get(key))} | {json.dumps(p4.get(key))} |")
    lines += ["", "`lead_uncertain_bound` is a forecast-lead parameter (the leads are scored by v3) and is copied, not "
              "re-derived.", "", "## Development burden and detection", "",
              "Share of universe-sample cell-days at the level or above (June-September) and development events at the "
              "level or above on their own cell and day (95% bootstrap interval of the detected share).", "",
              "| model and rules | Watch+ share | Warning+ share | Emergency share | Watch+ events | Warning+ events | "
              "Emergency events | dry Watch / Warning / Emergency cell-days | median lead (days) |",
              "|---|---|---|---|---|---|---|---|---|"]
    labels = {"v4_no_rules": "v4, no rules", "v4_v3_rules": "v4 with the v3 rules (live today)",
              "v4_v4_rules": "v4 with the v4 rules", "v3_no_rules": "v3, no rules (reference)",
              "v3_v3_rules": "v3 with the v3 rules (reference)"}
    for key, label in labels.items():
        r = result["results"][key]
        det = r["detected_at_least"]
        ev = [f"{det[n]['hits']} / {r['n_events']} ({_pct(det[n]['lo'])}-{_pct(det[n]['hi'])})"
              for n in ("Watch", "Warning", "Emergency")]
        dry = r["dry_cell_days_at"]
        lines.append(f"| {label} | {_pct(r['share_at_least']['Watch'])} | {_pct(r['share_at_least']['Warning'])} | "
                     f"{_pct(r['share_at_least']['Emergency'])} | {' | '.join(ev)} | {dry['Watch']} / {dry['Warning']} / "
                     f"{dry['Emergency']} | {r['median_lead_days']} |")
    lines += ["", "## v4 rules against the v3 rules, both on v4", "",
              "| level | share, v3 rules | share, v4 rules | change | events, v3 rules | events, v4 rules | change |",
              "|---|---|---|---|---|---|---|"]
    for level, d in result["v4_rules_against_v3_rules"].items():
        lines.append(f"| {level}+ | {_pct(d['share_v3_rules'])} | {_pct(d['share_v4_rules'])} | "
                     f"{100 * d['share_change']:+.2f} pp | {d['hits_v3_rules']} | {d['hits_v4_rules']} | {d['hits_change']:+d} |")
    agreement = result["derivation_v4"]["agreement"]
    split = agreement["split"]["by_minimum"].get("0.25", {})
    lines += ["", "## How the v4 rules were chosen", "",
              f"- Ensemble agreement: {agreement['choice']['rule']}. At 0.25 the disagreeing Warning+ alerts give "
              f"{split.get('disagreeing', {}).get('events_per_1000_alerted_cell_days')} events per 1,000 alerted cell-days "
              f"against {split.get('agreeing', {}).get('events_per_1000_alerted_cell_days')} for the agreeing ones -> "
              f"`agreement_min` {json.dumps(agreement['choice']['agreement_min'])}.",
              f"- Rain trigger: {json.dumps(result['derivation_v4']['rain_chosen'])} (candidates: 1st / 2nd / 5th "
              "percentiles of the development positives' 1-, 3-, 7-day IMERG rain; adopted per level when at most 1% of "
              "that level's development events is lost and the share falls).",
              f"- Hold windows: {json.dumps(None if result['derivation_v4']['hold_window'] is None else result['derivation_v4']['hold_window']['chosen'])}.",
              f"- Blind-hold limit: {result['derivation_v4']['blind_hold']['choice']['blind_hold_days']} day(s) "
              f"({result['derivation_v4']['blind_hold']['choice']['rule']}).", "", "## Caveats", "",
              *[f"- {c}" for c in result["caveats"]], ""]
    return "\n".join(lines)


def write_report(cfg: dict, out_dir: Path, say=print) -> dict:
    result = build_report(cfg, alerts_dir(PANEL_DIR), alerts_dir(V3_PANEL_DIR), say)
    out_dir.mkdir(parents=True, exist_ok=True)
    dump_json(out_dir / f"{REPORT_STEM}.json", result)
    (out_dir / f"{REPORT_STEM}.md").write_text(markdown(result), encoding="utf-8")
    say(f"wrote {out_dir / REPORT_STEM}.{{json,md}}")
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m aetherguard.live.post_rules_v4", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    dev = sub.add_parser("score-dev", help="v4 out-of-fold panels of the development seasons")
    dev.add_argument("--years", type=burden.parse_years, default=burden.DEV_YEARS)
    dev.add_argument("--out", type=Path, default=None, help=f"panel directory (default data/processed/alerts/{PANEL_DIR})")
    analysis = sub.add_parser("analyze-dev", help="choose the rules on the v4 panels -> post_rules_v4.json")
    analysis.add_argument("--force", action="store_true")
    report = sub.add_parser("report", help=f"reports/{REPORT_STEM}.{{json,md}}")
    report.add_argument("--out", type=Path, default=PROJECT_ROOT / "reports")
    args = parser.parse_args(argv)
    cfg = live_run.load_run_config()
    say = lambda m: print(m, flush=True)
    try:
        if args.command == "score-dev":
            score_dev(args.years, cfg, args.out or alerts_dir(PANEL_DIR), say)
        elif args.command == "analyze-dev":
            analyze_dev(cfg, alerts_dir(PANEL_DIR), live_run.project_path(RULES_V4), say, args.force)
        else:
            write_report(cfg, args.out, say)
    except (live_run.LiveRunError, ValueError, OSError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
