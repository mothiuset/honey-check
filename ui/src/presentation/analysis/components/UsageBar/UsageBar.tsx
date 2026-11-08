import { useUsageBar } from '../../hooks/useUsageBar'
import type { VolumeUsage } from '../../types/analysis.types'
import styles from './UsageBar.module.css'

/** Uso de un volumen: unidad, espacio libre y una barra que cambia de tono al llenarse. */
export function UsageBar({ usage }: { usage: VolumeUsage }) {
  const fill = useUsageBar(usage.percent)
  return (
    <div className={styles.volume}>
      <div className={styles.head}>
        <strong>{usage.drive}</strong>
        <span>{usage.name}</span>
        <span className={styles.free}>
          {usage.free} libres de {usage.size}
        </span>
      </div>
      <div
        className={styles.track}
        role="meter"
        aria-valuenow={Math.round(usage.percent)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`Uso de ${usage.drive}`}
      >
        <span ref={fill} className={styles.fill} data-tone={usage.tone} />
      </div>
    </div>
  )
}
