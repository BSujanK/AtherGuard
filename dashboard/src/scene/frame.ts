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
 * The animated values for this instant: the story's layers while the story is on screen, the landing sequence while it
 * plays, the rest state after. Outside the story, rain and the levels arrive with the terrain fill, as they always did.
 */
export function frameNow(): SceneNow {
  const story = useStory.getState()
  if (story.active) {
    const seconds = prefersReducedMotion() ? Infinity : (performance.now() - story.startedAt) / 1000
    return { ...REST_FRAME, ...storyFrame(story.position, seconds) }
  }
  const { status, startedAt } = useIntro.getState()
  const frame = status !== 'playing' ? REST_FRAME : introFrame(startedAt === 0 ? 0 : (performance.now() - startedAt) / 1000)
  return { ...frame, rain: frame.fill, risk: frame.fill }
}
