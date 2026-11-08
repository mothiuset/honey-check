import { useMemo, useState } from 'react'
import type { ResultRow, ResultTable } from '@/application'
import { fold } from '@/presentation/shared/formatters'

// Con pocas filas el buscador sobra.
const SEARCH_FROM = 12

/** Búsqueda dentro de las filas de un resultado y selección para la acción sobre varias. */
export function useResultTable(table: ResultTable) {
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set())

  const keyOf = (row: ResultRow) => String(row[table.rowKey] ?? '')
  const rows = useMemo(() => {
    const words = fold(query).split(/\s+/).filter(Boolean)
    if (!words.length) return table.rows
    return table.rows.filter((row) => {
      const text = fold(Object.values(row).join(' '))
      return words.every((word) => text.includes(word))
    })
  }, [query, table.rows])

  return {
    rows,
    keyOf,
    searchable: table.rows.length >= SEARCH_FROM,
    query,
    setQuery,
    selectable: Boolean(table.bulkAction && table.selectionParam),
    selected: [...selected],
    isSelected: (row: ResultRow) => selected.has(keyOf(row)),
    toggle: (row: ResultRow) => {
      const key = keyOf(row)
      setSelected((current) => {
        const next = new Set(current)
        if (next.has(key)) next.delete(key)
        else next.add(key)
        return next
      })
    },
    selectVisible: (on: boolean) => {
      setSelected(on ? new Set(rows.map(keyOf)) : new Set())
    },
  }
}
