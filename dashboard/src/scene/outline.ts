import type { Outline } from '../data/types'
import { lonLatToWorld, type Window } from './geo'
import type { TerrainField } from './terrainField'

/** How far above the terrain an outline floats, in scene units, so the line never sinks into the relief. */
export const OUTLINE_LIFT = 0.02

/**
 * Height of the terrain surface around a point: the highest of the four vertices whose triangles can hold it
 * (the mesh interpolates between them, so none of them is lower than the surface above the point's own cell).
 */
function surfaceHeight(lon: number, lat: number, window: Window, field: TerrainField): number {
  const col = (lon - window.lon0) / window.step - 0.5
  const row = (lat - window.lat0) / window.step - 0.5
  let top = 0
  for (const i of [Math.floor(row), Math.ceil(row)]) {
    for (const j of [Math.floor(col), Math.ceil(col)]) {
      if (i < 0 || j < 0 || i >= window.rows || j >= window.cols) continue
      top = Math.max(top, field.height[i * window.cols + j]!)
    }
  }
  return top
}

/**
 * Line segments (x, y, z of both ends, six floats each) tracing every ring of a country outline just above the
 * terrain. Rings are closed. A point outside the window ends the line there rather than drawing off the map.
 */
export function outlineSegments(outline: Outline, window: Window, field: TerrainField): Float32Array {
  const out: number[] = []
  const inside = (lon: number, lat: number): boolean =>
    lon >= window.lon0 &&
    lon <= window.lon0 + window.cols * window.step &&
    lat >= window.lat0 &&
    lat <= window.lat0 + window.rows * window.step
  const point = (lon: number, lat: number): [number, number, number] => {
    const { x, z } = lonLatToWorld(lon, lat, window)
    return [x, surfaceHeight(lon, lat, window, field) + OUTLINE_LIFT, z]
  }
  for (const ring of outline.rings) {
    const closed = ring.length > 1 && ring[0]![0] === ring.at(-1)![0] && ring[0]![1] === ring.at(-1)![1]
    const points = closed ? ring : ring.length > 1 ? [...ring, ring[0]!] : []
    for (let n = 1; n < points.length; n++) {
      const [lon0, lat0] = points[n - 1]!
      const [lon1, lat1] = points[n]!
      if (!inside(lon0, lat0) || !inside(lon1, lat1)) continue
      out.push(...point(lon0, lat0), ...point(lon1, lat1))
    }
  }
  return Float32Array.from(out)
}
