import type { ThunkDispatch, UnknownAction } from '@reduxjs/toolkit'
import type { AppUseCases } from '@/application'
import type { ActionsSliceState } from './actions/actions.types'
import type { ComparisonSliceState } from './comparison/comparison.types'
import type { ConfirmationSliceState } from './confirmation/confirmation.types'
import type { DevicesSliceState } from './devices/devices.types'
import type { InventorySliceState } from './inventory/inventory.types'
import type { SessionSliceState } from './session/session.types'
import type { SupportSliceState } from './support/support.types'

// Se declara explícito (no inferido de los reductores) para que los thunks puedan leerlo sin ciclos.
export interface RootState {
  readonly session: SessionSliceState
  readonly inventory: InventorySliceState
  readonly devices: DevicesSliceState
  readonly comparison: ComparisonSliceState
  readonly confirmation: ConfirmationSliceState
  readonly support: SupportSliceState
  readonly actions: ActionsSliceState
}

export interface ThunkExtra {
  readonly useCases: AppUseCases
}

export type AppDispatch = ThunkDispatch<RootState, ThunkExtra, UnknownAction>
