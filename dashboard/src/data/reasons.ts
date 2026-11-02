/**
 * Human wording for the codes the alert engine writes. The tables mirror the codes actually produced by
 * `aetherguard.alerts.confidence` (confidence causes, blind-escalation codes), `aetherguard.alerts.engine`
 * (tier and hysteresis codes) and `aetherguard.live` (causes and codes only a live run adds). An unknown code is shown
 * as its own words rather than dropped, so a new backend code is visible before this table learns it.
 */
import { GRID_FLAG, type RainRule } from './types'

export interface CodeText {
  label: string
  /** One sentence on what the code means for the reader. */
  detail: string
}

/** `confidence_causes`: why a cell-day is Degraded or Insufficient instead of High. */
export const CONFIDENCE_CAUSES: Readonly<Record<string, CodeText>> = {
  no_valid_source: {
    label: 'No valid rain source',
    detail: 'Neither the IMD grid nor the satellite estimate has a value for this cell today.',
  },
  imd_missing: {
    label: 'IMD rain missing',
    detail: 'The IMD gauge-based grid has no value for this cell today; the satellite estimate stands alone.',
  },
  chirps_missing: {
    label: 'Satellite rain missing',
    detail: 'The satellite estimate (CHIRPS in replay sets, IMERG in live runs) has no value for this cell today.',
  },
  sources_disagree: {
    label: 'Rain sources disagree',
    detail: 'The IMD and satellite 3-day totals differ by more than the range seen in development.',
  },
  stations_flagged_nearby: {
    label: 'Gauges flagged nearby',
    detail: 'A rain gauge within 100 km was flagged by the integrity checks in the last 7 days.',
  },
  station_out_of_distribution: {
    label: 'Gauge behaving unusually',
    detail: 'A gauge within 100 km reports far more flags than in its own recent history.',
  },
  all_nearby_stations_untrusted: {
    label: 'No trusted gauge nearby',
    detail: 'Gauges exist within 100 km, but none is currently trusted.',
  },
  model_input_missing: {
    label: 'Model input missing',
    detail: 'The rain inputs the hazard model needs are missing, so this cell got no risk score today.',
  },
  nowcast_tail_persisted: {
    label: 'Last hours of rain carried forward',
    detail: 'The newest hours of today’s rain were not available yet and were carried over from the day before.',
  },
  forecast_input_missing: {
    label: 'Forecast input missing',
    detail: 'The forecast rain this day needs is missing, so this cell got no risk score for it.',
  },
  forecast_uncertainty_uncalibrated: {
    label: 'Forecast uncertainty not calibrated',
    detail: 'No forecast-skill calibration exists yet, so confidence is capped at Degraded.',
  },
  ensemble_disagrees: {
    label: 'Ensemble disagrees',
    detail: 'Most of the 20 ensemble models put this cell lower than the main model does.',
  },
  forecast_day: {
    label: 'Forecast day',
    detail: 'No rain has been measured for this day yet; the rain behind it comes from a weather forecast, named under Rain behind this forecast.',
  },
  observed_through_d_high: {
    label: 'Observed rain was reliable',
    detail: 'The rain measured up to the issue day had High confidence.',
  },
  observed_through_d_degraded: {
    label: 'Observed rain was uncertain',
    detail: 'The rain measured up to the issue day had Degraded confidence.',
  },
  observed_through_d_insufficient: {
    label: 'Observed rain was missing',
    detail: 'The rain measured up to the issue day was insufficient.',
  },
  forecast_widened: {
    label: 'Interval widened for the forecast',
    detail: 'The risk range was widened by how far forecast-driven risk has strayed from observed risk in past seasons.',
  },
}

