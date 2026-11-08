import type { RootState } from '../store.types'

export const selectConfirmationRequest = (state: RootState) =>
  state.confirmation.request
