import type { Run } from '@/application'
import { Button } from '@/presentation/shared/components'
import { formatDate } from '@/presentation/shared/formatters'
import styles from './VersionBar.module.css'

interface VersionBarProps {
  readonly run: Run
  readonly versions: readonly Run[]
  readonly onOpen: (runId: string) => void
  readonly onRefresh: () => void
  readonly busy: boolean
  /** Un cambio terminó después de este resultado. */
  readonly stale?: boolean
}

/** «hace 12 min», «hace 3 h», «hace 2 días»: lo viejo que está el resultado a la vista. */
export function ago(iso: string, now = Date.now()): string {
  const minutes = Math.max(0, Math.round((now - Date.parse(iso)) / 60_000))
  if (minutes < 1) return 'recién'
  if (minutes < 60) return `hace ${String(minutes)} min`
  const hours = Math.round(minutes / 60)
  if (hours < 48) return `hace ${String(hours)} h`
  return `hace ${String(Math.round(hours / 24))} días`
}

const firstFact = (run: Run) => {
  const fact = run.result?.summary[0]
  return fact?.value ? `, ${fact.label.toLowerCase()} ${fact.value}` : ''
}

/**
 * De cuándo es el resultado a la vista, las otras versiones guardadas y «Actualizar». Un análisis
 * no se pierde al cambiar de pantalla y se repite solo cuando el técnico lo pide.
 */
export function VersionBar({
  run,
  versions,
  onOpen,
  onRefresh,
  busy,
  stale = false,
}: VersionBarProps) {
  const running = run.status === 'running'
  return (
    <div className={styles.bar}>
      <p className={styles.when}>
        {running ? 'En curso desde ' : 'Resultado del '}
        <strong>{formatDate(run.startedAt)}</strong> ({ago(run.startedAt)})
      </p>
      {stale ? (
        <p className={styles.stale} role="status">
          El equipo cambió después de este resultado: actualícelo para verlo
          como está.
        </p>
      ) : null}
      {versions.length > 1 ? (
        <label className={styles.versions}>
          <span>Versiones ({versions.length})</span>
          <select
            value={run.id}
            onChange={(event) => {
              onOpen(event.target.value)
            }}
          >
            {versions.map((version) => (
              <option key={version.id} value={version.id}>
                {formatDate(version.startedAt)}
                {version.status === 'running'
                  ? ' (en curso)'
                  : firstFact(version)}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      <Button
        size="small"
        tone="primary"
        onClick={onRefresh}
        disabled={running || busy}
      >
        Actualizar
      </Button>
    </div>
  )
}
