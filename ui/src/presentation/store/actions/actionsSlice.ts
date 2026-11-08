import { createSlice, type PayloadAction } from '@reduxjs/toolkit'
import type { Plan, Run } from '@/application'
import type { SupportNotice } from '../support/support.types'
import type { ActionToast, ActionsSliceState } from './actions.types'

const initialState: ActionsSliceState = { toasts: [], panel: null }

const actionsSlice = createSlice({
  name: 'actions',
  initialState,
  reducers: {
    toastAdded(state, action: PayloadAction<ActionToast>) {
      return { ...state, toasts: [...state.toasts, action.payload] }
    },
    toastUpdated(
      state,
      action: PayloadAction<Pick<ActionToast, 'id'> & Partial<ActionToast>>,
    ) {
      return {
        ...state,
        toasts: state.toasts.map((toast) =>
          toast.id === action.payload.id
            ? { ...toast, ...action.payload }
            : toast,
        ),
      }
    },
    toastDismissed(state, action: PayloadAction<number>) {
      return {
        ...state,
        toasts: state.toasts.filter((toast) => toast.id !== action.payload),
      }
    },
    panelOpened(state, action: PayloadAction<{ tool: string; title: string }>) {
      return {
        ...state,
        panel: {
          ...action.payload,
          preparing: true,
          plan: null,
          run: null,
          notice: null,
        },
      }
    },
    panelPlanned(state, action: PayloadAction<Plan>) {
      if (!state.panel) return state
      return {
        ...state,
        panel: { ...state.panel, preparing: false, plan: action.payload },
      }
    },
    panelRefused(state, action: PayloadAction<SupportNotice>) {
      if (!state.panel) return state
      return {
        ...state,
        panel: { ...state.panel, preparing: false, notice: action.payload },
      }
    },
    panelRun(state, action: PayloadAction<Run>) {
      if (!state.panel) return state
      return { ...state, panel: { ...state.panel, run: action.payload } }
    },
    panelClosed(state) {
      return { ...state, panel: null }
    },
  },
})

export const actionsActions = actionsSlice.actions
export const actionsReducer = actionsSlice.reducer
