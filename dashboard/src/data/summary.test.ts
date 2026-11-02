import { describe, expect, it } from 'vitest'
import {
  describeOdds,
  describePlace,
  describeRisk,
  formatPer100k,
  formatWeekday,
  NEUTRAL_RAIN,
  oddsOptions,
  oddsWhen,
  placeTitle,
  rainSourceName,
  spokenRisk,
} from './summary'
import { GRID_FLAG, type PlaceLabel } from './types'

const WATCH = 4.134155079431125e-6

describe('describeRisk', () => {
  it('gives risk per 100k cell-days, with two significant figures below 10', () => {
    expect(describeRisk(0.00045198, WATCH).primary).toBe('45 per 100k cell-days')
    expect(describeRisk(4.134155e-6, WATCH).primary).toBe('0.41 per 100k cell-days')
    expect(describeRisk(3.2e-5).primary).toBe('3.2 per 100k cell-days')
    expect(describeRisk(0.0123).primary).toBe('1,230 per 100k cell-days')
  })

  it('gives the multiple of the Watch threshold as the secondary figure', () => {
    expect(describeRisk(4.134155079431125e-6, WATCH).secondary).toBe('1× Watch threshold')
    expect(describeRisk(0.00045198, WATCH).secondary).toBe('109× Watch threshold')
    expect(describeRisk(1.5e-5, WATCH).secondary).toBe('3.6× Watch threshold')
    expect(describeRisk(1e-6, WATCH).secondary).toBe('0.24× Watch threshold')
  })

  it('has no secondary figure without a usable threshold', () => {
    for (const watch of [undefined, null, 0, -1, NaN]) expect(describeRisk(1e-4, watch).secondary).toBeNull()
  })

  it('keeps the raw probability for a tooltip only', () => {
    const text = describeRisk(0.00045198, WATCH)
    expect(text.raw).toBe('Raw probability 0.000452 per cell-day')
    expect(text.primary).not.toContain('0.000452')
    expect(text.secondary).not.toContain('0.000452')
  })

  describe('edge cases', () => {
    it('shows zero as zero', () => {
      const text = describeRisk(0, WATCH)
      expect(text.primary).toBe('0 per 100k cell-days')
      expect(text.secondary).toBe('0× Watch threshold')
      expect(text.raw).toBe('Raw probability 0 per cell-day')
    })

    it('says n/a for a missing, non-finite or negative risk, never a number', () => {
      for (const risk of [NaN, Infinity, -Infinity, -1e-6, null, undefined]) {
        const text = describeRisk(risk, WATCH)
        expect(text.primary).toBe('n/a')
        expect(text.secondary).toBeNull()
      }
    })

    it('uses a short exponent for a tiny risk instead of a long run of zeros', () => {
      expect(describeRisk(1.2e-12, WATCH).primary).toBe('1.2e-7 per 100k cell-days')
      expect(describeRisk(1.2e-12, WATCH).secondary).toBe('<0.01× Watch threshold')
    })

    it('rounds large values to whole numbers with thousands separators', () => {
      expect(describeRisk(0.9).primary).toBe('90,000 per 100k cell-days')
    })
  })

  it('reads out the primary figure, then the secondary one when there is one', () => {
    expect(spokenRisk(describeRisk(4.134155079431125e-6, WATCH))).toBe('0.41 per 100k cell-days, 1× Watch threshold')
    expect(spokenRisk(describeRisk(4.134155079431125e-6))).toBe('0.41 per 100k cell-days')
  })

  it('formats a bare number per 100k', () => {
    expect(formatPer100k(1.5830874747827032e-5)).toBe('1.6')
    expect(formatPer100k(3.697191461958891e-5)).toBe('3.7')
  })
})

describe('rainSourceName', () => {
  it('names IMERG for live sets and for a table carrying the IMERG column', () => {
    expect(rainSourceName({ set: 'live', column: 'rain_acc_1', sources: [] })).toBe('NASA IMERG (satellite)')
    expect(rainSourceName({ set: 'case', column: 'irain_acc_1', sources: ['imd'] })).toBe('NASA IMERG (satellite)')
  })

  it('names what the replay set says, in order of use', () => {
    expect(rainSourceName({ set: 'case', column: 'rain_acc_1', sources: ['imd'] })).toBe('IMD gauge-based grid')
    expect(rainSourceName({ set: 'case', column: 'rain_acc_1', sources: ['imd', 'chirps_aligned'] })).toBe(
      'IMD gauge-based grid and CHIRPS satellite estimate (aligned to IMD)',
    )
  })

  it('returns null when nothing is known, so the caller stays neutral', () => {
    expect(rainSourceName({ set: 'case', column: 'rain_acc_1', sources: [] })).toBeNull()
    expect(rainSourceName({ set: 'case', column: 'rain_acc_1', sources: ['none'] })).toBeNull()
    expect(NEUTRAL_RAIN).toBe('1-day rain (mm/day)')
  })

  it('shows an unrecognised source as the API wrote it', () => {
    expect(rainSourceName({ set: 'case', column: 'rain_acc_1', sources: ['gsmap'] })).toBe('gsmap')
  })
})

