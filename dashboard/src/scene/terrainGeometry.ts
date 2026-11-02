import { BufferAttribute, BufferGeometry } from 'three'
import type { Terrain } from '../data/types'
import { buildTerrainField, type TerrainField } from './terrainField'

export { METRES_PER_DEGREE, VERTICAL_EXAGGERATION } from './terrainField'

export interface TerrainGeometry {
  geometry: BufferGeometry
  /** Highest elevation in metres, used to normalise the contour reveal. */
  maxElevation: number
  /** Scene-space extent of the domain (x = longitude span, z = latitude span). */
  extent: { width: number; depth: number }
}

/**
 * Build one indexed mesh for the whole window. A quad is drawn when any of its four samples is land, so a
 * one-cell island still gets triangles; the sea samples of such a quad sit at height 0 and the shader cuts
 * the mesh at the coast where the interpolated `aLand` (1 land, 0 sea) crosses one half. Every vertex also
 * carries its true elevation in metres (`aElev`, -1 for sea) so the shader can draw contours, its distance
 * from the window border (`aEdge`) so the border feathers out instead of ending in a hard cut, and how
 * mountainous it is (`aProm`) so low-relief plains can recede.
 * x is longitude minus the window centre, z is the negated latitude offset, so north points away.
 */
export function buildTerrainGeometry(terrain: Terrain, field: TerrainField = buildTerrainField(terrain)): TerrainGeometry {
  const { rows, cols, step } = terrain
  const count = rows * cols
  const position = new Float32Array(count * 3)
  const normal = new Float32Array(count * 3)
  const uv = new Float32Array(count * 2)
  const cx = ((cols - 1) * step) / 2
  const cz = ((rows - 1) * step) / 2

  for (let i = 0; i < rows; i++) {
    for (let j = 0; j < cols; j++) {
      const k = i * cols + j
      position[3 * k] = j * step - cx
      position[3 * k + 1] = field.height[k]!
      position[3 * k + 2] = -(i * step - cz)
      uv[2 * k] = (j + 0.5) / cols
      uv[2 * k + 1] = (i + 0.5) / rows
    }
  }

  const heightAt = (i: number, j: number, fallback: number): number => {
    const ci = Math.min(rows - 1, Math.max(0, i))
    const cj = Math.min(cols - 1, Math.max(0, j))
    const k = ci * cols + cj
    return field.metres[k]! < 0 ? fallback : field.height[k]!
  }

  for (let i = 0; i < rows; i++) {
    for (let j = 0; j < cols; j++) {
      const k = i * cols + j
      const y = field.height[k]!
      const dx = (heightAt(i, j + 1, y) - heightAt(i, j - 1, y)) / (2 * step)
      const dLat = (heightAt(i + 1, j, y) - heightAt(i - 1, j, y)) / (2 * step)
      const len = Math.hypot(dx, 1, dLat)
      normal[3 * k] = -dx / len
      normal[3 * k + 1] = 1 / len
      normal[3 * k + 2] = dLat / len
    }
  }

  const index = new Uint32Array((rows - 1) * (cols - 1) * 6)
  let n = 0
  for (let i = 0; i < rows - 1; i++) {
    for (let j = 0; j < cols - 1; j++) {
      const a = i * cols + j
      const b = a + 1
      const c = a + cols
      const d = c + 1
      if (field.metres[a]! < 0 && field.metres[b]! < 0 && field.metres[c]! < 0 && field.metres[d]! < 0) continue
      // Counter-clockwise seen from above (+y); z points south, so row i+1 (c, d) is further away.
      index[n++] = a
      index[n++] = b
      index[n++] = c
      index[n++] = b
      index[n++] = d
      index[n++] = c
    }
  }

  const geometry = new BufferGeometry()
  geometry.setAttribute('position', new BufferAttribute(position, 3))
  geometry.setAttribute('normal', new BufferAttribute(normal, 3))
  geometry.setAttribute('uv', new BufferAttribute(uv, 2))
  geometry.setAttribute('aElev', new BufferAttribute(field.metres, 1))
  geometry.setAttribute('aEdge', new BufferAttribute(field.edge, 1))
  geometry.setAttribute('aProm', new BufferAttribute(field.prominence, 1))
  geometry.setAttribute('aLand', new BufferAttribute(Float32Array.from(field.metres, (m) => (m < 0 ? 0 : 1)), 1))
  geometry.setIndex(new BufferAttribute(index.subarray(0, n), 1))
  geometry.computeBoundingSphere()

  return {
    geometry,
    maxElevation: field.maxElevation,
    extent: { width: (cols - 1) * step, depth: (rows - 1) * step },
  }
}
