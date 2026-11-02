import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import AlertDrawer from '../components/alerts/AlertDrawer'
import AlertFeed from '../components/alerts/AlertFeed'
import LeadSwitch from '../components/alerts/LeadSwitch'
import { feedSource } from '../components/alerts/feed'
import { useNewAlerts } from '../components/alerts/useNewAlerts'
import EmptyState from '../components/EmptyState'
import ViewFrame from '../components/ViewFrame'
import { ApiError } from '../data/api'
import { queryKeys, useGrid, useMode, usePlaces } from '../data/hooks'
import { addDays, formatCount, formatDate, formatDayMonth, formatWeekday, LEAD_LABELS, modeLabel, parseLead } from '../data/summary'
import styles from './Alerts.module.css'

const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/

/** A cell id from the address: a non-negative whole number, else null. */
function parseCell(raw: string | null): number | null {
  return raw !== null && /^\d{1,12}$/.test(raw) ? Number(raw) : null
}

/**
 * Alerts and why: the day's cells as a feed, and the explanation of one cell in a drawer. Both live in the address
 * (`?date=` and `?cell=`), so a link, the map's click-through or the browser's Back button reaches the same state.
 */
export default function Alerts() {
  const mode = useMode()
  const queryClient = useQueryClient()
  const [params, setParams] = useSearchParams()

  const hasData = mode.data !== undefined && mode.data.mode !== 'none'
  const dates = useMemo(() => (hasData ? mode.data.dates : []), [hasData, mode.data])
  const latest = hasData ? mode.data.latest_date : null
  const requested = params.get('date')
  const pinned = requested !== null && ISO_DAY.test(requested) ? requested : null
  const date = pinned ?? latest
  const dateMissing = hasData && date !== null && !dates.includes(date)
  const lead = parseLead(params.get('lead'))
  const leads = hasData && date !== null ? (mode.data.leads?.[date] ?? [0]) : [0]
  const places = usePlaces().data

  const grid = useGrid(hasData && !dateMissing ? date : null, lead, true)
  const source = useMemo(() => (grid.data ? feedSource(grid.data) : undefined), [grid.data])
  const { fresh, announcement } = useNewAlerts(grid.data, pinned === null)

  const rawCell = params.get('cell')
  const cell = parseCell(rawCell)
  const drawerOpen = rawCell !== null

  const open = useCallback(
    (next: number) =>
      setParams((prev) => {
        const q = new URLSearchParams(prev)
        q.set('cell', String(next))
        if (!q.has('date') && date) q.set('date', date)
        return q
      }),
    [setParams, date],
  )
  const close = useCallback(
    () =>
      setParams(
        (prev) => {
          const q = new URLSearchParams(prev)
          q.delete('cell')
          if (q.get('date') === latest) q.delete('date')
          return q
        },
        { replace: true },
      ),
    [setParams, latest],
  )
  const setLead = useCallback(
    (next: number) =>
      setParams(
        (prev) => {
          const q = new URLSearchParams(prev)
          if (next === 0) q.delete('lead')
          else q.set('lead', String(next))
          if (!q.has('date') && date) q.set('date', date)
          return q
        },
        { replace: true },
      ),
    [setParams, date],
  )
  const setDate = (next: string) =>
    setParams((prev) => {
      const q = new URLSearchParams(prev)
      if (next === latest) q.delete('date')
      else q.set('date', next)
      return q
    })

  if (mode.isPending || mode.isError || mode.data.mode === 'none') {
    return <ViewFrame title="Alerts" blurb="Every Watch, Warning and Emergency cell, with the reasons behind each one." />
  }

  const options = date !== null && !dates.includes(date) ? [date, ...[...dates].reverse()] : [...dates].reverse()
  const counts = source ? [1, 2, 3].map((l) => countLevel(source.grid.level, l)) : null

  let feed
  if (dateMissing) {
    feed = (
      <EmptyState
        title={`No data for ${formatDate(date)}`}
        action={
          <button type="button" onClick={() => setParams({})}>
            Show the latest date
          </button>
        }
      >
        {mode.data.set} holds {formatDate(dates[0] ?? null)} to {formatDate(latest)}.
      </EmptyState>
    )
  } else if (grid.isError && !grid.data) {
    const missing = grid.error instanceof ApiError && grid.error.status === 404
    feed = (
      <EmptyState
        title={missing ? `No ${lead === 0 ? "" : `${LEAD_LABELS[lead]} `}risk grid for ${formatDate(date)}` : 'The alerts could not be loaded'}
        action={
          missing ? undefined : (
            <button type="button" onClick={() => void queryClient.invalidateQueries({ queryKey: queryKeys.grid(date!, lead) })}>
              Try again
            </button>
          )
        }
      >
        {grid.error.message}
      </EmptyState>
    )
  } else if (!source) {
    feed = (
      <p className={styles.hint} role="status">
        Loading the {LEAD_LABELS[lead]} alerts for {formatDate(date)}
      </p>
    )
  } else {
    feed = (
      <AlertFeed
        source={source}
        mode={mode.data}
        fresh={fresh}
        today={mode.data.mode === 'live' && date === latest}
        announcement={announcement}
        onOpen={open}
      />
    )
  }

  return (
    <div className={styles.view}>
      <header className={styles.head}>
        <div>
          <h1>Alerts</h1>
          <p>Every cell scored for the day, with the reasons behind its level.</p>
        </div>
        <div className={styles.controls}>
          {date !== null && <LeadSwitch name="feed-lead" value={lead} available={leads} onChange={setLead} />}
          {options.length > 0 && (
            <label className={styles.date}>
              <span>Date</span>
              <select value={date ?? ''} onChange={(e) => setDate(e.target.value)}>
                {options.map((d) => (
                  <option key={d} value={d}>
                    {formatDate(d)}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
      </header>
      <p className={styles.provenance}>
        {modeLabel(mode.data.mode)}, {mode.data.set}.{' '}
        {lead === 0
          ? 'Lead D0: the day\u2019s observed rain.'
          : `Lead ${LEAD_LABELS[lead]}: forecast for ${formatWeekday(date === null ? null : addDays(date, lead))}, issued ${formatDayMonth(date)}.${
              grid.data?.forecast?.label ? ` Forecast rain: ${grid.data.forecast.label}.` : ''
            } Each cell is Firm (rain already fallen sets the level) or Depends on the rain forecast.`}
        {counts && source && (
          <>
            {' '}
            <span className="num">{formatCount(source.grid.n)}</span> cells scored, of which{' '}
            <span className="num">{formatCount(counts[2]!)}</span> Emergency, <span className="num">{formatCount(counts[1]!)}</span>{' '}
            Warning and <span className="num">{formatCount(counts[0]!)}</span> Watch.
          </>
        )}
      </p>

      {feed}

      {places && <p className={styles.attribution}>{places.attribution}</p>}
      {lead > 0 && grid.data?.forecast?.attribution && <p className={styles.attribution}>{grid.data.forecast.attribution}.</p>}

      {drawerOpen && (
        <AlertDrawer
          cell={cell}
          rawCell={rawCell}
          date={date}
          set={mode.data.set}
          lead={lead}
          leads={leads}
          onLeadChange={setLead}
          onClose={close}
          onSelectCell={open}
          returnFocus={() => document.querySelector<HTMLElement>('[data-feed] button[tabindex="0"]')}
        />
      )}
    </div>
  )
}

function countLevel(levels: Uint8Array, level: number): number {
  let n = 0
  for (let i = 0; i < levels.length; i++) if (levels[i] === level) n++
  return n
}