/** `reason_codes`: what put the cell at its level. */
export const REASON_CODES: Readonly<Record<string, CodeText>> = {
  risk_above_watch: {
    label: 'Risk above the Watch threshold',
    detail: 'The calibrated risk is at or above the Watch threshold.',
  },
  risk_above_warning: {
    label: 'Risk above the Warning threshold',
    detail: 'The calibrated risk is at or above the Warning threshold.',
  },
  risk_above_emergency: {
    label: 'Risk above the Emergency threshold',
    detail: 'The calibrated risk is at or above the Emergency threshold.',
  },
  uncertain_high: {
    label: 'Upper estimate reaches Watch',
    detail: 'The best estimate is below Watch but the upper end of its likely range reaches it, so the cell was raised to Watch.',
  },
  sources_disagree_heavy_rain: {
    label: 'Heavy rain while sources disagree',
    detail: 'The rain sources are missing or disagree and one of them shows heavy rain, so the cell was raised to at least Watch.',
  },
  sensors_untrusted_heavy_rain: {
    label: 'Heavy rain while gauges are untrusted',
    detail: 'Nearby gauges are flagged or behaving unusually and some source shows heavy rain, so the cell was raised to at least Watch.',
  },
  nowcast_tail_persisted_heavy_rain: {
    label: 'Heavy rain while the newest rain hours are missing',
    detail: 'The newest hours of today’s rain were carried over from yesterday and a source shows heavy rain, so the cell was raised to at least Watch.',
  },
  hysteresis_hold: {
    label: 'Held at a higher level',
    detail: 'The risk has fallen, but the level is held until it stays lower for a couple of days, so alerts do not flap.',
  },
  model_input_missing: {
    label: 'No risk score today',
    detail: 'The cell keeps the level it had the day before because its model inputs are missing.',
  },
  no_recent_rain: {
    label: 'Capped: no recent rain',
    detail: 'Too little rain fell in the last 7 days for a landslide alert (below the rain-trigger minimum), so the level was lowered: Warning and Emergency to Watch, Watch to Normal.',
  },
  held_while_blind: {
    label: 'Held while inputs are missing',
    detail: 'The cell has had no risk score for a day or two, so its last level is kept for at most 2 days, then lowered one level a day.',
  },
}

/** What a confidence state means; a forecast day has no observation, so its text never speaks of agreeing sources. */
const OBSERVED_MEANING: Readonly<Record<string, string>> = {
  High: 'Both rain sources are valid and agree, or a trusted gauge agrees with the grid, and no nearby gauge is flagged.',
  Degraded: 'A rain source is missing or the sources disagree, or a nearby gauge has a problem.',
  Insufficient: 'There is no valid rain source today, or every nearby gauge is flagged while the sources disagree.',
}
const FORECAST_MEANING: Readonly<Record<string, string>> = {
  Degraded: 'A forecast: the rain of this day comes from a weather forecast, not a measurement, so it is never rated High.',
  Insufficient: 'The forecast inputs this day needs are missing.',
}

export function confidenceMeaning(state: string, forecast: boolean): string {
  return (forecast ? FORECAST_MEANING : OBSERVED_MEANING)[state] ?? ''
}

/** A label inside a sentence: its first letter in lower case unless it starts an acronym ("IMD rain missing"). */
const lowerFirst = (label: string): string => (/^[A-Z][a-z]/.test(label) ? `${label.charAt(0).toLowerCase()}${label.slice(1)}` : label)

const humanise = (code: string): CodeText => {
  const words = code.replace(/_/g, ' ').trim()
  return { label: words.charAt(0).toUpperCase() + words.slice(1), detail: 'A code this dashboard has no description for yet.' }
}

/** The one-line reasons a cell sits above the level its risk gives, from the grid's `GRID_FLAG` bits (none when unflagged). */
export function raisedReasons(flags: number): string[] {
  const lines: string[] = []
  if (flags & GRID_FLAG.blindRaised) {
    const code = flags & GRID_FLAG.gaugesUntrusted ? 'sensors_untrusted_heavy_rain' : 'sources_disagree_heavy_rain'
    const label = reasonCode(code).label
    lines.push(`Raised: ${lowerFirst(label)}`)
  }
  if (flags & GRID_FLAG.held) lines.push(`${reasonCode('hysteresis_hold').label} from yesterday`)
  return lines
}

export const confidenceCause = (code: string): CodeText => CONFIDENCE_CAUSES[code] ?? humanise(code)

/** A `<cause>_heavy_rain` code the table does not list is spelt out from the cause it names, when that is a known one. */
export function reasonCode(code: string): CodeText {
  const known = REASON_CODES[code]
  if (known) return known
  const cause = code.endsWith('_heavy_rain') ? CONFIDENCE_CAUSES[code.slice(0, -'_heavy_rain'.length)] : undefined
  if (cause) {
    return {
      label: `Heavy rain while: ${lowerFirst(cause.label)}`,
      detail: `${cause.detail} Some source shows heavy rain, so the cell was raised to at least Watch.`,
    }
  }
  return humanise(code)
}

/** The level the rain cap lowers a level to (`post_rules_v3.json`: Warning and Emergency to Watch, Watch to Normal). */
const CAPPED_TO: Readonly<Record<string, string>> = { Emergency: 'Watch', Warning: 'Watch', Watch: 'Normal' }
const TIER_CODES: readonly [string, string][] = [
  ['risk_above_emergency', 'Emergency'],
  ['risk_above_warning', 'Warning'],
  ['risk_above_watch', 'Watch'],
]

