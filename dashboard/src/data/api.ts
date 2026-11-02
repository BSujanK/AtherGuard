import {
  type Basemap,
  type BasemapPayload,
  type CellDetail,
  type CellHistory,
  type ForecastPoint,
  type ForecastRainDay,
  type ForecastSource,
  type Grid,
  type GridPayload,
  type Level,
  MASK,
  type ModeResponse,
  type PlaceLabel,
  type Places,
  type PlacesPayload,
  type Rain,
  type RainRule,
  type RainPayload,
  type SourceEvidence,
  type Thresholds,
} from './types'

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

function base64ToBytes(b64: string): Uint8Array<ArrayBuffer> {
  const bin = atob(b64)
  const bytes = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i)
  return bytes
}

function viewOf<T extends Float32Array | Uint32Array | Uint16Array>(
  b64: string,
  ctor: { new (buffer: ArrayBuffer): T; BYTES_PER_ELEMENT: number },
): T {
  const bytes = base64ToBytes(b64)
  if (bytes.length % ctor.BYTES_PER_ELEMENT !== 0) {
    throw new RangeError(
      `Byte length ${bytes.length} is not a multiple of ${ctor.BYTES_PER_ELEMENT}`,
    )
  }
  return new ctor(bytes.buffer)
}

/** Payload arrays are little endian; every browser we target is too. */
export const decodeFloat32 = (b64: string): Float32Array => viewOf(b64, Float32Array)
export const decodeUint32 = (b64: string): Uint32Array => viewOf(b64, Uint32Array)
export const decodeUint16 = (b64: string): Uint16Array => viewOf(b64, Uint16Array)
export const decodeUint8 = (b64: string): Uint8Array => base64ToBytes(b64)

/** IEEE 754 half precision to number, from the bit layout (no Float16Array dependency). */
export function float16ToNumber(h: number): number {
  const sign = h & 0x8000 ? -1 : 1
  const exp = (h >> 10) & 0x1f
  const frac = h & 0x3ff
  if (exp === 0) return sign * 2 ** -14 * (frac / 1024)
  if (exp === 0x1f) return frac ? NaN : sign * Infinity
  return sign * 2 ** (exp - 15) * (1 + frac / 1024)
}

export function decodeFloat16(b64: string): Float32Array {
  const bytes = base64ToBytes(b64)
  if (bytes.length % 2 !== 0) {
    throw new RangeError(`Byte length ${bytes.length} is not a multiple of 2`)
  }
  const out = new Float32Array(bytes.length / 2)
  for (let i = 0; i < out.length; i++) {
    out[i] = float16ToNumber(bytes[2 * i]! | (bytes[2 * i + 1]! << 8))
  }
  return out
}

/** The rain source of a forecast lead; null when absent or not an object. */
export function parseForecastSource(raw: unknown): ForecastSource | null {
  if (!isObject(raw)) return null
  return {
    source: textOrNull(raw.source),
    label: textOrNull(raw.label),
    mapped: typeof raw.mapped === 'boolean' ? raw.mapped : null,
    fallback: typeof raw.fallback === 'boolean' ? raw.fallback : null,
    cycle: textOrNull(raw.cycle),
    attribution: textOrNull(raw.attribution),
  }
}

/** The rain trigger entry of a cell-day, with the numbers behind a cap when the API has them. */
export function parseRainRule(raw: unknown): RainRule | null {
  if (!isObject(raw)) return null
  return {
    passed: raw.passed === true,
    exempt: raw.exempt === true,
    capped: raw.capped === true,
    windowDays: finiteOrNull(raw.window_days),
    rainMm: finiteOrNull(raw.rain_mm),
    minimumMm: finiteOrNull(raw.minimum_mm),
    cappedTo: textOrNull(raw.capped_to),
  }
}

