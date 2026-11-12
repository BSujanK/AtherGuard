import { useFrame, useThree } from '@react-three/fiber'
import { useEffect, useMemo, useRef } from 'react'
import { BufferGeometry, Float32BufferAttribute, LineBasicMaterial, LineLoop, Raycaster, Vector2 } from 'three'
import type { Grid } from '../data/types'
import { prefersReducedMotion } from '../lib/motion'
import { useMapState } from '../state/map'
import { cellToTexel, texelWorld, type Window } from './geo'
import { PALETTE } from './levelColors'
import { FrameWatchdog } from './perf'
import { pickTerrain } from './pick'
import { findCell } from './riskTexture'
import type { TerrainField } from './terrainField'

/** A press that moves less than this many pixels and ends within this many ms is a click, not a drag. */
const CLICK_SLOP_PX = 5
const CLICK_MAX_MS = 600
/** Half-size of the hover outline in scene units; larger than a cell so it shows from the overview. */
const MARKER_HALF = 0.22

interface InteractionProps {
  window: Window
  field: TerrainField
  grid: Grid | undefined
  visible: Uint8Array | null
}

/**
 * Hover and click on the terrain. The pointer ray is marched over the height field (see pick.ts),
 * the cell under it is looked up in the grid, and only cells that are scored and pass the filters
 * respond. Writes the hovered cell to the map store for the hover card and an outline in the scene;
 * a click opens the cell (fly-to and detail).
 */
export function MapInteraction({ window: win, field, grid, visible }: InteractionProps) {
  const gl = useThree((s) => s.gl)
  const camera = useThree((s) => s.camera)
  const invalidate = useThree((s) => s.invalidate)
  const live = useRef({ grid, visible })
  useEffect(() => {
    live.current = { grid, visible }
  }, [grid, visible])

  const marker = useMemo(() => {
    const g = new BufferGeometry()
    g.setAttribute(
      'position',
      new Float32BufferAttribute(
        [-MARKER_HALF, 0, -MARKER_HALF, MARKER_HALF, 0, -MARKER_HALF, MARKER_HALF, 0, MARKER_HALF, -MARKER_HALF, 0, MARKER_HALF],
        3,
      ),
    )
    const m = new LineBasicMaterial({ color: PALETTE.signal, depthTest: false, transparent: true })
    const line = new LineLoop(g, m)
    line.visible = false
    line.renderOrder = 10
    line.frustumCulled = false
    return line
  }, [])

  useEffect(
    () => () => {
      marker.geometry.dispose()
      ;(marker.material as LineBasicMaterial).dispose()
    },
    [marker],
  )

  useEffect(() => {
    const el = gl.domElement
    const raycaster = new Raycaster()
    const ndc = new Vector2()
    let frame = 0
    let pending: PointerEvent | null = null
    let down: { x: number; y: number; t: number } | null = null

    /** The scored, visible cell under the pointer, or null. */
    const cellAt = (e: PointerEvent): number | null => {
      const { grid: g, visible: v } = live.current
      if (!g || !v) return null
      const rect = el.getBoundingClientRect()
      ndc.set(((e.clientX - rect.left) / rect.width) * 2 - 1, -((e.clientY - rect.top) / rect.height) * 2 + 1)
      raycaster.setFromCamera(ndc, camera)
      const { origin, direction } = raycaster.ray
      const hit = pickTerrain(
        { origin: [origin.x, origin.y, origin.z], direction: [direction.x, direction.y, direction.z] },
        win,
        field,
      )
      if (!hit) return null
      const index = findCell(g, hit.cell)
      return index >= 0 && v[index] ? hit.cell : null
    }

    const showMarker = (cell: number | null) => {
      if (cell === null) {
        marker.visible = false
      } else {
        const texel = cellToTexel(cell, win)
        const { x, z } = texelWorld(texel, win)
        marker.position.set(x, field.height[texel]! + 0.03, z)
        marker.visible = true
      }
      el.style.cursor = cell === null ? '' : 'pointer'
      invalidate()
    }

    const run = () => {
      frame = 0
      const e = pending
      pending = null
      if (!e) return
      const cell = cellAt(e)
      showMarker(cell)
      useMapState.getState().setHover(cell === null ? null : { cell, x: e.clientX, y: e.clientY })
    }

    const onMove = (e: PointerEvent) => {
      if (e.buttons !== 0) {
        pending = null
        showMarker(null)
        useMapState.getState().setHover(null)
        return
      }
      pending = e
      if (!frame) frame = requestAnimationFrame(run)
    }
    const onLeave = () => {
      pending = null
      showMarker(null)
      useMapState.getState().setHover(null)
    }
    const onDown = (e: PointerEvent) => {
      down = e.button === 0 ? { x: e.clientX, y: e.clientY, t: performance.now() } : null
    }
    const onUp = (e: PointerEvent) => {
      const start = down
      down = null
      if (!start) return
      if (Math.hypot(e.clientX - start.x, e.clientY - start.y) > CLICK_SLOP_PX) return
      if (performance.now() - start.t > CLICK_MAX_MS) return
      const cell = cellAt(e)
      if (cell !== null) useMapState.getState().openCell(cell)
    }

    el.addEventListener('pointermove', onMove)
    el.addEventListener('pointerleave', onLeave)
    el.addEventListener('pointerdown', onDown)
    el.addEventListener('pointerup', onUp)
    return () => {
      cancelAnimationFrame(frame)
      el.removeEventListener('pointermove', onMove)
      el.removeEventListener('pointerleave', onLeave)
      el.removeEventListener('pointerdown', onDown)
      el.removeEventListener('pointerup', onUp)
      el.style.cursor = ''
      useMapState.getState().setHover(null)
    }
  }, [gl, camera, win, field, marker, invalidate])

  return <primitive object={marker} />
}

/** Whether the quality step is pinned by `?quality=full` (for captures and diagnosis). */
export function qualityPinned(search: string): boolean {
  return new URLSearchParams(search).get('quality') === 'full'
}

/** Samples frame times and lets the watchdog lower the visual quality (particles, pixel ratio) when frames are slow. */
export function QualityWatchdog() {
  const watchdog = useMemo(
    () => new FrameWatchdog((step) => useMapState.getState().setQuality(step), {}, useMapState.getState().quality),
    [],
  )
  const active = useMemo(() => !prefersReducedMotion() && !qualityPinned(window.location.search), [])
  useFrame((_state, delta) => {
    if (active) watchdog.sample(delta * 1000, performance.now())
  })
  return null
}
