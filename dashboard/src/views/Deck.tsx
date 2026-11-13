import { AnimatePresence, animate, motion, useMotionValue, useTransform, type Variants } from 'framer-motion'
import { type ReactNode, useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { countCodes } from '../data/api'
import { useGrid, useMode } from '../data/hooks'
import { formatCount, formatDate } from '../data/summary'
import { LEVELS } from '../data/types'
import { usePrefersReducedMotion } from '../lib/motion'
import { useStory } from '../state/story'
import styles from './Deck.module.css'

const EASE = [0.16, 1, 0.3, 1] as const

/** A slide's entrance: its parts arrive one after another, rising out of a blur; it leaves quickly, upward. */
const slide: Variants = {
  hidden: {},
  shown: { transition: { staggerChildren: 0.085, delayChildren: 0.12 } },
  gone: { opacity: 0, y: -18, filter: 'blur(6px)', transition: { duration: 0.32, ease: [0.7, 0, 0.84, 0] } },
}
const part: Variants = {
  hidden: { opacity: 0, y: 26, filter: 'blur(10px)' },
  shown: { opacity: 1, y: 0, filter: 'blur(0px)', transition: { duration: 0.8, ease: EASE } },
}

function Part({ children, className, as = 'div' }: { children: ReactNode; className?: string; as?: 'div' | 'p' | 'h1' | 'h2' | 'li' }) {
  const Tag = motion[as]
  return (
    <Tag className={className} variants={part}>
      {children}
    </Tag>
  )
}

/** A figure that counts up to its value when its slide arrives. */
function Count({ value, decimals = 0 }: { value: number; decimals?: number }) {
  const reduced = usePrefersReducedMotion()
  const n = useMotionValue(reduced ? value : 0)
  const text = useTransform(n, (v) => (decimals ? v.toFixed(decimals) : formatCount(Math.round(v))))
  useEffect(() => {
    if (reduced) return n.set(value)
    const controls = animate(n, value, { duration: 1.6, ease: EASE, delay: 0.35 })
    return () => controls.stop()
  }, [n, value, reduced])
  return <motion.span className="num">{text}</motion.span>
}

/** Today's cells by level, from the live run (null until it has loaded). */
function useToday() {
  const mode = useMode().data
  const latest = mode && mode.mode !== 'none' ? mode.latest_date : null
  const grid = useGrid(latest, 0)
  const counts = useMemo(() => (grid.data ? countCodes(grid.data.level, LEVELS.length) : null), [grid.data])
  return { latest, counts }
}

// ------------------------------------------------------------------------------------------------- slides

function Title() {
  return (
    <div className={styles.title}>
      <Part as="h1" className={styles.wordmark}>
        AetherGuard
      </Part>
      <Part as="p" className={styles.lede}>
        Landslide early warning for the Himalaya and the Western Ghats, one 5 km cell at a time, every morning.
      </Part>
      <Part className={styles.meta}>
        <span className="num">0.05°</span> grid <i aria-hidden="true" /> daily at <span className="num">11:00</span> IST <i aria-hidden="true" />
        <span className="num">4</span> days ahead
      </Part>
    </div>
  )
}

const FAILURES = [
  { name: 'The rain is mis-measured', text: 'Global rain products miss the storms that matter. On 30 July 2024 the IMD grid recorded 179 mm at Wayanad; CHIRPS recorded 0 mm and ERA5 about 67 mm.' },
  { name: 'Rain alone decides', text: 'A rainfall threshold does not know the slope the rain falls on: a flat plain and a cut hillside get the same warning.' },
  { name: 'One colour per district', text: 'Warnings are issued for areas of thousands of square kilometres, so the hillside at risk is lost inside the district around it.' },
  { name: 'Bad data goes unseen', text: 'A gauge that has failed reads like a dry day. Nothing says the input was wrong, so a quiet map can mean a blind one.' },
]

function Failures() {
  return (
    <div className={styles.column}>
      <Part as="h2" className={styles.heading}>
        Why warnings fail before the slope does.
      </Part>
      <ul className={styles.failures}>
        {FAILURES.map((f) => (
          <Part as="li" key={f.name}>
            <strong>{f.name}</strong>
            <span>{f.text}</span>
          </Part>
        ))}
      </ul>
    </div>
  )
}

function Solution() {
  const { latest, counts } = useToday()
  return (
    <div className={styles.column}>
      <Part as="h2" className={styles.heading}>
        AetherGuard: every cell, every morning, with its reasons.
      </Part>
      <Part as="p" className={styles.body}>
        Each day it scores every steep 5 km cell of the two ranges for landslide risk, today and three days ahead. It
        first checks whether each input can be trusted, and every alert carries a confidence and the inputs behind it.
      </Part>
      <Part className={styles.triad}>
        <div>
          <Count value={36792} />
          <span>cells assessed every day</span>
        </div>
        <div>
          <span className="num">D0–D+3</span>
          <span>today and three days ahead</span>
        </div>
        <div>
          <span className="num">3</span>
          <span>levels, each with a confidence</span>
        </div>
      </Part>
      {counts && latest && (
        <Part as="p" className={styles.today}>
          On the chart for <span className="num">{formatDate(latest)}</span>:{' '}
          {[3, 2, 1].map((level, i) => (
            <span key={level} className={styles.level} data-level={LEVELS[level]!.toLowerCase()}>
              <span className="num">{formatCount(counts[level]!)}</span> {LEVELS[level]}
              {i < 2 ? ', ' : '.'}
            </span>
          ))}
        </Part>
      )}
    </div>
  )
}

const STAGES = [
  { name: 'Sources', text: 'Satellite rain, gauges, forecasts, terrain and ground, each fetched and checked for freshness.' },
  { name: 'Stage 1: sensor integrity', text: 'Can each reading be trusted? Gauges are scored against their neighbours and the grids; sources that disagree are flagged.' },
  { name: 'Stage 2: hazard model', text: 'A calibrated chance of a landslide per cell and day, from trusted rain, rain intensity, terrain and ground.' },
  { name: 'Alert engine', text: 'Levels from region thresholds, then rules: a level is capped without recent rain, held for a day or two while blind, and lowered in confidence where the ensemble disagrees.' },
]

function Pipeline() {
  return (
    <div className={styles.wide}>
      <Part as="h2" className={styles.heading}>
        Two stages: first trust the data, then judge the slope.
      </Part>
      <div className={styles.pipeline}>
        <svg className={styles.wire} viewBox="0 0 1000 8" preserveAspectRatio="none" aria-hidden="true">
          <motion.line
            x1="0"
            y1="4"
            x2="1000"
            y2="4"
            variants={{ hidden: { pathLength: 0 }, shown: { pathLength: 1, transition: { duration: 1.6, ease: EASE, delay: 0.3 } } }}
          />
        </svg>
        {STAGES.map((s, i) => (
          <Part key={s.name} className={styles.stage}>
            <span className={styles.node} data-core={i === 1 || i === 2} aria-hidden="true" />
            <strong>{s.name}</strong>
            <span>{s.text}</span>
          </Part>
        ))}
      </div>
      <Part as="p" className={styles.note}>
        When the data are blind, the alerts escalate and say so, rather than going quiet.
      </Part>
    </div>
  )
}

const GROUPS = [
  { name: 'Rain, 1 to 90 days', n: 16, tone: 'cyan' },
  { name: 'Terrain', n: 10, tone: 'blue' },
  { name: 'Ground: cover, soil, steep share', n: 9, tone: 'lime' },
  { name: 'Rain intensity, half-hourly', n: 6, tone: 'flame' },
] as const

function Model() {
  const total = GROUPS.reduce((a, g) => a + g.n, 0)
  return (
    <div className={styles.column}>
      <Part as="h2" className={styles.heading}>
        The core: a LightGBM ensemble that cannot learn that more rain is safer.
      </Part>
      <Part as="p" className={styles.body}>
        Gradient-boosted trees: 20 models, each trained on a resample of the data and constrained so that more rain can
        never lower the risk, then calibrated region by region so a probability means the same in the Ghats and the
        Himalaya.
      </Part>
      <Part className={styles.bar} aria-label={`${total} inputs: ${GROUPS.map((g) => `${g.n} ${g.name}`).join(', ')}`}>
        {GROUPS.map((g, i) => (
          <motion.span
            key={g.name}
            data-tone={g.tone}
            style={{ flexGrow: g.n }}
            variants={{ hidden: { scaleX: 0 }, shown: { scaleX: 1, transition: { duration: 0.9, ease: EASE, delay: 0.45 + i * 0.12 } } }}
          />
        ))}
      </Part>
      <ul className={styles.legend}>
        {GROUPS.map((g) => (
          <Part as="li" key={g.name}>
            <i data-tone={g.tone} aria-hidden="true" />
            <span className="num">{g.n}</span> {g.name}
          </Part>
        ))}
      </ul>
      <Part className={styles.specs}>
        <span>
          <b className="num">41</b> inputs
        </span>
        <span>
          <b className="num">20</b> models
        </span>
        <span>
          <b className="num">438</b> trees each
        </span>
        <span>
          <b className="num">2</b> regional calibrations
        </span>
      </Part>
    </div>
  )
}

const SOURCES = [
  { name: 'Satellite rain', items: ['NASA GPM IMERG, Late and Early', 'Half-hourly IMERG for intensity'] },
  { name: 'Gauges and grids', items: ['NOAA GHCN-Daily', 'IMD real-time and gridded rain'] },
  { name: 'Forecasts', items: ['NOAA GFS', 'ECMWF IFS and ensemble'] },
  { name: 'Reference rain', items: ['CHIRPS v2.0', 'Open-Meteo, ERA5-Land', 'NASA POWER'] },
  { name: 'Terrain and ground', items: ['Copernicus DEM GLO-90', 'ESA WorldCover', 'ISRIC SoilGrids'] },
  { name: 'Landslides recorded', items: ['NASA Global Landslide Catalog, COOLR', 'Published Indian inventories'] },
]

function Sources() {
  return (
    <div className={styles.wide}>
      <Part as="h2" className={styles.heading}>
        Six kinds of evidence, all of it open data.
      </Part>
      <div className={styles.sources}>
        {SOURCES.map((s) => (
          <Part key={s.name} className={styles.source}>
            <strong>{s.name}</strong>
            <ul>
              {s.items.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </Part>
        ))}
      </div>
      <Part as="p" className={styles.note}>
        The live run reads NASA, NOAA, ECMWF and IMD each morning; the others built the model and checked it.
      </Part>
    </div>
  )
}

const LEDGER = [
  { label: 'Cells assessed each day', value: 36792 },
  { label: 'Landslide cell-days the model learned from, 2007–2017', value: 789 },
  { label: 'Non-landslide cell-days it learned against', value: 399272 },
  { label: 'Independent landslides held back to test it, 2018–2025', value: 87 },
  { label: '…caught at Warning or above, within 10 km and a day', value: 83 },
  { label: '…caught at Emergency, within 10 km and a day', value: 78 },
  { label: 'Integrity checks on every published day', value: 19 },
  { label: 'Automated tests guarding the code', value: 3542 },
]

function Numbers() {
  return (
    <div className={styles.column}>
      <Part as="h2" className={styles.heading}>
        The numbers, measured, not claimed.
      </Part>
      <dl className={styles.ledger}>
        {LEDGER.map((row) => (
          <Part key={row.label} className={styles.row}>
            <dt>{row.label}</dt>
            <dd>
              <Count value={row.value} />
            </dd>
          </Part>
        ))}
      </dl>
      <Part as="p" className={styles.note}>
        The 87 were tested once, after every choice was fixed, at the same alert burden as the model before. Recorded
        landslides after 2018 are incomplete, so the catch counts compare models rather than promise a rate.
      </Part>
    </div>
  )
}

function Demo({ go }: { go: (to: string) => void }) {
  return (
    <div className={styles.column}>
      <Part as="h2" className={styles.heading}>
        Now, the live chart.
      </Part>
      <Part as="p" className={styles.body}>
        The map is today&rsquo;s run: every cell at its level, the rain that put it there, and three days of forecast.
        Open any alert to see why.
      </Part>
      <Part className={styles.actions}>
        <button type="button" className={styles.primary} onClick={() => go('/map')}>
          Open the live map
        </button>
        <button type="button" className={styles.secondary} onClick={() => go('/alerts-why')}>
          Every alert and why
        </button>
        <button type="button" className={styles.secondary} onClick={() => go('/')}>
          The story of the chart
        </button>
      </Part>
      <Part as="p" className={styles.fine}>
        A research prototype, not validated for public warnings.
      </Part>
    </div>
  )
}

/** The slides, each with the story camera position it flies to (0 the whole map, 1 the Himalaya close, 2 the Ghats
 *  with rain, 3 the Himalayan arc with the levels, 4 the whole map with everything). */
const SLIDES = [
  { id: 'title', label: 'AetherGuard', camera: 0 },
  { id: 'failures', label: 'Why warnings fail', camera: 1 },
  { id: 'solution', label: 'The solution', camera: 4 },
  { id: 'pipeline', label: 'Two-stage pipeline', camera: 2 },
  { id: 'model', label: 'The core model', camera: 3 },
  { id: 'sources', label: 'Data sources', camera: 2.2 },
  { id: 'numbers', label: 'The numbers', camera: 3.4 },
  { id: 'demo', label: 'The demo', camera: 4 },
] as const

const fromHash = () => {
  const n = Number.parseInt(window.location.hash.replace('#', ''), 10)
  return Number.isFinite(n) ? Math.min(SLIDES.length, Math.max(1, n)) - 1 : 0
}

/**
 * The presentation: eight full-screen slides over the live terrain. Each slide flies the camera to its own view and
 * brings its parts in one after another; arrows, space, Page Up/Down, Home/End and the controls move through it, F goes
 * full screen. The slide number is in the address, so a reload or a shared link opens the same slide.
 */
export default function Deck() {
  const [index, setIndex] = useState(fromHash)
  const navigate = useNavigate()
  const go = useCallback((to: string) => void navigate(to, { viewTransition: true }), [navigate])
  const move = useCallback((by: number) => setIndex((i) => Math.min(SLIDES.length - 1, Math.max(0, i + by))), [])

  useEffect(() => {
    useStory.getState().enter(true)
    return () => useStory.getState().leave()
  }, [])
  useEffect(() => {
    useStory.getState().setPosition(SLIDES[index]!.camera)
    window.history.replaceState(null, '', `#${index + 1}`)
  }, [index])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLElement && e.target.closest('input, select, textarea')) return
      if (['ArrowRight', 'ArrowDown', 'PageDown', ' ', 'Enter'].includes(e.key) && !(e.key === 'Enter' && e.target instanceof HTMLButtonElement)) {
        e.preventDefault()
        move(1)
      } else if (['ArrowLeft', 'ArrowUp', 'PageUp', 'Backspace'].includes(e.key)) {
        e.preventDefault()
        move(-1)
      } else if (e.key === 'Home') setIndex(0)
      else if (e.key === 'End') setIndex(SLIDES.length - 1)
      else if (e.key === 'f' || e.key === 'F') {
        if (document.fullscreenElement) void document.exitFullscreen()
        else void document.documentElement.requestFullscreen?.()
      } else if (e.key === 'Escape' && !document.fullscreenElement) go('/')
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [move, go])

  const current = SLIDES[index]!
  const content = {
    title: <Title />,
    failures: <Failures />,
    solution: <Solution />,
    pipeline: <Pipeline />,
    model: <Model />,
    sources: <Sources />,
    numbers: <Numbers />,
    demo: <Demo go={go} />,
  }[current.id]

  return (
    <div className={styles.deck} data-slide={current.id}>
      <h1 className="sr-only">AetherGuard presentation</h1>
      <div className={styles.veil} aria-hidden="true" />
      <AnimatePresence mode="wait">
        <motion.section
          key={current.id}
          className={styles.slide}
          variants={slide}
          initial="hidden"
          animate="shown"
          exit="gone"
          aria-roledescription="slide"
          aria-label={`${index + 1} of ${SLIDES.length}: ${current.label}`}
        >
          {content}
        </motion.section>
      </AnimatePresence>

      <nav className={styles.controls} aria-label="Slides">
        <button type="button" onClick={() => move(-1)} disabled={index === 0} aria-label="Previous slide">
          <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
            <path d="m15 6-6 6 6 6" />
          </svg>
        </button>
        <ol>
          {SLIDES.map((s, i) => (
            <li key={s.id}>
              <button type="button" onClick={() => setIndex(i)} aria-current={i === index ? 'step' : undefined} aria-label={`${i + 1}: ${s.label}`}>
                <span />
              </button>
            </li>
          ))}
        </ol>
        <span className={`num ${styles.counter}`} aria-hidden="true">
          {String(index + 1).padStart(2, '0')} / {String(SLIDES.length).padStart(2, '0')}
        </span>
        <button type="button" onClick={() => move(1)} disabled={index === SLIDES.length - 1} aria-label="Next slide">
          <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
            <path d="m9 6 6 6-6 6" />
          </svg>
        </button>
      </nav>
      <Link to="/" viewTransition className={styles.exit}>
        Exit
      </Link>
    </div>
  )
}
