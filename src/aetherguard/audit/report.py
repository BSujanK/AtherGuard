"""Redaction and Markdown/JSON rendering of the Phase 0 audit."""
from __future__ import annotations

import json
import math
import netrc
import os
import re
from collections import defaultdict
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .env import netrc_candidate_paths
from .result import ProbeResult

ATTENTION = {"needs_login", "manual_pending", "inconclusive", "fail", "unreachable"}
_MIN_SECRET_LENGTH = 4
_MAX_PROBLEM_CHARS = 300
_PROBLEM_KEYS = ("problems", "errors", "failed_downloads", "missing")
_NO_DATA = "_probe did not return data - see Probe problems / Summary_"

_H_SUMMARY = "## Summary"
_H_ATTENTION = "## Needs human action"
_H_PROBLEMS = "## Probe problems"
_H_RAIN = "## Rain products at the reference point"
_H_GHCND = "## Real fault labels (GHCN-Daily quality flags)"
_H_CATALOGS = "## Landslide catalogs"
_H_FEASIBILITY = "## Ingest feasibility and volumes"


def collect_secrets() -> list[str]:
    secrets = [os.environ.get(k, "") for k in ("EARTHDATA_USERNAME", "EARTHDATA_PASSWORD", "EARTHDATA_TOKEN")]
    for path in netrc_candidate_paths():
        try:
            auth = netrc.netrc(str(path)).authenticators("urs.earthdata.nasa.gov")
            if auth:
                secrets += [auth[0] or "", auth[2] or ""]
        except Exception:  # never abort the run over an unreadable/odd netrc (e.g. a non-UTF-8 file)
            continue
    return [s for s in secrets if len(s) >= _MIN_SECRET_LENGTH]


def redact(text: str, secrets: list[str]) -> str:
    for secret in sorted(secrets, key=len, reverse=True):
        if len(secret) >= _MIN_SECRET_LENGTH:
            text = text.replace(secret, "[REDACTED]")
    return text


def _cell(value) -> str:
    """One Markdown table cell: whitespace runs collapsed to a space, pipes escaped."""
    text = " ".join(str(value).split())
    return re.sub(r"(\\*)\|", lambda m: m.group(1) * 2 + "\\|", text)


def _table(headers: list[str], rows: list[list]) -> list[str]:
    lines = ["| " + " | ".join(_cell(h) for h in headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join(_cell(c) for c in row) + " |" for row in rows]
    return lines + [""]


def _by_name(results):
    return {r.name: r for r in results}


def _ev(result) -> dict:
    return result.evidence if isinstance(result.evidence, dict) else {}


def _num(value) -> float | None:
    """A finite float, or None for anything missing, non-numeric, NaN or infinite."""
    if isinstance(value, bool) or not isinstance(value, (int, float, np.number)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _show(value) -> str:
    return "n/a" if value is None else str(value)


def _gb(value) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, (int, float, np.number)) and not isinstance(value, bool):
        return str(value) if math.isfinite(float(value)) else "n/a"
    return str(value)


def _one_line(value, limit: int = _MAX_PROBLEM_CHARS) -> str:
    """Readable single-line text for a problem entry (str, dict or anything else), truncated."""
    if isinstance(value, dict):
        text = ", ".join(f"{k}={v}" for k, v in value.items())
    else:
        text = str(value)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit] + "..."


def _summary_section(results) -> list[str]:
    return [_H_SUMMARY, ""] + _table(["probe", "status", "summary"], [[r.name, r.status, r.summary] for r in results])


def _attention_section(results) -> list[str]:
    lines = [_H_ATTENTION, ""]
    attention = [r for r in results if r.status in ATTENTION]
    if attention:
        return lines + _table(["probe", "status", "what is needed"], [[r.name, r.status, r.summary] for r in attention])
    return lines + ["_Nothing - all probes reported ok or partial._", ""]


def _problems_section(results) -> list[str]:
    lines = [_H_PROBLEMS, ""]
    failing = [r for r in results if r.status != "ok"]
    if not failing:
        return lines + ["_No probe problems - every probe reported ok._", ""]
    for r in failing:
        lines.append(f"**{r.name}** - {r.status}: {_one_line(r.summary)}")
        entries = []
        for key in _PROBLEM_KEYS:
            value = _ev(r).get(key)
            if not value:
                continue
            items = value if isinstance(value, (list, tuple)) else [value]
            entries += [f"{key}: {_one_line(item)}" for item in items]
        lines += [""] + ([f"- {e}" for e in entries] if entries else ["- no further detail recorded"]) + [""]
    return lines


