import type { Grid } from '../data/types'
import { cellToTexel, texelWorld, type Window } from './geo'
import type { TerrainField } from './terrainField'

/** Column footprint as a share of the cell size, and the height range (scene units) a column can take. */
export const COLUMN_WIDTH = 1.1
export const COLUMN_MIN_HEIGHT = 0.12
export const COLUMN_MAX_HEIGHT = 1.4
/** Watch and above is an alert: the lists count them even where the map shows only some as columns. */
export const MIN_ALERT_LEVEL = 1
/**
 * Columns stand for Warning and Emergency; Watch is a tint on the terrain. With 15,000 Watch cells a column
 * for each would drown the map, so Watch columns are opt-in.
 */
export const MIN_COLUMN_LEVEL = 2
export const MIN_COLUMN_LEVEL_WITH_WATCH = MIN_ALERT_LEVEL

export const columnMinLevel = (watchColumns: boolean): number =>
  watchColumns ? MIN_COLUMN_LEVEL_WITH_WATCH : MIN_COLUMN_LEVEL

export interface ColumnInstances {
  count: number
  /** Column-major 4x4 matrices, 16 floats per instance (scale w,h,w; translation to the terrain). */
  matrices: Float32Array
  /** Level code per instance (1..3), for colour and the Emergency pulse. */
  levels: Float32Array
  /** Grid index each instance was built from, to map back to a cell. */
  source: Uint32Array
  /** Highest risk among the columns; heights are relative to it. */
  maxRisk: number
}

/** Height of a column: linear in risk relative to the highest risk shown, never shorter than the minimum. */
export function columnHeight(risk: number, maxRisk: number): number {
  const share = maxRisk > 0 ? Math.min(1, Math.max(0, risk / maxRisk)) : 0
  return COLUMN_MIN_HEIGHT + (COLUMN_MAX_HEIGHT - COLUMN_MIN_HEIGHT) * share
}

/**
 * Instance data for every visible alert cell at or above `minLevel`, so all columns are drawn by one
 * instanced mesh. Columns stand on the terrain surface; cells outside the terrain window are skipped.
 */
export function buildColumns(
  grid: Grid,
  window: Window,
  field: TerrainField,
  visible: Uint8Array,
  minLevel: number = MIN_COLUMN_LEVEL,
): ColumnInstances {
  const picked: number[] = []
  let maxRisk = 0
  for (let i = 0; i < grid.n; i++) {
    if (!visible[i] || grid.level[i]! < minLevel) continue
    if (cellToTexel(grid.cells[i]!, window) < 0) continue
    picked.push(i)
    if (grid.risk[i]! > maxRisk) maxRisk = grid.risk[i]!
  }

  const count = picked.length
  const matrices = new Float32Array(count * 16)
  const levels = new Float32Array(count)
  const source = new Uint32Array(count)
  const width = window.step * COLUMN_WIDTH
  for (let n = 0; n < count; n++) {
    const i = picked[n]!
    const texel = cellToTexel(grid.cells[i]!, window)
    const { x, z } = texelWorld(texel, window)
    const base = 16 * n
    matrices[base] = width
    matrices[base + 5] = columnHeight(grid.risk[i]!, maxRisk)
    matrices[base + 10] = width
    matrices[base + 12] = x
    matrices[base + 13] = field.height[texel]!
    matrices[base + 14] = z
    matrices[base + 15] = 1
    levels[n] = grid.level[i]!
    source[n] = i
  }
  return { count, matrices, levels, source, maxRisk }
}
