import { useEffect, useRef, useState } from 'react'
import { useRoute } from '@/presentation/shared/navigation'

/**
 * Menú desplegable de la barra compacta: se cierra al navegar, con Escape o con un clic fuera.
 * El clic se mide con la ruta del evento, válida aunque el elemento cambie durante el clic.
 */
export function useMenu() {
  const [open, setOpen] = useState(false)
  const container = useRef<HTMLElement | null>(null)
  const route = useRoute()

  useEffect(() => {
    setOpen(false)
  }, [route.view, route.section, route.visit])

  useEffect(() => {
    if (!open) return
    const outside = (event: MouseEvent) => {
      if (
        container.current &&
        !event.composedPath().includes(container.current)
      )
        setOpen(false)
    }
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('click', outside)
    document.addEventListener('keydown', escape)
    return () => {
      document.removeEventListener('click', outside)
      document.removeEventListener('keydown', escape)
    }
  }, [open])

  return {
    open,
    container,
    toggle: () => {
      setOpen((value) => !value)
    },
    close: () => {
      setOpen(false)
    },
  }
}
