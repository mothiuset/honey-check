import type { CheckStatus, Run } from '@/application'
import { StatusGlyph } from '../StatusGlyph/StatusGlyph'
import styles from './Verdict.module.css'

interface Outcome {
  readonly status: CheckStatus
  readonly text: string
}

const plural = (n: number, one: string, many: string) =>
  `${String(n)} ${n === 1 ? one : many}`

/** Lo que pasó, en una frase: cuánto se logró, qué falta y si algo termina al reiniciar. */
export function outcomeOf(run: Run): Outcome | null {
  if (run.status === 'running') return null
  if (run.status === 'cancelled') {
    return run.error === 'elevation_declined'
      ? {
          status: 'skipped',
          text: 'No se dio permiso de administrador. No cambió nada.',
        }
      : {
          status: 'skipped',
          text: 'Se canceló. Lo hecho hasta ahí quedó en el registro.',
        }
  }
  if (run.status === 'failed') {
    return {
      status: 'fail',
      text: run.error ? `No se pudo: ${run.error}` : 'No se pudo.',
    }
  }
  const checks = (run.result?.checks ?? []).filter(
    (c) => c.status !== 'skipped',
  )
  const failed = checks.filter((c) => c.status === 'fail').length
  const warned = checks.filter((c) => c.status === 'warn').length
  if (checks.length) {
    const done = checks.length - failed
    if (failed) {
      return {
        status: 'fail',
        text: `${String(done)} de ${String(checks.length)} hechos. ${plural(failed, 'no se pudo', 'no se pudieron')}: abajo dice por qué y qué hacer.`,
      }
    }
    if (warned) {
      return {
        status: 'warn',
        text: `Hecho, con ${plural(warned, 'aviso', 'avisos')}: revise lo marcado en amarillo.`,
      }
    }
    return {
      status: 'ok',
      text:
        checks.length === 1
          ? 'Hecho y verificado.'
          : `Hecho: ${String(checks.length)} de ${String(checks.length)}, verificados.`,
    }
  }
  if (run.risk === 'read') return null
  return run.result?.verified === false
    ? {
        status: 'warn',
        text: 'Terminó, pero la verificación no confirmó el cambio.',
      }
    : { status: 'ok', text: 'Hecho y verificado.' }
}

export function Verdict({ run }: { run: Run }) {
  const outcome = outcomeOf(run)
  if (!outcome) return null
  return (
    <p className={styles.verdict} data-status={outcome.status} role="status">
      <StatusGlyph status={outcome.status} />
      <span>{outcome.text}</span>
    </p>
  )
}
