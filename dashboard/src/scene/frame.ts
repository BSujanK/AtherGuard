import { prefersReducedMotion } from '../lib/motion'
import { REST_FRAME, type SceneFrame, storyFrame, useStory } from '../state/story'

/** What the scene draws this instant: the story's layers while the story is on screen, the finished chart otherwise. */
export function frameNow(): SceneFrame {
  const { active, position, startedAt } = useStory.getState()
  if (!active) return REST_FRAME
  const seconds = prefersReducedMotion() ? Infinity : (performance.now() - startedAt) / 1000
  return storyFrame(position, seconds)
}
