import { useEffect, useRef, useState } from 'react'
import {
  isReadable,
  type DeviceSummary,
  type DeviceVersion,
} from '@/application'
import { formatDate } from '@/presentation/shared/formatters'
import {
  loadVersions,
  searchDevices,
  selectReferenceId,
  selectVersionsOf,
  useAppDispatch,
  useAppSelector,
} from '@/presentation/store'

const SEARCH_DELAY_MS = 250

/** Selector de equipo y versión con búsqueda en el servidor: sirve igual con miles de equipos. */
export function useDevicePicker(
  value: DeviceVersion | null,
  onChange: (value: DeviceVersion | null) => void,
) {
  const dispatch = useAppDispatch()
  const [text, setText] = useState('')
  const [results, setResults] = useState<readonly DeviceSummary[]>([])
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const deviceKey = value?.device.deviceKey ?? ''
  const versions = useAppSelector(selectVersionsOf(deviceKey))
  const referenceId = useAppSelector(selectReferenceId)

  useEffect(() => {
    if (deviceKey && !versions) void dispatch(loadVersions(deviceKey))
  }, [dispatch, deviceKey, versions])

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current)
    },
    [],
  )

  function search(next: string): void {
    setText(next)
    if (timer.current) clearTimeout(timer.current)
    if (!next.trim()) {
      setResults([])
      return
    }
    timer.current = setTimeout(() => {
      void dispatch(searchDevices(next.trim()))
        .unwrap()
        .then((page) => {
          setResults(page.items)
        })
    }, SEARCH_DELAY_MS)
  }

  // Al elegir un equipo se preselecciona su último análisis legible; la lista de versiones llega aparte.
  function choose(device: DeviceSummary): void {
    setText('')
    setResults([])
    onChange(
      device.lastInventoryId
        ? { device, inventoryId: device.lastInventoryId }
        : null,
    )
  }

  const options = (versions ?? []).filter(isReadable).map((version) => ({
    id: version.id,
    label: `v${String(version.sequence ?? '?')} del ${version.collectedAt ? formatDate(version.collectedAt) : 'fecha sin dato'}${version.id === referenceId ? ' (referencia)' : ''}`,
  }))

  return {
    text,
    results,
    options,
    search,
    choose,
    pickVersion: (inventoryId: string) => {
      if (value) onChange({ device: value.device, inventoryId })
    },
    clear: () => {
      onChange(null)
    },
  }
}
