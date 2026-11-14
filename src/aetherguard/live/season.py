"""The declared season of validity of the published alert chain and its visible flag (reports/phase8_season_validity.md).

The model was fitted on every month of 2007-2017, but the post-model rules and the alert-engine parameters were chosen on
June-September panels only, the held-out look covered June-December, and the development events outside June-September
are few. A lead whose date falls outside the declared months is therefore published as it is, with the flag
`outside_validated_season` in run.json (`season_of_validity` and each lead's `outside_validated_season`) and a line in the
bulletin: a statement about the evidence behind the alert, never a suppression.

Configuration: `season_of_validity.months` in configs/live_run.yaml (default June-September).
"""
from __future__ import annotations

from datetime import date, timedelta

DEFAULT_MONTHS = (6, 7, 8, 9)
FLAG = "outside_validated_season"
LEADS = (0, 1, 2, 3)
NOTE = ("the post-model rules and alert-engine parameters were derived on June-September development panels only and the "
        "held-out evaluation covered June-December; outside the declared months an alert is published unchanged and "
        "flagged (reports/phase8_season_validity.md)")


def validated_months(cfg: dict) -> tuple[int, ...]:
    months = tuple(int(m) for m in (cfg.get("season_of_validity") or {}).get("months", DEFAULT_MONTHS))
    if not months or any(m < 1 or m > 12 for m in months) or len(set(months)) != len(months):
        raise ValueError(f"season_of_validity.months must be distinct months 1-12, got {list(months)}")
    return months


def outside(day: date, months) -> bool:
    return day.month not in tuple(months)


def season_record(day: date, cfg: dict) -> dict:
    """run.json `season_of_validity` of the run of `day`: the declared months and, per lead, whether its date is outside."""
    months = validated_months(cfg)
    leads = {str(k): outside(day + timedelta(days=k), months) for k in LEADS}
    return {"months": list(months), "flag": FLAG, "leads": leads, "any_outside": any(leads.values()),
            "source": (cfg.get("season_of_validity") or {}).get("source", "reports/phase8_season_validity.md"), "note": NOTE}
