import { formatDate } from '@/presentation/shared/formatters'
import {
  openCurrentDevice,
  selectCurrentInventory,
  selectViewingOtherDevice,
  selectWorkspace,
  useAppDispatch,
  useAppSelector,
} from '@/presentation/store'

/** Avisos de la parte superior: la carpeta de datos no está disponible o se ve otro equipo. */
export function useWorkspaceBanners() {
  const dispatch = useAppDispatch()
  const workspace = useAppSelector(selectWorkspace)
  const viewingOther = useAppSelector(selectViewingOtherDevice)
  const inventory = useAppSelector(selectCurrentInventory)

  const otherDevice =
    viewingOther && inventory
      ? {
          name: inventory.device?.hostname.value ?? 'otro equipo',
          date: formatDate(inventory.collection.startedAt),
        }
      : null

  return {
    unavailable: workspace !== null && !workspace.available,
    readOnly: workspace !== null && workspace.available && !workspace.writable,
    otherDevice,
    backToThisDevice: () => void dispatch(openCurrentDevice()),
  }
}
