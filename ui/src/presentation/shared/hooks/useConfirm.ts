import {
  askConfirmation,
  useAppDispatch,
  type ConfirmationRequest,
} from '@/presentation/store'

/** Pregunta con el diálogo propio de Honey Check (nunca `confirm()` del navegador). */
export function useConfirm() {
  const dispatch = useAppDispatch()
  return (request: ConfirmationRequest): Promise<boolean> =>
    dispatch(askConfirmation(request)).unwrap()
}
