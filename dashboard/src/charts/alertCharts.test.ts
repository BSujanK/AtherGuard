import { describe, expect, it } from 'vitest'
import type { CellHistory, ShapFactor } from '../data/types'
import { buildRainHistoryOption, rainHistorySummary, satelliteName } from './rainHistoryOption'
import { buildRiskTrendOption, LEVEL_POINT, logBounds, riskTrendSummary } from './riskTrendOption'
import { buildShapOption, shapSummary, signed, topFactors } from './shapOption'
import { buildSourcesOption, SOURCE_COLORS, sourcesSummary } from './sourcesOption'
import { mixHex, PALETTE, TEXT_3 } from './theme'

type Item = { value: number | string; itemStyle?: { color: string } }
type Series = { name: string; type: string; color?: string; data: Item[] | (number | string)[]; markLine?: { data: { name: string; yAxis: number; lineStyle: { color: string } }[] } }
const seriesOf = (o: unknown) => (o as { series: Series[] }).series
const axis = (o: unknown, name: 'xAxis' | 'yAxis') => (o as Record<string, { data?: string[] }>)[name]!

/** Every colour the builders use must be a palette stop or a mix of palette stops. */
const ALLOWED = new Set<string>([
  ...Object.values(PALETTE),
  mixHex(PALETTE.blue, PALETTE.cyan, 0.5),
  TEXT_3,
])

const factor = (feature: string, contribution: number, value: number | null = 1): ShapFactor => ({ feature, value, contribution })

describe('SHAP bars', () => {
  const shap = [
    factor('rain_acc_3', 0.68),
    factor('rain_acc_1', 1.11, 179.2),
    factor('rain_share1_3', -0.47, 0.94),
    factor('stat_elev_mean', 0.74, 1619),
    factor('rain_acc_30', 0.47),
    factor('wet_top', 0.01),
  ]

  it('keeps the five largest contributions, largest first', () => {
    expect(topFactors(shap).map((f) => f.feature)).toEqual(['rain_acc_1', 'stat_elev_mean', 'rain_acc_3', 'rain_share1_3', 'rain_acc_30'])
  })

  it('draws one bar series, orange where the input raised the risk and cyan where it lowered it', () => {
    const option = buildShapOption(shap)
    const [series] = seriesOf(option)
    expect(series!.type).toBe('bar')
    const data = series!.data as Item[]
    expect(data.map((d) => d.value)).toEqual([1.11, 0.74, 0.68, -0.47, 0.47])
    expect(data.map((d) => d.itemStyle!.color)).toEqual([
      PALETTE.flame,
      PALETTE.flame,
      PALETTE.flame,
      PALETTE.cyan,
      PALETTE.flame,
    ])
    expect(axis(option, 'yAxis').data).toEqual(['Rain, today', 'Mean elevation', 'Rain, last 3 days', 'Today’s share of 3-day rain', 'Rain, last 30 days'])
  })

  it('handles a cell with no contributions', () => {
    expect(seriesOf(buildShapOption([]))[0]!.data).toEqual([])
    expect(shapSummary([])).toBe('')
  })

  it('summarises the bars for assistive technology and formats signs', () => {
    expect(shapSummary(shap)).toContain('Rain, today raises risk by 1.11')
    expect(shapSummary(shap)).toContain('lowers risk by 0.47')
    expect(signed(-0.472)).toBe('−0.47')
    expect(signed(0.5)).toBe('+0.50')
  })
})

describe('rain sources chart', () => {
  const bars = [
    { key: 'satellite', label: 'CHIRPS', value: null },
    { key: 'imd', label: 'IMD', value: 179.2 },
    { key: 'gauges', label: 'Gauges', value: 158.1 },
    { key: 'gfs', label: 'GFS', value: null },
  ] as const

  it('draws one bar per source with a value, in the source colour', () => {
    const [series] = seriesOf(buildSourcesOption(bars))
    expect(series!.type).toBe('bar')
    const data = series!.data as Item[]
    expect(data[1]).toEqual({ value: 179.2, itemStyle: { color: SOURCE_COLORS.imd } })
    expect(data[2]).toEqual({ value: 158.1, itemStyle: { color: SOURCE_COLORS.gauges } })
  })

  it('leaves a source without a value empty and says "not available" on its label, never a zero bar', () => {
    const option = buildSourcesOption(bars)
    const data = seriesOf(option)[0]!.data as Item[]
    expect(data[0]).toEqual({ value: '-' })
    expect(data[3]).toEqual({ value: '-' })
    expect(axis(option, 'xAxis').data).toEqual(['CHIRPS\nnot available', 'IMD', 'Gauges', 'GFS\nnot available'])
    expect(sourcesSummary(bars)).toBe('CHIRPS not available, IMD 179.2 mm, Gauges 158.1 mm, GFS not available')
  })
})

