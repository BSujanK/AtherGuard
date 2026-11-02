"""Ingest feasibility: how many Open-Meteo call units each fetching strategy would need."""
from __future__ import annotations

from datetime import date

from ..grid import domain_cell_counts
from .result import ProbeResult


def open_meteo_call_units(n_points: int, days: int, n_vars: int,
                          days_per_unit: float = 14, vars_per_unit: float = 10) -> float:
    """Provider weighting: max(1, days/14) * max(1, variables/10) per location."""
    return n_points * max(1.0, days / days_per_unit) * max(1.0, n_vars / vars_per_unit)


THRESHOLD_DAYS = 30  # a plan needing more days than this at the free daily limit is infeasible


def _period_days(domain_cfg: dict) -> int:
    try:
        start = date.fromisoformat(domain_cfg["period"]["start"])
        end = date.fromisoformat(domain_cfg["period"]["end"])
    except (ValueError, TypeError) as exc:
        raise ValueError(f"period start/end are not valid ISO dates: {exc}") from exc
    days = (end - start).days + 1
    if days <= 0:
        raise ValueError(f"period end {end} is before start {start}; cannot size an ingest")
    return days


def _validated_open_meteo(audit_cfg: dict) -> dict:
    om = audit_cfg["open_meteo"]
    for key in ("free_calls_per_day", "days_per_call_unit", "vars_per_call_unit"):
        value = om[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not value > 0:
            raise ValueError(f"open_meteo.{key} must be a positive number, got {value!r}")
    return om


def scenarios(domain_cfg: dict, audit_cfg: dict) -> list[dict]:
    om = _validated_open_meteo(audit_cfg)
    days_full = _period_days(domain_cfg)
    variables = 3  # precipitation, soil moisture, one more hourly variable
    plans = [
        ("full domain, ERA5 0.25 deg grid, whole period", domain_cell_counts(0.25)["total"], days_full),
        ("full domain, 0.05 deg grid, whole period", domain_cell_counts(0.05)["total"], days_full),
        ("sampled case-control, 30,000 points x 60 days", 30_000, 60),
    ]
    out = []
    for name, points, days in plans:
        units = open_meteo_call_units(points, days, variables, om["days_per_call_unit"], om["vars_per_call_unit"])
        out.append({"name": name, "points": points, "days": days, "variables": variables,
                    "call_units": round(units), "days_at_free_limit": round(units / om["free_calls_per_day"], 1)})
    return out


def probe_feasibility(domain_cfg: dict, audit_cfg: dict) -> ProbeResult:
    try:
        plans = scenarios(domain_cfg, audit_cfg)
    except KeyError as exc:
        return ProbeResult("feasibility", "fail", f"missing config key {exc}", {})
    except (ValueError, TypeError) as exc:
        return ProbeResult("feasibility", "fail", f"invalid feasibility config: {exc}", {})
    infeasible = [p for p in plans if p["days_at_free_limit"] > THRESHOLD_DAYS]
    feasible = [p for p in plans if p["days_at_free_limit"] <= THRESHOLD_DAYS]

    def fmt(group):
        return "; ".join(f"{p['name']} ({p['days_at_free_limit']:,.1f} d)" for p in group)

    parts = []
    if infeasible:
        parts.append(f"infeasible (>{THRESHOLD_DAYS} days at the free limit): {fmt(infeasible)}")
    if feasible:
        parts.append(f"feasible: {fmt(feasible)}")
    return ProbeResult(
        "feasibility", "ok", "; ".join(parts),
        {"scenarios": plans, "infeasible": [p["name"] for p in infeasible],
         "feasible": [p["name"] for p in feasible], "threshold_days": THRESHOLD_DAYS,
         "source": "https://open-meteo.com/en/pricing (checked 2026-09-30)"})
