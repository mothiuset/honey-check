import {
  actionsActions,
  cancelAction,
  closeActionPanel,
  selectActionPanel,
  selectActionToasts,
  startPanelAction,
  useAppDispatch,
  useAppSelector,
} from '@/presentation/store'
import { useElevation } from '@/presentation/shared/hooks/useElevation'

export type { ActionToast } from '@/presentation/store'

/** El panel de una acción en curso y los avisos de las inmediatas, sobre cualquier pantalla. */
export function useActionLayer() {
  const dispatch = useAppDispatch()
  const elevation = useElevation()
  return {
    panel: useAppSelector(selectActionPanel),
    toasts: useAppSelector(selectActionToasts),
    isElevated: elevation.isElevated,
    start: () => void dispatch(startPanelAction()),
    close: () => void dispatch(closeActionPanel()),
    cancel: (runId: string) => void dispatch(cancelAction(runId)),
    dismiss: (id: number) => dispatch(actionsActions.toastDismissed(id)),
  }
}
