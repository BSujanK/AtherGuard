import { describeRisk, formatDayMonth, LEAD_LABELS, RISK_SCALE } from '../data/summary'
import { type CellHistory, LEVELS, type Thresholds } from '../data/types'
import type { ChartOption } from './EChart'
import { PALETTE, TEXT_3 } from './theme'

/** Point colour by level, cool to hot; Normal is the royal blue itself so it stays visible on the dark panel. */
export const LEVEL_POINT = [PALETTE.blue, PALETTE.lime, PALETTE.flame, PALETTE.fire] as const

const esc = (s: string) => s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`)

/** One day on the time axis: an observed day of the history, or a forecast day after it. */
export interface TrendPoint {
  date: string
  risk: number | null
  level: number
  /** The forecast lead (1 to 3); 0 for an observed day. */
  lead: number
}

/** The history's days, then the forecast days of its run (a forecast day that is already in the history is not repeated). */
export function trendPoints(history: CellHistory): TrendPoint[] {
  const observed = history.dates.map((date, i) => ({ date, risk: history.risk[i] ?? null, level: history.level[i] ?? 0, lead: 0 }))
  const known = new Set(history.dates)
  const ahead = history.forecast
    .filter((f) => !known.has(f.targetDate))
    .map((f) => ({ date: f.targetDate, risk: f.risk, level: f.level, lead: f.lead }))
  return [...observed, ...ahead]
}

/**
 * Axis bounds in per-100k units: whole powers of ten around the data and the thresholds, so a log axis keeps the three
 * reference lines apart. Null when some risk is zero (it has no place on a log axis) or nothing can be plotted.
 */
export function logBounds(history: CellHistory, thresholds: Thresholds | null | undefined): { min: number; max: number } | null {
  const values = trendPoints(history)
    .map((p) => p.risk)
    .filter((r): r is number => r !== null)
  if (values.length === 0 || values.some((r) => r <= 0)) return null
  const all = [...values, ...(thresholds ? [thresholds.watch, thresholds.emergency] : [])].map((r) => r * RISK_SCALE)
  return {
    min: 10 ** Math.floor(Math.log10(Math.min(...all)) + 1e-9),
    max: 10 ** Math.ceil(Math.log10(Math.max(...all)) - 1e-9),
  }
}

const pointOf = (p: TrendPoint) => ({
  value: Number((p.risk! * RISK_SCALE).toPrecision(4)),
  itemStyle: { color: LEVEL_POINT[p.level as 0 | 1 | 2 | 3] ?? TEXT_3 },
})

/**
 * Risk per 100k cell-days over the history window, points coloured by level, with the three thresholds as reference
 * lines. The forecast days of the run follow on the same axis as a dashed line from the last observed point, so what
 * has happened and what is expected read differently. Risk spans orders of magnitude, so the axis is logarithmic
 * whenever every plotted risk is above zero.
 */
export function buildRiskTrendOption(history: CellHistory, thresholds: Thresholds | null | undefined): ChartOption {
  const bounds = logBounds(history, thresholds)
  const points = trendPoints(history)
  const lastObserved = points.findLastIndex((p) => p.lead === 0 && p.risk !== null)
  const lines = thresholds
    ? [
        { name: 'Watch', value: thresholds.watch, color: PALETTE.lime },
        { name: 'Warning', value: thresholds.warning, color: PALETTE.flame },
        { name: 'Emergency', value: thresholds.emergency, color: PALETTE.fire },
      ]
    : []
  const hasForecast = points.some((p) => p.lead > 0)
  return {
    grid: { left: 60, right: 76, top: 20, bottom: 32 },
    tooltip: {
      trigger: 'axis',
      formatter: (items: { dataIndex: number }[]) => {
        const p = points[items[0]?.dataIndex ?? 0]
        if (!p) return ''
        const level = LEVELS[p.level as 0 | 1 | 2 | 3] ?? ''
        const kind = p.lead > 0 ? `<br/>Forecast ${LEAD_LABELS[p.lead as 1 | 2 | 3]}, not yet observed` : ''
        return `${esc(p.date)}${kind}<br/>${level}<br/>${esc(describeRisk(p.risk, thresholds?.watch).primary)}`
      },
    },
    xAxis: { type: 'category', data: points.map((p) => formatDayMonth(p.date)), boundaryGap: false, axisLabel: { color: TEXT_3, fontSize: 11 } },
    yAxis: bounds
      ? { type: 'log', logBase: 10, name: 'per 100k', min: bounds.min, max: bounds.max, axisLabel: { color: TEXT_3, fontSize: 11 }, nameTextStyle: { color: TEXT_3, fontSize: 11 } }
      : { type: 'value', name: 'per 100k', min: 0, axisLabel: { color: TEXT_3, fontSize: 11 }, nameTextStyle: { color: TEXT_3, fontSize: 11 } },
    series: [
      {
        name: 'Risk',
        type: 'line',
        color: PALETTE.cyan,
        symbol: 'circle',
        symbolSize: 8,
        connectNulls: false,
        data: points.map((p) => (p.lead > 0 || p.risk === null ? '-' : pointOf(p))),
        markLine: {
          silent: true,
          symbol: 'none',
          lineStyle: { type: 'dashed', width: 1 },
          label: { position: 'end', formatter: '{b}', fontSize: 11 },
          data: lines.map((l) => ({
            name: l.name,
            yAxis: l.value * RISK_SCALE,
            lineStyle: { color: l.color },
            label: { color: l.color, fontSize: 11 },
          })),
        },
      },
      ...(hasForecast
        ? [
            {
              name: 'Forecast',
              type: 'line',
              color: PALETTE.cyan,
              symbol: 'emptyCircle',
              symbolSize: 9,
              connectNulls: false,
              lineStyle: { type: 'dashed', width: 2 },
              data: points.map((p, i) => {
                if (p.risk === null) return '-'
                if (p.lead > 0) return pointOf(p)
                return i === lastObserved ? { value: Number((p.risk * RISK_SCALE).toPrecision(4)), symbolSize: 0 } : '-'
              }),
            },
          ]
        : []),
    ],
  }
}

export function riskTrendSummary(history: CellHistory, thresholds: Thresholds | null | undefined): string {
  const last = history.risk.length - 1
  const ahead = history.forecast
    .map((f) => `${LEAD_LABELS[f.lead as 1 | 2 | 3] ?? `D+${f.lead}`} ${describeRisk(f.risk, thresholds?.watch).primary}`)
    .join(', ')
  return (
    `${history.dates.length} days to ${history.dates[last] ?? 'n/a'}; latest ${describeRisk(history.risk[last] ?? null, thresholds?.watch).primary}` +
    (ahead ? `; forecast ${ahead}` : '')
  )
}
