import { useMemo, useState } from 'react'
import type { SensorStation } from '../../data/sources'
import { formatDate } from '../../data/summary'
import styles from './FaultList.module.css'
import { faultName, isFault, stationLabel } from './stations'
import { formatTrust } from './trust'

export const ROW_HEIGHT = 44
const VIEWPORT_ROWS = 7
const OVERSCAN = 4

type SortKey = 'date' | 'station' | 'fault' | 'trust'
type Direction = 'asc' | 'desc'

const COLUMNS: ReadonlyArray<{ key: SortKey; label: string }> = [
  { key: 'date', label: 'Date' },
  { key: 'station', label: 'Station' },
  { key: 'fault', label: 'Fault type' },
  { key: 'trust', label: 'Trust' },
]

function compare(a: SensorStation, b: SensorStation, key: SortKey): number {
  switch (key) {
    case 'date':
      return 0
    case 'station':
      return stationLabel(a).localeCompare(stationLabel(b))
    case 'fault':
      return faultName(a).localeCompare(faultName(b))
    case 'trust':
      // A gauge with no value sorts after every gauge that has one.
      return (a.trust ?? Infinity) - (b.trust ?? Infinity)
  }
}

interface FaultListProps {
  stations: SensorStation[]
  date: string
  onActive?: (station: string | null) => void
}

/** Gauges with a fault on the shown date, sortable by column. Only the rows in view are in the DOM. */
export default function FaultList({ stations, date, onActive }: FaultListProps) {
  const [sort, setSort] = useState<{ key: SortKey; dir: Direction }>({ key: 'trust', dir: 'asc' })
  const [scrollTop, setScrollTop] = useState(0)

  const faults = useMemo(() => {
    const rows = stations.filter(isFault)
    const sign = sort.dir === 'asc' ? 1 : -1
    return rows.sort((a, b) => sign * compare(a, b, sort.key))
  }, [stations, sort])

  const toggle = (key: SortKey) =>
    setSort((cur) => (cur.key === key ? { key, dir: cur.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: 'asc' }))

  if (faults.length === 0) {
    return (
      <p className={styles.none}>
        No faults on {formatDate(date)}: every gauge with a value passed its checks.
      </p>
    )
  }

  const viewport = Math.min(faults.length, VIEWPORT_ROWS) * ROW_HEIGHT
  const first = Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - OVERSCAN)
  const last = Math.min(faults.length, Math.ceil((scrollTop + viewport) / ROW_HEIGHT) + OVERSCAN)

  return (
    <div className={styles.table} role="table" aria-label="Gauge faults" aria-rowcount={faults.length + 1}>
      <div className={styles.head} role="row">
        {COLUMNS.map(({ key, label }) => (
          <div
            key={key}
            role="columnheader"
            aria-sort={sort.key === key ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}
          >
            <button type="button" className={styles.sort} onClick={() => toggle(key)}>
              {label}
              <svg
                className={styles.arrow}
                data-dir={sort.key === key ? sort.dir : undefined}
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth={1.75}
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
                focusable="false"
              >
                <path d="m6 15 6-6 6 6" />
              </svg>
            </button>
          </div>
        ))}
      </div>
      <div
        className={styles.body}
        role="rowgroup"
        style={{ height: viewport }}
        onScroll={(e) => setScrollTop(e.currentTarget.scrollTop)}
        tabIndex={faults.length > VIEWPORT_ROWS ? 0 : undefined}
        aria-label={faults.length > VIEWPORT_ROWS ? 'Faults, scrollable' : undefined}
      >
        <div style={{ height: faults.length * ROW_HEIGHT, position: 'relative' }}>
          {faults.slice(first, last).map((s, i) => (
            <div
              key={s.station}
              className={styles.row}
              role="row"
              aria-rowindex={first + i + 2}
              style={{ top: (first + i) * ROW_HEIGHT, height: ROW_HEIGHT }}
              tabIndex={0}
              onPointerEnter={() => onActive?.(s.station)}
              onPointerLeave={() => onActive?.(null)}
              onFocus={() => onActive?.(s.station)}
              onBlur={() => onActive?.(null)}
            >
              <div role="cell" className="num">
                {formatDate(date)}
              </div>
              <div role="cell">
                <span className={styles.name}>{stationLabel(s)}</span>
                <span className={styles.id}>{s.station}</span>
              </div>
              <div role="cell">
                <span className={styles.tag}>{faultName(s)}</span>
                {s.genuineExtreme && <span className={styles.id}>Genuine extreme rain</span>}
              </div>
              <div role="cell" className="num">
                {formatTrust(s.trust)}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
