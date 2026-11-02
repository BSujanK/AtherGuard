import { useQueryClient } from '@tanstack/react-query'
import { ApiError } from '../../data/api'
import {
  buildSourceRows,
  DAILY_RUN_LABEL,
  formatIst,
  formatLatency,
  sourcesStatusKey,
  type SourceHealth as Health,
  type SourceRow,
  useSourcesStatus,
} from '../../data/sources'
import { useStreamStatus } from '../../data/stream'
import { formatDate } from '../../data/summary'
import EmptyState from '../EmptyState'
import styles from './SourceHealth.module.css'
import { useUpdateFlash } from './useUpdateFlash'

const STATUS_LABEL: Record<Health, string> = { ok: 'OK', late: 'Late', failed: 'Failed', unknown: 'Unknown' }

function StatusBadge({ status }: { status: Health }) {
  return (
    <span className={styles.badge} data-status={status}>
      <span className={styles.mark} aria-hidden="true" />
      {STATUS_LABEL[status]}
    </span>
  )
}

function Row({ row }: { row: SourceRow }) {
  const { record, status } = row
  return (
    <tr data-source={row.key} data-status={status}>
      <th scope="row">
        <span className={styles.name}>{row.label}</span>
        {record?.error && (
          <span className={styles.error} title={record.error}>
            {record.error}
          </span>
        )}
        {record === null && <span className={styles.error}>Not reported in this run</span>}
      </th>
      <td>
        <StatusBadge status={status} />
      </td>
      <td className="num">{status === 'failed' ? '—' : formatIst(record?.issued ?? null)}</td>
      <td className="num">{formatIst(record?.validThrough ?? null)}</td>
      <td className={`num ${styles.latency}`}>
        {formatLatency(record?.latencyH ?? null)}
        {row.expectedLatencyH !== null && <span className={styles.expected}>exp. {row.expectedLatencyH}</span>}
      </td>
    </tr>
  )
}

/** Freshness of each upstream source from the newest daily run, kept current by the stream's `sources` events. */
export default function SourceHealth() {
  const queryClient = useQueryClient()
  const query = useSourcesStatus()
  const stream = useStreamStatus((s) => s.state)
  const flashing = useUpdateFlash(query.dataUpdatedAt)

  if (query.isPending) {
    return (
      <p className={styles.note} role="status">
        Checking source health
      </p>
    )
  }

  if (query.isError) {
    const unreachable = !(query.error instanceof ApiError) || query.error.status === 0
    return (
      <EmptyState
        title={unreachable ? 'Cannot reach the AetherGuard API' : 'Source health could not be read'}
        action={
          <button type="button" onClick={() => void queryClient.invalidateQueries({ queryKey: sourcesStatusKey })}>
            Try again
          </button>
        }
      >
        {query.error.message}
      </EmptyState>
    )
  }

  const status = query.data
  if (!status.available) {
    return (
      <EmptyState title="No live run yet">
        <span className={styles.reason}>{status.reason}</span>
        <span className={styles.explain}>
          Source health fills in after the first daily run ({DAILY_RUN_LABEL}). It will list IMERG Late, IMERG Early, GFS,
          IMD real-time and GHCN gauges with when each last delivered, how far its data reaches, how late it arrived and
          whether it is on time.
        </span>
      </EmptyState>
    )
  }

  const rows = buildSourceRows(status.sources)
  return (
    <div className={styles.panel}>
      <div className={styles.meta}>
        <span>
          Run of <b className="num">{status.run.date ? formatDate(status.run.date) : 'unknown date'}</b>
          {status.run.generatedUtc && (
            <>
              , written <span className="num">{formatIst(status.run.generatedUtc)}</span> IST
            </>
          )}
        </span>
        {status.run.backtest && <span className={styles.tag}>Backtest</span>}
        <span className={styles.updated} data-flash={flashing} role="status">
          <span className={styles.pulse} aria-hidden="true" />
          {flashing ? 'Updated just now' : 'Live'}
        </span>
      </div>
      {stream === 'reconnecting' && (
        <p className={styles.warn} role="status">
          Live updates are paused while the connection is restored. These figures may be out of date.
        </p>
      )}
      <table className={styles.table}>
        <caption className="sr-only">Freshness of each data source in the newest run. Times are in IST.</caption>
        <thead>
          <tr>
            <th scope="col">Source</th>
            <th scope="col">Status</th>
            <th scope="col">Last success</th>
            <th scope="col">Valid through</th>
            <th scope="col">Latency (h)</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <Row key={row.key} row={row} />
          ))}
        </tbody>
      </table>
      {status.run.rainProvenance.length > 0 && (
        <p className={styles.foot} data-testid="rain-provenance">
          Rain provenance:{' '}
          {status.run.rainProvenance.map((p) => `${p.day} from ${p.product.split('+').join(' + ')}`).join('; ')}.
        </p>
      )}
      <p className={styles.foot}>
        Times in IST. Status is the verdict the daily run recorded; without one, late means slower than the measured
        median plus one hour.
      </p>
    </div>
  )
}
