// Enlaces que sirve el servicio local (descargas e iconos). Son thunks síncronos: el adaptador que
// sabe construirlos llega con los casos de uso.

import type { ThunkAction, UnknownAction } from '@reduxjs/toolkit'
import type { RootState, ThunkExtra } from '../store.types'

type LinkThunk = ThunkAction<string, RootState, ThunkExtra, UnknownAction>

export const iconUrlOf =
  (inventoryId: string, iconId: string): LinkThunk =>
  (_dispatch, _getState, { useCases }) =>
    useCases.inventories.iconUrl(inventoryId, iconId)

export const downloadUrlOf =
  (inventoryId: string): LinkThunk =>
  (_dispatch, _getState, { useCases }) =>
    useCases.inventories.downloadUrl(inventoryId)

export const pendingDownloadUrl =
  (): LinkThunk =>
  (_dispatch, _getState, { useCases }) =>
    useCases.inventories.pendingDownloadUrl()
