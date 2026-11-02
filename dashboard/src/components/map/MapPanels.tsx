import { sourceName } from '../../data/certainty'
import { useMode, usePlaces } from '../../data/hooks'
import {
  describeOdds,
  describePlace,
  describeRisk,
  formatCount,
  formatDate,
  MODEL_ESTIMATE,
  NEUTRAL_RAIN,
  oddsOptions,
  oddsWhen,
  rainSourceName,
  spokenRisk,
} from '../../data/summary'
import { CONFIDENCES, LEVELS } from '../../data/types'
import { LEVEL_HEX } from '../../scene/levelColors'
import type { MapModel } from '../../scene/useMapModel'
import { useMapState } from '../../state/map'
import { unavailableNotes } from './MapControls'
import { alertCount, topAlerts } from './topAlerts'
import styles from './MapPanels.module.css'

const LIST_LENGTH = 12

/** Which leads can be shown and why not, what a column's height means, and the state of the rain layer. */
export function MapLegend({ model, degraded }: { model: MapModel; degraded: boolean }) {
  const { grid, rain, rainMissing } = model
  const notes = unavailableNotes(model)
  const places = usePlaces().data
  const forecastReady = [1, 2, 3].some((l) => model.leadStatus[l as 1 | 2 | 3].state === 'ready')
  return (
    <section className={styles.panel} aria-label="Legend">
      <div id="map-lead-note" className={styles.fine}>
        {forecastReady && (
          <p>
            D+1 to D+3 are forecasts. <b>Firm</b>: the level would be the same with no more rain, with the forecast rain and
            with a lot more, because rain already fallen sets it. <b>Depends on rain forecast</b>: the level changes with the
            rain still to come; the range of levels is shown.
          </p>
        )}
        {notes.map((n) => (
          <p key={n}>{n}</p>
        ))}
      </div>
      <p className={styles.fine}>
        Columns mark Warning and Emergency; their height is risk relative to the highest in view. Watch is the lime
        tint on the terrain; switch on Watch columns to stand those up too.
      </p>
      <p className={styles.fine}>
        Not modelled: risk is computed for the Himalaya and Western Ghats hill cells
        {grid ? ` (${formatCount(grid.n)})` : ''}; the rest of India is shown for context.
      </p>
      <p className={styles.fine}>
        {rain
          ? `Rain streaks follow the day's ${rainSourceName(rain) ? `1-day rain (${rain.unit}) from ${rainSourceName(rain)}` : NEUTRAL_RAIN}; none where it did not rain.`
          : rainMissing
            ? 'Rain layer: the API has no rain field for this date.'
            : 'Rain layer: loading.'}
      </p>
      {grid && grid.lead > 0 && (
        <p className={styles.fine}>
          Showing the D+{grid.lead} forecast
          {sourceName(grid.forecast) ? `; forecast rain: ${sourceName(grid.forecast)}.` : '.'}
        </p>
      )}
      {degraded && <p className={styles.fine}>Effects reduced to keep the map smooth.</p>}
      {grid?.forecast?.attribution && grid.lead > 0 && <p className={styles.attribution}>{grid.forecast.attribution}.</p>}
      {places && <p className={styles.attribution}>{places.attribution}</p>}
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
  const watch = model.mode?.thresholds?.watch
  return (
    <details className={styles.panel}>
      <summary className={styles.summary}>
        Top alerts on the map <span className="num">({formatCount(total)})</span>
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
            const risk = describeRisk(a.risk, watch)
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
    </details>
  )
}