const mananthavady: PlaceLabel = { place: 'Mananthavady', district: 'Wayanad', state: 'Kerala', country: 'India', distanceKm: 8 }
/** Cell 20295122, the Wayanad cell at 11.475 N, 76.125 E. */
const WAYANAD = 20_295_122

describe('placeTitle', () => {
  it('joins place, district and state', () => {
    expect(placeTitle(mananthavady)).toBe('Mananthavady, Wayanad, Kerala')
  })

  it('names Nepal and Bhutan after the state and leaves India out', () => {
    expect(placeTitle({ place: 'Kathmandu', district: 'Kathmandu', state: 'Bagmati Province', country: 'Nepal', distanceKm: 5 })).toBe(
      'Kathmandu, Bagmati Province, Nepal',
    )
    expect(placeTitle({ place: 'Thimphu', district: null, state: 'Thimphu', country: 'Bhutan', distanceKm: 5 })).toBe('Thimphu, Bhutan')
  })

  it('leaves out a missing district or state and a part that repeats the one before', () => {
    expect(placeTitle({ ...mananthavady, district: null })).toBe('Mananthavady, Kerala')
    expect(placeTitle({ ...mananthavady, district: null, state: null })).toBe('Mananthavady')
    expect(placeTitle({ place: 'Shimla', district: 'Shimla', state: 'Himachal Pradesh', country: 'India', distanceKm: 2 })).toBe(
      'Shimla, Himachal Pradesh',
    )
  })
})

describe('describePlace', () => {
  it('gives the name line, then the distance to the town centre and the coordinates', () => {
    expect(describePlace(WAYANAD, mananthavady)).toEqual({
      primary: 'Mananthavady, Wayanad, Kerala',
      secondary: '8 km from town centre · 11.48°N, 76.13°E',
      far: false,
    })
  })

  it('says "nearest town" from 25 km on, so a remote ridge is not presented as the town', () => {
    const at24 = describePlace(WAYANAD, { ...mananthavady, distanceKm: 24 })
    expect(at24.secondary).toBe('24 km from town centre · 11.48°N, 76.13°E')
    const far = describePlace(WAYANAD, { ...mananthavady, distanceKm: 32 })
    expect(far.primary).toBe('Mananthavady, Wayanad, Kerala')
    expect(far.secondary).toBe('nearest town: Mananthavady (32 km) · 11.48°N, 76.13°E')
    expect(far.far).toBe(true)
    expect(describePlace(WAYANAD, { ...mananthavady, distanceKm: 25 }).far).toBe(true)
  })

  it('takes the far limit the API reports', () => {
    expect(describePlace(WAYANAD, { ...mananthavady, distanceKm: 12 }, 10).far).toBe(true)
  })

  it('says "<1 km" rather than "0 km" in the town centre', () => {
    expect(describePlace(WAYANAD, { ...mananthavady, distanceKm: 0 }).secondary).toBe('<1 km from town centre · 11.48°N, 76.13°E')
  })

  it('falls back to the coordinates alone without a label', () => {
    expect(describePlace(WAYANAD, null)).toEqual({ primary: '11.48°N, 76.13°E', secondary: null, far: false })
    expect(describePlace(WAYANAD, undefined).primary).toBe('11.48°N, 76.13°E')
  })
})

describe('formatWeekday', () => {
  it('names the weekday of an ISO day, whatever the viewer time zone', () => {
    expect(formatWeekday('2026-10-26')).toBe('Mon 26 Oct')
    expect(formatWeekday(null)).toBe('n/a')
  })
})

