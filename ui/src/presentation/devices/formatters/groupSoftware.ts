import type { ComparisonRow } from '@/application'
import { fold } from '@/presentation/shared/formatters'

export interface SoftwareGroup {
  readonly key: string
  readonly label: string
  readonly rows: readonly ComparisonRow[]
}

const GROUPS: readonly (readonly [ComparisonRow['state'], string])[] = [
  ['added', 'Nuevos en la segunda versión'],
  ['removed', 'Ya no están'],
  ['changed', 'Cambiaron de versión'],
  ['same', 'Iguales'],
]

/** Programas de la comparación agrupados por estado, con búsqueda por nombre o versión. */
export function groupSoftware(
  rows: readonly ComparisonRow[],
  search: string,
): readonly SoftwareGroup[] {
  const words = fold(search).split(/\s+/).filter(Boolean)
  const matching = rows.filter((row) =>
    words.every((word) =>
      fold(`${row.field} ${row.before ?? ''} ${row.after ?? ''}`).includes(
        word,
      ),
    ),
  )
  return GROUPS.map(([state, label]) => ({
    key: state,
    label,
    rows: matching.filter((row) => row.state === state),
  })).filter((group) => group.rows.length > 0)
}

export function softwareSummary(rows: readonly ComparisonRow[]): string {
  const count = (state: ComparisonRow['state']) =>
    rows.filter((row) => row.state === state).length
  return `${String(count('added'))} nuevos, ${String(count('removed'))} retirados, ${String(count('changed'))} actualizados`
}