def _rain_section(results, cfg) -> list[str]:
    lines = [_H_RAIN, ""]
    with_values, without = [], []
    for r in results:
        rows = _ev(r).get("event_rows")
        for row in rows if isinstance(rows, (list, tuple)) else []:
            if not isinstance(row, dict):
                continue
            daily = row.get("daily_mm")
            (with_values if isinstance(daily, dict) and daily else without).append((r, row))
    missing_note = []
    if without:
        labels = ", ".join(str(row.get("label", r.name)) for r, row in without)
        missing_note = [f"Rain rows without daily values: {labels}.", ""]
    if not with_values:
        return lines + ["_No rain probe returned data._", ""] + missing_note
    point = cfg.get("reference_point", {}) if isinstance(cfg, dict) else {}
    lines += [f"Reference point: {point.get('name')} ({point.get('lat')} N, {point.get('lon')} E). "
              "Products use different definitions of a 'day' (last column); the windows do not line up "
              "exactly, so totals are indicative only.", ""]
    dates = sorted({str(d) for _, row in with_values for d in row["daily_mm"]})
    body = []
    for result, row in with_values:
        by_date = {str(d): _num(v) for d, v in row["daily_mm"].items()}
        values = [by_date.get(d) for d in dates]
        total = "n/a" if any(v is None for v in values) else f"{sum(values):.0f}"
        body.append([row.get("label", result.name), *["n/a" if v is None else f"{v:.0f}" for v in values], total,
                     result.day_definition or "not stated"])
    lines += _table(["source", *dates, "sum (mm)", "day definition"], body)
    lines += missing_note
    gauge = cfg.get("reported_local_gauge_48h_mm") if isinstance(cfg, dict) else None
    if gauge is not None:
        lines += [f"Reported local gauges: about {gauge} mm in 48 h to 30 Jul 2024 "
                  "(secondary source - press/papers; not yet checked against a primary source).", ""]
    return lines


def _ghcnd_section(results) -> list[str]:
    res = _by_name(results).get("ghcnd")
    lines = [_H_GHCND, ""]
    if not res:
        return lines + ["_Not run._", ""]
    ev = _ev(res)
    if "census_by_group" not in ev:
        return lines + [_NO_DATA, ""]
    lines += [f"Stations selected: {_show(ev.get('n_selected'))} ({_show(ev.get('by_country'))}). A flag means "
              "the value failed an automated NOAA check (the value is kept).", ""]
    extras = []
    if "failed_downloads" in ev:
        failed = ev["failed_downloads"]
        extras.append(f"Failed downloads: {len(failed) if isinstance(failed, (list, tuple)) else 'n/a'}")
    if "n_unknown_elevation" in ev:
        extras.append(f"stations with unknown elevation: {_show(ev['n_unknown_elevation'])} (treated as lowland)")
    if extras:
        lines += ["; ".join(extras) + ".", ""]
    groups = ev["census_by_group"] if isinstance(ev["census_by_group"], dict) else {}
    if not groups:
        return lines + ["_No station groups with readable data._", ""]
    body = []
    for key, value in sorted(groups.items(), key=lambda kv: str(kv[0])):
        value = value if isinstance(value, dict) else {}
        by_flag = value.get("by_flag")
        flags = ", ".join(f"{f}:{n}" for f, n in by_flag.items()) if isinstance(by_flag, dict) else ""
        body.append([key, _show(value.get("n_stations")), _show(value.get("n_valid")),
                     _show(value.get("n_flagged")), flags or "-"])
    return lines + _table(["region|elevation", "stations", "valid values", "flagged", "flags"], body)


def _catalog_section(results) -> list[str]:
    lines = [_H_CATALOGS, ""]
    cats = [r for r in results if r.name.startswith("catalog_")]
    if not cats:
        manual = _by_name(results).get("manual_catalogs")
        return lines + ([_NO_DATA, ""] if manual else ["_Not run._", ""])
    for r in cats:
        lines.append(f"**{r.name}** - {r.status}: {r.summary}")
        summary = _ev(r).get("summary")
        if summary and isinstance(summary, dict):
            body = []
            for region, v in summary.items():
                v = v if isinstance(v, dict) else {}
                body.append([region, *[_show(v.get(k)) for k in
                                       ("n_total", "n_located", "n_unknown_accuracy", "first_date", "last_date")]])
            lines += [""] + _table(["region", "total", "located", "unknown accuracy", "first", "last"], body)
        elif summary:
            lines += ["", "_catalog summary was not in the expected form_", ""]
        else:
            lines.append("")
    return lines


