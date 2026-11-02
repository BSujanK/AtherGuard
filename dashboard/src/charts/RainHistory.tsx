import type { CellHistory } from '../data/types'
import EChart from './EChart'
import { buildRainHistoryOption, rainHistorySummary } from './rainHistoryOption'

/** Daily rain by source over the last 30 days. */
export default function RainHistory({ history }: { history: CellHistory }) {
  return (
    <EChart option={buildRainHistoryOption(history)} height={230} label={`Daily rain by source: ${rainHistorySummary(history)}`} />
  )
}
