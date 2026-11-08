// Animaciones del panal: el brillo de las celdas que se están leyendo y el pulso de las que terminan.
// Solo corren si el sistema no pide reducir el movimiento.

import { gsap } from 'gsap'

const MOTION = '(prefers-reduced-motion: no-preference)'

/** Brillo continuo en las celdas en lectura. Devuelve cómo deshacerlo. */
export function animateReadingCells(root: SVGSVGElement): () => void {
  const media = gsap.matchMedia()
  media.add(MOTION, () => {
    gsap.to(
      root.querySelectorAll('[data-status="running"] [data-part="glow"]'),
      {
        opacity: 0.8,
        duration: 0.9,
        repeat: -1,
        yoyo: true,
        ease: 'sine.inOut',
      },
    )
  })
  return () => {
    media.revert()
  }
}

/** Pulso breve de una celda que acaba de completarse. */
export function pulseCell(cell: Element): void {
  gsap.matchMedia().add(MOTION, () => {
    gsap.fromTo(
      cell,
      { scale: 0.9, transformOrigin: '50% 50%' },
      { scale: 1, duration: 0.4, ease: 'back.out(2.2)' },
    )
  })
}
