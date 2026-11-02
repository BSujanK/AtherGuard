"""Small markdown table formatting helpers shared by the hazard reports."""
from __future__ import annotations

import math

MODEL_ORDER = ("model", "intensity_duration", "lhasa_style", "logistic")
LABELS = {"model": "hazard model", "intensity_duration": "intensity-duration", "lhasa_style": "LHASA-style",
          "logistic": "logistic regression", "full_model": "full model",
          "region_held_out_model": "region-held-out model"}


def _num(value, digits: int = 4) -> str:
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return "n/a"
    if value != 0 and abs(value) < 10 ** -digits:
        return f"{value:.2e}"
    return f"{value:.{digits}f}"


def _ci(summary, digits: int = 4) -> str:
    return f"{_num(summary['value'], digits)} [{_num(summary['lo'], digits)}, {_num(summary['hi'], digits)}]"


def _pct(summary) -> str:
    return (f"{100 * summary['value']:.1f}% [{100 * summary['lo']:.1f}, {100 * summary['hi']:.1f}]")


def _table(header: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join(["---"] * len(header)) + "|"]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines)


def _label(name: str) -> str:
    return LABELS.get(name, name)


def _ordered(names, preferred=MODEL_ORDER):
    names = list(names)
    return [n for n in preferred if n in names] + [n for n in names if n not in preferred]
