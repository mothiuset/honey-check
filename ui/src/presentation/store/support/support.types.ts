import type {
  ParamChoice,
  Plan,
  Procedure,
  ProcedureRun,
  Run,
  SupportRefusal,
  ToolDefinition,
} from '@/application'

export interface SupportNotice {
  readonly reason: SupportRefusal
  readonly detail: string | null
}

export interface SupportSliceState {
  readonly catalog: readonly ToolDefinition[] | null
  readonly catalogFailed: boolean
  // Plan visible: lo que se hará si el técnico lo inicia.
  readonly plan: Plan | null
  readonly preparing: boolean
  readonly notice: SupportNotice | null
  // Ejecución que se está mirando (en curso o abierta desde el historial).
  readonly run: Run | null
  readonly history: readonly Run[] | null
  readonly procedures: readonly Procedure[] | null
  readonly procedureRuns: readonly ProcedureRun[] | null
  readonly versions: Readonly<Record<string, readonly Procedure[]>>
  readonly procedureMessage: string | null
  /** Opciones en vivo por fuente; `failed` si no se pudieron leer. */
  readonly sources: Readonly<Record<string, readonly ParamChoice[] | 'failed'>>
  /** Versiones guardadas de cada herramienta, la más reciente primero. */
  readonly toolVersions: Readonly<Record<string, readonly Run[]>>
  /** La versión anterior completa, para mostrar qué cambió. */
  readonly previous: Run | null
  /** Un cambio terminó después del resultado a la vista: puede no reflejar el equipo. */
  readonly stale: boolean
}
