import { useQuery } from '@tanstack/react-query'
import { ApiError, getJson } from './api'
import { queryKeys } from './hooks'

/** The daily pipeline run that writes freshness.json; before the first one there is no source health to show. */
export const DAILY_RUN_LABEL = '11:00 IST'

// ---- source health ---------------------------------------------------------------------------------------------------

/**
 * Median latencies in hours (data issued minus the end of the period it covers) measured by
 * reports/phase6_live_sources_probe.md: IMERG Late 14.46, IMERG Early 4.48 (median of the last five days), GFS first
 * hours 3.95, GHCN-Daily 115.9 with 168 as its weekly ceiling, IMD real-time not measurable by the probe so its daily
 * cadence stands in. A source running slower than this by more than `LATE_GRACE_H` is late.
 */
export const EXPECTED_LATENCY_H: Readonly<Record<string, number>> = {
  imerg_late: 14.5,
  imerg_early: 4.5,
  gfs: 5,
  imd_rt: 24,
  ghcn: 168,
}

/** Day-to-day jitter around the medians (IMERG Late measured 14.45 to 14.53 h on consecutive days) is not lateness. */
export const LATE_GRACE_H = 1

/**
 * Optional sources a run may report after the five core ones (live/sources.py `OPTIONAL_SOURCE_NAMES`): shown when the run
 * has them. ECMWF IFS: the ensemble of the 18Z run is complete 8.2 h after its cycle time (reports/phase6_ecmwf_publication.md).
 */
const OPTIONAL_SOURCES: Readonly<Record<string, { label: string; expectedLatencyH: number }>> = {
  ecmwf: { label: 'ECMWF IFS', expectedLatencyH: 8.2 },
}

/** Display order and names, keyed by the `name` freshness.json uses (live/sources.py `SOURCE_NAMES`). */
const SOURCE_LABELS: ReadonlyArray<readonly [string, string]> = [
  ['imerg_late', 'IMERG Late'],
  ['imerg_early', 'IMERG Early'],
  ['gfs', 'GFS'],
  ['imd_rt', 'IMD real-time'],
  ['ghcn', 'GHCN gauges'],
]

export interface SourceRecord {
  name: string
  ok: boolean
  /** ISO instant the source's data covers up to. */
  validThrough: string | null
  /** ISO instant the data was published. */
  issued: string | null
  latencyH: number | null
  error: string | null
  /** The runner's own verdict (`state` in freshness.json) when it wrote one. */
  state: 'ok' | 'late' | 'failed' | null
}

/** Which rain product fed one recent IMD day, e.g. `{day: 'D', product: 'late+early_mapped'}`. */
export interface RainProvenance {
  day: string
  product: string
}

export interface RunInfo {
  date: string | null
  generatedUtc: string | null
  backtest: boolean
  rainProvenance: RainProvenance[]
}

export type SourcesStatus =
  | { available: true; run: RunInfo; sources: SourceRecord[] }
  | { available: false; reason: string }

export type SourceHealth = 'ok' | 'late' | 'failed' | 'unknown'

export interface SourceRow {
  key: string
  label: string
  expectedLatencyH: number | null
  status: SourceHealth
  /** The run's record of the source; null when the run did not report it. */
  record: SourceRecord | null
}

const isObject = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v)
const text = (v: unknown): string | null => (typeof v === 'string' && v !== '' ? v : null)

function finite(v: unknown): number | null {
  if (typeof v === 'number') return Number.isFinite(v) ? v : null
  if (typeof v === 'string' && v.trim() !== '') {
    const n = Number(v)
    return Number.isFinite(n) ? n : null
  }
  return null
}

function parseRecord(raw: unknown, fallbackName: string | null): SourceRecord | null {
  if (!isObject(raw)) return null
  const name = text(raw.name) ?? fallbackName
  if (name === null) return null
  return {
    name,
    ok: raw.ok === true,
    validThrough: text(raw.valid_through),
    issued: text(raw.issued),
    latencyH: finite(raw.latency_h),
    error: text(raw.error),
    state: raw.state === 'ok' || raw.state === 'late' || raw.state === 'failed' ? raw.state : null,
  }
}

/**
 * Tolerant reader of `/api/sources/status`: the freshness.json the live runner writes (`sources` keyed by name) or the
 * `{available: false, reason}` the API returns before a first run. Unknown fields are ignored; `sources` may also be a list.
 */
export function parseSourcesStatus(raw: unknown): SourcesStatus {
  if (!isObject(raw)) return { available: false, reason: 'The API returned source status in an unknown format.' }
  if (raw.available === false) {
    return { available: false, reason: text(raw.reason) ?? 'The API reports no source status.' }
  }
  const list = Array.isArray(raw.sources) ? raw.sources.map((r) => parseRecord(r, null)) : null
  const keyed = isObject(raw.sources) ? Object.entries(raw.sources).map(([key, r]) => parseRecord(r, key)) : null
  const records = list ?? keyed
  if (records === null) {
    return raw.available === true
      ? { available: true, run: parseRun(raw), sources: [] }
      : { available: false, reason: 'The API returned source status in an unknown format.' }
  }
  return { available: true, run: parseRun(raw), sources: records.filter((r): r is SourceRecord => r !== null) }
}

function parseProvenance(raw: unknown): RainProvenance[] {
  if (!isObject(raw)) return []
  return Object.entries(raw).flatMap(([day, v]) => {
    const product = isObject(v) ? text(v.product) : null
    return product === null ? [] : [{ day, product }]
  })
}

function parseRun(raw: Record<string, unknown>): RunInfo {
  return {
    date: text(raw.date),
    generatedUtc: text(raw.generated_utc),
    backtest: raw.backtest === true,
    rainProvenance: parseProvenance(raw.imd_day_inputs),
  }
}

