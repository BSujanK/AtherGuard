import { http, HttpResponse } from 'msw'
import { cellCenter } from '../data/summary'
import type { Grid } from '../data/types'
import { bytesToBase64, noPlacesHandler } from './fixtures'

/** Cell id of the 0.05 degree cell holding a point. */
export const cellAt = (lat: number, lon: number): number =>
  Math.floor((lat + 90) / 0.05 + 1e-6) * 10_000 + Math.floor((lon + 180) / 0.05 + 1e-6)

export interface GridRow {
  cell: number
  risk: number
  level: number
  confidence?: number
  /** `GRID_FLAG` bits of the cell. */
  flags?: number
}

/** A grid of the given rows, sorted by cell id as the API sends it. */
export function makeGrid(rows: GridRow[], date = '2024-08-05'): Grid {
  const sorted = [...rows].sort((a, b) => a.cell - b.cell)
  return {
    date,
    lead: 0,
    n: sorted.length,
    cells: Uint32Array.from(sorted.map((r) => r.cell)),
    risk: Float32Array.from(sorted.map((r) => r.risk)),
    level: Uint8Array.from(sorted.map((r) => r.level)),
    confidence: Uint8Array.from(sorted.map((r) => r.confidence ?? 0)),
    ...(sorted.some((r) => r.flags) ? { flags: Uint8Array.from(sorted.map((r) => r.flags ?? 0)) } : {}),
    lat0: -90,
    lon0: -180,
    step: 0.05,
  }
}

/** `n` cells in a block over southern India with spread-out risks, levels and confidences (deterministic). */
export function syntheticGrid(n: number, date = '2024-08-05'): Grid {
  const rows: GridRow[] = []
  for (let i = 0; i < n; i++) {
    const level = i % 11 === 0 ? 3 : i % 5 === 0 ? 2 : i % 2 === 0 ? 1 : 0
    rows.push({
      cell: (2020 + Math.floor(i / 100)) * 10_000 + 5100 + (i % 100),
      risk: ((i * 7919) % 10_007) / 1e8,
      level,
      confidence: i % 3,
    })
  }
  return makeGrid(rows, date)
}

/** A base64 grid payload of a Grid, for serving it through msw. */
export function gridToPayload(grid: Grid) {
  const bytes = (view: ArrayBufferView) => bytesToBase64(new Uint8Array(view.buffer, view.byteOffset, view.byteLength))
  return {
    date: grid.date,
    lead: grid.lead,
    n: grid.n,
    cells: bytes(grid.cells),
    risk: bytes(grid.risk),
    level: bytes(grid.level),
    confidence: bytes(grid.confidence),
    ...(grid.flags ? { flags: bytes(grid.flags) } : {}),
    lat0: grid.lat0,
    lon0: grid.lon0,
    step: grid.step,
  }
}

export const place = (cell: number): string => {
  const { lat, lon } = cellCenter(cell)
  return `${lat.toFixed(2)} ${lon.toFixed(2)}`
}

/** The `/risk/cell/{id}` body the backend returns for an Emergency cell of the Wayanad replay (shape from CellExplanation). */
export const cellBody = {
  cell_id: 20285122,
  date: '2024-07-30',
  set: 'case_wayanad_2024_samples',
  lat: 11.525,
  lon: 76.075,
  region: 'western_ghats',
  level: 3,
  level_name: 'Emergency',
  raw_level: 'Emergency',
  confidence: 'Degraded',
  confidence_causes: ['sources_disagree', 'stations_flagged_nearby', 'made_up_cause'],
  reason_codes: ['risk_above_emergency', 'sensors_untrusted_heavy_rain', 'hysteresis_hold'],
  risk: 0.000451981836087848,
  risk_lo: 0.000332239748177021,
  risk_hi: 0.000626640804566144,
  risk_per_100k: 45.1981836087848,
  thresholds: { watch: 4.134155079431125e-6, warning: 1.583087474782703e-5, emergency: 3.697191461958891e-5, source: 'card.alert_levels' },
  provisional: null,
  shap: [
    { feature: 'rain_acc_1', value: 179.23580932617188, contribution: 1.1100553849347 },
    { feature: 'stat_elev_mean', value: 1619.12548828125, contribution: 0.737126799087882 },
    { feature: 'rain_acc_3', value: 190.806427001953, contribution: 0.675462703994114 },
    { feature: 'rain_share1_3', value: 0.9393594264984131, contribution: -0.471032737814813 },
    { feature: 'rain_acc_30', value: null, contribution: 0.468818509909339 },
  ],
  sources: {
    imd_acc_1: 179.23580932617188,
    chirps_acc_1: null,
    station_max_1: 176.0,
    imd_acc_3: 190.806427001953,
    chirps_acc_3: null,
    station_trw_3: 194.17005920410156,
    station_trw_1: 158.13038635253906,
    dis_ratio_3: null,
    rain_source: 'imd',
    max_1day: 179.23580932617188,
    spread_1day: null,
  },
  sensor_trust: { n_stations: 2, n_trusted: 1, n_flagged_7d: 1, n_out_of_distribution: 0, flagged_types: ['stuck_zero'] },
}

