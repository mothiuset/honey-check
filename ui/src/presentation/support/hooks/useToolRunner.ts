import { useEffect, useRef, useState } from 'react'
import {
  initialValues,
  missingRequired,
  requestParams,
  type ParamValue,
  type Run,
  type ToolDefinition,
} from '@/application'
import {
  cancelRun,
  checkChanged,
  closeTool,
  loadPrevious,
  openRun,
  preparePlan,
  selectPreviousRun,
  selectSupportNotice,
  selectSupportPlan,
  selectSupportPreparing,
  selectSupportRun,
  selectSupportStale,
  selectToolVersions,
  showLatestVersion,
  startPlan,
  useAppDispatch,
  useAppSelector,
} from '@/presentation/store'
import { useElevation } from '@/presentation/shared/hooks/useElevation'

const CHANGE_POLL_MS = 8000

const sameParams = (a: Run, b: Run) =>
  JSON.stringify(a.params) === JSON.stringify(b.params)

/**
 * Una herramienta abierta: su formulario, la revisión que preparó el servicio, la ejecución en
 * curso y su resultado. Al volver a una herramienta se ve lo que sigue en curso o la última
 * versión de una consulta, con las demás versiones y lo que cambió respecto de la anterior.
 */
export function useToolRunner(
  tool: ToolDefinition,
  given: Readonly<Record<string, string>>,
  auto: boolean,
) {
  const dispatch = useAppDispatch()
  const [values, setValues] = useState<Record<string, ParamValue>>(() =>
    initialValues(tool, given),
  )
  const plan = useAppSelector(selectSupportPlan)
  const current = useAppSelector(selectSupportRun)
  const notice = useAppSelector(selectSupportNotice)
  const preparing = useAppSelector(selectSupportPreparing)
  const versions = useAppSelector(selectToolVersions(tool.id)) ?? []
  const previousRun = useAppSelector(selectPreviousRun)
  const stale = useAppSelector(selectSupportStale)
  const elevation = useElevation()
  const started = useRef(false)
  const planMatches = plan?.tool === tool.id
  const run = current?.tool === tool.id ? current : null

  const missing = missingRequired(tool, values)
  const isRead = tool.risk === 'read'
  // Una herramienta que solo se abre desde un enlace no vuelve a pedir lo que el enlace trajo.
  const fixed = new Set(tool.hidden ? Object.keys(given) : [])

  async function prepareAndMaybeRun(
    runNow: boolean,
    params: Readonly<Record<string, ParamValue>> = values,
  ): Promise<void> {
    await dispatch(
      preparePlan({ tool: tool.id, params: requestParams(params) }),
    )
    if (runNow) await dispatch(startPlan())
  }

  useEffect(() => {
    void dispatch(closeTool())
    // Desde un enlace con los datos completos: una consulta se ejecuta y un cambio queda revisado,
    // listo para confirmarlo con un clic. Si no, se muestra lo último que hay.
    if (auto && !missing.length && !started.current) {
      started.current = true
      void prepareAndMaybeRun(isRead)
    } else {
      void dispatch(showLatestVersion({ tool: tool.id, isRead }))
    }
    return () => {
      void dispatch(closeTool())
    }
    // Solo al abrir la herramienta: cada ruta monta un componente nuevo.
  }, [])

  // La versión anterior con los mismos datos, para mostrar qué cambió.
  const previousId =
    run && run.status !== 'running'
      ? (versions.find(
          (version) =>
            version.id !== run.id &&
            version.status !== 'running' &&
            version.startedAt < run.startedAt &&
            sameParams(version, run),
        )?.id ?? null)
      : null
  useEffect(() => {
    void dispatch(loadPrevious(previousId))
  }, [previousId])

  // Mientras se ve el resultado de una consulta, se pregunta si el equipo cambió (un programa
  // desinstalado, espacio liberado), también desde fuera de Honey Check. Al volver a la ventana se
  // pregunta enseguida.
  const watched =
    run && isRead && run.status !== 'running' && run.fingerprint ? run.id : null
  useEffect(() => {
    if (!watched || stale) return
    const ask = () => void dispatch(checkChanged(watched))
    const timer = window.setInterval(ask, CHANGE_POLL_MS)
    const onVisible = () => {
      if (document.visibilityState === 'visible') ask()
    }
    document.addEventListener('visibilitychange', onVisible)
    window.addEventListener('focus', ask)
    return () => {
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', onVisible)
      window.removeEventListener('focus', ask)
    }
  }, [watched, stale])

  // El formulario muestra los datos de la versión a la vista (para actualizarla igual).
  useEffect(() => {
    if (!run || !isRead) return
    setValues((now) => {
      const next = { ...now }
      for (const param of tool.params)
        if (param.kind !== 'secret' && param.name in run.params)
          next[param.name] = run.params[param.name] ?? null
      return next
    })
  }, [run?.id])

  return {
    values,
    setValue: (name: string, value: ParamValue) => {
      const next = { ...values, [name]: value }
      setValues(next)
      // Con la revisión a la vista, cambiar una opción la vuelve a hacer: siempre muestra lo que
      // pasará con los datos actuales.
      if (planMatches && !isRead && !missingRequired(tool, next).length) {
        void prepareAndMaybeRun(false, next)
      }
    },
    fixed,
    missing,
    plan: planMatches ? plan : null,
    run,
    versions,
    stale,
    previous: previousRun && previousRun.id === previousId ? previousRun : null,
    notice,
    preparing,
    isElevated: elevation.isElevated,
    requestElevation: elevation.requestElevation,
    // Una consulta se prepara y ejecuta en un paso; un cambio muestra primero su revisión.
    submit: () => void prepareAndMaybeRun(isRead),
    refresh: () => void prepareAndMaybeRun(true),
    openVersion: (runId: string) => void dispatch(openRun(runId)),
    start: () => void dispatch(startPlan()),
    cancel: (runId: string) => void dispatch(cancelRun(runId)),
    reset: () => void dispatch(closeTool()),
  }
}
