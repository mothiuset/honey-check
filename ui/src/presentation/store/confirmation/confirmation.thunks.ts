// La respuesta del técnico llega por una promesa: su resolución vive fuera del estado de Redux, que
// solo guarda la pregunta visible.

import { createAppThunk } from '../createAppThunk'
import type { ConfirmationRequest } from './confirmation.types'
import { confirmationActions } from './confirmationSlice'

let pending: ((accepted: boolean) => void) | null = null

export const askConfirmation = createAppThunk(
  'confirmation/ask',
  (request: ConfirmationRequest, { dispatch }) => {
    pending?.(false)
    dispatch(confirmationActions.asked(request))
    return new Promise<boolean>((resolve) => {
      pending = resolve
    })
  },
)

export const answerConfirmation = createAppThunk(
  'confirmation/answer',
  (accepted: boolean, { dispatch }) => {
    pending?.(accepted)
    pending = null
    dispatch(confirmationActions.closed())
  },
)
