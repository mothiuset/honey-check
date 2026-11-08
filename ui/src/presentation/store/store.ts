import { configureStore } from '@reduxjs/toolkit'
import type { AppUseCases } from '@/application'
import { actionsReducer } from './actions/actionsSlice'
import { comparisonReducer } from './comparison/comparisonSlice'
import { confirmationReducer } from './confirmation/confirmationSlice'
import { devicesReducer } from './devices/devicesSlice'
import { inventoryReducer } from './inventory/inventorySlice'
import { sessionReducer } from './session/sessionSlice'
import { supportReducer } from './support/supportSlice'
import type { ThunkExtra } from './store.types'

export function buildStore(useCases: AppUseCases) {
  const extraArgument: ThunkExtra = { useCases }
  return configureStore({
    reducer: {
      session: sessionReducer,
      inventory: inventoryReducer,
      devices: devicesReducer,
      comparison: comparisonReducer,
      confirmation: confirmationReducer,
      support: supportReducer,
      actions: actionsReducer,
    },
    middleware: (getDefaultMiddleware) =>
      getDefaultMiddleware({
        thunk: { extraArgument },
        // Un inventario trae miles de programas: revisar su forma en cada acción no aporta nada.
        immutableCheck: false,
        serializableCheck: false,
      }),
  })
}

export type AppStore = ReturnType<typeof buildStore>
