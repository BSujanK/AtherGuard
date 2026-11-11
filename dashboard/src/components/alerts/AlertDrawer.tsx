import { useQueryClient } from '@tanstack/react-query'
import { lazy, type ReactNode, Suspense, useRef } from 'react'
import { createPortal } from 'react-dom'
import { ApiError } from '../../data/api'
import { queryKeys, useCell, useCellHistory, useGrid, useMode, usePlaces } from '../../data/hooks'
import { describeCertainty, forecastShortName, sourceName } from '../../data/certainty'
import { cappedExplanation, confidenceCause, confidenceMeaning, reasonCode } from '../../data/reasons'
import {
  addDays,
  describeOdds,
  describePlace,
  describeRisk,
  formatDate,
  formatDayMonth,
  formatPer100k,
  formatWeekday,
  MODEL_ESTIMATE,
  oddsWhen,
  type RiskText,
} from '../../data/summary'
import { type CellDetail, LEVELS, type PlaceLabel } from '../../data/types'
import { type ScopedThresholds, thresholdsOfCell } from '../../data/thresholds'
import { LEVEL_HEX } from '../../scene/levelColors'
import { REGION_LABELS, type RegionName } from '../../scene/geo'
import EmptyState from '../EmptyState'
import { rainRows } from './evidence'
import LeadSwitch from './LeadSwitch'
import NeighbourhoodView from './NeighbourhoodView'
import { useDialog } from './useDialog'
import styles from './AlertDrawer.module.css'

const ShapBars = lazy(() => import('../../charts/ShapBars'))
const SourcesCompare = lazy(() => import('../../charts/SourcesCompare'))
const RainHistory = lazy(() => import('../../charts/RainHistory'))
const RiskTrend = lazy(() => import('../../charts/RiskTrend'))

const words = (code: string) => code.replace(/_/g, ' ')

function Section({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section className={styles.section} aria-labelledby={id}>
      <h3 id={id}>{title}</h3>
      {children}
    </section>
  )
}

const Loading = ({ what }: { what: string }) => (
  <p className={styles.hint} role="status">
    Loading {what}
  </p>
)

function regionLabel(region: string | null): string {
  return region !== null && region in REGION_LABELS ? REGION_LABELS[region as RegionName] : (region ?? 'Outside both regions')
}

function LevelSection({
  detail,
  scoped,
  risk,
  today,
  heldFrom,
}: {
  detail: CellDetail
  scoped: ScopedThresholds
  risk: RiskText
  today: boolean
  /** The date the level of a cell without a score is held from, when known. */
  heldFrom: string | null
}) {
  const { thresholds, scope } = scoped
  const held = detail.rawLevel !== '' && detail.rawLevel !== detail.levelName
  const isCapped = detail.reasonCodes.includes('no_recent_rain')
  const odds = describeOdds(detail.risk, oddsWhen(detail.issuedDate, detail.lead, today), {
    capped: isCapped,
    disagrees: detail.confidenceCauses.includes('ensemble_disagrees'),
  })
  const certainty = describeCertainty(detail.certainty, detail.levelMin, detail.levelMax)
  const capped = cappedExplanation(detail.reasonCodes, detail.rainRule)
  return (
    <Section id="drawer-level" title="Level">
      <p className={styles.levelLine}>
        <i style={{ background: LEVEL_HEX[detail.level] }} aria-hidden="true" />
        <strong>{LEVELS[detail.level]}</strong>
        {held && <span className={styles.muted}>(risk alone gives {detail.rawLevel})</span>}
      </p>
      {capped && (
        <p className={styles.capped} data-testid="capped-reason">
          {capped}
        </p>
      )}
      {certainty && (
        <p className={styles.certainty} data-certainty={certainty.kind} data-testid="certainty">
          <strong>{certainty.headline}</strong>
          <span className={styles.muted}>{certainty.why}</span>
        </p>
      )}
      {odds && (
        <p className={styles.oddsLine} data-testid="odds">
          {odds.sentence}.
        </p>
      )}
      <p className={styles.riskLine} title={risk.raw}>
        {isCapped && <span className={styles.muted}>{MODEL_ESTIMATE}</span>}
        <span className={`num ${styles.riskBig}`}>{risk.primary}</span>
        {risk.secondary && (
          <span className={styles.muted}>
            {risk.secondary}
            {isCapped && `, ${MODEL_ESTIMATE}`}
          </span>
        )}
      </p>
      {detail.riskLo !== null && detail.riskHi !== null && (
        <p className={styles.muted}>
          {isCapped ? `Likely range of the ${MODEL_ESTIMATE}` : 'Likely range'} <span className="num">{formatPer100k(detail.riskLo)}</span> to{' '}
          <span className="num">{formatPer100k(detail.riskHi)}</span> per 100k cell-days.
          {detail.widened === true && ' The range is widened for forecast uncertainty.'}
        </p>
      )}
      {thresholds ? (
        <p className={styles.muted}>
          {scope} thresholds, per 100k cell-days: Watch <span className="num">{formatPer100k(thresholds.watch)}</span>, Warning{' '}
          <span className="num">{formatPer100k(thresholds.warning)}</span>, Emergency{' '}
          <span className="num">{formatPer100k(thresholds.emergency)}</span>.
        </p>
      ) : (
        <p className={styles.muted}>The API did not report the alert thresholds for this set.</p>
      )}
      {detail.reasonCodes.length > 0 ? (
        <ul className={styles.codes} aria-label="Why this level">
          {detail.reasonCodes.map((code) => {
            const { label, detail: text } = reasonCode(code)
            return (
              <li key={code}>
                <strong>{label}</strong>
                <span>
                  {text}
                  {code === 'model_input_missing' && heldFrom && ` The level is held from ${formatDate(heldFrom)}, the last day with a risk score.`}
                </span>
              </li>
            )
          })}
        </ul>
      ) : (
        <p className={styles.muted}>No reason code was recorded for this cell-day.</p>
      )}
    </Section>
  )
}

