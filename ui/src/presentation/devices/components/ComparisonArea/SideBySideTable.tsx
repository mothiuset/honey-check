import type { ComparisonRow } from '@/application'
import { DataTable, type Column } from '@/presentation/shared/components'
import { STATE_LABELS, sideValue } from '../../formatters/comparisonValue'
import styles from './ComparisonArea.module.css'

export interface SideBySideTableProps {
  readonly rows: readonly ComparisonRow[]
  readonly label: (row: ComparisonRow) => string
  readonly showHeader?: boolean
  readonly showState?: boolean
}

/** Filas con el dato, el valor de la base y el de la otra versión, resaltadas según su estado. */
export function SideBySideTable({
  rows,
  label,
  showHeader = true,
  showState = true,
}: SideBySideTableProps) {
  const columns: readonly Column<ComparisonRow>[] = [
    {
      key: 'field',
      label: 'Dato',
      render: (row) => (
        <>
          {label(row)}
          {showState ? (
            <span className={styles.state}>{STATE_LABELS[row.state]}</span>
          ) : null}
        </>
      ),
    },
    { key: 'before', label: 'Base', render: (row) => sideValue(row, 'before') },
    {
      key: 'after',
      label: 'Comparar con',
      render: (row) => sideValue(row, 'after'),
    },
  ]
  return (
    <DataTable
      columns={columns}
      rows={rows}
      rowKey={(row) => `${row.field}-${label(row)}`}
      rowState={(row) => row.state}
      hideHeader={!showHeader}
      rowHeaders
    />
  )
}
