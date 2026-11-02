"""Strict JSON output: NaN / inf become null, numpy scalars, arrays and timestamps become plain Python."""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd


def jsonable(value):
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(v) for v in value]
    if isinstance(value, np.ndarray):
        return jsonable(value.tolist())
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, Path):
        return value.as_posix()
    if value is pd.NaT:
        return None
    if isinstance(value, np.datetime64):
        return str(pd.Timestamp(value))
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def dump_json(path: Path, payload) -> None:
    text = json.dumps(jsonable(payload), indent=2, allow_nan=False)
    Path(path).write_text(text + "\n", encoding="utf-8")
