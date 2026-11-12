import { useEffect, useMemo, useRef } from 'react'
import { prefersReducedMotion } from '../lib/motion'
import { columnHeight, columnMinLevel } from '../scene/columns'
import { cellToTexel, lonLatToWorld, texelToCell, texelWorld, worldToTexel } from '../scene/geo'
import { easeOutMotion, FLY_MS } from '../scene/cameraEase'
import { LEVEL_HEX, PALETTE } from '../scene/levelColors'
import { QUALITY_STEPS } from '../scene/perf'
import { buildRainDrops } from '../scene/rainField'
import { buildRiskTexels, findCell } from '../scene/riskTexture'
import type { MapModel } from '../scene/useMapModel'
import {
  fitView,
  flipRows,
  regionView,
  screenToWorld,
  shadeTerrain,
  type View2D,
  worldToScreen,
  zoomAt,
} from '../scene/view2d'
import { type CameraCommand, useMapState } from '../state/map'
import styles from './Map2D.module.css'

const PULSE_SECONDS = 2.4
const CLICK_SLOP_PX = 5
const CELL_ZOOM = 90
/** Room kept free at the top of the canvas for the map controls floating over it. */
const TOP_INSET_PX = 150

/** An offscreen canvas holding RGBA pixels, one per terrain sample. */
function pixelCanvas(data: Uint8ClampedArray, cols: number, rows: number): HTMLCanvasElement | null {
  const canvas = document.createElement('canvas')
  canvas.width = cols
  canvas.height = rows
  const ctx = canvas.getContext('2d')
  if (!ctx) return null
  ctx.putImageData(new ImageData(data as Uint8ClampedArray<ArrayBuffer>, cols, rows), 0, 0)
  return canvas
}

/** Outline rings in scene space (x, z pairs) with the stroke they are drawn in: India brighter than its neighbours. */
interface DrawnRing {
  points: Float64Array
  alpha: number
}

/**
 * The map without WebGL: a 2D canvas with the same terrain relief, risk cells, alert markers and
 * rain, the same filters and the same hover, click and camera commands as the 3D view.
 */
