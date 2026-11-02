import { GRID_FLAG, type ModeResponse, type PlaceLabel } from './types'

/**
 * The next scheduled run as the API reports it (ISO datetime carrying the +05:30 offset), e.g.
 * "11:00 IST, 16 Oct". Read from the string so the viewer's own time zone never shifts it.
 */
export function formatNextRun(iso: string | undefined): string {
  const match = iso?.match(/^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/)
  if (!match) return 'n/a'
  const day = new Date(`${match[1]}T00:00:00Z`).toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'short',
    timeZone: 'UTC',
  })
  return `${match[2]} IST, ${day}`
}

export function formatDate(iso: string | null): string {
  if (!iso) return 'n/a'
  const d = new Date(`${iso}T00:00:00Z`)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })
}

/** Day and month only, for the ends of a timeline whose year is shown once. */
export function formatDayMonth(iso: string | null): string {
  if (!iso) return 'n/a'
  const d = new Date(`${iso}T00:00:00Z`)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' })
}

export const formatCount = (n: number): string => n.toLocaleString('en-IN')

export function modeLabel(mode: ModeResponse['mode']): string {
  return mode === 'live' ? 'Live' : mode === 'replay' ? 'Replay' : 'No data'
}

/** Cells are numbered row-major on the global 0.05 degree grid (see `Grid.lat0`, `Grid.lon0`). */
export const GRID_COLS = 10_000
export const GRID_ORIGIN = { lat0: -90, lon0: -180, step: 0.05 }

export function cellCenter(id: number): { lat: number; lon: number } {
  const { lat0, lon0, step } = GRID_ORIGIN
  return {
    lat: lat0 + (Math.floor(id / GRID_COLS) + 0.5) * step,
    lon: lon0 + ((id % GRID_COLS) + 0.5) * step,
  }
}

/** Daily cell risks are probabilities of a landslide per cell-day, mostly far below 1%; the display scales them to a count. */
export const RISK_SCALE = 1e5

/** Two significant digits down to 0.001, a short exponent form below, whole numbers from 10 up. */
function significant(value: number): string {
  if (value === 0) return '0'
  if (value >= 10) return Math.round(value).toLocaleString('en-US')
  if (value >= 0.001) return value.toLocaleString('en-US', { maximumSignificantDigits: 2 })
  return value.toExponential(1)
}

/** The risk as a bare number per 100k cell-days ("45", "0.41"), for ranges and thresholds. */
export const formatPer100k = (risk: number): string => significant(risk * RISK_SCALE)

export interface RiskText {
  /** "45 per 100k cell-days", or "n/a" when the risk is missing. */
  primary: string
  /** "3.2× Watch threshold", or null when the threshold is unknown or the risk missing. */
  secondary: string | null
  /** The raw probability, for a tooltip only. */
  raw: string
}

/**
 * The one way risk is shown: expected landslides per 100,000 cell-days, and how many times the Watch threshold
 * that is. `watch` is the model card's Watch risk (`/api/mode` thresholds); without it only the first part is shown.
 */
export function describeRisk(risk: number | null | undefined, watch?: number | null): RiskText {
  if (risk === null || risk === undefined || !Number.isFinite(risk) || risk < 0) {
    return { primary: 'n/a', secondary: null, raw: 'No risk score for this cell-day' }
  }
  const haveWatch = watch !== null && watch !== undefined && Number.isFinite(watch) && watch > 0
  const ratio = haveWatch ? risk / watch : null
  return {
    primary: `${formatPer100k(risk)} per 100k cell-days`,
    secondary: ratio === null ? null : `${ratio > 0 && ratio < 0.01 ? '<0.01' : significant(ratio)}× Watch threshold`,
    raw: `Raw probability ${risk === 0 ? '0' : risk.toPrecision(3)} per cell-day`,
  }
}

export interface OddsText {
  /** "About 1 in 330,000 chance of a landslide in this 5 km cell today"; for a capped cell, why no chance is given. */
  sentence: string
  /** "1 in 330,000", for places with little room; "not used" for a capped cell. */
  short: string
}

export interface OddsOptions {
  /** The rain trigger capped the level: the model's 1 in N is not trusted, so it is not given as the chance. */
  capped?: boolean
  /** Most of the 20 ensemble models put the risk lower than the point estimate. */
  disagrees?: boolean
}

/** What the figures beside a capped cell's odds are called, in place of the headline they would otherwise back. */
export const MODEL_ESTIMATE = 'model estimate (not used for the level)'

/** The `OddsOptions` a grid cell's `GRID_FLAG` bits give. */
export const oddsOptions = (flags: number | undefined): OddsOptions => ({
  capped: ((flags ?? 0) & GRID_FLAG.capped) !== 0,
  disagrees: ((flags ?? 0) & GRID_FLAG.ensembleDisagrees) !== 0,
})

/** `n` to two significant digits ("330,000", "1,200", "47"). */
function twoSignificant(n: number): string {
  const digits = Math.floor(Math.log10(n)) + 1
  const scale = 10 ** Math.max(digits - 2, 0)
  return (Math.round(n / scale) * scale).toLocaleString('en-US')
}

/**
 * The calibrated risk in words: "About 1 in N chance of a landslide in this 5 km cell today" (or `on <day>`), N being
 * 1 / risk rounded to two significant digits. null for a risk of 0, missing or not finite: no line is shown then.
 * `when` is "today" for the live run's own day, else a phrase such as "on Sat 26 Oct".
 * A `capped` cell gets no chance: the rain trigger has just decided not to trust the model's N, so the sentence says
 * so and names N as an estimate that is not used. With `disagrees` the sentence keeps N and adds that most ensemble
 * members put it lower.
 */
