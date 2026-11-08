import { useMemo, useState } from 'react'
import type { SoftwareItem } from '@/application'
import { formatBytes } from '@/presentation/shared/formatters'
import {
  filterSoftware,
  type SoftwareFilter,
} from '../formatters/filterSoftware'

const INITIAL: SoftwareFilter = {
  search: '',
  scope: '',
  installer: '',
  showSystem: false,
}

/** Filtro local de la lista de programas: lo que se escribe solo afecta a esta pantalla. */
export function useSoftwareFilter(items: readonly SoftwareItem[]) {
  const [filter, setFilter] = useState<SoftwareFilter>(INITIAL)
  const visible = useMemo(() => filterSoftware(items, filter), [items, filter])
  const declared = visible.reduce(
    (sum, item) => sum + (item.sizeBytes.value ?? 0),
    0,
  )

  return {
    filter,
    visible,
    declaredSize: declared ? formatBytes(declared) : null,
    update: (patch: Partial<SoftwareFilter>) => {
      setFilter((current) => ({ ...current, ...patch }))
    },
  }
}
