// API pública de la aplicación: lo único que la presentación importa.

export type {
  AppUseCases,
  CurrentDeviceView,
  SupportOutcome,
  SupportRefusal,
} from './use-cases'
export type { DeviceSearch } from './ports/HoneyCheckGateway'

export { isDifference } from '@/domain/comparison/Comparison'
export type {
  Comparison,
  ComparisonRow,
  ComparisonState,
} from '@/domain/comparison/Comparison'
export { isReadable } from '@/domain/devices/Device'
export type {
  DeviceFacet,
  DevicePage,
  DeviceSummary,
  DeviceVersion,
  InventorySummary,
} from '@/domain/devices/Device'
export {
  isDetailComponent,
  isUserFacingSoftware,
} from '@/domain/inventory/Inventory'
export type * from '@/domain/inventory/Inventory'
export { isScanActive } from '@/domain/session/AppStatus'
export type {
  AppStatus,
  SavedVersion,
  ScanProgress,
  ScanState,
  Workspace,
} from '@/domain/session/AppStatus'
export {
  compareResults,
  initialValues,
  isRunFinished,
  linkParams,
  missingRequired,
  requestParams,
} from '@/domain/support/Support'
export type * from '@/domain/support/Support'
