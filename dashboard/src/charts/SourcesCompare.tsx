import EChart from './EChart'
import { buildSourcesOption, type RainBar, sourcesSummary } from './sourcesOption'

/** The day's rain from each source side by side (for a forecast: observed through the run date, and the GFS forecast). */
export default function SourcesCompare({ bars, title = 'Rain today by source' }: { bars: readonly RainBar[]; title?: string }) {
  return <EChart option={buildSourcesOption(bars)} height={230} label={`${title}: ${sourcesSummary(bars)}`} />
}
