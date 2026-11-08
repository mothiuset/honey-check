import type {
  ParamChoice,
  ParamValue,
  Plan,
  Procedure,
  ProcedureRun,
  Run,
  ToolDefinition,
} from '@/domain/support/Support'

/** Por qué el servicio rechazó preparar o iniciar una herramienta, para explicarlo al técnico. */
export type SupportRefusal =
  | 'confirmation_required'
  | 'elevation_required'
  | 'change_in_progress'
  | 'plan_expired'
  | 'invalid_params'
  | 'refused'
  | 'not_found'
  | 'failed'

export type SupportOutcome<T> =
  | { readonly ok: true; readonly value: T }
  | {
      readonly ok: false
      readonly reason: SupportRefusal
      readonly detail: string | null
    }

export interface SupportUseCases {
  catalog(): Promise<readonly ToolDefinition[]>
  /** Opciones en vivo de un parámetro (discos y particiones, por ejemplo). */
  source(name: string): Promise<readonly ParamChoice[]>
  plan(
    tool: string,
    params: Readonly<Record<string, ParamValue>>,
  ): Promise<SupportOutcome<Plan>>
  start(plan: Plan, confirmed: boolean): Promise<SupportOutcome<Run>>
  run(runId: string): Promise<Run>
  cancel(runId: string): Promise<void>
  history(): Promise<readonly Run[]>
  versions(tool: string): Promise<readonly Run[]>
  changed(runId: string): Promise<boolean | null>
  pickPath(
    kind: 'folder' | 'file',
    title: string,
    filter: string | null,
  ): Promise<string | null>
  procedures(): Promise<readonly Procedure[]>
  procedureVersions(slug: string): Promise<readonly Procedure[]>
  saveProcedure(document: unknown): Promise<SupportOutcome<Procedure>>
  removeProcedure(slug: string): Promise<number>
  procedureRuns(): Promise<readonly ProcedureRun[]>
}