export function decodeGrid(p: GridPayload): Grid {
  const grid: Grid = {
    date: p.date,
    lead: p.lead,
    n: p.n,
    cells: decodeUint32(p.cells),
    risk: decodeFloat32(p.risk),
    level: decodeUint8(p.level),
    confidence: decodeUint8(p.confidence),
    flags: p.flags === undefined ? undefined : decodeUint8(p.flags),
    certainty: p.certainty === undefined ? undefined : decodeUint8(p.certainty),
    levelMin: p.level_min === undefined ? undefined : decodeUint8(p.level_min),
    levelMax: p.level_max === undefined ? undefined : decodeUint8(p.level_max),
    forecast: p.forecast === undefined ? undefined : parseForecastSource(p.forecast),
    lat0: p.lat0,
    lon0: p.lon0,
    step: p.step,
  }
  if (
    grid.cells.length !== p.n ||
    grid.risk.length !== p.n ||
    grid.level.length !== p.n ||
    grid.confidence.length !== p.n ||
    (grid.flags !== undefined && grid.flags.length !== p.n) ||
    (grid.certainty !== undefined && grid.certainty.length !== p.n) ||
    (grid.levelMin !== undefined && grid.levelMin.length !== p.n) ||
    (grid.levelMax !== undefined && grid.levelMax.length !== p.n)
  ) {
    throw new RangeError(`Grid arrays do not all hold n=${p.n} entries`)
  }
  return grid
}

export function decodeRain(p: RainPayload): Rain {
  const rain = decodeFloat32(p.rain)
  if (rain.length !== p.rows * p.cols) {
    throw new RangeError(`Rain has ${rain.length} samples, expected ${p.rows * p.cols}`)
  }
  return {
    date: p.date,
    set: p.set,
    column: p.column,
    unit: p.unit,
    sources: p.rain_sources ?? [],
    rows: p.rows,
    cols: p.cols,
    lat0: p.lat0,
    lon0: p.lon0,
    step: p.step,
    rain,
  }
}

/** Elevation in metres with NaN wherever the mask says sea (the payload keeps the sea floor, the map does not draw it). */
export function decodeBasemap(p: BasemapPayload): Basemap {
  const elev = decodeFloat16(p.elev)
  const mask = decodeUint8(p.mask)
  const size = p.rows * p.cols
  if (elev.length !== size || mask.length !== size) {
    throw new RangeError(`Base map has ${elev.length} elevations and ${mask.length} mask cells, expected ${size}`)
  }
  for (let k = 0; k < size; k++) if (mask[k] === MASK.sea) elev[k] = NaN
  return { rows: p.rows, cols: p.cols, lat0: p.lat0, lon0: p.lon0, step: p.step, elev, mask, outline: p.outline }
}

/** `/api/places` to a lookup by cell id (binary search over the sorted cell ids). */
export function decodePlaces(p: PlacesPayload): Places {
  const cells = decodeUint32(p.cells)
  const place = decodeUint32(p.place)
  const district = decodeUint16(p.district)
  const state = decodeUint16(p.state)
  const country = decodeUint8(p.country)
  const distance = decodeUint16(p.distance_km)
  for (const column of [place, district, state, country, distance]) {
    if (column.length !== cells.length) throw new RangeError(`Places arrays do not all hold ${cells.length} entries`)
  }
  const named = (names: string[], index: number): string | null => (index > 0 ? (names[index] ?? null) : null)
  return {
    attribution: p.attribution,
    farKm: p.far_km ?? 25,
    size: cells.length,
    lookup(cell) {
      let lo = 0
      let hi = cells.length - 1
      while (lo <= hi) {
        const mid = (lo + hi) >> 1
        const at = cells[mid]!
        if (at === cell) {
          const name = p.places[place[mid]!]
          if (name === undefined) return null
          return {
            place: name,
            district: named(p.districts, district[mid]!),
            state: named(p.states, state[mid]!),
            country: named(p.countries, country[mid]!),
            distanceKm: distance[mid]!,
          }
        }
        if (at < cell) lo = mid + 1
        else hi = mid - 1
      }
      return null
    },
  }
}

/** Count how many entries of a byte array hold each code 0..size-1. */
export function countCodes(codes: Uint8Array, size: number): number[] {
  const counts = new Array<number>(size).fill(0)
  for (let i = 0; i < codes.length; i++) {
    const c = codes[i]!
    if (c < size) counts[c]! += 1
  }
  return counts
}

