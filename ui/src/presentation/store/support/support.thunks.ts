// Ejecutar una herramienta: preparar su revisión, iniciarla desde el panel que la muestra y seguir
// su avance hasta que termine. Solo se sigue una ejecución a la vez: abrir otra detiene el seguimiento
// de la anterior (que sigue corriendo en el servicio y queda en el historial).

import type { ParamValue } from '@/application'
import { isRunFinished } from '@/application'
import { askConfirmation } from '../confirmation/confirmation.thunks'
import { createAppThunk } from '../createAppThunk'
import { supportActions } from './supportSlice'

const POLL_MS = 700
let watching = 0

const pause = (ms: number) =>
  new Promise<void>((resolve) => {
    window.setTimeout(resolve, ms)
  })

export const loadSupportCatalog = createAppThunk(
  'support/catalog',
  async (_: undefined, { dispatch, extra }) => {
    try {
      dispatch(
        supportActions.catalogReceived(await extra.useCases.support.catalog()),
      )
    } catch {
      dispatch(supportActions.catalogFailed())
    }
  },
)

/** Las opciones se leen de nuevo cada vez: una USB conectada recién debe aparecer. */
export const loadSource = createAppThunk(
  'support/source',
  async (name: string, { dispatch, extra }) => {
    try {
      const choices = await extra.useCases.support.source(name)
      dispatch(supportActions.sourceReceived({ name, choices }))
    } catch {
      dispatch(supportActions.sourceReceived({ name, choices: 'failed' }))
    }
  },
)

export const preparePlan = createAppThunk(
  'support/plan',
  async (
    {
      tool,
      params,
    }: { tool: string; params: Readonly<Record<string, ParamValue>> },
    { dispatch, extra },
  ) => {
    dispatch(supportActions.preparing())
    const result = await extra.useCases.support.plan(tool, params)
    if (result.ok) dispatch(supportActions.planReceived(result.value))
    else
      dispatch(
        supportActions.noticeShown({
          reason: result.reason,
          detail: result.detail,
        }),
      )
  },
)

const watchRun = createAppThunk(
  'support/watch',
  async (runId: string, { dispatch, extra }) => {
    watching += 1
    const token = watching
    for (;;) {
      await pause(POLL_MS)
      if (token !== watching) return
      try {
        const run = await extra.useCases.support.run(runId)
        if (token !== watching) return
        dispatch(supportActions.runShown(run))
        if (isRunFinished(run)) break
      } catch {
        // Un fallo puntual de red local no detiene el seguimiento; el siguiente intento sigue.
      }
    }
    await dispatch(loadSupportHistory())
    const finished = await extra.useCases.support.run(runId)
    await dispatch(loadToolVersions(finished.tool))
  },
)

export const startPlan = createAppThunk(
  'support/start',
  async (_: undefined, { dispatch, getState, extra }) => {
    const plan = getState().support.plan
    if (!plan) return
    // El panel de revisión es la confirmación: dice qué pasará y su botón lleva el nombre de la
    // acción. Un segundo diálogo solo agregaría un clic sin información nueva.
    const result = await extra.useCases.support.start(
      plan,
      plan.risk !== 'read',
    )
    if (!result.ok) {
      dispatch(
        supportActions.noticeShown({
          reason: result.reason,
          detail: result.detail,
        }),
      )
      return
    }
    dispatch(supportActions.planReceived(plan))
    dispatch(supportActions.runShown(result.value))
    void dispatch(watchRun(result.value.id))
  },
)

export const openRun = createAppThunk(
  'support/openRun',
  async (runId: string, { dispatch, extra }) => {
    const run = await extra.useCases.support.run(runId)
    dispatch(supportActions.runShown(run))
    if (!isRunFinished(run)) void dispatch(watchRun(run.id))
  },
)

export const cancelRun = createAppThunk(
  'support/cancel',
  async (runId: string, { extra }) => {
    await extra.useCases.support.cancel(runId)
  },
)

export const closeTool = createAppThunk(
  'support/close',
  (_: undefined, { dispatch }) => {
    watching += 1
    dispatch(supportActions.toolClosed())
  },
)

export const loadToolVersions = createAppThunk(
  'support/versions',
  async (tool: string, { dispatch, extra }) => {
    try {
      const runs = await extra.useCases.support.versions(tool)
      dispatch(supportActions.toolVersionsReceived({ tool, runs }))
    } catch {
      // Sin versiones a la vista: la herramienta igual se puede usar.
    }
  },
)

/**
 * Al abrir una herramienta: lo que sigue en curso o, en una consulta, la última versión. Volver a
 * una herramienta no obliga a repetir un análisis largo.
 */
