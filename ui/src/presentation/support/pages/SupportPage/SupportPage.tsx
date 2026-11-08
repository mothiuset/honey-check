import { Button, Lede, Notice } from '@/presentation/shared/components'
import { RouteLink } from '@/presentation/shared/navigation'
import { ToolCatalog } from '../../components/ToolCatalog/ToolCatalog'
import { ToolRunner } from '../../components/ToolRunner/ToolRunner'
import { HISTORY_VIEW, SUPPORT_VIEW } from '../../formatters/supportRoutes'
import { useSupportPage } from '../../hooks/useSupportPage'

export function SupportPage() {
  const page = useSupportPage()
  const { catalog } = page

  if (catalog.failed)
    return (
      <>
        <h1>Soporte</h1>
        <Notice tone="bad">
          <p>No se pudo leer el catálogo de herramientas.</p>
          <Button size="small" onClick={catalog.retry}>
            Reintentar
          </Button>
        </Notice>
      </>
    )
  if (catalog.loading) return <Lede live>Cargando las herramientas.</Lede>

  if (page.toolId) {
    if (!page.tool)
      return (
        <>
          <h1>Soporte</h1>
          <Notice tone="bad">
            <p>Esta herramienta no existe en esta versión de Honey Check.</p>
            <RouteLink href={`#${SUPPORT_VIEW}`}>Ver todas</RouteLink>
          </Notice>
        </>
      )
    return (
      <ToolRunner
        key={page.runnerKey}
        tool={page.tool}
        given={page.given}
        auto={page.auto}
      />
    )
  }

  return (
    <>
      <h1>Soporte</h1>
      <Lede>
        Cada herramienta muestra primero lo que hará y el comando equivalente.
        Los cambios piden confirmación, guardan un respaldo y se verifican al
        terminar. Todo queda en el{' '}
        <RouteLink href={`#${HISTORY_VIEW}`}>historial</RouteLink>.
      </Lede>
      <ToolCatalog groups={catalog.groups} />
    </>
  )
}
