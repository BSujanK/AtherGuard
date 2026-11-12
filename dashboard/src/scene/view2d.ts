import { MASK } from '../data/types'
import { REGION_BOXES, type RegionFilter, texelWorld, type Window } from './geo'
import { hexToRgb, mixHex, PALETTE } from './levelColors'
import type { TerrainField } from './terrainField'

/** The 2D fallback's viewport: the scene point at the canvas centre and pixels per scene unit. */
export interface View2D {
  cx: number
  cz: number
  scale: number
}

export interface Box {
  xMin: number
  xMax: number
  zMin: number
  zMax: number
}

export const MIN_SCALE = 4
export const MAX_SCALE = 400

const clampScale = (s: number): number => Math.min(MAX_SCALE, Math.max(MIN_SCALE, s))

/** The view that fits `box` inside a canvas of the given size with a margin. */
export function fitView(box: Box, width: number, height: number, margin = 0.94): View2D {
  const scale = Math.min((width * margin) / (box.xMax - box.xMin), (height * margin) / (box.zMax - box.zMin))
  return { cx: (box.xMin + box.xMax) / 2, cz: (box.zMin + box.zMax) / 2, scale: clampScale(scale) }
}

export function worldToScreen(v: View2D, width: number, height: number, x: number, z: number): [number, number] {
  return [width / 2 + (x - v.cx) * v.scale, height / 2 + (z - v.cz) * v.scale]
}

export function screenToWorld(v: View2D, width: number, height: number, sx: number, sy: number): [number, number] {
  return [v.cx + (sx - width / 2) / v.scale, v.cz + (sy - height / 2) / v.scale]
}

/** Zoom by `factor` keeping the scene point under (sx, sy) where it is. */
export function zoomAt(v: View2D, width: number, height: number, sx: number, sy: number, factor: number): View2D {
  const [wx, wz] = screenToWorld(v, width, height, sx, sy)
  const scale = clampScale(v.scale * factor)
  return { scale, cx: wx - (sx - width / 2) / scale, cz: wz - (sy - height / 2) / scale }
}

/** Scene-space box of the whole window, or of a region's box clipped to it. */
export function regionView(region: RegionFilter, window: Window): Box {
  const last = window.rows * window.cols - 1
  const sw = texelWorld(0, window)
  const ne = texelWorld(last, window)
  const half = window.step / 2
  const full: Box = { xMin: sw.x - half, xMax: ne.x + half, zMin: ne.z - half, zMax: sw.z + half }
  if (region === 'all') return full
  const b = REGION_BOXES[region]
  const row = (lat: number) => Math.min(window.rows - 1, Math.max(0, Math.floor((lat - window.lat0) / window.step)))
  const col = (lon: number) => Math.min(window.cols - 1, Math.max(0, Math.floor((lon - window.lon0) / window.step)))
  const a = texelWorld(row(b.latMin) * window.cols + col(b.lonMin), window)
  const c = texelWorld(row(b.latMax) * window.cols + col(b.lonMax), window)
  return { xMin: a.x - half, xMax: c.x + half, zMin: c.z - half, zMax: a.z + half }
}

const INK = hexToRgb(PALETTE.ink)
const CYAN = hexToRgb(PALETTE.cyan)
const LOW = hexToRgb(mixHex(PALETTE.ink, PALETTE.blue, 0.16))
const MID = hexToRgb(mixHex(PALETTE.ink, PALETTE.blue, 0.55))
const HIGH = hexToRgb(mixHex(PALETTE.blue, PALETTE.cyan, 0.4))
/** Neighbouring countries are drawn this far toward ink; the coastline gets this much cyan. */
const OTHER_LAND_DIM = 0.72
const COAST_CYAN = 0.38
/** Light from the north-west, the same as the 3D terrain shader. */
const LIGHT = (() => {
  const v = [-0.55, 0.62, -0.5]
  const len = Math.hypot(...v)
  return v.map((c) => c / len) as [number, number, number]
})()

const smoothstep = (lo: number, hi: number, x: number): number => {
  const t = Math.min(1, Math.max(0, (x - lo) / (hi - lo)))
  return t * t * (3 - 2 * t)
}
const mix = (a: number, b: number, t: number): number => a + (b - a) * t

/**
 * Shaded relief of the terrain as RGBA8, north at the top: the 3D shader's hypsometric ramp, flat light on
 * plains, a faint cyan coastline, land of other countries (`mask` 4) very dim, and the border feathered
 * into the background.
 */
export function shadeTerrain(field: TerrainField, mask?: Uint8Array): Uint8ClampedArray {
  const { rows, cols, step, height, metres, edge, prominence, maxElevation } = field
  const out = new Uint8ClampedArray(rows * cols * 4)
  const hAt = (i: number, j: number, fallback: number): number => {
    const k = Math.min(rows - 1, Math.max(0, i)) * cols + Math.min(cols - 1, Math.max(0, j))
    return metres[k]! < 0 ? fallback : height[k]!
  }
  const seaAt = (i: number, j: number): boolean => i >= 0 && j >= 0 && i < rows && j < cols && metres[i * cols + j]! < 0
  for (let i = 0; i < rows; i++) {
    for (let j = 0; j < cols; j++) {
      const k = i * cols + j
      const o = 4 * ((rows - 1 - i) * cols + j)
      out[o + 3] = 255
      if (metres[k]! < 0) {
        out[o] = INK[0]
        out[o + 1] = INK[1]
        out[o + 2] = INK[2]
        continue
      }
      const coast = seaAt(i - 1, j) || seaAt(i + 1, j) || seaAt(i, j - 1) || seaAt(i, j + 1)
      const other = mask?.[k] === MASK.other
      const y = height[k]!
      const dx = (hAt(i, j + 1, y) - hAt(i, j - 1, y)) / (2 * step)
      const dLat = (hAt(i + 1, j, y) - hAt(i - 1, j, y)) / (2 * step)
      const len = Math.hypot(dx, 1, dLat)
      const nx = -dx / len
      const ny = 1 / len
      const nz = dLat / len
      const mountain = prominence[k]!
      let lambert = Math.min(1, Math.max(0, nx * LIGHT[0] + ny * LIGHT[1] + nz * LIGHT[2]))
      lambert = mix(0.55, lambert, mix(0.35, 1, mountain))
      const h = Math.sqrt(Math.min(1, metres[k]! / Math.max(maxElevation, 1)))
      const toMid = smoothstep(0, 0.45, h)
      const toHigh = smoothstep(0.55, 1, h) * 0.6
      const gain = 0.42 + 1.05 * lambert
      for (let c = 0; c < 3; c++) {
        let ramp = mix(LOW[c]!, MID[c]!, toMid)
        ramp = mix(ramp, HIGH[c]!, toHigh)
        ramp = mix(mix(INK[c]!, ramp, 0.55), ramp, mountain)
        let shaded = ramp * gain
        if (other) shaded = mix(shaded, INK[c]!, OTHER_LAND_DIM)
        if (coast) shaded = mix(shaded, CYAN[c]!, COAST_CYAN)
        out[o + c] = INK[c]! + (shaded - INK[c]!) * edge[k]!
      }
    }
  }
  return out
}

/** Flip a south-first RGBA texel array to north-first, for drawing into a canvas. */
export function flipRows(data: Uint8Array, rows: number, cols: number): Uint8ClampedArray {
  const out = new Uint8ClampedArray(data.length)
  const stride = cols * 4
  for (let i = 0; i < rows; i++) out.set(data.subarray(i * stride, (i + 1) * stride), (rows - 1 - i) * stride)
  return out
}
