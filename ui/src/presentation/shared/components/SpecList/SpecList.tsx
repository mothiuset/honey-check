import type { SpecRow } from '../../types/display.types'
import { Value } from '../Value'
import styles from './SpecList.module.css'

/** Ficha de detalle: etiqueta y valor, en dos columnas que en móvil se apilan. */
export function SpecList({ rows }: { rows: readonly SpecRow[] }) {
  return (
    <dl className={styles.spec}>
      {rows.map((row) => (
        <div key={row.label} className={styles.row}>
          <dt>{row.label}</dt>
          <dd>
            <Value display={row.value} />
          </dd>
        </div>
      ))}
    </dl>
  )
}
