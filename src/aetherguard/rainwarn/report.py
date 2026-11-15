"""Markdown of the heavy-rain warning study, rendered only from `reports/phase8_rain_warnings.json` (no number is typed).

    python -m aetherguard.rainwarn report       re-render the markdown from the JSON
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from ..config import PROJECT_ROOT
from . import prob as P

LEAD_NAMES = {"0": "D (today, mostly observed)", "1": "D+1", "2": "D+2", "3": "D+3"}
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


def statement_summary(payload: dict, set_name: str) -> list[str]:
    """One line per lead and threshold of the set: the verdict per region with the events it rests on."""
    lines = []
    for lead, data in payload["leads"].items():
        block = data["sets"].get(set_name)
        if block is None:
            continue
        for name in P.THRESHOLDS:
            parts = []
            for region in REGIONS:
                e = block["thresholds"][name][region]
                p = e["product"]
                if not p.get("n"):
                    continue
                parts.append(f"{region}: {verdict(e['statements'])} ({p['events']} event pixel-days on {p['event_days']} days)")
            lines.append(f"- {LEAD_NAMES[lead]}, {name}: " + "; ".join(parts))
    return lines


def _bss_of(entry: dict, kind: str):
    """BSS of a 0/1 baseline against the same climatology as the product."""
    clim_bs = entry["climatology"].get("bs")
    base = entry["baselines"].get(kind, {})
    return None if not clim_bs or base.get("bs") is None else 1 - base["bs"] / clim_bs


def lead0_decomposition(payload: dict) -> list[str]:
    """How much of the lead-0 skill is the observed rain itself: the BSS of the observed total thresholded (no
    probability, no forecast), of the product, the product at D+1, and the IMD second opinion of lead 0."""
    lines = ["## How much of the D (today) skill is observation, not forecast", "",
             "At the run time (05:30 UTC of D) IMD day D has ended. 21 of its 24 hours are already observed by IMERG Early "
             "(UTC day D-1); only 00-03 UTC of D comes from a forecast, the GFS 00Z 0-3 h tail (in the archive the tail is "
             "persistence of D-1, so the study's lead 0 contains no forecast at all). Lead 0 is therefore a calibrated "
             "observation of rain that has already fallen, not a forecast. Its truth, IMERG Late, is the same satellite "
             "algorithm as Early run later with more input, so the two agree far better than either agrees with rain "
             "gauges. The table separates the parts: `observed 0/1` is the Early total thresholded (no calibration); the "
             "product adds the logistic map from Early to Late; `D+1` is the first real forecast; `IMD` scores the lead-0 "
             "product against the IMD gauge grid instead (sample-climatology reference).", "",
             "| test set | threshold | lead-0 days scored | BSS observed 0/1 | BSS lead-0 product | BSS D+1 product | lead-0 BSS vs IMD (CI) | lead-0 ROC area vs IMD |",
             "|---|---|---|---|---|---|---|---|"]
    lead0, lead1 = payload["leads"]["0"], payload["leads"]["1"]
    for set_name in payload["sets"]:
        block0, block1 = lead0["sets"][set_name], lead1["sets"][set_name]
        counts = block0["counts"]
        scored = counts["issue_days"] - counts["no_inputs"] - counts["no_truth"]
        for name in P.THRESHOLDS:
            e0, e1 = block0["thresholds"][name]["domain"], block1["thresholds"][name]["domain"]
            if not e0["product"].get("events"):
                continue
            imd = e0.get("imd") or {}
            lines.append(f"| {set_name} | {name} | {scored} of {counts['issue_days']} | {f(_bss_of(e0, 'observed'))} | "
                         f"{f(e0['product'].get('bss'))} | {f(e1['product'].get('bss'))} | {f(imd.get('bss'))} {ci(imd.get('bss_ci'))} | "
                         f"{f(imd.get('auc'))} |")
    lines += ["", "Reading: for heavy, very heavy and the two percentiles in the monsoon sets, most of the lead-0 Brier skill "
              "is already in the observed total thresholded; for the rarer rows the calibration, which learns how Early totals "
              "map onto Late totals, adds most of it. None of it is forecast skill, and against the independent IMD grid the lead-0 skill is much smaller "
              "and in some rows below zero. Lead-0 days without IMERG Early in the local store (16 August to 30 September "
              "of 2023 and 2024 are not in it) are not scored; the column gives the count.", ""]
    return lines


def unreliable_rows(payload: dict) -> list[str]:
    """The leads 1-3 rows of the heavier thresholds: base rate of the fitting season against the test season, mean
    probability / base rate, REL/UNC and the fitting events behind each calibration."""
    lines = ["## The rows marked NOT reliable at D+1..D+3", "",
             "`mean p / base rate` below 1 means the probabilities are too low on average (the event happens more often "
             "than forecast), above 1 too high. Each calibration is fitted on one season and tested on the other, so the "
             "two monsoon test sets swap roles:", "",
             "| lead | threshold | test set | fitting base rate | test base rate | mean p / base rate | REL/UNC | fitting events (pixel-days) | BSS (CI) |",
             "|---|---|---|---|---|---|---|---|---|"]
    for lead in ("1", "2", "3"):
        data = payload["leads"][lead]
        for name in ("very_heavy", "extremely_heavy", "heavy"):
            for set_name in ("test_2024", "test_2023"):
                if set_name not in data["sets"]:
                    continue
                p = data["sets"][set_name]["thresholds"][name]["domain"]["product"]
                fit = data["fits"][set_name][name]
                fit_rate = fit["n_events"] / fit["n"] if fit["n"] else None
                lines.append(f"| {LEAD_NAMES[lead]} | {name} | {set_name} | {pct(fit_rate, 3)} | {pct(p.get('base_rate'), 3)} | "
                             f"{f(p.get('calibration_in_the_large'), 2)} | {f(p.get('rel_over_unc'))} | {fit['n_events']} | "
                             f"{f(p.get('bss'))} {ci(p.get('bss_ci'))} |")
    lines += ["", "What it means in practice: the shape of the calibration holds (REL/UNC stays small and the ROC area high, "
              "so higher probabilities do mark wetter pixels), but its level is set by how often very heavy and extremely "
              "heavy rain happened in the one fitting season. The two monsoon seasons differ by several times in that "
              "frequency, so a map fitted on the drier season under-warns in the wetter one (orange and red issued too "
              "rarely) and the reverse. For extremely heavy rain the fitting season can hold only tens of event pixel-days "
              "on a handful of days, so that calibration is barely constrained.", "",
              "Is a recalibration on more training days the fix? Partly. Fitting on both seasons (the shipped calibration) "
              "averages the two base rates and gives the extremely heavy fit several times more events, which removes the "
              "worst of the under- and over-forecasting seen here; that is expected, not shown, because no third monsoon "
              "season is left to test it on. It cannot remove the season-to-season swing itself: no fixed map knows in "
              "advance whether a monsoon will be wet. That needs either more seasons (so the average is a good one and the "
              "swing is measured) or a predictor that carries the season's state (for example the observed rain of the past "
              "weeks), and a third season (June-September 2025 from the open ECMWF buckets) to test it. Until then the "
              "very heavy and extremely heavy probabilities at D+1..D+3 should be read as a ranking of where the risk is "
              "highest, not as calibrated frequencies.", ""]
    return lines


LIMITS = """## What this can and cannot conclude

