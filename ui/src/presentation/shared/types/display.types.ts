import type { TagTone } from '../components/Tag'

/** Un dato listo para mostrar: su texto, sus insignias y, si falta, por qué. */
export interface DisplayValue {
  readonly text: string | null
  readonly tags: readonly DisplayTag[]
  // Origen del dato (consulta WMI, clave del Registro…), mostrado al pasar el puntero.
  readonly source: string | null
  // Motivo legible cuando no hay texto.
  readonly reason: string | null
  // Rutas y comandos se muestran en monoespaciada.
  readonly mono?: boolean
}

export interface DisplayTag {
  readonly label: string
  readonly hint?: string
  readonly tone?: TagTone
}

export interface SpecRow {
  readonly label: string
  readonly value: DisplayValue
}
