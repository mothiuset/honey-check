import type { RootState } from '../store.types'

export const selectActionToasts = (state: RootState) => state.actions.toasts
export const selectActionPanel = (state: RootState) => state.actions.panel