const history: CellHistory = {
  cell: 1,
  set: 'case_wayanad_2024_samples',
  dates: ['2024-07-28', '2024-07-29', '2024-07-30'],
  risk: [0.00001, null, 0.000452],
  level: [1, 0, 3],
  rain: { imd: [30, 120, 179.2], satellite: [25, null, 150], gauges: [null, 100, 158.1] },
  place: null,
  issuedDate: null,
  forecast: [],
}
const thresholds = { watch: 4.13e-6, warning: 1.58e-5, emergency: 3.7e-5, source: 'card.alert_levels' }

describe('rain history chart', () => {
  it('draws a line per source in source colours, with gaps where a source had no value', () => {
    const series = seriesOf(buildRainHistoryOption(history))
    expect(series.map((s) => [s.name, s.type, s.color])).toEqual([
      ['IMD', 'line', SOURCE_COLORS.imd],
      ['CHIRPS', 'line', SOURCE_COLORS.satellite],
      ['Trusted gauges', 'line', SOURCE_COLORS.gauges],
    ])
    expect(series[0]!.data).toEqual([30, 120, 179.2])
    expect(series[1]!.data).toEqual([25, '-', 150])
    expect(series[2]!.data).toEqual(['-', 100, 158.1])
  })

  it('names the satellite slot after the set: IMERG for live, CHIRPS for replay', () => {
    expect(satelliteName('live')).toBe('IMERG')
    expect(seriesOf(buildRainHistoryOption({ ...history, set: 'live' }))[1]!.name).toBe('IMERG')
    expect(rainHistorySummary(history)).toBe('3 days to 2024-07-30; latest IMD 179.2 mm, CHIRPS 150.0 mm, trusted gauges 158.1 mm')
  })
})

describe('risk trend chart', () => {
  it('plots risk per 100k cell-days with points coloured by level and a gap for a missing day', () => {
    const [series] = seriesOf(buildRiskTrendOption(history, thresholds))
    expect(series!.name).toBe('Risk')
    const data = series!.data as Item[]
    expect(data[0]).toEqual({ value: 1, itemStyle: { color: PALETTE.lime } })
    expect(data[1]).toBe('-')
    expect(data[2]).toEqual({ value: 45.2, itemStyle: { color: PALETTE.fire } })
    expect(LEVEL_POINT).toEqual([PALETTE.blue, PALETTE.lime, PALETTE.flame, PALETTE.fire])
  })

  it('marks the three thresholds in their level colours, in per 100k units', () => {
    const [series] = seriesOf(buildRiskTrendOption(history, thresholds))
    const lines = series!.markLine!.data
    expect(lines.map((l) => [l.name, l.lineStyle.color])).toEqual([
      ['Watch', PALETTE.lime],
      ['Warning', PALETTE.flame],
      ['Emergency', PALETTE.fire],
    ])
    expect(lines[0]!.yAxis).toBeCloseTo(0.413, 3)
    expect(lines[2]!.yAxis).toBeCloseTo(3.7, 6)
  })

  it('uses a log axis in whole powers of ten so the three thresholds stay apart', () => {
    const option = buildRiskTrendOption(history, thresholds) as { yAxis: { type: string; min: number; max: number } }
    expect(option.yAxis).toMatchObject({ type: 'log', min: 0.1, max: 100 })
    expect(logBounds(history, null)).toEqual({ min: 1, max: 100 })
  })

  it('falls back to a linear axis when a risk is zero, which a log axis cannot show', () => {
    const zero = { ...history, risk: [0, 0.00001, 0.0002] }
    expect(logBounds(zero, thresholds)).toBeNull()
    expect((buildRiskTrendOption(zero, thresholds) as { yAxis: { type: string } }).yAxis.type).toBe('value')
    expect(logBounds({ ...history, risk: [null, null, null] }, thresholds)).toBeNull()
  })

  it('draws no reference lines when the API gave no thresholds', () => {
    expect(seriesOf(buildRiskTrendOption(history, null))[0]!.markLine!.data).toEqual([])
    expect(riskTrendSummary(history, null)).toBe('3 days to 2024-07-30; latest 45 per 100k cell-days')
  })
})

