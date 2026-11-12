import { useIntro } from '../state/intro'
import { introFrame, REST_FRAME, type IntroFrame } from './timeline'

/** The animated values for this instant: the landing sequence while it plays, the rest state after. */
export function frameNow(): IntroFrame {
  const { status, startedAt } = useIntro.getState()
  if (status !== 'playing') return REST_FRAME
  const t = startedAt === 0 ? 0 : (performance.now() - startedAt) / 1000
  return introFrame(t)
}