export async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const url = new URL(path, window.location.origin)
  let res: Response
  try {
    res = await fetch(url, { signal, headers: { Accept: 'application/json' } })
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err
    throw new ApiError(0, 'The AetherGuard API is not reachable.')
  }
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = (await res.json()) as { detail?: unknown }
      if (typeof body.detail === 'string') detail = body.detail
    } catch {
      /* body was not JSON; keep the status text */
    }
    throw new ApiError(res.status, detail || `Request failed (${res.status})`)
  }
  return (await res.json()) as T
}

const isObject = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v)
const finiteOrNull = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)
const textOrNull = (v: unknown): string | null => (typeof v === 'string' && v !== '' ? v : null)
const textList = (v: unknown): string[] =>
  Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string' && x !== '') : []

/** Thresholds only when all three are finite and positive; anything else is "unknown", never a guess. */
export function parseThresholds(raw: unknown): Thresholds | null {
  if (!isObject(raw)) return null
  const { watch, warning, emergency } = raw
  const ok = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v) && v > 0
  if (!ok(watch) || !ok(warning) || !ok(emergency)) return null
  return { watch, warning, emergency, source: textOrNull(raw.source) }
}

const shareOrNull = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) && v >= 0 && v <= 1 ? v : null)

/** Leads per date as `{date: [0, 1, ...]}` with only the whole numbers 0 to 3 kept; undefined when the API sends none. */
export function parseLeads(raw: unknown): Record<string, number[]> | undefined {
  if (!isObject(raw)) return undefined
  return Object.fromEntries(
    Object.entries(raw).map(([date, leads]) => [
      date,
      Array.isArray(leads) ? leads.filter((l): l is number => Number.isInteger(l) && l >= 0 && l <= 3) : [],
    ]),
  )
}

/** Thresholds per region, keeping only the regions whose three thresholds are usable; null when none is. */
export function parseRegionalThresholds(raw: unknown): Record<string, Thresholds> | null {
  if (!isObject(raw)) return null
  const found = Object.entries(raw).flatMap(([region, entry]) => {
    const thresholds = parseThresholds(entry)
    return thresholds ? [[region, thresholds] as const] : []
  })
  return found.length > 0 ? Object.fromEntries(found) : null
}

export async function getMode(signal?: AbortSignal): Promise<ModeResponse> {
  const raw = await getJson<
    Partial<Omit<ModeResponse, 'thresholds' | 'thresholds_by_region' | 'leads' | 'scored_share' | 'last_scored_date' | 'scored_reason'>> & {
      thresholds?: unknown
      thresholds_by_region?: unknown
      leads?: unknown
      scored_share?: unknown
      last_scored_date?: unknown
      scored_reason?: unknown
    }
  >('/api/mode', signal)
  return {
    mode: raw.mode ?? 'none',
    set: raw.set ?? null,
    latest_date: raw.latest_date ?? null,
    dates: raw.dates ?? [],
    leads: parseLeads(raw.leads),
    thresholds: parseThresholds(raw.thresholds),
    thresholds_by_region: parseRegionalThresholds(raw.thresholds_by_region),
    scored_share: shareOrNull(raw.scored_share),
    last_scored_date: textOrNull(raw.last_scored_date),
    scored_reason: textOrNull(raw.scored_reason),
    next_run: raw.next_run,
  }
}

export async function getGrid(date: string, lead: number, signal?: AbortSignal): Promise<Grid> {
  const q = new URLSearchParams({ date, lead: String(lead) })
  return decodeGrid(await getJson<GridPayload>(`/api/grid?${q}`, signal))
}

/** The place table; null when the API has none (not built yet, or unreadable), in which case coordinates are shown. */
export async function getPlaces(signal?: AbortSignal): Promise<Places | null> {
  try {
    return decodePlaces(await getJson<PlacesPayload>('/api/places', signal))
  } catch (err) {
    if (err instanceof ApiError || err instanceof RangeError) return null
    throw err
  }
}