- The truth is IMERG Late, a satellite estimate. Skill against IMERG is not skill against rain gauges; the IMD grid is
  shown as a second opinion at 0.25 degree, with the sample base rate as reference, and its day convention in the local
  store is marked unconfirmed.
- Lead 0 is fitted on IMERG Early against IMERG Late. The two runs share the algorithm and most of the microwave input,
  so the lead-0 scores against Late are optimistic; the IMD second opinion is the independent check of lead 0.
- Pixel-days are not independent: rain on one day covers many neighbouring pixels. The intervals resample whole days,
  and a statement needs a minimum number of distinct event days, so a large pixel-day count alone does not make a
  conclusion.
- The ensemble archive is two monsoon seasons; the 2026 set is October-November, where heavy rain is rare. A threshold
  marked "too few events" carries no conclusion, in either direction.
- The ensemble is summarised by four stored statistics; the raw probability is rebuilt from them, not counted from
  members.

## What a longer archive would add

The ECMWF open-data buckets hold every ensemble member from 2023 on, anonymously. Fetching June-September 2025 (an
existing command, `ingest.ecmwf.fetch_archive`) would add a third monsoon season, so the calibration could be fitted on
two seasons and tested on a third; adding the non-monsoon months would allow a seasonal calibration; storing the member
fraction above each threshold in the day file would replace the rebuilt CDF with the real one. Extremely heavy days
per region would then be numerous enough for a statement.

## Wiring into the daily run (branch only; not done)

`configs/live_run.yaml` carries `rain_warnings.enabled: false`. To switch it on, the live run would call
`aetherguard.rainwarn.product.run_day` for day D after its landslide tables are written, with the run directory as
both input and output and the shipped calibration, inside a guard that records a failure in `run.json` without failing
the run. It reads only `features_D0.parquet` and the ECMWF day file that the run has already fetched, adds
`rain_warnings.parquet` and `rain_warnings.md`, and changes no landslide table (a test checks the bytes);
`GET /api/rain-warnings` then serves it. That switch is the lead's step after the user's yes.
"""


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
        out += ["### Statements (pre-declared tests)", ""] + statement_summary(payload, set_name) + [""]
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
    out += lead0_decomposition(payload) + unreliable_rows(payload)
    out += [LIMITS]
    return "\n".join(out) + "\n"
