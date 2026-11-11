import EChart from './EChart'
import { buildLatencyOption, latencyOf, type LatencyRun } from './latencyOption'

interface LatencyHistoryProps {
  runs: LatencyRun[]
}

/**
 * Source latency across daily runs. With one run (all the API holds so far) it shows that run against the expected
 * latencies; from two runs on it becomes a line per source.
 */
export default function LatencyHistory({ runs }: LatencyHistoryProps) {
  if (runs.length === 0) return null
  const newest = runs[runs.length - 1]!
  const summary = newest.rows
    .map((r) => `${r.label} ${latencyOf(r) === null ? 'no latency reported' : `${latencyOf(r)!.toFixed(1)} hours`}`)
    .join(', ')
  return (
    <EChart
      option={buildLatencyOption(runs)}
      height={256}
      label={`Source latency in hours for the run of ${newest.date}: ${summary}`}
    />
  )
}