export const showLatestVersion = createAppThunk(
  'support/latest',
  async (
    { tool, isRead }: { tool: string; isRead: boolean },
    { dispatch, getState },
  ) => {
    await dispatch(loadToolVersions(tool))
    const state = getState().support
    if (state.run || state.plan || state.preparing) return
    const latest = state.toolVersions[tool]?.[0]
    if (latest && (latest.status === 'running' || isRead))
      await dispatch(openRun(latest.id))
  },
)

/** La versión anterior completa (misma herramienta y mismos datos), para comparar. */
export const loadPrevious = createAppThunk(
  'support/previous',
  async (runId: string | null, { dispatch, extra }) => {
    if (!runId) {
      dispatch(supportActions.previousShown(null))
      return
    }
    try {
      dispatch(
        supportActions.previousShown(await extra.useCases.support.run(runId)),
      )
    } catch {
      dispatch(supportActions.previousShown(null))
    }
  },
)

/** Pregunta si el equipo cambió desde el resultado a la vista; si cambió, lo marca atrasado. */
export const checkChanged = createAppThunk(
  'support/changed',
  async (runId: string, { dispatch, getState, extra }) => {
    try {
      const changed = await extra.useCases.support.changed(runId)
      if (changed && getState().support.run?.id === runId)
        dispatch(supportActions.changedAfterResult())
    } catch {
      // Sin respuesta no se avisa: el siguiente intento vuelve a preguntar.
    }
  },
)

/** Abre el diálogo de Windows para elegir una ruta; devuelve la elegida o null. */
export const pickPath = createAppThunk(
  'support/pickPath',
  async (
    {
      kind,
      title,
      filter,
    }: { kind: 'folder' | 'file'; title: string; filter: string | null },
    { extra },
  ) => {
    try {
      return await extra.useCases.support.pickPath(kind, title, filter)
    } catch {
      return null
    }
  },
)

export const loadSupportHistory = createAppThunk(
  'support/history',
  async (_: undefined, { dispatch, extra }) => {
    dispatch(
      supportActions.historyReceived(await extra.useCases.support.history()),
    )
  },
)

// --- Procesos de instalación ------------------------------------------------------------------

export const loadProcedures = createAppThunk(
  'support/procedures',
  async (_: undefined, { dispatch, extra }) => {
    const [procedures, runs] = await Promise.all([
      extra.useCases.support.procedures(),
      extra.useCases.support.procedureRuns(),
    ])
    dispatch(supportActions.proceduresReceived(procedures))
    dispatch(supportActions.procedureRunsReceived(runs))
  },
)

export const loadProcedureVersions = createAppThunk(
  'support/procedureVersions',
  async (slug: string, { dispatch, extra }) => {
    dispatch(
      supportActions.versionsReceived({
        slug,
        versions: await extra.useCases.support.procedureVersions(slug),
      }),
    )
  },
)

/** Guarda el texto JSON como versión nueva; devuelve si quedó guardado. */
export const saveProcedure = createAppThunk(
  'support/saveProcedure',
  async (text: string, { dispatch, extra }) => {
    let document: unknown
    try {
      document = JSON.parse(text)
    } catch {
      dispatch(
        supportActions.procedureMessageShown(
          'El texto no es JSON válido: revise comas, comillas y llaves.',
        ),
      )
      return false
    }
    const result = await extra.useCases.support.saveProcedure(document)
    if (!result.ok) {
      dispatch(
        supportActions.procedureMessageShown(
          `No se guardó: ${result.detail ?? 'datos no válidos'}.`,
        ),
      )
      return false
    }
    dispatch(
      supportActions.procedureMessageShown(
        `Guardado «${result.value.name}» como versión ${String(result.value.version)}.`,
      ),
    )
    await Promise.all([
      dispatch(loadProcedures()),
      dispatch(loadProcedureVersions(result.value.slug)),
    ])
    return true
  },
)

export const removeProcedure = createAppThunk(
  'support/removeProcedure',
  async (
    { slug, name }: { slug: string; name: string },
    { dispatch, extra },
  ) => {
    const confirmed = await dispatch(
      askConfirmation({
        title: `Eliminar «${name}»`,
        message:
          'Todas sus versiones van a la papelera de HoneyCheck-datos. Si era una copia de una plantilla, vuelve a verse la plantilla original.',
        confirmLabel: 'Eliminar',
        danger: true,
      }),
    ).unwrap()
    if (!confirmed) return
    const removed = await extra.useCases.support.removeProcedure(slug)
    dispatch(
      supportActions.procedureMessageShown(
        `${String(removed)} ${removed === 1 ? 'versión movida' : 'versiones movidas'} a la papelera.`,
      ),
    )
    await dispatch(loadProcedures())
  },
)
