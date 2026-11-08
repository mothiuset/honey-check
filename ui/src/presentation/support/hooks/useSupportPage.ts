import { selectToolById, useAppSelector } from '@/presentation/store'
import { useRoute } from '@/presentation/shared/navigation'
import { toolParamsOf } from '../formatters/supportRoutes'
import { useSupportCatalog } from './useSupportCatalog'

/** La herramienta pedida en la ruta (si hay) o el catálogo completo. */
export function useSupportPage() {
  const route = useRoute()
  const catalog = useSupportCatalog()
  const toolId = route.params.get('tool') ?? ''
  const tool = useAppSelector(selectToolById(toolId))
  return {
    catalog,
    toolId,
    tool,
    given: toolParamsOf(route.params),
    auto: route.params.get('auto') === '1',
    // Cada visita a una herramienta (también repetir el mismo enlace) empieza un formulario nuevo.
    runnerKey: `${route.params.toString()}#${String(route.visit)}`,
  }
}
