import { useId, type ReactNode } from 'react'
import styles from './ShareBars.module.css'

interface ShareRowProps {
  readonly name: string
  readonly detail?: string | null | undefined
  readonly value: number
  /** Total del que se calcula el porcentaje. */
  readonly total: number
  /** Contra qué se mide la barra: el elemento más grande de la lista, para poder compararlas. */
  readonly scale: number
  readonly format: (value: number) => string
  /** Entrar: la fila tiene más niveles adentro. */
  readonly onOpen?: (() => void) | undefined
  /** Elegir: la fila despliega sus acciones debajo. */
  readonly expanded?: boolean | undefined
  readonly onToggle?: (() => void) | undefined
  readonly actions?: ReactNode
}

/**
 * Una fila de reparto: nombre, barra proporcional, cantidad y porcentaje del total. Si tiene más
 * niveles, el clic entra; si tiene acciones, el clic la elige y las muestra debajo.
 */
export function ShareRow({
  name,
  detail,
  value,
  total,
  scale,
  format,
  onOpen,
  expanded,
  onToggle,
  actions,
}: ShareRowProps) {
  const panel = useId()
  const clamp = (n: number) => Math.max(0, Math.min(1, n))
  const percent = (total > 0 ? clamp(value / total) : 0) * 100
  const bar = (scale > 0 ? clamp(value / scale) : 0) * 100
  const content = (
    <>
      <span className={styles.name}>
        <span className={styles.title}>{name}</span>
        {detail ? <span className={styles.detail}>{detail}</span> : null}
      </span>
      <svg
        className={styles.bar}
        viewBox="0 0 100 4"
        preserveAspectRatio="none"
        aria-hidden="true"
      >
        <rect className={styles.track} width="100" height="4" />
        <rect className={styles.fill} width={bar.toFixed(2)} height="4" />
      </svg>
      <span className={styles.value}>{format(value)}</span>
      <span className={styles.share}>
        {percent >= 1 || percent === 0
          ? `${String(Math.round(percent))} %`
          : '<1 %'}
      </span>
    </>
  )
  const picks = Boolean(onToggle && !onOpen)
  return (
    <li className={styles.row} data-expanded={expanded || undefined}>
      {onOpen || onToggle ? (
        <button
          type="button"
          className={styles.line}
          data-kind={onOpen ? 'open' : 'pick'}
          onClick={onOpen ?? onToggle}
          aria-expanded={picks ? Boolean(expanded) : undefined}
          aria-controls={picks && expanded ? panel : undefined}
        >
          {content}
        </button>
      ) : (
        <span className={styles.line}>{content}</span>
      )}
      {expanded && actions ? (
        <div id={panel} className={styles.actions}>
          {actions}
        </div>
      ) : null}
    </li>
  )
}
