import { useRef, useState, type KeyboardEvent, type ReactNode } from 'react'
import styles from './Copyable.module.css'

interface CopyableProps {
  /** Lo que se copia (el valor completo, aunque se muestre recortado). */
  readonly text: string
  readonly children?: ReactNode
  /** En una línea con «…»: al final (texto) o al principio (rutas: queda a la vista el archivo). */
  readonly truncate?: 'end' | 'start' | undefined
  readonly mono?: boolean | undefined
}

/**
 * Un valor que se copia con un clic (serial, IP, MAC, ruta, cifra) y que se puede seleccionar
 * como cualquier texto: si hay una selección dentro, el clic no copia. Con teclado, Enter copia.
 */
export function Copyable({ text, children, truncate, mono }: CopyableProps) {
  const ref = useRef<HTMLSpanElement>(null)
  const [copied, setCopied] = useState(false)

  const copy = () => {
    void navigator.clipboard.writeText(text).then(
      () => {
        setCopied(true)
        window.setTimeout(() => {
          setCopied(false)
        }, 1400)
      },
      () => {
        setCopied(false)
      },
    )
  }

  const onClick = () => {
    const selection = window.getSelection()
    const selecting =
      selection !== null &&
      !selection.isCollapsed &&
      ref.current !== null &&
      ref.current.contains(selection.anchorNode)
    if (!selecting) copy()
  }

  const onKeyDown = (event: KeyboardEvent<HTMLSpanElement>) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      copy()
    }
  }

  return (
    <span
      ref={ref}
      className={styles.copyable}
      data-copied={copied || undefined}
      tabIndex={0}
      title={`${text}
Clic para copiar`}
      onClick={onClick}
      onKeyDown={onKeyDown}
    >
      <span
        className={styles.text}
        data-copy-text=""
        data-truncate={truncate}
        data-mono={mono || undefined}
      >
        {truncate === 'start' ? (
          // Se recorta por el principio; el contenido aislado se lee de izquierda a derecha.
          <bdi>{children ?? text}</bdi>
        ) : (
          (children ?? text)
        )}
      </span>
      <span className={styles.feedback} role="status" aria-live="polite">
        {copied ? 'Copiado' : ''}
      </span>
    </span>
  )
}
