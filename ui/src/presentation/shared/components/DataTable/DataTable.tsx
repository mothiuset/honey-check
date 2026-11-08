import { Fragment } from 'react'
import { Lede, VisuallyHidden } from '../Text'
import type { Column, DataTableProps } from './DataTable.types'
import styles from './DataTable.module.css'
import { useDataTable } from './useDataTable'

function cellContent<R>(column: Column<R>, row: R) {
  return column.render ? column.render(row) : (column.value?.(row) ?? '')
}

/**
 * Tabla de datos: encabezado fijo, orden por columna, columnas por prioridad según el ancho, filas
 * desplegables y, en móvil, una línea por fila sin repetir encabezados.
 */
export function DataTable<R>(props: DataTableProps<R>) {
  const {
    columns,
    rows,
    rowKey,
    emptyText = 'Sin datos.',
    loading = false,
    caption,
    id,
    renderExpanded,
    rowState,
    hideHeader = false,
    rowHeaders = false,
  } = props
  const table = useDataTable(props)

  if (!rows.length) return <Lede live>{loading ? 'Cargando.' : emptyText}</Lede>

  return (
    <div className={styles.scroller} aria-busy={loading} id={id}>
      <table className={styles.table}>
        {caption ? (
          <caption>
            <VisuallyHidden>{caption}</VisuallyHidden>
          </caption>
        ) : null}
        <thead data-hidden={hideHeader || undefined}>
          <tr>
            {columns.map((column) => (
              <th
                key={column.key}
                scope="col"
                data-priority={column.priority ?? 1}
                data-align={column.align ?? 'start'}
                aria-sort={table.ariaSort(column)}
              >
                {column.sortable ? (
                  <button
                    type="button"
                    className={styles.sort}
                    onClick={() => {
                      table.toggleSort(column)
                    }}
                  >
                    {column.label}
                    <span className={styles.sortMark} aria-hidden="true">
                      {table.sort.key === column.key
                        ? table.sort.order === 'asc'
                          ? '▲'
                          : '▼'
                        : '↕'}
                    </span>
                  </button>
                ) : (
                  column.label
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.sorted.map((row) => {
            const open = table.isOpen(row)
            return (
              <Fragment key={rowKey(row)}>
                <tr data-open={open} data-state={rowState?.(row)}>
                  {columns.map((column, index) => {
                    const Cell = rowHeaders && index === 0 ? 'th' : 'td'
                    return (
                      <Cell
                        key={column.key}
                        scope={Cell === 'th' ? 'row' : undefined}
                        data-priority={column.priority ?? 1}
                        data-align={column.align ?? 'start'}
                        data-lead={index === 0}
                      >
                        {index === 0 && renderExpanded ? (
                          <button
                            type="button"
                            className={styles.expand}
                            aria-expanded={open}
                            onClick={() => {
                              table.toggleRow(row)
                            }}
                          >
                            <span
                              className={styles.chevron}
                              aria-hidden="true"
                            />
                            {cellContent(column, row)}
                          </button>
                        ) : (
                          cellContent(column, row)
                        )}
                      </Cell>
                    )
                  })}
                </tr>
                {renderExpanded && open ? (
                  <tr data-detail="true">
                    <td colSpan={columns.length}>{renderExpanded(row)}</td>
                  </tr>
                ) : null}
              </Fragment>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
