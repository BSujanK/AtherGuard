import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { INTRO_SEEN_KEY, shouldPlayIntro, useIntro } from '../state/intro'
import Landing from './Landing'
import { CHROME_AT, INTRO_DURATION, TAGLINE } from './timeline'

const env = vi.hoisted(() => ({ reducedMotion: false, webgl: true }))

vi.mock('../lib/motion', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../lib/motion')>()),
  prefersReducedMotion: () => env.reducedMotion,
  webglAvailable: () => env.webgl,
}))

function startAt(url: string) {
  window.history.pushState({}, '', url)
  useIntro.getState().reset()
}

beforeEach(() => {
  env.reducedMotion = false
  env.webgl = true
})

afterEach(() => {
  window.history.pushState({}, '', '/')
})

describe('shouldPlayIntro', () => {
  const base = { pathname: '/', search: '', reducedMotion: false, webgl: true, seen: false }

  it('plays on a first visit to the home URL', () => {
    expect(shouldPlayIntro(base)).toBe(true)
  })

  it.each([
    ['already seen this session', { seen: true }],
    ['reduced motion', { reducedMotion: true }],
    ['no WebGL', { webgl: false }],
    ['deep link path', { pathname: '/alerts-why' }],
    ['deep link query', { search: '?cell=123' }],
  ])('does not play with %s', (_name, patch) => {
    expect(shouldPlayIntro({ ...base, ...patch })).toBe(false)
  })
})

describe('Landing', () => {
  it('shows the skip button, wordmark and tagline from the first frame', () => {
    startAt('/')
    render(<Landing />)
    expect(screen.getByRole('button', { name: 'Skip intro' })).toBeVisible()
    expect(screen.getByRole('img', { name: 'AetherGuard' })).toBeInTheDocument()
    expect(screen.getByText(TAGLINE)).toBeInTheDocument()
  })

  it('skips on click, remembers it for the session and reveals the shell chrome', async () => {
    startAt('/')
    render(<Landing />)
    expect(useIntro.getState().chrome).toBe(false)
    await userEvent.click(screen.getByRole('button', { name: 'Skip intro' }))
    expect(screen.queryByRole('button', { name: 'Skip intro' })).not.toBeInTheDocument()
    expect(useIntro.getState().status).toBe('done')
    expect(useIntro.getState().chrome).toBe(true)
    expect(window.sessionStorage.getItem(INTRO_SEEN_KEY)).toBe('1')
  })

  it('skips on Escape', async () => {
    startAt('/')
    render(<Landing />)
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByTestId('landing')).not.toBeInTheDocument()
  })

  it('does not play twice in one session', () => {
    window.sessionStorage.setItem(INTRO_SEEN_KEY, '1')
    startAt('/')
    render(<Landing />)
    expect(screen.queryByTestId('landing')).not.toBeInTheDocument()
    expect(useIntro.getState().chrome).toBe(true)
  })

  it('is skipped under prefers-reduced-motion without marking the session', () => {
    env.reducedMotion = true
    startAt('/')
    render(<Landing />)
    expect(screen.queryByTestId('landing')).not.toBeInTheDocument()
    expect(useIntro.getState().status).toBe('done')
    expect(window.sessionStorage.getItem(INTRO_SEEN_KEY)).toBeNull()
  })

  it('is skipped on deep links', () => {
    startAt('/sensors-sources')
    render(<Landing />)
    expect(screen.queryByTestId('landing')).not.toBeInTheDocument()
  })

  it('finishes by itself when the sequence ends', () => {
    vi.useFakeTimers({ toFake: ['requestAnimationFrame', 'cancelAnimationFrame', 'performance'] })
    try {
      startAt('/')
      render(<Landing />)
      act(() => {
        vi.advanceTimersByTime(1000)
      })
      expect(useIntro.getState().startedAt).toBe(0)                    // the clock waits for the terrain
      act(() => {
        useIntro.getState().setReady()
        vi.advanceTimersByTime(CHROME_AT * 1000 + 100)
      })
      expect(useIntro.getState().chrome).toBe(true)
      expect(screen.getByTestId('landing')).toBeInTheDocument()
      act(() => {
        vi.advanceTimersByTime((INTRO_DURATION - CHROME_AT) * 1000 + 100)
      })
      expect(screen.queryByTestId('landing')).not.toBeInTheDocument()
      expect(window.sessionStorage.getItem(INTRO_SEEN_KEY)).toBe('1')
    } finally {
      vi.useRealTimers()
    }
  })
})
