import { describe, expect, it } from 'vitest'
import { hexToRgb, mixHex, PALETTE } from '../../charts/theme'
import { formatTrust, inDomain, trustColor } from './trust'

describe('trustColor', () => {
  it('lands exactly on the palette at the four stops', () => {
    expect(trustColor(1)).toBe(PALETTE.signal)
    expect(trustColor(2 / 3)).toBe(PALETTE.yellow)
    expect(trustColor(1 / 3)).toBe(PALETTE.orange)
    expect(trustColor(0)).toBe(PALETTE.red)
  })

  it('clamps out-of-range trust to the end stops', () => {
    expect(trustColor(1.4)).toBe(PALETTE.signal)
    expect(trustColor(-0.2)).toBe(PALETTE.red)
  })

  it('mixes linearly between stops', () => {
    // Within one step per channel: a stop position like 5/6 is not exact in floating point.
    const near = (got: string, want: string) => hexToRgb(got).forEach((c, i) => expect(Math.abs(c - hexToRgb(want)[i]!)).toBeLessThanOrEqual(1))
    near(trustColor(5 / 6), mixHex(PALETTE.yellow, PALETTE.signal, 0.5))
    near(trustColor(0.5), mixHex(PALETTE.orange, PALETTE.yellow, 0.5))
    near(trustColor(1 / 6), mixHex(PALETTE.red, PALETTE.orange, 0.5))
  })

  it('gives every step of the ramp its own colour, so falling trust is always visible', () => {
    const steps = [1, 0.75, 0.5, 0.25, 0].map(trustColor)
    expect(new Set(steps).size).toBe(steps.length)
  })
})

describe('formatTrust', () => {
  it('shows two decimals, or says there is no value', () => {
    expect(formatTrust(0.96896)).toBe('0.97')
    expect(formatTrust(null)).toBe('no value')
  })
})

describe('inDomain', () => {
  it('keeps stations inside the modelled box', () => {
    expect(inDomain({ lat: 14.5, lon: 77.6 })).toBe(true)
    expect(inDomain({ lat: 5, lon: 77 })).toBe(false)
    expect(inDomain({ lat: 34, lon: 68.85 })).toBe(true)
  })
})
