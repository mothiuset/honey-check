// La barra de uso crece hasta su porcentaje; sin animación si el sistema pide reducir movimiento.

import { gsap } from 'gsap'

export function fillUsageBar(fill: HTMLElement, percent: number): () => void {
  const width = `${percent.toFixed(1)}%`
  const media = gsap.matchMedia()
  media.add('(prefers-reduced-motion: no-preference)', () => {
    gsap.fromTo(
      fill,
      { width: '0%' },
      { width, duration: 0.8, ease: 'power2.out' },
    )
  })
  media.add('(prefers-reduced-motion: reduce)', () => {
    gsap.set(fill, { width })
  })
  return () => {
    media.revert()
    gsap.set(fill, { width })
  }
}
