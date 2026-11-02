import { MotionConfig, motion } from 'framer-motion'
import { lazy, Suspense } from 'react'
import { NavLink, Outlet, useMatch } from 'react-router-dom'
import { webglAvailable } from '../lib/motion'
import Landing from '../scene/Landing'
import { useIntro } from '../state/intro'
import { AlertIcon, MapIcon, SensorIcon } from './icons'
import styles from './Shell.module.css'
import StatusStrip from './StatusStrip'

const TerrainScene = lazy(() => import('../scene/TerrainScene'))

export const NAV_ITEMS = [
  { to: '/map', label: 'Live map', Icon: MapIcon },
  { to: '/alerts-why', label: 'Alerts', Icon: AlertIcon },
  { to: '/sensors-sources', label: 'Sensors & sources', Icon: SensorIcon },
] as const

const EASE_OUT = [0.16, 1, 0.3, 1] as const

export default function Shell() {
  const chrome = useIntro((s) => s.chrome)
  const onMap = useMatch('/map') !== null

  return (
    <MotionConfig reducedMotion="user" transition={{ duration: 0.6, ease: EASE_OUT }}>
      <div className={styles.app}>
        {webglAvailable() && (
          <Suspense fallback={null}>
            <TerrainScene />
          </Suspense>
        )}
        <div className={styles.scrim} data-dim={!onMap} aria-hidden="true" />

        <motion.nav
          className={styles.rail}
          aria-label="Views"
          initial={false}
          animate={{ x: chrome ? 0 : '-100%', opacity: chrome ? 1 : 0 }}
          inert={!chrome}
        >
          <div className={styles.brand}>AetherGuard</div>
          <ul className={styles.nav}>
            {NAV_ITEMS.map(({ to, label, Icon }) => (
              <li key={to}>
                <NavLink to={to} className={({ isActive }) => `${styles.link} ${isActive ? styles.active : ''}`}>
                  <Icon />
                  <span>{label}</span>
                </NavLink>
              </li>
            ))}
          </ul>
        </motion.nav>

        <div className={styles.column}>
          <motion.div
            initial={false}
            animate={{ y: chrome ? 0 : '-100%', opacity: chrome ? 1 : 0 }}
            inert={!chrome}
          >
            <StatusStrip />
          </motion.div>
          <motion.main
            className={styles.main}
            id="view"
            data-map={onMap}
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
