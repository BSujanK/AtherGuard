import type { ChartOption } from './EChart'
import { mixHex, PALETTE, TEXT_2 } from './theme'

export type RainSourceKey = 'satellite' | 'imd' | 'gauges' | 'gfs'

export interface RainBar {
  key: RainSourceKey
  /** Short axis label. */
  label: string
  /** Rain of the day in mm; null when the source has no value (shown as "not available", never as zero). */
  value: number | null
}

/** One colour per source, so the same source keeps its colour next to the history chart. */
export const SOURCE_COLORS: Record<RainSourceKey, string> = {
  satellite: PALETTE.lime,
  imd: PALETTE.cyan,
  gauges: PALETTE.blue,
  gfs: mixHex(PALETTE.blue, PALETTE.cyan, 0.5),
}

const esc = (s: string) => s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`)
export const mm = (v: number): string => `${v.toLocaleString('en-US', { maximumFractionDigits: 1 })} mm`

/** Bars of the day's rain by source, side by side; a source without a value has no bar and says so on its label. */
export function buildSourcesOption(bars: readonly RainBar[]): ChartOption {
  return {
    grid: { left: 52, right: 16, top: 24, bottom: 52 },
    xAxis: {
      type: 'category',
      data: bars.map((b) => (b.value === null ? `${b.label}\nnot available` : b.label)),
      axisLabel: { interval: 0, lineHeight: 15 },
    },
    yAxis: { type: 'value', name: 'mm', min: 0 },
    tooltip: {
      trigger: 'item',
      formatter: (p: { dataIndex: number }) => {
        const b = bars[p.dataIndex]!
        return `${esc(b.label)}: ${b.value === null ? 'not available' : mm(b.value)}`
      },
    },
    series: [
      {
        name: 'Rain today',
        type: 'bar',
        barWidth: 28,
        label: {
          show: true,
          position: 'top',
          color: TEXT_2,
          textBorderWidth: 0,
          formatter: (p: { value: number | string }) => (typeof p.value === 'number' ? mm(p.value) : ''),
        },
        data: bars.map((b) =>
          b.value === null ? { value: '-' } : { value: b.value, itemStyle: { color: SOURCE_COLORS[b.key] } },
        ),
      },
    ],
  }
}

export function sourcesSummary(bars: readonly RainBar[]): string {
  return bars.map((b) => `${b.label} ${b.value === null ? 'not available' : mm(b.value)}`).join(', ')
}
