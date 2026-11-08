import { createSlice, type PayloadAction } from '@reduxjs/toolkit'
import type { CurrentDeviceView, Inventory } from '@/application'
import type { InventorySliceState } from './inventory.types'

const initialState: InventorySliceState = {
  current: null,
  currentId: null,
  history: [],
  deviceTotal: 0,
}

const inventorySlice = createSlice({
  name: 'inventory',
  initialState,
  reducers: {
    currentDeviceShown(_state, action: PayloadAction<CurrentDeviceView>) {
      return action.payload
    },
    historyReceived(
      state,
      action: PayloadAction<Pick<CurrentDeviceView, 'history' | 'deviceTotal'>>,
    ) {
      return { ...state, ...action.payload }
    },
    inventoryOpened(
      state,
      action: PayloadAction<{ id: string; inventory: Inventory }>,
    ) {
      return {
        ...state,
        current: action.payload.inventory,
        currentId: action.payload.id,
      }
    },
  },
})

export const inventoryActions = inventorySlice.actions
export const inventoryReducer = inventorySlice.reducer
