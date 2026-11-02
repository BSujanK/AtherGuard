import { describe, expect, it } from 'vitest'
import { mixHex, PALETTE } from '../../charts/theme'
import { formatTrust, inDomain, trustColor } from './trust'

describe('trustColor', () => {
  it('lands exactly on the palette at the four stops', () => {
    expect(trustColor(1)).toBe(PALETTE.cyan)
    expect(trustColor(2 / 3)).toBe(PALETTE.lime)
    expect(trustColor(1 / 3)).toBe(PALETTE.flame)
    expect(trustColor(0)).toBe(PALETTE.fire)
  })

  it('clamps out-of-range trust to the end stops', () => {
    expect(trustColor(1.4)).toBe(PALETTE.cyan)
    expect(trustColor(-0.2)).toBe(PALETTE.fire)
  })

  it('mixes linearly between stops', () => {
    expect(trustColor(5 / 6)).toBe(mixHex(PALETTE.lime, PALETTE.cyan, 0.5))
    expect(trustColor(0.5)).toBe(mixHex(PALETTE.flame, PALETTE.lime, 0.5))
    expect(trustColor(1 / 6)).toBe(mixHex(PALETTE.fire, PALETTE.flame, 0.5))
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