describe('risk trend chart with a forecast', () => {
  const ahead = {
    ...history,
    issuedDate: '2024-07-30',
    forecast: [
      { lead: 1, targetDate: '2024-07-31', risk: 2.1e-5, riskLo: 1e-5, riskHi: 5e-5, level: 2 },
      { lead: 3, targetDate: '2024-08-02', risk: 6.3e-5, riskLo: 3e-5, riskHi: 1e-4, level: 3 },
    ],
  }
  const option = buildRiskTrendOption(ahead, thresholds) as { xAxis: { data: string[] } }
  const [observed, forecast] = seriesOf(option)

  it('extends the time axis by the forecast days', () => {
    expect(option.xAxis.data).toEqual(['28 Jul', '29 Jul', '30 Jul', '31 Jul', '2 Aug'])
  })

  it('draws the forecast as a dashed line that starts at the last observed point', () => {
    expect(forecast!.name).toBe('Forecast')
    expect((forecast as unknown as { lineStyle: { type: string } }).lineStyle.type).toBe('dashed')
    const data = forecast!.data as (Item | string)[]
    expect(data.slice(0, 2)).toEqual(['-', '-'])
    expect(data[2]).toMatchObject({ value: 45.2, symbolSize: 0 })
    expect(data[3]).toEqual({ value: 2.1, itemStyle: { color: PALETTE.flame } })
    expect(data[4]).toEqual({ value: 6.3, itemStyle: { color: PALETTE.fire } })
  })

  it('keeps the observed series solid and empty on forecast days', () => {
    expect((observed!.data as unknown[]).slice(3)).toEqual(['-', '-'])
    expect((observed as unknown as { lineStyle?: unknown }).lineStyle).toBeUndefined()
  })

  it('has no forecast series when the run published none', () => {
    expect(seriesOf(buildRiskTrendOption(history, thresholds))).toHaveLength(1)
  })

  it('scales the axis to the forecast risks and names them in the summary', () => {
    expect(logBounds({ ...ahead, risk: [1e-9, 1e-9, 1e-9], forecast: [{ ...ahead.forecast[0]!, risk: 0.01 }] }, null)?.max).toBe(1000)
    expect(riskTrendSummary(ahead, thresholds)).toBe(
      '3 days to 2024-07-30; latest 45 per 100k cell-days; forecast D+1 2.1 per 100k cell-days, D+3 6.3 per 100k cell-days',
    )
  })

  it('uses only palette colours', () => {
    for (const s of seriesOf(option)) {
      for (const d of s.data) if (typeof d === 'object' && d.itemStyle) expect(ALLOWED.has(d.itemStyle.color)).toBe(true)
    }
  })
})

describe('palette', () => {
  it('uses only palette stops and their mixes in every series', () => {
    const colours: string[] = []
    const collect = (option: unknown) => {
      for (const s of seriesOf(option)) {
        if (s.color) colours.push(s.color)
        for (const d of s.data) if (typeof d === 'object' && d.itemStyle) colours.push(d.itemStyle.color)
        for (const l of s.markLine?.data ?? []) colours.push(l.lineStyle.color)
      }
    }
    collect(buildShapOption([factor('rain_acc_1', 1), factor('wet_top', -1)]))
    collect(buildSourcesOption([{ key: 'imd', label: 'IMD', value: 1 }, { key: 'gauges', label: 'G', value: 2 }]))
    collect(buildRainHistoryOption(history))
    collect(buildRiskTrendOption(history, thresholds))
    expect(colours.length).toBeGreaterThan(10)
    for (const c of colours) expect(ALLOWED.has(c), c).toBe(true)
  })
})