const mmText = (mm: number): string => mm.toLocaleString('en-US', { maximumFractionDigits: 1 })

/**
 * Why a level was capped, in plain words, or null when the cell was not capped:
 * "Model risk is in the Emergency range, but there was only 0 mm of rain in the last 7 days (rain trigger: 11.5 mm),
 * so the level is capped at Watch." The range is the one the tier code of the cell names (the level the risk alone
 * gives); the numbers come from the run when it kept them.
 */
export function cappedExplanation(reasonCodes: readonly string[], rule: RainRule | null): string | null {
  if (!reasonCodes.includes('no_recent_rain')) return null
  const tier = TIER_CODES.find(([code]) => reasonCodes.includes(code))?.[1]
  const from = tier ?? (reasonCodes.includes('uncertain_high') ? 'Watch' : null)
  const to = rule?.cappedTo ?? (from ? CAPPED_TO[from] : null)
  const days = rule?.windowDays ?? 7
  const rain =
    rule?.rainMm === null || rule?.rainMm === undefined
      ? `too little rain in the last ${days} days`
      : rule.rainMm === 0
        ? `no rain in the last ${days} days`
        : `only ${mmText(rule.rainMm)} mm of rain in the last ${days} days`
  const trigger = rule?.minimumMm === null || rule?.minimumMm === undefined ? '' : ` (rain trigger: ${mmText(rule.minimumMm)} mm)`
  const subject = tier
    ? `Model risk is in the ${tier} range`
    : from
      ? `The upper end of the risk range reaches ${from}`
      : 'The model risk would give a higher level'
  return `${subject}, but there was ${rain}${trigger}, so the level is capped${to ? ` at ${to}` : ''}.`
}

/** Names of the hazard model's inputs (`card.json` columns) as a reader would say them. */
export const FEATURE_LABELS: Readonly<Record<string, string>> = {
  rain_acc_1: 'Rain, today',
  rain_acc_3: 'Rain, last 3 days',
  rain_acc_5: 'Rain, last 5 days',
  rain_acc_7: 'Rain, last 7 days',
  rain_acc_14: 'Rain, last 14 days',
  rain_acc_30: 'Rain, last 30 days',
  rain_max1d_7: 'Wettest day, last 7',
  rain_max1d_30: 'Wettest day, last 30',
  rain_wetdays_30: 'Wet days, last 30',
  rain_days_since_10mm: 'Days since 10 mm',
  rain_share1_3: 'Today’s share of 3-day rain',
  rain_acc3_vs_clim: '3-day rain vs normal',
  rain_acc7_vs_clim: '7-day rain vs normal',
  rain_acc30_vs_clim: '30-day rain vs normal',
  wet_top: 'Topsoil wetness',
  wet_root: 'Root-zone wetness',
  wet_top_chg3: 'Topsoil wetness, 3-day change',
  wet_top_chg7: 'Topsoil wetness, 7-day change',
  wet_root_chg3: 'Root-zone wetness, 3-day change',
  wet_root_chg7: 'Root-zone wetness, 7-day change',
  stat_elev_mean: 'Mean elevation',
  stat_elev_std: 'Elevation spread',
  stat_relief: 'Relief',
  stat_slope_mean: 'Mean slope',
  stat_slope_p90: 'Steep slope (90th percentile)',
  stat_slope_max: 'Steepest slope',
  stat_curvature_mean: 'Surface curvature',
  stat_aspect_sin: 'Slope aspect (east-west)',
  stat_aspect_cos: 'Slope aspect (north-south)',
  stat_twi_proxy: 'Water convergence index',
}

export function featureLabel(feature: string): string {
  return FEATURE_LABELS[feature] ?? humanise(feature).label
}

/** Units of the inputs whose unit is not obvious from the name: rain totals are millimetres, elevation metres. */
export function featureValueText(feature: string, value: number | null): string {
  if (value === null) return 'n/a'
  const text = Math.abs(value) >= 100 ? Math.round(value).toLocaleString('en-US') : value.toLocaleString('en-US', { maximumSignificantDigits: 3 })
  if (/^rain_(acc_\d+|max1d_\d+)$/.test(feature)) return `${text} mm`
  if (feature === 'stat_elev_mean' || feature === 'stat_elev_std' || feature === 'stat_relief') return `${text} m`
  return text
}
