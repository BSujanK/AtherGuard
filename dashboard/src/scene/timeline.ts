/** Landing sequence (spec section 3). One pure function maps seconds since start to every animated value. */

export const INTRO_DURATION = 4.5
export const WORDMARK = 'AetherGuard'
export const TAGLINE =
  'Landslide risk for every 5 km of the Himalaya and the Western Ghats, every morning.'

/** Seconds at which the shell chrome starts sliding in. */
export const CHROME_AT = 3.8

export const clamp01 = (x: number): number => Math.min(1, Math.max(0, x))

export const ramp = (t: number, from: number, to: number): number => clamp01((t - from) / (to - from))

export const easeInOutCubic = (x: number): number =>
  x < 0.5 ? 4 * x * x * x : 1 - (-2 * x + 2) ** 3 / 2

export const easeOutQuad = (x: number): number => 1 - (1 - x) ** 2

export const easeOutExpo = (x: number): number => (x >= 1 ? 1 : 1 - 2 ** (-10 * x))

export interface IntroFrame {
  /** Contour lines revealed from low to high elevation, 0..1. */
  reveal: number
  /** Contours filling into shaded terrain, 0..1. */
  fill: number
  /** Camera travel from the overview pose to the map pose, 0..1. */
  dive: number
  /** Wordmark assembly, 0..1 across all letters. */
  wordmark: number
  tagline: number
  /** Opacity of the wordmark block (fades out as the camera dives). */
  textOpacity: number
  /** Spark and rain intensity, 0..1. */
  atmosphere: number
  chrome: boolean
}

/** The state the scene rests in once the sequence is over (or was skipped). */
export const REST_FRAME: IntroFrame = {
  reveal: 1,
  fill: 1,
  dive: 1,
  wordmark: 1,
  tagline: 1,
  textOpacity: 0,
  atmosphere: 0.3,
  chrome: true,
}

export function introFrame(t: number): IntroFrame {
  if (t >= INTRO_DURATION) return REST_FRAME
  return {
    reveal: easeOutQuad(ramp(t, 0.2, 2.6)),
    fill: easeInOutCubic(ramp(t, 2.6, 3.7)),
    dive: easeInOutCubic(ramp(t, 2.8, INTRO_DURATION)),
    wordmark: ramp(t, 0.9, 2.1),
    tagline: ramp(t, 1.8, 2.4),
    textOpacity: 1 - ramp(t, 3.2, 3.8),
    atmosphere: 1 - 0.7 * ramp(t, 3.2, INTRO_DURATION),
    chrome: t >= CHROME_AT,
  }
}

/** Per-letter assembly progress (0..1) for letter `index` of `count`, staggered across `wordmark`. */
export function letterProgress(wordmark: number, index: number, count: number): number {
  const span = 3
  return easeOutExpo(clamp01((wordmark * (count - 1 + span) - index) / span))
}
