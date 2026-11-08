import type { Run } from '@/application'
import { Button } from '@/presentation/shared/components'
import { formatDate } from '@/presentation/shared/formatters'
import { duration } from '../../formatters/supportText'
import styles from './RunView.module.css'

const LEVEL_MARK = {
  info: '·',
  command: '>',
  output: ' ',
  warn: '!',
  error: '✕',
} as const

/**
 * Una ejecución: mientras corre, qué está haciendo ahora y cómo cancelarla; al terminar, cuándo
 * fue y el registro completo, plegado salvo que algo haya fallado.
 */
export function RunView({
  run,
  onCancel,
}: {
  run: Run
  onCancel: (runId: string) => void
}) {
  const running = run.status === 'running'
  const { done, total, label } = run.progress
  const last = [...run.log].reverse().find((entry) => entry.level !== 'output')
  return (
    <section className={styles.run} aria-live="polite" data-status={run.status}>
      {running ? (
        <div className={styles.progress}>
          {total > 0 ? (
            <progress max={total} value={done} aria-label="Avance" />
          ) : (
            <progress aria-label="Avance" />
          )}
          <div className={styles.now}>
            <span className={styles.label}>
              {label ?? last?.text ?? 'Trabajando…'}
            </span>
            <Button
              size="small"
              onClick={() => {
                onCancel(run.id)
              }}
            >
              Cancelar
            </Button>
          </div>
        </div>
      ) : (
        <p className={styles.when}>
          {formatDate(run.startedAt)}
          {run.finishedAt
            ? `, duró ${duration(run.startedAt, run.finishedAt)}`
            : ''}
          {run.elevated ? ', como administrador' : ''}
        </p>
      )}
      {run.log.length ? (
        <details
          className={styles.log}
          open={running || run.status === 'failed'}
        >
          <summary>Registro ({run.log.length})</summary>
          <ol>
            {run.log.map((entry, index) => (
              <li key={`${String(index)}-${entry.at}`} data-level={entry.level}>
                <span aria-hidden="true">{LEVEL_MARK[entry.level]}</span>
                <span>{entry.text}</span>
              </li>
            ))}
          </ol>
        </details>
      ) : null}
    </section>
  )
}
