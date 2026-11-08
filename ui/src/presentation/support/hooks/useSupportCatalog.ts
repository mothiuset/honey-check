import { useEffect, useMemo } from 'react'
import type { ToolDefinition } from '@/application'
import {
  loadSupportCatalog,
  selectSupportCatalog,
  selectSupportCatalogFailed,
  useAppDispatch,
  useAppSelector,
} from '@/presentation/store'

export interface ToolGroup {
  readonly category: string
  readonly tools: readonly ToolDefinition[]
}

// Orden de las categorías: lo que más se usa en soporte primero.
const ORDER = [
  'Espacio en disco',
  'Limpieza',
  'Programas',
  'Impresoras',
  'Controladores',
  'Periféricos',
  'Red',
  'Dominio y directivas',
  'Certificados',
  'Servicios y procesos',
  'Sistema',
  'Registro',
  'Credenciales',
  'Procesos de instalación',
]

const rank = (category: string) => {
  const index = ORDER.indexOf(category)
  return index < 0 ? ORDER.length : index
}

/** El catálogo, cargado una vez, y las herramientas visibles agrupadas por categoría. */
export function useSupportCatalog() {
  const dispatch = useAppDispatch()
  const catalog = useAppSelector(selectSupportCatalog)
  const failed = useAppSelector(selectSupportCatalogFailed)

  useEffect(() => {
    if (!catalog) void dispatch(loadSupportCatalog())
  }, [catalog, dispatch])

  const groups = useMemo(() => {
    const byCategory = new Map<string, ToolDefinition[]>()
    for (const tool of catalog ?? []) {
      if (tool.hidden) continue
      byCategory.set(tool.category, [
        ...(byCategory.get(tool.category) ?? []),
        tool,
      ])
    }
    return [...byCategory.entries()]
      .sort(([a], [b]) => rank(a) - rank(b) || a.localeCompare(b))
      .map(([category, tools]): ToolGroup => ({ category, tools }))
  }, [catalog])

  return {
    loading: !catalog && !failed,
    failed,
    groups,
    retry: () => void dispatch(loadSupportCatalog()),
  }
}
