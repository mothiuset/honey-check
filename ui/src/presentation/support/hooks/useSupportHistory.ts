import { useEffect } from 'react'
import {
  cancelRun,
  closeTool,
  loadSupportHistory,
  openRun,
  selectSupportHistory,
  selectSupportRun,
  useAppDispatch,
  useAppSelector,
} from '@/presentation/store'
import { useRoute } from '@/presentation/shared/navigation'

/** Lo que se ejecutó (en HoneyCheck-datos\acciones) y, si la ruta lo pide, una ejecución abierta. */
export function useSupportHistory() {
  const dispatch = useAppDispatch()
  const route = useRoute()
  const runId = route.params.get('run')
  const history = useAppSelector(selectSupportHistory)
  const run = useAppSelector(selectSupportRun)

  useEffect(() => {
    void dispatch(loadSupportHistory())
  }, [dispatch, route.visit])

  useEffect(() => {
    if (runId) void dispatch(openRun(runId))
    return () => {
      void dispatch(closeTool())
    }
  }, [dispatch, runId])

  return {
    history,
    runId,
    run: run && run.id === runId ? run : null,
    cancel: (id: string) => void dispatch(cancelRun(id)),
  }
}
