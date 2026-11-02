import { useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import ViewFrame from '../components/ViewFrame'
import HoverCard from '../components/map/HoverCard'
import MapControls from '../components/map/MapControls'
import { AlertList, MapLegend } from '../components/map/MapPanels'
import { formatDate } from '../data/summary'
import { prefersReducedMotion, webglAvailable } from '../lib/motion'
import { FLY_MS } from '../scene/cameraEase'
import { useMapModel } from '../scene/useMapModel'
import { type Lead, useMapState } from '../state/map'
import styles from './LiveMap.module.css'
import Map2D from './Map2D'

const LEAD_NAMES = ['D0', 'D+1', 'D+2', 'D+3'] as const

/**
 * The live risk map. The 3D terrain with its risk layer, columns and rain is drawn by the shared
 * canvas behind the app; this view adds the controls, the legend, the hover card and the text
 * alternative on top of it, or draws a 2D map itself when WebGL is unavailable.
 */
export default function LiveMap() {
  const model = useMapModel()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const opened = useMapState((s) => s.opened)
  const quality = useMapState((s) => s.quality)
  const setDate = useMapState((s) => s.setDate)
  const setLead = useMapState((s) => s.setLead)
  const lead = useMapState((s) => s.lead)
  const [leadNotice, setLeadNotice] = useState<string | null>(null)
  const webgl = webglAvailable()

  // A fresh visit starts without a leftover click from a previous visit, and may be deep-linked to a date and lead.
  useEffect(() => {
    useMapState.setState({ opened: null, camera: null })
    const date = params.get('date')
    if (date) setDate(date)
    const requested = Number(params.get('lead'))
    if (requested === 1 || requested === 2 || requested === 3) setLead(requested as Lead)
    // Only on mount: later changes come from the controls, not the address.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // A click flies the camera to the cell first, then opens its detail: of the date and forecast lead on the map.
  const target = useRef({ date: model.grid?.date ?? model.date, lead: model.grid?.lead ?? 0 })
  useEffect(() => {
    target.current = { date: model.grid?.date ?? model.date, lead: model.grid?.lead ?? 0 }
  }, [model.grid?.date, model.grid?.lead, model.date])
  useEffect(() => {
    if (!opened) return
    const id = setTimeout(
      () => {
        const q = new URLSearchParams({ cell: String(opened.cell) })
        if (target.current.date) q.set('date', target.current.date)
        if (target.current.lead > 0) q.set('lead', String(target.current.lead))
        void navigate(`/alerts-why?${q}`)
      },
      prefersReducedMotion() ? 0 : FLY_MS,
    )
    return () => clearTimeout(id)
  }, [opened, navigate])

  // A forecast lead that has no data for the date (or after a date change) falls back to D0 and says so.
  const unavailable = lead !== 0 && model.leadStatus[lead].state === 'unavailable'
  useEffect(() => {
    if (!unavailable) return
    const status = model.leadStatus[lead]
    setLeadNotice(
      `${LEAD_NAMES[lead]} has no data for ${formatDate(model.date)}${status.state === 'unavailable' ? ` (${status.reason.replace(/\s*\([^)]*\)\s*$/, '')})` : ''}. Showing D0.`,
    )
    setLead(0)
  }, [unavailable, lead, model.leadStatus, model.date, setLead])

  const { mode } = model
  if (!mode || mode.mode === 'none') {
    return (
      <ViewFrame
        title="Live map"
        blurb="The terrain behind this panel is the domain."
        placement="bottom-right"
      />
    )
  }

  const first = mode.dates[0] ?? null
  const last = mode.latest_date
  const messages: { key: string; text: string; action?: { label: string; run: () => void } }[] = []
  if (model.dateMissing) {
    messages.push({
      key: 'missing',
      text: `No data for ${formatDate(model.date)} in ${mode.set}. Dates available: ${formatDate(first)} to ${formatDate(last)}.`,
      action: { label: 'Show the latest date', run: () => setDate(null) },
    })
  } else if (model.gridError) {
    messages.push({ key: 'grid', text: `No risk grid for ${formatDate(model.date)}: ${model.gridError}` })
  } else if (model.gridLoading) {
    messages.push({ key: 'loading', text: `Loading the risk grid for ${formatDate(model.date)}.` })
  }
  if (model.terrainFailed) {
    messages.push({
      key: 'terrain',
      text: 'The base map is not available, so the map cannot be drawn. The list of top alerts still works.',
    })
  }
  if (leadNotice) messages.push({ key: 'lead', text: leadNotice })

  return (
    <div className={styles.root}>
      <h1 className="sr-only">Live map</h1>
      {!webgl && <Map2D model={model} />}
      <MapControls model={model} />
      <div className={styles.bottom}>
        <MapLegend model={model} degraded={quality > 0} />
        {messages.length > 0 && (
          <section className={styles.notices} aria-label="Map status" role="status">
            {messages.map((m) => (
              <p key={m.key}>
                {m.text}
                {m.action && (
                  <button type="button" onClick={m.action.run}>
                    {m.action.label}
                  </button>
                )}
              </p>
            ))}
          </section>
        )}
        <AlertList model={model} />
      </div>
      <HoverCard grid={model.grid} />
    </div>
  )
}
