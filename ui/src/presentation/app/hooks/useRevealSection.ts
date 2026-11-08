import { useEffect } from 'react'
import type { Route } from '@/presentation/shared/navigation'

const WAIT_MS = 3000

/**
 * Tras cada navegación lleva el apartado (o el contenido) a la vista y le da el foco, para que el
 * lector de pantalla anuncie dónde se llegó. Espera a que la página diferida termine de pintarse.
 */
export function useRevealSection(route: Route, mainId: string): void {
  useEffect(() => {
    let frame = 0
    const deadline = performance.now() + WAIT_MS
    const reveal = () => {
      const target = document.getElementById(route.section || mainId)
      if (!target || (route.section && !target.isConnected)) {
        if (performance.now() < deadline) frame = requestAnimationFrame(reveal)
        return
      }
      target.focus({ preventScroll: true })
      if (route.section) target.scrollIntoView({ block: 'start' })
      else window.scrollTo({ top: 0 })
    }
    frame = requestAnimationFrame(reveal)
    return () => {
      cancelAnimationFrame(frame)
    }
  }, [route.view, route.section, route.visit, mainId])
}