export async function getBasemap(signal?: AbortSignal): Promise<Basemap> {
  return decodeBasemap(await getJson<BasemapPayload>('/api/basemap', signal))
}

export async function getRain(date: string, signal?: AbortSignal): Promise<Rain> {
  const q = new URLSearchParams({ date })
  return decodeRain(await getJson<RainPayload>(`/api/rain?${q}`, signal))
}

const malformed = (what: string) => new ApiError(502, `The API returned an unreadable ${what}.`)

function parseEvidence(raw: unknown): SourceEvidence {
  const e = isObject(raw) ? raw : {}
  return {
    imd1: finiteOrNull(e.imd_acc_1),
    satellite1: finiteOrNull(e.chirps_acc_1),
    gauge1: finiteOrNull(e.station_trw_1),
    imd3: finiteOrNull(e.imd_acc_3),
    satellite3: finiteOrNull(e.chirps_acc_3),
    gauge3: finiteOrNull(e.station_trw_3),
    gaugeMax1: finiteOrNull(e.station_max_1),
    disagreement3: finiteOrNull(e.dis_ratio_3),
    rainSource: textOrNull(e.rain_source),
    max1day: finiteOrNull(e.max_1day),
    spread1day: finiteOrNull(e.spread_1day),
  }
}

/** The `place` object of `/risk/cell/{id}` and `/api/cells/{id}/history`; null when absent or without a place name. */
export function parsePlace(raw: unknown): PlaceLabel | null {
  if (!isObject(raw)) return null
  const place = textOrNull(raw.place)
  const distance = finiteOrNull(raw.distance_km)
  if (place === null || distance === null) return null
  return {
    place,
    district: textOrNull(raw.district),
    state: textOrNull(raw.state),
    country: textOrNull(raw.country),
    distanceKm: distance,
  }
}

function parseForecastRain(raw: unknown): CellDetail['forecastRain'] {
  if (!isObject(raw)) return null
  const days: ForecastRainDay[] = Array.isArray(raw.forecast)
    ? raw.forecast.flatMap((d: unknown) => {
        if (!isObject(d) || typeof d.date !== 'string' || typeof d.lead !== 'number') return []
        return [{ date: d.date, lead: d.lead, mm: finiteOrNull(d.mm) }]
      })
    : []
  return { observed: parseEvidence(raw.observed), observedDate: textOrNull(raw.observed_date), days }
}

/** `/risk/cell/{id}` to a CellDetail. Missing numbers become null; a payload without a cell, date or level is an error. */
export function parseCellDetail(raw: unknown): CellDetail {
  if (!isObject(raw)) throw malformed('cell')
  const level = raw.level
  if (typeof raw.cell_id !== 'number' || typeof raw.date !== 'string' || typeof level !== 'number' || level < 0 || level > 3) {
    throw malformed('cell')
  }
  const trust = isObject(raw.sensor_trust) ? raw.sensor_trust : {}
  const count = (v: unknown) => finiteOrNull(v) ?? 0
  const shap = Array.isArray(raw.shap)
    ? raw.shap.flatMap((f: unknown) => {
        if (!isObject(f) || typeof f.feature !== 'string') return []
        const contribution = finiteOrNull(f.contribution)
        return contribution === null ? [] : [{ feature: f.feature, value: finiteOrNull(f.value), contribution }]
      })
    : []
  return {
    cell: raw.cell_id,
    date: raw.date,
    set: textOrNull(raw.set) ?? '',
    lat: finiteOrNull(raw.lat) ?? NaN,
    lon: finiteOrNull(raw.lon) ?? NaN,
    region: textOrNull(raw.region),
    thresholds: parseThresholds(raw.thresholds),
    thresholdsRegion: textOrNull(raw.thresholds_region),
    level: level as Level,
    levelName: textOrNull(raw.level_name) ?? '',
    rawLevel: textOrNull(raw.raw_level) ?? '',
    confidence: textOrNull(raw.confidence) ?? '',
    confidenceCauses: textList(raw.confidence_causes),
    reasonCodes: textList(raw.reason_codes),
    risk: finiteOrNull(raw.risk),
    riskLo: finiteOrNull(raw.risk_lo),
    riskHi: finiteOrNull(raw.risk_hi),
    shap,
    sources: parseEvidence(raw.sources),
    sensorTrust: {
      stations: count(trust.n_stations),
      trusted: count(trust.n_trusted),
      flagged7d: count(trust.n_flagged_7d),
      outOfDistribution: count(trust.n_out_of_distribution),
      flaggedTypes: textList(trust.flagged_types),
    },
    place: parsePlace(raw.place),
    lead: Math.min(3, Math.max(0, finiteOrNull(raw.lead) ?? 0)),
    issuedDate: textOrNull(raw.issued_date) ?? raw.date,
    targetDate: textOrNull(raw.target_date) ?? raw.date,
    forecast: raw.forecast === true,
    widened: typeof raw.widened === 'boolean' ? raw.widened : null,
    forecastRain: parseForecastRain(raw.rain),
    unavailable: textOrNull(raw.unavailable),
    detailMissing: textOrNull(raw.detail_missing),
    certainty: raw.certainty === 'firm' || raw.certainty === 'depends_on_forecast' ? raw.certainty : null,
    levelMin: levelOrNull(raw.level_min),
    levelMax: levelOrNull(raw.level_max),
    forecastSource: parseForecastSource(raw.forecast_source),
    rainRule: parseRainRule(raw.rain_rule),
  }
}

