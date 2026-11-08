// Equipos guardados en la carpeta de datos y sus versiones (cada análisis es una versión nueva).

export interface InventorySummary {
  readonly id: string
  readonly deviceKey: string
  readonly sequence: number | null
  readonly fileName: string
  readonly directory: string
  readonly sizeBytes: number
  readonly collectedAt: string | null
  readonly hostname: string | null
  readonly manufacturer: string | null
  readonly model: string | null
  readonly serialNumber: string | null
  readonly status: string | null
  readonly schemaVersion: string | null
  readonly appVersion: string | null
  // Presente si el archivo no se puede leer; la versión se lista igual para poder retirarla.
  readonly invalidReason: string | null
}

export function isReadable(summary: InventorySummary): boolean {
  return summary.invalidReason === null
}

export interface DeviceSummary {
  readonly deviceKey: string
  readonly isCurrent: boolean
  readonly hostname: string | null
  readonly manufacturer: string | null
  readonly model: string | null
  readonly serialNumber: string | null
  readonly deviceType: string | null
  readonly osName: string | null
  readonly domain: string | null
  readonly lastStatus: string | null
  readonly inventoryCount: number
  readonly unreadableCount: number
  readonly lastInventoryId: string | null
  readonly lastCollectedAt: string | null
  readonly firstCollectedAt: string | null
}

export type DeviceFacet = 'manufacturer' | 'deviceType' | 'os' | 'status'

export interface DevicePage {
  readonly items: readonly DeviceSummary[]
  readonly total: number
  readonly page: number
  readonly pages: number
  readonly size: number
  readonly facets: Readonly<
    Partial<Record<DeviceFacet, readonly (readonly [string, number])[]>>
  >
  readonly currentDeviceKey: string | null
}

/** Una versión concreta de un equipo, como la elige el técnico para comparar. */
export interface DeviceVersion {
  readonly device: DeviceSummary
  readonly inventoryId: string
}
