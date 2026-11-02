/** Risk levels as encoded in the `level` byte array of `/api/grid`. */
export const LEVELS = ['Normal', 'Watch', 'Warning', 'Emergency'] as const
export type Level = 0 | 1 | 2 | 3

/** Scenario certainty codes as encoded in the `certainty` byte array of a forecast `/api/grid`. */
export const CERTAINTY = { none: 0, firm: 1, depends: 2 } as const

/** Where the rain behind a forecast lead came from (`/api/grid` `forecast`, `/risk/cell` `forecast_source`). */
export interface ForecastSource {
  /** `gfs`, `ecmwf_hres` or `ecmwf_ens_mean`. */
  source: string | null
  /** Plain name for the screen, e.g. "ECMWF IFS HRES (CC BY 4.0)" or "GFS fallback". */
  label: string | null
  mapped: boolean | null
  /** The lead's own source was missing and GFS stood in. */
  fallback: boolean | null
  /** ISO time of the forecast cycle. */
  cycle: string | null
  /** Licence line to show wherever the forecast is shown; null for GFS. */
  attribution: string | null
}

/** Confidence codes as encoded in the `confidence` byte array of `/api/grid`. */
export const CONFIDENCES = ['High', 'Degraded', 'Insufficient'] as const

export type DataMode = 'live' | 'replay' | 'none'

/** Calibrated-risk thresholds of the three alert tiers, from the model card behind the set shown. */
export interface Thresholds {
  watch: number
  warning: number
  emergency: number
  source: string | null
}

export interface ModeResponse {
  mode: DataMode
  set: string | null
  latest_date: string | null
  dates: string[]
  /** Forecast leads (0 to 3) each date can show; a replay set holds lead 0 only. Absent from an API that predates the field. */
  leads?: Record<string, number[]>
  /** Absent from an API that predates the field, or null when no model card is known for the set. */
  thresholds?: Thresholds | null
  /**
   * Thresholds per region (`himalaya`, `western_ghats`) that each cell is levelled against; the pooled `thresholds` are
   * the all-India figures. Absent from an API that predates the field, or null when the set has none.
   */
  thresholds_by_region?: Record<string, Thresholds> | null
  /** Share (0 to 1) of the domain's cells the newest day has a risk score for; null for a replay set or an unreadable run. */
  scored_share?: number | null
  /** The newest live date, at or before the newest day, that scored any cell: where held levels come from. */
  last_scored_date?: string | null
  /** ISO datetime (+05:30) of the next scheduled daily run; absent from an API that predates the field. */
  next_run?: string
}

/**
 * Wire format of `/api/grid`: typed arrays arrive base64 encoded, little endian, sorted by cell id.
 * `lat0`, `lon0` and `step` describe the global grid (-90, -180, 0.05), not the domain; use `cellCenter`.
 */
export interface GridPayload {
  date: string
  lead: number
  n: number
  cells: string
  risk: string
  level: string
  confidence: string
  lat0: number
  lon0: number
  step: number
  /** Replay set or `live` that answered the request. */
  set?: string
  /** Upper bound of the risk interval, float32 base64. */
  risk_hi?: string
  /** One byte per cell, see `GRID_FLAG`; absent from an API that predates the field. */
  flags?: string
  /** Forecast leads: one `CERTAINTY` byte per cell, and the lowest and highest level over the rain scenarios. */
  certainty?: string
  level_min?: string
  level_max?: string
  /** Forecast leads: the rain source behind the lead; null for a run that did not record one. */
  forecast?: ForecastSource | null
}

/** Bits of the per-cell `flags` byte: why a cell sits above the level its risk alone would give. */
export const GRID_FLAG = {
  /** Raised to at least Watch because the rain data could not be trusted while some source showed heavy rain. */
  blindRaised: 1,
  /** Held at a higher level by hysteresis after the risk fell. */
  held: 2,
  /** With `blindRaised`: the doubt was untrusted gauges rather than disagreeing sources. */
  gaugesUntrusted: 4,
  /** The rain trigger capped the level (too little recent rain): the model's risk is not the basis of the level. */
  capped: 8,
  /** Most of the 20 ensemble models put the risk lower than the point estimate. */
  ensembleDisagrees: 16,
} as const

