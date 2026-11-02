import { Fragment, useDeferredValue, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { usePlaces } from '../../data/hooks'
import { describeOdds, describePlace, describeRisk, formatCount, MODEL_ESTIMATE, oddsOptions, oddsWhen, spokenRisk } from '../../data/summary'
import { watchAt } from '../../data/thresholds'
import { CERTAINTY, LEVELS, type ModeResponse } from '../../data/types'
import { LEVEL_HEX } from '../../scene/levelColors'
import { REGION_LABELS, type RegionFilter } from '../../scene/geo'
import {
  DEFAULT_LEVELS,
  DEFAULT_SORT,
  FIRST_DIRECTION,
  type FeedSource,
  rowAt,
  selectFeed,
  type Sort,
  type SortKey,
  windowRange,
} from './feed'
import styles from './AlertFeed.module.css'

/** Height of one row in pixels; fixed, which is what lets the list render only the rows in view. */
export const ROW_HEIGHT = 60
/** Viewport height assumed until the list has been measured (and where nothing can be measured). */
const DEFAULT_VIEWPORT = 600

/** In the order of the columns; the cell column between level and region has no sort of its own. */
const SORTS: readonly { key: SortKey; label: string }[] = [
  { key: 'level', label: 'Level' },
  { key: 'region', label: 'Region' },
  { key: 'risk', label: 'Risk' },
  { key: 'confidence', label: 'Confidence' },
]

const DIRECTION_WORDS: Record<SortKey, Record<'asc' | 'desc', string>> = {
  level: { desc: 'most severe first', asc: 'least severe first' },
  risk: { desc: 'highest first', asc: 'lowest first' },
  confidence: { asc: 'best first', desc: 'worst first' },
  region: { asc: 'A to Z', desc: 'Z to A' },
}

interface AlertFeedProps {
  source: FeedSource
  /** The API's thresholds, for the "times Watch" figure of each cell (its region's Watch threshold); none without them. */
  mode: Pick<ModeResponse, 'thresholds' | 'thresholds_by_region'> | undefined
  /** Cells that have just reached Watch or above (highlighted for a few seconds). */
  fresh: ReadonlySet<number>
  /** The live run's own day is shown ("today" in the probability line); a replay day or an older run is named by date. */
  today?: boolean
  /** Sentence for the live region. */
  announcement: string
  onOpen: (cell: number) => void
}

/** The cells of the day as a sortable, filterable, searchable list that renders only the rows in view. */
export default function AlertFeed({ source, mode, fresh, today = false, announcement, onOpen }: AlertFeedProps) {
  const { grid } = source
  const [levels, setLevels] = useState<readonly boolean[]>(DEFAULT_LEVELS)
  const [region, setRegion] = useState<RegionFilter>('all')
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState<Sort>(DEFAULT_SORT)
  const [firmOnly, setFirmOnly] = useState(false)
  const deferredQuery = useDeferredValue(query)
  const places = usePlaces().data

  const levelCounts = useMemo(() => {
    const counts = [0, 0, 0, 0]
    for (let i = 0; i < grid.n; i++) counts[grid.level[i]!]! += 1
    return counts
  }, [grid])
  const hasCertainty = grid.lead > 0 && grid.certainty !== undefined
  const firmCount = useMemo(() => {
    let n = 0
    if (grid.certainty) for (let i = 0; i < grid.n; i++) if (grid.certainty[i] === CERTAINTY.firm && levels[grid.level[i]!]) n++
    return n
  }, [grid, levels])
  const order = useMemo(
    () => selectFeed(source, { levels, region, query: deferredQuery, places, firmOnly: hasCertainty && firmOnly }, sort),
    [source, levels, region, deferredQuery, places, sort, hasCertainty, firmOnly],
  )

  const scroller = useRef<HTMLDivElement>(null)
  const [scrollTop, setScrollTop] = useState(0)
  const [viewport, setViewport] = useState(DEFAULT_VIEWPORT)
  const [active, setActive] = useState(0)
  const focusPending = useRef(false)
  const count = order.length
  const current = Math.min(active, Math.max(0, count - 1))
  const { start, end } = windowRange(scrollTop, viewport, ROW_HEIGHT, count)

  useEffect(() => {
    const el = scroller.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(() => setViewport(el.clientHeight || DEFAULT_VIEWPORT))
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  // A different selection starts again from the top.
  const [shownOrder, setShownOrder] = useState(order)
  if (shownOrder !== order) {
    setShownOrder(order)
    setActive(0)
    setScrollTop(0)
  }
  useLayoutEffect(() => {
    if (scroller.current) scroller.current.scrollTop = 0
  }, [order])

  // Keyboard navigation moves focus to the row once it has been rendered.
  useLayoutEffect(() => {
    if (!focusPending.current) return
    const row = scroller.current?.querySelector<HTMLElement>(`[data-index="${current}"]`)
    if (row) {
      row.focus()
      focusPending.current = false
    }
  }, [current, start, end])

  const scrollTo = (top: number) => {
    if (scroller.current) scroller.current.scrollTop = top
    setScrollTop(top)
  }

  const move = (to: number) => {
    const next = Math.max(0, Math.min(count - 1, to))
    setActive(next)
    focusPending.current = true
    if (next * ROW_HEIGHT < scrollTop) scrollTo(next * ROW_HEIGHT)
    else if ((next + 1) * ROW_HEIGHT > scrollTop + viewport) scrollTo((next + 1) * ROW_HEIGHT - viewport)
  }

  const onKeyDown = (event: React.KeyboardEvent) => {
    const page = Math.max(1, Math.floor(viewport / ROW_HEIGHT) - 1)
    const target: Record<string, number> = {
      ArrowDown: current + 1,
      ArrowUp: current - 1,
      PageDown: current + page,
      PageUp: current - page,
      Home: 0,
      End: count - 1,
    }
    const to = target[event.key]
    if (to === undefined || count === 0) return
    event.preventDefault()
    move(to)
  }

  const toggleLevel = (level: number) => setLevels((prev) => prev.map((on, i) => (i === level ? !on : on)))
  const chooseSort = (key: SortKey) =>
    setSort((prev) =>
      prev.key === key ? { key, dir: prev.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: FIRST_DIRECTION[key] },
    )

  const noAlerts = levelCounts[1]! + levelCounts[2]! + levelCounts[3]! === 0

  return (
    <section className={styles.feed} aria-label="Alert feed" data-feed>
      <div className="sr-only" role="status" aria-live="polite" data-testid="new-alerts-live">
        {announcement}
      </div>

      <div className={styles.toolbar}>
        <label className={styles.search}>
          <span>{places ? 'Search by place or cell id' : 'Search by cell id'}</span>
          <input
            type="search"
            autoComplete="off"
            placeholder={places ? 'e.g. Wayanad or 202851' : 'e.g. 202851'}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>

        <label className={styles.region}>
          <span>Region</span>
          <select value={region} onChange={(e) => setRegion(e.target.value as RegionFilter)}>
            {(Object.keys(REGION_LABELS) as RegionFilter[]).map((key) => (
              <option key={key} value={key}>
                {key === 'all' ? 'All regions' : REGION_LABELS[key]}
              </option>
            ))}
          </select>
        </label>

        <div role="group" aria-label="Levels" className={styles.chips}>
          {LEVELS.map((name, level) => (
            <button
              key={name}
              type="button"
              className={styles.chip}
              aria-pressed={levels[level]}
              onClick={() => toggleLevel(level)}
            >
              <i style={{ background: LEVEL_HEX[level] }} aria-hidden="true" />
              {name} <span className="num">{formatCount(levelCounts[level]!)}</span>
            </button>
          ))}
        </div>

        {hasCertainty && (
          <button type="button" className={styles.chip} aria-pressed={firmOnly} onClick={() => setFirmOnly((on) => !on)}
            title="List only the cells whose level is the same with no more rain, with the forecast and with heavy rain">
            Firm only <span className="num">{formatCount(firmCount)}</span>
          </button>
        )}

        <p className={styles.count}>
          <span className="num">{formatCount(count)}</span> of <span className="num">{formatCount(grid.n)}</span> cells
          {fresh.size > 0 && (
            <>
              {' '}
              <b className={styles.newTag}>{fresh.size} new</b>
            </>
          )}
        </p>
      </div>

      <div className={styles.head}>
        <div role="group" aria-label="Sort" className={styles.sorts}>
          {SORTS.map(({ key, label }) => {
            const on = sort.key === key
            return (
              <Fragment key={key}>
                {key === 'region' && <span className={styles.cellCol} aria-hidden="true" />}
                <button
                  type="button"
                  className={styles.sort}
                  data-key={key}
                  aria-pressed={on}
                  aria-label={`Sort by ${label.toLowerCase()}${on ? `, now ${DIRECTION_WORDS[key][sort.dir]}; activate to reverse` : ''}`}
                  onClick={() => chooseSort(key)}
                >
                  {label}
                  <span aria-hidden="true" className={styles.arrow}>
                    {on ? (sort.dir === 'asc' ? '↑' : '↓') : ''}
                  </span>
                </button>
              </Fragment>
            )
          })}
        </div>
      </div>

      <div
        ref={scroller}
        className={styles.scroller}
        onScroll={(e) => setScrollTop(e.currentTarget.scrollTop)}
        data-testid="feed-scroller"
      >
        {count === 0 ? (
          <p className={styles.none} role="status">
            {noAlerts && levels.every((on, i) => on === DEFAULT_LEVELS[i])
              ? 'No cell is at Watch or above on this date.'
              : 'No cell matches these filters.'}
          </p>
        ) : (
          <div className={styles.spacer} style={{ height: count * ROW_HEIGHT }}>
            <ul className={styles.list} role="list" style={{ top: start * ROW_HEIGHT }} onKeyDown={onKeyDown}>
              {Array.from({ length: end - start }, (_, k) => {
                const i = start + k
                const row = rowAt(source, order[i]!)
                const risk = describeRisk(row.risk, watchAt(mode, row.lat, row.lon))
                const oddsFor = oddsOptions(row.flags)
                const odds = describeOdds(row.risk, oddsWhen(grid.date, grid.lead, today), oddsFor)
                const level = LEVELS[row.level as 0 | 1 | 2 | 3]
                const isFresh = fresh.has(row.cell)
                const where = describePlace(row.cell, places?.lookup(row.cell), places?.farKm)
                return (
                  <li key={row.cell} role="listitem" aria-setsize={count} aria-posinset={i + 1} style={{ height: ROW_HEIGHT }}>
                    <button
                      type="button"
                      className={styles.row}
                      data-index={i}
                      data-level={row.level}
                      data-fresh={isFresh || undefined}
                      tabIndex={i === current ? 0 : -1}
                      aria-label={`${level}, cell ${row.cell}, ${where.primary}, ${row.region}, ${odds ? `${odds.sentence}, ` : ''}risk ${spokenRisk(risk)}, ${row.confidenceName} confidence${row.certainty ? `, ${row.certainty.headline}` : ''}${isFresh ? ', new' : ''}. Open details`}
                      onFocus={() => setActive(i)}
                      onClick={() => onOpen(row.cell)}
                    >
                      <span className={styles.level}>
                        <i style={{ background: LEVEL_HEX[row.level] }} aria-hidden="true" />
                        <strong>{level}</strong>
                        {isFresh && <em className={styles.newBadge}>New</em>}
                      </span>
                      {where.secondary ? (
                        <span className={styles.where} title={`${where.primary}. ${where.secondary}`}>
                          <strong className={styles.placeName}>{where.primary}</strong>
                          <span className="num">
                            Cell {row.cell} &middot; {where.secondary}
                            <span className={styles.regionInline}> &middot; {row.region}</span>
                          </span>
                        </span>
                      ) : (
                        <span className={styles.where}>
                          <span className="num">Cell {row.cell}</span>
                          <span className="num">
                            {where.primary}
                            <span className={styles.regionInline}> &middot; {row.region}</span>
                          </span>
                        </span>
                      )}
                      <span className={styles.regionName}>{row.region}</span>
                      <span className={styles.risk} title={odds ? `${odds.sentence}. ${oddsFor.capped ? `${MODEL_ESTIMATE}: ` : ''}${risk.raw}` : risk.raw}>
                        <span className="num">{odds ? odds.short : risk.primary}</span>
                        <span className="num">{odds ? risk.primary : risk.secondary}</span>
                      </span>
                      <span className={styles.conf} data-confidence={row.confidence}>
                        {row.confidenceName}
                        {row.certaintyShort && (
                          <span className={styles.certaintyTag} data-certainty={row.certainty!.kind} title={row.certainty!.headline}>
                            {row.certaintyShort}
                          </span>
                        )}
                      </span>
                    </button>
                  </li>
                )
              })}
            </ul>
          </div>
        )}
      </div>
    </section>
  )
}
