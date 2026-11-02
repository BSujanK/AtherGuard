/** Duration of every camera move on the map, in ms (spec section 2: 280-600 ms). */
export const FLY_MS = 600

/**
 * CSS-style cubic-bezier easing: the y of the curve at progress x, for control points
 * (x1, y1) and (x2, y2) with the curve running from (0,0) to (1,1).
 */
export function cubicBezier(x1: number, y1: number, x2: number, y2: number): (x: number) => number {
  const cx = 3 * x1
  const bx = 3 * (x2 - x1) - cx
  const ax = 1 - cx - bx
  const cy = 3 * y1
  const by = 3 * (y2 - y1) - cy
  const ay = 1 - cy - by
  const sampleX = (t: number) => ((ax * t + bx) * t + cx) * t
  const sampleY = (t: number) => ((ay * t + by) * t + cy) * t
  const slopeX = (t: number) => (3 * ax * t + 2 * bx) * t + cx

  return (x) => {
    if (x <= 0) return 0
    if (x >= 1) return 1
    let t = x
    for (let i = 0; i < 8; i++) {
      const err = sampleX(t) - x
      if (Math.abs(err) < 1e-6) return sampleY(t)
      const slope = slopeX(t)
      if (Math.abs(slope) < 1e-6) break
      t -= err / slope
    }
    let lo = 0
    let hi = 1
    for (let i = 0; i < 40; i++) {
      t = (lo + hi) / 2
      if (sampleX(t) < x) lo = t
      else hi = t
    }
    return sampleY(t)
  }
}

/** The motion grammar's ease-out: cubic-bezier(.16, 1, .3, 1). */
export const easeOutMotion = cubicBezier(0.16, 1, 0.3, 1)
