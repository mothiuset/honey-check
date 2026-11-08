import type { ReactNode } from 'react'

export type ColumnPriority = 1 | 2 | 3
export type SortValue = string | number | null | undefined

export interface Column<R> {
  readonly key: string
  readonly label: string
  // 1 siempre visible; 2 se oculta en pantallas medianas; 3 solo en pantallas anchas.
  readonly priority?: ColumnPriority
  readonly align?: 'start' | 'end'
  readonly sortable?: boolean
  // Valor para ordenar y texto por defecto de la celda.
  readonly value?: (row: R) => SortValue
  readonly render?: (row: R) => ReactNode
}

export interface ServerSort {
  readonly key: string
  readonly order: 'asc' | 'desc'
  readonly onSort: (key: string) => void
}

export interface DataTableProps<R> {
  readonly columns: readonly Column<R>[]
  readonly rows: readonly R[]
  readonly rowKey: (row: R) => string
  readonly emptyText?: string
  readonly loading?: boolean
  readonly caption?: string
  readonly id?: string
  // Orden controlado por el servidor; sin él, la tabla ordena en el navegador.
  readonly serverSort?: ServerSort
  // Contenido desplegable bajo cada fila; la primera celda se vuelve el botón que lo abre.
  readonly renderExpanded?: (row: R) => ReactNode
  readonly onExpand?: (row: R) => void
  // Estado de la fila (`changed`, `added`, `removed`): la colorea, como en una comparación.
  readonly rowState?: (row: R) => string | undefined
  // Sin encabezado: tablas de dos o tres columnas que se entienden solas.
  readonly hideHeader?: boolean
  // La primera celda es el título de la fila (`<th scope="row">`).
  readonly rowHeaders?: boolean
}

export interface SortState {
  readonly key: string | null
  readonly order: 'asc' | 'desc'
}
