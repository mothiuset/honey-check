import type { InventorySummary } from '@/domain/devices/Device'
import type { Inventory } from '@/domain/inventory/Inventory'

/** Lo que se muestra de ESTE equipo: su historial y el análisis más reciente que se puede leer. */
export interface DeviceHistory {
  readonly history: readonly InventorySummary[]
  readonly deviceTotal: number
}

export interface CurrentDeviceView extends DeviceHistory {
  readonly current: Inventory | null
  readonly currentId: string | null
}

export type ExportResult =
  { readonly ok: true } | { readonly ok: false; readonly reason: string }

export interface InventoryUseCases {
  history(deviceKey: string | null): Promise<DeviceHistory>
  currentDeviceView(
    deviceKey: string | null,
    hasPendingInventory: boolean,
  ): Promise<CurrentDeviceView>
  open(id: string): Promise<Inventory>
  remove(id: string): Promise<void>
  setReference(id: string): Promise<void>
  exportPending(directory: string): Promise<ExportResult>
  downloadUrl(id: string): string
  pendingDownloadUrl(): string
  iconUrl(inventoryId: string, iconId: string): string
}
