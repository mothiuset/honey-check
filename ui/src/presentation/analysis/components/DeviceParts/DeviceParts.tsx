import type { PeripheralPart } from '@/application'
import { Copyable } from '@/presentation/shared/components'
import styles from './DeviceParts.module.css'

/** Las piezas que Windows registra para un aparato: detalle técnico, plegado bajo su fila. */
export function DeviceParts({ parts }: { parts: readonly PeripheralPart[] }) {
  if (!parts.length) return null
  return (
    <div className={styles.parts}>
      <p className={styles.heading}>
        Windows lo registra en {parts.length} parte
        {parts.length === 1 ? '' : 's'}
      </p>
      <ul>
        {parts.map((part) => (
          <li key={part.instanceId}>
            <span className={styles.name}>{part.name ?? 'Sin nombre'}</span>
            <Copyable text={part.instanceId} truncate="start" mono />
          </li>
        ))}
      </ul>
    </div>
  )
}
