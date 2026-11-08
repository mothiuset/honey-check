import { createSlice, type PayloadAction } from '@reduxjs/toolkit'
import type {
  ParamChoice,
  Plan,
  Procedure,
  ProcedureRun,
  Run,
  ToolDefinition,
} from '@/application'
import type { SupportNotice, SupportSliceState } from './support.types'

const initialState: SupportSliceState = {
  catalog: null,
  catalogFailed: false,
  plan: null,
  preparing: false,
  notice: null,
  run: null,
  history: null,
  procedures: null,
  procedureRuns: null,
  versions: {},
  procedureMessage: null,
  sources: {},
  toolVersions: {},
  previous: null,
  stale: false,
}

const supportSlice = createSlice({
  name: 'support',
  initialState,
  reducers: {
    catalogReceived(state, action: PayloadAction<readonly ToolDefinition[]>) {
      return { ...state, catalog: action.payload, catalogFailed: false }
    },
    catalogFailed(state) {
      state.catalogFailed = true
    },
    preparing(state) {
      return { ...state, preparing: true, plan: null, notice: null }
    },
    planReceived(state, action: PayloadAction<Plan>) {
      return { ...state, plan: action.payload, preparing: false }
    },
    noticeShown(state, action: PayloadAction<SupportNotice | null>) {
      return { ...state, notice: action.payload, preparing: false }
    },
    toolClosed(state) {
      return { ...state, plan: null, notice: null, run: null, previous: null }
    },
    toolVersionsReceived(
      state,
      action: PayloadAction<{ tool: string; runs: readonly Run[] }>,
    ) {
      return {
        ...state,
        toolVersions: {
          ...state.toolVersions,
          [action.payload.tool]: action.payload.runs,
        },
      }
    },
    changedAfterResult(state) {
      return state.run ? { ...state, stale: true } : state
    },
    previousShown(state, action: PayloadAction<Run | null>) {
      return { ...state, previous: action.payload }
    },
    runShown(state, action: PayloadAction<Run | null>) {
      // Otra ejecución a la vista (o la misma actualizada desde el servicio) ya no está atrasada.
      const other = action.payload?.id !== state.run?.id
      return {
        ...state,
        run: action.payload,
        stale: other ? false : state.stale,
      }
    },
    historyReceived(state, action: PayloadAction<readonly Run[]>) {
      return { ...state, history: action.payload }
    },
    proceduresReceived(state, action: PayloadAction<readonly Procedure[]>) {
      return { ...state, procedures: action.payload }
    },
    procedureRunsReceived(
      state,
      action: PayloadAction<readonly ProcedureRun[]>,
    ) {
      return { ...state, procedureRuns: action.payload }
    },
    versionsReceived(
      state,
      action: PayloadAction<{
        slug: string
        versions: readonly Procedure[]
      }>,
    ) {
      return {
        ...state,
        versions: {
          ...state.versions,
          [action.payload.slug]: action.payload.versions,
        },
      }
    },
    sourceReceived(
      state,
      action: PayloadAction<{
        name: string
        choices: readonly ParamChoice[] | 'failed'
      }>,
    ) {
      return {
        ...state,
        sources: {
          ...state.sources,
          [action.payload.name]: action.payload.choices,
        },
      }
    },
    procedureMessageShown(state, action: PayloadAction<string | null>) {
      state.procedureMessage = action.payload
    },
  },
})

export const supportActions = supportSlice.actions
export const supportReducer = supportSlice.reducer
