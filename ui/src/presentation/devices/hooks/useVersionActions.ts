import type { DeviceSummary, InventorySummary } from '@/application'
import { useConfirm } from '@/presentation/shared/hooks/useConfirm'
import { useLinks } from '@/presentation/shared/hooks/useLinks'
import { hrefOf, navigate } from '@/presentation/shared/navigation'
import {
  loadVersions,
  openInventory,
  removeDevice,
  removeVersion,
  selectReferenceId,
  setReference,
  useAppDispatch,
  useAppSelector,
} from '@/presentation/store'
import {
  deviceRemovalQuestion,
  versionRemovalQuestion,
} from '../formatters/removalQuestions'

/** Acciones sobre las versiones de un equipo: ver, comparar, descargar, referencia y papelera. */
export function useVersionActions() {
  const dispatch = useAppDispatch()
  const confirm = useConfirm()
  const links = useLinks()

  return {
    referenceId: useAppSelector(selectReferenceId),
    downloadUrl: links.download,
    reload: (device: DeviceSummary) =>
      void dispatch(loadVersions(device.deviceKey)),
    async open(version: InventorySummary) {
      await dispatch(openInventory(version.id))
      navigate(hrefOf('panel'))
    },
    compare: (version: InventorySummary) => {
      navigate(hrefOf('comparar', '', { target: version.id }))
    },
    useAsReference: (version: InventorySummary) =>
      void dispatch(setReference(version.id)),
    async removeVersion(device: DeviceSummary, version: InventorySummary) {
      if (await confirm(versionRemovalQuestion(device, version)))
        await dispatch(removeVersion({ device, version }))
    },
    async removeDevice(device: DeviceSummary) {
      if (await confirm(deviceRemovalQuestion(device)))
        await dispatch(removeDevice(device))
    },
  }
}
