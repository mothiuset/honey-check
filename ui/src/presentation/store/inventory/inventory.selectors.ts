import { createSelector } from '@reduxjs/toolkit'
import { isReadable } from '@/application'
import type { RootState } from '../store.types'

export const selectCurrentInventory = (state: RootState) =>
  state.inventory.current
export const selectCurrentInventoryId = (state: RootState) =>
  state.inventory.currentId
export const selectHistory = (state: RootState) => state.inventory.history
export const selectDeviceTotal = (state: RootState) =>
  state.inventory.deviceTotal

export const selectReadableHistory = createSelector(
  [selectHistory],
  (history) => history.filter(isReadable),
)

export const selectViewedSummary = createSelector(
  [selectHistory, selectCurrentInventoryId],
  (history, id) =>
    id ? (history.find((item) => item.id === id) ?? null) : null,
)

/** Se está viendo el inventario de otro equipo de la carpeta de datos. */
export const selectViewingOtherDevice = (state: RootState) => {
  const key = state.session.status?.currentDevice?.deviceKey
  const current = state.inventory.current
  return Boolean(current && key && current.collection.deviceKey !== key)
}
