import { createAppThunk } from '../createAppThunk'
import { pollStatus } from '../session/session.thunks'
import { selectCurrentDeviceKey } from '../session/session.selectors'
import type { ExportFeedback } from './inventory.types'
import { inventoryActions } from './inventorySlice'

/** Muestra el último análisis de ESTE equipo; los de otros equipos de la USB no pasan por propios. */
export const openCurrentDevice = createAppThunk(
  'inventory/openCurrentDevice',
  async (_: undefined, { dispatch, getState, extra }) => {
    const state = getState()
    const view = await extra.useCases.inventories.currentDeviceView(
      selectCurrentDeviceKey(state),
      state.session.status?.exportFailure != null,
    )
    dispatch(inventoryActions.currentDeviceShown(view))
  },
)

export const refreshHistory = createAppThunk(
  'inventory/refreshHistory',
  async (_: undefined, { dispatch, getState, extra }) => {
    dispatch(
      inventoryActions.historyReceived(
        await extra.useCases.inventories.history(
          selectCurrentDeviceKey(getState()),
        ),
      ),
    )
  },
)

export const openInventory = createAppThunk(
  'inventory/open',
  async (id: string, { dispatch, extra }) => {
    dispatch(
      inventoryActions.inventoryOpened({
        id,
        inventory: await extra.useCases.inventories.open(id),
      }),
    )
  },
)

/** Mueve la versión a la papelera de la carpeta de datos. */
export const deleteInventory = createAppThunk(
  'inventory/delete',
  async (id: string, { dispatch, getState, extra }) => {
    await extra.useCases.inventories.remove(id)
    await dispatch(
      getState().inventory.currentId === id
        ? openCurrentDevice()
        : refreshHistory(),
    )
    await dispatch(pollStatus())
  },
)

export const setReference = createAppThunk(
  'inventory/setReference',
  async (id: string, { dispatch, extra }) => {
    await extra.useCases.inventories.setReference(id)
    await dispatch(pollStatus())
  },
)

export const exportPending = createAppThunk(
  'inventory/exportPending',
  async (directory: string, { dispatch, extra }): Promise<ExportFeedback> => {
    const result = await extra.useCases.inventories.exportPending(directory)
    if (result.ok) {
      await dispatch(pollStatus())
      await dispatch(openCurrentDevice())
    }
    return result
  },
)
