import { Suspense } from 'react'
import { Lede } from '@/presentation/shared/components'
import { useCurrentModule } from '../../hooks/useCurrentModule'
import { useRevealSection } from '../../hooks/useRevealSection'

export const MAIN_ID = 'main'

/** La página de la ruta, cargada bajo demanda, y el desplazamiento al apartado pedido. */
export function CurrentPage() {
  const { route, module } = useCurrentModule()
  useRevealSection(route, MAIN_ID)
  const Page = module?.page
  if (!Page) return null
  return (
    <Suspense fallback={<Lede live>Cargando.</Lede>}>
      <Page />
    </Suspense>
  )
}
