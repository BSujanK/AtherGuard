import { useFrame, useThree } from '@react-three/fiber'
import { useEffect, useMemo, useRef } from 'react'
import { type PerspectiveCamera, Vector3 } from 'three'
import { prefersReducedMotion } from '../lib/motion'
import { type CameraCommand, useMapState } from '../state/map'
import { easeOutMotion, FLY_MS } from './cameraEase'
import { cellToTexel, latLonToTexel, REGION_BOXES, texelWorld, type Window } from './geo'
import { MAP } from './poses'
import type { TerrainField } from './terrainField'

/** How close the camera comes to a cell it flies to, in scene units. */
export const CELL_DISTANCE = 6.5

/** The slice of the orbit controls the rig drives. */
interface Controls {
  target: Vector3
  update: () => unknown
}

interface Flight {
  startedAt: number
  fromPosition: Vector3
  fromTarget: Vector3
  toPosition: Vector3
  toTarget: Vector3
}

/** Direction from the map target to the resting camera, so a region view keeps the map's tilt. */
const REST_DIRECTION = MAP.position.clone().sub(MAP.target).normalize()

interface PoseRequest {
  position: Vector3
  target: Vector3
}

/** Where the camera should end up for a command; null when the command points at nothing known. */
export function poseFor(
  command: CameraCommand,
  window: Window,
  field: TerrainField,
  current: { position: Vector3; target: Vector3 },
): PoseRequest | null {
  if (command.kind === 'reset') return { position: MAP.position.clone(), target: MAP.target.clone() }

  if (command.kind === 'region') {
    if (command.region === 'all') return { position: MAP.position.clone(), target: MAP.target.clone() }
    const box = REGION_BOXES[command.region]
    const mid = latLonToTexel((box.latMin + box.latMax) / 2, (box.lonMin + box.lonMax) / 2, window)
    if (mid === null) return null
    const { x, z } = texelWorld(mid, window)
    const target = new Vector3(x, 0, z)
    const distance = Math.max((box.lonMax - box.lonMin) * 1.05, (box.latMax - box.latMin) * 1.5)
    return { position: target.clone().addScaledVector(REST_DIRECTION, distance), target }
  }

  const texel = cellToTexel(command.cell, window)
  if (texel < 0) return null
  const { x, z } = texelWorld(texel, window)
  const target = new Vector3(x, field.height[texel]!, z)
  const direction = current.position.clone().sub(current.target).normalize()
  return { position: target.clone().addScaledVector(direction, CELL_DISTANCE), target }
}

/**
 * Moves the camera on request: reset, a region framing or a fly-to to a cell. Moves ease out over
 * 600 ms; with reduced motion the camera jumps there instantly.
 */
export default function CameraRig({ window, field }: { window: Window; field: TerrainField }) {
  const camera = useThree((s) => s.camera) as PerspectiveCamera
  const controls = useThree((s) => s.controls) as Controls | null
  const invalidate = useThree((s) => s.invalidate)
  const flight = useRef<Flight | null>(null)
  const scratch = useMemo(() => new Vector3(), [])

  useEffect(() => {
    const handle = (command: CameraCommand | null) => {
      if (!command || !controls) return
      const pose = poseFor(command, window, field, { position: camera.position, target: controls.target })
      if (!pose) return
      if (prefersReducedMotion()) {
        flight.current = null
        camera.position.copy(pose.position)
        controls.target.copy(pose.target)
        controls.update()
        invalidate()
        return
      }
      flight.current = {
        startedAt: performance.now(),
        fromPosition: camera.position.clone(),
        fromTarget: controls.target.clone(),
        toPosition: pose.position,
        toTarget: pose.target,
      }
      invalidate()
    }
    let last = useMapState.getState().camera
    return useMapState.subscribe((state) => {
      if (state.camera === last) return
      last = state.camera
      handle(state.camera)
    })
  }, [camera, controls, window, field, invalidate])

  useFrame(() => {
    const f = flight.current
    if (!f || !controls) return
    const progress = Math.min(1, (performance.now() - f.startedAt) / FLY_MS)
    const e = easeOutMotion(progress)
    camera.position.lerpVectors(f.fromPosition, f.toPosition, e)
    scratch.lerpVectors(f.fromTarget, f.toTarget, e)
    controls.target.copy(scratch)
    controls.update()
    if (progress >= 1) flight.current = null
  })

  return null
}
