// Inventarios: abrir el de este equipo (nunca uno de otro equipo de la USB como propio), abrir una
// versión concreta, retirarla a la papelera y guardar un análisis pendiente.

import { isReadable } from '@/domain/devices/Device'
import {
  GatewayError,
  type HoneyCheckGateway,
} from '../../ports/HoneyCheckGateway'
import type { InventoryUseCases } from './inventories.types'

export function createInventoryUseCases({
  gateway,
}: {
  gateway: HoneyCheckGateway
}): InventoryUseCases {
  async function history(deviceKey: string | null) {
    const [items, page] = await Promise.all([
      deviceKey ? gateway.inventories(deviceKey) : Promise.resolve([]),
      gateway.devices({ size: 1 }),
    ])
    return { history: items, deviceTotal: page.total }
  }

  return {
    history,

    async currentDeviceView(deviceKey, hasPendingInventory) {
      const known = await history(deviceKey)
      const newest = known.history.find(isReadable)
      if (newest)
        return {
          ...known,
          current: await gateway.inventory(newest.id),
          currentId: newest.id,
        }
      const current = hasPendingInventory
        ? await gateway.pendingInventory()
        : null
      return { ...known, current, currentId: null }
    },

    open: (id) => gateway.inventory(id),
    remove: (id) => gateway.deleteInventory(id),
    setReference: (id) => gateway.setReference(id),

    async exportPending(directory) {
      try {
        await gateway.exportPending(directory)
        return { ok: true }
      } catch (error) {
        return {
          ok: false,
          reason:
            error instanceof GatewayError
              ? (error.reason ?? error.code ?? '')
              : '',
        }
      }
    },

    downloadUrl: (id) => gateway.downloadUrl(id),
    pendingDownloadUrl: () => gateway.pendingDownloadUrl(),
    iconUrl: (inventoryId, iconId) => gateway.iconUrl(inventoryId, iconId),
  }
}
