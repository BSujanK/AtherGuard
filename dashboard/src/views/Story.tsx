import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { countCodes } from '../data/api'
import { useGrid, useMode } from '../data/hooks'
import { formatCount, formatDate, formatPer100k } from '../data/summary'
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

      <section id="chart" data-chapter className={styles.chapter} data-place="foot">
        <div className={styles.text}>
          <h1 className={styles.wordmark}>AetherGuard</h1>
          <p className={styles.lede}>The daily landslide chart for the Himalaya and the Western Ghats, plotted every morning.</p>
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

      <section id="ground" data-chapter className={styles.chapter} data-place="head">
        <div className={styles.text}>
          <h2 className={styles.heading}>The ground decides where.</h2>
          {assessed !== null && (
            <p className={styles.figure}>
              <span className={styles.value}>{formatCount(assessed)}</span>
              <span className="label">steep cells assessed every day</span>
            </p>
          )}
          <p className={styles.body}>
            The chart is cut into cells about 5 km across. Before any rain falls it knows each one&rsquo;s shape: how steep, how
            high, how broken the relief is, from a 90 m elevation model. Flat ground cannot slide, so it is left off.
          </p>
        </div>
      </section>

      <section id="rain" data-chapter className={styles.chapter} data-place="head" data-crop>
        <div className={styles.text}>
          <h2 className={styles.heading}>The rain decides when.</h2>
          <p className={styles.body}>
            Each morning the run reads satellite rain from NASA&rsquo;s IMERG: the last day, the last three, the last week,
            the wettest hours, and how wet the season has been. A slope soaked for a week fails under rain that would do
            nothing to a dry one.
          </p>
          <p className={styles.body}>
            Rain is also the input most often wrong. At Wayanad on 30 July 2024, the day of its landslides:
          </p>
        </div>
        <div className={styles.pair} aria-label="Rain recorded at Wayanad on 30 July 2024">
          <p className={styles.figure}>
            <span className={styles.value}>
              179<small>mm</small>
            </span>
            <span className="label">IMD gridded rain</span>
          </p>
          <p className={styles.figure} data-dim>
            <span className={styles.value}>
              0<small>mm</small>
            </span>
            <span className="label">CHIRPS, a global product</span>
          </p>
        </div>
      </section>

      <section id="levels" data-chapter className={styles.chapter} data-place="head">
        <div className={styles.text}>
          <h2 className={styles.heading}>Three lines, each drawn on purpose.</h2>
          <p className={styles.body}>
            Ground and rain become one number per cell: the chance of a landslide there that day. Each line sits where it
            would have caught a known share of past landslides.
          </p>
          <table className={styles.levels}>
            <caption className="sr-only">Alert levels, the share of past landslides each catches, and the chance that raises it</caption>
            <thead>
              <tr>
                <th scope="col" className="label">Level</th>
                <th scope="col" className="label">Catches</th>
                {REGIONS.map((r) => (
                  <th scope="col" key={r.key} className="label">
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

      <section id="today" data-chapter className={styles.chapter} data-place="foot">
        <div className={styles.text}>
          <h2 className={styles.heading}>{latest ? <>The chart for {formatDate(latest)}.</> : 'Today&rsquo;s chart.'}</h2>
          {counts ? (
            <ul className={styles.tally} aria-label="Cells by level">
              {[3, 2, 1, 0].map((level) => (
                <li key={level} data-level={LEVELS[level]!.toLowerCase()}>
                  <span className={styles.count}>{formatCount(counts[level]!)}</span>
                  <span className="label">
                    <span className={styles.swatch} data-level={LEVELS[level]!.toLowerCase()} aria-hidden="true" />
                    {LEVELS[level]}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className={styles.body}>
              {mode.isError ? 'The data service is not answering, so there is no chart to show.' : 'The counts appear once a run has been published.'}
            </p>
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

      <section id="limits" data-chapter className={styles.chapter} data-place="head">
        <div className={styles.text}>
          <h2 className={styles.heading}>What this chart cannot tell you.</h2>
          <p className={styles.figure}>
            <span className={styles.value}>87</span>
            <span className="label">recorded landslides it was tested on, 2018 to 2025</span>
          </p>
          <p className={styles.body}>
            It says where a landslide is more likely, never that one will happen. Its test record is small and incomplete,
            so its skill is known only roughly. It is a research prototype and has never been used to warn anyone; the
            inputs can fail too, which is why every reading carries a confidence.
          </p>
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
