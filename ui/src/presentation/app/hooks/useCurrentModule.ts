import { useRoute } from '@/presentation/shared/navigation'
import { MODULES, moduleById } from '../routing/modules'

/** El módulo de la ruta actual; una ruta desconocida lleva al panel. */
export function useCurrentModule() {
  const route = useRoute()
  return { route, module: moduleById(route.view) ?? MODULES[0] }
}
