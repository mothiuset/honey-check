import { useLayoutEffect, useMemo, useRef } from 'react'
import { navigate } from '@/presentation/shared/navigation'
import {
  animateReadingCells,
  pulseCell,
} from '../components/HoneyComb/HoneyComb.gsap'
import { honeyCombCells } from '../formatters/honeyCombCells'

/** Celdas del panal y sus animaciones; cada celda lleva a su apartado. */
export function useHoneyComb(statuses: Readonly<Record<string, string>>) {
  const svg = useRef<SVGSVGElement | null>(null)
  const previous = useRef<Readonly<Record<string, string>>>({})
  const cells = useMemo(() => honeyCombCells(statuses), [statuses])
  const signature = cells.map((cell) => cell.status).join()

  useLayoutEffect(() => {
    const root = svg.current
    if (!root) return
    for (const cell of cells) {
      const before = previous.current[cell.name]
      if (cell.status === 'ok' && before && before !== 'ok') {
        const element = root.querySelector(`[data-cell="${cell.name}"]`)
        if (element) pulseCell(element)
      }
    }
    previous.current = statuses
    return animateReadingCells(root)
    // La firma resume los estados: solo se reanima cuando alguno cambia.
  }, [signature])

  return { svg, cells, open: navigate }
}
