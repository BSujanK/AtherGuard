import { describe, expect, it } from 'vitest'
import { makeGrid } from '../test/alertFixtures'
import { certaintyShort, describeCertainty, forecastShortName, gridCertainty, levelRange, sourceName } from './certainty'
import { CERTAINTY, type ForecastSource } from './types'

const ecmwf: ForecastSource = {
  source: 'ecmwf_hres',
  label: 'ECMWF IFS HRES (CC BY 4.0)',
  mapped: false,
  fallback: false,
  cycle: '2026-10-23T18:00:00+00:00',
  attribution: 'Contains ECMWF open data (IFS), licensed CC BY 4.0',
}

describe('describeCertainty', () => {
  it('says Firm with the one-line why, from the grid code or the API word', () => {
    for (const code of [CERTAINTY.firm, 'firm'] as const) {
      expect(describeCertainty(code, 2, 2)).toEqual({ kind: 'firm', headline: 'Firm', why: 'set by rain already fallen' })
    }
  })

  it('names the levels a depending cell can take', () => {
    expect(describeCertainty(CERTAINTY.depends, 1, 2)?.headline).toBe('Depends on rain forecast (Watch–Warning)')
    expect(describeCertainty('depends_on_forecast', 0, 3)?.headline).toBe('Depends on rain forecast (Normal–Emergency)')
    expect(describeCertainty('depends_on_forecast', null, null)?.headline).toBe('Depends on rain forecast')
  })

  it('has nothing to say for a cell without a certainty', () => {
    expect(describeCertainty(CERTAINTY.none, 0, 0)).toBeNull()
    expect(describeCertainty(null, null, null)).toBeNull()
    expect(describeCertainty(undefined, undefined, undefined)).toBeNull()
  })
})

describe('levelRange and the short form', () => {
  it('collapses a one-level range', () => {
    expect(levelRange(2, 2)).toBe('Warning')
    expect(levelRange(1, 3)).toBe('Watch–Emergency')
  })

  it('gives a few words for a list row', () => {
    expect(certaintyShort(describeCertainty('firm', 1, 1), 1, 1)).toBe('Firm')
    expect(certaintyShort(describeCertainty('depends_on_forecast', 1, 2), 1, 2)).toBe('Depends (Watch–Warning)')
    expect(certaintyShort(describeCertainty('depends_on_forecast', null, null), null, null)).toBe('Depends')
    expect(certaintyShort(null, 0, 0)).toBeNull()
  })
})

describe('gridCertainty', () => {
  it('reads the cell at an index; a lead-0 grid has none', () => {
    const grid = makeGrid([
      { cell: 10, risk: 1e-5, level: 2 },
      { cell: 20, risk: 1e-6, level: 0 },
    ])
    expect(gridCertainty(grid, 0)).toBeNull()
    const forecast = { ...grid, lead: 2, certainty: Uint8Array.of(2, 1), levelMin: Uint8Array.of(1, 0), levelMax: Uint8Array.of(3, 0) }
    expect(gridCertainty(forecast, 0)?.headline).toBe('Depends on rain forecast (Watch–Emergency)')
    expect(gridCertainty(forecast, 1)?.headline).toBe('Firm')
  })
})

describe('the forecast source', () => {
  it('names the source with its licence and shortens it for labels', () => {
    expect(sourceName(ecmwf)).toBe('ECMWF IFS HRES (CC BY 4.0)')
    expect(sourceName(null)).toBeNull()
    expect(forecastShortName(ecmwf)).toBe('ECMWF')
    expect(forecastShortName({ ...ecmwf, source: 'gfs', label: 'GFS fallback' })).toBe('GFS')
    expect(forecastShortName(undefined)).toBe('GFS')
  })
})
