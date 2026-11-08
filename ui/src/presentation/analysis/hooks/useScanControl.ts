import {
  cancelScan,
  selectIsScanning,
  selectScan,
  startScan,
  useAppDispatch,
  useAppSelector,
} from '@/presentation/store'

/** Iniciar o cancelar el análisis de este equipo y seguir su avance. */
export function useScanControl() {
  const dispatch = useAppDispatch()
  const scan = useAppSelector(selectScan)
  return {
    scan,
    scanning: useAppSelector(selectIsScanning),
    cancelling: scan?.state === 'cancelling',
    start: () => void dispatch(startScan()),
    cancel: () => void dispatch(cancelScan()),
  }
}
