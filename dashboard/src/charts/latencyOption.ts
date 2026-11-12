import type { SourceRow } from '../data/sources'
import type { ChartOption } from './EChart'
import { FONT_DATA, mixHex, PALETTE, SERIES_COLORS, TEXT_2 } from './theme'

/** One daily run: its date and how each source did. */
export interface LatencyRun {
  date: string
  rows: SourceRow[]
}

const LOG_AXIS = { type: 'log', logBase: 10, min: 1, max: 1000, name: 'hours', nameLocation: 'end' } as const
const OK_BAR = mixHex(PALETTE.slate, PALETTE.signal, 0.5)

const esc = (s: string) => s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`)
export const latencyOf = (row: SourceRow): number | null => {
  const h = row.record?.latencyH ?? null
  return h !== null && h > 0 ? h : null
}

/** Latest run: a bar per source against a tick at its expected latency. */
function barOption(run: LatencyRun): ChartOption {
  const rows = run.rows
  return {
    grid: { left: 104, right: 24, top: 10, bottom: 34 },
    xAxis: LOG_AXIS,
    yAxis: { type: 'category', inverse: true, data: rows.map((r) => r.label) },
    tooltip: {
      trigger: 'item',
      formatter: (p: { seriesName: string; name: string; value: number | string | [number, string] }) => {
        const [hours, label] = Array.isArray(p.value) ? p.value : [p.value, p.name]
        return `${esc(label)}<br/>${esc(p.seriesName)}: <span style="font-family:${FONT_DATA}">${hours} h</span>`
      },
    },
    series: [
      {
        name: 'Latency',
        type: 'bar',
        barWidth: 12,
        itemStyle: { borderRadius: [0, 3, 3, 0] },
        data: rows.map((r) => {
          const h = latencyOf(r)
          return h === null
            ? { value: '-' }
            : { value: Number(h.toFixed(1)), itemStyle: { color: r.status === 'late' ? PALETTE.orange : OK_BAR } }
        }),
      },
      {
        name: 'Expected',
        type: 'scatter',
        symbol: 'rect',
        symbolSize: [3, 22],
        itemStyle: { color: PALETTE.ink },
        z: 5,
        data: rows.flatMap((r) => (r.expectedLatencyH === null ? [] : [[r.expectedLatencyH, r.label]])),
      },
    ],
  }
}

/** Several runs: a line per source across the run dates. */
function lineOption(runs: LatencyRun[]): ChartOption {
  const labels = runs[0]!.rows.map((r) => r.label)
  return {
    grid: { left: 52, right: 24, top: 40, bottom: 28 },
    legend: { top: 0, icon: 'roundRect', itemWidth: 14, itemHeight: 4, textStyle: { color: TEXT_2 } },
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: runs.map((r) => r.date) },
    yAxis: LOG_AXIS,
    series: labels.map((label, i) => ({
      name: label,
      type: 'line',
      symbol: ['circle', 'rect', 'triangle', 'diamond', 'pin'][i % 5],
      color: SERIES_COLORS[i % SERIES_COLORS.length],
      connectNulls: false,
      data: runs.map((run) => {
        const row = run.rows.find((r) => r.label === label)
        const h = row ? latencyOf(row) : null
        return h === null ? '-' : Number(h.toFixed(1))
      }),
    })),
  }
}

export function buildLatencyOption(runs: LatencyRun[]): ChartOption {
  return runs.length > 1 ? lineOption(runs) : barOption(runs[0]!)
}

