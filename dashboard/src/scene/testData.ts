import type { Grid, Terrain } from '../data/types'
import { GRID_COLS } from '../data/summary'

/** The real base map window: lat 6-37.5, lon 68-98 at 0.05 degrees (what `/api/basemap` serves). */
export const REAL_WINDOW = { rows: 630, cols: 600, lat0: 6, lon0: 68, step: 0.05 }

/** First cell of the real window on the global grid (row 1920, column 4960). */
export const WINDOW_ORIGIN_CELL = 1920 * GRID_COLS + 4960

/** A flat terrain of the given size at the real window origin, `metres` high everywhere. */
export function flatTerrain(rows: number, cols: number, metres = 100): Terrain {
  return { rows, cols, lat0: 6, lon0: 68, step: 0.05, elev: new Float32Array(rows * cols).fill(metres) }
}

/** A grid of cells (row, col offsets from the window origin) with levels cycling through `levelOf`. */
export function makeGrid(
  cells: readonly { row: number; col: number }[],
  levelOf: (i: number) => number,
  riskOf: (i: number) => number = (i) => 0.001 * (i + 1),
): Grid {
  const ids = cells.map((c) => WINDOW_ORIGIN_CELL + c.row * GRID_COLS + c.col).sort((a, b) => a - b)
  return {
    date: '2024-08-05',
    lead: 0,
    n: ids.length,
    cells: Uint32Array.from(ids),
    risk: Float32Array.from(ids.map((_, i) => riskOf(i))),
    level: Uint8Array.from(ids.map((_, i) => levelOf(i))),
    confidence: new Uint8Array(ids.length),
    lat0: -90,
    lon0: -180,
    step: 0.05,
  }
}
