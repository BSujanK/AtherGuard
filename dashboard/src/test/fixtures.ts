import { http, HttpResponse } from 'msw'
import type { BasemapPayload, GridPayload, ModeResponse, PlacesPayload } from '../data/types'

export function bytesToBase64(bytes: Uint8Array): string {
  let bin = ''
  for (const b of bytes) bin += String.fromCharCode(b)
  return btoa(bin)
}

export const f32ToBase64 = (values: number[]): string =>
  bytesToBase64(new Uint8Array(new Float32Array(values).buffer))

export const u32ToBase64 = (values: number[]): string =>
  bytesToBase64(new Uint8Array(new Uint32Array(values).buffer))

/** Half-precision words (little endian) to base64; callers pass raw bit patterns. */
export function f16BitsToBase64(words: number[]): string {
  const bytes = new Uint8Array(words.length * 2)
  words.forEach((w, i) => {
    bytes[2 * i] = w & 0xff
    bytes[2 * i + 1] = w >> 8
  })
  return bytesToBase64(bytes)
}

export const replayMode: ModeResponse = {
  mode: 'replay',
  set: 'case_test_set',
  latest_date: '2024-08-05',
  dates: ['2024-08-04', '2024-08-05'],
}

export const noDataMode: ModeResponse = { mode: 'none', set: null, latest_date: null, dates: [] }

/** Ten cells: 4 Normal, 3 Watch, 2 Warning, 1 Emergency; 6 High, 3 Degraded, 1 Insufficient confidence. */
export const gridPayload: GridPayload = {
  date: '2024-08-05',
  lead: 0,
  n: 10,
  cells: u32ToBase64([100, 101, 102, 103, 104, 105, 106, 107, 108, 109]),
  risk: f32ToBase64([0.01, 0.02, 0.03, 0.04, 0.2, 0.25, 0.3, 0.5, 0.6, 0.9]),
  level: bytesToBase64(new Uint8Array([0, 0, 0, 0, 1, 1, 1, 2, 2, 3])),
  confidence: bytesToBase64(new Uint8Array([0, 0, 0, 0, 0, 0, 1, 1, 1, 2])),
  lat0: -90,
  lon0: -180,
  step: 0.05,
}

/** 2 x 2 base map: India land of 0 m, 100 m and 1 m, and one sea sample (the payload keeps a sea-floor depth there). */
export const basemapPayload: BasemapPayload = {
  rows: 2,
  cols: 2,
  lat0: 8,
  lon0: 72,
  step: 0.05,
  elev: f16BitsToBase64([0x0000, 0x5640, 0x3c00, 0xd640]),
  mask: bytesToBase64(new Uint8Array([1, 1, 1, 0])),
  outline: [{ name: 'India', rings: [[[72, 8], [72.1, 8], [72.1, 8.1], [72, 8]]] }],
}

export const u16ToBase64 = (values: number[]): string =>
  bytesToBase64(new Uint8Array(new Uint16Array(values).buffer))

/** The place table of the test grid: 107 Mananthavady (8 km), 108 a remote cell of Kathmandu (32 km, no district), 109 Thimphu (no district or state). */
export const placesPayload: PlacesPayload = {
  attribution: 'Place names: GeoNames (CC BY 4.0)',
  n: 3,
  far_km: 25,
  places: ['Kathmandu', 'Mananthavady', 'Thimphu'],
  districts: ['', 'Wayanad'],
  states: ['', 'Bagmati Province', 'Kerala'],
  countries: ['', 'India', 'Nepal', 'Bhutan'],
  cells: u32ToBase64([107, 108, 109]),
  place: u32ToBase64([1, 0, 2]),
  district: u16ToBase64([1, 0, 0]),
  state: u16ToBase64([2, 1, 0]),
  country: bytesToBase64(new Uint8Array([1, 2, 3])),
  distance_km: u16ToBase64([8, 32, 0]),
}

/** Place names are optional: tests that do not look at them get the "no table" answer, as an API without a build gives. */
export const noPlacesHandler = http.get('*/api/places', () => HttpResponse.json({ detail: 'no place names' }, { status: 404 }))

export function apiHandlers(mode: ModeResponse = replayMode) {
  return [
    http.get('*/api/mode', () => HttpResponse.json(mode)),
    noPlacesHandler,
    http.get('*/api/grid', () =>
      mode.mode === 'none'
        ? HttpResponse.json({ detail: 'no data' }, { status: 404 })
        : HttpResponse.json(gridPayload),
    ),
    http.get('*/api/basemap', () => HttpResponse.json(basemapPayload)),
  ]
}
