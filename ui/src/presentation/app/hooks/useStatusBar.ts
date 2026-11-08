import {
  selectCurrentInventory,
  selectScan,
  selectSession,
  selectViewedSummary,
  selectViewingOtherDevice,
  useAppSelector,
} from '@/presentation/store'

/** Datos de la barra de estado: este equipo, lo que se ve, la tarea en curso y la carpeta. */
export function useStatusBar() {
  const { status, message } = useAppSelector(selectSession)
  const inventory = useAppSelector(selectCurrentInventory)
  const viewingOther = useAppSelector(selectViewingOtherDevice)
  const summary = useAppSelector(selectViewedSummary)
  const scan = useAppSelector(selectScan)

  const sequence = inventory?.collection.sequence
  const task =
    scan?.state === 'running'
      ? `Analizando ${String(scan.completed)} de ${String(scan.total)}`
      : scan?.state === 'cancelling'
        ? 'Cancelando el análisis'
        : message

  return {
    thisDevice: status?.currentDevice?.hostname ?? 'Identificando este equipo',
    viewing: viewingOther
      ? (inventory?.device?.hostname.value ?? 'otro equipo')
      : null,
    version: sequence ? `v${String(sequence)}` : null,
    task,
    folder: summary?.directory ?? status?.workspace.directory ?? null,
  }
}