export interface Grid {
  date: string
  lead: number
  n: number
  cells: Uint32Array
  risk: Float32Array
  level: Uint8Array
  confidence: Uint8Array
  /** Per-cell `GRID_FLAG` bits; undefined when the API does not send them. */
  flags?: Uint8Array
  /** Forecast leads only: per-cell `CERTAINTY` code and the level range over the dry / forecast / wet rain scenarios. */
  certainty?: Uint8Array
  levelMin?: Uint8Array
  levelMax?: Uint8Array
  /** Forecast leads only: where the rain came from; null when the run did not record it. */
  forecast?: ForecastSource | null
  lat0: number
  lon0: number
  step: number
}

/** Country classes of the base map mask: sea or outside, India, Nepal, Bhutan, other land. */
export const MASK = { sea: 0, india: 1, nepal: 2, bhutan: 3, other: 4 } as const

/** One country's outline: closed rings of [lon, lat] points (exteriors and holes, islands included). */
export interface Outline {
  name: string
  rings: [number, number][][]
}

/**
 * Wire format of `/api/basemap`, the whole-India relief on the project's 0.05 degree global grid. `elev` is float16
 * little endian metres and `mask` one `MASK` byte per cell, both row-major with row 0 southernmost (latitude
 * `lat0 + i * step`) and column 0 westernmost. Sea keeps its bathymetry in `elev`; the mask says it is sea.
 */
export interface BasemapPayload {
  rows: number
  cols: number
  lat0: number
  lon0: number
  step: number
  elev: string
  mask: string
  outline: Outline[]
}

/** A window of the global grid with one elevation sample per cell. NaN means no data (sea). */
export interface Terrain {
  rows: number
  cols: number
  lat0: number
  lon0: number
  step: number
  elev: Float32Array
}

/** The map's terrain: the elevation window plus which country each cell belongs to and the national outlines. */
export interface Basemap extends Terrain {
  mask: Uint8Array
  outline: Outline[]
}

/**
 * Wire format of `/api/rain`: the day's rain averaged onto a coarse grid over the terrain domain,
 * float32 little endian, row-major, row 0 southernmost. NaN means no scored cell fell in that bin.
 */
export interface RainPayload {
  date: string
  set: string
  column: string
  unit: string
  n_cells: number
  /** Rain sources named by the day's alert rows (`imd`, `chirps_aligned`, `imerg`), most frequent first. */
  rain_sources?: string[]
  rows: number
  cols: number
  lat0: number
  lon0: number
  step: number
  rain: string
}

export interface Rain {
  date: string
  set: string
  column: string
  unit: string
  /** See `RainPayload.rain_sources`; empty when the API does not say. */
  sources: string[]
  rows: number
  cols: number
  lat0: number
  lon0: number
  step: number
  rain: Float32Array
}

/** One of the model's inputs and how much it moved the risk (log-odds of the raw score); `value` is the input itself. */
export interface ShapFactor {
  feature: string
  value: number | null
  contribution: number
}

/** The alert engine's evidence about one cell-day, as `/risk/cell/{id}` reports it (null where a source had no value). */
export interface SourceEvidence {
  imd1: number | null
  /** The satellite slot: CHIRPS in the replay sets, IMERG in live runs. */
  satellite1: number | null
  /** Trust-weighted mean of the usable gauges within 100 km (`integ_trw_rain_1`). */
  gauge1: number | null
  imd3: number | null
  satellite3: number | null
  gauge3: number | null
  gaugeMax1: number | null
  disagreement3: number | null
  rainSource: string | null
  max1day: number | null
  spread1day: number | null
}

export interface SensorTrust {
  stations: number
  trusted: number
  flagged7d: number
  outOfDistribution: number
  flaggedTypes: string[]
}

