import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { ApiError, getBasemap, getCell, getCellHistory, getGrid, getMode, getPlaces, getRain } from './api'

export const queryKeys = {
  mode: ['mode'] as const,
  grid: (date: string, lead: number) => ['grid', date, lead] as const,
  rain: (date: string) => ['rain', date] as const,
  basemap: ['basemap'] as const,
  places: ['places'] as const,
  cell: (cell: number, date: string, set: string | null, lead = 0) => ['cell', cell, date, set, lead] as const,
  history: (cell: number, date: string, set: string | null) => ['history', cell, date, set] as const,
  sources: ['sources'] as const,
}

export function useMode() {
  return useQuery({
    queryKey: queryKeys.mode,
    queryFn: ({ signal }) => getMode(signal),
    staleTime: 30_000,
  })
}

/**
 * Grid for one date and lead; disabled until a date is known. With `keepPrevious` the last grid
 * stays in `data` (flagged by `isPlaceholderData`) while the next one loads, so a map does not blank.
 */
export function useGrid(date: string | null | undefined, lead = 0, keepPrevious = false) {
  return useQuery({
    queryKey: queryKeys.grid(date ?? '', lead),
    queryFn: ({ signal }) => getGrid(date!, lead, signal),
    enabled: Boolean(date),
    staleTime: 60_000,
    retry: retryUnlessMissing,
    placeholderData: keepPrevious ? keepPreviousData : undefined,
  })
}

/** A 404 means the store has no such day or lead; asking again cannot change that. */
function retryUnlessMissing(failures: number, error: Error): boolean {
  return !(error instanceof ApiError && error.status === 404) && failures < 1
}

/** The day's coarse rain field; a 404 (no feature table for the day) is a normal "no rain data" state. */
export function useRain(date: string | null | undefined) {
  return useQuery({
    queryKey: queryKeys.rain(date ?? ''),
    queryFn: ({ signal }) => getRain(date!, signal),
    enabled: Boolean(date),
    staleTime: 60_000,
    retry: retryUnlessMissing,
  })
}

/** The whole-India relief, mask and outlines the map and the gauge map are drawn on; static for the life of a build. */
export function useBasemap() {
  return useQuery({
    queryKey: queryKeys.basemap,
    queryFn: ({ signal }) => getBasemap(signal),
    staleTime: Infinity,
    retry: 1,
  })
}

/**
 * The place names of the cells, fetched once per page load: hovering a cell reads this cached table and never asks the
 * API again. `data` is null when the API has no table (coordinates are shown then) and undefined while it loads.
 */
export function usePlaces() {
  return useQuery({
    queryKey: queryKeys.places,
    queryFn: ({ signal }) => getPlaces(signal),
    staleTime: Infinity,
    gcTime: Infinity,
    retry: false,
  })
}

/**
 * One cell's explanation for a date. `lead` 1 to 3 asks for the forecast of the live run of `date` for that many days
 * later. A 404 (unknown cell or date) is an answer, so it is not retried.
 */
export function useCell(cell: number | null, date: string | null | undefined, set: string | null, lead = 0) {
  return useQuery({
    queryKey: queryKeys.cell(cell ?? -1, date ?? '', set, lead),
    queryFn: ({ signal }) => getCell(cell!, date!, set, lead, signal),
    enabled: cell !== null && Boolean(date),
    staleTime: 60_000,
    retry: retryUnlessMissing,
  })
}

/** The 30 days of risk and rain ending at `date`; a cell with no rows in the window is a 404. */
export function useCellHistory(cell: number | null, date: string | null | undefined, set: string | null) {
  return useQuery({
    queryKey: queryKeys.history(cell ?? -1, date ?? '', set),
    queryFn: ({ signal }) => getCellHistory(cell!, date!, set, 30, signal),
    enabled: cell !== null && Boolean(date),
    staleTime: 60_000,
    retry: retryUnlessMissing,
  })
}
