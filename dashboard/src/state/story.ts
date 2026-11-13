import { create } from 'zustand'

/** The chapters of the story, in scroll order. Each is a section id and a rail label. */
export const CHAPTERS = [
  { id: 'chart', label: 'The chart' },
  { id: 'ground', label: 'The ground' },
  { id: 'rain', label: 'The rain' },
  { id: 'levels', label: 'The levels' },
  { id: 'today', label: 'Today' },
  { id: 'limits', label: 'Its limits' },
] as const

export const LAST_CHAPTER = CHAPTERS.length - 1

interface StoryState {
  /** True while the story route is on screen: the scene then follows the scroll instead of resting. */
  active: boolean
  /** Scroll position in chapters: 0 on the first, 1.5 halfway between the second and third. */
  position: number
  /** performance.now() when the story was entered; the chart plots itself once from there. */
  startedAt: number
  enter: () => void
  leave: () => void
  setPosition: (position: number) => void
}

export const useStory = create<StoryState>((set) => ({
  active: false,
  position: 0,
  startedAt: 0,
  enter: () => set({ active: true, position: 0, startedAt: performance.now() }),
  leave: () => set({ active: false }),
  setPosition: (position) => set({ position: Math.min(LAST_CHAPTER, Math.max(0, position)) }),
}))

/** What the scene draws at one instant, each 0..1. */
export interface SceneFrame {
  /** Contour lines drawn, from low ground to high. */
  reveal: number
  /** Contours filled into shaded relief. */
  fill: number
  /** Rain falling where the day's field says it rained. */
  rain: number
  /** Alert levels draped on the terrain and raised as columns. */
  risk: number
}

/** The finished chart: what every view but the story shows. */
export const REST_FRAME: SceneFrame = { reveal: 1, fill: 1, rain: 1, risk: 1 }

const clamp01 = (x: number): number => Math.min(1, Math.max(0, x))
const ramp = (x: number, from: number, to: number): number => clamp01((x - from) / (to - from))
const smooth = (t: number): number => t * t * (3 - 2 * t)

/** Seconds the opening plot of the contour lines takes. */
export const PLOT_SECONDS = 2.6

/**
 * The story plots the chart layer by layer. The lines draw themselves once on arrival (`seconds` since the story was
 * entered); everything after is tied to the scroll `position`: relief arrives with the ground chapter, rain with the
 * rain chapter, the levels with theirs, and each layer stays once it is on.
 */
export function storyFrame(position: number, seconds: number): SceneFrame {
  const plotted = ramp(seconds, 0.2, PLOT_SECONDS)
  return {
    reveal: Math.max(1 - (1 - plotted) ** 2, ramp(position, 0, 0.5)),
    fill: smooth(ramp(position, 0.35, 1)),
    rain: smooth(ramp(position, 1.45, 2)),
    risk: smooth(ramp(position, 2.45, 3)),
  }
}
