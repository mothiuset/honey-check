// API del store para los hooks de cada capacidad: acciones, thunks y selectores listos para usar.
// Ningún componente importa de aquí; solo los hooks.

export { buildStore, type AppStore } from './store'
export { useAppDispatch, useAppSelector } from './hooks'
export type { RootState } from './store.types'

export { sessionActions } from './session/sessionSlice'
export * from './session/session.thunks'
export * from './session/session.selectors'

export { inventoryActions } from './inventory/inventorySlice'
export * from './inventory/inventory.thunks'
export * from './inventory/inventory.selectors'
export type { ExportFeedback } from './inventory/inventory.types'

export { devicesActions } from './devices/devicesSlice'
export * from './devices/devices.thunks'
export * from './devices/devices.selectors'
export type {
  DeviceFilterKey,
  DeviceQuery,
  SortOrder,
} from './devices/devices.types'

export { comparisonActions } from './comparison/comparisonSlice'
export * from './comparison/comparison.thunks'
export * from './comparison/comparison.selectors'
export type { ComparisonFilter } from './comparison/comparison.types'

export * from './confirmation/confirmation.thunks'
export * from './confirmation/confirmation.selectors'
export type { ConfirmationRequest } from './confirmation/confirmation.types'

export * from './links/links.thunks'

export { supportActions } from './support/supportSlice'
export * from './support/support.thunks'
export * from './support/support.selectors'
export type { SupportNotice } from './support/support.types'

export { actionsActions } from './actions/actionsSlice'
export * from './actions/actions.thunks'
export * from './actions/actions.selectors'
export type {
  ActionPanel,
  ActionRequest,
  ActionToast,
} from './actions/actions.types'
