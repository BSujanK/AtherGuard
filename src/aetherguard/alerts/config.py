"""The alert engine parameters: structural values from `configs/alerts.yaml` plus the data-derived values stored in
`data/processed/alerts/alert_config.json` (see `derive.py`; development period 2007-2017 only)."""
from __future__ import annotations

import json
from dataclasses import MISSING, asdict, dataclass, fields
from pathlib import Path

from ..config import data_root, load_config
from ..hazard.jsonio import dump_json

CONFIG_FILE = "alert_config.json"
CONFIG_VERSION = 1
DEFAULT_UNCERTAIN_PERCENTILE = 90.0     # the upper bound of `HazardModel.score`'s interval (hazard.model.INTERVAL_PERCENTILES)


def alerts_dir() -> Path:
    return data_root() / "processed" / "alerts"


def default_config_path() -> Path:
    return alerts_dir() / CONFIG_FILE


def upper_column(percentile: float) -> str:
    """Score column that carries the `percentile` of the calibrated ensemble when it is not the model's own `risk_hi`."""
    return f"risk_p{percentile:g}"


def alerts_settings() -> dict:
    return load_config("alerts")


@dataclass(frozen=True)
class AlertConfig:
    exit_factor: float            # hysteresis: step down only below exit_factor x the level threshold
    exit_days: int                # ... for this many consecutive days
    radius_km: float              # nearby-station radius
    ood_window_days: int          # station out-of-distribution guard: trailing window
    ood_multiple: float           # ... flag rate above ood_multiple x engine_target_flag_rate
    ood_min_observed_days: int    # ... needs at least this many observed days in the window
    engine_target_flag_rate: float
    dis_ratio_lo: float           # development 5th percentile of src_dis_ratio_3
    dis_ratio_hi: float           # development 95th percentile
    heavy_acc1_mm: float          # heavy rain: 1-day amount reached by any independent source
    heavy_acc3_mm: float          # ... or 3-day amount
    agree_abs_mm: float           # a trusted station agrees with the grid within max(abs, rel x larger value)
    agree_rel: float
    uncertain_percentile: float | None = DEFAULT_UNCERTAIN_PERCENTILE   # `uncertain_high`: this percentile of the calibrated
                                                                        # ensemble reaching Watch; None: no such rule

    @property
    def ood_rate(self) -> float:
        return self.ood_multiple * self.engine_target_flag_rate

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, values: dict) -> "AlertConfig":
        required = [f.name for f in fields(cls) if f.default is MISSING]
        missing = [n for n in required if n not in values]
        if missing:
            raise ValueError(f"alert config lacks {missing}")
        out = cls(**{f.name: values[f.name] for f in fields(cls) if f.name in values})
        if not out.dis_ratio_lo < out.dis_ratio_hi:
            raise ValueError("alert config: dis_ratio_lo must be below dis_ratio_hi")
        if out.uncertain_percentile is not None and not 50.0 < out.uncertain_percentile <= 100.0:
            raise ValueError(f"alert config: uncertain_percentile must be None or in (50, 100], got {out.uncertain_percentile}")
        return out


def structural_parameters(settings: dict | None = None) -> dict:
    """The parameters that come straight from configs/alerts.yaml."""
    s = settings or alerts_settings()
    return {"exit_factor": s["hysteresis"]["exit_factor"], "exit_days": s["hysteresis"]["exit_days"],
            "radius_km": s["stations"]["radius_km"], "ood_window_days": s["stations"]["ood_window_days"],
            "ood_multiple": s["stations"]["ood_multiple"],
            "ood_min_observed_days": s["stations"]["ood_min_observed_days"],
            "engine_target_flag_rate": s["stations"]["engine_target_flag_rate"]}


def save_config(path: Path, config: AlertConfig, derivation: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    dump_json(path, {"version": CONFIG_VERSION, "parameters": config.to_dict(), "derivation": derivation})


def load_config_file(path: Path | None = None) -> AlertConfig:
    path = Path(path or default_config_path())
    if not path.is_file():
        raise FileNotFoundError(f"{path} not found; derive it first (python -m aetherguard.alerts.derive)")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("version") != CONFIG_VERSION:
        raise ValueError(f"{path} has version {payload.get('version')!r}, expected {CONFIG_VERSION}")
    return AlertConfig.from_dict(payload["parameters"])
