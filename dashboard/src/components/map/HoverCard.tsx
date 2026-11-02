import { useLayoutEffect, useRef, useState } from 'react'
import { useMode, usePlaces } from '../../data/hooks'
import { raisedReasons } from '../../data/reasons'
import { gridCertainty, sourceName } from '../../data/certainty'
import { describeOdds, describePlace, describeRisk, MODEL_ESTIMATE, oddsOptions, oddsWhen } from '../../data/summary'
import { CONFIDENCES, type Grid, LEVELS, type Places } from '../../data/types'
import { LEVEL_HEX } from '../../scene/levelColors'
import { findCell } from '../../scene/riskTexture'
import { watchForCell } from '../../data/thresholds'
import { useMapState } from '../../state/map'
import styles from './MapPanels.module.css'

const OFFSET = 16

/**
 * The details of one cell, from the grid; null when the grid does not hold it. `places` is the table loaded once for
 * the page: nothing here asks the API, so hovering never causes a request.
 */
export function describeCell(grid: Grid, cell: number, watch?: number | null, places?: Places | null, today = false) {
  const index = findCell(grid, cell)
  if (index < 0) return null
  const oddsFor = oddsOptions(grid.flags?.[index])
  return {
    cell,
    location: describePlace(cell, places?.lookup(cell), places?.farKm),
    level: grid.level[index]!,
    levelName: LEVELS[grid.level[index]! as 0 | 1 | 2 | 3] ?? 'Unknown',
    risk: describeRisk(grid.risk[index]!, watch),
    /** "About 1 in N chance ..." in words (why none is given for a rain-capped cell); null where there is no risk to put in words. */
    odds: describeOdds(grid.risk[index]!, oddsWhen(grid.date, grid.lead, today), oddsFor),
    /** The rain trigger capped this cell: its risk is shown only as the model's estimate. */
    capped: oddsFor.capped === true,
    /** Forecast leads: "Firm" or "Depends on rain forecast (Watch–Warning)" with a line on why; null for D0. */
    certainty: gridCertainty(grid, index),
    confidence: CONFIDENCES[grid.confidence[index]! as 0 | 1 | 2] ?? 'Unknown',
    /** Why the level is above the risk band, when the grid says so (blind escalation, hysteresis hold). */
    reasons: raisedReasons(grid.flags?.[index] ?? 0),
  }
}

/** Follows the pointer over the map and says what the cell under it is. Decorative to assistive tech; the alert list carries the same facts. */
export default function HoverCard({ grid }: { grid: Grid | undefined }) {
  const hover = useMapState((s) => s.hover)
  const ref = useRef<HTMLDivElement>(null)
  const [shift, setShift] = useState({ x: 0, y: 0 })

  useLayoutEffect(() => {
    const el = ref.current
    if (!el || !hover) return
    const { width, height } = el.getBoundingClientRect()
    setShift({
      x: hover.x + OFFSET + width > window.innerWidth ? -(width + 2 * OFFSET) : 0,
      y: hover.y + OFFSET + height > window.innerHeight ? -(height + 2 * OFFSET) : 0,
    })
  }, [hover])

  const mode = useMode().data
  const places = usePlaces().data
  const today = mode?.mode === 'live' && grid !== undefined && mode.latest_date === grid.date
  const info = hover && grid ? describeCell(grid, hover.cell, watchForCell(mode, hover.cell), places, today) : null
  if (!hover || !info) return null

  return (
    <div
      ref={ref}
      className={styles.hover}
      role="tooltip"
      data-testid="hover-card"
      style={{ left: hover.x + OFFSET + shift.x, top: hover.y + OFFSET + shift.y }}
    >
      <div className={styles.hoverTitle}>
        <i className={styles.swatch} style={{ background: LEVEL_HEX[info.level] }} aria-hidden="true" />
        <strong>{info.levelName}</strong>
        <span className="num">Cell {info.cell}</span>
      </div>
      <dl className={styles.hoverFacts}>
        <div>
          <dt>Location</dt>
          <dd className={styles.hoverWhere}>
            <strong>{info.location.primary}</strong>
            {info.location.secondary && <span className={`num ${styles.hoverSub}`}>{info.location.secondary}</span>}
          </dd>
        </div>
        <div>
          <dt>Risk</dt>
          <dd className="num" title={info.risk.raw}>
            {info.odds && <strong className={styles.hoverOdds}>{info.odds.sentence}</strong>}
            {info.capped && <span className={styles.hoverSub}>{MODEL_ESTIMATE}</span>}
            {info.risk.primary}
            {info.risk.secondary && <span className={styles.hoverSub}>{info.risk.secondary}</span>}
          </dd>
        </div>
        <div>
          <dt>Confidence</dt>
          <dd>{info.confidence}</dd>
        </div>
        {grid!.lead > 0 && (
          <div>
            <dt>Forecast</dt>
            <dd>
              D+{grid!.lead}
              {info.certainty ? (
                <>
                  {' '}
                  <strong data-certainty={info.certainty.kind}>{info.certainty.headline}</strong>
                  <span className={styles.hoverSub}>{info.certainty.why}</span>
                </>
              ) : (
                <span className={styles.hoverSub}>a forecast, not an observation</span>
              )}
              {sourceName(grid!.forecast) && <span className={styles.hoverSub}>Rain: {sourceName(grid!.forecast)}</span>}
            </dd>
          </div>
        )}
      </dl>
      {info.reasons.map((line) => (
        <p key={line} className={styles.hoverReason}>
          {line}
        </p>
      ))}
    </div>
  )
}
