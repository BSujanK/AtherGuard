import { describe, expect, it } from 'vitest'
import { cellBody, forecastBody, historyBody } from '../test/alertFixtures'
import { ApiError, parseCellDetail, parseCellHistory, parseRegionalThresholds, parseThresholds } from './api'

describe('parseCellDetail', () => {
  it('reads a /risk/cell response into the drawer model', () => {
    const d = parseCellDetail(cellBody)
    expect(d).toMatchObject({
      cell: 20285122,
      date: '2024-07-30',
      set: 'case_wayanad_2024_samples',
      region: 'western_ghats',
      level: 3,
      levelName: 'Emergency',
      rawLevel: 'Emergency',
      confidence: 'Degraded',
      confidenceCauses: ['sources_disagree', 'stations_flagged_nearby', 'made_up_cause'],
      reasonCodes: ['risk_above_emergency', 'sensors_untrusted_heavy_rain', 'hysteresis_hold'],
    })
    expect(d.risk).toBeCloseTo(0.000452, 6)
    expect(d.shap).toHaveLength(5)
    expect(d.sensorTrust).toEqual({ stations: 2, trusted: 1, flagged7d: 1, outOfDistribution: 0, flaggedTypes: ['stuck_zero'] })
  })

  it('reads the thresholds of the cell’s date and the region they are for, and leaves both null when absent', () => {
    const thresholds = { watch: 5e-6, warning: 2e-5, emergency: 6e-5, source: 'run.json' }
    expect(parseCellDetail({ ...cellBody, thresholds, thresholds_region: 'pooled' })).toMatchObject({ thresholds, thresholdsRegion: 'pooled' })
    expect(parseCellDetail({ ...cellBody, thresholds: { watch: 0 }, thresholds_region: undefined })).toMatchObject({
      thresholds: null,
      thresholdsRegion: null,
    })
  })

  it('keeps a source the API reports as null as null, never as zero', () => {
    const { sources } = parseCellDetail(cellBody)
    expect(sources.satellite1).toBeNull()
    expect(sources.satellite3).toBeNull()
    expect(sources.disagreement3).toBeNull()
    expect(sources.imd1).toBeCloseTo(179.2358, 3)
    expect(sources.gauge1).toBeCloseTo(158.13, 2)
    expect(sources.rainSource).toBe('imd')
  })

  it('treats a missing or non-finite number as null', () => {
    const d = parseCellDetail({ ...cellBody, risk: null, risk_lo: 'x', sources: { imd_acc_1: NaN, chirps_acc_1: Infinity }, shap: [{ feature: 'wet_top', value: null, contribution: 0.2 }] })
    expect([d.risk, d.riskLo]).toEqual([null, null])
    expect(d.riskHi).toBeCloseTo(0.000626641, 9)
    expect(d.sources.imd1).toBeNull()
    expect(d.sources.satellite1).toBeNull()
    expect(d.shap).toEqual([{ feature: 'wet_top', value: null, contribution: 0.2 }])
  })

  it('drops a contribution without a number rather than inventing one', () => {
    const d = parseCellDetail({ ...cellBody, shap: [{ feature: 'wet_top', value: 1, contribution: null }, { feature: 5 }, 'x'] })
    expect(d.shap).toEqual([])
  })

  it('rejects a payload that is not a cell', () => {
    for (const bad of [null, [], 'x', {}, { ...cellBody, level: 9 }, { ...cellBody, cell_id: '1' }]) {
      expect(() => parseCellDetail(bad)).toThrow(ApiError)
    }
  })
})

