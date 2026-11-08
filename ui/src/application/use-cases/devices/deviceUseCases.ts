// Equipos guardados en la carpeta de datos: búsqueda paginada en el servidor, versiones y retiro.

import type { HoneyCheckGateway } from '../../ports/HoneyCheckGateway'
import type { DeviceUseCases } from './devices.types'

export function createDeviceUseCases({
  gateway,
}: {
  gateway: HoneyCheckGateway
}): DeviceUseCases {
  return {
    search: (search) => gateway.devices(search),
    versions: (deviceKey) => gateway.inventories(deviceKey),

    async versionOwner(inventoryId) {
      try {
        const summary = await gateway.inventorySummary(inventoryId)
        const page = await gateway.devices({ q: summary.deviceKey, size: 10 })
        const device = page.items.find(
          (item) => item.deviceKey === summary.deviceKey,
        )
        return device ? { device, inventoryId } : null
      } catch {
        return null
      }
    },

    async remove(deviceKey) {
      return (await gateway.deleteDevice(deviceKey)).deleted
    },
  }
}
