import { describe, expect, it } from 'vitest'
import { buildSourceRows, type SourceRecord } from '../data/sources'
import { buildLatencyOption, type LatencyRun } from './latencyOption'
import { aetherguardTheme, hexToRgb, mixHex, PALETTE, SERIES_COLORS } from './theme'

const rec = (name: string, latencyH: number | null, ok = true): SourceRecord => ({
  name,
  ok,
  validThrough: null,
  issued: null,
  latencyH,
  error: null,
  state: null,
})

const run = (date: string, g: number): LatencyRun => ({
  date,
  rows: buildSourceRows([
    rec('imerg_late', 14.4),
    rec('imerg_early', 4.5),
    rec('gfs', g),
    rec('imd_rt', null, false),
    rec('ghcn', 116),
  ]),
})

type Series = { name: string; type: string; data: unknown[] }
const seriesOf = (option: unknown) => (option as { series: Series[] }).series

describe('buildLatencyOption', () => {
  it('draws one run as bars against expected ticks, leaving sources without a latency empty', () => {
    const [bars, expected] = seriesOf(buildLatencyOption([run('2026-10-15', 4)])) as [Series, Series]
    expect(bars.type).toBe('bar')
    expect(bars.data).toHaveLength(5)
    expect(bars.data[3]).toEqual({ value: '-' })
    expect((bars.data[2] as { value: number }).value).toBe(4)
    expect(expected.type).toBe('scatter')
    expect(expected.data[0]).toEqual([14.5, 'IMERG Late'])
  })

  it('marks a late source with flame orange and the rest with a cool blue-cyan', () => {
    const late = run('2026-10-15', 9)
    const [bars] = seriesOf(buildLatencyOption([late])) as [Series]
    const color = (i: number) => (bars.data[i] as { itemStyle: { color: string } }).itemStyle.color
    expect(color(2)).toBe(PALETTE.flame)
    expect(color(0)).toBe(mixHex(PALETTE.blue, PALETTE.cyan, 0.5))
  })

  it('becomes a line per source once there is more than one run', () => {
    const series = seriesOf(buildLatencyOption([run('2026-10-14', 4), run('2026-10-15', 5)]))
    expect(series.map((s) => s.type)).toEqual(['line', 'line', 'line', 'line', 'line'])
    expect(series[2]!.data).toEqual([4, 5])
    expect(series[3]!.data).toEqual(['-', '-'])
  })
})

describe('chart theme', () => {
  it('uses only palette stops and mixes for series colours', () => {
    expect(SERIES_COLORS.slice(0, 3)).toEqual([PALETTE.cyan, PALETTE.blue, PALETTE.lime])
    for (const c of SERIES_COLORS) expect(c).toMatch(/^#[0-9A-F]{6}$/)
    expect(aetherguardTheme.textStyle.color).toBe(PALETTE.cloud)
  })

  it('mixes linearly and rejects non-hex input', () => {
    expect(mixHex(PALETTE.ink, PALETTE.cloud, 0)).toBe(PALETTE.ink)
    expect(mixHex(PALETTE.ink, PALETTE.cloud, 1)).toBe(PALETTE.cloud)
    expect(hexToRgb(mixHex(PALETTE.ink, PALETTE.cloud, 0.5))).toEqual([120, 131, 136])
    expect(() => mixHex('red', PALETTE.cloud, 0.5)).toThrow(RangeError)
  })
})
