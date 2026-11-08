import type { ReactNode } from 'react'
import styles from './Field.module.css'

export interface FieldProps {
  readonly label: string
  readonly grow?: boolean
  readonly children: ReactNode
}

/** Etiqueta visible encima de su control (búsqueda, filtro, ruta). */
export function Field({ label, grow = false, children }: FieldProps) {
  return (
    <label className={styles.field} data-grow={grow}>
      <span className={styles.label}>{label}</span>
      {children}
    </label>
  )
}

export function Check({
  label,
  checked,
  onChange,
}: {
  label: string
  checked: boolean
  onChange: (value: boolean) => void
}) {
  return (
    <label className={styles.check}>
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => {
          onChange(event.target.checked)
        }}
      />
      {label}
    </label>
  )
}
