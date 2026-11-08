import type { DeviceSummary, InventorySummary } from '@/application'
import { createAppThunk } from '../createAppThunk'
import { deleteInventory } from '../inventory/inventory.thunks'
import { devicesActions } from './devicesSlice'

export const loadDevices = createAppThunk(
  'devices/load',
  async (_: undefined, { dispatch, getState, extra }) => {
    dispatch(devicesActions.loading())
    dispatch(
      devicesActions.pageReceived(
        await extra.useCases.devices.search(getState().devices.query),
      ),
    )
  },
)

export const loadVersions = createAppThunk(
  'devices/loadVersions',
  async (deviceKey: string, { dispatch, extra }) => {
    dispatch(
      devicesActions.versionsReceived({
        deviceKey,
        versions: await extra.useCases.devices.versions(deviceKey),
      }),
    )
  },
)

export const removeVersion = createAppThunk(
  'devices/removeVersion',
  async (
    { device, version }: { device: DeviceSummary; version: InventorySummary },
    { dispatch },
  ) => {
    await dispatch(deleteInventory(version.id)).unwrap()
    dispatch(
      devicesActions.noticeShown(
        `Versión ${String(version.sequence ?? '?')} movida a la papelera.`,
      ),
    )
    await Promise.all([
      dispatch(loadVersions(device.deviceKey)),
      dispatch(loadDevices()),
    ])
  },
)

export const removeDevice = createAppThunk(
  'devices/removeDevice',
  async (device: DeviceSummary, { dispatch, extra }) => {
    const deleted = await extra.useCases.devices.remove(device.deviceKey)
    dispatch(
      devicesActions.noticeShown(
        `${String(deleted)} ${deleted === 1 ? 'versión movida' : 'versiones movidas'} a la papelera.`,
      ),
    )
    dispatch(devicesActions.versionsForgotten(device.deviceKey))
    await dispatch(loadDevices())
  },
)

/** Búsqueda puntual (selectores de equipo): devuelve la página sin reemplazar la de la lista. */
export const searchDevices = createAppThunk(
  'devices/search',
  (text: string, { extra }) =>
    extra.useCases.devices.search({ q: text, size: 8 }),
)
