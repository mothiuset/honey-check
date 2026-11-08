import {
  downloadUrlOf,
  iconUrlOf,
  pendingDownloadUrl,
  useAppDispatch,
} from '@/presentation/store'

/** Enlaces de descarga e iconos del servicio local. */
export function useLinks() {
  const dispatch = useAppDispatch()
  return {
    download: (inventoryId: string) => dispatch(downloadUrlOf(inventoryId)),
    pendingDownload: () => dispatch(pendingDownloadUrl()),
    icon: (inventoryId: string, iconId: string) =>
      dispatch(iconUrlOf(inventoryId, iconId)),
  }
}