/**
 * The runner's `state` when the record carries one. Otherwise: failed = the source did not deliver (`ok` false);
 * late = delivered but slower than expected; unknown = cannot tell.
 */
export function classifySource(record: SourceRecord | null, expectedLatencyH: number | null): SourceHealth {
  if (record === null) return 'unknown'
  if (record.state !== null) return record.state
  if (!record.ok) return 'failed'
  if (record.latencyH === null || !Number.isFinite(record.latencyH)) return 'unknown'
  if (expectedLatencyH !== null && record.latencyH > expectedLatencyH + LATE_GRACE_H) return 'late'
  return 'ok'
}

/** One row per known source in display order (a source the run did not report is `unknown`), then any extras. */
export function buildSourceRows(sources: SourceRecord[]): SourceRow[] {
  const byName = new Map(sources.map((s) => [s.name, s]))
  const known = new Set(SOURCE_LABELS.map(([key]) => key))
  const extras = sources.filter((s) => !known.has(s.name)).map((s) => [s.name, OPTIONAL_SOURCES[s.name]?.label ?? s.name] as const)
  return [...SOURCE_LABELS, ...extras].map(([key, label]) => {
    const record = byName.get(key) ?? null
    const expectedLatencyH = EXPECTED_LATENCY_H[key] ?? OPTIONAL_SOURCES[key]?.expectedLatencyH ?? null
    return { key, label, expectedLatencyH, status: classifySource(record, expectedLatencyH), record }
  })
}

export const formatLatency = (hours: number | null): string =>
  hours === null || !Number.isFinite(hours) ? '—' : hours.toFixed(1)

const IST = new Intl.DateTimeFormat('en-GB', {
  timeZone: 'Asia/Kolkata',
  day: 'numeric',
  month: 'short',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
})

/** "15 Oct, 11:01": an instant in India Standard Time. */
export function formatIst(iso: string | null): string {
  if (iso === null) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  const p = Object.fromEntries(IST.formatToParts(d).map((part) => [part.type, part.value]))
  return `${p.day} ${p.month}, ${p.hour}:${p.minute}`
}

// ---- sensors ---------------------------------------------------------------------------------------------------------

/**
 * One station of `/sensors`. `trust` is null when the gauge has no value that day (state "missing"); `lastReading` is
 * the ISO date of its newest value (live tables only; GHCN reports arrive days late, so on a live day most gauges have
 * none yet), null when unknown.
 */
export interface SensorStation {
  station: string
  name: string | null
  lat: number
  lon: number
  trust: number | null
  faultType: string
  flagged: boolean
  genuineExtreme: boolean
  reasons: string
  state: string
  flagRateWindow: number | null
  ood: boolean
  lastReading: string | null
}

export interface SensorsReport {
  date: string
  set: string
  stateCounts: Record<string, number>
  stations: SensorStation[]
  /** Why `stations` is empty when the API holds the date but no gauge table for it; null otherwise. */
  reason: string | null
}

export function parseSensors(raw: unknown): SensorsReport {
  if (!isObject(raw) || !Array.isArray(raw.stations)) {
    throw new TypeError('The sensors response has no stations list.')
  }
  const stations: SensorStation[] = []
  for (const s of raw.stations) {
    if (!isObject(s)) continue
    const lat = finite(s.lat)
    const lon = finite(s.lon)
    if (typeof s.station !== 'string' || lat === null || lon === null) continue
    stations.push({
      station: s.station,
      name: text(s.name),
      lat,
      lon,
      trust: finite(s.trust),
      faultType: typeof s.fault_type === 'string' ? s.fault_type : '',
      flagged: s.flagged === true,
      genuineExtreme: s.genuine_extreme === true,
      reasons: typeof s.reasons === 'string' ? s.reasons : '',
      state: typeof s.state === 'string' ? s.state : '',
      flagRateWindow: finite(s.flag_rate_window),
      ood: s.ood === true,
      lastReading: text(s.last_reading),
    })
  }
  const counts: Record<string, number> = {}
  if (isObject(raw.state_counts)) {
    for (const [k, v] of Object.entries(raw.state_counts)) {
      const n = finite(v)
      if (n !== null) counts[k] = n
    }
  }
  return { date: text(raw.date) ?? '', set: text(raw.set) ?? '', stateCounts: counts, stations, reason: text(raw.reason) }
}

// ---- clients and hooks -----------------------------------------------------------------------------------------------

export async function getSourcesStatus(signal?: AbortSignal): Promise<SourcesStatus> {
  return parseSourcesStatus(await getJson<unknown>('/api/sources/status', signal))
}

export async function getSensors(date: string, signal?: AbortSignal): Promise<SensorsReport> {
  return parseSensors(await getJson<unknown>(`/sensors?${new URLSearchParams({ date })}`, signal))
}

/** Under the `sources` key prefix, so the stream's `sources` event refreshes it. */
export const sourcesStatusKey = [...queryKeys.sources, 'status'] as const
export const sensorsKey = (date: string) => ['sensors', date] as const

export function useSourcesStatus() {
  return useQuery({
    queryKey: sourcesStatusKey,
    queryFn: ({ signal }) => getSourcesStatus(signal),
    staleTime: 30_000,
  })
}

/** Gauge trust for one date; a date the store does not hold (404) is an answer, not worth retrying. */
export function useSensors(date: string | null | undefined) {
  return useQuery({
    queryKey: sensorsKey(date ?? ''),
    queryFn: ({ signal }) => getSensors(date!, signal),
    enabled: Boolean(date),
    staleTime: 60_000,
    retry: (count, error) => !(error instanceof ApiError && error.status === 404) && count < 1,
  })
}
