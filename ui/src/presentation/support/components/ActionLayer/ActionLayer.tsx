import { useEffect, useRef } from 'react'
import { Button, LinkButton } from '@/presentation/shared/components'
import { REFUSALS } from '../../formatters/supportText'
import { runHref } from '../../formatters/supportRoutes'
import { useActionLayer, type ActionToast } from '../../hooks/useActionLayer'
import { CheckList } from '../CheckList/CheckList'
import { ConfirmPanel } from '../ConfirmPanel/ConfirmPanel'
import { Readout } from '../Readout/Readout'
import { RunView } from '../RunView/RunView'
import { StatusGlyph } from '../StatusGlyph/StatusGlyph'
import { outcomeOf, Verdict } from '../Verdict/Verdict'
import styles from './ActionLayer.module.css'

const OK_TOAST_MS = 4000

function Toast({
  toast,
  onDismiss,
}: {
  toast: ActionToast
  onDismiss: (id: number) => void
}) {
  // Una consulta inmediata (abrir una carpeta) no tiene verificaciones: si terminó bien, su primera
  // cifra dice qué hizo.
  const fact = toast.run?.result?.summary[0]
  const outcome = toast.run
    ? (outcomeOf(toast.run) ??
      (toast.run.status === 'succeeded'
        ? {
            status: 'ok' as const,
            text: fact ? `${fact.label}: ${fact.value ?? ''}` : 'Hecho.',
          }
        : null))
    : null
  const running =
    !toast.notice && (!toast.run || toast.run.status === 'running')
  const status = toast.notice ? 'fail' : (outcome?.status ?? 'info')
  const text = toast.notice
    ? [REFUSALS[toast.notice.reason], toast.notice.detail]
        .filter(Boolean)
        .join(' ')
    : running
      ? 'En curso…'
      : (outcome?.text ?? null)

  // Lo que salió bien se va solo; lo que falló queda hasta que el técnico lo cierre.
  useEffect(() => {
    if (running || status !== 'ok') return
    const timer = window.setTimeout(() => {
      onDismiss(toast.id)
    }, OK_TOAST_MS)
    return () => {
      window.clearTimeout(timer)
    }
  }, [running, status, toast.id, onDismiss])

  return (
    <li className={styles.toast} data-status={running ? 'running' : status}>
      {running ? (
        <span className={styles.spinner} aria-hidden="true" />
      ) : (
        <StatusGlyph status={status} />
      )}
      <div className={styles.toastText}>
        <strong>{toast.label}</strong>
        {text ? <span>{text}</span> : null}
        {!running && status !== 'ok' && toast.run ? (
          <a href={runHref(toast.run.id)}>Ver el detalle</a>
        ) : null}
      </div>
      <button
        type="button"
        className={styles.dismiss}
        aria-label="Cerrar el aviso"
        onClick={() => {
          onDismiss(toast.id)
        }}
      >
        ×
      </button>
    </li>
  )
}

/**
 * Lo que se ejecuta sin salir de la pantalla: un panel lateral con la revisión, el avance y el
 * resultado de un cambio, y avisos breves para lo inmediato. Cerrar el panel no detiene nada.
 */
export function ActionLayer() {
  const layer = useActionLayer()
  const { panel } = layer
  const heading = useRef<HTMLHeadingElement>(null)
  const { close } = layer

  useEffect(() => {
    if (panel) heading.current?.focus()
  }, [panel?.tool, panel?.title])

  useEffect(() => {
    if (!panel) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') close()
    }
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('keydown', onKey)
    }
  }, [panel, close])

  const run = panel?.run ?? null
  const finished = run !== null && run.status !== 'running'
  return (
    <>
      {panel ? (
        <aside
          className={styles.panel}
          aria-labelledby="action-panel-title"
          data-testid="action-panel"
        >
          <header className={styles.head}>
            <h2 id="action-panel-title" ref={heading} tabIndex={-1}>
              {panel.title}
            </h2>
            <Button size="small" tone="ghost" onClick={close}>
              Cerrar
            </Button>
          </header>
          {panel.preparing ? <p className={styles.muted}>Revisando…</p> : null}
          {panel.notice ? (
            <p className={styles.notice}>
              <StatusGlyph status="fail" />
              <span>
                {REFUSALS[panel.notice.reason]}
                {panel.notice.detail ? ` ${panel.notice.detail}` : ''}
              </span>
            </p>
          ) : null}
          {panel.plan && !run ? (
            <ConfirmPanel
              plan={panel.plan}
              isElevated={layer.isElevated}
              onStart={layer.start}
              onEdit={null}
            />
          ) : null}
          {run && !finished ? (
            <RunView run={run} onCancel={layer.cancel} />
          ) : null}
          {run && finished ? <Verdict run={run} /> : null}
          {run?.result?.summary.length ? (
            <Readout facts={run.result.summary} />
          ) : null}
          {run?.result?.checks.length ? (
            <CheckList checks={run.result.checks} />
          ) : null}
          {/* Cuándo fue y el registro: al final, plegado salvo que algo haya fallado. */}
          {run && finished ? (
            <RunView run={run} onCancel={layer.cancel} />
          ) : null}
          {finished ? (
            <footer className={styles.foot}>
              <Button tone="primary" onClick={close}>
                Listo
              </Button>
              <LinkButton href={runHref(run.id)} onClick={close}>
                Ver el detalle
              </LinkButton>
            </footer>
          ) : null}
        </aside>
      ) : null}
      <ul
        className={styles.toasts}
        aria-live="polite"
        aria-label="Acciones en curso"
      >
        {layer.toasts.map((toast) => (
          <Toast key={toast.id} toast={toast} onDismiss={layer.dismiss} />
        ))}
      </ul>
    </>
  )
}
