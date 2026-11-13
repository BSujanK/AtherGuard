import { Vector3 } from 'three'

/**
 * Camera poses: the landing opens on OVERVIEW and dives to MAP, where the live map rests and "Reset view"
 * returns. MAP frames the whole of India (the base map window is 30 by 31.5 degrees).
 */
export const OVERVIEW = { position: new Vector3(-10, 36, 56), target: new Vector3(0, 0, -0.5) }
export const MAP = { position: new Vector3(0.51, 28.4, 32.6), target: new Vector3(0, -0.3, -0.6) }
