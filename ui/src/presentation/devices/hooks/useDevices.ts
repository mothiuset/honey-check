import { useEffect, useRef, useState } from 'react'
import {
  devicesActions,
  loadDevices,
  selectDeviceNotice,
  selectDevicePage,
  selectDeviceQuery,
  selectDevicesLoading,
  selectHasDeviceFilters,
  useAppDispatch,
  useAppSelector,
  type DeviceFilterKey,
} from '@/presentation/store'

const SEARCH_DELAY_MS = 250

/** Lista paginada de equipos con búsqueda, filtros y orden resueltos en el servidor. */
export function useDevices() {
  const dispatch = useAppDispatch()
  const query = useAppSelector(selectDeviceQuery)
  const [text, setText] = useState(query.q)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    void dispatch(loadDevices())
  }, [dispatch, query])

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current)
    },
    [],
  )

  function search(value: string): void {
    setText(value)
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(
      () => dispatch(devicesActions.searched(value)),
      SEARCH_DELAY_MS,
    )
  }

  return {
    text,
    query,
    page: useAppSelector(selectDevicePage),
    loading: useAppSelector(selectDevicesLoading),
    notice: useAppSelector(selectDeviceNotice),
    hasFilters: useAppSelector(selectHasDeviceFilters),
    search,
    filter: (key: DeviceFilterKey, value: string) =>
      dispatch(devicesActions.filtered({ key, value })),
    sort: (key: string) => dispatch(devicesActions.sorted(key)),
    goToPage: (page: number) => dispatch(devicesActions.paged(page)),
    setPageSize: (size: number) => dispatch(devicesActions.pageSized(size)),
  }
}
