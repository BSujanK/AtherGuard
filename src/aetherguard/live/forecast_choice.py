"""Which forecast rain the forecast leads use (spec section 12): sources, the per-lead choice, and the three rain scenarios.

    day = load_product_days(rain_dir, issue_day)                      # {source: ProductDay} from the archive files of the day
    choice = load_choice(path)                                        # reports/forecast_selection.json (GFS everywhere without it)
    lead = resolve_lead(day, choice, maps, lead)                      # the chosen field of one lead, GFS where it is missing
    scenarios = scenario_fields(lead, hi_factor)                      # dry / forecast / wet IMD-day totals for D+1..D+lead

Sources (`SOURCES`): `gfs` (NOAA GFS 00Z), `ecmwf_hres` (ECMWF IFS HRES), `ecmwf_ens_mean` (mean of the 51 ECMWF ensemble
members). A configuration is a source and whether its rain is moved onto the IMERG Late scale by the quantile mapping of
`forecast_map`. GFS without correction is the fallback of every lead (`ForecastChoice.fallback`).

Scenarios of one lead k (F1): `dry` has no rain after day D, `forecast` is the chosen field, `wet` is the chosen field plus the
upper spread of the ECMWF ensemble, (p90 - mean)+, in mm when the source is an ECMWF product and its ensemble is present (for the
ensemble-mean source that is exactly the ensemble's 90th percentile), else the chosen field times the lead's high widening factor.
`wet` is never below `forecast`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np

from ..hazard.jsonio import dump_json
from ..ingest import ecmwf

UTC = timezone.utc
SOURCES = ("gfs", "ecmwf_hres", "ecmwf_ens_mean")
LABELS = {"gfs": "NOAA GFS", "ecmwf_hres": "ECMWF IFS HRES", "ecmwf_ens_mean": "ECMWF IFS ensemble mean"}
FALLBACK_LABEL = "GFS fallback"
ECMWF_PREFIX = "ecmwf"
VERSION = 1
LEADS = (1, 2, 3)
SCENARIOS = ("dry", "forecast", "wet")


def is_ecmwf(source: str) -> bool:
    return source.startswith(ECMWF_PREFIX)


def source_label(source: str, mapped: bool, fallback: bool = False) -> str:
    """The name shown next to a forecast: ECMWF with its licence, the GFS fallback, or GFS as a choice."""
    if fallback:
        return FALLBACK_LABEL
    name = f"{LABELS[source]} (CC BY 4.0)" if is_ecmwf(source) else LABELS[source]
    return f"{name}, bias-corrected" if mapped else name


@dataclass(frozen=True)
class Config:
    """One forecast configuration: a source and whether its rain is bias-corrected."""
    source: str
    mapped: bool = False

    def __post_init__(self) -> None:
        if self.source not in SOURCES:
            raise ValueError(f"source must be one of {SOURCES}, got {self.source!r}")

    def to_dict(self) -> dict:
        return {"source": self.source, "mapped": self.mapped}


GFS_RAW = Config("gfs", False)


@dataclass(frozen=True)
class ForecastChoice:
    """The configuration of each lead and the fallback used where its source is missing."""
    leads: dict[int, Config]
    fallback: Config = GFS_RAW
    maps_file: str | None = None
    report: str | None = None

    def __post_init__(self) -> None:
        if sorted(self.leads) != list(LEADS):
            raise ValueError(f"a forecast choice needs leads {LEADS}, got {sorted(self.leads)}")
        if any(c.mapped for c in (*self.leads.values(), self.fallback)) and not self.maps_file:
            raise ValueError("a bias-corrected configuration needs the mapping file (maps_file)")

    @property
    def needs_ecmwf(self) -> bool:
        return any(is_ecmwf(c.source) for c in self.leads.values())

    def to_dict(self) -> dict:
        return {"version": VERSION, "leads": {str(k): c.to_dict() for k, c in sorted(self.leads.items())},
                "fallback": self.fallback.to_dict(), "maps_file": self.maps_file, "report": self.report}

    @classmethod
    def from_dict(cls, payload: dict) -> "ForecastChoice":
        if payload.get("version") != VERSION:
            raise ValueError(f"forecast choice has version {payload.get('version')!r}, expected {VERSION}")
        return cls(leads={int(k): Config(v["source"], bool(v["mapped"])) for k, v in payload["leads"].items()},
                   fallback=Config(payload["fallback"]["source"], bool(payload["fallback"]["mapped"])),
                   maps_file=payload.get("maps_file"), report=payload.get("report"))


GFS_EVERYWHERE = ForecastChoice(leads={k: GFS_RAW for k in LEADS})


def save_choice(path: Path, choice: ForecastChoice, derivation: dict | None = None) -> None:
    dump_json(Path(path), {**choice.to_dict(), "derivation": derivation or {}})


def load_choice(path: Path | str | None) -> ForecastChoice:
    """The choice in `path`; GFS everywhere when the file does not exist (the forecast days as before section 12)."""
    if path is None or not Path(path).is_file():
        return GFS_EVERYWHERE
    return ForecastChoice.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


# ---------------------------------------------------------------------------------------------- product days

@dataclass(frozen=True)
class ProductDay:
    """One source's IMD-day totals (3, rows, cols) for an issue day; `p90` and `mean` are the ECMWF ensemble's upper
    percentile and mean (NaN where the ensemble has no value), None for GFS."""
    days: np.ndarray
    valid: np.ndarray
    cycle: datetime | None
    p90: np.ndarray | None = None
    mean: np.ndarray | None = None


def load_product_days(rain_dir: Path, issue_day: date) -> dict[str, ProductDay]:
    """The sources that have an archive file for `issue_day` with at least one valid lead day."""
    rain_dir = Path(rain_dir)
    out: dict[str, ProductDay] = {}
    path = rain_dir / f"gfs_imdday_{issue_day.isoformat()}.npz"
    if path.is_file():
        with np.load(path, allow_pickle=False) as data:
            valid = data["day_valid"].astype(bool)
            if valid.any():
                out["gfs"] = ProductDay(data["days"].astype(np.float32), valid,
                                        datetime.fromisoformat(str(data["cycle"])).astimezone(UTC))
    forecast = ecmwf.load_day(rain_dir / ecmwf.day_file_name(issue_day))
    if forecast is not None:
        if forecast.hres is not None:
            out["ecmwf_hres"] = ProductDay(forecast.hres, forecast.hres_valid, forecast.hres_cycle,
                                           forecast.ens_p90, forecast.ens_mean)
        if forecast.ens_mean is not None:
            out["ecmwf_ens_mean"] = ProductDay(forecast.ens_mean, forecast.ens_valid, forecast.ens_cycle,
                                               forecast.ens_p90, forecast.ens_mean)
    return out


# ------------------------------------------------------------------------------------------------ one lead

@dataclass(frozen=True)
class LeadField:
    """The rain the forecast of lead k is built from: IMD-day totals for D+1..D+k and where they came from."""
    lead: int
    config: Config
    fallback: bool
    cycle: datetime | None
    days: np.ndarray                    # (k, rows, cols) the chosen field, bias-corrected when the config says so
    spread: np.ndarray | None           # (k, rows, cols) (p90 - mean)+ of the ECMWF ensemble, None without one

    @property
    def label(self) -> str:
        return source_label(self.config.source, self.config.mapped, self.fallback)


def resolve_lead(products: dict[str, ProductDay], choice: ForecastChoice, maps, lead: int) -> LeadField | None:
    """The field of `lead` for the configured source, else for the fallback; None when neither can supply it.

    A source supplies the lead when it has every day D+1..D+lead; failing that, one that has D+`lead` only is used (the days
    before it are NaN, so the lead's rows come out unscored rather than the lead missing). `maps` is the
    `forecast_map.ForecastMaps` the choice names (None when no configuration is bias-corrected).
    """
    for complete in (True, False):
        for fallback, config in ((False, choice.leads[lead]), (True, choice.fallback)):
            product = products.get(config.source)
            if product is None or not (product.valid[:lead].all() if complete else product.valid[lead - 1]):
                continue
            days = product.days[:lead].astype(np.float32)
            if config.mapped:
                days = np.stack([maps.apply(config.source, k + 1, days[k]) for k in range(lead)])
            spread = None
            if is_ecmwf(config.source) and product.p90 is not None and product.mean is not None:
                raw = np.maximum(product.p90[:lead] - product.mean[:lead], 0.0).astype(np.float32)
                spread = raw if np.isfinite(raw).all() else None
            return LeadField(lead, config, fallback and config != choice.leads[lead], product.cycle, days, spread)
    return None


def scenario_fields(lead: LeadField, hi_factor: float) -> dict[str, np.ndarray]:
    """{dry, forecast, wet}: (k, rows, cols) IMD-day totals for D+1..D+k (module doc)."""
    forecast = lead.days
    wet = forecast + lead.spread if lead.spread is not None else forecast * np.float32(max(hi_factor, 1.0))
    return {"dry": np.zeros_like(forecast), "forecast": forecast, "wet": wet.astype(np.float32)}
