import { texelToCell, worldToTexel, type Window } from './geo'
import type { TerrainField } from './terrainField'

export interface Ray {
  origin: readonly [number, number, number]
  direction: readonly [number, number, number]
}

export interface Pick {
  /** Window index of the vertex the ray lands on. */
  texel: number
  /** Global cell id. */
  cell: number
  point: readonly [number, number, number]
}

const BISECTIONS = 10
const MAX_STEPS = 5000

/** Parametric range of the ray inside the axis-aligned box, or null when it misses. */
function intersectBox(
  ray: Ray,
  min: readonly [number, number, number],
  max: readonly [number, number, number],
): [number, number] | null {
  let t0 = 0
  let t1 = Infinity
  for (let a = 0; a < 3; a++) {
    const o = ray.origin[a]!
    const d = ray.direction[a]!
    if (Math.abs(d) < 1e-12) {
      if (o < min[a]! || o > max[a]!) return null
      continue
    }
    let near = (min[a]! - o) / d
    let far = (max[a]! - o) / d
    if (near > far) [near, far] = [far, near]
    t0 = Math.max(t0, near)
    t1 = Math.min(t1, far)
    if (t0 > t1) return null
  }
  return [t0, t1]
}

/**
 * First point where a ray meets the terrain surface, found by marching the height field (no mesh
 * raycast: the mesh has hundreds of thousands of triangles). Samples without data are not surface.
 * Returns null when the ray misses the land.
 */
export function pickTerrain(ray: Ray, window: Window, field: TerrainField): Pick | null {
  const halfX = ((window.cols - 1) * window.step) / 2
  const halfZ = ((window.rows - 1) * window.step) / 2
  let top = 0
  for (let k = 0; k < field.height.length; k++) if (field.height[k]! > top) top = field.height[k]!
  const range = intersectBox(ray, [-halfX, 0, -halfZ], [halfX, top, halfZ])
  if (!range) return null
  const [tMin, tMax] = range

  const surface = (t: number): { texel: number; below: boolean } => {
    const x = ray.origin[0] + ray.direction[0] * t
    const y = ray.origin[1] + ray.direction[1] * t
    const z = ray.origin[2] + ray.direction[2] * t
    const texel = worldToTexel(x, z, window)
    if (texel < 0 || field.metres[texel]! < 0) return { texel: -1, below: false }
    return { texel, below: y <= field.height[texel]! }
  }

  const horizontal = Math.hypot(ray.direction[0], ray.direction[2])
  const dt = Math.max(window.step * 0.5, (window.step * 0.5) / Math.max(horizontal, 0.05))
  let previous = tMin
  let n = 0
  for (let t = tMin; t <= tMax && n < MAX_STEPS; t += dt, n++) {
    if (surface(t).below) {
      let lo = previous
      let hi = t
      for (let b = 0; b < BISECTIONS; b++) {
        const mid = (lo + hi) / 2
        if (surface(mid).below) hi = mid
        else lo = mid
      }
      const hit = surface(hi)
      if (hit.texel < 0) return null
      return {
        texel: hit.texel,
        cell: texelToCell(hit.texel, window),
        point: [
          ray.origin[0] + ray.direction[0] * hi,
          ray.origin[1] + ray.direction[1] * hi,
          ray.origin[2] + ray.direction[2] * hi,
        ],
      }
    }
    previous = t
  }
  return null
}
