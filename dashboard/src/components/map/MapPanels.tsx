import { sourceName } from '../../data/certainty'
import { useMode, usePlaces } from '../../data/hooks'
import {
  describeOdds,
  describePlace,
  describeRisk,
  formatCount,
  formatDate,
  MODEL_ESTIMATE,
  oddsOptions,
  oddsWhen,
  spokenRisk,
} from '../../data/summary'
import { watchForCell } from '../../data/thresholds'
import { CONFIDENCES, LEVELS } from '../../data/types'
import { LEVEL_HEX } from '../../scene/levelColors'
import type { MapModel } from '../../scene/useMapModel'
import { useMapState } from '../../state/map'
import { unavailableNotes } from './MapControls'
import { alertCount, topAlerts } from './topAlerts'
import styles from './MapPanels.module.css'

const LIST_LENGTH = 12

/** The few things the map cannot say by itself: why a lead is unavailable, a missing rain layer, and the credits. */
export function MapLegend({ model, degraded }: { model: MapModel; degraded: boolean }) {
  const { grid, rain, rainMissing } = model
  const notes = unavailableNotes(model)
  const forecast = grid !== undefined && grid.lead > 0
  // Nothing to say on an ordinary day: no panel then, only the (empty) note the lead control points at.
  if (notes.length === 0 && !(!rain && rainMissing) && !forecast && !degraded) return <div id="map-lead-note" hidden />
  return (
    <section className={`${styles.panel} ${styles.notes}`} aria-label="Legend">
      <div id="map-lead-note" className={styles.fine}>
        {notes.map((n) => (
          <p key={n}>{n}</p>
        ))}
      </div>
      {!rain && rainMissing && <p className={styles.fine}>Rain layer: the API has no rain field for this date.</p>}
      {grid && grid.lead > 0 && (
        <p className={styles.fine}>
          Showing the D+{grid.lead} forecast
          {sourceName(grid.forecast) ? `; forecast rain: ${sourceName(grid.forecast)}.` : '.'}
        </p>
      )}
      {degraded && <p className={styles.fine}>Effects reduced to keep the map smooth.</p>}
      {grid?.forecast?.attribution && grid.lead > 0 && <p className={styles.attribution}>{grid.forecast.attribution}.</p>}
    </section>
  )
}

/**
 * The map as text: how many cells are at Watch or above and the top few, each a button that opens
 * the cell. This is the keyboard and screen reader route to everything the canvas shows.
 */
export function AlertList({ model }: { model: MapModel }) {
  const openCell = useMapState((s) => s.openCell)
  const { grid, visible } = model
  const places = usePlaces().data
  const mode = useMode().data
  if (!grid || !visible) return null

  const today = mode?.mode === 'live' && mode.latest_date === grid.date
  const total = alertCount(grid, visible)
  const top = topAlerts(grid, visible, LIST_LENGTH)
  return (
    <details className={`${styles.panel} ${styles.disclosure}`} open>
      <summary className={styles.summary}>
        <span>
          Top alerts on the map <span className="num">({formatCount(total)})</span>
        </span>
        <svg className={styles.chevron} viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="m6 9 6 6 6-6" />
        </svg>
      </summary>
      <p className="sr-only" role="status">
        {formatCount(total)} cells at Watch or above on {formatDate(grid.date)}, lead D{grid.lead === 0 ? '0' : `+${grid.lead}`}.
      </p>
      {top.length === 0 ? (
        <p className={styles.fine}>No cell at Watch or above with the current filters.</p>
      ) : (
        <ol className={styles.alerts} aria-label="Top alerts">
          {top.map((a) => {
            const where = describePlace(a.cell, places?.lookup(a.cell), places?.farKm)
            const risk = describeRisk(a.risk, watchForCell(model.mode, a.cell))
            const oddsFor = oddsOptions(a.flags)
            const odds = describeOdds(a.risk, oddsWhen(grid.date, grid.lead, today), oddsFor)
            const label = `Cell ${a.cell}, ${where.primary}, ${LEVELS[a.level as 0 | 1 | 2 | 3]}, risk ${spokenRisk(risk)}, ${CONFIDENCES[a.confidence as 0 | 1 | 2]} confidence`
            return (
              <li key={a.cell}>
                <button type="button" onClick={() => openCell(a.cell)} aria-label={`${label}. Open details`}>
                  <i className={styles.swatch} style={{ background: LEVEL_HEX[a.level] }} aria-hidden="true" />
                  <span className={styles.alertMain}>
                    <strong>{LEVELS[a.level as 0 | 1 | 2 | 3]}</strong>
                    <span className="num" title={where.primary}>
                      {where.primary}
                    </span>
                    {where.secondary && (
                      <span className={`num ${styles.alertSub}`} title={where.secondary}>
                        {where.secondary}
                      </span>
                    )}
                  </span>
                  <span className={`num ${styles.alertRisk}`} title={odds ? `${odds.sentence}. ${oddsFor.capped ? `${MODEL_ESTIMATE}: ` : ''}${risk.raw}` : risk.raw}>
                    {odds ? odds.short : risk.primary}
                    {odds && <span>{risk.primary}</span>}
                    {!odds && risk.secondary && <span>{risk.secondary}</span>}
                  </span>
                </button>
              </li>
            )
          })}
        </ol>
      )}
      {places && <p className={styles.attribution}>{places.attribution}</p>}
    </details>
  )
}