describe('describeOdds', () => {
  it('says 1 in N to two significant figures with the day', () => {
    expect(describeOdds(0.00045198, 'today')).toEqual({
      sentence: 'About 1 in 2,200 chance of a landslide in this 5 km cell today',
      short: '1 in 2,200',
    })
    expect(describeOdds(3e-6, 'on Sat 26 Oct')?.sentence).toBe('About 1 in 330,000 chance of a landslide in this 5 km cell on Sat 26 Oct')
    expect(describeOdds(0.0123, 'today')?.short).toBe('1 in 81')
    expect(describeOdds(0.4, 'today')?.short).toBe('1 in 3')
    expect(describeOdds(1, 'today')?.short).toBe('1 in 1')
  })

  it('has no line for a risk of zero, a negative, a missing or a non-finite risk', () => {
    for (const risk of [0, -1e-6, NaN, Infinity, null, undefined]) expect(describeOdds(risk, 'today')).toBeNull()
  })

  it('rounds 1 / risk, not the risk', () => {
    expect(describeOdds(1 / 123456, 'today')?.short).toBe('1 in 120,000')
    expect(describeOdds(1 / 99, 'today')?.short).toBe('1 in 99')
    expect(describeOdds(1 / 996, 'today')?.short).toBe('1 in 1,000')
  })

  it('gives no chance for a cell capped by the rain trigger, and names the model estimate as not used', () => {
    const odds = describeOdds(1 / 2600, 'today', { capped: true })
    expect(odds).toEqual({
      sentence: "Too little recent rain for a rain-triggered landslide, so no chance is given (the model's 1 in 2,600 estimate is not used)",
      short: 'not used',
    })
    expect(odds!.sentence).not.toContain('About 1 in')
    expect(describeOdds(0, 'today', { capped: true })).toBeNull()
  })

  it('is unchanged when the cell is not capped', () => {
    expect(describeOdds(0.00045198, 'today', { capped: false })).toEqual(describeOdds(0.00045198, 'today'))
    expect(describeOdds(0.00045198, 'today', { disagrees: false })!.sentence).toBe(
      'About 1 in 2,200 chance of a landslide in this 5 km cell today',
    )
  })

  it('keeps the odds but says most ensemble models put them lower when they disagree', () => {
    expect(describeOdds(0.00045198, 'today', { disagrees: true })).toEqual({
      sentence: 'About 1 in 2,200 chance of a landslide in this 5 km cell today (most of the 20 ensemble models put it lower)',
      short: '1 in 2,200',
    })
  })

  it('reads the capped and disagreeing options from the grid flag bits', () => {
    expect(oddsOptions(undefined)).toEqual({ capped: false, disagrees: false })
    expect(oddsOptions(GRID_FLAG.held | GRID_FLAG.capped)).toEqual({ capped: true, disagrees: false })
    expect(oddsOptions(GRID_FLAG.ensembleDisagrees)).toEqual({ capped: false, disagrees: true })
  })
})

describe('describeOdds against 1 / risk (integrity audit)', () => {
  // risks of every magnitude the model publishes (its alert thresholds, the 5 km cell base rate, a certain landslide)
  const RISKS = [
    ...Array.from({ length: 91 }, (_, k) => 10 ** (-9 + k / 10)),
    2.782149847271763e-6, 3.0146490326518273e-6, 1.1842377470857583e-5, 4.814709609428837e-5, 0.00045198, 0.0123, 0.4, 0.5, 0.9999, 1,
  ]
  const parsed = (risk: number) => Number(describeOdds(risk, 'today')!.short.replace('1 in ', '').replaceAll(',', ''))
  const significant = (n: number) => String(n).replace(/0+$/, '').length

  it('shows N within the two-significant-figure rounding of 1 / risk', () => {
    for (const risk of RISKS) {
      const exact = Math.max(1, 1 / risk)
      const n = parsed(risk)
      // the rounding unit is 1 below 100 and a tenth of the leading power of ten above: at most half of it either way
      const unit = exact < 100 ? 1 : 10 ** (Math.floor(Math.log10(exact)) - 1)
      expect(Math.abs(n - exact), `risk ${risk}`).toBeLessThanOrEqual(unit / 2 + 1e-9 * exact)
      expect(n, `risk ${risk}`).toBeGreaterThanOrEqual(1)
      if (n >= 100) expect(significant(n), `risk ${risk}`).toBeLessThanOrEqual(2)
    }
  })

  it('never shows fewer odds for a higher risk', () => {
    const shown = [...RISKS].sort((a, b) => a - b).map(parsed)
    for (let i = 1; i < shown.length; i++) expect(shown[i]!).toBeLessThanOrEqual(shown[i - 1]!)
  })

  it('writes the same N in the sentence, the short form and the capped and disagreeing variants', () => {
    for (const risk of RISKS) {
      const n = describeOdds(risk, 'today')!.short.replace('1 in ', '')
      expect(describeOdds(risk, 'today')!.sentence).toBe(`About 1 in ${n} chance of a landslide in this 5 km cell today`)
      expect(describeOdds(risk, 'today', { disagrees: true })!.sentence).toContain(`About 1 in ${n} chance`)
      expect(describeOdds(risk, 'today', { capped: true })!.sentence).toContain(`1 in ${n} estimate is not used`)
      expect(describeOdds(risk, 'today', { capped: true })!.short).toBe('not used')
    }
  })

  it('gives no line for a risk that is not a probability above zero', () => {
    for (const risk of [0, -0.1, NaN, Infinity, -Infinity]) expect(describeOdds(risk, 'today')).toBeNull()
  })
})

describe('oddsWhen', () => {
  it('is today for the live run’s own day and names the date otherwise', () => {
    expect(oddsWhen('2026-10-24', 0, true)).toBe('today')
    expect(oddsWhen('2026-10-24', 0, false)).toBe('on Sat 24 Oct')
    expect(oddsWhen('2026-10-24', 2, true)).toBe('on Mon 26 Oct')
    expect(oddsWhen(null, 0, false)).toBe('today')
  })
})
