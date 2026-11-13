import { type CSSProperties, useEffect, useMemo, useRef, useState } from 'react'
import type { SensorStation } from '../../data/sources'
import { formatDate } from '../../data/summary'
import type { Basemap, Outline } from '../../data/types'
import styles from './GaugeMap.module.css'
import { renderRelief } from './relief'
import { faultName, stationLabel } from './stations'
import { DOMAIN, formatTrust, inDomain, trustColor } from './trust'

/** SVG units per degree; the viewBox is the base map's box at this scale. */
const SCALE = 20
const WIDTH = (DOMAIN.lonMax - DOMAIN.lonMin) * SCALE
const HEIGHT = (DOMAIN.latMax - DOMAIN.latMin) * SCALE
const TICK_DEG = 4

const x = (lon: number) => (lon - DOMAIN.lonMin) * SCALE
const y = (lat: number) => (DOMAIN.latMax - lat) * SCALE

/** SVG path of a country's rings, one closed subpath per ring. */
const outlinePath = (rings: Outline['rings']): string =>
  rings
    .map((ring) => `M${ring.map(([lon, lat]) => `${x(lon).toFixed(1)} ${y(lat).toFixed(1)}`).join('L')}Z`)
    .join('')

const ticks = (min: number, max: number) => {
  const out: number[] = []
  for (let v = min; v <= max; v += TICK_DEG) out.push(v)
  return out
}

function describe(s: SensorStation): string {
  const fault = s.flagged || s.faultType ? faultName(s) : 'no fault'
  const last = s.trust === null && s.lastReading !== null ? `, last reading ${formatDate(s.lastReading)}` : ''
  return `${stationLabel(s)}, trust ${formatTrust(s.trust)}, ${fault}${last}`
}

function Relief({ terrain }: { terrain: Basemap }) {
  const canvas = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const el = canvas.current
    const ctx = el?.getContext('2d')
    if (!el || !ctx) return
    const img = renderRelief(terrain)
    el.width = img.width
    el.height = img.height
    ctx.putImageData(new ImageData(img.data, img.width, img.height), 0, 0)
  }, [terrain])
  return <canvas ref={canvas} className={styles.relief} aria-hidden="true" data-testid="relief" />
}

function Tooltip({ station }: { station: SensorStation }) {
  const left = x(station.lon) / WIDTH
  const top = y(station.lat) / HEIGHT
  return (
    <div
      className={styles.tip}
      data-flip={left > 0.55}
      style={{ left: `${left * 100}%`, top: `${top * 100}%` }}
      role="tooltip"
    >
      <strong>{stationLabel(station)}</strong>
      <span className={styles.id}>{station.station}</span>
      <dl>
        <div>
          <dt>Trust</dt>
          <dd className="num">{formatTrust(station.trust)}</dd>
        </div>
        <div>
          <dt>State</dt>
          <dd>{station.state || 'unknown'}</dd>
        </div>
        <div>
          <dt>Fault</dt>
          <dd>{station.flagged || station.faultType ? faultName(station) : 'none'}</dd>
        </div>
        {station.trust === null && (
          <div>
            <dt>Last reading</dt>
            <dd className="num">
              {station.lastReading === null ? 'none in the recent window' : formatDate(station.lastReading)}
            </dd>
          </div>
        )}
        {station.flagRateWindow !== null && (
          <div>
            <dt>Flagged days</dt>
            <dd className="num">{Math.round(station.flagRateWindow * 100)}% of recent window</dd>
          </div>
        )}
        {station.reasons && (
          <div>
            <dt>Reasons</dt>
            <dd>{station.reasons.split(';').join(', ')}</dd>
          </div>
        )}
      </dl>
    </div>
  )
}

interface GaugeMapProps {
  stations: SensorStation[]
  /** Base map for the faint relief backdrop and the national outlines; the map is complete without it. */
  terrain?: Basemap | null
  /** A station highlighted from outside the map (the fault list). */
  highlight?: string | null
}

