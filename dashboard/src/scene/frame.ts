import { prefersReducedMotion } from '../lib/motion'
import { useIntro } from '../state/intro'
import { storyFrame, useStory } from '../state/story'
import { introFrame, REST_FRAME, type IntroFrame } from './timeline'

/** The animated values of the scene, with the two layers the story brings in on their own: rain and the alert levels. */
export interface SceneNow extends IntroFrame {
  rain: number
  risk: number
}

/**
 * The animated values for this instant. The landing runs on its own clock wherever it plays. On the home page it plays
 * over the story's opening: it draws and fills the relief as always, and leaves the rain and the levels to the story's
 * chapters, which then take over (the relief the landing filled in stays). Elsewhere the rest state follows.
 */
export function frameNow(): SceneNow {
  const intro = useIntro.getState()
  const story = useStory.getState()
  const playing = intro.status === 'playing'
  const frame = playing ? introFrame(intro.startedAt === 0 ? 0 : (performance.now() - intro.startedAt) / 1000) : REST_FRAME
  if (story.active) {
    if (playing) return { ...frame, rain: 0, risk: 0 }
    const seconds = prefersReducedMotion() ? Infinity : (performance.now() - story.startedAt) / 1000
    const layers = storyFrame(story.position, seconds)
    return { ...REST_FRAME, ...layers, fill: intro.played ? 1 : layers.fill }
  }
  return { ...frame, rain: frame.fill, risk: frame.fill }
}