/** The rain trigger's entry for a cell-day; the numbers are present when the level was capped and the run kept them. */
export interface RainRule {
  passed: boolean
  exempt: boolean
  capped: boolean
  windowDays: number | null
  rainMm: number | null
  minimumMm: number | null
  /** The level the cap lowered the cell to. */
  cappedTo: string | null
}

export interface CellDetail {
  cell: number
  date: string
  set: string
  lat: number
  lon: number
  region: string | null
  level: Level
  levelName: string
  /** The level before hysteresis held it. */
  rawLevel: string
  confidence: string
  confidenceCauses: string[]
  reasonCodes: string[]
  risk: number | null
  riskLo: number | null
  riskHi: number | null
  shap: ShapFactor[]
  sources: SourceEvidence
  sensorTrust: SensorTrust
  /** The API's place label of the cell; the places table (`usePlaces`) is preferred, this is the fallback. */
  place: PlaceLabel | null
  /** 0 is the run date's assessment, 1 to 3 a forecast for that many days later. */
  lead: number
  /** The run date; the day the assessment is for is `targetDate`. */
  issuedDate: string
  targetDate: string
  forecast: boolean
  /** Forecast only: the interval was widened by the forecast-skill factors. */
  widened: boolean | null
  /** Forecast only: observed rain through the run date and the GFS totals for the days after it. */
  forecastRain: { observed: SourceEvidence; observedDate: string | null; days: ForecastRainDay[] } | null
  /** Forecast only: why the gauge, IMD and satellite fields are empty. */
  unavailable: string | null
  /** Set when the run predates the per-lead detail (no contributions or forecast rain stored). */
  detailMissing: string | null
  /** Forecast only: `firm` (the level is the same under no more rain, the forecast and its heavy-rain bound) or `depends_on_forecast`. */
  certainty: 'firm' | 'depends_on_forecast' | null
  /** Forecast only: the lowest and highest level over those three rain scenarios. */
  levelMin: Level | null
  levelMax: Level | null
  /** Forecast only: the rain source behind the forecast. */
  forecastSource: ForecastSource | null
  rainRule: RainRule | null
}

/** A cell's recent days from `/api/cells/{id}/history`; every array has one entry per date. */
export interface CellHistory {
  cell: number
  set: string
  dates: string[]
  risk: (number | null)[]
  level: number[]
  rain: { imd: (number | null)[]; satellite: (number | null)[]; gauges: (number | null)[] }
  place: PlaceLabel | null
  /** The run (date) whose forecasts follow; null when the history carries none. */
  issuedDate: string | null
  /** The D+1 to D+3 forecasts of the live run of the history's last day; empty for a replay set. */
  forecast: ForecastPoint[]
}

/**
 * Wire format of `/api/places`: the distinct names once, then one entry per labelled cell in typed arrays (base64, little
 * endian, sorted by cell id). `places[place[i]]` is the place of `cells[i]`; index 0 of `districts`, `states` and
 * `countries` is the empty string and means "not given".
 */
export interface PlacesPayload {
  attribution: string
  n: number
  /** Distance in km from which the place is "the nearest town" rather than where the cell is. */
  far_km?: number
  places: string[]
  districts: string[]
  states: string[]
  countries: string[]
  cells: string
  place: string
  district: string
  state: string
  country: string
  distance_km: string
}

/** The populated place nearest to a cell by the rule of `serve.places` (GeoNames), with where it lies. */
export interface PlaceLabel {
  place: string
  district: string | null
  state: string | null
  country: string | null
  /** Whole kilometres from the cell centre to the place. */
  distanceKm: number
}

export interface Places {
  attribution: string
  /** See `PlacesPayload.far_km`. */
  farKm: number
  size: number
  lookup: (cell: number) => PlaceLabel | null
}

/** One forecast day of a cell's history: the risk the live run of the history's last day expects for that day. */
export interface ForecastPoint {
  lead: number
  targetDate: string
  risk: number | null
  riskLo: number | null
  riskHi: number | null
  level: number
}

/** The GFS rain total (mm) of one forecast day at the cell. */
export interface ForecastRainDay {
  date: string
  lead: number
  mm: number | null
}