def _feasibility_section(results, manifest_entries) -> list[str]:
    lines = [_H_FEASIBILITY, ""]
    res = _by_name(results).get("feasibility")
    if res is None:
        lines += ["_Feasibility probe not run._", ""]
    else:
        scenarios = _ev(res).get("scenarios")
        rows = [s for s in (scenarios if isinstance(scenarios, (list, tuple)) else []) if isinstance(s, dict)]
        if rows:
            lines += _table(["strategy", "points", "days", "call units", "days at free limit"],
                            [[s.get("name", "n/a"), *[_show(s.get(k)) for k in
                                                      ("points", "days", "call_units", "days_at_free_limit")]]
                             for s in rows])
        else:
            lines += [_NO_DATA, ""]
    volumes = [[r.name, _gb(_ev(r)["est_total_gb"])] for r in results if "est_total_gb" in _ev(r)]
    if volumes:
        lines += ["Estimated download volume for the full domain/period:", ""]
        lines += _table(["source", "GB"], volumes)
    if manifest_entries:
        groups = defaultdict(lambda: [0, 0, set()])
        for e in manifest_entries.values():
            source = getattr(e, "source", "unknown")
            groups[source][0] += 1
            groups[source][1] += _num(getattr(e, "size_bytes", 0)) or 0
            groups[source][2].add(str(getattr(e, "licence", "")))
        lines += ["Files downloaded so far (from the manifest):", ""]
        lines += _table(["source", "files", "MB", "licence recorded"],
                        [[s, n, f"{b / 1e6:.1f}", "; ".join(sorted(lic))] for s, (n, b, lic) in sorted(groups.items())])
    return lines


def _guarded(heading: str, builder, *args) -> list[str]:
    """Run one section builder; an unexpected error becomes a line, never a crash of the whole report."""
    try:
        return builder(*args)
    except Exception as exc:
        return [heading, "", f"_section could not be rendered: {type(exc).__name__}_", ""]


def render_markdown(results: list[ProbeResult], generated_utc: str, cfg: dict,
                    manifest_entries: dict | None = None) -> str:
    lines = ["# Phase 0 data audit", "", f"Generated: {generated_utc}", "",
             "Status meanings: ok = works as planned; partial = works with caveats; fail = does not work; "
             "unreachable = network problem; needs_login = free account required; manual_pending = you must "
             "place a file; inconclusive = the probe itself could not decide.", "",
             "'Probe problems' lists every probe that is not ok (including partial) with its reason; "
             "'Needs human action' lists only the probes that need something from you.", ""]
    lines += _guarded(_H_SUMMARY, _summary_section, results)
    lines += _guarded(_H_ATTENTION, _attention_section, results)
    lines += _guarded(_H_PROBLEMS, _problems_section, results)
    lines += _guarded(_H_RAIN, _rain_section, results, cfg)
    lines += _guarded(_H_GHCND, _ghcnd_section, results)
    lines += _guarded(_H_CATALOGS, _catalog_section, results)
    lines += _guarded(_H_FEASIBILITY, _feasibility_section, results, manifest_entries)
    return "\n".join(lines) + "\n"


def _jsonable(obj):
    """Recursively convert to plain JSON types; non-finite floats become None (strict JSON)."""
    if obj is None or isinstance(obj, (str, bool)):
        return obj
    if obj is pd.NaT or obj is pd.NA:
        return None
    if isinstance(obj, dict):
        return {(k if isinstance(k, str) else str(k)): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (set, frozenset)):
        return [_jsonable(v) for v in sorted(obj, key=str)]
    if isinstance(obj, np.ndarray):
        return _jsonable(obj.tolist())
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return _jsonable(float(obj))
    if isinstance(obj, (np.datetime64, np.timedelta64)):
        return str(obj)
    if isinstance(obj, int):
        return int(obj)
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, (datetime, date)):  # includes pandas Timestamp
        return obj.isoformat()
    return str(obj)


def _redact_obj(obj, secrets: list[str]):
    """Redact every string (and dict key) of a plain-JSON structure."""
    if isinstance(obj, str):
        return redact(obj, secrets)
    if isinstance(obj, dict):
        return {redact(k, secrets) if isinstance(k, str) else k: _redact_obj(v, secrets) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact_obj(v, secrets) for v in obj]
    return obj


def _clean_result(result: ProbeResult, secrets: list[str]) -> ProbeResult:
    """A plain-JSON, secret-free copy of a result (so redaction happens before any rendering rewrites text)."""
    evidence = _redact_obj(_jsonable(result.evidence), secrets)
    return replace(result, summary=redact(str(result.summary), secrets),
                   evidence=evidence if isinstance(evidence, dict) else {"value": evidence},
                   day_definition=None if result.day_definition is None else redact(str(result.day_definition), secrets))


def write_reports(results, out_dir, secrets, cfg, manifest_entries=None) -> tuple[Path, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    md_path, json_path = out_dir / "phase0_data_audit.md", out_dir / "phase0_data_audit.json"
    cleaned = [_clean_result(r, secrets) for r in results]
    md_path.write_text(redact(render_markdown(cleaned, generated, cfg, manifest_entries), secrets),
                       encoding="utf-8", newline="\n")
    document = {"generated_utc": generated, "results": [r.as_dict() for r in cleaned]}
    payload = json.dumps(document, indent=2, allow_nan=False)
    # safety net: also match the JSON-escaped spelling of a secret (quotes, backslashes, non-ASCII characters)
    escaped = [json.dumps(s)[1:-1] for s in secrets if s]
    json_path.write_text(redact(payload, list(secrets) + escaped), encoding="utf-8", newline="\n")
    return md_path, json_path
