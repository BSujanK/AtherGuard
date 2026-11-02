import { cellCenter } from '../data/summary'
import type { Grid } from '../data/types'
import { cellToTexel, type RegionFilter, regionOf, type Window } from './geo'
import { LEVEL_ALPHA, LEVEL_RGB } from './levelColors'

export interface MapFilter {
  /** Which risk levels (index = level code) are shown. */
  levels: readonly boolean[]
  region: RegionFilter
}

export const ALL_LEVELS: readonly boolean[] = [true, true, true, true]

/** 1 for each grid cell that passes the level and region filters, 0 otherwise. */
export function visibleCells(grid: Grid, filter: MapFilter): Uint8Array {
  const out = new Uint8Array(grid.n)
  for (let i = 0; i < grid.n; i++) {
    if (!filter.levels[grid.level[i]!]) continue
    if (filter.region !== 'all') {
      const { lat, lon } = cellCenter(grid.cells[i]!)
      if (regionOf(lat, lon) !== filter.region) continue
    }
    out[i] = 1
  }
  return out
}

/**
 * RGBA8 heat map of the grid over a window, one texel per cell and row 0 southernmost, ready to be
 * uploaded as a DataTexture. Level colours are the palette's; texels without a visible cell stay
 * fully transparent. Cells outside the window are skipped.
 */
export function buildRiskTexels(grid: Grid, window: Window, visible: Uint8Array, into?: Uint8Array): Uint8Array {
  const size = window.rows * window.cols * 4
  const data = into && into.length === size ? into.fill(0) : new Uint8Array(size)
  for (let i = 0; i < grid.n; i++) {
    if (!visible[i]) continue
    const texel = cellToTexel(grid.cells[i]!, window)
    if (texel < 0) continue
    const level = grid.level[i]!
    const [r, g, b] = LEVEL_RGB[level]!
    data[4 * texel] = r
    data[4 * texel + 1] = g
    data[4 * texel + 2] = b
    data[4 * texel + 3] = LEVEL_ALPHA[level]!
  }
  return data
}

/** Index of a cell id in the grid's sorted `cells` array, or -1 when the grid does not hold it. */
export function findCell(grid: Grid, id: number): number {
  let lo = 0
  let hi = grid.n - 1
  while (lo <= hi) {
    const mid = (lo + hi) >>> 1
    const value = grid.cells[mid]!
    if (value === id) return mid
    if (value < id) lo = mid + 1
    else hi = mid - 1
  }
  return -1
}
