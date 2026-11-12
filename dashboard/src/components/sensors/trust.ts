import { mixHex, PALETTE } from '../../charts/theme'

/** Trust at or above this reads as fully trusted (cyan); the scale ends at 0 (fire red). */
export const TRUST_STOPS = [
  { at: 1, color: PALETTE.signal },
  { at: 2 / 3, color: PALETTE.yellow },
  { at: 1 / 3, color: PALETTE.orange },
  { at: 0, color: PALETTE.red },
] as const

/**
 * Gauge trust 0..1 to colour: cyan at 1, neon lime at 2/3, flame orange at 1/3, fire red at 0, mixed linearly
 * between the pinned palette stops. Out-of-range values clamp; callers handle a missing trust (no colour) themselves.
 */
export function trustColor(trust: number): string {
  const t = Math.min(1, Math.max(0, trust))
  for (let i = 0; i < TRUST_STOPS.length - 1; i++) {
    const hi = TRUST_STOPS[i]!
    const lo = TRUST_STOPS[i + 1]!
    if (t >= lo.at) return mixHex(lo.color, hi.color, (t - lo.at) / (hi.at - lo.at))
  }
  return TRUST_STOPS[TRUST_STOPS.length - 1]!.color
}

export const formatTrust = (trust: number | null): string => (trust === null ? 'no value' : trust.toFixed(2))

/** The area the gauge map draws (the whole-India base map); gauges outside it are counted but not drawn. */
export const DOMAIN = { latMin: 6, latMax: 37.5, lonMin: 68, lonMax: 98 } as const

export const inDomain = (s: { lat: number; lon: number }): boolean =>
  s.lat >= DOMAIN.latMin && s.lat <= DOMAIN.latMax && s.lon >= DOMAIN.lonMin && s.lon <= DOMAIN.lonMax
