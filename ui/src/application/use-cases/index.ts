import type { ComparisonUseCases } from './comparison/comparisonUseCases'
import type { DeviceUseCases } from './devices/devices.types'
import type { InventoryUseCases } from './inventories/inventories.types'
import type { SessionUseCases } from './session/session.types'
import type { SupportUseCases } from './support/support.types'

export interface AppUseCases {
  readonly session: SessionUseCases
  readonly inventories: InventoryUseCases
  readonly devices: DeviceUseCases
  readonly comparison: ComparisonUseCases
  readonly support: SupportUseCases
}

export {
  createComparisonUseCases,
  type ComparisonUseCases,
} from './comparison/comparisonUseCases'
export { createDeviceUseCases } from './devices/deviceUseCases'
export type { DeviceUseCases } from './devices/devices.types'
export { createInventoryUseCases } from './inventories/inventoryUseCases'
export type {
  CurrentDeviceView,
  DeviceHistory,
  ExportResult,
  InventoryUseCases,
} from './inventories/inventories.types'
export { createSessionUseCases } from './session/sessionUseCases'
export type {
  ElevationResult,
  ScanStartResult,
  SessionUseCases,
  StatusResult,
} from './session/session.types'
export { createSupportUseCases } from './support/supportUseCases'
export type {
  SupportOutcome,
  SupportRefusal,
  SupportUseCases,
} from './support/support.types'
