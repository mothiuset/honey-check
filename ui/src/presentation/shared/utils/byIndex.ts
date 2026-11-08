/** Clave de fila por posición, para listas inmutables sin identificador propio (tablas pequeñas). */
export function byIndex<R>(rows: readonly R[]): (row: R) => string {
  return (row) => String(rows.indexOf(row))
}
