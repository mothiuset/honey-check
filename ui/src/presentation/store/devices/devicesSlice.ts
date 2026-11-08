import { createSlice, type PayloadAction } from '@reduxjs/toolkit'
import type { DevicePage, InventorySummary } from '@/application'
import type {
  DeviceFilterKey,
  DeviceQuery,
  DevicesSliceState,
} from './devices.types'

// Por defecto, primero lo analizado más recientemente; por nombre o modelo, de la A a la Z.
const DESCENDING_FIRST = new Set(['last', 'versions'])

const initialState: DevicesSliceState = {
  query: {
    q: '',
    manufacturer: '',
    type: '',
    os: '',
    status: '',
    sort: 'last',
    order: 'desc',
    page: 1,
    size: 25,
  },
  page: null,
  loading: false,
  versions: {},
  notice: null,
}

const devicesSlice = createSlice({
  name: 'devices',
  initialState,
  reducers: {
    searched(state, action: PayloadAction<string>) {
      state.query = { ...state.query, q: action.payload, page: 1 }
    },
    filtered(
      state,
      action: PayloadAction<{ key: DeviceFilterKey; value: string }>,
    ) {
      state.query = {
        ...state.query,
        [action.payload.key]: action.payload.value,
        page: 1,
      }
    },
    sorted(state, action: PayloadAction<string>) {
      const key = action.payload
      const order: DeviceQuery['order'] =
        state.query.sort === key
          ? state.query.order === 'asc'
            ? 'desc'
            : 'asc'
          : DESCENDING_FIRST.has(key)
            ? 'desc'
            : 'asc'
      state.query = { ...state.query, sort: key, order, page: 1 }
    },
    paged(state, action: PayloadAction<number>) {
      state.query = { ...state.query, page: action.payload }
    },
    pageSized(state, action: PayloadAction<number>) {
      state.query = { ...state.query, size: action.payload, page: 1 }
    },
    loading(state) {
      state.loading = true
    },
    pageReceived(state, action: PayloadAction<DevicePage>) {
      return { ...state, page: action.payload, loading: false }
    },
    versionsReceived(
      state,
      action: PayloadAction<{
        deviceKey: string
        versions: readonly InventorySummary[]
      }>,
    ) {
      return {
        ...state,
        versions: {
          ...state.versions,
          [action.payload.deviceKey]: action.payload.versions,
        },
      }
    },
    versionsForgotten(state, action: PayloadAction<string>) {
      const versions = Object.fromEntries(
        Object.entries(state.versions).filter(
          ([key]) => key !== action.payload,
        ),
      )
      return { ...state, versions }
    },
    noticeShown(state, action: PayloadAction<string | null>) {
      state.notice = action.payload
    },
  },
})

export const devicesActions = devicesSlice.actions
export const devicesReducer = devicesSlice.reducer
