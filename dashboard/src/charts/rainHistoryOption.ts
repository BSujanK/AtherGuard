import { formatDayMonth } from '../data/summary'
import type { CellHistory } from '../data/types'
import type { ChartOption } from './EChart'
import { SOURCE_COLORS } from './sourcesOption'
import { TEXT_2, TEXT_3 } from './theme'

/** The satellite slot of the alert table is IMERG in live runs and CHIRPS in the replay sets. */
export const satelliteName = (set: string): string => (set === 'live' ? 'IMERG' : 'CHIRPS')

const esc = (s: string) => s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`)

/** 1-day rain per source over the history window: a line per source, a gap where a source had no value. */
export function buildRainHistoryOption(history: CellHistory): ChartOption {
  const line = (name: string, color: string, symbol: string, values: (number | null)[]) => ({
    name,
    type: 'line',
    color,
    symbol,
    symbolSize: 6,
    connectNulls: false,
    data: values.map((v) => (v === null ? '-' : Number(v.toFixed(1)))),
  })
  return {
    grid: { left: 56, right: 16, top: 44, bottom: 32 },
    legend: { top: 0, icon: 'roundRect', itemWidth: 14, itemHeight: 4, textStyle: { color: TEXT_2, fontSize: 12 } },
    tooltip: {
      trigger: 'axis',
      formatter: (items: { axisValue: string; marker: string; seriesName: string; value: number | string }[]) =>
        `${esc(String(items[0]?.axisValue ?? ''))}<br/>` +
        items
          .map((i) => `${i.marker} ${esc(i.seriesName)}: ${typeof i.value === 'number' ? `${i.value} mm` : 'not available'}`)
          .join('<br/>'),
    },
    xAxis: { type: 'category', data: history.dates.map(formatDayMonth), boundaryGap: false, axisLabel: { color: TEXT_3, fontSize: 11 } },
    yAxis: { type: 'value', name: 'mm/day', min: 0, axisLabel: { color: TEXT_3, fontSize: 11 }, nameTextStyle: { color: TEXT_3, fontSize: 11 } },
    series: [
      line('IMD', SOURCE_COLORS.imd, 'circle', history.rain.imd),
      line(satelliteName(history.set), SOURCE_COLORS.satellite, 'rect', history.rain.satellite),
      line('Trusted gauges', SOURCE_COLORS.gauges, 'triangle', history.rain.gauges),
    ],
  }
}

export function rainHistorySummary(history: CellHistory): string {
  const last = history.dates.length - 1
  const at = (v: (number | null)[]) => (v[last] === null || v[last] === undefined ? 'not available' : `${v[last]!.toFixed(1)} mm`)
  return (
    `${history.dates.length} days to ${history.dates[last] ?? 'n/a'}; latest IMD ${at(history.rain.imd)}, ` +
    `${satelliteName(history.set)} ${at(history.rain.satellite)}, trusted gauges ${at(history.rain.gauges)}`
  )
}
