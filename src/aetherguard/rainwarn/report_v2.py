"""Markdown of the v2 rain-warning study (spec section 12), rendered only from `reports/phase8_rain_warnings_v2.json`."""
from __future__ import annotations

import json

from . import prob as P
from . import report as R
from . import v2

ROWS = ("heavy", "very_heavy", "extremely_heavy", "p95", "p99")


def _as_sets(test: dict, name: str) -> dict:
    return {"leads": {lead: {"sets": {name: block}} for lead, block in test["leads"].items()}}


def _fold_table(dev: dict) -> list[str]:
    lines = ["| lead | threshold | candidate | cross-season log loss (sum) | test 2024: BSS, mean p / base rate | test 2023: BSS, mean p / base rate |",
             "|---|---|---|---|---|---|"]
    for lead, data in dev["leads"].items():
        for name in ROWS:
            for cand in data["cross_season"]:
                loss = data["cross_season"][cand][name]["log_loss_sum"]
                f24 = data["folds"][cand]["test_2024"][name]
                f23 = data["folds"][cand]["test_2023"][name]
                lines.append(f"| {R.LEAD_NAMES[lead]} | {name} | {cand} | {loss:.1f} | {R.f(f24['bss'])}, "
                             f"{R.f(f24['calibration_in_the_large'], 2)} | {R.f(f23['bss'])}, {R.f(f23['calibration_in_the_large'], 2)} |")
    return lines


def _cutoffs(dev: dict) -> list[str]:
    lines = ["| lead | red: P_vh >= | orange: max(P_h, P_99) >= | yellow: max(P_h, P_95) >= | pixel-days |", "|---|---|---|---|---|"]
    for lead, c in dev["levels"].items():
        lines.append(f"| {R.LEAD_NAMES[lead]} | {c['red']:.4f} | {c['orange']:.4f} | {c['yellow']:.4f} | {c['n']} |")
    return lines


def _levels(tables: dict) -> list[str]:
    lines = ["| lead | level | share of pixel-days | observed >= heavy | share of heavy events | share of very heavy events |",
             "|---|---|---|---|---|---|"]
    for lead, by_region in tables.items():
        t = by_region["domain"]["levels"]
        for level in ("none", "yellow", "orange", "red"):
            e = t[level]
            lines.append(f"| {R.LEAD_NAMES[lead]} | {level} | {R.pct(e['share'], 3)} | {R.pct(e['freq_heavy_or_more'], 1)} | "
                         f"{R.pct(e['share_of_heavy_events'], 1)} | {R.pct(e['share_of_very_heavy_events'], 1)} |")
    return lines


def render(payload: dict) -> str:
    dev = payload["dev"]
    t = payload["targets"]
    out = ["# Heavy-rain warnings v2: shipped calibration, levels at target frequencies, the test on June-September 2025", "",
           f"Spec: `{payload['spec']}`, committed before any 2025 data was fetched. Research prototype: not validated for "
           "public warnings; it does not change any landslide alert level. Base report: `reports/phase8_rain_warnings.md`.", "",
           "## Development (June-September 2023 + 2024 only)", "",
           f"Candidate A = the section 4 predictors; B = A plus the season-state predictor. Cross-season log loss summed over "
           f"D+1..D+3 and the five thresholds: A {dev['cross_season_log_loss']['A']:.1f}, B {dev['cross_season_log_loss']['B']:.1f}. "
           f"Shipped: **{dev['chosen']}** (lead 0 keeps A). Calibration file `data/{payload['calibration']}` "
           f"(sha256 {payload['calibration_sha256'][:12]}).", ""]
    out += _fold_table(dev) + [""]
    out += [f"Level cutoffs per lead, set on the 2023 + 2024 pixel-days so that red fires on {R.pct(t['red'], 1)}, orange or "
            f"above on {R.pct(t['orange'], 1)} and yellow or above on {R.pct(t['yellow'], 1)}:", ""] + _cutoffs(dev) + [""]
    out += ["In sample (2023 + 2024, shipped calibration, v2 levels):", ""] + _levels(dev["insample_levels"]) + [""]
    test = payload.get("test_2025")
    if test is None:
        out += ["## June-September 2025", "", "Not run yet.", ""]
        return "\n".join(out) + "\n"
    verdict = test["verdict"]
    out += ["## The one test on June-September 2025", "",
            f"Issue days with an ECMWF file: {test['issue_days']} ({test['first']}..{test['last']}); calibration sha256 "
            f"{test['calibration_sha256'][:12]}. No GFS and no IMD grid exist locally for 2025, so the GFS baseline and the IMD second opinion are absent; the ECMWF ensemble-mean and HRES baselines are scored.", "",
            f"**Verdict: {'PASS' if verdict['pass'] else 'FAIL'}** (spec section 12.4).", "",
            "| check | value | rule | met |", "|---|---|---|---|"]
    for c in verdict["checks"]:
        value = c["value"]
        if isinstance(value, float):
            value = f"{value:.3f}"
        out.append(f"| {c['check']} | {value} | {c['rule']} | {'yes' if c['ok'] else 'NO'} |")
    sets = _as_sets(test, "test_2025")
    out += ["", "### All rows (product = shipped v2 calibration)", ""] + R.headline(sets, "test_2025") + [""]
    out += ["### Warning levels on 2025 (domain)", ""] + _levels({k: v["levels"] for k, v in test["leads"].items()}) + [""]
    out += ["### Reliability on 2025 (domain)"] + R.reliability_tables(sets, "test_2025", "1") + [""]
    return "\n".join(out) + "\n"


def rerender() -> int:
    json_path, md_path = v2.report_paths()
    md_path.write_text(render(json.loads(json_path.read_text(encoding="utf-8"))), encoding="utf-8")
    print(f"[rainwarn] wrote {md_path}")
    return 0
