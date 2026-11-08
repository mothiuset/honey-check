import type {
  DevicePage,
  DeviceVersion,
  InventorySummary,
} from '@/domain/devices/Device'
import type { DeviceSearch } from '../../ports/HoneyCheckGateway'

export interface DeviceUseCases {
  search(search: DeviceSearch): Promise<DevicePage>
  versions(deviceKey: string): Promise<readonly InventorySummary[]>
  /** El equipo dueño de una versión, para preseleccionarla al comparar. */
  versionOwner(inventoryId: string): Promise<DeviceVersion | null>
  remove(deviceKey: string): Promise<number>
}
