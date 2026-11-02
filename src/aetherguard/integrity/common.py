"""Shared paths and strict-JSON helpers for the sensor-integrity package."""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import PROJECT_ROOT, data_dir


def integrity_dir() -> Path:
    """`<data root>/processed/integrity` (created on demand)."""
    return data_dir("processed", "integrity")


def reports_dir() -> Path:
    path = PROJECT_ROOT / "reports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def display_path(path) -> str:
    """Project-relative POSIX path, or just the file name for a file outside the project."""
    try:
        return Path(path).resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return Path(path).name


def to_jsonable(obj):
    """Plain-Python copy of `obj` for strict JSON: NaN/inf -> None, numpy/pandas scalars unwrapped."""
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [to_jsonable(v) for v in (sorted(obj, key=str) if isinstance(obj, set) else obj)]
    if isinstance(obj, np.ndarray):
        return to_jsonable(obj.tolist())
    if isinstance(obj, pd.Timestamp):
        return obj.strftime("%Y-%m-%d")
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    if isinstance(obj, (np.integer, int)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        value = float(obj)
        return value if math.isfinite(value) else None
    if obj is None or isinstance(obj, str):
        return obj
    raise TypeError(f"cannot serialise {type(obj).__name__} to JSON")


def dumps_strict(obj) -> str:
    return json.dumps(to_jsonable(obj), indent=2, allow_nan=False) + "\n"