/** Rain gauges on the whole-India base map, coloured by trust; flagged gauges pulse. Hover or focus shows the details. */
export default function GaugeMap({ stations, terrain, highlight = null }: GaugeMapProps) {
  const [hovered, setHovered] = useState<string | null>(null)
  const { drawn, outside } = useMemo(() => {
    const inside = stations.filter(inDomain)
    // Low trust is drawn last so a bad gauge is never hidden under a good neighbour; missing values go underneath.
    const order = (s: SensorStation) => s.trust ?? 2
    return { drawn: [...inside].sort((a, b) => order(b) - order(a)), outside: stations.length - inside.length }
  }, [stations])

  const activeId = hovered ?? highlight
  const active = activeId === null ? undefined : drawn.find((s) => s.station === activeId)

  return (
    <figure className={styles.figure}>
      <div className={styles.frame} style={{ aspectRatio: `${WIDTH} / ${HEIGHT}` }}>
        {terrain && <Relief terrain={terrain} />}
        <svg
          className={styles.svg}
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          role="group"
          aria-label={`Map of ${drawn.length} rain gauges coloured by trust`}
        >
          <g className={styles.grid} aria-hidden="true">
            {ticks(DOMAIN.lonMin, DOMAIN.lonMax).map((lon) => (
              <g key={`lon${lon}`}>
                <line x1={x(lon)} x2={x(lon)} y1={0} y2={HEIGHT} />
                <text x={x(lon) + 4} y={HEIGHT - 6}>
                  {lon}°E
                </text>
              </g>
            ))}
            {ticks(DOMAIN.latMin, DOMAIN.latMax).map((lat) => (
              <g key={`lat${lat}`}>
                <line x1={0} x2={WIDTH} y1={y(lat)} y2={y(lat)} />
                <text x={6} y={y(lat) - 5}>
                  {lat}°N
                </text>
              </g>
            ))}
            <rect x={0} y={0} width={WIDTH} height={HEIGHT} className={styles.outline} />
          </g>
          {terrain && (
            <g className={styles.countries} aria-hidden="true">
              {terrain.outline.map((country) => (
                <path key={country.name} data-country={country.name} d={outlinePath(country.rings)} />
              ))}
            </g>
          )}
          {drawn.map((s, i) => {
            const missing = s.trust === null
            const cx = x(s.lon)
            const cy = y(s.lat)
            return (
              <g
                key={s.station}
                className={styles.gauge}
                data-station={s.station}
                data-flagged={s.flagged}
                data-missing={missing}
                data-active={s.station === activeId}
                style={{ '--i': i } as CSSProperties}
              >
                {s.flagged && <circle className={styles.pulse} cx={cx} cy={cy} r={6} />}
                <circle
                  className={styles.dot}
                  cx={cx}
                  cy={cy}
                  r={5}
                  fill={s.trust === null ? undefined : trustColor(s.trust)}
                />
                <circle
                  className={styles.hit}
                  cx={cx}
                  cy={cy}
                  r={10}
                  role="img"
                  aria-label={describe(s)}
                  tabIndex={s.flagged ? 0 : -1}
                  onPointerEnter={() => setHovered(s.station)}
                  onPointerLeave={() => setHovered(null)}
                  onFocus={() => setHovered(s.station)}
                  onBlur={() => setHovered(null)}
                />
              </g>
            )
          })}
        </svg>
        {active && <Tooltip station={active} />}
      </div>
      <figcaption className={styles.legend}>
        <span className={styles.scale}>
          <span>Trusted</span>
          <span className={styles.ramp} aria-hidden="true" />
          <span>Low trust</span>
        </span>
        <span className={styles.key}>
          <span className={styles.keyMissing} aria-hidden="true" />
          No value that day
        </span>
        <span className={styles.key}>
          <span className={styles.keyFlag} aria-hidden="true" />
          Flagged
        </span>
        {outside > 0 && (
          <span>
            {outside} {outside === 1 ? 'gauge' : 'gauges'} outside the mapped area not drawn
          </span>
        )}
      </figcaption>
    </figure>
  )
}
