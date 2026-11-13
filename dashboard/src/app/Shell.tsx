import { MotionConfig, motion } from 'framer-motion'
import { lazy, Suspense } from 'react'
import { NavLink, Outlet, useMatch } from 'react-router-dom'
import { webglAvailable } from '../lib/motion'
import Landing from '../scene/Landing'
import { useIntro } from '../state/intro'
import { AlertIcon, MapIcon, PeakIcon, SensorIcon, StoryIcon } from './icons'
import styles from './Shell.module.css'
import StatusStrip from './StatusStrip'

const TerrainScene = lazy(() => import('../scene/TerrainScene'))

export const NAV_ITEMS = [
  { to: '/map', label: 'Live map', Icon: MapIcon },
  { to: '/alerts-why', label: 'Alerts', Icon: AlertIcon },
  { to: '/sensors-sources', label: 'Sensors & sources', Icon: SensorIcon },
  { to: '/story', label: 'How it works', Icon: StoryIcon },
] as const

const EASE_OUT = [0.16, 1, 0.3, 1] as const

export default function Shell() {
  const chrome = useIntro((s) => s.chrome)
  const onMap = useMatch('/map') !== null
  const onStory = useMatch('/story') !== null

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
          <motion.div
            className={styles.top}
            initial={false}
            animate={{ y: chrome ? 0 : '-100%', opacity: chrome ? 1 : 0 }}
            inert={!chrome}
          >
            <StatusStrip>
              <div className={styles.brand}>
                <PeakIcon size={20} />
                AetherGuard
              </div>
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
            data-story={onStory}
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
