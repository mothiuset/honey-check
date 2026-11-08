import { isUserFacingSoftware, type SoftwareItem } from '@/application'
import { fold } from '@/presentation/shared/formatters'
import type { SoftwareScopeFilter } from '../types/analysis.types'

export interface SoftwareFilter {
  readonly search: string
  readonly scope: SoftwareScopeFilter
  readonly installer: string
  readonly showSystem: boolean
}

/** Búsqueda por palabras (sin tildes) en nombre, editor, versión y rutas, más los filtros. */
export function filterSoftware(
  items: readonly SoftwareItem[],
  filter: SoftwareFilter,
): readonly SoftwareItem[] {
  const words = fold(filter.search).split(/\s+/).filter(Boolean)
  return items.filter((item) => {
    if (!filter.showSystem && !isUserFacingSoftware(item)) return false
    if (filter.scope && item.scope !== filter.scope) return false
    if (filter.installer && item.installerType !== filter.installer)
      return false
    if (!words.length) return true
    const haystack = fold(
      [
        item.name,
        item.publisher.value,
        item.version.value,
        item.executablePath.value,
        item.installPath.value,
      ]
        .filter(Boolean)
        .join(' '),
    )
    return words.every((word) => haystack.includes(word))
  })
}
