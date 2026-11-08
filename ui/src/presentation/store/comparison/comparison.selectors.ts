import { createSelector } from '@reduxjs/toolkit'
import { isDifference, type ComparisonRow } from '@/application'
import type { RootState } from '../store.types'
import type { ComparisonFilter } from './comparison.types'

export const selectComparison = (state: RootState) => state.comparison
export const selectComparisonFilter = (state: RootState) =>
  state.comparison.filter
export const selectComparisonResult = (state: RootState) =>
  state.comparison.result

const matchesFilter = (filter: ComparisonFilter) => (row: ComparisonRow) =>
  filter === 'all' ||
  (filter === 'same' ? row.state === 'same' : isDifference(row))

export interface ComparisonArea {
  readonly area: string
  readonly rows: readonly ComparisonRow[]
  readonly differences: number
}

/** Filas de equipo, hardware y sistema agrupadas por área, con el filtro aplicado. */
export const selectComparisonAreas = createSelector(
  [selectComparisonResult, selectComparisonFilter],
  (result, filter) => {
    const groups = new Map<string, ComparisonRow[]>()
    for (const row of result?.rows ?? [])
      groups.set(row.area, [...(groups.get(row.area) ?? []), row])
    // Un área sin filas para el filtro elegido no se muestra: evita repetir «nada que mostrar».
    return [...groups.entries()]
      .map(([area, rows]): ComparisonArea => ({
        area,
        rows: rows.filter(matchesFilter(filter)),
        differences: rows.filter(isDifference).length,
      }))
      .filter((area) => area.rows.length > 0)
  },
)

export const selectFilteredSoftware = createSelector(
  [selectComparisonResult, selectComparisonFilter],
  (result, filter) => (result?.software ?? []).filter(matchesFilter(filter)),
)

export const selectComparisonTotals = createSelector(
  [selectComparisonResult],
  (result) => {
    const rows = [...(result?.rows ?? []), ...(result?.software ?? [])]
    return {
      differences: rows.filter(isDifference).length,
      same: rows.filter((row) => row.state === 'same').length,
    }
  },
)
