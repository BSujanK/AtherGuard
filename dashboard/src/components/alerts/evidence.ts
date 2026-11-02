import { satelliteName } from '../../charts/rainHistoryOption'
import type { RainBar } from '../../charts/sourcesOption'
import { formatDate } from '../../data/summary'
import { forecastShortName } from '../../data/certainty'
import type { CellDetail, SourceEvidence } from '../../data/types'

export interface RainRow extends RainBar {
  /** What the number is, for the list under the chart. */
  detail: string
  /** Why there is no number, when there is none. */
  missing: string
}

type RainInput = Pick<CellDetail, 'set' | 'sources' | 'forecast' | 'forecastRain' | 'targetDate' | 'issuedDate' | 'detailMissing'> &
  Partial<Pick<CellDetail, 'forecastSource'>>

const NO_EVIDENCE: SourceEvidence = {
  imd1: null,
  satellite1: null,
  gauge1: null,
  imd3: null,
  satellite3: null,
  gauge3: null,
  gaugeMax1: null,
  disagreement3: null,
  rainSource: null,
  max1day: null,
  spread1day: null,
}

/**
 * The rain from each source, in the order the drawer shows them. A value the API reports as missing stays null.
 * For a cell-day (lead 0) the sources are the day's own rain and the forecast is not stored per cell. For a forecast the
 * first three are what was observed through the run date and the last (key `gfs`, labelled with the source the run used:
 * GFS or ECMWF) is the forecast total for the target day, so the bars read "rain so far" next to "rain expected".
 */
export function rainRows(detail: RainInput): RainRow[] {
  const satellite = satelliteName(detail.set)
  const model = forecastShortName(detail.forecastSource)
  const forecast = detail.forecast
  const sources = forecast ? (detail.forecastRain?.observed ?? NO_EVIDENCE) : detail.sources
  const through = forecast ? ` on ${formatDate(detail.forecastRain?.observedDate ?? detail.issuedDate)}` : ' today'
  const target = forecast ? (detail.forecastRain?.days.find((d) => d.date === detail.targetDate) ?? null) : null
  return [
    {
      key: 'satellite',
      label: satellite,
      value: sources.satellite1,
      detail: `${satellite} satellite estimate at the cell${forecast ? through : ''}`,
      missing: `${satellite} has no value for this cell${through}`,
    },
    {
      key: 'imd',
      label: 'IMD',
      value: sources.imd1,
      detail: !forecast && sources.rainSource === 'imd' ? 'IMD gauge-based grid, the rain the model used' : `IMD gauge-based grid${forecast ? through : ''}`,
      missing: `IMD has no value for this cell${through}`,
    },
    {
      key: 'gauges',
      label: 'Gauges',
      value: sources.gauge1,
      detail: `Trust-weighted mean of the unflagged rain gauges within 100 km${forecast ? through : ''}`,
      missing: `No trusted gauge within 100 km reported${through}`,
    },
    {
      key: 'gfs',
      label: model,
      value: target?.mm ?? null,
      detail: forecast ? `${model} forecast rain for ${formatDate(detail.targetDate)}` : `${model} forecast rain`,
      missing: forecast
        ? detail.detailMissing
          ? 'This run predates per-lead detail, so the forecast rain was not stored'
          : `${model} has no forecast rain for this cell on ${formatDate(detail.targetDate)}`
        : `${model} forecast rain is only used for the D+1 to D+3 forecasts and is not stored per cell`,
    },
  ]
}
