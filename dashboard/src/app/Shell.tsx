import { MotionConfig, motion } from 'framer-motion'
import { lazy, Suspense, useEffect, useLayoutEffect } from 'react'
import { NavLink, Outlet, useLocation, useMatch } from 'react-router-dom'
import { prefersReducedMotion, webglAvailable } from '../lib/motion'
import Landing from '../scene/Landing'
import { useIntro } from '../state/intro'
import { AlertIcon, MapIcon, PeakIcon, SensorIcon } from './icons'
import styles from './Shell.module.css'
import StatusStrip from './StatusStrip'

const TerrainScene = lazy(() => import('../scene/TerrainScene'))

export const NAV_ITEMS = [
  { to: '/map', label: 'Live map', Icon: MapIcon },
  { to: '/alerts-why', label: 'Alerts', Icon: AlertIcon },
  { to: '/sensors-sources', label: 'Sensors & sources', Icon: SensorIcon },
] as const

const EASE_OUT = [0.16, 1, 0.3, 1] as const
/** Length of the press glint (global.css keeps the same). */
const GLINT_MS = 650

export default function Shell() {
  const chrome = useIntro((s) => s.chrome)
  const onMap = useMatch('/map') !== null
  const onDeck = useMatch('/deck') !== null
  const onStory = useMatch('/') !== null || onDeck
  const { pathname } = useLocation()

  // Every press glints: a band of light crosses the control (global.css `[data-glint]`). One listener for the whole app.
  useEffect(() => {
    const onDown = (event: PointerEvent) => {
      if (prefersReducedMotion()) return
      const target = event.target instanceof Element ? event.target.closest<HTMLElement>('button, a, summary, [role="button"]') : null
      if (!target || target.matches(':disabled')) return
      target.removeAttribute('data-glint')
      void target.offsetWidth                       // restart the animation on a second press
      target.setAttribute('data-glint', '')
      window.setTimeout(() => target.removeAttribute('data-glint'), GLINT_MS)
    }
    document.addEventListener('pointerdown', onDown)
    return () => document.removeEventListener('pointerdown', onDown)
  }, [])

  // The views share one scrolling region: each opens at its top, not where the last view was left.
  useLayoutEffect(() => {
    const view = document.getElementById('view')
    if (!view) return
    view.style.scrollBehavior = 'auto'      // the story scrolls smoothly; this reset must not
    view.scrollTop = 0
    view.style.scrollBehavior = ''
  }, [pathname])

  return (
    <MotionConfig reducedMotion="user" transition={{ duration: 0.6, ease: EASE_OUT }}>
      <div className={styles.app}>
        {webglAvailable() && (
          <Suspense fallback={null}>
            <TerrainScene />
          </Suspense>
        )}
        <div className={styles.scrim} data-dim={!onMap && !onStory} aria-hidden="true" />

        <div className={styles.column}>
          {/* The presentation is full-screen: the bar steps away while it runs. */}
          <motion.div
            className={styles.top}
            initial={false}
            animate={{ y: chrome && !onDeck ? 0 : '-100%', opacity: chrome && !onDeck ? 1 : 0 }}
            style={onDeck ? { position: 'absolute', insetInline: 0 } : undefined}
            inert={!chrome || onDeck}
          >
            <StatusStrip>
              <NavLink to="/" end viewTransition className={styles.brand} aria-label="AetherGuard, the story of the chart">
                <PeakIcon size={20} />
                AetherGuard
              </NavLink>
              <nav className={styles.nav} aria-label="Views">
                {NAV_ITEMS.map(({ to, label, Icon }) => (
                  <NavLink key={to} to={to} viewTransition className={styles.link}>
                    {({ isActive }) => (
                      <>
                        {/* One pill shared by the three links: it slides to the view that is open. */}
                        {isActive && (
                          <motion.span
                            layoutId="nav-pill"
                            className={styles.pill}
                            transition={{ duration: 0.42, ease: EASE_OUT }}
                            aria-hidden="true"
                          />
                        )}
                        <Icon size={18} />
                        <span>{label}</span>
                      </>
                    )}
                  </NavLink>
                ))}
              </nav>
            </StatusStrip>
          </motion.div>
          <motion.main
            className={styles.main}
            id="view"
            data-map={onMap}
            data-story={onStory && !onDeck}
            data-deck={onDeck}
            initial={false}
            animate={{ opacity: chrome ? 1 : 0 }}
            inert={!chrome}
          >
            <Outlet />
          </motion.main>
        </div>

        <Landing />
      </div>
    </MotionConfig>
  )
}