/** The header badge of a forecast: Firm, or Depends on rain forecast with the levels it can take. */
function CertaintyBadge({ detail }: { detail: CellDetail | undefined }) {
  const certainty = detail ? describeCertainty(detail.certainty, detail.levelMin, detail.levelMax) : null
  if (!certainty) return <span className={styles.badge}>forecast</span>
  return (
    <span className={styles.badge} data-certainty={certainty.kind}>
      {certainty.headline}
    </span>
  )
}

function ConfidenceSection({ detail }: { detail: CellDetail }) {
  const trust = detail.sensorTrust
  return (
    <Section id="drawer-confidence" title="Confidence">
      <p className={styles.levelLine}>
        <strong>{detail.confidence || 'Unknown'}</strong>
        <span className={styles.muted}>{confidenceMeaning(detail.confidence, detail.forecast)}</span>
      </p>
      {detail.confidenceCauses.length > 0 ? (
        <ul className={styles.codes} aria-label="Why confidence is reduced">
          {detail.confidenceCauses.map((code) => {
            const { label, detail: text } = confidenceCause(code)
            return (
              <li key={code}>
                <strong>{label}</strong>
                <span>{text}</span>
              </li>
            )
          })}
        </ul>
      ) : (
        <p className={styles.muted}>No data-quality issue was found for this cell-day.</p>
      )}
      <p className={styles.muted}>
        {detail.forecast && detail.unavailable
          ? detail.unavailable
          : trust.stations === 0
            ? 'No rain gauge reported within 100 km.'
            : `${trust.stations} ${trust.stations === 1 ? 'gauge' : 'gauges'} within 100 km: ${trust.trusted} trusted, ${trust.flagged7d} flagged in the last 7 days${
              trust.flaggedTypes.length > 0 ? ` (${trust.flaggedTypes.map(words).join(', ')})` : ''
            }, ${trust.outOfDistribution} behaving unusually.`}
      </p>
    </Section>
  )
}

function SourcesSection({ detail }: { detail: CellDetail }) {
  const rows = rainRows(detail)
  const { disagreement3, spread1day } = detail.sources
  return (
    <Section id="drawer-sources" title={detail.forecast ? 'Rain behind this forecast' : 'Rain today, by source'}>
      <Suspense fallback={<Loading what="chart" />}>
        <SourcesCompare
          bars={rows}
          title={detail.forecast ? `Rain observed through the run date and forecast by ${forecastShortName(detail.forecastSource)}` : undefined}
        />
      </Suspense>
      <dl className={styles.facts}>
        {rows.map((row) => (
          <div key={row.key}>
            <dt>{row.label}</dt>
            <dd>
              {row.value === null ? (
                <>
                  <span>not available</span> <span className={styles.muted}>{row.missing}.</span>
                </>
              ) : (
                <>
                  <span className="num">{row.value.toLocaleString('en-US', { maximumFractionDigits: 1 })} mm</span>{' '}
                  <span className={styles.muted}>{row.detail}.</span>
                </>
              )}
            </dd>
          </div>
        ))}
        {detail.forecast && detail.forecastSource && (
          <div>
            <dt>Forecast rain</dt>
            <dd>
              {sourceName(detail.forecastSource)}
              {detail.forecastSource.mapped && <span className={styles.muted}> Bias-corrected to the satellite rain scale.</span>}
              {detail.forecastSource.attribution && <span className={styles.muted}> {detail.forecastSource.attribution}.</span>}
            </dd>
          </div>
        )}
        {detail.forecast &&
          detail.forecastRain?.days.map((day) => (
            <div key={day.date}>
              <dt>{forecastShortName(detail.forecastSource)} {formatWeekday(day.date)}</dt>
              <dd>
                {day.mm === null ? 'not available' : <span className="num">{day.mm.toLocaleString('en-US', { maximumFractionDigits: 1 })} mm</span>}{' '}
                <span className={styles.muted}>forecast D+{day.lead}.</span>
              </dd>
            </div>
          ))}
        {spread1day !== null && (
          <div>
            <dt>Spread</dt>
            <dd>
              <span className="num">{spread1day.toLocaleString('en-US', { maximumFractionDigits: 1 })} mm</span>{' '}
              <span className={styles.muted}>between the highest and lowest source</span>
            </dd>
          </div>
        )}
        {disagreement3 !== null && (
          <div>
            <dt>3-day ratio</dt>
            <dd>
              <span className="num">{disagreement3.toLocaleString('en-US', { maximumFractionDigits: 2 })}</span>{' '}
              <span className={styles.muted}>IMD over satellite</span>
            </dd>
          </div>
        )}
      </dl>
    </Section>
  )
}

