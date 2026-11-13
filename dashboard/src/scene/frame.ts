import { prefersReducedMotion } from '../lib/motion'
import { useIntro } from '../state/intro'
import { storyFrame, useStory } from '../state/story'
import { introFrame, REST_FRAME, type IntroFrame } from './timeline'

/** The animated values of the scene, with the two layers the story brings in on their own: rain and the alert levels. */
export interface SceneNow extends IntroFrame {
  rain: number
  risk: number
}

/** How fast the relief, rain and levels follow a change of view, per second: most of a change in about 0.3 s. */
const FOLLOW_RATE = 7
const EASED = ['fill', 'rain', 'risk'] as const

let layersShown = true
let chartShown = false
let lastEased = -1
const eased = { fill: 0, rain: 0, risk: 0 }

/** Whether the current view draws the rain and the levels on the terrain (the map and the story do, the others do not). */
export function setLayersShown(shown: boolean): void {
  layersShown = shown
}

/** What the view asks for at this instant, before easing. */
function target(): SceneNow {
  const intro = useIntro.getState()
  const story = useStory.getState()
  const playing = intro.status === 'playing'
  const frame = playing ? introFrame(intro.startedAt === 0 ? 0 : (performance.now() - intro.startedAt) / 1000) : REST_FRAME
  if (story.active) {
    if (playing) return { ...frame, rain: 0, risk: 0 }
    const seconds = prefersReducedMotion() ? Infinity : (performance.now() - story.startedAt) / 1000
    const layers = storyFrame(story.position, seconds)
    // The chart is plotted once per page load: by the landing, by the story's opening, or by any other view. Coming back
    // to the story later keeps the lines and the relief instead of drawing them again from nothing.
    const plotted = intro.played || chartShown || story.deck
    return { ...REST_FRAME, ...layers, reveal: plotted ? 1 : layers.reveal, fill: plotted ? 1 : layers.fill }
  }
  if (!playing) chartShown = true
  return { ...frame, rain: frame.fill, risk: frame.fill }
}

/**
 * The animated values for this instant. The landing runs on its own clock wherever it plays; on the home page it plays
 * over the story's opening and leaves rain and the levels to the story's chapters. The relief, rain and levels then
 * follow every change of view with a short ease, so no view switch makes a layer jump in or out. The easing is in
 * time, not in calls, so any number of readers per frame see the same values.
 */
export function frameNow(): SceneNow {
  const want = target()
  if (!layersShown) {
    want.rain = 0
    want.risk = 0
  }
  const now = performance.now()
  const k = lastEased < 0 || prefersReducedMotion() ? 1 : 1 - Math.exp(-((now - lastEased) / 1000) * FOLLOW_RATE)
  lastEased = now
  for (const key of EASED) eased[key] += (want[key] - eased[key]) * k
  return { ...want, fill: eased.fill, rain: eased.rain, risk: eased.risk }
}
