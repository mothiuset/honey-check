import { fold } from '@/presentation/shared/formatters/formatValue'
import type { Column, SortState } from './DataTable.types'

/** Orden local estable; los valores vacíos siempre al final. */
export function sortRows<R>(
  rows: readonly R[],
  columns: readonly Column<R>[],
  sort: SortState,
): readonly R[] {
  const pick = columns.find((column) => column.key === sort.key)?.value
  if (!pick) return rows
  const direction = sort.order === 'asc' ? 1 : -1
  return [...rows].sort((a, b) => {
    const x = pick(a)
    const y = pick(b)
    if (x === y) return 0
    if (x === null || x === undefined) return 1
    if (y === null || y === undefined) return -1
    if (typeof x === 'number' && typeof y === 'number')
      return (x - y) * direction
    return fold(String(x)).localeCompare(fold(String(y))) * direction
  })
}
