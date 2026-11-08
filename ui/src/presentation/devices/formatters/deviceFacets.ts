import type { DeviceFacet, DevicePage } from '@/application'
import { DEVICE_TYPES, STATUS_LABELS } from '@/presentation/shared/formatters'
import type { DeviceFilterKey } from '@/presentation/store'

export interface FacetFilter {
  readonly key: DeviceFilterKey
  readonly label: string
  readonly options: readonly {
    readonly value: string
    readonly label: string
  }[]
}

const FACETS: readonly (readonly [
  DeviceFilterKey,
  DeviceFacet,
  string,
  (value: string) => string,
])[] = [
  ['manufacturer', 'manufacturer', 'Fabricante', (value) => value],
  ['type', 'deviceType', 'Tipo', (value) => DEVICE_TYPES[value] ?? value],
  ['os', 'os', 'Sistema', (value) => value],
  [
    'status',
    'status',
    'Último resultado',
    (value) => STATUS_LABELS[value] ?? value,
  ],
]

/** Filtros disponibles con los valores que existen en la carpeta y cuántos equipos tiene cada uno. */
export function facetFilters(page: DevicePage | null): readonly FacetFilter[] {
  return FACETS.map(([key, facet, label, format]) => ({
    key,
    label,
    options: (page?.facets[facet] ?? []).map(([value, count]) => ({
      value,
      label: `${format(value)} (${String(count)})`,
    })),
  }))
}