export function describeOdds(risk: number | null | undefined, when: string, options: OddsOptions = {}): OddsText | null {
  if (risk === null || risk === undefined || !Number.isFinite(risk) || risk <= 0) return null
  const n = twoSignificant(Math.max(1, 1 / risk))
  if (options.capped) {
    return {
      sentence: `Too little recent rain for a rain-triggered landslide, so no chance is given (the model's 1 in ${n} estimate is not used)`,
      short: 'not used',
    }
  }
  const sentence = `About 1 in ${n} chance of a landslide in this 5 km cell ${when}`
  return {
    sentence: options.disagrees ? `${sentence} (most of the 20 ensemble models put it lower)` : sentence,
    short: `1 in ${n}`,
  }
}

/** The day phrase of `describeOdds`: "today" for the live run's own day at lead 0, "on Sat 26 Oct" otherwise. */
export function oddsWhen(date: string | null | undefined, lead: number, today: boolean): string {
  if (lead === 0 && today) return 'today'
  return date ? `on ${formatWeekday(lead > 0 ? addDays(date, lead) : date)}` : 'today'
}

/** The risk as one sentence fragment for labels read aloud: primary, then secondary when known. */
export const spokenRisk = ({ primary, secondary }: RiskText): string => (secondary ? `${primary}, ${secondary}` : primary)

const RAIN_SOURCE_NAMES: Readonly<Record<string, string>> = {
  imd: 'IMD gauge-based grid',
  chirps_aligned: 'CHIRPS satellite estimate (aligned to IMD)',
  imerg: 'NASA IMERG (satellite)',
}
export const NEUTRAL_RAIN = '1-day rain (mm/day)'

/**
 * Name of the rain product behind the shown rain layer: IMERG for live sets and for a table carrying the IMERG
 * column, else what the day's `rain_source` values say; null when nothing says (the caller then stays neutral).
 */
export function rainSourceName(rain: { set: string; column: string; sources: readonly string[] }): string | null {
  if (rain.set === 'live' || rain.column === 'irain_acc_1') return RAIN_SOURCE_NAMES.imerg!
  const names = rain.sources.filter((s) => s !== 'none').map((s) => RAIN_SOURCE_NAMES[s] ?? s)
  return names.length > 0 ? names.join(' and ') : null
}

export function formatLatLon(lat: number, lon: number): string {
  const ns = lat >= 0 ? 'N' : 'S'
  const ew = lon >= 0 ? 'E' : 'W'
  return `${Math.abs(lat).toFixed(2)}°${ns}, ${Math.abs(lon).toFixed(2)}°${ew}`
}

/** The distance from which the nearest place is "the nearest town", not where the cell is. */
export const FAR_KM = 25

/** "Mananthavady, Wayanad, Kerala" (", Nepal" or ", Bhutan" after it; India is the default and is left out). */
export function placeTitle(label: PlaceLabel): string {
  const parts: string[] = []
  for (const part of [label.place, label.district, label.state]) {
    if (part && parts[parts.length - 1] !== part) parts.push(part)
  }
  if (label.country && label.country !== 'India') parts.push(label.country)
  return parts.join(', ')
}

export interface PlaceText {
  /** The place name line, or the coordinates when the cell has no label. */
  primary: string
  /** "8 km from town centre · 11.83°N, 75.93°E", or "nearest town: X (32 km) · ..." from `farKm` on; null without a label. */
  secondary: string | null
  /** The nearest place is `farKm` or more away. */
  far: boolean
}

/**
 * The one way a cell's location is shown. With a place label: the place, district and state, and under it the distance
 * to the town centre and the coordinates. A remote cell (`farKm` or more from its place) says "nearest town" instead,
 * so a ridge 32 km out is not presented as if it lay in the town. Without a label (no place table, or the cell is not
 * in it): the coordinates alone.
 */
export function describePlace(cell: number, label: PlaceLabel | null | undefined, farKm = FAR_KM): PlaceText {
  const { lat, lon } = cellCenter(cell)
  const coordinates = formatLatLon(lat, lon)
  if (!label) return { primary: coordinates, secondary: null, far: false }
  const far = label.distanceKm >= farKm
  const distance = far
    ? `nearest town: ${label.place} (${label.distanceKm} km)`
    : `${label.distanceKm < 1 ? '<1' : label.distanceKm} km from town centre`
  return { primary: placeTitle(label), secondary: `${distance} · ${coordinates}`, far }
}

/** "Sat 26 Oct" in the viewer-independent calendar of an ISO day. */
export function formatWeekday(iso: string | null): string {
  if (!iso) return 'n/a'
  const d = new Date(`${iso}T00:00:00Z`)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', timeZone: 'UTC' }).replace(',', '')
}

/** The ISO day `days` after (or, negative, before) an ISO day. */
export function addDays(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() + days)
  return d.toISOString().slice(0, 10)
}

export const LEAD_LABELS = ['D0', 'D+1', 'D+2', 'D+3'] as const

/** A lead from the address or a control: a whole number 0 to 3, else 0. */
export function parseLead(raw: string | number | null | undefined): 0 | 1 | 2 | 3 {
  const n = typeof raw === 'string' ? (/^[0-3]$/.test(raw) ? Number(raw) : 0) : (raw ?? 0)
  return n === 1 || n === 2 || n === 3 ? n : 0
}
