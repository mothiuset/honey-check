import { useMemo, useState } from 'react'
import type { ComparisonRow } from '@/application'
import { groupSoftware, softwareSummary } from '../formatters/groupSoftware'

/** Búsqueda local dentro del software comparado. */
export function useSoftwareComparison(
  rows: readonly ComparisonRow[],
  all: readonly ComparisonRow[],
) {
  const [search, setSearch] = useState('')
  const groups = useMemo(() => groupSoftware(rows, search), [rows, search])
  return {
    search,
    setSearch,
    groups,
    summary: softwareSummary(all),
    hasDifferences: all.some((row) => row.state !== 'same'),
  }
}