function HistorySection({ cell, date, set, scoped }: { cell: number; date: string; set: string | null; scoped: ScopedThresholds }) {
  const history = useCellHistory(cell, date, set)
  let body: ReactNode
  if (history.isPending) body = <Loading what="the last 30 days" />
  else if (history.isError) {
    body = (
      <p className={styles.hint} role="status">
        {history.error instanceof ApiError && history.error.status === 404
          ? history.error.message
          : 'The 30-day history could not be loaded.'}
      </p>
    )
  } else {
    const days = history.data.dates.length
    body = (
      <>
        <p className={styles.muted}>
          {days} {days === 1 ? 'day' : 'days'} with a score, ending {formatDate(history.data.dates[days - 1] ?? null)}. A gap means a
          source had no value that day.
          {history.data.forecast.length > 0 &&
            ` The dashed line is the D+1 to D+${history.data.forecast.length} forecast of the run of ${formatDayMonth(history.data.issuedDate ?? history.data.dates[days - 1] ?? null)}.`}
          {scoped.thresholds && ` The horizontal lines are the ${scoped.scope} Watch, Warning and Emergency thresholds.`}
        </p>
        <Suspense fallback={<Loading what="charts" />}>
          <RainHistory history={history.data} />
          <RiskTrend history={history.data} thresholds={scoped.thresholds} />
        </Suspense>
      </>
    )
  }
  return (
    <Section id="drawer-history" title="Last 30 days">
      {body}
    </Section>
  )
}

function NeighbourhoodSection({ cell, date, lead, onSelect }: { cell: number; date: string; lead: number; onSelect: (cell: number) => void }) {
  const grid = useGrid(date, lead)
  return (
    <Section id="drawer-around" title="Around this cell">
      {grid.data ? (
        <NeighbourhoodView grid={grid.data} centre={cell} onSelect={onSelect} />
      ) : grid.isError ? (
        <p className={styles.hint} role="status">
          The risk grid for this date could not be loaded, so the neighbourhood cannot be drawn.
        </p>
      ) : (
        <Loading what="the neighbourhood" />
      )}
    </Section>
  )
}

interface AlertDrawerProps {
  /** The cell id from the address; null when it is not a valid number. */
  cell: number | null
  rawCell: string
  date: string | null
  /** The replay set or `live` the view is showing. */
  set: string | null
  /** 0 for the run date's assessment, 1 to 3 for the forecast of the live run of `date`. */
  lead: number
  /** The leads the run of `date` published, for the switch. */
  leads: readonly number[]
  onLeadChange: (lead: number) => void
  onClose: () => void
  onSelectCell: (cell: number) => void
  /** Element to focus on close when the one that opened the drawer is gone. */
  returnFocus?: () => HTMLElement | null
}

