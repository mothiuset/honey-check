import { compareResults, type Run } from '@/application'
import { Copyable } from '@/presentation/shared/components'
import { formatBytes, formatDate } from '@/presentation/shared/formatters'
import styles from './Changes.module.css'

const signed = (bytes: number) =>
  `${bytes > 0 ? '+' : '−'}${formatBytes(Math.abs(bytes))}`

/**
 * Qué cambió desde la versión anterior con los mismos datos: las cifras del resumen y las
 * carpetas que más crecieron o bajaron. Si nada cambió, lo dice en una línea.
 */
export function Changes({ before, after }: { before: Run; after: Run }) {
  if (!before.result || !after.result) return null
  const changes = compareResults(before.result, after.result)
  const nothing = !changes.facts.length && !changes.space.length
  return (
    <section className={styles.changes} aria-labelledby="changes-title">
      <h3 id="changes-title">
        Cambios desde el {formatDate(before.startedAt)}
      </h3>
      {nothing ? (
        <p className={styles.none}>Nada cambió de forma notable.</p>
      ) : null}
      {changes.facts.length ? (
        <ul className={styles.facts}>
          {changes.facts.map((fact) => (
            <li key={fact.label}>
              <span className={styles.label}>{fact.label}</span>
              <span className={styles.before}>{fact.before ?? 'sin dato'}</span>
              <span aria-hidden="true">→</span>
              <span className={styles.after}>{fact.after ?? 'sin dato'}</span>
            </li>
          ))}
        </ul>
      ) : null}
      {changes.space.length ? (
        <ul className={styles.space}>
          {changes.space.map((change) => (
            <li key={change.path} data-grew={change.delta > 0 || undefined}>
              <Copyable text={change.path} truncate="start" mono />
              <span className={styles.delta}>{signed(change.delta)}</span>
              <span className={styles.now}>{formatBytes(change.after)}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  )
}
