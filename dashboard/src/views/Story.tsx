import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { countCodes } from '../data/api'
import { useGrid, useMode } from '../data/hooks'
import { formatCount, formatDate, formatPer100k, modeLabel } from '../data/summary'
import { thresholdsFor } from '../data/thresholds'
import { LEVELS } from '../data/types'
import { CHAPTERS, useStory } from '../state/story'
import styles from './Story.module.css'

const LEVEL_KEYS = ['watch', 'warning', 'emergency'] as const
/** Share of past landslides each line was set to catch on the development years (the model card's recall targets). */
const CAUGHT = { watch: 'about 9 in 10', warning: '3 in 4', emergency: '1 in 2' } as const
const REGIONS = [
  { key: 'himalaya', name: 'Himalaya' },
  { key: 'western_ghats', name: 'Western Ghats' },
] as const

/** The element the story scrolls in: the shell's main region. */
const scroller = (): HTMLElement | null => document.getElementById('view')

/**
 * The story: six chapters over the shared terrain. Scrolling moves the camera and plots the chart layer by layer
 * (contours, relief, rain, levels); the last chapters rest on the live map's own view and hand over to it. Every figure
 * here comes from the API; the chapters are plain text and links, so the page reads the same without WebGL.
 */
export default function Story() {
  const root = useRef<HTMLDivElement>(null)
  const [current, setCurrent] = useState(0)
  const mode = useMode()
  const data = mode.data
  const latest = data && data.mode !== 'none' ? data.latest_date : null
  const grid = useGrid(latest, 0)
  const counts = useMemo(() => (grid.data ? countCodes(grid.data.level, LEVELS.length) : null), [grid.data])
  const assessed = counts ? counts.reduce((a, b) => a + b, 0) : null

  useEffect(() => {
    const view = scroller()
    const { enter, leave, setPosition } = useStory.getState()
    enter()
    if (!view || !root.current) return leave
    const sections = Array.from(root.current.querySelectorAll<HTMLElement>('[data-chapter]'))
    const measure = () => {
      const tops = sections.map((s) => s.offsetTop)
      const y = view.scrollTop + tops[0]!
      let i = 0
      // Sections without layout (a hidden tab, a test DOM) all sit at 0: stay on the first chapter then.
      while (i < tops.length - 2 && tops[i + 1]! > tops[i]! && y >= tops[i + 1]!) i++
      const position = i + Math.min(1, Math.max(0, (y - tops[i]!) / Math.max(1, tops[i + 1]! - tops[i]!)))
      setPosition(position)
      setCurrent(Math.round(position))
      // Each chapter knows how far it is from the reading position, so its copy can settle in and lift away in CSS.
      sections.forEach((s, k) => s.style.setProperty('--away', String(Math.min(1, Math.abs(position - k)))))
    }
    measure()
    view.addEventListener('scroll', measure, { passive: true })
    window.addEventListener('resize', measure)
    return () => {
      view.removeEventListener('scroll', measure)
      window.removeEventListener('resize', measure)
      leave()
    }
  }, [])

  const goTo = (index: number) => root.current?.querySelector<HTMLElement>(`#${CHAPTERS[index]!.id}`)?.scrollIntoView({ block: 'start' })

  return (
    <div className={styles.story} ref={root}>
      <nav className={styles.rail} aria-label="Chapters">
        <ol>
          {CHAPTERS.map((chapter, i) => (
            <li key={chapter.id}>
              <a href={`#${chapter.id}`} aria-current={i === current ? 'step' : undefined} onClick={(e) => (e.preventDefault(), goTo(i))}>
                <span className={styles.tick} aria-hidden="true" />
                <span className={styles.railLabel}>{chapter.label}</span>
              </a>
            </li>
          ))}
        </ol>
      </nav>

      <section id="chart" data-chapter className={styles.chapter} data-opening>
        <div className={styles.masthead}>
          <h1 className={styles.wordmark}>AetherGuard</h1>
          <p className={styles.lede}>The daily landslide chart for the Himalaya and the Western Ghats, plotted every morning.</p>
          <p className={styles.issue}>
            {mode.isError ? 'The data service is not answering.' : !data ? 'Reading the latest run.' : data.mode === 'none' ? 'No run has been published yet.' : (
              <>
                {modeLabel(data.mode)} data through <span className="num">{formatDate(latest)}</span>
              </>
            )}{' '}
            Research prototype, not validated for public warnings.
          </p>
          <div className={styles.actions}>
            <button type="button" className={styles.primary} onClick={() => goTo(1)}>
              Read the chart
            </button>
            <Link to="/map" viewTransition className={styles.quiet}>
              Go straight to the live map
            </Link>
          </div>
        </div>
      </section>

      <section id="ground" data-chapter className={styles.chapter}>
        <div className={styles.slip}>
          <h2>The ground decides where.</h2>
          <p>
            The chart is cut into cells about 5 km across. Before any rain falls it already knows each one&rsquo;s shape: how
            steep, how high, how broken the relief is, measured from a 90 m elevation model.
          </p>
          <p>
            Flat ground cannot slide, so it is left off.{' '}
            {assessed !== null ? (
              <>
                <span className="num">{formatCount(assessed)}</span> cells are steep enough to be assessed.
              </>
            ) : (
              'Only cells steep enough to slide are assessed.'
            )}
          </p>
        </div>
      </section>

      <section id="rain" data-chapter className={styles.chapter} data-side="low">
        <div className={styles.slip}>
          <h2>The rain decides when.</h2>
          <p>
            Each morning the run reads satellite rain from NASA&rsquo;s IMERG: what fell in the last day, the last three days
            and the last week, and how wet the season has been.
          </p>
          <p>A slope that has soaked for a week fails under rain that would do nothing to a dry one. That is why a total alone is never the whole reading.</p>
        </div>
      </section>

      <section id="levels" data-chapter className={styles.chapter}>
        <div className={styles.slip}>
          <h2>Three lines, each drawn on purpose.</h2>
          <p>
            Ground and rain become one number per cell: the chance of a landslide there that day. Crossing a line raises the
            cell. Each line sits where it would have caught a known share of past landslides.
          </p>
          <table className={styles.levels}>
            <caption className="sr-only">Alert levels, the share of past landslides each catches, and the chance that raises it</caption>
            <thead>
              <tr>
                <th scope="col">Level</th>
                <th scope="col">Catches</th>
                {REGIONS.map((r) => (
                  <th scope="col" key={r.key}>
                    {r.name}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {LEVEL_KEYS.map((key, i) => (
                <tr key={key}>
                  <th scope="row">
                    <span className={styles.swatch} data-level={key} aria-hidden="true" />
                    {LEVELS[i + 1]}
                  </th>
                  <td>{CAUGHT[key]}</td>
                  {REGIONS.map((r) => {
                    const t = thresholdsFor(data, r.key).thresholds
                    return (
                      <td key={r.key} className="num">
                        {t ? formatPer100k(t[key]) : 'n/a'}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
          <p className={styles.note}>Chance per 100,000 cell-days that raises the level. Shares are of landslides recorded 2007 to 2017.</p>
        </div>
      </section>

      <section id="today" data-chapter className={styles.chapter} data-side="low">
        <div className={styles.slip}>
          <h2>{latest ? <>The chart for {formatDate(latest)}.</> : 'Today&rsquo;s chart.'}</h2>
          {counts ? (
            <ul className={styles.tally} aria-label="Cells by level">
              {[3, 2, 1, 0].map((level) => (
                <li key={level}>
                  <span className={styles.swatch} data-level={LEVELS[level]!.toLowerCase()} aria-hidden="true" />
                  <span className="num">{formatCount(counts[level]!)}</span> {LEVELS[level]}
                </li>
              ))}
            </ul>
          ) : (
            <p>{mode.isError ? 'The data service is not answering, so there is no chart to show.' : 'The counts appear once a run has been published.'}</p>
          )}
          <div className={styles.actions}>
            <Link to="/map" viewTransition className={styles.primary}>
              Open the live map
            </Link>
            <Link to="/alerts-why" viewTransition className={styles.quiet}>
              See each alert and why
            </Link>
          </div>
        </div>
      </section>

      <section id="limits" data-chapter className={styles.chapter}>
        <div className={styles.slip}>
          <h2>What this chart cannot tell you.</h2>
          <p>
            It says where a landslide is more likely, never that one will happen. It has been checked against 87 recorded
            landslides from 2018 to 2025, a small and incomplete record, so its skill is known only roughly.
          </p>
          <p>It is a research prototype and has never been used to warn anyone. The inputs can fail too, which is why every reading carries a confidence.</p>
          <div className={styles.actions}>
            <Link to="/sensors-sources" viewTransition className={styles.primary}>
              Check sensors and sources
            </Link>
            <button type="button" className={styles.quiet} onClick={() => goTo(0)}>
              Back to the start
            </button>
          </div>
        </div>
      </section>
    </div>
  )
}
