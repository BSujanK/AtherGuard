import { create } from 'zustand'
import { prefersReducedMotion, webglAvailable } from '../lib/motion'

export const INTRO_SEEN_KEY = 'aetherguard.intro.seen'

export interface IntroEnv {
  pathname: string
  search: string
  reducedMotion: boolean
  webgl: boolean
  seen: boolean
}

/** The intro plays once per session, on the home URL, with motion and WebGL available. */
export function shouldPlayIntro(env: IntroEnv): boolean {
  const deepLink = env.pathname !== '/' || env.search !== ''
  return !env.seen && !deepLink && !env.reducedMotion && env.webgl
}

function readSeen(): boolean {
  try {
    return window.sessionStorage.getItem(INTRO_SEEN_KEY) === '1'
  } catch {
    return false
  }
}

function markSeen() {
  try {
    window.sessionStorage.setItem(INTRO_SEEN_KEY, '1')
  } catch {
    /* storage can be blocked; the intro then plays again on reload, which is acceptable */
  }
}

function currentEnv(): IntroEnv {
  return {
    pathname: window.location.pathname,
    search: window.location.search,
    reducedMotion: prefersReducedMotion(),
    webgl: webglAvailable(),
    seen: readSeen(),
  }
}

interface IntroState {
  status: 'playing' | 'done'
  /** performance.now() when the sequence started; 0 until the scene is ready and Landing starts the clock. */
  startedAt: number
  /** The terrain has been built and drawn once: the sequence has something to show. */
  ready: boolean
  setReady: () => void
  begin: () => void
  /** True once the shell chrome may slide in. */
  chrome: boolean
  showChrome: () => void
  /** End the sequence (finished or skipped) and remember it for the session. */
  finish: () => void
  /** Re-evaluate whether to play, from the current URL, preferences and session. */
  reset: () => void
}

function initial(): Pick<IntroState, 'status' | 'startedAt' | 'chrome'> {
  const play = shouldPlayIntro(currentEnv())
  return { status: play ? 'playing' : 'done', startedAt: 0, chrome: !play }
}

export const useIntro = create<IntroState>((set) => ({
  ...initial(),
  ready: false,
  setReady: () => set({ ready: true }),
  begin: () => set((s) => (s.startedAt === 0 ? { startedAt: performance.now() } : s)),
  showChrome: () => set({ chrome: true }),
  finish: () => {
    markSeen()
    set({ status: 'done', chrome: true })
  },
  reset: () => set(initial()),
}))
