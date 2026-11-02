import { REGION_LABELS, regionOf, type RegionName } from '../scene/geo'
import { cellCenter } from './summary'
import type { ModeResponse, Thresholds } from './types'

/** What the cells of a region are levelled against, and whose figures they are. */
export interface ScopedThresholds {
  thresholds: Thresholds | null
  /** "Western Ghats" or "Himalaya" for a region's own thresholds, "All-India" for the pooled ones. */
  scope: string
}

export const ALL_INDIA = 'All-India'

/**
 * The thresholds the cells of `region` are levelled against: the region's own when the API reports them, else the pooled
 * all-India ones (null when it reports neither).
 */
export function thresholdsFor(mode: Pick<ModeResponse, 'thresholds' | 'thresholds_by_region'> | null | undefined, region: string | null | undefined): ScopedThresholds {
  const own = region ? mode?.thresholds_by_region?.[region] : undefined
  if (own) return { thresholds: own, scope: region! in REGION_LABELS ? REGION_LABELS[region as RegionName] : region! }
  return { thresholds: mode?.thresholds ?? null, scope: ALL_INDIA }
}

/** The Watch threshold of the cell at a point: its region's, else the pooled one; undefined when none is known. */
export function watchAt(mode: Pick<ModeResponse, 'thresholds' | 'thresholds_by_region'> | null | undefined, lat: number, lon: number): number | undefined {
  return thresholdsFor(mode, regionOf(lat, lon)).thresholds?.watch
}

/** `watchAt` for a cell id. */
export function watchForCell(mode: Pick<ModeResponse, 'thresholds' | 'thresholds_by_region'> | null | undefined, cell: number): number | undefined {
  const { lat, lon } = cellCenter(cell)
  return watchAt(mode, lat, lon)
}
