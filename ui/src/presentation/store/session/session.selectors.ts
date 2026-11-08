import { isScanActive } from '@/application'
import type { RootState } from '../store.types'

export const selectSession = (state: RootState) => state.session
export const selectStatus = (state: RootState) => state.session.status
export const selectScan = (state: RootState) =>
  state.session.status?.scan ?? null
export const selectIsScanning = (state: RootState) =>
  isScanActive(state.session.status?.scan)
export const selectCurrentDeviceKey = (state: RootState) =>
  state.session.status?.currentDevice?.deviceKey ?? null
export const selectReferenceId = (state: RootState) =>
  state.session.status?.referenceId ?? null
export const selectWorkspace = (state: RootState) =>
  state.session.status?.workspace ?? null
export const selectIsElevated = (state: RootState) =>
  state.session.status?.isElevated === true
