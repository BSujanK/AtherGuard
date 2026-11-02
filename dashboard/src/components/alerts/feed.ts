import { type CertaintyText, certaintyShort, gridCertainty } from '../../data/certainty'
import { cellCenter } from '../../data/summary'
import { CERTAINTY, CONFIDENCES, type Grid, type Places } from '../../data/types'
import { REGION_LABELS, type RegionFilter, regionOf, type RegionName } from '../../scene/geo'

export type SortKey = 'level' | 'risk' | 'confidence' | 'region'
export type SortDir = 'asc' | 'desc'
export interface Sort {
  key: SortKey
  dir: SortDir
}

export interface FeedFilter {
  /** Which levels are listed, indexed by level code 0..3. */
  levels: readonly boolean[]
  region: RegionFilter
  /** Text typed in the search box: matched against the cell id (its digits) and against the place, district and state. */
  query: string
  /** The place names to search; without them only the cell id can match. */
  places?: Places | null
  /** Forecast leads: list only the cells whose level is firm (the same under every rain scenario). */
  firmOnly?: boolean
}

/** Watch and above, the cells that are alerts; Normal cells are listed only on request. */
export const DEFAULT_LEVELS: readonly boolean[] = [false, true, true, true]
export const DEFAULT_SORT: Sort = { key: 'level', dir: 'desc' }

/** The natural first direction of each sort: most severe, highest or best first, and A to Z. */
export const FIRST_DIRECTION: Record<SortKey, SortDir> = { level: 'desc', risk: 'desc', confidence: 'asc', region: 'asc' }

export const OUTSIDE_REGIONS = 'Outside both regions'

/** A grid with the region of each cell worked out once, which sorting, filtering and rendering then share. */
export interface FeedSource {
  grid: Grid
  /** 0 = outside both regions, 1 = Himalaya, 2 = Western Ghats; indexed like the grid. */
  region: Uint8Array
}

const REGION_CODES: readonly (RegionName | null)[] = [null, 'himalaya', 'western_ghats']

export function feedSource(grid: Grid): FeedSource {
  const region = new Uint8Array(grid.n)
  for (let i = 0; i < grid.n; i++) {
    const { lat, lon } = cellCenter(grid.cells[i]!)
    region[i] = REGION_CODES.indexOf(regionOf(lat, lon))
  }
  return { grid, region }
}

export const regionName = (code: number): string => {
  const name = REGION_CODES[code]
  return name ? REGION_LABELS[name] : OUTSIDE_REGIONS
}

export interface FeedRow {
  cell: number
  level: number
  risk: number
  confidence: number
  confidenceName: string
  /** The cell's `GRID_FLAG` bits; 0 for a grid without them. */
  flags: number
  region: string
  lat: number
  lon: number
  /** Forecast leads: how sure the level is; null at D0 and for a grid without the field. */
  certainty: CertaintyText | null
  /** `certainty` in a few words for the row ("Firm", "Depends (Watch–Warning)"). */
  certaintyShort: string | null
}

export function rowAt(source: FeedSource, index: number): FeedRow {
  const { grid } = source
  const cell = grid.cells[index]!
  const { lat, lon } = cellCenter(cell)
  const confidence = grid.confidence[index]!
  const certainty = gridCertainty(grid, index)
  return {
    cell,
    level: grid.level[index]!,
    risk: grid.risk[index]!,
    confidence,
    confidenceName: CONFIDENCES[confidence as 0 | 1 | 2] ?? 'Unknown',
    flags: grid.flags?.[index] ?? 0,
    region: regionName(source.region[index]!),
    lat,
    lon,
    certainty,
    certaintyShort: certaintyShort(certainty, grid.levelMin?.[index], grid.levelMax?.[index]),
  }
}

/** The digits of a search text, or '' when it holds none. */
export const searchDigits = (query: string): string => query.replace(/\D/g, '')

/**
 * Whether a cell answers a search: its id contains the digits of the text, or its place, district, state or country
 * contains the text, ignoring case. An empty text answers every cell.
 */
