import { MODULE_STATUS } from '@/presentation/shared/formatters'
import { useCurrentInventory } from '@/presentation/shared/hooks/useCurrentInventory'

/** Cómo terminó un módulo y qué errores dejó, para explicar por qué falta su sección. */
export function useModuleReport(module: string) {
  const { inventory } = useCurrentInventory()
  const report = inventory?.modules.find((item) => item.name === module)
  return {
    statusText: report
      ? (MODULE_STATUS[report.status] ?? report.status)
      : 'desconocido',
    errors: inventory?.errors.filter((issue) => issue.module === module) ?? [],
  }
}
