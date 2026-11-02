import { useMemo } from 'react'
import { countCodes } from '../data/api'
import { useGrid, useMode } from '../data/hooks'
import { formatCount, formatDate, formatNextRun, modeLabel } from '../data/summary'
import { useStreamStatus } from '../data/stream'
import { CONFIDENCES, LEVELS } from '../data/types'
import styles from './StatusStrip.module.css'

const LEVEL_CLASS = ['normal', 'watch', 'warning', 'emergency'] as const

export default function StatusStrip() {
  const mode = useMode()
  const latest = mode.data?.latest_date
  const grid = useGrid(mode.data?.mode === 'none' ? null : latest, 0)
  const stream = useStreamStatus((s) => s.state)

  const levels = useMemo(() => (grid.data ? countCodes(grid.data.level, LEVELS.length) : null), [grid.data])
  const confidences = useMemo(
    () => (grid.data ? countCodes(grid.data.confidence, CONFIDENCES.length) : null),
    [grid.data],
  )

  const data = mode.data
  const badge = mode.isError ? 'unreachable' : data ? data.mode : 'loading'

  return (
    <header className={styles.strip} aria-label="Data status">
      <div className={styles.group}>
        <span className={styles.mode} data-mode={badge}>
          <span className={styles.dot} aria-hidden="true" />
          <strong>{mode.isError ? 'API unreachable' : data ? modeLabel(data.mode) : 'Loading'}</strong>
          {data?.set && <span className={styles.setName}>{data.set}</span>}
        </span>
        {data && data.mode !== 'none' && (
          <span className={styles.fact}>
            Data through <b className="num">{formatDate(latest ?? null)}</b>
          </span>
        )}
        {data && (
          <span className={styles.fact}>
            Next run <b className="num">{formatNextRun(data.next_run)}</b>
          </span>
        )}
        {stream === 'reconnecting' && (
          <span className={styles.reconnecting} role="status">
            Reconnecting to live updates
          </span>
        )}
      </div>

      {levels && confidences && (
        <div className={styles.group}>
          <ul className={styles.counts} aria-label="Cells by risk level">
            {LEVELS.map((name, i) => (
              <li key={name} className={styles.count}>
                <span className={styles.swatch} data-level={LEVEL_CLASS[i]} aria-hidden="true" />
                <span className="num">{formatCount(levels[i]!)}</span> {name}
              </li>
            ))}
          </ul>
          <ul className={styles.counts} aria-label="Cells by confidence">
            {CONFIDENCES.map((name, i) => (
              <li key={name} className={styles.count}>
                <span className="num">{formatCount(confidences[i]!)}</span> {name}
              </li>
            ))}
          </ul>
        </div>
      )}
    </header>
  )
}
