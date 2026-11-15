"""Markdown of the heavy-rain warning study, rendered only from `reports/phase8_rain_warnings.json` (no number is typed).

    python -m aetherguard.rainwarn report       re-render the markdown from the JSON
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from ..config import PROJECT_ROOT
from . import prob as P

LEAD_NAMES = {"0": "D (today)", "1": "D+1", "2": "D+2", "3": "D+3"}
REGIONS = ("domain", "himalaya", "western_ghats")


def paths(cfg: dict) -> tuple[Path, Path]:
    stem = PROJECT_ROOT / cfg["report"]
    return stem.with_suffix(".json"), stem.with_suffix(".md")


def clean(value):
    """NaN and infinities become null; numpy scalars become Python numbers."""
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def write(cfg: dict, payload: dict) -> None:
    payload = clean(payload)
    json_path, md_path = paths(cfg)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=1, allow_nan=False) + "\n", encoding="utf-8")
    md_path.write_text(render(payload), encoding="utf-8")


def rerender(cfg: dict) -> int:
    json_path, md_path = paths(cfg)
    md_path.write_text(render(json.loads(json_path.read_text(encoding="utf-8"))), encoding="utf-8")
    print(f"[rainwarn] wrote {md_path}")
    return 0


def f(value, digits: int = 3) -> str:
    if value is None:
        return "-"
    return f"{value:.{digits}f}"


def pct(value, digits: int = 2) -> str:
    return "-" if value is None else f"{100 * value:.{digits}f}%"


def ci(pair, digits: int = 3) -> str:
    if not pair or pair[0] is None:
        return "-"
    return f"[{pair[0]:+.{digits}f}, {pair[1]:+.{digits}f}]"


def yes(flag) -> str:
    return "yes" if flag else "no"


def verdict(s: dict) -> str:
    if not s.get("enough_events"):
        return "too few events to conclude"
    parts = [("skilful" if s["skilful"] else "NOT skilful"),
             ("beats every baseline" if s["beats_baselines"] else
              "does not beat " + ", ".join(k for k, v in s["beats"].items() if not v) if s["beats"] else "no baseline"),
             ("reliable" if s["reliable"] else "NOT reliable"),
             ("discriminates" if s["discriminates"] else "does NOT discriminate")]
    return "; ".join(parts)


def headline(payload: dict, set_name: str) -> list[str]:
    lines = ["| lead | threshold | region | event pixel-days | event days | BSS (95% CI) | ROC area (CI) | REL/UNC | mean p / base rate | verdict |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for lead, data in payload["leads"].items():
        block = data["sets"].get(set_name)
        if block is None:
            continue
        for name in P.THRESHOLDS:
            for region in REGIONS:
                e = block["thresholds"][name][region]
                p = e["product"]
                if not p.get("n"):
                    continue
                lines.append(f"| {LEAD_NAMES[lead]} | {name} | {region} | {p['events']} | {p['event_days']} | "
                             f"{f(p.get('bss'))} {ci(p.get('bss_ci'))} | {f(p.get('auc'))} {ci(p.get('auc_ci'))} | "
                             f"{f(p.get('rel_over_unc'))} | {f(p.get('calibration_in_the_large'), 2)} | "
                             f"{verdict(e['statements'])} |")
    return lines


def baselines_table(payload: dict, set_name: str) -> list[str]:
    lines = ["| lead | threshold | BS product | BS climatology | BS raw ensemble | baseline: BS, diff (95% CI), hit rate, FAR |",
             "|---|---|---|---|---|---|"]
    for lead, data in payload["leads"].items():
        block = data["sets"].get(set_name)
        if block is None:
            continue
        for name in P.THRESHOLDS:
            e = block["thresholds"][name]["domain"]
            p = e["product"]
            if not p.get("n"):
                continue
            base = []
            for k, v in p.get("vs", {}).items():
                det = e["baselines"].get(k, {})
                base.append(f"{k}: {f(v['bs'], 5)}, {v['diff']:+.5f} {ci(v['diff_ci'], 5)}, "
                            f"{f(det.get('hit_rate'), 3)}, {f(det.get('false_alarm_ratio'), 3)}")
            raw = e.get("raw", {}).get("bs")
            lines.append(f"| {LEAD_NAMES[lead]} | {name} | {f(p['bs'], 5)} | {f(p['bs_reference'], 5)} | {f(raw, 5)} | "
                         f"{'; '.join(base) or '-'} |")
    return lines


def raw_table(payload: dict, set_name: str) -> list[str]:
    lines = ["| lead | threshold | raw BSS (CI) | raw ROC area | raw mean p / base rate | calibrated BSS |", "|---|---|---|---|---|---|"]
    for lead, data in payload["leads"].items():
        if lead == "0":
            continue
        block = data["sets"].get(set_name)
        for name in P.THRESHOLDS:
            e = block["thresholds"][name]["domain"]
            raw = e.get("raw")
            if not raw or raw.get("bs") is None:
                continue
            lines.append(f"| {LEAD_NAMES[lead]} | {name} | {f(raw.get('bss'))} {ci(raw.get('bss_ci'))} | {f(raw.get('auc'))} | "
                         f"{f(raw.get('calibration_in_the_large'), 2)} | {f(e['product'].get('bss'))} |")
    return lines


def reliability_tables(payload: dict, set_name: str, lead: str, names=("heavy", "very_heavy", "p95")) -> list[str]:
    lines = []
    block = payload["leads"][lead]["sets"].get(set_name)
    for name in names:
        p = block["thresholds"][name]["domain"]["product"]
        if not p.get("n"):
            continue
        lines += ["", f"Lead {LEAD_NAMES[lead]}, {name}, domain:", "",
                  "| probability bin | pixel-days | mean probability | observed frequency |", "|---|---|---|---|"]
        for b in p["reliability"]:
            if b["n"]:
                lines.append(f"| {b['bin'][0]:.2f}-{b['bin'][1]:.2f} | {b['n']} | {f(b['mean_prob'], 4)} | {f(b['observed'], 4)} |")
    return lines


def imd_table(payload: dict, set_name: str) -> list[str]:
    lines = ["| lead | threshold | region | pixel-days | events | BSS vs sample climatology (CI) | ROC area | mean p / IMD base rate |",
             "|---|---|---|---|---|---|---|---|"]
    for lead, data in payload["leads"].items():
        block = data["sets"].get(set_name)
        for name in P.FIXED_MM:
            for region in REGIONS:
                imd = block["thresholds"][name][region].get("imd")
                if not imd or not imd.get("n"):
                    continue
                lines.append(f"| {LEAD_NAMES[lead]} | {name} | {region} | {imd['n']} | {imd['events']} | "
                             f"{f(imd.get('bss'))} {ci(imd.get('bss_ci'))} | {f(imd.get('auc'))} | "
                             f"{f(imd.get('calibration_in_the_large'), 2)} |")
    return lines


def levels_table(payload: dict, set_name: str | None) -> list[str]:
    lines = ["| lead | level | share of pixel-days | pixel-days | observed >= heavy | observed >= very heavy | share of heavy events | share of very heavy events |",
             "|---|---|---|---|---|---|---|---|"]
    for lead, data in payload["leads"].items():
        table = data["shipped_levels_in_sample"]["domain"] if set_name is None else data["sets"][set_name]["levels"]["domain"]
        for level in ("none", "yellow", "orange", "red", "unavailable"):
            e = table["levels"][level]
            if not e["n"] and level == "unavailable":
                continue
            lines.append(f"| {LEAD_NAMES[lead]} | {level} | {pct(e['share'], 3)} | {e['n']} | {pct(e['freq_heavy_or_more'], 1)} | "
                         f"{pct(e['freq_very_heavy_or_more'], 1)} | {pct(e['share_of_heavy_events'], 1)} | "
                         f"{pct(e['share_of_very_heavy_events'], 1)} |")
    return lines


def fits_table(payload: dict) -> list[str]:
    lines = ["| lead | threshold | radius (pixels) | fitting pixel-days | events | log loss by radius |", "|---|---|---|---|---|---|"]
    for lead, data in payload["leads"].items():
        for name, e in data["shipped_fit"].items():
            losses = ", ".join(f"r{r}: {v:.5f}" for r, v in e["log_loss_by_radius"].items())
            lines.append(f"| {LEAD_NAMES[lead]} | {name} | {e['radius']} | {e['n']} | {e['n_events']} | {losses} |")
    return lines


def render(payload: dict) -> str:
    sets = payload["sets"]
    out = ["# Probabilistic heavy-rain warnings: verification", "",
           f"Spec: `{payload['spec']}` (criteria declared before any number). Research prototype: not validated for issuing "
           "real public warnings. This product does not read or change any landslide alert level.", "",
           f"Truth: {payload['observed']}. Forecast: {payload['forecast']}. Domain: {payload['domain_pixels']} pixels of 0.1 degree "
           f"holding the assessed cells (himalaya {payload['regions']['himalaya']}, western_ghats {payload['regions']['western_ghats']}). "
           f"Issue days with an ECMWF file: {payload['issue_days']}. Climatology: IMERG Late {payload['climatology']['years'][0]}-"
           f"{payload['climatology']['years'][1]}, +-{payload['climatology']['window_days']} days, percentile thresholds floored at "
           f"{payload['climatology']['percentile_floor_mm']} mm. Intervals: {payload['bootstrap']['n']} bootstrap resamples of test "
           "days (each day keeps all its pixels).", "",
           "Statement rules (spec section 6): enough events = at least "
           f"{payload['statement_rules']['min_event_pixel_days']} event pixel-days on at least {payload['statement_rules']['min_event_days']} "
           "distinct days; skilful = BSS 95% interval above 0 (reference: the pixel's climatology for the day of year); beats the "
           "baselines = BS(product) - BS(baseline) interval below 0 for every 0/1 baseline of the lead (lead 0: the observed total "
           "thresholded; leads 1-3: GFS, ECMWF ensemble mean, ECMWF HRES); reliable = REL/UNC at most "
           f"{payload['statement_rules']['rel_over_unc_max']} and mean probability / base rate within "
           f"{payload['statement_rules']['calibration_in_the_large']}; discriminates = ROC-area interval above 0.5.", ""]
    for set_name, s in sets.items():
        fit = ", ".join(f"{r['first']}..{r['last']}" for r in s["fit"])
        test = s["test"]
        out += [f"## Test set `{set_name}` ({s['role']}): test {test['first']}..{test['last']}, fitted on {fit}", ""]
        days = next(iter(payload["leads"].values()))["sets"][set_name]["test_days"]
        out += [f"Test issue days with an ECMWF file: {days[2]} ({days[0]}..{days[1]}).", ""]
        out += ["### Headline (product = calibrated probability)", ""] + headline(payload, set_name) + [""]
        out += ["### Against the deterministic baselines and the raw ensemble (domain)", ""] + baselines_table(payload, set_name) + [""]
        out += ["### Raw quantile probability (uncalibrated) beside the product (domain)", ""] + raw_table(payload, set_name) + [""]
        out += ["### Reliability (domain)"] + reliability_tables(payload, set_name, "1") + reliability_tables(payload, set_name, "0", ("heavy",)) + [""]
        if any(payload["leads"][l]["sets"][set_name]["thresholds"]["heavy"]["domain"].get("imd") for l in payload["leads"]):
            out += ["### Second opinion: IMD gridded rainfall (0.25 degree, India only)", ""] + imd_table(payload, set_name) + [""]
        out += ["### Warning levels on this test set (domain)", ""] + levels_table(payload, set_name) + [""]
    out += ["## Shipped calibration (fitted on June-September 2023 + 2024)", "",
            f"File: `data/{payload['shipped_calibration']}`. Expected level frequency = the in-sample share on its fitting days:", ""]
    out += levels_table(payload, None) + ["", "Chosen neighbourhood radius per lead and threshold:", ""] + fits_table(payload) + [""]
    return "\n".join(out) + "\n"
