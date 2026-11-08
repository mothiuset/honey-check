// Rutas del soporte: `#soporte?tool=<id>&<parámetro>=<valor>`. Un enlace desde cualquier vista (una
// impresora, un programa, una fila de resultado) abre la herramienta con sus datos ya escritos.

import { linkParams, type ActionLink, type ResultRow } from '@/application'
import { hrefOf } from '@/presentation/shared/navigation'

export const SUPPORT_VIEW = 'soporte'
export const HISTORY_VIEW = 'historial'
export const PROCEDURES_VIEW = 'procesos'

// Parámetros de la ruta que no son de la herramienta.
const ROUTE_KEYS = new Set(['tool', 'auto'])

/** `auto`: una consulta abierta desde un enlace se ejecuta sin pedir otro clic. */
export function toolHref(
  tool: string,
  params: Readonly<Record<string, string>> = {},
  auto = false,
): string {
  return hrefOf(SUPPORT_VIEW, '', {
    tool,
    ...params,
    ...(auto ? { auto: '1' } : {}),
  })
}

export function linkHref(
  link: ActionLink,
  row: ResultRow | null,
  selection?: { readonly param: string; readonly keys: readonly string[] },
): string {
  const params = linkParams(link, row)
  if (selection) params[selection.param] = selection.keys.join('\n')
  return toolHref(link.tool, params, true)
}

export function toolParamsOf(
  search: URLSearchParams,
): Readonly<Record<string, string>> {
  const params: Record<string, string> = {}
  for (const [key, value] of search.entries())
    if (!ROUTE_KEYS.has(key)) params[key] = value
  return params
}

export const runHref = (runId: string) =>
  hrefOf(HISTORY_VIEW, '', { run: runId })
