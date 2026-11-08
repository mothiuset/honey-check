// Ejecutar donde está el técnico, sin cambiar de página. Lo inmediato (abrir una carpeta, vaciar la
// caché DNS) corre con el clic y un aviso dice cómo terminó. Un cambio abre su revisión en un panel
// sobre la pantalla actual; su botón es la confirmación y el resultado queda en el mismo panel.

import { isRunFinished, type Run } from '@/application'
import { createAppThunk } from '../createAppThunk'
import type { AppDispatch, ThunkExtra } from '../store.types'
import { supportActions } from '../support/supportSlice'
import { loadSupportHistory } from '../support/support.thunks'
import { actionsActions } from './actionsSlice'
import type { ActionRequest } from './actions.types'

const POLL_MS = 500
let nextToast = 0
let panelToken = 0

const pause = (ms: number) =>
  new Promise<void>((resolve) => {
    window.setTimeout(resolve, ms)
  })

/** Sigue una ejecución hasta que termine, avisando cada cambio. */
async function follow(
  first: Run,
  extra: ThunkExtra,
  onUpdate: (run: Run) => void,
  stillWanted: () => boolean = () => true,
): Promise<Run | null> {
  let run = first
  while (!isRunFinished(run)) {
    await pause(POLL_MS)
    if (!stillWanted()) return null
    try {
      run = await extra.useCases.support.run(run.id)
      onUpdate(run)
    } catch {
      // Un fallo puntual de red local no detiene el seguimiento.
    }
  }
  return run
}

/** Un cambio terminado deja atrás el resultado que la pantalla muestra: se avisa para actualizar. */
function markChanged(run: Run | null, dispatch: AppDispatch): void {
  if (run && run.risk !== 'read' && run.status !== 'cancelled')
    dispatch(supportActions.changedAfterResult())
}

function followAsToast(
  run: Run,
  label: string,
  dispatch: AppDispatch,
  extra: ThunkExtra,
): Promise<void> {
  nextToast += 1
  const id = nextToast
  dispatch(actionsActions.toastAdded({ id, label, run, notice: null }))
  return follow(run, extra, (next) =>
    dispatch(actionsActions.toastUpdated({ id, run: next })),
  ).then(async (last) => {
    markChanged(last, dispatch)
    await dispatch(loadSupportHistory())
  })
}

export const runInstant = createAppThunk(
  'actions/instant',
  async (request: ActionRequest, { dispatch, extra }) => {
    nextToast += 1
    const id = nextToast
    dispatch(
      actionsActions.toastAdded({
        id,
        label: request.label,
        run: null,
        notice: null,
      }),
    )
    const plan = await extra.useCases.support.plan(request.tool, request.params)
    if (!plan.ok) {
      dispatch(
        actionsActions.toastUpdated({
          id,
          notice: { reason: plan.reason, detail: plan.detail },
        }),
      )
      return
    }
    // El clic es la confirmación: una acción inmediata no tiene nada que revisar.
    const started = await extra.useCases.support.start(plan.value, true)
    if (!started.ok) {
      dispatch(
        actionsActions.toastUpdated({
          id,
          notice: { reason: started.reason, detail: started.detail },
        }),
      )
      return
    }
    dispatch(actionsActions.toastUpdated({ id, run: started.value }))
    const last = await follow(started.value, extra, (run) =>
      dispatch(actionsActions.toastUpdated({ id, run })),
    )
    markChanged(last, dispatch)
    await dispatch(loadSupportHistory())
  },
)

export const openActionPanel = createAppThunk(
  'actions/open',
  async (request: ActionRequest, { dispatch, extra }) => {
    panelToken += 1
    const token = panelToken
    dispatch(
      actionsActions.panelOpened({ tool: request.tool, title: request.label }),
    )
    const plan = await extra.useCases.support.plan(request.tool, request.params)
    if (token !== panelToken) return
    dispatch(
      plan.ok
        ? actionsActions.panelPlanned(plan.value)
        : actionsActions.panelRefused({
            reason: plan.reason,
            detail: plan.detail,
          }),
    )
  },
)

export const startPanelAction = createAppThunk(
  'actions/start',
  async (_: undefined, { dispatch, getState, extra }) => {
    const plan = getState().actions.panel?.plan
    if (!plan) return
    const token = panelToken
    const started = await extra.useCases.support.start(
      plan,
      plan.risk !== 'read',
    )
    if (token !== panelToken) return
    if (!started.ok) {
      dispatch(
        actionsActions.panelRefused({
          reason: started.reason,
          detail: started.detail,
        }),
      )
      return
    }
    dispatch(actionsActions.panelRun(started.value))
    const last = await follow(
      started.value,
      extra,
      (run) => dispatch(actionsActions.panelRun(run)),
      () => token === panelToken,
    )
    markChanged(last, dispatch)
    await dispatch(loadSupportHistory())
  },
)

/** Cerrar el panel no detiene lo que corre: sigue como aviso hasta que termine. */
export const closeActionPanel = createAppThunk(
  'actions/close',
  (_: undefined, { dispatch, getState, extra }) => {
    const panel = getState().actions.panel
    panelToken += 1
    dispatch(actionsActions.panelClosed())
    if (panel?.run && !isRunFinished(panel.run))
      void followAsToast(panel.run, panel.title, dispatch, extra)
  },
)

export const cancelAction = createAppThunk(
  'actions/cancel',
  async (runId: string, { extra }) => {
    await extra.useCases.support.cancel(runId)
  },
)
