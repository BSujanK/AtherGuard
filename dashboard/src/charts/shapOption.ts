import { featureLabel, featureValueText } from '../data/reasons'
import type { ShapFactor } from '../data/types'
import type { ChartOption } from './EChart'
import { PALETTE, TEXT_2, TEXT_3 } from './theme'

/** Inputs shown: the five that moved the risk most. */
export const SHAP_TOP = 5

const esc = (s: string) => s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`)
export const signed = (v: number): string => `${v >= 0 ? '+' : '−'}${Math.abs(v).toFixed(2)}`

/** The factors in the order drawn: largest push first. */
export const topFactors = (shap: readonly ShapFactor[]): ShapFactor[] =>
  [...shap].sort((a, b) => Math.abs(b.contribution) - Math.abs(a.contribution)).slice(0, SHAP_TOP)

/** Horizontal bars: orange where an input raised the risk, cyan where it lowered it. */
export function buildShapOption(shap: readonly ShapFactor[]): ChartOption {
  const factors = topFactors(shap)
  return {
    grid: { left: 150, right: 56, top: 12, bottom: 34 },
    xAxis: { type: 'value', name: 'log-odds', nameLocation: 'end', scale: false, axisLabel: { color: TEXT_3, fontSize: 11 }, nameTextStyle: { color: TEXT_3, fontSize: 11 } },
    yAxis: { type: 'category', inverse: true, data: factors.map((f) => featureLabel(f.feature)), axisTick: { show: false }, axisLabel: { color: TEXT_2, fontSize: 12 } },
    tooltip: {
      trigger: 'item',
      formatter: (p: { dataIndex: number }) => {
        const f = factors[p.dataIndex]!
        return `${esc(featureLabel(f.feature))}<br/>Input: ${esc(featureValueText(f.feature, f.value))}<br/>${f.contribution >= 0 ? 'Raises' : 'Lowers'} the risk: ${signed(f.contribution)}`
      },
    },
    series: [
      {
        name: 'Contribution',
        type: 'bar',
        barWidth: 14,
        label: { show: true, position: 'right', color: TEXT_2, fontSize: 11, textBorderWidth: 0, formatter: (p: { value: number }) => signed(p.value) },
        data: factors.map((f) => ({
          value: Number(f.contribution.toFixed(4)),
          itemStyle: { color: f.contribution >= 0 ? PALETTE.orange : PALETTE.signal },
        })),
      },
    ],
  }
}

/** One sentence for assistive technology: each input, its direction and size. */
export function shapSummary(shap: readonly ShapFactor[]): string {
  return topFactors(shap)
    .map((f) => `${featureLabel(f.feature)} ${f.contribution >= 0 ? 'raises' : 'lowers'} risk by ${Math.abs(f.contribution).toFixed(2)}`)
    .join(', ')
}
