import { useEffect, useRef, useState } from 'react'
import type { Grid } from '../../data/types'
import { newAlertCells } from './feed'

/** How long a new alert keeps its highlight. */
export const FRESH_MS = 8000

export interface NewAlerts {
  /** Cells that reached Watch or above with the latest refresh. */
  fresh: ReadonlySet<number>
  /** Sentence for the live region; empty until something is new. */
  announcement: string
}

const NONE: NewAlerts = { fresh: new Set(), announcement: '' }

/**
 * Compares each grid that arrives with the one before it. When the stream reports a new run, the cells that have just
 * reached Watch or above are `fresh` for a few seconds, and the announcement says how many.
 */
export function useNewAlerts(grid: Grid | undefined, followingLatest: boolean): NewAlerts {
  const previous = useRef<Grid | null>(null)
  const [state, setState] = useState<NewAlerts>(NONE)

  useEffect(() => {
    if (!grid || grid === previous.current) return
    const fresh = newAlertCells(previous.current, grid, followingLatest)
    previous.current = grid
    if (fresh.size === 0) {
      setState(NONE)
      return
    }
    setState({
      fresh,
      announcement: `${fresh.size} new ${fresh.size === 1 ? 'alert' : 'alerts'} at Watch or above since the last run.`,
    })
  }, [grid, followingLatest])

  // The highlight fades after a while; the announcement stays until the next refresh replaces it.
  useEffect(() => {
    if (state.fresh.size === 0) return
    const id = setTimeout(() => setState((s) => ({ ...s, fresh: new Set() })), FRESH_MS)
    return () => clearTimeout(id)
  }, [state.fresh])

  return state
}
