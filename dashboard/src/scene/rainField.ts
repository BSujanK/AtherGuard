import type { Rain } from '../data/types'
import { latLonToTexel, texelWorld, type Window } from './geo'
import type { TerrainField } from './terrainField'

/** Daily rain (mm) at which a coarse bin is fully dense, and the drops a fully dense bin gets. */
export const RAIN_FULL_MM = 60
export const DROPS_PER_FULL_BIN = 16
/** Rain below this is not drawn: a trace is not a shower. */
export const RAIN_MIN_MM = 1
/** Upper bound of drops ever built; the quality step draws a prefix of them. */
export const MAX_DROPS = 8000

export interface RainDrops {
  count: number
  /** x, z, falling phase 0..1 and ground height per drop, 4 floats each, in a shuffled order so any prefix is an even sample. */
  data: Float32Array
}

/** Deterministic pseudo-random sequence so the same rain looks the same on every load. */
function seeded(seed: number): () => number {
  let s = seed >>> 0
  return () => {
    s = (s + 0x6d2b79f5) >>> 0
    let t = s
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

/**
 * Drops for the day's rain: each coarse bin gets a number of drops proportional to its rain, placed
 * at random inside the bin on the terrain surface. Bins with no data or trace rain get none, so a
 * dry day is an empty sky. Returns no drops when the field does not overlap the terrain window.
 */
export function buildRainDrops(rain: Rain, window: Window, field: TerrainField, seed = 17): RainDrops {
  const rand = seeded(seed)
  const drops: number[] = []
  for (let r = 0; r < rain.rows && drops.length / 4 < MAX_DROPS; r++) {
    for (let c = 0; c < rain.cols; c++) {
      const mm = rain.rain[r * rain.cols + c]!
      if (!Number.isFinite(mm) || mm < RAIN_MIN_MM) continue
      const n = Math.round(Math.min(1.5, mm / RAIN_FULL_MM) * DROPS_PER_FULL_BIN)
      for (let d = 0; d < n; d++) {
        const lat = rain.lat0 + (r + rand()) * rain.step
        const lon = rain.lon0 + (c + rand()) * rain.step
        const texel = latLonToTexel(lat, lon, window)
        if (texel === null || field.metres[texel]! < 0) continue
        const { x, z } = texelWorld(texel, window)
        drops.push(x, z, rand(), field.height[texel]!)
      }
    }
  }

  const count = Math.min(MAX_DROPS, drops.length / 4)
  const order = Array.from({ length: count }, (_, i) => i)
  for (let i = count - 1; i > 0; i--) {
    const j = Math.floor(rand() * (i + 1))
    ;[order[i], order[j]] = [order[j]!, order[i]!]
  }
  const data = new Float32Array(count * 4)
  order.forEach((from, to) => data.set(drops.slice(from * 4, from * 4 + 4), to * 4))
  return { count, data }
}
