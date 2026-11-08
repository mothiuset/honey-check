import { createSlice, type PayloadAction } from '@reduxjs/toolkit'
import type {
  ConfirmationRequest,
  ConfirmationSliceState,
} from './confirmation.types'

const initialState: ConfirmationSliceState = { request: null }

const confirmationSlice = createSlice({
  name: 'confirmation',
  initialState,
  reducers: {
    asked(state, action: PayloadAction<ConfirmationRequest>) {
      state.request = action.payload
    },
    closed(state) {
      state.request = null
    },
  },
})

export const confirmationActions = confirmationSlice.actions
export const confirmationReducer = confirmationSlice.reducer
