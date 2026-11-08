import type { ResultChart } from '@/application'
import { formatBytes, formatNumber } from '@/presentation/shared/formatters'
import styles from './ShareBars.module.css'
import { ShareRow } from './ShareRow'

const MAX_ROWS = 15

/** Reparto plano (por tipo de archivo, por consumible…): las filas más grandes primero. */
export function ShareBars({ chart }: { chart: ResultChart }) {
  const format = chart.unit === 'bytes' ? formatBytes : formatNumber
  const items = [...chart.data].sort((a, b) => b.value - a.value)
  const total = items.reduce((sum, item) => sum + item.value, 0)
  const shown = items.slice(0, MAX_ROWS)
  const rest = items.slice(MAX_ROWS).reduce((sum, item) => sum + item.value, 0)
  return (
    <section aria-label={chart.title}>
      <h3>{chart.title}</h3>
      <ul className={styles.list}>
        {shown.map((item) => (
          <ShareRow
            key={item.name}
            name={item.name}
            value={item.value}
            total={total}
            scale={shown[0]?.value ?? 0}
            format={format}
          />
        ))}
        {rest > 0 ? (
          <ShareRow
            name={`Otros ${String(items.length - MAX_ROWS)}`}
            value={rest}
            total={total}
            scale={shown[0]?.value ?? 0}
            format={format}
          />
        ) : null}
      </ul>
    </section>
  )
}
