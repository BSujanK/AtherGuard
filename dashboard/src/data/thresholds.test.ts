import { describe, expect, it } from 'vitest'
import { cellAt } from '../test/alertFixtures'
import { thresholdsFor, watchForCell } from './thresholds'
import type { Thresholds } from './types'

const pooled: Thresholds = { watch: 3e-6, warning: 1.2e-5, emergency: 4.8e-5, source: 'pooled' }
const himalaya: Thresholds = { watch: 2.8e-6, warning: 1.4e-5, emergency: 4.9e-5, source: 'himalaya' }
const ghats: Thresholds = { watch: 3.8e-6, warning: 1.4e-5, emergency: 2.6e-5, source: 'ghats' }
const mode = { thresholds: pooled, thresholds_by_region: { himalaya, western_ghats: ghats } }

describe('thresholdsFor', () => {
  it('gives a region its own thresholds, named after it', () => {
    expect(thresholdsFor(mode, 'western_ghats')).toEqual({ thresholds: ghats, scope: 'Western Ghats' })
    expect(thresholdsFor(mode, 'himalaya')).toEqual({ thresholds: himalaya, scope: 'Himalaya' })
  })

  it('falls back to the pooled all-India thresholds for a cell outside both regions or a region without its own', () => {
    expect(thresholdsFor(mode, null)).toEqual({ thresholds: pooled, scope: 'All-India' })
    expect(thresholdsFor({ thresholds: pooled, thresholds_by_region: { himalaya } }, 'western_ghats')).toEqual({ thresholds: pooled, scope: 'All-India' })
    expect(thresholdsFor({ thresholds: pooled }, 'himalaya')).toEqual({ thresholds: pooled, scope: 'All-India' })
  })

  it('has no thresholds when the API reported none', () => {
    expect(thresholdsFor(undefined, 'himalaya')).toEqual({ thresholds: null, scope: 'All-India' })
    expect(thresholdsFor({ thresholds: null, thresholds_by_region: null }, null).thresholds).toBeNull()
  })
})

describe('watchForCell', () => {
  it('is the Watch threshold of the region holding the cell', () => {
    expect(watchForCell(mode, cellAt(11.5, 76.1))).toBe(ghats.watch)
    expect(watchForCell(mode, cellAt(30.025, 80.025))).toBe(himalaya.watch)
    expect(watchForCell(mode, cellAt(2, 60))).toBe(pooled.watch)
    expect(watchForCell(undefined, cellAt(11.5, 76.1))).toBeUndefined()
  })
})