export function matchesSearch(cell: number, query: string, places: Places | null | undefined): boolean {
  const text = query.trim().toLowerCase()
  if (text === '') return true
  const digits = searchDigits(text)
  if (digits !== '' && String(cell).includes(digits)) return true
  const label = places?.lookup(cell)
  if (!label) return false
  return [label.place, label.district, label.state, label.country].some((part) => part?.toLowerCase().includes(text))
}

function comparator(source: FeedSource, sort: Sort): (a: number, b: number) => number {
  const { grid } = source
  const sign = sort.dir === 'asc' ? 1 : -1
  // Highest risk first; a missing risk (NaN) is always last, whichever way the primary sort runs.
  const riskDesc = (a: number, b: number): number => {
    const x = grid.risk[a]!
    const y = grid.risk[b]!
    if (Number.isNaN(x) || Number.isNaN(y)) return Number.isNaN(x) ? (Number.isNaN(y) ? 0 : 1) : -1
    return y - x
  }
  const byCell = (a: number, b: number) => grid.cells[a]! - grid.cells[b]!
  switch (sort.key) {
    case 'level':
      return (a, b) => sign * (grid.level[a]! - grid.level[b]!) || riskDesc(a, b) || byCell(a, b)
    case 'risk':
      return (a, b) => {
        if (Number.isNaN(grid.risk[a]!) || Number.isNaN(grid.risk[b]!)) return riskDesc(a, b) || byCell(a, b)
        return sign * (grid.risk[a]! - grid.risk[b]!) || byCell(a, b)
      }
    case 'confidence':
      return (a, b) => sign * (grid.confidence[a]! - grid.confidence[b]!) || riskDesc(a, b) || byCell(a, b)
    case 'region':
      return (a, b) =>
        sign * regionName(source.region[a]!).localeCompare(regionName(source.region[b]!)) || riskDesc(a, b) || byCell(a, b)
  }
}

/** Grid indices of the cells that pass the filter, in the requested order. */
export function selectFeed(source: FeedSource, filter: FeedFilter, sort: Sort): Uint32Array {
  const { grid } = source
  const picked: number[] = []
  for (let i = 0; i < grid.n; i++) {
    if (!filter.levels[grid.level[i]!]) continue
    if (filter.region !== 'all' && REGION_CODES[source.region[i]!] !== filter.region) continue
    if (!matchesSearch(grid.cells[i]!, filter.query, filter.places)) continue
    if (filter.firmOnly && grid.certainty?.[i] !== CERTAINTY.firm) continue
    picked.push(i)
  }
  const out = Uint32Array.from(picked)
  return out.sort(comparator(source, sort))
}

/** Rows to render for a scroll position: the visible span plus `overscan` rows each side, clamped to the list. */
export function windowRange(
  scrollTop: number,
  viewport: number,
  rowHeight: number,
  count: number,
  overscan = 6,
): { start: number; end: number } {
  const first = Math.floor(Math.max(0, scrollTop) / rowHeight)
  const last = Math.ceil((Math.max(0, scrollTop) + viewport) / rowHeight)
  return { start: Math.max(0, first - overscan), end: Math.min(count, last + overscan) }
}

/** Cells at Watch or above in `next` that were not in `prev`: the alerts a refreshed run added (none across a change of lead). */
export function newAlertCells(prev: Grid | null, next: Grid, followingLatest: boolean): Set<number> {
  const fresh = new Set<number>()
  if (prev === null || prev.lead !== next.lead) return fresh
  const sameDay = prev.date === next.date
  if (!sameDay && !(followingLatest && next.date > prev.date)) return fresh
  const before = new Set<number>()
  for (let i = 0; i < prev.n; i++) if (prev.level[i]! >= 1) before.add(prev.cells[i]!)
  for (let i = 0; i < next.n; i++) {
    if (next.level[i]! >= 1 && !before.has(next.cells[i]!)) fresh.add(next.cells[i]!)
  }
  return fresh
}
