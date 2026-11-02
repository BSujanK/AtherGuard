import { useQueryClient } from '@tanstack/react-query'
import { ApiError } from '../data/api'
import { useGrid, useMode, queryKeys } from '../data/hooks'
import { formatCount, formatDate, modeLabel } from '../data/summary'
import EmptyState from './EmptyState'
import styles from './ViewFrame.module.css'

interface ViewFrameProps {
  title: string
  /** One sentence on what the finished view shows. */
  blurb: string
  /** Where the panel sits: over the map it sits in the bottom-right corner, clear of the terrain. */
  placement?: 'top' | 'bottom-right'
}

/**
 * Shared page frame for the three views. It owns the states every view has to handle (loading,
 * API unreachable, no data) so the views only render once there is data to show.
 */
export default function ViewFrame({ title, blurb, placement = 'top' }: ViewFrameProps) {
  const queryClient = useQueryClient()
  const mode = useMode()
  const latest = mode.data && mode.data.mode !== 'none' ? mode.data.latest_date : null
  const grid = useGrid(latest, 0)

  if (mode.isPending) {
    return (
      <div className={styles.frame} data-placement={placement}>
        <h1 className="sr-only">{title}</h1>
        <p className={styles.loading} role="status">
          Checking for data
        </p>
      </div>
    )
  }

  if (mode.isError) {
    const unreachable = !(mode.error instanceof ApiError) || mode.error.status === 0
    return (
      <div className={styles.frame} data-placement={placement}>
        <h1 className="sr-only">{title}</h1>
        <EmptyState
          title={unreachable ? 'Cannot reach the AetherGuard API' : 'The API returned an error'}
          action={
            <button type="button" onClick={() => void queryClient.invalidateQueries({ queryKey: queryKeys.mode })}>
              Try again
            </button>
          }
        >
          {mode.error.message} The dashboard keeps trying and will fill in as soon as the API answers.
        </EmptyState>
      </div>
    )
  }

  if (mode.data.mode === 'none') {
    return (
      <div className={styles.frame} data-placement={placement}>
        <h1 className="sr-only">{title}</h1>
        <EmptyState title="No data yet">
          There is no live run and no replay set to show. This view fills in on its own as soon as one lands.
        </EmptyState>
      </div>
    )
  }

  return (
    <div className={styles.frame} data-placement={placement}>
      <section className={styles.panel}>
        <h1>{title}</h1>
        <p>{blurb}</p>
        <dl className={styles.facts}>
          <div>
            <dt>Source</dt>
            <dd>
              {modeLabel(mode.data.mode)}, {mode.data.set}
            </dd>
          </div>
          <div>
            <dt>Data through</dt>
            <dd className="num">{formatDate(mode.data.latest_date)}</dd>
          </div>
          <div>
            <dt>Cells scored</dt>
            <dd className="num">{grid.data ? formatCount(grid.data.n) : 'loading'}</dd>
          </div>
        </dl>
      </section>
    </div>
  )
}
