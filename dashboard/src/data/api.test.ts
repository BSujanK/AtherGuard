import { describe, expect, it } from 'vitest'
import {
  bytesToBase64,
  f16BitsToBase64,
  f32ToBase64,
  gridPayload,
  placesPayload,
  u16ToBase64,
  basemapPayload,
  u32ToBase64,
} from '../test/fixtures'
import {
  countCodes,
  decodeFloat16,
  decodeFloat32,
  decodeGrid,
  decodePlaces,
  decodeBasemap,
  decodeUint32,
  decodeUint8,
  float16ToNumber,
  parseLeads,
} from './api'
import { cellCenter } from './summary'
import { GRID_FLAG } from './types'

describe('base64 typed array decoders', () => {
  it('decodes float32 little endian', () => {
    const out = decodeFloat32(f32ToBase64([0, 0.5, -1.25, 1e6]))
    expect(out).toBeInstanceOf(Float32Array)
    expect(Array.from(out)).toEqual([0, 0.5, -1.25, 1e6])
  })

  it('decodes uint32 including values above 2^31', () => {
    const out = decodeUint32(u32ToBase64([0, 1, 4_000_000_000]))
    expect(out).toBeInstanceOf(Uint32Array)
    expect(Array.from(out)).toEqual([0, 1, 4_000_000_000])
  })

  it('decodes uint8', () => {
    const out = decodeUint8(bytesToBase64(new Uint8Array([0, 1, 2, 255])))
    expect(out).toBeInstanceOf(Uint8Array)
    expect(Array.from(out)).toEqual([0, 1, 2, 255])
  })

  it('rejects a length that is not a whole number of elements', () => {
    expect(() => decodeFloat32(bytesToBase64(new Uint8Array([1, 2, 3])))).toThrow(RangeError)
    expect(() => decodeUint32(bytesToBase64(new Uint8Array([1, 2, 3, 4, 5])))).toThrow(RangeError)
    expect(() => decodeFloat16(bytesToBase64(new Uint8Array([1])))).toThrow(RangeError)
  })
})

describe('float16 decoding', () => {
  it('matches known half-precision bit patterns', () => {
    expect(float16ToNumber(0x0000)).toBe(0)
    expect(float16ToNumber(0x3c00)).toBe(1)
    expect(float16ToNumber(0xc000)).toBe(-2)
    expect(float16ToNumber(0x5640)).toBe(100)
    expect(float16ToNumber(0x7bff)).toBe(65504)
    expect(float16ToNumber(0x0001)).toBe(2 ** -24)
    expect(float16ToNumber(0x7c00)).toBe(Infinity)
    expect(float16ToNumber(0xfc00)).toBe(-Infinity)
    expect(Number.isNaN(float16ToNumber(0x7e00))).toBe(true)
  })

  it('decodes a base64 array into Float32Array with NaN preserved', () => {
    const out = decodeFloat16(f16BitsToBase64([0x5640, 0x7e00, 0x4248]))
    expect(out).toBeInstanceOf(Float32Array)
    expect(out[0]).toBe(100)
    expect(Number.isNaN(out[1]!)).toBe(true)
    expect(out[2]).toBeCloseTo(3.140625, 6)
  })
})

describe('payload decoders', () => {
  it('decodes a grid payload into typed arrays of length n', () => {
    const grid = decodeGrid(gridPayload)
    expect(grid.n).toBe(10)
    expect(grid.cells).toBeInstanceOf(Uint32Array)
    expect(grid.risk).toBeInstanceOf(Float32Array)
    expect(grid.level).toBeInstanceOf(Uint8Array)
    expect(grid.confidence).toBeInstanceOf(Uint8Array)
    expect(grid.cells[9]).toBe(109)
    expect(grid.risk[9]).toBeCloseTo(0.9, 6)
  })

  it('rejects a grid whose arrays disagree with n', () => {
    expect(() => decodeGrid({ ...gridPayload, n: 11 })).toThrow(RangeError)
  })

  it('decodes the per-cell flag bits and rejects flags of the wrong length', () => {
    const flags = bytesToBase64(new Uint8Array([0, 0, 0, 0, 0, 0, 1, 2, 7, 5]))
    const grid = decodeGrid({ ...gridPayload, flags })
    expect(Array.from(grid.flags!)).toEqual([0, 0, 0, 0, 0, 0, 1, 2, 7, 5])
    expect([GRID_FLAG.blindRaised, GRID_FLAG.held, GRID_FLAG.gaugesUntrusted, GRID_FLAG.capped, GRID_FLAG.ensembleDisagrees]).toEqual([1, 2, 4, 8, 16])
    expect(decodeGrid(gridPayload).flags).toBeUndefined()
    expect(() => decodeGrid({ ...gridPayload, flags: bytesToBase64(new Uint8Array(3)) })).toThrow(RangeError)
  })

  it('reads the leads of each date and ignores anything that is not a lead', () => {
    expect(parseLeads({ '2024-08-05': [0, 1, 3], '2024-08-06': [0, 7, 'x', 1.5], '2024-08-07': 'no' })).toEqual({
      '2024-08-05': [0, 1, 3],
      '2024-08-06': [0],
      '2024-08-07': [],
    })
    expect(parseLeads(undefined)).toBeUndefined()
  })

  it('decodes the base map and turns sea cells into NaN whatever depth the payload holds there', () => {
    const t = decodeBasemap(basemapPayload)
    expect([t.rows, t.cols]).toEqual([2, 2])
    expect(Array.from(t.elev.slice(0, 3))).toEqual([0, 100, 1])
    expect(Number.isNaN(t.elev[3]!)).toBe(true)
    expect(Array.from(t.mask)).toEqual([1, 1, 1, 0])
    expect(t.outline[0]!.name).toBe('India')
  })

  it('rejects a base map whose arrays disagree with its shape', () => {
    expect(() => decodeBasemap({ ...basemapPayload, rows: 3 })).toThrow(RangeError)
  })

  it('counts level and confidence codes', () => {
    const grid = decodeGrid(gridPayload)
    expect(countCodes(grid.level, 4)).toEqual([4, 3, 2, 1])
    expect(countCodes(grid.confidence, 3)).toEqual([6, 3, 1])
  })

  it('maps a cell id to its centre on the global 0.05 degree grid', () => {
    // id = row * 10000 + col, row 0 is -90, col 0 is -180.
    const c = cellCenter(3100 * 10_000 + 4400)
    expect(c.lat).toBeCloseTo(-90 + 3100.5 * 0.05, 9)
    expect(c.lon).toBeCloseTo(-180 + 4400.5 * 0.05, 9)
  })
})

