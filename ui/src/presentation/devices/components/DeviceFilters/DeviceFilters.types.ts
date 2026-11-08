import type { DeviceFilterKey, DeviceQuery } from '@/presentation/store'
import type { FacetFilter } from '../../formatters/deviceFacets'

export interface DeviceFiltersProps {
  readonly text: string
  readonly query: DeviceQuery
  readonly filters: readonly FacetFilter[]
  readonly onSearch: (text: string) => void
  readonly onFilter: (key: DeviceFilterKey, value: string) => void
}
