import {
  elevate,
  selectIsElevated,
  useAppDispatch,
  useAppSelector,
} from '@/presentation/store'

/** Saber si la sesión tiene permisos de administrador y pedirlos con el aviso UAC. */
export function useElevation() {
  const dispatch = useAppDispatch()
  return {
    isElevated: useAppSelector(selectIsElevated),
    requestElevation: () => void dispatch(elevate()),
  }
}
