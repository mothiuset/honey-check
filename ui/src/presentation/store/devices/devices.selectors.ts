import type { RootState } from '../store.types'

export const selectDeviceQuery = (state: RootState) => state.devices.query
export const selectDevicePage = (state: RootState) => state.devices.page
export const selectDevicesLoading = (state: RootState) => state.devices.loading
export const selectDeviceNotice = (state: RootState) => state.devices.notice
export const selectVersionsOf = (deviceKey: string) => (state: RootState) =>
  state.devices.versions[deviceKey]

export const selectHasDeviceFilters = (state: RootState) => {
  const { q, manufacturer, type, os, status } = state.devices.query
  return Boolean(q || manufacturer || type || os || status)
}
