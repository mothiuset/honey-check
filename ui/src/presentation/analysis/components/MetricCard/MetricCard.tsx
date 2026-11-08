import { RouteLink } from '@/presentation/shared/navigation'
import type { Metric } from '../../types/analysis.types'
import styles from './MetricCard.module.css'

/** Tarjeta de un dato clave del panel; con `href` es un enlace a su apartado. */
export function MetricCard({ metric }: { metric: Metric }) {
  const body = (
    <>
      <span className={styles.label}>{metric.label}</span>
      <span className={styles.value}>{metric.value ?? 'Sin dato'}</span>
      {metric.detail ? (
        <span className={styles.detail}>{metric.detail}</span>
      ) : null}
    </>
  )
  return metric.href ? (
    <RouteLink
      href={metric.href}
      className={styles.card}
      data-tone={metric.tone}
    >
      {body}
    </RouteLink>
  ) : (
    <div className={styles.card} data-tone={metric.tone}>
      {body}
    </div>
  )
}
