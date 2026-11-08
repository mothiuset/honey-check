import {
  linkParams,
  type ResultRow,
  type ResultTable as Table,
} from '@/application'
import {
  DataTable,
  Field,
  Copyable,
  Toolbar,
  type Column,
} from '@/presentation/shared/components'
import { ActionButton } from '../ActionButton/ActionButton'
import { cellText } from '../../formatters/supportText'
import { useResultTable } from '../../hooks/useResultTable'
import styles from './ResultTable.module.css'

const buttonTone = (tone: string) =>
  tone === 'bad' ? 'danger' : tone === 'ok' ? 'primary' : 'default'

/** Tabla de un resultado: celdas según su tipo, acciones por fila y selección para varias. */
export function ResultTable({ table }: { table: Table }) {
  const view = useResultTable(table)

  const columns: Column<ResultRow>[] = table.columns.map((column) => ({
    key: column.key,
    label: column.label,
    priority: column.priority,
    sortable: true,
    align:
      column.kind === 'bytes' || column.kind === 'number' ? 'end' : 'start',
    value: (row) => {
      const value = row[column.key]
      return typeof value === 'boolean' ? Number(value) : value
    },
    render: (row) =>
      column.kind === 'path' ? (
        <Copyable
          text={cellText(row[column.key], column.kind)}
          truncate="start"
          mono
        />
      ) : column.kind === 'bool' ? (
        cellText(row[column.key], column.kind)
      ) : (
        <Copyable text={cellText(row[column.key], column.kind)} />
      ),
  }))

  if (view.selectable)
    columns.unshift({
      key: '__select',
      label: 'Elegir',
      render: (row) => (
        <input
          type="checkbox"
          aria-label={`Elegir ${view.keyOf(row)}`}
          checked={view.isSelected(row)}
          onChange={() => {
            view.toggle(row)
          }}
        />
      ),
    })

  if (table.rowActions.length)
    columns.push({
      key: '__actions',
      label: 'Acciones',
      render: (row) => (
        <span className={styles.actions}>
          {table.rowActions.map((action) => (
            <ActionButton
              key={`${action.tool}-${action.label}`}
              size="small"
              tone={buttonTone(action.tone)}
              tool={action.tool}
              params={linkParams(action, row)}
            >
              {action.label}
            </ActionButton>
          ))}
        </span>
      ),
    })

  const bulk = table.bulkAction
  return (
    <section className={styles.table} data-table={table.id}>
      <h3>
        {table.title}{' '}
        <span className={styles.count}>({table.rows.length})</span>
      </h3>
      {view.searchable || (view.selectable && bulk) ? (
        <Toolbar align="center">
          {view.searchable ? (
            <Field label="Buscar en la tabla" grow>
              <input
                type="search"
                value={view.query}
                onChange={(event) => {
                  view.setQuery(event.target.value)
                }}
              />
            </Field>
          ) : null}
          {view.selectable && bulk && table.selectionParam ? (
            <>
              <label className={styles.all}>
                <input
                  type="checkbox"
                  checked={
                    view.rows.length > 0 &&
                    view.selected.length >= view.rows.length
                  }
                  onChange={(event) => {
                    view.selectVisible(event.target.checked)
                  }}
                />
                Elegir todo lo visible
              </label>
              {view.selected.length ? (
                <ActionButton
                  tone={buttonTone(bulk.tone)}
                  tool={bulk.tool}
                  params={{
                    ...linkParams(bulk, null),
                    [table.selectionParam]: view.selected.join('\n'),
                  }}
                >
                  {bulk.label} ({view.selected.length})
                </ActionButton>
              ) : null}
            </>
          ) : null}
        </Toolbar>
      ) : null}
      <DataTable
        columns={columns}
        rows={view.rows}
        rowKey={view.keyOf}
        caption={table.title}
        emptyText={view.query ? 'Nada coincide con la búsqueda.' : 'Sin filas.'}
      />
      {table.truncated ? (
        <p className={styles.note}>
          Se muestran las primeras filas; afine la búsqueda para ver el resto.
        </p>
      ) : null}
    </section>
  )
}
