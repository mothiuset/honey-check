import { createSlice, type PayloadAction } from '@reduxjs/toolkit'
import type { Comparison, DeviceVersion } from '@/application'
import type { ComparisonFilter, ComparisonSliceState } from './comparison.types'

const initialState: ComparisonSliceState = {
  base: null,
  target: null,
  result: null,
  loading: false,
  filter: 'differences',
}

const comparisonSlice = createSlice({
  name: 'comparison',
  initialState,
  reducers: {
    basePicked(state, action: PayloadAction<DeviceVersion | null>) {
      return { ...state, base: action.payload }
    },
    targetPicked(state, action: PayloadAction<DeviceVersion | null>) {
      return { ...state, target: action.payload }
    },
    filtered(state, action: PayloadAction<ComparisonFilter>) {
      state.filter = action.payload
    },
    started(state) {
      state.loading = true
    },
    finished(state, action: PayloadAction<Comparison | null>) {
      return { ...state, loading: false, result: action.payload }
    },
  },
})

export const comparisonActions = comparisonSlice.actions
export const comparisonReducer = comparisonSlice.reducer
