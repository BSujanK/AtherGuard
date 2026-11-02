import type { CellHistory, Thresholds } from '../data/types'
import EChart from './EChart'
import { buildRiskTrendOption, riskTrendSummary } from './riskTrendOption'

/** Daily risk over the last 30 days against the Watch, Warning and Emergency thresholds. */
export default function RiskTrend({ history, thresholds }: { history: CellHistory; thresholds: Thresholds | null | undefined }) {
  return (
    <EChart
      option={buildRiskTrendOption(history, thresholds)}
      height={230}
      label={`Daily risk per 100k cell-days: ${riskTrendSummary(history, thresholds)}`}
    />
  )
}