/** The explanation of one cell-day, as a modal dialog over the feed. */
export default function AlertDrawer({
  cell,
  rawCell,
  date,
  set,
  lead,
  leads,
  onLeadChange,
  onClose,
  onSelectCell,
  returnFocus,
}: AlertDrawerProps) {
  const panel = useRef<HTMLElement>(null)
  const queryClient = useQueryClient()
  const detail = useCell(cell, date, set, lead)
  const places = usePlaces().data
  useDialog(panel, onClose, returnFocus)

  const mode = useMode().data
  const scoped = thresholdsOfCell(detail.data, mode)
  const risk = describeRisk(detail.data?.risk, scoped.thresholds?.watch)
  const today = mode?.mode === 'live' && mode.latest_date === date
  const lastScored = mode?.last_scored_date
  const heldFrom = today && !detail.data?.forecast && lastScored && lastScored !== date ? lastScored : null
  const label: PlaceLabel | null = cell !== null ? (places?.lookup(cell) ?? detail.data?.place ?? null) : null
  const where = cell !== null ? describePlace(cell, label, places?.farKm) : null
  const target = date !== null && lead > 0 ? addDays(date, lead) : date

  let body: ReactNode
  if (cell === null) {
    body = (
      <EmptyState title="Not a cell id">
        &ldquo;{rawCell}&rdquo; is not a cell id. Cell ids are whole numbers; pick a cell from the feed.
      </EmptyState>
    )
  } else if (date === null) {
    body = <EmptyState title="No date to look up">There is no date to read this cell on, because no data has landed yet.</EmptyState>
  } else if (detail.isPending) {
    body = <Loading what="the cell" />
  } else if (detail.isError) {
    const missing = detail.error instanceof ApiError && detail.error.status === 404
    body = (
      <EmptyState
        title={missing ? 'No alert for this cell and date' : 'This cell could not be loaded'}
        action={
          missing ? undefined : (
            <button type="button" onClick={() => void queryClient.invalidateQueries({ queryKey: queryKeys.cell(cell, date, set, lead) })}>
              Try again
            </button>
          )
        }
      >
        {detail.error.message}
      </EmptyState>
    )
  } else {
    const d = detail.data
    body = (
      <>
        {d.detailMissing && (
          <p className={styles.notice} role="status">
            Some detail is missing: {d.detailMissing}.
          </p>
        )}
        <LevelSection detail={d} scoped={scoped} risk={risk} today={today} heldFrom={heldFrom} />
        <ConfidenceSection detail={d} />
        <Section id="drawer-why" title="Why the model says this">
          {d.shap.length > 0 ? (
            <>
              <Suspense fallback={<Loading what="chart" />}>
                <ShapBars shap={d.shap} />
              </Suspense>
              <p className={styles.muted}>
                The five inputs that moved the risk most. Orange raised it, cyan lowered it, in log-odds of the model&apos;s raw score.
              </p>
            </>
          ) : (
            <p className={styles.muted}>
              No input contributions are stored for this {d.forecast ? 'forecast' : 'cell-day'}
              {d.detailMissing ? `: ${d.detailMissing}` : ''}.
            </p>
          )}
        </Section>
        <SourcesSection detail={d} />
        <HistorySection cell={d.cell} date={d.date} set={set} scoped={scoped} />
        <NeighbourhoodSection cell={d.cell} date={d.date} lead={lead} onSelect={onSelectCell} />
      </>
    )
  }

  // Portalled to the body: inside the view the top bar (a sibling with a higher layer) would cover the sheet's header.
  return createPortal(
    <div className={styles.layer}>
      <div className={styles.scrim} onClick={onClose} aria-hidden="true" />
      <aside ref={panel} className={styles.panel} role="dialog" aria-modal="true" aria-labelledby="drawer-title" data-testid="alert-drawer">
        <header className={styles.head}>
          <div className={styles.headText}>
            <p className={styles.kicker}>
              {lead > 0 ? 'Forecast detail' : 'Alert detail'}
              {lead > 0 && <CertaintyBadge detail={detail.data} />}
            </p>
            <h2 id="drawer-title">{cell === null ? 'Unknown cell' : label ? where!.primary : `Cell ${cell}`}</h2>
            <p className={styles.muted}>
              {[
                label && cell !== null ? `Cell ${cell}` : null,
                label ? where!.secondary : where?.primary,
                detail.data ? regionLabel(detail.data.region) : null,
              ]
                .filter(Boolean)
                .join(' · ')}
            </p>
            <p className={styles.when}>
              {lead > 0 && target && date
                ? `Forecast for ${formatWeekday(target)} (D+${lead}), issued ${formatDayMonth(date)}`
                : date
                  ? formatDate(date)
                  : null}
            </p>
          </div>
          <button type="button" className={styles.close} onClick={onClose} aria-label="Close alert details">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" aria-hidden="true">
              <path d="M6 6l12 12M18 6 6 18" />
            </svg>
          </button>
        </header>
        {cell !== null && date !== null && (
          <div className={styles.leadBar}>
            <span className={styles.muted}>Assessment for</span>
            <LeadSwitch name="drawer-lead" value={lead} available={leads} onChange={onLeadChange} />
          </div>
        )}
        <div className={styles.body}>{body}</div>
      </aside>
    </div>,
    document.body,
  )
}
