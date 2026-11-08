import { createAsyncThunk } from '@reduxjs/toolkit'
import type { AppDispatch, RootState, ThunkExtra } from './store.types'

/** Thunks con el estado, el dispatch y los casos de uso ya tipados. */
export const createAppThunk = createAsyncThunk.withTypes<{
  state: RootState
  dispatch: AppDispatch
  extra: ThunkExtra
}>()