const levelOrNull = (v: unknown): Level | null => {
  const n = finiteOrNull(v)
  return n !== null && Number.isInteger(n) && n >= 0 && n <= 3 ? (n as Level) : null
}

export function parseCellHistory(raw: unknown): CellHistory {
  if (!isObject(raw) || !Array.isArray(raw.dates) || typeof raw.cell_id !== 'number') throw malformed('cell history')
  const dates = raw.dates.filter((d): d is string => typeof d === 'string')
  const series = (v: unknown): (number | null)[] => dates.map((_, i) => (Array.isArray(v) ? finiteOrNull(v[i]) : null))
  const rain = isObject(raw.rain) ? raw.rain : {}
  return {
    cell: raw.cell_id,
    set: textOrNull(raw.set) ?? '',
    dates,
    risk: series(raw.risk),
    level: dates.map((_, i) => (Array.isArray(raw.level) ? (finiteOrNull(raw.level[i]) ?? 0) : 0)),
    rain: { imd: series(rain.imd_acc_1), satellite: series(rain.chirps_acc_1), gauges: series(rain.station_trw_1) },
    place: parsePlace(raw.place),
    issuedDate: textOrNull(raw.issued_date),
    forecast: Array.isArray(raw.forecast) ? raw.forecast.flatMap(parseForecastPoint) : [],
  }
}

function parseForecastPoint(raw: unknown): ForecastPoint[] {
  if (!isObject(raw) || typeof raw.target_date !== 'string' || typeof raw.lead !== 'number') return []
  return [
    {
      lead: raw.lead,
      targetDate: raw.target_date,
      risk: finiteOrNull(raw.risk),
      riskLo: finiteOrNull(raw.risk_lo),
      riskHi: finiteOrNull(raw.risk_hi),
      level: finiteOrNull(raw.level) ?? 0,
    },
  ]
}

export async function getCell(
  cell: number,
  date: string,
  set: string | null,
  lead = 0,
  signal?: AbortSignal,
): Promise<CellDetail> {
  const q = new URLSearchParams({ date })
  if (set) q.set('set', set)
  if (lead > 0) q.set('lead', String(lead))
  return parseCellDetail(await getJson<unknown>(`/risk/cell/${cell}?${q}`, signal))
}

export async function getCellHistory(
  cell: number,
  date: string,
  set: string | null,
  days = 30,
  signal?: AbortSignal,
): Promise<CellHistory> {
  const q = new URLSearchParams({ date, days: String(days) })
  if (set) q.set('set', set)
  return parseCellHistory(await getJson<unknown>(`/api/cells/${cell}/history?${q}`, signal))
}