export default function Map2D({ model }: { model: MapModel }) {
  const { terrain, field, grid, visible, rain } = model
  const box = useRef<HTMLDivElement>(null)
  const canvas = useRef<HTMLCanvasElement>(null)
  const view = useRef<View2D | null>(null)
  const size = useRef({ width: 0, height: 0 })
  const requestDraw = useRef<() => void>(() => {})
  const live = useRef({ grid, visible })
  useEffect(() => {
    live.current = { grid, visible }
  }, [grid, visible])
  const quality = useMapState((s) => s.quality)
  const watchColumns = useMapState((s) => s.watchColumns)

  const relief = useMemo(() => {
    if (!terrain || !field) return null
    return pixelCanvas(shadeTerrain(field, terrain.mask), terrain.cols, terrain.rows)
  }, [terrain, field])

  const rings = useMemo<DrawnRing[]>(() => {
    if (!terrain) return []
    return terrain.outline.flatMap((country) =>
      country.rings.map((ring) => {
        const points = new Float64Array(ring.length * 2)
        ring.forEach(([lon, lat], n) => {
          const { x, z } = lonLatToWorld(lon, lat, terrain)
          points[2 * n] = x
          points[2 * n + 1] = z
        })
        return { points, alpha: country.name === 'India' ? 0.8 : 0.5 }
      }),
    )
  }, [terrain])

  const risk = useMemo(() => {
    if (!terrain || !grid || !visible) return null
    return pixelCanvas(flipRows(buildRiskTexels(grid, terrain, visible), terrain.rows, terrain.cols), terrain.cols, terrain.rows)
  }, [terrain, grid, visible])

  const drops = useMemo(() => (terrain && field && rain ? buildRainDrops(rain, terrain, field) : null), [terrain, field, rain])

  const markers = useMemo(() => {
    if (!terrain || !grid || !visible) return []
    const minLevel = columnMinLevel(watchColumns)
    let maxRisk = 0
    const picked: number[] = []
    for (let i = 0; i < grid.n; i++) {
      if (!visible[i] || grid.level[i]! < minLevel || cellToTexel(grid.cells[i]!, terrain) < 0) continue
      picked.push(i)
      if (grid.risk[i]! > maxRisk) maxRisk = grid.risk[i]!
    }
    return picked.map((i) => ({
      ...texelWorld(cellToTexel(grid.cells[i]!, terrain), terrain),
      level: grid.level[i]!,
      share: columnHeight(grid.risk[i]!, maxRisk),
    }))
  }, [terrain, grid, visible, watchColumns])

  const hasEmergency = markers.some((m) => m.level === 3)

  useEffect(() => {
    const el = canvas.current
    const holder = box.current
    if (!el || !holder || !terrain || !field) return
    const ctx = el.getContext('2d')
    if (!ctx) return
    const reduced = prefersReducedMotion()
    let raf = 0
    let flight: { from: View2D; to: View2D; startedAt: number } | null = null

    const home = (region: Parameters<typeof regionView>[0]): View2D => {
      const inset = Math.min(TOP_INSET_PX, size.current.height / 4)
      const fit = fitView(regionView(region, terrain), size.current.width, size.current.height - inset)
      return { ...fit, cz: fit.cz - inset / 2 / fit.scale }
    }

    const draw = () => {
      raf = 0
      const { width, height } = size.current
      if (!width || !height) return
      const v = (view.current ??= home('all'))
      ctx.fillStyle = PALETTE.paper
      ctx.fillRect(0, 0, width, height)

      const half = terrain.step / 2
      const [x0, y0] = worldToScreen(v, width, height, texelWorld(0, terrain).x - half, texelWorld(terrain.cols * (terrain.rows - 1), terrain).z - half)
      const w = terrain.cols * terrain.step * v.scale
      const h = terrain.rows * terrain.step * v.scale
      if (relief) {
        ctx.imageSmoothingEnabled = true
        ctx.drawImage(relief, x0, y0, w, h)
      }
      if (risk) {
        ctx.imageSmoothingEnabled = false
        ctx.drawImage(risk, x0, y0, w, h)
      }

      ctx.strokeStyle = PALETTE.signal
      ctx.lineWidth = 1
      for (const ring of rings) {
        ctx.globalAlpha = ring.alpha
        ctx.beginPath()
        for (let n = 0; n < ring.points.length; n += 2) {
          const [sx, sy] = worldToScreen(v, width, height, ring.points[n]!, ring.points[n + 1]!)
          if (n === 0) ctx.moveTo(sx, sy)
          else ctx.lineTo(sx, sy)
        }
        ctx.closePath()
        ctx.stroke()
      }
      ctx.globalAlpha = 1

      const share = QUALITY_STEPS[useMapState.getState().quality].particles
      if (drops && share > 0) {
        ctx.strokeStyle = PALETTE.signal
        ctx.globalAlpha = 0.45
        ctx.lineWidth = 1
        ctx.beginPath()
        const n = Math.floor(drops.count * share)
        for (let k = 0; k < n; k++) {
          const [sx, sy] = worldToScreen(v, width, height, drops.data[4 * k]!, drops.data[4 * k + 1]!)
          ctx.moveTo(sx, sy - 3)
          ctx.lineTo(sx - 1, sy + 3)
        }
        ctx.stroke()
        ctx.globalAlpha = 1
      }

      const beat = reduced ? 1 : 0.55 + 0.45 * Math.sin(((performance.now() / 1000) * Math.PI * 2) / PULSE_SECONDS)
      for (const m of markers) {
        const [sx, sy] = worldToScreen(v, width, height, m.x, m.z)
        if (sx < -20 || sy < -20 || sx > width + 20 || sy > height + 20) continue
        const radius = 2 + 5 * m.share
        ctx.fillStyle = LEVEL_HEX[m.level]!
        ctx.globalAlpha = m.level === 3 ? 0.55 + 0.45 * beat : 0.9
        ctx.beginPath()
        ctx.arc(sx, sy, radius, 0, Math.PI * 2)
        ctx.fill()
        if (m.level === 3) {
          ctx.strokeStyle = PALETTE.red
          ctx.globalAlpha = 0.5 * beat
          ctx.beginPath()
          ctx.arc(sx, sy, radius + 3 + 3 * beat, 0, Math.PI * 2)
          ctx.stroke()
        }
        ctx.globalAlpha = 1
      }

      const hover = useMapState.getState().hover
      if (hover && live.current.grid) {
        const texel = cellToTexel(hover.cell, terrain)
        if (texel >= 0) {
          const { x, z } = texelWorld(texel, terrain)
          const [sx, sy] = worldToScreen(v, width, height, x, z)
          const r = Math.max(5, terrain.step * v.scale * 0.8)
          ctx.strokeStyle = PALETTE.signal
          ctx.lineWidth = 2
          ctx.strokeRect(sx - r, sy - r, 2 * r, 2 * r)
        }
      }

      if (flight || (hasEmergency && !reduced)) schedule()
    }

    function schedule() {
      if (!raf) raf = requestAnimationFrame(tick)
    }
    const tick = () => {
      if (flight) {
        const p = Math.min(1, (performance.now() - flight.startedAt) / FLY_MS)
        const e = easeOutMotion(p)
        view.current = {
          cx: flight.from.cx + (flight.to.cx - flight.from.cx) * e,
          cz: flight.from.cz + (flight.to.cz - flight.from.cz) * e,
          scale: flight.from.scale * (flight.to.scale / flight.from.scale) ** e,
        }
        if (p >= 1) flight = null
      }
      draw()
    }
    requestDraw.current = schedule

    const resize = () => {
      const rect = holder.getBoundingClientRect()
      const ratio = Math.min(window.devicePixelRatio || 1, QUALITY_STEPS[useMapState.getState().quality].dprMax)
      const first = size.current.width === 0
      size.current = { width: rect.width, height: rect.height }
      el.width = Math.max(1, Math.round(rect.width * ratio))
      el.height = Math.max(1, Math.round(rect.height * ratio))
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0)
      if (first) view.current = null
      schedule()
    }
    const observer = new ResizeObserver(resize)
    observer.observe(holder)
    resize()

    const goTo = (to: View2D) => {
      const from = view.current ?? home('all')
      if (reduced) {
        view.current = to
        flight = null
        schedule()
      } else {
        flight = { from, to, startedAt: performance.now() }
        schedule()
      }
    }
    const command = (c: CameraCommand | null) => {
      if (!c) return
      if (c.kind === 'reset') goTo(home('all'))
      else if (c.kind === 'region') goTo(home(c.region))
      else {
        const texel = cellToTexel(c.cell, terrain)
        if (texel < 0) return
        const { x, z } = texelWorld(texel, terrain)
        goTo({ cx: x, cz: z, scale: CELL_ZOOM })
      }
    }
    let lastCommand = useMapState.getState().camera
    const unsubscribe = useMapState.subscribe((s) => {
      if (s.camera !== lastCommand) {
        lastCommand = s.camera
        command(s.camera)
      }
      schedule()
    })

    const cellAt = (e: PointerEvent): number | null => {
      const { grid: g, visible: vis } = live.current
      const v = view.current
      if (!g || !vis || !v) return null
      const rect = el.getBoundingClientRect()
      const [wx, wz] = screenToWorld(v, size.current.width, size.current.height, e.clientX - rect.left, e.clientY - rect.top)
      const texel = worldToTexel(wx, wz, terrain)
      if (texel < 0) return null
      const id = texelToCell(texel, terrain)
      const index = findCell(g, id)
      return index >= 0 && vis[index] ? id : null
    }

    let drag: { x: number; y: number; moved: boolean; button: number } | null = null
    const onDown = (e: PointerEvent) => {
      drag = { x: e.clientX, y: e.clientY, moved: false, button: e.button }
      el.setPointerCapture(e.pointerId)
    }
    const onMove = (e: PointerEvent) => {
      const v = view.current
      if (drag && v) {
        const dx = e.clientX - drag.x
        const dy = e.clientY - drag.y
        if (Math.hypot(dx, dy) > CLICK_SLOP_PX) drag.moved = true
        if (drag.moved) {
          flight = null
          view.current = { ...v, cx: v.cx - dx / v.scale, cz: v.cz - dy / v.scale }
          drag.x = e.clientX
          drag.y = e.clientY
          useMapState.getState().setHover(null)
          el.style.cursor = 'grabbing'
          schedule()
        }
        return
      }
      const cell = cellAt(e)
      el.style.cursor = cell === null ? '' : 'pointer'
      const current = useMapState.getState().hover
      if (cell === null) {
        if (current) useMapState.getState().setHover(null)
      } else {
        useMapState.getState().setHover({ cell, x: e.clientX, y: e.clientY })
      }
    }
    const onUp = (e: PointerEvent) => {
      const d = drag
      drag = null
      el.style.cursor = ''
      if (!d || d.moved || d.button !== 0) return
      const cell = cellAt(e)
      if (cell !== null) useMapState.getState().openCell(cell)
    }
    const onLeave = () => useMapState.getState().setHover(null)
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      const v = view.current
      if (!v) return
      const rect = el.getBoundingClientRect()
      flight = null
      view.current = zoomAt(v, size.current.width, size.current.height, e.clientX - rect.left, e.clientY - rect.top, Math.exp(-e.deltaY * 0.0015))
      schedule()
    }
    el.addEventListener('pointerdown', onDown)
    el.addEventListener('pointermove', onMove)
    el.addEventListener('pointerup', onUp)
    el.addEventListener('pointerleave', onLeave)
    el.addEventListener('wheel', onWheel, { passive: false })

    return () => {
      cancelAnimationFrame(raf)
      observer.disconnect()
      unsubscribe()
      el.removeEventListener('pointerdown', onDown)
      el.removeEventListener('pointermove', onMove)
      el.removeEventListener('pointerup', onUp)
      el.removeEventListener('pointerleave', onLeave)
      el.removeEventListener('wheel', onWheel)
      useMapState.getState().setHover(null)
      requestDraw.current = () => {}
    }
  }, [terrain, field, relief, rings, risk, drops, markers, hasEmergency])

  useEffect(() => requestDraw.current(), [quality])

  return (
    <div ref={box} className={styles.map} data-testid="map-2d">
      <canvas ref={canvas} className={styles.canvas} aria-hidden="true" />
    </div>
  )
}
