import { Vector3 } from 'three'
import { lonLatToWorld, type Window } from './geo'
import { MAP } from './poses'

export interface Pose {
  position: Vector3
  target: Vector3
}

/** Where the camera last looked; the map's orbit controls start from here, so leaving the story never snaps the view. */
export const lookTarget = MAP.target.clone()

const smooth = (t: number): number => t * t * (3 - 2 * t)

function over(lon: number, lat: number, w: Window, height: number, offset: [number, number, number]): Pose {
  const { x, z } = lonLatToWorld(lon, lat, w)
  const target = new Vector3(x, height, z)
  return { position: target.clone().add(new Vector3(...offset)), target }
}

/**
 * One camera pose per chapter (`CHAPTERS` order): the whole chart where the landing's dive ends, low across the Uttarakhand Himalaya, in
 * from the Arabian Sea over the Western Ghats, wide along the Himalayan arc, then the live map's own resting pose for
 * the last two, so stepping from the story into the map moves nothing.
 */
export function storyPoses(w: Window): Pose[] {
  const rest = { position: MAP.position.clone(), target: MAP.target.clone() }
  return [
    { position: MAP.position.clone(), target: MAP.target.clone() },
    over(79.4, 30.4, w, 0.3, [-3.2, 3.4, 9.5]),
    over(76.2, 11.6, w, 0.2, [-8.2, 5.2, 6.4]),
    over(88.0, 27.0, w, 0.2, [0.5, 12.5, 17]),
    rest,
    rest,
  ]
}

/** The pose at a scroll position: eased between the poses of the two chapters it lies between. */
export function poseAt(poses: readonly Pose[], position: number, out: Pose): Pose {
  const last = poses.length - 1
  const p = Math.min(last, Math.max(0, position))
  const i = Math.min(last - 1, Math.floor(p))
  const t = smooth(p - i)
  out.position.lerpVectors(poses[i]!.position, poses[i + 1]!.position, t)
  out.target.lerpVectors(poses[i]!.target, poses[i + 1]!.target, t)
  return out
}
