// Geometría del panal: 14 módulos en filas de 5, 4 y 5 celdas hexagonales.

import { MODULE_LABELS, MODULE_STATUS } from '@/presentation/shared/formatters'
import { hrefOf } from '@/presentation/shared/navigation'
import type { CombCell } from '../types/analysis.types'

const CELLS: readonly (readonly [string, string, string])[] = [
  ['identity', 'hardware', 'identificacion'],
  ['processor', 'hardware', 'procesador'],
  ['memory', 'hardware', 'memoria'],
  ['storage', 'almacenamiento', ''],
  ['operating_system', 'sistema', ''],
  ['graphics', 'hardware', 'graficos'],
  ['displays', 'hardware', 'pantallas'],
  ['network', 'hardware', 'red'],
  ['battery', 'hardware', 'bateria'],
  ['tpm', 'hardware', 'tpm'],
  ['devices', 'hardware', 'dispositivos'],
  ['peripherals', 'perifericos', ''],
  ['security', 'seguridad', ''],
  ['software', 'software', ''],
]
const ROWS = [5, 4, 5]
const RADIUS = 46
const GAP = 5
const WIDTH = Math.sqrt(3) * RADIUS
const ROW_HEIGHT = RADIUS * 1.5

export const COMB_WIDTH = 5 * (WIDTH + GAP) + GAP
export const COMB_HEIGHT = 2 * ROW_HEIGHT + 2 * RADIUS + GAP * 4

function hexagon(cx: number, cy: number): string {
  return Array.from({ length: 6 }, (_, i) => {
    const angle = (Math.PI / 3) * i + Math.PI / 6
    return `${(cx + RADIUS * Math.cos(angle)).toFixed(1)},${(cy + RADIUS * Math.sin(angle)).toFixed(1)}`
  }).join(' ')
}

export function honeyCombCells(
  statuses: Readonly<Record<string, string>>,
): readonly CombCell[] {
  const cells: CombCell[] = []
  let index = 0
  ROWS.forEach((count, row) => {
    const offset = (COMB_WIDTH - count * (WIDTH + GAP) + GAP) / 2
    const cy = RADIUS + GAP + row * (ROW_HEIGHT + GAP)
    for (let column = 0; column < count; column += 1) {
      const entry = CELLS[index]
      index += 1
      if (!entry) continue
      const [name, view, section] = entry
      const cx = offset + column * (WIDTH + GAP) + WIDTH / 2
      const status = statuses[name] ?? 'pending'
      cells.push({
        name,
        label: MODULE_LABELS[name] ?? name,
        href: hrefOf(view, section),
        status,
        statusText: MODULE_STATUS[status] ?? status,
        cx,
        cy,
        points: hexagon(cx, cy),
      })
    }
  })
  return cells
}
