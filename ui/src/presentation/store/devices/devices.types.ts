import type { DevicePage, InventorySummary } from '@/application'

export type SortOrder = 'asc' | 'desc'

export interface DeviceQuery {
  readonly q: string
  readonly manufacturer: string
  readonly type: string
  readonly os: string
  readonly status: string
  readonly sort: string
  readonly order: SortOrder
  readonly page: number
  readonly size: number
}

export type DeviceFilterKey = 'manufacturer' | 'type' | 'os' | 'status'

export interface DevicesSliceState {
  readonly query: DeviceQuery
  readonly page: DevicePage | null
  readonly loading: boolean
  // Versiones cargadas al desplegar cada equipo, por su clave.
  readonly versions: Readonly<Record<string, readonly InventorySummary[]>>
  readonly notice: string | null
}
