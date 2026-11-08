import { Button } from '@/presentation/shared/components'
import { useConfirmationDialog } from '../../hooks/useConfirmationDialog'
import styles from './ConfirmDialog.module.css'

/** Confirmación propia (no `confirm()` del navegador): explica qué pasará y permite cancelar. */
export function ConfirmDialog() {
  const { dialog, request, answer } = useConfirmationDialog()
  return (
    <dialog
      ref={dialog}
      className={styles.dialog}
      aria-labelledby="confirm-title"
      onCancel={(event) => {
        event.preventDefault()
        answer(false)
      }}
    >
      {request ? (
        <>
          <h2 id="confirm-title" className={styles.title}>
            {request.title}
          </h2>
          <p>{request.message}</p>
          <div className={styles.buttons}>
            <Button
              onClick={() => {
                answer(false)
              }}
            >
              Cancelar
            </Button>
            <Button
              tone={request.danger ? 'danger' : 'default'}
              autoFocus
              onClick={() => {
                answer(true)
              }}
            >
              {request.confirmLabel}
            </Button>
          </div>
        </>
      ) : null}
    </dialog>
  )
}