describe('parseCellHistory', () => {
  it('reads dates, risk, level and the three rain series', () => {
    const h = parseCellHistory(historyBody)
    expect(h.dates).toHaveLength(5)
    expect(h.rain.imd).toEqual([1, 4, 30, 120, 179.2])
    expect(h.rain.satellite).toEqual([2, null, 25, 90, 150])
    expect(h.rain.gauges).toEqual([null, null, 28, 100, 158.1])
    expect(h.level).toEqual([0, 1, 1, 3, 3])
  })

  it('pads a series shorter than the dates with null, and copes with an API that sends no rain', () => {
    const h = parseCellHistory({ cell_id: 1, set: 's', dates: ['a', 'b'], risk: [0.1], level: [1] })
    expect(h.risk).toEqual([0.1, null])
    expect(h.level).toEqual([1, 0])
    expect(h.rain).toEqual({ imd: [null, null], satellite: [null, null], gauges: [null, null] })
  })

  it('rejects a payload without dates', () => {
    expect(() => parseCellHistory({ cell_id: 1 })).toThrow(ApiError)
  })
})

describe('parseThresholds', () => {
  it('accepts three finite positive risks', () => {
    expect(parseThresholds({ watch: 1e-6, warning: 2e-6, emergency: 3e-6, source: 'card' })).toEqual({
      watch: 1e-6,
      warning: 2e-6,
      emergency: 3e-6,
      source: 'card',
    })
  })

  it('is null for anything else, so the multiple of Watch is left out instead of guessed', () => {
    for (const bad of [null, undefined, 3, { watch: 0, warning: 1, emergency: 2 }, { watch: 1, warning: NaN, emergency: 2 }, { watch: '1', warning: 1, emergency: 2 }, {}]) {
      expect(parseThresholds(bad)).toBeNull()
    }
  })
})

describe('parseRegionalThresholds', () => {
  const good = { watch: 1e-6, warning: 2e-6, emergency: 3e-6, source: 'card' }

  it('keeps the regions whose three thresholds are usable', () => {
    expect(parseRegionalThresholds({ himalaya: good, western_ghats: { ...good, watch: 0 }, elsewhere: 'no' })).toEqual({ himalaya: good })
  })

  it('is null without any usable region', () => {
    for (const bad of [null, undefined, [], 3, {}, { himalaya: 3 }]) expect(parseRegionalThresholds(bad)).toBeNull()
  })
})

describe('section 12 fields of a forecast cell', () => {
  it('reads the certainty, the level range, the rain source and the rain rule', () => {
    const d = parseCellDetail(
      forecastBody(2, {
        certainty: 'firm',
        level_min: 2,
        level_max: 2,
        forecast_source: { source: 'ecmwf_hres', label: 'ECMWF IFS HRES (CC BY 4.0)', mapped: true, fallback: false, cycle: '2026-10-23T18:00:00+00:00', attribution: 'x' },
        rain_rule: { passed: false, exempt: false, capped: true, window_days: 7, rain_mm: 0, minimum_mm: 11.5, capped_to: 'Watch' },
      }),
    )
    expect(d).toMatchObject({ certainty: 'firm', levelMin: 2, levelMax: 2 })
    expect(d.forecastSource).toEqual({
      source: 'ecmwf_hres',
      label: 'ECMWF IFS HRES (CC BY 4.0)',
      mapped: true,
      fallback: false,
      cycle: '2026-10-23T18:00:00+00:00',
      attribution: 'x',
    })
    expect(d.rainRule).toEqual({ passed: false, exempt: false, capped: true, windowDays: 7, rainMm: 0, minimumMm: 11.5, cappedTo: 'Watch' })
  })

  it('has none of them for a lead-0 cell or an API that predates the fields', () => {
    const d = parseCellDetail(cellBody)
    expect([d.certainty, d.levelMin, d.levelMax, d.forecastSource, d.rainRule]).toEqual([null, null, null, null, null])
  })

  it('ignores an unknown certainty word and a level outside 0 to 3', () => {
    const d = parseCellDetail(forecastBody(1, { certainty: 'sure', level_min: 7, level_max: -1, forecast_source: 'gfs' }))
    expect([d.certainty, d.levelMin, d.levelMax, d.forecastSource]).toEqual([null, null, null, null])
  })
})
