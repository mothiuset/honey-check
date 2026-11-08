import { useMemo, useState } from 'react'
import type { Column, DataTableProps, SortState } from './DataTable.types'
import { sortRows } from './sortRows'

export function useDataTable<R>({
  columns,
  rows,
  rowKey,
  serverSort,
  onExpand,
}: DataTableProps<R>) {
  const [localSort, setLocalSort] = useState<SortState>({
    key: null,
    order: 'asc',
  })
  const [open, setOpen] = useState<ReadonlySet<string>>(new Set())

  const sort: SortState = serverSort
    ? { key: serverSort.key, order: serverSort.order }
    : localSort
  const sorted = useMemo(
    () => (serverSort ? rows : sortRows(rows, columns, localSort)),
    [rows, columns, localSort, serverSort],
  )

  function toggleSort(column: Column<R>): void {
    if (!column.sortable) return
    if (serverSort) {
      serverSort.onSort(column.key)
      return
    }
    setLocalSort((current) =>
      current.key === column.key
        ? { key: column.key, order: current.order === 'asc' ? 'desc' : 'asc' }
        : { key: column.key, order: 'asc' },
    )
  }

  function toggleRow(row: R): void {
    const key = rowKey(row)
    const next = new Set(open)
    if (next.has(key)) next.delete(key)
    else {
      next.add(key)
      onExpand?.(row)
    }
    setOpen(next)
  }

  function ariaSort(
    column: Column<R>,
  ): 'ascending' | 'descending' | 'none' | undefined {
    if (!column.sortable) return undefined
    if (sort.key !== column.key) return 'none'
    return sort.order === 'asc' ? 'ascending' : 'descending'
  }

  return {
    sorted,
    sort,
    toggleSort,
    toggleRow,
    ariaSort,
    isOpen: (row: R) => open.has(rowKey(row)),
  }
}
