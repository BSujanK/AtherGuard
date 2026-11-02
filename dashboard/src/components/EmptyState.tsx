import type { ReactNode } from 'react'
import { PeakIcon } from '../app/icons'
import styles from './EmptyState.module.css'

interface EmptyStateProps {
  title: string
  children: ReactNode
  action?: ReactNode
}

/** A plain statement of why a view has nothing to show, and what to do about it. */
export default function EmptyState({ title, children, action }: EmptyStateProps) {
  return (
    <section className={styles.empty} role="status">
      <PeakIcon size={36} className={styles.icon} />
      <h2>{title}</h2>
      <p>{children}</p>
      {action}
    </section>
  )
}
