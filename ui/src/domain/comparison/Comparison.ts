// Comparación de dos inventarios: cada fila trae ambos valores y su estado, también las iguales,
// para poder filtrar por diferencias o por coincidencias.

export type ComparisonState =
  'same' | 'changed' | 'added' | 'removed' | 'unknown'

export interface ComparisonRow {
  readonly area: string
  // Campo del contrato; en software, el nombre del programa.
  readonly field: string
  readonly kind: 'text' | 'bytes' | 'bool' | 'date'
  readonly before: string | null
  readonly after: string | null
  readonly state: ComparisonState
}

export interface Comparison {
  readonly baseId: string
  readonly targetId: string
  readonly sameDevice: boolean | null
  readonly rows: readonly ComparisonRow[]
  readonly software: readonly ComparisonRow[]
  readonly notComparable: readonly string[]
}

/** «Sin dato» en ambas versiones no es una diferencia. */
export function isDifference(row: ComparisonRow): boolean {
  return row.state !== 'same' && row.state !== 'unknown'
}