/** The `place` object `/risk/cell/{id}` and the history carry once `python -m aetherguard.serve.places build` has run. */
export const placeBody = {
  place: 'Kalpatta',
  district: 'Wayanad',
  state: 'Kerala',
  country: 'India',
  distance_km: 16,
  place_lat: 11.6087,
  place_lon: 76.0834,
  population: 31580,
}

/** Observed rain through the run date of the forecast fixtures (the alert engine's evidence of 2024-07-30). */
const observedThroughD = { ...cellBody.sources, imd_acc_1: 82.5, chirps_acc_1: 91.2, station_max_1: 88, station_trw_1: 79.4 }

/**
 * `/risk/cell/{id}?lead=k` for the Wayanad cell on the run of 2024-07-30: a Warning forecast whose GFS rain for the target
 * day (and the days before it) is stored with the run. Sources, gauges and IMD are empty, as for any future day.
 */
export const forecastBody = (lead: number, over: Record<string, unknown> = {}) => ({
  ...cellBody,
  date: '2024-07-30',
  set: 'live',
  lead,
  issued_date: '2024-07-30',
  target_date: ['2024-07-30', '2024-07-31', '2024-08-01', '2024-08-02'][lead],
  forecast: true,
  widened: true,
  level: 2,
  level_name: 'Warning',
  raw_level: 'Warning',
  confidence: 'Degraded',
  confidence_causes: [],
  reason_codes: ['risk_above_warning'],
  risk: 2.1e-5 * lead,
  risk_lo: 1.2e-5 * lead,
  risk_hi: 6e-5 * lead,
  shap: [
    { feature: 'irain_acc_1', value: 31.5 * lead, contribution: 0.9 },
    { feature: 'stat_elev_mean', value: 1619.1, contribution: 0.7 },
  ],
  sources: Object.fromEntries(Object.keys(cellBody.sources).map((k) => [k, k === 'rain_source' ? 'gfs' : null])),
  sensor_trust: { n_stations: 0, n_trusted: 0, n_flagged_7d: 0, n_out_of_distribution: 0, flagged_types: [] },
  rain: {
    unit: 'mm/day',
    observed_date: '2024-07-30',
    observed: observedThroughD,
    forecast: [
      { date: '2024-07-31', lead: 1, mm: 18.4 },
      { date: '2024-08-01', lead: 2, mm: 42.1 },
      { date: '2024-08-02', lead: 3, mm: 67.9 },
    ].slice(0, lead),
  },
  unavailable: 'A forecast day has no gauge reading, IMD grid or satellite estimate yet, so those fields are empty; the rain behind it is the NOAA GFS forecast.',
  detail_missing: null,
  certainty: 'depends_on_forecast',
  level_min: 1,
  level_max: 3,
  forecast_source: { source: 'gfs', label: 'NOAA GFS', mapped: false, fallback: false, cycle: '2024-07-30T00:00:00+00:00', attribution: null },
  ...over,
})

/** `/api/cells/{id}/history` for five days; the satellite series misses one day, the gauges two. */
export const historyBody = {
  cell_id: 20285122,
  set: 'case_wayanad_2024_samples',
  days: 30,
  dates: ['2024-07-26', '2024-07-27', '2024-07-28', '2024-07-29', '2024-07-30'],
  risk: [0.000001, 0.000004, 0.00001, 0.0002, 0.000452],
  level: [0, 1, 1, 3, 3],
  rain: {
    imd_acc_1: [1, 4, 30, 120, 179.2],
    chirps_acc_1: [2, null, 25, 90, 150],
    station_trw_1: [null, null, 28, 100, 158.1],
  },
  place: null,
  issued_date: '2024-07-30',
  forecast: [],
}

/** The same history with the D+1 to D+3 forecasts of the run of its last day. */
export const forecastHistoryBody = {
  ...historyBody,
  forecast: [
    { lead: 1, target_date: '2024-07-31', risk: 2.1e-5, risk_lo: 1.2e-5, risk_hi: 6e-5, level: 2 },
    { lead: 2, target_date: '2024-08-01', risk: 4.2e-5, risk_lo: 2.4e-5, risk_hi: 1.2e-4, level: 3 },
    { lead: 3, target_date: '2024-08-02', risk: 6.3e-5, risk_lo: 3.6e-5, risk_hi: 1.8e-4, level: 3 },
  ],
}

export const alertsHandlers = (over: { cell?: unknown; history?: unknown; forecast?: (lead: number) => unknown } = {}) => [
  noPlacesHandler,
  http.get('*/risk/cell/:id', ({ params, request }) => {
    const lead = Number(new URL(request.url).searchParams.get('lead') ?? 0)
    if (lead > 0 && Number(params.id) === cellBody.cell_id) return HttpResponse.json(over.forecast?.(lead) ?? forecastBody(lead))
    return undefined
  }),
  http.get('*/risk/cell/:id', ({ params }) =>
    Number(params.id) === cellBody.cell_id
      ? HttpResponse.json(over.cell ?? cellBody)
      : HttpResponse.json(
          { detail: `cell ${String(params.id)} has no alert row on 2024-07-30 in set 'case_wayanad_2024_samples'` },
          { status: 404 },
        ),
  ),
  http.get('*/api/cells/:id/history', ({ params }) =>
    Number(params.id) === cellBody.cell_id
      ? HttpResponse.json(over.history ?? historyBody)
      : HttpResponse.json({ detail: `cell ${String(params.id)} has no rows` }, { status: 404 }),
  ),
]
