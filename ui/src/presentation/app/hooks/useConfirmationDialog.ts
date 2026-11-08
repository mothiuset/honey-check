import { useEffect, useRef } from 'react'
import {
  answerConfirmation,
  selectConfirmationRequest,
  useAppDispatch,
  useAppSelector,
} from '@/presentation/store'

/** Abre el diálogo modal nativo cuando hay una pregunta y lo cierra al responderla. */
export function useConfirmationDialog() {
  const dispatch = useAppDispatch()
  const request = useAppSelector(selectConfirmationRequest)
  const dialog = useRef<HTMLDialogElement | null>(null)

  useEffect(() => {
    const element = dialog.current
    if (!element) return
    if (request && !element.open) element.showModal()
    if (!request && element.open) element.close()
  }, [request])

  return {
    dialog,
    request,
    answer: (accepted: boolean) => void dispatch(answerConfirmation(accepted)),
  }
}
