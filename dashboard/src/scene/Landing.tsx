import { useEffect, useState } from 'react'
import { useIntro } from '../state/intro'
import styles from './Landing.module.css'
import {
  CHROME_AT,
  INTRO_DURATION,
  introFrame,
  letterProgress,
  TAGLINE,
  WORDMARK,
} from './timeline'

const LETTERS = Array.from(WORDMARK)

/** Fixed scatter per letter so the assembly looks hand-placed and identical on every run. */
const SCATTER = LETTERS.map((_, i) => ({
  dx: (((i * 37) % 13) - 6) * 5,
  dy: 34 + ((i * 17) % 7) * 6,
  rot: (((i * 29) % 9) - 4) * 2.2,
}))

/**
 * DOM layer of the landing sequence: wordmark, tagline and the skip control. The terrain,
 * sparks and camera dive run in the shared canvas off the same clock (see `frameNow`).
 */
export default function Landing() {
  const status = useIntro((s) => s.status)
  const begin = useIntro((s) => s.begin)
  const finish = useIntro((s) => s.finish)
  const showChrome = useIntro((s) => s.showChrome)
  const [t, setT] = useState(0)

  useEffect(() => {
    if (status !== 'playing') return
    begin()
    let raf = 0
    const tick = () => {
      const startedAt = useIntro.getState().startedAt
      const elapsed = (performance.now() - startedAt) / 1000
      setT(elapsed)
      if (elapsed >= CHROME_AT) showChrome()
      if (elapsed >= INTRO_DURATION) {
        finish()
        return
      }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') finish()
    }
    window.addEventListener('keydown', onKey)
    return () => {
      cancelAnimationFrame(raf)
      window.removeEventListener('keydown', onKey)
    }
  }, [status, begin, finish, showChrome])

  if (status !== 'playing') return null

  const f = introFrame(t)
  // Cyan scan: strong while the letters assemble, relaxing as they settle but never quite stopping, on the
  // same clock as the heat shimmer it replaces. One sweep every 2.4 s.
  const scan = (1.6 + 5 * (1 - f.wordmark)) / 6.6
  const sweep = (t / 2.4) % 1
  const breathe = 0.5 + 0.5 * Math.sin(t * 2.4)

  return (
    <div className={styles.landing} data-testid="landing">
      <div className={styles.vignette} style={{ opacity: f.textOpacity }} />
      <div className={styles.copy} style={{ opacity: f.textOpacity }}>
        <div className={styles.wordmark} role="img" aria-label={WORDMARK}>
          <span
            className={styles.scan}
            aria-hidden="true"
            style={{ opacity: scan * (0.55 + 0.45 * breathe), top: `${-10 + sweep * 120}%` }}
          />
          {LETTERS.map((ch, i) => {
            const p = letterProgress(f.wordmark, i, LETTERS.length)
            const s = SCATTER[i]!
            return (
              <span
                key={i}
                aria-hidden="true"
                className={styles.letter}
                style={{
                  opacity: p,
                  transform: `translate(${s.dx * (1 - p)}px, ${s.dy * (1 - p)}px) rotate(${s.rot * (1 - p)}deg)`,
                  color: `color-mix(in srgb, var(--text) ${Math.round(p * 100)}%, var(--neon-cyan))`,
                  textShadow: `0 0 ${Math.round(10 + 26 * (1 - p))}px color-mix(in srgb, var(--neon-cyan) ${Math.round(70 - 20 * p)}%, transparent)`,
                }}
              >
                {ch}
              </span>
            )
          })}
        </div>
        <p className={styles.tagline} style={{ opacity: f.tagline, transform: `translateY(${(1 - f.tagline) * 10}px)` }}>
          {TAGLINE}
        </p>
      </div>
      {!f.chrome && (
        <button type="button" className={styles.skip} onClick={finish} aria-keyshortcuts="Escape">
          Skip intro
        </button>
      )}
    </div>
  )
}
