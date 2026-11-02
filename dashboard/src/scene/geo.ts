import { GRID_COLS, GRID_ORIGIN } from '../data/summary'

/**
 * Cell ids are `lat_index * 10000 + lon_index` on the global 0.05 degree grid (aetherguard/grid.py:
 * ID_STRIDE, origin -90/-180). The terrain grid is a window of that grid, one sample per cell, so a
 * cell maps to texel (row, col) = (lat_index - row0, lon_index - col0) with no resampling.
 */

export interface Window {
  rows: number
  cols: number
  lat0: number
  lon0: number
  step: number
}

/** Index offsets of a window's first sample on the global grid. */
function offsets(w: Window): { row0: number; col0: number } {
  return {
    row0: Math.round((w.lat0 - GRID_ORIGIN.lat0) / GRID_ORIGIN.step),
    col0: Math.round((w.lon0 - GRID_ORIGIN.lon0) / GRID_ORIGIN.step),
  }
}

/** Row-major texel index of a cell in the window, or -1 when the cell lies outside it. */
export function cellToTexel(id: number, w: Window): number {
  const { row0, col0 } = offsets(w)
  const row = Math.floor(id / GRID_COLS) - row0
  const col = (id % GRID_COLS) - col0
  if (row < 0 || row >= w.rows || col < 0 || col >= w.cols) return -1
  return row * w.cols + col
}

/** Inverse of `cellToTexel`. */
export function texelToCell(index: number, w: Window): number {
  const { row0, col0 } = offsets(w)
  const row = Math.floor(index / w.cols)
  const col = index % w.cols
  return (row0 + row) * GRID_COLS + col0 + col
}

/** Window index (row, col) of a point, or null outside the window. A point belongs to the cell containing it. */
export function latLonToTexel(lat: number, lon: number, w: Window): number | null {
  const row = Math.floor(Math.round(((lat - w.lat0) / w.step) * 1e6) / 1e6)
  const col = Math.floor(Math.round(((lon - w.lon0) / w.step) * 1e6) / 1e6)
  if (row < 0 || row >= w.rows || col < 0 || col >= w.cols) return null
  return row * w.cols + col
}

/**
 * Scene space is degrees: x is longitude from the window centre, z is the negated latitude offset
 * (north points away from the viewer), matching the terrain mesh. A cell sits on its terrain vertex.
 */
export function texelWorld(index: number, w: Window): { x: number; z: number } {
  const row = Math.floor(index / w.cols)
  const col = index % w.cols
  return {
    x: col * w.step - ((w.cols - 1) * w.step) / 2,
    z: -(row * w.step - ((w.rows - 1) * w.step) / 2),
  }
}

/**
 * Scene-space (x, z) of a longitude and latitude: the same plane as `texelWorld`, but for any point rather
 * than a cell centre, so outlines and cells line up exactly.
 */
export function lonLatToWorld(lon: number, lat: number, w: Window): { x: number; z: number } {
  return { x: lon - w.lon0 - (w.cols * w.step) / 2, z: -(lat - w.lat0 - (w.rows * w.step) / 2) }
}

/** The window index whose vertex is nearest to a scene-space point, or -1 outside the window. */
export function worldToTexel(x: number, z: number, w: Window): number {
  const col = Math.round((x + ((w.cols - 1) * w.step) / 2) / w.step)
  const row = Math.round((-z + ((w.rows - 1) * w.step) / 2) / w.step)
  if (row < 0 || row >= w.rows || col < 0 || col >= w.cols) return -1
  return row * w.cols + col
}

/** Region boxes, mirrored from configs/domain.yaml (read by aetherguard.grid.region_labels). */
export const REGION_BOXES = {
  himalaya: { latMin: 22, latMax: 36, lonMin: 72, lonMax: 98 },
  western_ghats: { latMin: 8, latMax: 21.5, lonMin: 72.5, lonMax: 78.5 },
} as const

export type RegionName = keyof typeof REGION_BOXES
export type RegionFilter = 'all' | RegionName

export const REGION_LABELS: Record<RegionFilter, string> = {
  all: 'All',
  himalaya: 'Himalaya',
  western_ghats: 'Western Ghats',
}

/** The region whose box holds the point (lower bound inclusive, upper exclusive, as in the backend), or null. */
export function regionOf(lat: number, lon: number): RegionName | null {
  for (const name of Object.keys(REGION_BOXES) as RegionName[]) {
    const b = REGION_BOXES[name]
    if (lat >= b.latMin && lat < b.latMax && lon >= b.lonMin && lon < b.lonMax) return name
  }
  return null
}
