import type { Grid } from '../../data/types'
import { MIN_ALERT_LEVEL } from '../../scene/columns'

export interface TopAlert {
  cell: number
  level: number
  risk: number
  confidence: number
  /** The cell's `GRID_FLAG` bits; 0 for a grid without them. */
  flags: number
}

/** The `limit` highest alerts among the visible cells: highest level first, then highest risk. */
export function topAlerts(grid: Grid, visible: Uint8Array, limit: number): TopAlert[] {
  const picked: number[] = []
  for (let i = 0; i < grid.n; i++) {
    if (visible[i] && grid.level[i]! >= MIN_ALERT_LEVEL) picked.push(i)
  }
  picked.sort((a, b) => grid.level[b]! - grid.level[a]! || grid.risk[b]! - grid.risk[a]! || grid.cells[a]! - grid.cells[b]!)
  return picked.slice(0, limit).map((i) => ({
    cell: grid.cells[i]!,
    level: grid.level[i]!,
    risk: grid.risk[i]!,
    confidence: grid.confidence[i]!,
    flags: grid.flags?.[i] ?? 0,
  }))
}

/** How many visible cells are at Watch or above. */
export function alertCount(grid: Grid, visible: Uint8Array): number {
  let n = 0
  for (let i = 0; i < grid.n; i++) if (visible[i] && grid.level[i]! >= MIN_ALERT_LEVEL) n++
  return n
}
