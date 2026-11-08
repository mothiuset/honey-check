import { useEffect } from 'react'
import {
  initialValues,
  missingRequired,
  requestParams,
  type ToolDefinition,
} from '@/application'
import {
  loadSupportCatalog,
  openActionPanel,
  runInstant,
  selectSupportCatalog,
  useAppDispatch,
  useAppSelector,
} from '@/presentation/store'

/**
 * Cómo se ejecuta una herramienta desde un botón:
 * - `instant`: con el clic, donde está el técnico, y un aviso dice cómo terminó (abrir una carpeta);
 * - `panel`: un cambio muestra su revisión en un panel sobre la pantalla actual;
 * - `page`: una consulta con resultado propio, o algo a lo que le faltan datos, abre su pantalla.
 */
export type ActionMode = 'instant' | 'panel' | 'page'

function modeOf(
  tool: ToolDefinition | null,
  given: Readonly<Record<string, string>>,
): ActionMode {
  if (!tool) return 'page'
  if (missingRequired(tool, initialValues(tool, given)).length) return 'page'
  if (tool.instant) return 'instant'
  return tool.risk === 'read' ? 'page' : 'panel'
}

export function useToolAction(
  toolId: string,
  given: Readonly<Record<string, string>>,
) {
  const dispatch = useAppDispatch()
  const catalog = useAppSelector(selectSupportCatalog)

  useEffect(() => {
    if (!catalog) void dispatch(loadSupportCatalog())
  }, [catalog, dispatch])

  const tool = catalog?.find((item) => item.id === toolId) ?? null
  const mode = modeOf(tool, given)
  return {
    mode,
    run: () => {
      if (!tool || mode === 'page') return
      const request = {
        tool: tool.id,
        label: tool.title,
        params: requestParams(initialValues(tool, given)),
      }
      void dispatch(
        mode === 'instant' ? runInstant(request) : openActionPanel(request),
      )
    },
  }
}