describe('decodePlaces', () => {
  const places = decodePlaces(placesPayload)

  it('looks a cell up and resolves its names, leaving a missing district or state null', () => {
    expect(places.lookup(107)).toEqual({ place: 'Mananthavady', district: 'Wayanad', state: 'Kerala', country: 'India', distanceKm: 8 })
    expect(places.lookup(108)).toEqual({ place: 'Kathmandu', district: null, state: 'Bagmati Province', country: 'Nepal', distanceKm: 32 })
    expect(places.lookup(109)).toEqual({ place: 'Thimphu', district: null, state: null, country: 'Bhutan', distanceKm: 0 })
  })

  it('has no label for a cell that is not in the table', () => {
    for (const cell of [0, 106, 110, 999999]) expect(places.lookup(cell)).toBeNull()
  })

  it('carries the attribution, the far limit and the number of labelled cells', () => {
    expect(places.attribution).toBe('Place names: GeoNames (CC BY 4.0)')
    expect([places.farKm, places.size]).toEqual([25, 3])
    expect(decodePlaces({ ...placesPayload, far_km: undefined }).farKm).toBe(25)
  })

  it('finds every cell of a large sorted table', () => {
    const n = 5000
    const ids = Array.from({ length: n }, (_, i) => 20_000_000 + i * 3)
    const big = decodePlaces({
      ...placesPayload,
      n,
      cells: u32ToBase64(ids),
      place: u32ToBase64(ids.map((_, i) => i % 3)),
      district: u16ToBase64(ids.map(() => 0)),
      state: u16ToBase64(ids.map(() => 0)),
      country: bytesToBase64(new Uint8Array(n).fill(1)),
      distance_km: u16ToBase64(ids.map((_, i) => i % 200)),
    })
    for (const i of [0, 1, 2499, 4999]) expect(big.lookup(ids[i]!)).toMatchObject({ place: placesPayload.places[i % 3], distanceKm: i % 200 })
    expect(big.lookup(20_000_001)).toBeNull()
  })

  it('rejects arrays of different lengths', () => {
    expect(() => decodePlaces({ ...placesPayload, distance_km: u16ToBase64([1, 2]) })).toThrow(RangeError)
  })
})

describe('decodeGrid of a forecast lead', () => {
  const forecast = {
    ...gridPayload,
    lead: 2,
    certainty: bytesToBase64(new Uint8Array([0, 1, 2, 2, 1, 0, 1, 2, 1, 2])),
    level_min: bytesToBase64(new Uint8Array([0, 0, 0, 0, 1, 1, 1, 0, 2, 1])),
    level_max: bytesToBase64(new Uint8Array([0, 0, 3, 3, 1, 1, 1, 3, 2, 3])),
    forecast: { source: 'ecmwf_hres', label: 'ECMWF IFS HRES (CC BY 4.0)', mapped: false, fallback: false, cycle: null, attribution: 'a' },
  }

  it('carries the certainty bytes, the level range and the rain source', () => {
    const grid = decodeGrid(forecast)
    expect(Array.from(grid.certainty!)).toEqual([0, 1, 2, 2, 1, 0, 1, 2, 1, 2])
    expect(Array.from(grid.levelMin!)).toEqual([0, 0, 0, 0, 1, 1, 1, 0, 2, 1])
    expect(Array.from(grid.levelMax!)).toEqual([0, 0, 3, 3, 1, 1, 1, 3, 2, 3])
    expect(grid.forecast).toMatchObject({ source: 'ecmwf_hres', attribution: 'a', cycle: null })
  })

  it('is absent from a lead-0 grid and an older API', () => {
    const grid = decodeGrid(gridPayload)
    expect([grid.certainty, grid.levelMin, grid.levelMax, grid.forecast]).toEqual([undefined, undefined, undefined, undefined])
  })

  it('reports a forecast the run did not record as null, and a length mismatch as an error', () => {
    expect(decodeGrid({ ...forecast, forecast: null }).forecast).toBeNull()
    expect(() => decodeGrid({ ...forecast, certainty: bytesToBase64(new Uint8Array([1, 2])) })).toThrow(RangeError)
  })
})
