import { CERTAINTY, type ForecastSource, type Grid, LEVELS } from './types'

/** How sure a forecast row is of its level (spec section 12): the same under every rain scenario, or not. */
export interface CertaintyText {
  kind: 'firm' | 'depends'
  /** "Firm" or "Depends on rain forecast (Watch–Warning)". */
  headline: string
  /** One line on why. */
  why: string
}

const levelName = (level: number): string => LEVELS[level as 0 | 1 | 2 | 3] ?? 'Unknown'

/** "Watch–Warning", or the one level name when the range is a single level. */
export function levelRange(min: number, max: number): string {
  return min === max ? levelName(min) : `${levelName(min)}–${levelName(max)}`
}

/**
 * The certainty line of a forecast cell. `firm` means the level is the same with no further rain, with the forecast
 * and with its heavy-rain bound, i.e. set by rain already on the ground; otherwise the level depends on the rain
 * forecast and the range of levels it can take is shown. null for lead 0, an unscored cell or a table without the field.
 */
export function describeCertainty(
  code: number | 'firm' | 'depends_on_forecast' | null | undefined,
  min: number | null | undefined,
  max: number | null | undefined,
): CertaintyText | null {
  const firm = code === CERTAINTY.firm || code === 'firm'
  const depends = code === CERTAINTY.depends || code === 'depends_on_forecast'
  if (firm) return { kind: 'firm', headline: 'Firm', why: 'set by rain already fallen' }
  if (!depends) return null
  const range = min !== null && min !== undefined && max !== null && max !== undefined ? ` (${levelRange(min, max)})` : ''
  return {
    kind: 'depends',
    headline: `Depends on rain forecast${range}`,
    why: 'the level changes with how much rain comes',
  }
}

/** The certainty of the cell at grid index `index`; null where the grid has none (lead 0, or an older run). */
export function gridCertainty(grid: Grid, index: number): CertaintyText | null {
  if (grid.certainty === undefined) return null
  return describeCertainty(grid.certainty[index]!, grid.levelMin?.[index], grid.levelMax?.[index])
}

/** The forecast rain source as one phrase with its licence ("ECMWF IFS HRES (CC BY 4.0)", "GFS fallback"); null when unknown. */
export function sourceName(source: ForecastSource | null | undefined): string | null {
  return source?.label ?? null
}

/** Short name of the forecast rain source for a label or a bar: "ECMWF" or "GFS" (GFS when the run did not say). */
export function forecastShortName(source: ForecastSource | null | undefined): string {
  return source?.source?.startsWith('ecmwf') ? 'ECMWF' : 'GFS'
}

/** The certainty as a few words for a list row: "Firm" or "Depends (Watch–Warning)". */
export function certaintyShort(text: CertaintyText | null, min: number | null | undefined, max: number | null | undefined): string | null {
  if (text === null) return null
  if (text.kind === 'firm') return 'Firm'
  return min !== null && min !== undefined && max !== null && max !== undefined ? `Depends (${levelRange(min, max)})` : 'Depends'
}
