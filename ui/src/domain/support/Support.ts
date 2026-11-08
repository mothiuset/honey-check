// Contrato de las herramientas de soporte (espejo de domain/support.py) y reglas sin framework.

export type Risk = 'read' | 'change' | 'destructive'
export type ParamKind =
  'text' | 'path' | 'number' | 'bool' | 'choice' | 'multi' | 'secret'
export type ParamValue = string | number | boolean | readonly string[] | null

export interface ParamChoice {
  readonly value: string
  readonly label: string
  /** Opciones en vivo (particiones de un disco): grupo, detalle, uso y por qué no se elige. */
  readonly group?: string | null
  readonly detail?: string | null
  readonly used?: number | null
  readonly disabledReason?: string | null
}

export interface ToolParam {
  readonly name: string
  readonly label: string
  readonly kind: ParamKind
  readonly required: boolean
  readonly default: ParamValue
  readonly help: string | null
  readonly choices: readonly ParamChoice[]
  readonly maxLength: number
  /** Las opciones se leen del equipo al abrir la herramienta. */
  readonly source?: string | null
}

export interface ToolDefinition {
  readonly id: string
  readonly category: string
  readonly title: string
  readonly description: string
  readonly risk: Risk
  readonly requiresAdmin: boolean
  readonly params: readonly ToolParam[]
  readonly hidden: boolean
  readonly contactsNetwork: boolean
  /** Texto del botón cuando el título describe un problema. */
  readonly actionLabel: string | null
  /** Se ejecuta con el clic donde esté el técnico, sin pantalla ni revisión. */
  readonly instant: boolean
}

export interface PlanStep {
  readonly title: string
  readonly command: string | null
  readonly detail: string | null
}

export interface Plan {
  readonly id: string
  readonly tool: string
  readonly title: string
  readonly risk: Risk
  readonly requiresAdmin: boolean
  readonly params: Readonly<Record<string, ParamValue>>
  readonly steps: readonly PlanStep[]
  readonly actionLabel: string | null
  /** Una frase con lo que va a pasar. */
  readonly summary: string | null
  /** Revisión previa: qué existe, qué está en uso, qué necesita administrador. */
  readonly checks: readonly Check[]
  readonly warnings: readonly string[]
  readonly backup: string | null
  readonly createdAt: string
}

export type Tone = 'neutral' | 'ok' | 'warn' | 'bad'
export type CheckStatus = 'ok' | 'warn' | 'fail' | 'info' | 'skipped'
export type ColumnKind = 'text' | 'number' | 'bytes' | 'date' | 'bool' | 'path'
export type CellValue = string | number | boolean | null

export interface Fact {
  readonly label: string
  readonly value: string | null
  readonly tone: Tone
}

export interface ActionLink {
  readonly tool: string
  readonly label: string
  readonly params: Readonly<Record<string, string>>
  readonly tone: Tone
}

export interface Check {
  readonly label: string
  readonly status: CheckStatus
  readonly detail: string | null
  readonly fix: ActionLink | null
  /** Código y texto de Windows: solo en «Detalles técnicos». */
  readonly technical: string | null
}

export interface ResultColumn {
  readonly key: string
  readonly label: string
  readonly kind: ColumnKind
  readonly priority: 1 | 2 | 3
}

export type ResultRow = Readonly<Record<string, CellValue>>

export interface ResultTable {
  readonly id: string
  readonly title: string
  readonly columns: readonly ResultColumn[]
  readonly rows: readonly ResultRow[]
  readonly rowKey: string
  readonly rowActions: readonly ActionLink[]
  readonly bulkAction: ActionLink | null
  readonly selectionParam: string | null
  readonly truncated: boolean
}

