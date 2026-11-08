import { useEffect } from 'react'
import {
  selectSession,
  startSession,
  useAppDispatch,
  useAppSelector,
} from '@/presentation/store'

/** Abre la sesión con el servicio local y expone si ya está lista o terminó. */
export function useAppStartup() {
  const dispatch = useAppDispatch()
  const { ready, stopped, appVersion } = useAppSelector(selectSession)

  useEffect(() => {
    void dispatch(startSession())
  }, [dispatch])

  return { ready, stopped, appVersion }
}
