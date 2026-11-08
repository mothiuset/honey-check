import { useEffect } from 'react'
import type { DeviceSummary } from '@/application'
import {
  loadVersions,
  selectVersionsOf,
  useAppDispatch,
  useAppSelector,
} from '@/presentation/store'

/** Versiones de un equipo, cargadas al desplegarlo. */
export function useDeviceVersions(device: DeviceSummary) {
  const dispatch = useAppDispatch()
  const versions = useAppSelector(selectVersionsOf(device.deviceKey))

  useEffect(() => {
    if (!versions) void dispatch(loadVersions(device.deviceKey))
  }, [dispatch, device.deviceKey, versions])

  return versions ?? null
}
