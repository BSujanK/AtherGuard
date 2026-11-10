import { formatDate, formatDayMonth } from '../../data/summary'
import { LEVELS } from '../../data/types'
import { REGION_LABELS, type RegionFilter } from '../../scene/geo'
import { LEVEL_HEX } from '../../scene/levelColors'
import type { MapModel } from '../../scene/useMapModel'
import { type Lead, LEADS, useMapState } from '../../state/map'
import styles from './MapControls.module.css'

const LEAD_LABEL = ['D0', 'D+1', 'D+2', 'D+3'] as const
const REGIONS: readonly RegionFilter[] = ['all', 'himalaya', 'western_ghats']

/** A reason without the lead number the API puts in it, so one cause shared by several leads reads the same. */
function commonReason(reason: string): string {
  return reason.replace(/\blead[- ]?[1-3]\b/g, 'lead').replace(/\s*\([^)]*\)\s*$/, '')
}

/**
 * Why leads are unavailable: one line naming every lead when they share a cause ("D+1, D+2, D+3:
 * replay set holds lead 0 only"), else one line per lead with the API's own message.
 */
export function unavailableNotes(model: Pick<MapModel, 'leadStatus'>): string[] {
  const missing = ([1, 2, 3] as const).flatMap((lead) => {
    const status = model.leadStatus[lead]
    return status.state === 'unavailable' ? [{ lead, reason: status.reason }] : []
  })
  if (missing.length > 1 && new Set(missing.map((m) => commonReason(m.reason))).size === 1) {
    return [`${missing.map((m) => LEAD_LABEL[m.lead]).join(', ')}: ${commonReason(missing[0]!.reason)}`]
  }
  return missing.map((m) => `${LEAD_LABEL[m.lead]}: ${m.reason}`)
}

/** Date scrubber, lead switch, level filter, region toggle and reset, all native inputs so the keyboard just works. */
export default function MapControls({ model }: { model: MapModel }) {
  const { date, lead, levels, region } = useMapState()
  const setDate = useMapState((s) => s.setDate)
  const setLead = useMapState((s) => s.setLead)
  const toggleLevel = useMapState((s) => s.toggleLevel)
  const setRegion = useMapState((s) => s.setRegion)
  const resetView = useMapState((s) => s.resetView)

  const { dates } = model
  const current = date ?? model.date
  const index = Math.max(0, current ? dates.indexOf(current) : dates.length - 1)

  return (
    <section className={styles.controls} aria-label="Map controls">
      <div className={styles.group}>
        <label className={styles.label} htmlFor="map-date">
          Date
        </label>
        <div className={styles.slider}>
          <input
            id="map-date"
            type="range"
            min={0}
            max={Math.max(0, dates.length - 1)}
            step={1}
            value={index}
            disabled={dates.length < 2}
            aria-valuetext={formatDate(dates[index] ?? null)}
            aria-describedby="map-date-range"
            onChange={(e) => setDate(dates[Number(e.target.value)] ?? null)}
          />
          <div className={styles.range} id="map-date-range">
            <span className={`num ${styles.first}`}>{formatDayMonth(dates[0] ?? null)}</span>
            <strong className={`num ${styles.current}`}>{formatDate(dates[index] ?? null)}</strong>
            <span className={`num ${styles.last}`}>{formatDayMonth(dates.at(-1) ?? null)}</span>
          </div>
        </div>
        {dates.length < 2 && <p className={styles.note}>Only one date is available.</p>}
      </div>

      <fieldset className={styles.group}>
        <legend className={styles.label}>Lead</legend>
        <div className={styles.segment}>
          {LEADS.map((l: Lead) => {
            const status = l === 0 ? null : model.leadStatus[l as 1 | 2 | 3]
            const disabled = status?.state === 'unavailable'
            return (
              <label
                key={l}
                className={styles.chip}
                title={disabled ? status.reason : l > 0 ? 'Forecast: each cell is Firm or Depends on the rain forecast' : undefined}
              >
                <input
                  type="radio"
                  name="map-lead"
                  checked={lead === l}
                  disabled={disabled}
                  aria-describedby="map-lead-note"
                  onChange={() => setLead(l)}
                />
                <span>{LEAD_LABEL[l]}</span>
              </label>
            )
          })}
        </div>
      </fieldset>

      <fieldset className={`${styles.group} ${styles.levels}`}>
        <legend className={styles.label}>Show levels</legend>
        <div className={styles.toggles}>
          {LEVELS.map((name, i) => (
            <label key={name} className={styles.chip}>
              <input type="checkbox" checked={levels[i]} onChange={() => toggleLevel(i)} />
              <span>
                <i className={styles.swatch} style={{ background: LEVEL_HEX[i] }} aria-hidden="true" />
                {name}
              </span>
            </label>
          ))}
        </div>
      </fieldset>

      <fieldset className={styles.group}>
        <legend className={styles.label}>Region</legend>
        <div className={styles.segment}>
          {REGIONS.map((r) => (
            <label key={r} className={styles.chip}>
              <input type="radio" name="map-region" checked={region === r} onChange={() => setRegion(r)} />
              <span>{REGION_LABELS[r]}</span>
            </label>
          ))}
        </div>
      </fieldset>

      <div className={styles.resetRow}>
        <button type="button" className={styles.reset} onClick={resetView}>
          Reset view
        </button>
      </div>
    </section>
  )
}
