// Textos de la comparación: nombre legible del dato y su valor según el tipo.

import type { ComparisonRow, ComparisonState } from '@/application'
import type { ComparisonFilter } from '../types/devices.types'
import {
  AREAS,
  COMPARE_FIELDS,
  DEVICE_TYPES,
  formatBool,
  formatBytes,
  formatDate,
} from '@/presentation/shared/formatters'

export const STATE_LABELS: Record<ComparisonState, string> = {
  same: 'Igual',
  changed: 'Cambió',
  added: 'Nuevo',
  removed: 'Retirado',
  unknown: 'Sin dato',
}

export const areaLabel = (area: string): string => AREAS[area] ?? area

export const fieldLabel = (row: ComparisonRow): string =>
  COMPARE_FIELDS[`${row.area}.${row.field}`] ?? row.field

function formatRaw(row: ComparisonRow, raw: string): string {
  if (row.kind === 'bytes') return formatBytes(Number(raw))
  if (row.kind === 'bool') return formatBool(raw === 'true')
  if (row.kind === 'date') return formatDate(raw)
  if (row.area === 'device' && row.field === 'device_type')
    return DEVICE_TYPES[raw] ?? raw
  return raw
}

/** Valor de un lado; lo que solo existe en el otro lado queda vacío, no «Sin dato». */
export function sideValue(
  row: ComparisonRow,
  side: 'before' | 'after',
): string {
  if (
    (side === 'before' && row.state === 'added') ||
    (side === 'after' && row.state === 'removed')
  )
    return ''
  const raw = row[side]
  return raw === null ? 'Sin dato' : formatRaw(row, raw)
}

/** Mensaje cuando ningún dato de equipo, hardware o sistema cumple el filtro. */
export function emptyFilterText(filter: ComparisonFilter): string {
  if (filter === 'differences')
    return 'El equipo, el hardware y el sistema coinciden en las dos versiones.'
  if (filter === 'same')
    return 'Ningún dato de equipo, hardware o sistema coincide entre las dos versiones.'
  return 'No hay datos que comparar.'
}
