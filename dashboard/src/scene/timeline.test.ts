import { describe, expect, it } from 'vitest'
import { Float32BufferAttribute } from 'three'
import { decodeBasemap } from '../data/api'
import { basemapPayload, bytesToBase64, f16BitsToBase64 } from '../test/fixtures'
import { buildTerrainGeometry } from './terrainGeometry'
import { CHROME_AT, INTRO_DURATION, introFrame, letterProgress, REST_FRAME } from './timeline'

describe('introFrame', () => {
  it('starts dark and ends at rest', () => {
    const start = introFrame(0)
    expect(start.reveal).toBe(0)
    expect(start.fill).toBe(0)
    expect(start.dive).toBe(0)
    expect(start.wordmark).toBe(0)
    expect(start.chrome).toBe(false)
    expect(introFrame(INTRO_DURATION)).toEqual(REST_FRAME)
  })

  it('orders the beats: contours, wordmark, fill and dive, chrome last', () => {
    expect(introFrame(0.8).reveal).toBeGreaterThan(0)
    expect(introFrame(0.8).wordmark).toBe(0)
    expect(introFrame(2.5).wordmark).toBeGreaterThan(0.5)
    expect(introFrame(2.5).fill).toBe(0)
    expect(introFrame(4.0).fill).toBe(1)
    expect(introFrame(4.0).dive).toBeGreaterThan(0.5)
    expect(introFrame(CHROME_AT - 0.01).chrome).toBe(false)
    expect(introFrame(CHROME_AT).chrome).toBe(true)
  })

  it('never moves backwards', () => {
    let prev = introFrame(0)
    for (let t = 0.05; t < INTRO_DURATION; t += 0.05) {
      const f = introFrame(t)
      expect(f.reveal).toBeGreaterThanOrEqual(prev.reveal)
      expect(f.fill).toBeGreaterThanOrEqual(prev.fill)
      expect(f.dive).toBeGreaterThanOrEqual(prev.dive)
      expect(f.wordmark).toBeGreaterThanOrEqual(prev.wordmark)
      prev = f
    }
  })
})

describe('letterProgress', () => {
  it('staggers letters left to right and completes them all', () => {
    expect(letterProgress(0, 0, 11)).toBe(0)
    expect(letterProgress(0.5, 0, 11)).toBeGreaterThan(letterProgress(0.5, 10, 11))
    for (let i = 0; i < 11; i++) expect(letterProgress(1, i, 11)).toBe(1)
  })
})

describe('buildTerrainGeometry', () => {
  it('records elevation in metres and marks which vertices are land', () => {
    const { geometry, maxElevation, extent } = buildTerrainGeometry(decodeBasemap(basemapPayload))
    expect(maxElevation).toBe(100)
    expect(extent.width).toBeCloseTo(0.05, 9)
    expect(geometry.getAttribute('position').count).toBe(4)
    const elev = geometry.getAttribute('aElev') as Float32BufferAttribute
    expect(Array.from(elev.array)).toEqual([0, 100, 1, -1])
    const land = geometry.getAttribute('aLand') as Float32BufferAttribute
    expect(Array.from(land.array)).toEqual([1, 1, 1, 0])
  })

  it('draws a coastal quad (the shader cuts it at the coast) but no quad of only sea', () => {
    const coastal = buildTerrainGeometry(decodeBasemap(basemapPayload)).geometry
    expect(coastal.getIndex()!.count).toBe(6)
    const open = decodeBasemap({ ...basemapPayload, mask: bytesToBase64(new Uint8Array(4)) })
    expect(buildTerrainGeometry(open).geometry.getIndex()!.count).toBe(0)
  })

  it('keeps a one-cell island: the quads around its single land vertex are drawn', () => {
    const island = decodeBasemap({
      ...basemapPayload,
      rows: 3,
      cols: 3,
      elev: f16BitsToBase64(new Array<number>(9).fill(0x5640)),
      mask: bytesToBase64(new Uint8Array([0, 0, 0, 0, 1, 0, 0, 0, 0])),
    })
    const { geometry } = buildTerrainGeometry(island)
    expect(geometry.getIndex()!.count).toBe(4 * 6)
    expect(Array.from((geometry.getAttribute('aLand') as Float32BufferAttribute).array)).toEqual([0, 0, 0, 0, 1, 0, 0, 0, 0])
  })

  it('triangulates fully valid terrain with upward-facing triangles', () => {
    const terrain = {
      rows: 3,
      cols: 3,
      lat0: 8,
      lon0: 72,
      step: 0.05,
      elev: new Float32Array([0, 10, 20, 30, 40, 50, 60, 70, 80]),
    }
    const { geometry } = buildTerrainGeometry(terrain)
    expect(geometry.getIndex()!.count).toBe(2 * 2 * 6)
    const pos = geometry.getAttribute('position')
    const idx = geometry.getIndex()!
    const v = (i: number) => [pos.getX(idx.getX(i)), pos.getY(idx.getX(i)), pos.getZ(idx.getX(i))] as const
    const [a, b, c] = [v(0), v(1), v(2)]
    const e1 = [b[0] - a[0], b[1] - a[1], b[2] - a[2]] as const
    const e2 = [c[0] - a[0], c[1] - a[1], c[2] - a[2]] as const
    const ny = e1[2] * e2[0] - e1[0] * e2[2]
    expect(ny).toBeGreaterThan(0)
    const normal = geometry.getAttribute('normal')
    expect(normal.getY(4)).toBeGreaterThan(0)
  })
})
