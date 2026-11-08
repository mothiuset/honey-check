import type { ReactNode } from 'react'
import { Button, LinkButton } from '@/presentation/shared/components'
import type { ButtonTone } from '@/presentation/shared/components'
import { toolHref } from '../../formatters/supportRoutes'
import { useToolAction } from '../../hooks/useToolAction'

interface ActionButtonProps {
  readonly tool: string
  /** Datos ya completos de la acción (los `{campo}` llenados con la fila). */
  readonly params: Readonly<Record<string, string>>
  readonly children: ReactNode
  readonly tone?: ButtonTone
  readonly size?: 'small'
}

/**
 * El botón de una acción de Soporte desde cualquier vista. Lo inmediato corre con el clic, un
 * cambio abre su revisión en un panel sobre la pantalla actual y solo una consulta con resultado
 * propio (o a la que le faltan datos) lleva a su pantalla, donde empieza sola.
 */
export function ActionButton({
  tool,
  params,
  children,
  tone,
  size,
}: ActionButtonProps) {
  const action = useToolAction(tool, params)
  if (action.mode === 'page')
    return (
      <LinkButton
        size={size}
        tone={tone}
        href={toolHref(tool, params, true)}
        data-action={tool}
      >
        {children}
      </LinkButton>
    )
  return (
    <Button
      size={size}
      tone={tone}
      onClick={action.run}
      data-action={tool}
      data-mode={action.mode}
    >
      {children}
    </Button>
  )
}
