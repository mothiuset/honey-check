import { useLayoutEffect, useRef } from 'react'
import { fillUsageBar } from '../components/UsageBar/UsageBar.gsap'

/** Ancho de la barra según el uso, aplicado por la animación (no por estilos en el marcado). */
export function useUsageBar(percent: number) {
  const fill = useRef<HTMLSpanElement | null>(null)
  useLayoutEffect(
    () => (fill.current ? fillUsageBar(fill.current, percent) : undefined),
    [percent],
  )
  return fill
}
