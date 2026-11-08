import type { ComparisonFilter as Filter } from '../../types/devices.types'
import styles from './ComparisonFilter.module.css'

export interface ComparisonFilterProps {
  readonly value: Filter
  readonly differences: number
  readonly same: number
  readonly onChange: (value: Filter) => void
}

/** Conmutador Solo diferencias, Solo iguales y Todo, con sus conteos. */
export function ComparisonFilter({
  value,
  differences,
  same,
  onChange,
}: ComparisonFilterProps) {
  const options: readonly (readonly [Filter, string, number | null])[] = [
    ['differences', 'Solo diferencias', differences],
    ['same', 'Solo iguales', same],
    ['all', 'Todo', null],
  ]
  return (
    <div className={styles.switch} role="group" aria-label="Qué mostrar">
      {options.map(([option, label, count]) => (
        <button
          key={option}
          type="button"
          className={styles.option}
          aria-pressed={value === option}
          onClick={() => {
            onChange(option)
          }}
        >
          {label}
          {count === null ? null : (
            <strong className={styles.count}>{count}</strong>
          )}
        </button>
      ))}
    </div>
  )
}