export interface ChartNode {
  readonly name: string
  readonly value: number
  readonly path?: string
  readonly children?: readonly ChartNode[]
  /** Tiene subcarpetas que el análisis no desglosó: se puede analizar aparte. */
  readonly more?: boolean
  /** Línea secundaria (versión de un programa, origen del tamaño). */
  readonly detail?: string | null
  /** Lo que se puede hacer con este elemento; `{campo}` se llena con sus datos. */
  readonly actions?: readonly ActionLink[]
  /** Resto agrupado («Archivos y otras carpetas»): no es un elemento propio. */
  readonly group?: boolean
  readonly id?: string
}

export interface ResultChart {
  readonly id: string
  readonly title: string
  readonly kind: 'treemap' | 'bar'
  readonly data: readonly ChartNode[]
  readonly unit: string
}

export interface FileRef {
  readonly label: string
  readonly path: string
}

export interface ToolResult {
  readonly summary: readonly Fact[]
  readonly checks: readonly Check[]
  readonly tables: readonly ResultTable[]
  readonly charts: readonly ResultChart[]
  readonly files: readonly FileRef[]
  readonly text: string | null
  readonly verified: boolean | null
}

export type RunStatus =
  'running' | 'succeeded' | 'partial' | 'failed' | 'cancelled'
export type LogLevel = 'info' | 'command' | 'output' | 'warn' | 'error'

export interface LogEntry {
  readonly at: string
  readonly level: LogLevel
  readonly text: string
}

export interface Run {
  readonly id: string
  readonly planId: string
  readonly tool: string
  readonly title: string
  readonly risk: Risk
  readonly params: Readonly<Record<string, ParamValue>>
  readonly status: RunStatus
  readonly startedAt: string
  readonly finishedAt: string | null
  readonly progress: {
    readonly done: number
    readonly total: number
    readonly label: string | null
  }
  readonly log: readonly LogEntry[]
  readonly result: ToolResult | null
  readonly error: string | null
  readonly elevated: boolean | null
  /** Huella del estado que leyó una consulta: si cambia, el resultado quedó atrás. */
  readonly fingerprint?: string | null
}

// --- Procesos de instalación ----------------------------------------------------------------

export type StepKind =
  | 'install'
  | 'verify_program'
  | 'verify_certificate'
  | 'verify_service'
  | 'verify_file'
  | 'tool'
  | 'command'
  | 'manual'
  | 'reboot'

export interface ProcedureStep {
  readonly id: string
  readonly kind: StepKind
  readonly title: string
  readonly params: Readonly<Record<string, unknown>>
  readonly optional: boolean
  readonly help: string | null
}

export interface Procedure {
  readonly slug: string
  readonly name: string
  readonly description: string
  readonly version: number
  readonly steps: readonly ProcedureStep[]
  readonly savedAt: string | null
  readonly template: boolean
}

export type StepState = 'pending' | 'ok' | 'failed' | 'skipped' | 'waiting'

export interface ProcedureRun {
  readonly id: string
  readonly slug: string
  readonly version: number
  readonly name: string
  readonly device: string | null
  readonly startedAt: string
  readonly updatedAt: string
  readonly steps: readonly {
    readonly step: string
    readonly state: StepState
    readonly detail: string | null
  }[]
  readonly finished: boolean
}

// --- Reglas ---------------------------------------------------------------------------------

export function isRunFinished(run: Run): boolean {
  return run.status !== 'running'
}

/** Una acción ofrecida por una fila: `{campo}` se reemplaza por el valor de esa fila. */
export function linkParams(
  link: ActionLink,
  row: ResultRow | null,
): Record<string, string> {
  const filled: Record<string, string> = {}
  for (const [name, template] of Object.entries(link.params)) {
    filled[name] = template.replace(/\{(\w+)\}/g, (_, field: string) => {
      const value = row?.[field]
      return value === null || value === undefined ? '' : String(value)
    })
  }
  return filled
}

