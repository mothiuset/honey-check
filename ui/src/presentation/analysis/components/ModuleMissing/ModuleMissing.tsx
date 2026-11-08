import { Notice } from '@/presentation/shared/components'
import { useModuleReport } from '../../hooks/useModuleReport'

/** Aviso cuando un módulo no dejó datos: dice cómo terminó y por qué. */
export function ModuleMissing({
  module,
  label,
}: {
  module: string
  label: string
}) {
  const { statusText, errors } = useModuleReport(module)
  return (
    <Notice tone="bad">
      <p>
        No hay datos de {label}: el módulo terminó como «{statusText}».
      </p>
      {errors.map((error) => (
        <p key={error.code + error.message}>{error.message}</p>
      ))}
    </Notice>
  )
}
