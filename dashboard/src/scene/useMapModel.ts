import { useEffect, useMemo, useState } from 'react'
import { ApiError } from '../data/api'
import { useBasemap, useGrid, useMode, useRain } from '../data/hooks'
import type { Basemap, Grid, ModeResponse, Rain } from '../data/types'
import { type Lead, useMapState } from '../state/map'
import { visibleCells } from './riskTexture'
import { type TerrainField, terrainField } from './terrainField'

/** Dates of a long set are limited to the most recent 30 runs on the timeline (spec 4.1). */
export const TIMELINE_DAYS = 30

export function useDebounced<T>(value: T, ms: number): T {
  const [held, setHeld] = useState(value)
  useEffect(() => {
    const id = setTimeout(() => setHeld(value), ms)
    return () => clearTimeout(id)
  }, [value, ms])
  return held
}

export type LeadStatus =
  | { state: 'loading' }
  | { state: 'ready' }
  | { state: 'unavailable'; reason: string }

export interface MapModel {
  mode: ModeResponse | undefined
  /** Dates offered on the timeline, oldest first. */
  dates: string[]
  /** The date the user is looking at: their choice, else the latest. */
  date: string | null
  /** True when the chosen date is not one the API reports (for example a stale deep link). */
  dateMissing: boolean
  lead: Lead
  grid: Grid | undefined
  /** Why there is no grid to show: the API's message, or null while loading or when there is one. */
  gridError: string | null
  gridLoading: boolean
  leadStatus: Record<1 | 2 | 3, LeadStatus>
  rain: Rain | undefined
  /** The API said it has no rain field for this date (as opposed to still loading). */
  rainMissing: boolean
  /** The whole-India base map: the window every other layer is aligned to. */
  terrain: Basemap | undefined
  /** The base map could not be loaded, so no map can be drawn. */
  terrainFailed: boolean
  field: TerrainField | undefined
  /** 1 per grid cell that passes the level and region filters. */
  visible: Uint8Array | null
}

/** Why the API does not offer `lead` for the date shown, in its own wording for a replay set; null when it does. */
function notOffered(mode: ModeResponse | undefined, date: string | null, lead: 1 | 2 | 3): string | null {
  if (mode === undefined || date === null || (mode.leads?.[date] ?? [0]).includes(lead)) return null
  return mode.mode === 'live'
    ? `the ${date} run has no forecast for this lead`
    : `replay set '${mode.set}' holds lead 0 only (requested lead ${lead})`
}

function status(query: ReturnType<typeof useGrid>, missing: string | null): LeadStatus {
  if (missing !== null) return { state: 'unavailable', reason: missing }
  if (query.isError) {
    const reason =
      query.error instanceof ApiError && query.error.status === 404
        ? query.error.message
        : 'The forecast could not be loaded.'
    return { state: 'unavailable', reason }
  }
  return query.data ? { state: 'ready' } : { state: 'loading' }
}

/**
 * Everything the 3D map, the 2D fallback and the map controls share, resolved from the view state
 * and the API: which grid to show, which leads exist for the date, rain, terrain and the filter mask.
 */
export function useMapModel(): MapModel {
  const mode = useMode()
  const chosen = useMapState((s) => s.date)
  const lead = useMapState((s) => s.lead)
  const levels = useMapState((s) => s.levels)
  const region = useMapState((s) => s.region)

  const hasData = mode.data !== undefined && mode.data.mode !== 'none'
  const all = mode.data?.dates ?? []
  const dates = all.slice(-TIMELINE_DAYS)
  const date = chosen ?? mode.data?.latest_date ?? null
  const dateMissing = hasData && date !== null && !all.includes(date)
  const queryDate = useDebounced(hasData && !dateMissing ? date : null, 120)

  const missing = {
    1: notOffered(mode.data, queryDate, 1),
    2: notOffered(mode.data, queryDate, 2),
    3: notOffered(mode.data, queryDate, 3),
  } as const
  const forecastDate = (l: 1 | 2 | 3) => (missing[l] === null ? queryDate : null)
  const main = useGrid(lead === 0 ? queryDate : forecastDate(lead), lead, true)
  const lead1 = useGrid(forecastDate(1), 1)
  const lead2 = useGrid(forecastDate(2), 2)
  const lead3 = useGrid(forecastDate(3), 3)
  const leadStatus = {
    1: status(lead1, missing[1]),
    2: status(lead2, missing[2]),
    3: status(lead3, missing[3]),
  } as const

  const unavailable = lead !== 0 && leadStatus[lead].state === 'unavailable'
  const grid = hasData && !unavailable ? main.data : undefined
  const gridError = main.isError
    ? main.error instanceof ApiError
      ? main.error.message
      : 'The risk grid could not be loaded.'
    : null

  const rainQuery = useRain(queryDate)
  const terrainQuery = useBasemap()
  const terrain = terrainQuery.data
  const field = useMemo(() => (terrain ? terrainField(terrain) : undefined), [terrain])
  const visible = useMemo(() => (grid ? visibleCells(grid, { levels, region }) : null), [grid, levels, region])

  return {
    mode: mode.data,
    dates,
    date,
    dateMissing,
    lead,
    grid,
    gridError,
    gridLoading: hasData && !dateMissing && !grid && !unavailable && gridError === null,
    leadStatus,
    rain: rainQuery.data,
    rainMissing: rainQuery.isError,
    terrain,
    terrainFailed: terrainQuery.isError,
    field,
    visible,
  }
}
