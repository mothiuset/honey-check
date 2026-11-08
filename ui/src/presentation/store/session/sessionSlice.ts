import { createSlice, type PayloadAction } from '@reduxjs/toolkit'
import type { AppStatus } from '@/application'
import type { SessionSliceState } from './session.types'

const initialState: SessionSliceState = {
  ready: false,
  stopped: null,
  appVersion: '',
  status: null,
  message: null,
}

const sessionSlice = createSlice({
  name: 'session',
  initialState,
  reducers: {
    started(
      state,
      action: PayloadAction<{ appVersion: string; status: AppStatus }>,
    ) {
      return { ...state, ...action.payload }
    },
    ready(state) {
      state.ready = true
    },
    statusReceived(state, action: PayloadAction<AppStatus>) {
      return { ...state, status: action.payload }
    },
    messageShown(state, action: PayloadAction<string | null>) {
      state.message = action.payload
    },
    stopped(state, action: PayloadAction<string>) {
      state.stopped = action.payload
    },
  },
})

export const sessionActions = sessionSlice.actions
export const sessionReducer = sessionSlice.reducer
