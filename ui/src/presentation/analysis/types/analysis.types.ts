// Tipos de presentación propios del análisis del equipo.

export interface Metric {
  readonly label: string
  readonly value: string | null
  readonly detail?: string | null
  readonly href?: string
  readonly tone?: 'ok' | 'warn' | 'bad'
}

export interface CombCell {
  readonly name: string
  readonly label: string
  readonly href: string
  readonly status: string
  readonly statusText: string
  readonly cx: number
  readonly cy: number
  readonly points: string
}

export interface VolumeUsage {
  readonly drive: string
  readonly name: string
  readonly free: string
  readonly size: string
  readonly percent: number
  readonly tone: 'ok' | 'warn' | 'bad'
  /** Letra de la unidad, para sus acciones (abrir, analizar). */
  readonly letter?: string | null
}

export type SoftwareScopeFilter = '' | 'machine' | 'current_user'