/** Valores iniciales del formulario: los que llegan por la ruta y, si no, los por defecto. */
export function initialValues(
  tool: ToolDefinition,
  given: Readonly<Record<string, string>>,
): Record<string, ParamValue> {
  const values: Record<string, ParamValue> = {}
  for (const param of tool.params) {
    const raw = given[param.name]
    if (raw === undefined) values[param.name] = param.default
    else if (param.kind === 'number') values[param.name] = Number(raw)
    else if (param.kind === 'bool') values[param.name] = raw === 'true'
    else if (param.kind === 'multi')
      values[param.name] = raw ? raw.split('\n') : []
    else values[param.name] = raw
  }
  return values
}

/** Lo que se envía: sin vacíos, para que el servidor aplique sus valores por defecto. */
export function requestParams(
  values: Readonly<Record<string, ParamValue>>,
): Record<string, ParamValue> {
  return Object.fromEntries(
    Object.entries(values).filter(
      ([, value]) =>
        value !== null &&
        value !== '' &&
        !(Array.isArray(value) && value.length === 0) &&
        !(typeof value === 'number' && Number.isNaN(value)),
    ),
  )
}

export function missingRequired(
  tool: ToolDefinition,
  values: Readonly<Record<string, ParamValue>>,
): readonly string[] {
  return tool.params
    .filter((param) => param.required)
    .filter((param) => {
      const value = values[param.name]
      return value === null || value === undefined || value === ''
    })
    .map((param) => param.label)
}

// --- Versiones: qué cambió entre dos resultados de la misma herramienta ---------------------------

export interface FactChange {
  readonly label: string
  readonly before: string | null
  readonly after: string | null
}

export interface SpaceChange {
  readonly name: string
  readonly path: string
  readonly before: number
  readonly after: number
  readonly delta: number
}

export interface ResultChanges {
  readonly facts: readonly FactChange[]
  readonly space: readonly SpaceChange[]
}

function spaceByPath(
  result: ToolResult,
  depth: number,
): Map<string, ChartNode> {
  const nodes = new Map<string, ChartNode>()
  const visit = (node: ChartNode, level: number) => {
    if (node.path && !node.group) nodes.set(node.path, node)
    if (level < depth)
      for (const child of node.children ?? []) visit(child, level + 1)
  }
  for (const chart of result.charts)
    if (chart.kind === 'treemap') for (const root of chart.data) visit(root, 0)
  return nodes
}

/**
 * Lo que cambió de una versión a otra: las cifras del resumen y las carpetas que más crecieron o
 * bajaron (al menos 10 MiB y 1 % del total, para no llenar la lista de ruido).
 */
export function compareResults(
  before: ToolResult,
  after: ToolResult,
  limit = 8,
): ResultChanges {
  const previous = new Map(
    before.summary.map((fact) => [fact.label, fact.value]),
  )
  const facts = after.summary
    .filter(
      (fact) =>
        previous.has(fact.label) && previous.get(fact.label) !== fact.value,
    )
    .map((fact) => ({
      label: fact.label,
      before: previous.get(fact.label) ?? null,
      after: fact.value,
    }))
  const old = spaceByPath(before, 3)
  const now = spaceByPath(after, 3)
  const total = Math.max(1, ...[...now.values()].map((node) => node.value))
  const threshold = Math.max(10 * 1024 ** 2, total * 0.01)
  const paths = new Set([...old.keys(), ...now.keys()])
  const space = [...paths]
    .map((path) => {
      const a = old.get(path)?.value ?? 0
      const b = now.get(path)?.value ?? 0
      const name = now.get(path)?.name ?? old.get(path)?.name ?? path
      return { name, path, before: a, after: b, delta: b - a }
    })
    .filter((change) => Math.abs(change.delta) >= threshold)
  // Una carpeta cuyo cambio ya lo explica una subcarpeta sobra: se muestra la más profunda.
  const explained = (change: SpaceChange) =>
    space.some(
      (other) =>
        other.path.length > change.path.length &&
        other.path.startsWith(change.path) &&
        Math.abs(other.delta - change.delta) < threshold,
    )
  const kept = space
    .filter((change) => !explained(change))
    .sort((x, y) => Math.abs(y.delta) - Math.abs(x.delta))
    .slice(0, limit)
  return { facts, space: kept }
}
