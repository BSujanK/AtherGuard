import { useQueryClient } from '@tanstack/react-query'
import { lazy, type ReactNode, Suspense, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import EmptyState from '../components/EmptyState'
import FaultList from '../components/sensors/FaultList'
import GaugeMap from '../components/sensors/GaugeMap'
import SourceHealth from '../components/sensors/SourceHealth'
import { isFault, isMostlyMissing } from '../components/sensors/stations'
import { ApiError } from '../data/api'
import { useBasemap, useMode } from '../data/hooks'
import { buildSourceRows, sensorsKey, useSensors, useSourcesStatus } from '../data/sources'
import { formatDate, modeLabel } from '../data/summary'
import styles from './Sensors.module.css'

const LatencyHistory = lazy(() => import('../charts/LatencyHistory'))

const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/

function Card({ title, area, children }: { title: string; area: string; children: ReactNode }) {
  return (
    <section className={styles.card} style={{ gridArea: area }} aria-labelledby={`card-${area}`}>
      <h2 id={`card-${area}`}>{title}</h2>
      {children}
    </section>
  )
}

/** Latency of the newest run per source. The API holds only that run so far; the chart takes a list for when it holds more. */
function LatencyCard() {
  const status = useSourcesStatus()
  if (!status.data?.available) return null
  const { run, sources } = status.data
  const runs = [{ date: run.date ?? 'latest run', rows: buildSourceRows(sources) }]
  return (
    <Card title="Source latency" area="latency">
      <Suspense fallback={<p className={styles.hint}>Loading chart</p>}>
        <LatencyHistory runs={runs} />
      </Suspense>
      <p className={styles.hint}>
        Hours from the end of the data period to its publication, on a log scale. The tick marks each source&apos;s
        expected latency. History appears as daily runs accumulate.
      </p>
    </Card>
  )
}

/** Gauge map and fault list for the chosen date, with an empty state for each way there can be nothing to show. */
function Gauges({ date }: { date: string | null }) {
  const queryClient = useQueryClient()
  const sensors = useSensors(date)
  const basemap = useBasemap()
  const [highlight, setHighlight] = useState<string | null>(null)
  const stations = useMemo(() => sensors.data?.stations ?? [], [sensors.data])

  if (date === null) {
    return (
      <>
        <Card title="Rain gauges" area="map">
          <EmptyState title="No gauge data yet">
            There is no live run and no replay set to read gauges from. The map fills in as soon as one lands.
          </EmptyState>
        </Card>
        <Card title="Gauge faults" area="faults">
          <p className={styles.hint}>Faults are listed once gauge data exists.</p>
        </Card>
      </>
    )
  }

  if (sensors.isError) {
    const unreachable = !(sensors.error instanceof ApiError) || sensors.error.status === 0
    const missing = sensors.error instanceof ApiError && sensors.error.status === 404
    const title = missing
      ? `No gauge data for ${formatDate(date)}`
      : unreachable
        ? 'Cannot reach the AetherGuard API'
        : 'Gauges could not be read'
    return (
      <>
        <Card title="Rain gauges" area="map">
          <EmptyState
            title={title}
            action={
              missing ? undefined : (
                <button type="button" onClick={() => void queryClient.invalidateQueries({ queryKey: sensorsKey(date) })}>
                  Try again
                </button>
              )
            }
          >
            {sensors.error.message}
          </EmptyState>
        </Card>
        <Card title="Gauge faults" area="faults">
          <p className={styles.hint}>No gauge data to list faults from.</p>
        </Card>
      </>
    )
  }

  if (!sensors.data) {
    return (
      <Card title="Rain gauges" area="map">
        <p className={styles.hint} role="status">
          Loading gauges
        </p>
      </Card>
    )
  }

  const { stateCounts, reason } = sensors.data
  if (stations.length === 0) {
    return (
      <>
        <Card title="Rain gauges" area="map">
          <div data-sensors-reason={reason === null ? undefined : ''}>
            <EmptyState title="No gauge readings to show">{reason ?? 'The API returned no gauges for this date.'}</EmptyState>
          </div>
        </Card>
        <Card title="Gauge faults" area="faults">
          <p className={styles.hint}>No gauge data to list faults from.</p>
        </Card>
      </>
    )
  }

  const faults = stations.filter(isFault).length
  return (
    <>
      <Card title="Rain gauges" area="map">
        <ul className={styles.counts} aria-label="Gauges by state">
          {Object.entries(stateCounts).map(([state, n]) => (
            <li key={state}>
              <b className="num">{n}</b> {state}
            </li>
          ))}
          <li>
            <b className="num">{faults}</b> with a fault
          </li>
        </ul>
        {isMostlyMissing(stations) && (
          <p className={styles.hint}>
            Gauge reports reach GHCN 3–13 days late; the map shows each gauge&apos;s latest state.
          </p>
        )}
        <GaugeMap stations={stations} terrain={basemap.data} highlight={highlight} />
      </Card>
      <Card title="Gauge faults" area="faults">
        <FaultList stations={stations} date={sensors.data.date || date} onActive={setHighlight} />
      </Card>
    </>
  )
}

export default function Sensors() {
  const mode = useMode()
  const [params, setParams] = useSearchParams()
  const requested = params.get('date')
  const hasData = mode.data !== undefined && mode.data.mode !== 'none'
  const latest = hasData ? mode.data.latest_date : null
  const date = requested !== null && ISO_DAY.test(requested) ? requested : latest

  const options = useMemo(() => {
    const dates = hasData ? [...mode.data.dates].reverse() : []
    return date !== null && !dates.includes(date) ? [date, ...dates] : dates
  }, [hasData, mode.data, date])

  return (
    <div className={styles.view}>
      <header className={styles.head}>
        <div>
          <h1>Sensors &amp; sources</h1>
          <p>Rain gauge trust and the health of each upstream data source.</p>
        </div>
        {options.length > 0 && (
          <label className={styles.date}>
            <span>Gauge date</span>
            <select
              value={date ?? ''}
              onChange={(e) => setParams(e.target.value === latest ? {} : { date: e.target.value })}
            >
              {options.map((d) => (
                <option key={d} value={d}>
                  {formatDate(d)}
                </option>
              ))}
            </select>
          </label>
        )}
      </header>
      {mode.data && hasData && (
        <p className={styles.provenance}>
          Gauges: {modeLabel(mode.data.mode)}, {mode.data.set}
        </p>
      )}

      <div className={styles.layout}>
        <Card title="Data sources" area="health">
          <SourceHealth />
        </Card>
        <LatencyCard />
        {mode.isPending ? (
          <Card title="Rain gauges" area="map">
            <p className={styles.hint} role="status">
              Checking for data
            </p>
          </Card>
        ) : (
          <Gauges date={mode.isError ? null : date} />
        )}
      </div>
    </div>
  )
}
