"""Pydantic response models of the AetherGuard API (read-only, replay data)."""
from __future__ import annotations

from pydantic import BaseModel


class ThresholdsOut(BaseModel):
    watch: float
    warning: float
    emergency: float
    source: str


class StoreSet(BaseModel):
    first_date: str
    last_date: str
    n_days: int
    n_rows: int


class Health(BaseModel):
    status: str                                # ok | degraded
    aetherguard_version: str
    python: str
    packages: dict[str, str]
    model_card_sha256: str | None              # the card the replay store was built with
    live_model_card_sha256: str | None         # the card on disk now
    model_card_matches_store: bool | None
    model_freeze_status: str                   # verified | mismatch | not_frozen (hazard.freeze.verify_freeze, live)
    model_frozen_utc: str | None
    model_freeze_detail: str | None
    data_manifest_status: str                  # replay store: ok | incomplete | missing
    replay_store: str
    provisional: str | None
    thresholds: ThresholdsOut | None
    sets: dict[str, StoreSet]


class RiskCell(BaseModel):
    cell_id: int
    lat: float
    lon: float
    region: str | None
    risk: float | None
    risk_per_100k: float | None
    level: int
    level_name: str
    confidence: str
    blind: bool
    uncertain_high: bool
    reason_codes: list[str]


class RiskResponse(BaseModel):
    date: str
    set: str
    thresholds: ThresholdsOut | None
    provisional: str | None
    n_cells: int
    level_counts: dict[str, int]
    cells: list[RiskCell]


class ShapFactor(BaseModel):
    feature: str
    value: float | None
    contribution: float


class PlaceOut(BaseModel):
    """The place name of a cell (GeoNames, CC BY 4.0): the nearest sizeable populated place and where it lies."""
    place: str | None
    district: str | None
    state: str | None
    country: str | None
    distance_km: int
    place_lat: float
    place_lon: float
    population: int


class ForecastRainDay(BaseModel):
    date: str                                  # the IMD day the GFS total is for
    lead: int                                  # 1..3: days after the run date
    mm: float | None


class CellRain(BaseModel):
    """The rain behind a forecast: what was observed through the run date and the GFS totals for the days after it."""
    unit: str
    observed_date: str | None
    observed: dict[str, float | str | None]    # the alert engine's rain evidence of the run date (same keys as `sources`)
    forecast: list[ForecastRainDay]


class ForecastSourceOut(BaseModel):
    """The rain source a forecast lead was built from (run.json `leads.<k>.forecast`)."""
    source: str | None
    label: str | None
    mapped: bool | None
    fallback: bool | None                      # the lead's own source was missing and GFS stood in
    cycle: str | None                          # ISO time of the forecast cycle
    attribution: str | None                    # licence line to show wherever the forecast is shown (ECMWF: CC BY 4.0)


class CellExplanation(BaseModel):
    cell_id: int
    date: str
    set: str
    lat: float
    lon: float
    region: str | None
    level: int
    level_name: str
    raw_level: str
    confidence: str
    confidence_causes: list[str]
    reason_codes: list[str]
    risk: float | None
    risk_lo: float | None
    risk_hi: float | None
    risk_per_100k: float | None
    thresholds: ThresholdsOut | None
    provisional: str | None
    shap: list[ShapFactor]
    sources: dict[str, float | str | None]
    sensor_trust: dict[str, int | list[str]]
    place: PlaceOut | None = None              # None when no place table is built or the cell has no label
    lead: int = 0                              # 0 = the run date's assessment, 1..3 = the forecast for that many days later
    issued_date: str | None = None             # the run date (`date`)
    target_date: str | None = None             # the day the assessment is for (= issued_date at lead 0)
    forecast: bool = False
    widened: bool | None = None                # forecast leads: the interval was widened by the forecast-skill factors
    rain: CellRain | None = None               # forecast leads only
    unavailable: str | None = None             # forecast leads: why sources, gauges and IMD are empty
    detail_missing: str | None = None          # set when the run predates the per-lead detail
    ensemble: dict[str, float | None] | None = None   # median_risk / agreement of the 20 members (post-model rules)
    rain_rule: dict[str, bool | float | int | str | None] | None = None   # passed / exempt / capped of the rain trigger; a
                                               # capped row also has window_days, rain_mm, minimum_mm and capped_to
    certainty: str | None = None               # forecast leads: firm | depends_on_forecast (None: not scored / lead 0)
    level_min: int | None = None               # forecast leads: lowest level over the no-rain, forecast and heavy-rain scenarios
    level_max: int | None = None
    forecast_source: ForecastSourceOut | None = None   # forecast leads: where the rain behind the forecast came from


class SensorRow(BaseModel):
    station: str
    name: str | None
    lat: float
    lon: float
    trust: float | None
    fault_type: str
    flagged: bool
    genuine_extreme: bool
    reasons: str
    state: str
    flag_rate_window: float | None
    ood: bool
    last_reading: str | None = None            # ISO date of the gauge's newest value (live sets); None when unknown


class SensorsResponse(BaseModel):
    date: str
    set: str
    n_stations: int
    state_counts: dict[str, int]
    stations: list[SensorRow]
    reason: str | None = None                  # why `stations` is empty when the set holds the date but no gauge table


class CellReasons(BaseModel):
    confidence: dict[str, str | list[str]]
    sources: dict[str, float | str | None]
    sensor_trust: dict[str, int | list[str]]
    shap: list[ShapFactor]


class AlertItem(BaseModel):
    cell_id: int
    date: str
    set: str
    lat: float
    lon: float
    region: str | None
    risk: float | None
    level: int
    level_name: str
    confidence: str
    reason_codes: list[str]
    reasons: CellReasons


class AlertsResponse(BaseModel):
    start: str
    end: str
    min_level: str
    set: str | None
    n_alerts: int
    truncated: bool
    alerts: list[AlertItem]
